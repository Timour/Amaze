"""This computer's `settings.json`: read once, merged with another pane's save, written whole."""

from __future__ import annotations

import copy
import json
import os

from amaze.core import debug
from amaze.helpers import hostos

FILENAME = "settings.json"    # machine-local: it holds the library's path and is never copied to another machine

READ, FRESH, UNREADABLE = "read", "fresh", "blind"    # parsed; missing; present but unreadable: no writes
LAYOUT = {  # the top-level keys and the type each must have; another type makes the file unreadable
    "directory": str, "libraries": list, "shared_settings": dict, "library_user": str,
    "cache_dir": str, "users": dict,
}

_GONE = object()    # a key a document does not hold
COMBINE, FIELDS = "combine", "fields"    # a list: this pane's, then the other's; a table: field by field
RULES = {    # merge of another pane's save per key; a key with no rule keeps ours if both changed it
    "users/*/file_folders": COMBINE,
    "users/*/file_favorites": COMBINE,
    "users/*/file_location_records": FIELDS,
    "users": FIELDS,
}


def _rule(path: tuple) -> str:
    """The rule for a key path, the most specific first; "" for none."""
    best, fewest = "", None
    for pattern, rule in RULES.items():
        parts = pattern.split("/")
        if len(parts) == len(path) and all(part in ("*", actual)
                                           for part, actual in zip(parts, path)):
            stars = parts.count("*")
            if fewest is None or stars < fewest:
                best, fewest = rule, stars
    return best


def _deeper(path: tuple) -> bool:
    """Whether a rule names something below this key path."""
    return any(len(parts) > len(path) and all(part in ("*", actual)
                                              for part, actual in zip(parts, path))
               for parts in (pattern.split("/") for pattern in RULES))


def _merged(ours, theirs, base, read, path: tuple = ()):
    """The file's value, or ours where this pane changed it since `base`; changed in both: the rule."""
    if ours == base or ours == theirs:
        return theirs    # not changed here: the file keeps its value, spelled as it is there
    rule = _rule(path) or (FIELDS if _deeper(path) else "")
    if rule == FIELDS and isinstance(ours, dict) and isinstance(theirs, dict):
        base, read = (table if isinstance(table, dict) else {} for table in (base, read))
        out = {}
        for key in list(ours) + [key for key in theirs if key not in ours]:
            value = _merged(*(table.get(key, _GONE) for table in (ours, theirs, base, read)),
                            path + (str(key),))
            if value is not _GONE:
                out[key] = value
        return out
    if theirs == read or theirs is _GONE:
        return ours    # no other save changed it since this pane read or wrote the file
    if ours is _GONE:
        return theirs    # the other save's edit is kept over our removal
    if rule == COMBINE and isinstance(ours, list) and isinstance(theirs, list):
        return ours + [value for value in theirs if value not in ours]
    return ours    # both changed it: ours is kept


def _document(raw: bytes) -> dict:
    """The settings document in `raw`; ValueError when it is not in the layout this Amaze reads."""
    loaded = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError("settings hold %s, not a table" % type(loaded).__name__)
    wrong = sorted(key for key, kind in LAYOUT.items()
                   if key in loaded and not isinstance(loaded[key], kind))
    if wrong:    # a newer Amaze's layout: a save would replace these keys with defaults
        raise ValueError("settings hold %s of another type" % ", ".join(wrong))
    return loaded


class _NotRead(OSError):
    """settings.json is there but could not be read now."""


class SettingsFile:
    """One Prefs object's copy of `settings.json`, with the base its next save merges against."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.reread()

    def reread(self) -> bool:
        """Read the file again; whether it can be written."""
        self._table, self._raw, self.state = {}, None, FRESH
        if os.path.exists(self.path):
            try:
                with open(self.path, "rb") as handle:
                    raw = handle.read()
                self._table, self._raw, self.state = _document(raw), raw, READ
            except (OSError, ValueError) as exc:
                self.state = UNREADABLE
                hostos.preserve_unreadable(self.path, why="settings")
                debug.event("prefs", "settings.json unreadable - not written this session",
                            path=self.path, error=str(exc))
        self._base = copy.deepcopy(self._table)
        return self.writable

    @property
    def writable(self) -> bool:
        return self.state in (READ, FRESH)

    def whole_document(self) -> dict:
        return copy.deepcopy(self._table)

    def compare_with(self, document: dict) -> None:
        """`document` is what its Prefs writes with nothing changed: the base of the next save's merge."""
        self._base = copy.deepcopy({str(key): value for key, value in document.items()})

    def _on_disk(self):
        """The file's document now, another save's or our last one: None for no file, False if unreadable."""
        try:
            with open(self.path, "rb") as handle:
                raw = handle.read()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _NotRead(exc) from exc    # held a moment: a write now drops its changes
        if raw == self._raw:
            return copy.deepcopy(self._table)
        try:
            return _document(raw)
        except ValueError:
            return False

    def _merge(self, staged: dict, theirs: dict) -> None:
        merged = _merged(dict(staged), theirs, self._base, self._table)
        staged.clear()
        staged.update(merged)

    def replace(self, document: dict, before_write=None) -> bool:
        """Write a whole document, merged with another pane's or session's save; False if not."""
        if not self.writable:
            return False
        with hostos.file_lock(self.path):    # another Houdini's save waits, or it would not be merged
            return self._replace_locked(document, before_write)

    def _replace_locked(self, document: dict, before_write) -> bool:
        staged = {str(key): value for key, value in document.items()}
        try:
            theirs = self._on_disk()    # merged every time: a save writes this pane's changes onto the file as it is
        except _NotRead as exc:
            debug.event("prefs", "settings.json not saved - it could not be read to merge",
                        path=self.path, error=str(exc))
            return False    # the next save tries again
        if theirs is False:
            self.state = UNREADABLE
            hostos.preserve_unreadable(self.path, why="settings")
            return False
        if theirs is not None:
            self._merge(staged, theirs)
        if before_write is not None:
            before_write(staged)
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            raw = (json.dumps(staged, indent=1, sort_keys=True) + "\n").encode("utf-8")
            hostos.write_json_atomic(self.path, staged, indent=1, serialised=raw)
        except (OSError, TypeError, ValueError) as exc:
            cause, why = hostos.why_failed(exc, self.path) if isinstance(exc, OSError) \
                else ("unknown", str(exc))
            debug.event("prefs", "could not save settings.json", path=self.path,
                        error=str(exc), cause=cause)
            return False
        self._table, self._raw, self.state = staged, raw, READ
        self._base = copy.deepcopy(staged)
        return True
