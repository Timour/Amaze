"""Five tabs built in code, no .ui file: every control writes into the prefs object IMMEDIATELY, the dialog persists on close, and there is no Cancel."""

import os
import shutil

import hou

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QCloseEvent

from amaze import amazetheme
from amaze import branding
from amaze.core import debug, library_policy, texture_library, users
from amaze.dialogs import base_dialog, user_dialog
from amaze.helpers import hostos
from amaze.core import tile_icons
from amaze.helpers import theme
from amaze.helpers import ui_helpers
from amaze.panel import sections as sections_module
from amaze.prefs import prefs as prefs_mod


LINK_COLOR = amazetheme.LINK_COLOR   # About-tab links ▸p/one-design-document

_logo_cache = None   # rendered once and reused as a QTextDocument resource, so the About page can reference it as an img src


def _logo_image(widget=None):
    """The Amaze wordmark cropped to its ink, since the artboard is mostly transparent; pass the WIDGET it will be drawn into. ▸r/screen-dpr"""
    global _logo_cache
    dpr = theme.screen_ratio(widget)   # keyed by DPR: rendered for one density and reused on another draws at half resolution
    if isinstance(_logo_cache, dict) and _logo_cache.get("dpr") == dpr:
        return _logo_cache["image"] or None

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", "logo.svg",
    )
    image = None
    try:
        from PySide6 import QtSvg

        renderer = QtSvg.QSvgRenderer(path)
        if renderer.isValid():
            full = QtGui.QImage(1024, 512,
                                QtGui.QImage.Format.Format_ARGB32)
            full.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(full)
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.Antialiasing, True)
            renderer.render(painter)
            painter.end()
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


def _picker_start(path: str) -> str:
    """A `start_directory` in the spelling `hou.ui.selectFile` requires: forward slashes on every OS, since on Windows the documented form is `D:/temp` while `os.path.join` there hands out backslashes."""
    return hostos.canonical_path_key(path) if path else ""   # empty stays empty: `canonical_path_key("")` is `"."`, which would open the chooser on the process working directory


