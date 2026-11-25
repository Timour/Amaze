"""The one menu engine: a section's menu table and its selection become rows; a pick runs its row."""

from PySide6 import QtCore

from amaze.pane import asks


def resolve(context, name, indexes, current, default):
    """A named value on the section: an attribute as is, or a method called with the selection."""
    if not name:
        return default
    fact = getattr(context, name, None)
    if callable(fact):
        return bool(fact(indexes, current))
    return bool(fact)


def enabled(context, entry, indexes, current) -> bool:
    """Whether an entry is enabled; one lacking what it needs greys out and is never hidden."""
    if entry.needs == "always":
        return True
    if entry.needs == "one":
        return len(indexes) == 1
    if entry.needs == "any":
        return bool(indexes)
    return resolve(context, entry.needs, indexes, current, False)


def is_chip(icon) -> bool:
    """A child's icon that is a colour ("#rrggbb"), drawn as a chip; any other names a ui/ icon."""
    return bool(icon) and icon.startswith("#")


def tidy(rows) -> list:
    """No leading, doubled or trailing divider: a table with conditional rows makes all three."""
    out = []
    for row in rows:
        if row is None:
            if out and out[-1] is not None:
                out.append(None)
        else:
            out.append(row)
    while out and out[-1] is None:
        out.pop()
    return out


def _needs(entries, handler) -> str:
    """What the entry naming `handler` needs; its submenu rows use the same handler."""
    for entry in entries:
        if entry.handler == handler:
            return entry.needs
        if isinstance(entry.children, tuple):
            found = _needs(entry.children, handler)
            if found != "":
                return found
    return ""


class Menu:
    """One open menu: rows any host can draw, and what each row runs when it is picked."""

    def __init__(self, context, entries, indexes, current, host=None) -> None:
        self.context = context
        self.entries = entries
        self.host = host    # the window the menu opens in; a row whose window it lacks greys out
        self._indexes = [QtCore.QPersistentModelIndex(index) for index in indexes]    # a pick can follow a reset
        self._current = QtCore.QPersistentModelIndex(current) if current is not None else None
        self.runs = {}    # row key: (handler, payload)
        self.rows = self._rows(entries, indexes, current, "")

    def _rows(self, entries, indexes, current, prefix) -> list:
        """The table's rows as dicts: key, text, enabled, and separator, checked, rows, glyph or chip."""
        listed = [entry if entry.label else None for entry in entries
                  if not entry.label or resolve(self.context, entry.shown, indexes, current, True)]
        out = []
        for at, entry in enumerate(tidy(listed)):
            key = prefix + str(at)
            if entry is None:
                out.append({"key": key, "separator": True})
                continue
            text = entry.label
            if entry.count_suffix and len(indexes) > 1:
                text += " (%d)" % len(indexes)
            row = {"key": key, "text": text,
                   "enabled": enabled(self.context, entry, indexes, current) and self._answered(entry)}
            if entry.glyph:
                row["glyph"] = entry.glyph
            if isinstance(entry.children, tuple):    # a fixed submenu: each row keeps its own shown and needs
                row["rows"] = self._rows(entry.children, indexes, current, key + "/")
            elif entry.children:
                row["rows"] = self._children(entry, indexes, current, key + "/")
            elif entry.checkable:    # a toggle: the handler is handed the state the user asks for
                state = resolve(self.context, entry.checkable, indexes, current, False)
                row["checked"] = state
                self.runs[key] = (entry.handler, not state)
            else:
                self.runs[key] = (entry.handler, None)
            out.append(row)
        return out

    def _children(self, entry, indexes, current, prefix) -> list:
        """The rows a section lists for a submenu: (label, payload, icon, live[, checked]), None a divider."""
        out = []
        for at, child in enumerate(getattr(self.context, entry.children)(indexes, current)):
            key = prefix + str(at)
            if child is None:
                out.append({"key": key, "separator": True})
                continue
            label, payload, icon, live = child[:4]
            checked = child[4] if len(child) > 4 else None
            row = {"key": key, "text": label, "enabled": bool(live)}
            if is_chip(icon):
                row["chip"] = icon
            elif icon:
                row["icon"] = icon
            if checked is None:
                self.runs[key] = (entry.handler, payload)
            else:
                row["checked"] = bool(checked)
                self.runs[key] = (entry.handler, (payload, not checked))
            out.append(row)
        return out

    def _answered(self, entry) -> bool:
        """Whether the host has the window the entry opens; an entry that opens none always is."""
        return not entry.opens or self.host is None or asks.answers(self.host, entry.opens)

    def run(self, key: str) -> bool:
        """Run the picked row on the rows the menu was opened on that are still there; False if none ran."""
        handler, payload = self.runs.get(key, ("", None))
        if not handler:
            return False
        live = [QtCore.QModelIndex(index) for index in self._indexes if index.isValid()]
        if self._indexes and not live and _needs(self.entries, handler) != "always":
            return False    # every row the menu was opened on was removed while it was open
        if self._current is not None and self._current.isValid():
            current = QtCore.QModelIndex(self._current)
        else:
            current = live[0] if live else None
        getattr(self.context, handler)(live, current, payload)
        return True
