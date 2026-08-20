"""The library's SHARED settings, one record per preference key - one answer for everyone who opens the library; `prefs/persistence.py` is the one product consumer, adopting these into `Prefs` when a session meets a library and pushing them back in one batch write from save; a value is a record, never a bare scalar (practice.md ▸ A BARE SCALAR IN A KEYED STORE READS AS A DELETE)."""

from __future__ import annotations

from amaze.core import keyed_store

PREFS_FILE = "prefs.json"

_SCALARS = (str, int, float)  # what a stored value may hold - bool passes as int; dict/list/None are refused at the door


def normalise(value) -> dict:
    """A well-formed record kept whole, or {} for junk - an unreadable record answers {} and the engine holds it aside as foreign."""
    if not isinstance(value, dict) or "value" not in value:
        return {}
    if not isinstance(value["value"], _SCALARS):
        return {}
    return dict(value)


SPEC = keyed_store.bind(PREFS_FILE, normalise)


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def value_of(preferences, key: str, default=None):
    """One shared setting, or `default` when the library has no answer (absent, latched and unreachable all degrade to it) - the tests' single-key read: the product adopts in batch through `all_values`, and this stays as the granular half beside it."""
    record = _store(preferences).get(str(key))
    if not record:
        return default
    return record.get("value", default)


def set_value(preferences, key: str, value) -> bool:
    """Write one shared setting - True when it reached disk; a non-scalar raises rather than reading back absent later."""
    if not isinstance(value, _SCALARS):
        raise TypeError(
            "a shared setting is a scalar, not %s" % type(value).__name__)
    return bool(_store(preferences).set(str(key), {"value": value}))


def set_values(preferences, mapping: dict) -> bool:
    """Write many shared settings in ONE commit - the save-path push and the flat-file migration need the set to land together, and per-key writes would rotate the restore tier once per key and could stop halfway; a non-scalar raises like `set_value`, because the normaliser would junk it and the write would report success for a value that reads back absent."""
    records = {}
    for key, value in (mapping or {}).items():
        if not isinstance(value, _SCALARS):
            raise TypeError(
                "a shared setting is a scalar, not %s"
                % type(value).__name__)
        records[str(key)] = {"value": value}
    return bool(_store(preferences).update(records))


def takes_writes(preferences) -> bool:
    """May a write land right now? False while the store is latched on damage or refused on an absence trace - the caller keeps its local copy and retries another session."""
    return _store(preferences).writable


def all_values(preferences) -> dict:
    """Every shared setting, `{key: value}` - a COPY, like every store read."""
    return {key: record.get("value")
            for key, record in _store(preferences).all().items()}


def clear(preferences, keys) -> bool:
    """Reset the named settings out loud - a retire, because absence is not a delete anywhere in this engine."""
    return bool(_store(preferences).retire(
        [str(key) for key in keys]))


def forget() -> None:
    """Drop the cache - a test seam like its keyed-store siblings; the product's library switch drops every table through `keyed_store.release()` at the switch door."""
    keyed_store.release()
