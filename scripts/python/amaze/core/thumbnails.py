"""The ONE thumbnail system every section flows through: keyed (never row-numbered) images in one byte-capped LRU with absent/pending/done/missing states, missing sticky until `discard()`; the providers (FILE, CONVERT ▸o/conversion, RENDER, PAINT) are the only per-source code - this engine keeps the cache and the loaders, it is not the decoder."""

import atexit
import functools
import os
from collections import OrderedDict

from PySide6 import QtCore, QtGui

from amaze.core import debug
from amaze.helpers import hostos

CACHE_PNG_QUALITY = 80    # the zlib level only - PNG is lossless, so the picture is the same at any


_unstoppable: list = globals().get("_unstoppable", [])    # threads that refused to stop, parked FOREVER and carried across reloads: the parked reference must exist at thread COMPLETION, and an isRunning()-based prune re-opens the dealloc-inside-run window - they finish or the process ends ▸r/model-contracts ▸r/module-reload


def _thread_finished(thread) -> bool:
    """isFinished(), treating a deleted C++ side as finished."""
    try:
        return thread.isFinished()
    except RuntimeError:
        return True


class _FileLoader(QtCore.QThread):
    """Loads image files for a batch of keys off the main thread, naming each one that fails."""

    loaded = QtCore.Signal(object, QtGui.QImage, int)    # (key, image, the token it was asked under)
    failed = QtCore.Signal(object, int)

    def __init__(self, items) -> None:
        super().__init__()
        self._items = items  # [(key, path, token)]
        self._canceled = False

    def requests(self):
        """(key, token) for every item - what a verdict on this loader may judge."""
        return [(item[0], item[-1]) for item in self._items]

    def cancel(self) -> None:
        """Stop after the current file - shutdown needs this: waiting for a full batch of disk reads would stall a panel reopen."""
        self._canceled = True

    def run(self) -> None:
        for key, path, token in self._items:
            if self._canceled:
                return
            image = QtGui.QImage(path)
            if image.isNull():
                self.failed.emit(key, token)
            else:
                self.loaded.emit(key, image, token)


def _encoded(image, dest: str, source: str):
    """`image` as a PNG in a scratch beside `dest`: (scratch, dest), or None, said, when it won't save."""
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        scratch = hostos.unique_scratch(dest)
    except (OSError, hostos.SandboxRefused) as exc:
        why = str(exc)
    else:
        if image.save(scratch, "PNG", CACHE_PNG_QUALITY):    # False, not a raise ▸r/model-contracts
            return scratch, dest
        hostos.discard_scratch(scratch)
        why = "the PNG did not save"
    debug.note("the thumbnail for %s could not be saved (%s), so it is made again on every visit. "
               "The image itself is untouched." % (os.path.basename(source), why), path=dest)
    return None


class _ConvertLoader(QtCore.QThread):
    """The CONVERT worker: converts and encodes each cache PNG off the UI thread, never the manifest."""

    loaded = QtCore.Signal(object, QtGui.QImage, int, object)    # (key, image, token, (scratch, dest) or None)
    attempted = QtCore.Signal(object, int)    # after EVERY item, or the progress bar stalls short of 100%
    failed = QtCore.Signal(object, int)

    def __init__(self, items, hfs) -> None:
        super().__init__()
        self._items = items  # [(key, full_path, size, dest, token)]; dest "" asks for no PNG
        self._hfs = hfs
        self._canceled = False    # the ONE stop flag, `_prune_threads`' read and the run loop's alike - _FileLoader keeps the identical contract

    requests = _FileLoader.requests

    def cancel(self) -> None:
        self._canceled = True

    def _cancelled(self) -> bool:
        """Polled by `conversion._run_process`'s 100ms watchdog from inside the nested event loop where this worker lives - wired, cancel() gets the worker out within 100ms with its own child killed and temp file removed, and interruption counts too since shutdown() requests it on every thread."""
        return self._canceled or self.isInterruptionRequested()

    def run(self) -> None:
        """One call to the Conversion Engine per item, and nothing else - the engine owns decoder policy, this worker owns staying off the UI thread and stopping when told."""
        from amaze.core import conversion
        for key, full_path, size, dest, token in self._items:
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
                self.loaded.emit(key, image, token,
                                 _encoded(image, dest, full_path) if dest else None)
            else:
                self.failed.emit(key, token)
            self.attempted.emit(key, token)



