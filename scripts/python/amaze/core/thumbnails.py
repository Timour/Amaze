"""The thumbnail engine: keyed images in one byte-capped LRU; missing stays until `discard()`."""

import functools
import os
from collections import OrderedDict

from PySide6 import QtCore, QtGui

from amaze.core import debug, workers
from amaze.helpers import hostos

CACHE_PNG_QUALITY = 80    # the zlib level only - PNG is lossless, so the image is the same at any level


class _FileLoader(QtCore.QThread):
    """Loads image files for a batch of keys off the main thread, emitting `failed` for each failure."""

    loaded = QtCore.Signal(object, QtGui.QImage, int)    # (key, image, the token it was requested with)
    failed = QtCore.Signal(object, int)

    def __init__(self, items) -> None:
        super().__init__()
        self._items = items  # [(key, path, token)]
        self._canceled = False

    def requests(self):
        """(key, token) for every item - the requests this loader handles."""
        return [(item[0], item[-1]) for item in self._items]

    def cancel(self) -> None:
        """Stop after the current file."""
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
    """`image` as a PNG in a scratch beside `dest`: (scratch, dest), or None, logged, if it fails."""
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        scratch = hostos.unique_scratch(dest)
    except (OSError, hostos.SandboxRefused) as exc:
        why = str(exc)
    else:
        if image.save(scratch, "PNG", CACHE_PNG_QUALITY):    # returns False, does not raise ▸r/model-contracts
            return scratch, dest
        hostos.discard_scratch(scratch)
        why = "the PNG did not save"
    debug.note("the thumbnail for %s could not be saved (%s), so it is made again on every visit. "
               "The image itself is untouched." % (os.path.basename(source), why), path=dest)
    return None


