"""Captures: a photo of the Scene View kept as a tile's picture, in the library. ▸r/tile-captures"""

import hashlib
import json
import os
import shutil

from PySide6 import QtCore

from amaze.core import debug
from amaze.helpers import hostos

FOLDER = "captures"    # <library>/captures, beside img/ and mat/
FILE_PREFIX = "file_"    # a File row has no asset id, so its key is hashed into the name
LEGACY_FOLDER = "hip_thumbnails"    # where a machine kept its scene captures before 1.9
LEGACY_MANIFEST = "manifest.json"    # in that folder: scene path -> {"thumbnail": <png name>}


def folder(preferences) -> str:
    """`<library>/captures`."""
    return os.path.join(str(preferences.dir), FOLDER)


def asset_path(preferences, asset_id) -> str:
    """`<library>/captures/<id>.png`; raises hostos.PathEscape for an id leaving the folder."""
    return hostos.contained_join(folder(preferences), str(asset_id) + ".png")


def file_key(preferences, path: str) -> str:
    """A File row's key: its location ident, else its canonical path - the key icons.json uses."""
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


def adopt_machine_captures(preferences) -> int:
    """Move this machine's pre-1.9 scene captures into the library; answers how many landed."""
    from amaze.core import locations
    if not locations.ready(preferences):
        return 0    # no idents yet: a capture keyed by its path now would miss its row later
    adopted = 0
    for old in _machine_folders():
        adopted += _adopt_from(preferences, old)
    return adopted


def machine_capture_count() -> int:
    """How many of this machine's pre-1.9 scene captures wait to move into a library."""
    count = 0
    for old in _machine_folders():
        for entry in _read_json(os.path.join(old, LEGACY_MANIFEST)).values():
            name = os.path.basename(str((entry or {}).get("thumbnail") or ""))
            if name and exists(os.path.join(old, name)):
                count += 1
    return count


def _machine_folders() -> list:
    """This machine's old capture folders that exist: settings first, then the older cache one."""
    found = []
    for root in (hostos.config_root(), hostos.cache_root()):
        path = os.path.join(root, LEGACY_FOLDER)
        if os.path.isdir(path) and path not in found:
            found.append(path)
    return found


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _adopt_from(preferences, old: str) -> int:
    """Move one old folder's captures in under their new names, each original set aside."""
    manifest = os.path.join(old, LEGACY_MANIFEST)
    left = {}    # what could not be moved stays listed, for the next start
    landed = kept = 0
    for scene, entry in _read_json(manifest).items():
        name = os.path.basename(str((entry or {}).get("thumbnail") or ""))
        source = os.path.join(old, name)
        if not name or not exists(source):
            continue    # nothing on disk to move: the entry goes with the manifest
        target = file_path(preferences, file_key(preferences, scene))
        try:
            if os.path.exists(target):
                kept += 1    # the library's own wins, another machine's or newer
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with hostos.scratch_beside(target) as scratch:
                    shutil.copyfile(source, scratch)
                landed += 1
        except OSError as exc:
            left[scene] = entry
            debug.event("capture", "machine capture not moved - trying again next start",
                        scene=str(scene), error=str(exc))
            continue
        _set_aside(preferences, source)
    if left:
        try:
            hostos.write_json_atomic(manifest, left, indent=2)
        except OSError as exc:
            debug.event("capture", "old manifest not rewritten", folder=old, error=str(exc))
    else:
        _set_aside(preferences, manifest)
        try:
            os.rmdir(old)    # only when empty: a file no manifest names stays where it is
        except OSError:
            pass
    debug.event("capture", "machine captures moved into the library", folder=old,
                landed=landed, kept=kept, left=len(left),
                library=hostos.canonical_path_key(str(preferences.dir)))
    return landed


def _set_aside(preferences, path: str) -> None:
    """An old original goes to this library's holding folder, kept 30 days ▸ core/quarantine.py"""
    from amaze.core import quarantine
    if os.path.exists(path):
        quarantine.quarantine_as(str(preferences.dir), path,
                                 os.path.join(LEGACY_FOLDER, os.path.basename(path)))
