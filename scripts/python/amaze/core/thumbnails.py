"""The ONE thumbnail system - every section's thumbnails flow through
this engine: one system for all sections, by design.

Design:

- **Keys, not rows.** Every thumbnail is identified by a hashable key
  (e.g. ``("library.json", mat_id)``) and deliveries are BY KEY, so
  row reordering or a library reload can never mis-deliver an image -
  the whole generation-guard bug class from the old per-model workers
  dies at the root here.

- **One RAM budget.** A byte-capped LRU shared by every section (the
  "RAM Cache (MB)" preference). Eviction is safe because every
  thumbnail already exists on disk - an evicted row simply re-reads
  its file the next time it scrolls into view. Disk is the swap, and
  it is already written. Small sets (Cop) never reach the budget, so
  no section needs an exemption.

- **States.** absent = never requested, "pending" = in flight,
  "done" = delivered at least once (the image lives in the LRU; an
  evicted key re-queues on its next repaint), "missing" = the load
  genuinely failed - the model shows its placeholder; sticky until
  discard() (a rerender/overwrite discards, so failures get retried
  exactly when their file could actually have changed).

- **Providers.** How bytes become a QImage is the only per-source
  code. Shipped: FILE (materials/cop library PNGs, and texture rows
  already in the disk cache) and CONVERT (textures - one call to the
  **Conversion Engine**, `core/conversion.py`, which owns the decoder
  order, the size contract, the verification of what a converter
  returned and the temp files), RENDER (geometry: the model's
  main-thread Houdini pass deposits finished frames via deposit())
  and PAINT (colors: synchronous paint-on-miss, also via deposit()).

  This engine used to BE the conversion code as well: four converter
  functions, the order between them written inside the worker thread
  below, three hand-rolled temp-file lifetimes, and nobody checking
  what any of them returned. It keeps the cache, the budget and the
  loaders; conversion is its own engine now.
"""

import atexit
import functools
from collections import OrderedDict

from PySide6 import QtCore, QtGui

from amaze.core import conversion, debug


#: Threads that refused to stop. Parked forever ON PURPOSE: dropping
#: the last Python reference to a running QThread frees its C++ object
#: mid-run and takes the process down. They finish or the process ends.
#
# Carried ACROSS reloads, like `engine` below. panel.py reloads this
# module on every panel open and reload re-runs this body, so a plain
# `= []` handed the collector every thread parked by an EARLIER reopen.
#
# The crash is deferred, which is why this looked harmless: nothing dies
# at reload time. What keeps a running PySide QThread alive is the bound
# `self.run` method held by C++ QThreadWrapper::run() - and the dying
# thread releases that reference ITSELF when run() returns. So the
# parked-list reference is exactly the one that has to exist at thread
# COMPLETION. Measured, with a real _FileLoader parked by a real
# shutdown() and the list then replaced by a reload:
#
#   QThread: Destroyed while thread is still running
#   QMessageLogger::fatal -> abort  <- inside QThreadWrapper::run()
#
# Do NOT "tidy" this by pruning entries whose isRunning() is False:
# measured, isRunning() flips BEFORE the wrapper releases the bound
# method, so an isRunning()-based prune re-opens the identical window.
_unstoppable: list = globals().get("_unstoppable", [])


def _thread_finished(thread) -> bool:
    """isFinished(), treating a deleted C++ side as finished."""
    try:
        return thread.isFinished()
    except RuntimeError:
        return True


class _FileLoader(QtCore.QThread):
    """Loads image files for a batch of keys off the main thread.
    Failures deliberately emit nothing - a key still pending when the
    batch finishes is how the engine knows the file is missing."""

    loaded = QtCore.Signal(object, QtGui.QImage)

    def __init__(self, items) -> None:
        super().__init__()
        self._items = items  # [(key, path)]
        self._canceled = False

    def keys(self):
        return [key for key, _path in self._items]

    def cancel(self) -> None:
        """Stop after the current file. Shutdown needs this: waiting
        for a full batch of disk reads would stall a panel reopen."""
        self._canceled = True

    def run(self) -> None:
        for key, path in self._items:
            if self._canceled:
                return
            image = QtGui.QImage(path)
            if not image.isNull():
                self.loaded.emit(key, image)