class _ConvertLoader(QtCore.QThread):
    """The CONVERT worker: converts and encodes each cache PNG off the UI thread, never the manifest."""

    loaded = QtCore.Signal(object, QtGui.QImage, int, object)    # (key, image, token, (scratch, dest) or None)
    attempted = QtCore.Signal(object, int)    # after EVERY item, or the progress bar stops before 100%
    failed = QtCore.Signal(object, int)

    def __init__(self, items, hfs) -> None:
        super().__init__()
        self._items = items  # [(key, full_path, size, dest, token)]; an empty dest means no PNG
        self._hfs = hfs
        self._canceled = False    # the one stop flag, read by `_prune_threads` and the run loop

    requests = _FileLoader.requests

    def cancel(self) -> None:
        self._canceled = True

    def _cancelled(self) -> bool:
        """True once canceled or interrupted; polled every 100ms by `conversion._run_process`."""
        return self._canceled or self.isInterruptionRequested()

    def run(self) -> None:
        """One Conversion Engine call per item, off the UI thread, until canceled."""
        from amaze.core import conversion
        for key, full_path, size, dest, token in self._items:
            if self._canceled:
                return
            try:
                result = conversion.convert_image(
                    full_path, size, cancelled=self._cancelled,
                    hfs=self._hfs)
                image = result.image
            except Exception as exc:                          # noqa: BLE001 - a last-resort catch only
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
    converted = QtCore.Signal(object, str)    # (key, png): a conversion's PNG is saved at the requested path
    ready = QtCore.Signal(object)    # a key's image loaded or failed: repaint it
    convert_attempted = QtCore.Signal(object)    # a convert item was attempted, success or failure - drives the texture progress bar

    def __init__(self, budget_mb: int = 256) -> None:
        super().__init__()
        self._lru = OrderedDict()  # key -> (QImage, nbytes)
        self._bytes = 0
        self._budget = int(budget_mb) * 1024 * 1024
        self._states = {}  # key -> `pending` | `done` | `missing`
        self._generations = {}  # key -> times discarded; a result is used only under the current count
        self._file_queue = []  # [(key, path, token)] awaiting dispatch
        self._dispatch_scheduled = False
        self._convert_queue = []  # [(key, full_path, size, dest, token)]
        self._convert_scheduled = False
        self._convert_hfs = ""    # convert options, set by the texture model per batch
        self._convert_parallel = 4
        self._threads = []    # threads stay referenced until finished ▸r/model-contracts

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
        """The cached image, or None with a background load queued; cheap enough for data()."""
        image = self._cache_get(key)
        if image is not None:
            return image
        state = self._states.get(key)
        if state == "pending" or state == "missing":
            return None
        self._states[key] = "pending"    # never requested - or loaded once and since evicted: load
        self._file_queue.append((key, path, self._generations.get(key, 0)))
        if not self._dispatch_scheduled:
            self._dispatch_scheduled = True
            QtCore.QTimer.singleShot(0, self._dispatch_files)
        return None

    def peek(self, key):
        """The cached image or None, with no request on a miss."""
        return self._cache_get(key)

    def is_pending(self, key) -> bool:
        return self._states.get(key) == "pending"

    def is_missing(self, key) -> bool:
        return self._states.get(key) == "missing"

    def _current(self, key, token) -> bool:
        """Whether a result requested with `token` still matches the key's pending request."""
        return self._states.get(key) == "pending" and self._generations.get(key, 0) == token

    def deposit(self, key, image) -> None:
        """Cache a finished image from the main thread, mark it done and emit `ready`."""
        self._cache_put(key, image)
        self._states[key] = "done"
        QtCore.QTimer.singleShot(0, lambda k=key: self.ready.emit(k))    # deferred: safe from inside data()

    def discard(self, key) -> None:
        """Forget a key's image and state, so the next repaint reloads it."""
        old = self._lru.pop(key, None)
        if old is not None:
            self._bytes -= old[1]
        self._states.pop(key, None)
        self._generations[key] = self._generations.get(key, 0) + 1    # a load already running is now stale

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
        """Queue an image for background generation through the Conversion Engine."""
        if self._states.get(key) == "pending":
            return
        self._states[key] = "pending"
        self._convert_queue.append(    # `dest`: where its PNG is saved; `converted` emits it; empty for none
            (key, full_path, size, dest, self._generations.get(key, 0)))
        if not self._convert_scheduled:
            self._convert_scheduled = True
            QtCore.QTimer.singleShot(0, self._dispatch_converts)

    def cancel_pending_converts(self) -> None:
        """Abandon unfinished conversions; their keys reset to unrequested, never to missing."""
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
        """Split the queue round-robin across the Parallel Conversions count of loaders."""
        self._convert_scheduled = False
        items = self._convert_queue
        self._convert_queue = []
        if not items:
            return
        parallel = self._convert_parallel
        live = sum(    # the cap counts loaders already running
            1 for t in self._threads
            if isinstance(t, _ConvertLoader) and not workers.finished(t)
        )
        free = parallel - live
        if free <= 0:
            self._convert_queue = items + self._convert_queue    # retried one frame later
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
            loader.finished.connect(    # the finished loader is passed explicitly
                functools.partial(self._prune_threads, loader))
            self._threads.append(loader)
            loader.start()

    def _on_convert_attempted(self, key, token) -> None:
        if self._generations.get(key, 0) == token:    # an attempt for an older request is ignored
            self.convert_attempted.emit(key)

    FILE_LOADER_LIMIT = 4    # concurrent _FileLoader threads at most

    def _dispatch_files(self) -> None:
        self._dispatch_scheduled = False
        items = self._file_queue
        self._file_queue = []
        if not items:
            return
        live = sum(
            1 for t in self._threads
            if isinstance(t, _FileLoader) and not workers.finished(t)
        )
        if live >= self.FILE_LOADER_LIMIT:
            self._file_queue = items + self._file_queue    # back on the queue: it waits for a free slot instead of starting a thread per turn
            if not self._dispatch_scheduled:
                self._dispatch_scheduled = True
                QtCore.QTimer.singleShot(16, self._dispatch_files)    # one frame, never zero
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
        if not self._current(key, token):    # discarded while loading, or requested again since: stale
            if written:
                hostos.discard_scratch(written[0])    # so a stale PNG never replaces a fresh one
            return
        self._cache_put(key, image)
        self._states[key] = "done"
        if written:
            self._file_png(key, *written)
        self.ready.emit(key)

    def _file_png(self, key, scratch, dest) -> None:
        """Promote a current conversion's scratch PNG to `dest` and emit `converted`; a failure is logged."""
        try:
            hostos.promote_scratch(scratch, dest)
        except (OSError, hostos.SandboxRefused) as exc:
            hostos.discard_scratch(scratch)
            debug.event("thumbnails", "converted png not written", path=dest, error=str(exc))
            return
        self.converted.emit(key, dest)

    def shutdown(self) -> None:
        """Stop every worker and wait for it; safe twice and when idle ▸r/model-contracts"""
        workers.stop(self._threads, "thumbnails")
        self._threads = []
        self._lru.clear()    # the cache is cleared with the engine
        self._bytes = 0
        self._states = {}
        self._generations = {}
        self._file_queue = []
        self._convert_queue = []
        self._dispatch_scheduled = False
        self._convert_scheduled = False

    def _prune_threads(self, finisher=None) -> None:
        """A finished loader's own unloaded keys are reset to be requested again; other loaders' are kept."""
        if finisher is None:
            finisher = self.sender()    # fallback for a direct call; the connect sites pass the loader explicitly
        self._threads = [t for t in self._threads    # another finished loader stays until its own signal
                         if t is not finisher and not workers.gone(t)]
        if finisher is None:
            return
        try:
            thread_requests = finisher.requests()
        except RuntimeError:
            return            # a deleted object cannot report its requests
        if getattr(finisher, "_canceled", False):
            return    # cancelled work is unrequested, not missing - the next repaint queues it again

        def _forget(requests=tuple(thread_requests)):
            for key, token in requests:
                if self._current(key, token):    # never a newer request's key, still loading elsewhere
                    self._states.pop(key, None)    # not loaded, not failed: the next paint requests it again
                    try:
                        self.ready.emit(key)
                    except RuntimeError:
                        return   # the engine's C++ object was deleted by a reload between turns; nothing to repaint
        QtCore.QTimer.singleShot(0, _forget)    # one event-loop turn later: its own queued loads are handled first ▸p/prune-outran-deliveries


_previous_engine = globals().get("engine")    # its signals are disconnected below; install() stops it

class _EngineSignals(QtCore.QObject):
    """Signals kept across reloads: models connect here; a method would keep old code ▸r/module-reload"""

    ready = QtCore.Signal(object)
    convert_attempted = QtCore.Signal(object)
    converted = QtCore.Signal(object, str)


signals = globals().get("signals")
if signals is None or not hasattr(signals, "converted"):
    signals = _EngineSignals()    # rebuilt when absent or missing a signal

if _previous_engine is not None:
    for _sig, _relay in (("ready", signals.ready),
                         ("convert_attempted", signals.convert_attempted),
                         ("converted", signals.converted)):
        try:
            getattr(_previous_engine, _sig).disconnect(_relay)
        except (AttributeError, RuntimeError, TypeError):    # an older engine may lack the signal
            pass

engine = workers.install(__name__, ThumbnailEngine, QtCore.QCoreApplication.instance())
engine.ready.connect(signals.ready)
engine.convert_attempted.connect(signals.convert_attempted)
engine.converted.connect(signals.converted)
