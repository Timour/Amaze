"""The Grid area: the thumbnail view and the QMenu builder over GRID_MENU tables ▸o/section-api"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.core import debug, grid_columns, grid_engine
from amaze.helpers import theme, ui_helpers
from amaze.panel import delegates
from amaze.pane import menus


def _chip_room():
    """A clear icon the size of a chip: the row keeps its icon column, and the chip is painted over it."""
    pixmap = QtGui.QPixmap(*(theme.ui_px(n) for n in amazetheme.MENU_CHIP[2:]))
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    return QtGui.QIcon(pixmap)


class _ChipMenu(QtWidgets.QMenu):
    """A submenu whose rows show colour chips, at the box `amazetheme.MENU_CHIP` gives inside each row."""

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self.chips = {}    # action -> colour

    def paintEvent(self, event):
        super().paintEvent(event)
        x, y, w, h = (theme.ui_px(n) for n in amazetheme.MENU_CHIP)
        painter = QtGui.QPainter(self)
        for action, colour in self.chips.items():
            row = self.actionGeometry(action)
            painter.fillRect(row.x() + x, row.y() + y, w, h, QtGui.QColor(colour))
        painter.end()


def build_menu(panel, context, entries, indexes, current):
    """The QMenu drawn from the menu engine's rows, its {action: row key}, and the engine's menu."""
    engine = menus.Menu(context, entries, indexes, current, host=panel)
    menu = QtWidgets.QMenu(panel)
    keys = {}
    _draw(menu, panel, engine.rows, keys)
    return menu, keys, engine


def _draw(menu, panel, rows, keys) -> None:
    """Add the engine's rows to `menu`; a row with `rows` is a submenu, one with chips paints them."""
    for row in rows:
        if row.get("separator"):
            menu.addSeparator()
            continue
        if "rows" in row:
            if any(child.get("chip") for child in row["rows"]):    # colour chips: the menu paints them
                submenu = _ChipMenu(row["text"], menu)
                menu.addMenu(submenu)
            else:
                submenu = menu.addMenu(row["text"])
            submenu.menuAction().setEnabled(row["enabled"])    # an openable submenu with nothing to pick looks broken
            _draw(submenu, panel, row["rows"], keys)
            continue
        if row.get("chip"):
            action = menu.addAction(_chip_room(), row["text"])
            menu.chips[action] = row["chip"]
        elif row.get("icon"):    # a ui/ icon, drawn as the Filter menu draws its own
            action = menu.addAction(ui_helpers.menu_icon(row["icon"], panel), row["text"])
        else:
            action = menu.addAction(row["text"])
        action.setEnabled(row["enabled"])
        if "checked" in row:
            action.setCheckable(True)
            action.setChecked(row["checked"])
        keys[action] = row["key"]


def build_grid_menu(panel, context, indexes, current):
    """The Grid's menu table under its own name: the tests and docs refer to the grid menu."""
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
    context.reselect_sidebar_row()    # the right-click moved only the highlight; restore it, picked or not


def selected_current(view, indexes):
    """The row a menu acts on: the current one while selected, else the first, else None."""
    current = grid_columns.live_current_index(view)
    if current is None or not current.isValid() or current not in indexes:
        current = indexes[0] if indexes else None    # Qt keeps a current row OUTSIDE the selection
    return current


def selected_current_in(view, selection):
    """`selected_current` from the selection model: tests one row; builds the list if needed."""
    current = grid_columns.live_current_index(view)
    if current is not None and selection is not None \
            and selection.isSelected(current):
        return current
    return selected_current(view, grid_columns.selected_rows(selection))


def _open(panel, context, entries, indexes, view) -> None:
    """Build a menu, show it and run what was picked; the selection is read once, here."""
    if not entries or view is None:
        return
    current = selected_current(view, indexes)    # the row the menu is about is ALWAYS a selected row

    menu, keys, engine = build_menu(panel, context, entries, indexes, current)    # the engine keeps the rows across Qt's loop
    chosen = menu.exec_(QtGui.QCursor.pos())
    key = keys.get(chosen)    # a dismissed menu and a never-built entry are both None
    menu.deleteLater()    # after the lookup, which is keyed by its QActions ▸r/menu-lifetime
    if key is not None:
        engine.run(key)


