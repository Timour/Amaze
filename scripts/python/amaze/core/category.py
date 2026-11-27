"""The Category Model behind the panel's sidebar."""

from typing import Any
from PySide6 import QtCore

from amaze.prefs import prefs
from amaze.core import (category_list, documents, grid_engine, library_db, library_files,
                        material, multifilterproxy_model, renderers, sidebar_model)

SIDEBAR_COUNT_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 40  # the ONLY declaration - every sidebar model and SidebarItemDelegate import it from here
SIDEBAR_COLOR_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 41  # a category's colour, for the sidebar's left-edge bar
SIDEBAR_KEY_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 42  # a sidebar row's stored identity, "" on All; `index_of` takes it
SIDEBAR_UNREACHABLE_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 43  # True on a folder its last read could not open
ROLE_NAMES = {SIDEBAR_COUNT_ROLE: b"count", SIDEBAR_COLOR_ROLE: b"colour",    # the names QML reads them by
              SIDEBAR_KEY_ROLE: b"key", SIDEBAR_UNREACHABLE_ROLE: b"unreachable"}

ROW_ROLES = frozenset((int(QtCore.Qt.ItemDataRole.DisplayRole), SIDEBAR_COUNT_ROLE,
                       SIDEBAR_COLOR_ROLE, SIDEBAR_KEY_ROLE))    # every role a category row answers

ALL = "_All"    # the first row: a view of every asset, never stored
JOIN, KEEP_BOTH = "join", "keep both"    # the answers `settle_names` acts on; any other changes nothing
SECTION = "categories"    # {id: {"name": n, "order": n, "color": c}} in the section's database


def change_categories(model, keys, on_assets, on_sidebar) -> bool:
    """`on_assets(key)` in one layout change, saved after it, then `on_sidebar(key)`, per key."""
    keys = [key for key in keys if key and not category_list.is_all(key)]
    if not keys or not model.takes_edits():
        return False
    with grid_engine.relayout(model):    # the asset rows change in place
        for key in keys:
            on_assets(key)
    model.save()    # after the layout change: a save merging another session's rows inserts them
    for key in keys:
        on_sidebar(key)
    return True


def rename(model, sidebar, keys, typed) -> str:
    """Categories `keys` named `typed`, joined to a category already of that name; its key or ""."""
    typed = str(typed or "").strip()
    keys = [key for key in keys if key and not category_list.is_all(key)]
    if not typed or category_list.is_all(typed) or not keys:
        return ""
    target = sidebar.key_of(typed) or keys[0]    # the category that stays

    def assets(key):
        if key != target:
            model.rename_category(key, target)

    def sidebar_row(key):
        if key == target:
            sidebar.set_name(key, typed)
        else:
            sidebar.join(key, target)
    if not change_categories(model, keys, assets, sidebar_row):
        return ""
    model.repaint_category_names()
    return target


def settle_names(model, sidebar, ask) -> bool:
    """Categories of one name put to `ask(name, count, apart)`, once an open; whether any changed."""
    names = {key: sidebar.name_of(key) for key in sidebar.top_keys()}
    groups = category_list.same_named(names)
    if not groups or not model.takes_edits():
        return False
    changed = False
    for keys in groups:
        if not sidebar.ask_once(keys):
            continue
        apart = []
        for _key in keys[1:]:    # the lower ones in the sidebar, the same on every computer
            apart.append(category_list.free_name(list(names.values()) + apart, names[keys[0]]))
        answer = ask(names[keys[0]], len(keys), apart)
        if answer == JOIN:
            changed = bool(rename(model, sidebar, keys, names[keys[0]])) or changed
        elif answer == KEEP_BOTH:
            for key, name in zip(keys[1:], apart):
                changed = bool(rename(model, sidebar, [key], name)) or changed
    return changed


def settle_renames(model, sidebar, ask) -> bool:
    """Each category two users renamed put to `ask(mine, theirs, by)`: theirs taken on True."""
    changed = False
    for key, theirs, by in sidebar.take_renames():
        mine = sidebar.name_of(key)
        if mine and theirs and mine != theirs and ask(mine, theirs, by):
            changed = bool(rename(model, sidebar, [key], theirs)) or changed
    return changed


def remove(model, sidebar, keys) -> bool:
    """Categories `keys` taken off every asset, then out of the sidebar; False when refused."""
    return change_categories(model, keys, model.remove_category, sidebar.remove_category)


def assign(model, sidebar, keys, key: str) -> bool:
    """A drop of the tiles keyed `keys` on the category keyed `key`: each one moves into it."""
    return bool(key and not category_list.is_all(key) and keys
                and model.edit_tiles(keys, category=key))


