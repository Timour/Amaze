"""The library's shared settings, one record `{value: ...}` per key. ▸p/bare-scalar-keyed-store"""

from __future__ import annotations

from amaze.core import keyed_store

PREFS_FILE = "prefs.json"

_SCALARS = (str, int, float)  # what a stored value may hold; bool passes as int


def normalise(value) -> dict:
    """A well-formed record kept whole, or {} for junk."""
    if not isinstance(value, dict) or "value" not in value:
        return {}
    if not isinstance(value["value"], _SCALARS):
        return {}
    return dict(value)


SPEC = keyed_store.bind(PREFS_FILE, normalise)


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def value_of(preferences, key: str, default=None):
    """One shared setting, or `default` when the library has no answer."""
    record = _store(preferences).get(str(key))
    if not record:
        return default
    return record.get("value", default)


def set_value(preferences, key: str, value) -> bool:
    """Write one shared setting; True when it reached disk, TypeError for a non-scalar."""
    if not isinstance(value, _SCALARS):
        raise TypeError(
            "a shared setting is a scalar, not %s" % type(value).__name__)
    return bool(_store(preferences).set(str(key), {"value": value}))


def set_values(preferences, mapping: dict) -> bool:
    """Write many shared settings in one commit; TypeError for a non-scalar, like `set_value`."""
    records = {}
    for key, value in (mapping or {}).items():
        if not isinstance(value, _SCALARS):
            raise TypeError(
                "a shared setting is a scalar, not %s"
                % type(value).__name__)
        records[str(key)] = {"value": value}
    return bool(_store(preferences).update(records))


def takes_writes(preferences) -> bool:
    """May a write land now? When False, keep the local copy and retry another session."""
    return _store(preferences).writable


def all_values(preferences) -> dict:
    """Every shared setting, `{key: value}` - a COPY, like every store read."""
    return {key: record.get("value")
            for key, record in _store(preferences).all().items()}


def clear(preferences, keys) -> bool:
    """Reset the named settings by retiring them; absence is not a delete."""
    return bool(_store(preferences).retire(
        [str(key) for key in keys]))
