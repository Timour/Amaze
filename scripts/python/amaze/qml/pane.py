"""The Amaze (QML) pane: its pane-tab widget, its QML view, and the state hosting the engine."""

from PySide6 import QtCore, QtGui, QtQml, QtQuick, QtWidgets
import shiboken6

import amaze
from amaze import amazetheme, tooltips
from amaze.core import debug, grid_columns, grid_engine, locations
from amaze.dialogs import code_window, name_window, save_window, versions_window
from amaze.helpers import ui_helpers
from amaze.pane import asks, drag_session, menus, node_drop, pane as pane_mod, sidebar as pane_sidebar
from amaze.panel import delegates
from amaze.qml import hotkeys
from amaze.utils import rc_calls
from hutil.qt.common import qmlviews    # Houdini's own QML panels' base ▸r/houdini-qml-tabs

PANE_QML = amaze.package_file("ui", "pane", "Pane.qml")
SIZE_SAVE_MS = 500    # the slider's pause before its tile size is saved, as in the widget panel
TILE_BUTTONS = (    # the tile's buttons on its picture, by `tile_badges` ID; art in ui/tile/, "" for none
    {"name": "favourite", "role": "FavoriteRole", "equals": "", "handler": "menu_favourite",
     "art": "tile/favourite", "hover": "tile/favourite_hover", "press": "tile/favourite_on",
     "on": "tile/favourite_on"},    # pressed is drawn as on
    {"name": "execute", "role": "RendererRole", "equals": "Python", "handler": "menu_run",
     "art": "tile/run", "hover": "tile/run_hover", "press": "tile/run_press", "on": ""},
)
TILE_MARKS = (    # the marks on the tile's second line left of a renderer icon, right to left
    {"name": "open", "with": "open", "frames": ("QML T08", "QML T08b"), "layer": "CheckCircle",
     "alone": None, "role": "OpenSceneRole", "art": "tile/open", "off": "tile/open_off",
     "kindRole": "KindRole", "kind": locations.KIND_HIP},    # on every scene file, grey while not open
    {"name": "running", "with": "execute", "frames": ("QML T05", "QML T05B"), "layer": "CheckCircle",
     "alone": None, "role": "RunningRole", "art": "tile/running", "off": "tile/running_off",
     "kindRole": "RendererRole", "kind": "Python"},    # on every snippet Run runs, green while it runs
    {"name": "comment", "with": "comment", "frames": ("QML T23",), "layer": "message-circle",
     "alone": ("QML T24", "icon"), "role": "NotesRole", "art": "tile/comment", "off": "",
     "kindRole": "", "kind": ""},
)    # with: the `tile_badges` ID showing it; alone: its right edge with nothing right of it
RUN_WAIT_LIMIT_MS = 250    # a hidden pane draws nothing: Run's snippet starts anyway after this
RENDERER_MARKS = {    # a material's renderer icon on that line, by the art its model names
    "renderer_materialx": ("QML T24", "icon", "tile/materialx"),
    "renderer_redshift": ("QML T25", "icon", "tile/redshift"),
    "renderer_octane": ("QML T26", "renderer icon", "tile/octane"),
}


class TilePictures(QtQuick.QQuickImageProvider):
    """`image://amazetile/...`: a tile's painted picture, made on the main thread, kept nowhere."""

    def __init__(self, state) -> None:
        super().__init__(QtQml.QQmlImageProviderBase.ImageType.Image)
        self._state = state

    def requestImage(self, key: str, size: QtCore.QSize, requested: QtCore.QSize) -> QtGui.QImage:
        image = None
        try:    # the shown grid's model paints it, if the url is that model's
            token, row = key.split("/")[:2]
            proxy = self._state.gridModel
            model = proxy.sourceModel() if proxy is not None else None
            if model is not None and "%x" % id(model) == token:
                image = model.paint_tile(int(row))
        except (RuntimeError, ValueError):    # the pane closed, or a url not made by `picture_for_view`
            image = None
        if image is None or image.isNull():    # a null image is an error in the QML log: a clear dot instead
            image = QtGui.QImage(1, 1, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QtCore.Qt.GlobalColor.transparent)
        elif requested.isValid() and (image.width() > requested.width() or image.height() > requested.height()):
            image = image.scaled(requested, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                 QtCore.Qt.TransformationMode.SmoothTransformation)
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image


def badge_rows(section) -> list:
    """The section's buttons on the tile's picture: the role each reads, its arts, its place."""
    places = amazetheme.drawn_qml_buttons()
    rows = []
    for button in TILE_BUTTONS:
        if button["name"] not in section.tile_badges:
            continue
        clicks = bool(section.tile_badge_clicks)    # where False, a state shown, no hover and no click
        rows.append(dict(places[button["name"]], name=button["name"],
                         role=grid_engine.role_name(button["role"]), equals=button["equals"],
                         art=button["art"] if clicks else "", hover=button["hover"] if clicks else "",
                         press=button["press"] if clicks else "", on=button["on"], button=clicks))
    return rows


def mark_rows(section) -> list:
    """The section's marks on the tile's second line, right to left, each with its drawn box."""
    rows = []
    for mark in TILE_MARKS:
        if mark["with"] not in section.tile_badges:
            continue
        drawn = amazetheme.drawn_line_mark(mark["frames"], mark["layer"])
        alone = amazetheme.drawn_line_mark(mark["alone"][:1], mark["alone"][1]) if mark["alone"] else drawn
        rows.append(dict(drawn, inset=alone["inset"], role=grid_engine.role_name(mark["role"]),
                         art=mark["art"], off=mark["off"], kind=mark["kind"],
                         kindRole=grid_engine.role_name(mark["kindRole"]) if mark["kindRole"] else ""))
    return rows


def list_columns(section) -> list:
    """Per column for `RowsTable`: L01's starting width, 0 where its list hides it, and if a tick."""
    shown, widths = section.shown_list_columns(), amazetheme.drawn_list()["widths"]
    return [{"width": widths[key] if key in shown else 0, "tick": key in grid_engine.GridEngine.TICK_COLUMNS}
            for key in grid_columns.KEYS]


