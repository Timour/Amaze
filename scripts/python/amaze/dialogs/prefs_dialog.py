"""Five tabs built in code, no .ui file: every control writes into the prefs object IMMEDIATELY, the dialog persists on close, and there is no Cancel."""

import os
import platform
import urllib.parse

import hou

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QCloseEvent

import amaze
from amaze import amazetheme
from amaze import branding
from amaze.core import (debug, keyed_store, library_policy, renderers,
                        texture_library, users)
from amaze.dialogs import base_dialog, user_dialog
from amaze.helpers import hostos
from amaze.core import tile_icons
from amaze.helpers import theme
from amaze.helpers import ui_helpers
from amaze import messages
from amaze import tooltips
from amaze.panel import sections as sections_module
from amaze.prefs import prefs as prefs_mod


LINK_COLOR = amazetheme.LINK_COLOR   # About-tab links ▸p/one-design-document

PREFS_FRAMES = ("P01", "P02", "P03a", "P03b", "P04", "P05", "P06")   # the drawn frame per page, in tab order; a sub-tab is a page ▸p/one-design-document

VERSION_STEM = branding.APP_NAME + " v"   # what the drawn version line opens with; the number after it is a sample, and the widget goes on to carry the updater's answers
LIBRARY_VERSION_STEM = "Library version "   # P01's drawn line opens with it; its number is a sample

_logo_cache = None   # rendered once and reused as a QTextDocument resource, so the About page can reference it as an img src


def _logo_image(widget=None):
    """The Amaze wordmark cropped to its ink, since the artboard is mostly transparent; pass the WIDGET it will be drawn into. ▸r/screen-dpr"""
    global _logo_cache
    dpr = theme.screen_ratio(widget)   # keyed by DPR: rendered for one density and reused on another draws at half resolution
    if isinstance(_logo_cache, dict) and _logo_cache.get("dpr") == dpr:
        return _logo_cache["image"] or None

    path = amaze.package_file("ui", "logo.svg")
    image = None
    try:
        full = QtGui.QImage(1024, 512, QtGui.QImage.Format.Format_ARGB32)
        if ui_helpers.paint_svg(full, path):
            box = QtGui.QRegion(
                QtGui.QBitmap.fromImage(full.createAlphaMask())
            ).boundingRect()
            if not box.isEmpty():
                image = full.copy(box).scaledToHeight(   # DEVICE pixels tall with the ratio stamped, so the document draws it back at logical size
                    max(1, round(theme.ui_px(34) * dpr)),
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                image.setDevicePixelRatio(dpr)
    except Exception as exc:                                # noqa: BLE001
        debug.event("prefs", "About logo not loaded", error=str(exc))   # event, not note: the About logo is cosmetic
    _logo_cache = {"dpr": dpr, "image": image if image is not None
                   else False}
    return image


def bug_report_url() -> str:
    """The repo's new-issue page with this machine's three facts in GitHub's documented `body` query parameter - the URL only pre-fills a page in the user's browser, nothing is sent by building or opening it."""
    from amaze.core import updater

    body = ("Amaze: %s\nHoudini: %s\nOS: %s\n\nWhat happened:\n"
            % (branding.APP_VERSION, hou.applicationVersionString(),
               platform.platform()))
    return updater.NEW_ISSUE_URL + "?body=" + urllib.parse.quote(
        body, safe="")


def _open_url(url: str) -> None:
    if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):    # False = the OS refused the hand-off, and nothing-happened is the one outcome that teaches nothing
        debug.event("prefs", "the OS refused to open the bug page",
                    url=url)


def _show_value(widget, value) -> None:
    """Put a stored setting on a row: a combo by its token or text, a switch, or a number."""
    if isinstance(widget, QtWidgets.QComboBox):
        index = widget.findData(value)
        if index < 0:
            index = widget.findText(str(value))
        if index >= 0:
            widget.setCurrentIndex(index)
    elif isinstance(widget, QtWidgets.QAbstractButton):
        widget.setChecked(bool(value))
    else:
        try:
            widget.setValue(int(value))
        except (TypeError, ValueError):    # a hand-edited store can hold junk; the row keeps its value
            pass


def _show_quietly(widget, value) -> None:
    """`_show_value` with the widget's signals held, then left blocked or not as they were."""
    with QtCore.QSignalBlocker(widget):
        _show_value(widget, value)


def _chooser_path(path: str) -> str:
    """A folder spelled for `selectFile` and for prefs: forward slashes, trailing one only at a root."""
    return hostos.canonical_path_key(path) if path else ""   # empty stays empty: `canonical_path_key("")` is `"."`, which would open the chooser on the process working directory


def _content_holder(inner) -> QtWidgets.QWidget:
    """`inner` (a layout) inside a widget pinned to the drawn content column, so what the page is handed above that width stays empty at the right rather than moving every control. ▸r/tabwidget-adds-eight"""
    holder = QtWidgets.QWidget()
    inner.setContentsMargins(0, 0, 0, 0)    # a layout given to a WIDGET takes the style's own margin, where one added to another layout takes none - the page already carries the drawn margin
    holder.setLayout(inner)
    holder.setFixedWidth(theme.ui_px(amazetheme.PREFS_CONTENT_WIDTH))
    return holder


ADDON_ROW = ("add-on picture", "ToggleSwitch", "add-on version", "add-on author",
             "add-on short description")


def _p05(kind: str) -> list:
    """The Add-On frame's drawn boxes of one kind, (x, y, w, h), in drawn order."""
    return [node[1:5] for node in amazetheme.DIALOG_LAYOUT["P05"]["nodes"] if node[0] == kind]


def addon_row_boxes(index: int) -> dict:
    """Row `index`'s boxes in the list, design px: the first row as drawn, later ones as the second."""
    left, top = _p05("QTextBrowser")[0][:2]
    shift = max(index - 1, 0) * amazetheme.P05_ROW_PITCH
    boxes = {}
    for kind in ADDON_ROW + (("QWidget ▸ group divider",) if index else ()):
        drawn = _p05(kind)
        x, y, w, h = drawn[min(index, len(drawn) - 1)]
        boxes[kind] = (x - left, y - top + shift, w, h)
    return boxes


