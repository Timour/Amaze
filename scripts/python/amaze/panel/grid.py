"""The Grid area: the one thumbnail view, and the one QMenu builder over `Section.GRID_MENU` tables - dispatch by identity, never by comparing actions. ▸o/section-api"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import debug, grid_columns
from amaze.helpers import theme, ui_helpers
from amaze.panel import delegates

AssetItemDelegate = delegates.AssetItemDelegate    # resolved through the module, which is reloaded per Houdini session - never bound at import



def _resolve(context, name, indexes, current, default):
    """A named fact on the context: an attribute as it is, a method asked about THIS selection - one name resolves both."""
    if not name:
        return default
    fact = getattr(context, name, None)
    if callable(fact):
        return bool(fact(indexes, current))
    return bool(fact)


def _enabled(context, entry, indexes, current):
    """The selection law: an entry greys when it lacks what it needs, and is never hidden for it - a menu must not move under the cursor between two right-clicks."""
    if entry.needs == "always":
        return True
    if entry.needs == "one":
        return len(indexes) == 1
    if entry.needs == "any":
        return bool(indexes)
    return _resolve(context, entry.needs, indexes, current, False)


def _swatch_icon(colour: str):
    """A solid colour chip for a submenu row - Color's Copy Color menu doubles as a palette preview."""
    side = theme.ui_px(14)
    pixmap = QtGui.QPixmap(side, side)
    pixmap.fill(QtGui.QColor(colour))
    return QtGui.QIcon(pixmap)


def _tidy_separators(rows):
    """No leading, doubled or trailing divider - a table with conditional rows produces all three."""
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


def build_menu(panel, context, entries, indexes, current):
    """The QMenu for one entry table, plus {action: (verb, payload)} - split from the exec so tests read menus without a popup; the Sidebar menus use the same builder."""
    menu = QtWidgets.QMenu(panel)
    verbs = {}
    rows = []
    for entry in entries:
        if not entry.label:
            rows.append(None)
            continue
        if not _resolve(context, entry.shown, indexes, current, True):
            continue
        rows.append(entry)

    for entry in _tidy_separators(rows):
        if entry is None:
            menu.addSeparator()
            continue
        label = entry.label
        if entry.count_suffix and len(indexes) > 1:
            label += " (%d)" % len(indexes)
        enabled = _enabled(context, entry, indexes, current)
        if entry.children:
            submenu = menu.addMenu(label)
            submenu.menuAction().setEnabled(enabled)    # the PARENT carries the enabled state - an openable submenu with nothing to pick reads as broken
            children = getattr(context, entry.children)(indexes, current)
            for child_label, payload, colour, live in children:    # (label, payload, swatch colour, live); a child GREYS when it has nothing to act on, same law as the top level
                if colour:
                    action = submenu.addAction(
                        _swatch_icon(colour), child_label)
                else:
                    action = submenu.addAction(child_label)
                action.setEnabled(bool(live))
                verbs[action] = (entry.verb, payload)
            continue
        action = menu.addAction(label)
        action.setEnabled(enabled)
        if entry.checkable:
            action.setCheckable(True)    # a TOGGLE: the verb is handed the state the user just asked for
            state = _resolve(context, entry.checkable, indexes, current,
                             False)
            action.setChecked(state)
            verbs[action] = (entry.verb, not state)
        else:
            verbs[action] = (entry.verb, None)
    return menu, verbs


def build_grid_menu(panel, context, indexes, current):
    """The Grid's table, kept as its own name - the tests and docs speak of the grid menu specifically."""
    return build_menu(panel, context, context.GRID_MENU, indexes, current)


def open_grid_menu(panel, context) -> None:
    """Right-click on the Grid."""
    if context is None:
        return
    _open(panel, context, getattr(context, "GRID_MENU", ()),
          context.grid_selection(), panel.thumblist)


def open_catlist_menu(panel, context) -> None:
    """Right-click on the Sidebar - the same builder over a different table and a different selection."""
    if context is None:
        return
    _open(panel, context, getattr(context, "SIDEBAR_MENU", ()),
          context.sidebar_selection(), panel.cat_list)