def restore_drag_mode(panel) -> None:
    """Re-enable Qt's native file-path drag; call after any setViewMode() ▸r/static-disables-drag"""
    panel.thumblist.setDragEnabled(True)
    panel.thumblist.setDragDropMode(
        QtWidgets.QAbstractItemView.DragDropMode.DragOnly
    )


def sidebar_row_height(panel, table) -> int:
    """One row height for both views: the category list's, else the table delegate's."""
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


def visible_view(panel):
    """The grid view the user is looking at, by isHidden, which also works headless."""
    table = getattr(panel, "thumbrows", None)
    if table is not None and not table.isHidden():
        return table
    return panel.thumblist


def show_rows(panel, showing: bool) -> None:
    """Swap which grid view is visible; both share model and selection."""
    table = getattr(panel, "thumbrows", None)
    if table is None:
        return
    if showing:
        model = table.model()
        if model is not None and model.rowCount():
            table.set_row_height(sidebar_row_height(panel, table))    # the CATEGORY list sets the row height: two delegates measuring separately differed by 2px
        rows_palette = QtGui.QPalette(panel.thumblist.palette())
        rows_palette.setColor(
            QtGui.QPalette.ColorRole.Text, delegates.AssetItemDelegate.TEXT_COLOR)    # resolved through the module, which is reloaded per Houdini session - never bound at import
        table.setPalette(rows_palette)
        table.setFont(panel.thumblist.font())
        table.viewport().setAutoFillBackground(True)    # never a QProxyStyle here ▸r/no-proxystyle
        sync_row_columns(panel)
    page = getattr(panel, "empty_page", None)    # a visible empty page stays visible across a view-mode change, so read its state here
    blank_up = page is not None and not page.isHidden()
    panel._rows_mode = bool(showing)
    apply_grid_face(panel, blank_up)


def grid_pane_layout(panel):
    """The layout holding the grid views; the empty page is added to it."""
    root = getattr(panel, "ui", None)
    if root is None:
        return None
    return root.findChild(QtWidgets.QVBoxLayout, "verticalLayout_7")


def apply_grid_face(panel, blank_up: bool) -> None:
    """The only function that sets the grid pane's visibility: one of table, list and empty page."""
    table = getattr(panel, "thumbrows", None)
    page = getattr(panel, "empty_page", None)
    showing_rows = bool(getattr(panel, "_rows_mode", False))
    if page is not None:
        page.setVisible(bool(blank_up))
    if blank_up and page is not None:
        if table is not None:
            table.setVisible(False)
        panel.thumblist.setVisible(False)
        return
    if table is not None:
        table.setVisible(showing_rows)
    panel.thumblist.setVisible(not showing_rows)


def bind_row_cell_delegates(panel, tile_delegate) -> None:
    """Per-column delegates for cells Qt cannot paint as text, chosen by the active delegate."""
    table = getattr(panel, "thumbrows", None)
    if table is None:
        return

    for previous in getattr(table, "_amaze_cell_delegates", ()):    # previous set first ▸r/replaced-delegate-stays-alive
        try:
            previous.setParent(None)    # leaves the child list at once; deleteLater then frees it under the real event loop
            previous.deleteLater()
        except RuntimeError:
            pass          # already deleted with a rebuilt table
    installed = []

    keys = grid_columns.KEYS
    grid_cell = delegates.GridCellDelegate(table)    # the cell padding and hover text; the host stylesheet draws the selection
    installed.append(grid_cell)
    table.setItemDelegate(grid_cell)
    sources = {    # what each tick column reads and draws
        "favorite": ("_favorite_role", tile_delegate.FAV_MARK_COLOR),
        "open": ("_open_role", tile_delegate.OPEN_MARK_COLOR),
        "comments": ("_notes_role", tile_delegate.NOTE_MARK_COLOR),
    }
    ticks = ((key,) + sources[key]
             for key in grid_engine.GridEngine.TICK_COLUMNS)
    category_cell = delegates.CategoryCellDelegate(tile_delegate, table)
    installed.append(category_cell)
    table.setItemDelegateForColumn(keys.index("category"), category_cell)
    for key, attribute, colour in ticks:
        tick = delegates.TickCellDelegate(
            tile_delegate, getattr(tile_delegate, attribute, None),
            colour, table)
        installed.append(tick)
        table.setItemDelegateForColumn(keys.index(key), tick)
    table._amaze_cell_delegates = installed    # the delegates this call installed, for the next call to remove


