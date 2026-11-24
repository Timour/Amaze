"""Preferences as Houdini builds its own: a QML window on Houdini's prefs state and its rows."""

import html
import os

from PySide6 import QtCore, QtGui

import amaze
from amaze import amazetheme, branding, messages, tooltips
from amaze.actions import check as check_actions
from amaze.actions import library as library_actions
from amaze.core import (check_library, debug, library_db, library_settings, model_registry,
                        renderers, section_list, texture_library, tile_icons, updater, users)
from amaze.dialogs import library_dialog, user_dialog
from amaze.helpers import hostos, ui_helpers
from amaze.pane import files as pane_files
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


def _chooser_path(path: str) -> str:
    """A folder path for `selectFile` and prefs: forward slashes, trailing one only at a root."""
    return hostos.canonical_path_key(path) if path else ""   # empty stays empty: not `"."`


def _same_folder(one: str, other: str) -> bool:
    """Whether two paths are the same folder; an empty path matches none."""
    return bool(one and other) and hostos.comparable_path(one) == hostos.comparable_path(other)


SWITCH = (_switch_text, _switch_value)    # Houdini's switch rows write "1" and "0"
NOT_SWITCH = (lambda value: _switch_text(not value),    # a switch on while its setting is off
              lambda text: not _switch_value(text))
WORD = (str, str)
NUMBER = (str, _number_value)    # Houdini's number rows write "256"; Prefs holds the whole number

SECTION = "enabled_sections."    # a Sections switch's `pref`: this, then the section's key
SECTION_PREFS = tuple(SECTION + key for key in section_list.keys())
MATERIAL = SECTION + "material"    # on again when every other section is off, as the old dialog

LIBRARY = "library"    # the Active Library row's `pref`: the folder picked, opened on Apply
USER = "library_user"    # the Active User row's `pref`: the user picked, switched to with the library
NEW_USER = "\x00new:"    # a user named here and created on Apply: this, then the name
OVERWRITE = "allow_overwrite"    # Enable Asset Versions: the open library's policy, not a Prefs setting
CACHE = "cache_dir"    # the Cache Path row: empty is this machine's own place
ADDON = "addon/"    # an add-on switch's `pref`: this, its folder, a slash, its row's name

SETTINGS = {    # a row's `pref` -> (the Prefs value as Houdini's rows' text, that text as the value)
    "rendersize": NUMBER,
    **{renderer.samples: NUMBER for renderer in renderers.RENDER_TAB},
    "geometry_shading_mode": WORD,
    "geometry_bg": WORD,
    "render_on_import": SWITCH,
    "texture_parallel_conversions": NUMBER,
    "matx_resolution": WORD,
    "matx_parallel_downloads": NUMBER,
    **{renderer.switch: SWITCH for renderer in renderers.ALL},
    "sidebar_counts": SWITCH,
    "hide_empty_categories": SWITCH,
    "qt_wheel_fix": SWITCH,
    "step_size": SWITCH,
    "render_rat_files": SWITCH,
    "system_file_icons": NOT_SWITCH,    # the Show Generic File Icons switch
    "path_style": WORD,
    "icon_line_weight": WORD,
    "debug_mode": SWITCH,
    "addon_betas": SWITCH,
    CACHE: WORD,
}

RANGES = {    # a slider row's `pref` -> the [from, to] it offers, the old dialog's ranges
    "rendersize": list(prefs_mod.RENDERSIZE_RANGE),
    **{renderer.samples: list(renderer.samples_range) for renderer in renderers.RENDER_TAB},
    "texture_parallel_conversions": list(prefs_mod.CONVERSIONS_RANGE),
    "matx_parallel_downloads": list(prefs_mod.DOWNLOADS_RANGE),
}

TIPS = {    # a row's or a button's `tipID` -> the text Houdini's tip window shows over it
    LIBRARY: tooltips.PREFS_LIBRARY,
    "manage_libraries": tooltips.PREFS_MANAGE_LIBRARIES,
    "add_library": tooltips.PREFS_ADD_LIBRARY,
    "reload_library": tooltips.PREFS_RELOAD_LIBRARY,
    "show_library_folder": tooltips.PREFS_OPEN_LIBRARY_FOLDER,
    "check_library": tooltips.PREFS_CHECK_LIBRARY,
    USER: tooltips.PREFS_LIBRARY_USER,
    "rename_user": tooltips.PREFS_RENAME_USER,
    "delete_user": tooltips.PREFS_DELETE_USER,
    CACHE: tooltips.PREFS_CACHE_PATH,
    "default_cache": tooltips.PREFS_DEFAULT_CACHE,
    "delete_cache": tooltips.PREFS_DELETE_LOCAL_CACHE,
    OVERWRITE: tooltips.PREFS_MATERIAL_VERSIONS,
    "rendersize": tooltips.PREFS_RENDER_SIZE,
    **{renderer.samples: getattr(tooltips, renderer.samples_tip)
       for renderer in renderers.RENDER_TAB},
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
    "qt_wheel_fix": tooltips.PREFS_QT_WHEEL_FIX,
    "step_size": tooltips.PREFS_STEP_SIZE,
    "render_rat_files": tooltips.PREFS_RENDER_RAT_FILES,
    "system_file_icons": tooltips.PREFS_GENERIC_FILE_ICONS,
    "path_style": tooltips.PREFS_WRITE_PATHS_AS,
    "icon_line_weight": tooltips.PREFS_TILE_ICON_LINE,
    "addons_check": tooltips.PREFS_ADDONS_CHECK,
    "addons_update": tooltips.PREFS_ADDONS_UPDATE,
    "addon_betas": tooltips.PREFS_ADDON_BETAS,
    "check_for_updates": tooltips.PREFS_CHECK_FOR_UPDATES,
    "install_update": tooltips.PREFS_INSTALL_UPDATE,
    "report_bug": tooltips.PREFS_REPORT_A_BUG,
    "debug_mode": tooltips.PREFS_DEBUG_MODE,
    "open_log": tooltips.PREFS_OPEN_LOG,
    "save_log": tooltips.PREFS_SAVE_LOG,
    "clear_log": tooltips.PREFS_CLEAR_LOG,
}

