"""Files moved between folders on disk, never over a name already taken. ▸r/cross-volume-move"""

import collections
import errno
import os
import shutil
import time

from PySide6 import QtCore

from amaze import messages
from amaze.core import captures, debug, locations, workers
from amaze.helpers import hostos

Result = collections.namedtuple("Result", "moved skipped failed")    # pairs, pairs, (source, why)
PART = ".amaze-part"    # a cross-drive copy's suffix until it is whole and placed
CHUNK = 4 << 20    # bytes per read: one stop check and one progress tick between reads
HELD_WAITS = (0.05, 0.15, 0.35)    # seconds between tries at a file Windows says is in use
carriers = globals().get("carriers", {})    # name -> fn(preferences, pairs), a higher layer's share


class Stopped(Exception):
    """Told to stop: the file in hand stays where it was."""


def targets(paths, folder: str) -> list:
    """(source, destination) for each file not already in `folder`, in the order given."""
    return [(path, os.path.join(folder, os.path.basename(path)))
            for path in paths if path and not _same_folder(os.path.dirname(path), folder)]


def _same_folder(one: str, other: str) -> bool:
    try:
        return os.path.samefile(one, other)
    except OSError:
        return (hostos.canonical_path_key(one).rstrip("/")
                == hostos.canonical_path_key(other).rstrip("/"))


def back(pairs) -> list:
    """What an undo moves: each file from where it went to where it was."""
    return [(dest, source) for source, dest in pairs]


def same_drive(path: str, folder: str) -> bool:
    """Whether a rename can carry `path` into `folder`. ▸r/cross-volume-move"""
    try:
        return os.stat(path).st_dev == os.stat(folder).st_dev
    except OSError:
        return False


def _patiently(call, *args):
    """`call(*args)`, retried while Windows answers the file is held, then once more raising - `hostos.replace_file`'s waits."""
    for wait in HELD_WAITS:
        try:
            return call(*args)
        except PermissionError:    # a thumbnail read or a sync scanner holding it for a moment
            time.sleep(wait)
    return call(*args)


def place(source: str, dest: str) -> bool:
    """Move a file within one drive; False, and nothing changed, when `dest` is taken."""
    if hostos.is_windows():
        try:
            _patiently(os.rename, source, dest)    # Windows refuses a taken name itself
        except FileExistsError:
            return False
        return True
    try:
        os.link(source, dest)    # refuses a taken name, where a rename replaces it ▸r/cross-volume-move
    except FileExistsError:
        return False
    except OSError:    # no hard links here: a network share, some synced folders
        if os.path.lexists(dest):
            return False
        os.rename(source, dest)
        return True
    try:
        os.unlink(source)
    except OSError:
        os.unlink(dest)    # one file, where it was
        raise
    return True


def copy_across(source: str, dest: str, tick=None, stopped=lambda: False) -> bool:
    """Copy `source` whole beside `dest`, place it, then remove the source; False if `dest` is taken."""
    if os.path.lexists(dest):
        return False
    _patiently(hostos.check_deletable, source)    # held open on Windows: copying would only make a second file
    part = hostos.unique_scratch(    # a fresh name each copy: a part an interrupted one left blocks nothing
        os.path.join(os.path.dirname(dest), "." + os.path.basename(dest)), PART, create=False)
    made = False
    try:
        with open(source, "rb") as reader, open(part, "xb") as writer:
            made = True
            while True:
                if stopped():
                    raise Stopped()
                block = reader.read(CHUNK)
                if not block:
                    break
                writer.write(block)
                if tick is not None:
                    tick(len(block))
            writer.flush()
            os.fsync(writer.fileno())
        try:
            shutil.copystat(source, part)
        except OSError as exc:    # the content is whole; dates and flags are not worth the move
            debug.event("move", "dates not copied", file=source, error=str(exc))
        if not place(part, dest):
            return False
        made = False
    finally:
        if made:
            _remove(part)
    try:
        hostos.remove_file(source)    # a read-only original goes too, as it does on POSIX
    except OSError as exc:
        raise OSError(exc.errno, messages.MOVE_KEPT_BOTH % (exc.strerror or exc)) from exc
    return True


def _remove(path: str) -> None:
    try:
        hostos.remove_file(path)
    except OSError as exc:    # left behind, hidden; the next copy of that name takes another
        debug.event("move", "a part could not be removed", file=path, error=str(exc))


