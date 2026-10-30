"""How every engine stops its QThreads, and hands itself over on a reload. ▸r/model-contracts"""

import atexit
import time

from amaze.core import debug

WAIT_MS = 3000    # ONE window for all of them at once: a stuck socket must not hold up a quit
TERMINATE_MS = 500    # the window after terminate(), shared the same way

_unstoppable: list = globals().get("_unstoppable", [])    # parked FOREVER, across reloads ▸r/module-reload
_installed: dict = globals().get("_installed", {})    # name -> the engine install() made last


def gone(thread) -> bool:
    """A thread whose C++ side is deleted: it can never emit again."""
    try:
        thread.isFinished()
        return False
    except RuntimeError:
        return True


def finished(thread) -> bool:
    """isFinished(), a deleted C++ side counting as finished."""
    try:
        return thread.isFinished()
    except RuntimeError:
        return True


def stop(threads, label: str, cancel: bool = True) -> None:
    """Ask every thread to stop, then wait them out together; one that will not end is parked."""
    threads = list(threads)
    for thread in threads:
        try:
            if cancel:
                thread.cancel()    # the worker's own stop flag, `_canceled`, read between its items
            thread.requestInterruption()
        except RuntimeError:
            pass    # C++ side deleted: nothing left to stop
    running = _running_after(threads, WAIT_MS)
    for thread in running:
        try:
            if thread.isRunning():    # one that ended since its wait gets no terminate()
                thread.terminate()
        except RuntimeError:
            pass
    unstopped = _running_after(running, TERMINATE_MS)
    if unstopped:    # dropped while it runs, it is freed inside run() and aborts ▸r/model-contracts
        _unstoppable.extend(unstopped)
        debug.event(label, "threads would not stop - parked", count=len(unstopped))


def _running_after(threads, window_ms: int) -> list:
    """The threads still running once `window_ms` has passed, the one window shared by all."""
    deadline = time.monotonic() + window_ms / 1000.0
    running = []
    for thread in threads:
        left = max(0, int((deadline - time.monotonic()) * 1000))
        try:
            if thread.isRunning() and not thread.wait(left):
                running.append(thread)
        except RuntimeError:
            pass    # already gone
    return running


def install(name: str, make, app, keep=None):
    """`make()` as the process's one `name` engine; the last one is stopped and unhooked first."""
    old = _installed.get(name)
    if old is not None and keep is not None and keep(old):
        return old    # carries on as it is, quit hooks and all
    if old is not None:
        _retire(old, app)
    engine = make()
    if app is not None:
        app.aboutToQuit.connect(engine.shutdown)    # quitting Houdini mid-run
    atexit.register(engine.shutdown)    # headless, aboutToQuit never fires ▸r/model-contracts
    _installed[name] = engine
    return engine


def _retire(engine, app) -> None:
    """Stop `engine` and take back its quit hooks, or each reload adds a dead engine to them."""
    try:
        engine.shutdown()
    except Exception:                                    # noqa: BLE001 - the new engine comes anyway
        pass
    atexit.unregister(engine.shutdown)
    if app is not None:
        try:
            app.aboutToQuit.disconnect(engine.shutdown)
        except (RuntimeError, TypeError):
            pass    # never connected, or already gone
