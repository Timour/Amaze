"""The ONE thumbnail system every section flows through: keyed (never row-numbered) images in one byte-capped LRU with absent/pending/done/missing states, missing sticky until `discard()`; the providers (FILE, CONVERT ▸o/conversion, RENDER, PAINT) are the only per-source code - this engine keeps the cache and the loaders, it is not the decoder."""

import atexit
import functools
from collections import OrderedDict

from PySide6 import QtCore, QtGui

from amaze.core import conversion, debug


_unstoppable: list = globals().get("_unstoppable", [])    # threads that refused to stop, parked FOREVER and carried across reloads: the parked reference must exist at thread COMPLETION, and an isRunning()-based prune re-opens the dealloc-inside-run window - they finish or the process ends ▸r/model-contracts ▸r/module-reload


def _thread_finished(thread) -> bool:
    """isFinished(), treating a deleted C++ side as finished."""
    try:
        return thread.isFinished()
    except RuntimeError:
        return True


class _FileLoader(QtCore.QThread):
    """Loads image files for a batch of keys off the main thread; failures deliberately emit nothing - a key still pending when the batch finishes is how the engine knows the file is missing."""

    loaded = QtCore.Signal(object, QtGui.QImage)

    def __init__(self, items) -> None:
        super().__init__()
        self._items = items  # [(key, path)]
        self._canceled = False

    def keys(self):
        return [key for key, _path in self._items]

    def cancel(self) -> None:
        """Stop after the current file - shutdown needs this: waiting for a full batch of disk reads would stall a panel reopen."""
        self._canceled = True

    def run(self) -> None:
        for key, path in self._items:
            if self._canceled:
                return
            image = QtGui.QImage(path)
            if not image.isNull():
                self.loaded.emit(key, image)


class _ConvertLoader(QtCore.QThread):
    """The CONVERT provider's worker: generates texture thumbnails off the UI thread - each item may shell out to iconvert (up to a 30s timeout), the one work worth cancelling when the user browses away; it only generates images and never touches the disk cache, whose manifest is main-thread-only."""

    loaded = QtCore.Signal(object, QtGui.QImage)
    attempted = QtCore.Signal(object)    # fired after EVERY item, success or failure - the progress bar must advance on a failed file too, or it stalls short of 100%

    def __init__(self, items, hfs) -> None:
        super().__init__()
        self._items = items  # [(key, full_path, size)]
        self._hfs = hfs
        self._canceled = False    # the ONE stop flag, `_prune_threads`' read and the run loop's alike - _FileLoader keeps the identical contract

    def keys(self):
        return [item[0] for item in self._items]

    def cancel(self) -> None:
        self._canceled = True

    def _cancelled(self) -> bool:
        """Polled by `conversion._run_process`'s 100ms watchdog from inside the nested event loop where this worker lives - wired, cancel() gets the worker out within 100ms with its own child killed and temp file removed, and interruption counts too since shutdown() requests it on every thread."""
        return self._canceled or self.isInterruptionRequested()

    def run(self) -> None:
        """One call to the Conversion Engine per item, and nothing else - the engine owns decoder policy, this worker owns staying off the UI thread and stopping when told."""
        for key, full_path, size in self._items:
            if self._canceled:
                return
            try:
                result = conversion.convert_image(
                    full_path, size, cancelled=self._cancelled,
                    hfs=self._hfs)
                image = result.image
            except Exception as exc:                          # noqa: BLE001 - a backstop only: convert_image answers with a reason rather than raising, and a raise here would take the rest of the batch with it
                debug.event(
                    "texture", "thumbnail failed", file=full_path, error=str(exc)
                )
                image = None
            if self._canceled:
                return
            if image is not None:
                self.loaded.emit(key, image)
            self.attempted.emit(key)



