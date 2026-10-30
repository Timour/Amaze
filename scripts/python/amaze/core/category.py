"""The Category Model behind the panel's sidebar."""

from typing import Any
from PySide6 import QtCore

from amaze.prefs import prefs
from amaze.core import database, material, renderers

SIDEBAR_COUNT_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 40  # the ONLY declaration - every sidebar model and SidebarItemDelegate import it from here
SIDEBAR_COLOR_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 41  # a category's colour, for the sidebar's left-edge bar


display_name = database.category_label    # the sidebar label for a STORED category


def is_all(name) -> bool:
    """Whether `name` is the All row, stored `_All` or shown `All`: a view, never a category."""
    return name in ("All", "_All")


class Categories(QtCore.QAbstractListModel):
    """The category list for one library, backed by DB_FILENAME."""

    DB_FILENAME = "library.json"  # subclassed by the COP section over its own cops.json

    def __init__(self, preferences: prefs.Prefs) -> None:
        super().__init__()
        self.preferences = preferences  # REQUIRED: a model that can default binds to whatever library the machine's settings name ▸p/duplication-third-verb
        self._data = database.open_document(self)  # a sidecar that will not read must not take the panel down
        self._categories = self._data["categories"]
        self._shown = list(self._categories)    # what the views have been told about; `apply_refresh` compares against it, and starting empty made its FIRST call silent
        self.CatSortRole = QtCore.Qt.ItemDataRole.UserRole  # 256
        self._renderer_filter = ""  # lowercased; "" = no filter. Pushed in by the panel so counts agree with the grid
        self._count_cache = None  # category -> visible count, "_All" = total; dropped on every mutation path
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
        renderer = renderers.normalized(asset.get("renderer", "")).lower()
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
                if not isinstance(asset, dict):    # the model side skips junk rows rather than abort (library.py) - the count pass walks the same document
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

    def switch_model_data(self):
        # Same whole-row-set replacement as MaterialLibrary.switch_model_data.
        self.beginResetModel()
        try:
            data = database.open_document(self, reload=True)    # one unreadable file must not stop the switch
            self._data = data  # the whole dict: counts and empty-category hiding read _data["assets"]
            self._categories = data["categories"]
            self._shown = list(self._categories)    # a switch has told the views everything already
            self.drop_count_cache()
        finally:
            self.endResetModel()

    def apply_refresh(self, db) -> bool:
        """Signal the rows a refresh already merged. This list IS the connector's, so the merge landed in it unseen; what is missing is the reset the views need. True when the sidebar moved. ▸p/mutate-not-rebind"""
        recoloured = database.colours_moved(self, db)
        if list(self._categories) == self._shown:
            if recoloured and self._categories:
                self.dataChanged.emit(
                    self.index(0, 0), self.index(len(self._categories) - 1, 0),
                    [SIDEBAR_COLOR_ROLE])
            return recoloured
        self.beginResetModel()
        try:
            self._told_views()
            self.drop_count_cache()
        finally:
            self.endResetModel()
        return True

    def _told_views(self) -> None:
        """The views now know these rows: every local door ends here, so only a merge resets."""
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
        self._told_views()
        self._recolor(cat, "")
        self.save()

    def rename_category(self, old: str, new: str) -> None:
        """Rename a category here and in every asset; renamed onto one that exists, the two become one."""
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
        self._told_views()
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
            self.beginResetModel()  # a whole-row-set replacement outside a reset pair leaves proxies and the selection describing rows that are gone ▸r/model-contracts
            try:
                self._categories[:] = cleaned  # IN PLACE: this list aliases the connector's document; a rebind detaches it
            finally:
                self.endResetModel()
            self._told_views()
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
        self._told_views()
        return True

    def sort_categories(self) -> None:
        """The menu's one-off Sort by name: everything below `_All` lands alphabetically by LABEL, written through `restore_order` and saved at once - which resets the model, so a caller holding a selection has to put it back (the drag's own path is `move_category`, which does not)."""
        head = [c for c in self._categories if c == "_All"]
        rest = sorted((c for c in self._categories if c != "_All"),
                      key=lambda c: display_name(c).lower())    # by the LABEL, not the stored spelling: `_WIP` reads WIP and must sort there, and str() keeps a non-str row out of the raiser normalize_categories exists for
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
        self._told_views()

    def _recolor(self, old_name: str, new_name: str) -> None:
        """Carry a colour across a rename, or drop it on a removal (empty new_name) - an orphan key would silently reattach if the name came back."""
        table = self.colors()
        color = table.pop(str(old_name), "")
        if color and new_name:
            table.setdefault(str(new_name), color)    # a merge keeps the surviving row's own colour

    def stored_name(self, typed: str) -> str:
        """The stored category a TYPED name means: itself, or the one that reads as it (`_WIP` reads WIP)."""
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
        self._told_views()
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
        db = database.connector_for_save(self, "category save")
        if db is None:  # a switch in another pane repoints the shared connector, and db.set replaces in place
            return False
        data = {}
        data["categories"] = self._categories
        data["category_colors"] = self.colors()
        db.set(data)
        stored = db.save()  # the connector's answer, never an unconditional True
        self.drop_count_cache()
        from amaze.core import model_registry
        model_registry.apply_merged(db, also=self)    # every model on this file takes what the save merged
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
        if is_all(raw):
            return True
        return model._category_count(raw) > 0