def _open(panel, context, entries, indexes, view) -> None:
    """Build a menu, show it, and run whatever was picked - the selection and the current row are read ONCE here, for every menu."""
    if not entries or view is None:
        return
    current = ui_helpers.live_current_index(view)
    if current is None or not current.isValid() or current not in indexes:
        current = indexes[0] if indexes else None    # the row the menu is about is ALWAYS a selected row: current and selection are independent in Qt, so a valid current OUTSIDE the selection is reachable

    menu, verbs = build_menu(panel, context, entries, indexes, current)
    chosen = menu.exec_(QtGui.QCursor.pos())
    verb, payload = verbs.get(chosen, ("", None))    # a dismissed menu and a never-built entry are both None - a dict lookup, never `==` chains
    menu.deleteLater()    # after the lookup (the dict is keyed by the menu's own QActions); parented menus otherwise live forever - research.md ▸ Qt widgets, FORTY QMenus
    if not verb:
        return
    getattr(context, verb)(indexes, current, payload)


def restore_drag_mode(panel) -> None:
    """Re-arm Qt's native file-path drag after any setViewMode() - setMovement(Static) silently sets dragEnabled(False). research.md ▸ Qt widgets"""
    panel.thumblist.setDragEnabled(True)
    panel.thumblist.setDragDropMode(
        QtWidgets.QAbstractItemView.DragDropMode.DragOnly
    )


def sidebar_row_height(panel, table) -> int:
    """One row height for both views: the category list's own, else the table delegate's when the sidebar has no rows yet."""
    cat = getattr(panel, "cat_list", None)
    model = cat.model() if cat is not None else None
    if model is not None and model.rowCount():
        height = cat.sizeHintForRow(0)
        if height > 0:
            return height
    option = QtWidgets.QStyleOptionViewItem()
    option.initFrom(table)
    option.font = table.font()
    return table.itemDelegate().sizeHint(
        option,
        table.model().index(0, grid_columns.KEYS.index("name"))
    ).height()


ALWAYS_SHOWN = "always-shown"    # distinct objects: absence, always and never are three answers, and two once shared None
NEVER_SHOWN = "never-shown"


def visible_view(panel):
    """The grid view the user is actually looking at - asks isHidden, never isVisible, which has no headless answer."""
    table = getattr(panel, "thumbtable", None)
    if table is not None and not table.isHidden():
        return table
    return panel.thumblist


def show_table(panel, showing: bool) -> None:
    """Swap which grid view is visible - both share model and selection, so this is a visibility change and nothing more."""
    table = getattr(panel, "thumbtable", None)
    if table is None:
        return
    if showing:
        header = table.verticalHeader()
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Fixed)
        model = table.model()
        if model is not None and model.rowCount():
            hint = sidebar_row_height(panel, table)    # the CATEGORY list decides the row height - two delegates measuring independently sat 2px apart
            header.setMinimumSectionSize(hint)    # the minimum FIRST, or the default is silently clamped to the style's 19 - research.md ▸ Qt widgets
            header.setDefaultSectionSize(hint)
        table_palette = QtGui.QPalette(panel.thumblist.palette())    # a QTableView brings the platform's palette: white rows on a dark panel without this
        table_palette.setColor(
            QtGui.QPalette.ColorRole.Text, AssetItemDelegate.TEXT_COLOR)
        table.setPalette(table_palette)
        table.setFont(panel.thumblist.font())
        table.viewport().setAutoFillBackground(True)    # no QProxyStyle for the padding: setStyle hands over a pointer nobody owns and bus-errored - research.md ▸ Qt widgets
        sync_table_columns(panel)
    page = getattr(panel, "empty_page", None)    # a blank showing must survive a view-mode change, so ask what is up rather than assume
    blank_up = page is not None and not page.isHidden()
    panel._table_mode = bool(showing)
    apply_grid_face(panel, blank_up)


def grid_pane_layout(panel):
    """The layout holding the grid views - the empty page joins it."""
    root = getattr(panel, "ui", None)
    if root is None:
        return None
    return root.findChild(QtWidgets.QVBoxLayout, "verticalLayout_7")


def apply_grid_face(panel, blank_up: bool) -> None:
    """THE ONE WRITER of the grid pane's three visibilities - exactly one of table, list and empty page is up; the blank verdict arrives as an argument."""
    table = getattr(panel, "thumbtable", None)
    page = getattr(panel, "empty_page", None)
    showing_table = bool(getattr(panel, "_table_mode", False))
    if page is not None:
        page.setVisible(bool(blank_up))
    if blank_up and page is not None:
        if table is not None:
            table.setVisible(False)
        panel.thumblist.setVisible(False)
        return
    if table is not None:
        table.setVisible(showing_table)
    panel.thumblist.setVisible(not showing_table)


