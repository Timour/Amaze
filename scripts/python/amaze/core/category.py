"""The Category Model behind the panel's sidebar."""

from typing import Any
from PySide6 import QtCore

from amaze.prefs import prefs
from amaze.core import database, debug, material

SIDEBAR_COUNT_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 40  # the ONLY declaration - every sidebar model and SidebarItemDelegate import it from here
SIDEBAR_COLOR_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 41  # a category's colour, for the sidebar's left-edge bar


class Categories(QtCore.QAbstractListModel):
    """The category list for one library, backed by DB_FILENAME."""

    DB_FILENAME = "library.json"  # subclassed by the COP section over its own cops.json

    def __init__(self, preferences: prefs.Prefs) -> None:
        super().__init__()
        self.preferences = preferences  # REQUIRED: a model that can default binds to whatever library the machine's settings name ▸p/duplication-third-verb
        db = database.DatabaseConnector(self.DB_FILENAME)
        self._data = database.load_survivable(db, self.preferences.dir)  # survivable: a sidecar that will not read must not take the panel down from here
        self._categories = self._data["categories"]
        self.CatSortRole = QtCore.Qt.ItemDataRole.UserRole  # 256
        self._renderer_filter = ""  # lowercased; "" = no filter. Pushed in by the panel so counts agree with the grid
        self._count_cache = None  # category -> visible count, "_All" = total; dropped on every mutation path
        self.layoutChanged.connect(self.drop_count_cache)

    def rowCount(
        self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex | None = None
    ) -> int:
        return len(self._categories)

    def reload(self):
        db = database.DatabaseConnector(self.DB_FILENAME)
        self._data = db.load(self.preferences.dir)
        self._categories = self._data["categories"]
        self.drop_count_cache()

    def data(
        self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex, role: int = 0
    ) -> Any:
        if role == self.CatSortRole:
            return self._categories[index.row()]

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            elem = self._categories[index.row()]
            if elem.startswith("_"):
                elem = elem[1:]
            return elem

        if role == SIDEBAR_COUNT_ROLE:
            return self._category_count(self._categories[index.row()])

        if role == SIDEBAR_COLOR_ROLE:
            return self.color_of(self._categories[index.row()])

    def set_renderer_filter(self, render_filter: str) -> None:
        """Store the grid's active renderer filter; pass the exact value the panel feeds MultiFilterProxyModel ("all_renderers" for All)."""
        self._renderer_filter = str(render_filter or "").lower()
        self.drop_count_cache()

    def drop_count_cache(self, *args) -> None:
        """Invalidate the one-pass count map (also a layoutChanged slot, hence the ignored args)."""
        self._count_cache = None

    def _asset_matches_renderer(self, asset: dict) -> bool:
        """Whether an asset is visible under the active renderer filter - MUST mirror MultiFilterProxyModel's RendererRole matching exactly, or sidebar and grid disagree."""
        rf = self._renderer_filter
        if not rf:
            return True
        renderer = material.normalized_renderer(asset.get("renderer", "")).lower()
        if rf in renderer:
            return True
        return "all_renderers" in rf  # All passes EVERY row, an empty renderer included

    def showing_all_renderers(self) -> bool:
        """True when the Renderer filter is All (or unset) - the view where empty categories stay visible so they can be deleted."""
        rf = self._renderer_filter
        return (not rf) or ("all_renderers" in rf)

    def _category_count(self, raw_name: str) -> int:
        """How many VISIBLE assets live in this category ("_All" = every visible asset), served from a lazily rebuilt one-pass map."""
        counts = self._count_cache
        if counts is None:
            counts = {}
            total = 0
            for asset in self._data.get("assets", []):
                if not self._asset_matches_renderer(asset):
                    continue
                total += 1
                cats = asset.get("categories", [])
                if isinstance(cats, str):
                    cats = cats.split(",")
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

    def switch_model_data(self):
        # Same whole-row-set replacement as MaterialLibrary.switch_model_data.
        self.beginResetModel()
        try:
            self.preferences.load()
            db = database.DatabaseConnector(self.DB_FILENAME)
            data = db.reload_with_path(self.preferences.dir)
            self._data = data  # the whole dict: counts and empty-category hiding read _data["assets"]
            self._categories = data["categories"]
            self.drop_count_cache()
        finally:
            self.endResetModel()

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
        self._recolor(cat, "")
        self.save()

    def rename_category(self, old: str, new: str) -> None:
        """Rename a category in the library and in every asset."""
        for count, current in enumerate(self._categories):
            if current == old:
                self._categories[count] = new
        self._recolor(old, new)
        self.save()

    def normalize_categories(self) -> int:
        """Strip whitespace and drop duplicate/empty entries (legacy data cleanup); returns the changed entry count."""
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
            self.beginResetModel()  # a whole-row-set replacement outside a reset pair reads out of range natively ▸r/model-contracts
            try:
                self._categories[:] = cleaned  # IN PLACE: this list aliases the connector's document; a rebind detaches it
            finally:
                self.endResetModel()
            self.save()
        return changed

    def move_category(self, from_row: int, to_row: int) -> bool:
        """Move one category to another row - the manual order. Row 0 is `_All`, which neither moves nor accepts a row above it; deliberately NO save, the caller commits on release. ▸r/press-gestures"""
        count = len(self._categories)
        if not (1 <= from_row < count and 1 <= to_row < count):
            return False
        if from_row == to_row:
            return False
        destination = to_row if to_row < from_row else to_row + 1  # beginMoveRows speaks PRE-move coordinates ▸r/press-gestures
        if not self.beginMoveRows(QtCore.QModelIndex(), from_row,
                                  from_row, QtCore.QModelIndex(),
                                  destination):
            return False
        try:
            self._categories.insert(to_row, self._categories.pop(from_row))  # IN PLACE, never a rebuild
        finally:
            self.endMoveRows()
        return True

    def sort_categories(self) -> None:
        """The menu's one-off Sort by name: everything below `_All` lands alphabetically (case-insensitive) through the same restore/save pair the drag gesture uses - manual drags carry on from there."""
        head = [c for c in self._categories if c == "_All"]
        rest = sorted((c for c in self._categories if c != "_All"),
                      key=str.lower)
        ordered = head + rest
        if ordered == self._categories:
            return
        self.restore_order(ordered)
        self.save()

    def order_snapshot(self) -> list:
        """The order as it stands, copied - what Esc puts back."""
        return list(self._categories)

    def restore_order(self, snapshot: list) -> None:
        """Put a snapshot's order back, in place, under a reset pair - same contract as normalize_categories. ▸r/model-contracts"""
        if list(snapshot) == self._categories:
            return
        self.beginResetModel()
        try:
            self._categories[:] = list(snapshot)
        finally:
            self.endResetModel()

    def _recolor(self, old_name: str, new_name: str) -> None:
        """Carry a colour across a rename, or drop it on a removal (empty new_name) - an orphan key would silently reattach if the name came back."""
        table = self.colors()
        color = table.pop(str(old_name), "")
        if color and new_name:
            table[str(new_name)] = color

    def check_add_category(self, cat: str) -> None:
        """Add this category if it does not exist yet."""
        if material.MULTIPLE_VALUES in cat:
            return
        changed = False
        for c in cat.split(","):
            c = c.strip()
            if c != "" and c not in self._categories:
                row = len(self._categories)
                self.beginInsertRows(QtCore.QModelIndex(), row, row)
                try:
                    self._categories.append(c)
                finally:
                    self.endInsertRows()
                changed = True
        if changed:
            self.save()

    def colors(self) -> dict:
        """{category name: colour} for this library, stored beside the names in the same json so it travels with the library."""
        table = self._data.get("category_colors")
        if not isinstance(table, dict):
            table = {}
            self._data["category_colors"] = table
        return table

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
        """Save categories and colours to disk as json; False when the write was refused."""
        db = database.DatabaseConnector(self.DB_FILENAME)
        if not db.serves(self.preferences.dir):  # a switch in another pane repoints the shared connector, and db.set replaces in place
            debug.event("library", "category save refused - the "
                        "connector now serves another library",
                        model=self.preferences.dir, connector=db._path)
            debug.alert(
                "Amaze did not save this library, because another Amaze "
                "panel has been pointed at a different one.\n\n"
                "Nothing is lost. Close the other panel, or reopen this "
                "one, and your changes will save again.",
                key="connector-moved")
            return False
        data = {}
        data["categories"] = self._categories
        data["category_colors"] = self.colors()
        db.set(data)
        stored = db.save()  # the connector's answer, never an unconditional True
        self.drop_count_cache()
        return bool(stored)


class CategoriesSidebarProxy(QtCore.QSortFilterProxyModel):
    """Sidebar NAVIGATION proxy over Categories: presents the STORED order and hides categories with zero visible assets, so you can never click your way to an empty grid. Never call sort()/setSortRole on an instance serving a sidebar; editing surfaces read the source model instead, so empty categories stay assignable. Hiding is optional (prefs.hide_empty_categories). ▸r/press-gestures"""

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
        if model.showing_all_renderers():  # All reveals every category, empty ones included
            return True
        raw = model.index(source_row, 0).data(model.CatSortRole)
        if raw == "_All":
            return True
        return model._category_count(raw) > 0
