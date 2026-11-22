"""The Amaze (QML) pane: its pane-tab widget, its QML view, and the state hosting the engine."""

from PySide6 import QtCore, QtWidgets
import shiboken6

import amaze
from amaze import amazetheme, tooltips
from amaze.core import debug
from amaze.helpers import ui_helpers
from amaze.pane import asks, pane as pane_mod
from amaze.panel import delegates
from amaze.utils import rc_calls
from hutil.qt.common import qmlviews    # Houdini's own QML panels' base ▸r/houdini-qml-tabs

PANE_QML = amaze.package_file("ui", "pane", "Pane.qml")
SIZE_SAVE_MS = 500    # the slider's pause before its tile size is saved, as in the widget panel


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
    takesCapture: bool = True
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

    searchCleared = QtCore.Signal()    # the empty state's Clear Search: the QML empties its field

    pane = None    # the engine, built by `start`
    os_file_icon = staticmethod(delegates.os_file_icon)    # held by the shared File model

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tab_keys = []
        self._empty_handler = ""
        self._sidebar_selection = None
        self._prefs_window = None
        self._size_save = QtCore.QTimer(self)
        self._size_save.setSingleShot(True)
        self._size_save.setInterval(SIZE_SAVE_MS)
        self._size_save.timeout.connect(self._save_prefs)
        tabs = amazetheme.drawn_tabs()
        self.toolbar = dict(amazetheme.drawn_toolbar(), end_gap=amazetheme.TOOLBAR_SEARCH_END_GAP)
        self.strip = {"height": tabs["height"], "left": tabs["left"]}
        self.tips = {"online": tooltips.PANEL_ONLINE, "favourites": tooltips.PANEL_FAVORITES,
                     "prefs": tooltips.PANEL_PREFERENCES, "capture": tooltips.PANEL_CAPTURE,
                     "tileSize": tooltips.PANEL_TILE_SIZE, "tileSizeList": tooltips.PANEL_TILE_SIZE_LIST,
                     "search": tooltips.PANEL_SEARCH}
        self.words = {"cancel": amazetheme.BTN_CANCEL, "search": "Search"}

    def start(self) -> None:
        """Build this pane's engine, follow it, and open the library; Qt deletes the engine with this."""
        pane = self.pane = pane_mod.Pane(self, self)
        pane.tabs_changed.connect(self._show_tabs)
        pane.context_bound.connect(self._use_sidebar_rows)
        pane.context_shown.connect(self._show_context)
        pane.online_changed.connect(self._show_online)
        pane.sidebar_highlight.connect(self._highlight_sidebar_row)
        pane.library_shown.connect(self._show_settings)
        pane.library_switched.connect(self._show_settings)
        pane.library_updated.connect(self._refresh_open_prefs)
        pane.progress_shown.connect(self._show_progress)
        pane.progress.connect(self._set_progress)
        pane.empty_changed.connect(self._show_empty)
        self._show_tabs()
        self._show_settings()
        pane.library.start()

    def _show_tabs(self) -> None:
        segments = self.pane.tabs()
        self._tab_keys = [key for key, _label in segments]
        self.tabs = ui_helpers.section_tab_rows(segments)
        self.currentTab = self._tab_keys.index(self.pane.current_tab())

    def _use_sidebar_rows(self, section) -> None:
        """This pane's selection of the section's sidebar rows, which the engine reads and moves."""
        listed = getattr(self.pane, section.sidebar_attr, None) if section.sidebar_attr else None
        if listed is None:
            return
        if self._sidebar_selection is not None:
            self._sidebar_selection.deleteLater()
        self._sidebar_selection = QtCore.QItemSelectionModel(listed, self)
        self.pane.sidebar.use_selection(self._sidebar_selection)

    def _highlight_sidebar_row(self, index) -> None:
        if self._sidebar_selection is not None and index.model() is self._sidebar_selection.model():
            flag = QtCore.QItemSelectionModel.SelectionFlag
            self._sidebar_selection.setCurrentIndex(index, flag.ClearAndSelect | flag.Rows)

    def _show_context(self, context) -> None:
        """The shown context's tab and what its toolbar offers."""
        self.currentTab = self._tab_keys.index(self.pane.current_tab())
        self.takesFavourites = bool(getattr(context, "takes_favourites", True))
        self.takesCapture = bool(getattr(context, "takes_capture", True))
        self.searchHint = getattr(context, "search_hint", "")

    def _show_online(self) -> None:
        self.online = self.pane.is_online()
        self.onlinePossible = getattr(self.pane, "matx_online_model", None) is not None

    def _show_settings(self) -> None:
        prefs = self.pane.prefs
        self.viewMode = prefs.view_mode
        self.tileStepped = bool(prefs.step_size)
        self.tileSize = self.pane.tile_size()

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
        self.tileSize = self.pane.tile_size()
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
    def capture(self) -> None:
        self.pane.tile_capture.from_toolbar()

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
            self.destroyed.connect(window.close)    # the window must not outlive the pane it applies to
        window.show()
        window.raise_()
        window.requestActivate()
        if page:
            window.setPageName(page)

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


class PaneView(qmlviews.BaseQmlWidget):
    """The pane's QML, made as Houdini makes its own QML panels."""

    SOURCE_URL = QtCore.QUrl.fromLocalFile(PANE_QML).toString()

    def _makeSharedState(self) -> PaneState:
        return PaneState()


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

    def panelActivated(self) -> None:
        """Called by the .pypanel when the tab comes to the front."""
        self.state.visible = True

    def panelDeactivated(self) -> None:
        self.state.visible = False

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
