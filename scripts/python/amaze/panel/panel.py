"""Constructs the Python panel Widget for the MatLib and provides Views to the Models"""

import os
import shutil
import importlib
import time
import contextlib

from PySide6 import QtWidgets, QtGui, QtCore, QtUiTools
import hou

import amaze
from amaze.core import grid_columns
from amaze.panel import (dragdrop_widgets, empty_state, grid, notes_panel,
                         sections, sidebar)
from amaze.core import debug, library_policy, repair
from amaze.core import versions
from amaze.core import notes
from amaze.core import scene_captures
from amaze.core import (
    folders,
    material,
    thumbnails,
    library,
    category,
    multifilterproxy_model,
    texture_library,
    gradient_library,
    cop_library,
    geo_library,
    file_library,
    code_library,
    matx_library,
    matx_import,
    matx_sources,
)
from amaze.dialogs import (
    base_dialog,
    prefs_dialog,
    usd_dialog,
    gradient_dialog,
    code_dialog,
    icon_dialog,
)
from amaze import branding
from amaze.prefs import prefs
from amaze.helpers import helpers, hostos, theme, ui_helpers, vex_syntax
from amaze.core import (
    database, dragengine, gallery_import, lop_assign, matx_icon, matx_translate,
    tile_icons,
)
from amaze.render import (
    generator,
    material_converter,
    nodes,
    thumbs,
)
from amaze import preview

# THE RELOAD CHAIN, and why it is off by default (2026-08-02).
#
# Houdini caches modules per session, so reopening the panel re-runs
# panel.py but would otherwise leave an old render/nodes.py behind -
# "new UI, old behavior". This chain re-executes every module the panel
# owns so a reopen picks up edits everywhere.
#
# It costs that on every open a person ever does, and the workflow it
# serves does not actually rely on it: the live-test loop already says
# to FULLY QUIT and relaunch Houdini rather than reopen the panel,
# precisely because module caching makes a reopen untrustworthy. So the
# chain was paying for a shortcut nobody is allowed to take.
#
# Set AMAZE_DEV_RELOAD=1 to turn it back on for a session where you do
# want reopen-to-refresh. Everything below stays one call per module,
# in dependency order, so the ordering comments keep their meaning -
# only whether they RUN changes.
_DEV_RELOAD = bool(os.environ.get("AMAZE_DEV_RELOAD"))


def _reload(module):
    """importlib.reload, unless the dev switch is off."""
    if _DEV_RELOAD:
        importlib.reload(module)


# Before library - the models import the shared thumbnail engine.
_reload(hostos)
_reload(debug)
_reload(dragengine)
_reload(lop_assign)
_reload(thumbnails)
_reload(database)
# Before library, which gates overwriting on it.
_reload(library_policy)
_reload(versions)
_reload(notes)
_reload(material)
# The render stack, leaf-first. These reloads used to live at the
# TOP of library.py/thumbs.py/nodes.py/thumbnail_scene.py - dev
# hot-reload in production import paths, with nodes and thumbs
# even reloading each other mid-import. ONE chain owns reloads
# now; the modules just import each other normally.
#
# THE PREVIEW ENGINE RELOADS ITSELF, and has to. Reloading a PACKAGE
# re-runs only its __init__.py, which then finds both submodules
# already in sys.modules and hands back the cached ones - the chain
# would look complete and refresh nothing. reload_engine() re-executes
# them leaf-first and re-binds the names the package exports.
if _DEV_RELOAD:
    preview.reload_engine()
_reload(material_converter)
_reload(nodes)
_reload(thumbs)
_reload(tile_icons)
# Before gradient_library (tile icons for gradients) and before the
# Node Info dialog, whose facts it reads.
# BEFORE library and its siblings: they mix in GridColumnsMixin and
# read the shared column order from it, so a stale grid_columns means
# the models answer a stale set of columns while the header answers
# the new one.
_reload(grid_columns)
_reload(library)
_reload(category)
_reload(repair)
_reload(folders)
_reload(prefs)
# Before ui_helpers - its class bodies read theme colors.
_reload(theme)
# FIRST: everything below reads its constants, and a stale branding is
# how adding APP_VERSION produced 38 unhandled AttributeErrors in a
# live session - the dialog reloaded, branding did not.
_reload(branding)
_reload(ui_helpers)
_reload(helpers)
_reload(texture_library)
_reload(gradient_library)
# After library/category so its subclasses bind to the freshly
# reloaded material classes.
_reload(cop_library)
# After texture_library - geo_library reuses its ThumbnailCache/proxy.
_reload(geo_library)
_reload(scene_captures)
# After texture/geo/hip - file_library composes all three engines.
_reload(file_library)
# Before code_library/code_dialog - both consume its palette/tokenizer.
_reload(vex_syntax)
# After library/category - subclasses the material machinery.
_reload(code_library)

# base_dialog FIRST: it is the shared base class of every form dialog,
# and gradient_dialog does `from amaze.dialogs.base_dialog import
# AssetDialog` - the one from-import of a CLASS in the package - so
# reloading gradient_dialog without reloading this first re-binds the
# SAME stale class. Verified: AssetDialog's identity was unchanged
# across a panel reopen, so editing base_dialog.py needed a full
# Houdini restart.
_reload(base_dialog)
_reload(prefs_dialog)
_reload(usd_dialog)
_reload(icon_dialog)
_reload(gradient_dialog)
_reload(code_dialog)
_reload(dragdrop_widgets)
# BEFORE sections, which imports it: the Grid area's builder and its
# ListColumns are read by every section's menu table, so a stale grid
# module means a panel reopen serves the old menu code while the
# sections around it get the new - the mixed-modules state the live
# test loop exists to avoid.
_reload(grid)
_reload(sidebar)
_reload(sections)
# After grid AND sections: it imports the first and reads the second's
# EMPTY declarations.
_reload(empty_state)
_reload(notes_panel)
_reload(multifilterproxy_model)
# The online stack was never in the chain at all - a panel reopen
# kept serving its cached pre-sync code.
_reload(matx_sources)
_reload(matx_translate)
_reload(matx_icon)
_reload(matx_import)
_reload(matx_library)
# Reachable from the panel (gallery_import from the Online menu,
# generator from the material generator) and both were missing from
# this chain, so editing either did nothing until a Houdini restart -
# the exact bug class that produced 38 unhandled AttributeErrors when
# branding was left out (log #285).
_reload(gallery_import)
_reload(generator)



# The two item delegates (610 lines of pure painting) live in
# panel/delegates.py. They are re-exported here because every section
# constructs them by these names, and because the reload chain below
# owns module reloading for the whole panel.
from amaze.panel import delegates            # noqa: E402

_reload(delegates)
# Houdini caches modules per session: a delegates.py left out of this
# chain would keep painting yesterday's tiles after a panel reopen.
AssetItemDelegate = delegates.AssetItemDelegate

#: When THIS execution of the module body began - so the reload chain
#: above can be measured. Deliberately NOT reload-survival state: the
#: point is to time the chain that just ran, and every panel open runs
#: it again. Reported once, in the "panel ready" record.
#:
#: The debug span used to open inside the constructor and close before
#: the widget was ever shown, so it could see neither phase a person
#: actually waits through - the import + chain before it, and the show
#: + first paint after it. Both are bracketed now.
_BODY_T0 = time.perf_counter()

#: The sentinel a mixed multi-selection shows in the details form;
#: set_assetdata reads it as the instruction to leave that field
#: alone. ONE home (material.py) - it is compared against, so a
#: second spelling is a silent overwrite; the source scan in
#: test_library keeps this the only one.
MULTIPLE_VALUES = material.MULTIPLE_VALUES
SidebarItemDelegate = delegates.SidebarItemDelegate

#: THE PANEL'S WIDTH FLOOR. ONE CONSTANT, deliberately not a computed
#: one: an earlier round grew this while Comments was open, and a floor
#: that moves under the user is worse than a narrow grid. Text in a
#: squeezed grid gets cut, and that is accepted.
#:
#: THE GRID PANE CARRIES NO MINIMUM, and that is not an oversight: a
#: child minimum propagates into the window's own, so flooring the grid
#: grew the floor whenever Comments opened - the same moving floor by
#: another route.
#:
#: Earned by measurement (research.md ▸ WHAT A SQUEEZED PANEL ACTUALLY
#: LEAVES THE GRID): the splitter left the grid viewport 48px wide,
#: narrower than one tile, inside a 537px panel.
#:
#: Design pixels, scaled through `theme.ui_px` at the point of use like
#: every other size in the panel.
MIN_PANEL_WIDTH = 500