def sync_row_columns(panel) -> None:
    """Which columns the table shows, the section's own answer, and their starting widths."""
    table = getattr(panel, "thumbrows", None)
    section = panel.pane.active_section()
    if table is None or section is None:
        return
    shown = section.shown_list_columns()    # the QML list reads the same answer
    for column, key in enumerate(grid_columns.KEYS):
        table.setColumnHidden(column, key not in shown)
    header = table.header()
    if not getattr(table, "_widths_seeded", False):    # default widths set once per view; after that the user's
        table._widths_seeded = True
        header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Interactive)    # never ResizeToContents ▸r/resize-mode-forbids-drag
        header.setMinimumSectionSize(theme.ui_px(panel.COLUMN_MIN_WIDTH))
        for column, key in enumerate(grid_columns.KEYS):
            width = panel.COLUMN_DEFAULT_WIDTH.get(key)
            if width:
                header.resizeSection(column, theme.ui_px(width))
        header.setStretchLastSection(True)    # the last column takes the slack; the others stay draggable


def sync_sort_indicator(panel) -> None:
    """Set the shared header's sort arrow to the bound model's order. ▸r/one-header-many-proxies"""
    table = getattr(panel, "thumbrows", None)
    proxy = table.model() if table is not None else None
    model = proxy.sourceModel() if proxy is not None else None
    if not isinstance(model, grid_engine.GridEngine):
        return
    table.header().setSortIndicator(    # an unchanged arrow emits nothing
        model.sort_column(), model.sort_order())


def set_up_rows_header(panel) -> None:
    """Set up the list's headline, which the style paints; a heading click sorts, an edge drag resizes."""
    header = panel.thumbrows.header()
    header.setFixedHeight(panel.HEADER_HEIGHT)
    header.setStretchLastSection(False)
    header.setHighlightSections(False)
    header.setSectionsMovable(False)
    header.setSortIndicatorShown(True)
    header.setSortIndicator(
        grid_columns.KEYS.index("name"),
        QtCore.Qt.SortOrder.AscendingOrder)    # on Name: section 0 is the hidden picture column
    panel.thumbrows.setSortingEnabled(True)    # a click sorts the MODEL, through the proxy
    header.setSectionsClickable(True)    # needed on a replacement header ▸r/replacement-header-clickable
    header.setDefaultAlignment(
        QtCore.Qt.AlignmentFlag.AlignLeft
        | QtCore.Qt.AlignmentFlag.AlignVCenter)


def apply_view_mode(panel) -> None:
    """Apply the saved grid/list view mode and sync the toggles; a bad state falls back to grid."""
    if not panel.pane.material_model:
        return
    panel._sync_slider_for_mode()
    ts = panel.pane.tile_size()
    try:
        if panel.pane.prefs.view_mode == "list":
            restore_drag_mode(panel)    # list mode is the row list; the QListView stays in IconMode
            show_rows(panel, True)    # show_rows ends with sync_row_columns
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
                delegates.AssetItemDelegate.grid_cell_size(ts, panel.thumblist.font())
            )    # extra height over the icon for the two text lines
            show_rows(panel, False)
        panel.thumblist.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
    except Exception as e:
        debug.event("grid", "view mode switch failed - falling back "
                    "to grid", error=str(e))
        try:
            panel.thumblist.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
            restore_drag_mode(panel)
            panel.thumblist.setGridSize(
                delegates.AssetItemDelegate.grid_cell_size(ts, panel.thumblist.font())
            )
            show_rows(panel, False)
        except Exception:
            pass
    sync_view_mode_controls(panel)


def sync_view_mode_controls(panel) -> None:
    """Show prefs.view_mode on the toggle button and menu, without re-entering the handlers."""
    panel._suppress_view_signals = True
    try:
        is_list = panel.pane.prefs.view_mode == "list"
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
