"""
Stores the Category Model for the MatLib Panel and provides the data to it's corresponding view
Uses QtCore.QAbstractListModel as a Base Class
"""

from typing import Any
from PySide6 import QtCore

from amaze.prefs import prefs
from amaze.core import database, debug, material

# Shared sidebar-count role: SidebarItemDelegate (panel/delegates.py)
# reads this from WHICHEVER model backs the sidebar and paints
# "Name (N)". THIS declaration is the only one - every sidebar model
# and the delegate import it from here. It used to say "keep the number
# identical across four modules", which is a rule a person has to
# remember; the delegate was still hand-writing `UserRole + 40` as late
# as 2026-08-02, with a comment pointing at this constant.
SIDEBAR_COUNT_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 40
#: A category's colour, for the sidebar's left-edge bar. Shared like
#: the count role so one delegate serves every sidebar model.
SIDEBAR_COLOR_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 41


class Categories(QtCore.QAbstractListModel):
    """
    Stores the Category Model for the MatLib Panel and provides the data to it's corresponding view
    Uses QtCore.QAbstractListModel as a Base Class
    """

    #: which json file in the library dir backs this model - the COP
    #: section subclasses this over its own cops.json.
    DB_FILENAME = "library.json"

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        preferences: prefs.Prefs | None = None,
    ) -> None:
        super().__init__()

        # A Prefs passed POSITIONALLY lands in `parent` and leaves
        # `preferences` None - so the model silently loads the LIVE
        # library instead of the caller's. That is how a test run wrote
        # a stray material into the real library; refuse it loudly
        # rather than quietly binding to the user's data.
        # Duck-typed on purpose: the category tests patch prefs.Prefs
        # with a mock, and isinstance() against a non-class raises. A
        # QObject parent has neither of these attributes; a Prefs has
        # both.
        if parent is not None and hasattr(parent, "asset_dir") \
                and hasattr(parent, "dir"):
            raise TypeError(
                "%s: pass preferences by KEYWORD (preferences=...) - a "
                "positional Prefs binds the model to the live library."
                % type(self).__name__
            )

        # Share the panel's Prefs when given (see MaterialLibrary).
        if preferences is None:
            preferences = prefs.Prefs()
            preferences.load()
        self.preferences = preferences
        db = database.DatabaseConnector(self.DB_FILENAME)
        # Through the survivable door: this model is constructed during
        # panel setup too, and a sidecar list that will not read must
        # not take the panel down from the SIDEBAR's constructor after
        # the asset model already survived it.
        self._data = database.load_survivable(db, self.preferences.dir)
        self._categories = self._data["categories"]
        self.CatSortRole = QtCore.Qt.ItemDataRole.UserRole  # 256
        # Active renderer filter (lowercased; "" = no filter). Pushed in
        # by the panel whenever the Renderer menu changes, so counts and
        # empty-category hiding agree with what the grid actually shows.
        self._renderer_filter = ""
        # One-pass count map cache (category -> visible-asset count,
        # "_All" = total). The old per-call scan walked every asset for
        # EVERY sidebar row on every repaint and every proxy filter
        # pass. Dropped on any mutation path: our own layoutChanged
        # (save/assign/update flows emit it), renderer switches,
        # reloads, saves, and the panel's sidebar refresh hook.
        self._count_cache = None
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
        """Store the grid's active renderer filter so counts and the
        sidebar's empty-category hiding evaluate against the same set of
        materials the grid shows. Pass the exact value the panel feeds
        MultiFilterProxyModel ("all_renderers" for All)."""
        self._renderer_filter = str(render_filter or "").lower()
        self.drop_count_cache()

    def drop_count_cache(self, *args) -> None:
        """Invalidate the one-pass count map (also a layoutChanged
        slot, hence the ignored args)."""
        self._count_cache = None

    def _asset_matches_renderer(self, asset: dict) -> bool:
        """Mirror MultiFilterProxyModel's RendererRole matching EXACTLY
        (case-insensitive substring; "all_renderers" passes EVERY row,
        including one whose renderer is empty) so sidebar and grid can
        never disagree about what counts as visible.

        The empty renderer used to be rejected here before the All
        escape - matching the proxy, which had the same ordering bug -
        so a Repair-recovered row counted zero in the sidebar as well as
        being missing from the grid. Both were fixed together; changing
        one alone reintroduces the disagreement this docstring forbids.
        """
        rf = self._renderer_filter
        if not rf:
            return True
        renderer = material.normalized_renderer(asset.get("renderer", "")).lower()
        if rf in renderer:
            return True
        return "all_renderers" in rf

    def showing_all_renderers(self) -> bool:
        """True when the Renderer filter is All (or unset). The sidebar
        uses this to reveal EVERY category, empty ones included, so they
        can be seen and deleted - "All" doubles as the manage-categories
        view."""
        rf = self._renderer_filter
        return (not rf) or ("all_renderers" in rf)

    def _category_count(self, raw_name: str) -> int:
        """How many VISIBLE assets live in this category ("_All" = every
        visible asset) - visible meaning matching the active renderer
        filter, so the number is exactly what clicking the row will
        show. Served from a one-pass map over the shared database dict,
        rebuilt lazily after any mutation (see drop_count_cache)."""
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
        # Same whole-row-set replacement as MaterialLibrary.switch_model_data
        # - see the note there for why the reset is a correctness
        # requirement and not bookkeeping.
        self.beginResetModel()
        try:
            self.preferences.load()
            db = database.DatabaseConnector(self.DB_FILENAME)
            data = db.reload_with_path(self.preferences.dir)
            # Keep the whole dict, not just the category list - counts and
            # empty-category hiding read _data["assets"], which otherwise
            # stayed pointing at the PREVIOUS library after a switch.
            self._data = data
            self._categories = data["categories"]
            self.drop_count_cache()
        finally:
            self.endResetModel()

    def remove_category(self, cat: str) -> None:
        """Removes the given category from the library (and also in all assets)

        A no-op for a name that is not present, and bracketed by row
        signals. list.remove() raises ValueError for any name the
        sidebar displayed with its leading underscore stripped (data()
        returns elem[1:]) - and that exception escaped the panel slot
        AFTER the asset model had already stripped the category from
        every Material in memory and BEFORE save() ran. The panel
        compensated for the missing signals with layoutChanged, which is
        the wrong signal for a changed row COUNT and leaves persistent
        indexes dangling."""
        if cat not in self._categories:
            return
        row = self._categories.index(cat)
        self.beginRemoveRows(QtCore.QModelIndex(), row, row)
        try:
            self._categories.pop(row)
        finally:
            self.endRemoveRows()
        self._recolor(cat, "")
        self.save()

    def rename_category(self, old: str, new: str) -> None:
        """Renames the given category in the library (and also in all assets)"""
        # Update Categories with that name
        for count, current in enumerate(self._categories):
            if current == old:
                self._categories[count] = new
        self._recolor(old, new)
        self.save()

    def normalize_categories(self) -> int:
        """Strip whitespace and remove duplicate/empty entries from the
        category list (legacy data cleanup). Returns changed entry count."""
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
            # begin/endResetModel, because this REPLACES the row set.
            # research.md: a proxy left on its old row count and a
            # selection model pointing at rows that no longer exist read
            # out of range on the native side - a segfault, not a
            # catchable exception. Measured here at 9 rows -> 4 with the
            # proxy still reporting 9 and the current index on row 8.
            # check_add_category and remove_category in this same class
            # already do this; only this one did not, and Clean Library
            # calls it. The panel's bare layoutChanged afterwards is the
            # wrong signal for a changed row COUNT - this class's own
            # remove_category docstring says so.
            self.beginResetModel()
            try:
                # IN PLACE: `_categories` aliases the connector's own
                # `_data["categories"]`, which the two-writer merge
                # repairs in place - a rebind detaches the model from
                # the document and the next save erases whatever a peer
                # machine added.
                self._categories[:] = cleaned
            finally:
                self.endResetModel()
            self.save()
        return changed

    def move_category(self, from_row: int, to_row: int) -> bool:
        """Move one category to another row - the manual order.

        The stored list IS the order the sidebar shows (the name sort
        retired 2026-08-14), so a move is list surgery on the
        connector's own list, in place, bracketed by the MOVE signals -
        a proxy and the selection follow a move without dangling
        (probed, research.md ▸ Model row moves).

        Row 0 is `_All` (the database pins it there) and it neither
        moves nor accepts a row above it. Deliberately NO save: the
        gesture moves live while the mouse is down and saves once on
        release - `commit` is the caller's word to say.
        """
        count = len(self._categories)
        if not (1 <= from_row < count and 1 <= to_row < count):
            return False
        if from_row == to_row:
            return False
        # beginMoveRows speaks PRE-move coordinates: moving DOWN to
        # become row N is destination N+1 (research.md, probed). A
        # destination inside [from, from+1] is the no-op range Qt
        # refuses; the guards above already exclude it.
        destination = to_row if to_row < from_row else to_row + 1
        if not self.beginMoveRows(QtCore.QModelIndex(), from_row,
                                  from_row, QtCore.QModelIndex(),
                                  destination):
            return False
        try:
            # IN PLACE: pop/insert on the aliased list, never a
            # rebuild - `_categories` is the connector's document.
            self._categories.insert(to_row, self._categories.pop(from_row))
        finally:
            self.endMoveRows()
        return True

    def order_snapshot(self) -> list:
        """The order as it stands, copied - what Esc puts back."""
        return list(self._categories)

    def restore_order(self, snapshot: list) -> None:
        """Put a snapshot's order back, in place, under a reset pair
        (a whole-row-set replacement, same contract as
        normalize_categories - an unbracketed one reads out of range
        on the native side)."""
        if list(snapshot) == self._categories:
            return
        self.beginResetModel()
        try:
            self._categories[:] = list(snapshot)
        finally:
            self.endResetModel()

    def _recolor(self, old_name: str, new_name: str) -> None:
        """Carry a colour across a rename; drop it on a removal (empty
        new_name). An orphan key would silently reattach the old colour
        if that name were ever created again."""
        table = self.colors()
        color = table.pop(str(old_name), "")
        if color and new_name:
            table[str(new_name)] = color

    def check_add_category(self, cat: str) -> None:
        """Checks if this category exists and adds it if needed"""
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

    # -- colours ------------------------------------------------------
    #
    # A category can carry a colour, which the grid paints behind each
    # tile's name. Stored beside the category NAMES in the same json -
    # so it travels with the library, and the asset model (which shares
    # this connector's data dict) can read it without knowing about
    # this model at all.
    #
    # Keyed by name, so a rename has to carry the colour across, and a
    # removed category takes its colour with it. Both are handled below
    # rather than left as orphan keys that would silently reattach if
    # the name ever came back.

    def colors(self) -> dict:
        """{category name: colour} for this library."""
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
        """Save data to disk as json. False when the write was refused.

        The categories and their colours live in the SAME library.json
        as the assets, so they need the same guard MaterialLibrary.save
        has - and did not get it when that one was written. The
        connector is shared by filename across every pane in the
        process, so a library switch in another pane repoints it while
        this model still holds the old library's category list; `db.set`
        replaces the list in place (`current[:] = incoming`), so the
        next colour change or Clean Library wrote library A's categories
        and colours over library B's.
        """
        db = database.DatabaseConnector(self.DB_FILENAME)
        if not db.serves(self.preferences.dir):
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
        # The connector's answer, not an unconditional True: a refused
        # write (latch, merge refusal, held file) reported success here
        # while the in-memory list had already moved - the same shape
        # MaterialLibrary.save was fixed for.
        stored = db.save()
        self.drop_count_cache()
        return bool(stored)