def network_background() -> str:
    """The network editor's background as Houdini's theme sets it; headless, the measured one."""
    import hou
    ui = getattr(hou, "ui", None)    # hython has no interface, so no theme colours
    if ui is None:
        return amazetheme.GRID_BACK
    return QtGui.QColor.fromRgbF(*ui.colorFromName("GraphBackground").rgb()).name()


def drawn_tile() -> dict:
    """For `Tile`: the spacing of T01, the strip of QML T20, the gap between marks, each renderer icon."""
    marks = {model_art: dict(amazetheme.drawn_line_mark((frame,), layer), art=art)
             for model_art, (frame, layer, art) in RENDERER_MARKS.items()}
    return dict(amazetheme.drawn_tile(), strip=amazetheme.drawn_category_strip("QML T20"),
                card=amazetheme.TILE_GROUND, back=network_background(), least=amazetheme.BADGE_LEAST,
                markGap=amazetheme.drawn_mark_gap("QML T23", "message-circle", "icon"), renderers=marks)


class PaneState(qmlviews.SharedState, asks.Asks):
    """The QML side of the pane's host: what the QML shows, fed by the engine, and the asks it answers."""

    toolbar: dict = {}    # frame B01's figures, which place the toolbar's parts
    strip: dict = {}    # frame S01's height and left edge
    tips: dict = {}
    words: dict = {}
    tabs: list = []    # `ui_helpers.section_tab_rows` for the engine's tabs
    currentTab: int = 0
    online: bool = False
    onlinePossible: bool = False
    onlineColor: str = amazetheme.ONLINE_ICON_COLOR
    viewMode: str = "grid"
    favouritesOnly: bool = False
    takesFavourites: bool = True
    filterOffered: bool = False    # the Filter button has a menu here
    filterTip: str = ""    # what the Filter button narrows by, per section; online, the kind
    tileSizes: list = list(amazetheme.TILE_SIZES)
    tileSize: int = amazetheme.TILE_SIZES[1]
    tileStepped: bool = False
    searchHint: str = ""
    progressShown: bool = False
    progressDone: int = 0
    progressTotal: int = 0
    emptyHeadline: str = ""
    emptySentence: str = ""
    emptyButton: str = ""
    sidebar: dict = {}    # frame G01's figures: the sidebar's width and its colour bar
    sidebarModel: QtCore.QAbstractItemModel = None    # the shown section's sidebar rows
    sidebarSelection: QtCore.QObject = None    # this pane's one selection of them, which the engine moves
    sidebarCounts: bool = True
    sidebarShown: bool = True
    prefsOpen: bool = False    # the Preferences button shows its on state while the window is open
    sidebarWidth: float = 0.0    # in the pane's design px
    gridModel: QtCore.QAbstractItemModel = None    # the shown section's tiles, the proxy the widget grid shows
    gridSelection: QtCore.QObject = None    # the section's own selection of them, the engine's
    tile: dict = {}    # `drawn_tile`
    badges: list = []    # `badge_rows` of the shown section
    marks: list = []    # `mark_rows` of the shown section
    table: dict = {}    # frame L01's figures: the header's height, the text's inset, the tick's box
    listColumns: list = []    # `list_columns` of the shown section
    sortColumn: int = -1    # the column the shown rows are sorted by, the model's own sort
    sortDescending: bool = False

    searchCleared = QtCore.Signal()    # the empty state's Clear Search: the QML empties its field
    keyStepped = QtCore.Signal(str, bool)    # a move by Houdini's hotkey: its name, and if Shift extends
    sidebarOpened = QtCore.Signal(QtCore.QModelIndex)    # the tree opens this folder and those above it
    menuOffered = QtCore.Signal("QVariantList", QtCore.QPoint)    # the engine's menu at a screen point

    pane = None    # the engine, built by `start`
    drag = None    # the view's `drag_session`, which a press on a tile or row past the drag distance begins
    reorder = None    # the view's `SidebarReorder`, which a press on a sidebar row past it begins
    after_paint = None    # the view's `AfterPaint`, which `after_drawn` waits on
    os_file_icon = staticmethod(delegates.os_file_icon)    # held by the shared File model

    def after_drawn(self, then) -> None:
        """`then()` once the pane's change is in Houdini's window ▸r/qml-on-screen-before-a-block."""
        if self.after_paint is None:    # no view yet: nothing is on screen to wait for
            then()
            return
        self.after_paint.wait(then)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tab_keys = []
        self._empty_handler = ""
        self._sidebar_selection = QtCore.QItemSelectionModel(None, self)    # Qt's tree points it at each list
        self._sidebar_selection.currentChanged.connect(self._sidebar_row_moved)
        self.sidebarSelection = self._sidebar_selection
        self._prefs_window = None
        self._size_save = QtCore.QTimer(self)
        self._size_save.setSingleShot(True)
        self._size_save.setInterval(SIZE_SAVE_MS)
        self._size_save.timeout.connect(self._save_prefs)
        self._key_pause = QtCore.QTimer(self)    # the arrow keys' pause, as the widget panel's
        self._key_pause.setSingleShot(True)
        self._key_pause.setInterval(pane_sidebar.KEY_PAUSE_MS)
        self._key_pause.timeout.connect(self._show_key_choice)
        self._key_start = QtCore.QPersistentModelIndex()    # the current row when the keys began
        self._app_moves_row = False    # the app is moving the sidebar's current row: no choice
        self._reveal = ""    # a File folder highlighted once the walks have given it a row
        self._rows_followed = None
        self._grid_anchor = QtCore.QPersistentModelIndex()    # where a Shift click's span starts
        self._menu = None    # the open menu's engine, which runs its picked row
        self._after_menu = None    # what the open menu puts back once it has closed, picked or not
        self.tile = drawn_tile()
        self.table = amazetheme.drawn_list()
        tabs = amazetheme.drawn_tabs()
        self.toolbar = dict(amazetheme.drawn_toolbar(), end_gap=amazetheme.TOOLBAR_SEARCH_END_GAP,
                            field_text=amazetheme.TOOLBAR_FIELD_TEXT, on=amazetheme.TOOLBAR_ON)
        self.strip = {"height": tabs["height"], "left": tabs["left"]}
        self.tips = {"online": tooltips.PANEL_ONLINE, "favourites": tooltips.PANEL_FAVORITES,
                     "viewMode": tooltips.PANEL_VIEW_MODE, "viewMenu": tooltips.PANEL_VIEW_MENU,
                     "prefs": tooltips.PANEL_PREFERENCES,
                     "tileSize": tooltips.PANEL_TILE_SIZE, "tileSizeList": tooltips.PANEL_TILE_SIZE_LIST,
                     "search": tooltips.PANEL_SEARCH, "sidebar": tooltips.PANEL_CATEGORIES}
        self.words = {"cancel": amazetheme.BTN_CANCEL, "search": "Search"}
        self.sidebar = amazetheme.drawn_sidebar()

    def start(self) -> None:
        """Build this pane's engine, follow it, and open the library; Qt deletes the engine with this."""
        pane = self.pane = pane_mod.Pane(self, self)
        pane.tabs_changed.connect(self._show_tabs)
        pane.context_bound.connect(self._use_sidebar_rows)
        pane.context_bound.connect(self._show_grid)
        pane.grid_reordered.connect(self._show_sort)    # sorted here, or in another pane on the same model
        pane.context_shown.connect(self._show_context)
        pane.online_changed.connect(self._show_online)
        pane.sidebar_highlight.connect(self._highlight_sidebar_row)
        pane.sidebar_reveal.connect(self._reveal_folder)
        pane.library_shown.connect(self._show_settings)
        pane.library_switched.connect(self._show_settings)
        pane.library_updated.connect(self._refresh_open_prefs)
        pane.progress_shown.connect(self._show_progress)
        pane.progress.connect(self._set_progress)
        pane.empty_changed.connect(self._show_empty)
        pane.filter_changed.connect(self._show_filter)
        self._show_tabs()
        self._show_settings()
        pane.library.start()

    def _show_tabs(self) -> None:
        segments = self.pane.tabs()
        self._tab_keys = [key for key, _label in segments]
        self.tabs = ui_helpers.section_tab_rows(segments)
        self.currentTab = self._tab_keys.index(self.pane.current_tab())

    def _use_sidebar_rows(self, section) -> None:
        """The section's sidebar rows on the tree, and the one selection of them to the engine."""
        listed = getattr(self.pane, section.sidebar_attr, None) if section.sidebar_attr else None
        if listed is None:
            return
        self._key_pause.stop()    # the keys' row was the other section's
        self._sidebar_selection.clear()    # the old rows unmarked while the tree still shows them
        self.sidebarModel = listed    # Qt's tree points the selection at these rows as it takes them
        self.pane.sidebar.use_selection(self._sidebar_selection)
        self._reveal = ""
        if self._rows_followed is not listed:    # a reveal waits for rows the walks insert
            try:
                self._rows_followed.rowsInserted.disconnect(self._reveal_step)
            except (AttributeError, RuntimeError, TypeError):    # none yet, or deleted with its library
                pass
            self._rows_followed = listed
            listed.rowsInserted.connect(self._reveal_step)

    def _show_grid(self, section) -> None:
        """The section's tiles, its own selection of them and its badges, as the widget grid binds them."""
        proxy = getattr(self.pane, section.proxy_attr, None) if section.proxy_attr else None
        self._grid_anchor = QtCore.QPersistentModelIndex()
        self.badges = badge_rows(section)
        self.marks = mark_rows(section)
        self.listColumns = list_columns(section)
        self._show_rows("grid", proxy, section.grid_selection_model() if proxy is not None else None)
        self._show_sort()

    def _show_sort(self) -> None:
        """The heading the shown rows are sorted by and its direction, read off the model's own sort."""
        model = self.gridModel.sourceModel() if self.gridModel is not None else None
        sorted_here = isinstance(model, grid_engine.GridEngine)
        self.sortColumn = model.sort_column() if sorted_here else -1
        self.sortDescending = sorted_here and model.sort_order() == grid_engine.DESCENDING

    def _show_rows(self, view: str, rows, selection) -> None:
        """A view's rows, then its selection: Qt's view points any selection it holds at its rows."""
        setattr(self, view + "Selection", None)
        setattr(self, view + "Model", rows)
        setattr(self, view + "Selection", selection)

    def _highlight_sidebar_row(self, index) -> None:
        """The app's move: the row is current and selected, and nothing is chosen."""
        if self._sidebar_selection is not None and index.model() is self._sidebar_selection.model():
            flag = QtCore.QItemSelectionModel.SelectionFlag
            self._app_moves_row = True
            try:
                self._sidebar_selection.setCurrentIndex(index, flag.ClearAndSelect | flag.Rows)
            finally:
                self._app_moves_row = False

    def _reveal_folder(self, path: str) -> None:
        """Open the folders down to `path` as the walks give them rows, then highlight it; File only."""
        self._reveal = path
        self._reveal_step()

    def _reveal_step(self, *_rows) -> None:
        model, path = self.pane.sidebar.model, self._reveal
        if not path or model is None or not hasattr(model, "key_above"):
            return
        index = model.index_of(path)
        if index.isValid():
            self._reveal = ""
            self.pane.sidebar.highlight(index)    # the app's move: the folder is browsed already
            index = index.parent()
        else:    # the deepest folder above it that has a row: opening it reads the next one
            key = model.key_above(path.rstrip("/"))
            while key and not model.index_of(key).isValid():
                key = model.key_above(key)
            index = model.index_of(key) if key else QtCore.QModelIndex()
        if index.isValid():
            self.sidebarOpened.emit(index)

    def _show_context(self, context) -> None:
        """The shown context's tab and what its toolbar offers."""
        self.currentTab = self._tab_keys.index(self.pane.current_tab())
        self.takesFavourites = bool(getattr(context, "takes_favourites", True))
        self.searchHint = getattr(context, "search_hint", "")
        self._show_filter()

    def _show_filter(self) -> None:
        """Whether the Filter button opens a menu here, and its tip: the section's, or online the kind's."""
        toolbar = self.pane.toolbar_menus
        self.filterOffered = toolbar.filter_offered()
        context = self.pane.active_section()
        self.filterTip = (tooltips.PANEL_KIND_FILTER if toolbar.kinds_shown()
                          else getattr(context, "filter_tooltip", ""))

    def _show_online(self) -> None:
        self.online = self.pane.is_online()
        self.onlinePossible = getattr(self.pane, "matx_online_model", None) is not None

    def _show_settings(self) -> None:
        prefs = self.pane.prefs
        self.viewMode = prefs.view_mode
        self.tileStepped = bool(prefs.step_size)
        self.tileSize = self.pane.tile_size("grid")    # the list shows no pictures: no list size
        self.sidebarShown = bool(prefs.show_categories)
        self.sidebarCounts = bool(prefs.sidebar_counts)
        drawn = self.sidebar["width"]    # the last dragged width, never wider than drawn
        self.sidebarWidth = min(prefs.sidebar_width / self.uiScale, drawn) if prefs.sidebar_width else drawn

    def _show_progress(self, visible: bool) -> None:
        self.progressShown = bool(visible)

    def _set_progress(self, done: int, total: int) -> None:
        self.progressDone, self.progressTotal = done, total

    def _show_empty(self) -> None:
        """The engine's empty state, its button only where this host has the handler it names."""
        blank, detail = self.pane.empty_state.verdict()
        headline, sentence, label, handler = (
            self.pane.empty_state.words(blank, detail) if blank else ("", "", "", ""))
        self._empty_handler = handler if callable(getattr(self, handler or "", None)) else ""
        self.emptyHeadline, self.emptySentence = headline, sentence
        self.emptyButton = label if self._empty_handler else ""

    @QtCore.Slot(int)
    def chooseTab(self, index: int) -> None:
        if 0 <= index < len(self._tab_keys) and self._tab_keys[index] != self.pane.current_tab():
            self.pane.choose_tab(self._tab_keys[index])

    def _sidebar_row_moved(self, current, _previous) -> None:
        """Qt's tree moved the current row for the user's click: the grid shows it at once."""
        if self._app_moves_row or not current.isValid() or self._key_pause.isActive():
            return    # the app's move chooses nothing; a key's row is shown once the keys pause
        self._reveal = ""    # the user's row, not the one the app was opening the folders to
        self.pane.sidebar.show_row(current)

    @QtCore.Slot()
    def stepSidebar(self) -> None:
        """An arrow key in the sidebar: the row Qt's keys stop on is shown once they pause, if it moved."""
        if not self._key_pause.isActive():
            current = self.pane.sidebar.current()
            self._key_start = QtCore.QPersistentModelIndex(current if current is not None
                                                           else QtCore.QModelIndex())
        self._key_pause.start()

    def _show_key_choice(self) -> None:
        current = self.pane.sidebar.current()
        if current is not None and current != QtCore.QModelIndex(self._key_start):
            self._reveal = ""
            self.pane.sidebar.show_row(current)

    @QtCore.Slot(int, int)
    def clickTile(self, row: int, modifiers: int) -> None:
        """The user's click on tile or row `row`, -1 for none, as Qt's views take it; Ctrl/Cmd, Shift."""
        self._choose(row, modifiers, by_key=False)

    @QtCore.Slot(int, int)
    def keyTile(self, row: int, modifiers: int) -> None:
        """The user's move by key landing on `row`, as Qt's views take it."""
        self._choose(row, modifiers, by_key=True)

    def run_key(self, name: str, extend: bool) -> None:
        """An Amaze hotkey: select all here; a move goes to the shown grid or list, which knows its rows."""
        if name == hotkeys.SELECT_ALL:
            self.selectAllTiles()
        else:
            self.keyStepped.emit(name, extend)

    @QtCore.Slot()
    def selectAllTiles(self) -> None:
        """Ctrl/Cmd+A: every row of the shown section, as Qt's views select all."""
        rows = self.gridModel.rowCount() if self.gridModel is not None else 0
        if self.gridSelection is not None and rows:
            flag = QtCore.QItemSelectionModel.SelectionFlag
            self.gridSelection.select(QtCore.QItemSelection(self.gridModel.index(0, 0), self.gridModel.index(rows - 1, 0)),
                                      flag.Select | flag.Rows)

    def _choose(self, row: int, modifiers: int, by_key: bool) -> None:
        """Qt's extended selection: Shift spans from the anchor; Ctrl/Cmd toggles a click, moves a key."""
        selection = self.gridSelection
        if selection is None or self.gridModel is None:
            return
        flag = QtCore.QItemSelectionModel.SelectionFlag
        keys = QtCore.Qt.KeyboardModifier(modifiers)
        span, toggle = keys & QtCore.Qt.KeyboardModifier.ShiftModifier, keys & QtCore.Qt.KeyboardModifier.ControlModifier
        index = self.gridModel.index(row, 0) if row >= 0 else QtCore.QModelIndex()
        if not index.isValid():
            if not (span or toggle):
                selection.clearSelection()
            return
        if span:
            anchor = QtCore.QModelIndex(self._grid_anchor)
            anchor = anchor if anchor.isValid() else index
            selection.select(QtCore.QItemSelection(anchor, index), flag.SelectCurrent | flag.Rows)
            selection.setCurrentIndex(index, flag.NoUpdate)
            return
        if toggle and by_key:
            selection.setCurrentIndex(index, flag.NoUpdate)
            return
        selection.setCurrentIndex(index, (flag.Toggle if toggle else flag.ClearAndSelect) | flag.Rows)
        self._grid_anchor = QtCore.QPersistentModelIndex(index)

    @QtCore.Slot(int)
    def doubleClickTile(self, row: int) -> None:
        """The user's double-click on tile or row `row`: the pane's, as the widget grid's."""
        if self.gridModel is not None and row >= 0:
            self.pane.double_click(self.gridModel.index(row, 0))

    @QtCore.Slot(int, int)
    @debug.guarded("PaneState.dragTile")
    def dragTile(self, row: int, modifiers: int) -> None:
        """A press on tile or row `row` moved past the drag distance: the drag out of the pane begins."""
        key = self.pane.current_section
        index = self.gridModel.index(row, 0) if self.gridModel is not None and row >= 0 else QtCore.QModelIndex()
        if self.drag is None or not index.isValid() or not drag_session.drags(self.pane, key):
            return
        if self.gridSelection is not None and not self.gridSelection.isSelected(index):
            self._choose(row, modifiers, by_key=False)    # as Qt's views select an unselected row at its press
        self.drag.begin(self.pane, key, index, index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
                        sidebar=SidebarDrop(self.drag.source))

    @QtCore.Slot(QtCore.QModelIndex)
    def dragSidebarRow(self, index: QtCore.QModelIndex) -> None:
        """A press on sidebar row `index` moved past the drag distance: the row may move between rows."""
        if self.reorder is not None and index.isValid():
            self.reorder.begin(index)

    @QtCore.Slot(int, result="QVariantList")
    def tileMenu(self, row: int) -> list:
        """The rows of the right-click menu on tile or row `row`; as in Qt's views, it selects it first."""
        context = self.pane.active_section()
        entries = getattr(context, "GRID_MENU", ()) if context is not None else ()
        if not entries or self.gridModel is None or self.gridSelection is None:
            return []
        index = self.gridModel.index(row, 0) if row >= 0 else QtCore.QModelIndex()
        if not index.isValid() or not self.gridSelection.isSelected(index):
            self._choose(row, 0, by_key=False)
        indexes = context.grid_selection()
        current = index if index.isValid() and index in indexes else (indexes[0] if indexes else None)
        self._menu = menus.Menu(context, entries, indexes, current, host=self)
        return self._menu.rows

    @QtCore.Slot(QtCore.QModelIndex, result="QVariantList")
    def sidebarMenu(self, index: QtCore.QModelIndex) -> list:
        """The sidebar's right-click menu on row `index`; the row shown comes back once it closes."""
        context = self.pane.active_section()
        entries = getattr(context, "SIDEBAR_MENU", ()) if context is not None else ()
        if not entries or self._sidebar_selection is None:
            return []
        if index.isValid() and not self._sidebar_selection.isSelected(index):
            self.pane.sidebar.highlight(index)    # as Qt's list moves its highlight on a right press
        indexes = context.sidebar_selection()
        current = index if index.isValid() and index in indexes else (indexes[0] if indexes else None)
        self._menu = menus.Menu(context, entries, indexes, current, host=self)
        self._after_menu = context.reselect_sidebar_row    # the old panel's own put-back
        return self._menu.rows

    @QtCore.Slot()
    @debug.guarded("PaneState.menuClosed")
    def menuClosed(self) -> None:
        """The open menu closed, after its pick if any: what it moved is put back."""
        after, self._after_menu = self._after_menu, None
        self._menu = None
        if after is not None:
            after()

    @QtCore.Slot(str, result="QVariantList")
    def toolbarMenu(self, name: str) -> list:
        """The rows of a toolbar button's menu, "view" or "filter"; `pickMenu` runs the one picked."""
        self._menu = self.pane.toolbar_menus.menu(name, host=self)
        return self._menu.rows[0].get("rows", [])

    @QtCore.Slot(str)
    def pickMenu(self, key: str) -> None:
        """The picked row of the open menu: the engine runs it on the rows still there."""
        menu, self._menu = self._menu, None
        if menu is not None:
            menu.run(key)

    def ask_drop_choice(self, labels: list, then, at) -> None:
        """A menu at `at`, not waited on: once it closes, `then` gets the place picked, or None."""
        choice = menus.Choice(labels)
        menu = choice.menu(host=self)
        self._menu, self._after_menu = menu, lambda: then(choice.place)
        self.menuOffered.emit(menu.rows[0].get("rows", []), at)    # a menu that cannot open closes at once

    def ask_name(self, title: str, default: str, then) -> None:
        """The Name window, not modal: `then` gets the name, "" for a cleared field, None for Cancel."""
        name_window.ask(self, title, default, then)

    def open_versions(self, name: str, listed: list, active: int, then) -> None:
        """The Versions window, not modal: `then` gets the version picked on Select or Delete."""
        versions_window.ask(self, name, listed, active, then)

    def open_save(self, question, then) -> None:
        """The Save window, not modal: `then` gets a SaveAnswer on OK, None for Cancel."""
        save_window.ask(self, question, then)

    def open_code(self, question, apply) -> None:
        """The code window, not modal: each Apply hands `apply` a CodeAnswer; a close hands on nothing."""
        code_window.ask(self, question, apply)

    def ask_colour(self, start: str, title: str, then) -> None:
        """Houdini's colour picker, the one the widget panel opens: `then` gets "#rrggbb", None for Cancel."""
        chosen = ui_helpers.pick_color(start, None, title)
        then(chosen.name() if chosen is not None else None)

    @QtCore.Slot(int)
    def sortList(self, column: int) -> None:
        """A heading's click: the proxy's own sort, by Qt's header rule; the same heading reverses it."""
        model = self.gridModel.sourceModel() if self.gridModel is not None else None
        if not isinstance(model, grid_engine.GridEngine):
            return
        again = column == model.sort_column() and model.sort_order() == grid_engine.ASCENDING
        self.gridModel.sort(column, grid_engine.DESCENDING if again else grid_engine.ASCENDING)
        self._show_sort()

    @QtCore.Slot(QtGui.QColor, result=QtGui.QColor)
    def listInk(self, colour) -> QtGui.QColor:
        """A cell's own colour, Category's, made readable on Houdini's list ground as the widget list's."""
        ground = QtGui.QColor(self.theme.viewSurface)    # the palette base of Houdini's widget lists
        return delegates.AssetItemDelegate.readable_on(QtGui.QColor(colour), ground)

    @QtCore.Slot(int, str)
    def clickBadge(self, row: int, name: str) -> None:
        """The user's click on a tile's badge: the section's handler for it, by the engine's rule."""
        handler = next((button["handler"] for button in TILE_BUTTONS if button["name"] == name), "")
        if handler and self.gridModel is not None:
            self.pane.assets.click_badge(handler, self.gridModel.index(row, 0))

    @QtCore.Slot(bool)
    def showSidebar(self, on: bool) -> None:
        """The toolbar's sidebar button: shown or hidden, remembered as the widget panel does."""
        self.pane.prefs.show_categories = bool(on)
        self.pane.prefs.save()
        self.sidebarShown = bool(on)

    @QtCore.Slot(float)
    def keepSidebarWidth(self, width: float) -> None:
        """A drag of the split ended: the width is kept in the widget panel's px, as its drags are."""
        if width <= 0:
            return    # a sidebar dragged shut keeps the width it had, as the widget panel's
        self.pane.prefs.sidebar_width = int(round(width * self.uiScale))
        self.pane.prefs.save()
        self.sidebarWidth = width

    @QtCore.Slot(bool)
    def setOnline(self, on: bool) -> None:
        if on:
            self.pane.enter_online()
        else:
            self.pane.leave_online()

    @QtCore.Slot(str)
    def setViewMode(self, mode: str) -> None:
        self.pane.set_view_mode(mode)
        self._show_settings()

    @QtCore.Slot(bool)
    def showFavouritesOnly(self, on: bool) -> None:
        self.pane.show_favourites_only(on)
        self.favouritesOnly = self.pane.favourites_only

    @QtCore.Slot(int)
    def setTileSize(self, size: int) -> None:
        """The slider moved: the grid's tile size, saved once the slider rests."""
        self.pane.prefs.thumbsize = int(size)
        self.tileSize = self.pane.tile_size("grid")
        self._size_save.start()

    def save_size(self) -> None:
        """Save now a tile size the slider set and the pause has not saved yet."""
        if self._size_save.isActive():
            self._size_save.stop()
            self._save_prefs()

    def _save_prefs(self) -> None:
        self.pane.prefs.save()

    @QtCore.Slot(str)
    def typeSearch(self, text: str) -> None:
        self.pane.type_search(text)

    @QtCore.Slot()
    def showPrefs(self) -> None:
        self.show_prefs()

    @QtCore.Slot()
    def cancelWork(self) -> None:
        self.pane.cancel_work()

    @QtCore.Slot()
    def pressEmptyButton(self) -> None:
        if self._empty_handler:
            getattr(self, self._empty_handler)()

    def clear_filter_box(self) -> None:
        """The empty state's Clear Search: the QML's field is emptied, which filters."""
        self.searchCleared.emit()

    def clear_favourites_filter(self) -> None:
        """The empty state's Show All."""
        self.showFavouritesOnly(False)

    def locate_unreadable_folder(self) -> None:
        """The empty state's Locate: the folder it names is re-pointed."""
        self.pane.files.locate_unreadable(self.pane.empty_state.unreadable_folder())

    def show_prefs(self, page: str = "") -> None:
        """Preferences, one window per pane as in the widget panel; a second open raises it."""
        from amaze.dialogs import prefs_window
        self.save_size()
        window = self._prefs_window
        try:
            open_now = window is not None and window.isVisible()
        except RuntimeError:    # closed: the window deleted itself, as Houdini's does
            open_now = False
        if not open_now:
            window = self._prefs_window = prefs_window.AmazePrefsWindow(self.pane.prefs, pane=self.pane)
            window.sharedState().applied.connect(self._apply_preferences)    # Apply, and Accept
            window.closed.connect(self._apply_preferences)    # any close: a library chosen behind it opens
            window.closed.connect(self._prefs_closed)
            self.destroyed.connect(window.close)    # the window must not outlive the pane it applies to
        window.show()
        self.prefsOpen = True
        window.raise_()
        window.requestActivate()
        if page:
            window.setPageName(page)

    def _prefs_closed(self) -> None:
        if shiboken6.isValid(self):    # the pane closed first
            self.prefsOpen = False

    def _apply_preferences(self) -> None:
        if not shiboken6.isValid(self):    # the pane closed first
            return
        self.pane.apply_preferences()
        self._show_settings()

    def _refresh_open_prefs(self) -> None:
        """An open Preferences window shows the library's new version."""
        try:
            if self._prefs_window is not None:
                self._prefs_window.sharedState().refresh_library_version()
        except RuntimeError:    # closed and deleted
            self._prefs_window = None


