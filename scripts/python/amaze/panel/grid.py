"""The Grid area: the thumbnail view and the QMenu builder over GRID_MENU tables ▸o/section-api"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.core import debug, grid_columns, grid_engine
from amaze.helpers import theme, ui_helpers
from amaze.panel import delegates




def _resolve(context, name, indexes, current, default):
    """A named fact on the context: an attribute as is, or a method called with the selection."""
    if not name:
        return default
    fact = getattr(context, name, None)
    if callable(fact):
        return bool(fact(indexes, current))
    return bool(fact)


def _enabled(context, entry, indexes, current):
    """Whether an entry is enabled; one lacking what it needs greys out and is never hidden."""
    if entry.needs == "always":
        return True
    if entry.needs == "one":
        return len(indexes) == 1
    if entry.needs == "any":
        return bool(indexes)
    return _resolve(context, entry.needs, indexes, current, False)


def _is_chip(icon) -> bool:
    """A child's icon that is a colour ("#rrggbb"), painted as a chip; any other names a ui/ icon."""
    return bool(icon) and icon.startswith("#")


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
    """The QMenu for one entry table and its {action: (verb, payload)}, without showing it."""
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
            children = getattr(context, entry.children)(indexes, current)
            if any(child and _is_chip(child[2]) for child in children):    # colour chips: the menu paints them
                submenu = _ChipMenu(label, menu)
                menu.addMenu(submenu)
            else:
                submenu = menu.addMenu(label)
            submenu.menuAction().setEnabled(enabled)    # the PARENT carries the enabled state - an openable submenu with nothing to pick reads as broken
            for child in children:    # (label, payload, icon, live[, checked]); None is a divider
                if child is None:
                    submenu.addSeparator()
                    continue
                child_label, payload, icon, live = child[:4]
                checked = child[4] if len(child) > 4 else None
                if _is_chip(icon):
                    action = submenu.addAction(_chip_room(), child_label)
                    submenu.chips[action] = icon
                elif icon:    # a ui/ icon, drawn as the Filter menu draws its own
                    action = submenu.addAction(
                        ui_helpers.menu_icon(icon, panel), child_label)
                else:
                    action = submenu.addAction(child_label)
                action.setEnabled(bool(live))    # greys when it has nothing to act on, as at the top
                if checked is None:
                    verbs[action] = (entry.verb, payload)
                else:    # a toggle: the verb gets the state the user just asked for
                    action.setCheckable(True)
                    action.setChecked(bool(checked))
                    verbs[action] = (entry.verb, (payload, not checked))
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
    context.stand_again()    # the right press moved only the highlight, picked or not


def selected_current(view, indexes):
    """The row a selection is ABOUT: the current one while selected, else the first, else None."""
    current = ui_helpers.live_current_index(view)
    if current is None or not current.isValid() or current not in indexes:
        current = indexes[0] if indexes else None    # Qt keeps a current row OUTSIDE the selection
    return current


def selected_current_in(view, selection):
    """`selected_current` asked of the selection MODEL: one row tested, the list built only on a miss."""
    current = ui_helpers.live_current_index(view)
    if current is not None and selection is not None \
            and selection.isSelected(current):
        return current
    return selected_current(view, grid_columns.selected_rows(selection))


def _open(panel, context, entries, indexes, view) -> None:
    """Build a menu, show it and run what was picked; the selection is read once, here."""
    if not entries or view is None:
        return
    current = selected_current(view, indexes)    # the row the menu is about is ALWAYS a selected row

    menu, verbs = build_menu(panel, context, entries, indexes, current)
    held = [QtCore.QPersistentModelIndex(index) for index in indexes]    # exec_ runs Qt's loop: a model can reset
    held_current = QtCore.QPersistentModelIndex(current) if current is not None else None
    chosen = menu.exec_(QtGui.QCursor.pos())
    verb, payload = verbs.get(chosen, ("", None))    # a dismissed menu and a never-built entry are both None - a dict lookup, never `==` chains
    menu.deleteLater()    # after the lookup, which is keyed by its QActions ▸r/menu-lifetime
    if not verb:
        return
    live = [QtCore.QModelIndex(index) for index in held if index.isValid()]
    if held and not live and _needs(entries, verb) != "always":
        return    # every row the menu was opened on has left the model
    if held_current is not None and held_current.isValid():
        current = QtCore.QModelIndex(held_current)
    else:
        current = live[0] if live else None
    getattr(context, verb)(live, current, payload)


def _needs(entries, verb) -> str:
    """What the entry naming `verb` needs; its submenu rows carry the same verb."""
    return next((entry.needs for entry in entries if entry.verb == verb), "any")


def restore_drag_mode(panel) -> None:
    """Re-arm Qt's native file-path drag; call after any setViewMode() ▸r/static-kills-drag"""
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


ALWAYS_SHOWN = "always-shown"    # distinct objects: absence, always and never are three answers, and two once shared None
NEVER_SHOWN = "never-shown"


