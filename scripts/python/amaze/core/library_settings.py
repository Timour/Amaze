"""`DataBase.json`'s own sections: the library's policy, its shared settings and its starter marks."""

from __future__ import annotations

import types

from amaze.core import documents, guard, library_db, library_files, library_policy

POLICY, SETTINGS, MARKS = "policy", "settings", "marks"
VERSION_ENTRY = "library"    # in `policy`: {"version": n}, the library's own version
OVERWRITE_ENTRY = "allow_overwrite"    # in `policy`: {"value": bool}; Preferences > Versions, on or off
DEFAULTS = {OVERWRITE_ENTRY: True}

_SCALARS = (str, int, float)    # what a shared setting may hold; bool passes as int


def _master(preferences):
    return library_db.document(preferences, library_files.MASTER)


def _folder(library_dir: str):
    return types.SimpleNamespace(dir=str(library_dir or ""), library_user="")


THIS_AMAZE = (library_policy.LIBRARY_VERSION, library_policy.DATABASE_FORMAT,
              library_policy.RECORD_FORMAT)    # the three numbers this Amaze writes
_STAMPED = ("version", "database", "record")    # their fields in the policy's `library` entry


def version_label(version, database: int = 0, record: int = 0) -> str:
    """The format shown to the user, from a library version or the three numbers together."""
    if isinstance(version, (tuple, list)):
        version, database, record = version
    return library_policy.format_label(version, database, record)


def library_formats(library_dir: str) -> tuple:
    """(library version, database format, record format) the library's policy records; zeros for none."""
    if not library_dir:
        return 0, 0, 0
    reading = guard.Guard(str(library_dir)).read(library_files.MASTER)
    entry = ((reading.document or {}).get(POLICY) or {}).get(VERSION_ENTRY) or {}
    found = [entry.get(field) if isinstance(entry, dict) else None for field in _STAMPED]
    found = [one if isinstance(one, int) and not isinstance(one, bool) and one > 0 else 0
             for one in found]
    if not found[0]:
        return 0, 0, 0
    return tuple(one or base for one, base in zip(found, library_policy.FORMAT_3_0))


def library_version(library_dir: str) -> int:
    """The version in the policy of the library in `library_dir`; 0 for a folder that holds none."""
    return library_formats(library_dir)[0]


def stamp_version(preferences) -> bool:
    """Record this Amaze's three format numbers in the library's policy; True once they are there."""
    held = _master(preferences)
    wanted = dict(zip(_STAMPED, THIS_AMAZE))
    entry = held.get(POLICY, VERSION_ENTRY) or {}
    if {field: entry.get(field) for field in _STAMPED} == wanted:
        return True
    return held.put(POLICY, VERSION_ENTRY, wanted) and \
        bool(library_db.save(preferences, library_files.MASTER))


def policy_readable(preferences) -> bool:
    """Whether the library's policy can be read; nothing is saved over an asset without it."""
    return _master(preferences).verdict in (guard.FINE, guard.FRESH)


def allow_overwrite(library_dir_or_preferences) -> bool:
    """Whether saving over a material keeps a version (Enable Asset Versions); False if unreadable."""
    preferences = library_dir_or_preferences
    if isinstance(preferences, str):
        if not preferences:
            return DEFAULTS[OVERWRITE_ENTRY]
        reading = guard.Guard(preferences).read(library_files.MASTER)
        if reading.verdict not in (guard.FINE, guard.FRESH):
            return False
        entry = ((reading.document or {}).get(POLICY) or {}).get(OVERWRITE_ENTRY)
    else:
        if not policy_readable(preferences):
            return False
        entry = _master(preferences).get(POLICY, OVERWRITE_ENTRY)
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, bool) else DEFAULTS[OVERWRITE_ENTRY]


def set_allow_overwrite(preferences, allowed: bool) -> bool:
    """Save the overwrite setting in the library's policy; True when it was saved."""
    held = _master(preferences)
    if not held.writable or not held.user():
        return False
    held.put(POLICY, OVERWRITE_ENTRY, {"value": bool(allowed)})
    return bool(library_db.save(preferences, library_files.MASTER))


def value_of(preferences, key: str, default=None):
    """One shared setting, or `default` when the library has no value for it."""
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
    """Can a shared setting be saved now? When False, keep the local copy and retry later."""
    if _master(preferences).verdict != guard.FINE:
        return False    # no `DataBase.json` yet: creating a library writes the first one
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
    """Whether the library records `mark`, set once a starter was offered in this library."""
    return bool(_master(preferences).get(MARKS, mark))


def mark(preferences, mark: str, **facts) -> bool:
    """Record `mark` in the library, saved now; True once it is there."""
    held = _master(preferences)
    if held.get(MARKS, mark):
        return True
    if not held.put(MARKS, mark, dict(facts, offered=True)):
        return False    # the database refused the change: nothing recorded, so return False
    saved = library_db.save(preferences, library_files.MASTER)
    return bool(saved) or saved.reason == documents.UNCHANGED
