"""The library's SHARED settings: one record per preference key.

One answer for everyone who opens the library (ROADMAP line 22).
Nothing reads this store until that line's flip commits. A value is
a record, never a bare scalar - the practice wiki carries why, under
A BARE SCALAR IN A KEYED STORE READS AS A DELETE.
"""

from __future__ import annotations

from amaze.core import keyed_store

PREFS_FILE = "prefs.json"

#: What a stored value may hold - bool passes as int, and
#: dict/list/None are refused at the door.
_SCALARS = (str, int, float)


def normalise(value) -> dict:
    """A well-formed record, kept whole, or {} for junk - an
    unreadable record answers {} and the engine holds it aside as
    foreign."""
    if not isinstance(value, dict) or "value" not in value:
        return {}
    if not isinstance(value["value"], _SCALARS):
        return {}
    return dict(value)


SPEC = keyed_store.bind(PREFS_FILE, normalise)


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def value_of(preferences, key: str, default=None):
    """One shared setting, or `default` when the library has no
    answer - absent, latched and unreachable all degrade to it."""
    record = _store(preferences).get(str(key))
    if not record:
        return default
    return record.get("value", default)


def set_value(preferences, key: str, value) -> bool:
    """Write one shared setting - True when it reached disk. A
    non-scalar raises rather than reading back absent later."""
    if not isinstance(value, _SCALARS):
        raise TypeError(
            "a shared setting is a scalar, not %s" % type(value).__name__)
    return bool(_store(preferences).set(str(key), {"value": value}))


def all_values(preferences) -> dict:
    """Every shared setting, `{key: value}` - a COPY, like every
    store read."""
    return {key: record.get("value")
            for key, record in _store(preferences).all().items()}


def clear(preferences, keys) -> bool:
    """Reset the named settings out loud - a retire, because absence
    is not a delete anywhere in this engine."""
    return bool(_store(preferences).retire(
        [str(key) for key in keys]))


def forget() -> None:
    """Drop the cache - a library switch or a test needs a re-read."""
    keyed_store.release()
