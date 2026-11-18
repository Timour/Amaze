"""The Category Model behind the panel's sidebar."""

from typing import Any
from PySide6 import QtCore

from amaze.prefs import prefs
from amaze.core import documents, library_db, library_files, material, renderers

SIDEBAR_COUNT_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 40  # the ONLY declaration - every sidebar model and SidebarItemDelegate import it from here
SIDEBAR_COLOR_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 41  # a category's colour, for the sidebar's left-edge bar

ALL = "_All"    # the first row: a view of every asset, never stored
SECTION = "categories"    # {name: {"order": n, "color": c}} in the section's database


def display_name(stored) -> str:
    """How a STORED category name reads to the user: a leading underscore is not shown."""
    text = str(stored)
    return text[1:] if text.startswith("_") else text


def is_all(name) -> bool:
    """Whether `name` is the All row, stored `_All` or shown `All`: a view, never a category."""
    return name in ("All", "_All")


def stored_order(held) -> list:
    """The category names a database holds, in their order, All first."""
    table = held.table(SECTION)
    names = sorted((name for name in table if not is_all(name)),
                   key=lambda name: ((table[name] or {}).get("order", 1 << 30), name))
    return [ALL] + names


class Categories(QtCore.QAbstractListModel):
    """The category list for one library, backed by DB_FILENAME."""

    DB_FILENAME = library_files.MATERIALS  # subclassed by each section over its own database

    def __init__(self, preferences: prefs.Prefs) -> None:
        super().__init__()
        self.preferences = preferences  # required, never defaulted ▸p/delete-both-duplicates
        self._categories = stored_order(self._doc())
        self._seen = list(self._categories)    # the database's order as last read or saved
        self._colour_table = self._read_colours()
        self._removed = set()    # names this model took out, dropped from the database at its save
        self._shown = list(self._categories)    # the rows the views last showed; `apply_refresh` compares
        self.CatSortRole = QtCore.Qt.ItemDataRole.UserRole  # 256
        self._renderer_filter = ""  # lowercased; empty = no filter. Set by the panel so counts match the grid
        self._count_cache = None  # category -> visible count, `_All` = total; cleared on every change
        self.layoutChanged.connect(self.drop_count_cache)

    def rowCount(
        self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex | None = None
    ) -> int:
        return len(self._categories)

    def data(
        self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex, role: int = 0
    ) -> Any:
        if role == self.CatSortRole:
            return self._categories[index.row()]

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return display_name(self._categories[index.row()])

        if role == SIDEBAR_COUNT_ROLE:
            return self._category_count(self._categories[index.row()])

        if role == SIDEBAR_COLOR_ROLE:
            return self.color_of(self._categories[index.row()])

    def set_renderer_filter(self, render_filter: str) -> None:
        """Store the grid's renderer filter, the value MultiFilterProxyModel gets (`all_renderers`)."""
        self._renderer_filter = str(render_filter or "").lower()
        self.drop_count_cache()

    def drop_count_cache(self, *args) -> None:
        """Invalidate the one-pass count map (also a layoutChanged slot, hence the ignored args)."""
        self._count_cache = None

    def _asset_matches_renderer(self, asset: dict) -> bool:
        """Whether an asset passes the renderer filter; must match MultiFilterProxyModel exactly."""
        rf = self._renderer_filter
        if not rf:
            return True
        renderer = renderers.normalized(asset.get("renderer", "")).lower()
        if rf in renderer:
            return True
        return "all_renderers" in rf  # All passes EVERY row, an empty renderer included

    def showing_all_renderers(self) -> bool:
        """True when the Renderer filter is All or unset; empty categories then stay visible."""
        rf = self._renderer_filter
        return (not rf) or ("all_renderers" in rf)

    def _category_count(self, raw_name: str) -> int:
        """How many visible assets are in this category; `_All` counts every visible asset."""
        counts = self._count_cache
        if counts is None:
            counts = {}
            total = 0
            for asset in self._doc().table("assets").values():
                if not isinstance(asset, dict):    # skips rows that are not tables, as the model does
                    continue
                if not self._asset_matches_renderer(asset):
                    continue
                total += 1
                cats = asset.get("categories", [])
                if isinstance(cats, str):
                    cats = [cats]    # one name, its commas included
                seen = set()
                for cat in cats:
                    if isinstance(cat, str):
                        cleaned = cat.strip()
                        if cleaned and cleaned not in seen:
                            seen.add(cleaned)
                            counts[cleaned] = counts.get(cleaned, 0) + 1
            counts["_All"] = total
            self._count_cache = counts
        if raw_name == "_All":
            return counts.get("_All", 0)
        return counts.get(raw_name.strip(), 0)

    def _doc(self) -> documents.Document:
        """This sidebar's database, as library_db holds it in memory."""
        return library_db.document(self.preferences, self.DB_FILENAME)

    def _read_colours(self) -> dict:
        return {name: str(entry.get("color")) for name, entry in self._doc().table(SECTION).items()
                if isinstance(entry, dict) and entry.get("color")}

    def switch_model_data(self):
        # Same whole-row-set replacement as MaterialLibrary.switch_model_data.
        self.beginResetModel()
        try:
            self._categories = stored_order(self._doc())
            self._seen = list(self._categories)
            self._colour_table = self._read_colours()
            self._removed = set()
            self._shown = list(self._categories)    # the model reset has already updated the views
            self.drop_count_cache()
        finally:
            self.endResetModel()

    def apply_refresh(self) -> bool:
        """Read in the names and colours the database holds now; True when the sidebar changed."""
        colours = self._read_colours()
        recoloured = colours != self._colour_table
        self._colour_table = colours
        stored = stored_order(self._doc())
        moved, self._seen = stored != self._seen, stored    # a local edit not yet saved is kept
        names = [name for name in stored if name not in self._removed]
        self.drop_count_cache()
        if not moved or names == list(self._categories):
            if recoloured and self._categories:
                self.dataChanged.emit(
                    self.index(0, 0), self.index(len(self._categories) - 1, 0),
                    [SIDEBAR_COLOR_ROLE])
            return recoloured
        self.beginResetModel()
        try:
            self._categories[:] = names
            self._mark_rows_shown()
        finally:
            self.endResetModel()
        return True

    def _mark_rows_shown(self) -> None:
        """Record that the views show these rows: every local change calls this, so only a merge resets."""
        self._shown = list(self._categories)

    def remove_category(self, cat: str) -> None:
        """Remove a category from the library and from every asset; a no-op for a name that is not present."""
        if cat not in self._categories:
            return  # the sidebar strips a leading underscore, so a displayed name may not be a stored one
        row = self._categories.index(cat)
        self.beginRemoveRows(QtCore.QModelIndex(), row, row)
        try:
            self._categories.pop(row)
        finally:
            self.endRemoveRows()
        self._removed.add(cat)
        self._mark_rows_shown()
        self._recolor(cat, "")
        self.save()

    def rename_category(self, old: str, new: str) -> None:
        """Rename a category here and in every asset; renaming onto an existing name merges the two."""
        merging = new != old and new in self._categories
        for count in reversed(range(len(self._categories))):
            if self._categories[count] != old:
                continue
            if merging:
                self.beginRemoveRows(QtCore.QModelIndex(), count, count)
                try:
                    del self._categories[count]
                finally:
                    self.endRemoveRows()
            else:
                self._categories[count] = new
                index = self.index(count, 0)
                self.dataChanged.emit(index, index)
        if new != old:
            self._removed.add(old)
            self._removed.discard(new)
        self._mark_rows_shown()
        self._recolor(old, new)
        self.save()

    def normalize_categories(self) -> int:
        """Strip whitespace and drop duplicate or empty entries; returns how many changed."""
        cleaned = []
        changed = 0
        for c in self._categories:
            c2 = c.strip() if isinstance(c, str) else ""
            if c2 == "" or c2 in cleaned:
                changed += 1
                continue
            if c2 != c:
                changed += 1
            cleaned.append(c2)
        if changed:
            self._removed.update(name for name in self._categories
                                 if isinstance(name, str) and name not in cleaned)
            self.beginResetModel()  # a whole-row-set replacement needs a reset pair ▸r/model-contracts
            try:
                self._categories[:] = cleaned
            finally:
                self.endResetModel()
            self._mark_rows_shown()
            self.save()
        return changed

    def move_category(self, from_row: int, to_row: int) -> bool:
        """Move one category below `_All` to another row; the caller saves. ▸r/press-gestures"""
        count = len(self._categories)
        if not (1 <= from_row < count and 1 <= to_row < count):
            return False
        if from_row == to_row:
            return False
        destination = to_row if to_row < from_row else to_row + 1  # beginMoveRows takes PRE-move row numbers ▸r/press-gestures
        if not self.beginMoveRows(QtCore.QModelIndex(), from_row,
                                  from_row, QtCore.QModelIndex(),
                                  destination):
            return False
        try:
            self._categories.insert(to_row, self._categories.pop(from_row))  # IN PLACE, never a rebuild
        finally:
            self.endMoveRows()
        self._mark_rows_shown()
        return True

    def sort_categories(self) -> None:
        """Sort everything below `_All` by label and save; it resets the model, so restore a selection."""
        head = [c for c in self._categories if c == "_All"]
        rest = sorted((c for c in self._categories if c != "_All"),
                      key=lambda c: display_name(c).lower())    # by the label: `_WIP` sorts as WIP
        ordered = head + rest
        if ordered == self._categories:
            return
        self.restore_order(ordered)
        self.save()

    def order_snapshot(self) -> list:
        """The current order, copied - what Esc restores."""
        return list(self._categories)

    def restore_order(self, snapshot: list) -> None:
        """Put a snapshot's order back, in place, under a reset pair. ▸r/model-contracts"""
        if list(snapshot) == self._categories:
            return
        self.beginResetModel()
        try:
            self._categories[:] = list(snapshot)
        finally:
            self.endResetModel()
        self._mark_rows_shown()

    def _recolor(self, old_name: str, new_name: str) -> None:
        """Keep a colour through a rename, or drop it on a removal (empty new_name)."""
        table = self.colors()
        color = table.pop(str(old_name), "")
        if color and new_name:
            table.setdefault(str(new_name), color)    # a merge keeps the colour of the row that remains

    def stored_name(self, typed: str) -> str:
        """The stored category a TYPED name means: itself, or the one shown as it (`_WIP` shows as WIP)."""
        typed = str(typed or "").strip()
        if typed in self._categories:
            return typed
        label = display_name(typed)
        return next((name for name in self._categories
                     if isinstance(name, str) and display_name(name) == label), typed)

    def check_add_category(self, cat: str) -> None:
        """Add this category if it does not exist yet - one name, its commas included."""
        if material.MULTIPLE_VALUES in cat:
            return
        cat = cat.strip()
        if cat == "" or cat in self._categories:
            return
        row = len(self._categories)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        try:
            self._categories.append(cat)
        finally:
            self.endInsertRows()
        self._removed.discard(cat)
        self._mark_rows_shown()
        self.save()

    def colors(self) -> dict:
        """{category name: colour} for this library, kept with the names in its database."""
        return self._colour_table

    def color_of(self, cat: str) -> str:
        return str(self.colors().get(str(cat), "") or "")

    def set_color(self, cat: str, color: str) -> None:
        """Colour one category, or clear it with an empty colour."""
        table = self.colors()
        cat = str(cat)
        if color:
            table[cat] = str(color)
        else:
            table.pop(cat, None)
        self.save()
        row = self._row_of(cat)
        if row is not None:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index)

    def _row_of(self, cat: str):
        for row, name in enumerate(self._categories):
            if name == cat:
                return row
        return None

    def save(self) -> bool:
        """Write the names, order and colours to the database; False when it accepts no change now."""
        if not library_db.accepts(self.preferences, self.DB_FILENAME):
            return False
        held = self._doc()
        with library_db.library_for(self.preferences).holding():
            order = 0
            for name in self._categories:
                if is_all(name) or not isinstance(name, str):
                    continue
                entry = {"order": order}
                if self._colour_table.get(name):
                    entry["color"] = self._colour_table[name]
                held.put(SECTION, name, entry)
                order += 1
            for name in self._removed:
                if name not in self._categories:
                    held.drop(SECTION, name)
            self._removed = set()
        self._seen = stored_order(held)
        self.drop_count_cache()
        library_db.changed(self.preferences, self.DB_FILENAME)
        return True


class CategoriesSidebarProxy(QtCore.QSortFilterProxyModel):
    """Sidebar proxy: stored order, empty categories hidden; never sort() it. ▸r/press-gestures"""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.hide_empty = True

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex,
    ) -> bool:
        if not self.hide_empty:
            return True
        model = self.sourceModel()
        if model is None:
            return True
        if model.showing_all_renderers():  # All shows every category, empty ones included
            return True
        raw = model.index(source_row, 0).data(model.CatSortRole)
        if is_all(raw):
            return True
        return model._category_count(raw) > 0