def bind_table_cell_delegates(panel, tile_delegate) -> None:
    """Per-COLUMN delegates for the cells Qt cannot paint as text; WHICH columns comes from the active delegate's roles. Row height belongs to show_table, where the mode is known."""
    table = getattr(panel, "thumbtable", None)
    if table is None:
        return

    for previous in getattr(table, "_amaze_cell_delegates", ()):    # the previous set goes first: setItemDelegate* takes no ownership, and rebinding leaves orphans alive - research.md ▸ Qt widgets, ELEVEN delegates
        try:
            previous.setParent(None)    # leaves the child list at once; deleteLater then frees it under the real event loop
            previous.deleteLater()
        except RuntimeError:
            pass          # already gone with a rebuilt table
    installed = []

    keys = grid_columns.KEYS
    grid_cell = delegates.GridCellDelegate(table)    # owns the cell padding and nothing else; selection is the host stylesheet's
    installed.append(grid_cell)
    table.setItemDelegate(grid_cell)
    sources = {    # which columns are ticks is the model's list; what each reads and draws belongs here with the drawer
        "favorite": ("_favorite_role", tile_delegate.FAV_MARK_COLOR),
        "open": ("_open_role", tile_delegate.OPEN_MARK_COLOR),
        "comments": ("_notes_role", tile_delegate.NOTE_MARK_COLOR),
    }
    ticks = ((key,) + sources[key]
             for key in grid_columns.GridColumnsMixin.TICK_COLUMNS)
    category_cell = delegates.CategoryCellDelegate(tile_delegate, table)
    installed.append(category_cell)
    table.setItemDelegateForColumn(keys.index("category"), category_cell)
    for key, attribute, colour in ticks:
        tick = delegates.TickCellDelegate(
            tile_delegate, getattr(tile_delegate, attribute, None),
            colour, table)
        installed.append(tick)
        table.setItemDelegateForColumn(keys.index(key), tick)
    table._amaze_cell_delegates = installed    # what this bind owns, for the next one to drop


def sync_table_columns(panel) -> None:
    """WHICH columns the table shows - the section's answer - and their STARTING widths; the user drags the rest."""
    table = getattr(panel, "thumbtable", None)
    if table is None:
        return
    delegate = (panel.thumblist.itemDelegate()
                if panel.thumblist is not None else None)
    roles = {
        "category": "_category_role", "tags": "_tag_role",
        "license": "_licence_role", "favorite": "_favorite_role",
        "open": "_open_role", "comments": "_notes_role",
        "version": "_active_version_role",
        "thumb": NEVER_SHOWN,    # no picture column: a 16px thumbnail is a smudge, and hiding it took DecorationRole reads from 1668 to 0
        "name": ALWAYS_SHOWN,    # every column NAMED, the always-up pair included - absence once doubled as always-shown
        "type": ALWAYS_SHOWN,
    }
    source = table.model()    # the delegate says what it can PAINT, the model what it can ANSWER - a column needs both, or it shows empty in every row
    inner = getattr(source, "sourceModel", None)
    source = (inner() if inner is not None else None) or source
    column_role = getattr(source, "_column_role", None)

    header = table.horizontalHeader()
    for column, key in enumerate(grid_columns.KEYS):
        attribute = roles.get(key)
        if attribute is None:
            debug.event("grid", "column is in no roles entry - shown "
                                "unconditionally", column=key)
            table.setColumnHidden(column, False)
            continue
        if attribute is NEVER_SHOWN:
            table.setColumnHidden(column, True)
            continue
        fills = True
        if attribute is not ALWAYS_SHOWN and column_role is not None:
            fills = column_role(key) is not None
        shown = (attribute is ALWAYS_SHOWN
                 or (getattr(delegate, attribute, None) is not None
                     and fills))
        table.setColumnHidden(column, not shown)
    if not getattr(table, "_widths_seeded", False):    # seeded ONCE per view: re-applying defaults per call snapped a dragged width back - widths are the USER's, visibility the section's
        table._widths_seeded = True
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive)    # never ResizeToContents as a MODE: it re-measures for the view's life and forbids dragging - research.md ▸ Qt widgets
        header.setMinimumSectionSize(theme.ui_px(panel.COLUMN_MIN_WIDTH))
        for column, key in enumerate(grid_columns.KEYS):
            width = panel.COLUMN_DEFAULT_WIDTH.get(key)
            if width:
                header.resizeSection(column, theme.ui_px(width))
        header.setStretchLastSection(True)    # the LAST column takes the slack; overrides the mode on that section alone, so the others stay draggable