class PrefsDialog(base_dialog.AssetDialog):
    """Preferences on the house shell - live-apply, so no OK/Cancel and the inherited `canceled` is never read; resizable, tabs as the content."""

    def __init__(self, prefs, panel=None, file_files_model=None,
                 parent=None) -> None:
        super().__init__(branding.APP_NAME + " Preferences",
                         fixed_size=False, parent=parent)
        self._prefs = prefs
        # the panel owns the library operations and this only forwards; None in tests keeps the other tabs constructable
        self._panel = panel
        self._file_files_model = file_files_model

        tabs = QtWidgets.QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_library_tab(), "Library")
        tabs.addTab(self._build_render_tab(), "Render")
        tabs.addTab(self._build_showhide_tab(), "Show/Hide")
        tabs.addTab(self._build_look_tab(), "Look")
        tabs.addTab(self._build_about_tab(), "About")

        self.set_content(tabs)
        self.finish(ok_cancel=False, margins=12)   # 12px, recorded: a tabbed window keeps its air - the 5px house margin is for compact forms

        for combo in self.findChildren(QtWidgets.QComboBox):   # combos never TAKE focus, and this MUST run after setLayout since findChildren walks only the CURRENT tree
            combo.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setMinimumWidth(theme.ui_px(480))
        self.resize(   # natural content height plus 100 rendered px of headroom
            theme.ui_px(480),
            self.sizeHint().height() + theme.ui_px(50),
        )


    def _tab_page(self):
        """(page widget, its form layout): every tab is one form with the shared right-aligned label column, top-aligned so short tabs keep their row spacing."""
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        _m = theme.ui_px(8)
        outer.setContentsMargins(_m, _m, _m, _m)
        form = self._make_form()
        outer.addLayout(form)
        outer.addStretch()
        return page, form

    def _reload_library_users(self) -> None:
        """Fill the picker and select the current user, UNDER `blockSignals`: the first `addItem` emits `currentIndexChanged(0)`, so a plain repopulate would silently switch the user."""
        combo = self.cbb_library_user
        uid = users.current(self._prefs)
        combo.blockSignals(True)
        try:
            combo.clear()
            for user_id, name in sorted(users.all_users(self._prefs).items(),
                                        key=lambda pair: pair[1].lower()):
                combo.addItem(name, user_id)
            combo.addItem("Create a new user...",
                          user_dialog.UserPickerDialog.CREATE)    # the picker dialog's own create row, LAST so it never reads as a user
            combo.setCurrentIndex(max(combo.findData(uid), 0) if uid else -1)
        finally:
            combo.blockSignals(False)
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
            self._btn_edit_user.setEnabled(True)
            self._btn_delete_user.setEnabled(True)

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
        if not dialog.canceled:
            self.rename_library_user(dialog.name)

    def create_library_user(self, name: str) -> None:
        """Mint a user and switch this machine to them - creating-then-becoming is this row's case; a second machine picking ITSELF is the first-open picker's."""
        uid = users.create(self._prefs, name)
        if uid:
            users.adopt(self._prefs, uid)
        self._reload_library_users()

    def _ask_create_library_user(self) -> None:
        dialog = base_dialog.NameDialog("Create User", "", parent=self)
        dialog.exec()
        if dialog.canceled:
            self._reload_library_users()    # the combo is sitting on the create row; put the real selection back
            return
        self.create_library_user(dialog.name)

    def delete_library_user(self, uid) -> None:
        """Delete `uid` and everything tagged theirs; the row goes blank until somebody is picked - nobody is adopted silently."""
        if users.delete(self._prefs, uid):
            self._reload_library_users()

    def _ask_delete_library_user(self) -> None:
        uid = users.current(self._prefs)
        if not uid:
            return
        name = users.name_for(self._prefs, uid)
        answer = hou.ui.displayMessage(  # type: ignore
            'Delete user "%s" from this library?' % name,
            help="Their favorites and registered folders are removed "
                 "from this library everywhere it syncs. A machine "
                 'signed in as "%s" will ask who is using the library '
                 "the next time it opens. This cannot be undone." % name,
            buttons=("Delete User", "Cancel"),
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
                "Turn on Material Versions for this library?",
                help="This applies to EVERYONE who opens this library, "
                     "on every machine - it is stored with the library, "
                     "not in your preferences.\n\n"
                     "With it on, saving over an existing material "
                     "offers Save Version: the old version is kept and "
                     "the tile's badge switches between them.",
                buttons=("Turn On", "Cancel"),
                default_choice=1, close_choice=1,
                severity=hou.severityType.Warning,
                title=branding.APP_NAME,
            )
            if answer != 0:
                self._cbx_allow_overwrite.blockSignals(True)
                self._cbx_allow_overwrite.setChecked(False)
                self._cbx_allow_overwrite.blockSignals(False)
                return
        if not library_policy.set_allow_overwrite(library_dir, checked):
            hou.ui.displayMessage(  # type: ignore
                "Could not write the setting to the library folder, so "
                "it was not changed.")
            self._cbx_allow_overwrite.blockSignals(True)
            self._cbx_allow_overwrite.setChecked(not checked)
            self._cbx_allow_overwrite.blockSignals(False)

    def _build_library_tab(self) -> QtWidgets.QWidget:
        page, form = self._tab_page()

        self.line_workdir = QtWidgets.QLineEdit(self._prefs.dir)
        self.line_workdir.setReadOnly(True)
        self.line_workdir.setToolTip(ui_helpers.tooltip_text(
            "The folder the library lives in."))
        browse_lib = QtWidgets.QPushButton("...")
        browse_lib.setFixedWidth(theme.ui_px(28))
        browse_lib.clicked.connect(self.change_library_path)
        form.addRow(self._label("Library Path"), self._path_row(self.line_workdir, browse_lib))

        cleanup_btn = QtWidgets.QPushButton("Clean Up Library")
        cleanup_btn.clicked.connect(self._panel_call("cleanup_db"))
        cleanup_btn.setToolTip(ui_helpers.tooltip_text(
            "Tidy up: missing files are reported, leftovers are set "
            "aside for 30 days. Everything still showing in the "
            "panel stays."))
        form.addRow(self._label(""), cleanup_btn)
        reload_btn = QtWidgets.QPushButton("Reload Library")
        reload_btn.clicked.connect(self._panel_call("open"))
        reload_btn.setToolTip(ui_helpers.tooltip_text(
            "Read the library from disk again."))
        form.addRow(self._label(""), reload_btn)
        open_btn = QtWidgets.QPushButton("Open Library Folder")
        open_btn.clicked.connect(self._panel_call("open_usdlib_folder"))
        open_btn.setToolTip(ui_helpers.tooltip_text(
            "Open the library folder."))
        form.addRow(self._label(""), open_btn)

        self._add_divider(form)
        # NOT A PREFERENCE: it lives in the library's own policy.json, because a switch protecting a SHARED thing must travel with the thing
        self._cbx_allow_overwrite = ui_helpers.ToggleSwitch(
            "Material Versions")
        self._cbx_allow_overwrite.setChecked(
            library_policy.allow_overwrite(self._prefs.dir))
        self._cbx_allow_overwrite.setToolTip(ui_helpers.tooltip_text(
            "Whether saving over an existing material creates a new "
            "VERSION of it. Stored in the library itself, not in your "
            "preferences - so it applies to everyone who opens this "
            "library, on every machine. ON: saving over an existing "
            "material offers Save Version - the old version is kept, "
            "and the tile's badge switches between them any time. "
            "OFF: saving always adds a separate new material, and "
            "existing ones are never touched."))
        self._cbx_allow_overwrite.toggled.connect(self.set_allow_overwrite)
        form.addRow(self._label(""),
                    self._cbx_allow_overwrite)

        self.cbb_library_user = QtWidgets.QComboBox()   # shows the NAME, never the UID that everything is tagged with
        self.cbb_library_user.setToolTip(ui_helpers.tooltip_text(
            "Who you are in this library. Your favorites and your "
            "folders are saved under you, so the same user on another "
            "computer gives you the same things back - and two people "
            "sharing one library keep theirs apart. It also signs the "
            "versions you save. Never taken from your computer's user "
            "or machine name."))
        self._btn_edit_user = QtWidgets.QPushButton("Rename")
        self._btn_edit_user.setToolTip(ui_helpers.tooltip_text(
            "Change the name shown for this user. Only the name "
            "changes - your favorites and folders stay yours."))
        self._btn_edit_user.clicked.connect(self._ask_rename_library_user)
        self._btn_delete_user = QtWidgets.QPushButton("Delete")
        self._btn_delete_user.setToolTip(ui_helpers.tooltip_text(
            "Remove this user from the library, along with their "
            "favorites and registered folders. Asks first."))
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
            "Where the preview copies live on this machine."))
        browse_cache = QtWidgets.QPushButton("...")
        browse_cache.setFixedWidth(theme.ui_px(28))
        browse_cache.clicked.connect(self.change_cache_path)
        self._default_cache = QtWidgets.QPushButton("Default")
        self._default_cache.clicked.connect(self.reset_cache_path)
        self._default_cache.setToolTip(ui_helpers.tooltip_text(
            "Put the preview cache back where this machine keeps it. "
            "Nothing is deleted - previews at the old location stay "
            "where they are, and remake themselves at the new one as "
            "you browse."))
        form.addRow(self._label("Cache Path"),
                    self._path_row(self.line_cache, browse_cache,
                                   self._default_cache))
        clear_cache_btn = QtWidgets.QPushButton("Delete Local Cache")
        clear_cache_btn.clicked.connect(self.clear_texture_cache)
        clear_cache_btn.setToolTip(ui_helpers.tooltip_text(
            "Throw away the preview copies. They are remade as you "
            "browse, the library is untouched."))
        form.addRow(self._label(""), clear_cache_btn)

        self._real_path_widgets = (self.line_workdir, browse_lib)   # inert under Test Mode: showing the test path while writing the real field could lose a library. CACHE rows stay live, Test Mode does not move the cache
        self._sync_test_mode_rows()
        return page

    def _sync_test_mode_rows(self) -> None:
        """Show where the library actually points, freezing the library row while the test switch is on."""
        on = bool(self._prefs.test_mode and self._prefs.test_dir)
        for widget in getattr(self, "_real_path_widgets", ()):
            widget.setEnabled(not on)
        self.line_workdir.setText(self._prefs.dir)

    def _build_render_tab(self) -> QtWidgets.QWidget:
        page, form = self._tab_page()

        self.line_rendersize = QtWidgets.QSpinBox()
        # range BEFORE value: a fresh QSpinBox clamps to Qt's default 0-99, so setValue(256) landed as 99 and persisted
        self.line_rendersize.setRange(64, 1024)
        self.line_rendersize.setValue(self._prefs.rendersize)
        self.line_rendersize.valueChanged.connect(self.set_rendersize)
        self.line_rendersize.setToolTip(ui_helpers.tooltip_text(
            "Thumbnail resolution in pixels. Bigger is sharper "
            "and slower."))
        form.addRow(self._label("RenderSize"), self._field_slider_row(self.line_rendersize, 64, 1024)
        )
        self.line_rendersamples = QtWidgets.QSpinBox()   # the Redshift dial (its ROP's UnifiedMaxSamples); Karma is CPU and needs its own far smaller scale
        self.line_rendersamples.setRange(1, 1024)
        self.line_rendersamples.setValue(self._prefs.rendersamples)
        self.line_rendersamples.valueChanged.connect(self.set_rendersamples)
        self.line_rendersamples.setToolTip(ui_helpers.tooltip_text(
            "Render quality for Redshift thumbnails."))
        form.addRow(self._label("Samples (Redshift)"),
            self._field_slider_row(self.line_rendersamples, 1, 1024),
        )
        self.spin_karma_samples = QtWidgets.QSpinBox()
        self.spin_karma_samples.setRange(1, 256)
        self.spin_karma_samples.setValue(self._prefs.karma_rendersamples)
        self.spin_karma_samples.valueChanged.connect(self.set_karma_rendersamples)
        self.spin_karma_samples.setToolTip(ui_helpers.tooltip_text(
            "Render quality for Karma thumbnails, 9 is Karma's "
            "default."))
        form.addRow(self._label("Samples (Karma)"),
            self._field_slider_row(self.spin_karma_samples, 1, 256),
        )
        self.spin_ram_cache = QtWidgets.QSpinBox()
        self.spin_ram_cache.setRange(64, 4096)
        self.spin_ram_cache.setValue(self._prefs.ram_cache_mb)
        self.spin_ram_cache.valueChanged.connect(self.set_ram_cache_mb)
        self.spin_ram_cache.setToolTip(ui_helpers.tooltip_text(
            "Memory for keeping thumbnails ready. More scrolls "
            "smoother."))
        form.addRow(self._label("RAM Cache (MB)"),
            self._field_slider_row(self.spin_ram_cache, 64, 4096),
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
            "How geometry thumbnails are drawn: shaded, wireframe "
            "or both."))
        self._combo_geo_bg = self._data_combo((
            ("Black", "black"),
            ("White", "white"),
            ("Default (grey sky)", "default"),
        ), "geometry_bg")
        form.addRow(self._label("Geometry Background"), self._combo_geo_bg)
        self._combo_geo_bg.setToolTip(ui_helpers.tooltip_text(
            "The backdrop for geometry thumbnails."))
        self.cbx_render_on_import = ui_helpers.ToggleSwitch("Render Thumbs on Import")
        self.cbx_render_on_import.setChecked(bool(self._prefs.render_on_import))
        self.cbx_render_on_import.stateChanged.connect(self.set_render_on_import)
        self.cbx_render_on_import.setToolTip(ui_helpers.tooltip_text(
            "Render thumbnails as soon as materials are imported. "
            "Off = render later with Update Preview."))
        form.addRow(self._label(""), self.cbx_render_on_import)

        self._add_divider(form)
        self.spin_parallel = QtWidgets.QSpinBox()
        self.spin_parallel.setToolTip(ui_helpers.tooltip_text(
            "How many texture conversions (EXR/HDR to thumbnail) run "
            "at once."
        ))
        form.addRow(
            self._label("Conversion Threads"),
            self._field_slider_row(self.spin_parallel, 1, 8),
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
            "Texture resolution to download. A floor, not a hard match: "
            "the next highest available is used, or the highest below."
        ))
        form.addRow(self._label("Download Resolution"), self.cbb_matx_res)
        self.spin_matx_parallel = QtWidgets.QSpinBox()
        self.spin_matx_parallel.setRange(1, 16)
        self.spin_matx_parallel.setValue(self._prefs.matx_parallel_downloads)
        self.spin_matx_parallel.valueChanged.connect(
            self.set_matx_parallel_downloads
        )
        self.spin_matx_parallel.setToolTip(ui_helpers.tooltip_text(
            "Preview downloads at once. These wait on network latency "
            "rather than bandwidth, so more is markedly faster."
        ))
        form.addRow(self._label("Parallel Downloads"),
            self._field_slider_row(self.spin_matx_parallel, 1, 16),
        )
        return page

    def _build_showhide_tab(self) -> QtWidgets.QWidget:
        page, form = self._tab_page()

        self._renderer_boxes = {}
        # the ONE table, like the section list below it
        for label, attr in sections_module.renderer_prefs():
            box = ui_helpers.ToggleSwitch(label)
            box.setToolTip(ui_helpers.tooltip_text(
                "Which renderers Amaze offers. Hide the ones you "
                "don't use."))
            box.setChecked(bool(getattr(self._prefs, attr)))
            box.toggled.connect(
                lambda checked, a=attr: setattr(self._prefs, a, checked)
            )
            self._renderer_boxes[attr] = box
            form.addRow(self._label(""), box)

        self._add_divider(form)
        self._section_boxes = {}
        for key, label in sections_module.all_sections():   # from the sections THEMSELVES; a hardcoded copy never learned about "hip", so that tab had no switch and was deleted by toggling any other
            box = ui_helpers.ToggleSwitch(label)
            box.setToolTip(ui_helpers.tooltip_text(
                "Which sections the panel shows. A hidden section "
                "keeps everything, the tab just goes away."))
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
            "Show how many things each category holds."))
        form.addRow(self._label(""), self._cbx_sidebar_counts)

        self._cbx_hide_empty = ui_helpers.ToggleSwitch("Hide Empty Categories")
        self._cbx_hide_empty.setChecked(self._prefs.hide_empty_categories)
        self._cbx_hide_empty.toggled.connect(self.set_hide_empty_categories)
        self._cbx_hide_empty.setToolTip(ui_helpers.tooltip_text(
            "Hide categories with nothing in them, they come back "
            "when something lands there."))
        form.addRow(self._label(""), self._cbx_hide_empty)

        self._cbx_show_unknown = ui_helpers.ToggleSwitch(
            "All show unknown files"
        )
        self._cbx_show_unknown.setToolTip(ui_helpers.tooltip_text(
            "Show files Amaze has no preview for, using their "
            "system icon. Each location can override this in its "
            "own right-click menu."
        ))
        self._cbx_show_unknown.setChecked(self._prefs.file_show_unknown)
        self._cbx_show_unknown.toggled.connect(self.set_file_show_unknown)
        form.addRow(self._label(""), self._cbx_show_unknown)

        self._combo_path_style = self._data_combo((
            ("$HOME", "home"),
            ("$JOB", "job"),
            ("$HIP", "hip"),
            ("Absolute", "absolute"),
        ), "path_style")
        self._combo_path_style.setToolTip(ui_helpers.tooltip_text(
            "How Amaze writes paths - Copy Path and the File "
            "section's location labels. A variable applies when the "
            "path lives under it; otherwise the path stays absolute."
        ))
        form.addRow(self._label("Write Paths As"), self._combo_path_style)

        self._combo_icon_weight = self._data_combo((
            ("Thin", "template"),
            ("Regular (Feather)", "feather"),
        ), "icon_line_weight")
        self._combo_icon_weight.currentIndexChanged.connect(
            self._recompose_tile_icons)
        form.addRow(self._label("Tile Icon Line"), self._combo_icon_weight)
        self._combo_icon_weight.setToolTip(ui_helpers.tooltip_text(
            "Line weight of the tile icons, thin or regular."))

        self.spin_scroll_speed = QtWidgets.QSpinBox()
        self.spin_scroll_speed.setRange(10, 300)
        self.spin_scroll_speed.setValue(round(self._prefs.scroll_speed * 100))
        self.spin_scroll_speed.valueChanged.connect(self.set_scroll_speed)
        self.spin_scroll_speed.setToolTip(ui_helpers.tooltip_text(
            "How fast the grid scrolls, 100 is normal."))
        form.addRow(self._label("Scroll Speed (%)"),
            self._field_slider_row(self.spin_scroll_speed, 10, 300),
        )
        return page

    def _build_about_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        _m = theme.ui_px(8)
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
        outer.addWidget(browser, 1)

        form = self._make_form()
        self._btn_update = QtWidgets.QPushButton("Check for Updates")   # ON REQUEST ONLY: nothing consults the release feed at launch
        self._btn_update.setToolTip(ui_helpers.tooltip_text(
            "Ask whether a newer Amaze has been released. Nothing is "
            "downloaded or changed by asking."
        ))
        self._btn_update.clicked.connect(self.check_for_updates)
        form.addRow("", self._btn_update)
        self._lbl_update = QtWidgets.QLabel("")   # THE ANSWER GOES HERE, not a popup: this dialog is non-modal by design ▸r/houdini-colour-picker
        self._lbl_update.setWordWrap(True)
        self._lbl_update.setVisible(False)
        form.addRow("", self._lbl_update)
        self._btn_install = QtWidgets.QPushButton("Install Update")   # shown only when there IS something to install; two presses on purpose, the first changing nothing
        self._btn_install.setToolTip(ui_helpers.tooltip_text(
            "Download the new release and put it in place. Your library "
            "and your settings are not touched, and Houdini must be "
            "restarted afterwards."
        ))
        self._btn_install.clicked.connect(self.install_update)
        self._btn_install.setVisible(False)
        form.addRow("", self._btn_install)
        self._add_divider(form)
        self._cbx_debug = ui_helpers.ToggleSwitch("Debug Mode")
        self._cbx_debug.setChecked(self._prefs.debug_mode)
        self._cbx_debug.setToolTip(ui_helpers.tooltip_text(
            "Write a structured session log for diagnosing problems. "
            "Off by default."
        ))
        self._cbx_debug.toggled.connect(self.set_debug_mode)
        debug_row = QtWidgets.QWidget()   # toggle and its two buttons on ONE row: three stacked rows read as three unrelated settings
        row = QtWidgets.QHBoxLayout(debug_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.ui_px(8))
        row.addWidget(self._cbx_debug)
        row.addStretch(1)

        reveal_btn = QtWidgets.QPushButton("Open Log")
        reveal_btn.clicked.connect(self.reveal_debug_log)
        reveal_btn.setToolTip(ui_helpers.tooltip_text(
            "Open the debug log."))
        row.addWidget(reveal_btn)
        save_btn = QtWidgets.QPushButton("Save Log...")
        save_btn.setToolTip(ui_helpers.tooltip_text(
            "Copy the debug log to a folder you choose, named for this\n"
            "machine and Houdini version - so two machines' logs can sit\n"
            "side by side when a problem happens on only one of them.\n\n"
            "The copy contains your file paths, asset and material names."))
        save_btn.clicked.connect(self.save_debug_log)
        row.addWidget(save_btn)
        clear_btn = QtWidgets.QPushButton("Clear Log")
        clear_btn.clicked.connect(self.clear_debug_log)
        clear_btn.setToolTip(ui_helpers.tooltip_text(
            "Empty the log and start fresh."))
        row.addWidget(clear_btn)

        form.addRow(self._label(""), debug_row)

        self._add_divider(form)
        self._cbx_test_mode = ui_helpers.ToggleSwitch("Test Library")   # under Debug Mode but NOT attached to it; both paths are overlays and locations stay isolated both ways
        self._cbx_test_mode.setChecked(self._prefs.test_mode)
        self._cbx_test_mode.setToolTip(ui_helpers.tooltip_text(
            "Work against a throwaway library instead of the real one. "
            "Point it at any folder: Amaze uses the lib folder inside "
            "it as the library and the cache folder as the preview "
            "cache, making either if it is missing. Your real Library "
            "Path, Cache Path and registered folders are left exactly "
            "as they are and come back when you switch this off."))
        self._cbx_test_mode.toggled.connect(self.set_test_mode)
        form.addRow(self._label(""), self._cbx_test_mode)

        self.line_test_dir = QtWidgets.QLineEdit(self._prefs.test_dir)
        self.line_test_dir.setReadOnly(True)
        self.line_test_dir.setToolTip(ui_helpers.tooltip_text(
            "The folder holding the test lib and cache folders."))
        self._browse_test = QtWidgets.QPushButton("...")
        self._browse_test.setFixedWidth(theme.ui_px(28))
        self._browse_test.clicked.connect(self.change_test_path)
        form.addRow(self._label("Test Folder"),
                    self._path_row(self.line_test_dir, self._browse_test))

        outer.addLayout(form)
        return page

    LABEL_COL = 120   # ONE fixed label-column width for every row on every tab, matching Houdini's own panes, which CLIP a long label rather than widen

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
        """A path field, its browse button, and any button after it; the cache row carries a Default beside the browse."""
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.ui_px(4))
        h.addWidget(line_edit, 1)
        h.addWidget(browse_btn)
        for widget in extra:
            h.addWidget(widget)
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
        v.setContentsMargins(0, theme.ui_px(8), 0, theme.ui_px(6))
        divider = QtWidgets.QWidget()
        divider.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_StyledBackground, True
        )
        divider.setStyleSheet("background-color: #434343;")
        divider.setFixedHeight(theme.ui_px(1))
        v.addWidget(divider)
        form.addRow(box)

    def _field_slider_row(
        self, spinbox: QtWidgets.QSpinBox, lo: int, hi: int
    ) -> QtWidgets.QWidget:
        """Houdini-style numeric row: number field + ClickSlider kept in sync both ways, terminating because setValue with an unchanged value emits nothing."""
        spinbox.setRange(lo, hi)
        spinbox.setFixedWidth(theme.ui_px(64))
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
        h.setSpacing(theme.ui_px(8))
        h.addWidget(spinbox)
        h.addWidget(slider, 1)
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
        form.setHorizontalSpacing(theme.ui_px(8))   # EXPLICIT: a style computes label-to-field spacing per widget-type pair, drifting the shared column between tabs
        form.setVerticalSpacing(theme.ui_px(6))
        return form


    def change_library_path(self) -> None:
        """Browse for a new library directory, through the panel's own set_library flow: validation, seed copy, model switching."""
        if self._panel is None:
            return
        self._panel.set_library()
        self.line_workdir.setText(self._prefs.dir)
        self._reload_library_users()    # the users live IN the library, so the open picker is otherwise a list of the PREVIOUS one's people until Preferences is reopened

    def change_cache_path(self) -> None:
        """Pick a custom thumbnail-cache location; an empty selection keeps the current one and existing caches regenerate at the new location on demand."""
        start = _picker_start(self._prefs.cache_dir or hostos.cache_root())
        path = hou.ui.selectFile(
            start_directory=start, file_type=hou.fileType.Directory
        )
        if not path:
            return
        self._prefs.cache_dir = hou.text.expandString(path).rstrip("/")
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
        start = _picker_start(self._prefs.test_dir or self._prefs.dir)
        path = hou.ui.selectFile(
            start_directory=start, file_type=hou.fileType.Directory
        )
        if not path:
            return
        folder = hou.text.expandString(path).rstrip("/")
        ok, what = prefs_mod.seed_test_folder(folder)
        if not ok:
            hou.ui.displayMessage(  # type: ignore
                "That folder could not be prepared:\n\n%s" % what)
            return
        self._prefs.test_dir = folder
        self._prefs.save()
        self.line_test_dir.setText(folder)
        self._apply_test_mode()

    def set_test_mode(self, on: bool) -> None:
        """Switch the library and cache onto the test folder, or back; turning it on with no folder asks for one first, since the overlay ignores a blank one."""
        self._prefs.test_mode = bool(on)
        if on and not self._prefs.test_dir:
            self._prefs.save()
            self.change_test_path()
            if not self._prefs.test_dir:
                self._prefs.test_mode = False   # still nothing chosen, so put the switch back rather than leave it lying
                self._cbx_test_mode.setChecked(False)
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
        if self._panel is not None:
            self._panel.switch_all_models()   # NOT open(): that reloads the library already bound, so the connectors keep serving the previous one and every save is refused
        self._reload_library_users()    # a different library means different people, and the picker is open in front of them

    def clear_texture_cache(self) -> None:
        """Delete every cached image and geometry thumbnail; they regenerate on the next browse. Scene CAPTURES are untouched - hand-framed, not regenerable, and stored under config_root for that reason."""
        if not hou.ui.displayConfirmation(
            "This deletes all cached image and geometry thumbnails "
            "from disk. They will regenerate automatically next time "
            "each folder is browsed. Scene captures are kept. Continue?",
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

    @debug.guarded("prefs.check_for_updates")
    def check_for_updates(self) -> None:
        """Ask the release feed and say the answer in the tab; it BLOCKS, which is why the button says so - a worker thread would be more machinery than the wait it saves."""
        from amaze.core import updater

        self._btn_update.setEnabled(False)
        self._btn_update.setText("Checking...")
        self._lbl_update.setVisible(False)
        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            result = updater.check()
        finally:
            self._btn_update.setEnabled(True)
            self._btn_update.setText("Check for Updates")
        self._lbl_update.setText(result.sentence)
        self._lbl_update.setVisible(True)
        self._last_update = result
        self._btn_install.setVisible(bool(result) and bool(result.url))   # only when the release NAMED a file; one with no archive is offered nowhere rather than offered and then failing

    def install_update(self) -> None:
        """Fetch the release the last check found, with NO confirmation and no popup - the button's label IS the outcome. Only the install is replaced, and the previous one is kept beside it."""
        from amaze.core import updater

        result = getattr(self, "_last_update", None)
        if not result or not getattr(result, "url", ""):
            return
        install = hou.getenv("AMAZE") or ""
        if not install or not os.path.isdir(install):
            self._lbl_update.setText(
                "Amaze cannot tell where it is installed, so it cannot "
                "replace itself. Nothing has been changed.")
            return

        workspace = os.path.join(hostos.cache_root(), "updates")
        self._btn_install.setEnabled(False)
        self._btn_install.setText("Installing...")
        QtWidgets.QApplication.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            staged = updater.fetch_and_stage(
                result.url, workspace,
                digest=getattr(result, "digest", ""),
                size=getattr(result, "size", 0))
            backup = updater.apply_update(staged, install)
        except OSError as exc:
            self._lbl_update.setText(str(exc))   # the updater raises with a FINISHED sentence, shown as-is rather than wrapped in a second one
            return
        except Exception as exc:                              # noqa: BLE001
            debug.exception("update install", exc)
            self._lbl_update.setText(
                "The update could not be installed (%s). Nothing has "
                "been changed." % exc)
            return
        finally:
            self._btn_install.setEnabled(True)
            self._btn_install.setText("Install Update")
            shutil.rmtree(workspace, ignore_errors=True)

        self._btn_install.setVisible(False)
        self._lbl_update.setText(
            "Amaze %s is installed. Restart Houdini to run it - this "
            "session keeps the old one in memory. Your library and your "
            "settings were not touched, and the previous version is "
            "beside the new one at %s."
            % (result.version, backup))

    def set_debug_mode(self, checked: bool) -> None:
        """Takes effect IMMEDIATELY: the engine is reconfigured here as well as on close, so a session can be captured without restarting Houdini."""
        self._prefs.debug_mode = checked
        debug.configure(checked)
        if checked:
            debug.prefs_snapshot(self._prefs)

    def reveal_debug_log(self) -> None:
        """Open the log FILE itself; an empty log opens its folder instead."""
        path = debug.log_path()
        folder = os.path.dirname(path)
        try:
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(path):
                try:
                    hostos.open_path(path)
                except OSError:
                    hostos.reveal_path(path)   # nothing is associated with .jsonl on a stock Windows install, so show the file selected in its folder
            else:
                hostos.open_path(folder)
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
                self, "Amaze - log not saved", str(exc))
            debug.event("prefs", "log export refused", reason=str(exc))
            return
        except Exception as exc:                         # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, "Amaze - log not saved",
                "Unexpected error: %s" % exc)
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
            try:
                hostos.reveal_path(target)
            except Exception as exc:                     # noqa: BLE001
                debug.event("prefs", "could not reveal export",
                            error=str(exc))

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

    def set_rendersamples(self):
        self._prefs.rendersamples = self.line_rendersamples.value()

    def set_scroll_speed(self, value: int) -> None:
        self._prefs.scroll_speed = value / 100.0

    def set_ram_cache_mb(self, value: int) -> None:
        """NO save() here, closeEvent persists it: a slider fires valueChanged per mouseMoveEvent, so one drag fsynced settings.json hundreds of times. The live budget still updates immediately."""
        self._prefs.ram_cache_mb = value

    def _recompose_tile_icons(self, _index=None) -> None:
        """Line weight changed, so redraw every tile icon that exists; the composed PNGs are baked, and without this the setting only shows on icons chosen afterwards."""
        panel = self._panel   # NOT parent(): the dialog is reparented to Houdini's main window, so parent() is the application window and every lookup returns None
        for attr in ("material_model", "cop_model", "code_model"):
            model = getattr(panel, attr, None)
            if model is not None and hasattr(model, "rerender_tile_icons"):
                model.rerender_tile_icons()
        tile_icons.forget_composed()   # the File section composes in memory, so it needs a repaint AND a cleared cache or it redraws the old weight
        for attr in ("file_files_model",):
            model = getattr(panel, attr, None)
            if model is None:
                continue
            rows = model.rowCount()
            if rows:
                model.dataChanged.emit(
                    model.index(0, 0), model.index(rows - 1, 0),
                    [QtCore.Qt.ItemDataRole.DecorationRole],
                )

    def set_sidebar_counts(self, checked: bool) -> None:
        self._prefs.sidebar_counts = checked
        self._prefs.save()

    def set_file_show_unknown(self, checked: bool) -> None:
        self._prefs.file_show_unknown = checked
        self._prefs.save()

    def _on_section_toggled(self, _checked: bool) -> None:
        """Rebuild enabled_sections in ALL_SECTIONS order, never leaving zero enabled; keys THIS build does not register are carried over untouched, or another build's tabs are deleted by side effect."""
        order = [k for k, _lbl in sections_module.all_sections()]
        enabled = [k for k in order
                   if k in self._section_boxes
                   and self._section_boxes[k].isChecked()]
        if not enabled:
            self._section_boxes["material"].blockSignals(True)
            self._section_boxes["material"].setChecked(True)
            self._section_boxes["material"].blockSignals(False)
            enabled = ["material"]
        enabled.extend(
            k for k in self._prefs.enabled_sections
            if k not in order and k not in enabled)
        self._prefs.enabled_sections = enabled
        self._prefs.save()

    def set_hide_empty_categories(self, checked: bool) -> None:
        self._prefs.hide_empty_categories = checked
        self._prefs.save()

    def set_karma_rendersamples(self):
        """Set the Karma-specific thumbnail sample count"""
        self._prefs.karma_rendersamples = self.spin_karma_samples.value()

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
