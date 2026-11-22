"""Preferences as Houdini builds its own: a QML window on Houdini's prefs state and its rows."""

import html
import os

from PySide6 import QtCore, QtGui

import amaze
from amaze import branding, messages, tooltips
from amaze.core import debug, model_registry, renderers, section_list, tile_icons
from amaze.helpers import hostos, ui_helpers
from amaze.prefs import prefs as prefs_mod
from hutil.qt.common import qmlviews    # Houdini's own QML windows' base ▸r/qml-widget-blackout
from hutil.qt.prefs import mainprefs    # Houdini's Preferences window: its state is the base here

PAGES_FOLDER = amaze.package_file("ui", "prefs")    # the window's QML and its pages


def _switch_text(value) -> str:
    return "1" if value else "0"


def _switch_value(text: str) -> bool:
    return text == "1"


def _number_value(text: str) -> int:
    return round(float(text))


def _percent_text(value: float) -> str:
    return str(round(value * 100))


def _percent_value(text: str) -> float:
    return float(text) / 100


SWITCH = (_switch_text, _switch_value)    # Houdini's switch rows write "1" and "0"
WORD = (str, str)
NUMBER = (str, _number_value)    # Houdini's number rows write "256"; Prefs holds the whole number
PERCENT = (_percent_text, _percent_value)    # a factor in Prefs, a percent on its row

SECTION = "enabled_sections."    # a Sections switch's `pref`: this, then the section's key
SECTION_PREFS = tuple(SECTION + key for key in section_list.keys())
MATERIAL = SECTION + "material"    # on again when every other section is off, as the old dialog

SETTINGS = {    # a row's `pref` -> (the Prefs value as Houdini's rows' text, that text as the value)
    "rendersize": NUMBER,
    **{renderer.samples: NUMBER for renderer in renderers.RENDER_TAB},
    "ram_cache_mb": NUMBER,
    "geometry_shading_mode": WORD,
    "geometry_bg": WORD,
    "render_on_import": SWITCH,
    "texture_parallel_conversions": NUMBER,
    "matx_resolution": WORD,
    "matx_parallel_downloads": NUMBER,
    **{renderer.switch: SWITCH for renderer in renderers.ALL},
    "sidebar_counts": SWITCH,
    "hide_empty_categories": SWITCH,
    "step_size": SWITCH,
    "render_rat_files": SWITCH,
    "system_file_icons": SWITCH,
    "path_style": WORD,
    "icon_line_weight": WORD,
    "scroll_speed": PERCENT,
    "debug_mode": SWITCH,
    "addon_betas": SWITCH,
}

RANGES = {    # a slider row's `pref` -> the [from, to] it offers, the old dialog's ranges
    "rendersize": list(prefs_mod.RENDERSIZE_RANGE),
    **{renderer.samples: list(renderer.samples_range) for renderer in renderers.RENDER_TAB},
    "ram_cache_mb": list(prefs_mod.RAM_CACHE_RANGE),
    "texture_parallel_conversions": list(prefs_mod.CONVERSIONS_RANGE),
    "matx_parallel_downloads": list(prefs_mod.DOWNLOADS_RANGE),
    "scroll_speed": [round(end * 100) for end in prefs_mod.SCROLL_SPEED_RANGE],
}