class MatLibPanel(QtWidgets.QWidget):
    """Constructs the Python panel Widget for the MatLib and provides Views to the Models"""

    def __init__(self) -> None:
        super(MatLibPanel, self).__init__()
        # Stamped before any work, so "panel ready" can report the two
        # spans separately: everything the module body did before this
        # point, and the construction itself.
        self._construct_t0 = time.perf_counter()
        self._first_show_logged = False
        # Arm the always-on crash recorder before anything else, so a
        # failure during construction lands in the log even with Debug
        # Mode off (see core/debug.py).
        debug.install()
        try:
            self._build()
        except Exception as exc:
            debug.exception("panel construction", exc)
            raise

    def _build(self) -> None:
        # Initialize
        # The package locates its own bundled files ONE way.
        self.script_path = amaze.PACKAGE_ROOT
        self.prefs = prefs.Prefs()

        # load() returns False merely because the library DIRECTORY is
        # missing - the preferences object is populated either way. The
        # debug engine, the settings snapshot (the designated restore
        # source) and the cache override must therefore run on BOTH
        # paths: the session right after a settings loss is exactly the
        # one whose record matters most.
        loaded = self.prefs.load()
        # Configured before anything else runs: a crash during
        # setup() is precisely the case a debug log has to survive.
        debug.configure(self.prefs.debug_mode)
        debug.prefs_snapshot(self.prefs)
        # Custom thumbnail-cache location, before any cache is
        # touched - everything downstream resolves hostos.cache_root().
        hostos.set_cache_override(self.prefs.cache_dir)
        if loaded:
            self.init_ui()
            # AN UNREADABLE INDEX GETS A DIALOG, NOT A TRACEBACK. The
            # narrow catch below absorbs exactly one situation - the
            # primary index is on disk and will not parse - and offers
            # the repair the shelf tool would run. Everything else
            # still raises where it can be seen.
            try:
                self.load()
                self.setup()
            except (ValueError, OSError) as broken:
                index_path = os.path.join(self.prefs.dir or "",
                                          "library.json")
                try:
                    with open(index_path, "rb") as index_file:
                        index_bytes = index_file.read()
                except OSError:
                    index_bytes = b""
                if (self.prefs.dir and os.path.isfile(index_path)
                        and not hostos.parses_as_json(index_bytes)):
                    if not self._offer_index_repair(broken):
                        self._open_libraryless()
                        return
                else:
                    raise
            # Construction-complete tripwire: written seconds after the
            # session header through the same engine. A log whose header
            # exists but whose 'panel ready' is missing means logging
            # died DURING construction - see debug.probe().
            debug.event(
                "session", "panel ready",
                # The two spans the old record could not see. Module
                # body = the import + the 50-module reload chain that
                # runs before construction can start; construction =
                # what "session start -> panel ready" always measured.
                module_body_ms=round(
                    (self._construct_t0 - _BODY_T0) * 1000, 1),
                construction_ms=round(
                    (time.perf_counter() - self._construct_t0) * 1000, 1),
                **debug.probe())
        else:
            self.init_ui()
            self._open_libraryless()

    def _open_libraryless(self) -> None:
        """The no-library shape of the panel: every model attribute
        present and None, so the gear (the only way to configure a
        library) and every guard keep working."""
        self.material_model = None
        self.category_model = None
        # The same unconfigured defaults for the Cop stack -
        # save_cop_from_node (reachable from a node right-click at
        # any time) guards on cop_model, and without this the guard
        # itself would raise AttributeError.
        self.cop_model = None
        self.cop_category_model = None
        self.code_model = None
        self.code_category_model = None
        # The File models too: show_prefs hands file_files_model to
        # the Preferences dialog (which takes None), and Preferences
        # is the ONLY way to configure a library - leaving the
        # attribute unset made the gear an AttributeError on
        # exactly the machine that needs it most, the first run.
        self.file_files_model = None
        self.file_folders_model = None

    def _offer_index_repair(self, broken) -> bool:
        """The dialog an unreadable library.json earns: Repair (the
        newest saved copy, else the per-asset recovery stamps) or
        open without a library. True = repaired AND reopened. No
        success dialog - the recovered grid is the announcement."""
        debug.exception("library index unreadable at open", broken)
        ui = getattr(hou, "ui", None)
        if ui is None:
            return False
        choice = ui.displayMessage(
            "Your library's list could not be read.\n\n"
            "Repair puts back the newest saved copy - or, if none "
            "reads, rebuilds the list from what each asset itself "
            "remembers. Categories keep their names; their order and "
            "colours may not survive a rebuild. The broken file is "
            "kept beside itself either way.\n\n"
            "Open Without Library leaves the folder untouched.",
            buttons=("Repair", "Open Without Library"),
            severity=hou.severityType.Warning,
            default_choice=0, close_choice=1,
            title="Amaze")
        if choice != 0:
            debug.event("session", "index repair declined")
            return False
        ok, how = repair.repair_index(self.prefs.dir,
                                      self.prefs.asset_dir)
        if not ok:
            ui.displayMessage(
                "Repair could not fix the list: %s.\n\n"
                "Amaze opens without a library. The Repair tool on "
                "the Amaze shelf can tell you more." % how,
                severity=hou.severityType.Warning,
                title="Amaze")
            return False
        try:
            self.load()
            self.setup()
        except (ValueError, OSError) as still:
            debug.exception("index still unreadable after repair",
                            still)
            ui.displayMessage(
                "The repaired list still could not be read.\n\n"
                "Amaze opens without a library. The Repair tool on "
                "the Amaze shelf can tell you more.",
                severity=hou.severityType.Warning,
                title="Amaze")
            return False
        ui.setStatusMessage("Amaze: %s." % how)
        debug.event("session", "index repaired at open", how=how)
        return True

    # Menu title -> icon asset, each with a baked-in corner triangle as
    # the "opens a menu" hint. The two were swapped from the original
    # wireframe: the EYE belongs on the Filter menu, which is what you
    # can see, while the 3D box suits the View menu,
    # whose items are the library and the material sources. The gear
    # (icon_library.svg) is not here: it is a plain ACTION button
    # straight into Preferences, and its triangle was removed from the
    # SVG - the Library menu's items live on the Preferences Library
    # tab now.
    MENU_ICON_FILES = {
        "View": "icon_renderer.svg",
        "Filter": "icon_view.svg",
    }

    def _ui_icon_path(self, filename: str) -> str:
        """Absolute path of an icon asset in the plugin's ui/ folder, or
        "" if $AMAZE isn't set or no filename was given (callers and
        render_svg_pixmap treat "" as icon-missing and degrade). The
        four icon-loading sites all computed this same join inline
        before."""
        base = hou.getenv("AMAZE")
        if not base or not filename:
            return ""
        return os.path.join(
            base, "scripts", "python", "amaze", "ui", filename
        )

    def _make_menu_button(self, menu: QtWidgets.QMenu) -> "ui_helpers.IconMenuButton":
        """Stands in for a real QMenuBar item - QMainWindow reserves a
        dedicated dock area for its menu bar that can't share a row with
        other widgets, so the real menu bar (self.menu) stays alive and
        owns these QMenu objects but is hidden; this opens the same
        QMenu instance from an icon button instead (IconMenuButton in
        ui_helpers.py - hand-painted chips, tinted icon)."""
        icon_path = self._ui_icon_path(
            self.MENU_ICON_FILES.get(menu.title(), "")
        )
        button = ui_helpers.IconMenuButton(menu, icon_path)
        # A STABLE identity for this widget, independent of whether any
        # panel attribute happens to hold it. These buttons are held by
        # the layout alone, so a toolbar-row test could only call them
        # all "IconMenuButton" - three interchangeable entries, and
        # swapping Renderer and View ON SCREEN passed every layout test
        # in the suite. Exactly the ui_snapshot failure practice.md
        # records: unnamed siblings collapsed onto one key, so deleting
        # one of three toolbar buttons was invisible.
        button.setObjectName(
            "btn_menu_" + "".join(
                c for c in menu.title().lower() if c.isalnum())
        )
        return button

    def setup(self):
        self.category_model = category.Categories(preferences=self.prefs)
        self.category_sorted_model = category.CategoriesSidebarProxy()
        self.category_sorted_model.setSourceModel(self.category_model)
        self.category_sorted_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.category_sorted_model.setSortRole(self.category_model.CatSortRole)
        self.category_sorted_model.hide_empty = self.prefs.hide_empty_categories
        self.category_sorted_model.sort(0)

        self.material_model = library.MaterialLibrary(preferences=self.prefs)
        self.material_sorted_model = multifilterproxy_model.MultiFilterProxyModel()
        self.material_sorted_model.setSourceModel(self.material_model)
        self.material_sorted_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.material_sorted_model.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.material_sorted_model.sort(0)
        self.material_sorted_model.setDynamicSortFilter(False)  # Improves Performance
        self.material_selection_model = QtCore.QItemSelectionModel(
            self.material_sorted_model
        )
        self.thumb_delegate = AssetItemDelegate(
            self.material_model.RendererLabelRole,
            self.thumblist,
            category_role=self.material_model.CategoryRole,
            favorite_role=self.material_model.FavoriteRole,
            tag_role=self.material_model.TagRole,
            licence_role=self.material_model.LicenceRole,
            # The Nodes and Code sections share this delegate (one grid
            # view, models swapped) - and share the role NUMBER, since
            # both models subclass MaterialLibrary. So one wiring here
            # colours all three.
            category_color_role=self.material_model.CategoryColorRole,
            versions_role=self.material_model.VersionsRole,
            notes_role=self.material_model.NotesRole,
            active_version_role=self.material_model.ActiveVersionRole,
        )
        # A click on the chevrons badge opens the versions dialog; the
        # delegate only detects the hit, the panel owns the dialog.
        self.thumb_delegate.set_versions_click(self._open_versions_dialog)

        # NODE AND CODE GET THEIR OWN, WITHOUT THE VERSION ROLES.
        # They used to borrow thumb_delegate outright, and
        # `_sync_table_columns` decides a column EXISTS from the active
        # delegate's roles - so both painted a "Version" column reading
        # "none" on every row, floored at the width of "Version 99",
        # pushing Tags and License right. Worse and latent: editorEvent
        # and _sync_versions_hover run against the same delegate there,
        # and _open_versions_dialog maps its index through the MATERIAL
        # proxy and indexes material_model.assets - so the moment a
        # Node or Code asset grows a versions ledger, a badge click
        # opens (and can switch) an unrelated MATERIAL, with row -1
        # indexing the last asset.
        #
        # overview.md §2 and ListColumnHeader.COLUMNS both already say
        # "Version is materials-only and Open is File-only, so the two
        # are never in one row". This is what delivers it.
        self.asset_delegate = AssetItemDelegate(
            self.material_model.RendererLabelRole,
            self.thumblist,
            category_role=self.material_model.CategoryRole,
            favorite_role=self.material_model.FavoriteRole,
            tag_role=self.material_model.TagRole,
            licence_role=self.material_model.LicenceRole,
            category_color_role=self.material_model.CategoryColorRole,
            notes_role=self.material_model.NotesRole,
        )

        # The File section (the 2026-07-31 merge of Images, Geometry
        # and HIP): one folder-pointer list (plus the synthetic "All"
        # row) and a live, non-persisted listing of EVERY file in the
        # selected folder, each row behaving as its kind. Filtered
        # through TextureFilterProxyModel for the search box /
        # favorites-only star. See core/file_library.py.
        self.file_folders_model = file_library.FileFolders(self.prefs)
        self.file_files_model = file_library.FileFiles(self.prefs)
        self.file_sorted_model = texture_library.TextureFilterProxyModel()
        self.file_sorted_model.setSourceModel(self.file_files_model)
        self.file_selection_model = QtCore.QItemSelectionModel(
            self.file_sorted_model
        )
        self.file_delegate = AssetItemDelegate(
            self.file_files_model.FormatRole,
            self.thumblist,
            category_role=self.file_files_model.FolderRole,
            category_color_role=self.file_files_model.CategoryColorRole,
            favorite_role=self.file_files_model.FavoriteRole,
            open_role=self.file_files_model.OpenSceneRole,
            crop_role=self.file_files_model.CropRole,
            notes_role=self.file_files_model.NotesRole,
        )
        # The accent sweep for the tile delegates runs at the END of
        # setup(): tile_delegates() derives from self.sections, which
        # do not exist yet here - a sweep at this point walks an empty
        # tuple, which left every subtitle on the class default until
        # Preferences was opened once.
        # The "Type" header label follows the same accent as the type
        # entries the delegates paint.
        # The star preference colours the NOTES surfaces (chip lit +
        # pane accent); the tile badges render as drawn since the
        # unified family of 2026-08-01 and take no colour push.
        self._sync_notes_button_pixmaps()
        self.sidebar_delegate.show_counts = self.prefs.sidebar_counts
        thumbnails.engine.set_budget_mb(self.prefs.ram_cache_mb)
        self.file_files_model.progress_changed.connect(
            lambda done, total: self._on_folder_progress(
                "file", done, total))

        # v2: Gradients section - Sanzo Wada's color combinations as
        # curated, read-only content (see core/gradient_library.py).
        # Painted thumbnails, no files/workers, so the model trio is all
        # there is to set up.
        self.gradient_model = gradient_library.GradientLibrary(self.prefs)
        self.gradient_categories_model = gradient_library.GradientCategories(
            preferences=self.prefs
        )
        self.gradient_sorted_model = gradient_library.GradientFilterProxyModel()
        self.gradient_sorted_model.setSourceModel(self.gradient_model)
        self.gradient_selection_model = QtCore.QItemSelectionModel(
            self.gradient_sorted_model
        )
        self.gradient_delegate = AssetItemDelegate(
            self.gradient_model.RendererLabelRole,
            self.thumblist,
            category_role=self.gradient_model.CategoryLabelRole,
            category_color_role=self.gradient_model.CategoryColorRole,
            favorite_role=self.gradient_model.FavoriteRole,
            notes_role=self.gradient_model.NotesRole,
        )
        # (No per-delegate accent set here: the one sweep at the end of
        # setup() covers every tile delegate - a hand-set on this one
        # masked the dead early sweep for exactly one of five.)

        # v2: Cop section - standalone COP-network assets. A second,
        # fully independent material-style stack over its own cops.json
        # database (see core/cop_library.py); mirrors the material
        # model/proxy/selection construction above exactly. It uses
        # `asset_delegate`, NOT thumb_delegate: it did borrow that one
        # until the version roles were split out above, and this comment
        # went on saying so for two days.
        self.cop_model = cop_library.CopLibrary(preferences=self.prefs)
        self.cop_category_model = cop_library.CopCategories(preferences=self.prefs)
        self.cop_category_sorted_model = category.CategoriesSidebarProxy()
        self.cop_category_sorted_model.setSourceModel(self.cop_category_model)
        self.cop_category_sorted_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.cop_category_sorted_model.setSortRole(self.cop_category_model.CatSortRole)
        self.cop_category_sorted_model.hide_empty = self.prefs.hide_empty_categories
        self.cop_category_sorted_model.sort(0)
        self.cop_sorted_model = multifilterproxy_model.MultiFilterProxyModel()
        self.cop_sorted_model.setSourceModel(self.cop_model)
        self.cop_sorted_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.cop_sorted_model.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.cop_sorted_model.sort(0)
        self.cop_sorted_model.setDynamicSortFilter(False)
        self.cop_selection_model = QtCore.QItemSelectionModel(self.cop_sorted_model)

        # v2: Code section - reusable snippets over its own code.json
        # (see core/code_library.py). Same material machinery as COP,
        # storing snippet text inline and painting a code preview.
        self.code_model = code_library.CodeLibrary(preferences=self.prefs)
        self.code_category_model = code_library.CodeCategories(
            preferences=self.prefs
        )
        self.code_category_sorted_model = category.CategoriesSidebarProxy()
        self.code_category_sorted_model.setSourceModel(self.code_category_model)
        self.code_category_sorted_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.code_category_sorted_model.setSortRole(self.code_category_model.CatSortRole)
        self.code_category_sorted_model.hide_empty = self.prefs.hide_empty_categories
        self.code_category_sorted_model.sort(0)
        self.code_sorted_model = multifilterproxy_model.MultiFilterProxyModel()
        self.code_sorted_model.setSourceModel(self.code_model)
        self.code_sorted_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.code_sorted_model.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.code_sorted_model.sort(0)
        self.code_sorted_model.setDynamicSortFilter(False)
        self.code_selection_model = QtCore.QItemSelectionModel(self.code_sorted_model)
        # Seed the curated "Starter Toolbox" snippets once per library.
        self.code_model.seed_starter_snippets(self.code_category_model)

        # Multi-category was removed: collapse every asset to a single
        # category (its first). Idempotent, so this one-time migration
        # just no-ops on every subsequent launch.
        for _model in (self.material_model, self.cop_model, self.code_model):
            try:
                _model.collapse_multicategory()
            except Exception as exc:
                # event, not note, for all four panel sites: the panel's
                # user-facing channel here is a dialog (the geometry
                # import below raises one), and each of these lines is an
                # internal fallback the user cannot act on.
                debug.event("session", "category collapse failed",
                            error=str(exc))

        # v2: online MaterialX browser. Not a section - a VIEW MODE over
        # the Materials grid (View menu > Online Materials). Uses the
        # same role numbers as MaterialLibrary, so the existing delegate
        # and filter proxy serve it unchanged.
        self.matx_online_model = matx_library.MatxOnlineLibrary(
            preferences=self.prefs
        )
        self.matx_sorted_model = multifilterproxy_model.MultiFilterProxyModel()
        self.matx_sorted_model.setSourceModel(self.matx_online_model)
        self.matx_sorted_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.matx_sorted_model.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.matx_sorted_model.setDynamicSortFilter(False)
        self.matx_selection_model = QtCore.QItemSelectionModel(
            self.matx_sorted_model
        )
        self.matx_source_model = matx_library.MatxSidebarModel(
            self.matx_online_model
        )
        # THE ONLINE WORLD GETS ITS OWN, WITH ONLY THE ROLES ITS MODEL
        # HAS. matx_library exposes seven roles and none of them is
        # licence, versions, notes or category colour - so borrowing a
        # local delegate gave the online grid columns that can never
        # carry a value on any row, and `_sync_table_columns` decides a
        # column EXISTS from the active delegate's roles. Same defect
        # shape as Node and Code borrowing the Materials delegate, one
        # world over.
        self.matx_delegate = AssetItemDelegate(
            self.matx_online_model.RendererLabelRole,
            self.thumblist,
            category_role=self.matx_online_model.CategoryRole,
            favorite_role=self.matx_online_model.FavoriteRole,
            tag_role=self.matx_online_model.TagRole,
        )
        # Preview downloads drive the same thin bar as texture/geo thumbs.
        self.matx_online_model.progress_changed.connect(
            self._on_online_preview_progress
        )
        self.online_mode = False
        self.online_source = None
        #: The online world, as a context object with a Section's
        #: interface. NOT in `sections` and not in `enabled_sections` -
        #: it is a parallel world, not a section - but every area path
        #: reaches it through `_section()` like any other.
        self.online_context = sections.OnlineContext(self)

        # THE COLUMN MEMO IS GONE, and these six connections with it.
        # They kept a hand-built measure-and-fit fresh as filters,
        # renames and folder changes altered what was shown - including
        # the online grid, which was once left out and showed a few
        # hundred names elided into a 120px floor. `ResizeToContents`
        # on the table's own header is what does it now, per column,
        # and Qt keeps it fresh without being told (2026-08-04).

        self.material_selection_model.selectionChanged.connect(self.update_details_view)
        # Keyboard selection moves reach the Notes pane too - every
        # section's selection model, guarded inside the handler (a
        # no-op while the pane is hidden, and it reads only the ACTIVE
        # section's current index). Connected HERE because the models
        # are built in setup(), after init_ui.
        for _notes_selection in (
            self.material_selection_model,
            self.cop_selection_model,
            self.code_selection_model,
            self.file_selection_model,
            self.gradient_selection_model,
        ):
            _notes_selection.selectionChanged.connect(
                self._refresh_notes_subject)

        # The section registry: one object per tab, each encapsulating how
        # it drives the shared widgets (activate/filter/favourites/
        # category-select/double-click). The shared handlers dispatch to
        # self._section() instead of branching on current_section - a new
        # section is a new class in panel/sections.py, not edits here.
        self.sections = sections.build_sections(self)

        # Tile subtitle line follows the accent preference for EVERY
        # tile delegate (instance attribute shadows the class default;
        # refreshed again in show_prefs() when the accent changes).
        # AFTER build_sections, deliberately: tile_delegates() derives
        # from the sections, so any earlier sweep walks an empty tuple.
        for tile_delegate in self.tile_delegates():
            tile_delegate.DIM = theme.accent(self.prefs.accent_color)

        # Start on the first ENABLED section (usually Materials, but a
        # user may have hidden it). Models all exist regardless of which
        # tabs are shown.
        first_key = next(
            (k for k, _ in self.ALL_SECTIONS if k in self.prefs.enabled_sections),
            "material",
        )
        if first_key == "material":
            self.sections["material"].activate()
        else:
            self._on_tab_toggled(first_key, True)
        self.section_tabs.setChecked(first_key, emit=False)
        # The Materials branch above does NOT go through _on_tab_toggled,
        # so the toolbar sync every tab click gets never ran for the
        # section the panel OPENS on - which is the one a user sees first.
        self._sync_toolbar_for_mode()
        # ...and the Filter menu belongs to the section that just
        # opened, so it is filled here for the same reason.
        self.build_filter_menu()
        self.click_slider.setValue(self._active_thumbsize())
        self.slide()
        self.apply_view_state()

    def open(self) -> None:
        """Open the currently in preferences specified library"""
        if not self.material_model or not self.category_model:
            return
        self.material_model.save()
        self.prefs.load()
        self.load()
        if not self.material_model:
            self.setup()

        # THE SAME WALK EVERY OTHER SWITCH SITE USES. This was a
        # hand-written copy with its own nested relayouts, and it is
        # one of the three that between them carried seven of the
        # eight library-backed models.
        self.switch_all_models()

        debug.event("session", "library reloaded")

    @staticmethod
    def starter_would_overwrite(lib_dir: str) -> list:
        """The evidence that `lib_dir` has HELD a library, or [].

        One function, called by load() and by the test that proves
        load() refuses - the first version of that test re-derived this
        logic privately, so sabotaging the panel left it green: it was
        testing its own copy, not the product.
        """
        found = []
        evidence = database.absent_but_known(lib_dir, "library.json")
        if evidence:
            found.append(evidence)
        for name in ("mat", "img"):
            folder = os.path.join(lib_dir, name)
            if os.path.isdir(folder) and os.listdir(folder):
                found.append(name + "/")
        return found

    def load(self) -> None:
        """Load the currently in preferences specified library
        Copies necessary data to the target directory if not created yet"""
        lib_dir = self.prefs.dir
        if not lib_dir or lib_dir == "/" or not os.path.isdir(lib_dir):
            # No (or invalid) library directory set - the panel opens
            # library-less and the Preferences Library tab sets one;
            # copying the starter db against an empty dir once wrote
            # to the filesystem root ("//library.json").
            debug.event("session", "no library directory set",
                        dir=lib_dir)
            return
        new_folder = False
        if not os.path.exists(self.prefs.dir + "/library.json"):
            # ABSENT IS NOT EMPTY. This guarded on library.json alone,
            # and any of the causes _refuse_absent exists for - a sync
            # that has not finished arriving, a selective-sync hole, a
            # network volume mid-mount - leaves a directory FULL of
            # assets with a momentarily missing index. Seeding the
            # starter over that turns a hiccup into a library whose next
            # Clean would read every real file as unowned.
            # database.absent_but_known is the same question the loaders
            # ask, deliberately, so the two can never disagree.
            #
            # The starter seeds an EMPTY asset list. It shipped holding
            # one blank record (id -1, no name, date -1) inherited from
            # the fork, which meant every library ever created opened
            # with a phantom asset that nothing removed and every save
            # re-emitted; removed 2026-08-04, pinned by
            # test_absent_database ▸ TheStarterSeedsNoAssetsTest.
            held = self.starter_would_overwrite(self.prefs.dir)
            if held:
                debug.event("session", "starter NOT seeded - the "
                            "directory has held a library",
                            dir=self.prefs.dir, evidence=held)
                debug.alert(
                    "This folder looks like a library whose list has not "
                    "arrived yet, so Amaze did not set up a new one over "
                    "it.\n\n"
                    "If it lives in a synced folder, let the sync finish "
                    "and reopen Amaze. If the list really is gone, run "
                    "Repair Library from the Amaze shelf to rebuild it.",
                    key="starter-refused")
                return
            oldpath = amaze.package_file("res", "def", "library.json")
            shutil.copy(oldpath, self.prefs.dir + "/library.json")
            new_folder = True
        if self.ensure_library_dirs(self.prefs):
            new_folder = True
        if new_folder:
            debug.event("session", "library created", dir=self.prefs.dir)

    @staticmethod
    def ensure_library_dirs(preferences) -> bool:
        """Make sure `img/` and `mat/` both exist. True if either was
        created.

        ASKED PER FOLDER, because they are created as a pair and were
        guarded as one: `img/` missing beside a present `mat/` raised
        `FileExistsError` out of the second `os.mkdir`, which `_build`
        reads as a broken library and re-raises, so the panel refused
        to open on a library that was fine. `mat/` missing beside a
        present `img/` was never created at all.

        `exist_ok=True` is what every other folder-creating site in
        this package already uses; these two were the only bare
        `os.mkdir` calls in it.
        """
        made = False
        for tail in (preferences.img_dir, preferences.asset_dir):
            folder = os.path.join(preferences.dir, tail)
            if not os.path.isdir(folder):
                made = True
            os.makedirs(folder, exist_ok=True)
        return made

    def set_library(self) -> None:
        """
        User Sets library via Menu Option so we have to reroute

        """
        # if not self.material_model or not self.category_model:
        #   return
        if self.prefs.get_dir_from_user():
            self.prefs.load()
            self.load()
            if not self.material_model:
                self.setup()

            # Every library-backed model switches - leaving the Cop and
            # Code stacks on the OLD library's data was a long-standing
            # gap versus open()/show_prefs(), which always switched all
            # four. Colors was the last one missing (2026-08-02): the
            # only library-backed model in none of the three lists.
            self.switch_all_models()

    def library_models(self) -> tuple:
        """EVERY library-backed model that exists right now, DERIVED
        from the sections - the way `tile_delegates()` derives.

        Each section declares its own in `library_model_attrs`, so a
        section arriving with a model of its own joins by existing.
        There were THREE hand-written lists here instead, each naming
        seven models where there are eight: the Colors SIDEBAR
        (`gradient_categories_model`) was in none of them, so a
        library switch left it showing the previous library's
        category names beside the new library's counts - every row
        zero, and a rename aimed at the new library carrying the old
        label. Five siblings had been added to those same three lists
        over time, one at a time, which is what a hand-kept list
        costs.
        """
        found = []
        for section in getattr(self, "sections", {}).values():
            for attr in getattr(section, "library_model_attrs", ()):
                model = getattr(self, attr, None)
                if model is not None and model not in found:
                    found.append(model)
        return tuple(found)

    def switch_all_models(self) -> None:
        """Re-point every library-backed model at `prefs.dir`.

        THE ONE ROUTE ONTO ANOTHER LIBRARY, and now the one route
        that re-points models at all: `open()` and `_prefs_closed()`
        each carried their own copy of this walk, which is how a list
        goes short without anything failing. A switch that skipped a
        model left it serving the previous library with every save
        refused (measured 2026-08-08 through the Test Library toggle).
        """
        models = self.library_models()
        if not models:
            return
        with ui_helpers.relayout(*models):
            for m in models:
                m.switch_model_data()
            self.click_slider.setValue(self._active_thumbsize())

    def toggle_catview(self) -> None:
        """Show and Hide the Category View via Menu"""
        if self.action_catview.isChecked():
            self.cat_wrapper.setVisible(True)
            self.action_catview.setChecked(True)
        else:
            self.cat_wrapper.setVisible(False)
            self.action_catview.setChecked(False)
        # Remember the choice across sessions
        self.prefs.show_categories = self.action_catview.isChecked()
        self.prefs.save()
        # The chip IS this state - keep it in step whichever side moved
        # (the action can still be toggled from code and from tests).
        button = getattr(self, "btn_categories", None)
        if button is not None and button.isChecked() != (
                self.action_catview.isChecked()):
            was = button.blockSignals(True)
            button.setChecked(self.action_catview.isChecked())
            button.blockSignals(was)

    def _on_categories_button(self, checked: bool) -> None:
        """The button moved - tell the action, which owns the rest."""
        if self.action_catview.isChecked() != checked:
            self.action_catview.setChecked(checked)
        self.toggle_catview()

    def _on_online_button(self, checked: bool) -> None:
        if checked:
            self.enter_online_world()
        else:
            self.leave_online_world()

    def _sync_online_button_pixmaps(self) -> None:
        """Amber when you are in the online world, the family blue when
        you are not - the star's treatment, through the one engine."""
        button = getattr(self, "btn_online", None)
        if button is None:
            return
        button.set_art(
            self._ui_icon_path("icon_online.svg"),
            lighten_on_hover=False,
            recolour_on={ui_helpers.IconMenuButton.IDLE_BODY:
                         theme.color_hex("star")})

    def _sync_categories_button_pixmaps(self) -> None:
        """The chip's four states, in the toolbar icon family's own
        tints - as drawn at rest, lit when hovered or on."""
        button = getattr(self, "btn_categories", None)
        if button is None:
            return
        button.set_art(self._ui_icon_path("icon_categories.svg"),
                       lighten_on_hover=False)

    def edit_material_info(self) -> None:
        """Open the material info dialog for the current selection
        (right-click "Edit Info"). update_details_view already keeps the
        form populated from the selection, so this just shows/raises the
        floating dialog."""
        if not self.material_model:
            return
        self.update_details_view()
        self.details.setVisible(True)
        self.details_dialog.show()
        self.details_dialog.raise_()
        self.details_dialog.activateWindow()

    def apply_view_state(self) -> None:
        """Apply the persisted category/details visibility from preferences"""
        self.action_catview.setChecked(self.prefs.show_categories)
        self.cat_wrapper.setVisible(self.prefs.show_categories)
        self.apply_view_mode()

    def _restore_drag_mode(self) -> None:
        return grid.restore_drag_mode(self)

    def bind_grid_views(self, proxy, selection, delegate) -> None:
        """Point BOTH grid views at one context's model, proxy,
        selection model and delegate.

        Two views over one selection model is Qt's own arrangement and
        it is what keeps list mode from doubling every area binding:
        the four `activate()` bodies bind once, and neither view can
        drift from the other because there is nothing to keep in step.
        """
        for view in (self.thumblist, getattr(self, "thumbtable", None)):
            if view is None:
                continue
            view.setModel(proxy)
            if selection is not None:
                view.setSelectionModel(selection)
        if delegate is not None:
            self.thumblist.setItemDelegate(delegate)
            # THE TABLE DOES NOT WEAR THE TILE DELEGATE. That delegate
            # paints a whole TILE per index, which is right where one
            # index is one tile and catastrophic where a row is ten of
            # them - the first render put ten tile-height cells side by
            # side. Qt paints every text cell itself; only the picture
            # and the tick columns get one, and they are per COLUMN.
            self._bind_table_cell_delegates(delegate)

    def _sidebar_row_height(self, table) -> int:
        return grid.sidebar_row_height(self, table)

    def _show_table(self, showing: bool) -> None:
        return grid.show_table(self, showing)

    #: AIR EITHER SIDE OF A CELL'S TEXT - asked for 2026-08-04, on the
    #: first table build. Without it a name starts hard against the
    #: column line and the next column's first letter sits against the
    #: end of the last one.
    #:
    #: ONE HOME, in the delegate that draws the cells. It is named here
    #: because the header strip has to start its label where the rows
    #: start theirs, and a second literal is how the two drift apart.
    #: Two earlier routes are gone: a `QTableView::item` stylesheet,
    #: which hands item drawing to `QStyleSheetStyle` and takes the
    #: font, the selection blend and the selected-text colour with it;
    #: and a `QProxyStyle` on `PM_FocusFrameHMargin`, which `setStyle`
    #: does not own and nothing else keeps alive.
    CELL_PAD = theme.ui_px(5)
    #: The strip's own two colours and height, kept so the table
    #: matches the painted header it replaced - a `QHeaderView` picks
    #: up none of them on its own. The LABEL colour is not here: it is
    #: the rows' ink, read from the delegate that paints them.
    HEADER_BG = QtGui.QColor("#2a2a2a")
    HEADER_DIVIDER = QtGui.QColor("#454545")
    HEADER_HEIGHT = theme.ui_px(20)

    def _bind_table_cell_delegates(self, tile_delegate) -> None:
        return grid.bind_table_cell_delegates(self, tile_delegate)
        # NOT the row height here: `activate()` can run in GRID mode,
        # where `_active_thumbsize()` answers with the grid slider's
        # 128 and the rows came out 133px tall. The height is set where
        # the mode is actually known - `_show_table`.

    def sync_list_columns(self) -> None:
        return grid.sync_list_columns(self)

    #: A COLUMN'S STARTING WIDTH. Nothing is measured at runtime any
    #: more - a fit costs 0.4ms sampled and 13.5ms over every row, and
    #: it ran again on every change of the row set, which is what made
    #: a big category slow to open.
    #:
    #: Derived once instead, offscreen, from the real 549-asset library
    #: (2026-08-04): each is the wider of its HEADING and the 90th
    #: percentile of the values in it, capped at 300 so one long Tags
    #: entry cannot eat the row. The p90 rather than the maximum
    #: because a column you can DRAG does not have to fit its worst
    #: case - Tags reaches 851px on a single asset.
    #:
    #: There were no earlier tuned numbers to recover, which is worth
    #: recording: the retired `ListColumns` was
    #: `namedtuple("ListColumns", KEYS)` - names and no values - and
    #: the only stored widths in the old machinery were
    #: `LIST_FALLBACKS = {"name": 200, "type": 150}`, reached only when
    #: measuring produced nothing. Measured p90 puts Name at 176.
    COLUMN_DEFAULT_WIDTH = {
        "thumb": 24, "name": 176, "type": 59, "category": 76,
        "favorite": 69, "version": 66, "open": 54, "comments": 85,
        "tags": 300, "license": 287,
    }

    #: The floor for ANY column: `minimumSectionSize` is global, not
    #: per-column (Qt docs), so it cannot be used to give License a
    #: minimum of its own. Small enough that a tick column is not
    #: forced wide by it.
    COLUMN_MIN_WIDTH = 24

    def _sync_table_columns(self) -> None:
        return grid.sync_table_columns(self)

    def _style_table_header(self) -> None:
        return grid.style_table_header(self)

    def apply_view_mode(self) -> None:
        grid.apply_view_mode(self)
        # The other view is up now, so the blank re-attaches to ITS
        # model - the two carry the same proxy today, and this does not
        # rely on that staying true.
        empty_state.track(self)

    def showEvent(self, event):
        """Close the other half of the timing gap, once.

        "panel ready" fires while the widget is still unparented and
        unpainted: Houdini then shows it, Qt polishes it under the
        Houdini stylesheet, lays it out and paints the first page of
        tiles. None of that was measured, and it is the part a person
        sits and watches. Recorded on the FIRST show only - reopening
        a tab must not look like a fresh open - and after the event
        loop turns once, so the number includes the first paint rather
        than stopping just before it.
        """
        super(MatLibPanel, self).showEvent(event)
        if self._first_show_logged:
            return
        self._first_show_logged = True
        t0 = getattr(self, "_construct_t0", None)
        if t0 is None:
            return

        def _record():
            debug.event(
                "session", "panel visible",
                construct_to_painted_ms=round(
                    (time.perf_counter() - t0) * 1000, 1))

        QtCore.QTimer.singleShot(0, _record)

    def event(self, event):
        """Flush the Comments pane when this panel is being DESTROYED.

        Measured (Qt 6.8, offscreen): hiding or closing a window sends
        a hide event to its children, so the pane's own hideEvent
        covers those - but DELETING a parent sends its children
        nothing at all. That is how a Houdini pane tab goes away, and
        it left the last 600ms of typing (the save debounce) in a
        widget about to stop existing.

        DeferredDelete arrives while every widget is still alive, which
        is what makes the pending page serializable here.
        """
        if event.type() == QtCore.QEvent.Type.DeferredDelete:
            pane = getattr(self, "notes_panel", None)
            if pane is not None:
                pane.flush()
        return super(MatLibPanel, self).event(event)

    def eventFilter(self, watched, event):
        """Hover tracking for the grid's version marks.

        It also re-applied a list-mode row size on every viewport
        resize. That went with the painted list: THE TABLE IS LIST
        MODE now (grid.apply_view_mode), and `thumblist` is hidden the
        whole time list mode is up - so the branch computed a grid
        size, compared it, and set it on a widget nobody could see.
        The table sizes its own rows and columns, in `show_table` and
        `_sync_table_columns`.
        """
        if (getattr(self, "thumblist", None) is not None
                and watched is self.thumblist.viewport()
                and hasattr(self, "thumb_delegate")):
            if event.type() == QtCore.QEvent.Type.MouseMove:
                self._sync_versions_hover(event.position().toPoint())
            elif event.type() == QtCore.QEvent.Type.Leave:
                self._sync_versions_hover(None)
        return False

    def _sync_versions_hover(self, point) -> None:
        """Light the versions badge the cursor is on, and only that
        one. Repaints ONLY when the answer changed - this runs on
        every mouse move across the grid."""
        # THE ACTIVE delegate, not thumb_delegate by name: Node and
        # Code have their own now (no version roles), and hard-coding
        # the Materials one meant this ran the versions hit-test and
        # hover state against a delegate that is not the one painting.
        delegate = self.thumblist.itemDelegate()
        if not hasattr(delegate, "versions_badge_at"):
            return
        index = QtCore.QModelIndex()
        if point is not None:
            candidate = self.thumblist.indexAt(point)
            if candidate.isValid() and delegate.versions_badge_at(
                    candidate,
                    self.thumblist.visualRect(candidate),
                    point,
                    # The WIDGET's own answer, like the delegate's -
                    # prefs.view_mode was a third proxy for one fact.
                    self.thumblist.viewMode()
                    != QtWidgets.QListView.ViewMode.ListMode):
                index = candidate
        previous = getattr(delegate, "_versions_hover", None)
        if delegate.set_versions_hover(index):
            if previous is not None and previous.isValid():
                self.thumblist.update(QtCore.QModelIndex(previous))
            if index.isValid():
                self.thumblist.update(index)






    def _sync_view_mode_controls(self) -> None:
        return grid.sync_view_mode_controls(self)

    #: List mode's ONE size (2026-08-01). A list row is a text line,
    #: not a picture, so it does not scale and its slider is greyed:
    #: 16px of thumbnail under a ~30px row. `thumbsize_list` is still
    #: written for older builds on the other machine, and no longer
    #: read here.
    LIST_THUMB_SIZE = 16

    def _active_thumbsize(self) -> int:
        return grid.active_thumbsize(self)

    def _sync_slider_for_mode(self) -> None:
        """The slider drives GRID only. In list it is greyed - there
        is one list size and nothing to choose - and its value is
        parked at the minimum so the handle does not sit somewhere
        that implies otherwise."""
        grid = self.prefs.view_mode != "list"
        self.click_slider.setEnabled(grid)
        self.click_slider.setToolTip(ui_helpers.tooltip_text(
            "Tile size." if grid else
            "Tile size - grid only. A list row is one text line, so "
            "it does not scale."))
        if not grid:
            was = self.click_slider.blockSignals(True)
            self.click_slider.setValue(self.click_slider.minimum())
            self.click_slider.blockSignals(was)

    def _set_view_mode(self, mode: str) -> None:
        """Central entry: persist and apply a view mode ('grid' or 'list')."""
        self.prefs.view_mode = mode
        self.prefs.save()
        # Jump the slider to the new mode's own remembered size. If the
        # value actually changes this fires slide(), which re-applies
        # sizing/icons; the explicit apply_view_mode() below covers the
        # equal-values case (setValue emits nothing then, but the view
        # still has to restructure for the new mode).
        self.click_slider.setValue(self._active_thumbsize())
        self.apply_view_mode()

    def on_viewmode_button(self, checked: bool) -> None:
        """Filter-row toggle: checked = list, unchecked = grid."""
        if getattr(self, "_suppress_view_signals", False):
            return
        self._set_view_mode("list" if checked else "grid")

    def _build_slider_and_layout(self) -> None:
        """The size slider, the filter box's icon, and the panel's own layout.

        Split out of init_ui, which built the whole panel in one
        800-line method. Called from init_ui in the same order it
        ran in - no local variable crosses this boundary.
        """
        self.click_slider.setMaximumWidth(theme.ui_px(200))
        # The design's order is [Filter box] [slider] [star] [toggle]
        # [menus], but this block runs after the star/toggle blocks -
        # insert at the spot remembered right after the filter box was
        # added. Both slider-side gaps are 20 (40px rendered each -
        # up from the design rev's 10/6).
        if self.toolbar_layout is not None:
            idx = getattr(
                self, "_after_filter_index", self.toolbar_layout.count()
            )
            self.toolbar_layout.insertSpacing(idx, theme.ui_px(20))
            self.toolbar_layout.insertWidget(idx + 1, self.click_slider)
            self.toolbar_layout.insertSpacing(idx + 2, theme.ui_px(20))
        # Debounce for persisting the per-mode icon size: slide() fires
        # on every pixel of a drag, and settings.json lives in the
        # cloud-synced install folder - write once, shortly after the
        # drag settles, instead of dozens of times per second.
        self._thumbsize_save_timer = QtCore.QTimer(self)
        self._thumbsize_save_timer.setSingleShot(True)
        self._thumbsize_save_timer.setInterval(500)
        self._thumbsize_save_timer.timeout.connect(self.prefs.save)
        self.click_slider.valueChanged.connect(self.slide)
        # Houdini-22-style look (groove/handle) is painted directly by
        # ClickSlider.paintEvent - QSS sub-page/add-page styling proved
        # unreliable (colors landed on the correct side, but the declared
        # heights didn't) so this widget draws itself deterministically
        # instead of relying on the style/stylesheet system for it.

        # TEST: mirror the whole toolbar row to
        # the left. All toolbar_layout additions are complete by this
        # point (the slider insertion above is the last one).
        self._mirror_toolbar()

        # RC Menus
        self.thumblist.customContextMenuRequested.connect(self.thumblist_rc_menu)
        self.cat_list.customContextMenuRequested.connect(self.catlist_rc_menu)

        # set main layout and attach to widget
        mainlayout = QtWidgets.QVBoxLayout()
        mainlayout.addWidget(self.ui)
        mainlayout.setContentsMargins(0, 0, 0, 0)  # Remove Margins

        self.setLayout(mainlayout)

    def _build_menus(self) -> None:
        """The View and Renderer menus, and the toolbar buttons that own them.

        Split out of init_ui, which built the whole panel in one
        800-line method. Called from init_ui in the same order it
        ran in - no local variable crosses this boundary.
        """
        self.menu.addMenu(self.menu_filter)
        if self.toolbar_layout is not None:
            # Icon controls at the toolbar's right end, per the
            # "ui_wireframe 2 only menu" design - order left to right:
            # Filter (box, menu), View (eye, menu), Preferences (gear,
            # outermost - a PLAIN button straight into Preferences; the
            # Library menu it used to pop dissolved into the dialog's
            # Library tab).
            menu_view = self.ui.findChild(QtWidgets.QMenu, "menuView")
            # The Comments chip joins the ICON FAMILY and stays that

            # blue in all states, not white while on"; the state is
            # carried by the chip's BACKGROUND. `_sync_notes_button_
            # pixmaps` has the whole reasoning.
            #
            # It is built FIRST of the toolbar chips - Online, Filter,
            # Categories and Capture follow it below - and the row is
            # mirrored afterwards, so build order is not display order:
            # read overview.md §2 for where it lands.
            #
            # This comment used to say the chip lights in the STAR's
            # colour and that it is built just before the Renderer
            # button. Both were true once and neither survived: the
            # star-yellow lighting was removed WITH the yellow art, and
            # btn_filter is built after this, not before.
            self.btn_notes = ui_helpers.ChipToggleButton()
            self.btn_notes.setObjectName("btn_notes")
            self.btn_notes.setToolTip(ui_helpers.tooltip_text(
                "Comments - a page of text and to-dos for the selected "
                "tile"))
            self._sync_notes_button_pixmaps()
            self.btn_notes.setChecked(bool(self.prefs.show_notes))
            # Connected AFTER the initial state, so restoring a saved
            # "open" does not re-save preferences mid-construction.
            self.btn_notes.toggled.connect(self._on_notes_toggled)
            self.toolbar_layout.addWidget(self.btn_notes)
            # Online, immediately LEFT of Comments once the row is
            # mirrored - so it is added right after it here. The AMBER
            # is the whole signal

            # indicate your in a state" - which is the favourites
            # star's pattern exactly, so it is built the same way, by
            # the same engine, and does not lighten on hover because
            # the colour is what carries the state.
            self.toolbar_layout.addSpacing(theme.ui_px(2))
            self.btn_online = ui_helpers.ChipToggleButton()
            self.btn_online.setObjectName("btn_online")
            self.btn_online.setToolTip(ui_helpers.tooltip_text(
                "Browse materials online."))
            self._sync_online_button_pixmaps()
            self.btn_online.setChecked(self._is_online())
            self.btn_online.toggled.connect(self._on_online_button)
            self.toolbar_layout.addWidget(self.btn_online)
            self.toolbar_layout.addSpacing(theme.ui_px(2))
            # Held on self, unlike the other two menu buttons: this one
            # is disabled online and its tooltip is rewritten on every
            # section change, so the layout is no longer the only thing
            # that needs to reach it.
            self.btn_filter = self._make_menu_button(self.menu_filter)
            self.toolbar_layout.addWidget(self.btn_filter)
            if menu_view is not None:
                self.toolbar_layout.addSpacing(theme.ui_px(2))
                btn_view = self._make_menu_button(menu_view)
                btn_view.setToolTip(ui_helpers.tooltip_text(
                    "Import a gallery file, or generate a material."))
                self.toolbar_layout.addWidget(btn_view)
            self.toolbar_layout.addSpacing(theme.ui_px(2))
            btn_prefs = ui_helpers.IconMenuButton(
                None,
                self._ui_icon_path("icon_library.svg"),
                on_click=self.show_prefs,
                fallback_label="Preferences",
            )
            # Named for the same reason as the two menu buttons above -
            # nothing else can tell these three apart. Deliberately NOT
            # also stored on self: the layout owns it, and adding an
            # attribute is what made a toolbar test report a naming
            # refactor as a layout defect.
            btn_prefs.setObjectName("btn_prefs")
            btn_prefs.setToolTip(ui_helpers.tooltip_text(
                "Open preferences."))
            self.toolbar_layout.addWidget(btn_prefs)
            # Show Categories, promoted out of the View menu to a button

            # because the row is mirrored at the end of construction, so
            # the last widget added is the leftmost one drawn - this

            # for it.
            #
            # It DRIVES action_catview rather than repeating it. The
            # action already owns the behaviour and the persistence, and
            # two paths to one preference is how a toggle ends up
            # disagreeing with the thing it toggles.
            self.toolbar_layout.addSpacing(theme.ui_px(2))
            self.btn_categories = ui_helpers.ChipToggleButton()
            self.btn_categories.setObjectName("btn_categories")
            self.btn_categories.setToolTip(ui_helpers.tooltip_text(
                "Show the category sidebar."))
            self._sync_categories_button_pixmaps()
            self.btn_categories.setChecked(
                bool(self.prefs.show_categories))
            self.btn_categories.toggled.connect(
                self._on_categories_button)
            self.toolbar_layout.addWidget(self.btn_categories)
            # Capture, outermost - HIP only. Same button class and the
            # same 2px gap as the cluster to its left, so it reads as
            # one row rather than an afterthought bolted on the end.
            # Hidden for every other section: it acts on the open SCENE,
            # which is meaningless where the tiles are materials.
            self.toolbar_layout.addSpacing(theme.ui_px(2))
            self.btn_hip_capture = ui_helpers.IconMenuButton(
                None,
                self._ui_icon_path("icon_screenshot.svg"),
                on_click=self.capture_open_scene_thumbnail,
                fallback_label="Capture",
            )
            self.btn_hip_capture.setObjectName("btn_hip_capture")
            self.btn_hip_capture.setToolTip(ui_helpers.tooltip_text(
                'Captures a preview from "scene view" pane'
            ))
            self.btn_hip_capture.setVisible(False)
            self.toolbar_layout.addWidget(self.btn_hip_capture)
        # The Filter menu is NOT built here: its entries belong to
        # whichever section is showing, and no section exists yet at
        # this point in construction. build_filter_menu fills it, and
        # runs again on every section change.
        self.filter_action_group = None
        self.filter_actions = {}
        self.filter_values = {}

        # View menu, in the order specified in ui-text.md:
        #   Material Library / Online Materials / --- / Show Categories /
        #   Grid View / List View
        # The .ui supplies action_show_cat ("Show Category View") + a
        # trailing separator at the top; drop that separator, relabel the
        # action to "Show Categories", and insert the material-source items
        # above it.
        self.view_actions = {}
        menu_view = self.ui.findChild(QtWidgets.QMenu, "menuView")
        if menu_view is not None:
            for a in list(menu_view.actions()):
                if a.isSeparator():
                    menu_view.removeAction(a)
            anchor = self.action_catview        # = action_show_cat
            self.action_catview.setText("Show Categories")
            # Render "Show Categories" with a radio-style CIRCLE indicator
            # to match the other View items, not a checkmark. A
            # standalone checkable action draws a checkmark; an action in
            # an exclusive group draws a circle. ExclusiveOptional keeps it
            # a free on/off toggle (a lone member can be unchecked) while
            # still rendering as a circle.
            self.show_cat_group = QtGui.QActionGroup(self)
            self.show_cat_group.setExclusionPolicy(
                QtGui.QActionGroup.ExclusionPolicy.ExclusiveOptional
            )
            self.show_cat_group.addAction(self.action_catview)

            # Material Library (the local library) and each online source
            # form ONE exclusive group - exactly one is active, so picking
            # a source unchecks Material Library and vice versa. Material
            # Library is the default (local view). Browsing online is a
            # VIEW MODE over the Materials tab, which is why it lives in the
            # View menu rather than the Renderer menu.
            self.online_source_group = QtGui.QActionGroup(self)
            self.online_source_group.setExclusive(True)
            self.action_material_library = QtGui.QAction(
                "Material Library", self
            )
            self.action_material_library.setCheckable(True)
            self.action_material_library.setChecked(True)
            self.online_source_group.addAction(self.action_material_library)
            # NOT IN THE MENU. Its one job was leaving the online
            # browser, and the toolbar's Online button does that now.
            # The action itself stays: it is what _on_online_source
            # recognises as "the local library", and it is the group's
            # default checked member.

            # "Import Materials": the online SOURCES (view modes over
            # the Materials tab) first, then - below a divider - the
            # one-shot importers that pull materials in from elsewhere.
            # NO SUBMENU. Two entries do not earn one, now that the
            # sources have left for the tab strip - they are added
            # straight to the View menu below.
            self.online_menu = menu_view
            # THE SOURCES ARE NOT IN THIS MENU. They are the online
            # world's tab strip now, reached by the toolbar button, so
            # a menu row for each would be a second way to the same
            # place. What stays here is the one-shot importers below.
            #
            # The dict stays and stays EMPTY: open_online_source looks
            # a name up in it to tick the matching row, and an empty
            # dict answers "no row to tick" without a special case.
            self.online_source_actions = {}
            self.action_gallery_import = self.online_menu.addAction(
                "Gallery Import (.gal)"
            )
            self.action_gallery_import.triggered.connect(
                self.import_galleries
            )
            # Generating is a third way to get a material into the
            # scene, next to browsing online sources and importing a
            # gallery - its own group below them.
            self.online_menu.addSeparator()
            self.action_generate_material = self.online_menu.addAction(
                "Generate Material"
            )
            self.action_generate_material.triggered.connect(
                self.generate_random_material
            )
            # OUT OF THE MENU. "Show Categories" is a toolbar button
            # now, so the menu entry would be a second control for one
            # preference. The ACTION stays - it owns the behaviour and
            # the button drives it - only its menu row goes.
            menu_view.removeAction(self.action_catview)
            self.online_source_group.triggered.connect(self._on_online_source)

            # NO Grid / List ROWS. The toolbar's grid-list chip is the
            # control, and a menu pair beside it is a second way to one
            # preference - the same duplication Show Categories and the
            # online sources were just taken out of.
            #
            # view_actions stays and stays EMPTY: _sync_view_mode_controls
            # pushes the current mode into whatever is in it, so an empty
            # dict is "nothing else to keep in step" without a branch.

    def _build_view_toggles(self) -> None:
        """The favorites chip and the grid/list toggle.

        Split out of init_ui, which built the whole panel in one
        800-line method. Called from init_ui in the same order it
        ran in - no local variable crosses this boundary.
        """
        self.cb_favsonly = ui_helpers.ChipToggleButton()
        self.cb_favsonly.setObjectName("cb_favsonly")
        self.cb_favsonly.setToolTip(ui_helpers.tooltip_text(
            "Show favorites."))
        try:
            # The amber fill IS the on/off signal here, so hover must
            # not whiten it - the two states would be
            # indistinguishable mid-hover. That is what
            # lighten_on_hover=False means.
            self.cb_favsonly.set_art(
                self._ui_icon_path("star.svg"),
                self._ui_icon_path("star_on.svg"),
                lighten_on_hover=False,
            )
        except (TypeError, AttributeError):
            pass
        self.cb_favsonly.toggled.connect(self.filter_favs)
        if self.toolbar_layout is not None:
            self.toolbar_layout.addWidget(self.cb_favsonly)
            # Tight 2px gaps through the right-hand icon cluster - the
            # design's ~21px rendered icon-to-icon spacing is mostly
            # provided by each button's own internal padding already.
            self.toolbar_layout.addSpacing(theme.ui_px(2))

        # Grid/List view-mode toggle: same hand-painted ChipToggleButton
        # treatment as the star. Unchecked = grid (icon mode), checked =
        # list mode; the icon shows the CURRENT mode, both hover
        # variants whiten to the shared light color.
        self.ui.cb_ViewMode.setVisible(False)  # type: ignore
        self.cb_viewmode = ui_helpers.ChipToggleButton()
        self.cb_viewmode.setObjectName("cb_viewmode")
        self.cb_viewmode.setToolTip(ui_helpers.tooltip_text(
            "Switch between the thumbnail grid and the detail list."))
        try:
            # Grid and list are different SHAPES, so lightening on
            # hover cannot be mistaken for a change of state.
            self.cb_viewmode.set_art(
                self._ui_icon_path("grid.svg"),
                self._ui_icon_path("list.svg"),
            )
        except (TypeError, AttributeError):
            pass

    def _build_splitter_and_sidebar(self) -> None:
        """The splitter proportions and the category sidebar's palette.

        Split out of init_ui; no local crosses this boundary.
        """
        # Per-section view memory: sidebar choice + grid scroll,
        # captured on every tab switch so returning to a section lands
        # exactly where it was left (losing your place in a big
        # database and having to find the material again on every
        # switch is very annoying). In-memory only - Textures
        # additionally persist their folder across sessions via prefs,
        # which stays as is.
        self._section_view_state = {}
        splitter = self.cat_list.parentWidget()
        cat_index = -1
        if isinstance(splitter, QtWidgets.QSplitter):
            cat_index = splitter.indexOf(self.cat_list)
            # The Notes panel docks as the splitter's rightmost pane
            # (the 2026-08-01 design): sidebar | grid | notes. Hidden
            # until its toolbar button shows it; visibility persists.
            self.notes_panel = notes_panel.NotesPanel(self.prefs)
            splitter.addWidget(self.notes_panel)
            self.notes_panel.adopt_look(self.cat_list)
            splitter.splitterMoved.connect(self._on_splitter_moved)
            self.notes_panel.changed.connect(self._on_note_saved)
            self.notes_panel.setVisible(bool(self.prefs.show_notes))
            self.notes_panel.set_note_accent(theme.color_hex("star"))
            # Width set explicitly, painting left fully native otherwise
            # (no color, no hand-painted grip dots/hover). A prior round
            # tried a full custom paint (color + hand-painted grip dots +
            # hover) via an event filter, which strayed too far from
            # Houdini's own native look (read as too hand-painted) -
            # reverted that entirely, keeping only the explicit width
            # from before that revert (6, matching what was actually in
            # code at the time). setHandleWidth() alone doesn't touch
            # how the handle is painted, just how much room native
            # painting has to work with, so this keeps the native grip
            # dots/hover intact.
            splitter.setHandleWidth(theme.ui_px(6))
        # catview's own <maximumSize width="220"> in amaze.ui is what
        # kept the category pane narrow in the splitter - that property
        # stays on catview itself after reparenting below, but the
        # splitter now sees cat_wrapper (unconstrained by default) as its
        # pane widget, not catview, so it no longer has any width limit
        # to respect. An earlier attempt at this fix tried to capture and
        # reapply splitter.sizes() around the reparent instead - that
        # backfired badly (a capture taken before the panel is ever shown
        # can be [0, 0, 0], not real pixel widths, and reapplying it
        # collapsed the grid pane to nothing) and has been dropped in
        # favor of just propagating the same real constraint catview
        # already had.
        # The sidebar OWNS its width like the notes pane does (the
        # remembered drag, or the 220 design width) - before HeldPane
        # it asked the splitter for nothing and launched at whatever
        # cat_list's bare hint happened to be.
        self.cat_wrapper = ui_helpers.HeldPane(
            self.prefs, "sidebar_width", theme.ui_px(220))
        self.cat_wrapper.setMaximumWidth(theme.ui_px(220))
        # catview carries its own maximumSize width=220 in amaze.ui.
        # At UI scale 1.0 that matches the wrapper cap exactly, but on a
        # scaled display (Windows/Linux) the wrapper grows while the
        # list inside stays 220, leaving a dead band of wrapper backdrop
        # between the list and the grid (first seen on Windows at 1.5x).
        # Runtime override, .ui untouched - the standing practice.
        self.cat_list.setMaximumWidth(theme.ui_px(220))
        # Backdrop fill for the whole category section (tab row's own
        # margins, any space the list doesn't cover) - deliberately
        # darker than BG1 (#2d2d2d, still on cat_list/line_tags) so the
        # section reads as one frame with the list as a distinct surface
        # inside it. Set via QPalette, not setStyleSheet()/WA_StyledBackground
        # - a stylesheet on this ancestor would push cat_list onto Qt's CSS
        # rendering path for parts it doesn't style itself (its scrollbar),
        # knocking it off Houdini's native look, the same class of bug
        # documented elsewhere in this file for the details panel. Palette
        # changes don't cascade that way.
        self.cat_wrapper.setAutoFillBackground(True)
        cat_wrapper_palette = self.cat_wrapper.palette()
        cat_wrapper_palette.setColor(QtGui.QPalette.ColorRole.Window, theme.color("surface_low"))
        self.cat_wrapper.setPalette(cat_wrapper_palette)
        cat_wrapper_layout = QtWidgets.QVBoxLayout(self.cat_wrapper)
        cat_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        cat_wrapper_layout.setSpacing(0)

        cat_wrapper_layout.addWidget(self.cat_list)
        if splitter is not None and cat_index >= 0:
            splitter.insertWidget(cat_index, self.cat_wrapper)
            # ONE construction for the three panes (the 2026-08-01
            # unification): the sidebar and the notes pane HOLD their
            # width, the grid is the splitter's only flexible pane -
            # so every redistribution Qt performs (the notes toggle's
            # tax and refund, window resizes) lands on the grid alone.
            # Probed: stretch 0/1/0 leaves the sidebar untouched
            # through hide/show/resize, and Qt reopens the notes pane
            # at its last width from the grid by itself. This replaces
            # a hand-rolled capture-and-restore of the sidebar width,
            # which fought the same redistribution it should have
            # turned off.
            held = (self.cat_wrapper, getattr(self, "notes_panel", None))
            for i in range(splitter.count()):
                flexible = splitter.widget(i) not in held
                splitter.setStretchFactor(i, 1 if flexible else 0)

    def _build_sidebar_palette(self) -> None:
        """The category list's palette and selection colours.

        Split out of init_ui; no local crosses this boundary.
        """
        # Category UI
        self.cat_list = self.ui.catview  # type: ignore
        # Palette, not setStyleSheet() - a stylesheet on cat_list itself
        # (not just an ancestor) also pushes Qt onto the CSS rendering
        # path for parts this stylesheet doesn't cover, namely its own
        # scrollbar, which is the most likely reason its scrollbar still
        # doesn't match the grid's (thumbview never got a stylesheet at
        # all) even after moving the *ancestor* (cat_wrapper) background
        # to a palette. QListView paints its viewport from Base/Text.
        cat_list_palette = self.cat_list.palette()
        cat_list_palette.setColor(
            QtGui.QPalette.ColorRole.Base, theme.color("surface_low")
        )
        cat_list_palette.setColor(
            QtGui.QPalette.ColorRole.Text, AssetItemDelegate.TEXT_COLOR
        )
        # NO SELECTION COLOURS HERE (2026-08-04). The sidebar wears
        # Houdini's own, the same as the Grid table: this panel applies
        # `hou.qt.styleSheet()` to its root and every child inherits
        # it, so `QAbstractItemView::item:selected` already paints the
        # band and answers `HighlightedText` for the ink. Setting
        # Highlight and HighlightedText here bought nothing - the sheet
        # outranks a palette at paint time, which is exactly why
        # `SidebarItemDelegate` had grown a hand-painted band on top.
        self.cat_list.setPalette(cat_list_palette)
        # It paints the NAME, the count and the colour bar; the cell
        # under them - band, hover, alternating colour - is the style's
        # (see SidebarItemDelegate's docstring).
        self.sidebar_delegate = SidebarItemDelegate(self.cat_list)
        # Only the ASSET sidebars carry colours; the folder and palette
        # sidebars answer nothing for this role, so the bar never draws
        # there without needing a second delegate.
        self.sidebar_delegate.color_role = category.SIDEBAR_COLOR_ROLE

    def init_ui(self) -> None:
        """Creates the panel-view on load"""
        # Load UI from ui.file
        loader = QtUiTools.QUiLoader()
        file = QtCore.QFile(self.script_path + "/ui/amaze.ui")
        # Override Widgets for Drag and Drop Support
        loader.registerCustomWidget(dragdrop_widgets.DragDropCentralWidget)
        loader.registerCustomWidget(dragdrop_widgets.DragDropListView)

        file.open(QtCore.QFile.ReadOnly)  # type: ignore
        self.ui = loader.load(file)
        file.close()

        # Apply Houdini's own Qt stylesheet so standard widgets (combo
        # boxes, scrollbars, etc.) render like native Houdini UI instead
        # of the OS-default Qt style. hou.qt.styleSheet() is SideFX's
        # documented mechanism for this in custom PySide panels. The
        # toolbar's own controls are all hand-painted widgets and ignore
        # it entirely.
        try:
            self.ui.setStyleSheet(hou.qt.styleSheet())
        except AttributeError:
            pass
        # A WIDTH FLOOR, AND ONLY WIDTH. This used to drop the .ui's
        # 420x400 minimum entirely so the pane could shrink to nothing
        # and clip like Houdini's own panes; measured live, that left
        # the grid viewport 48px wide, narrower than one tile. Height
        # stays free, because a short grid reads fine (research.md >
        # WHAT A SQUEEZED PANEL ACTUALLY LEAVES THE GRID).
        self.ui.setMinimumSize(theme.ui_px(MIN_PANEL_WIDTH), 0)
        # Vertical stays Ignored so the pane still shrinks and clips
        # downward like its neighbours; horizontal must be able to
        # honour the minimum, and Ignored ignores it.
        self.ui.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Minimum,
            QtWidgets.QSizePolicy.Policy.Ignored,
        )

        # Match Houdini's UI font and track the user's Global UI Size
        # preference. THE FLOOR IS THEME'S, not this method's: it used to
        # be a bare 12.0 here while the tile sub-line carried a second,
        # independent floor of its own, and two floors that agree only
        # where the view inherits this font is the whole Windows defect.
        # One rule, one place - and scaled, the way the host scales its
        # own chrome (helpers/theme.py ▸ THE ONE FONT TABLE).
        #
        # `hou.qt` does not exist under hython, so this whole stamp is a
        # GUI-session thing; the except is what makes the headless suite
        # possible at all.
        try:
            self.ui.setFont(theme.ui_font(hou.qt.mainWindow().font()))
        except AttributeError:
            pass

        # Load Ui Element so self
        self.menu = self.ui.findChild(QtWidgets.QMenuBar, "menubar")
        # No background/border styling here: the real menu bar is
        # permanently hidden further down (self.menu.setVisible(False)),
        # once its items move into the merged toolbar row - a stylesheet
        # on a hidden widget has no visual effect at all, so one was
        # never worth keeping around once that move happened.
        self.action_prefs = self.ui.action_prefs  # type: ignore
        self.action_prefs.triggered.connect(self.show_prefs)

        self.action_catview = self.ui.action_show_cat  # type: ignore
        self.action_catview.triggered.connect(self.toggle_catview)

        # Details is a dialog now (Edit Info); the old docked-panel
        # View-menu toggle (action_show_details) was removed from the
        # .ui in the 2026-07-21 Designer clean-up.
        self.action_cleanup_db = self.ui.action_cleanup_db  # type: ignore
        self.action_cleanup_db.triggered.connect(self.cleanup_db)

        self.action_open_folder = self.ui.action_open_folder  # type: ignore
        self.action_open_folder.triggered.connect(self.open_usdlib_folder)

        self.action_open = self.ui.action_open  # type: ignore
        self.action_open.triggered.connect(self.open)

        self.action_set_library = self.ui.action_set_library  # type: ignore
        self.action_set_library.triggered.connect(self.set_library)

        # MatLib v1 import dropped entirely; its action_import_lib_v1 was
        # removed from the .ui in the 2026-07-21 Designer clean-up.

        # Overwrite the widgets for Drag and Drop in dragdrop_widgets.py
        self.centralwidget = self.ui.centralwidget  # type: ignore

        # An ATTRIBUTE, not a local: everything in the panel's middle
        # section is built into this layout, so as a local it pinned
        # ~280 lines of init_ui together and nothing in that stretch
        # could be split out. As an attribute the same code cuts into
        # builders freely (largest block 278 -> 62 lines).
        #
        # It is the attribute the panel ALREADY had - the section-tab
        # insert (see _rebuild_section_tabs) has always used
        # self._central_layout. Promoting the local under a second
        # name would have left two attributes pointing at one layout.
        self._central_layout = self.centralwidget.layout()
        self.toolbar_layout = None
        if self._central_layout is not None:
            # Merge the menu bar and the filter row into one strip
            # (reference: Houdini's own pane toolbars put menu
            # items and icon controls on a single row, not stacked).
            # QMainWindow reserves a dedicated dock area for its menu bar
            # that can't share a row with arbitrary other widgets, so the
            # real QMenuBar (self.menu) is hidden - its QMenus/QActions
            # stay alive and fully wired, just opened from flat buttons
            # instead (see _make_menu_button). horizontalLayout (the old
            # filter row) is a bare nested <layout> with no widget of its
            # own to paint a background on - same issue documented
            # elsewhere in this file - so its contents move into a new
            # QWidget wrapper that can be colored to match the menu bar.
            if self.menu is not None:
                self.menu.setVisible(False)
            filter_row = self.ui.findChild(QtWidgets.QHBoxLayout, "horizontalLayout")
            self.toolbar_row = QtWidgets.QWidget()
            self.toolbar_row.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_StyledBackground, True
            )
            # border: none first clears whatever Houdini's own base
            # stylesheet (applied panel-wide, self.ui.setStyleSheet(...))
            # might otherwise contribute now that WA_StyledBackground puts
            # this widget on the CSS rendering path - that's what was
            # producing a border on all sides instead of just the bottom
            # one actually being set here.
            # QSS border-width renders as literal screen pixels, not
            # scaled by the ~2x factor widget geometry (setFixedHeight
            # etc.) goes through - confirmed live: "1px" renders
            # as an actual 1px, not 2. Divider color #434343 per
            # the "ui_wireframe 2 only menu" design (was #414141).
            self.toolbar_row.setStyleSheet(
                "background-color: " + theme.color_hex("surface")
                + "; border: none;"
                + " border-bottom: 1px solid "
                + theme.color_hex("field") + ";"
            )
            # 30 code px = the design's 60px bar (down from the old 80px
            # row that MenuBarButton's height used to drive).
            self.toolbar_row.setFixedHeight(theme.ui_px(30))
            self.toolbar_layout = QtWidgets.QHBoxLayout(self.toolbar_row)
            # Design rev 2026-07-19 ("moved down 1px, spaces cleaned
            # up"): content is now dead-centered vertically (the earlier
            # rev floated everything 1-3px above center; it was nudged
            # back down), so no top/bottom bias. Right margin 2 -> the
            # design's ~12px rendered edge inset, most of which the last
            # icon button's own internal padding already provides.
            self.toolbar_layout.setContentsMargins(0, 0, theme.ui_px(2), 0)
            self.toolbar_layout.setSpacing(0)

            # No menu buttons on the left anymore - the design moves all
            # three menus (Renderer/View/Library) to the toolbar's right
            # end as icon buttons, appended at the end of setup once the
            # Renderer menu exists. The leading stretch pushes the whole
            # content cluster (Filter/slider/toggles/menus) to the right,
            # matching the design's empty left region (reserved for
            # a planned section-tab integration).
            self.toolbar_layout.addStretch()

            if filter_row is not None:
                self._central_layout.removeItem(filter_row)
            self._central_layout.insertWidget(0, self.toolbar_row)

        self.thumblist = self.ui.thumbview  # type: ignore
        # Per-PIXEL scrolling, not Qt's default per-ITEM mode - one
        # "item" is a whole tile row in grid mode, so per-item wheel
        # steps jumped enormous distances (and interacted erratically
        # with trackpad deltas: sometimes turbo, sometimes crawling).
        self.thumblist.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        # BOTH AXES. Only the vertical mode was ever set, so sideways
        # scrolling - which nothing could do until list rows became
        # wider than the panel - was still on Qt's per-ITEM default,
        # where one step is a whole row and the movement reads as
        # wildly accelerated. Same mode, same reasoning, other axis.
        self.thumblist.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        # Every row/tile has the same geometry, so Qt can lay out by
        # arithmetic instead of asking the delegate per item - a real
        # saving at 500+ materials, and it keeps list rows uniform
        # while the viewport resizes.
        self.thumblist.setUniformItemSizes(True)
        # SINGLE-PASS layout, overriding the .ui's Batched: a batched
        # layout publishes a scrollbar range covering only the batches
        # laid out so far (batchSize 100), so any repaint that restarts
        # the layout - a thumbnail arriving mid-scroll - collapses the
        # range to ~100 rows and then snaps it back. Live that reads as
        # a flickering list that never scrolls to the end; measured in
        # the debug log as range_max alternating 16062 <-> 2772 on a
        # 543-row library. Uniform item sizes make single-pass cheap:
        # positions are arithmetic, not per-item queries.
        self.thumblist.setLayoutMode(
            QtWidgets.QListView.LayoutMode.SinglePass
        )
        # Three .ui leftovers from upstream, wrong for a view that is
        # a pure drag SOURCE of a fixed grid (overridden here rather
        # than in the .ui, which is the Designer source):
        #  * AdjustToContents makes the scroll area's size HINT follow
        #    its content, so the grid renegotiates space with its
        #    neighbours whenever the content geometry changes - a grid
        #    that nudges itself is never what a browser wants.
        #  * Snap movement treats tiles as individually placed items
        #    that re-snap to the grid on interaction; the tiles here are
        #    laid out by the view and never rearranged by the user, and
        #    Static is also the mode where uniform-size arithmetic
        #    layout applies.
        #  * DragDrop/dragDropOverwriteMode on a view with
        #    acceptDrops=false: it only ever drags OUT (to Houdini's
        #    network and viewports), so DragOnly states that exactly.
        self.thumblist.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self.thumblist.setMovement(QtWidgets.QListView.Movement.Static)
        self.thumblist.setDragDropMode(
            QtWidgets.QAbstractItemView.DragDropMode.DragOnly
        )
        self.thumblist.setDragDropOverwriteMode(False)
        # Selecting a tile must never move the grid: Qt's autoScroll
        # re-scrolls on EVERY currentChanged - a click on a half-cut
        # tile included, which read as the grid jumping under the
        # cursor. Off is off for keyboard navigation too, deliberately:
        # the grid is a mouse surface. Explicit calls (scrollToTop on
        # section switch) are not gated by this property.
        self.thumblist.setAutoScroll(False)

        # List rows span the viewport, so they must re-fit when it
        # resizes; the versions badge lights under the cursor, which
        # needs button-free mouse moves - a viewport does NOT track
        # the mouse by default (measured). Both live in eventFilter.
        self.thumblist.viewport().setMouseTracking(True)
        self.thumblist.viewport().installEventFilter(self)
        self.thumblist.doubleClicked.connect(self.import_asset_auto)
        # update_details_view is NOT connected here: the material
        # selection model's selectionChanged already fires for every
        # click that changes what is selected, and a click that changes
        # nothing leaves the details already correct. Wired to both,
        # every click rebuilt the form twice - six role reads per
        # selected asset each time, so select-all-then-click paid it
        # over the whole library. Refresh-after-edit has its own
        # explicit calls (edit_material_info, user_update_asset).
        # _refresh_notes_subject stays: it is idempotent (set_subject
        # returns immediately when the key has not changed).
        self.thumblist.clicked.connect(self._refresh_notes_subject)
        # Grid and details panel had two different, unstyled/native
        # backgrounds - unified to #313131 via QPalette (Base role, same
        # role QListView paints its viewport from) rather than
        # setStyleSheet(), consistent with the cat_list fix above.
        thumblist_palette = self.thumblist.palette()
        thumblist_palette.setColor(QtGui.QPalette.ColorRole.Base, theme.color("surface_high"))
        self.thumblist.setPalette(thumblist_palette)

        # v2: thin progress bar for texture thumbnail generation, docked
        # above thumbview in its own layout (verticalLayout_7 in amaze.ui
        # wraps only thumbview, isolated from catview/details in the
        # splitter) - added in code, not the .ui file, same as the other
        # v2 widgets. Hidden until a folder with actual work to do is
        # selected; see _on_texture_progress().
        self.texture_progress = ui_helpers.ThinProgressBar()
        self.texture_progress.set_accent_color(theme.accent(self.prefs.accent_color))
        self.texture_progress.setVisible(False)
        thumb_layout = self.ui.findChild(QtWidgets.QVBoxLayout, "verticalLayout_7")
        if thumb_layout is not None:
            thumb_layout.insertWidget(0, self.texture_progress)

        # LIST MODE AS A REAL TABLE (step 2 of the QTableView
        # migration). A second VIEW, not a second area: it shares the
        # model, the proxy and the SELECTION MODEL with the grid, so
        # selecting in one is selecting in the other and every area
        # binding stays single. Only one is ever visible.
        self.thumbtable = dragdrop_widgets.DragDropTableView()
        self.thumbtable.setObjectName("thumbtable")
        # The header goes in BEFORE it is styled: `_style_table_header`
        # sets the sort indicator, and this is the header that decides
        # what the indicator costs the columns that do not have it.
        self.thumbtable.setHorizontalHeader(
            ui_helpers.GridHeaderView(
                QtCore.Qt.Orientation.Horizontal, self.thumbtable))
        self.thumbtable.setVisible(False)
        if thumb_layout is not None:
            thumb_layout.addWidget(self.thumbtable)
        self._style_table_header()
        # The table IS the grid while list mode shows: same menu, same
        # primary action. thumblist takes its CustomContextMenu policy
        # from the .ui; this view is built in code, so it takes both
        # wirings here - without them right-click and double-click are
        # dead in one of the two view modes.
        self.thumbtable.setContextMenuPolicy(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbtable.customContextMenuRequested.connect(
            self.thumblist_rc_menu)
        self.thumbtable.doubleClicked.connect(self.import_asset_auto)
        # NO SCROLL-OFFSET WIRING. The painted strip sat ABOVE the view
        # and had to be told when the rows scrolled sideways, or its
        # labels named whichever column had slid underneath them. A
        # QHeaderView IS the view's header and scrolls with it.

        self._build_sidebar_palette()
        self.sidebar_delegate.set_drag_color(
            theme.accent(self.prefs.accent_color)
        )
        self.cat_list.setItemDelegate(self.sidebar_delegate)
        self.cat_list.clicked.connect(self.update_selected_cat)
        # Make the sidebar a real DROP TARGET: drag assets from the grid
        # onto a category to recategorise them. The filter also
        # keeps such a drop from falling through to the central widget's
        # save-node handler ("... already exists in the library").
        self._cat_drop_filter = dragdrop_widgets.CategoryDropFilter(
            self.cat_list, self
        )

        self.line_filter = self.ui.line_filter  # type: ignore
        self.line_filter.textEdited.connect(self.filter_thumb_view)
        # The box is EMPTY by decree (2026-08-01): the "Search" label
        # and the magnifier already name the control, and the per-
        # section placeholder texts were noise beside them. The
        # search_hint machinery stays (a section may one day need a
        # word again), but every hint is "" and the box's tooltip is
        # where :tag gets taught. The .ui file is maintained externally
        # in Qt Designer and is never edited from code.
        self.line_filter.setPlaceholderText(sections.Section.search_hint)
        self.line_filter.setToolTip(ui_helpers.tooltip_text(
            "Search for objects, a leading colon searches tags "
            "instead: :metal finds everything tagged metal."))
        # Per the "ui_wireframe 2 only menu" design: borderless box,
        # #434343 fill, magnifier icon inside the left edge. Stylesheet
        # set directly on the widget itself, not an ancestor (same "avoid
        # the details-panel regression class of bug" reasoning used
        # everywhere else in this file). padding-left reserves room so
        # typed text doesn't start underneath the icon.
        self.line_filter.setStyleSheet(
            "QLineEdit { border: none; background-color: "
            + theme.color_hex("field")
            + "; padding-left: %dpx; }" % theme.ui_px(20)
        )
        # 20 code px = the design's 40px rendered box. The old height was
        # 22 to compensate for a 1px QSS border eating into the fill
        # (rendered = (code - 2) * 2, see git history) - borderless now,
        # so the plain 2x relationship applies again.
        self.line_filter.setFixedHeight(theme.ui_px(20))
        # Sizing rule: 300px rendered max, 75px min (the .ui's
        # own 80 minimum is overridden here - setMinimumWidth wins over
        # the .ui value at runtime).
        self.line_filter.setMinimumWidth(theme.ui_px(38))
        # Max raised 150 -> 200 (300R -> 400R),
        # together with the slider's.
        self.line_filter.setMaximumWidth(theme.ui_px(200))
        # Magnifier icon (replaces the old funnel) pinned to the LEFT
        # edge - a real overlay QLabel + SideIconPinner (ui_helpers.py),
        # not a QLineEdit addAction() icon, since that API doesn't expose
        # control over the exact margin and this project has consistently
        # favored precise hand-positioning over accepting Qt's own
        # default spacing wherever an exact pixel value was asked for.
        try:
            filter_icon_path = self._ui_icon_path("icon_search.svg")
            if filter_icon_path and os.path.exists(filter_icon_path):
                # Design: ~25px rendered magnifier, ~9px in from the box
                # edge -> 13 code px icon at a 4px pin margin.
                icon_size = theme.ui_px(13)
                # render_svg_pixmap = QSvgRenderer straight onto a
                # transparent pixmap; QIcon's own SVG engine produced an
                # opaque black background here (see git history).
                pixmap = ui_helpers.render_svg_pixmap(
                    filter_icon_path, icon_size
                )
                self.filter_icon_label = QtWidgets.QLabel(self.line_filter)
                self.filter_icon_label.setPixmap(pixmap)
                self.filter_icon_label.resize(icon_size, icon_size)
                self.filter_icon_label.setAttribute(
                    QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
                )
                # The dark square was the label WIDGET's own background,
                # not the pixmap's alpha (the QSvgRenderer switch fixed
                # the pixmap; a clean, label-sized square pointed
                # elsewhere) - almost certainly Houdini's panel-wide
                # stylesheet (self.ui.setStyleSheet(hou.qt.styleSheet()))
                # defining a default QLabel background that this label
                # inherited since nothing had told it not to. Both belt
                # and suspenders here since it's cheap: the attribute
                # stops Qt from auto-filling the widget's background, the
                # stylesheet explicitly overrides whatever panel-wide rule
                # would otherwise apply to a plain QLabel.
                self.filter_icon_label.setAttribute(
                    QtCore.Qt.WidgetAttribute.WA_TranslucentBackground
                )
                self.filter_icon_label.setStyleSheet("background: transparent;")
                self._filter_icon_pinner = ui_helpers.SideIconPinner(
                    self.line_filter, self.filter_icon_label,
                    theme.ui_px(4), side="left"
                )
        except (TypeError, AttributeError):
            pass
        if self.toolbar_layout is not None:
            # "Search" label (was "Filter" until 2026-08-01 - the box
            # searches, so the label says so) to the left of the box -
            # a real QLabel, not placeholder text inside line_filter
            # itself. Font stays the panel-wide Houdini font stamp.
            self.filter_label = QtWidgets.QLabel("Search")
            self.filter_label.setObjectName("filter_label")
            self.filter_label.setStyleSheet(
                "color: " + theme.color_hex("text_bright") + ";"
            )
            self.toolbar_layout.addWidget(self.filter_label)
            self.toolbar_layout.addSpacing(theme.ui_px(12))
            self.toolbar_layout.addWidget(self.line_filter)
            # The size slider is built much later in this method but sits
            # between the box and the star in the design - remember this
            # spot so its block can insert itself here.
            self._after_filter_index = self.toolbar_layout.count()

        # v2: section tabs - restructured 2026-07-19 per the
        # "ui_wireframe 2 only menu" design: a full-width strip BELOW
        # the toolbar (no longer inside the category sidebar), holding a
        # rounded-top tray of full-word text tabs (Materials / Textures
        # / Colors / Cop / Geometry). Hand-built (SectionTabBar in
        # ui_helpers.py) for the same reasons as its SegmentedControl
        # predecessor. Only Materials/Textures/Colors have real content
        # behind them so far; see _on_tab_toggled. catview has no
        # wrapper of its own in amaze.ui (it's a direct QSplitter
        # pane), so it's reparented into a new wrapper widget, then that
        # wrapper takes catview's old place in the splitter.
        self.current_section = "material"
        self._build_splitter_and_sidebar()

        # The tab strip itself lives OUTSIDE the sidebar now: full panel
        # width, directly under the toolbar row (self._central_layout index 1,
        # toolbar_row sits at 0). Tab order, labels and chip styling per
        # the design; "Colors" is the Gradients section's user-facing
        # name (internal key stays "gradient"), Cop and Geometry are
        # placeholders. Chip colors are fixed design constants, not
        # accent-derived, so there's no set_accent_color here.
        self.section_tabs = None
        # Built from the enabled_sections pref (rebuildable when that
        # pref changes in Preferences) - see _build_section_tabs.
        self._build_section_tabs()

        # Favorites toggle: hand-painted ChipToggleButton with the exact
        # same grey hover chip and icon-whitening as the icon menu
        # buttons (hover must match across favorites/grid-list/
        # menus). The .ui's own cb_FavsOnly is unused and hidden - left
        # unparented it could paint stray in the panel.
        self.ui.cb_FavsOnly.setVisible(False)  # type: ignore
        self._build_view_toggles()
        self.cb_viewmode.toggled.connect(self.on_viewmode_button)
        if self.toolbar_layout is not None:
            self.toolbar_layout.addWidget(self.cb_viewmode)
            # Fixed gap to the icon-menu cluster appended right after -
            # the design right-anchors everything from the star outward.
            self.toolbar_layout.addSpacing(theme.ui_px(2))

        # Updated Details UI
        self.details = self.ui.details_widget  # type: ignore
        # Match the grid's #313131 (see thumblist above). QPalette +
        # setAutoFillBackground(), not setStyleSheet() - a stylesheet
        # here previously knocked the Name/Category/Tags fields off
        # their own native box rendering entirely (see the "details-panel
        # color pass" entry earlier in this file); palette changes don't
        # cascade onto descendants the way a stylesheet does.
        self.details.setAutoFillBackground(True)
        details_palette = self.details.palette()
        details_palette.setColor(QtGui.QPalette.ColorRole.Window, theme.color("surface_high"))
        self.details.setPalette(details_palette)
        self.line_name = self.ui.line_name  # type: ignore
        self.line_cat = self.ui.line_cat  # type: ignore

        # Every asset has exactly ONE category now - the multi-category
        # feature was removed (a hazard that made sorting harder).
        # The single-category dropdown is the only category input; the old
        # "Multi-category material" tick box and its comma-separated
        # textbox are hidden (kept in the .ui, never shown).
        self.cat_combo = self.ui.cat_combo  # type: ignore
        self.box_multicat = self.ui.box_multicat  # type: ignore
        self.cat_combo.setEnabled(True)
        try:
            form = self.ui.findChild(  # type: ignore
                QtWidgets.QFormLayout, "details_form"
            )
            if form is not None:
                form.setRowVisible(self.box_multicat, False)
                form.setRowVisible(self.line_cat, False)
        except Exception:
            self.box_multicat.setVisible(False)
            self.line_cat.setVisible(False)

        self.line_tags = self.ui.line_tags  # type: ignore
        self.line_tags.setStyleSheet(
            "background-color: " + theme.color_hex("surface") + ";"
        )
        self.line_id = self.ui.line_id  # type: ignore
        self.line_id.setDisabled(True)
        self.line_id.setStyleSheet(
            "QLineEdit:disabled { background-color: #333333; }"
        )

        self.line_date = self.ui.line_date  # type: ignore
        self.line_date.setDisabled(True)
        self.line_date.setStyleSheet(
            "QLineEdit:disabled { background-color: #333333; }"
        )

        # Greyed renderer row inserted directly under Name (e.g. "USD
        # Redshift" / "Redshift" / "Karma"). Inserted in code so we don't have
        # to renumber the whole form; disabled so it reads as metadata.
        self.line_renderer = QtWidgets.QLineEdit()
        self.line_renderer.setReadOnly(True)
        self.line_renderer.setDisabled(True)
        self.line_renderer.setStyleSheet(
            "QLineEdit:disabled { background-color: #333333; }"
        )
        # Provenance rows for downloaded online materials (empty for local
        # ones): the License in its own field, and a multi-line About /
        # credit block at the very bottom to pay homage to the creators
        # (source, author, link). Both editable, saved with the rest of
        # the Material Info form.
        self.line_license = QtWidgets.QLineEdit()
        self.text_about = QtWidgets.QPlainTextEdit()
        self.text_about.setFixedHeight(theme.ui_px(84))   # ~4 lines
        try:
            details_form = self.ui.findChild(  # type: ignore
                QtWidgets.QFormLayout, "details_form"
            )
            name_row, _ = details_form.getWidgetPosition(self.line_name)
            details_form.insertRow(name_row + 1, "Type", self.line_renderer)
            # Appended, so they sit at the bottom of the form.
            details_form.addRow("License", self.line_license)
            details_form.addRow("About", self.text_about)
        except Exception:
            pass

        self.box_fav = self.ui.cb_set_fav  # type: ignore
        self.box_fav.clicked.connect(self.box_fav_clicktoggle)

        self.btn_update = self.ui.btn_update  # type: ignore
        # The .ui text "Update Material" now collides with the real
        # content-update in the save flow - this button only saves
        # name/category/tags/favorite. Property change at runtime, not a
        # .ui edit (standing practice).
        self.btn_update.setText("Update Info")
        self.btn_update.clicked.connect(self.user_update_asset)

        # Material metadata now lives in a FLOATING DIALOG, not a docked
        # panel (the panel ate grid width and only materials
        # used it). Reparenting details_widget into a QDialog removes it
        # from the splitter, so the grid gets the freed space; the edit
        # form (update_details_view / user_update_asset) is unchanged.
        self.details_dialog = QtWidgets.QDialog(self)
        self.details_dialog.setWindowTitle("Material Info")
        _dlg_layout = QtWidgets.QVBoxLayout(self.details_dialog)
        _m = theme.ui_px(8)
        _dlg_layout.setContentsMargins(_m, _m, _m, _m)
        _dlg_layout.addWidget(self.details)  # reparents out of the splitter
        self.details.setVisible(True)
        self.details.setMinimumWidth(theme.ui_px(360))

        # The Filter menu lives in the hidden menubar and is opened from
        # a toolbar button (moved out of the details view). It held the
        # renderers alone until 2026-08-02; every section fills it with
        # its own entries now, from panel/sections.py.
        self.menu_filter = QtWidgets.QMenu("Filter", self.menu)
        self._build_menus()

        # The .ui's original icon-size slider is superseded by ClickSlider
        # below; keep it hidden rather than removing it from the .ui file
        # (the .ui file is maintained externally in Qt Designer, and
        # edited versions of it are sometimes handed over).
        self.ui.slide_iconSize.setVisible(False)  # type: ignore

        # Set Up Clickable Slider
        self.click_slider = ui_helpers.ClickSlider()
        # No tooltip here: _sync_slider_for_mode() owns it, because the
        # text differs by view mode (grid says "Tile size.", list
        # explains why it is greyed). A construction-time one is dead
        # the moment apply_view_mode runs - and the one that used to
        # sit here said "independent for grid and list", contradicting
        # the mode-aware text that overwrote it.
        self.click_slider.setObjectName("click_slider")
        self.click_slider.setOrientation(QtCore.Qt.Horizontal)  # type: ignore
        # 64 is the floor (2026-08-01): below it a grid tile is
        # smaller than the badges it carries. LIST does not use
        # this range at all - it sits at LIST_THUMB_SIZE with the
        # slider disabled, because a list row is a text line.
        self.click_slider.setRange(64, 512)
        self.click_slider.setValue(ui_helpers.ClickSlider.DEFAULT_VALUE)
        self.click_slider.setSingleStep(50)
        self.click_slider.setPageStep(50)
        self.click_slider.set_accent_color(theme.accent(self.prefs.accent_color))
        # Sizing rule, same as the filter box: 400px rendered
        # max (raised from 300), 75px min.
        self.click_slider.setMinimumWidth(theme.ui_px(38))
        self._build_slider_and_layout()

    def _mirror_toolbar(self) -> None:
        """TEST: mirror the toolbar row - every
        item flows from the LEFT edge in the reverse of the designed
        order (Library/View/Renderer icons first, then grid-list toggle,
        star, slider, filter box, "Filter" label, with the stretch
        landing at the far right). The layout is still BUILT in its
        designed right-aligned order everywhere above, then reversed
        here in one pass - so ending the test is just deleting this
        method and its call, nothing else moves."""
        if self.toolbar_layout is None:
            return
        items = []
        while self.toolbar_layout.count():
            items.append(self.toolbar_layout.takeAt(0))
        for item in reversed(items):
            self.toolbar_layout.addItem(item)
        # Exception to the literal mirror: the "Filter" label
        # still reads left-to-right, so it stays on the LEFT of its box.
        # A plain reversal lands it on the box's right as
        # [box][12-gap][label] - swap the label (and re-seat the gap)
        # back to [label][12-gap][box]. Strict about the expected
        # adjacency so a future construction change can't silently
        # shuffle the wrong items.
        i_box = self.toolbar_layout.indexOf(self.line_filter)
        i_label = self.toolbar_layout.indexOf(self.filter_label)
        if i_box >= 0 and i_label == i_box + 2:
            label_item = self.toolbar_layout.takeAt(i_label)
            gap_item = self.toolbar_layout.takeAt(i_label - 1)
            self.toolbar_layout.insertItem(i_box, gap_item)
            self.toolbar_layout.insertItem(i_box, label_item)
        # Second exception: the capture button is the OUTERMOST control
        # in both orders. A literal mirror makes "outermost right" into
        # "outermost left", which is where it actually landed - so it is
        # moved back to the end here, along with the 2px gap that
        # precedes it in build order and therefore follows it after the
        # reversal.
        #
        # Doing it here rather than by building it at index 0 keeps this
        # method's promise intact: the designed order above still has it
        # outermost-right, so deleting the mirror leaves it where it
        # belongs and nothing else moves.
        # Capture, then the gear, in that order - so the row ends
        # ... stretch, Capture, gear, with Capture immediately to the

        # call). The gear moved out of the cluster it used to lead.
        self._move_to_toolbar_end(getattr(self, "btn_hip_capture", None))
        self._move_to_toolbar_end(self._toolbar_widget("btn_prefs"))

        # The designed row insets its RIGHT edge by 2 (outside the
        # outermost icon button); mirrored, the icon cluster gains a
        # left edge - and with the capture button moved back to the end
        # above, BOTH edges now hold a control, so both are inset.
        self.toolbar_layout.setContentsMargins(
            theme.ui_px(2), 0, theme.ui_px(2), 0)

    def _toolbar_widget(self, name: str):
        """A toolbar item by objectName. The gear is deliberately not
        kept on self (an attribute for it once made a naming refactor
        read as a layout defect), so the row is where to look."""
        for i in range(self.toolbar_layout.count()):
            item = self.toolbar_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None and widget.objectName() == name:
                return widget
        return None

    def _move_to_toolbar_end(self, widget) -> None:
        """Move one control (and the 2px gap that travels with it) to
        the end of the mirrored row.

        The mirror reverses everything, which turns "outermost right"
        into "outermost left". Two controls need putting back, so this
        is the one routine both use rather than the second being a copy
        of the first.

        Doing it HERE rather than by building at index 0 keeps the
        mirror's promise: the designed order above still reads as the
        row does, so deleting the mirror leaves everything where it
        belongs.
        """
        if widget is None:
            return
        index = self.toolbar_layout.indexOf(widget)
        if index < 0:
            return
        item = self.toolbar_layout.takeAt(index)
        gap_item = None
        # The gap sat immediately BEFORE it in build order, so it
        # follows it after the reversal. Strict adjacency, so a
        # construction change cannot silently move the wrong item.
        if index < self.toolbar_layout.count():
            probe = self.toolbar_layout.itemAt(index)
            if probe is not None and probe.widget() is None:
                gap_item = self.toolbar_layout.takeAt(index)
        if gap_item is not None:
            self.toolbar_layout.addItem(gap_item)
        self.toolbar_layout.addItem(item)

    @staticmethod
    def _category_names_from(model) -> list[str]:
        """ALL category names from a Categories model (empty ones
        included), excluding the 'All' pseudo-category. Reads the SOURCE
        model, not the sidebar proxy - the sidebar hides empty
        categories, but every ASSIGNMENT surface (the save dialog, the
        Edit Info dialog's Category dropdown) must still offer the
        complete list. The one implementation behind all three
        sections' getters."""
        names = []
        if not model:
            return names
        for elem in range(model.rowCount()):
            cidx = model.index(elem, 0)
            name = model.data(cidx, QtCore.Qt.ItemDataRole.DisplayRole)
            if name and name != "All":
                names.append(name)
        return sorted(names, key=str.lower)

    def get_category_names(self) -> list[str]:
        return self._category_names_from(self.category_model)

    def assign_category_active(self, category: str) -> None:
        """Set (replace) the category of the ACTIVE section's selected
        assets. The path behind dragging assets onto a sidebar
        category, for every section with real categories: Materials /
        Cop / Code (the curated-library stack) and Colors (user
        gradients). A single category per asset now - the
        multi-category feature was removed."""
        category = (category or "").strip()
        if not category:
            return
        if self.current_section == "gradient":
            self._assign_gradient_category(category)
            return
        stack = self._active_asset_stack()
        if stack is None:
            return
        model, proxy, selmodel, catmodel = stack
        indexes = grid_columns.selected_rows(selmodel)
        if not indexes:
            return
        # OUTSIDE the wrapper: check_add_category announces itself with
        # begin/endInsertRows, and pairing the two segfaults H21
        # (research.md, measured 2026-08-04). The row edits below are
        # data changes, which is what the wrapper is for.
        catmodel.check_add_category(category)
        with ui_helpers.relayout(model):
            for index in indexes:
                idx = model.index(proxy.mapToSource(index).row(), 0)
                asset = model.assets[idx.row()]
                # fav=None: a recategorise edits the record, never the
                # star - the star is per-user and lives in settings.
                # save=False: one index write for the whole selection,
                # not one per row.
                model.set_assetdata(
                    idx, asset.name, category, ", ".join(asset.tags),
                    None, save=False
                )
            model.save()
        self._refresh_sidebar_categories()

    def _assign_gradient_category(self, category: str) -> None:
        """Move the selected gradients to a category - every gradient is a
        normal editable entry now (the seeded palettes included)."""
        rows = [
            self.gradient_sorted_model.mapToSource(i).row()
            for i in grid_columns.selected_rows(self.gradient_selection_model)
        ]
        moved = self.gradient_model.set_user_category(rows, category)
        if moved:
            self._refresh_sidebar_categories()

    def _grid_geometry(self) -> dict:
        """The numbers that would have to change for the grid to appear
        to move - viewport, scroll range, grid step, size hint."""
        view = self.thumblist
        bar = view.verticalScrollBar()
        return {
            "viewport": list(view.viewport().size().toTuple()),
            "scroll": bar.value(), "range_max": bar.maximum(),
            "bar_visible": bar.isVisible(),
            "grid": list(view.gridSize().toTuple()),
            "hint": list(view.sizeHint().toTuple()),
            "rows": view.model().rowCount() if view.model() else 0,
        }

    def thumblist_rc_menu(self) -> None:
        """Grid right-click - the active section builds its own menu."""
        # A right-click must not move the grid. When it does, the
        # before/after pair names which number moved (debug only - this
        # measures four widget geometries, so it stays off the hot path).
        watch = self._grid_geometry() if debug.is_on() else None
        try:
            self._thumblist_rc_menu()
        finally:
            if watch is not None:
                after = self._grid_geometry()
                if after != watch:
                    debug.event("grid", "geometry changed by right-click",
                                before=watch, after=after)

    def _thumblist_rc_menu(self) -> None:
        """The menu itself - the active CONTEXT builds its own, from
        its own entry table (`Section.GRID_MENU`, rendered by
        panel/grid.py).

        No online branch: `_section()` answers with the online world
        while it shows, and the online world has a GRID_MENU like every
        other context. That branch was the last place a grid path had
        to know which world it was in.
        """
        context = self._section()
        if context is not None:
            context.rc_menu()

    def _open_versions_dialog(self, index) -> None:
        """The versions dialog: a dropdown of the versions, a field to
        rename the selected one, Cancel / Apply. Browses, switches and
        names - never creates (creation is automatic on save).

        `index` arrives from the DELEGATE, so it belongs to the proxy
        the view shows; the model methods want source rows.
        """
        source = self.material_sorted_model.mapToSource(index)
        row = source.row()
        model = self.material_model
        mat = model.assets[row]
        listed = versions.list_versions(self.prefs, mat.mat_id)
        if len(listed) < 2:
            return
        active = versions.active_version(self.prefs, mat.mat_id)

        dialog = ui_helpers.DesignedDialog(
            self,
            title="Versions",
            subtitle="%s/%s" % (mat.name, ", ".join(
                str(c) for c in (mat.categories or [])) or "Uncategorized"),
            kind=model.renderer_label(mat),
            icon=self._ui_icon_path("icon_versions_dialog.svg"),
        )
        dialog.setWindowTitle('Versions of "%s"' % mat.name)
        layout = dialog.body_layout

        picker = QtWidgets.QComboBox(dialog)
        for version in listed:
            label = version.get("name") or "Version %s" % version.get("n")
            extra = []
            if version.get("author"):
                extra.append(str(version["author"]))
            if version.get("date"):
                extra.append(str(version["date"]))
            if extra:
                label += "   (%s)" % ", ".join(extra)
            picker.addItem(label, int(version.get("n", 0)))
        current_row = next(
            (i for i, v in enumerate(listed)
             if int(v.get("n", 0)) == active), 0)
        picker.setCurrentIndex(current_row)
        picker.setToolTip(ui_helpers.tooltip_text(
            "Pick the active version in the list, rename it in the "
            "field. Versions are made automatically when you save."))
        dialog.add_field(picker)

        name_field = QtWidgets.QLineEdit(dialog)
        name_field.setToolTip(ui_helpers.tooltip_text(
            "Pick the active version in the list, rename it in the "
            "field. Versions are made automatically when you save."))
        name_field.setPlaceholderText("Rename this version")
        name_field.setText(listed[current_row].get("name") or "")
        dialog.add_field(name_field, label="Name")

        def _sync_field(combo_row):
            name_field.setText(listed[combo_row].get("name") or "")

        picker.currentIndexChanged.connect(_sync_field)

        dialog.add_buttons("cancel", "Apply")

        # DELETED ON BOTH EXITS, and only after its fields are read.
        # It is parented to the panel, which outlives it, so dropping
        # the Python name frees nothing - the cost `edit_tile_icon`
        # records measuring at ~6.5MB per open. NOT WA_DeleteOnClose:
        # the values below come out of the dialog's own children after
        # exec() returns, and that attribute schedules them for
        # destruction, so the read would depend on when the event loop
        # happens to dispatch DeferredDelete.
        try:
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return

            chosen = int(picker.currentData())
            typed = name_field.text().strip()
            combo_row = picker.currentIndex()  # not a proxy
        finally:
            dialog.deleteLater()

        if typed and typed != (listed[combo_row].get("name") or ""):
            model.rename_version(row, chosen, typed)
        if chosen != active:
            model.switch_version(row, chosen)



    def _scene_path(self, path: str) -> str:
        """Every path Amaze WRITES INTO THE SCENE goes through here,
        spelled per Preferences - Write Paths As. The function-sheet
        decision covers Copy Path and every path handed to the user
        after it; loads and existence checks stay on the raw path,
        which is a location, not a spelling."""
        return file_library.houdini_path(
            path, getattr(self.prefs, "path_style", "home"))

    def copy_file_paths(self, proxy_indexes) -> None:
        """Copy the selection's paths to the clipboard, one per line,
        written as Houdini paths ($HIP/... $JOB/... $HOME/...) - the
        function-sheet decision, and the ONLY action an unrecognised
        file has. No dialog: the clipboard changing IS the report."""
        paths = []
        for proxy_index in proxy_indexes:
            path = proxy_index.data(self.file_files_model.PathRole) or ""
            if path:
                paths.append(file_library.houdini_path(
                    path, getattr(self.prefs, "path_style", "home")))
        if not paths:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(paths))
        debug.event("file", "paths copied", count=len(paths))

    def catlist_rc_menu(self) -> None:
        """Sidebar right-click - the active section builds its own menu."""
        if self._is_online():
            # A remote catalogue's categories aren't ours to edit.
            return
        section = self._section()
        if section is not None:
            section.catlist_menu()


    def _locate_folder_user(self, folders_model) -> None:
        """Sidebar "Locate Folder...": re-point the selected registered
        folder at a new location - for a folder that moved on disk, or
        (cross-machine) one whose path only exists on the other
        computer. Shared by the Textures and Geometry sidebars; the
        model rewrites its favorites onto the new path so they survive
        the move."""
        indexes = self.cat_list.selectedIndexes()
        row = indexes[0].row() if indexes else -1
        if row <= 0:
            hou.ui.displayMessage(  # type: ignore
                "Select the registered folder to re-point first "
                '("All" is not a real folder).'
            )
            return
        path = hou.ui.selectFile(file_type=hou.fileType.Directory)  # type: ignore
        if not path:
            return
        rewritten = folders_model.relocate_folder(row, hou.expandString(path))
        if rewritten < 0:
            hou.ui.displayMessage(  # type: ignore
                "That location doesn't exist as a folder - nothing "
                "was changed."
            )
            return
        if rewritten:
            debug.event("folders", "relocated", favorites=rewritten)
        # Rescan under the new path.
        self.update_selected_cat()


    # ------------------------------------- scene capture (hip rows)

    def capture_open_scene_thumbnail(self) -> None:
        """Toolbar button: capture the scene currently open.

        Works off the OPEN scene rather than the grid selection - the
        capture photographs the viewport, so the only scene it can
        honestly be filed against is the one the viewport is showing.
        """
        # No second copy of the policy. This button used to carry its
        # own opened_path/amaze_opened_current_scene gate and its own
        # wording, so the SAME refusal had two phrasings that could
        # drift - the duplication the shared path was introduced to
        # remove, left behind by the first pass.
        # "" = whatever is open. That is what this button has always
        # claimed to do ("the only scene it can honestly be filed
        # against is the one the viewport is showing"); the old gate
        # additionally required AMAZE to have opened it, a stricter rule
        # the shelf tool does not share and cannot be made to.
        self._capture_and_report()

    def _hip_path_for(self, index):
        """The scene path behind a File-grid index, or '' - '' also for
        a row that is not a scene, so every hip-only path stays inert
        on other kinds."""
        if index is None or not index.isValid():
            return ""
        if index.data(self.file_files_model.KindRole) != \
                file_library.KIND_HIP:
            return ""
        return index.data(self.file_files_model.PathRole) or ""

    def open_hip_scene(self, index) -> None:
        """Open a scene file from the grid.

        Houdini's own save prompt is left in charge of unsaved changes -
        re-implementing that dialog would be a second, worse copy of a
        decision the user already has a well-known answer for.
        """
        path = self._hip_path_for(index)
        if not path:
            return
        if not os.path.isfile(path):
            hou.ui.displayMessage(  # type: ignore
                "That scene file is no longer there:\n%s" % path,
                severity=hou.severityType.Warning)
            debug.event("hip", "scene missing", file=path)
            return
        try:
            hou.hipFile.load(path, suppress_save_prompt=False,
                             ignore_load_warnings=False)
        except hou.LoadWarning as warn:
            # A scene that loads WITH warnings is still open and still
            # worth a thumbnail - missing assets are the normal state of
            # an old library, not a failure to open.
            debug.event("hip", "opened with warnings", file=path,
                        warning=str(warn)[:400])
        except Exception as exc:                         # noqa: BLE001
            hou.ui.displayMessage(  # type: ignore
                "Could not open that scene:\n%s\n\n%s" % (path, exc),
                severity=hou.severityType.Error)
            debug.event("hip", "open failed", file=path, error=str(exc))
            return
        scene_captures.note_opened(path)
        debug.event("hip", "scene opened", file=path)

    def _capture_and_report(self, target: str = "") -> None:
        """Run the shared capture and SAY WHY if it refuses.

        Both entry points end here, and every check lives one layer
        down in scene_captures.capture_open_scene - so the tile menu, the
        toolbar button and the shelf tool cannot grow three wordings of
        the same refusal, which is what they had.

        An empty target means "whatever is open".
        """
        try:
            scene_captures.capture_open_scene(target)
        except scene_captures.CaptureRefused as exc:
            # A capture that silently does nothing teaches the user that
            # the feature is broken.
            debug.event("hip", "capture refused", file=target,
                        reason=str(exc))
            hou.ui.displayMessage(str(exc))  # type: ignore

    def capture_hip_thumbnail(self, index, path: str = "") -> None:
        """Capture the current scene view as this scene's thumbnail.

        ONLY ever called from the right-click menu. There is no
        automatic version and there must not be one: the capture runs a
        flipbook, a flipbook forces the scene to COOK, and the cost of
        cooking an arbitrary scene is unbounded.

        Measured 2026-07-29, from the debug log of the attempt that had
        one: a capture scheduled 1.2s after opening a cloth-sim scene
        blocked for 22 SECONDS on the first file, and on the second it
        never returned - Houdini filled 86GB of RAM and crashed. No
        delay fixes that, because the problem is not that the scene had
        not finished loading; it is that forcing a render of someone
        else's scene is work of unknown size. The user presses the
        button when the scene is up and looks right, which is the same
        judgement they were already making by hand.
        """
        target = path or self._hip_path_for(index)
        if not target:
            return
        self._capture_and_report(target)
        # No refresh here: scene_captures announces a landed capture and
        # every live model repaints itself. Doing it again discarded the
        # cached image and emitted dataChanged a second time, and it hid
        # which layer actually owns the refresh.

    def _raw_category_name(self, index) -> str:
        """The STORED name behind a sidebar row, not the displayed one.

        `Categories.data` returns `elem[1:]` for DisplayRole when the
        stored name starts with "_" - the mechanism that makes the
        stored "_All" sort first and read as "All". Every action that
        acts on a category has to key off the stored form or it acts on
        a name that does not exist:

          * Rename "_WIP" -> "Done" matched no asset and no entry, so
            nothing changed and nothing said so;
          * Remove returned early on its own `cat not in self._categories`
            guard and the row stayed;
          * dragging a tile onto that row called check_add_category
            with "WIP", creating a SECOND category beside "_WIP" and
            filing the asset under it - so the tile vanished from the
            row it was dropped on.

        The colour gesture already did this and said why; three
        sibling sites read DisplayRole. One helper now, so a fourth
        cannot get it wrong - and `sidebar_set_colour` reads every
        sidebar's selection through it, not just the asset one.

        "All" stays in its displayed form on purpose: callers compare
        against it to skip the view row.
        """
        if index is None or not index.isValid():
            return ""
        model = self.cat_list.model() if self.cat_list is not None else None
        if model is not None and hasattr(model, "sourceModel"):
            raw = index.data(model.sourceModel().CatSortRole)
            if raw:
                return str(raw)
        return str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")

    def _selected_category_name(self) -> str:
        """The category the sidebar is standing in, blank for All.

        Three copies of this answered it for the save dialogs and they
        already disagreed: one fell back to `live_current_index` when
        the selection model was empty and two returned "", one gated on
        the section and the others did not, and all three read the
        DISPLAYED name. The fallback is the RIGHT behaviour - the panel
        reaches "current but not selected" through
        _restore_section_state's setCurrentIndex - so it is the one
        kept here, and the section gate stays with the callers, since
        only some of them want it.
        """
        if self.cat_list is None:
            return ""
        indexes = self.cat_list.selectedIndexes()
        index = indexes[0] if indexes else ui_helpers.live_current_index(
            self.cat_list)
        name = self._raw_category_name(index)
        return "" if name in ("All", "_All") else name

    #: The picker's starting colour when a row has none. One place.
    DEFAULT_SIDEBAR_COLOUR = "#4af2a1"

    def ask_category_name(self, title: str):
        """The category-name dialog, once - so a caller never unpacks
        CategoryDialog's two-field answer (`canceled` plus `name`),
        which three sidebar menus each did in their own way.

        NONE means CANCELLED and "" means the user cleared the field,
        and the two are not the same thing: File's Label uses an empty
        name to clear a location's custom label back to the path, so
        collapsing them would make Cancel wipe the label."""
        dialog = gradient_dialog.CategoryDialog(title)
        dialog.exec_()
        if dialog.canceled:
            return None
        return dialog.name or ""

    def sidebar_set_colour(self, pick: bool) -> None:
        """Set Color / Clear Color on the sidebar selection.

        ONE gesture for all three sidebars: read the selection's STORED
        names, ask the context what colour the first one has, open the
        picker once, hand the answer back to the context. What a colour
        IS - which store, which models repaint - is the context's
        (`Section.set_sidebar_colour`).

        It was written three times, once per sidebar menu, and only the
        asset copy read the stored name: the sidebar DISPLAYS "_WIP" as
        "WIP", and a colour written under the displayed name is one
        nothing ever reads. "All" is skipped everywhere - it is a view,
        not a category, and colouring it would mean colouring
        everything.
        """
        context = self._section()
        if context is None or self.cat_list is None:
            return
        # ASK THE CONTEXT what a row is keyed by: a category name in
        # three sections, a registered folder PATH in File.
        names = [context.sidebar_key(index)
                 for index in self.cat_list.selectedIndexes()]
        names = [name for name in names
                 if name and name not in ("All", "_All")]
        if not names:
            return

        colour = ""
        if pick:
            chosen = ui_helpers.pick_color(
                context.sidebar_colour(names[0])
                or self.DEFAULT_SIDEBAR_COLOUR,
                self, context.colour_title)
            if chosen is None:
                return
            colour = chosen.name()

        for name in names:
            context.set_sidebar_colour(name, colour)


    def grid_toggle_favourite(self, indexes) -> None:
        """Flip the star on the grid's selection - one entry point for
        every section's menu.

        It was five, one per right-click handler, each naming its own
        model method and its own proxy; three also emitted a layout
        change to force the grid to re-map, and the two that did not
        left an un-favourited tile sitting in a favourites-only grid.
        The re-map is the proxy's own invariant now (grid_proxy.py) and
        the flip is the context's own verb, so what is left here is
        which selection to act on and refreshing the details form.
        """
        context = self._section()
        if context is None:
            return
        context.toggle_favourite(list(indexes))
        self.update_details_view()

    def _selection_has_redshift(self) -> bool:
        """Whether any currently-selected material is Redshift - gates
        showing "Convert to Karma" in the right-click menu."""
        if not self.material_model:
            return False
        for index in grid_columns.selected_rows(
                self.material_selection_model):
            idx = self.material_sorted_model.mapToSource(index)
            mat = self.material_model.assets[idx.row()]
            if "Redshift" in mat.renderer:
                return True
        return False

    def convert_selected_to_karma(self) -> None:
        """Right-click "Convert to Karma": node-graph conversion of
        selected Redshift materials to Karma/MaterialX (see
        core/library.py's convert_redshift_to_karma() and
        render/material_converter.py for what is and isn't handled).
        Non-Redshift items in a mixed selection are silently skipped, not
        errored on. Everything - success and skips alike - lands in one
        summary dialog, since a "successful" conversion can still have
        approximated or skipped inputs worth reviewing; nothing here is
        claimed to be a faithful reproduction."""
        if not self.material_model:
            return
        indexes = grid_columns.selected_rows(self.material_selection_model)
        if not indexes:
            return
        all_lines = []
        converted_count = 0
        redshift_count = 0
        with ui_helpers.relayout(self.material_model):
            for index in indexes:
                idx = self.material_sorted_model.mapToSource(index)
                mat = self.material_model.assets[idx.row()]
                if "Redshift" not in mat.renderer:
                    continue
                redshift_count += 1
                try:
                    ok, report = (
                        self.material_model.convert_redshift_to_karma(idx))
                except Exception as exc:
                    # An exception here previously aborted the whole
                    # batch silently (no summary dialog ever reached,
                    # and any earlier successes in the same selection
                    # were never reported either) - one bad material
                    # must not take the rest of the selection down.
                    all_lines.append(f'"{mat.name}": crashed - {exc}')
                    continue
                if ok:
                    converted_count += 1
                all_lines.extend(report.summary_lines())
        hou.ui.displayMessage(  # type: ignore
            f"Converted {converted_count} of {redshift_count} Redshift "
            "material(s) to Karma.\n\n" + "\n".join(all_lines)
        )

    def show_prefs(self) -> None:
        """Show the Preferences Dialog - NON-MODAL, floating above the
        main window. Opens WITHOUT a library too - with the Library
        menu gone, the dialog's Library tab is the only way to set
        one. Modality mattered: the operations Preferences launches
        (cleanup, set library) open native confirmation/summary
        dialogs, and those landed UNDER a modal prefs dialog -
        invisible, and once fatal (wiki: Qt facts). A second open
        while the window exists just fronts it."""
        # Flush any pending debounced thumbsize save first - prefs.load()
        # at close re-reads settings.json, and a still-pending write
        # would silently revert the newest slider value.
        if self._thumbsize_save_timer.isActive():
            self._thumbsize_save_timer.stop()
            self.prefs.save()
        existing = getattr(self, "_prefs_dialog", None)
        if existing is not None:
            try:
                existing.show()
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                self._prefs_dialog = None
        old_dir = self.prefs.dir
        dlg = prefs_dialog.PrefsDialog(
            self.prefs, panel=self,
            file_files_model=self.file_files_model,
        )
        # Parented to the main window with plain Dialog flags: floats
        # on top of Houdini without blocking it. DeleteOnClose keeps
        # repeated opens from accumulating hidden instances.
        try:
            dlg.setParent(
                hou.qt.mainWindow(), QtCore.Qt.WindowType.Dialog
            )
        except AttributeError:
            pass
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._prefs_dialog = dlg
        # finished on every close path (the dialog's closeEvent calls
        # done()), destroyed as DeleteOnClose insurance - idempotent,
        # so double delivery applies once.
        applied = {"done": False}

        def _closed(*_a, od=old_dir):
            if applied["done"]:
                return
            applied["done"] = True
            self._prefs_dialog_closed(od)

        dlg.finished.connect(_closed)
        dlg.destroyed.connect(_closed)
        # The dialog must not outlive the panel it applies to.
        self.destroyed.connect(dlg.close)
        dlg.show()

    def _prefs_dialog_closed(self, old_dir) -> None:
        """Everything Preferences used to apply when the modal exec_()
        returned, now driven by the non-modal dialog's finished
        signal. A non-modal dialog can outlive its panel (closing the
        pane tab with Preferences open), so the first thing this does
        is confirm the panel still exists on the C++ side."""
        try:
            self.isVisible()
        except RuntimeError:
            return
        self._prefs_dialog = None

        if not self.material_model or not self.category_model:
            # Still no library after the dialog - nothing below applies.
            return

        # Update Thumblist Grid (mode-aware, respects grid/list)
        self.apply_view_mode()
        self.update_renderer_toggles()
        self.prefs.load()
        debug.configure(self.prefs.debug_mode)
        hostos.set_cache_override(self.prefs.cache_dir)
        # Only a changed library DIRECTORY needs the models rebuilt.
        # The old unconditional reload re-read the json, rebuilt every
        # Material, dropped the per-id usd/shader caches (re-derived by
        # reading two files per material on the next paint) and
        # re-loaded every thumbnail PNG - well over a thousand file
        # reads on every single Preferences close, for nothing.
        if self.prefs.dir != old_dir:
            self.switch_all_models()
        accent = theme.accent(self.prefs.accent_color)
        self.click_slider.set_accent_color(accent)
        self.texture_progress.set_accent_color(accent)
        # Tile subtitle line ("Redshift:Standard", "HDR", ...) tracks
        # the accent too.
        for tile_delegate in self.tile_delegates():
            tile_delegate.DIM = accent
        self._sync_notes_button_pixmaps()
        self.sidebar_delegate.set_drag_color(accent)
        self.sidebar_delegate.show_counts = self.prefs.sidebar_counts
        thumbnails.engine.set_budget_mb(self.prefs.ram_cache_mb)
        # Empty-category hiding toggled in Preferences: push the flag
        # into EVERY sidebar proxy and re-evaluate. If turning it ON
        # just hid the category the user was standing in, fall back to
        # All like a filter switch does.
        #
        # Through sidebar_proxies(), which names the three in one
        # place. This loop listed Material and Node and not Code - the
        # same three that setup() and _refresh_sidebar_categories both
        # enumerate completely - so Code kept whatever value it was
        # constructed with for the rest of the run. It was invisible
        # only because nothing set a filter on the Code category model
        # at all, which is the defect above; fixing that made this one
        # live, which is why they ship together.
        for _sidebar_proxy in self.sidebar_proxies():
            _sidebar_proxy.hide_empty = self.prefs.hide_empty_categories
        self._refresh_sidebar_categories()
        self._ensure_sidebar_selection(self.current_section)
        self.cat_list.viewport().update()
        grid.visible_view(self).viewport().update()
        # Geometry look prefs (shading mode / background) may have
        # changed: the cache key covers them, but nothing re-runs the
        # folder scan while the section is showing - re-run the current
        # selection so the new look renders without re-clicking the
        # folder.
        section = self._section()
        if section is not None:
            section.prefs_changed()
        # Safe point to (re)start image thumbnail generation - back in
        # the plain main event loop, no longer nested inside the modal
        # Preferences dialog. See the clear_cache() docstrings.
        #
        # ONLY while the File section is showing. The merged model's
        # refresh can start the BLOCKING geometry render pass, and
        # before the merge that pass was only reachable from the
        # section whose tiles it renders - a Delete Local Cache from
        # the Material tab must not freeze Houdini rendering geometry
        # nobody is looking at. Not deferred-and-lost: FolderSection.
        # activate() re-runs the folder scan on every File activation,
        # so the next visit rescans anyway.
        if self.current_section == "file":
            self.file_files_model.refresh_current_folder()
        # Visible section tabs may have changed in Preferences.
        self._apply_enabled_sections()

    def update_renderer_toggles(self):
        """A renderer was enabled or disabled - in Preferences, or by
        saving a material of a new one - so the Filter menu may offer
        something different now.

        It used to show and hide pre-built renderer actions here, and
        hand-check the "the checked one just vanished" case. Rebuilding
        covers both: MaterialSection.filter_entries reads the same prefs
        flags, and build_filter_menu falls back to All for any section
        whose remembered choice is no longer on offer. Kept under its
        own name because its three callers mean this event, not "redraw
        the menu"."""
        if getattr(self, "menu_filter", None) is None:
            return
        self.build_filter_menu()

    def import_galleries(self) -> None:
        """Gallery Import: every material preset in Houdini's galleries
        becomes a library material, through the same save funnel a
        hand-saved material takes. Thumbnails are skipped during the
        run (hundreds of renders would take hours) - the summary says
        how to render them afterwards."""
        if not self.material_model:
            hou.ui.displayMessage("Please set a library first.")  # type: ignore
            return
        # Pick the .gal file: nobody remembers where Houdini keeps
        # them, so the dialog opens in the user gallery directory and
        # any file elsewhere works just as well.
        picked = hou.ui.selectFile(  # type: ignore
            start_directory=gallery_import.default_gallery_dir(),
            title="Import Gallery (.gal)",
            file_type=hou.fileType.Any,
            pattern="*.gal",
            chooser_mode=hou.fileChooserMode.Read,
        )
        picked = (picked or "").strip()
        if not picked:
            return
        picked = hou.text.expandString(picked)
        entries = gallery_import.entries_from_file(picked)
        if not entries:
            hou.ui.displayMessage(  # type: ignore
                "No material presets found in:\n%s" % picked
            )
            return
        types = {}
        for _entry, type_name, _cat in entries:
            types[type_name] = types.get(type_name, 0) + 1
        listing = "\n".join(
            "  %d x %s" % (count, name)
            for name, count in sorted(types.items(), key=lambda x: -x[1])
        )
        choice = hou.ui.displayMessage(  # type: ignore
            "Import %d material presets from\n%s\n\n%s\n\n"
            "Thumbnails are NOT rendered during the import - select the "
            "new materials afterwards and use Rerender Thumbnail."
            % (len(entries), os.path.basename(picked), listing),
            buttons=("Import", "Cancel"),
            default_choice=0, close_choice=1,
        )
        if choice != 0:
            return
        render_pref = self.prefs.render_on_import
        self.prefs.render_on_import = 0
        summary = {}
        try:
            with hou.InterruptableOperation(  # type: ignore
                "Importing gallery presets", open_interrupt_dialog=True
            ) as op:
                def progress(index, total, name):
                    op.updateLongProgress(
                        float(index) / max(total, 1),
                        "%d/%d  %s" % (index + 1, total, name),
                    )
                summary = gallery_import.import_entries(
                    self.material_model, entries, progress=progress
                )
        except hou.OperationInterrupted:
            debug.event("gallery", "import interrupted", **summary)
        finally:
            self.prefs.render_on_import = render_pref
            self.prefs.save()
        for name in sorted(summary.get("categories", {})):
            self.category_model.check_add_category(name)
        self._refresh_sidebar_categories()
        hou.ui.displayMessage(  # type: ignore
            "Gallery import finished.\n\n"
            "Imported: %d\nSkipped: %d\nFailed: %d\n\n"
            "Select the new materials and use Rerender Thumbnail to "
            "generate their previews."
            % (summary.get("imported", 0), summary.get("skipped", 0),
               summary.get("failed", 0))
        )

    def cleanup_db(self) -> None:
        """Cleans the WHOLE v2 estate in one pass, one combined report:
        the material library, the COP library (same integrity passes
        over cops.json), registered texture/geometry folder pointers
        whose directory no longer exists, and favorites pointing at
        files (or curated gradient entries) that are gone."""
        if not self.material_model:
            hou.ui.displayMessage("Please open a library first")  # type: ignore
            return

        # CONFIRM BEFORE, because this DELETES. The rule is "dialogs
        # confirm an action before it happens - never announce that one
        # finished", and this had it exactly inverted: no gate, and two
        # completion dialogs. What runs unguarded is not cosmetic - it
        # unlinks .mat/.interface/.png files and drops registered folder
        # pointers and favourites - and two one-click entry points reach
        # it, the View menu and a Preferences button sitting directly
        # above "Reload Library".
        if hou.ui.displayMessage(  # type: ignore
            "Clean Library?",
            help="Removes index rows whose files are gone, deletes "
                 "orphaned files that no library references, and drops "
                 "folder pointers and favourites that no longer exist.\n\n"
                 "Files are deleted from disk. This cannot be undone.",
            buttons=("Clean Library", "Cancel"),
            default_choice=1, close_choice=1,
            severity=hou.severityType.Warning,
            title="Amaze",
        ) != 0:
            debug.event("cleanup", "cancelled at the confirm dialog")
            return
        sections = []

        rescued = self.material_model.cleanup_db(show_dialog=False)
        if rescued:
            self.category_model.check_add_category("Uncategorized")
        normalized = self.category_model.normalize_categories()
        if normalized:
            debug.event("cleanup", "legacy category entries normalized",
                        count=normalized)
        mat_summary = list(
            getattr(self.material_model, "last_cleanup_summary", [])
        )
        if mat_summary:
            sections.append("Materials:\n- " + "\n- ".join(mat_summary))

        if getattr(self, "cop_model", None):
            cop_rescued = self.cop_model.cleanup_db(show_dialog=False)
            if cop_rescued:
                self.cop_category_model.check_add_category("Uncategorized")
            self.cop_category_model.normalize_categories()
            cop_summary = list(
                getattr(self.cop_model, "last_cleanup_summary", [])
            )
            if cop_summary:
                sections.append("Node assets:\n- " + "\n- ".join(cop_summary))

        browser_lines = self._cleanup_browser_prefs()
        if browser_lines:
            sections.append("Folders and favorites:\n- " + "\n- ".join(browser_lines))

        if sections:
            # The one completion dialog that earns its OK-click. "Never
            # announce that one finished" exists because "the refreshed
            # grid IS the report" - and here it is not: files were
            # unlinked and folder pointers dropped, none of which the
            # grid can show. This is the RECORD of an irreversible act,
            # not a notification that work ended.
            hou.ui.displayMessage(  # type: ignore
                "Library cleanup removed:\n\n" + "\n\n".join(sections)
            )
        else:
            # "Nothing to clean" IS just an announcement - the estate is
            # unchanged and the grid already shows that. Dropped; the
            # log keeps the record.
            debug.event("cleanup", "nothing to clean")

    @staticmethod
    def _volume_unreachable(path: str) -> bool:
        """The path's VOLUME is not mounted - as opposed to the path
        being gone from a volume that is right here.

        An unmounted NAS share answers os.path.isdir exactly like a
        deleted folder, and pruning on that answer deletes the user's
        folder list every time the network hiccups - to be rebuilt by
        hand when the share comes back. A path under an absent
        /Volumes/<name> root is unreachable, not gone; the same holds
        for a bare drive letter on Windows.
        """
        path = os.path.abspath(path)
        if hostos.is_windows():
            drive = os.path.splitdrive(path)[0]
            return bool(drive) and not os.path.exists(drive + os.sep)
        if path.startswith("/Volumes/"):
            parts = path.split("/")
            root = "/".join(parts[:3])      # /Volumes/<name>
            return not os.path.exists(root)
        return False

    def _cleanup_browser_prefs(self) -> list:
        """The File section's cleanup: drops registered folder pointers
        whose directory no longer exists and favorites whose file is
        gone. Only pointers and prefs entries are touched - never
        anything on disk.

        Only the LIVE file_* keys are pruned. The dormant pre-merge
        quartets (texture_*/geometry_*/hip_*) are deliberately left
        untouched: they are what an older build on another machine
        still reads, and pruning data this build no longer uses would
        be all risk and no benefit."""
        lines = []

        removed_folders = []
        skipped_unmounted = 0
        # HIGHEST ROW FIRST, so removing one never shifts the row of
        # another not yet examined - the rule cleanup_db already
        # follows for assets.
        folders = list(self.prefs.file_folders)
        for index in range(len(folders) - 1, -1, -1):
            path = folders[index]
            if os.path.isdir(path):
                continue
            # UNREACHABLE IS NOT GONE. An unmounted share answers
            # isdir exactly like a deleted folder; pruning on that
            # deletes the user's folder list every time the network
            # blinks, to be rebuilt by hand when the share returns.
            if self._volume_unreachable(path):
                skipped_unmounted += 1
                debug.event("cleanup", "folder pointer kept - its volume "
                            "is not mounted", path=path)
                continue
            debug.event("cleanup", "folder pointer removed", path=path)
            # THROUGH THE MODEL, not through prefs. FolderListModel
            # reads its rows straight out of prefs, so writing there
            # changed the row COUNT with nothing announcing it, and
            # the bare layoutChanged that used to follow was the wrong
            # signal for a changed count (category.normalize_categories
            # says why) as well as a native H21 segfault (research.md).
            # remove_folder wraps the same prefs write in
            # beginRemoveRows and drops the count cache with it.
            # Row 0 is the synthetic "All" entry.
            self.file_folders_model.remove_folder(index + 1)
            removed_folders.append(path)
        if removed_folders:
            # NAMES, not a count: "3 folder pointers were removed" is a
            # sentence nobody can check.
            lines.append(
                "These folders no longer exist, so their entries were "
                "removed:\n  " + "\n  ".join(sorted(removed_folders)))
        if skipped_unmounted:
            lines.append(
                "%d folder(s) on an unmounted drive were left alone - "
                "they will be back when the drive is."
                % skipped_unmounted)

        removed_favs = []
        for path, drop in (
                [(p, self.prefs.remove_file_favorite)
                 for p in list(self.prefs.file_favorites)]):
            if os.path.exists(path):
                continue
            if self._volume_unreachable(path):
                debug.event("cleanup", "favorite kept - its volume is "
                            "not mounted", path=path)
                continue
            debug.event("cleanup", "missing-file favorite removed",
                        path=path)
            drop(path)
            removed_favs.append(path)
        if removed_favs:
            lines.append(
                "These favorites pointed at files that are gone, so they "
                "were removed:\n  " + "\n  ".join(sorted(removed_favs)))
        return lines

    def open_usdlib_folder(self) -> None:
        """Open the Library Folder in the System explorer"""
        if not self.material_model:
            hou.ui.displayMessage("Please open a library first")  # type: ignore
            return
        lib_dir = self.prefs.dir
        hostos.open_path(lib_dir)

    def add_file_folder_user(self) -> None:
        """Register a new folder pointer for the File section. Only
        stores the path - never scans or copies anything until the
        folder is actually selected in the list."""
        path = hou.ui.selectFile(file_type=hou.fileType.Directory)  # type: ignore
        if not path:
            return
        self.file_folders_model.add_folder(hou.expandString(path))

    def remove_file_folder_user(self) -> None:
        """Unregister the selected folder pointer(s). Only removes the
        pointer from the list - never touches anything on disk."""
        rows = sorted(
            (i.row() for i in self.cat_list.selectedIndexes()), reverse=True
        )
        for row in rows:
            self.file_folders_model.remove_folder(row)

    #: Fixed section order + DISPLAY labels; the enabled_sections pref
    #: chooses which of these actually appear (let a user show only the
    #: sections they use, e.g. Materials + Code).
    #:
    #: The KEYS are storage, not display: "cop" and "gradient" are what
    #: enabled_sections and the per-section state remember, so they
    #: stay put while the labels change (plural -> singular 2026-07-31,
    #: Textures/Geometry/HIP -> File the same day) - renaming them
    #: would silently reset which sections a user has enabled.
    #: Delegates to sections.all_sections() - the sections own their own
    #: labels now. Three copies of this list existed and two of them
    #: silently disagreed.
    ALL_SECTIONS = sections.all_sections()

    def _online_segments(self) -> list:
        """The ONLINE strip: one tab per source, in source order.

        A parallel world, not a filtered version of the local one. The
        local sections have nothing to do with it - no File tab, and
        the enabled_sections preference does not apply, because these
        are not sections. Built from matx_sources.all_sources(), which
        is already the one list of them, so a new source is one entry
        there and appears here on its own.
        """
        return [(source.name, source.name)
                for source in matx_sources.all_sources()]

    def _build_section_tabs(self) -> None:
        """(Re)build the tab strip - the local sections, or the online
        sources while the online browser is showing.

        ONE strip, two lists. The rebuild path already existed for the
        enabled_sections preference, so switching worlds reuses it
        rather than adding a second strip to keep in sync.
        """
        if self._is_online():
            segments = self._online_segments()
        else:
            enabled = self.prefs.enabled_sections
            segments = [(k, lbl) for (k, lbl) in self.ALL_SECTIONS
                        if k in enabled]
        if not segments:
            segments = [("material", "Material")]
        # Replace any existing strip in the layout (index 1, under the
        # toolbar row).
        if getattr(self, "section_tabs", None) is not None:
            if self._central_layout is not None:
                self._central_layout.removeWidget(self.section_tabs)
            self.section_tabs.deleteLater()
        self.section_tabs = ui_helpers.SectionTabBar(segments)
        self.section_tabs.segmentClicked.connect(
            lambda key: self._on_tab_toggled(key, True)
        )
        if self._central_layout is not None:
            self._central_layout.insertWidget(1, self.section_tabs)
        # Keep the current section checked if it survived; else the
        # first available. emit=False: setup() activates the section
        # explicitly (and the models may not exist yet at construction).
        keys = [k for k, _ in segments]
        current = (getattr(self, "online_source", None) if self._is_online()
                   else getattr(self, "current_section", "material"))
        self.section_tabs.setChecked(
            current if current in keys else keys[0], emit=False
        )


    def _apply_enabled_sections(self) -> None:
        """After Preferences may have changed enabled_sections: rebuild
        the strip, and if the section that was showing got hidden,
        switch to the first still-enabled one."""
        enabled = self.prefs.enabled_sections
        self._build_section_tabs()
        if self.current_section not in enabled and self.material_model:
            keys = [k for k, _ in self.ALL_SECTIONS if k in enabled] or [
                "material"
            ]
            # A SECTION KEY IS NOT A SOURCE NAME. `_on_tab_toggled`
            # forwards whatever it is given to `open_online_source`
            # while the online world is showing, so hiding a section in
            # Preferences from inside that world filtered the catalogue
            # to a source called "gradient": empty grid, `online_source`
            # left holding it, and no source tab highlighted because no
            # chip matches. The tab strip already rebuilt above; the
            # section behind the online world is switched when it is
            # actually shown again.
            if self._is_online():
                self._section_before_online = keys[0]
            else:
                self._on_tab_toggled(keys[0], True)

    def _on_tab_toggled(self, key: str, checked: bool) -> None:
        """Section-tab click (Materials / Textures / Colors / Cop /
        Geometry). Geometry is still a placeholder - its content is not
        built yet, so the view underneath simply doesn't change when
        it's clicked."""
        if not checked:
            return
        if self._is_online():
            # In the online world a tab is a SOURCE, not a section.
            self.open_online_source(key)
            return
        if self.material_model is None:
            # setup() (which creates category_sorted_model,
            # file_folders_model, material_selection_model, etc.)
            # never ran - no library is configured yet. init_ui() builds
            # and enables the tab strip unconditionally, so this is
            # reachable by just clicking a tab before that - same class
            # of crash as the emit=False fix above, different
            # precondition. Same guard pattern used everywhere else in
            # this file for "library not set up yet".
            return
        # Snapshot the OUTGOING section's view state before anything
        # changes - current_section still names it here.
        self._capture_section_state()
        self.current_section = key
        debug.event("section", "switched", to=key, online=self._is_online())
        section = self.sections.get(key)
        if section is None:
            debug.event("section", "section not built yet - the view "
                        "below will not change", section=key)
            return
        self._apply_context(section, key)

    def _apply_context(self, context, key: str) -> None:
        """Activate a context and do everything that MUST follow it.

        Entering the online world used to call its activation directly
        and skip all of this, which is why three separate things drifted
        there: the Capture button kept the state the section you left
        had given it, the search box kept text that filters nothing in
        this world, and the Comments pane went on pointing at the local
        asset you had selected. One path, and none of that is something
        anyone has to remember.
        """
        context.activate()
        # EVERY toolbar control, from the one table - including Capture,
        # whose rule used to be `key == "file"` right here, five sync
        # methods away from the three chips that follow the same kind
        # of fact.
        self._sync_toolbar(context)
        self._sync_filters_to_section(context)
        self._restore_section_state(key)
        self._refresh_notes_subject()
        # A section switch swaps the MODEL under a view that has not
        # changed, so the blank has to re-attach here or it keeps
        # watching the section you left.
        empty_state.track(self)

    def _sync_filters_to_section(self, section) -> None:
        """Push the SHARED filter widgets into the incoming section.

        line_filter and cb_favsonly are one pair of widgets serving every
        section, but each section's filter lives on its own proxy and was
        only ever written from a textEdited/toggled signal. So the two
        drifted the moment you switched tabs: filter Images to "brick"
        with favourites-only on, click Geometry (which shows everything,
        while the box still reads "brick" and the star is still lit),
        clear both there, come back to Images - and Images is STILL
        filtered to nothing, with an empty search box and an unlit star.
        An empty grid with no visible cause, and the only way out is to
        retype the filter and clear it again inside that tab.

        Syncing on entry makes the visible widgets always describe the
        visible grid."""
        text = self.line_filter.text() if self.line_filter else ""
        favourites = bool(self.cb_favsonly and self.cb_favsonly.isChecked())
        section.filter_text(text)
        section.filter_favorites(favourites)
        # The Filter menu is the third shared control, and the one that
        # does NOT carry its setting across: each section keeps its own
        # (a renderer means nothing to Colors), so entering a section
        # rebuilds the menu from what that section offers and re-applies
        # what it was left on. build_filter_menu ends by applying it.
        self.build_filter_menu()

    def _capture_section_state(self) -> None:
        """Remember the current section's sidebar choice and grid scroll
        position (keyed by section) for _restore_section_state."""
        state = {}
        # THE 2026-07-29 00:13 CRASH. This read `.data()` on the stored
        # currentIndex, which for the sidebar is a proxy index: signal 11
        # inside proxy_to_source, no log record, nothing catchable. See
        # ui_helpers.live_current_index for why isValid() is not a guard.
        current = ui_helpers.live_current_index(self.cat_list)
        if current is not None:
            state["cat_text"] = current.data()
        state["scroll"] = grid.visible_view(self).verticalScrollBar().value()
        self._section_view_state[self.current_section] = state

    def _restore_section_state(self, key: str) -> None:
        """Re-select the sidebar entry the section had when last left
        (overriding the activation method's default) and bring the grid
        scroll back. Matching is by display TEXT, so category renames
        or reordering between visits degrade gracefully to the default
        instead of selecting the wrong row. Textures skip the sidebar
        part - their folder restore (prefs-based, survives relaunches)
        already ran in FolderSection.activate()."""
        state = self._section_view_state.get(key)
        if not state:
            return
        cat_text = state.get("cat_text")
        if (
            cat_text
            and key not in ("file",)
            and self.cat_list is not None
        ):
            model = self.cat_list.model()
            selection_model = self.cat_list.selectionModel()
            if model is not None and selection_model is not None:
                for row in range(model.rowCount()):
                    idx = model.index(row, 0)
                    if idx.data() == cat_text:
                        selection_model.select(
                            idx,
                            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect,
                        )
                        self.cat_list.setCurrentIndex(idx)
                        # Re-applies the right filter for whichever
                        # section this is - same handler a real click
                        # runs.
                        self.update_selected_cat()
                        break
        scroll = state.get("scroll")
        if scroll:
            # Deferred one event-loop turn: the view has just swapped
            # models and relaid itself out - an immediate setValue gets
            # clamped/overridden by that layout pass.
            QtCore.QTimer.singleShot(
                0,
                lambda: grid.visible_view(self)
                .verticalScrollBar().setValue(scroll),
            )

    # ------------------------------------------------------------------
    # Online MaterialX browser (View menu > Online Materials)
    # ------------------------------------------------------------------

    #: THE TOOLBAR, AS DATA: which control follows which fact about the
    #: context showing, and whether that fact governs enabled-ness or
    #: visibility.
    #:
    #: This was five sync methods that could disagree, because each
    #: carried its own idea of which context it was in - three chips
    #: disabled by asking `_is_online()` twice in one method, and the
    #: Capture button governed from inside the activation path by
    #: `key == "file"`. A control's rule is one row here now, and the
    #: context answers it. A disabled chip paints at half opacity, so
    #: it reads as switched off rather than broken.
    TOOLBAR_CONTROLS = (
        ("cb_favsonly", "takes_favourites", "enabled"),
        ("btn_notes", "takes_comments", "enabled"),
        ("btn_filter", "takes_filter_menu", "enabled"),
        ("btn_hip_capture", "takes_capture", "shown"),
    )

    def _sync_toolbar(self, context) -> None:
        """Walk the table. No toolbar path asks which WORLD it is in -
        the online world is a context like any other since batch 5, and
        what it does not offer it declares."""
        for name, fact, verb in self.TOOLBAR_CONTROLS:
            control = getattr(self, name, None)
            if control is None:
                continue
            offered = bool(getattr(context, fact, True))
            if verb == "shown":
                control.setVisible(offered)
            else:
                control.setEnabled(offered)
        self._sync_filter_placeholder()

    def _sync_toolbar_for_mode(self) -> None:
        """The old entry point, kept because two call sites reach the
        toolbar without a context in hand."""
        context = self._section()
        if context is not None:
            self._sync_toolbar(context)

    def _sync_filter_placeholder(self) -> None:
        """Say what the Filter Box searches in the section it is serving.

        One box serves seven tabs and the online browser, and what it
        matches is not the same in any two archetypes: the Asset sections
        take a name or ":tag", the Folder sections have only a file name,
        Colors also matches the color names inside a palette, and the
        online browser matches name, category and tag with no prefix at
        all. So the text cannot be set once at construction - it is set
        from here, which _sync_toolbar_for_mode already documents as the
        place that runs on every section AND mode change."""
        if self.line_filter is None:
            return
        if self._is_online():
            hint = ""
        else:
            hint = getattr(self._section(), "search_hint",
                           sections.Section.search_hint)
        self.line_filter.setPlaceholderText(hint)

    def _section(self):
        """The active CONTEXT - a Section, or the online world.

        The online world is not in `sections` and never appears in
        `enabled_sections`, because it is not a section. But it drives
        the same four areas, so every area path asks for it the same
        way and stops needing to know which world it is in - which is
        what takes `_is_online()` out of those paths.
        """
        if getattr(self, "online_mode", False):
            return getattr(self, "online_context", None)
        return getattr(self, "sections", {}).get(self.current_section)

    def tile_delegates(self) -> tuple:
        """EVERY tile delegate, once, walked by every site that has to
        reach all of them.

        There were THREE hand-written lists of these and the fourth
        delegate was in NONE of them. `asset_delegate` was added
        deliberately - to fix another bug, so Node and Code would stop
        painting a Version column reading "none" on every row - and
        joining it to the accent sweep and to `set_list_columns` was

        reported as "the type column started under category and continues to halfway to
        comments": Node and Code rows were laid out with column widths
        the panel had never told that delegate about.

        Built from the SECTIONS, not written out here, so a section
        that arrives with a delegate of its own joins by existing. The
        online delegate is included by name because the online world is
        not a section yet - batch 5 is where that stops being true.
        """
        found = []
        for section in getattr(self, "sections", {}).values():
            name = getattr(section, "delegate_attr", "")
            delegate = getattr(self, name, None) if name else None
            if delegate is not None and delegate not in found:
                found.append(delegate)
        # The online world's grid uses the Materials delegate today, so
        # this adds nothing while that is true - and adds it the moment
        # it stops being true.
        online = getattr(self, "matx_delegate", None)
        if online is not None and online not in found:
            found.append(online)
        return tuple(found)

    def _is_online(self) -> bool:
        """Is the online world showing?

        It used to read `online_mode AND current_section == "material"`,
        because online was a VIEW MODE over the Materials section and
        could not be true anywhere else. Online is its own world now,
        with its own tab strip of sources, so the section it is layered
        over is no longer a thing - the mode alone is the answer.

        current_section keeps naming the LOCAL section underneath,
        untouched while you are away, which is what leaving puts you
        back on.

        Still one predicate, for the reason it was one before: four
        handlers knew about online mode and six did not."""
        return bool(getattr(self, "online_mode", False))

    def _on_online_source(self, action) -> None:
        """A View menu material-source entry was clicked. Material Library
        returns to the local library; an online source enters its browser.
        They share one exclusive group, so Qt keeps exactly one checked."""
        if action is self.action_material_library:
            self.leave_online_world()
            if self.current_section != "material":
                self.section_tabs.setChecked("material")
        elif action.isChecked():
            self.open_online_source(action.text())

    def enter_online_world(self) -> None:
        """Switch to the online world: its own tab strip, one tab per
        source, nothing to do with the local sections.

        Where you came FROM is remembered, because leaving puts you
        back there - you dipped into the online browser, you did not
        change what you were working on.
        """
        if self._is_online():
            return
        # WHAT YOU WERE LOOKING AT, not what you were looking at the
        # last time you switched tabs. Leaving routes through
        # `_apply_context` -> `_restore_section_state`, and nothing on
        # the way IN ever captured - so coming back put you on the
        # category stored at the last TAB SWITCH, or on All when there
        # had been none.
        self._capture_section_state()
        self._section_before_online = self.current_section
        self.online_mode = True
        first = self._online_segments()[0][0]
        self._build_section_tabs()
        self.open_online_source(first)

    def leave_online_world(self) -> None:
        """Back to the local sections, and to the one you left from."""
        if not self._is_online():
            return
        back = getattr(self, "_section_before_online", None) \
            or self.current_section
        self.exit_online_materials()
        self._build_section_tabs()
        if back in dict(self.ALL_SECTIONS):
            self.section_tabs.setChecked(back)
        # ENTERING repoints every shared widget at the online models, so
        # LEAVING has to repoint them back - and nothing else will.
        # setChecked cannot do it: `back` is the section we never left
        # (entering the online world does not change current_section),
        # and SectionTabBar.setChecked emits only on a real change, so
        # no _on_tab_toggled and no activate() ever ran. Leaving from
        # Node, Code, Color or File therefore kept the online model in
        # the grid, and the next double-click mapped an ONLINE proxy
        # index through a LOCAL proxy.
        section = self._section()
        if section is not None:
            # THE ONE PATH, as entering already takes. Calling
            # `activate()` alone left the toolbar to a standalone
            # `_sync_toolbar_for_mode()` further up - which is the
            # duplicate this batch exists to remove, and it only looked
            # correct because the two happened to agree.
            self._apply_context(section, section.key)

    def open_online_source(self, source_name: str) -> None:
        """Show one source in the online world. A tab click, now that
        the strip IS the sources."""
        self.online_mode = True
        self.online_source = source_name
        act = self.online_source_actions.get(source_name)
        if act is not None and not act.isChecked():
            act.setChecked(True)
        debug.event("online", "source opened", source=source_name)
        # NO TAB FORCING. Online used to be a view mode over the
        # Materials widgets, so opening a source switched you there.
        # Online is its own world now with its own strip, and the tab
        # you want is the source you just picked.
        if self.section_tabs is not None:
            self.section_tabs.setChecked(source_name, emit=False)
        self.matx_online_model.set_source(source_name)
        self.enter_online()
        # Picking a source starts you on "All" - not a stale category from
        # a previous source and not an unhighlighted sidebar. Done here (on
        # the explicit source-pick) rather than in _activate_online_
        # materials(), so switching tabs away and back doesn't reset the
        # category you were browsing.
        self._select_online_all()

    def _select_online_all(self) -> None:
        """Select the online sidebar's "All" row (row 0) and clear any
        category filter, so the grid shows the whole source."""
        if not self.cat_list or self.matx_source_model.rowCount() == 0:
            return
        idx = self.matx_source_model.index(0, 0)
        sel = self.cat_list.selectionModel()
        if sel is not None:
            sel.select(
                idx, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
            self.cat_list.setCurrentIndex(idx)
        self.update_selected_cat()

    def exit_online_materials(self) -> None:
        """Leave the online browser, back to the local library (Material
        Library)."""
        self.online_mode = False
        if getattr(self, "action_material_library", None) is not None:
            # Exclusive group: checking this unchecks any source.
            self.action_material_library.setChecked(True)
        debug.event("online", "exited")
        # WHERE YOU LAND is the caller's business: the button remembers
        # the section you left from, and the Material Library menu
        # entry means the material library. This used to force the
        # Materials tab from in here, which is the same coupling the
        # online world was just taken out of - and it kept a
        # Material-shaped remnant of that coupling until 2026-08-02:
        # re-activating ONLY the material section, which left the grid
        # pointed at the online model for the other four.

    def enter_online(self) -> None:
        """Enter the online world through the SAME path a section takes.

        The body that used to be here - four setModel calls and a
        reload - is `OnlineContext.activate()` now, and this routes it
        through `_apply_context` so the Capture button, the search box
        and the Comments subject follow it the way they follow every
        section. They did not, before, and that was three defects with
        one cause.

        Named for what it DOES rather than `_activate_online_materials`.
        Every other `_activate_*` moved onto its own section; this one
        cannot, because the online world is deliberately not a Section
        and never appears in `enabled_sections`. A ban test keeps the
        old shape from coming back.
        """
        self._apply_context(self.online_context, self.online_context.key)


    #: Sub-steps per material for the download bar - a smooth 0..N*SCALE
    #: range folds each material's own 0..1 download fraction into the
    #: overall multi-import progress.
    _IMPORT_PROGRESS_SCALE = 1000

    @contextlib.contextmanager
    def _download_bar(self, records):
        """The download bar, for the length of a multi-record import.

        Yields `progress_for(i)` - the per-record 0..1 callback for
        record `i` of the batch, folded into the overall 0..N*SCALE
        range. The bar is shown only when something actually has to be
        downloaded, and is always taken down again.

        ONE frame for both online importers. `_import_online_records`
        and `_import_online_records_to_scene` each carried this setup,
        this teardown and a byte-identical `on_progress` closure - the
        one literal clone the duplicate scan found in `panel.py`.

        The download is synchronous (it blocks the UI thread), so the
        byte callback pumps events per 64KB chunk with
        ExcludeUserInputEvents - the bar animates without a second
        click re-entering mid-import. Same pattern as the geometry
        thumbnail pass.
        """
        total = len(records)
        scale = self._IMPORT_PROGRESS_SCALE
        pump = QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
        # The event pumping can deliver a late preview-worker signal;
        # this flag keeps that from repainting the bar with preview
        # counts while the download owns it.
        self._online_download_active = True
        show_bar = self._needs_download(records)
        if show_bar:
            self.texture_progress.setVisible(True)
            self.texture_progress.set_progress(0, total * scale)
            QtWidgets.QApplication.processEvents(pump)

        def progress_for(i):
            def on_progress(frac):
                if not show_bar:
                    return
                frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
                self.texture_progress.set_progress(
                    int((i + frac) * scale), total * scale
                )
                QtWidgets.QApplication.processEvents(pump)
            return on_progress

        try:
            yield progress_for
        finally:
            self._online_download_active = False
            if show_bar:
                self.texture_progress.setVisible(False)

    def _import_online_records(self, records) -> None:
        """Import one or more online records into the LIBRARY."""
        if not len(records):
            return
        total = len(records)
        failures = []
        with self._download_bar(records) as progress_for:
            for i, rec in enumerate(records):
                on_progress = progress_for(i)
                # ONE BAD RECORD MUST NOT ABANDON THE BATCH, which is
                # what the to-scene copy of this loop already says and
                # does. matx_import.import_record has only try/finally,
                # so build_karma_material and library.add_asset raise
                # straight through it: a hou.Error or an OSError on the
                # second of five records aborted the loop, records 3-5
                # were never imported, and the "%d of %d could not be
                # imported" dialog that `failures` exists for never
                # appeared - the user got a traceback in the log and
                # three silently missing materials. The identical batch
                # sent to /mat carried on and reported it.
                try:
                    ok, reason = self.import_online_material(
                        rec, on_progress=on_progress
                    )
                except Exception as exc:                  # noqa: BLE001
                    debug.exception("online import", exc, record=rec.title)
                    ok, reason = False, str(exc)
                if not ok:
                    failures.append("%s: %s" % (rec.title, reason))
        # ONE dialog for the batch: a five-material selection that
        # fails five times used to pop five modal dialogs in a row.
        if failures:
            hou.ui.displayMessage(  # type: ignore
                "Amaze: %d of %d could not be imported:\n\n%s"
                % (len(failures), total, "\n".join(failures[:10]))
            )

    def import_online_material(self, record, on_progress=None):
        """Download (if needed) and register one online material as a
        normal library material with renderer Karma. on_progress(frac)
        is called with a 0..1 fraction during the download when given.

        Returns (ok, reason). The CALLER reports - reporting per record
        turned one five-material selection into five modal dialogs."""
        if record is None or not self.material_model:
            return (False, "No library to import into.")
        source, resolution, error = self._online_source_for(record)
        if error:
            return (False, error)
        if source is None:
            return (False, "Unknown source")
        with ui_helpers.relayout(self.material_model):
            ok, reason = matx_import.import_record(
                record, source, resolution, self.material_model, self.prefs,
                progress=on_progress,
            )
        if not ok:
            return (False, reason or "Import failed.")
        # check_add_category() writes and saves SILENTLY - no model
        # signal - so the sidebar never learned about the new row. The
        # data was always correct; only the view was stale.
        # No layout wrapper: check_add_category announces itself with
        # begin/endInsertRows, and pairing the two segfaults H21
        # (research.md, measured 2026-08-04).
        self.category_model.check_add_category(record.category)
        self._refresh_sidebar_categories()
        return (True, "")

    def _needs_download(self, records) -> bool:
        """True when importing these records will actually fetch bytes.

        The progress bar sits ABOVE the grid in the layout, so showing
        it shifts every tile down by its height and hiding it shifts
        them back. Value sources (RGL, PhysicallyBased) carry their
        numbers in the catalogue and download nothing, so the bar would
        appear and vanish within one frame - the grid visibly jumping
        for no work at all.
        """
        # The source is looked up DIRECTLY rather than through
        # _online_source_for, which also resolves the download
        # RESOLUTION - and that costs one HTTP GET per package, on the
        # main thread, before the progress bar is even shown. Measured
        # live: 254 of GPUOpen's 454 materials carry 6 packages and 170
        # carry 4, so a ten-material selection blocked Houdini on ~50
        # serial requests, each able to stall for TIMEOUT (30s).
        #
        # needs_download never looks at the resolution: package sources
        # answer `kind != "values"` and RGL checks its shipped table.
        # Nothing here needs the network at all.
        for record in records:
            source = next(
                (s for s in self.matx_online_model.sources
                 if s.name == record.source),
                None,
            )
            if source is None:
                continue
            try:
                if source.needs_download(record):
                    return True
            except Exception:                          # noqa: BLE001
                return True          # unknown = assume it downloads
        return False

    def _online_source_for(self, record):
        """The Source object a record came from, and the resolution to
        fetch it at: (source, resolution, error)."""
        source = next(
            (s for s in self.matx_online_model.sources
             if s.name == record.source),
            None,
        )
        if source is None:
            return (None, None, "Unknown source %s" % record.source)
        # ASK THE SOURCE, never re-spell its answer. This read
        # `record.kind == "values"`, which is the BASE class's answer -
        # and RGL overrides it, because a uid the shipped table has
        # never seen still costs a measurement download. A values
        # source needs no resolution either way; what was wrong was
        # the claim beside it that nothing would be fetched.
        if not source.needs_download(record):
            return (source, None, "")     # nothing to download
        if record.kind == "values":
            return (source, None, "")     # downloads, but picks no package
        resolution = matx_sources.pick_resolution(
            source.resolutions(record), self.prefs.matx_resolution
        )
        if resolution is None:
            return (None, None,
                    '"%s" has no downloadable package.' % record.title)
        return (source, resolution, "")

    def _import_online_records_to_scene(self, records) -> None:
        """Build online records straight into the scene - the current LOP
        material library (or /mat) - without adding them to the library.

        The whole gesture is ONE undo step INCLUDING the destination
        resolution, which may itself create a material library: a
        material moved into a library that an undo then removes would
        have nothing coherent to undo to.
        """
        total = len(records)
        if not total:
            return
        built, failures, last = [], [], None
        with self._download_bar(records) as progress_for:
            with hou.undos.group("Amaze Import to Scene"):
                destination = nodes.karma_destination(self.prefs)
                if destination is None:
                    hou.ui.displayMessage(  # type: ignore
                        "Amaze: no place to create the material - open a "
                        "LOP or /mat network first."
                    )
                    return
                for i, rec in enumerate(records):
                    source, resolution, error = self._online_source_for(rec)
                    if error:
                        failures.append("%s: %s" % (rec.title, error))
                        continue
                    on_progress = progress_for(i)

                    try:
                        builder, reason = matx_import.build_in_scene(
                            rec, source, resolution, destination, self.prefs,
                            progress=on_progress,
                        )
                    except Exception as exc:           # noqa: BLE001
                        # One bad record must not abandon the batch:
                        # only DOWNLOAD failures come back as a reason,
                        # anything else raises.
                        debug.exception("import to scene", exc,
                                        title=rec.title)
                        builder, reason = None, str(exc)
                    if builder is None:
                        failures.append("%s: %s" % (rec.title, reason))
                        continue
                    built.append(builder.name())
                    last = builder
                if last is not None:
                    # Front the new material like any hand-created node
                    # (a menu action IS the user asking for it).
                    last.setCurrent(True, True)
        debug.event("import", "to scene finished", built=len(built),
                    failed=len(failures))
        if failures:
            hou.ui.displayMessage(  # type: ignore
                "Amaze: %d of %d could not be built:\n\n%s"
                % (len(failures), total, "\n".join(failures[:10]))
            )
        elif last is not None:
            hou.ui.setStatusMessage(  # type: ignore
                "Amaze: %s in %s" % (", ".join(built[:3]),
                                     last.parent().path())
            )


    def _select_default_sidebar_row(self, sidebar_proxy):
        """Select the sidebar's first row and return its RAW name.

        `cat_list` has no persistent selection model of its own (unlike
        thumblist), so `setModel()` in an activate always leaves it
        with nothing selected - which is why three of the four
        sidebar-bearing activates each ended with their own copy of
        this. The programmatic select does not fire clicked(), so the
        caller applies the filter explicitly, and it applies it FROM
        the row that actually got selected rather than from an
        assumption about what sorts first (a blanket "" while row 0 was
        a real category produced an "Abstract highlighted but
        everything shown" mismatch on pre-migration data).

        Materials was the one activate without it, and
        _restore_section_state only compensates while the remembered
        category TEXT is still a row: when it is not - renamed,
        removed, or hidden by the sidebar proxy while the user was in
        another tab - the material proxy kept its old CategoryRole
        filter while the sidebar highlighted nothing, so the grid was
        short or empty with no row to click to clear it.
        """
        if self.cat_list is None or sidebar_proxy is None:
            return None
        if sidebar_proxy.rowCount() <= 0:
            return None
        selection_model = self.cat_list.selectionModel()
        if selection_model is None:
            return None
        target = sidebar_proxy.index(0, 0)
        selection_model.select(
            target, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.cat_list.setCurrentIndex(target)
        return self._raw_category_name(target)

    def edit_tile_icon(self, model, proxy, proxy_indexes) -> None:
        """"Edit Icon" on any tile, in any section that has tiles.

        One handler for all of them: a library asset stores the choice
        on its record and a file row stores it in the library's
        icons.json, but both models answer tile_icon()/set_tile_icon(),
        so the panel does not need to know which kind it is holding.

        Applies to the WHOLE selection - picking one icon for twelve
        LOP setups is the case this exists for."""
        if model is None or not proxy_indexes:
            return
        # IDENTITY, not row numbers and not Qt indexes. This dialog is
        # non-modal (see below), so the library can move while it is
        # open: a save appends, a delete shifts every row after it, and
        # a RELOAD renumbers the lot. A captured row number then names
        # a different asset - and a QPersistentModelIndex does no
        # better, because endResetModel() invalidates every one of them
        # even when nothing moved (measured), and an ordinary
        # Preferences close resets the File model twice. So the tile is
        # held by the key its own model files it under.
        held = []
        rows = []
        for proxy_index in proxy_indexes:
            source = proxy.mapToSource(proxy_index) if proxy is not None \
                else proxy_index
            if not source.isValid() or source.row() in rows:
                continue
            key = model.tile_key(source.row())
            if key:
                rows.append(source.row())
                held.append(key)
        if not held:
            return

        # NON-modal, so the Custom Color button can open Houdini's own
        # picker (a native modal lands UNDER a Qt exec loop - recorded).
        # One instance at a time: a second Edit Icon while one is open
        # fronts the existing dialog instead of stacking another.
        existing = getattr(self, "_icon_dialog", None)
        if existing is not None:
            try:
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                pass                      # already deleted underneath
        # The Name field rides along (2026-08-01): sections whose
        # model can rename get one, greyed on a multi-selection per
        # the selection law. File has no rename - a file's name is the
        # file on disk - so its dialog shows no field at all.
        single = len(rows) == 1
        tile_name = None
        if hasattr(model, "set_tile_name"):
            tile_name = model.tile_name(rows[0]) if single else ""
        dialog = icon_dialog.IconDialog(
            model.tile_icon(rows[0]),
            tile_icons.stroke_for(self.prefs),
            self,
            tile_name=tile_name,
            tile_name_enabled=single,
        )
        self._icon_dialog = dialog

        def _finished(_result=0, dialog=dialog, held=frozenset(held),
                      model=model):
            self._icon_dialog = None
            try:
                if not dialog.canceled:
                    # Resolved HERE, not at open: where the held tiles
                    # are NOW. One scan of the model, once, on OK. A
                    # tile that went away during the dialog simply is
                    # not found.
                    rows = [row for row in range(model.rowCount())
                            if model.tile_key(row) in held]
                    if not rows:
                        return
                    self._apply_icon_spec(model, rows, dialog.spec)
                    new_name = getattr(dialog, "new_tile_name", None)
                    if new_name and len(rows) == 1 and \
                            hasattr(model, "set_tile_name"):
                        model.set_tile_name(rows[0], new_name)
            finally:
                # The panel is its C++ parent and outlives every
                # dialog, so dropping the Python name frees nothing:
                # 287 buttons and ~6.5MB stay alive per open otherwise.
                dialog.deleteLater()

        dialog.finished.connect(_finished)
        dialog.show()
        return

    def _apply_icon_spec(self, model, rows, spec) -> None:

        # ONE save for the whole selection. set_tile_icon saves the
        # index per call, and the case this exists for is "twelve LOP
        # setups at once" - twelve full database writes of a
        # cloud-synced file, ~10ms each, and Ctrl-A over 546 materials
        # would freeze the panel for five seconds.
        failed = 0
        for row in rows:
            if not model.set_tile_icon(row, spec, save=False):
                failed += 1
        model.commit_tile_icons(rows)
        if failed:
            # A real plural, not "icon(s)". This one is a MODAL the user
            # cannot look away from, so the fake plural was the most
            # visible instance of it in the product.
            hou.ui.displayMessage(  # type: ignore
                "%d tile icon%s could not be saved - check that the "
                "library folder is writable."
                % (failed, "" if failed == 1 else "s")
            )


    def import_cop_assets(self) -> None:
        """Import every selected Nodes-section asset, reporting failures
        in one summary dialog (same shape as the material importer)."""
        failures = []
        # One user action, one undo - the drag path already groups; this
        # one built a container and loaded into it as separate entries,
        # so a single Ctrl+Z left the empty container behind.
        with hou.undos.group("Amaze Import Nodes Asset"):
            for index in grid_columns.selected_rows(
                    self.thumblist.selectionModel()):
                source_index = self.cop_sorted_model.mapToSource(index)
                try:
                    ok, reason, _created = self.cop_model.import_asset_to_scene(
                        source_index)
                except Exception as e:
                    try:
                        name = self.cop_model.assets[source_index.row()].name
                    except Exception:
                        name = "node asset"
                    failures.append(f'"{name}" failed to import: {e}')
                    continue
                if not ok and reason:
                    failures.append(reason)
        if failures:
            hou.ui.displayMessage(  # type: ignore
                "Some node assets could not be imported:\n\n"
                + "\n".join(failures)
            )

    # ------------------------------------------------------------------
    # Code section
    # ------------------------------------------------------------------

    def get_code_category_names(self) -> list[str]:
        return self._category_names_from(self.code_category_model)

    def _current_code_category(self) -> str:
        """The category selected in the sidebar when the Code section is
        showing, "" for All - the save/new dialog's default category."""
        if self.current_section != "code":
            return ""
        return self._selected_category_name()

    def _add_code_snippet(
        self, code: str, language: str, default_name: str
    ) -> None:
        """Shared save flow for both Save-from-Node and New Snippet:
        open the Code dialog prefilled, then register the snippet."""
        if not self.code_model:
            hou.ui.displayMessage(  # type: ignore
                "Please set a library first. Use the %s panel - "
                "Library/Open Dialog." % branding.APP_NAME
            )
            return
        dialog = code_dialog.CodeDialog(
            self.get_code_category_names(),
            name=default_name,
            language=language or "VEX",
            category=self._current_code_category(),
            code=code,
        )
        dialog.exec_()
        if dialog.canceled:
            return
        if dialog.category:
            self.code_category_model.check_add_category(dialog.category)
        # No layout wrapper: add_asset announces itself with
        # begin/endInsertRows, and pairing the two segfaults H21.
        self.code_model.add_asset(
            dialog.code,
            dialog.name,
            dialog.language,
            dialog.category,
            dialog.tags,
            False,
            dialog.description,
        )
        self._refresh_sidebar_categories()

    def save_code_from_node(self, node: hou.Node | None = None) -> None:
        """Node right-click "Save Code to <app>": grab the node's
        code/snippet parm and open the save dialog prefilled."""
        if node is None:
            sel = hou.selectedNodes()
            node = sel[0] if len(sel) == 1 else None
        if node is None:
            hou.ui.displayMessage(  # type: ignore
                "Right-click a wrangle (or other node with a code "
                "parameter) to save its snippet."
            )
            return
        parm = helpers.find_code_parm(node)
        if parm is None:
            hou.ui.displayMessage(  # type: ignore
                '"%s" has no code/snippet parameter.' % node.name()
            )
            return
        self._add_code_snippet(
            parm.eval(),
            helpers.code_parm_language(parm),
            node.name(),
        )

    def new_code_snippet(self) -> None:
        """Create a snippet by typing/pasting into an empty editor."""
        self._add_code_snippet("", "VEX", "")

    # ---- THE CLICK WALKER --------------------------------------
    #
    # The second half of the interaction engine (ROADMAP - the matrix;
    # sections.DropRule carries the declarations). It replaced FIVE
    # hand-written double-click handlers that answered one question
    # five ways: three carried a selection VETO (a selected node that
    # could not take the payload refused instead of creating) and two
    # never consulted the selection at all. The drag walker has read
    # these same declarations since the behaviour table shipped; this
    # is the aiming method it was always missing.

    def click_on_row(self, section, index, payload=None) -> None:
        """A click door on `index` in `section` - aimed by the
        SELECTION, executed from the section's own declaration.

        BOTH DOORS COME THROUGH HERE: the double-click, and the menu
        entry labelled with the same verb. They used to be two
        implementations of one policy and they disagreed - the menu
        side treated a selection as a VETO, which is the bug the
        precedence below was written to remove, so the same tile with
        the same selection created a node on double-click and showed
        a modal refusal from the menu.

        `payload` is the menu's extra word where an entry carries one
        (Color's Apply as names a ramp basis); it reaches only the
        verbs that declare they take it.
        """
        if index is None or not index.isValid():
            return
        # THE DRAG WALKER'S READER, not a second one. These four lines
        # were written here and again in `dragdrop_widgets._drop_rule`,
        # so the two doors read one declaration twice - the shape this
        # walker exists to end.
        rule = sections.drop_rule(section, self, index)
        if rule is None:
            self._cannot_load_here()
            return
        try:
            with helpers.preserving_selection_and_current():
                landed = self._apply_click_rule(rule, index, payload)
        except hou.PermissionError as refusal:
            # HOUDINI REFUSING IS NOT A BUG - the same absorption the
            # drag dispatch carries (dragdrop_widgets, drop refused):
            # a click into a locked network gets Houdini's own
            # sentence in the status bar, a log record, and no slot
            # crash. Only this class; a genuine defect still raises.
            debug.exception("click refused", refusal,
                            section=getattr(section, "key", ""))
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.setStatusMessage(
                    "Amaze: %s" % refusal,
                    severity=hou.severityType.Warning,
                )
            return
        if not landed:
            self._cannot_load_here()

    def _apply_click_rule(self, rule, index, payload=None) -> bool:
        """ONE precedence for every section's click door.

        THE SELECTION IS A HINT, NOT A VETO. A single visible selected
        node is offered the payload first, and a node that cannot take
        it FALLS THROUGH to the creation walk - the host's own rule
        (the manual's tab-menu flow: a selection never blocks a
        creation; wiring to the current node is a separate, explicit
        gesture). The veto is what made a double-click refuse whenever
        anything happened to be selected, which in Houdini is almost
        always.
        """
        # The menu's extra word, handed on ONLY when there is one, so
        # no verb ever sees a keyword it does not declare.
        extra = {"basis": payload} if payload else {}
        sel = self._visible_selected_nodes()
        if rule.click_on_node and len(sel) == 1:
            if bool(getattr(self, rule.click_on_node)(index, sel[0],
                                                      **extra)):
                return True
            debug.event("interact", "click hint declined - falling "
                        "through to the network",
                        verb=rule.click_on_node, node=sel[0].path())
        if rule.click_resolve:
            return bool(getattr(self, rule.click_resolve)(index, **extra))
        if rule.on_space:
            for network in self._view_create_networks():
                if getattr(self, rule.on_space)(index, network, **extra):
                    return True
        return False

    # ---- the click-door verbs the declarations name ---------------

    def click_import_material(self, _index) -> bool:
        """Materials aim themselves - the context-aware import reads
        the selection and the network under the cursor."""
        self.import_asset("auto")
        return True

    def click_import_cop(self, _index) -> bool:
        self.import_cop_assets()
        return True

    def click_import_geo(self, index) -> bool:
        self.import_geo_asset(index)
        return True

    def click_open_hip(self, index) -> bool:
        self.open_hip_scene(index)
        return True

    def click_copy_path(self, index) -> bool:
        """An unknown file has no scene behaviour - its one action."""
        self.copy_file_paths([index])
        return True

    def _edit_code_row(self, row: int) -> None:
        asset = self.code_model.assets[row]
        dialog = code_dialog.CodeDialog(
            self.get_code_category_names(),
            name=asset.name,
            language=asset.renderer,
            category=asset.categories[0] if asset.categories else "",
            tags=", ".join(asset.tags),
            code=asset.code,
            description=asset.description,
            title="Edit Snippet",
        )
        dialog.exec_()
        if dialog.canceled:
            return
        if dialog.category:
            self.code_category_model.check_add_category(dialog.category)
        with ui_helpers.relayout(self.code_model,
                                 self.code_category_model):
            self.code_model.update_asset(
                row, dialog.code, dialog.name, dialog.language,
                dialog.category, dialog.tags, dialog.description,
            )
        self._refresh_sidebar_categories()

    def get_cop_category_names(self) -> list[str]:
        return self._category_names_from(self.cop_category_model)

    def save_cop_from_node(self, node: hou.Node | None = None) -> None:
        """Node right-click "Save Network/Selection to <app>"
        (rc_calls.save_cop passes the clicked node through). Works in
        any context the Nodes section supports - SOP, COP, LOP and the
        rest; the asset records which one.
        v1 keeps standard-new semantics only - no Overwrite flow yet."""
        if not self.cop_model:
            hou.ui.displayMessage(  # type: ignore
                "Please set a library first. Use the %s panel - "
                "Library/Open Dialog." % branding.APP_NAME
            )
            return
        if node is None:
            sel = hou.selectedNodes()
            node = sel[0] if len(sel) == 1 else None
        if node is None:
            hou.ui.displayMessage(  # type: ignore
                "Right-click the network - or the nodes - you want to save."
            )
            return
        # Container vs selection. Right-clicking a network container on
        # its own (a geo, a copnet, a lopnet, a subnet) saves the WHOLE
        # network; anything else saves the selection inside the network
        # that holds it, named after the clicked node.
        #
        # A multi-selection wins over the container reading: two geos
        # selected means those two nodes, not one of their interiors.
        net = node.parent()
        items = [i for i in hou.selectedItems() if i.parent() == net]
        if not any(i == node for i in items):
            items.append(node)
        if len(items) == 1 and self.cop_model.saves_whole_network(node):
            items = None

        # Pre-select the category active in the panel when the Cop
        # section is showing (mirrors the material save dialog).
        current_cat = ""
        if self.current_section == "cop":
            current_cat = self._selected_category_name()

        dialog = usd_dialog.UsdDialog(
            self.get_cop_category_names(), current_cat, name=node.name()
        )
        r = dialog.exec_()
        if dialog.canceled or not r:
            return
        if dialog.categories:
            self.cop_category_model.check_add_category(dialog.categories)
        if dialog.tags:
            self.cop_model.check_add_tags(dialog.tags)

        result = None
        save_error = None
        # NO LAYOUT WRAPPER. add_asset announces itself with
        # begin/endInsertRows, and pairing the two segfaults H21
        # (research.md, measured 2026-08-04) - which is also why the
        # hand-written `finally` this carried is gone rather than
        # becoming a context manager: there is no longer a pair to
        # close.
        try:
            result = self.cop_model.add_asset(
                node,
                dialog.categories,
                dialog.tags,
                dialog.fav,
                items=items,
                name=dialog.name,
            )
        except Exception as exc:                        # noqa: BLE001
            debug.exception("save_cop_from_node", exc, node=node.path())
            save_error = str(exc)
        if save_error is not None:
            hou.ui.displayMessage(  # type: ignore
                '"%s" could not be saved: %s' % (node.name(), save_error)
            )
            return
        if not result:
            hou.ui.displayMessage(  # type: ignore
                '"%s" could not be saved.' % node.name()
            )

    def _active_network_pwd(self) -> hou.Node | None:
        """The network the user is most likely looking at: the visible
        (current-tab) network editor's pwd, falling back to any open
        editor - the same preference get_active_network_editor uses on
        the material side."""
        editors = [
            pt
            for pt in hou.ui.paneTabs()  # type: ignore
            if pt.type() == hou.paneTabType.NetworkEditor
        ]
        if not editors:
            return None
        visible = [e for e in editors if e.isCurrentTab()]
        try:
            return (visible or editors)[0].pwd()
        except AttributeError:
            return None

    @staticmethod
    def _is_sop_container(node: hou.Node) -> bool:
        """True for anything whose children are SOPs - a geo object, a
        SOP Create LOP, a plain sopnet - i.e. a valid drop-INTO target
        for a geometry file."""
        try:
            category = node.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return False
        return category is not None and category.name() == "Sop"

    @staticmethod
    def _create_loader_inside(container: hou.Node, loader_type: str):
        """Create the loader in the DEEPEST SOP network in/under the
        container, falling outward on failure. A SOP Create LOP is a
        locked HDA whose EDITABLE network sits at sopcreate/sopnet/
        create - picking the first SOP-children network found landed on
        the locked middle level and raised hou.PermissionError
        ("Cannot create a node inside a locked asset", from a live log),
        so depth-first-preference plus try-per-candidate is the robust
        form: whichever level actually accepts the node wins."""
        candidates = []

        def walk(node, depth):
            try:
                category = node.childTypeCategory()
            except (AttributeError, hou.OperationFailed):
                category = None
            if category is not None and category.name() == "Sop":
                candidates.append((depth, node))
            if depth < 3:
                for child in node.children():
                    walk(child, depth + 1)

        walk(container, 0)
        last_error = None
        for _depth, net in sorted(candidates, key=lambda c: -c[0]):
            try:
                return net.createNode(loader_type)
            except hou.Error as exc:
                last_error = exc
        raise last_error or hou.OperationFailed("no SOP network found")

    def import_geo_asset(self, index: QtCore.QModelIndex) -> None:
        """Double-click/right-click import for a geometry file -
        CONTEXT-AWARE (per spec): in an OBJ network, a new geo
        named after the file with the right loader SOP inside; already
        inside a SOP network (a geo node's innards, a SOP Create's), a
        new loader SOP in place; in a LOP network, a new SOP Create
        holding the loader - geometry lives directly in the stage,
        never as stray /obj exports. The drag imports the same way at
        the release point (drop_geo_at_release)."""
        path = index.data(self.file_files_model.PathRole)
        if not path:
            return
        # WRAPPED HERE, not at each caller. Every other scene-importing
        # verb preserves what it disturbed and this one did not, so a
        # menu Import moved the artist's current node and display flag
        # with no way back. Putting it on the verb rather than on the
        # menu entry means the door, the drag and any later caller
        # inherit it instead of having to remember.
        with helpers.preserving_selection_and_current():
            self._import_geo_in_context(path, self._active_network_pwd())

    def _import_geo_in_context(
        self, path: str, dest: hou.Node | None
    ) -> hou.Node | None:
        base = os.path.basename(path)
        name = helpers.sanitize_usd_path(os.path.splitext(base)[0]) or "geo"
        loader_type = geo_library.loader_sop_for(path)

        category = ""
        if dest is not None:
            try:
                cat_obj = dest.childTypeCategory()
                category = cat_obj.name() if cat_obj is not None else ""
            except (AttributeError, hou.OperationFailed):
                category = ""

        container = None  # created here; cleaned up if the import fails
        try:
            if category == "Sop":
                loader = dest.createNode(loader_type)
            elif category == "Lop":
                # Chain it onto the current tree, the way Houdini's own
                # tab menu does when you add a light or a render node:
                # createOutputNode() is that built-in, wiring the new
                # node to the display node's output. Falls back to a
                # loose node in an empty stage.
                anchor = None
                try:
                    anchor = dest.displayNode()
                except (AttributeError, hou.OperationFailed):
                    anchor = None
                if anchor is not None:
                    container = anchor.createOutputNode("sopcreate", name)
                else:
                    container = dest.createNode("sopcreate", name)
                loader = self._create_loader_inside(container, loader_type)
            elif category == "Object":
                container = dest.createNode("geo", name)
                loader = container.createNode(loader_type)
            else:
                # Not a network that can hold geometry (mat/cop/...):
                # fall back to a fresh geo at /obj, the old behavior.
                obj = hou.node("/obj")
                if obj is None:
                    raise hou.OperationFailed("no /obj network")
                container = obj.createNode("geo", name)
                loader = container.createNode(loader_type)
        # hou.Error, NOT just OperationFailed: the locked-asset case
        # raises hou.PermissionError (a SIBLING class) - catching too
        # narrowly turned the failure into a silent traceback with a
        # dead sopcreate left in the scene.
        except hou.Error as exc:
            if container is not None:
                try:
                    container.destroy()
                except (hou.OperationFailed, hou.ObjectWasDeleted):
                    pass
            debug.event("import", "geometry import failed",
                        file=base, error=str(exc))
            hou.ui.displayMessage(  # type: ignore
                f"Could not import {base}: {exc}"
            )
            return
        parm = helpers.find_file_parm(loader)
        if parm is None:
            try:
                (container or loader).destroy()
            except (hou.OperationFailed, hou.ObjectWasDeleted):
                pass
            hou.ui.displayMessage(  # type: ignore
                f'The "{loader_type}" SOP has no file parameter to set.'
            )
            return
        parm.set(self._scene_path(path))
        try:
            loader.setName(name, unique_name=True)
        except hou.OperationFailed:
            pass
        loader.setDisplayFlag(True)
        try:
            loader.setRenderFlag(True)
        except AttributeError:
            pass
        helpers.auto_place(loader)
        if container is not None:
            helpers.auto_place(container)
            # What you just added is what you want to see. createOutput
            # Node wires but does not flag, so a Solaris import would
            # otherwise land downstream of the display node and show
            # nothing.
            try:
                container.setDisplayFlag(True)
            except (AttributeError, hou.Error):
                pass
        # The import seam: the caller receives what was created - the
        # container when one was built, else the loader itself.
        return container or loader

    def drop_geo_at_release(self, index: QtCore.QModelIndex) -> bool:
        """Geometry drag released: import in context at the release
        point - on a SOP-capable node (geo, SOP Create) the loader
        lands inside it; an OBJ network gets a new geo; a LOP network
        a new SOP Create. Release over nothing is silent - a miss is a
        normal drag outcome, not an error."""
        context = self._drop_context_under_cursor(
            self._is_sop_container, include_viewports=True
        )
        if context is None:
            return False
        path = index.data(self.file_files_model.PathRole)
        if not path:
            return False
        with hou.undos.group("Amaze Import Geometry"):
            created = self._import_geo_in_context(path, context)
        if created is not None:
            helpers.place_nodes([created],
                                self._release_position_in(context))
        return True




    @staticmethod
    def _entry_ramp(entry: dict, basis: str = "") -> hou.Ramp:
        # An explicit basis rebuilds the ramp from the gradient's
        # colours on that one interpolation; otherwise the recorded
        # ramp (bases/keys/values) applies exactly as saved.
        if basis:
            return helpers.build_basis_ramp(
                [c["hex"] for c in entry["colors"]], basis)
        ramp = entry.get("ramp")
        if ramp:
            return helpers.data_to_ramp(ramp)
        return helpers.build_stepped_ramp([c["hex"] for c in entry["colors"]])


    def _copy_gradient_swatch(self, color: dict) -> None:
        """Put one swatch's hex code on the system clipboard.

        Deliberately not an assignment: a material carries many colour
        inputs (base, specular, coat, emission, subsurface...), so
        choosing one for the user was a guess. A hex code pastes into
        the input they meant - Houdini's own colour fields accept it,
        and so does every other application."""
        hex_code = str(color.get("hex", "")).strip()
        if not hex_code:
            return
        if not hex_code.startswith("#"):
            hex_code = "#" + hex_code
        hex_code = hex_code.upper()
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is None:
            return
        clipboard.setText(hex_code)
        debug.event("gradient", "colour copied",
                    name=color.get("name"), hex=hex_code)
        hou.ui.setStatusMessage(  # type: ignore
            "Amaze: copied %s (%s)" % (hex_code, color.get("name", ""))
        )

    def _drop_context_under_cursor(
        self, matcher, include_viewports: bool = False
    ) -> hou.Node | None:
        """Resolve where a drag was RELEASED, for drops Houdini's native
        handling ignores: network editors (the canvas takes no native
        node drops - DRAGTEST log, 2026-07-19). Returns the node to
        import against - the node under the cursor when it matches
        (matcher = a type-name substring like "materiallibrary"/
        "copnet", or a callable(node) -> bool, e.g. geometry's
        SOP-container test), else the editor's own pwd (which is itself
        the target when the user is working inside one).

        include_viewports (geometry drops): a release over a Scene
        Viewer resolves to the network the VIEWPORT is showing (its
        pwd - /obj for the object view, /stage for the Solaris view, a
        geo node's innards at SOP level), so the same context rules
        apply as everywhere else. Materials deliberately keep this off:
        their viewport releases are the Drag Engine's own
        (viewport_release_target picks the actual prim/node under the
        cursor), so resolving a network here would double-handle them.

        None = the release wasn't over anything import-worthy."""
        pane_tab = dragengine.pane_tab_under_cursor()
        if pane_tab is None:
            return None
        try:
            pane_type = pane_tab.type()
        except AttributeError:
            return None
        if (
            include_viewports
            and pane_type == hou.paneTabType.SceneViewer
        ):
            try:
                return pane_tab.pwd()
            except AttributeError:
                return None
        if pane_type != hou.paneTabType.NetworkEditor:
            return None
        node = None
        for item in self._network_items_at_cursor(pane_tab):
            candidates = (
                item if isinstance(item, (tuple, list)) else (item,)
            )
            for candidate in candidates:
                if isinstance(candidate, hou.Node):
                    node = candidate
                    break
            if node is not None:
                break
        if node is not None:
            hit = (
                matcher(node)
                if callable(matcher)
                else matcher in node.type().name()
            )
            if hit:
                return node
        try:
            return pane_tab.pwd()
        except AttributeError:
            return None

    def drop_cop_at_release(self, index) -> bool:
        """Nodes drag released: same context rules as double-click, but
        against the network editor under the RELEASE POINT - released
        ON a network container (a geo, a copnet, a lopnet...) or INSIDE
        one, the saved nodes load directly into it; any other network
        gets a fresh container. An asset whose context doesn't match
        where it landed is refused with a message rather than half
        created. A release over nothing is silent - a miss is a normal
        drag outcome, not an error."""
        if not self.cop_model:
            return False
        if index is None or not index.isValid():
            # A drag armed on EMPTY grid space arrives here with an
            # invalid index; mapToSource() would return row -1, which
            # Python-indexes to the LAST asset in the model.
            return False
        context = self._drop_context_under_cursor(self.cop_model.is_container)
        if context is None:
            return False
        try:
            source_index = self.cop_sorted_model.mapToSource(index)
        except Exception:
            return False
        with hou.undos.group("Amaze Import COP Network"):
            ok, reason, created = self.cop_model.import_asset_to_scene(
                source_index, context_node=context
            )
        if not ok and reason:
            hou.ui.displayMessage(reason)  # type: ignore
        if ok:
            helpers.place_nodes(created,
                                self._release_position_in(context))
        return True

    def _import_material_builder(self, asset_id, target, context_node=None):
        """One import shape for every release bridge: import a library
        material by id, report failures, return the builder VOP or
        None. Creation happens at the drop, nowhere before."""
        if not self.material_model:
            return None
        row = self.material_model.find_asset_row_by_id(str(asset_id))
        if row < 0:
            return None
        mat = self.material_model.assets[row]
        handler = nodes.NodeHandler(self.prefs)
        ok, reason, _created = handler.import_asset_to_scene(
            mat, target, context_node=context_node
        )
        if not ok:
            # Every failed import leaves a NAMED reason in the log -
            # an "imported: 0" with nothing beside it once cost a
            # debugging round.
            debug.event("import", "import failed",
                        material=mat.name, target=target,
                        reason=reason or "(no reason reported)")
            if reason:
                hou.ui.displayMessage(reason)  # type: ignore
            return None
        return handler.builder_node

    def import_material_into_container(self, asset_id, container):
        """LOP-release bridge: import into the given materiallibrary."""
        return self._import_material_builder(
            asset_id, "lop", context_node=container
        )

    def assign_material_to_obj(self, asset_ids, obj_node) -> bool:
        """OBJ-viewport release: import to /mat - the OBJ world's
        home - and assign the FIRST material to the picked object;
        extra selected materials import beside it unassigned."""
        if not self.material_model or not asset_ids:
            return False
        builder = None
        for i, aid in enumerate(asset_ids):
            vop = self._import_material_builder(aid, "mat")
            if i == 0 and vop is not None:
                builder = vop
        if builder is None:
            return False
        parm = obj_node.parm("shop_materialpath")
        if parm is None:
            hou.ui.displayMessage(  # type: ignore
                "'%s' has no material parameter - imported to /mat "
                "without assigning." % obj_node.name()
            )
            return False
        parm.set(builder.path())
        return True

    def _selected_material_ids(self, index) -> list:
        """Asset ids of the selection, the pressed tile first."""
        # isValid() does NOT catch a stale row: a proxy index built when
        # the model was longer still reports valid, and mapToSource then
        # returns row -1 - which indexes assets[] from the END and hands
        # back the WRONG material silently, or raises IndexError on an
        # empty library, inside a release slot. drop_cop_at_release
        # already guards this; the material path did not. (Reachable
        # mainly through a gesture that outlived a refresh or a section
        # switch - which is why this and the press-state leak compose so
        # badly.)
        row = self.material_sorted_model.mapToSource(index).row()
        if not 0 <= row < len(self.material_model.assets):
            return []
        pressed_id = self.material_model.assets[row].mat_id
        ids = [pressed_id]
        try:
            for sel in grid_columns.selected_rows(
                    self.material_selection_model):
                src_row = self.material_sorted_model.mapToSource(sel).row()
                if not 0 <= src_row < len(self.material_model.assets):
                    continue      # same stale-row trap, per selected row
                aid = self.material_model.assets[src_row].mat_id
                if aid != pressed_id:
                    ids.append(aid)
        except Exception:
            pass
        return ids

    def drop_material_at_release(self, index) -> bool:
        """Material drag released (Drag & Drop Engine gesture). THE
        LAW: the drop lands where it was dropped, and nothing was
        created before this moment.

        - LOP viewport: ancestor-prim menu, import into a material-
          library in THAT stage (stock resolution), assign with
          Houdini's own stock helper. Never /mat.
        - OBJ viewport: import to /mat and assign to the picked object
          directly (the native OBJ behavior has no menu).
        - Network editor: import into the network under the cursor.
        - Anything else: a miss, silent.

        Returns True when the release hit an actionable target, False
        for a miss, and "menu" when a menu carried the interaction -
        the drag widgets map this to the outcome icon (loader / X /
        nothing)."""
        if not self.material_model or index is None or not index.isValid():
            return False
        ids = self._selected_material_ids(index)
        target = dragengine.viewport_release_target(self)
        if target is not None:
            kind, viewer, data = target
            debug.event("drag", "material release", target=kind,
                        data=str(data), count=len(ids))
            if kind == "lop":
                if not data:
                    # Empty viewport space: no prim picked = a MISS,
                    # not an import offer.
                    return False
                shown = self._material_lop_viewport_drop(ids, viewer, data)
                # The menu IS the feedback on this path - no outcome
                # icon on top of it, chosen or dismissed alike.
                #
                # But "menu" was returned unconditionally, and
                # _material_lop_viewport_drop returns False in three
                # cases where NO menu was ever shown: no stock LOP
                # helper, a viewer whose pwd() failed, and - the
                # reachable one - no choices at all, which happens on a
                # stale prim path or a display node whose cook failed.
                # _finish_preview reads "menu" as "suppress the miss
                # icon", so the user dropped on a visible object and got
                # nothing whatsoever: no menu, no red X, no message.
                return "menu" if shown is not False else False
            if kind == "obj" and data is not None:
                with hou.undos.group("Amaze Assign Material"), \
                        dragengine.keep_editor_focus():
                    # Propagated, not discarded: assign_material_to_obj
                    # returns False when the picked object has no
                    # shop_materialpath, and a hard True here showed the
                    # success feedback for an assignment that did not
                    # happen.
                    return bool(self.assign_material_to_obj(ids, data))
            return False
        context = self._drop_context_under_cursor("materiallibrary")
        if context is None:
            debug.event("drag", "material release", target="miss")
            return False
        debug.event("drag", "material release", target="network",
                    context=context.path(), count=len(ids))
        position = self._release_position_in(context)
        self._import_materials_into_context(context, ids, position)
        return True

    def _material_lop_viewport_drop(self, ids, viewer, primpath) -> bool:
        """LOP-viewport release: our ancestor-prim menu, then import
        into a materiallibrary resolved by Houdini's STOCK helper and
        assign with its stock assignMat - SideFX semantics, Amaze law."""
        stock = dragengine.stock_lop()
        if stock is None:
            hou.ui.displayMessage(  # type: ignore
                "Amaze: could not load Houdini's material-assignment "
                "helpers - material not imported."
            )
            return False
        try:
            lopnet = viewer.pwd()
        except AttributeError:
            return False
        target_lop = lopnet.displayNode()
        if target_lop is None:
            children = lopnet.children()
            target_lop = children[-1] if children else None

        stage = target_lop.stage() if target_lop is not None else None
        # WHAT to offer is USD reasoning and lives in core/lop_assign;
        # this only renders it. No "Import only" entry: a drop aimed at
        # a specific object always means assign - network drops are the
        # import-only path.
        choices = lop_assign.drop_choices(stage, primpath)
        if not choices:
            return False
        cmenu = QtWidgets.QMenu(self)
        actions = {}
        previous_kind = None
        for kind, label, payload in choices:
            if previous_kind == "swap" and kind != "swap":
                cmenu.addSeparator()
            actions[cmenu.addAction(label)] = (kind, payload)
            previous_kind = kind
        chosen = cmenu.exec_(QtGui.QCursor.pos())
        # A QMenu parented to the panel outlives the gesture, and the
        # panel outlives the session - the same measured leak
        # `grid._open` pays a `deleteLater()` for (twenty right-clicks,
        # forty live menus). Read the choice out FIRST: the dict is
        # keyed by the menu's own QActions.
        cmenu.deleteLater()
        if chosen is None:
            # Menu dismissed - nothing happens. No outcome icon either
            # way: the dispatcher reports "menu" for this whole path
            # (the menu itself was the feedback).
            return False
        kind, payload = actions[chosen]
        assign_path = payload if kind == "assign" else None
        swap_targets = payload if kind == "swap" else None
        # The undo group opens HERE, before the container policy -
        # not just around the import. Creating the materiallibrary,
        # wiring it, moving it and moving the display flag all ran
        # OUTSIDE the group, so one Ctrl+Z undid the assignment and
        # the VOP and left an EMPTY materiallibrary wired into the
        # display chain, with the display flag still moved. Verified
        # through hou.undos.undoLabels(): a second entry labelled
        # "hou.Node.createNode" sat behind ours in the Edit menu, and
        # that orphan library is what the container policy then picks
        # up for every later drop in the network.
        undo_label = (
            "Amaze Swap Material" if swap_targets is not None
            else "Amaze Assign Material"
        )
        with hou.undos.group(undo_label), dragengine.keep_editor_focus():
            # CONTAINER POLICY (the anti-clutter rule): the network's FIRST
            # existing materiallibrary takes every drop; only a library-less
            # network gets a new one. Assignments reuse the network's first
            # existing assignmaterial the same way - repeated drops converge
            # on ONE library and ONE assign node instead of scattering pairs.
            # Viewport drops prefer a library IN THE DISPLAY CHAIN (an
            # assignment into a disconnected one silently does not
            # display), then any first, then create WIRED into the chain -
            # the placement law: viewport-created libraries join the
            # display; network-created ones stay unwired.
            liblop = dragengine.first_materiallibrary(
                lopnet, connected_to=target_lop
            )
            if liblop is None and not (assign_path or swap_targets):
                # The unconditional fallback is only safe when nothing
                # is going to be ASSIGNED. With an assignment pending,
                # an unwired leftover library silently does not display
                # - the comment above says so - and taking it means the
                # material imports, the binding is written, and the
                # viewport does not change. Better to create one wired
                # into the chain (below).
                liblop = dragengine.first_materiallibrary(lopnet)
            created = False
            if liblop is None:
                try:
                    liblop = lopnet.createNode("materiallibrary")
                    if target_lop is not None:
                        liblop.setInput(0, target_lop)
                    helpers.auto_place(liblop)
                    liblop.setDisplayFlag(True)
                    created = True
                except hou.Error as refusal:
                    # hou.Error, NOT hou.OperationFailed: a locked
                    # digital asset answers `Cannot create a node
                    # inside a locked asset` as hou.PermissionError,
                    # which is a SIBLING of OperationFailed and went
                    # straight past this handler - 12 tracebacks in the
                    # real log, over two days and one code move, with
                    # this message sitting one line away unreachable.
                    # The network-drop path already catches it this way
                    # (research.md > hou.PermissionError is a SIBLING).
                    debug.event("drag", "the network refused a material "
                                "library", dest=lopnet.path(),
                                error=str(refusal))
                    hou.ui.displayMessage(  # type: ignore
                        "Amaze: %s cannot take a Material Library, so "
                        "the material was not imported.\n\n%s"
                        % (lopnet.name(), refusal)
                    )
                    return False
            # Prefer one in the display chain, exactly as the library lookup
            # above does. Unfiltered, this took the first assignmaterial in
            # CREATION order, so a leftover disconnected one won over the
            # live node: the material imported and the binding was written
            # where nothing displays it, silently.
            assign_node = dragengine.find_assignmaterial(
                lopnet, connected_to=target_lop
            ) or dragengine.find_assignmaterial(lopnet)
            # stock.assignMat REUSES an assignmaterial passed as the node
            # (multiparm dedupe); anything else makes it create a fresh one
            # chained onto what we pass. That anchor must sit AT OR BELOW
            # the library: chaining onto the old display node when the
            # library was JUST created put the assign in a parallel branch
            # UPSTREAM of its own material (live bug report).
            if assign_node is not None:
                node2 = assign_node
            elif created:
                node2 = liblop
            else:
                node2 = target_lop if target_lop is not None else liblop
            if swap_targets is not None:
                # A swap replaces ONE material - importing the rest of a
                # multi-selection would recreate the dead-material pile the
                # swap exists to prevent.
                ids = list(ids)[:1]
            vops = []
            # PAIRED with their asset id: vops[0] was assumed to be the
            # pressed tile, but the list only collects SUCCESSFUL
            # imports - so if the pressed material failed (a missing
            # plugin or node type, a real reported class), vops[0] was a
            # DIFFERENT material and that is what got assigned, with no
            # warning.
            imported = []
            for aid in ids:
                vop = self.import_material_into_container(aid, liblop)
                if vop is not None:
                    imported.append((aid, vop))
                    vops.append(vop)
            pressed_vop = None
            if imported and ids and imported[0][0] == ids[0]:
                pressed_vop = imported[0][1]
            elif imported:
                hou.ui.displayMessage(  # type: ignore
                    "The material you dropped could not be imported, so "
                    "nothing was assigned. The others in the selection "
                    "were still added to the library."
                )
            debug.event("drag", "lop viewport drop", imported=len(vops),
                        amaze=liblop.path(), assign=str(assign_path),
                        swap=bool(swap_targets))
            if pressed_vop is not None and swap_targets is not None:
                # The module does the USD and REPORTS; the panel owns
                # the dialog (it is the half with a screen).
                reason = lop_assign.swap_assignments(
                    stock, lopnet, liblop, node2, swap_targets,
                    pressed_vop
                )
                if reason:
                    hou.ui.displayMessage("Amaze: " + reason)  # type: ignore
            elif assign_path and pressed_vop is not None:
                try:
                    matpath = stock.getMaterialPrimPathForNode(
                        liblop, pressed_vop
                    )
                    before = {
                        n for n in lopnet.children()
                        if n.type().name() == "assignmaterial"
                    }
                    stock.assignMat(assign_path, str(matpath), node2)
                    lop_assign.name_new_assign(lopnet, before, assign_path)
                except Exception as exc:
                    debug.event("drag", "lop assign failed", error=str(exc))
                    hou.ui.displayMessage(  # type: ignore
                        "Amaze: imported, but assigning failed: %s" % exc
                    )
        return bool(vops)





    def _import_materials_into_context(self, context, ids,
                                       position=None) -> None:
        """Network-release import for the material section. One undo
        group: the whole multi-drop reverts as one step. Placement
        rides the import seam - the import RETURNS what it created
        and `helpers.place_nodes` is the one placement rule - so a
        position lands each copy at the release point, a multi-drop
        cascading from it."""
        with hou.undos.group("Amaze Import Materials"):
            self._import_materials_into_context_grouped(
                context, ids, position)

    def _import_materials_into_context_grouped(self, context, ids,
                                               position=None) -> None:
        for offset, aid in enumerate(ids):
            row = self.material_model.find_asset_row_by_id(aid)
            if row < 0:
                continue
            idx = self.material_model.index(row, 0)
            ok, reason, created = self.material_model.import_asset_to_scene(
                idx, "auto", context_node=context
            )
            if not ok and reason:
                # Guarded: hou.ui is absent in a headless session, and
                # the refusal must surface, not crash.
                ui = getattr(hou, "ui", None)
                if ui is not None:
                    ui.displayMessage(reason)  # type: ignore
                debug.event("import", "network import refused",
                            reason=str(reason))
                break
            if position is not None:
                helpers.place_nodes(created, hou.Vector2(
                    position.x() + offset * 0.6,
                    position.y() - offset * 0.9))

    def drop_code_at_release(self, index, node: hou.Node) -> bool:
        """Code snippet drag released (self-managed): apply the snippet to
        the node under the cursor - same as a double-click, but targeting
        where the drag landed. A release over nothing is silent; a node
        with no code/snippet parm reports why."""
        if not self.code_model or index is None or node is None:
            return False
        try:
            source_index = self.code_sorted_model.mapToSource(index)
        except Exception:
            return False
        with hou.undos.group("Amaze Apply Code Snippet"):
            ok, reason = self.code_model.apply_to_node(
                source_index.row(), node
            )
        if not ok:
            # Drag-door rule: the miss indicator carries the refusal;
            # the reason goes to the status line, never a dialog.
            ui = getattr(hou, "ui", None)
            if ui is not None and reason:
                ui.setStatusMessage(
                    "Amaze: %s" % reason,
                    severity=hou.severityType.Warning,
                )
            return False
        return True

    #: Sections whose sidebar holds real, assignable categories. The
    #: File section is excluded on purpose - deliberately partial: its
    #: sidebar is a list of filesystem FOLDERS, so a drop there would
    #: mean moving files on disk, a different and dangerous operation,
    #: not a metadata change.
    def _category_under_cursor(self):
        return sidebar.category_under_cursor(self)

    def _set_drag_hover_row(self, row: int) -> None:
        """Highlight (row) or clear (row=-1) the sidebar row being
        dragged over. Logic in panel/sidebar.py."""
        sidebar.set_hover_row(self, row)

    def _update_category_drag_hover(self, pos) -> None:
        sidebar.update_hover(self, pos)

    def _update_category_drag_hover_global(self) -> None:
        sidebar.update_hover_global(self)

    def _can_drop_category(self, event) -> bool:
        return sidebar.can_drop(self, event)

    def _handle_category_drop(self, event) -> bool:
        return sidebar.handle_drop(self, event)

    def _network_items_at_cursor(self, editor):
        """Droppable items under the cursor in a network editor, via
        the editor's OWN coordinate chain (cursorPosition -> posToScreen
        -> networkItemsInBox; all documented in the same screen space -
        wiki: Node graph). isUnderCursor() gates out the pane's chrome
        (toolbars/controls), where the old pane-rect math silently
        produced out-of-view points. Hits arrive as (item, ...) tuples."""
        try:
            if not editor.isUnderCursor():
                return ()
            p = editor.posToScreen(editor.cursorPosition())
            r = theme.ui_px(2)
            return editor.networkItemsInBox(
                hou.Vector2(p.x() - r, p.y() - r),
                hou.Vector2(p.x() + r, p.y() + r),
                for_drop=True,
            )
        except (AttributeError, TypeError, hou.OperationFailed):
            return ()

    def _node_under_cursor(self) -> hou.Node | None:
        """The scene node the cursor is over. In a network editor: the
        node under the mouse (native cursor chain, see
        _network_items_at_cursor). Over a Parameter Editor: the node
        whose parameters that pane is showing - dropping a gradient on
        the parm pane you are already looking at beats hunting the
        node, especially for ramps."""
        pane_tab = dragengine.pane_tab_under_cursor()
        if pane_tab is None:
            return None
        try:
            pane_type = pane_tab.type()
        except AttributeError:
            return None
        if pane_type == hou.paneTabType.Parm:
            try:
                return pane_tab.currentNode()
            except (AttributeError, hou.OperationFailed):
                return None
        if pane_type != hou.paneTabType.NetworkEditor:
            return None
        for item in self._network_items_at_cursor(pane_tab):
            candidates = (
                item if isinstance(item, (tuple, list)) else (item,)
            )
            for candidate in candidates:
                if isinstance(candidate, hou.Node):
                    return candidate
        return None

    def apply_gradient_to_node(
        self, index: QtCore.QModelIndex, node: hou.Node,
        basis: str = "",
    ) -> bool:
        """Drag-drop completion for the Gradients section: apply the
        dragged combination to the node the drag was released over.
        A node that takes nothing answers False - the gesture shows
        its own miss (drag-door rule: the red indicator and the status
        line, never a dialog)."""
        if index is None or not index.isValid():
            return False
        source_index = self.gradient_sorted_model.mapToSource(index)
        entry = self.gradient_model.entry(source_index.row())
        if entry is None:
            return False
        parm = helpers.find_color_ramp_parm(node)
        if parm is None:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.setStatusMessage(
                    "Amaze: %s has no color ramp to take the gradient"
                    % node.name(),
                    severity=hou.severityType.Warning,
                )
            return False
        with hou.undos.group("Amaze Apply Gradient"):
            parm.set(self._entry_ramp(entry, basis))
        return True

    def save_gradient_from_node(self, node: hou.Node | None = None) -> None:
        """"Save Gradient to <app>" (node right-click, or any caller
        with a ramp-bearing node): serializes the node's first color
        ramp and registers it as a user gradient in the Gradients
        section, in a category chosen (or created) in the save dialog.
        Follows the material save flow's conventions - selection-based
        fallback, specific error messages instead of silent no-ops."""
        if not self.material_model:
            hou.ui.displayMessage(  # type: ignore
                "Please set a library first. Use the %s panel - "
                "Library/Open Dialog." % branding.APP_NAME
            )
            return
        if node is None:
            sel = hou.selectedNodes()
            if len(sel) != 1:
                hou.ui.displayMessage(  # type: ignore
                    "Select a single node with a color ramp first."
                )
                return
            node = sel[0]
        parm = helpers.find_color_ramp_parm(node)
        if parm is None:
            hou.ui.displayMessage(  # type: ignore
                f'"{node.name()}" ({node.type().name()}) has no color '
                "ramp parameter to save."
            )
            return
        ramp_data = helpers.ramp_to_data(parm.evalAsRamp())
        dialog = gradient_dialog.GradientDialog(
            self.gradient_model.user_categories(), default_name=node.name()
        )
        dialog.exec_()
        if dialog.canceled:
            return
        self.gradient_model.add_user_gradient(
            dialog.name, dialog.category, ramp_data
        )
        # The shared verb, which brackets its own insert - not
        # switch_model_data(), which belongs to a library switch and
        # only ever runs through switch_all_models().
        if dialog.category:
            self.gradient_categories_model.check_add_category(
                dialog.category)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """Any splitter drag records BOTH side panes' widths; the
        debounced save timer writes them (the slider's own pattern,
        reused). The construction's law - side panes hold their width
        - only works if each side pane KNOWS its width."""
        pane = getattr(self, "notes_panel", None)
        if pane is None:
            return
        splitter = pane.parentWidget()
        if not isinstance(splitter, QtWidgets.QSplitter):
            return
        sizes = splitter.sizes()
        changed = False
        for widget, pref_key in (
                (pane, "notes_panel_width"),
                (getattr(self, "cat_wrapper", None), "sidebar_width")):
            if widget is None or widget.isHidden():
                continue
            index = splitter.indexOf(widget)
            if 0 <= index < len(sizes) and sizes[index] > 0:
                setattr(self.prefs, pref_key, sizes[index])
                changed = True
        if changed:
            self._thumbsize_save_timer.start()

    def toggle_notes_panel(self) -> None:
        """Flip the Notes pane via its toolbar button, so the chip's
        lit state can never disagree with the pane."""
        button = getattr(self, "btn_notes", None)
        if button is not None:
            button.setChecked(not button.isChecked())

    def _on_notes_toggled(self, checked: bool) -> None:
        """Show or hide the pane, nothing more: the one-flexible-pane
        construction (see _build_splitter_and_sidebar) makes the grid
        absorb the change on its own - no width bookkeeping here."""
        panel = getattr(self, "notes_panel", None)
        if panel is None:
            return
        panel.setVisible(bool(checked))
        self.prefs.show_notes = bool(checked)
        self.prefs.save()
        if checked:
            self._refresh_notes_subject()

    def _sync_notes_button_pixmaps(self) -> None:
        """The chip's four states, in the TOOLBAR's own colours.


        and its to-dos, not to this button - "change the color on the
        toolbar to the default color for the toolbar icons". So the
        chip wears the icon family's own blue, IDLE_BODY, in ALL FOUR
        states - "keep it blue in all states, not white while on". It
        used to light in the star yellow, which said "notes are
        yellow", a thing that stopped being true when Comments took
        its own colour; lighting it to LIT_BODY instead just made it
        go white. The state is carried by the chip's BACKGROUND, which
        is what a chip is for; the glyph does not need to change
        colour to say it too.

        The tint map keys on the ART's colour. That is not decoration:
        the map replaces a literal, so when the icon changed from the
        old yellow-keyed drawing to this one, a map still keyed on
        "#fffc66" silently matched NOTHING and the chip rendered its
        own blue in all four states - the bug this replaces.
        """
        button = getattr(self, "btn_notes", None)
        if button is None:
            return
        # The glyph is the section's blue as drawn; on the TOOLBAR it
        # wears the icon family's blue like every other chip, and it
        # does not whiten when on.
        button.set_art(
            self._ui_icon_path("icon_comments.svg"),
            lighten_on_hover=False,
            recolour={notes_panel.COMMENT_INK:
                      ui_helpers.IconMenuButton.IDLE_BODY})

    def _on_note_saved(self, _key: str) -> None:
        """A page was written - repaint the grid so the tile's note
        badge appears or clears with it.

        THE VISIBLE view: `NotesRole` is answered live from the store
        with no `dataChanged`, so this repaint is the whole signal - and
        naming `thumblist` meant list mode got none of it. The tick
        column stayed blank until something unrelated repainted."""
        grid.visible_view(self).viewport().update()

    def _notes_subject(self):
        """What the Comments pane points at, or None.

        Two things happen here and nothing else: find the LIVE current
        index - never a stored proxy index, the one selection source
        every handler uses - and ask the context what that index means.

        The three per-section mappings that used to follow are on the
        contexts now (`Section.comment_subject`), so a section that
        arrives with tiles of its own gets a Comments pane by writing
        one method rather than by being remembered here.
        """
        index = ui_helpers.live_current_index(self.thumblist)
        if index is None or not index.isValid():
            return None
        context = self._section()
        # ASK THE CONTEXT, do not test which world this is. The online
        # world answers no because an online record is not a library
        # asset - a fact that belongs on it, not in a branch here.
        if context is None or not context.takes_comments:
            return None
        return context.comment_subject(index)

    def _refresh_notes_subject(self, *_args) -> None:
        """Point the Notes pane at the current selection. Cheap when
        the pane is hidden (returns immediately), called from every
        selection change and tab switch."""
        panel = getattr(self, "notes_panel", None)
        if panel is None or panel.isHidden():
            return
        subject = self._notes_subject()
        if subject is None:
            panel.clear_subject()
        else:
            panel.set_subject(subject)

    def _on_folder_progress(self, section: str, done: int, total: int) -> None:
        """The conversion bar, but only while its OWN section is showing.

        One handler served both folder sections with no guard, and the
        bar sits ABOVE the grid - so a batch finishing (or starting)
        while you were somewhere else drew a progress bar over that
        section and shifted every tile down. Easy to trigger: changing
        any preference calls refresh_current_folder() unconditionally,
        and a RenderSize change or Delete Local Cache turns the whole
        texture folder into a cache miss, so the Images bar appeared
        over Materials, Nodes or Code and stayed until the batch ended.

        _on_online_preview_progress already had this guard, and its
        docstring gives the same reason.

        AND THE ONLINE HALF OF IT, which was missing: `current_section`
        deliberately keeps naming the LOCAL section while the online
        world is showing (see _is_online), so the section test alone
        cannot see that the user has left. Browse a File folder that
        starts a conversion batch, press the Online chip, and the bar
        drew itself over the ONLINE grid - shifting every tile down and
        back up as it appeared and finished, which is the exact symptom
        the section guard was added for, one world over.
        """
        if self._is_online() or self.current_section != section:
            return
        self._on_texture_progress(done, total)

    def _on_texture_progress(self, done: int, total: int) -> None:
        """Shows/updates the thin progress bar above the thumbnail grid
        while texture thumbnails are generating for the selected folder.
        Hidden when there's nothing to do (fully cached / empty folder)
        or once generation completes."""
        if total <= 0 or done >= total:
            self.texture_progress.setVisible(False)
            return
        self.texture_progress.setVisible(True)
        self.texture_progress.set_progress(done, total)

    def _on_online_preview_progress(self, done: int, total: int) -> None:
        """Same bar, for the online preview pool - but only while the
        online browser is actually showing. Previews load lazily, so a
        worker finishing after you've switched away must not flash the bar
        over another section."""
        if not self._is_online():
            return
        if getattr(self, "_online_download_active", False):
            return  # a download import owns the bar right now
        self._on_texture_progress(done, total)

    def _active_asset_stack(self):
        """(model, proxy, selection model, category model) of whichever
        curated-library section is showing (Materials / Cop / Code), or
        None for a folder/gradient section or before setup. The section
        object owns this now - see panel/sections.py AssetSection.stack."""
        section = self._section()
        return section.stack() if section is not None else None

    def filter_thumb_view(self) -> None:
        """Search box changed - the active section applies it."""
        if self._is_online():
            # Online browsing searches the SOURCE's API, not a local
            # model - the whole catalogue is never resident.
            self.matx_online_model.set_search(self.line_filter.text())
            return
        section = self._section()
        if section is not None:
            section.filter_text(self.line_filter.text())

    def filter_favs(self) -> None:
        """Favourites star toggled - the active section applies it."""
        if self._is_online():
            # Belt and braces: the button is disabled online, but a
            # stale checked state must never filter the material proxy
            # while the online grid is showing.
            return
        section = self._section()
        if section is not None:
            section.filter_favorites(self.cb_favsonly.isChecked())

    def build_filter_menu(self) -> None:
        """Fill the Filter menu with the ACTIVE section's entries.

        One menu and one button serve every tab, exactly as the Search
        box and the favourites star do - so like them, the contents
        cannot be decided once at construction. The section says what
        it offers (sections.py ▸ filter_entries) and what an entry
        MEANS (apply_filter); this only carries the choice between
        them, and never looks inside a value.

        Runs on every section change, and again whenever Preferences
        may have changed what is on offer - Materials drops a renderer
        that has been switched off. A remembered choice that is no
        longer offered falls back to the everything-entry, which is
        what stopped "the checked renderer just got hidden" from
        needing a special case of its own.
        """
        section = self._section()
        entries = tuple(section.filter_entries()) if section is not None else ()
        self.menu_filter.clear()
        # A QActionGroup owns its actions: dropping the old group with
        # the old menu is what keeps a stale action from staying
        # checked and answering for a section that is no longer showing.
        self.filter_action_group = QtGui.QActionGroup(self.menu_filter)
        self.filter_action_group.setExclusive(True)
        self.filter_actions = {}
        self.filter_values = {}
        button = getattr(self, "btn_filter", None)
        if button is not None:
            if (section is not None
                    and not getattr(section, "takes_filter_menu", True)):
                # Offered-but-off belongs to the toolbar table, which
                # DISABLES the button (half opacity, like Favourites
                # and Comments beside it). Hiding it here was a second
                # owner for the same control: the eye VANISHED in the
                # online world, whose context always has no entries.
                button.setVisible(True)
            else:
                # No entries, no menu: a button that opens an empty popup
                # is worse than no button. Nothing shipped hits this - all
                # five sections filter - but a new section gets it free.
                button.setVisible(bool(entries))
            if section is not None:
                button.setToolTip(ui_helpers.tooltip_text(
                    section.filter_tooltip))
        if not entries:
            return
        for label, value in entries:
            act = self.menu_filter.addAction(label)
            act.setCheckable(True)
            self.filter_action_group.addAction(act)
            self.filter_actions[label] = act
            self.filter_values[label] = value
        remembered = self.prefs.section_filter(self.current_section)
        act = self.filter_actions.get(remembered) or self.filter_actions[
            entries[0][0]]
        act.setChecked(True)
        self.filter_action_group.triggered.connect(self.filter_menu_changed)
        self.apply_section_filter()

    def filter_menu_changed(self, action) -> None:
        """An entry was picked: apply it and remember it for this tab."""
        self.apply_section_filter()
        self.prefs.set_section_filter(self.current_section, action.text())
        self.prefs.save()

    def apply_section_filter(self) -> None:
        """Push the menu's checked entry into the active section.

        Separate from filter_menu_changed because the same push has to
        happen with nobody clicking anything: entering a section,
        rebuilding the menu, or opening the panel.
        """
        section = self._section()
        if section is None or not self.filter_actions:
            return
        checked = (self.filter_action_group.checkedAction()
                   if self.filter_action_group is not None else None)
        label = checked.text() if checked is not None else ""
        value = self.filter_values.get(label)
        section.apply_filter(value)
        debug.event(
            "filter", "section filter applied",
            section=self.current_section, entry=label, value=str(value),
            visible=self.thumblist.model().rowCount()
            if self.thumblist.model() is not None else -1,
        )

    def _refresh_sidebar_categories(self) -> None:
        """Re-evaluate empty-category hiding and counts after anything
        that changed which materials/COPs exist, what they belong to,
        or which renderer filter is active. Flows that already emit
        category_model.layoutChanged refilter automatically - this is
        for the ones that don't (deletes, overwrite, renderer switch)."""
        for cats_model in (
            getattr(self, "category_model", None),
            getattr(self, "cop_category_model", None),
            getattr(self, "code_category_model", None),
        ):
            if cats_model is not None:
                cats_model.drop_count_cache()
        proxy = getattr(self, "category_sorted_model", None)
        if proxy is not None:
            proxy.invalidateFilter()
        cop_proxy = getattr(self, "cop_category_sorted_model", None)
        if cop_proxy is not None:
            cop_proxy.invalidateFilter()
        code_proxy = getattr(self, "code_category_sorted_model", None)
        if code_proxy is not None:
            code_proxy.invalidateFilter()
        if self.cat_list is not None:
            self.cat_list.viewport().update()

    #: The sidebar proxy each asset section's categories are shown
    #: through. Named once: the three were enumerated correctly in
    #: setup() and in _refresh_sidebar_categories, and INCOMPLETELY in
    #: the Preferences push (Code was missing) and in the
    #: filter-to-sidebar path (only Material had one at all).
    SIDEBAR_PROXY_ATTRS = {
        "material": "category_sorted_model",
        "cop": "cop_category_sorted_model",
        "code": "code_category_sorted_model",
    }

    def sidebar_proxies(self) -> tuple:
        """Every asset section's sidebar proxy that exists right now."""
        found = []
        for attr in self.SIDEBAR_PROXY_ATTRS.values():
            proxy = getattr(self, attr, None)
            if proxy is not None:
                found.append(proxy)
        return tuple(found)

    def _ensure_sidebar_selection(self, section_key: str) -> None:
        """If the filter just hid the sidebar category the user was
        standing in, fall back to All and refilter the grid - the
        sidebar must never sit with an empty/hidden selection.

        Takes the section KEY because all three asset sections run this
        now: it was Material-gated while only Material pushed a filter
        into its category model, and Node and Code reach it through the
        shared AssetSection.apply_filter.
        """
        if self.current_section != section_key:
            return
        proxy = getattr(
            self, self.SIDEBAR_PROXY_ATTRS.get(section_key, ""), None)
        if proxy is None:
            return
        if self.cat_list is None or self.cat_list.model() is not proxy:
            return
        selection_model = self.cat_list.selectionModel()
        if selection_model is None:
            return
        indexes = self.cat_list.selectedIndexes()
        if indexes and indexes[0].isValid():
            # The selected category survived the refilter (proxy
            # selections track items, not row numbers).
            return
        self._stand_on_all_category()

    def _stand_on_all_category(self) -> None:
        """Point the sidebar at All and refilter.

        One owner: the fallback above and the empty state's Show All
        button both need it, and a second copy of the row walk would be
        the third reader this codebase keeps growing.
        """
        view = getattr(self, "cat_list", None)
        proxy = view.model() if view is not None else None
        if proxy is None:
            return
        selection_model = view.selectionModel()
        for row in range(proxy.rowCount()):
            idx = proxy.index(row, 0)
            if idx.data() == "All":
                view.setCurrentIndex(idx)
                if selection_model is not None:
                    selection_model.select(
                        idx,
                        QtCore.QItemSelectionModel.SelectionFlag
                        .ClearAndSelect,
                    )
                break
        self.update_selected_cat()

    def show_all_categories(self) -> None:
        """The empty state's Show All button."""
        self._stand_on_all_category()

    def clear_filter_box(self) -> None:
        """The empty state's Clear Search button.

        The refilter is called BY HAND and is not redundant: the box is
        wired on `textEdited`, which Qt does not emit for a
        programmatic change. Qt's own clear button emits it explicitly
        for this exact reason.
        """
        box = getattr(self, "line_filter", None)
        if box is None or not box.text():
            return
        box.clear()
        self.filter_thumb_view()

    def user_update_asset(self) -> None:
        """User modifies an assete in the detailview"""
        if not self.material_model or not self.category_model:
            return
        indexes = grid_columns.selected_rows(self.material_selection_model)
        # About/license are per-material provenance - only save them for a
        # single selection, so editing a multi-selection can't overwrite
        # everyone's credits with one material's text (None = keep).
        single = len(indexes) == 1
        about = self.text_about.toPlainText() if single else None
        license_ = self.line_license.text() if single else None
        name = self.line_name.text()
        tags = self.line_tags.text()
        cats = self.cat_combo.currentText()
        # THE TRI-STATE, READ AS THREE. `isChecked()` is True for
        # PartiallyChecked, which is the state update_details_view sets
        # when the selected rows disagree - so editing only the Tags
        # field of a mixed selection starred every one of them.
        # `set_assetdata`
        # already honours None as leave-alone; this was the one call
        # site that never passed it, while name, tags and category are
        # protected by the MULTIPLE_VALUES sentinel.
        state = self.box_fav.checkState()
        fav = (None if state == QtCore.Qt.CheckState.PartiallyChecked
               else state == QtCore.Qt.CheckState.Checked)
        # OUTSIDE the layout wrapper, and hoisted out of the loop with
        # the other four: every value here is read from a widget, so it
        # was the same on each pass anyway. check_add_category
        # announces itself with begin/endInsertRows, and pairing the
        # two segfaults H21 (research.md, measured 2026-08-04).
        self.category_model.check_add_category(cats)
        with ui_helpers.relayout(self.material_model):
            for index in indexes:
                idx = self.material_model.index(
                    self.material_sorted_model.mapToSource(index).row(), 0
                )
                # save=False: one index write after the loop, not one
                # per selected row.
                self.material_model.set_assetdata(
                    idx, name, cats, tags, fav, about=about,
                    license=license_, save=False
                )
            self.material_model.save()

    def _refresh_cat_combo(self) -> None:
        """Repopulate the category dropdown from the current category list"""
        current = self.cat_combo.currentText()
        self.cat_combo.blockSignals(True)
        self.cat_combo.clear()
        self.cat_combo.addItems(self.get_category_names())
        i = self.cat_combo.findText(current)
        if i >= 0:
            self.cat_combo.setCurrentIndex(i)
        self.cat_combo.blockSignals(False)

    def update_details_view(self) -> None:
        """Update upon changes in Detail view"""
        if self.current_section != "material":
            return
        if not self.material_model or not self.category_model:
            return
        if not self.material_selection_model.hasSelection():
            self.line_name.setText("")
            self.line_id.setText("")
            self.line_date.setText("")
            self.line_renderer.setText("")
            self.line_tags.setText("")
            self.line_license.setText("")
            self.text_about.setPlainText("")
            self.box_fav.setCheckState(QtCore.Qt.CheckState.Unchecked)
            return

        indexes = grid_columns.selected_rows(self.material_selection_model)

        asset_id = ""
        name = ""
        date = ""
        sel_cats = []
        sel_tags = []
        fav = []
        for pos, idx in enumerate(indexes):
            curr_asset = self.material_model.index(
                self.material_sorted_model.mapToSource(idx).row(), 0
            )
            name = curr_asset.data(QtCore.Qt.ItemDataRole.DisplayRole)
            asset_id = curr_asset.data(self.material_model.IdRole)
            date = curr_asset.data(self.material_model.DateRole)

            for cat in curr_asset.data(self.material_model.CategoryRole):
                sel_cats.append(cat)
                # for tag in curr_asset.data(self.material_model.TagRole):
            sel_tags.append(curr_asset.data(self.material_model.TagRole))

            fav.append(curr_asset.data(self.material_model.FavoriteRole))

        clean_name = name
        msg = MULTIPLE_VALUES if len(indexes) > 1 else clean_name
        self.line_name.setText(msg)

        msg = MULTIPLE_VALUES if len(indexes) > 1 else asset_id
        self.line_id.setText(msg)

        msg = MULTIPLE_VALUES if len(indexes) > 1 else date
        self.line_date.setText(msg)

        if len(indexes) > 1:
            self.line_renderer.setText(MULTIPLE_VALUES)
        else:
            self.line_renderer.setText(
                curr_asset.data(self.material_model.RendererLabelRole) or ""
            )

        msg = (
            QtCore.Qt.CheckState.Checked
            if fav[0] is True
            else QtCore.Qt.CheckState.Unchecked
        )
        for f in fav:
            if f != fav[0]:
                msg = QtCore.Qt.CheckState.PartiallyChecked
                break
        self.box_fav.setCheckState(msg)

        self._refresh_cat_combo()
        # Single category per asset now. Show it in the dropdown; a mixed
        # multi-selection just shows the first item's category as the
        # editable value (updating applies it to all selected).
        cats_clean = [str(c).strip() for c in sel_cats if c and str(c).strip()]
        # A MIXED selection must say so. Name and tags already use this
        # sentinel and set_assetdata already honours it - categories did
        # not, so pressing Update after editing a tag on a selection
        # spanning twelve categories refiled every one of them into the
        # first asset's category, with no undo.
        mixed = len(set(cats_clean)) > 1 or (
            len(indexes) > 1 and len(cats_clean) != len(indexes)
        )
        if mixed:
            if self.cat_combo.findText(MULTIPLE_VALUES) < 0:
                self.cat_combo.addItem(MULTIPLE_VALUES)
            self.cat_combo.setCurrentIndex(
                self.cat_combo.findText(MULTIPLE_VALUES))
        else:
            single = cats_clean[0] if cats_clean else ""
            i = self.cat_combo.findText(single)
            if i >= 0:
                self.cat_combo.setCurrentIndex(i)
            else:
                # No stale text: leaving the PREVIOUS asset's category
                # showing is how a single asset gets silently refiled.
                self.cat_combo.setCurrentIndex(-1)

        if sel_tags:
            # dict.fromkeys dedupes while preserving order; a plain set()
            # here made displayed tag order reshuffle unpredictably.
            msg = ", ".join(dict.fromkeys(filter(None, sel_tags[0])))
            if len(sel_tags) > 1:
                for elem in sel_tags:
                    if elem != sel_tags[0]:
                        msg = MULTIPLE_VALUES
            self.line_tags.setText(msg)
        else:
            self.line_tags.setText("")

        # Provenance (per-material) - only meaningful for a single
        # selection; blanked for a multi-selection so nothing is shown as
        # shared that isn't (and user_update_asset won't overwrite it).
        if len(indexes) == 1:
            src_row = self.material_sorted_model.mapToSource(indexes[0]).row()
            asset = self.material_model.assets[src_row]
            self.line_license.setText(asset.license)
            self.text_about.setPlainText(asset.about)
        else:
            self.line_license.setText("")
            self.text_about.setPlainText("")

    # Update the Views when selection changes
    def update_selected_cat(self) -> None:
        """Update thumb view on change of category (Materials) or browse
        the selected folder's images (Textures)."""
        # A ctrl-click on the already-selected row DEselects it, leaving
        # the grid showing contents with nothing highlighted - makes no
        # sense for a category/folder list, so it is removed. Qt has
        # no "single selection but never empty" mode, so an emptied
        # selection is simply re-selected in place; the active category
        # never actually changed, so nothing else needs to run.
        if self._is_online():
            sel = self.cat_list.selectedIndexes()
            if sel:
                cat = self.matx_source_model.category_at(sel[0].row())
                if cat is None:
                    self.matx_sorted_model.removeFilter(
                        self.matx_online_model.CategoryRole
                    )
                else:
                    self.matx_sorted_model.setFilter(
                        self.matx_online_model.CategoryRole, cat
                    )
                grid.visible_view(self).scrollToTop()
            return
        indexes = self.cat_list.selectedIndexes()
        if not indexes:
            current = ui_helpers.live_current_index(self.cat_list)
            selection_model = self.cat_list.selectionModel()
            if current is not None and selection_model is not None:
                selection_model.select(
                    current,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect,
                )
            return

        section = self._section()
        if section is not None:
            section.select_category(indexes[0])

    # Library Stuffs
    def grid_update_preview(self, indexes) -> None:
        """Re-render the grid selection's thumbnails - one entry point
        for every section's menu.

        It was three, and a fourth section (Code) had the capability
        and no way to reach it. No layout-change pair here any more:
        the models emit their own dataChanged and the proxy re-tests on
        it (grid_proxy.py), so the hand-forced re-map - which had to
        sit in a `finally` because a corrupt asset raising between the
        two signals left every attached view believing a layout change
        was still running - is gone with the thing it was working
        around.

        No "updated" dialog: the fresh thumbnail on screen is the
        confirmation.
        """
        context = self._section()
        if context is None:
            return
        context.update_preview(list(indexes))

    def grid_delete(self, indexes) -> None:
        """Delete the grid selection - one entry point for every
        section's menu.

        It was written four times, and every copy had the same shape:
        count the DISTINCT source rows, ask with a sentence that says
        what goes and how many, remove highest row first, refresh the
        sidebar. Only the SENTENCE is per-section, and it is the
        context's (`Section.delete_prompt`); the removal is the
        context's too, because what a row IS differs (an asset record,
        a palette entry).

        A cancelled dialog leaves everything alone - and so does a
        section with no Delete: File's rows are files on disk.
        """
        context = self._section()
        if context is None or not context.deletes_rows:
            return
        proxy = self.thumblist.model()
        sources = []
        seen = set()
        for index in indexes:
            source = proxy.mapToSource(index) if proxy is not None else index
            if source.isValid() and source.row() not in seen:
                seen.add(source.row())
                sources.append(source)
        if not sources:
            return
        # The single row's NAME rides along for the one section whose
        # approved wording quotes it; the others ignore it.
        name = sources[0].data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        if hou.ui.displayMessage(  # type: ignore
            context.delete_prompt(len(sources), name),
            buttons=("Delete", "Cancel"),
            default_choice=1, close_choice=1,
        ) != 0:
            return
        context.delete_rows(sources)

    def generate_random_material(self) -> None:
        """The Generator Engine's first output: one random plausible
        material, built INTO THE SCENE where the user is working -
        the current LOP material library (or one created per the drop
        placement law) when the context is LOP, else /mat. Generated
        materials are scene nodes, not library entries: keeping one is
        a deliberate "Save to Amaze", exactly like any other material
        the user builds by hand.

        Built in /obj staging and moved in ONE step (structure changes
        inside a live library retranslate the whole thing - wiki).
        v1 is random; the SPEC it runs on is the interface a
        parametric generator will drive later."""
        builder = None
        destination = None
        # The whole gesture is ONE undo step: staging AND the
        # destination resolution, which may itself create a material
        # library - a move whose source parent was destroyed outside
        # the group has nothing coherent to undo to, and a library
        # created outside it would survive the undo as an orphan.
        with hou.undos.group("Amaze Generate Material"):
            destination = nodes.karma_destination(self.prefs)
            if destination is None:
                hou.ui.displayMessage(  # type: ignore
                    "Amaze: no place to create the material - open a "
                    "LOP or /mat network first."
                )
                return
            staging = hou.node("/obj").createNode("matnet")
            try:
                builder, spec = generator.generate_random_material(staging)
                if builder is None:
                    hou.ui.displayMessage(  # type: ignore
                        "Generation failed - see the debug log."
                    )
                    return
                moved = hou.moveNodesTo((builder,), destination)
                if not moved:
                    builder = None
                    debug.event("generate", "move failed",
                                destination=destination.path())
                    hou.ui.displayMessage(  # type: ignore
                        "Amaze: the generated material could not be "
                        "moved into %s." % destination.path()
                    )
                    return
                builder = moved[0]
                helpers.auto_place(builder)
                # Registered the same way an import is: a library whose
                # wildcard was narrowed or disabled would otherwise
                # take the material as a node that renders nowhere.
                registered = True
                if destination.type().name() == "materiallibrary":
                    registered = nodes.register_in_materiallibrary(
                        destination, builder
                    )
                # Front the new material like any hand-created node
                # (a menu action IS the user asking for it - unlike
                # a drop, where keep_editor_focus applies).
                builder.setCurrent(True, True)
                debug.event("generate", "random material",
                            name=builder.name(),
                            destination=destination.path(),
                            registered=registered,
                            spec={
                                k: ([round(c, 3) for c in v]
                                    if isinstance(v, (list, tuple))
                                    else round(v, 3))
                                for k, v in spec.items()
                            },
                            provenance=builder.comment())
                if not registered:
                    hou.ui.displayMessage(  # type: ignore
                        '"%s" was created in %s but no material entry '
                        "covers it - check the library node's material "
                        "list." % (builder.name(), destination.path())
                    )
            except hou.Error as exc:
                builder = None
                debug.event("generate", "failed", error=str(exc))
                hou.ui.displayMessage(  # type: ignore
                    "Amaze: generation failed (%s)." % exc
                )
            finally:
                staging.destroy()
        if builder is not None:
            hou.ui.setStatusMessage(  # type: ignore
                "Amaze: generated %s in %s"
                % (builder.name(), destination.path())
            )

    def save_asset(self) -> None:
        """Saves the selected nodes (Network Editor) to the Library.

        Standard file-save semantics (by design): if the selected
        node matches an EXISTING library material - via the id stamp a
        previous save/import left on it, or a unique name match - offer
        Update Existing / Save as New / Cancel; otherwise go straight to
        the normal new-material dialog. Multi-selections always save new
        materials, as before."""
        # Get Selected from Network View
        sel = hou.selectedNodes()
        debug.event("save", "save_asset entry", selected=len(sel))
        # Check selection
        if not sel:
            hou.ui.displayMessage("No material selected")  # type: ignore
            return
        if not self.material_model:
            hou.ui.displayMessage(
                "Please set a library first. Use the %s panel - "
                "Library/Open Dialog." % branding.APP_NAME  # type: ignore
            )
            return
        # Standard file-save semantics for ANY selection size (the old
        # single-node-only check let a re-dropped BATCH silently save 16
        # duplicates): find which dropped nodes already exist, offer
        # Overwrite / Save as New / Cancel once for the whole drop.
        existing = []
        new_nodes = []
        for node in sel:
            row = self._find_existing_asset_row(node)
            if row >= 0:
                existing.append((row, node))
            else:
                new_nodes.append(node)
        debug.event("save", "overwrite check",
                    existing=len(existing), new=len(new_nodes))
        if existing:
            if len(sel) == 1:
                name = self.material_model.data(
                    self.material_model.index(existing[0][0], 0),
                    QtCore.Qt.ItemDataRole.DisplayRole,
                )
                message = '"%s" already exists in the library.' % name
            else:
                message = (
                    "%d of %d dropped materials already exist in the "
                    "library." % (len(existing), len(sel))
                )
            # The LIBRARY decides, not this machine's preferences - a
            # switch only one machine can see protects nobody. The
            # stored key is still allow_overwrite (keys are
            # identifiers, never names); the UI calls it Material
            # Versions since 2026-08-01, because that is what saying
            # yes DOES now: a save-over archives a version first and
            # destroys nothing. When it is off the button is not
            # offered at all: an option that always fails is worse
            # than an option that is not there.
            may_overwrite = library_policy.allow_overwrite(
                self.material_model.preferences.dir)
            if may_overwrite:
                buttons = ("Save Version", "Save New", "Cancel")
                cancel_at, overwrite_at = 2, 0
            else:
                message += (
                    "\n\nMaterial Versions is off for this library, "
                    "so the existing material stays as it is. Saving "
                    "will add a new material."
                )
                buttons = ("Save New", "Cancel")
                cancel_at, overwrite_at = 1, -1
            choice = hou.ui.displayMessage(  # type: ignore
                message,
                buttons=buttons,
                default_choice=0,
                close_choice=cancel_at,
                title="Save to " + branding.APP_NAME,
            )
            if choice == cancel_at:
                return
            if choice == overwrite_at:
                # Overwrites neither insert nor remove rows, so the
                # collected row indexes stay valid through the loop.
                for row, node in existing:
                    self._update_existing_asset(row, node)
                    QtWidgets.QApplication.processEvents()
                if new_nodes:
                    self.get_material_info_user(new_nodes)
                return
            # Save as New falls through with the FULL selection.
        self.get_material_info_user(sel)

    def _find_existing_asset_row(self, node: hou.Node) -> int:
        """Source-model row of the library material this node came from,
        or -1. The id stamp (setUserData on save/import) is authoritative;
        a UNIQUE name match is the fallback for nodes imported before
        stamping existed."""
        mat_id = node.userData("assetlib_id")
        if mat_id:
            row = self.material_model.find_asset_row_by_id(mat_id)
            if row >= 0:
                return row
        return self.material_model.find_asset_row_by_name(node.name())

    def _update_existing_asset(self, row: int, node: hou.Node) -> None:
        """Overwrite an existing library entry's content from the scene
        node: same entry/metadata, new node files + thumbnail + type."""
        with ui_helpers.relayout(self.material_model):
            renderer = self.material_model.update_asset_content(row, node)
        # Overwrite can re-detect a different renderer - counts and
        # renderer-aware hiding may shift.
        self._refresh_sidebar_categories()
        if not renderer:
            hou.ui.displayMessage(
                "Update failed - the library material was not changed."  # type: ignore
            )
            return
        self.enable_renderer_on_add(renderer)
        self.prefs.save()
        self.update_renderer_toggles()

    def get_material_info_user(self, sel: list[hou.Node]) -> None:
        if not self.material_model or not self.category_model:
            return
        """Query user for input upon material-save"""
        # Get Stuff from User
        self.usd_dialog_category_model = QtCore.QSortFilterProxyModel()
        # Source model, NOT the sidebar proxy: the sidebar hides empty
        # categories, but the save dialog must offer every category
        # (this proxy sorts and All-filters on its own regardless).
        self.usd_dialog_category_model.setSourceModel(self.category_model)
        usd_filter = "^(?!All).*$"
        self.usd_dialog_category_model.setFilterRegularExpression(usd_filter)
        self.usd_dialog_category_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.usd_dialog_category_model.sort(0)

        cats = []
        for elem in range(self.usd_dialog_category_model.rowCount()):
            idx = self.usd_dialog_category_model.index(elem, 0)
            cats.append(self.usd_dialog_category_model.data(idx))

        # Default the dialog to the category currently selected in the
        # panel (skip the "All" pseudo-category and empty selections).
        # One helper for all three save dialogs. They were three
        # copies that already disagreed - only this one fell back to
        # live_current_index, which is the state _restore_section_state
        # reaches through setCurrentIndex without a select, so the Node
        # dialog silently defaulted to Uncategorized where this one
        # pre-selected the category.
        current_cat = self._selected_category_name()

        dialog = usd_dialog.UsdDialog(cats, current_cat)
        r = dialog.exec_()

        debug.event(
            "save", "save dialog closed",
            accepted=bool(r and not dialog.canceled),
            category=dialog.categories, preselected=current_cat,
        )
        if dialog.canceled or not r:
            return

        # Check if Category or Tags already exist
        if dialog.categories:
            self.category_model.check_add_category(dialog.categories)
        if dialog.tags:
            self.material_model.check_add_tags(dialog.tags)

        renderers = []
        failures = []
        for asset in sel:
            try:
                # The whole save chain had NO exception handling: a
                # read-only or unreachable library directory produced a
                # raw traceback in Houdini (verified: IsADirectoryError
                # on the .interface). debug.guarded logs and RE-RAISES,
                # so it does not cover this. The import side has
                # reported per-material failures for a long time; the
                # save side now matches it.
                renderer = self.material_model.add_asset(
                    asset, dialog.categories, dialog.tags, dialog.fav
                )
            except Exception as exc:                    # noqa: BLE001
                debug.exception("save_asset", exc, node=asset.path())
                failures.append('"%s": %s' % (asset.name(), exc))
                continue
            if not renderer:
                # A refused save answers "" now, and a refused save is
                # exactly what this dialog exists to report. Two of the
                # three causes have already shown their own dialog
                # naming the reason, so this line only has to say WHICH
                # material out of the batch never made it.
                failures.append('"%s": the save did not complete'
                                % asset.name())
                continue
            renderers.append(renderer)
            # Let the fresh tile PAINT before the next material's
            # blocking render starts - add_asset emits real row-insert
            # signals now, and this flush is what makes saved materials
            # appear one by one through a long multi-save batch.
            QtWidgets.QApplication.processEvents()

        if failures:
            hou.ui.displayMessage(  # type: ignore
                "Some materials could not be saved:\n\n"
                + "\n".join(failures)
            )
        for renderer in renderers:
            self.enable_renderer_on_add(renderer)
        self.prefs.save()
        self.update_renderer_toggles()
        self._refresh_sidebar_categories()

    def enable_renderer_on_add(self, renderer: str) -> None:
        """Switch a renderer's Filter entry on when its first material
        is saved, so the thing the user just saved is visible in the
        tab they saved it from.

        Walks the ONE renderer table rather than repeating it as a
        third if/elif chain. Karma keeps its own first test because
        `is_karma_renderer` covers the legacy stored labels (MaterialX,
        MtlX) that no substring match would.
        """
        if material.is_karma_renderer(renderer):
            self.prefs.renderer_matx_enabled = True
        else:
            for label, attr in sections.renderer_prefs():
                if label != "Karma" and label in renderer:
                    setattr(self.prefs, attr, True)
                    break
        self.prefs.save()

    def import_asset(self, target: str = "auto"):
        """Import the selected materials.

        target: "auto" lets MatLib decide from the active network editor
        (double-click); "mat" forces /mat; "lop" forces a LOP
        materiallibrary. Materials that cannot live in the requested context
        are skipped and collected into a single summary dialog."""
        if not self.material_model or not self.category_model:
            return
        failures = []
        # ONE undo entry for the whole import. This was the only import
        # entry point not grouped - the online import, the Nodes-section
        # import, the COP drag, the material network drop and the
        # viewport assign all group. So a double-click created the
        # destination container, a staging matnet, the builder, the move
        # and the materiallibrary entry as SEPARATE undo entries: one
        # Ctrl+Z reverted the last of them and left a stray
        # matnet/materiallibrary and a half-imported builder behind.
        # (Exactly the bug the comment at the Nodes-section import says
        # was fixed there.)
        with hou.undos.group("Amaze Import Materials"):
            self._import_selected_materials(target, failures)
        if failures:
            hou.ui.displayMessage(  # type: ignore
                "Some materials could not be imported:\n\n" + "\n".join(failures)
            )

    def _import_selected_materials(self, target: str, failures: list) -> None:
        """The import loop itself - see import_asset for the grouping."""
        for index in grid_columns.selected_rows(
                self.thumblist.selectionModel()):
            source_index = self.material_sorted_model.mapToSource(index)
            try:
                ok, reason, _created = self.material_model.import_asset_to_scene(
                    source_index, target
                )
            except Exception as e:
                # An unexpected failure (corrupt .interface file, unusual
                # node structure) previously surfaced as a raw traceback
                # instead of joining the normal per-material failure
                # report; catch it here so the rest of the selection still
                # gets a chance to import.
                try:
                    name = self.material_model.assets[source_index.row()].name
                except Exception:
                    name = "material"
                failures.append(f'"{name}" failed to import: {e}')
                continue
            if not ok and reason:
                failures.append(reason)

    def import_asset_auto(self, index: QtCore.QModelIndex | None = None):
        """Double-click handler, shared across sections since thumblist is
        reused for all of them. Materials: context-aware import (the model
        index isn't used here - it never reaches the "auto"/"mat"/"lop"
        target argument that import_asset() expects a string for).
        Textures: push the double-clicked file's path onto a selected
        texture node's image parm - here the index *is* what's needed, to
        know which file was double-clicked."""
        if index is not None and index.isValid():
            # THE ROW, not the clicked cell: in list mode the double-
            # click lands on a visible column >= 1, where the models
            # answer roles with None (research.md > Row selection over
            # a table view).
            index = index.siblingAtColumn(0)
        if self._is_online():
            # Without this the online branch fell through to Materials,
            # and import_asset() reads the MATERIAL selection model -
            # which still holds whatever was selected before going
            # online, so double-clicking imported an unrelated local
            # material. Double-click is "the primary action" in every
            # section; here - as for a local material - that is putting
            # the material INTO THE SCENE, not into the library.
            if index is not None and index.isValid():
                source = self.matx_sorted_model.mapToSource(index)
                record = self.matx_online_model.record(source.row())
                if record is not None:
                    self._import_online_records_to_scene([record])
            return
        section = self._section()
        if section is not None:
            section.double_click(index)

    #: The ONE double-click refusal, everywhere (ROADMAP - the
    #: interaction matrix; exact copy also in ui-text.md). The drag
    #: door never dialogs - it has the miss indicator.
    CANNOT_LOAD_HERE = "This content can not be loaded into this context."

    #: What the Code section creates per language and per network kind
    #: - names from the shipped manual (sop/attribwrangle, cop/wrangle,
    #: lop/attribwrangle, sop+cop/opencl, sop/python). A pair absent
    #: here, or a type this Houdini does not carry, refuses.
    CODE_CARRIERS = {
        "vex": {"Sop": "attribwrangle", "Lop": "attribwrangle",
                "Cop": "wrangle"},
        "opencl": {"Sop": "opencl", "Cop": "opencl"},
        "python": {"Sop": "python"},
    }

    def _cannot_load_here(self) -> None:
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(self.CANNOT_LOAD_HERE)  # type: ignore

    def _network_under_release(self) -> hou.Node | None:
        """The network a no-node release happened INSIDE - the editor
        under the cursor answers with its pwd. None off any editor."""
        return self._drop_context_under_cursor(lambda _node: False)

    def _release_position_in(self, net):
        """The release position, ONLY when the editor under the cursor
        is showing `net` itself. A release over a container node
        resolves INSIDE it while the cursor's coordinates stay in the
        OUTER editor's plane - stage coordinates applied inside a
        material library put the node anywhere but the cursor (the
        live find). Cross-space answers None and the carrier
        auto-places, exactly like the import seam's gate."""
        pane_tab = dragengine.pane_tab_under_cursor()
        if pane_tab is None or net is None:
            debug.event("interact", "no drop point - no editor under "
                        "the cursor", net=net.path() if net else None)
            return None
        try:
            if pane_tab.type() != hou.paneTabType.NetworkEditor:
                return None
            if pane_tab.pwd() != net:
                # The cross-space case: the release resolved INTO a
                # container while the cursor's coordinates belong to
                # the outer editor. Named, because it is the honest
                # reason a drop auto-places instead of landing.
                debug.event("interact", "no drop point - the editor "
                            "shows another network",
                            showing=pane_tab.pwd().path(),
                            destination=net.path())
                return None
            spot = pane_tab.cursorPosition()
            debug.event("interact", "drop point",
                        at=[round(spot.x(), 3), round(spot.y(), 3)],
                        net=net.path())
            return spot
        except AttributeError:
            return None

    def _visible_selected_nodes(self) -> list:
        """The double-click doors' idea of THE SELECTION: only nodes
        the user can SEE - children of a visible editor's network.
        Houdini tags imported nodes selected (research.md -
        moveNodesTo), so the global hou.selectedNodes() carries
        invisible leftovers of the previous import, and the doors
        applied to a node the user was not looking at and refused,
        every time - the live find. Menu verbs keep the global read:
        their sentences name the selection explicitly."""
        networks = self._view_create_networks()
        every = hou.selectedNodes()
        sel = [node for node in every if node.parent() in networks]
        debug.event("interact", "click door selection",
                    visible=len(sel), total=len(every),
                    networks=len(networks))
        return sel

    def _view_create_networks(self) -> list:
        """The click doors' aim when nothing is selected: every
        visible network editor's pwd, current tabs first. The caller
        creates in the FIRST network that can hold the carrier - one
        resolver for every door, and a payload finds the network that
        supports it instead of failing on whichever editor happened to
        be listed first."""
        ui = getattr(hou, "ui", None)
        if ui is None:
            return []
        editors = [
            pt
            for pt in ui.paneTabs()  # type: ignore
            if pt.type() == hou.paneTabType.NetworkEditor
        ]
        editors.sort(key=lambda editor: not editor.isCurrentTab())
        networks = []
        for editor in editors:
            try:
                pwd = editor.pwd()
            except AttributeError:
                continue
            if pwd is not None and pwd not in networks:
                networks.append(pwd)
        return networks

    def _create_carrier(self, dest, type_name: str, name: str,
                        position=None):
        """Create `type_name` inside `dest` when that network can hold
        one - the type existing in the network's child category IS the
        capability test - or answer None. The carrier half of the
        matrix's creation rule; the caller loads the payload and owns
        the undo group. A position places the node where the release
        happened; without one it auto-places."""
        if dest is None:
            return None
        try:
            category = dest.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return None
        if category is None or hou.nodeType(category, type_name) is None:
            debug.event("interact", "no carrier for this network",
                        carrier=type_name, dest=dest.path())
            return None
        try:
            node = dest.createNode(type_name)
        except hou.Error as refusal:
            # HOUDINI IS THE AUTHORITY ON WHETHER A NETWORK CAN TAKE A
            # NODE, and it answers in one sentence - a locked digital
            # asset says `Cannot create a node inside a locked asset`,
            # and only the nodes an asset MARKS editable are exempt (a
            # SOP Create's `create` subnet is, its sopnet is not).
            # Asking hou.isLockedHDA/isEditableInsideLockedHDA here
            # FIRST was tried and deleted the same hour: a second
            # answerer for a question the host already answers, and a
            # sabotage of it changed nothing. What was missing was
            # never the predicate - it was this line, which used to
            # swallow the reason and cost two wrong diagnoses. The
            # walk moves on to a network that can take it; unlocking
            # the user's asset (allowEditingOfContents) is never ours
            # to do.
            debug.event("interact", "the network refused the carrier",
                        carrier=type_name, dest=dest.path(),
                        error=str(refusal))
            return None
        if name:
            try:
                node.setName(name, unique_name=True)
            except hou.OperationFailed:
                pass
        # A given position IS the placement. Auto-place is only the
        # no-position fallback: moveToGoodPosition may shove
        # unconnected siblings aside to make room, which read live as
        # every other node moving away from the drop.
        if position is None:
            helpers.auto_place(node)
        else:
            helpers.place_nodes([node], position)
        debug.event("interact", "carrier created", carrier=type_name,
                    dest=dest.path())
        return node

    def code_carrier_type(self, index, dest) -> str:
        """WHICH carrier a snippet becomes in `dest` - a wrangle, an
        opencl, a python - or "" where this network kind has none.

        ONE ANSWER, TWO READERS: `create_code_node_in` builds it, and
        the drag ghost draws its shape before the drop happens. A
        ghost that computed its own type could promise a wrangle and
        deliver nothing.
        """
        if index is None or not index.isValid() or not self.code_model:
            return ""
        source_index = self.code_sorted_model.mapToSource(index)
        row = source_index.row()
        if not 0 <= row < len(self.code_model.assets) or dest is None:
            return ""
        asset = self.code_model.assets[row]
        language = str(getattr(asset, "renderer", "") or "").lower()
        try:
            category = dest.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return ""
        return self.CODE_CARRIERS.get(language, {}).get(
            category.name() if category is not None else "", "")

    def create_image_node_in(self, index, dest, position=None) -> bool:
        """The image creation rule: a release on empty network space
        (or a double-click with nothing selected) makes a mtlximage
        carrying the spelled path, wherever the network can hold one."""
        path = index.data(self.file_files_model.PathRole)
        if not path:
            return False
        base = helpers.sanitize_usd_path(
            os.path.splitext(os.path.basename(path))[0]) or "image"
        with hou.undos.group("Amaze Create Image Node"):
            node = self._create_carrier(dest, "mtlximage", base, position)
            if node is None:
                return False
            parm = helpers.find_file_parm(node)
            if parm is None:
                node.destroy()
                return False
            parm.set(self._scene_path(path))
        return True

    def create_gradient_node_in(self, index, dest, position=None,
                                basis: str = "") -> bool:
        """The gradient creation rule: a MtlX colour ramp carrying the
        combination, wherever the network can hold one.

        `basis` is Apply as's chosen interpolation, arriving through
        the click door's payload; empty means the gradient's own
        recorded ramp, which is every other door."""
        if index is None or not index.isValid():
            return False
        source_index = self.gradient_sorted_model.mapToSource(index)
        entry = self.gradient_model.entry(source_index.row())
        if entry is None:
            return False
        return self._create_gradient_carrier(entry, dest, basis,
                                             position=position)

    def _create_gradient_carrier(self, entry, dest, basis: str = "",
                                 position=None) -> bool:
        """The carrier half shared by the drag door (an index) and the
        double-click and menu doors (an entry, optionally re-based by
        Apply as)."""
        name = helpers.sanitize_usd_path(
            str(entry.get("name") or "")) or "gradient"
        with hou.undos.group("Amaze Create Gradient Node"):
            node = self._create_carrier(dest, "hmtlxrampc", name,
                                        position)
            if node is None:
                return False
            parm = helpers.find_color_ramp_parm(node)
            if parm is None:
                node.destroy()
                return False
            parm.set(self._entry_ramp(entry, basis))
        return True

    def create_code_node_in(self, index, dest, position=None) -> bool:
        """The code creation rule: the language's own carrier - a
        wrangle, an opencl, a python - wherever the network kind has
        one, loaded through the same apply the node drop uses."""
        if index is None or not index.isValid() or not self.code_model:
            return False
        source_index = self.code_sorted_model.mapToSource(index)
        row = source_index.row()
        if not 0 <= row < len(self.code_model.assets):
            return False
        asset = self.code_model.assets[row]
        type_name = self.code_carrier_type(index, dest)
        if not type_name:
            return False
        name = helpers.sanitize_usd_path(
            str(getattr(asset, "name", "") or "")) or "snippet"
        with hou.undos.group("Amaze Create Code Node"):
            node = self._create_carrier(dest, type_name, name, position)
            if node is None:
                return False
            ok, _reason = self.code_model.apply_to_node(row, node)
            if not ok:
                node.destroy()
                return False
        return True

    def drop_file_path_on_node(self, index, node) -> bool:
        """A File row released on a node: the node's FIRST file
        parameter takes the spelled path - the same act as selecting
        the node and double-clicking the row, aimed by the cursor
        instead of the selection. Uniform across kinds, unknown files
        included (ROADMAP - the interaction matrix, 2026-08-07). A
        node with no file parameter answers
        False, so the gesture shows its own refusal - the miss
        indicator and the tag flying home - never a dialog; the status
        line carries the why."""
        path = index.data(self.file_files_model.PathRole)
        if not path:
            return False
        parm = helpers.find_file_parm(node)
        if parm is None:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.setStatusMessage(
                    "Amaze: %s has no file parameter to take %s"
                    % (node.name(), os.path.basename(path)),
                    severity=hou.severityType.Warning,
                )
            return False
        with hou.undos.group("Amaze Set File Path"):
            parm.set(self._scene_path(path))
        return True

    def import_asset_to_mat(self):
        """Explicitly import the selected materials into /mat."""
        self.import_asset("mat")

    def import_asset_to_lop(self):
        """Explicitly import the selected materials into a LOP materiallibrary."""
        self.import_asset("lop")

    def slide(self) -> None:
        """Set IconSize via Slider - writes to the ACTIVE view mode's own
        persisted size (grid and list are independent)."""
        if not self.material_model or not self.category_model:
            return
        if self.prefs.view_mode == "list":
            # List has one size and a greyed slider; a stray value
            # change must not become a stored size.
            return
        value = self.click_slider.value()
        self.prefs.thumbsize = value
        # Persist debounced (500ms after the last slider tick) - saving
        # settings.json on every pixel of a drag would thrash a file
        # that lives in the cloud-synced install folder.
        self._thumbsize_save_timer.start()
        self.material_model.thumbsize = value

        # Apply sizing for the active mode (grid grows icons, list grows rows).
        self.apply_view_mode()
        # Also need to resize the images!
        self.material_model.set_custom_iconsize(QtCore.QSize(value, value))

    def box_fav_clicktoggle(self):
        if self.box_fav.checkState() == QtCore.Qt.CheckState.PartiallyChecked:
            self.box_fav.nextCheckState()
