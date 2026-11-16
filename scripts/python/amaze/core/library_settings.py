"""`DataBase.json`'s own sections: the library's policy, its shared settings and its starter marks."""

from __future__ import annotations

import types

from amaze.core import documents, guard, library_db, library_files, library_policy

POLICY, SETTINGS, MARKS = "policy", "settings", "marks"
VERSION_ENTRY = "library"    # in `policy`: {"version": n}, the library's own version
OVERWRITE_ENTRY = "allow_overwrite"    # in `policy`: {"value": bool}; off makes the library append-only
DEFAULTS = {OVERWRITE_ENTRY: True}

_SCALARS = (str, int, float)    # what a shared setting may hold; bool passes as int


def _master(preferences):
    return library_db.document(preferences, library_files.MASTER)


def _folder(library_dir: str):
    return types.SimpleNamespace(dir=str(library_dir or ""), library_user="")


def version_label(version: int) -> str:
    """How a library version reads to the user: 4 is `2.0`, an older one its own number."""
    version = int(version or 0)
    if version >= library_policy.LIBRARY_VERSION:
        return "2.%d" % (version - library_policy.LIBRARY_VERSION)
    return "%d" % version


def library_version(library_dir: str) -> int:
    """The version in the policy of the library in `library_dir`; 0 for a folder that holds none."""
    if not library_dir:
        return 0
    reading = guard.Guard(str(library_dir)).read(library_files.MASTER)
    entry = ((reading.document or {}).get(POLICY) or {}).get(VERSION_ENTRY) or {}
    found = entry.get("version") if isinstance(entry, dict) else None
    return found if isinstance(found, int) and not isinstance(found, bool) and found > 0 else 0


def stamp_version(preferences) -> bool:
    """Record this Amaze's library version in the library's policy; True once it is there."""
    held = _master(preferences)
    if held.get(POLICY, VERSION_ENTRY) == {"version": library_policy.LIBRARY_VERSION}:
        return True
    return held.put(POLICY, VERSION_ENTRY, {"version": library_policy.LIBRARY_VERSION}) and \
        bool(library_db.save(preferences, library_files.MASTER))


def allow_overwrite(library_dir_or_preferences) -> bool:
    """Whether saving over an existing asset is allowed HERE; a policy that will not read says no."""
    preferences = library_dir_or_preferences
    if isinstance(preferences, str):
        if not preferences:
            return DEFAULTS[OVERWRITE_ENTRY]
        reading = guard.Guard(preferences).read(library_files.MASTER)
        if reading.verdict not in (guard.FINE, guard.FRESH):
            return False
        entry = ((reading.document or {}).get(POLICY) or {}).get(OVERWRITE_ENTRY)
    else:
        held = _master(preferences)
        if held.verdict not in (guard.FINE, guard.FRESH):
            return False
        entry = held.get(POLICY, OVERWRITE_ENTRY)
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, bool) else DEFAULTS[OVERWRITE_ENTRY]


def set_allow_overwrite(preferences, allowed: bool) -> bool:
    """Keep the setting in the LIBRARY; True when it was saved."""
    held = _master(preferences)
    if not held.writable or not held.user():
        return False
    held.put(POLICY, OVERWRITE_ENTRY, {"value": bool(allowed)})
    return bool(library_db.save(preferences, library_files.MASTER))


def value_of(preferences, key: str, default=None):
    """One shared setting, or `default` when the library has no answer."""
    entry = _master(preferences).get(SETTINGS, str(key))
    if not isinstance(entry, dict) or "value" not in entry:
        return default
    return entry["value"]


def set_values(preferences, mapping: dict) -> bool:
    """Write many shared settings as one change; TypeError for a value that is not a scalar."""
    held = _master(preferences)
    for key, value in (mapping or {}).items():
        if not isinstance(value, _SCALARS):
            raise TypeError("a shared setting is a scalar, not %s" % type(value).__name__)
    if not held.writable or not held.user():
        return False
    with library_db.library_for(preferences).holding():
        for key, value in (mapping or {}).items():
            held.put(SETTINGS, str(key), {"value": value})
    saved = library_db.save(preferences, library_files.MASTER)
    return bool(saved)


def set_value(preferences, key: str, value) -> bool:
    return set_values(preferences, {key: value})


def takes_writes(preferences) -> bool:
    """May a shared setting be kept now? When False, keep the local copy and retry later."""
    if _master(preferences).verdict != guard.FINE:
        return False    # no `DataBase.json` yet: a library's creation or conversion writes the first
    return library_db.accepts(preferences, library_files.MASTER)


def all_values(preferences) -> dict:
    """Every shared setting, `{key: value}`."""
    return {key: entry["value"] for key, entry in _master(preferences).table(SETTINGS).items()
            if isinstance(entry, dict) and "value" in entry}


def clear(preferences, keys) -> bool:
    """Reset the named settings by removing them."""
    held = _master(preferences)
    with library_db.library_for(preferences).holding():
        for key in keys:
            held.drop(SETTINGS, str(key))
    return bool(library_db.save(preferences, library_files.MASTER))


def marked(preferences, mark: str) -> bool:
    """Whether the library records `mark`: a starter offered here once."""
    return bool(_master(preferences).get(MARKS, mark))


def mark(preferences, mark: str, **facts) -> bool:
    """Record `mark` in the library, saved now; True once it is there."""
    held = _master(preferences)
    if held.get(MARKS, mark):
        return True
    if not held.put(MARKS, mark, dict(facts, offered=True)):
        return False    # a database that takes no change: not recorded, so not claimed
    saved = library_db.save(preferences, library_files.MASTER)
    return bool(saved) or saved.reason == documents.UNCHANGED