TIPS = {    # a row's or a button's `tipID` -> the text Houdini's tip window shows over it
    "rendersize": tooltips.PREFS_RENDER_SIZE,
    **{renderer.samples: getattr(tooltips, renderer.samples_tip)
       for renderer in renderers.RENDER_TAB},
    "ram_cache_mb": tooltips.PREFS_RAM_CACHE,
    "geometry_shading_mode": tooltips.PREFS_GEOMETRY_SHADING,
    "geometry_bg": tooltips.PREFS_GEOMETRY_BACKGROUND,
    "render_on_import": tooltips.PREFS_RENDER_ON_IMPORT,
    "texture_parallel_conversions": tooltips.PREFS_CONVERSION_THREADS,
    "matx_resolution": tooltips.PREFS_DOWNLOAD_RESOLUTION,
    "matx_parallel_downloads": tooltips.PREFS_PARALLEL_DOWNLOADS,
    **{renderer.switch: tooltips.PREFS_RENDERER_SWITCH for renderer in renderers.ALL},
    **{pref: tooltips.PREFS_SECTION_SWITCH for pref in SECTION_PREFS},
    "sidebar_counts": tooltips.PREFS_SIDEBAR_COUNTS,
    "hide_empty_categories": tooltips.PREFS_HIDE_EMPTY_CATEGORIES,
    "step_size": tooltips.PREFS_STEP_SIZE,
    "render_rat_files": tooltips.PREFS_RENDER_RAT_FILES,
    "system_file_icons": tooltips.PREFS_SYSTEM_FILE_ICONS,
    "path_style": tooltips.PREFS_WRITE_PATHS_AS,
    "icon_line_weight": tooltips.PREFS_TILE_ICON_LINE,
    "scroll_speed": tooltips.PREFS_SCROLL_SPEED,
    "check_for_updates": tooltips.PREFS_CHECK_FOR_UPDATES,
    "install_update": tooltips.PREFS_INSTALL_UPDATE,
    "report_bug": tooltips.PREFS_REPORT_A_BUG,
    "debug_mode": tooltips.PREFS_DEBUG_MODE,
    "open_log": tooltips.PREFS_OPEN_LOG,
    "save_log": tooltips.PREFS_SAVE_LOG,
    "clear_log": tooltips.PREFS_CLEAR_LOG,
    "addon_betas": tooltips.PREFS_ADDON_BETAS,
}

SAMPLES_ROWS = [    # the Render page's samples row per renderer, in the old dialog's order
    {"key": renderer.key, "label": "Samples (%s)" % renderer.engine, "pref": renderer.samples}
    for renderer in renderers.RENDER_TAB]
RENDERER_SWITCHES = [{"label": renderer.label, "pref": renderer.switch} for renderer in renderers.ALL]
SECTION_SWITCHES = [{"label": label, "pref": SECTION + key} for key, label in section_list.SECTIONS]

FILE_TAB_SWITCHES = frozenset(("render_rat_files", "system_file_icons"))    # applied: File relists

ABOUT_TEXT = (
    "<p>An asset library for Houdini: materials, textures, "
    "node setups, color palettes, geometry and code.</p>"
    "<p>By Fredrik Timour.<br>"
    "<a href='https://github.com/Timour/Amaze'>"
    "github.com/Timour/Amaze</a></p>"
    "<p>Code and assets released under GPLv3 - free to use, "
    "modify, embed and redistribute under the license's "
    "terms.</p>"
)
CREDITS_TEXT = (    # credit, not obligation: every online source is CC0 or MIT, each import its licence
    "<p>Amaze uses the egMatLib preview engine for material "
    "thumbnails &mdash; egMatLib by Elmar Glaubauf "
    "<a href='https://github.com/eglaubauf/egMatLib'>"
    "github.com/eglaubauf/egMatLib</a>"
    " &nbsp;|&nbsp; "
    "<a href='https://polyhaven.com/'>Poly Haven</a> (CC0)"
    " &middot; "
    "<a href='https://matlib.gpuopen.com/'>AMD GPUOpen</a> "
    "(MIT Public Domain)"
    " &middot; "
    "<a href='https://github.com/NVIDIA-Omniverse/PhysicalAI-SimReady-Materials'>"
    "NVIDIA SimReady</a> (MIT-0)"
    " &nbsp;|&nbsp; "
    "<a href='https://physicallybased.info/'>Physically Based</a>"
    " by Anton Palmqvist (CC0 1.0)"
    " &nbsp;|&nbsp; "
    "<a href='https://rgl.epfl.ch/materials'>EPFL RGL</a> "
    "measured materials (CC0 1.0)<br>"
    "Every imported material stores its own source and "
    "license.</p>"
    "<p><b>Generate Material</b> builds from the measured "
    "values of these two CC0 datasets: (Physically Based "
    "and EPFL RGL).</p>"
    "<p>Additional thanks: Feather Icons (MIT), "
    "Sanzo Wada / Paul Klee / Josef Albers / Johannes Itten "
    "(color palette sources, public domain).</p>"
)
CHECK_LABEL = "Check for Updates"
INSTALL_LABEL = "Install Update"