class AfterPaint(QtCore.QObject):
    """Runs what waits once a newer frame is on screen. ▸r/qml-on-screen-before-a-block"""

    def __init__(self, view) -> None:
        super().__init__(view)    # the view is reached as the Qt parent: no Python cycle through the state
        self._waiting = []
        self._rendered = False    # a frame was drawn since the wait began
        self._limit = QtCore.QTimer(self)
        self._limit.setSingleShot(True)
        self._limit.setInterval(RUN_WAIT_LIMIT_MS)
        self._limit.timeout.connect(self._release)
        view.installEventFilter(self)

    def wait(self, then) -> None:
        """`then()` after the next frame drawn and painted, or after the limit."""
        if not self._waiting:
            self._rendered = False
            self.parent().quickWindow().afterRendering.connect(self._on_rendered)
            self._limit.start()
        self._waiting.append(then)

    def _on_rendered(self) -> None:
        self._rendered = True

    def eventFilter(self, watched, event) -> bool:
        if self._waiting and self._rendered and event.type() == QtCore.QEvent.Type.Paint:
            self._rendered = False
            QtCore.QTimer.singleShot(0, self._release)
        return False

    def _release(self) -> None:
        if not self._waiting:
            return
        self._limit.stop()
        self.parent().quickWindow().afterRendering.disconnect(self._on_rendered)
        waiting, self._waiting = self._waiting, []
        for then in waiting:
            then()