def _move_one(source: str, dest: str, tick, stopped) -> bool:
    """Placed on one drive, copied whole across two; False when `dest` is taken."""
    if not same_drive(source, os.path.dirname(dest)):
        return copy_across(source, dest, tick, stopped)
    try:
        return place(source, dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    return copy_across(source, dest, tick, stopped)    # one st_dev, two mounts ▸r/cross-volume-move


def move(pairs, tick=None, stopped=lambda: False) -> Result:
    """Each (source, destination) in turn: placed on one drive, copied whole across two."""
    moved, skipped, failed = [], [], []
    for source, dest in pairs:
        if stopped():
            break
        try:
            landed = _move_one(source, dest, tick, stopped)
        except Stopped:
            break
        except OSError as exc:
            failed.append((source, exc.strerror or str(exc)))
            continue
        (moved if landed else skipped).append((source, dest))
    return Result(moved, skipped, failed)


def carry(preferences, pairs) -> None:
    """What Amaze keeps about each moved file follows it: star, comment, icon, capture, pictures."""
    keys = {}
    for old, new in pairs:
        before = captures.file_key(preferences, old)
        after = captures.file_key(preferences, new)
        if before and after and before != after:
            keys[before] = after
    if keys:
        locations.files_moved(preferences, keys)
    for before, after in keys.items():
        try:
            captures.move_file_capture(preferences, before, after)
        except OSError as exc:
            debug.event("move", "a capture did not follow its file",
                        key=before, error=str(exc))
    for name, follow in list(carriers.items()):
        try:
            follow(preferences, pairs)
        except Exception as exc:                          # noqa: BLE001 - one carrier failing leaves the rest theirs
            debug.event("move", "a carrier failed", carrier=name, error=str(exc))


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


class _MoveWorker(QtCore.QThread):
    """One batch off the GUI thread; a stop leaves the file in hand where it was."""

    ticked = QtCore.Signal(object, object)    # (bytes copied, bytes to copy)
    landed = QtCore.Signal(object)    # the Result

    def __init__(self, pairs) -> None:
        super().__init__()
        self.pairs = list(pairs)
        self._canceled = False

    def cancel(self) -> None:
        self._canceled = True

    def _stopped(self) -> bool:
        return self._canceled or self.isInterruptionRequested()

    def run(self) -> None:
        total = sum(_size(source) for source, dest in self.pairs
                    if not same_drive(source, os.path.dirname(dest)))
        done = [0]

        def tick(count) -> None:
            done[0] += count
            self.ticked.emit(done[0], total)

        try:
            result = move(self.pairs, tick, self._stopped)
        except Exception as exc:                          # noqa: BLE001 - logged; the batch still lands
            debug.event("move", "move failed", error=str(exc))
            result = Result([], [], [(source, str(exc)) for source, _dest in self.pairs])
        self.landed.emit(result)


class _MoveEngine(QtCore.QObject):
    """The process's one running move, stopped on quit. ▸r/model-contracts"""

    def __init__(self) -> None:
        super().__init__()
        self._worker = None    # a running QThread must keep a reference until it ends ▸r/model-contracts
        self._job = None    # (preferences, ticked, landed) of the running move

    def busy(self) -> bool:
        return self._worker is not None

    def start(self, pairs, preferences, ticked, landed) -> bool:
        """Move `pairs` on a worker: `ticked(done, total)`, then `landed(result)`; False while busy."""
        if self._worker is not None:
            return False
        worker = _MoveWorker(pairs)
        worker.ticked.connect(self._ticked)    # BOUND slots, so each arrives on this thread
        worker.landed.connect(self._landed)
        worker.finished.connect(self._finished)
        self._worker, self._job = worker, (preferences, ticked, landed)
        worker.start()
        return True

    def _ticked(self, done, total) -> None:
        if self._job is not None:
            self._job[1](done, total)

    def _landed(self, result) -> None:
        if self._job is None:
            return
        preferences, _ticked, landed = self._job
        carry(preferences, result.moved)    # here, on the GUI thread the stores are written from
        try:
            landed(result)
        except RuntimeError:    # the panel that asked is gone; the files and their keys moved
            pass

    def _finished(self) -> None:
        worker = self._worker
        if worker is not None and worker.isFinished():
            self._worker, self._job = None, None

    def shutdown(self) -> None:
        """Stop the move, THEN wait; safe twice and with nothing running."""
        if self._worker is not None:
            workers.stop([self._worker], "move")    # one that will not stop is parked, never dropped
        self._worker, self._job = None, None


mover = workers.install(__name__, _MoveEngine, QtCore.QCoreApplication.instance(),
                        keep=lambda old: old.busy())    # a move under way ends on the engine it began on
