"""
Preferences Dialog attached to the MatLibPanel.

Five tabs (Library / Render / Show/Hide / Look / About) built entirely
in code - no .ui file. Library management (set/reload/cleanup/open
folder) lives on the Library tab now that the toolbar's gear opens
Preferences directly instead of a menu; About and Debug share the last
tab, replacing the old separate About dialog.

Apply semantics are unchanged from the single-column era: every control
writes into the prefs object immediately, the dialog persists on close
(the close button and Esc alike - there is no Cancel), and the panel
re-propagates after close (see MatLibPanel.show_prefs).
"""

import os

import hou

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtGui import QCloseEvent

from amaze import branding
from amaze.core import debug, library_policy, texture_library, versions
from amaze.helpers import hostos
from amaze.core import tile_icons
from amaze.helpers import theme
from amaze.helpers import ui_helpers
from amaze.panel import sections as sections_module
from amaze.prefs import prefs as prefs_mod


#: Links in the About tab: a step darker than the body text, so they
#: read as secondary rather than as Qt's default blue - the one colour
#: in this panel that belongs to no palette here.
LINK_COLOR = "#8e8a85"

#: Rendered once and reused - a QTextDocument resource, so the About
#: page can reference it as <img src="amaze_logo">.
_logo_cache = None


def _logo_image():
    """The Amaze wordmark, cropped to its ink.

    The artboard is 1024x512 and the drawing occupies about a third of
    it, so rendering the viewBox as-is would place a small logo inside
    a large transparent block and push the text down the page. Crop to
    the alpha bounds, then scale to a height that sits with the text.
    """
    global _logo_cache
    # Keyed by DPR: rendered for one screen density, reused on another,
    # is exactly the half-resolution look this function existed to
    # avoid. A retina display draws a DPR-less image at one device
    # pixel per TWO the panel has - "at half resolution", which
    # is precisely what it was.
    app = QtWidgets.QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
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
                # DEVICE pixels tall, with the ratio stamped on the
                # image so the text document draws it back at logical
                # size - the same contract every badge pixmap follows.
                image = full.copy(box).scaledToHeight(
                    max(1, round(theme.ui_px(34) * dpr)),
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                image.setDevicePixelRatio(dpr)
    except Exception as exc:                                # noqa: BLE001
        # note vs event for this file: the About logo is cosmetic, so
        # event. Clearing the log is something the user just asked for,
        # so that failure stays visible as a note.
        debug.event("prefs", "About logo not loaded", error=str(exc))
    _logo_cache = {"dpr": dpr, "image": image if image is not None
                   else False}
    return image


class PrefsDialog(QtWidgets.QDialog):
    """
    Preferences Dialog attached to the MatLibPanel
    """

    def __init__(self, prefs, panel=None, file_files_model=None) -> None:
        super(PrefsDialog, self).__init__()
        self._prefs = prefs
        # The panel provides the library operations (set/reload/cleanup/
        # open folder) - the dialog only forwards to its existing
        # handlers. None in tests keeps the other tabs constructable.
        self._panel = panel
        self._file_files_model = file_files_model

        self.setWindowTitle(branding.APP_NAME + " Preferences")

        tabs = QtWidgets.QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_library_tab(), "Library")
        tabs.addTab(self._build_render_tab(), "Render")
        tabs.addTab(self._build_showhide_tab(), "Show/Hide")
        tabs.addTab(self._build_look_tab(), "Look")
        tabs.addTab(self._build_about_tab(), "About")

        mainlayout = QtWidgets.QVBoxLayout()
        _m = theme.ui_px(12)
        mainlayout.setContentsMargins(_m, _m, _m, _m)
        mainlayout.addWidget(tabs)
        self.setLayout(mainlayout)

        # Combos never TAKE focus: Houdini's stylesheet paints a
        # focused combo navy with a blue ring, so whichever dropdown
        # was last clicked (or auto-focused on a tab switch) looked
        # permanently different from its siblings. Clicking still opens
        # the popup; this also stops stray wheel-scrolls over the page
        # from changing a combo's value.
        # MUST run after setLayout: findChildren walks the dialog's own
        # tree, and `tabs` only joins it on addWidget/setLayout above -
        # placed earlier, this loop matched nothing and every combo
        # kept focus, which is exactly the live report it exists to
        # prevent.
        for combo in self.findChildren(QtWidgets.QComboBox):
            combo.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setMinimumWidth(theme.ui_px(480))
        # Natural content height plus 100 rendered px of headroom
        # (2x rule: code halves end-pixel values).
        self.resize(
            theme.ui_px(480),
            self.sizeHint().height() + theme.ui_px(50),
        )

    # ------------------------------------------------------------ tabs

    def _tab_page(self):
        """(page widget, its form layout) - every tab is one form with
        the shared right-aligned label column, top-aligned so short tabs
        don't stretch their rows apart."""
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        _m = theme.ui_px(8)
        outer.setContentsMargins(_m, _m, _m, _m)
        form = self._make_form()
        outer.addLayout(form)
        outer.addStretch()
        return page, form

    def _save_version_author(self) -> None:
        """The name version files are signed with. Saved as typed;
        blank stays blank here - the store mints a colour placeholder
        only when a version is actually written, so an untouched
        field costs nothing."""
        self._prefs.version_author = self.line_version_author.text()
        self._prefs.save()

    def set_allow_overwrite(self, checked: bool) -> None:
        """Write the library's overwrite policy - to the LIBRARY.

        Confirmed when being turned OFF is not the risk; turning it ON
        is, because that is the direction that exposes other people's
        work. The dialog names the consequence rather than asking
        "are you sure", which answers nothing.
        """
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
        # THIS SETTING IS NOT A PREFERENCE. It is stored in the library
        # (policy.json, beside library.json), because a switch that
        # protects a SHARED thing has to travel with the thing - one
        # kept in the OS preferences directory is per-user and
        # per-machine, so it would protect its owner and nobody else
        # while looking like protection.
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

        # The box shows the REAL name, always: a blank pref gets its
        # colour name minted right here, not promised for later.
        if not self._prefs.version_author:
            versions.writer_tag(self._prefs)
        self.line_version_author = QtWidgets.QLineEdit(
            self._prefs.version_author)
        self.line_version_author.setToolTip(ui_helpers.tooltip_text(
            "The name this machine signs its versions with - picked "
            "for you, yours to change. It goes into the version "
            "filenames so two machines can never write the same "
            "file. Never taken from your computer's user or machine "
            "name."))
        self.line_version_author.editingFinished.connect(
            self._save_version_author)
        form.addRow(self._label("Version Author"),
                    self.line_version_author)

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
        form.addRow(self._label("Cache Path"), self._path_row(self.line_cache, browse_cache))
        clear_cache_btn = QtWidgets.QPushButton("Delete Local Cache")
        clear_cache_btn.clicked.connect(self.clear_texture_cache)
        clear_cache_btn.setToolTip(ui_helpers.tooltip_text(
            "Throw away the preview copies. They are remade as you "
            "browse, the library is untouched."))
        form.addRow(self._label(""), clear_cache_btn)

        self._add_divider(form)
        # TEST LIBRARY. One switch and one folder, so a session can be
        # pointed at throwaway data and back again without either real
        # path ever being written (prefs.dir and prefs.cache_dir are
        # overlays while this is on).
        #
        # Not attached to Debug Mode: verbose logging exists to
        # diagnose the REAL library, so swapping the library out with
        # it would remove the one thing it is for.
        self._cbx_test_mode = ui_helpers.ToggleSwitch("Test Library")
        self._cbx_test_mode.setChecked(self._prefs.test_mode)
        self._cbx_test_mode.setToolTip(ui_helpers.tooltip_text(
            "Work against a throwaway library instead of the real one. "
            "Point it at any folder: Amaze uses the lib folder inside "
            "it as the library and the cache folder as the preview "
            "cache, making either if it is missing. Your real Library "
            "Path and Cache Path are left exactly as they are and come "
            "back when you switch this off."))
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

        # The real-path rows are INERT while the switch is on - they
        # would be showing the test paths and writing the real fields,
        # which is the one combination that could lose a library. Same
        # treatment the accent rows get under a theme.
        self._real_path_widgets = (self.line_workdir, browse_lib,
                                   self.line_cache, browse_cache)
        self._sync_test_mode_rows()
        return page

    def _sync_test_mode_rows(self) -> None:
        """Show where the library and cache actually point, and freeze
        the real-path rows while the test switch is on."""
        on = bool(self._prefs.test_mode and self._prefs.test_dir)
        for widget in getattr(self, "_real_path_widgets", ()):
            widget.setEnabled(not on)
        self.line_workdir.setText(self._prefs.dir)
        self.line_cache.setText(self._prefs.cache_dir
                                or hostos.cache_root())

    def _build_render_tab(self) -> QtWidgets.QWidget:
        page, form = self._tab_page()

        self.line_rendersize = QtWidgets.QSpinBox()
        # Range BEFORE value: a fresh QSpinBox clamps to Qt's default
        # 0-99, so setValue(256) landed as 99 (and then persisted).
        self.line_rendersize.setRange(64, 1024)
        self.line_rendersize.setValue(self._prefs.rendersize)
        self.line_rendersize.valueChanged.connect(self.set_rendersize)
        self.line_rendersize.setToolTip(ui_helpers.tooltip_text(
            "Thumbnail resolution in pixels. Bigger is sharper "
            "and slower."))
        form.addRow(self._label("RenderSize"), self._field_slider_row(self.line_rendersize, 64, 1024)
        )
        # rendersamples is the Redshift thumbnail dial (the Redshift
        # ROP's UnifiedMaxSamples); Karma renders on the CPU engine and
        # needs its own, far smaller scale (9 = Karma's own default).
        self.line_rendersamples = QtWidgets.QSpinBox()
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
        # Geometry thumbnail look. Takes effect on newly rendered
        # thumbnails; each mode/bg combination keeps its own disk cache.
        self._combo_geo_shading = self._data_combo((
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
        # Range BEFORE value (the rule stated at the top of this form):
        # a fresh QSpinBox clamps to Qt's default 0-99, and this was the
        # one row setting its value first. Connect after both, so the
        # initial set does not write the preference back to itself.
        self.spin_parallel.setValue(self._prefs.texture_parallel_conversions)
        self.spin_parallel.valueChanged.connect(self.set_texture_parallel)
        # "Force iconvert only" stood here until 2026-08-03. It was the
        # MANUAL WORKAROUND for a converter that returned a wrong
        # picture and said it had succeeded - and the Conversion Engine
        # now catches that itself, tries the next decoder and says so in
        # the log. A control whose job an engine has taken over is a
        # question the user should not be asked; it also never did what
        # its label said, since Houdini's converter cannot resize and so
        # could not serve an oversized image at all.

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
        # The ONE table, like the section list below it. This was a
        # literal copy of MaterialSection.RENDERER_PREFS.
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
        # From the sections themselves. This used to be a hardcoded
        # six-entry copy that never learned about "hip", so the HIP tab
        # had no switch here AND was deleted by toggling any other one.
        for key, label in sections_module.all_sections():
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

        # QTextBrowser, not QTextEdit: it renders <a href> AND opens it.
        browser = QtWidgets.QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        # No viewport box of its own - the text sits directly on the
        # dialog's background. Palette-level transparency, not a
        # stylesheet (the documented CSS-rendering-path trap).
        browser.viewport().setAutoFillBackground(False)
        pal = browser.palette()
        pal.setColor(
            QtGui.QPalette.ColorRole.Base,
            QtGui.QColor(0, 0, 0, 0),
        )
        browser.setPalette(pal)
        # Links in a slightly darker grey than the body text. Qt's
        # default link blue is the one colour in this panel that
        # belongs to no palette here, and it pulls the eye to the
        # credits rather than to what the page says.
        logo = _logo_image()
        if logo is not None:
            browser.document().addResource(
                QtGui.QTextDocument.ResourceType.ImageResource,
                QtCore.QUrl("amaze_logo"), logo,
            )
        browser.document().setDefaultStyleSheet(
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
            # Credit, not obligation: every online source ships under
            # CC0 or MIT public domain, so none of them REQUIRE
            # attribution. They are named because a library full of
            # imported materials should say where they came from, and
            # each imported material additionally records its own
            # source and licence.
            "<p><b>Modules and libraries from other projects</b><br>"
            "egMatLib by Elmar Glaubauf "
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
        self._add_divider(form)
        self._cbx_debug = ui_helpers.ToggleSwitch("Debug Mode")
        self._cbx_debug.setChecked(self._prefs.debug_mode)
        self._cbx_debug.setToolTip(ui_helpers.tooltip_text(
            "Write a structured session log for diagnosing problems. "
            "Off by default."
        ))
        self._cbx_debug.toggled.connect(self.set_debug_mode)
        # Toggle and its two buttons on ONE row: they are one subject
        # (the debug log), and three stacked full-width rows read as
        # three unrelated settings.
        debug_row = QtWidgets.QWidget()
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
        outer.addLayout(form)
        return page

    # ------------------------------------------- shared row machinery

    #: ONE label-column width for every row on every tab, FIXED - not
    #: sized to the longest label. Houdini's own parameter panes put
    #: the label right edge ~280 rendered px into the window (2x rule:
    #: 140 code px; minus the window/tab margins = this width) and CLIP
    #: a label that does not fit, rather than widening the column.
    #: Checkbox rows use an empty label of the same width so the boxes
    #: indent to the field column too.
    LABEL_COL = 120

    def _label(self, text: str) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setFixedWidth(theme.ui_px(self.LABEL_COL))
        lbl.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        return lbl

    def _data_combo(self, items, attr) -> QtWidgets.QComboBox:
        """Combo whose entries carry a token in itemData; selecting one
        writes self._prefs.<attr> = token and saves. Shared by the
        geometry-shading/background and star-mode rows."""
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

    def _path_row(self, line_edit, browse_btn) -> QtWidgets.QWidget:
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.ui_px(4))
        h.addWidget(line_edit, 1)
        h.addWidget(browse_btn)
        return row

    def _panel_call(self, method_name: str):
        """A click handler forwarding to a panel method, guarded for the
        panel-less (test) construction."""
        def _call():
            if self._panel is not None:
                getattr(self._panel, method_name)()
        return _call

    def _add_divider(self, form: QtWidgets.QFormLayout) -> None:
        """A 1px group divider as a spanning row - groups carry no
        title text, exactly like Houdini's own parameter panes."""
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
        """Houdini-style numeric parameter row: narrow number field +
        slider, kept in sync both ways (the mutual setValue connections
        terminate because setValue with an unchanged value emits
        nothing). The slider is the project's own ClickSlider so it
        matches the toolbar's size slider exactly."""
        spinbox.setRange(lo, hi)
        spinbox.setFixedWidth(theme.ui_px(64))
        spinbox.setButtonSymbols(
            QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        slider = ui_helpers.ClickSlider()
        slider.setOrientation(QtCore.Qt.Orientation.Horizontal)
        # No tick dots / snap magnets here - those belong to
        # the toolbar's thumbnail-size slider only.
        slider.snap_marks = ()
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
        """A QFormLayout configured exactly like the main panel's details
        view - right-aligned label column, fields grow to fill the rest -
        so every group in this dialog reads as the same kind of row."""
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight
            | QtCore.Qt.AlignmentFlag.AlignTrailing
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )
        # Explicit spacings: styles compute label<->field spacing PER
        # WIDGET-TYPE PAIR, which drifted the shared field column a few
        # px between tabs (line edits vs spinboxes vs checkboxes).
        form.setHorizontalSpacing(theme.ui_px(8))
        form.setVerticalSpacing(theme.ui_px(6))
        return form

    # ------------------------------------------------- library actions

    def change_library_path(self) -> None:
        """Browse for a new library directory - the panel's own
        set_library flow (validation, seed copy, model switching)."""
        if self._panel is None:
            return
        self._panel.set_library()
        self.line_workdir.setText(self._prefs.dir)

    def change_cache_path(self) -> None:
        """Pick a custom thumbnail-cache location; empty selection keeps
        the current one. The override lands in hostos.cache_root() when
        the dialog closes (the panel pushes it), and existing caches
        regenerate at the new location on demand."""
        start = self._prefs.cache_dir or hostos.cache_root()
        path = hou.ui.selectFile(
            start_directory=start, file_type=hou.fileType.Directory
        )
        if not path:
            return
        self._prefs.cache_dir = hou.expandString(path).rstrip("/")
        self._prefs.save()
        hostos.set_cache_override(self._prefs.cache_dir)
        self.line_cache.setText(self._prefs.cache_dir)

    def change_test_path(self) -> None:
        """Pick the folder holding the test lib and cache.

        Seeded on the way in, not on first use: a library directory
        with no index does not load, so choosing an empty folder and
        switching on would otherwise answer with a traceback.
        """
        start = self._prefs.test_dir or self._prefs.dir
        path = hou.ui.selectFile(
            start_directory=start, file_type=hou.fileType.Directory
        )
        if not path:
            return
        folder = hou.expandString(path).rstrip("/")
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
        """Switch the library and cache onto the test folder, or back.

        Turning it on with no folder chosen asks for one first, rather
        than half-applying: the overlay ignores a blank folder, so the
        switch would otherwise read ON while nothing had moved.
        """
        self._prefs.test_mode = bool(on)
        if on and not self._prefs.test_dir:
            self._prefs.save()
            self.change_test_path()
            if not self._prefs.test_dir:
                # Still nothing chosen - the switch cannot mean
                # anything, so put it back rather than leave it lying.
                self._prefs.test_mode = False
                self._cbx_test_mode.setChecked(False)
                self._prefs.save()
            return
        if on:
            prefs_mod.seed_test_folder(self._prefs.test_dir)
        self._prefs.save()
        self._apply_test_mode()

    def _apply_test_mode(self) -> None:
        """Point the running session at whichever library now applies."""
        hostos.set_cache_override(self._prefs.cache_dir)
        self._sync_test_mode_rows()
        debug.event("prefs", "test library switched",
                    on=self._prefs.test_mode, folder=self._prefs.test_dir,
                    library=self._prefs.dir)
        if self._panel is not None:
            self._panel.open()

    def clear_texture_cache(self) -> None:
        """Delete all cached image+geometry thumbnails from disk (every
        resolution and look - see ThumbnailCache.clear()). They
        regenerate automatically next time each folder is browsed.
        Scene CAPTURES are not touched: hand-framed, not regenerable,
        and stored under config_root for exactly that reason."""
        if not hou.ui.displayConfirmation(
            "This deletes all cached image and geometry thumbnails "
            "from disk. They will regenerate automatically next time "
            "each folder is browsed. Scene captures are kept. Continue?"
        ):
            return
        if self._file_files_model is not None:
            self._file_files_model.clear_cache()
        else:
            texture_library.ThumbnailCache(self._prefs.rendersize).clear()

    # -------------------------------------------------------- setters

    def set_texture_parallel(self, value: int) -> None:
        self._prefs.texture_parallel_conversions = value

    def set_matx_resolution(self, label: str) -> None:
        self._prefs.matx_resolution = label

    def set_matx_parallel_downloads(self, value: int) -> None:
        """Read fresh on every dispatch, so it applies to the next batch
        without a restart - same as the texture conversion count."""
        self._prefs.matx_parallel_downloads = value

    def set_debug_mode(self, checked: bool) -> None:
        """Takes effect immediately - the engine is reconfigured here as
        well as when the dialog closes, so a session can be captured
        without restarting Houdini."""
        self._prefs.debug_mode = checked
        debug.configure(checked)
        if checked:
            debug.prefs_snapshot(self._prefs)

    def reveal_debug_log(self) -> None:
        """Open the log FILE itself (there is no path text in the
        dialog anymore); an empty log opens its folder instead."""
        path = debug.log_path()
        folder = os.path.dirname(path)
        try:
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(path):
                try:
                    hostos.open_path(path)
                except OSError:
                    # No application is associated with .jsonl on a
                    # stock Windows install; show the file selected in
                    # its folder instead.
                    hostos.reveal_path(path)
            else:
                hostos.open_path(folder)
        except Exception as exc:
            debug.event("prefs", "could not open log", error=str(exc))

    def save_debug_log(self) -> None:
        """Export the log to a folder the user picks.

        A deliberate act, every time. There is no setting that leaves
        this on, because the exported file carries the author's file
        paths and asset names - a log is a manifest of what someone is
        working on, and that is not something to mirror in the
        background.
        """
        # `.dir` - the attribute Prefs actually has, and the one every
        # other reader in this dialog uses. `library_path` has never
        # existed, so this raised AttributeError before the folder
        # chooser could open and PySide swallowed it: the one control
        # whose whole job is producing a bug report did nothing, said
        # nothing, and logged nothing.
        start = self._prefs.dir or os.path.expanduser("~")
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Save Amaze log to folder", start)
        if not folder:
            return                       # cancelled, not failed
        try:
            target = debug.export_log(folder)
        except debug.ExportRefused as exc:
            # SAY WHY. "Nothing happened" is the one outcome that
            # teaches the user nothing.
            QtWidgets.QMessageBox.information(
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
        # Through the ENGINE, not os.remove behind its back: it owns
        # the session header and the flood counters, and a cleared log
        # that keeps either is not the clean capture the user asked
        # for. See debug.clear_log().
        ok, reason = debug.clear_log()
        if not ok:
            debug.note(
                "the debug log could not be cleared (%s). It is still "
                "there, and Debug Mode keeps writing to it." % reason)

    def set_rendersize(self):
        """RenderSize is also the resolution texture/geometry thumbnails
        generate at (their caches are keyed by it)."""
        self._prefs.rendersize = self.line_rendersize.value()

    def set_rendersamples(self):
        self._prefs.rendersamples = self.line_rendersamples.value()

    def set_scroll_speed(self, value: int) -> None:
        self._prefs.scroll_speed = value / 100.0

    def set_ram_cache_mb(self, value: int) -> None:
        """NO save() here - closeEvent persists it, like every other
        numeric row in this dialog.

        This was the one setter that saved per tick, and the row is a
        slider: ClickSlider fires valueChanged on every mouseMoveEvent,
        so one drag from 64 to 4096 rewrote and FSYNCED settings.json
        dozens to hundreds of times, each write also re-reading and
        re-parsing the file for the history snapshot and re-stat'ing
        the config directory. set_rendersize, set_rendersamples,
        set_karma_rendersamples, set_texture_parallel and
        set_scroll_speed all already leave persistence to closeEvent -
        and the toolbar's own size slider debounces by 500ms for
        exactly this reason (panel.py:1487).

        The live engine budget still updates immediately; it is only
        the WRITE that waits.
        """
        self._prefs.ram_cache_mb = value

    def _recompose_tile_icons(self, _index=None) -> None:
        """Line weight changed - redraw every tile icon that exists.

        The composed PNGs are baked, so without this the setting would
        only show up on icons chosen AFTER the change, which reads as
        the preference not working."""
        # self._panel, NOT parent(): this dialog is reparented to
        # Houdini's main window when it opens, so parent() is the
        # application window and every model lookup below silently
        # returns None - the preference would appear to do nothing.
        panel = self._panel
        for attr in ("material_model", "cop_model", "code_model"):
            model = getattr(panel, attr, None)
            if model is not None and hasattr(model, "rerender_tile_icons"):
                model.rerender_tile_icons()
        # The File section composes in memory, so it only needs a
        # repaint - and a cleared cache, or it redraws the old weight.
        tile_icons.forget_composed()
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
        """Rebuild enabled_sections from the checked boxes, in the fixed
        ALL_SECTIONS order. Never leave zero enabled - if the user
        unticks the last one, Materials is forced back on.

        Keys this build does NOT register are carried over untouched:
        an older build on the other machine still lists its tabs from
        this same shared setting ('texture'/'geometry'/'hip'), and a
        rebuild that drops what it does not recognise deletes that
        machine's tabs by side effect - the exact shape of the
        recorded toggle-deleted-HIP bug, recreated across builds."""
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

    # --------------------------------------------------- close = save

    def closeEvent(self, arg__1: QCloseEvent) -> None:
        """Save Preferences on ANY close path, then finish() the
        dialog: done() emits finished(int), the non-modal owner's
        apply hook - a plain close only HIDES a QDialog and skips
        that signal entirely."""
        self._prefs.save()
        arg__1.accept()
        self.done(0)

    def reject(self) -> None:
        """Esc must behave exactly like the window's close button: this
        dialog applies edits live and persists on close (there is no
        Cancel). QDialog's default reject() hides the window WITHOUT a
        close event, so Esc used to skip the save and the panel's
        prefs.load() then reverted every change made in the session."""
        self.close()
