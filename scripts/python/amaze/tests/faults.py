"""The one fault simulator: a real disk that crashes at a step, runs full, holds a file or races."""

import builtins
import contextlib
import errno
import os
from unittest import mock

from amaze.core import guard


class Cut(Exception):
    """The simulated crash: the disk stopped at the chosen step."""


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


class _CutFile:
    """A file opened for writing whose `write` is one step of a `CutWrites`."""

    def __init__(self, handle, fault: "CutWrites") -> None:
        self._handle, self._fault = handle, fault

    def write(self, data):
        if self._fault._reached():
            if self._fault.torn:
                self._handle.write(data[: len(data) // 2])
                self._handle.flush()
            raise Cut()
        return self._handle.write(data)

    def __getattr__(self, name):
        return getattr(self._handle, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self._handle.close()


class CutWrites:
    """Each write or rename of a file under `folder` crashes at step `cut_at`; `torn`: mid-write."""

    def __init__(self, folder: str, cut_at: int = 0, torn: bool = False) -> None:
        self.folder = os.path.realpath(folder) + os.sep
        self.cut_at, self.torn = cut_at, torn
        self.steps = 0
        self.cut = False

    def _reached(self) -> bool:
        if self.cut:
            raise Cut()
        self.steps += 1
        self.cut = self.steps == self.cut_at
        return self.cut

    def _inside(self, path) -> bool:
        return (isinstance(path, (str, os.PathLike))
                and os.path.realpath(path).startswith(self.folder))

    def __enter__(self) -> "CutWrites":
        real_open, real_replace = builtins.open, os.replace

        def opened(name, mode="r", *args, **kwargs):
            handle = real_open(name, mode, *args, **kwargs)
            writing = any(letter in mode for letter in "wax+")
            return _CutFile(handle, self) if writing and self._inside(name) else handle

        def replaced(source, target, *args, **kwargs):
            if self._inside(target) and self._reached():
                raise Cut()
            return real_replace(source, target, *args, **kwargs)

        self._patches = contextlib.ExitStack()
        self._patches.enter_context(mock.patch("builtins.open", opened))
        self._patches.enter_context(mock.patch("os.replace", replaced))
        return self

    def __exit__(self, *exc) -> bool:
        self._patches.close()
        return exc[0] is Cut