class PaneView(qmlviews.BaseQmlWidget):
    """The pane's QML, made as Houdini makes its own QML panels."""

    SOURCE_URL = QtCore.QUrl.fromLocalFile(PANE_QML).toString()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        hotkeys.watch(self)    # Amaze's hotkey context is active for this pane
        # Qt's context menu request, as the widget grid takes it: answered here, never passed up to Houdini
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.drag = self.sharedState().drag = drag_session.DragSession(self, ui_helpers.DragMarks())
        self.reorder = self.sharedState().reorder = SidebarReorder(self)
        self.sharedState().after_paint = AfterPaint(self)
        self._drag_held = False    # a drag's left button is still down: another button goes nowhere
        self._node_drag = False    # Qt's drag over the pane carries scene nodes: the pane saves them

    def _context_menu(self, at) -> None:
        """The pane's menu for whatever is under `at`, as the QML finds it."""
        QtCore.QMetaObject.invokeMethod(self.rootObject(), "menuAt", QtCore.Qt.ConnectionType.DirectConnection,
                                        QtCore.Q_ARG("QVariant", at.x()), QtCore.Q_ARG("QVariant", at.y()))

    def _makeSharedState(self) -> PaneState:
        return PaneState()

    def setupEngine(self) -> None:
        self.engine().addImageProvider(grid_engine.PAINTED, TilePictures(self.sharedState()))

    def event(self, event) -> bool:
        """Qt's shortcut override: the pane claims the keys it acts on, or Houdini's hotkey takes them."""
        if event.type() == QtCore.QEvent.Type.ShortcutOverride:
            return self._route(event, lambda: super(PaneView, self).event(event), act=False)
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if self._gesture() is not None and event.key() == QtCore.Qt.Key.Key_Escape:    # it ends any drag
            self._gesture().cancel()
            event.accept()
            return
        self._route(event, lambda: super(PaneView, self).keyPressEvent(event), act=True)

    def _route(self, event, to_qt_quick, act: bool) -> bool:
        """In the grid or list Amaze's hotkeys first, elsewhere the focused item; what is left to Houdini."""
        focused = self.quickWindow().activeFocusItem()
        first = focused is None or _takes_hotkeys_first(focused)    # Qt's ScrollView scrolls on arrows
        if first and self._amaze_key(event, act):
            return True
        if focused is not None:    # with none, Qt Quick would still mark the key taken
            to_qt_quick()
            if event.isAccepted():
                return True
        if not first and self._amaze_key(event, act):
            return True
        event.ignore()
        return False

    def _amaze_key(self, event, act: bool) -> bool:
        """Whether the key resolves to an Amaze action in Houdini's hotkeys; at the press, it runs."""
        found = hotkeys.action(event)
        if found is None:
            return False
        if act:
            self.sharedState().run_key(*found)
        event.accept()
        return True

    def _gesture(self):
        """The drag the view runs, of tiles or of a sidebar row, or None; each has one end."""
        return next((gesture for gesture in (self.drag, self.reorder) if gesture.running), None)

    def _drag_takes(self, event) -> bool:
        """Whether a press belongs to the drag: any while it runs, another button while its left is down."""
        return (self._gesture() is not None
                or (self._drag_held and event.button() != QtCore.Qt.MouseButton.LeftButton))

    def mousePressEvent(self, event) -> None:
        """A press the drag takes goes nowhere: in the QML it would start a second drag."""
        if self._drag_takes(event):
            event.accept()
            return
        self._drag_held = False    # a left press: no drag's button is down any more
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._drag_takes(event):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    @debug.guarded("PaneView.mouseMoveEvent")
    def mouseMoveEvent(self, event) -> None:
        """A running drag takes the move alone: in the QML too, Qt sent it on to the pane under it."""
        gesture = self._gesture()
        if gesture is not None:    # measured: the network editor repainted between outline draws
            self._drag_held = True
            gesture.move()
            event.accept()
            return
        super().mouseMoveEvent(event)

    @debug.guarded("PaneView.mouseReleaseEvent")
    def mouseReleaseEvent(self, event) -> None:
        """The left release drops a running drag; another button's ends it and makes nothing."""
        gesture = self._gesture()
        if self._drag_held and event.button() != QtCore.Qt.MouseButton.LeftButton:
            if gesture is not None:
                gesture.cancel(miss=True)
            event.accept()
            return
        if not event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self._drag_held = False
        super().mouseReleaseEvent(event)    # the QML's press ends first: the drop may open a menu
        if gesture is not None:
            gesture.release()

    def dragEnterEvent(self, event) -> None:
        """Nodes dragged in from a network editor are the pane's to save; any other drag goes to Qt."""
        self._node_drag = event.source() is not self and bool(node_drop.node_paths(event.mimeData()))
        if self._node_drag:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._node_drag:    # the QML has no drop area: passed on, the move would refuse the drop
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        if self._node_drag:
            self._node_drag = False
            return
        super().dragLeaveEvent(event)

    @debug.guarded("PaneView.dropEvent")
    def dropEvent(self, event) -> None:
        """Dropped nodes are saved as Save to Amaze saves them, once the drop has returned."""
        if not self._node_drag:
            super().dropEvent(event)
            return
        self._node_drag = False
        if node_drop.save(self.sharedState().pane, event.mimeData()):
            event.acceptProposedAction()

    def hideEvent(self, event) -> None:
        self.drag.cancel()    # a pane hidden mid-drag gets no release
        self.reorder.cancel()
        self._drag_held = False
        super().hideEvent(event)


