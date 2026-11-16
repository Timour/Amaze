"""Captures: a photo of the Scene View kept as a tile's picture, in the library. ▸r/tile-captures"""

import hashlib
import os

from PySide6 import QtCore

from amaze.core import debug
from amaze.helpers import hostos

FOLDER = "captures"    # <library>/captures: a File row's capture; an asset's is its one picture
FILE_PREFIX = "file_"    # a File row has no asset id, so its key is hashed into the name


def folder(preferences) -> str:
    """`<library>/captures`."""
    return os.path.join(str(preferences.dir), FOLDER)


def file_key(preferences, path: str) -> str:
    """A File row's key: its location ident, else its canonical path - the key its icon is under."""
    from amaze.core import locations
    full = hostos.canonical_path_key(str(path))
    return locations.file_ident(preferences, full) or full


def file_path(preferences, key: str) -> str:
    """`<library>/captures/file_<sha1 of the key>.png` for a File row's key."""
    digest = hashlib.sha1(str(key).encode("utf-8")).hexdigest()
    return os.path.join(folder(preferences), FILE_PREFIX + digest + ".png")


def exists(path: str) -> bool:
    """A non-empty file at `path`: a zero-byte file is no capture."""
    try:
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def move_file_capture(preferences, old_key: str, new_key: str) -> bool:
    """A moved file's capture follows its key; one already under the new key goes to the trash."""
    from amaze.core import library_db
    old, new = file_path(preferences, old_key), file_path(preferences, new_key)
    if not exists(old):
        return False
    held = library_db.guard_of(preferences)
    change = held.change(str(getattr(preferences, "library_user", "") or ""))
    if os.path.lexists(new):
        change.trash(held.inside(new))
    change.take(held.inside(new), old)
    try:
        change.commit()
    except OSError as exc:
        debug.event("capture", "a moved file's capture stays under its old key", error=str(exc))
        return False
    announce(new_key)
    return True


class _Signals(QtCore.QObject):
    """Announces a landed capture by its tile key, so every live model repaints that tile."""

    landed = QtCore.Signal(object)


_RELAY_VERSION = 1    # bumped when a signal is added, removed or changes arity

signals = globals().get("signals")    # reload-stable: a reload must not strand the old connections
if signals is None or getattr(signals, "version", None) != _RELAY_VERSION:
    signals = _Signals()
    signals.version = _RELAY_VERSION


def announce(key: str) -> None:
    """Tell every live model that the tile keyed `key` has a new capture."""
    try:
        signals.landed.emit(str(key))
    except Exception as exc:                                  # noqa: BLE001
        debug.event("capture", "could not announce a capture",
                    key=str(key), error=str(exc))