SAMPLES_ROWS = [    # the Render page's samples row per renderer, in RENDER_TAB's order
    {"key": renderer.key, "label": "%s Samples" % renderer.engine, "pref": renderer.samples}
    for renderer in renderers.RENDER_TAB]
RENDERER_SWITCHES = [{"label": renderer.label, "pref": renderer.switch} for renderer in renderers.ALL]
SECTION_SWITCHES = [{"label": label, "pref": SECTION + key} for key, label in section_list.SECTIONS]

FILE_TAB_SWITCHES = frozenset(("render_rat_files", "system_file_icons"))    # applied: File relists
LIGHT_FILLS = {check_library.FOUND: amazetheme.P01_LIGHT_FOUND,    # the light: first state any part is in
               check_library.UNCHECKED: amazetheme.P01_LIGHT_UNCHECKED,
               check_library.CLEAN: amazetheme.P01_LIGHT_CLEAN}

ABOUT_TEXT = (    # the About page's text under the logo, word for word as the P06 frame
    "<p>An asset library for Houdini by Fredrik Timour.</p>"
    "<p><b>License:</b><br>Released under GPLv3 - free to use, modify, embed and "
    "redistribute under the license's terms.</p>"
)
CREDITS_TEXT = (    # credit, not obligation: every online source is CC0 or MIT, each import its licence
    "<p><b>Modules and libraries from other projects:</b><br>"
    "egMatLib by Elmar Glaubauf <a href='https://github.com/eglaubauf/egMatLib'>"
    "github.com/eglaubauf/egMatLib</a><br>"
    "<a href='https://polyhaven.com/'>Poly Haven</a> (CC0)<br>"
    "<a href='https://matlib.gpuopen.com/'>AMD GPUOpen</a> (MIT Public Domain)<br>"
    "<a href='https://github.com/NVIDIA-Omniverse/PhysicalAI-SimReady-Materials'>"
    "NVIDIA SimReady</a> (MIT-0)<br>"
    "<a href='https://physicallybased.info/'>Physically Based</a> by Anton Palmqvist "
    "(CC0 1.0)<br>"
    "<a href='https://rgl.epfl.ch/materials'>EPFL RGL</a> measured materials (CC0 1.0)</p>"
    "<p>The source and license is stored with every imported material.</p>"
    "<p><b>Additional thanks:</b><br>Feather Icons (MIT), "
    "Sanzo Wada / Paul Klee / Josef Albers / Johannes Itten.</p>"
)
CHECK_LABEL = "Check for Updates"
INSTALL_LABEL = "Install Update"
ADDONS_UPDATE_LABEL = "Update"    # the Add-On page's button once a check found something


def _tip_html(text: str) -> str:
    """Text for Houdini's tip window, which reads HTML: escaped, its line breaks kept."""
    return html.escape(text).replace("\n", "<br>")


class LibraryRows(QtCore.QAbstractTableModel):
    """Manage Libraries' rows, a model with a role per field as Houdini's OCIO page has its rules."""

    COLUMNS = ("name", "shown")    # the library's name, then its folder as shown
    FIELDS = ("shown", "folder", "dim", "isOpen")    # a row's roles besides `display`, its name
    FOLDER_ROLE = QtCore.Qt.ItemDataRole.UserRole + FIELDS.index("folder")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list = []    # one dict per library, keyed by `name` and FIELDS

    def fill(self, rows: list) -> None:
        """New rows, the old removed as rows: a reset clears Qt's selection model with no signal."""
        if self.rows:
            self.beginRemoveRows(QtCore.QModelIndex(), 0, len(self.rows) - 1)
            self.rows = []
            self.endRemoveRows()
        if rows:
            self.beginInsertRows(QtCore.QModelIndex(), 0, len(rows) - 1)
            self.rows = rows
            self.endInsertRows()

    def roleNames(self) -> dict:
        roles = {QtCore.Qt.ItemDataRole.DisplayRole: b"display"}
        roles.update({QtCore.Qt.ItemDataRole.UserRole + number: field.encode()
                      for number, field in enumerate(self.FIELDS)})
        return roles

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def flags(self, index):
        """Every row can be selected but the open library's, which is only shown."""
        flags = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemNeverHasChildren
        if index.isValid() and not self.rows[index.row()]["isOpen"]:
            flags |= QtCore.Qt.ItemFlag.ItemIsSelectable
        return flags

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return row[self.COLUMNS[index.column()]]
        number = int(role) - int(QtCore.Qt.ItemDataRole.UserRole)
        return row[self.FIELDS[number]] if 0 <= number < len(self.FIELDS) else None