class _ConvertLoader(QtCore.QThread):
    """The CONVERT provider's worker: generates texture thumbnails off
    the UI thread. Each item may shell out to iconvert (native Houdini
    startup overhead, up to a 30s timeout), which is why this work is
    the one kind worth cancelling when the user browses away (see
    ThumbnailEngine.cancel_pending_converts). Only generates images -
    it never touches the disk cache, whose manifest is main-thread-only
    by design (the model writes the cache when a delivery lands)."""

    loaded = QtCore.Signal(object, QtGui.QImage)
    #: fired after EVERY item, success or failure - the progress bar
    #: must advance on a file that fails/times out too, or it stalls
    #: short of 100%.
    attempted = QtCore.Signal(object)

    def __init__(self, items, hfs) -> None:
        super().__init__()
        self._items = items  # [(key, full_path, size)]
        self._hfs = hfs
        self._stop = False
        self._canceled = False

    def keys(self):
        return [item[0] for item in self._items]

    def cancel(self) -> None:
        self._stop = True
        self._canceled = True

    def _cancelled(self) -> bool:
        """Polled from inside the Conversion Engine's nested event loop,
        which is where this worker spends nearly all of its life.

        This is the callback `conversion._run_process` has always taken
        and NOBODY EVER PASSED - its whole 100ms watchdog was dead
        code, so cancel() could only take effect BETWEEN items. A worker
        already inside a 30s iconvert ignored it completely, which is
        what made shutdown() fall through to wait(3000) and then
        terminate(): measured 3.0s per stuck worker, sequentially, so a
        panel reopen with Parallel Conversions at 8 could stall ~24s -
        and terminate() then skipped the cleanup below, orphaning the
        iconvert child (measured: still alive after shutdown) and
        leaking its temp PNG.

        Wired up, cancel() gets the worker out within the watchdog's
        100ms, it kills its own child and removes its own temp file, and
        wait(3000) succeeds - so terminate() is not reached at all.
        Interruption counts too: shutdown() requests it on every thread,
        including ones with no cancel() of their own."""
        return self._stop or self.isInterruptionRequested()

    def run(self) -> None:
        """One call to the Conversion Engine per item, and nothing else.

        The decoder ORDER used to live here: a native-extension test, a
        force-iconvert branch, and a sips-then-iconvert fallback with
        its own cancel check - a policy decision inside a worker thread,
        where nothing could see it and nothing checked its result. The
        engine owns all of that now, and this worker owns what a worker
        should: staying off the UI thread, and stopping when told."""
        for key, full_path, size in self._items:
            if self._stop:
                return
            try:
                result = conversion.convert_image(
                    full_path, size, cancelled=self._cancelled,
                    hfs=self._hfs)
                image = result.image
            except Exception as exc:                          # noqa: BLE001
                # A backstop only: convert_image answers with a reason
                # rather than raising. A raise here would otherwise take
                # the rest of the batch with it.
                debug.event(
                    "texture", "thumbnail failed", file=full_path, error=str(exc)
                )
                image = None
            if self._stop:
                return
            if image is not None:
                self.loaded.emit(key, image)
            self.attempted.emit(key)