class ThumbnailEngine(QtCore.QObject):
    ready = QtCore.Signal(object)    # a key's image arrived (repaint it) - or its load failed, and data() will now see is_missing() and paint a placeholder
    convert_attempted = QtCore.Signal(object)    # a convert item was attempted, success or failure - drives the texture progress bar

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
        self._convert_hfs = ""    # convert options, pushed by the texture model per batch so Preferences changes apply without a restart
        self._convert_parallel = 4
        self._threads = []    # threads stay referenced until finished - dropping a running QThread's only Python reference frees the C++ object mid-run ▸r/model-contracts

    def set_budget_mb(self, budget_mb) -> None:
        try:
            budget_mb = int(budget_mb)
        except (TypeError, ValueError):
            return
        self._budget = max(64, budget_mb) * 1024 * 1024
        self._evict()

    def _evict(self) -> None:
        while self._bytes > self._budget and len(self._lru) > 1:    # the newest entry always stays, so one oversized image cannot evict itself into a reload loop
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

    def request_file(self, key, path):
        """The FILE provider: the cached image, or queue a background load and answer None (the caller paints its placeholder) - one paint pass's requests coalesce into a single loader batch via the zero-timer, and this is called from data(), so it stays cheap."""
        image = self._cache_get(key)
        if image is not None:
            return image
        state = self._states.get(key)
        if state == "pending" or state == "missing":
            return None
        self._states[key] = "pending"    # never requested - or delivered once and since evicted: load
        self._file_queue.append((key, path))
        if not self._dispatch_scheduled:
            self._dispatch_scheduled = True
            QtCore.QTimer.singleShot(0, self._dispatch_files)
        return None

    def peek(self, key):
        """Cache lookup only, no request on miss - convert-sourced rows use this, their generation queued eagerly per folder rather than driven by paints."""
        return self._cache_get(key)

    def is_pending(self, key) -> bool:
        return self._states.get(key) == "pending"

    def is_missing(self, key) -> bool:
        return self._states.get(key) == "missing"

    def deposit(self, key, image) -> None:
        """Main-thread providers hand finished images straight in (geometry's render pass, colors' synchronous paints): cached under the budget, marked done, announced like any other delivery."""
        self._cache_put(key, image)
        self._states[key] = "done"
        QtCore.QTimer.singleShot(0, lambda k=key: self.ready.emit(k))    # DEFERRED: several models deposit from inside data(), and a synchronous emit reaches dataChanged FROM INSIDE a view's own fetch - re-entrant by construction

    def discard(self, key) -> None:
        """Forget a key entirely (image AND state) - a rerender or overwrite calls this so the next repaint reloads the fresh file, and a previously-missing key gets its retry."""
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

    def configure_convert(self, hfs, parallel) -> None:
        self._convert_hfs = hfs
        self._convert_parallel = max(1, min(8, int(parallel)))

    def request_convert(self, key, full_path, size) -> None:
        """Queue an image for background generation through the Conversion Engine - eagerly per folder, so the expensive one-time work runs on open with the progress bar; NO extension is passed, because which decoder a file needs is measured from the file, never guessed from its name here."""
        if self._states.get(key) == "pending":
            return
        self._states[key] = "pending"
        self._convert_queue.append((key, full_path, size))
        if not self._convert_scheduled:
            self._convert_scheduled = True
            QtCore.QTimer.singleShot(0, self._dispatch_converts)

    def cancel_pending_converts(self) -> None:
        """A folder switch abandons its unfinished conversions (a revisit re-queues): undelivered keys reset to unrequested, never to missing, and a canceled loader's late delivery is dropped by the state check in _on_loaded."""
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
        """Split the queued batch round-robin across N concurrent loaders (Preferences > Parallel Conversions) - each iconvert pays a fixed Houdini-process startup cost, so N at once cuts wall-clock roughly by N."""
        self._convert_scheduled = False
        items = self._convert_queue
        self._convert_queue = []
        if not items:
            return
        parallel = self._convert_parallel
        live = sum(    # a LIVE cap, not per-dispatch: counting nothing let a rerender during a running batch double the subprocesses, 8 loaders against a preference of 4
            1 for t in self._threads
            if isinstance(t, _ConvertLoader) and not _thread_finished(t)
        )
        free = parallel - live
        if free <= 0:
            self._convert_queue = items + self._convert_queue    # back on the queue, retried when a slot frees - ONE FRAME, not 0ms, which would spin this handler every event-loop turn while a 30s iconvert holds the slot
            if not self._convert_scheduled:
                self._convert_scheduled = True
                QtCore.QTimer.singleShot(16, self._dispatch_converts)
            return
        parallel = min(parallel, free)
        chunks = [c for c in (items[i::parallel] for i in range(parallel)) if c]
        for chunk in chunks:
            loader = _ConvertLoader(chunk, self._convert_hfs)
            loader.loaded.connect(self._on_loaded)
            loader.attempted.connect(self._on_convert_attempted)
            loader.finished.connect(    # the loader passed EXPLICITLY: _prune_threads may only judge the thread that actually finished, and binding beats sender() across a queued connection
                functools.partial(self._prune_threads, loader))
            self._threads.append(loader)
            loader.start()

    def _on_convert_attempted(self, key) -> None:
        self.convert_attempted.emit(key)

    FILE_LOADER_LIMIT = 4    # concurrent _FileLoader threads - uncapped, one loader per event-loop turn measured 22 concurrent QThreads from a 300-request scroll, and every extra thread widens the sibling-prune exposure

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
            self._file_queue = items + self._file_queue    # back on the queue: it drains into free slots instead of spawning a thread per turn
            if not self._dispatch_scheduled:
                self._dispatch_scheduled = True
                QtCore.QTimer.singleShot(16, self._dispatch_files)    # ONE FRAME, not zero - a 0ms re-arm spins on the paint thread for as long as the cap stays full, measured ~7.5s of pure spin on a 300-tile scroll
            return
        loader = _FileLoader(items)
        loader.loaded.connect(self._on_loaded)
        loader.finished.connect(
            functools.partial(self._prune_threads, loader))
        self._threads.append(loader)
        loader.start()

    def _on_loaded(self, key, image) -> None:
        if self._states.get(key) != "pending":    # discarded while in flight (library switched away, or a rerender superseded it) - drop the stale delivery
            return
        self._cache_put(key, image)
        self._states[key] = "done"
        self.ready.emit(key)

    def shutdown(self) -> None:
        """Stop every worker and WAIT for it - a QThread freed while run() executes takes the process down (▸r/model-contracts), which is what a panel reopen's reload used to do. Safe to call twice, and safe when nothing is running."""
        for thread in list(self._threads):    # cancel EVERYTHING first, then wait - one thread at a time let the other seven keep working through the first one's timeout, ~28s per reopen
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
                if not thread.wait(3000):    # bounded: a stuck iconvert must not hold up a reopen
                    thread.terminate()
                    if not thread.wait(500):
                        unstopped.append(thread)
            except RuntimeError:
                pass          # already gone - nothing left to wait for
        if unstopped:    # a thread that would NOT stop keeps its Python reference - parked, it dies with the process; cleared, the collector frees a QThread mid-run ▸r/model-contracts
            _unstoppable.extend(unstopped)
            debug.event("thumbnails", "threads would not stop - parked",
                        count=len(unstopped))
        self._threads = []
        self._lru.clear()    # the cache dies with the engine - a reopen replaces the singleton, and holding the old images pinned a full budget per reopen
        self._bytes = 0
        self._states = {}    # cleared, or a shut-down engine keeps one entry per key it ever saw for as long as the handover below references it
        self._file_queue = []
        self._convert_queue = []
        self._dispatch_scheduled = False
        self._convert_scheduled = False

    def _prune_threads(self, finisher=None) -> None:
        """A loader finished: mark its still-pending keys missing, JUDGING ONLY THE LOADER THAT EMITTED THE SIGNAL - the ordering guarantee is per-thread, and a sibling reports isFinished() while its own deliveries are still queued, so condemning its keys makes _on_loaded drop them, sticky."""
        if finisher is None:
            finisher = self.sender()    # fallback for a direct call; the connect sites pass the loader explicitly

        def _gone(thread):
            try:
                thread.isFinished()
                return False
            except RuntimeError:
                return True   # C++ side deleted - it can never emit

        self._threads = [t for t in self._threads    # drops the finisher and the C++-deleted; a finished SIBLING is deliberately kept until its own signal, since Qt may still hold its queued deliveries
                         if t is not finisher and not _gone(t)]
        if finisher is None:
            return
        try:
            thread_keys = finisher.keys()
        except RuntimeError:
            return            # cannot ask a deleted object what it held
        if getattr(finisher, "_canceled", False):
            return    # cancelled work is unrequested, not missing - the revisit re-queues it

        def _condemn(keys=tuple(thread_keys)):
            for key in keys:
                if self._states.get(key) == "pending":
                    self._states[key] = "missing"
                    try:
                        self.ready.emit(key)
                    except RuntimeError:
                        return   # the engine's C++ side died between turns - a reload handover; nothing left to repaint
        QtCore.QTimer.singleShot(0, _condemn)    # ONE TURN LATER, never in the finished-turn itself: on a stalled main thread the finisher's own queued deliveries can arrive BEHIND its finished signal, and a same-turn verdict condemned 16 of 16 real images at the 2026-08-29 cold open - sticky, since missing never retries ▸p/prune-outran-deliveries