class CategoriesSidebarProxy(QtCore.QSortFilterProxyModel):
    """Sidebar NAVIGATION proxy over Categories: PRESENTS the stored
    order (it does not sort - the manual order retired the name sort
    2026-08-14, whose "_All" lost to any digit so a category called
    "2" sat above All), and hides categories with zero visible assets
    - you can never click your way to an empty grid. An unsorted
    QSortFilterProxyModel tracks source order across row moves
    (probed, research.md ▸ Model row moves), so nobody may call
    sort()/setSortRole on an instance serving a sidebar; the stored
    list is the order, "_All" first because the database pins it.
    "Visible" respects the Materials renderer filter (pushed into the
    source model via Categories.set_renderer_filter), so with Redshift
    selected a category holding only Karma materials hides too; "_All"
    always shows. Editing surfaces (save dialog, details dropdown,
    Move to/Add to menus) deliberately do NOT use this proxy - they
    read the source model, so empty categories stay assignable and
    come back to life the moment a material is filed into them; the
    save dialog's own proxy keeps its alphabetical sort() on purpose
    (a dropdown you type against stays predictable).

    The hiding is optional (prefs.hide_empty_categories, pushed in by
    the panel): with hide_empty False this proxy passes every row in
    stored order."""

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
        # Renderer "All" shows every category, empty ones included - it's
        # the view where you can see and delete unused categories. A
        # specific renderer still hides its empties.
        if model.showing_all_renderers():
            return True
        raw = model.index(source_row, 0).data(model.CatSortRole)
        if raw == "_All":
            return True
        return model._category_count(raw) > 0