def visible_view(panel):
    """The grid view the user is looking at, by isHidden, which also answers headless."""
    table = getattr(panel, "thumbtable", None)
    if table is not None and not table.isHidden():
        return table
    return panel.thumblist


def show_table(panel, showing: bool) -> None:
    """Swap which grid view is visible; both share model and selection."""
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
            header.setMinimumSectionSize(hint)    # the minimum FIRST, or the default is silently clamped to the style's 19 ▸r/min-section-first
            header.setDefaultSectionSize(hint)
        table_palette = QtGui.QPalette(panel.thumblist.palette())    # a QTableView brings the platform's palette: white rows on a dark panel without this
        table_palette.setColor(
            QtGui.QPalette.ColorRole.Text, delegates.AssetItemDelegate.TEXT_COLOR)    # resolved through the module, which is reloaded per Houdini session - never bound at import
        table.setPalette(table_palette)
        table.setFont(panel.thumblist.font())
        table.viewport().setAutoFillBackground(True)    # never a QProxyStyle here ▸r/no-proxystyle
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
    """The one writer of the grid pane's visibility: exactly one of table, list and empty page."""
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
    """Per-column delegates for cells Qt cannot paint as text, chosen by the active delegate."""
    table = getattr(panel, "thumbtable", None)
    if table is None:
        return

    for previous in getattr(table, "_amaze_cell_delegates", ()):    # previous set first ▸r/delegate-orphans
        try:
            previous.setParent(None)    # leaves the child list at once; deleteLater then frees it under the real event loop
            previous.deleteLater()
        except RuntimeError:
            pass          # already gone with a rebuilt table
    installed = []

    keys = grid_columns.KEYS
    grid_cell = delegates.GridCellDelegate(table)    # the cell padding and hover words; selection is the host stylesheet's
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
    table._amaze_cell_delegates = installed    # what this bind owns, for the next one to drop


def sync_table_columns(panel) -> None:
    """Which columns the table shows, by the section, and their starting widths."""
    table = getattr(panel, "thumbtable", None)
    if table is None:
        return
    delegate = (panel.thumblist.itemDelegate()
                if panel.thumblist is not None else None)
    roles = {
        "category": "_category_role", "tags": "_tag_role",
        "license": "_licence_role", "favorite": "_favorite_role",
        "date": "_date_role", "id": "_id_role",
        "open": "_open_role", "comments": "_notes_role",
        "version": "_active_version_role",
        "thumb": NEVER_SHOWN,    # no picture column
        "name": ALWAYS_SHOWN,    # every column NAMED, the always-up pair included - absence once doubled as always-shown
        "type": ALWAYS_SHOWN,
    }
    source = table.model()    # a column shows only if the delegate paints it and the model answers it
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
    if not getattr(table, "_widths_seeded", False):    # widths seeded once per view; then the user's
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
    """Point the one header's arrow at the order the bound MODEL keeps. ▸r/one-header-many-proxies"""
    table = getattr(panel, "thumbtable", None)
    proxy = table.model() if table is not None else None
    model = proxy.sourceModel() if proxy is not None else None
    if not isinstance(model, grid_engine.GridEngine):
        return
    table.horizontalHeader().setSortIndicator(    # an unchanged arrow emits nothing
        model.sort_column(), model.sort_order())


def style_table_header(panel) -> None:
    """Style the table header; a heading click sorts, an edge drag resizes."""
    header = panel.thumbtable.horizontalHeader()
    header.setFixedHeight(panel.HEADER_HEIGHT)
    header.setStretchLastSection(False)
    header.setHighlightSections(False)
    header.setSectionsMovable(False)
    header.setSortIndicatorShown(True)
    header.setSortIndicator(
        grid_columns.KEYS.index("name"),
        QtCore.Qt.SortOrder.AscendingOrder)    # on Name: section 0 is the hidden picture column
    panel.thumbtable.setSortingEnabled(True)    # a click sorts the MODEL, through the proxy
    header.setSectionsClickable(True)    # needed on a replacement header ▸r/replacement-header-clickable
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
    """Apply the saved grid/list view mode and sync the toggles; a bad state falls back to grid."""
    if not panel.material_model:
        return
    panel._sync_slider_for_mode()
    ts = active_thumbsize(panel)
    try:
        if panel.prefs.view_mode == "list":
            restore_drag_mode(panel)    # list mode is the table; the QListView stays in IconMode
            show_table(panel, True)    # whose own last statement is the column sync
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
            show_table(panel, False)
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
            show_table(panel, False)
        except Exception:
            pass
    sync_view_mode_controls(panel)


def sync_view_mode_controls(panel) -> None:
    """Show prefs.view_mode on the toggle button and menu, without re-entering the handlers."""
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
    """The size in force: list's fixed one, else the remembered one - its nearest mark under Step Size."""
    if panel.prefs.view_mode == "list":
        return panel.LIST_THUMB_SIZE
    if panel.prefs.step_size:
        return ui_helpers.ClickSlider.nearest_mark(panel.prefs.thumbsize)
    return panel.prefs.thumbsize