class ThumbnailEngine(QtCore.QObject):
    #: a key's image arrived (repaint it) - or its load failed (the
    #: model's data() will now see is_missing() and paint a placeholder)
    ready = QtCore.Signal(object)
    #: a convert item was attempted, success or failure - drives the
    #: texture progress bar
    convert_attempted = QtCore.Signal(object)

    def __init__(self, budget_mb: int = 256) -> None:
        super().__init__()
        self._lru = OrderedDict()  # key -> (QImage, nbytes)
        self._bytes = 0
        self._budget = int(budget_mb) * 1024 * 1024
        self._states = {}  # key -> "pending" | "done" | "missing"
        self._file_queue = []  # [(key, path)] awaiting dispatch
        self._dispatch_scheduled = False
        self._convert_queue = []  # [(key, path, ext, size)]
        self._convert_scheduled = False
        # Convert options, pushed by the texture model per batch (so
        # Preferences changes apply without a restart, same as always).
        self._convert_hfs = ""
        self._convert_parallel = 4
        # Threads stay referenced until finished - dropping a QThread's
        # only Python reference while it runs risks a garbage-collected
        # C++ thread object (the texture worker's #21 lesson).
        self._threads = []

    # -- budget ---------------------------------------------------------

    def set_budget_mb(self, budget_mb) -> None:
        try:
            budget_mb = int(budget_mb)
        except (TypeError, ValueError):
            return
        self._budget = max(64, budget_mb) * 1024 * 1024
        self._evict()

    def _evict(self) -> None:
        # Always keep the newest entry, so one oversized image can't
        # evict itself into a reload loop.
        while self._bytes > self._budget and len(self._lru) > 1:
            _key, (_image, nbytes) = self._lru.popitem(last=False)
            self._bytes -= nbytes

    def _cache_get(self, key):
        item = self._lru.get(key)
        if item is None:
            return None
        self._lru.move_to_end(key)
        return item[0]

    def _cache_put(self, key, image) -> None:
        try:
            nbytes = max(int(image.sizeInBytes()), 1)
        except AttributeError:
            nbytes = 1
        old = self._lru.pop(key, None)
        if old is not None:
            self._bytes -= old[1]
        self._lru[key] = (image, nbytes)
        self._bytes += nbytes
        self._evict()

    # -- the request surface models talk to ------------------------------

    def request_file(self, key, path):
        """The FILE provider: return the cached image, or queue a
        background load of `path` and return None (the caller paints
        its loading/placeholder state). Everything queued during one
        paint pass coalesces into a single loader batch via the
        zero-timer. Called from data(), so it must stay cheap."""
        image = self._cache_get(key)
        if image is not None:
            return image
        state = self._states.get(key)
        if state == "pending" or state == "missing":
            return None
        # Never requested - or delivered once and since evicted: load.
        self._states[key] = "pending"
        self._file_queue.append((key, path))
        if not self._dispatch_scheduled:
            self._dispatch_scheduled = True
            QtCore.QTimer.singleShot(0, self._dispatch_files)
        return None

    def peek(self, key):
        """Cache lookup only - no request on miss. Convert-sourced rows
        use this, since their generation is queued eagerly per folder
        rather than driven by paints."""
        return self._cache_get(key)

    def is_pending(self, key) -> bool:
        return self._states.get(key) == "pending"

    def is_missing(self, key) -> bool:
        return self._states.get(key) == "missing"

    def deposit(self, key, image) -> None:
        """Main-thread providers hand finished images straight in:
        geometry's Houdini render pass (renders can't leave the main
        thread) and colors' synchronous paints. Cached under the
        budget, marked done, announced like any other delivery."""
        self._cache_put(key, image)
        self._states[key] = "done"
        # DEFERRED. matx_library, gradient_library and code_library all
        # deposit from inside data(), so a synchronous emit reached
        # their _on_*_ready -> dataChanged.emit() FROM INSIDE a view's
        # own data fetch. Emitting dataChanged during a data() call is
        # re-entrant by construction, and it is the shape the
        # 8,973-record stale-callback flood came from.
        QtCore.QTimer.singleShot(0, lambda k=key: self.ready.emit(k))

    def discard(self, key) -> None:
        """Forget a key entirely (image AND state) - a rerender or
        overwrite calls this so the next repaint reloads the fresh
        file, and a previously-missing key gets its retry."""
        old = self._lru.pop(key, None)
        if old is not None:
            self._bytes -= old[1]
        self._states.pop(key, None)

    def clear(self) -> None:
        self._lru.clear()
        self._bytes = 0
        self._states = {
            k: s for k, s in self._states.items() if s == "pending"
        }

    # -- the CONVERT provider (textures) ----------------------------------

    def configure_convert(self, hfs, parallel) -> None:
        self._convert_hfs = hfs
        self._convert_parallel = max(1, min(8, int(parallel)))

    def request_convert(self, key, full_path, size) -> None:
        """Queue an image for background generation through the
        Conversion Engine. Queued eagerly per folder by the model -
        conversions are the expensive one-time work, so the whole folder
        generates on open (with the progress bar) instead of waiting for
        each tile to scroll into view.

        No extension is passed, and that is the point: which decoder a
        file needs is measured from the file, in one place, never
        guessed from its name here."""
        if self._states.get(key) == "pending":
            return
        self._states[key] = "pending"
        self._convert_queue.append((key, full_path, size))
        if not self._convert_scheduled:
            self._convert_scheduled = True
            QtCore.QTimer.singleShot(0, self._dispatch_converts)

    def cancel_pending_converts(self) -> None:
        """A folder switch abandons its unfinished conversions - the
        one kind of work expensive enough to be worth stopping (a
        revisit simply re-queues). Undelivered keys reset to
        unrequested, never to missing; a canceled loader's late
        delivery is dropped by the state check in _on_loaded."""
        for item in self._convert_queue:
            if self._states.get(item[0]) == "pending":
                self._states.pop(item[0], None)
        self._convert_queue = []
        for thread in self._threads:
            if isinstance(thread, _ConvertLoader) and not thread.isFinished():
                thread.cancel()
                for key in thread.keys():
                    if self._states.get(key) == "pending":
                        self._states.pop(key, None)

    def _dispatch_converts(self) -> None:
        """Split the queued batch round-robin across N concurrent
        loaders (Preferences > Parallel Conversions): each iconvert
        call pays a fixed Houdini-process startup cost regardless of
        file size, so N at once cuts wall-clock roughly by N."""
        self._convert_scheduled = False
        items = self._convert_queue
        self._convert_queue = []
        if not items:
            return
        parallel = self._convert_parallel
        # A LIVE cap, not a per-dispatch one. This counted nothing and
        # started up to `parallel` new loaders every time it ran, so a
        # rerender during a running batch doubled the subprocesses:
        # measured, 4 loaders after the first dispatch and 8 after the
        # second with none finished, against a preference of 4. Each
        # one shells out to iconvert - a full Houdini process startup -
        # and every extra thread also widens the sibling-prune exposure
        # the FILE_LOADER_LIMIT comment names. Same shape as
        # _dispatch_files, which is where the comment claiming converts
        # were already capped lives.
        live = sum(
            1 for t in self._threads
            if isinstance(t, _ConvertLoader) and not _thread_finished(t)
        )
        free = parallel - live
        if free <= 0:
            # Back on the queue, retried when a slot frees.
            self._convert_queue = items + self._convert_queue
            if not self._convert_scheduled:
                self._convert_scheduled = True
                QtCore.QTimer.singleShot(0, self._dispatch_converts)
            return
        parallel = min(parallel, free)
        chunks = [c for c in (items[i::parallel] for i in range(parallel)) if c]
        for chunk in chunks:
            loader = _ConvertLoader(chunk, self._convert_hfs)
            loader.loaded.connect(self._on_loaded)
            loader.attempted.connect(self._on_convert_attempted)
            # The loader is passed EXPLICITLY: _prune_threads may only
            # judge the thread that actually finished, and binding it
            # here beats relying on sender() across a queued connection.
            loader.finished.connect(
                functools.partial(self._prune_threads, loader))
            self._threads.append(loader)
            loader.start()

    def _on_convert_attempted(self, key) -> None:
        self.convert_attempted.emit(key)

    # -- delivery ---------------------------------------------------------

    #: Concurrent _FileLoader threads. Converts are capped
    #: (Parallel Conversions, clamped 1-8); file loads were NOT, and one
    #: loader per event-loop turn is unbounded - measured 22 concurrent
    #: QThreads from a 300-request scroll on warm local SSD, worse on
    #: network storage where each lives longer. Every extra thread also
    #: widens the exposure to the sibling-prune race.
    FILE_LOADER_LIMIT = 4

    def _dispatch_files(self) -> None:
        self._dispatch_scheduled = False
        items = self._file_queue
        self._file_queue = []
        if not items:
            return
        live = sum(
            1 for t in self._threads
            if isinstance(t, _FileLoader) and not _thread_finished(t)
        )
        if live >= self.FILE_LOADER_LIMIT:
            # Put them back and try again on the next turn: the queue
            # drains into free slots instead of spawning a thread per
            # turn regardless of how many are already running.
            self._file_queue = items + self._file_queue
            if not self._dispatch_scheduled:
                self._dispatch_scheduled = True
                # ONE FRAME, not zero. A zero-delay timer re-runs this
                # handler on every event-loop turn for as long as the
                # cap is full - rebuilding the whole queue list and
                # re-counting threads each time - and the thing it is
                # waiting for is a loader FINISHING, which can be
                # several seconds on a network mount. Measured shape:
                # a 300-tile scroll at ~100ms per read keeps four
                # loaders busy for ~7.5s, all of it spent spinning on
                # the thread that also has to paint.
                QtCore.QTimer.singleShot(16, self._dispatch_files)
            return
        loader = _FileLoader(items)
        loader.loaded.connect(self._on_loaded)
        loader.finished.connect(
            functools.partial(self._prune_threads, loader))
        self._threads.append(loader)
        loader.start()

    def _on_loaded(self, key, image) -> None:
        if self._states.get(key) != "pending":
            # Discarded while in flight (library switched away, or a
            # rerender superseded it) - drop the stale delivery.
            return
        self._cache_put(key, image)
        self._states[key] = "done"
        self.ready.emit(key)

    def shutdown(self) -> None:
        """Stop every worker and WAIT for it.

        A QThread whose C++ object is freed while run() is executing
        takes the process down - not an exception, a dealloc inside the
        running thread. That is what a panel reopen used to do: this
        module is RELOADED on reopen, which replaces the engine
        singleton, and the old engine (with its only references to the
        running loaders) was then garbage collected mid-flight.

        Safe to call twice, and safe when nothing is running.
        """
        # Cancel EVERYTHING first, then wait. Cancelling and waiting
        # one thread at a time let the other seven keep working through
        # the first one's timeout - a reopen could sit for ~28s.
        for thread in list(self._threads):
            try:
                cancel = getattr(thread, "cancel", None)
                if cancel is not None:
                    cancel()
                thread.requestInterruption()
            except RuntimeError:
                pass
        unstopped = []
        for thread in list(self._threads):
            try:
                if not thread.isRunning():
                    continue
                # Bounded: a stuck iconvert must not hold up a reopen.
                if not thread.wait(3000):
                    thread.terminate()
                    if not thread.wait(500):
                        unstopped.append(thread)
            except RuntimeError:
                pass          # already gone - nothing left to wait for
        # A thread we could NOT stop must keep its Python reference:
        # clearing the list would let the collector free a QThread whose
        # run() is still executing, which is the very crash this method
        # exists to prevent (a dealloc inside the thread, not an
        # exception). Park it instead - it dies with the process.
        if unstopped:
            _unstoppable.extend(unstopped)
            debug.event("thumbnails", "threads would not stop - parked",
                        count=len(unstopped))
        self._threads = []
        # The cache dies with the engine: a reopen replaces the
        # singleton, and holding the old one's images pinned a full
        # budget (256MB by default) per reopen for the session.
        self._lru.clear()
        self._bytes = 0
        # _states was never cleared, so a shut-down engine kept one
        # entry per key it had ever seen (measured: 300 after 300
        # requests) for as long as anything referenced it - and the
        # handover below keeps the previous engine referenced.
        self._states = {}
        self._thumb_rows = getattr(self, "_thumb_rows", {})
        self._file_queue = []
        self._convert_queue = []
        self._dispatch_scheduled = False
        self._convert_scheduled = False

    def _prune_threads(self, finisher=None) -> None:
        """A loader finished. Its deliveries were queued before its
        finished signal, so any of its keys STILL pending never
        delivered - the file is genuinely unreadable/absent: mark
        missing and notify, so the row repaints with its placeholder.

        THAT ORDERING GUARANTEE IS PER-THREAD, and this used to judge
        every thread it found finished. A sibling loader that had just
        finished reported isFinished() True while its own `loaded`
        signals were still sitting in the main thread's queue, unhandled
        - so the finisher's prune condemned the sibling's keys, and when
        those deliveries finally arrived _on_loaded dropped them,
        because the state was no longer "pending".

        Sticky, too: texture_library short-circuits on is_missing(), so
        those rows never even fall back to the disk cache on a revisit.
        Only a rerender or a panel reopen cleared them.

        Measured over 300 real PNGs, keys never reaching "done", with a
        3ms repaint handler standing in for the model (A = HEAD,
        B = this fix, 4 runs each):

            parallel=4, idle main thread   A 0,0,0,0      B 0,0,0,0
            parallel=4, 3ms repaints       A 3,2,15,5     B 0,0,0,0
            parallel=8, idle main thread   A 2,1,3,1      B 0,0,0,0
            parallel=8, 3ms repaints       A 27,29,52,22  B 0,0,0,0

        Every lost key had already been emitted by its worker, and the
        losses were the TAIL of each chunk across all eight siblings -
        exactly the deliveries still queued behind the finished being
        handled. Zero loss with an idle main thread at parallel=4, which
        is why this read as intermittent rather than as a bug.

        So: judge ONLY the loader that emitted the signal. Siblings stay
        in the list and are judged when their own finished arrives.
        (The review reported 293 of 300 lost; reproduction never
        exceeded 52.)
        """
        if finisher is None:
            # Fallback for a direct call; the connect sites pass the
            # loader explicitly so this never depends on sender().
            finisher = self.sender()

        def _gone(thread):
            try:
                thread.isFinished()
                return False
            except RuntimeError:
                return True   # C++ side deleted - it can never emit

        # Drop the finisher and anything whose C++ object is already
        # gone. A finished SIBLING is deliberately kept: dropping our
        # last reference while Qt still holds queued deliveries from it
        # is the hazard shutdown() exists to avoid, and it will be
        # removed by its own finished signal a moment later.
        self._threads = [t for t in self._threads
                         if t is not finisher and not _gone(t)]
        if finisher is None:
            return
        try:
            thread_keys = finisher.keys()
        except RuntimeError:
            return            # cannot ask a deleted object what it held
        if getattr(finisher, "_canceled", False):
            # Cancelled work is unrequested, not missing - the revisit
            # re-queues it.
            return
        for key in thread_keys:
            if self._states.get(key) == "pending":
                self._states[key] = "missing"
                self.ready.emit(key)