class AmazePrefsState(mainprefs.PrefsState):
    """Houdini's prefs state - undo, unapplied changes, Apply, Accept, Cancel - on Amaze's Prefs."""

    ranges: dict = RANGES
    samplesRows: list = SAMPLES_ROWS
    rendererSwitches: list = RENDERER_SWITCHES
    sectionSwitches: list = SECTION_SWITCHES
    offeredRenderers: list = []    # the renderers switched on, unapplied switches included
    appVersion: str = branding.APP_VERSION
    aboutText: str = ABOUT_TEXT
    creditsText: str = CREDITS_TEXT
    versionLine: str = "Amaze version " + branding.APP_VERSION    # every update result shows here
    updateLabel: str = CHECK_LABEL
    updateOffered: bool = False
    updateWarns: bool = False
    updateBusy: bool = False

    def __init__(self, prefs, panel=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._prefs = prefs
        self._panel = panel    # None in tests; it holds the models a setting changes
        self._last_update = None    # what the last Check for Updates found
        model_registry.refresh_all(prefs)    # other sessions' saves first, as the old dialog ▸r/peer-read
        prefs.apply_shared_changes()
        self.prefsUpdated.connect(self._follow_renderer_switches)
        self._follow_renderer_switches()

    def _getPreference(self, name: str, registry: str = "") -> str:
        if name.startswith(SECTION):
            return _switch_text(name[len(SECTION):] in self._prefs.enabled_sections)
        if name not in SETTINGS:
            return ""    # as hou.getPreference answers a name it does not hold
        to_text, _to_value = SETTINGS[name]
        return to_text(getattr(self._prefs, name))

    def _setPreference(self, name: str, value: str, registry: str = "") -> None:
        if name.startswith(SECTION):
            self._set_section(name[len(SECTION):], _switch_value(value))
            return
        _to_text, to_value = SETTINGS[name]
        setattr(self._prefs, name, to_value(value))

    def _set_section(self, key: str, on: bool) -> None:
        """The sections in tab order with `key` on or off; keys no section has are kept."""
        order = section_list.keys()
        stored = self._prefs.enabled_sections
        shown = [k for k in order if (k == key and on) or (k != key and k in stored)]
        self._prefs.enabled_sections = shown + [k for k in stored if k not in order]

    def setPref(self, name: str, value: str, registry="", auto_apply=False, record=True) -> None:
        """The last section switched off turns Material on in the same step; Material stays on."""
        if record and name.startswith(SECTION) and not _switch_value(value) and not any(
                self.getBool(other) for other in SECTION_PREFS if other != name):
            if name == MATERIAL:
                self.prefsUpdated.emit()    # its switch reads its value again: on
            else:
                self.setAll({name: value, MATERIAL: "1"}, registry, auto_apply)
            return
        super().setPref(name, value, registry, auto_apply=auto_apply, record=record)

    def _follow_renderer_switches(self) -> None:
        """A renderer switched off on Show/Hide has no samples row on Render, as the old dialog."""
        self.offeredRenderers = [renderer.key for renderer in renderers.ALL
                                 if self.getBool(renderer.switch)]

    def _apply(self) -> None:
        changed = {name for name, _registry in self._overlay}
        for (name, registry), value in self._overlay.items():
            self._setPreference(name, value, registry)
        self._prefs.save()
        if changed & FILE_TAB_SWITCHES:
            self._relist_files(changed & FILE_TAB_SWITCHES)
        if "icon_line_weight" in changed:
            self._recompose_tile_icons()
        if "debug_mode" in changed:
            self._reconfigure_debug()

    def _reconfigure_debug(self) -> None:
        """Debug Mode applied: the log follows it at once; switched on, it records the settings."""
        debug.configure(self._prefs.debug_mode)
        if self._prefs.debug_mode:
            debug.prefs_snapshot(self._prefs)

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

    def _installable(self):
        """The release the last check found with a file to fetch; None when there is nothing to install."""
        found = self._last_update
        return found if found and getattr(found, "url", "") else None

    def _show_busy(self, label: str) -> None:
        """The update button off, showing `label`, drawn before the call that blocks."""
        self.updateBusy = True
        self.updateLabel = label
        QtCore.QCoreApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _show_update_offer(self) -> None:
        """One button, two labels: Install Update once a check has found a release with a file."""
        from amaze.core import updater
        offered = self._installable() is not None
        self.updateOffered = offered
        self.updateLabel = INSTALL_LABEL if offered else CHECK_LABEL
        self.updateWarns = offered and updater.updates_library(self._last_update, self._prefs.dir)
        self.updateBusy = False

    @QtCore.Slot()
    @debug.guarded("prefs.update")
    def pressUpdate(self) -> None:
        """Check, then install: the install runs only on a press after a check has found a release."""
        if self._installable() is None:
            self._check_for_updates()
        else:
            self._install_update()

    def _check_for_updates(self) -> None:
        """Query the release feed and show the result in the version line; blocks until done."""
        from amaze.core import updater
        self._show_busy("Checking...")
        try:
            self._last_update = updater.check()
        finally:
            self._show_update_offer()
        self.versionLine = updater.offer_line(self._last_update, self._prefs.dir)

    def _install_update(self) -> None:
        """Fetch the release the last check found; Continue or Cancel first if it updates the library."""
        from amaze.core import updater
        from amaze.dialogs import update_dialog
        found = self._installable()
        if not update_dialog.confirmed(found, self._prefs.dir):    # the shelf tool asks the same
            return
        self._show_busy("Installing...")
        try:
            updater.install(found)    # the SAME call the shelf tool makes
        except OSError as exc:
            self.versionLine = str(exc)    # the updater's own complete message
        except Exception as exc:                              # noqa: BLE001
            debug.exception("update install", exc)
            self.versionLine = messages.UPDATE_FAILED_UNEXPECTED % exc
        else:
            self._last_update = None    # the offer is used: the next press queries the feed again
            self.versionLine = messages.UPDATE_INSTALLED % found.version
        finally:
            self._show_update_offer()

    @QtCore.Slot()
    @debug.guarded("prefs.report_bug")
    def reportBug(self) -> None:
        """Open the pre-filled new-issue page, built by the old dialog's module. ▸r/github-issue-url"""
        from amaze.dialogs import prefs_dialog
        prefs_dialog._open_url(prefs_dialog.bug_report_url())

    @QtCore.Slot()
    @debug.guarded("prefs.convert_old_library")
    def convertOldLibrary(self) -> None:
        """About ▸ Convert pre-1.40: the panel's converter, on a folder picked there."""
        if self._panel is not None:
            self._panel.convert_old_library()

    @QtCore.Slot()
    def openLog(self) -> None:
        """Open the log FILE itself; an empty log opens its folder instead."""
        path = debug.log_path()
        folder = os.path.dirname(path)
        try:
            os.makedirs(folder, exist_ok=True)
            hostos.open_path(path if os.path.exists(path) else folder)
        except Exception as exc:                              # noqa: BLE001
            debug.event("prefs", "could not open log", error=str(exc))

    @QtCore.Slot()
    def saveLog(self) -> None:
        """Export the log to a folder picked each time; the file contains paths and asset names."""
        import hou
        start = self._prefs.dir or os.path.expanduser("~")
        path = hou.ui.selectFile(
            start_directory=hostos.canonical_path_key(start), title=messages.TITLE_SAVE_LOG_TO_FOLDER,
            file_type=hou.fileType.Directory)
        if not path:
            return    # cancelled, not failed
        folder = hou.text.expandString(path)
        try:
            target = debug.export_log(folder)
        except debug.ExportRefused as exc:
            hou.ui.displayMessage(    # the reason: a silent failure gives no clue
                str(exc), title=messages.TITLE_LOG_NOT_SAVED, severity=hou.severityType.Warning)
            debug.event("prefs", "log export refused", reason=str(exc))
            return
        except Exception as exc:                              # noqa: BLE001
            hou.ui.displayMessage(
                messages.LOG_NOT_SAVED_UNEXPECTED % exc, title=messages.TITLE_LOG_NOT_SAVED,
                severity=hou.severityType.Warning)
            return
        if hou.ui.displayMessage(
                messages.LOG_SAVED_AS % os.path.basename(target), help=messages.HELP_LOG_SAVED,
                buttons=messages.BUTTONS_SHOW_IN_FOLDER, default_choice=1, close_choice=1,
                title=messages.TITLE_LOG_SAVED, severity=hou.severityType.Message) == 0:
            ui_helpers.reveal(target)

    @QtCore.Slot()
    def clearLog(self) -> None:
        """Through `debug.clear_log`, never a file removal: it also starts a new session header."""
        ok, reason = debug.clear_log()
        if not ok:
            debug.note(messages.LOG_NOT_CLEARED % reason)

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
    DEFAULT_SIZE = QtCore.QSize(760, 680)    # Houdini's Preferences window's own default
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