class AmazePrefsState(mainprefs.PrefsState):
    """Houdini's prefs state - undo, unapplied changes, Apply, Accept, Cancel - on Amaze's Prefs."""

    ranges: dict = RANGES
    samplesRows: list = SAMPLES_ROWS
    rendererSwitches: list = RENDERER_SWITCHES
    sectionSwitches: list = SECTION_SWITCHES
    offeredRenderers: list = []    # the renderers switched on, unapplied switches included
    logoHeight: int = ui_helpers.LOGO_HEIGHT
    repo: dict = dict(amazetheme.ABOUT_REPO, address=updater.REPO_URL.split("://", 1)[1])
    aboutText: str = ABOUT_TEXT
    creditsText: str = CREDITS_TEXT
    versionLine: str = "Amaze version " + branding.APP_VERSION    # every update result shows here
    updateLabel: str = CHECK_LABEL
    updateOffered: bool = False
    updateWarns: bool = False
    updateBusy: bool = False
    libraryOptions: list = []    # the Library list as {text, value}: each folder by name
    libraryRows: QtCore.QObject = None    # Manage Libraries' rows, a `LibraryRows`
    libraryNameWidth: int = amazetheme.drawn_list_rows("D15")["second_x"]    # its name column
    manageLibrariesTitle: str = amazetheme.TITLE_MANAGE_LIBRARIES
    removeFromListLabel: str = amazetheme.BTN_REMOVE_FROM_LIST
    userOptions: list = []    # the picked library's users A to Z, a new one, then the create row
    userPicked: bool = False
    userEditable: bool = False    # Rename and Delete: a new user, or one of the open library
    libraryOpen: bool = False    # the picked library is the one open: its own buttons work
    libraryFormat: str = ""    # the Check Database row's text
    applyLine: str = ""    # what Apply does to the picked library, when it warns
    cachePath: str = ""
    checkLight: str = amazetheme.P01_LIGHT_IDLE    # the Check Database row's one light
    checkInfo: str = ""
    checkTip: str = ""
    checkLabel: str = amazetheme.BTN_CHECK
    checkFixable: bool = False
    addonRows: list = []    # one row per group of each installed add-on, from its package
    addonsAltered: bool = False    # an add-on switch waits for Apply, then for a Houdini start
    addonsNone: str = messages.ADDONS_NONE
    addonsLine: str = ""
    addonsLabel: str = CHECK_LABEL
    addonsOffered: bool = False
    addonsBusy: bool = False

    userNameRequested = QtCore.Signal(str, str)    # the name dialog opens: its title, its field's name

    def __init__(self, prefs, pane=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._prefs = prefs
        self._pane = pane    # the pane engine; None in tests; it holds the models a setting changes
        self.libraryRows = LibraryRows(self)
        self._creating = False    # the name dialog was opened by the create row, not by Rename
        self._last_update = None    # what the last Check for Updates found
        self._added: list = []    # folders Add put in the Library list, until applied
        self._shown_folder = None    # the library the Check Database row was last emptied for
        self._check_found = None    # what the last check found, while Repair can fix some of it
        self._addons_found: list = []    # what the last add-on check found, until installed
        self._addon_rows: dict = {}    # an add-on switch's `pref` -> (root, folder, row)
        self._refused: dict = {}    # the library pick the last Apply could not open, kept pending
        model_registry.refresh_all(prefs)    # other sessions' saves first, as the old dialog ▸r/peer-read
        prefs.apply_shared_changes()
        self.prefsUpdated.connect(self._follow_renderer_switches)
        self.prefsUpdated.connect(self._show_library)
        self.prefsUpdated.connect(self._follow_addon_switches)
        self._follow_renderer_switches()
        self._fill_addon_rows()
        self._show_library()

    def _getPreference(self, name: str, registry: str = "") -> str:
        if name.startswith(SECTION):
            return _switch_text(name[len(SECTION):] in self._prefs.enabled_sections)
        if name == LIBRARY:
            return str(self._prefs.dir or "")
        if name == USER:
            return self._preselected(str(self._prefs.dir or ""))
        if name == OVERWRITE:
            return _switch_text(library_settings.allow_overwrite(self._prefs))
        if name.startswith(ADDON):
            return self._addon_on(name)
        if name not in SETTINGS:
            return ""    # as hou.getPreference answers a name it does not hold
        to_text, _to_value = SETTINGS[name]
        return to_text(getattr(self._prefs, name))

    def _setPreference(self, name: str, value: str, registry: str = "") -> None:
        if name.startswith(SECTION):
            self._set_section(name[len(SECTION):], _switch_value(value))
        elif name == OVERWRITE:
            self._set_overwrite(_switch_value(value))
        elif name.startswith(ADDON):
            self._turn_addon(name, _switch_value(value))
        else:
            _to_text, to_value = SETTINGS[name]
            setattr(self._prefs, name, to_value(value))

    def _set_section(self, key: str, on: bool) -> None:
        """The sections in tab order with `key` on or off; keys no section has are kept."""
        order = section_list.keys()
        stored = self._prefs.enabled_sections
        shown = [k for k in order if (k == key and on) or (k != key and k in stored)]
        self._prefs.enabled_sections = shown + [k for k in stored if k not in order]

    def setPref(self, name: str, value: str, registry="", auto_apply=False, record=True) -> None:
        """The rules a row's change carries, as the old dialog's: each in the same undo step."""
        if name == "addon_betas":
            self._forget_addon_check()    # the other kind's last check result is no answer
        if record and name == LIBRARY:
            self.setAll({LIBRARY: value, USER: self._picked_library_user(value)}, registry, auto_apply)
            return
        if record and name == USER and value == user_dialog.CREATE:
            self._ask_new_user()
            return
        if (record and name == OVERWRITE and _switch_value(value)
                and not library_settings.allow_overwrite(self._prefs)
                and not self._overwrite_confirmed()):
            self.prefsUpdated.emit()    # its switch reads its value again: off
            return
        if record and name.startswith(SECTION) and not _switch_value(value) and not any(
                self.getBool(other) for other in SECTION_PREFS if other != name):
            if name == MATERIAL:
                self.prefsUpdated.emit()    # its switch reads its value again: on
            else:
                self.setAll({name: value, MATERIAL: "1"}, registry, auto_apply)
            return
        super().setPref(name, value, registry, auto_apply=auto_apply, record=record)

    def _follow_renderer_switches(self) -> None:
        """A renderer switched off on the UI page has no samples row on Render, as the old dialog."""
        self.offeredRenderers = [renderer.key for renderer in renderers.ALL
                                 if self.getBool(renderer.switch)]

    def _apply(self) -> None:
        pending = {name: value for (name, _registry), value in self._overlay.items()}
        drawn_weight = self._prefs.icon_line_weight    # what the tiles were composed with
        for name, value in pending.items():
            if name not in (LIBRARY, USER):
                self._setPreference(name, value)
        self._prefs.save()
        if FILE_TAB_SWITCHES.intersection(pending):
            self._relist_files(FILE_TAB_SWITCHES.intersection(pending))
        if "debug_mode" in pending:
            self._reconfigure_debug()
        if CACHE in pending:
            hostos.set_cache_override(self._prefs.cache_dir)
        self._refused = {}
        if LIBRARY in pending or USER in pending:
            folder = pending.get(LIBRARY, self.getPref(LIBRARY))
            uid = pending.get(USER, self.getPref(USER))
            if not self._apply_library(folder, uid):
                self._refused = {(LIBRARY, ""): folder, (USER, ""): uid}
        if self._prefs.icon_line_weight != drawn_weight:
            self._recompose_tile_icons()

    @QtCore.Slot()
    def apply(self) -> None:
        """Houdini's Apply; a library pick that could not be opened stays pending, its line says why."""
        super().apply()
        self._overlay.update(self._refused)
        self._updateFlags()
        self.prefsUpdated.emit()    # every row shows the value now in use, a switch's new user's too

    @QtCore.Slot()
    def accept(self) -> None:
        """Houdini's Accept; it stays open on a library pick Apply could not open, as the old Accept."""
        self.apply()
        if self._refused:
            return
        self.accepted.emit()
        self.finished.emit()
        self.windowCloseRequested.emit()

    def _reconfigure_debug(self) -> None:
        """Debug Mode applied: the log follows it at once; switched on, it records the settings."""
        debug.configure(self._prefs.debug_mode)
        if self._prefs.debug_mode:
            debug.prefs_snapshot(self._prefs)

    def _relist_files(self, names) -> None:
        """The File model's own Prefs takes the switches, then its folder relists. ▸p/one-model-set"""
        files = getattr(self._pane, "file_files_model", None)
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
        if self._pane is None:
            return
        for model in self._pane.tile_icon_models():
            model.rerender_tile_icons()

    def _is_open(self, folder: str) -> bool:
        """Whether the pane has `folder` open; with no pane, whether it is the library Prefs names."""
        if self._pane is not None:
            return self._pane.library.serves(folder)
        return _same_folder(folder, self._prefs.dir)

    def _known_users(self, folder: str) -> dict:
        """`{uid: name}` in `folder`; empty for a folder that cannot be reached."""
        if not folder or not os.path.isdir(folder):
            return {}
        return users.all_users(self._prefs, library=folder)

    def _preselected(self, folder: str) -> str:
        """This computer's user when `folder` is the open library and knows that id; else nobody."""
        current = str(self._prefs.library_user or "")
        if _same_folder(folder, self._prefs.dir) and current in self._known_users(folder):
            return current
        return ""

    def _picked_library_user(self, folder: str) -> str:
        """A library pick's user: this computer's in the open library, else the first A to Z, else new."""
        rows = user_dialog.user_rows(self._known_users(folder))    # the create row last
        first = rows[0][1] if len(rows) > 1 else NEW_USER + user_dialog.DEFAULT_NAME
        return self._preselected(folder) or first

    def _library_folders(self) -> list:
        """The Library list: folders Add put there, newest first, the open library, then the rest."""
        folders = []
        for folder in self._added[::-1] + [str(self._prefs.dir or "")] + list(self._prefs.libraries):
            if folder and not any(_same_folder(folder, known) for known in folders):
                folders.append(folder)
        return folders

    def _user_rows(self, folder: str, uid: str) -> list:
        """The User list for `folder`: its users A to Z, the one named here, then the create row."""
        rows = [{"text": name, "value": user_id}
                for name, user_id in user_dialog.user_rows(self._known_users(folder))]
        if uid.startswith(NEW_USER):
            rows.insert(len(rows) - 1, {"text": uid[len(NEW_USER):], "value": uid})
        return rows

    def _library_note(self, folder: str) -> tuple:
        """(Format line, line under the rows, whether Apply may open it) for `folder`."""
        known = library_settings.THIS_AMAZE    # the three format numbers, shown as one `2.x`
        label = library_settings.version_label
        if not folder:
            return "", "", False
        if not os.path.isdir(folder):
            return "", amazetheme.LABEL_LIBRARY_UNREACHABLE, False
        if not library_actions.index_present(folder):
            return amazetheme.LABEL_LIBRARY_FORMAT % label(known), "", True    # set up on Apply
        found = library_settings.library_formats(folder)
        shown = amazetheme.LABEL_LIBRARY_FORMAT % label(found)
        if any(one > ours for one, ours in zip(found, known)):
            return shown, amazetheme.LABEL_LIBRARY_TOO_NEW, False
        if any(one < ours for one, ours in zip(found, known)):
            return shown, amazetheme.LABEL_UPGRADES_LIBRARY % label(known), True
        return shown, "", True

    def _show_library(self) -> None:
        """The Library page's rows for the library and user picked; nothing switches before Apply."""
        folder, uid = self.getPref(LIBRARY), self.getPref(USER)
        if folder != self._shown_folder:
            self._shown_folder = folder
            self._clear_check()
        self.libraryOptions = [{"text": library_dialog.library_name(known), "value": known}
                               for known in self._library_folders()]
        self.userOptions = self._user_rows(folder, uid)
        self.userPicked = bool(uid) and uid != user_dialog.CREATE
        self.libraryOpen = self._is_open(folder)
        self.userEditable = uid.startswith(NEW_USER) or (self.libraryOpen and self.userPicked)
        self.libraryFormat, self.applyLine, _may_apply = self._library_note(folder)
        self.cachePath = self.getPref(CACHE) or hostos.cache_root()

    def refresh_library_version(self) -> None:
        """Re-read the picked library's format: an update can be installed while this is open."""
        self._show_library()

    def _apply_library(self, folder: str, uid: str) -> bool:
        """Open the library and the user picked; False when that could not be done."""
        if not uid or uid == user_dialog.CREATE or not self._library_note(folder)[2]:
            return False
        switching = not self._is_open(folder)
        if not switching and uid == self._prefs.library_user:
            return True
        self._prefs.save()    # before the switch: unsaved edits belong to the library they were made in
        if switching and self._pane is not None and not self._pane.library.takes_library(folder):
            return False    # checked before anything is written to it
        unopenable = switching and library_actions.index_unopenable(folder)    # the open says why
        if uid.startswith(NEW_USER) and not unopenable:    # made first: no library opens without its user
            name = uid[len(NEW_USER):]
            uid = users.create(self._prefs, name, library=folder if switching else "")
            if not uid:
                if users.name_taken(self._prefs, name, library=folder if switching else ""):
                    self._show_name_taken(name)
                return False
        if switching and not self._switch_library(folder, uid):
            return False
        library_db.flush()    # pending changes are saved as the user who made them
        users.set_current_user(self._prefs, uid)
        debug.event("prefs", "library and user applied", library=self._prefs.dir, user=uid)
        self._added = [known for known in self._added if not _same_folder(known, folder)]
        return True

    def _switch_library(self, folder: str, uid: str) -> bool:
        """Open `folder` with the picked user; both are put back when it does not open."""
        before, before_dir = str(self._prefs.library_user or ""), self._prefs.dir
        library_db.flush()    # the open library's pending changes, saved as the user who made them
        if not uid.startswith(NEW_USER):
            self._prefs.library_user = uid    # before the models switch, so they read this user's favourites
        self._prefs.dir = folder
        self._prefs.save()    # the models' switch re-reads settings.json
        opened = self._pane is None or self._pane.library.open_library()
        if not opened:    # with no library open the pane has nothing to put back
            self._prefs.library_user = before
            self._prefs.dir = before_dir
            self._prefs.save()
        return opened

    def _drop_library_pick(self) -> None:
        """The Active Library and Active User rows back to the open library, outside the undo steps."""
        self._overlay.pop((LIBRARY, ""), None)
        self._overlay.pop((USER, ""), None)
        self._updateFlags()

    def pick_library(self, folder: str) -> None:
        """Show `folder` in the Active Library row, added to its list until applied when it lacks it."""
        folder = hostos.canonical_path_key(folder).rstrip("/") + "/"    # the library folder's canonical form
        known = next((one for one in self._library_folders() if _same_folder(one, folder)), None)
        if known is None:
            self._added.append(folder)
        self.setPref(LIBRARY, known or folder)

    @QtCore.Slot()
    def addLibrary(self) -> None:
        """A library folder, or an empty one for a new library, into the Library list; Apply opens it."""
        try:
            import hou
        except ImportError:
            hou = None
        ui = getattr(hou, "ui", None)
        if ui is None:
            return
        if len(self._prefs.libraries) >= prefs_mod.LIBRARY_LIST_LIMIT:
            ui.displayMessage(messages.LIBRARY_LIST_FULL % prefs_mod.LIBRARY_LIST_LIMIT,
                              severity=hou.severityType.Warning, title=branding.APP_NAME)
            return
        path = ui.selectFile(file_type=hou.fileType.Directory,
                             title=messages.TITLE_CHOOSE_LIBRARY_FOLDER)
        if not path:
            return
        folder = _chooser_path(hou.text.expandString(path))
        if not prefs_mod.can_hold_a_library(folder):
            ui.displayMessage(messages.LIBRARY_PATH_INVALID,
                              severity=hou.severityType.Warning, title=branding.APP_NAME)
            return
        if library_actions.folder_not_empty_without_library(folder):
            debug.event("prefs", "library not added - the folder is not empty and holds no library", dir=folder)
            ui.displayMessage(messages.LIBRARY_FOLDER_NOT_EMPTY,
                              severity=hou.severityType.Warning, title=messages.TITLE_AMAZE)
            return
        self.pick_library(folder)

    @QtCore.Slot()
    def listLibraries(self) -> None:
        """Manage Libraries' rows, read as it opens: the Library list, most recent first."""
        rows = []
        for folder in self._prefs.libraries:
            reached, shown = os.path.isdir(folder), library_dialog.shown_path(folder)
            rows.append({
                "name": library_dialog.library_name(folder), "folder": folder, "dim": not reached,
                "shown": shown if reached else "%s, %s" % (shown, amazetheme.LABEL_NOT_CONNECTED),
                "isOpen": _same_folder(folder, self._prefs.dir)})    # shown, never selectable
        self.libraryRows.fill(rows)

    @QtCore.Slot(QtCore.QModelIndex, list)
    def removeLibraries(self, current, indexes: list) -> None:
        """Remove from List on the current and selected rows, as Node Search reads its table's."""
        folders = [str(index.data(LibraryRows.FOLDER_ROLE)) for index in [current, *indexes]
                   if index.isValid()]
        if not self._prefs.remove_libraries(folders):
            return
        self._prefs.save()
        self.libraryRows.fill([row for row in self.libraryRows.rows
                               if not any(_same_folder(row["folder"], gone) for gone in folders)])
        if any(_same_folder(self.getPref(LIBRARY), gone) for gone in folders):
            self._drop_library_pick()
        self.prefsUpdated.emit()

    @QtCore.Slot()
    def reloadLibrary(self) -> None:
        if self._pane is not None:
            self._pane.library.reload()

    @QtCore.Slot()
    def showLibraryFolder(self) -> None:
        if self._pane is not None:
            self._pane.library.open_folder()

    def _name_taken(self, name: str, besides: str = "") -> bool:
        """Whether the picked library has another user called `name`."""
        folder = self.getPref(LIBRARY)
        return (bool(folder) and os.path.isdir(folder)
                and users.name_taken(self._prefs, name, besides=besides, library=folder))

    def _show_name_taken(self, name: str) -> None:
        try:
            import hou
        except ImportError:
            hou = None
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(messages.USER_NAME_TAKEN % name.strip(),
                              severity=hou.severityType.Warning, title=branding.APP_NAME)

    def create_user(self, name: str) -> None:
        """Name a new user for the picked library; Apply creates them."""
        self.setPref(USER, NEW_USER + str(name or "").strip())

    def _ask_new_user(self) -> None:
        """The create row opens the name dialog, empty; its OK comes back to `nameUser`."""
        self._creating = True
        self.userNameRequested.emit("Create User", "")

    def rename_user(self, name: str) -> None:
        """Rename the user Active User shows: a new one before Apply, else in the open library now."""
        uid, name = self.getPref(USER), str(name or "").strip()
        if not name:
            return
        if uid.startswith(NEW_USER):
            self.setPref(USER, NEW_USER + name)
        elif uid and self._is_open(self.getPref(LIBRARY)) and users.rename(self._prefs, uid, name):
            self.prefsUpdated.emit()

    @QtCore.Slot()
    def renameUser(self) -> None:
        """Rename opens the name dialog on the user's name; its OK comes back to `nameUser`."""
        uid = self.getPref(USER)
        if not uid or uid == user_dialog.CREATE:
            return
        self._creating = False
        new = uid.startswith(NEW_USER)
        self.userNameRequested.emit(
            "Rename User", uid[len(NEW_USER):] if new else users.name_for(self._prefs, uid))

    @QtCore.Slot(str)
    def nameUser(self, name: str) -> None:
        """The name dialog's OK: a new user named, or the user renamed; a taken name is only shown."""
        name, uid = str(name or "").strip(), self.getPref(USER)
        if self._creating:
            if name and not self._name_taken(name):
                self.create_user(name)
                return
            if name:
                self._show_name_taken(name)
            self.prefsUpdated.emit()    # the Active User row shows the user it showed before
            return
        if self._name_taken(name, besides="" if uid.startswith(NEW_USER) else uid):
            self._show_name_taken(name)
            return
        self.rename_user(name)

    def delete_user(self, uid: str) -> None:
        """Delete `uid`, their favourites and folder list from the open library; nobody is picked after."""
        if users.delete(self._prefs, uid):
            self._overlay.pop((USER, ""), None)
            self._updateFlags()
            self.prefsUpdated.emit()

    @QtCore.Slot()
    def deleteUser(self) -> None:
        import hou
        uid = self.getPref(USER)
        if uid.startswith(NEW_USER):
            self.setPref(USER, "")
            return
        if not uid or uid == user_dialog.CREATE or not self._is_open(self.getPref(LIBRARY)):
            return
        name = users.name_for(self._prefs, uid)
        if hou.ui.displayMessage(
                messages.USER_DELETE_CONFIRM % name, help=messages.HELP_DELETE_USER % name,
                buttons=messages.BUTTONS_DELETE_USER, default_choice=1, close_choice=1,
                severity=hou.severityType.Warning, title=branding.APP_NAME) == 0:
            self.delete_user(uid)

    def _clear_check(self) -> None:
        """The Check Database row before a check: a grey light, no tip, `Check`."""
        self._check_found = None
        self.checkLight = amazetheme.P01_LIGHT_IDLE
        self._show_check_line("", False)

    def _show_check_line(self, info: str, fixable: bool) -> None:
        """What the check found, the light's tip, and the one button: `Check`, or `Repair` drawn red."""
        self.checkInfo = info
        self.checkTip = _tip_html(info)
        self.checkFixable = fixable
        self.checkLabel = amazetheme.BTN_REPAIR if fixable else amazetheme.BTN_CHECK

    def _show_check(self, findings: dict) -> None:
        """Fill the row from one survey: the light's colour, its tip, the button."""
        found = check_library.summary(findings)
        states = {state for state, _number in found["lights"].values()}
        self.checkLight = next(fill for state, fill in LIGHT_FILLS.items() if state in states)
        self._check_found = findings if found["lines"] else None
        self._show_check_line(found["info"], bool(found["lines"]))

    def _survey_open_library(self) -> dict:
        """One survey of the open library on disk, the pane's pending changes saved first."""
        if self._pane is not None:
            check_actions.save_before_check(self._pane)
        findings = check_library.survey(str(self._prefs.dir), self._prefs)
        debug.event("check", "surveyed", holding_back=findings["holding_back"],
                    states={entry["name"]: entry["state"] for entry in findings["databases"]})
        return findings

    @QtCore.Slot()
    @debug.guarded("prefs.check_or_repair")
    def checkOrRepair(self) -> None:
        """The row's button: `Check` checks; `Repair` opens the Repair dialog, then checks again."""
        if not self._is_open(self.getPref(LIBRARY)):
            return
        if self._check_found is None:
            self._show_check(self._survey_open_library())
            return
        from amaze.dialogs import check_dialog
        if self._pane is not None:
            check_actions.save_before_check(self._pane)
        pane = self._pane
        check_dialog.show(str(self._prefs.dir), self._prefs,
                          changed=None if pane is None else lambda: check_actions.reload_after_check(pane))
        self._show_check(self._survey_open_library())

    @QtCore.Slot()
    def changeCachePath(self) -> None:
        """Pick a folder for the preview cache, used from Apply; an empty pick keeps the current one."""
        import hou
        start = _chooser_path(self.getPref(CACHE) or hostos.cache_root())
        path = hou.ui.selectFile(start_directory=start, file_type=hou.fileType.Directory)
        if path:
            self.setPref(CACHE, _chooser_path(hou.text.expandString(path)))

    @QtCore.Slot()
    def resetCachePath(self) -> None:
        """Back to this machine's own place for the cache, from Apply; deletes nothing."""
        self.setPref(CACHE, "")

    @QtCore.Slot()
    def deleteCache(self) -> None:
        """Delete every cached image and geometry thumbnail; scene captures are left alone."""
        import hou
        if not hou.ui.displayConfirmation(
                messages.CONFIRM_CLEAR_THUMBNAIL_CACHE,
                suppress=hou.confirmType.NoConfirmType):    # not `OverwriteFile`, Houdini's global flag
            return
        files = getattr(self._pane, "file_files_model", None)
        if files is not None:
            files.clear_cache()
        else:
            texture_library.ThumbnailCache(self._prefs.rendersize).clear()

    def _overwrite_confirmed(self) -> bool:
        """Enable Asset Versions switched on asks first; True on Turn On."""
        import hou
        return hou.ui.displayMessage(
            messages.MATERIAL_VERSIONS_TURN_ON_CONFIRM, help=messages.HELP_MATERIAL_VERSIONS,
            buttons=messages.BUTTONS_TURN_ON, default_choice=1, close_choice=1,
            severity=hou.severityType.Warning, title=branding.APP_NAME) == 0

    def _set_overwrite(self, on: bool) -> None:
        """Versions applied: written to the library's policy; a failed write says so."""
        if not library_settings.set_allow_overwrite(self._prefs, on):
            import hou
            hou.ui.displayMessage(messages.LIBRARY_SETTING_NOT_WRITTEN,
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)

    def _fill_addon_rows(self) -> None:
        """A row per group of each installed add-on, from its package alone."""
        from amaze.core import addons, updater
        root = updater.install_root()
        self._addon_rows, shown = {}, []
        for folder, manifest in (addons.installed_all(root) if root else []):
            for group in addons.rows(manifest):
                pref = ADDON + folder + "/" + group["name"]
                self._addon_rows[pref] = (root, folder, group)
                picture = os.path.join(root, addons.ROOT, folder, *group["addon_icon"].split("/"))
                shown.append({
                    "pref": pref, "label": group["name"],
                    "version": messages.ADDON_VERSION % manifest["version"],
                    "author": messages.ADDON_AUTHOR % manifest["author"],
                    "description": group["short_description"],
                    "tip": _tip_html("\n\n".join(n["description"] for n in group["nodes"]
                                                 if n["description"])),
                    "picture": QtCore.QUrl.fromLocalFile(picture).toString(),
                    "halved": not picture.lower().endswith(".svg")})    # a PNG shows at half its pixels
        self.addonRows = shown

    def _addon_on(self, name: str) -> str:
        if name not in self._addon_rows:
            return ""
        from amaze.core import addons
        root, folder, group = self._addon_rows[name]
        return _switch_text(addons.is_on(root, folder, group))

    def _turn_addon(self, name: str, on: bool) -> None:
        """An add-on switch applied: its files move now; Houdini loads or skips them at its next start."""
        from amaze.core import addons, packages
        if name not in self._addon_rows:
            return
        root, folder, group = self._addon_rows[name]
        try:
            addons.set_on(root, folder, group, on)
        except packages.PackageError as exc:
            self.addonsLine = str(exc)
            return
        self.addonsLine = messages.ADDONS_TURNED % (group["name"], "on" if on else "off")

    def _follow_addon_switches(self) -> None:
        self.addonsAltered = any(self.isAlterted(pref) for pref in self._addon_rows)

    def _draw_now(self) -> None:
        """Draw a button's busy state before the call that blocks."""
        QtCore.QCoreApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _show_addons_offer(self) -> None:
        """One button, two labels: Update once a check has found something."""
        self.addonsOffered = bool(self._addons_found)
        self.addonsLabel = ADDONS_UPDATE_LABEL if self.addonsOffered else CHECK_LABEL
        self.addonsBusy = False

    def _forget_addon_check(self) -> None:
        self._addons_found = []
        self._show_addons_offer()

    @QtCore.Slot()
    def pressAddons(self) -> None:
        """Check, then update: the press that installs is never the press that checked."""
        if self._addons_found:
            self._install_addons()
        else:
            self._check_addons()

    @debug.guarded("prefs.check_addons")
    def _check_addons(self) -> None:
        """Query the store, on request only, for the kind the beta switch shows; the line says what."""
        from amaze.actions import addons as addon_actions
        self.addonsBusy, self.addonsLabel = True, "Checking..."
        self._draw_now()
        found, sentence = addon_actions.check(self.getBool("addon_betas"))
        self._addons_found = found
        self._show_addons_offer()
        self.addonsLine = sentence

    @debug.guarded("prefs.install_addons")
    def _install_addons(self) -> None:
        """Install what the last check found, with no popup: the line shows the result."""
        from amaze.actions import addons as addon_actions
        from amaze.core import updater
        root = updater.install_root()
        if not root:
            self.addonsLine = messages.ADDONS_LOCATION_UNKNOWN
            return
        self.addonsBusy, self.addonsLabel = True, "Installing..."
        self._draw_now()
        sentence = addon_actions.install(self._addons_found, root)
        self._addons_found = []
        self._show_addons_offer()
        self.addonsLine = sentence
        self._fill_addon_rows()

    def _installable(self):
        """The release the last check found with a file to fetch; None when there is nothing to install."""
        found = self._last_update
        return found if found and getattr(found, "url", "") else None

    def _show_busy(self, label: str) -> None:
        """The update button off, showing `label`, drawn before the call that blocks."""
        self.updateBusy = True
        self.updateLabel = label
        self._draw_now()

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
        """Open the pre-filled new-issue page. ▸r/github-issue-url"""
        from amaze.core import updater
        ui_helpers.open_url(updater.bug_report_url())

    @QtCore.Slot()
    def openRepo(self) -> None:
        ui_helpers.open_url(updater.REPO_URL)

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
            start_directory=_chooser_path(start), title=messages.TITLE_SAVE_LOG_TO_FOLDER,
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
            pane_files.reveal(target)

    @QtCore.Slot()
    def clearLog(self) -> None:
        """Through `debug.clear_log`, never a file removal: it also starts a new session header."""
        ok, reason = debug.clear_log()
        if not ok:
            debug.note(messages.LOG_NOT_CLEARED % reason)

    def setPageName(self, name: str) -> None:
        """Show page `name`, as the page list holds it: an Amaze page file, not one of Houdini's."""
        self.setPage(QtCore.QUrl.fromLocalFile(os.path.join(PAGES_FOLDER, name + "Page.qml")))

    def _tip_text(self, tip_id: str) -> str:
        """The tip a row or button shows; Active Library's also names the picked folder's path."""
        if tip_id == LIBRARY and self.getPref(LIBRARY):
            return TIPS[LIBRARY] + "\n\n" + library_dialog.shown_path(self.getPref(LIBRARY))
        if tip_id.startswith(ADDON):
            return tooltips.PREFS_ADDON_SWITCH
        return TIPS.get(tip_id, "")

    @QtCore.Slot(str, result=bool)
    def hasHelpTip(self, help_id: str) -> bool:
        return bool(self._tip_text(help_id))

    @QtCore.Slot(str, str, str)
    @QtCore.Slot(str, str, str, float, float, float, float, str)
    def showHelpTip(self, title: str, text: str, tip_id: str,
                    x=-1.0, y=-1.0, w=1.0, h=1.0, alignment="Left") -> None:
        """Houdini's tip window, with Amaze's text where Houdini reads its help pages."""
        text = text or _tip_html(self._tip_text(tip_id))
        super().showHelpTip(title, text, tip_id, x, y, w, h, alignment)


class AmazePrefsWindow(qmlviews.BaseQmlView):
    """Amaze Preferences: a QML window made as Houdini makes its Preferences window."""

    SOURCE_URL = QtCore.QUrl.fromLocalFile(os.path.join(PAGES_FOLDER, "Preferences.qml")).toString()
    DEFAULT_SIZE = QtCore.QSize(760, 680)    # Houdini's Preferences window's own default
    MINIMUM_SIZE = QtCore.QSize(530, 350)    # Houdini's Preferences window's own minimum

    closed = QtCore.Signal()    # at every close, Apply or not: a library chosen behind it is opened then

    def __init__(self, prefs, pane=None, *, parent_window: QtGui.QWindow = None) -> None:
        super().__init__(state=AmazePrefsState(prefs, pane), parent_window=parent_window)
        self.setTitle(branding.APP_NAME + " Preferences")

    def setupEngine(self) -> None:
        self.engine().addImageProvider("amazelogo", ui_helpers.LogoImages())    # as the section tabs' art

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
        self.closed.emit()
        self.deleteLater()    # as Houdini's window does: Qt deletes it, on the main thread

    def setPageName(self, name: str) -> None:
        self.sharedState().setPageName(name)