def stored_order(held) -> list:
    """The keys of the categories a database holds, in their order, All first."""
    table = held.table(SECTION)
    keys = sorted((key for key, entry in table.items() if isinstance(entry, dict)),
                  key=lambda key: (table[key].get("order", 1 << 30),
                                   str(table[key].get("name") or ""), key))
    return [ALL] + keys


class Categories(sidebar_model.SidebarModel):
    """The category list for one library, backed by DB_FILENAME; each row keyed by its id."""

    DB_FILENAME = library_files.MATERIALS  # subclassed by each section over its own database
    names_clash = QtCore.Signal()    # a read of the database left categories of one name: the pane asks

    def __init__(self, preferences: prefs.Prefs) -> None:
        super().__init__()
        self.preferences = preferences  # required, never defaulted ▸p/delete-both-duplicates
        self.read_from = library_db.key_of(preferences)    # the library these rows came from
        self._categories = stored_order(self._doc())
        self._seen = list(self._categories)    # the database's order as last read or saved
        self._colour_table = self._read_colours()
        self._names = self._read_names()
        self._named = set()    # keys this model named, their names written at its save
        self._asked = set()    # the same-named categories asked about since the library opened
        self._renamed = []    # the collisions on a category's name that the pane has not asked about
        self._removed = set()    # keys this model took out, dropped from the database at its save
        self._shown = list(self._categories)    # the rows the views last showed; `apply_refresh` compares
        self._renderer_filter = None  # the grid's kind filter, folded; None = none. Counts match the grid
        self._count_cache = None  # category -> visible count, `_All` = total; cleared on every change
        self.layoutChanged.connect(self.drop_count_cache)

    def top_keys(self) -> list:
        """The keys below All, in their order; row n shows `_categories[n]`."""
        return self._categories[1:]

    def data(
        self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex, role: int = 0
    ) -> Any:
        if index.column():
            return self.color_cell(index, role)
        if role not in ROW_ROLES:
            return None    # the style asks for six more roles per row on every repaint
        key = super().data(index, SIDEBAR_KEY_ROLE)
        if key is None or role == SIDEBAR_KEY_ROLE:
            return key

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return category_list.display_name(self._names.get(key, "") if key else ALL)

        if role == SIDEBAR_COUNT_ROLE:
            return self._category_count(key or ALL)    # All counts every asset as `_All`

        if role == SIDEBAR_COLOR_ROLE:
            return self.color_of(key)

    def set_renderer_filter(self, render_filter) -> None:
        """The grid's Filter value as MultiFilterProxyModel gets it: None, one kind, or All's kinds."""
        empty = render_filter is None or render_filter == ""
        self._renderer_filter = None if empty else multifilterproxy_model.folded(render_filter)
        self.drop_count_cache()

    def drop_count_cache(self, *args) -> None:
        """Invalidate the one-pass count map (also a layoutChanged slot, hence the ignored args)."""
        self._count_cache = None

    def counts_changed(self) -> None:
        """Drop the counts and tell every view each row's count may differ; a QML view reads only then."""
        self.drop_count_cache()
        if self._categories:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._categories) - 1, 0),
                                  [SIDEBAR_COUNT_ROLE])

    def _asset_matches_renderer(self, asset: dict) -> bool:
        """Whether an asset passes the renderer filter; must match MultiFilterProxyModel exactly."""
        rf = self._renderer_filter
        if rf is None:
            return True
        return multifilterproxy_model.kind_matches(rf, renderers.normalized(asset.get("renderer", "")))

    def _category_count(self, key: str) -> int:
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
                for one in set(material.category_names(asset.get("categories"))):
                    counts[one] = counts.get(one, 0) + 1
            counts["_All"] = total
            self._count_cache = counts
        if key == "_All":
            return counts.get("_All", 0)
        return counts.get(key.strip(), 0)

    def _doc(self) -> documents.Document:
        """This sidebar's database, as library_db holds it in memory."""
        return library_db.document(self.preferences, self.DB_FILENAME)

    def _read_colours(self) -> dict:
        return {key: str(entry.get("color")) for key, entry in self._doc().table(SECTION).items()
                if isinstance(entry, dict) and entry.get("color")}

    def _read_names(self) -> dict:
        table = self._doc().table(SECTION)
        return {key: str(entry.get("name") or "") for key, entry in table.items()
                if isinstance(entry, dict)}

    def switch_model_data(self):
        # Same whole-row-set replacement as MaterialLibrary.switch_model_data.
        self.beginResetModel()
        try:
            self.read_from = library_db.key_of(self.preferences)
            self._categories = stored_order(self._doc())
            self._seen = list(self._categories)
            self._colour_table = self._read_colours()
            self._names, self._named = self._read_names(), set()
            self._removed, self._asked, self._renamed = set(), set(), []
            self._shown = list(self._categories)    # the model reset has already updated the views
            self.drop_count_cache()
            self._forget_rows()
        finally:
            self.endResetModel()
        self._tell_names_clash()

    def _tell_names_clash(self) -> None:
        """`names_clash` when two categories just read have one name, or one was renamed two ways."""
        if self._renamed or category_list.same_named(
                {key: self._names.get(key, "") for key in self.top_keys()}):
            self.names_clash.emit()

    def apply_refresh(self) -> bool:
        """Read in the database's names, colours and order; True when the sidebar changed."""
        changed = self._read_database()
        self._renamed += self._doc().take_collisions(library_db.is_rename)
        if changed or self._renamed:
            self._tell_names_clash()
        return changed

    def take_renames(self) -> list:
        """(key, the other name, its user) of each category two users renamed, ours kept; once."""
        found, self._renamed = self._renamed, []
        return [(one.key, str(one.theirs or ""), one.by) for one in found]

    def _read_database(self) -> bool:
        """The database's names, colours and order taken; whether any differs from what was shown."""
        colours, names = self._read_colours(), self._read_names()
        recoloured = colours != self._colour_table
        renamed = [key for key in self.top_keys() if names.get(key) != self._names.get(key)]
        self._colour_table, self._names = colours, names
        stored = stored_order(self._doc())
        moved, self._seen = stored != self._seen, stored    # a local edit not yet saved is kept
        keys = [key for key in stored if key not in self._removed]
        self.drop_count_cache()
        if not moved or keys == list(self._categories):
            if (recoloured or renamed) and self._categories:
                self.dataChanged.emit(
                    self.index(0, 0), self.index(len(self._categories) - 1, 0),
                    [SIDEBAR_COLOR_ROLE, QtCore.Qt.ItemDataRole.DisplayRole])
            return recoloured or bool(renamed)
        self.beginResetModel()
        try:
            self._categories[:] = keys
            self._mark_rows_shown()
            self._forget_rows()
        finally:
            self.endResetModel()
        return True

    def _mark_rows_shown(self) -> None:
        """Record that the views show these rows: every local change calls this, so only a merge resets."""
        self._shown = list(self._categories)

    def _takes(self) -> bool:
        """Whether its database takes a change now; when not, the user is told why."""
        return library_db.takes_change(self, tell=True)

    def remove_category(self, key: str) -> None:
        """Remove a category from the library and every asset; a no-op for a key not present."""
        if key not in self._categories or not self._takes():
            return
        row = self._categories.index(key)
        self.beginRemoveRows(QtCore.QModelIndex(), row, row)
        try:
            self._categories.pop(row)
            self._forget_row(self._node_ids.get((None, key)))
        finally:
            self.endRemoveRows()
        self._removed.add(key)
        self._mark_rows_shown()
        self._colour_table.pop(key, None)
        self.save()

    def set_name(self, key: str, name: str) -> None:
        """Give the category keyed `key` another name; its assets, colour and place stay."""
        name = str(name or "").strip()
        if not name or key not in self._categories or self._names.get(key) == name \
                or not self._takes():
            return
        self._names[key] = name
        self._named.add(key)
        index = self.index(self._categories.index(key), 0)
        self.dataChanged.emit(index, index)
        self.save()

    def join(self, key: str, into: str) -> None:
        """The category keyed `key` taken into the one keyed `into`, which keeps its own colour."""
        if key == into or key not in self._categories or into not in self._categories:
            return
        colour = self._colour_table.get(key)
        if colour:
            self._colour_table.setdefault(into, colour)    # a colour only where `into` has none
        self.remove_category(key)

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
        """Sort below `_All` by name and save; it resets the model, so restore a selection."""
        head = [c for c in self._categories if c == "_All"]
        rest = sorted((c for c in self._categories if c != "_All"),
                      key=lambda c: category_list.display_name(self._names.get(c, "")).lower())
        ordered = head + rest
        if ordered == self._categories or not self._takes():
            return
        self.restore_order(ordered)
        self.save()

    def restore_order(self, snapshot: list) -> None:
        """Put a snapshot's order back, in place, under a reset pair. ▸r/model-contracts"""
        if list(snapshot) == self._categories:
            return
        self.beginResetModel()
        try:
            self._categories[:] = list(snapshot)
            self._forget_rows()
        finally:
            self.endResetModel()
        self._mark_rows_shown()

    def ask_once(self, keys) -> bool:
        """Whether these same-named categories were not asked about yet since the library opened."""
        new = frozenset(keys) not in self._asked
        self._asked.add(frozenset(keys))
        return new

    def name_of(self, key: str) -> str:
        """The stored name of the category keyed `key`, "" for none."""
        return self._names.get(str(key or ""), "")

    def key_of(self, name: str) -> str:
        """The key of the category named `name`, capitals aside, `_WIP` as WIP; "" for none."""
        return category_list.key_named({key: self._names.get(key, "") for key in self.top_keys()},
                                       name)

    def choices(self) -> list:
        """(key, name as shown) of every category, by name: what a dialog's Category list offers."""
        shown = category_list.display_name
        return sorted(((key, shown(self._names.get(key, ""))) for key in self.top_keys()),
                      key=lambda pair: pair[1].lower())

    def check_add_category(self, name: str) -> str:
        """The key of the category named `name`, its commas included, made when there is none."""
        name = str(name or "").strip()
        found = self.key_of(name)
        if not name or found or category_list.is_all(name) or not self._takes():
            return found
        key, row = category_list.new_key(), len(self._categories)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        try:
            self._categories.append(key)
            self._names[key] = name
        finally:
            self.endInsertRows()
        self._named.add(key)
        self._mark_rows_shown()
        self.save()
        return key

    def colors(self) -> dict:
        """{category key: colour} for this library, kept with the names in its database."""
        return self._colour_table

    def color_of(self, key: str) -> str:
        return str(self.colors().get(str(key), "") or "")

    def set_color(self, key: str, color: str) -> None:
        """Colour one category, or clear it with an empty colour."""
        if not self._takes():
            return
        table = self.colors()
        key = str(key)
        if color:
            table[key] = str(color)
        else:
            table.pop(key, None)
        self.save()
        row = self._row_of(key)
        if row is not None:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index)

    def _row_of(self, key: str):
        for row, held in enumerate(self._categories):
            if held == key:
                return row
        return None

    def save(self) -> bool:
        """Write the names, order and colours to the database; False, the user told, if refused."""
        if not self._takes():
            return False
        held = self._doc()
        with library_db.library_for(self.preferences).holding():
            order = 0
            for key in self._categories:
                if category_list.is_all(key) or not isinstance(key, str):
                    continue
                entry = dict(held.get(SECTION, key) or {}, order=order)
                if key in self._named or not entry.get("name"):
                    entry["name"] = self._names.get(key, "")    # only a name this model gave
                if self._colour_table.get(key):
                    entry["color"] = self._colour_table[key]
                else:
                    entry.pop("color", None)
                held.put(SECTION, key, entry)
                order += 1
            for key in self._removed:
                if key not in self._categories:
                    held.drop(SECTION, key)
            self._removed, self._named = set(), set()
        self._seen = stored_order(held)
        self.drop_count_cache()
        library_db.changed(self.preferences, self.DB_FILENAME)
        return True