class PrefsDialog(base_dialog.AssetDialog):
    """Preferences on the house shell - live-apply, so no OK/Cancel and the inherited `canceled` is never read; resizable, tabs as the content."""

    FORM_WIDTH = amazetheme.PREFS_FORM_WIDTH

    def __init__(self, prefs, panel=None, file_files_model=None,
                 parent=None) -> None:
        super().__init__(branding.APP_NAME + " Preferences",
                         fixed_size=False, parent=parent)
        self._prefs = prefs
        keyed_store.refresh_all(prefs)    # opening this dialog is a DOOR: without it every list below is the copy read when the panel opened, so a user another machine created is invisible until Houdini restarts ▸r/peer-read
        # the panel owns the library operations and this only forwards; None in tests keeps the other tabs constructable
        self._panel = panel
        self._file_files_model = file_files_model
        self._tab_built: dict = {}    # each tab's widgets per KIND in CREATION order, which is what the frame's drawn rects of that kind answer
        self._sliders: dict = {}      # the slider `_field_slider_row` built beside each spin box
        self._path_rows: list = []    # every field-and-buttons row, re-spaced once its widgets wear their drawn widths

        tabs = QtWidgets.QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_library_tab(), "Library")
        tabs.addTab(self._build_render_tab(), "Render")
        tabs.addTab(self._build_showhide_tab(), "Show/Hide")
        tabs.addTab(self._build_look_tab(), "Look")
        tabs.addTab(self._build_addon_tab(), "Add-On")
        tabs.addTab(self._build_about_tab(), "About")
        self._tabs = tabs
        self._page_steps = dict(zip(PREFS_FRAMES, self._steps_to_pages()))

        self.set_content(tabs)
        self.finish(ok_cancel=False,   # a tabbed window keeps its air - the house margin is for compact forms
                    margins=amazetheme.PREFS_DIALOG_MARGIN)

        for combo in self.findChildren(QtWidgets.QComboBox):   # combos never TAKE focus, and this MUST run after setLayout since findChildren walks only the CURRENT tree
            combo.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._pin_pages_to_document()
        self.resize(   # BOTH numbers come from the document: `self.width()` stood here and is Qt's unshown-widget default of 640x480, so the drawn width was never `FORM_WIDTH` ▸p/one-design-document
            theme.ui_px(amazetheme.PREFS_FRAME[0]),
            theme.ui_px(amazetheme.PREFS_FRAME[1]),
        )


    def _tab_page(self):
        """(page widget, its form layout): every tab is one form with the shared right-aligned label column, top-aligned so short tabs keep their row spacing."""
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        _m = theme.ui_px(amazetheme.PREFS_PAGE_MARGIN)
        outer.setContentsMargins(_m, _m, _m, _m)
        form = self._make_form()
        outer.addWidget(_content_holder(form),
                        alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        outer.addStretch()
        return page, form

    def _steps_to_pages(self) -> list:
        """Every page as the clicks that show it - its tab, then its sub-tab - in tab order."""
        steps = []
        for index in range(self._tabs.count()):
            sub_tabs = self._tabs.widget(index).findChild(
                QtWidgets.QTabWidget, "",
                QtCore.Qt.FindChildOption.FindDirectChildrenOnly)
            if sub_tabs is None:
                steps.append(((self._tabs, index),))
                continue
            steps.extend(((self._tabs, index), (sub_tabs, sub))
                         for sub in range(sub_tabs.count()))
        return steps

    def frame_page(self, frame_key: str) -> QtWidgets.QWidget:
        """The page drawn as `frame_key`."""
        tab_widget, index = self._page_steps[frame_key][-1]
        return tab_widget.widget(index)

    def show_frame(self, frame_key: str) -> QtWidgets.QWidget:
        """Bring the page drawn as `frame_key` to the front: its tab, then its sub-tab."""
        for tab_widget, index in self._page_steps[frame_key]:
            tab_widget.setCurrentIndex(index)
        return self.frame_page(frame_key)

    def _reload_library_users(self) -> None:
        """Fill the picker and select the current user, signals held so the refill cannot switch user."""
        combo = self.cbb_library_user
        uid = users.current(self._prefs)
        with QtCore.QSignalBlocker(combo):
            combo.clear()
            user_dialog.fill_users(combo, users.all_users(self._prefs))
            combo.setCurrentIndex(max(combo.findData(uid), 0) if uid else -1)
        self._btn_edit_user.setEnabled(bool(uid))
        self._btn_delete_user.setEnabled(bool(uid))

    def _pick_library_user(self, index: int) -> None:
        """Switch this machine to the chosen user - or, on the create row, ask for a name and switch to the new one; which is what a second machine does instead of becoming a stranger."""
        data = self.cbb_library_user.itemData(index)
        if data == user_dialog.UserPickerDialog.CREATE:
            self._ask_create_library_user()
            return
        if data:
            users.adopt(self._prefs, data)
            self._sync_rows()

    def rename_library_user(self, name: str) -> None:
        """Relink the current user's NAME; the UID is untouched so everything already tagged stays tagged - one field write, not a migration."""
        uid = users.current(self._prefs)
        if uid and users.rename(self._prefs, uid, name):
            self._reload_library_users()

    def _ask_rename_library_user(self) -> None:
        uid = users.current(self._prefs)
        if not uid:
            return
        dialog = base_dialog.NameDialog(
            "Rename User", users.name_for(self._prefs, uid), parent=self)
        dialog.exec()
        if dialog.canceled:
            return
        if users.name_taken(self._prefs, dialog.name, besides=uid):
            self._say_name_taken(dialog.name)
            return
        self.rename_library_user(dialog.name)

    def _say_name_taken(self, name: str) -> None:
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(messages.USER_NAME_TAKEN % name.strip(),
                              severity=hou.severityType.Warning,
                              title=branding.APP_NAME)

    def create_library_user(self, name: str) -> None:
        """Mint a user and switch this machine to them - creating-then-becoming is this row's case; a second machine picking ITSELF is the first-open picker's."""
        uid = users.create(self._prefs, name)
        if uid:
            users.adopt(self._prefs, uid)
        self._sync_rows()

    def _ask_create_library_user(self) -> None:
        dialog = base_dialog.NameDialog("Create User", "", parent=self)
        dialog.exec()
        if dialog.canceled:
            self._reload_library_users()    # the combo is sitting on the create row; put the real selection back
            return
        if users.name_taken(self._prefs, dialog.name):
            self._say_name_taken(dialog.name)
            self._reload_library_users()
            return
        self.create_library_user(dialog.name)

    def delete_library_user(self, uid) -> None:
        """Delete `uid` and everything tagged theirs; the row goes blank until somebody is picked - nobody is adopted silently."""
        if users.delete(self._prefs, uid):
            self._sync_rows()

    def _ask_delete_library_user(self) -> None:
        uid = users.current(self._prefs)
        if not uid:
            return
        name = users.name_for(self._prefs, uid)
        answer = hou.ui.displayMessage(  # type: ignore
            messages.USER_DELETE_CONFIRM % name,
            help="Their favorites and registered folders are removed "
                 "from this library everywhere it syncs. A machine "
                 'signed in as "%s" will ask who is using the library '
                 "the next time it opens. This cannot be undone." % name,
            buttons=messages.BUTTONS_DELETE_USER,
            default_choice=1, close_choice=1,
            severity=hou.severityType.Warning,
            title=branding.APP_NAME,
        )
        if answer == 0:
            self.delete_library_user(uid)

    def set_allow_overwrite(self, checked: bool) -> None:
        """Write the overwrite policy to the LIBRARY; turning it ON is the direction that exposes other people's work, so that is the direction confirmed."""
        library_dir = self._prefs.dir
        if checked and not library_policy.allow_overwrite(library_dir):
            answer = hou.ui.displayMessage(  # type: ignore
                messages.MATERIAL_VERSIONS_TURN_ON_CONFIRM,
                help=messages.HELP_MATERIAL_VERSIONS,
                buttons=messages.BUTTONS_TURN_ON,
                default_choice=1, close_choice=1,
                severity=hou.severityType.Warning,
                title=branding.APP_NAME,
            )
            if answer != 0:
                _show_quietly(self._cbx_allow_overwrite, False)
                return
        if not library_policy.set_allow_overwrite(library_dir, checked):
            hou.ui.displayMessage(  # type: ignore
                messages.LIBRARY_SETTING_NOT_WRITTEN)
            _show_quietly(self._cbx_allow_overwrite, not checked)

    def _build_library_tab(self) -> QtWidgets.QWidget:
        page, form = self._tab_page()

        self.line_workdir = QtWidgets.QLineEdit(self._prefs.dir)
        self.line_workdir.setReadOnly(True)
        self.line_workdir.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_LIBRARY_PATH))
        browse_lib = QtWidgets.QPushButton("...")
        browse_lib.setFixedWidth(theme.ui_px(amazetheme.PREFS_BROWSE_W))
        browse_lib.clicked.connect(self.change_library_path)
        form.addRow(self._label("Library Path"), self._path_row(self.line_workdir, browse_lib))

        cleanup_btn = QtWidgets.QPushButton("Clean Up Library")
        cleanup_btn.clicked.connect(self._panel_call("cleanup_db"))
        cleanup_btn.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_CLEAN_UP_LIBRARY))
        form.addRow(self._label(""), cleanup_btn)
        reload_btn = QtWidgets.QPushButton("Reload Library")
        reload_btn.clicked.connect(self._panel_call("open"))
        reload_btn.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_RELOAD_LIBRARY))
        form.addRow(self._label(""), reload_btn)
        open_btn = QtWidgets.QPushButton("Open Library Folder")
        open_btn.clicked.connect(self._panel_call("open_usdlib_folder"))
        open_btn.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_OPEN_LIBRARY_FOLDER))
        form.addRow(self._label(""), open_btn)

        self._add_divider(form)
        # NOT A PREFERENCE: it lives in the library's own policy.json, because a switch protecting a SHARED thing must travel with the thing
        self._cbx_allow_overwrite = ui_helpers.ToggleSwitch(
            "Material Versions")
        self._cbx_allow_overwrite.setChecked(
            library_policy.allow_overwrite(self._prefs.dir))
        self._cbx_allow_overwrite.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_MATERIAL_VERSIONS))
        self._cbx_allow_overwrite.toggled.connect(self.set_allow_overwrite)
        form.addRow(self._label(""),
                    self._cbx_allow_overwrite)

        self.cbb_library_user = QtWidgets.QComboBox()   # shows the NAME, never the UID that everything is tagged with
        self.cbb_library_user.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_LIBRARY_USER))
        self._btn_edit_user = QtWidgets.QPushButton("Rename")
        self._btn_edit_user.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_RENAME_USER))
        self._btn_edit_user.clicked.connect(self._ask_rename_library_user)
        self._btn_delete_user = QtWidgets.QPushButton("Delete")
        self._btn_delete_user.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_DELETE_USER))
        self._btn_delete_user.clicked.connect(self._ask_delete_library_user)
        self._reload_library_users()
        self.cbb_library_user.currentIndexChanged.connect(
            self._pick_library_user)
        form.addRow(self._label("User"),
                    self._path_row(self.cbb_library_user,
                                   self._btn_edit_user,
                                   self._btn_delete_user))

        self._add_divider(form)
        self.line_cache = QtWidgets.QLineEdit(
            self._prefs.cache_dir or hostos.cache_root()
        )
        self.line_cache.setReadOnly(True)
        self.line_cache.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_CACHE_PATH))
        browse_cache = QtWidgets.QPushButton("...")
        browse_cache.setFixedWidth(theme.ui_px(amazetheme.PREFS_BROWSE_W))
        browse_cache.clicked.connect(self.change_cache_path)
        self._default_cache = QtWidgets.QPushButton("Default")
        self._default_cache.clicked.connect(self.reset_cache_path)
        self._default_cache.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_DEFAULT_CACHE))
        form.addRow(self._label("Cache Path"),
                    self._path_row(self.line_cache, browse_cache,
                                   self._default_cache))
        clear_cache_btn = QtWidgets.QPushButton("Delete Local Cache")
        clear_cache_btn.clicked.connect(self.clear_texture_cache)
        clear_cache_btn.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_DELETE_LOCAL_CACHE))
        form.addRow(self._label(""), clear_cache_btn)

        self._add_divider(form)
        self._lbl_library_version = QtWidgets.QLabel()    # filled by _sync_test_mode_rows
        form.addRow(self._label(""), self._lbl_library_version)

        self._tab_built["P01"] = {
            "QLineEdit": (self.line_workdir, self.line_cache),
            "QComboBox": (self.cbb_library_user,),
        }
        self._real_path_widgets = (self.line_workdir, browse_lib)   # inert under Test Mode: showing the test path while writing the real field could lose a library. CACHE rows stay live, Test Mode does not move the cache
        self._sync_test_mode_rows()
        return page

    def _sync_test_mode_rows(self) -> None:
        """Show where the library actually points, freezing the library row while the test switch is on."""
        on = bool(self._prefs.test_mode and self._prefs.test_dir)
        for widget in getattr(self, "_real_path_widgets", ()):
            widget.setEnabled(not on)
        self.line_workdir.setText(self._prefs.dir)
        self.refresh_library_version()

    def refresh_library_version(self) -> None:
        """Re-read the library's version: an update can land while this window is open."""
        label = getattr(self, "_lbl_library_version", None)
        if label is not None:
            label.setText(self._library_version_line())

    def _library_version_line(self) -> str:
        """`Library version 2` for the library the dialog points at; "" with none."""
        library_dir = str(self._prefs.dir or "")
        if not library_dir or not os.path.isdir(library_dir):
            return ""
        return LIBRARY_VERSION_STEM + str(library_policy.library_version(library_dir))

    def _build_render_tab(self) -> QtWidgets.QWidget:
        page, form = self._tab_page()

        self.line_rendersize = QtWidgets.QSpinBox()
        # range BEFORE value: a fresh QSpinBox clamps to Qt's default 0-99, so setValue(256) landed as 99 and persisted
        self.line_rendersize.setRange(*prefs_mod.RENDERSIZE_RANGE)
        self.line_rendersize.setValue(self._prefs.rendersize)
        self.line_rendersize.valueChanged.connect(self.set_rendersize)
        self.line_rendersize.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_RENDER_SIZE))
        form.addRow(self._label("RenderSize"), self._field_slider_row(
            self.line_rendersize, *prefs_mod.RENDERSIZE_RANGE))
        self._samples_spins, self._samples_rows = {}, {}
        for renderer in renderers.RENDER_TAB:
            spin = QtWidgets.QSpinBox()
            spin.setRange(*renderer.samples_range)
            spin.setValue(getattr(self._prefs, renderer.samples))
            spin.valueChanged.connect(
                lambda value, attr=renderer.samples: setattr(self._prefs, attr, value))
            spin.setToolTip(ui_helpers.tooltip_text(getattr(tooltips, renderer.samples_tip)))
            row = self._field_slider_row(spin, *renderer.samples_range)
            form.addRow(self._label("Samples (%s)" % renderer.engine), row)
            self._samples_spins[renderer.key] = spin
            self._samples_rows[renderer.key] = (form, row)
        self._show_offered_rows()
        self.spin_ram_cache = QtWidgets.QSpinBox()
        self.spin_ram_cache.setRange(*prefs_mod.RAM_CACHE_RANGE)
        self.spin_ram_cache.setValue(self._prefs.ram_cache_mb)
        self.spin_ram_cache.valueChanged.connect(self.set_ram_cache_mb)
        self.spin_ram_cache.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_RAM_CACHE))
        form.addRow(self._label("RAM Cache (MB)"),
            self._field_slider_row(self.spin_ram_cache,
                                   *prefs_mod.RAM_CACHE_RANGE),
        )
        self._combo_geo_shading = self._data_combo((   # geometry look, on NEWLY rendered thumbnails; each mode/bg combination keeps its own disk cache
            ("Hidden Line Ghost", "hiddenlineghost"),
            ("Smooth Wire Shaded", "smoothwireshaded"),
            ("Smooth Shaded", "smoothshaded"),
            ("Flat Wire Shaded", "flatwireshaded"),
            ("Flat Shaded", "flatshaded"),
            ("Wireframe", "wireframe"),
            ("Hidden Line Invisible", "hiddenlineinvisible"),
        ), "geometry_shading_mode")
        form.addRow(self._label("Geometry Shading"), self._combo_geo_shading)
        self._combo_geo_shading.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_GEOMETRY_SHADING))
        self._combo_geo_bg = self._data_combo((
            ("Black", "black"),
            ("White", "white"),
            ("Default (grey sky)", "default"),
        ), "geometry_bg")
        form.addRow(self._label("Geometry Background"), self._combo_geo_bg)
        self._combo_geo_bg.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_GEOMETRY_BACKGROUND))
        self.cbx_render_on_import = ui_helpers.ToggleSwitch("Render Thumbs on Import")
        self.cbx_render_on_import.setChecked(bool(self._prefs.render_on_import))
        self.cbx_render_on_import.stateChanged.connect(self.set_render_on_import)
        self.cbx_render_on_import.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_RENDER_ON_IMPORT))
        form.addRow(self._label(""), self.cbx_render_on_import)

        self._add_divider(form)
        self.spin_parallel = QtWidgets.QSpinBox()
        self.spin_parallel.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_CONVERSION_THREADS))
        form.addRow(
            self._label("Conversion Threads"),
            self._field_slider_row(self.spin_parallel,
                                   *prefs_mod.CONVERSIONS_RANGE),
        )
        self.spin_parallel.setValue(self._prefs.texture_parallel_conversions)   # range BEFORE value, then connect, so the initial set does not write the preference back to itself
        self.spin_parallel.valueChanged.connect(self.set_texture_parallel)

        self._add_divider(form)
        self.cbb_matx_res = QtWidgets.QComboBox()
        for label in ("1k", "2k", "4k", "8k"):
            self.cbb_matx_res.addItem(label)
        current = self.cbb_matx_res.findText(self._prefs.matx_resolution)
        self.cbb_matx_res.setCurrentIndex(current if current >= 0 else 1)
        self.cbb_matx_res.currentTextChanged.connect(self.set_matx_resolution)
        self.cbb_matx_res.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_DOWNLOAD_RESOLUTION))
        form.addRow(self._label("Download Resolution"), self.cbb_matx_res)
        self.spin_matx_parallel = QtWidgets.QSpinBox()
        self.spin_matx_parallel.setRange(*prefs_mod.DOWNLOADS_RANGE)
        self.spin_matx_parallel.setValue(self._prefs.matx_parallel_downloads)
        self.spin_matx_parallel.valueChanged.connect(
            self.set_matx_parallel_downloads
        )
        self.spin_matx_parallel.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_PARALLEL_DOWNLOADS))
        form.addRow(self._label("Parallel Downloads"),
            self._field_slider_row(self.spin_matx_parallel,
                                   *prefs_mod.DOWNLOADS_RANGE),
        )
        spins = ((self.line_rendersize,)
                 + tuple(self._samples_spins[r.key] for r in renderers.RENDER_TAB)
                 + (self.spin_ram_cache, self.spin_parallel, self.spin_matx_parallel))
        self._tab_built["P02"] = {
            "QComboBox": (self._combo_geo_shading, self._combo_geo_bg,
                          self.cbb_matx_res),
            "QSpinBox": spins,
            "ClickSlider": tuple(self._sliders[spin] for spin in spins),
        }
        return page

    def _build_showhide_tab(self) -> QtWidgets.QWidget:
        """Two sub-tabs, drawn as P03a and P03b: the renderer switches, then the section switches."""
        holder = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(holder)
        bar_x, bar_y = amazetheme.PREFS_SUBTAB_BAR[:2]
        tab_x, tab_y, _tab_w, tab_h = amazetheme.PREFS_TAB_BAR
        column.setContentsMargins(theme.ui_px(bar_x - tab_x),
                                  theme.ui_px(bar_y - tab_y - tab_h), 0, 0)
        sub_tabs = QtWidgets.QTabWidget()
        sub_tabs.setDocumentMode(True)
        sub_tabs.addTab(self._build_renderer_page(), "Renderer")
        sub_tabs.addTab(self._build_sections_page(), "Sections")
        column.addWidget(sub_tabs)
        return holder

    def _build_renderer_page(self) -> QtWidgets.QWidget:
        page, form = self._tab_page()
        self._renderer_boxes = {}
        for renderer in renderers.ALL:
            box = ui_helpers.ToggleSwitch(renderer.label)
            box.setToolTip(ui_helpers.tooltip_text(
                tooltips.PREFS_RENDERER_SWITCH))
            box.setChecked(bool(getattr(self._prefs, renderer.switch)))
            box.toggled.connect(
                lambda checked, attr=renderer.switch: self._offer_renderer(attr, checked))
            self._renderer_boxes[renderer.switch] = box
            form.addRow(self._label(""), box)
        return page

    def _build_sections_page(self) -> QtWidgets.QWidget:
        page, form = self._tab_page()
        self._section_boxes = {}
        for key, label in sections_module.all_sections():   # from the sections THEMSELVES; a hardcoded copy never learned about "hip", so that tab had no switch and was deleted by toggling any other
            box = ui_helpers.ToggleSwitch(label)
            box.setToolTip(ui_helpers.tooltip_text(
                tooltips.PREFS_SECTION_SWITCH))
            box.setChecked(key in self._prefs.enabled_sections)
            box.toggled.connect(self._on_section_toggled)
            self._section_boxes[key] = box
            form.addRow(self._label(""), box)
        return page

    def _build_look_tab(self) -> QtWidgets.QWidget:
        page, form = self._tab_page()

        self._cbx_sidebar_counts = ui_helpers.ToggleSwitch(
            "Show Counts on Categories"
        )
        self._cbx_sidebar_counts.setChecked(self._prefs.sidebar_counts)
        self._cbx_sidebar_counts.toggled.connect(self.set_sidebar_counts)
        self._cbx_sidebar_counts.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_SIDEBAR_COUNTS))
        form.addRow(self._label(""), self._cbx_sidebar_counts)

        self._cbx_hide_empty = ui_helpers.ToggleSwitch("Hide Empty Categories")
        self._cbx_hide_empty.setChecked(self._prefs.hide_empty_categories)
        self._cbx_hide_empty.toggled.connect(self.set_hide_empty_categories)
        self._cbx_hide_empty.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_HIDE_EMPTY_CATEGORIES))
        form.addRow(self._label(""), self._cbx_hide_empty)

        self._cbx_step_size = ui_helpers.ToggleSwitch("Step Size")
        self._cbx_step_size.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_STEP_SIZE))
        self._cbx_step_size.setChecked(self._prefs.step_size)
        self._cbx_step_size.toggled.connect(self.set_step_size)
        form.addRow(self._label(""), self._cbx_step_size)

        self._combo_path_style = self._data_combo((
            ("$HOME", "home"),
            ("$JOB", "job"),
            ("$HIP", "hip"),
            ("Absolute", "absolute"),
        ), "path_style")
        self._combo_path_style.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_WRITE_PATHS_AS))
        form.addRow(self._label("Write Paths As"), self._combo_path_style)

        self._combo_icon_weight = self._data_combo((
            ("Thin", "template"),
            ("Regular (Feather)", "feather"),
        ), "icon_line_weight")
        self._combo_icon_weight.currentIndexChanged.connect(
            self._recompose_tile_icons)
        form.addRow(self._label("Tile Icon Line"), self._combo_icon_weight)
        self._combo_icon_weight.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_TILE_ICON_LINE))

        self.spin_scroll_speed = QtWidgets.QSpinBox()
        percent = [round(end * 100) for end in prefs_mod.SCROLL_SPEED_RANGE]
        self.spin_scroll_speed.setRange(*percent)
        self.spin_scroll_speed.setValue(round(self._prefs.scroll_speed * 100))
        self.spin_scroll_speed.valueChanged.connect(self.set_scroll_speed)
        self.spin_scroll_speed.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_SCROLL_SPEED))
        form.addRow(self._label("Scroll Speed (%)"),
            self._field_slider_row(self.spin_scroll_speed, *percent),
        )
        self._tab_built["P04"] = {
            "QComboBox": (self._combo_path_style, self._combo_icon_weight),
            "QSpinBox": (self.spin_scroll_speed,),
            "ClickSlider": (self._sliders[self.spin_scroll_speed],),
        }
        return page

    def _build_about_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        _m = theme.ui_px(amazetheme.PREFS_PAGE_MARGIN)
        outer.setContentsMargins(_m, _m, _m, _m)

        browser = QtWidgets.QTextBrowser()   # not QTextEdit: it renders <a href> AND opens it
        browser.setOpenExternalLinks(True)
        browser.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        browser.viewport().setAutoFillBackground(False)   # palette-level transparency, NOT a stylesheet, so the text sits on the dialog's background
        pal = browser.palette()
        pal.setColor(
            QtGui.QPalette.ColorRole.Base,
            QtGui.QColor(0, 0, 0, 0),
        )
        browser.setPalette(pal)
        logo = _logo_image(self)
        if logo is not None:
            browser.document().addResource(
                QtGui.QTextDocument.ResourceType.ImageResource,
                QtCore.QUrl("amaze_logo"), logo,
            )
        browser.document().setDefaultStyleSheet(   # links a step darker than body text; Qt's default blue pulls the eye to the credits rather than the page
            "a { color: %s; text-decoration: underline; }" % LINK_COLOR
        )
        browser.setHtml(
            '<p><img src="amaze_logo"></p>'
            "<p><i>" + branding.APP_TAGLINE + "</i> "
            + '<span style="color:%s;">v' % LINK_COLOR
            + branding.APP_VERSION + "</span></p>"
            "<p>An asset library for Houdini: materials, textures, "
            "node setups, color palettes, geometry and code - browse, "
            "save, drag and assign.</p>"
            "<p>By Fredrik Timour.<br>"
            "<a href='https://github.com/Timour/Amaze'>"
            "github.com/Timour/Amaze</a></p>"
            "<p>Code and assets released under GPLv3 - free to use, "
            "modify, embed and redistribute under the license's "
            "terms.</p>"
            "<p><b>Modules and libraries from other projects</b><br>"   # credit, not obligation: every online source is CC0 or MIT, and each import records its own licence
            "Amaze uses the egMatLib preview engine for material "
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
            "licence.</p>"
            "<p><b>Generate Material</b> builds from the measured "
            "values of these two CC0 datasets: (Physically Based "
            "and EPFL RGL).</p>"
            "<p>Additional thanks: Feather Icons (MIT), "
            "Sanzo Wada / Paul Klee / Josef Albers / Johannes Itten "
            "(color palette sources, public domain).</p>"
        )
        inner = QtWidgets.QVBoxLayout()   # browser AND form share the pinned content column, the browser being drawn 450 wide like every row
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(browser, 1)

        form = self._make_form()
        self._lbl_version = QtWidgets.QLabel(   # EVERY update answer lands here, not in a popup: this dialog is non-modal by design ▸r/houdini-colour-picker
            "Amaze version " + branding.APP_VERSION)
        self._lbl_version.setWordWrap(True)
        form.addRow(self._label(""), self._lbl_version)
        self._last_update = None
        self._btn_update = QtWidgets.QPushButton()   # ON REQUEST ONLY: nothing consults the release feed at launch
        self._btn_update.clicked.connect(self._press_update)
        self._set_update_button(False)
        self._btn_report = QtWidgets.QPushButton("Report a Bug...")
        self._btn_report.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_REPORT_A_BUG))
        self._btn_report.clicked.connect(self.report_bug)
        ask_row = QtWidgets.QWidget()   # the two live side by side, from P06
        ask = QtWidgets.QHBoxLayout(ask_row)
        ask.setContentsMargins(0, 0, 0, 0)
        ask.setSpacing(theme.ui_px(amazetheme.PREFS_BUTTON_GAP))
        ask.addWidget(self._btn_update)
        ask.addWidget(self._btn_report)
        ask.addStretch(1)
        form.addRow(self._label(""), ask_row)
        self._path_rows.append(ask_row)    # spaced from the drawing like every other row of pinned widgets
        self._cbx_debug = ui_helpers.ToggleSwitch("Debug Mode")
        self._cbx_debug.setChecked(self._prefs.debug_mode)
        self._cbx_debug.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_DEBUG_MODE))
        self._cbx_debug.toggled.connect(self.set_debug_mode)
        debug_row = QtWidgets.QWidget()   # toggle and its two buttons on ONE row: three stacked rows read as three unrelated settings
        row = QtWidgets.QHBoxLayout(debug_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.ui_px(amazetheme.PREFS_BUTTON_GAP))
        row.addWidget(self._cbx_debug)
        row.addStretch(1)

        reveal_btn = QtWidgets.QPushButton("Open Log")
        reveal_btn.clicked.connect(self.reveal_debug_log)
        reveal_btn.setToolTip(ui_helpers.tooltip_text(tooltips.PREFS_OPEN_LOG))
        row.addWidget(reveal_btn)
        save_btn = QtWidgets.QPushButton("Save Log...")
        save_btn.setToolTip(ui_helpers.tooltip_text(tooltips.PREFS_SAVE_LOG))
        save_btn.clicked.connect(self.save_debug_log)
        row.addWidget(save_btn)
        clear_btn = QtWidgets.QPushButton("Clear Log")
        clear_btn.clicked.connect(self.clear_debug_log)
        clear_btn.setToolTip(ui_helpers.tooltip_text(tooltips.PREFS_CLEAR_LOG))
        row.addWidget(clear_btn)

        form.addRow(self._label(""), debug_row)
        self._path_rows.append(debug_row)    # the three log buttons take the drawn 8 and 6, not one gap twice

        self._add_divider(form)
        self._cbx_test_mode = ui_helpers.ToggleSwitch("Test Library")   # under Debug Mode but NOT attached to it; both paths are overlays and locations stay isolated both ways
        self._cbx_test_mode.setChecked(self._prefs.test_mode)
        self._cbx_test_mode.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_TEST_LIBRARY))
        self._cbx_test_mode.toggled.connect(self.set_test_mode)

        self.line_test_dir = QtWidgets.QLineEdit(self._prefs.test_dir)
        self.line_test_dir.setReadOnly(True)
        self.line_test_dir.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_TEST_FOLDER))
        self._browse_test = QtWidgets.QPushButton("...")
        self._browse_test.setFixedWidth(theme.ui_px(amazetheme.PREFS_BROWSE_W))
        self._browse_test.clicked.connect(self.change_test_path)
        test_row = QtWidgets.QWidget()   # the switch and its folder on ONE row, as P06 draws them
        row = QtWidgets.QHBoxLayout(test_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._cbx_test_mode)
        row.addStretch(1)
        row.addWidget(self.line_test_dir)
        row.addWidget(self._browse_test)
        form.addRow(self._label(""), test_row)
        self._path_rows.append(test_row)

        self._cbx_addon_betas = ui_helpers.ToggleSwitch("Add-On beta versions")
        self._cbx_addon_betas.setChecked(self._prefs.addon_betas)
        self._cbx_addon_betas.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_ADDON_BETAS))
        self._cbx_addon_betas.toggled.connect(self.set_addon_betas)
        form.addRow(self._label(""), self._cbx_addon_betas)

        inner.addLayout(form)
        outer.addWidget(_content_holder(inner),
                        alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        self._tab_built["P06"] = {
            "QTextBrowser": (browser,),
            "QLineEdit": (self.line_test_dir,),
        }
        return page

    def _build_addon_tab(self) -> QtWidgets.QWidget:
        """The installed add-ons as their packages list them, and one button: check, then update."""
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        _m = theme.ui_px(amazetheme.PREFS_PAGE_MARGIN)
        outer.setContentsMargins(_m, _m, _m, _m)
        inner = QtWidgets.QVBoxLayout()
        inner.setSpacing(theme.ui_px(amazetheme.P05_LIST_TO_BUTTON))
        self._addon_list = QtWidgets.QScrollArea()
        self._addon_list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._addon_list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner.addWidget(self._addon_list, 1)
        self._btn_addons = QtWidgets.QPushButton()
        self._btn_addons.clicked.connect(self._press_addons)
        self._lbl_addons = QtWidgets.QLabel()
        self._lbl_addons.setWordWrap(True)
        bottom = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(bottom)
        row.setContentsMargins(
            theme.ui_px(_p05("QPushButton")[0][0] - _p05("QTextBrowser")[0][0]), 0, 0, 0)
        row.addWidget(self._btn_addons)
        row.addWidget(self._lbl_addons, 1)
        inner.addWidget(bottom)
        self._path_rows.append(bottom)
        outer.addWidget(_content_holder(inner),
                        alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        self._addons_found = []
        self._set_addons_button(False)
        self.fill_addon_rows()
        return page

    def fill_addon_rows(self) -> None:
        """A row per group of every installed add-on, from its package alone; a line when none is."""
        from amaze.core import addons, updater
        root = updater.install_root()
        rows = [(folder, manifest, group)
                for folder, manifest in (addons.installed_all(root) if root else [])
                for group in addons.rows(manifest)]
        holder = QtWidgets.QWidget()
        width = theme.ui_px(_p05("QTextBrowser")[0][2])
        self.addon_rows = []
        if not rows:
            blank = QtWidgets.QLabel(messages.ADDONS_NONE, holder)
            blank.setWordWrap(True)
            blank.setFixedWidth(width)
            blank.adjustSize()
        for index, (folder, manifest, group) in enumerate(rows):
            self.addon_rows.append(self._addon_row(holder, index, root, folder, manifest, group))
        holder.setFixedSize(width, max(child.geometry().bottom() + 1
                                       for child in holder.findChildren(QtWidgets.QWidget)))
        self._addon_list.setWidget(holder)

    def _addon_row(self, holder, index, root, folder, manifest, group) -> dict:
        """Row `index`, placed from the drawn rows; answers its widgets by drawn kind."""
        from amaze.core import addons
        box = {kind: tuple(theme.ui_px(v) for v in rect)
               for kind, rect in addon_row_boxes(index).items()}
        picture = QtWidgets.QLabel(holder)
        picture.setPixmap(self._addon_picture(
            os.path.join(root, addons.ROOT, folder, *group["addon_icon"].split("/")), holder))
        picture.move(*box["add-on picture"][:2])
        picture.adjustSize()
        built = {"add-on picture": picture}
        for kind, text, ink in (
                ("add-on version", messages.ADDON_VERSION % manifest["version"], amazetheme.P05_DIM_INK),
                ("add-on author", messages.ADDON_AUTHOR % manifest["author"], amazetheme.P05_DIM_INK),
                ("add-on short description", group["short_description"], amazetheme.P05_TEXT_INK)):
            label = QtWidgets.QLabel(text, holder)
            label.setStyleSheet("color: %s;" % ink)
            if kind == "add-on short description":
                label.setWordWrap(True)
                label.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
                label.setToolTip("\n\n".join(n["description"] for n in group["nodes"] if n["description"]))
                label.setGeometry(*box[kind])
            else:
                label.move(*box[kind][:2])
                label.adjustSize()
            built[kind] = label
        switch = ui_helpers.ToggleSwitch(group["name"], holder)
        switch.setChecked(addons.is_on(root, folder, group))
        switch.setToolTip(ui_helpers.tooltip_text(tooltips.PREFS_ADDON_SWITCH))
        switch.toggled.connect(
            lambda on, f=folder, g=group, s=switch: self.turn_addon(root, f, g, s, on))
        switch.move(*box["ToggleSwitch"][:2])
        switch.adjustSize()
        built["ToggleSwitch"] = switch
        if index:
            divider = QtWidgets.QWidget(holder)
            divider.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
            divider.setStyleSheet("background-color: %s;" % amazetheme.PREFS_DIVIDER_INK)
            divider.setGeometry(*box["QWidget ▸ group divider"])
            built["QWidget ▸ group divider"] = divider
        picture.lower()
        return built

    def _addon_picture(self, path: str, widget) -> QtGui.QPixmap:
        """The package's own picture: an SVG fills the drawn slot, a PNG shows at half its pixels."""
        ratio = theme.screen_ratio(widget)
        if path.lower().endswith(".svg"):
            return ui_helpers.device_pixmap(path, theme.ui_px(_p05("add-on picture")[0][2]), ratio)
        image = QtGui.QPixmap(path)
        if image.isNull():
            return image
        size = QtCore.QSize(int(round(theme.ui_px(image.width() / 2) * ratio)),
                            int(round(theme.ui_px(image.height() / 2) * ratio)))
        image = image.scaled(size, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                             QtCore.Qt.TransformationMode.SmoothTransformation)
        image.setDevicePixelRatio(ratio)
        return image

    def turn_addon(self, root: str, folder: str, group, switch, on: bool) -> None:
        """Move a group in or out of Houdini's reach and say a restart is due; on failure, undo the switch."""
        from amaze.core import addons, packages
        try:
            addons.set_on(root, folder, group, on)
        except packages.PackageError as exc:
            _show_quietly(switch, not on)
            self._lbl_addons.setText(str(exc))
            return
        self._lbl_addons.setText(messages.ADDONS_TURNED % (group["name"], "on" if on else "off"))

    def _set_addons_button(self, offer: bool) -> None:
        """Check for Updates, or Update once a check found something; one drawn box for both."""
        self._btn_addons.setText("Update" if offer else "Check for Updates")
        ui_helpers.pin_drawn(self._btn_addons, "P05", "QPushButton", "Check for Updates")
        self._btn_addons.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_ADDONS_UPDATE if offer else tooltips.PREFS_ADDONS_CHECK))

    def _press_addons(self) -> None:
        """Check, then update: the press that installs is never the press that looked."""
        if self._addons_found:
            self.install_addons()
        else:
            self.check_addons()

    @debug.guarded("prefs.check_addons")
    def check_addons(self) -> None:
        """Ask the store, on request only, and say the answer in the line beside the button."""
        from amaze.actions import addons as addon_actions
        self._btn_addons.setEnabled(False)
        self._btn_addons.setText("Checking...")
        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        found, sentence = addon_actions.check(self._prefs.addon_betas)
        self._addons_found = found
        self._btn_addons.setEnabled(True)
        self._set_addons_button(bool(found))
        self._lbl_addons.setText(sentence)

    @debug.guarded("prefs.install_addons")
    def install_addons(self) -> None:
        """Install what the last check found, with no popup: the line says what happened."""
        from amaze.actions import addons as addon_actions
        from amaze.core import updater
        root = updater.install_root()
        if not root:
            self._lbl_addons.setText(messages.ADDONS_LOCATION_UNKNOWN)
            return
        self._btn_addons.setEnabled(False)
        self._btn_addons.setText("Installing...")
        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        sentence = addon_actions.install(self._addons_found, root)
        self._addons_found = []
        self._btn_addons.setEnabled(True)
        self._set_addons_button(False)
        self._lbl_addons.setText(sentence)
        self.fill_addon_rows()

    def _pin_pages_to_document(self) -> None:
        """Take every widget on every tab from the frame drawn for that tab, so a node resized in Figma resizes the widget. The editor INSIDE a spin box is left alone - the document draws that box 2 taller and insets its editor by 1. ▸p/one-design-document"""
        for frame_key in PREFS_FRAMES:
            page = self.frame_page(frame_key)
            drawn_again: dict = {}    # P01 draws `...` twice, so the second browse button takes the second box
            for button in page.findChildren(QtWidgets.QPushButton):
                label = button.text()
                nth = drawn_again.get(label, 0)
                drawn_again[label] = nth + 1
                ui_helpers.pin_drawn(button, frame_key, "QPushButton",
                                     label, nth=nth)
            for kind, widgets in self._tab_built.get(frame_key, {}).items():
                ui_helpers.pin_drawn_series(widgets, frame_key, kind)
        ui_helpers.pin_drawn_stem(self._lbl_version, "P06", "QLabel",
                                  VERSION_STEM, height=False)
        ui_helpers.pin_drawn_stem(self._lbl_library_version, "P01", "QLabel",
                                  LIBRARY_VERSION_STEM, height=False)
        ui_helpers.pin_drawn(self._addon_list, "P05", "QTextBrowser", None, height=False)
        ui_helpers.pin_drawn(self._lbl_addons, "P05", "QLabel", None, height=False)
        for row in self._path_rows:
            self._space_pinned_row(row)

    def _space_pinned_row(self, row) -> None:
        """Give the row the DRAWN gap between each pair, so every widget lands on its drawn x. The frame draws them uneven - P01's cache row leaves 4 then 2 - and one shared spacing puts each widget near its box instead of on it."""
        layout = row.layout()
        items = [layout.itemAt(i) for i in range(layout.count())]
        plan = []
        for index in range(len(items) - 1):
            left, right = items[index].widget(), items[index + 1].widget()
            if left is None or right is None:
                continue    # a stretch stands between them and owns that gap
            drawn = (getattr(left, "drawn_box", None),
                     getattr(right, "drawn_box", None))
            if None in drawn:
                continue    # an unpinned widget: its drawn x is unknown, and a guessed gap is worse than Qt's own
            plan.append((index + 1,
                         max(drawn[1][0] - (drawn[0][0] + drawn[0][2]), 0)))
        if not plan:
            return
        layout.setSpacing(0)    # the gaps are the spacers below; a spacing on top of them would add itself to every one
        for position, gap in reversed(plan):    # from the END, so the positions ahead of each insert are still the ones planned
            layout.insertSpacing(position, theme.ui_px(gap))

    LABEL_COL = amazetheme.PREFS_LABEL_COL   # ONE fixed label-column width for every row on every tab, matching Houdini's own panes, which CLIP a long label rather than widen

    def _label(self, text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setFixedWidth(theme.ui_px(self.LABEL_COL))
        lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        return lbl

    def _data_combo(self, items, attr) -> QtWidgets.QComboBox:
        """Combo whose entries carry a token in itemData; selecting one writes `self._prefs.<attr>` and saves."""
        combo = QtWidgets.QComboBox()
        for label, token in items:
            combo.addItem(label, token)
        current = combo.findData(getattr(self._prefs, attr))
        combo.setCurrentIndex(max(current, 0))

        def _changed(index, c=combo, a=attr):
            token = c.itemData(index)
            if token:
                setattr(self._prefs, a, token)
                self._prefs.save()

        combo.currentIndexChanged.connect(_changed)
        return combo

    def _path_row(self, line_edit, browse_btn, *extra) -> QtWidgets.QWidget:
        """A path field, its browse button, and any button after it; the cache row carries a Default beside the browse. The gaps land in `_space_pinned_row`, once every widget in it wears its drawn width."""
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(line_edit, 1)
        h.addWidget(browse_btn)
        for widget in extra:
            h.addWidget(widget)
        self._path_rows.append(row)
        return row

    def _panel_call(self, method_name: str):
        """A click handler forwarding to a panel method, guarded for the panel-less test construction."""
        def _call():
            if self._panel is not None:
                getattr(self._panel, method_name)()
        return _call

    def _add_divider(self, form: QtWidgets.QFormLayout) -> None:
        """A 1px group divider as a spanning row; groups carry no title text, like Houdini's own parameter panes."""
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(0, theme.ui_px(amazetheme.PREFS_DIVIDER_ABOVE),
                             0, theme.ui_px(amazetheme.PREFS_DIVIDER_BELOW))
        divider = QtWidgets.QWidget()
        divider.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_StyledBackground, True
        )
        divider.setStyleSheet("background-color: %s;"
                              % amazetheme.PREFS_DIVIDER_INK)
        divider.setFixedHeight(theme.ui_px(amazetheme.PREFS_DIVIDER_H))
        v.addWidget(divider)
        form.addRow(box)

    def _field_slider_row(
        self, spinbox: QtWidgets.QSpinBox, lo: int, hi: int
    ) -> QtWidgets.QWidget:
        """Houdini-style numeric row: number field + ClickSlider kept in sync both ways, terminating because setValue with an unchanged value emits nothing."""
        spinbox.setRange(lo, hi)
        spinbox.setButtonSymbols(
            QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        slider = ui_helpers.ClickSlider()
        slider.setOrientation(QtCore.Qt.Orientation.Horizontal)
        slider.snap_marks = ()   # no tick dots or snap magnets here; those belong to the toolbar's size slider only
        slider.setRange(lo, hi)
        slider.setValue(spinbox.value())
        slider.set_accent_color(theme.accent(self._prefs.accent_color))
        spinbox.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(spinbox.setValue)
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.ui_px(amazetheme.PREFS_BUTTON_GAP))
        h.addWidget(spinbox)
        h.addWidget(slider, 1)
        self._sliders[spinbox] = slider
        return row

    @staticmethod
    def _make_form() -> QtWidgets.QFormLayout:
        """A QFormLayout configured like the panel's details view, so every group in this dialog reads as the same kind of row."""
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignTrailing
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        form.setHorizontalSpacing(   # EXPLICIT: a style computes label-to-field spacing per widget-type pair, drifting the shared column between tabs
            theme.ui_px(amazetheme.PREFS_LABEL_GAP))
        form.setVerticalSpacing(theme.ui_px(amazetheme.PREFS_ROW_GAP))
        return form


    def change_library_path(self) -> None:
        """Browse for a new library directory, through the panel's own set_library flow: validation, seed copy, model switching."""
        if self._panel is None:
            return
        self._prefs.save()    # before the switch: unsaved edits belong to the library they were made in
        self._panel.set_library()
        self.line_workdir.setText(self._prefs.dir)
        self._sync_rows()

    def change_cache_path(self) -> None:
        """Pick a custom thumbnail-cache location; an empty selection keeps the current one and existing caches regenerate at the new location on demand."""
        start = _chooser_path(self._prefs.cache_dir or hostos.cache_root())
        path = hou.ui.selectFile(
            start_directory=start, file_type=hou.fileType.Directory
        )
        if not path:
            return
        self._prefs.cache_dir = _chooser_path(hou.text.expandString(path))
        self._prefs.save()
        hostos.set_cache_override(self._prefs.cache_dir)
        self.line_cache.setText(self._prefs.cache_dir)

    def reset_cache_path(self) -> None:
        """Put the cache back to this machine's own location by CLEARING the preference, never by writing today's default as a literal path; nothing is deleted."""
        self._prefs.cache_dir = ""
        self._prefs.save()
        hostos.set_cache_override("")
        self.line_cache.setText(hostos.cache_root())

    def change_test_path(self) -> None:
        """Pick the folder holding the test lib and cache, SEEDED on the way in: a directory with no index does not load, so an empty folder would answer with a traceback."""
        start = _chooser_path(self._prefs.test_dir or self._prefs.dir)
        path = hou.ui.selectFile(
            start_directory=start, file_type=hou.fileType.Directory
        )
        if not path:
            return
        folder = _chooser_path(hou.text.expandString(path))
        ok, what = prefs_mod.seed_test_folder(folder)
        if not ok:
            hou.ui.displayMessage(  # type: ignore
                messages.TEST_FOLDER_NOT_PREPARED % what)
            return
        self._prefs.save()    # before the switch: unsaved edits belong to the library they were made in
        self._prefs.test_dir = folder
        self._prefs.save()
        self.line_test_dir.setText(folder)
        self._apply_test_mode()

    def set_test_mode(self, on: bool) -> None:
        """Switch the library and cache onto the test folder, or back; turning it on with no folder asks for one first, since the overlay ignores a blank one."""
        self._prefs.save()    # before the switch: unsaved edits belong to the library they were made in
        self._prefs.test_mode = bool(on)
        if on and not self._prefs.test_dir:
            self._prefs.save()
            self.change_test_path()
            if not self._prefs.test_dir:
                self._prefs.test_mode = False   # still nothing chosen, so put the switch back rather than leave it lying
                _show_quietly(self._cbx_test_mode, False)
                self._prefs.save()
            return
        if on:
            prefs_mod.seed_test_folder(self._prefs.test_dir)
        self._prefs.save()
        self._apply_test_mode()

    def _apply_test_mode(self) -> None:
        """Point the running session at whichever library now applies; the cache is NOT touched, so thumbnails already generated stay valid."""
        self._sync_test_mode_rows()
        debug.event("prefs", "test library switched",
                    on=self._prefs.test_mode, folder=self._prefs.test_dir,
                    library=self._prefs.dir)
        if self._panel is not None and not self._panel.open_library():
            _show_quietly(self._cbx_test_mode, self._prefs.test_mode)    # a Cancel put it back
            self._sync_test_mode_rows()
        self._sync_rows()

    _SHARED_ROWS = (    # (row attribute, the shared setting it shows); renderer switches ride beside
        ("line_rendersize", "rendersize"),
        ("spin_ram_cache", "ram_cache_mb"),
        ("spin_parallel", "texture_parallel_conversions"),
        ("spin_matx_parallel", "matx_parallel_downloads"),
        ("cbb_matx_res", "matx_resolution"),
        ("_combo_geo_shading", "geometry_shading_mode"),
        ("_combo_geo_bg", "geometry_bg"),
        ("_combo_path_style", "path_style"),
        ("cbx_render_on_import", "render_on_import"),
    )

    _USER_ROWS = (    # (row attribute, the per-user setting it shows); sections and scroll ride beside
        ("_cbx_sidebar_counts", "sidebar_counts"),
        ("_cbx_hide_empty", "hide_empty_categories"),
        ("_cbx_step_size", "step_size"),
        ("_combo_icon_weight", "icon_line_weight"),
        ("_cbx_debug", "debug_mode"),
        ("_cbx_addon_betas", "addon_betas"),
    )

    def _shown_values(self):
        """(row, the value it shows) for every row holding a shared or a per-user setting."""
        prefs = self._prefs
        for name, prop in self._SHARED_ROWS + self._USER_ROWS:
            yield getattr(self, name), getattr(prefs, prop)
        for attr, box in self._renderer_boxes.items():
            yield box, getattr(prefs, attr)
        for renderer in renderers.RENDER_TAB:
            yield self._samples_spins[renderer.key], getattr(prefs, renderer.samples)
        for key, box in self._section_boxes.items():
            yield box, key in prefs.enabled_sections
        yield self.spin_scroll_speed, round(prefs.scroll_speed * 100)

    def _sync_rows(self) -> None:
        """The door after a library or user change: every row re-reads, signals blocked."""
        drawn_weight = self._combo_icon_weight.currentData()    # what the tiles were composed with
        self._reload_library_users()
        self._sync_overwrite_switch()
        for widget, value in self._shown_values():
            for shown in (widget, self._sliders.get(widget)):
                if shown is not None:
                    _show_quietly(shown, value)
        self._show_offered_rows()
        if self._prefs.icon_line_weight != drawn_weight:
            self._recompose_tile_icons()

    def _sync_overwrite_switch(self) -> None:
        """Re-read the overwrite switch from the library NOW bound - policy.json travels with the library, not with these preferences."""
        _show_quietly(self._cbx_allow_overwrite,
                      library_policy.allow_overwrite(self._prefs.dir))

    def clear_texture_cache(self) -> None:
        """Delete every cached image and geometry thumbnail; they regenerate on the next browse. Scene CAPTURES are untouched - hand-framed, not regenerable, and stored under config_root for that reason."""
        if not hou.ui.displayConfirmation(
            messages.CONFIRM_CLEAR_THUMBNAIL_CACHE,
            suppress=hou.confirmType.NoConfirmType,   # NOT the default, which is `hou.confirmType.OverwriteFile` - Houdini's GLOBAL do-not-ask-again flag for file overwrites, so one tick of that box anywhere would let this delete every thumbnail unasked
        ):
            return
        if self._file_files_model is not None:
            self._file_files_model.clear_cache()
        else:
            texture_library.ThumbnailCache(self._prefs.rendersize).clear()


    def set_texture_parallel(self, value: int) -> None:
        self._prefs.texture_parallel_conversions = value

    def set_matx_resolution(self, label: str) -> None:
        self._prefs.matx_resolution = label

    def set_matx_parallel_downloads(self, value: int) -> None:
        """Read fresh on every dispatch, so it applies to the next batch without a restart."""
        self._prefs.matx_parallel_downloads = value

    @debug.guarded("prefs.report_bug")
    def report_bug(self) -> None:
        """Open the pre-filled new-issue page; openUrl answers only whether the OS ACCEPTED the hand-off, and `_open_url` records a refusal. ▸r/github-issue-url"""
        _open_url(bug_report_url())

    def _installable(self):
        """The release the last check found, when it named a file to fetch; None when there is nothing to install."""
        result = self._last_update
        return result if result and getattr(result, "url", "") else None

    def _set_update_button(self, offer: bool) -> None:
        """The one button in its two readings; the tooltip moves with the label, since nothing being downloaded stops being true in the second."""
        self._btn_update.setText(
            "Install Update" if offer else "Check for Updates")
        ui_helpers.pin_drawn(   # ONE drawn box for both readings: the word moves, the geometry does not
            self._btn_update, "P06", "QPushButton", "Check for Updates")
        self._btn_update.setToolTip(ui_helpers.tooltip_text(
            tooltips.PREFS_INSTALL_UPDATE
            if offer else
            tooltips.PREFS_CHECK_FOR_UPDATES))
        warn = offer and self._update_reaches_library()    # ▸ P06 draws it red
        self._btn_update.setStyleSheet(
            "QPushButton { background-color: %s; }" % amazetheme.UPDATE_WARNING_FILL
            if warn else "")

    def _update_reaches_library(self) -> bool:
        """The update the last check found also updates this library."""
        from amaze.core import updater
        return updater.updates_library(self._last_update, self._prefs.dir)

    def _press_update(self) -> None:
        """Check, then install: the button only reaches the install once a check has found one, so the press that downloads is never the press that looked."""
        if self._installable() is None:
            self.check_for_updates()
        else:
            self.install_update()

    @debug.guarded("prefs.check_for_updates")
    def check_for_updates(self) -> None:
        """Ask the release feed and say the answer in the version line; it BLOCKS, which is why the button says so - a worker thread would be more machinery than the wait it saves."""
        from amaze.core import updater

        self._btn_update.setEnabled(False)
        self._btn_update.setText("Checking...")
        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            self._last_update = updater.check()
        finally:
            self._btn_update.setEnabled(True)
            self._set_update_button(   # offered only when the release NAMED a file; one with no archive is offered nowhere rather than offered and then failing
                self._installable() is not None)
        self._lbl_version.setText(updater.offer_line(self._last_update, self._prefs.dir))

    def install_update(self) -> None:
        """Fetch the release the last check found; Continue or Cancel first if it updates the library."""
        from amaze.core import updater
        from amaze.dialogs import update_dialog

        result = self._installable()
        if result is None:
            return
        if not update_dialog.confirmed(result, self._prefs.dir):    # the shelf tool asks the same
            return

        self._btn_update.setEnabled(False)
        self._btn_update.setText("Installing...")
        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            updater.install(result)    # the SAME call the shelf tool makes, so the two cannot drift
        except OSError as exc:
            self._lbl_version.setText(str(exc))   # the updater raises with a FINISHED sentence, shown as-is rather than wrapped in a second one
        except Exception as exc:                              # noqa: BLE001
            debug.exception("update install", exc)
            self._lbl_version.setText(messages.UPDATE_FAILED_UNEXPECTED % exc)
        else:
            self._last_update = None   # the offer is spent, so the next press asks the feed again rather than fetching a second time
            self._lbl_version.setText(
                messages.UPDATE_INSTALLED % result.version)
        finally:
            self._btn_update.setEnabled(True)
            self._set_update_button(self._installable() is not None)

    def set_debug_mode(self, checked: bool) -> None:
        """Takes effect IMMEDIATELY: the engine is reconfigured here as well as on close, so a session can be captured without restarting Houdini."""
        self._prefs.debug_mode = checked
        debug.configure(checked)
        if checked:
            debug.prefs_snapshot(self._prefs)

    def set_addon_betas(self, checked: bool) -> None:
        """Pick the kind Check for Updates installs; what a check found was the other kind's."""
        self._prefs.addon_betas = checked
        self._addons_found = []
        self._set_addons_button(False)

    def reveal_debug_log(self) -> None:
        """Open the log FILE itself; an empty log opens its folder instead."""
        path = debug.log_path()
        folder = os.path.dirname(path)
        try:
            os.makedirs(folder, exist_ok=True)
            hostos.open_path(path if os.path.exists(path) else folder)    # it reveals what nothing opens
        except Exception as exc:
            debug.event("prefs", "could not open log", error=str(exc))

    def save_debug_log(self) -> None:
        """Export the log to a folder the user picks - a DELIBERATE act every time, never a setting, because the file carries their paths and asset names."""
        start = self._prefs.dir or os.path.expanduser("~")   # `.dir` is the attribute Prefs actually has; a wrong name raises inside a Qt slot, which PySide swallows
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Save Amaze log to folder", start)
        if not folder:
            return                       # cancelled, not failed
        try:
            target = debug.export_log(folder)
        except debug.ExportRefused as exc:
            QtWidgets.QMessageBox.information(   # SAY WHY: nothing-happened is the one outcome that teaches nothing
                self, messages.TITLE_LOG_NOT_SAVED, str(exc))
            debug.event("prefs", "log export refused", reason=str(exc))
            return
        except Exception as exc:                         # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, messages.TITLE_LOG_NOT_SAVED,
                messages.LOG_NOT_SAVED_UNEXPECTED % exc)
            return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Amaze - log saved")
        box.setText("Saved as:\n%s" % os.path.basename(target))
        box.setInformativeText(
            "It contains your file paths, asset and material names - "
            "check before sharing it.")
        reveal = box.addButton("Show in Folder",
                               QtWidgets.QMessageBox.ActionRole)
        box.addButton(QtWidgets.QMessageBox.Close)
        box.exec()
        if box.clickedButton() is reveal:
            hostos.reveal_path(target)

    def clear_debug_log(self) -> None:
        # through the ENGINE, not os.remove behind its back: it owns the session header and the flood counters
        ok, reason = debug.clear_log()
        if not ok:
            debug.note(
                "the debug log could not be cleared (%s). It is still "
                "there, and Debug Mode keeps writing to it." % reason)

    def set_rendersize(self):
        """RenderSize is ALSO the resolution texture and geometry thumbnails generate at; their caches are keyed by it."""
        self._prefs.rendersize = self.line_rendersize.value()

    def _offer_renderer(self, switch, checked) -> None:
        """A Show/Hide switch: the preference, and that renderer's samples row with it."""
        setattr(self._prefs, switch, checked)
        self._show_offered_rows()

    def _show_offered_rows(self) -> None:
        """A renderer hidden in Show/Hide has no samples row on the Render tab either."""
        offered = {renderer.key for renderer in renderers.offered(self._prefs)}
        for key, (form, row) in getattr(self, "_samples_rows", {}).items():
            form.setRowVisible(row, key in offered)

    def set_scroll_speed(self, value: int) -> None:
        self._prefs.scroll_speed = value / 100.0

    def set_ram_cache_mb(self, value: int) -> None:
        """NO save() here, closeEvent persists it: a slider fires valueChanged per mouseMoveEvent, so one drag fsynced settings.json hundreds of times. The live budget still updates immediately."""
        self._prefs.ram_cache_mb = value

    def _recompose_tile_icons(self, _index=None) -> None:
        """Line weight changed: forget composed pictures, then every tile-icon model redraws."""
        tile_icons.forget_composed()
        if self._panel is None:
            return
        for model in self._panel.tile_icon_models():
            model.rerender_tile_icons()

    def set_sidebar_counts(self, checked: bool) -> None:
        self._prefs.sidebar_counts = checked
        self._prefs.save()

    def _on_section_toggled(self, _checked: bool) -> None:
        """Rebuild enabled_sections in ALL_SECTIONS order, never leaving zero enabled; keys THIS build does not register are carried over untouched, or another build's tabs are deleted by side effect."""
        order = [k for k, _lbl in sections_module.all_sections()]
        enabled = [k for k in order
                   if k in self._section_boxes
                   and self._section_boxes[k].isChecked()]
        if not enabled:
            _show_quietly(self._section_boxes["material"], True)
            enabled = ["material"]
        enabled.extend(
            k for k in self._prefs.enabled_sections
            if k not in order and k not in enabled)
        self._prefs.enabled_sections = enabled
        self._prefs.save()

    def set_hide_empty_categories(self, checked: bool) -> None:
        self._prefs.hide_empty_categories = checked
        self._prefs.save()

    def set_step_size(self, checked: bool) -> None:
        self._prefs.step_size = checked
        self._prefs.save()

    def set_render_on_import(self):
        self._prefs.render_on_import = int(self.cbx_render_on_import.isChecked())


    def closeEvent(self, arg__1: QCloseEvent) -> None:
        """Save on ANY close path, then finish() the dialog: a plain close only HIDES a QDialog and skips `finished(int)`, which is the non-modal owner's apply hook."""
        self._prefs.save()
        arg__1.accept()
        self.done(0)

    def reject(self) -> None:
        """Esc behaves exactly like the close button: QDialog's reject() hides the window WITHOUT a close event, so Esc would skip the save and the panel's load() would revert the session."""
        self.close()