def style_table_header(panel) -> None:
    """Make the real header look like the strip it replaced, and add what a header gives free: click a heading to sort, drag an edge to resize."""
    header = panel.thumbtable.horizontalHeader()
    header.setFixedHeight(panel.HEADER_HEIGHT)
    header.setStretchLastSection(False)
    header.setHighlightSections(False)
    header.setSectionsMovable(False)
    header.setSortIndicatorShown(True)
    header.setSortIndicator(
        grid_columns.KEYS.index("name"),
        QtCore.Qt.SortOrder.AscendingOrder)    # the indicator starts on section 0, the HIDDEN picture column - point it at Name so the arrow is drawn somewhere
    panel.thumbtable.setSortingEnabled(True)    # a user's chosen column survives filter changes and inserts: GridProxyModel re-sorts by sortColumn()
    header.setSectionsClickable(True)    # explicitly: a REPLACEMENT header is not clickable and setSortingEnabled does not repair it (measured, Qt 6.8.3) - without this the arrow shows and every click is swallowed. research.md ▸ Qt widgets
    header.setDefaultAlignment(
        QtCore.Qt.AlignmentFlag.AlignLeft
        | QtCore.Qt.AlignmentFlag.AlignVCenter)
    header.setStyleSheet(
        "QHeaderView { background-color: %s; border: 0; }"
        "QHeaderView::section {"
        "  background-color: %s; color: %s; border: 0;"
        "  border-right: 1px solid %s; padding-left: %dpx;"
        "}" % (
            panel.HEADER_BG.name(), panel.HEADER_BG.name(),
            delegates.AssetItemDelegate.LIST_INK.name(),
            panel.HEADER_DIVIDER.name(), panel.CELL_PAD,
        ))


def apply_view_mode(panel) -> None:
    """Apply the persisted grid/list view mode and sync the toggle controls; a bad state falls back to grid instead of hanging."""
    if not panel.material_model:
        return
    panel._sync_slider_for_mode()
    ts = active_thumbsize(panel)
    try:
        if panel.prefs.view_mode == "list":
            restore_drag_mode(panel)    # the TABLE is list mode; the QListView stays in IconMode, hidden, so the grid is the only thing it ever paints
            show_table(panel, True)
            sync_table_columns(panel)
        else:
            panel.thumblist.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
            restore_drag_mode(panel)
            panel.thumblist.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            panel.thumblist.setAlternatingRowColors(False)
            panel.thumblist.setFlow(QtWidgets.QListView.Flow.LeftToRight)
            panel.thumblist.setWrapping(True)
            panel.thumblist.setIconSize(QtCore.QSize(ts, ts))
            panel.thumblist.setGridSize(
                AssetItemDelegate.grid_cell_size(ts, panel.thumblist.font())
            )    # extra height over the icon for the two text lines
            show_table(panel, False)
        panel.thumblist.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
    except Exception as e:
        debug.event("grid", "view mode switch failed - falling back "
                    "to grid", error=str(e))
        try:
            panel.thumblist.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
            restore_drag_mode(panel)
            panel.thumblist.setGridSize(
                AssetItemDelegate.grid_cell_size(ts, panel.thumblist.font())
            )
            show_table(panel, False)
        except Exception:
            pass
    sync_view_mode_controls(panel)


def sync_view_mode_controls(panel) -> None:
    """Reflect prefs.view_mode on the toggle button and menu - both actions set explicitly so they can never both read as selected, handler re-entry suppressed."""
    panel._suppress_view_signals = True
    try:
        is_list = panel.prefs.view_mode == "list"
        if hasattr(panel, "cb_viewmode"):
            panel.cb_viewmode.setChecked(is_list)
        if getattr(panel, "view_actions", None):
            grid_act = panel.view_actions.get("grid")
            list_act = panel.view_actions.get("list")
            if grid_act is not None:
                grid_act.setChecked(not is_list)
            if list_act is not None:
                list_act.setChecked(is_list)
    finally:
        panel._suppress_view_signals = False


def active_thumbsize(panel) -> int:
    """The icon size for the CURRENT view mode: the remembered one in grid, the fixed one in list."""
    if panel.prefs.view_mode == "list":
        return panel.LIST_THUMB_SIZE
    return panel.prefs.thumbsize