class SidebarDrop:
    """The QML sidebar's row under the cursor, as a drag asks for it; the row a drop takes is lit."""

    def __init__(self, view) -> None:
        self.view = view
        self._lit = QtCore.QPersistentModelIndex()

    def _under(self):
        """The sidebar row under the cursor, an invalid index off the sidebar."""
        at = self.view.mapFromGlobal(QtGui.QCursor.pos())
        return QtCore.QMetaObject.invokeMethod(
            self.view.rootObject(), "sidebarIndexAt", QtCore.Qt.ConnectionType.DirectConnection,
            QtCore.Q_RETURN_ARG("QVariant"), QtCore.Q_ARG("QVariant", at.x()), QtCore.Q_ARG("QVariant", at.y()))

    def target(self) -> tuple:
        return self.view.sharedState().pane.sidebar.drop_target(self._under())

    def hover(self) -> None:
        under = self._under()
        self._light(under if self.view.sharedState().pane.sidebar.drop_target(under) != (None, None)
                    else QtCore.QModelIndex())

    def clear(self) -> None:
        self._light(QtCore.QModelIndex())

    def _light(self, index) -> None:
        """The tree draws `index`'s row as its selected rows, none for an invalid index."""
        if QtCore.QPersistentModelIndex(index) != self._lit:
            self._lit = QtCore.QPersistentModelIndex(index)
            QtCore.QMetaObject.invokeMethod(self.view.rootObject(), "showSidebarDrop",
                                            QtCore.Qt.ConnectionType.DirectConnection,
                                            QtCore.Q_ARG("QVariant", index))