class ThumbnailEngine(QtCore.QObject):
    converted = QtCore.Signal(object, str)    # (key, png): a conversion's PNG is filed where it was asked
    ready = QtCore.Signal(object)    # a key's image arrived (repaint it) - or its load failed, and data() will now see is_missing() and paint a placeholder
    convert_attempted = QtCore.Signal(object)    # a convert item was attempted, success or failure - drives the texture progress bar

    def __init__(self, budget_mb: int = 256) -> None:
        super().__init__()
        self._lru = OrderedDict()  # key -> (QImage, nbytes)
        self._bytes = 0
        self._budget = int(budget_mb) * 1024 * 1024
        self._states = {}  # key -> "pending" | "done" | "missing"
        self._generations = {}  # key -> times discarded; a delivery counts only under the current one
        self._file_queue = []  # [(key, path, token)] awaiting dispatch
        self._dispatch_scheduled = False
        self._convert_queue = []  # [(key, full_path, size, dest, token)]
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
        self._file_queue.append((key, path, self._generations.get(key, 0)))
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

    def _current(self, key, token) -> bool:
        """Whether a delivery asked under `token` still answers the key's open request."""
        return self._states.get(key) == "pending" and self._generations.get(key, 0) == token

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
        self._generations[key] = self._generations.get(key, 0) + 1    # a load already in flight is stale

    def clear(self) -> None:
        self._lru.clear()
        self._bytes = 0
        self._states = {
            k: s for k, s in self._states.items() if s == "pending"
        }

    def configure_convert(self, hfs, parallel) -> None:
        self._convert_hfs = hfs
        self._convert_parallel = max(1, min(8, int(parallel)))

    def request_convert(self, key, full_path, size, dest="") -> None:
        """Queue an image for background generation through the Conversion Engine - eagerly per folder, so the expensive one-time work runs on open with the progress bar; NO extension is passed, because which decoder a file needs is measured from the file, never guessed from its name here."""
        if self._states.get(key) == "pending":
            return
        self._states[key] = "pending"
        self._convert_queue.append(    # `dest`: where its PNG is filed, `converted` says so; "" for none
            (key, full_path, size, dest, self._generations.get(key, 0)))
        if not self._convert_scheduled:
            self._convert_scheduled = True
            QtCore.QTimer.singleShot(0, self._dispatch_converts)

    def cancel_pending_converts(self) -> None:
        """A folder switch abandons its unfinished conversions (a revisit re-queues): undelivered keys reset to unrequested, never to missing, and a canceled loader's late delivery is dropped by the state check in _on_loaded."""
        for item in self._convert_queue:
            if self._current(item[0], item[-1]):
                self._states.pop(item[0], None)
        self._convert_queue = []
        for thread in self._threads:
            if isinstance(thread, _ConvertLoader) and not thread.isFinished():
                thread.cancel()
                for key, token in thread.requests():
                    if self._current(key, token):
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
            loader.failed.connect(self._on_failed)
            loader.attempted.connect(self._on_convert_attempted)
            loader.finished.connect(    # the loader passed EXPLICITLY: _prune_threads may only judge the thread that actually finished, and binding beats sender() across a queued connection
                functools.partial(self._prune_threads, loader))
            self._threads.append(loader)
            loader.start()

    def _on_convert_attempted(self, key, token) -> None:
        if self._generations.get(key, 0) == token:    # a superseded attempt is not this request's
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
        loader.failed.connect(self._on_failed)
        loader.finished.connect(
            functools.partial(self._prune_threads, loader))
        self._threads.append(loader)
        loader.start()

    def _on_failed(self, key, token) -> None:
        """A key its loader could not read or convert: missing, until `discard()`."""
        if not self._current(key, token):
            return
        self._states[key] = "missing"
        self.ready.emit(key)

    def _on_loaded(self, key, image, token, written=None) -> None:
        if not self._current(key, token):    # discarded while in flight, or re-asked since: stale
            if written:
                hostos.discard_scratch(written[0])    # so a stale PNG never replaces a fresh one
            return
        self._cache_put(key, image)
        self._states[key] = "done"
        if written:
            self._file_png(key, *written)
        self.ready.emit(key)

    def _file_png(self, key, scratch, dest) -> None:
        """Promote a current conversion's scratch PNG to `dest` and say so; a failure is logged."""
        try:
            hostos.promote_scratch(scratch, dest)
        except (OSError, hostos.SandboxRefused) as exc:
            hostos.discard_scratch(scratch)
            debug.event("thumbnails", "converted png not filed", path=dest, error=str(exc))
            return
        self.converted.emit(key, dest)

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
        self._generations = {}
        self._file_queue = []
        self._convert_queue = []
        self._dispatch_scheduled = False
        self._convert_scheduled = False

    def _prune_threads(self, finisher=None) -> None:
        """A finished loader's own unanswered keys are asked for again; a sibling's are left alone."""
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
            thread_requests = finisher.requests()
        except RuntimeError:
            return            # cannot ask a deleted object what it held
        if getattr(finisher, "_canceled", False):
            return    # cancelled work is unrequested, not missing - the revisit re-queues it

        def _forget(requests=tuple(thread_requests)):
            for key, token in requests:
                if self._current(key, token):    # never a newer request's key, still loading elsewhere
                    self._states.pop(key, None)    # unanswered, not failed: the next paint asks again
                    try:
                        self.ready.emit(key)
                    except RuntimeError:
                        return   # the engine's C++ side died between turns - a reload handover; nothing left to repaint
        QtCore.QTimer.singleShot(0, _forget)    # one turn later: its own queued deliveries land first ▸p/prune-outran-deliveries


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
    """Reload-stable engine signals: models connect here; a method here would freeze. ▸r/module-reload"""

    ready = QtCore.Signal(object)
    convert_attempted = QtCore.Signal(object)
    converted = QtCore.Signal(object, str)


signals = globals().get("signals")
if signals is None or not hasattr(signals, "converted"):
    signals = _EngineSignals()    # rebuilt when absent, or when an older relay lacks a signal added since - degrading rather than raising inside the reload chain and leaving the panel unopenable

if _previous_engine is not None:
    for _sig, _relay in (("ready", signals.ready),
                         ("convert_attempted", signals.convert_attempted),
                         ("converted", signals.converted)):
        try:
            getattr(_previous_engine, _sig).disconnect(_relay)
        except (AttributeError, RuntimeError, TypeError):    # an older engine may lack the signal
            pass

engine = ThumbnailEngine()
engine.ready.connect(signals.ready)
engine.convert_attempted.connect(signals.convert_attempted)
engine.converted.connect(signals.converted)

_app_instance = QtCore.QCoreApplication.instance()
if _app_instance is not None:
    _app_instance.aboutToQuit.connect(engine.shutdown)    # quitting Houdini mid-load is the same hazard by another route

atexit.register(engine.shutdown)    # once more at interpreter teardown: aboutToQuit never fires in a headless script, where PySide tears the QApplication down from atexit and destroys any live QThread mid-run