_previous_engine = globals().get("engine")    # the reopen HANDOVER: reload re-runs this body, and without stopping the old engine first the collector freed a QThread mid-run ▸r/module-reload ▸r/model-contracts
if _previous_engine is not None:
    try:
        _previous_engine.shutdown()
    except Exception:                                    # noqa: BLE001
        pass
    try:
        atexit.unregister(_previous_engine.shutdown)    # the old engine's hooks go too, or every reopen adds another dead engine to atexit and aboutToQuit for the session
    except Exception:                                    # noqa: BLE001
        pass
    try:
        _prev_app = QtCore.QCoreApplication.instance()
        if _prev_app is not None:
            _prev_app.aboutToQuit.disconnect(_previous_engine.shutdown)
    except (RuntimeError, TypeError):
        pass                     # was never connected, or already gone

class _EngineSignals(QtCore.QObject):
    """A reload-stable relay for the engine's two delivery signals: models connect HERE at construction, because the engine singleton is replaced on every reload and a model wired to the dead one never repaints (measured: 0 of 7 arrival repaints reached a first pane tab after a second opened). Nothing but signals lives here - a method would freeze against reloads too. ▸r/module-reload"""

    ready = QtCore.Signal(object)
    convert_attempted = QtCore.Signal(object)


signals = globals().get("signals")
if signals is None or not hasattr(signals, "convert_attempted"):
    signals = _EngineSignals()    # rebuilt when absent, or when an older relay lacks a signal added since - degrading rather than raising inside the reload chain and leaving the panel unopenable

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
    _app_instance.aboutToQuit.connect(engine.shutdown)    # quitting Houdini mid-load is the same hazard by another route

atexit.register(engine.shutdown)    # once more at interpreter teardown: aboutToQuit never fires in a headless script, where PySide tears the QApplication down from atexit and destroys any live QThread mid-run
