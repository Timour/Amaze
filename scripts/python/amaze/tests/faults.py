"""The one fault simulator: a real disk that crashes at a step, runs full, holds a file or races."""

import errno
import os

from amaze.core import guard


class Cut(Exception):
    """The simulated crash: the disk stopped at the chosen step."""


def crash(preferences) -> None:
    """The session ends at the cut, its unsaved changes lost; the next one opens the library."""
    from amaze.core import library_db, model_registry
    library_db.release(preferences)
    model_registry.release()
    library_db.guard_of(preferences)    # a new session finishes a change cut off halfway


class FaultDisk(guard.Disk):
    """`guard.Disk` that crashes at step `cut_at` (`torn`: mid-write), fills at write `full_from`."""

    def __init__(self, cut_at: int = 0, torn: bool = False, full_from: int = 0, busy: str = "",
                 racing: str = "") -> None:
        """`busy`: a file held until `free`; `racing`: a database another session keeps saving."""
        self.cut_at, self.torn, self.full_from = cut_at, torn, full_from
        self.busy, self.free = busy, False
        self.racing, self.races = racing, 0
        self.steps = self.writes = 0
        self.cut = False

    def _reached(self) -> bool:
        if self.cut:
            raise Cut()
        self.steps += 1
        self.cut = self.steps == self.cut_at
        return self.cut

    def _held(self, path: str) -> None:
        if self.busy and not self.free and path.replace(os.sep, "/").endswith(self.busy):
            raise PermissionError(errno.EACCES, "%s is in use" % self.busy, path)

    def read(self, path):
        if self.racing and os.path.basename(path) == self.racing:    # the other session saves first
            self.races += 1
            document = guard._parse(super().read(path), guard.DATABASES[self.racing])[0] or {}
            raced = dict(document, assets=dict(document.get("assets") or {}, **{
                "R%d" % self.races: {"name": "the other session's save %d" % self.races}}))
            super().write(path, guard.encode(raced))
        return super().read(path)

    def write(self, path, data):
        if self._reached():
            if self.torn:
                super().write(path, data[: len(data) // 2])
            raise Cut()
        self.writes += 1
        if self.full_from and self.writes >= self.full_from:
            raise OSError(errno.ENOSPC, "No space left on device", path)
        super().write(path, data)

    def swap(self, scratch, target):
        if self._reached():
            raise Cut()
        self._held(target)
        super().swap(scratch, target)

    def move(self, source, target):
        if self._reached():
            raise Cut()
        self._held(source)
        super().move(source, target)

    def remove(self, path):
        if self._reached():
            raise Cut()
        self._held(path)
        super().remove(path)

    def remove_folder(self, path):
        if self._reached():
            raise Cut()
        super().remove_folder(path)
