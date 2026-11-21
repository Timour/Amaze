"""Preferences as Houdini builds its own: a QML window on Houdini's prefs state and its rows."""

import html
import os

from PySide6 import QtCore, QtGui

import amaze
from amaze import branding, tooltips
from amaze.core import model_registry, tile_icons
from amaze.prefs import prefs as prefs_mod
from hutil.qt.common import qmlviews    # Houdini's own QML windows' base ▸r/qml-widget-blackout
from hutil.qt.prefs import mainprefs    # Houdini's Preferences window: its state is the base here

PAGES_FOLDER = amaze.package_file("ui", "prefs")    # the window's QML and its pages


def _switch_text(value) -> str:
    return "1" if value else "0"


def _switch_value(text: str) -> bool:
    return text == "1"


def _percent_text(value: float) -> str:
    return str(round(value * 100))


def _percent_value(text: str) -> float:
    return float(text) / 100


SWITCH = (_switch_text, _switch_value)    # Houdini's switch rows write "1" and "0"
WORD = (str, str)
PERCENT = (_percent_text, _percent_value)    # a factor in Prefs, a percent on its row

SETTINGS = {    # a row's `pref` -> (the Prefs value as Houdini's rows' text, that text as the value)
    "sidebar_counts": SWITCH,
    "hide_empty_categories": SWITCH,
    "step_size": SWITCH,
    "render_rat_files": SWITCH,
    "system_file_icons": SWITCH,
    "path_style": WORD,
    "icon_line_weight": WORD,
    "scroll_speed": PERCENT,
}

TIPS = {    # a row's `pref` -> the text Houdini's tip window shows over it
    "sidebar_counts": tooltips.PREFS_SIDEBAR_COUNTS,
    "hide_empty_categories": tooltips.PREFS_HIDE_EMPTY_CATEGORIES,
    "step_size": tooltips.PREFS_STEP_SIZE,
    "render_rat_files": tooltips.PREFS_RENDER_RAT_FILES,
    "system_file_icons": tooltips.PREFS_SYSTEM_FILE_ICONS,
    "path_style": tooltips.PREFS_WRITE_PATHS_AS,
    "icon_line_weight": tooltips.PREFS_TILE_ICON_LINE,
    "scroll_speed": tooltips.PREFS_SCROLL_SPEED,
}

FILE_TAB_SWITCHES = frozenset(("render_rat_files", "system_file_icons"))    # applied: File relists


class AmazePrefsState(mainprefs.PrefsState):
    """Houdini's prefs state - undo, unapplied changes, Apply, Accept, Cancel - on Amaze's Prefs."""

    scrollSpeedFrom: int = round(prefs_mod.SCROLL_SPEED_RANGE[0] * 100)
    scrollSpeedTo: int = round(prefs_mod.SCROLL_SPEED_RANGE[1] * 100)

    def __init__(self, prefs, panel=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._prefs = prefs
        self._panel = panel    # None in tests; it holds the models a setting changes
        model_registry.refresh_all(prefs)    # other sessions' saves first, as the old dialog ▸r/peer-read
        prefs.apply_shared_changes()

    def _getPreference(self, name: str, registry: str = "") -> str:
        if name not in SETTINGS:
            return ""    # as hou.getPreference answers a name it does not hold
        to_text, _to_value = SETTINGS[name]
        return to_text(getattr(self._prefs, name))

    def _setPreference(self, name: str, value: str, registry: str = "") -> None:
        _to_text, to_value = SETTINGS[name]
        setattr(self._prefs, name, to_value(value))

    def _apply(self) -> None:
        changed = {name for name, _registry in self._overlay}
        for (name, registry), value in self._overlay.items():
            self._setPreference(name, value, registry)
        self._prefs.save()
        if changed & FILE_TAB_SWITCHES:
            self._relist_files(changed & FILE_TAB_SWITCHES)
        if "icon_line_weight" in changed:
            self._recompose_tile_icons()

    def _relist_files(self, names) -> None:
        """The File model's own Prefs takes the switches, then its folder relists. ▸p/one-model-set"""
        files = getattr(self._panel, "file_files_model", None)
        if files is None:
            return
        shown = getattr(files, "preferences", None)
        if shown is not None and shown is not self._prefs:
            for name in names:
                setattr(shown, name, getattr(self._prefs, name))
        files.refresh_current_folder()

    def _recompose_tile_icons(self) -> None:
        """Line weight changed: forget composed pictures, then every tile-icon model redraws."""
        tile_icons.forget_composed()
        if self._panel is None:
            return
        for model in self._panel.tile_icon_models():
            model.rerender_tile_icons()

    def setPageName(self, name: str) -> None:
        """Show page `name`, as the page list holds it: an Amaze page file, not one of Houdini's."""
        self.setPage(QtCore.QUrl.fromLocalFile(os.path.join(PAGES_FOLDER, name + "Page.qml")))

    @QtCore.Slot(str, result=bool)
    def hasHelpTip(self, help_id: str) -> bool:
        return help_id in TIPS

    @QtCore.Slot(str, str, str)
    @QtCore.Slot(str, str, str, float, float, float, float, str)
    def showHelpTip(self, title: str, text: str, tip_id: str,
                    x=-1.0, y=-1.0, w=1.0, h=1.0, alignment="Left") -> None:
        """Houdini's tip window, with Amaze's text where Houdini reads its help pages."""
        text = text or html.escape(TIPS.get(tip_id, ""))
        super().showHelpTip(title, text, tip_id, x, y, w, h, alignment)


class AmazePrefsWindow(qmlviews.BaseQmlView):
    """Amaze Preferences: a QML window made as Houdini makes its Preferences window."""

    SOURCE_URL = QtCore.QUrl.fromLocalFile(os.path.join(PAGES_FOLDER, "Preferences.qml")).toString()
    DEFAULT_SIZE = QtCore.QSize(680, 480)    # the old pages' 498 wide, and Houdini's page list beside them
    MINIMUM_SIZE = QtCore.QSize(530, 350)    # Houdini's Preferences window's own minimum

    def __init__(self, prefs, panel=None, *, parent_window: QtGui.QWindow = None) -> None:
        super().__init__(state=AmazePrefsState(prefs, panel), parent_window=parent_window)
        self.setTitle(branding.APP_NAME + " Preferences")

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == mainprefs.TOOLTIP_KEY:    # held, tips show at once, as in Houdini's window
            self.sharedState().ctrlHeld = True
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == mainprefs.TOOLTIP_KEY:
            self.sharedState().ctrlHeld = False
        super().keyReleaseEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        super().closeEvent(event)
        self.deleteLater()    # as Houdini's window does: Qt deletes it, on the main thread

    def setPageName(self, name: str) -> None:
        self.sharedState().setPageName(name)