class SidebarReorder:
    """A sidebar row dragged between rows: its list's own drop moves it there, as Qt's view drops it."""

    def __init__(self, view) -> None:
        self.view = view
        self.running = False
        self._model = None
        self._data = None    # the list's own drag data for the row, made once at the start as Qt's drag does
        self._gap = None    # (row, parent) of the gap under the pointer, while the list takes the row there
        self._shown = -1

    def begin(self, index) -> None:
        """Drag sidebar row `index`, where its list lets that row move; All and a fixed list never do."""
        model = index.model()
        if self.running or model is None or not model.flags(index) & QtCore.Qt.ItemFlag.ItemIsDragEnabled:
            return
        self._model, self._data, self.running = model, model.mimeData([index]), True

    def move(self) -> None:
        """The gap under the pointer is lined where the list would take the row, as Qt asks it."""
        found = self._gap_under()
        takes = found is not None and self._model.canDropMimeData(
            self._data, QtCore.Qt.DropAction.MoveAction, found[1], 0, found[2])
        self._gap = found[1:] if takes else None
        self._line(found[0] if takes else -1)

    def release(self) -> None:
        """The left release: the list's own drop moves the row and saves, or puts it back if refused."""
        gap, model, data = self._gap, self._model, self._data
        self.cancel()
        if gap is not None:
            model.dropMimeData(data, QtCore.Qt.DropAction.MoveAction, gap[0], 0, gap[1])

    def cancel(self, miss: bool = False) -> None:
        if self.running:
            self.running, self._gap = False, None
            self._line(-1)

    def _gap_under(self):
        """(tree row, list row, parent) of the gap under the pointer; None off the top rows' gaps."""
        at = self.view.mapFromGlobal(QtGui.QCursor.pos())
        found = QtCore.QMetaObject.invokeMethod(
            self.view.rootObject(), "sidebarGapAt", QtCore.Qt.ConnectionType.DirectConnection,
            QtCore.Q_RETURN_ARG("QVariant"), QtCore.Q_ARG("QVariant", at.x()), QtCore.Q_ARG("QVariant", at.y()))
        found = found.toVariant() if isinstance(found, QtQml.QJSValue) else found    # a JS array, as Qt converts it
        if not found:
            return None
        row, below = found
        if not below.isValid():    # after the last row
            return row, self._model.rowCount(), QtCore.QModelIndex()
        return None if below.parent().isValid() else (row, below.row(), QtCore.QModelIndex())

    def _line(self, row: int) -> None:
        """The tree draws its insert line above tree row `row`, none for -1."""
        if row != self._shown:
            self._shown = row
            QtCore.QMetaObject.invokeMethod(self.view.rootObject(), "showSidebarGap",
                                            QtCore.Qt.ConnectionType.DirectConnection, QtCore.Q_ARG("QVariant", row))


