"""This computer's `settings.json`: read once, merged with another pane's save, written whole."""

from __future__ import annotations

import copy
import json
import os

from amaze.core import debug
from amaze.helpers import hostos

FILENAME = "settings.json"    # machine-local: it holds the library's path and is never copied to another machine

READ, FRESH, BLIND = "read", "fresh", "blind"    # parsed; missing; present but unreadable: no writes

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


def _fold(rule: str, ours, theirs, path: tuple = ()):
    """This pane's value with the other pane's additions merged in; None when there are none."""
    if rule == COMBINE:
        if not (isinstance(ours, list) and isinstance(theirs, list)):
            return None
        extra = [value for value in theirs if value not in ours]
        return (ours + extra) if extra else None
    if rule == FIELDS:
        if not (isinstance(ours, dict) and isinstance(theirs, dict)):
            return None
        merged, changed = dict(ours), False
        for key, value in theirs.items():
            if key not in merged:
                merged[key], changed = value, True
                continue
            below = path + (str(key),)
            named = _rule(below) or (FIELDS if _deeper(below) else "")
            if named:
                folded = _fold(named, merged[key], value, below)
            elif isinstance(merged[key], dict) and isinstance(value, dict):
                missing = {f: v for f, v in value.items() if f not in merged[key]}
                folded = {**merged[key], **missing} if missing else None
            else:
                folded = None
            if folded is not None:
                merged[key], changed = folded, True
        return merged if changed else None
    return None


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
                loaded = json.loads(raw.decode("utf-8-sig"))
                if not isinstance(loaded, dict):
                    raise ValueError("settings hold %s, not a table" % type(loaded).__name__)
                self._table, self._raw, self.state = loaded, raw, READ
            except (OSError, ValueError) as exc:
                self.state = BLIND
                hostos.preserve_unreadable(self.path, why="settings")
                debug.event("prefs", "settings.json unreadable - not written this session",
                            path=self.path, error=str(exc))
        self._base = copy.deepcopy(self._table)
        return self.writable

    @property
    def writable(self) -> bool:
        return self.state in (READ, FRESH)

    def everyones(self) -> dict:
        return copy.deepcopy(self._table)

    def _theirs(self):
        """What is on disk now, when another SettingsFile saved since our read; None otherwise."""
        try:
            with open(self.path, "rb") as handle:
                raw = handle.read()
        except OSError:
            return None
        if raw == self._raw:
            return None
        try:
            loaded = json.loads(raw.decode("utf-8-sig"))
        except ValueError:
            return False
        return loaded if isinstance(loaded, dict) else False

    def _merge(self, staged: dict, theirs: dict) -> None:
        base = self._base
        for key, value in theirs.items():
            based = key in base
            moved = not based or value != base[key]
            if key not in staged:
                if moved:
                    staged[key] = value    # the other pane's addition, or its edit to a key we removed
                continue
            if staged[key] == value:
                continue
            named = _rule((key,)) or (FIELDS if _deeper((key,)) else "")
            if named:
                folded = _fold(named, staged[key], value, (key,))
                if folded is not None:
                    staged[key] = folded
                continue
            if moved and based and staged[key] == base[key]:
                staged[key] = value    # only the other pane changed it
        for key in list(staged):
            if key not in theirs and key in base and staged[key] == base[key]:
                staged.pop(key)    # the other pane deleted a key we did not change

    def replace(self, document: dict, settle=None) -> bool:
        """Write a whole document, merged with another pane's save; False when not written."""
        if not self.writable:
            return False
        staged = {str(key): value for key, value in document.items()}
        theirs = self._theirs()
        if theirs is False:
            self.state = BLIND
            hostos.preserve_unreadable(self.path, why="settings")
            return False
        if theirs is not None:
            self._merge(staged, theirs)
        if settle is not None:
            settle(staged)
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