class CategoriesSidebarProxy(sidebar_model.RowMoves, QtCore.QSortFilterProxyModel):
    """Sidebar proxy: stored order, empty categories hidden; never sort() it. ▸r/press-gestures"""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.hide_empty = True

    @property
    def unfolds(self) -> bool:
        """Whether rows may hold rows under them, as its list answers."""
        model = self.sourceModel()
        return model is not None and model.unfolds

    def index_of(self, key) -> QtCore.QModelIndex:
        """The shown row keyed `key`, "" giving All, a row under a row too; invalid when hidden."""
        model = self.sourceModel()
        if model is None:
            return QtCore.QModelIndex()
        return self.mapFromSource(model.index_of(key))

    def refresh(self) -> None:
        """Drop its list's counts, say so, and refilter, for changes that emit no layoutChanged."""
        model = self.sourceModel()
        if model is not None:
            model.counts_changed()
        self.invalidateFilter()

    def flags(self, index):
        return self.move_flags(index, super().flags(index))

    def movable(self, index) -> bool:
        """Whether a shown row may be dragged to reorder: every row below All."""
        if index is None or not index.isValid() or index.row() < 1:
            return False
        return bool(self.index(index.row(), 0).data(SIDEBAR_KEY_ROLE))    # "" on All

    def move_row(self, index, to_row: int) -> bool:
        """Move a shown row to shown row `to_row`, clamped below All, as a move of the stored rows."""
        model = self.sourceModel()
        if model is None or index is None or not index.isValid():
            return False
        to_row = max(1, min(int(to_row), self.rowCount() - 1))
        from_source = self.mapToSource(self.index(index.row(), 0)).row()
        to_source = self.mapToSource(self.index(to_row, 0)).row()
        return model.move_category(from_source, to_source)

    def commit_order(self) -> bool:
        """Save the order, once per drag, on release; False when the library refuses the change."""
        model = self.sourceModel()
        return model is not None and model.save()

    def color_of(self, key) -> str:
        model = self.sourceModel()
        return "" if model is None else model.color_of(key)

    def set_color(self, key, color: str) -> None:
        model = self.sourceModel()
        if model is not None:
            model.set_color(key, color)    # its database and its row's repaint

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
        raw = model.index(source_row, 0, source_parent).data(SIDEBAR_KEY_ROLE)
        if not raw:    # All, keyed ""
            return True
        return model._category_count(raw) > 0