#: the app-wide engine every section shares
# Panel reopen RELOADS this module, which re-runs this line. Without
# the handover the previous engine - holding the only references to its
# running loader threads - was simply dropped, and the garbage
# collector freed a QThread whose run() was still executing (a dealloc
# inside the thread, not a catchable exception). Stop the old one
# first; the new engine starts clean.
_previous_engine = globals().get("engine")
if _previous_engine is not None:
    try:
        _previous_engine.shutdown()
    except Exception:                                    # noqa: BLE001
        pass
    # Drop the old engine's hooks, or every reopen adds another dead
    # engine to atexit and to aboutToQuit for the rest of the session.
    try:
        atexit.unregister(_previous_engine.shutdown)
    except Exception:                                    # noqa: BLE001
        pass
    try:
        _prev_app = QtCore.QCoreApplication.instance()
        if _prev_app is not None:
            _prev_app.aboutToQuit.disconnect(_previous_engine.shutdown)
    except (RuntimeError, TypeError):
        pass                     # was never connected, or already gone

class _EngineSignals(QtCore.QObject):
    """A reload-stable relay for the engine's two delivery signals.

    Models connect at CONSTRUCTION - core/library.py, texture_library,
    geo_library and matx_library all do
    `thumbnails.engine.ready.connect(...)` in __init__ - but the engine
    SINGLETON is replaced on every module reload, and the handover above
    shuts the old one down. So with Amaze open in two pane tabs (an
    explicitly supported layout), opening the second reloads this module
    and the FIRST tab's models stay wired to a dead engine.

    Measured: after the reload the new engine loaded and cached all 6
    loadable rows, a later data() call returned 7/7 images, but 0 of 7
    arrival repaints reached the old model. So the first tab's tiles sit
    on placeholders while idle and fill in the moment you scroll or
    resize - plus its texture progress bar freezes.

    This object survives the reload; the engine is still rebuilt every
    time, so code edits keep taking effect. Nothing but signals lives
    here - adding a method later would freeze it against reloads too.
    """

    ready = QtCore.Signal(object)
    convert_attempted = QtCore.Signal(object)


signals = globals().get("signals")
if signals is None or not hasattr(signals, "convert_attempted"):
    # Rebuilt when absent, or when an older relay lacks a signal added
    # since - which degrades to the old behaviour rather than raising
    # inside the reload chain and leaving the panel unopenable.
    signals = _EngineSignals()

if _previous_engine is not None:
    for _sig, _relay in (("ready", signals.ready),
                         ("convert_attempted", signals.convert_attempted)):
        try:
            getattr(_previous_engine, _sig).disconnect(_relay)
        except (RuntimeError, TypeError):
            pass

engine = ThumbnailEngine()
engine.ready.connect(signals.ready)
engine.convert_attempted.connect(signals.convert_attempted)

_app_instance = QtCore.QCoreApplication.instance()
if _app_instance is not None:
    # Quitting Houdini mid-load is the same hazard by another route.
    _app_instance.aboutToQuit.connect(engine.shutdown)

# ...and once more at interpreter teardown. aboutToQuit only fires when
# Qt's event loop is asked to quit, which a headless script never does:
# there, PySide tears the QApplication down from atexit and any live
# QThread is destroyed while running - the same dealloc-inside-run().
atexit.register(engine.shutdown)