def _takes_hotkeys_first(item) -> bool:
    """Whether `item` is in a view that declares `hotkeysFirst`: the grid and the list."""
    while item is not None:
        if item.property("hotkeysFirst"):
            return True
        item = item.parentItem()
    return False


class QmlPanel(QtWidgets.QFrame):
    """The Amaze (QML) pane tab: one QML view filling it, as Houdini's Node Info pane is built."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        rc_calls.start()    # before the log writes anything, so its header knows the Houdini
        debug.install()
        self._shown = False
        self.view = PaneView(parent=self)
        self.state = self.view.sharedState()
        self.state.setParent(self.view)    # deleted by Qt with the view, on the main thread
        self.view.resize(self.size())
        self.setAutoFillBackground(True)
        self.setPalette(self.view.palette())
        self.state.start()
        self.pane = self.state.pane

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.view.resize(self.size())

    def mousePressEvent(self, event) -> None:
        """A press in the pane is Amaze's: passed on, Houdini moves the keyboard to its main window."""
        event.accept()

    def panelActivated(self) -> None:
        """Called by the .pypanel when the tab comes to the front."""
        self.state.visible = True

    def panelDeactivated(self) -> None:
        self.state.visible = False

    def interfaceDestroyed(self) -> None:
        """Houdini is about to destroy the pane: it stops asking the view for hotkey contexts."""
        hotkeys.unwatch(self.view)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._shown:    # after the first paint: a modal blocks a half-built paint
            self._shown = True
            QtCore.QTimer.singleShot(0, self.pane.library.ensure_library_user)

    def event(self, event) -> bool:
        """At the close, a tile size the slider set is saved; the children get no event of their own."""
        if event.type() == QtCore.QEvent.Type.DeferredDelete:
            self.state.save_size()
        return super().event(event)
