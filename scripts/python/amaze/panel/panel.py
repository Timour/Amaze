"""Constructs the Python panel Widget for the MatLib and provides Views to the Models"""

import os
import importlib
import time
import contextlib

from PySide6 import QtWidgets, QtGui, QtCore, QtUiTools
import hou

import amaze
from amaze.core import grid_columns
from amaze.panel import (dragdrop_widgets, empty_state, grid, notes_panel,
                         sections, sidebar)
from amaze.core import debug, keyed_store, library_policy, locations, repair
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
    save_dialog,
    gradient_dialog,
    code_dialog,
    icon_dialog,
    user_dialog,
)
from amaze import branding
from amaze.prefs import prefs
from amaze.helpers import helpers, hostos, theme, ui_helpers, vex_syntax
from amaze.core import (
    database, dragengine, gallery_import, lop_assign, matx_icon, matx_translate, packages,
    tile_icons, users,
)
from amaze.render import (
    generator,
    material_converter,
    nodes,
    thumbs,
)
from amaze import preview

_DEV_RELOAD = bool(os.environ.get("AMAZE_DEV_RELOAD"))    # the reload chain below is OFF by default: it re-runs on every panel open to serve a reopen-to-refresh the live-test loop forbids anyway ▸r/module-reload


def _reload(module):
    """importlib.reload, unless the dev switch is off."""
    if _DEV_RELOAD:
        importlib.reload(module)


_reload(keyed_store)    # FIRST: eleven modules read their stores through it, so a stale engine keeps old tables while every caller gets new code; a re-register keeps existing bindings, so binder modules outside this chain stay whole
_reload(locations)      # right after the engine it binds two stores into - and the switch door calls locations.forget()
_reload(hostos)    # before library: the models import the shared thumbnail engine
_reload(debug)
_reload(dragengine)
_reload(lop_assign)
_reload(thumbnails)
_reload(database)
_reload(library_policy)    # before library, which gates overwriting on it
_reload(versions)
_reload(notes)
_reload(users)    # before versions and the dialogs showing a user: both resolve a UID through it, so a stale one answers from the previous library's people
_reload(material)
if _DEV_RELOAD:
    preview.reload_engine()    # the package RELOADS ITSELF: reloading a package re-runs only __init__.py, which hands back the cached submodules, so the chain would look complete and refresh nothing
_reload(material_converter)
_reload(nodes)
_reload(thumbs)
_reload(tile_icons)    # before gradient_library and the Node Info dialog, which read its facts
_reload(grid_columns)    # BEFORE library and its siblings: they mix in GridColumnsMixin, so a stale one has the models answering old columns while the header answers new
_reload(library)
_reload(category)
_reload(repair)
_reload(folders)
_reload(prefs)
_reload(theme)    # before ui_helpers, whose class bodies read theme colours
_reload(branding)    # FIRST of the ones below: everything reads its constants, and a stale branding produced 38 unhandled AttributeErrors live when APP_VERSION was added
_reload(ui_helpers)
_reload(helpers)
_reload(texture_library)
_reload(gradient_library)
_reload(cop_library)    # after library/category, so its subclasses bind to the freshly reloaded material classes
_reload(geo_library)    # after texture_library, whose ThumbnailCache/proxy it reuses
_reload(scene_captures)
_reload(file_library)    # after texture/geo/hip: it composes all three engines
_reload(vex_syntax)    # before code_library/code_dialog, which consume its palette and tokenizer
_reload(code_library)    # after library/category: it subclasses the material machinery

_reload(base_dialog)    # FIRST of the dialogs: gradient_dialog from-imports AssetDialog by CLASS, so reloading it without this re-binds the SAME stale class
_reload(prefs_dialog)
_reload(save_dialog)
_reload(icon_dialog)
_reload(gradient_dialog)
_reload(code_dialog)
_reload(user_dialog)
_reload(dragdrop_widgets)
_reload(grid)    # BEFORE sections, which imports it: every section's menu table reads the Grid area's builder and ListColumns
_reload(sidebar)
_reload(sections)
_reload(empty_state)    # after grid AND sections: it imports the first and reads the second's EMPTY declarations
_reload(notes_panel)
_reload(multifilterproxy_model)
_reload(matx_sources)    # the online stack, which was never in this chain at all
_reload(matx_translate)
_reload(matx_icon)
_reload(matx_import)
_reload(matx_library)
_reload(gallery_import)    # reachable from the Online menu, and missing here meant editing it did nothing until a full restart
_reload(packages)
_reload(generator)



from amaze.panel import delegates            # noqa: E402 - re-exported below because every section constructs them by these names

_reload(delegates)
AssetItemDelegate = delegates.AssetItemDelegate

_BODY_T0 = time.perf_counter()    #: when THIS module body began, so the chain above can be timed; NOT reload-survival state, every open runs it again

MULTIPLE_VALUES = material.MULTIPLE_VALUES    #: the mixed-multi-selection sentinel, ONE home in material.py because it is compared against and a second spelling is a silent overwrite
SidebarItemDelegate = delegates.SidebarItemDelegate

MIN_PANEL_WIDTH = 500    #: design px through `theme.ui_px` at use. ONE constant, never computed: a floor that moves under the user is worse than a narrow grid, and THE GRID PANE CARRIES NO MINIMUM because a child minimum propagates into the window's own ▸r/qt-windows-macos




class MatLibPanel(QtWidgets.QWidget):
    """Constructs the Python panel Widget for the MatLib and provides Views to the Models"""

    def __init__(self) -> None:
        super(MatLibPanel, self).__init__()
        self._construct_t0 = time.perf_counter()    # stamped before any work, so "panel ready" can report the two spans separately: everything the module body did before this point, and the construction itself
        self._first_show_logged = False
        debug.install()    # arm the always-on crash recorder before anything else, so a failure during construction lands in the log even with Debug Mode off (see core/debug.py)
        try:
            self._build()
        except Exception as exc:
            debug.exception("panel construction", exc)
            raise

    def _build(self) -> None:
        self.script_path = amaze.PACKAGE_ROOT    # the package locates its own bundled files ONE way
        self.prefs = prefs.Prefs()

        loaded = self.prefs.load()    # False means only that there was nothing usable on disk - no settings.json, an unreadable one, or a library directory that is gone - and the preferences object is populated either way, so the debug engine, the settings snapshot (the designated restore source) and the cache override must all run on BOTH paths: the session right after a settings loss is exactly the one whose record matters most
        debug.configure(self.prefs.debug_mode)    # configured before anything else runs: a crash during setup() is precisely the case a debug log has to survive
        debug.prefs_snapshot(self.prefs)
        hostos.set_cache_override(self.prefs.cache_dir)    # custom thumbnail-cache location, set before any cache is touched - everything downstream resolves hostos.cache_root()
        if loaded:
            self.init_ui()
            try:
                self.load()
                self.setup()
            except (ValueError, OSError) as broken:    # AN UNREADABLE INDEX GETS A DIALOG, NOT A TRACEBACK: this narrow catch absorbs exactly one situation - the primary index is on disk and will not parse - and offers the repair the shelf tool would run. Everything else still raises where it can be seen
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
            debug.event(    # construction-complete tripwire, through the same engine as the session header: a log whose header exists but whose 'panel ready' is missing means logging died DURING construction - see debug.probe()
                "session", "panel ready",
                module_body_ms=round(    # module body = the import plus the 50-module reload chain that runs before construction can start; construction = what "session start -> panel ready" always measured
                    (self._construct_t0 - _BODY_T0) * 1000, 1),
                construction_ms=round(
                    (time.perf_counter() - self._construct_t0) * 1000, 1),
                **debug.probe())
        else:
            self.init_ui()
            self._open_libraryless()

    def _open_libraryless(self) -> None:
        """The no-library shape of the panel: every model attribute present and None, so the gear (the only way to configure a library) and every guard keep working"""
        self.material_model = None
        self.category_model = None
        self.cop_model = None    # the Cop stack gets the same unconfigured defaults: save_cop_from_node is reachable from a node right-click at any time and guards on cop_model, so without this the guard itself raises AttributeError
        self.cop_category_model = None
        self.code_model = None
        self.code_category_model = None
        self.file_files_model = None    # the File models too: show_prefs hands file_files_model to the Preferences dialog (which takes None), and Preferences is the ONLY way to configure a library, so an unset attribute makes the gear an AttributeError on the machine that needs it most - the first run
        self.file_folders_model = None

    def _offer_index_repair(self, broken) -> bool:
        """The dialog an unreadable library.json earns - Repair (the newest saved copy, else the per-asset recovery stamps) or open without a library. True = repaired AND reopened; no success dialog, the recovered grid is the announcement"""
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

    MENU_ICON_FILES = {    # menu title -> icon asset, each with a baked-in corner triangle as the "opens a menu" hint. The EYE belongs on the Filter menu, which is what you can see, and the 3D box on the View menu, whose items are the library and the material sources. The gear (icon_library.svg) is NOT here: it is a plain ACTION button straight into Preferences, its triangle removed from the SVG, and the Library menu's items live on the Preferences Library tab
        "View": "icon_renderer.svg",
        "Filter": "icon_view.svg",
    }

    def _ui_icon_path(self, filename: str) -> str:
        """An icon in ui/, or "" for no filename (callers degrade) - resolved through `ui_asset` like the badge art, never a path join of its own. ▸p/adoption"""
        if not filename:
            return ""
        return ui_helpers.ui_asset(filename)

    def _make_menu_button(self, menu: QtWidgets.QMenu) -> "ui_helpers.IconMenuButton":
        """Opens `menu` from an icon button, standing in for a real QMenuBar item: QMainWindow reserves its menu bar a dock area that cannot share a row with other widgets, so the real menu bar (self.menu) stays alive and owns these QMenu objects but is hidden, and the button pops the same QMenu instance"""
        icon_path = self._ui_icon_path(
            self.MENU_ICON_FILES.get(menu.title(), "")
        )
        button = ui_helpers.IconMenuButton(menu, icon_path)
        button.setObjectName(    # a STABLE identity, independent of whether any panel attribute happens to hold the button: these are held by the layout alone, so unnamed they would collapse onto ONE ui_snapshot key - interchangeable "IconMenuButton" entries, where swapping two of them on screen passes every layout test and deleting one is invisible
            "btn_menu_" + "".join(
                c for c in menu.title().lower() if c.isalnum())
        )
        return button

    def setup(self):
        self.category_model = category.Categories(preferences=self.prefs)    # UNSORTED, all four sidebar proxies: the stored list order IS the sidebar order, manual and drag-to-reorder. A name sort put "_All" below any digit-named category; the proxy presents source order (probed) and only filters
        self.category_sorted_model = category.CategoriesSidebarProxy()
        self.category_sorted_model.setSourceModel(self.category_model)
        self.category_sorted_model.hide_empty = self.prefs.hide_empty_categories

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
            category_color_role=self.material_model.CategoryColorRole,    # Nodes and Code share this delegate (one grid view, models swapped) and share the role NUMBER, both models subclassing MaterialLibrary, so one wiring here colours all three
            versions_role=self.material_model.VersionsRole,
            notes_role=self.material_model.NotesRole,
            active_version_role=self.material_model.ActiveVersionRole,
        )
        self.thumb_delegate.set_badge_click("versions", self._open_versions_dialog)    # a click on the versions badge opens the Versions dialog: the delegate only detects the hit, the panel owns the dialog
        self.thumb_delegate.set_badge_click("favourite", self._favourite_badge_clicked)    # wiring the click is what makes the star a BUTTON with a visible rest state; the online delegate wires neither, so its corner stays empty

        self.asset_delegate = AssetItemDelegate(    # Node and Code get their OWN delegate, without the version roles. `grid.sync_table_columns` decides a column exists from the active delegate's roles, so borrowing thumb_delegate painted a "Version" column reading "none" on every row, floored at the width of "Version 99". Latent and worse: editorEvent and _sync_versions_hover run against that delegate too, and _open_versions_dialog maps through the MATERIAL proxy and indexes material_model.assets - so a Node or Code asset with a versions ledger would open an unrelated MATERIAL. overview.md §2 and ListColumnHeader.COLUMNS both say Version is materials-only and Open is File-only; this is what delivers it
            self.material_model.RendererLabelRole,
            self.thumblist,
            category_role=self.material_model.CategoryRole,
            favorite_role=self.material_model.FavoriteRole,
            tag_role=self.material_model.TagRole,
            licence_role=self.material_model.LicenceRole,
            category_color_role=self.material_model.CategoryColorRole,
            notes_role=self.material_model.NotesRole,
        )
        self.asset_delegate.set_badge_click(
            "favourite", self._favourite_badge_clicked)

        self.file_folders_model = file_library.FileFolders(self.prefs)    # the File section merges Images, Geometry and HIP: one folder-pointer list plus the synthetic "All" row, and a live, non-persisted listing of EVERY file in the selected folder, each row behaving as its kind. Filtered through TextureFilterProxyModel for the search box and favourites star; see core/file_library.py
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
        self.file_delegate.set_badge_click(
            "favourite", self._favourite_badge_clicked)
        self._sync_notes_button_pixmaps()    # the star preference colours the NOTES surfaces (chip lit + pane accent); tile badges render as drawn and take no colour push. The accent sweep for the tile delegates runs at the END of setup() instead, because tile_delegates() derives from self.sections, which do not exist yet here - a sweep at this point walks an empty tuple. The "Type" header label follows the same accent as the type entries the delegates paint
        self.sidebar_delegate.show_counts = self.prefs.sidebar_counts
        thumbnails.engine.set_budget_mb(self.prefs.ram_cache_mb)
        self.file_files_model.progress_changed.connect(
            lambda done, total: self._on_folder_progress(
                "file", done, total))

        self.gradient_model = gradient_library.GradientLibrary(    # the Gradients section is Sanzo Wada's colour combinations as curated, read-only content: painted thumbnails, no files and no workers, so the model trio is all there is to set up (core/gradient_library.py)
            preferences=self.prefs)
        self.gradient_categories_model = gradient_library.GradientCategories(
            preferences=self.prefs
        )
        self.gradient_category_sorted_model = category.CategoriesSidebarProxy()    # the SAME proxy class as the other three sidebars and unsorted like them; Colors showing its model bare was the last odd-one-out pipeline. Nothing hides here - no renderer filter is ever pushed - and the unification is the point
        self.gradient_category_sorted_model.setSourceModel(
            self.gradient_categories_model)
        self.gradient_category_sorted_model.hide_empty = (
            self.prefs.hide_empty_categories)
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
        )    # no per-delegate accent is set here: the one sweep at the end of setup() covers every tile delegate, and a hand-set on this one masked the dead early sweep for exactly one of five
        self.gradient_delegate.set_badge_click(
            "favourite", self._favourite_badge_clicked)

        self.cop_model = cop_library.CopLibrary(preferences=self.prefs)    # the Cop section is standalone COP-network assets: a second, fully independent material-style stack over its own cops.json (core/cop_library.py), mirroring the material model/proxy/selection construction above. It uses `asset_delegate`, NOT thumb_delegate
        self.cop_category_model = cop_library.CopCategories(preferences=self.prefs)
        self.cop_category_sorted_model = category.CategoriesSidebarProxy()
        self.cop_category_sorted_model.setSourceModel(self.cop_category_model)
        self.cop_category_sorted_model.hide_empty = self.prefs.hide_empty_categories
        self.cop_sorted_model = multifilterproxy_model.MultiFilterProxyModel()
        self.cop_sorted_model.setSourceModel(self.cop_model)
        self.cop_sorted_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.cop_sorted_model.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.cop_sorted_model.sort(0)
        self.cop_sorted_model.setDynamicSortFilter(False)
        self.cop_selection_model = QtCore.QItemSelectionModel(self.cop_sorted_model)

        self.code_model = code_library.CodeLibrary(preferences=self.prefs)    # the Code section is reusable snippets over its own code.json (core/code_library.py): the same material machinery as COP, storing snippet text inline and painting a code preview
        self.code_category_model = code_library.CodeCategories(
            preferences=self.prefs
        )
        self.code_category_sorted_model = category.CategoriesSidebarProxy()
        self.code_category_sorted_model.setSourceModel(self.code_category_model)
        self.code_category_sorted_model.hide_empty = self.prefs.hide_empty_categories
        self.code_sorted_model = multifilterproxy_model.MultiFilterProxyModel()
        self.code_sorted_model.setSourceModel(self.code_model)
        self.code_sorted_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.code_sorted_model.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.code_sorted_model.sort(0)
        self.code_sorted_model.setDynamicSortFilter(False)
        self.code_selection_model = QtCore.QItemSelectionModel(self.code_sorted_model)
        self._seed_curated_content()    # seeds the snippets AND the palettes once per library, through one door a library switch also takes, so a virgin library seeds whichever way it arrives

        for _model in (self.material_model, self.cop_model, self.code_model):    # multi-category was removed, so every asset collapses to its first category; idempotent, so this one-time migration no-ops on every subsequent launch
            try:
                _model.collapse_multicategory()
            except Exception as exc:
                debug.event("session", "category collapse failed",    # event, not note, at all four panel sites: the panel's user-facing channel here is a dialog, and each of these lines is an internal fallback the user cannot act on
                            error=str(exc))

        self.matx_online_model = matx_library.MatxOnlineLibrary(    # the online MaterialX browser is NOT a section but a VIEW MODE over the Materials grid (View > Online Materials); it uses the same role numbers as MaterialLibrary, so the existing delegate and filter proxy serve it unchanged
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
        self.matx_delegate = AssetItemDelegate(    # the online world gets its own delegate, with only the roles its model has: matx_library exposes seven and none is licence, versions, notes or category colour, so borrowing a local delegate gave the online grid columns that can never carry a value on any row. Same defect shape as Node and Code borrowing the Materials delegate, one world over
            self.matx_online_model.RendererLabelRole,
            self.thumblist,
            category_role=self.matx_online_model.CategoryRole,
            favorite_role=self.matx_online_model.FavoriteRole,
            tag_role=self.matx_online_model.TagRole,
        )
        self.matx_online_model.progress_changed.connect(    # preview downloads drive the same thin bar as texture/geo thumbs
            self._on_online_preview_progress
        )
        self.online_mode = False
        self.online_source = None
        self.online_context = sections.OnlineContext(self)    # the online world as a context object with a Section's interface. NOT in `sections` and not in `enabled_sections` - it is a parallel world, not a section - but every area path reaches it through `_section()` like any other

        self.material_selection_model.selectionChanged.connect(self.update_details_view)
        for _notes_selection in (    # keyboard selection moves reach the Notes pane too, every section's selection model, guarded inside the handler: a no-op while the pane is hidden, and it reads only the ACTIVE section's current index. Connected HERE because the models are built in setup(), after init_ui
            self.material_selection_model,
            self.cop_selection_model,
            self.code_selection_model,
            self.file_selection_model,
            self.gradient_selection_model,
        ):
            _notes_selection.selectionChanged.connect(
                self._refresh_notes_subject)

        self.sections = sections.build_sections(self)    # the section registry: one object per tab, each encapsulating how it drives the shared widgets (activate/filter/favourites/category-select/double-click). Shared handlers dispatch to self._section() instead of branching on current_section, so a new section is a new class in panel/sections.py, not edits here

        self.sidebar_reorder = sidebar.SidebarReorder(self)    # the press-hold sidebar reorder: one controller for the one sidebar list, asking whichever context is active, parented to cat_list so it dies with the widget

        for tile_delegate in self.tile_delegates():    # the tile subtitle line follows the accent preference for EVERY tile delegate; the instance attribute shadows the class default and show_prefs() refreshes it when the accent changes. AFTER build_sections deliberately, because tile_delegates() derives from the sections and any earlier sweep walks an empty tuple
            tile_delegate.DIM = theme.accent(self.prefs.accent_color)

        first_key = next(    # start on the first ENABLED section - usually Materials, but a user may have hidden it; the models all exist regardless of which tabs are shown
            (k for k, _ in self.ALL_SECTIONS if k in self.prefs.enabled_sections),
            "material",
        )
        if first_key == "material":
            self.sections["material"].activate()
        else:
            self._on_tab_toggled(first_key, True)
        self.section_tabs.setChecked(first_key, emit=False)
        self._sync_toolbar_for_mode()    # the Materials branch above does NOT go through _on_tab_toggled, so the toolbar sync every tab click gets never ran for the section the panel OPENS on - the one a user sees first
        self.build_filter_menu()    # and the Filter menu belongs to the section that just opened, so it is filled here for the same reason
        self.click_slider.setValue(grid.active_thumbsize(self))
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

        self.switch_all_models()    # THE SAME WALK every other switch site uses, never a copy of it

        debug.event("session", "library reloaded")

    @staticmethod
    def starter_would_overwrite(lib_dir: str) -> list:
        """The evidence that `lib_dir` has HELD a library, or [] - ONE function, so load() and the test that proves load() refuses ask exactly the same question rather than two copies of it"""
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
        """Load the currently in preferences specified library, copying necessary data to the target directory if not created yet"""
        lib_dir = self.prefs.dir
        if not lib_dir or lib_dir == "/" or not os.path.isdir(lib_dir):
            debug.event("session", "no library directory set",    # no (or invalid) library directory set: the panel opens library-less and the Preferences Library tab sets one. The guard is load-bearing - copying the starter db against an empty dir once wrote to the filesystem root ("//library.json")
                        dir=lib_dir)
            return
        new_folder = False
        if not os.path.exists(self.prefs.dir + "/library.json"):
            held = self.starter_would_overwrite(self.prefs.dir)    # ABSENT IS NOT EMPTY: every cause _refuse_absent exists for - a sync that has not finished arriving, a selective-sync hole, a network volume mid-mount - leaves a directory FULL of assets with a momentarily missing index, and seeding the starter over that turns a hiccup into a library whose next Clean reads every real file as unowned. It asks database.absent_but_known, deliberately the same question the loaders ask, so the two can never disagree
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
            prefs.seed_starter_index(self.prefs.dir)    # the shipped starter carries no version key, so it is STAMPED on the way in rather than copied verbatim ▸p/library-creation-doors
            new_folder = True
        if self.ensure_library_dirs(self.prefs):
            new_folder = True
        if new_folder:
            debug.event("session", "library created", dir=self.prefs.dir)

    @staticmethod
    def ensure_library_dirs(preferences) -> bool:
        """Make sure `img/` and `mat/` both exist, ASKED PER FOLDER rather than guarded as a pair, and with `exist_ok=True` like every other folder-creating site in this package. True if either was created"""
        made = False
        for tail in (preferences.img_dir, preferences.asset_dir):
            folder = os.path.join(preferences.dir, tail)
            if not os.path.isdir(folder):
                made = True
            os.makedirs(folder, exist_ok=True)
        return made

    def set_library(self) -> None:
        """User Sets library via Menu Option so we have to reroute"""
        if self.prefs.get_dir_from_user():
            self.prefs.load()
            self.load()
            if not self.material_model:
                self.setup()

            self.switch_all_models()    # EVERY library-backed model switches, not just the Materials pair

    def library_models(self) -> tuple:
        """EVERY library-backed model that exists right now, DERIVED from the sections the way `tile_delegates()` derives - each section declares its own in `library_model_attrs`, so a section arriving with a model of its own joins by existing"""
        found = []
        for section in getattr(self, "sections", {}).values():
            for attr in getattr(section, "library_model_attrs", ()):
                model = getattr(self, attr, None)
                if model is not None and model not in found:
                    found.append(model)
        return tuple(found)

    def switch_all_models(self) -> None:
        """Re-point every library-backed model at `prefs.dir` - THE ONE ROUTE ONTO ANOTHER LIBRARY and the only route that re-points models at all, because a model a switch skips goes on serving the previous library with every save refused"""
        locations.forget()    # drop EVERY cached store table first (keyed_store.release inside), so a switch BACK to a library re-reads what is on disk instead of serving the session's old rows - sync can land another machine's edits behind the cache (test_switch_rereads is the pin) - and re-arm the migration retry guards, since a switch is exactly the change that earns another try
        models = self.library_models()
        if not models:
            return
        with ui_helpers.relayout(*models):
            for m in models:
                m.switch_model_data()
            self.click_slider.setValue(grid.active_thumbsize(self))
        self._seed_curated_content()    # a switch can land on a library nobody has opened before, and a virgin library gets its curated content however it arrives - the same door construction takes, marker-guarded, so an already-seeded library costs two stat calls

    def _seed_curated_content(self) -> None:
        """Seed the curated starters once per library - the Code section's Toolbox snippets and the Colors section's palette sets - through ONE door for construction and the library switch. getattr, not attribute reads: the libraryless shape leaves model attributes None or absent"""
        code_model = getattr(self, "code_model", None)
        if code_model is not None:
            code_model.seed_starter_snippets(self.code_category_model)
        gradient_model = getattr(self, "gradient_model", None)
        if gradient_model is not None:
            gradient_model.seed_curated_palettes(
                self.gradient_categories_model)

    def toggle_catview(self) -> None:
        """Show and Hide the Category View via Menu"""
        if self.action_catview.isChecked():
            self.cat_wrapper.setVisible(True)
            self.action_catview.setChecked(True)
        else:
            self.cat_wrapper.setVisible(False)
            self.action_catview.setChecked(False)
        self.prefs.show_categories = self.action_catview.isChecked()    # remembered across sessions
        self.prefs.save()
        button = getattr(self, "btn_categories", None)    # the chip IS this state, so it is kept in step whichever side moved - the action can still be toggled from code and from tests
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
        """Amber when you are in the online world, the family blue when you are not - the star's treatment, through the one engine"""
        button = getattr(self, "btn_online", None)
        if button is None:
            return
        button.set_art(
            self._ui_icon_path("icon_online.svg"),
            lighten_on_hover=False,
            recolour_on={ui_helpers.IconMenuButton.IDLE_BODY:
                         theme.color_hex("star")})

    def _sync_categories_button_pixmaps(self) -> None:
        """The chip's four states, in the toolbar icon family's own tints - as drawn at rest, lit when hovered or on"""
        button = getattr(self, "btn_categories", None)
        if button is None:
            return
        button.set_art(self._ui_icon_path("icon_categories.svg"),
                       lighten_on_hover=False)

    def edit_material_info(self) -> None:
        """Open the material info dialog for the current selection (right-click "Edit Info") - update_details_view already keeps the form populated from the selection, so this only shows and raises the floating dialog"""
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

    def bind_grid_views(self, proxy, selection, delegate) -> None:
        """Point BOTH grid views at one context's model, proxy, selection model and delegate - two views over ONE selection model is Qt's own arrangement, so a section's `activate()` binds once and neither view can drift from the other"""
        for view in (self.thumblist, getattr(self, "thumbtable", None)):
            if view is None:
                continue
            view.setModel(proxy)
            if selection is not None:
                view.setSelectionModel(selection)
        if delegate is not None:
            self.thumblist.setItemDelegate(delegate)
            grid.bind_table_cell_delegates(self, delegate)    # THE TABLE DOES NOT WEAR THE TILE DELEGATE: that one paints a whole TILE per index, right where an index is a tile and catastrophic where a row is ten of them. Qt paints every text cell itself; only the picture and the tick columns get a delegate, and those are per COLUMN

    CELL_PAD = theme.ui_px(5)    #: air either side of a cell's text; ONE home, named here only because the header must start its label where the rows start theirs. NOT a `QTableView::item` sheet (that hands item drawing to QStyleSheetStyle and takes the font and selection colours with it) and not a QProxyStyle (setStyle does not own it)
    HEADER_BG = QtGui.QColor("#2a2a2a")    #: the strip's own colours and height, kept so the table matches the painted header it replaced - a QHeaderView picks up none of them. The LABEL colour is the rows' ink, read from the delegate
    HEADER_DIVIDER = QtGui.QColor("#454545")
    HEADER_HEIGHT = theme.ui_px(20)

    def sync_list_columns(self) -> None:
        """Re-fit list mode's columns for the context now showing - THE SECTIONS' entry point, called from every `activate()`."""
        return grid.sync_table_columns(self)

    COLUMN_DEFAULT_WIDTH = {    #: starting widths, derived offscreen from the real library and never measured at runtime: a fit cost 13.5ms over every row and re-ran on every row-set change, which is what made a big category slow to open. Each is the wider of its heading and the p90 of its values, capped at 300 so one long Tags entry cannot eat the row

        "thumb": 24, "name": 176, "type": 59, "category": 76,
        "favorite": 69, "version": 66, "open": 54, "comments": 85,
        "tags": 300, "license": 287,
    }

    COLUMN_MIN_WIDTH = 24    #: the floor for ANY column: `minimumSectionSize` is global rather than per-column, so License cannot be given one of its own; small enough that a tick column is not forced wide

    def apply_view_mode(self) -> None:
        grid.apply_view_mode(self)
        empty_state.track(self)    # the other view is up now, so the blank re-attaches to ITS model rather than relying on the two sharing a proxy

    def showEvent(self, event):
        """Record construct-to-painted on the FIRST show only - reopening a tab must not look like a fresh open - and after the event loop turns once, so the number includes the first paint: "panel ready" fires while the widget is still unparented and unpainted, before Houdini shows it and Qt polishes it under the Houdini stylesheet, lays it out and paints the first page of tiles"""
        super(MatLibPanel, self).showEvent(event)
        if self._first_show_logged:
            return
        self._first_show_logged = True
        QtCore.QTimer.singleShot(0, self.ensure_library_user)    # after the first paint, never during construction: a modal dialog raised from a half-built panel blocks the paint it is sitting on top of
        t0 = getattr(self, "_construct_t0", None)
        if t0 is None:
            return

        def _record():
            debug.event(
                "session", "panel visible",
                construct_to_painted_ms=round(
                    (time.perf_counter() - t0) * 1000, 1))

        QtCore.QTimer.singleShot(0, _record)

    def ensure_library_user(self, chooser=None) -> str:
        """Ask WHICH user this machine is, and ONLY where the library already has some and this one is not among them (`users.ASK`): a library with nobody in it mints silently, a machine whose pointer already resolves is never questioned, and cancelling is allowed - it leaves no user, so nothing is keyed under a blank this session and the question comes back next time. `chooser` takes `{uid: name}` and answers `(uid, new_name)`, both empty for a cancel, so the decision can be driven without a dialog on screen"""
        preferences = self.prefs
        if users.first_run_state(preferences) != users.ASK:
            return users.current(preferences) or ""
        known = users.all_users(preferences)
        if chooser is None:
            def chooser(entries):
                dialog = user_dialog.UserPickerDialog(entries)
                dialog.exec()
                if dialog.canceled:
                    return ("", "")
                return (dialog.uid, dialog.new_name)
        uid, new_name = chooser(known)
        if not uid and new_name:
            uid = users.create(preferences, new_name)
        if not uid:
            debug.event("users", "no user picked for this library",
                        known=len(known))
            return ""
        users.adopt(preferences, uid)
        return uid

    def event(self, event):
        """Flush the Comments pane when this panel is being DESTROYED. Measured (Qt 6.8, offscreen): hiding or closing a window sends its children a hide event, which the pane's own hideEvent covers, but DELETING a parent sends its children nothing at all - and that is how a Houdini pane tab goes away, taking the last 600ms of typing (the save debounce) with it. DeferredDelete arrives while every widget is still alive, which is what makes the pending page serializable here"""
        if event.type() == QtCore.QEvent.Type.DeferredDelete:
            pane = getattr(self, "notes_panel", None)
            if pane is not None:
                pane.flush()
        return super(MatLibPanel, self).event(event)

    def eventFilter(self, watched, event):
        """Hover tracking for the grid's button badges, and nothing else: `thumblist` is hidden the whole time list mode is up, and the table sizes its own rows and columns in `grid.show_table` and `grid.sync_table_columns`"""
        if (getattr(self, "thumblist", None) is not None
                and watched is self.thumblist.viewport()
                and hasattr(self, "thumb_delegate")):
            if event.type() == QtCore.QEvent.Type.MouseMove:
                self._sync_badge_hover(event.position().toPoint())
            elif event.type() == QtCore.QEvent.Type.Leave:
                self._sync_badge_hover(None)
        return False

    def _sync_badge_hover(self, point) -> None:
        """Light the button badge the cursor is on, and only that one. Repaints ONLY when the answer changed - this runs on every mouse move across the grid"""
        delegate = self.thumblist.itemDelegate()    # THE ACTIVE delegate, never thumb_delegate by name: Node and Code have their own (no version roles), and hard-coding the Materials one runs the hit-test and hover state against a delegate that is not the one painting
        if not hasattr(delegate, "button_badge_at"):
            return
        badge = None
        index = QtCore.QModelIndex()
        if point is not None:
            candidate = self.thumblist.indexAt(point)
            if candidate.isValid():
                badge = delegate.button_badge_at(
                    candidate,
                    self.thumblist.visualRect(candidate),
                    point,
                    self.thumblist.viewMode()
                    != QtWidgets.QListView.ViewMode.ListMode)    # the WIDGET's own answer, like the delegate's - prefs.view_mode would be a third proxy for one fact
                if badge is not None:
                    index = candidate
        previous = delegate._button_hover
        if delegate.set_button_hover(
                badge.name if badge is not None else None, index):
            if previous is not None and previous[1].isValid():
                self.thumblist.update(QtCore.QModelIndex(previous[1]))
            if index.isValid():
                self.thumblist.update(index)






    LIST_THUMB_SIZE = 16    # list mode's ONE size: a list row is a text line, not a picture, so it does not scale and its slider is greyed - 16px of thumbnail under a ~30px row. `thumbsize_list` is still WRITTEN for older builds on the other machine, and no longer read here

    def _sync_slider_for_mode(self) -> None:
        """The slider drives GRID only: in list it is greyed - one list size, nothing to choose - and its value parked at the minimum so the handle does not sit somewhere that implies otherwise"""
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
        self.click_slider.setValue(grid.active_thumbsize(self))    # jump the slider to the new mode's own remembered size: if the value actually changes this fires slide(), which re-applies sizing and icons, and the explicit apply_view_mode() below covers the equal-values case, where setValue emits nothing but the view still has to restructure
        self.apply_view_mode()

    def on_viewmode_button(self, checked: bool) -> None:
        """Filter-row toggle: checked = list, unchecked = grid."""
        if getattr(self, "_suppress_view_signals", False):
            return
        self._set_view_mode("list" if checked else "grid")

    def _build_slider_and_layout(self) -> None:
        """The size slider, the filter box's icon, and the panel's own layout."""
        self.click_slider.setMaximumWidth(theme.ui_px(200))    # the slider paints its own Houdini-22-style groove and handle in ClickSlider.paintEvent: QSS sub-page/add-page styling is unreliable for it (colours land on the correct side, the declared heights do not), so it draws itself deterministically and a stylesheet is not the way to change its look
        if self.toolbar_layout is not None:
            idx = getattr(    # the design's order is [Filter box] [slider] [star] [toggle] [menus] but this block runs AFTER the star/toggle blocks, so the slider goes in at the spot remembered right after the filter box was added; both slider-side gaps are 20 design px
                self, "_after_filter_index", self.toolbar_layout.count()
            )
            self.toolbar_layout.insertSpacing(idx, theme.ui_px(20))
            self.toolbar_layout.insertWidget(idx + 1, self.click_slider)
            self.toolbar_layout.insertSpacing(idx + 2, theme.ui_px(20))
        self._thumbsize_save_timer = QtCore.QTimer(self)    # debounce for persisting the per-mode icon size: slide() fires on every pixel of a drag and settings.json lives in the cloud-synced install folder, so write once shortly after the drag settles rather than dozens of times a second
        self._thumbsize_save_timer.setSingleShot(True)
        self._thumbsize_save_timer.setInterval(500)
        self._thumbsize_save_timer.timeout.connect(self.prefs.save)
        self.click_slider.valueChanged.connect(self.slide)

        self._mirror_toolbar()    # mirrors the whole toolbar row to the left, so every toolbar_layout addition must already be done - the slider insertion above is the last one

        self.thumblist.customContextMenuRequested.connect(self.thumblist_rc_menu)
        self.cat_list.customContextMenuRequested.connect(self.catlist_rc_menu)

        mainlayout = QtWidgets.QVBoxLayout()
        mainlayout.addWidget(self.ui)
        mainlayout.setContentsMargins(0, 0, 0, 0)  # Remove Margins

        self.setLayout(mainlayout)

    def _build_menus(self) -> None:
        """The View and Renderer menus, and the toolbar buttons that own them. Called from init_ui in the order it ran in; no local variable crosses this boundary."""
        self.menu.addMenu(self.menu_filter)
        if self.toolbar_layout is not None:
            menu_view = self.ui.findChild(QtWidgets.QMenu, "menuView")    # icon controls at the toolbar's right end, left to right: Filter (box, menu), View (eye, menu), Preferences (gear, outermost - a PLAIN button straight into Preferences, the Library menu it used to pop having dissolved into the dialog's Library tab)
            self.btn_notes = ui_helpers.ChipToggleButton()    # the Comments chip joins the ICON FAMILY and stays blue in ALL FOUR states, the state carried by the chip's BACKGROUND - `_sync_notes_button_pixmaps` has the reasoning. Built FIRST of the toolbar chips, with Online, Filter, Categories and Capture following, and the row is mirrored afterwards, so build order is NOT display order; overview.md §2 has where it lands
            self.btn_notes.setObjectName("btn_notes")
            self.btn_notes.setToolTip(ui_helpers.tooltip_text(
                "Comments - a page of text and to-dos for the selected "
                "tile"))
            self._sync_notes_button_pixmaps()
            self.btn_notes.setChecked(bool(self.prefs.show_notes))
            self.btn_notes.toggled.connect(self._on_notes_toggled)    # connected AFTER the initial state, so restoring a saved "open" does not re-save preferences mid-construction
            self.toolbar_layout.addWidget(self.btn_notes)
            self.toolbar_layout.addSpacing(theme.ui_px(2))
            self.btn_online = ui_helpers.ChipToggleButton()    # Online sits immediately LEFT of Comments once the row is mirrored, so it is added right after it here. The AMBER is the whole signal that you are in the other world - the favourites star's pattern exactly, so it is built the same way by the same engine, and does not lighten on hover because the colour is what carries the state
            self.btn_online.setObjectName("btn_online")
            self.btn_online.setToolTip(ui_helpers.tooltip_text(
                "Browse materials online."))
            self._sync_online_button_pixmaps()
            self.btn_online.setChecked(self._is_online())
            self.btn_online.toggled.connect(self._on_online_button)
            self.toolbar_layout.addWidget(self.btn_online)
            self.toolbar_layout.addSpacing(theme.ui_px(2))
            self.btn_filter = self._make_menu_button(self.menu_filter)    # held on self, unlike the other two menu buttons: this one is disabled online and its tooltip is rewritten on every section change, so the layout is no longer the only thing that needs to reach it
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
            btn_prefs.setObjectName("btn_prefs")    # named for the same reason as the two menu buttons above - nothing else tells these three apart. Deliberately NOT also stored on self: the layout owns it, and adding an attribute is what made a toolbar test report a naming refactor as a layout defect
            btn_prefs.setToolTip(ui_helpers.tooltip_text(
                "Open preferences."))
            self.toolbar_layout.addWidget(btn_prefs)
            self.toolbar_layout.addSpacing(theme.ui_px(2))
            self.btn_categories = ui_helpers.ChipToggleButton()    # Show Categories, promoted out of the View menu to a button of its own. Added AFTER the gear because the row is mirrored at the end of construction, so the last widget added is the leftmost drawn. It DRIVES action_catview rather than repeating it: the action owns the behaviour and the persistence, and two paths to one preference is how a toggle ends up disagreeing with the thing it toggles
            self.btn_categories.setObjectName("btn_categories")
            self.btn_categories.setToolTip(ui_helpers.tooltip_text(
                "Show the category sidebar."))
            self._sync_categories_button_pixmaps()
            self.btn_categories.setChecked(
                bool(self.prefs.show_categories))
            self.btn_categories.toggled.connect(
                self._on_categories_button)
            self.toolbar_layout.addWidget(self.btn_categories)
            self.toolbar_layout.addSpacing(theme.ui_px(2))
            self.btn_hip_capture = ui_helpers.IconMenuButton(    # Capture, outermost and HIP only: same button class and same 2px gap as the cluster left of it, so it reads as one row rather than an afterthought. Hidden for every other section, because it acts on the open SCENE, which is meaningless where the tiles are materials
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
        self.filter_action_group = None    # the Filter menu is NOT built here: its entries belong to whichever section is showing and no section exists yet at this point in construction. build_filter_menu fills it, and runs again on every section change
        self.filter_actions = {}
        self.filter_values = {}

        self.view_actions = {}    # the View menu follows the UI text register's order; the .ui supplies action_show_cat with a trailing separator, so that separator is dropped, the action relabelled "Show Categories", and the material-source items inserted above it. NO Grid/List rows - the toolbar's grid-list chip is the control, and a menu pair beside it would be a second way to one preference. This dict stays EMPTY: grid.sync_view_mode_controls pushes the current mode into whatever is in it, so empty means "nothing else to keep in step" without a branch
        menu_view = self.ui.findChild(QtWidgets.QMenu, "menuView")
        if menu_view is not None:
            for a in list(menu_view.actions()):
                if a.isSeparator():
                    menu_view.removeAction(a)
            anchor = self.action_catview        # = action_show_cat
            self.action_catview.setText("Show Categories")
            self.show_cat_group = QtGui.QActionGroup(self)    # renders "Show Categories" with a radio-style CIRCLE to match the other View items: a standalone checkable action draws a checkmark, one in an exclusive group draws a circle, and ExclusiveOptional keeps it a free on/off toggle since a lone member can be unchecked
            self.show_cat_group.setExclusionPolicy(
                QtGui.QActionGroup.ExclusionPolicy.ExclusiveOptional
            )
            self.show_cat_group.addAction(self.action_catview)

            self.online_source_group = QtGui.QActionGroup(self)    # Material Library and each online source form ONE exclusive group, so picking a source unchecks Material Library and vice versa, with Material Library the default. Browsing online is a VIEW MODE over the Materials tab, which is why it lives in the View menu rather than the Renderer menu
            self.online_source_group.setExclusive(True)
            self.action_material_library = QtGui.QAction(
                "Material Library", self
            )
            self.action_material_library.setCheckable(True)
            self.action_material_library.setChecked(True)
            self.online_source_group.addAction(self.action_material_library)    # action_material_library is NOT in the menu: its one job was leaving the online browser and the toolbar's Online button does that. The action stays because _on_online_source recognises it as "the local library" and it is the group's default checked member

            self.online_menu = menu_view    # no submenu: the online SOURCES live in the online world's tab strip, reached by the toolbar button, so a menu row each would be a second way to one place. What stays here is the one-shot importers below, and two entries do not earn a submenu
            self.online_source_actions = {}    # stays, and stays EMPTY: open_online_source looks a name up here to tick the matching row, and an empty dict answers "no row to tick" without a special case
            self.action_gallery_import = self.online_menu.addAction(
                "Gallery Import (.gal)"
            )
            self.action_gallery_import.triggered.connect(
                self.import_galleries
            )
            self.action_package_import = self.online_menu.addAction(
                "Package Import (.amazepkg)"
            )
            self.action_package_import.triggered.connect(
                self.import_amaze_package
            )
            self.online_menu.addSeparator()    # generating is a third way to get a material into the scene, beside browsing online sources and importing a gallery, so it gets its own group below them
            self.action_generate_material = self.online_menu.addAction(
                "Generate Material"
            )
            self.action_generate_material.triggered.connect(
                self.generate_random_material
            )
            menu_view.removeAction(self.action_catview)    # "Show Categories" is a toolbar button, so a menu entry would be a second control for one preference. The ACTION stays - it owns the behaviour and the button drives it - and only its menu row goes
            self.online_source_group.triggered.connect(self._on_online_source)


    def _build_view_toggles(self) -> None:
        """The favorites chip and the grid/list toggle."""
        self.cb_favsonly = ui_helpers.ChipToggleButton()
        self.cb_favsonly.setObjectName("cb_favsonly")
        self.cb_favsonly.setToolTip(ui_helpers.tooltip_text(
            "Show favorites."))
        try:
            self.cb_favsonly.set_art(
                self._ui_icon_path("star.svg"),
                self._ui_icon_path("star_on.svg"),
                lighten_on_hover=False,    # the amber fill IS the on/off signal here, so hover must not whiten it: the two states would be indistinguishable mid-hover
            )
        except (TypeError, AttributeError):
            pass
        self.cb_favsonly.toggled.connect(self.filter_favs)
        if self.toolbar_layout is not None:
            self.toolbar_layout.addWidget(self.cb_favsonly)
            self.toolbar_layout.addSpacing(theme.ui_px(2))    # tight 2px gaps through the right-hand icon cluster: the design's ~21px rendered icon-to-icon spacing is mostly each button's own internal padding already

        self.ui.cb_ViewMode.setVisible(False)  # type: ignore
        self.cb_viewmode = ui_helpers.ChipToggleButton()    # the Grid/List view-mode toggle, the same hand-painted chip treatment as the star: unchecked = grid (icon mode), checked = list mode, and the icon shows the CURRENT mode
        self.cb_viewmode.setObjectName("cb_viewmode")
        self.cb_viewmode.setToolTip(ui_helpers.tooltip_text(
            "Switch between the thumbnail grid and the detail list."))
        try:
            self.cb_viewmode.set_art(    # both hover variants whiten to the shared light colour, which is safe here because grid and list are different SHAPES - the lightening cannot be mistaken for a change of state
                self._ui_icon_path("grid.svg"),
                self._ui_icon_path("list.svg"),
            )
        except (TypeError, AttributeError):
            pass

    def _build_splitter_and_sidebar(self) -> None:
        """The splitter proportions and the category sidebar's palette."""
        self._section_view_state = {}    # per-section view memory: sidebar choice + grid scroll, captured on every tab switch so returning to a section lands where it was left. In-memory only - Textures additionally persist their folder across sessions via prefs
        splitter = self.cat_list.parentWidget()
        cat_index = -1
        if isinstance(splitter, QtWidgets.QSplitter):
            cat_index = splitter.indexOf(self.cat_list)
            self.notes_panel = notes_panel.NotesPanel(self.prefs)    # the Notes panel docks as the splitter's RIGHTMOST pane: sidebar | grid | notes. Hidden until its toolbar button shows it, and that visibility persists
            splitter.addWidget(self.notes_panel)
            self.notes_panel.adopt_look(self.cat_list)
            splitter.splitterMoved.connect(self._on_splitter_moved)
            self.notes_panel.changed.connect(self._on_note_saved)
            self.notes_panel.setVisible(bool(self.prefs.show_notes))
            self.notes_panel.set_note_accent(theme.color_hex("star"))
            splitter.setHandleWidth(theme.ui_px(6))    # WIDTH only, painting left fully native: setHandleWidth changes how much room native painting has, never how the handle is drawn, so Houdini's own grip dots and hover survive
        self.cat_wrapper = ui_helpers.HeldPane(    # the sidebar OWNS its width like the notes pane does: the remembered drag, or the 220 design width, asked of the splitter rather than left to cat_list's bare size hint
            self.prefs, "sidebar_width", theme.ui_px(220))
        self.cat_wrapper.setMaximumWidth(theme.ui_px(220))    # the splitter's pane widget is cat_wrapper, and catview's own <maximumSize width="220"> in amaze.ui constrains catview alone, so the cap is re-declared here or the category pane has no width limit at all
        self.cat_list.setMaximumWidth(theme.ui_px(220))    # and again on the list, this time AT UI SCALE: catview's own maximumSize in amaze.ui is a flat 220, so without this override a scaled display (Windows/Linux at 1.5x) would grow the wrapper while the list stayed at 220 and open a dead band of wrapper backdrop between list and grid. Runtime override, .ui untouched - the standing practice
        self.cat_wrapper.setAutoFillBackground(True)    # backdrop fill for the whole category section - the tab row's margins and any space the list does not cover - darker than the list's own BG1 so the section reads as one frame. Via QPalette, NEVER setStyleSheet/WA_StyledBackground on this ancestor: a stylesheet here pushes cat_list onto Qt's CSS rendering path for the parts it does not style itself (its scrollbar) and off Houdini's native look, where a palette change does not cascade
        cat_wrapper_palette = self.cat_wrapper.palette()
        cat_wrapper_palette.setColor(QtGui.QPalette.ColorRole.Window, theme.color("surface_low"))
        self.cat_wrapper.setPalette(cat_wrapper_palette)
        cat_wrapper_layout = QtWidgets.QVBoxLayout(self.cat_wrapper)
        cat_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        cat_wrapper_layout.setSpacing(0)

        cat_wrapper_layout.addWidget(self.cat_list)
        if splitter is not None and cat_index >= 0:
            splitter.insertWidget(cat_index, self.cat_wrapper)    # ONE arrangement for the three panes: the sidebar and the notes pane HOLD their width, the grid is the splitter's only flexible pane (the stretch 0/1/0 below), so every redistribution Qt performs - the notes toggle's tax and refund, a window resize - lands on the grid alone. Probed: that leaves the sidebar untouched through hide/show/resize, and Qt reopens the notes pane at its last width out of the grid by itself
            held = (self.cat_wrapper, getattr(self, "notes_panel", None))
            for i in range(splitter.count()):
                flexible = splitter.widget(i) not in held
                splitter.setStretchFactor(i, 1 if flexible else 0)

    def _build_sidebar_palette(self) -> None:
        """The category list's palette and selection colours."""
        self.cat_list = self.ui.catview  # type: ignore
        cat_list_palette = self.cat_list.palette()    # PALETTE, not setStyleSheet(): QListView paints its viewport from Base/Text, and a sheet on cat_list itself puts Qt on the CSS path for the parts that sheet does not cover, its own scrollbar first
        cat_list_palette.setColor(
            QtGui.QPalette.ColorRole.Base, theme.color("surface_low")
        )
        cat_list_palette.setColor(
            QtGui.QPalette.ColorRole.Text, AssetItemDelegate.TEXT_COLOR
        )
        self.cat_list.setPalette(cat_list_palette)    # NO selection colours in it: the sidebar wears Houdini's own like the Grid table does, because hou.qt.styleSheet() on the panel root makes QAbstractItemView::item:selected paint the band and answer HighlightedText - and a sheet outranks a palette at paint time, so setting Highlight here achieves nothing
        self.sidebar_delegate = SidebarItemDelegate(self.cat_list)    # paints the NAME, the count and the colour bar only; the cell under them - band, hover, alternating colour - is the style's (see SidebarItemDelegate's docstring)
        self.sidebar_delegate.color_role = category.SIDEBAR_COLOR_ROLE    # only the ASSET sidebars answer this role, so the bar simply never draws in the folder and palette sidebars and no second delegate is needed

    def init_ui(self) -> None:
        """Creates the panel-view on load"""
        loader = QtUiTools.QUiLoader()
        file = QtCore.QFile(self.script_path + "/ui/amaze.ui")
        loader.registerCustomWidget(dragdrop_widgets.DragDropCentralWidget)    # the .ui names these, so they must be registered before load
        loader.registerCustomWidget(dragdrop_widgets.DragDropListView)

        file.open(QtCore.QFile.ReadOnly)  # type: ignore
        self.ui = loader.load(file)
        file.close()

        try:
            self.ui.setStyleSheet(hou.qt.styleSheet())    # SideFX's documented way to make standard widgets render as native Houdini; the toolbar's own controls are hand-painted and ignore it
        except AttributeError:
            pass
        self.ui.setMinimumSize(theme.ui_px(MIN_PANEL_WIDTH), 0)    # WIDTH ONLY: dropping the .ui minimum entirely left the grid viewport 48px, narrower than one tile, while a short grid reads fine
        self.ui.setSizePolicy(    # vertical stays Ignored so the pane clips downward like its neighbours; horizontal must honour the minimum, which Ignored would not
            QtWidgets.QSizePolicy.Policy.Minimum,
            QtWidgets.QSizePolicy.Policy.Ignored,
        )

        try:
            self.ui.setFont(theme.ui_font(hou.qt.mainWindow().font()))    # THE FLOOR IS THEME'S, never a second one here: two floors agreeing only where the view inherits this font is the Windows defect. `hou.qt` is absent under hython, which is what the except buys
        except AttributeError:
            pass

        self.menu = self.ui.findChild(QtWidgets.QMenuBar, "menubar")    # styled nowhere: it is hidden below once its items move into the toolbar row, and a sheet on a hidden widget paints nothing
        self.action_prefs = self.ui.action_prefs  # type: ignore
        self.action_prefs.triggered.connect(self.show_prefs)

        self.action_catview = self.ui.action_show_cat  # type: ignore
        self.action_catview.triggered.connect(self.toggle_catview)

        self.action_cleanup_db = self.ui.action_cleanup_db  # type: ignore
        self.action_cleanup_db.triggered.connect(self.cleanup_db)

        self.action_open_folder = self.ui.action_open_folder  # type: ignore
        self.action_open_folder.triggered.connect(self.open_usdlib_folder)

        self.action_open = self.ui.action_open  # type: ignore
        self.action_open.triggered.connect(self.open)

        self.action_set_library = self.ui.action_set_library  # type: ignore
        self.action_set_library.triggered.connect(self.set_library)

        self.centralwidget = self.ui.centralwidget  # type: ignore

        self._central_layout = self.centralwidget.layout()    # an ATTRIBUTE, and the one the panel already had: as a local it pinned ~280 lines of init_ui together and nothing in that stretch could be split out
        self.toolbar_layout = None
        if self._central_layout is not None:
            if self.menu is not None:    # the real QMenuBar is HIDDEN, its QMenus and QActions still alive and opened from flat buttons: QMainWindow reserves a menu-bar dock area that cannot share a row, and the merged strip is what the host's own pane toolbars do
                self.menu.setVisible(False)
            filter_row = self.ui.findChild(QtWidgets.QHBoxLayout, "horizontalLayout")
            self.toolbar_row = QtWidgets.QWidget()
            self.toolbar_row.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_StyledBackground, True
            )
            self.toolbar_row.setStyleSheet(    # `border: none` FIRST, or Houdini's panel-wide sheet contributes a border on all sides once WA_StyledBackground puts this widget on the CSS path. QSS border-width is literal screen px, unscaled by the factor widget geometry goes through
                "background-color: " + theme.color_hex("surface")
                + "; border: none;"
                + " border-bottom: 1px solid "
                + theme.color_hex("field") + ";"
            )
            self.toolbar_row.setFixedHeight(theme.ui_px(30))    # 30 code px = the design's 60px bar
            self.toolbar_layout = QtWidgets.QHBoxLayout(self.toolbar_row)
            self.toolbar_layout.setContentsMargins(0, 0, theme.ui_px(2), 0)    # no top/bottom bias, content dead-centred; the right margin is the design's edge inset, most of which the last icon button's own padding provides
            self.toolbar_layout.setSpacing(0)

            self.toolbar_layout.addStretch()    # the three icon controls at the toolbar's RIGHT end are Filter, View and Preferences (`_build_menus` names them, and the gear is a plain button rather than a menu); this leading stretch pushes the cluster right and leaves the design's empty left region

            if filter_row is not None:
                self._central_layout.removeItem(filter_row)
            self._central_layout.insertWidget(0, self.toolbar_row)

        self.thumblist = self.ui.thumbview  # type: ignore
        self.thumblist.setVerticalScrollMode(    # per-PIXEL, not Qt's default per-ITEM: one "item" is a whole tile row in grid mode, so a per-item wheel step jumps enormous distances and reads erratically against trackpad deltas
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.thumblist.setHorizontalScrollMode(    # BOTH AXES, same mode and same reasoning: sideways scrolling stayed on the per-ITEM default until list rows grew wider than the panel and anything could reach it
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.thumblist.setUniformItemSizes(True)    # same geometry every row/tile, so Qt lays out by arithmetic instead of asking the delegate per item - a real saving at 500+ materials, and list rows stay uniform while the viewport resizes
        self.thumblist.setLayoutMode(    # SINGLE-PASS, overriding the .ui's Batched: a batched layout publishes a scrollbar range covering only the batches laid out so far (batchSize 100), so a repaint that restarts it - a thumbnail arriving mid-scroll - collapses the range and snaps it back; measured in the debug log as range_max alternating 16062 <-> 2772 on a 543-row library. Uniform item sizes make single-pass cheap
            QtWidgets.QListView.LayoutMode.SinglePass
        )
        self.thumblist.setSizeAdjustPolicy(    # .ui leftover 1 of 3: AdjustToContents makes the scroll area's size HINT follow its content, so the grid renegotiates space with its neighbours whenever the content geometry changes
            QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self.thumblist.setMovement(QtWidgets.QListView.Movement.Static)    # leftover 2 of 3: Snap treats tiles as individually placed items that re-snap on interaction, where these are laid out by the view and never rearranged by the user; Static is also where uniform-size arithmetic layout applies
        self.thumblist.setDragDropMode(    # leftover 3 of 3: DragDrop on a view with acceptDrops=false, when it only ever drags OUT to Houdini's network and viewports
            QtWidgets.QAbstractItemView.DragDropMode.DragOnly
        )
        self.thumblist.setDragDropOverwriteMode(False)
        self.thumblist.setAutoScroll(False)    # selecting a tile must never move the grid: Qt's autoScroll re-scrolls on EVERY currentChanged, a click on a half-cut tile included, which reads as the grid jumping under the cursor. Off for keyboard navigation too, deliberately - the grid is a mouse surface; explicit scrollToTop calls are not gated by this
        self.thumblist.viewport().setMouseTracking(True)    # list rows span the viewport and must re-fit when it resizes; the versions badge lights under the cursor, which needs button-free mouse moves, and a viewport does NOT track the mouse by default (measured). Both live in eventFilter
        self.thumblist.viewport().installEventFilter(self)
        self.thumblist.doubleClicked.connect(self.import_asset_auto)
        self.thumblist.clicked.connect(self._refresh_notes_subject)    # update_details_view is deliberately NOT wired here: selectionChanged already fires for every click that changes the selection, and a click that changes nothing leaves the details correct - wired to both, each click rebuilt the form twice. Refresh-after-edit calls it explicitly (edit_material_info, user_update_asset); _refresh_notes_subject stays because it is idempotent
        thumblist_palette = self.thumblist.palette()    # grid and details unify on the `surface_high` token via QPalette (Base, the role QListView paints its viewport from) rather than setStyleSheet(), consistent with the cat_list fix above
        thumblist_palette.setColor(QtGui.QPalette.ColorRole.Base, theme.color("surface_high"))
        self.thumblist.setPalette(thumblist_palette)

        self.texture_progress = ui_helpers.ThinProgressBar()    # thin bar for texture thumbnail generation, docked above thumbview in verticalLayout_7 - which wraps thumbview ALONE, isolated from catview/details in the splitter. Built in code rather than the .ui; hidden until a folder with work to do is selected (see _on_texture_progress)
        self.texture_progress.set_accent_color(theme.accent(self.prefs.accent_color))
        self.set_conversion_bar_visible(False)
        thumb_layout = self.ui.findChild(QtWidgets.QVBoxLayout, "verticalLayout_7")
        if thumb_layout is not None:
            thumb_layout.insertWidget(0, self.texture_progress)

        self.thumbtable = dragdrop_widgets.DragDropTableView()    # list mode is a real table: a second VIEW, not a second area, sharing the model, the proxy and the SELECTION MODEL with the grid, so selecting in one is selecting in the other and every area binding stays single. Only one is ever visible
        self.thumbtable.setObjectName("thumbtable")
        self.thumbtable.setHorizontalHeader(    # the header goes in BEFORE it is styled: `grid.style_table_header` sets the sort indicator, and this is the header that decides what that indicator costs the columns without one
            ui_helpers.GridHeaderView(
                QtCore.Qt.Orientation.Horizontal, self.thumbtable))
        self.thumbtable.setVisible(False)
        if thumb_layout is not None:
            thumb_layout.addWidget(self.thumbtable)
        grid.style_table_header(self)
        self.thumbtable.setContextMenuPolicy(    # the table IS the grid while list mode shows, so it takes the same menu and the same primary action; thumblist gets CustomContextMenu from the .ui, this view is built in code and takes both wirings here or right-click and double-click are dead in one of the two modes
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbtable.customContextMenuRequested.connect(
            self.thumblist_rc_menu)
        self.thumbtable.doubleClicked.connect(self.import_asset_auto)    # and NO scroll-offset wiring is owed: a QHeaderView IS the view's header and scrolls with it, where the painted strip it replaced sat above the view and had to be told when rows scrolled sideways

        self._build_sidebar_palette()
        self.sidebar_delegate.set_drag_color(
            theme.accent(self.prefs.accent_color)
        )
        self.cat_list.setItemDelegate(self.sidebar_delegate)
        self.cat_list.clicked.connect(self.update_selected_cat)
        self._cat_drop_filter = dragdrop_widgets.CategoryDropFilter(    # makes the sidebar a drop target for recategorising grid assets, and keeps such a drop from falling through to the central widget's save-node handler
            self.cat_list, self
        )

        self.line_filter = self.ui.line_filter  # type: ignore
        self.line_filter.textEdited.connect(self.filter_thumb_view)
        self.line_filter.setPlaceholderText(sections.Section.search_hint)    # the box is EMPTY by decree (2026-08-01): the "Search" label and the magnifier already name the control. The search_hint machinery stays for the day a section needs a word again, but every hint is "" and the tooltip is where :tag gets taught
        self.line_filter.setToolTip(ui_helpers.tooltip_text(
            "Search for objects, a leading colon searches tags "
            "instead: :metal finds everything tagged metal."))
        self.line_filter.setStyleSheet(    # borderless box on the `field` token with the magnifier inside the left edge; the sheet goes on the widget ITSELF, never an ancestor, which is the rule the whole file follows to avoid the details-panel regression class. padding-left reserves room so typed text does not start under the icon
            "QLineEdit { border: none; background-color: "
            + theme.color_hex("field")
            + "; padding-left: %dpx; }" % theme.ui_px(20)
        )
        self.line_filter.setFixedHeight(theme.ui_px(20))    # 20 code px = the design's 40px rendered box; the plain 2x relationship holds because the box is borderless, where a 1px QSS border would eat into the fill
        self.line_filter.setMinimumWidth(theme.ui_px(38))    # overrides the .ui's own 80 minimum - setMinimumWidth wins at runtime
        self.line_filter.setMaximumWidth(theme.ui_px(200))    # 400px rendered, raised with the slider's to match
        try:    # the magnifier is an overlay QLabel + SideIconPinner, NOT a QLineEdit addAction() icon: that API does not expose the exact margin, and this design asks for one
            filter_icon_path = self._ui_icon_path("icon_search.svg")
            if filter_icon_path and os.path.exists(filter_icon_path):
                icon_size = theme.ui_px(13)    # ~25px rendered magnifier, ~9px in from the box edge, at a 4px pin margin
                pixmap = ui_helpers.render_svg_pixmap(    # QSvgRenderer straight onto a transparent pixmap - QIcon's own SVG engine produced an opaque black background here
                    filter_icon_path, icon_size
                )
                self.filter_icon_label = QtWidgets.QLabel(self.line_filter)
                self.filter_icon_label.setPixmap(pixmap)
                self.filter_icon_label.resize(icon_size, icon_size)
                self.filter_icon_label.setAttribute(
                    QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
                )
                self.filter_icon_label.setAttribute(    # belt AND suspenders, deliberately: the attribute stops Qt auto-filling the widget background, the sheet below overrides whatever panel-wide QLabel rule Houdini's own stylesheet contributes. A dark square here was the LABEL's background, not the pixmap's alpha
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
            self.filter_label = QtWidgets.QLabel("Search")    # a real QLabel left of the box, not placeholder text inside line_filter; font stays the panel-wide Houdini stamp
            self.filter_label.setObjectName("filter_label")
            self.filter_label.setStyleSheet(
                "color: " + theme.color_hex("text_bright") + ";"
            )
            self.toolbar_layout.addWidget(self.filter_label)
            self.toolbar_layout.addSpacing(theme.ui_px(12))
            self.toolbar_layout.addWidget(self.line_filter)
            self._after_filter_index = self.toolbar_layout.count()    # the size slider is built much later in this method but sits between the box and the star, so its block inserts itself back at this remembered spot

        self.current_section = "material"
        self._build_splitter_and_sidebar()    # catview has no wrapper of its own in amaze.ui (it is a direct QSplitter pane), so it is reparented into a new wrapper which then takes catview's old place
        self.section_tabs = None
        self._build_section_tabs()    # a full-width strip BELOW the toolbar, outside the sidebar, at _central_layout index 1 with toolbar_row at 0; built from the enabled_sections pref and rebuilt when that pref changes. "Colors" is the Gradients section's user-facing name, internal key still "gradient". Chip colours are fixed design constants, not accent-derived, so no set_accent_color here
        self.ui.cb_FavsOnly.setVisible(False)  # type: ignore  -- the .ui's own favourites box is unused and hidden; left unparented it can paint stray in the panel. The real toggle is a hand-painted ChipToggleButton built below, sharing its hover chip and icon-whitening with the icon menu buttons
        self._build_view_toggles()
        self.cb_viewmode.toggled.connect(self.on_viewmode_button)
        if self.toolbar_layout is not None:
            self.toolbar_layout.addWidget(self.cb_viewmode)
            self.toolbar_layout.addSpacing(theme.ui_px(2))    # fixed gap to the icon-menu cluster appended right after; the design right-anchors everything from the star outward

        self.details = self.ui.details_widget  # type: ignore
        self.details.setAutoFillBackground(True)    # matches the grid on `surface_high` via QPalette, NOT setStyleSheet: a sheet here knocked the Name/Category/Tags fields off their native box rendering, because palette changes do not cascade onto descendants the way a sheet does
        details_palette = self.details.palette()
        details_palette.setColor(QtGui.QPalette.ColorRole.Window, theme.color("surface_high"))
        self.details.setPalette(details_palette)
        self.line_name = self.ui.line_name  # type: ignore
        self.line_cat = self.ui.line_cat  # type: ignore

        self.cat_combo = self.ui.cat_combo  # type: ignore  -- every asset has exactly ONE category, so this dropdown is the only category input; the multi-category tick box and its comma-separated textbox stay in the .ui and are never shown
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

        self.line_renderer = QtWidgets.QLineEdit()    # greyed renderer row under Name ("USD Redshift" / "Redshift" / "Karma"), inserted in code so the whole form need not be renumbered, and disabled so it reads as metadata
        self.line_renderer.setReadOnly(True)
        self.line_renderer.setDisabled(True)
        self.line_renderer.setStyleSheet(
            "QLineEdit:disabled { background-color: #333333; }"
        )
        self.line_license = QtWidgets.QLineEdit()    # provenance for downloaded online materials and empty for local ones: License in its own field, and a multi-line About/credit block at the bottom naming source, author and link. Both editable, both saved with the rest of the Material Info form
        self.text_about = QtWidgets.QPlainTextEdit()
        self.text_about.setFixedHeight(theme.ui_px(84))   # ~4 lines
        try:
            details_form = self.ui.findChild(  # type: ignore
                QtWidgets.QFormLayout, "details_form"
            )
            name_row, _ = details_form.getWidgetPosition(self.line_name)
            details_form.insertRow(name_row + 1, "Type", self.line_renderer)
            details_form.addRow("License", self.line_license)    # appended, so the provenance rows sit at the bottom of the form
            details_form.addRow("About", self.text_about)
        except Exception:
            pass

        self.box_fav = self.ui.cb_set_fav  # type: ignore
        self.box_fav.clicked.connect(self.box_fav_clicktoggle)

        self.btn_update = self.ui.btn_update  # type: ignore
        self.btn_update.setText("Update Info")    # the .ui's own "Update Material" collides with the real content-update in the save flow; this button saves name/category/tags/favourite alone. Changed as a runtime property, never a .ui edit, which is standing practice here
        self.btn_update.clicked.connect(self.user_update_asset)

        self.details_dialog = QtWidgets.QDialog(self)    # material metadata is a FLOATING dialog, not a docked panel - the panel ate grid width and only materials used it. Reparenting details_widget into a QDialog takes it out of the splitter so the grid gets the space; the edit form itself is unchanged
        self.details_dialog.setWindowTitle("Material Info")
        _dlg_layout = QtWidgets.QVBoxLayout(self.details_dialog)
        _m = theme.ui_px(8)
        _dlg_layout.setContentsMargins(_m, _m, _m, _m)
        _dlg_layout.addWidget(self.details)  # reparents out of the splitter
        self.details.setVisible(True)
        self.details.setMinimumWidth(theme.ui_px(360))

        self.menu_filter = QtWidgets.QMenu("Filter", self.menu)    # lives in the hidden menubar and opens from a toolbar button; every section fills it with its own entries from panel/sections.py
        self._build_menus()

        self.ui.slide_iconSize.setVisible(False)  # type: ignore  -- the .ui's own icon-size slider is superseded by the ClickSlider below, and stays hidden rather than deleted because the .ui is maintained externally in Qt Designer and edited versions of it are sometimes handed over

        self.click_slider = ui_helpers.ClickSlider()
        self.click_slider.setObjectName("click_slider")    # NO tooltip here - _sync_slider_for_mode owns it, because the text differs by view mode and a construction-time one is dead the moment apply_view_mode runs
        self.click_slider.setOrientation(QtCore.Qt.Horizontal)  # type: ignore
        self.click_slider.setRange(64, 512)    # 64 is the floor: below it a grid tile is smaller than the badges it carries. LIST does not use this range at all - it sits at LIST_THUMB_SIZE with the slider disabled, because a list row is a text line
        self.click_slider.setValue(ui_helpers.ClickSlider.DEFAULT_VALUE)
        self.click_slider.setSingleStep(50)
        self.click_slider.setPageStep(50)
        self.click_slider.set_accent_color(theme.accent(self.prefs.accent_color))
        self.click_slider.setMinimumWidth(theme.ui_px(38))    # same sizing rule as the filter box: 400px rendered max, 75px min
        self._build_slider_and_layout()

    def _mirror_toolbar(self) -> None:
        """TEST, NOT THE DESIGNED LAYOUT: mirror the toolbar row so every item flows from the LEFT edge in the reverse of the designed order. Everything above still BUILDS right-aligned, so ending the test is deleting this method and its call - nothing else moves."""
        if self.toolbar_layout is None:
            return
        items = []
        while self.toolbar_layout.count():
            items.append(self.toolbar_layout.takeAt(0))
        for item in reversed(items):
            self.toolbar_layout.addItem(item)
        i_box = self.toolbar_layout.indexOf(self.line_filter)
        i_label = self.toolbar_layout.indexOf(self.filter_label)
        if i_box >= 0 and i_label == i_box + 2:    # exception to the literal mirror: the "Filter" label still reads left-to-right, so the label and its gap go back to [label][12-gap][box]. Strict adjacency, so a construction change cannot silently shuffle the wrong items
            label_item = self.toolbar_layout.takeAt(i_label)
            gap_item = self.toolbar_layout.takeAt(i_label - 1)
            self.toolbar_layout.insertItem(i_box, gap_item)
            self.toolbar_layout.insertItem(i_box, label_item)
        self._move_to_toolbar_end(getattr(self, "btn_hip_capture", None))    # second exception: the capture button is the OUTERMOST control in both orders, and the mirror would leave it outermost-LEFT
        self._move_to_toolbar_end(self._toolbar_widget("btn_prefs"))    # capture first, then the gear, so the row ends ... stretch, Capture, gear

        self.toolbar_layout.setContentsMargins(    # both edges hold a control once the capture button is back at the end, so both are inset by 2
            theme.ui_px(2), 0, theme.ui_px(2), 0)

    def _toolbar_widget(self, name: str):
        """A toolbar item by objectName - the gear is deliberately not kept on self, so the row is where to look for it."""
        for i in range(self.toolbar_layout.count()):
            item = self.toolbar_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None and widget.objectName() == name:
                return widget
        return None

    def _move_to_toolbar_end(self, widget) -> None:
        """Move one control (and the 2px gap that travels with it) to the end of the mirrored row - the mirror turns "outermost right" into "outermost left", and two controls need putting back."""
        if widget is None:
            return
        index = self.toolbar_layout.indexOf(widget)
        if index < 0:
            return
        item = self.toolbar_layout.takeAt(index)
        gap_item = None
        if index < self.toolbar_layout.count():    # the gap sat immediately BEFORE the widget in build order, so it FOLLOWS it after the reversal. Strict adjacency, so a construction change cannot silently move the wrong item
            probe = self.toolbar_layout.itemAt(index)
            if probe is not None and probe.widget() is None:
                gap_item = self.toolbar_layout.takeAt(index)
        if gap_item is not None:
            self.toolbar_layout.addItem(gap_item)
        self.toolbar_layout.addItem(item)

    @staticmethod
    def _category_names_from(model) -> list[str]:
        """ALL category names from a Categories model, empty ones included, excluding the 'All' pseudo-category - the one implementation behind all three sections' getters."""
        names = []
        if not model:
            return names
        for elem in range(model.rowCount()):    # pass the SOURCE model, never the sidebar proxy: the proxy hides empty categories, and every ASSIGNMENT surface (the save dialog, the Edit Info dialog's Category dropdown) must still offer the complete list
            cidx = model.index(elem, 0)
            name = model.data(cidx, QtCore.Qt.ItemDataRole.DisplayRole)
            if name and name != "All":
                names.append(name)
        return sorted(names, key=str.lower)

    def get_category_names(self) -> list[str]:
        return self._category_names_from(self.category_model)

    def assign_category_active(self, category: str) -> None:
        """Set (replace) the category of the ACTIVE section's selected assets - one category per asset. The path behind dragging assets onto a sidebar category, for every section with real categories: Materials / Cop / Code and Colors."""
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
        catmodel.check_add_category(category)    # OUTSIDE the relayout wrapper: this announces itself with begin/endInsertRows, and pairing the two segfaults H21 (research.md). The row edits below are data changes, which is what the wrapper is for
        with ui_helpers.relayout(model):
            for index in indexes:
                idx = model.index(proxy.mapToSource(index).row(), 0)
                asset = model.assets[idx.row()]
                model.set_assetdata(
                    idx, asset.name, category, ", ".join(asset.tags),
                    None, save=False    # fav=None: a recategorise edits the record, never the star, which is per-user and lives in settings. save=False: one index write for the whole selection, not one per row
                )
            model.save()
        self._refresh_sidebar_categories()

    def _assign_gradient_category(self, category: str) -> None:
        """Move the selected gradients to a category - the seeded palettes included, since every gradient is a normal editable entry."""
        rows = [
            self.gradient_sorted_model.mapToSource(i).row()
            for i in grid_columns.selected_rows(self.gradient_selection_model)
        ]
        moved = self.gradient_model.set_user_category(rows, category)
        if moved:
            self._refresh_sidebar_categories()

    def _grid_geometry(self) -> dict:
        """The numbers that would have to change for the grid to appear to move - viewport, scroll range, grid step, size hint."""
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
        watch = self._grid_geometry() if debug.is_on() else None    # a right-click must not move the grid; when it does, the before/after pair names which number moved. Debug only - it interrogates the view's geometry, so it stays off the hot path
        try:
            self._thumblist_rc_menu()
        finally:
            if watch is not None:
                after = self._grid_geometry()
                if after != watch:
                    debug.event("grid", "geometry changed by right-click",
                                before=watch, after=after)

    def _thumblist_rc_menu(self) -> None:
        """The menu itself - the active CONTEXT builds its own from its own entry table (`Section.GRID_MENU`, rendered by panel/grid.py)."""
        context = self._section()    # answers with the ONLINE world while that shows, and it has a GRID_MENU like every other context, so no world test belongs here
        if context is not None:
            context.rc_menu()

    def _open_versions_dialog(self, index) -> None:
        """The versions dialog: a dropdown of the versions, a field to rename the selected one, Cancel / Apply. Browses, switches and names - never creates (creation is automatic on save)."""
        source = self.material_sorted_model.mapToSource(index)    # `index` arrives from the DELEGATE, so it belongs to the proxy the view shows; the model methods want source rows
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

        try:
            if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
                return

            chosen = int(picker.currentData())
            typed = name_field.text().strip()
            combo_row = picker.currentIndex()  # not a proxy
        finally:
            dialog.deleteLater()    # deleted on BOTH exits and only after its fields are read: it is parented to the panel, so dropping the Python name frees nothing (~6.5MB per open). NOT WA_DeleteOnClose - the values above are read out of its own children after exec() returns, and that attribute would schedule them for destruction first

        if typed and typed != (listed[combo_row].get("name") or ""):
            model.rename_version(row, chosen, typed)
        if chosen != active:
            model.switch_version(row, chosen)



    def _scene_path(self, path: str) -> str:
        """Every path Amaze WRITES INTO THE SCENE goes through here, spelled per Preferences - Write Paths As."""
        return file_library.houdini_path(    # NOT for loads or existence checks: those keep the raw path, which is a location and not a spelling
            path, getattr(self.prefs, "path_style", "home"))

    def copy_file_paths(self, proxy_indexes) -> None:
        """Copy the selection's paths to the clipboard, one per line, written as Houdini paths ($HIP/... $JOB/... $HOME/...) - and the ONLY action an unrecognised file has."""
        paths = []
        for proxy_index in proxy_indexes:
            path = proxy_index.data(self.file_files_model.PathRole) or ""
            if path:
                paths.append(file_library.houdini_path(
                    path, getattr(self.prefs, "path_style", "home")))
        if not paths:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(paths))    # no dialog - the clipboard changing IS the report
        debug.event("file", "paths copied", count=len(paths))

    def catlist_rc_menu(self) -> None:
        """Sidebar right-click - the active context builds its own menu."""
        section = self._section()    # the online world declares no SIDEBAR_MENU and the builder returns on an empty table, so no world test belongs here
        if section is not None:
            section.catlist_menu()


    def _locate_folder_user(self, folders_model) -> None:
        """Sidebar "Locate Folder...": re-point the selected registered folder at a new location - a folder that moved on disk, or one whose path only exists on the other machine. Shared by the Textures and Geometry sidebars."""
        ui = getattr(hou, "ui", None)
        indexes = self.cat_list.selectedIndexes()
        row = indexes[0].row() if indexes else -1
        if row <= 0:
            if ui is not None:
                ui.displayMessage(
                    "Select the registered folder to re-point first "
                    '("All" is not a real folder).'
                )
            return
        path = ui.selectFile(file_type=hou.fileType.Directory) if ui else ""
        if not path:
            return
        rewritten = folders_model.relocate_folder(row, hou.expandString(path))    # the model rewrites its favorites onto the new path so they survive the move; a negative answer means the location is not a folder
        if rewritten < 0:
            if ui is not None:
                ui.displayMessage(
                    "That location doesn't exist as a folder - nothing "
                    "was changed."
                )
            return
        if rewritten:
            debug.event("folders", "relocated", favorites=rewritten)
        self.update_selected_cat()    # rescan under the new path


    def capture_open_scene_thumbnail(self) -> None:
        """Toolbar button: capture the scene currently OPEN, not the grid selection - the capture photographs the viewport, so the only scene it can honestly be filed against is the one the viewport is showing."""
        self._capture_and_report()    # "" = whatever is open, and no gate of its own: the refusal wording lives one layer down so this button, the tile menu and the shelf tool cannot drift apart

    def _hip_path_for(self, index):
        """The scene path behind a File-grid index, or '' - also '' for a row that is not a scene, so every hip-only path stays inert on other kinds."""
        if index is None or not index.isValid():
            return ""
        if index.data(self.file_files_model.KindRole) != \
                file_library.KIND_HIP:
            return ""
        return index.data(self.file_files_model.PathRole) or ""

    def _capture_and_report(self, target: str = "") -> None:
        """Run the shared capture and SAY WHY if it refuses - both entry points end here, and an empty target means whatever scene is open."""
        try:
            scene_captures.capture_open_scene(target)    # every check lives one layer down, so the tile menu, the toolbar button and the shelf tool cannot grow three wordings of the same refusal
        except scene_captures.CaptureRefused as exc:    # a capture that silently does nothing teaches the user the feature is broken
            debug.event("hip", "capture refused", file=target,
                        reason=str(exc))
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(str(exc))

    def capture_hip_thumbnail(self, index, path: str = "") -> None:
        """Capture the current scene view as this scene's thumbnail - ONLY ever from the right-click menu, and there must never be an automatic version."""
        target = path or self._hip_path_for(index)    # why never automatic: the capture runs a flipbook, a flipbook forces the scene to COOK, and cooking an arbitrary scene is work of unknown size - measured 2026-07-29, an auto-capture 1.2s after opening a cloth-sim scene blocked 22 SECONDS on one file and on the next filled 86GB of RAM and crashed Houdini. No delay fixes it; the user pressing the button when the scene looks right is the judgement
        if not target:
            return
        self._capture_and_report(target)    # and NO refresh after it: scene_captures announces a landed capture and every live model repaints itself. Doing it again discarded the cached image, emitted dataChanged a second time, and hid which layer owns the refresh

    def _raw_category_name(self, index) -> str:
        """The STORED name behind a sidebar row, not the displayed one - every action on a category must key off this, or it acts on a name nothing has."""
        if index is None or not index.isValid():
            return ""
        model = self.cat_list.model() if self.cat_list is not None else None
        if model is not None and hasattr(model, "sourceModel"):
            raw = index.data(model.sourceModel().CatSortRole)    # `Categories.data` strips a leading "_" for DisplayRole - the mechanism that makes the stored "_All" sort first and read as "All" - so for such a row DisplayRole answers a name no store holds
            if raw:
                return str(raw)
        return str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")    # fallback only for a model with no sourceModel to ask; it answers the DISPLAYED name, so a caller reaching it is on the degraded path

    def _selected_category_name(self) -> str:
        """The category the sidebar is standing in, blank for All - selection first, then the live current index. NO section gate: that belongs to the caller, since only some want it."""
        if self.cat_list is None:
            return ""
        indexes = self.cat_list.selectedIndexes()
        index = indexes[0] if indexes else ui_helpers.live_current_index(    # the fallback is deliberate: _restore_section_state's setCurrentIndex leaves the sidebar "current but not selected", and returning "" there would answer All
            self.cat_list)
        name = self._raw_category_name(index)
        return "" if name in ("All", "_All") else name

    DEFAULT_SIDEBAR_COLOUR = "#4af2a1"    # the picker's starting colour when a row has none; one place

    def ask_category_name(self, title: str):
        """The category-name dialog, once, so no caller unpacks CategoryDialog's two-field answer itself: None means CANCELLED, "" means the user cleared the field, and the two are NOT the same thing."""
        dialog = gradient_dialog.CategoryDialog(title)
        dialog.exec_()
        if dialog.canceled:
            return None
        return dialog.name or ""    # "" is a real answer: File's Label clears a location's custom label back to the path with it, so folding it into Cancel would make Cancel wipe the label

    def sidebar_set_colour(self, pick: bool) -> None:
        """Set Color / Clear Color on the sidebar selection - the panel's ONE gesture for every sidebar: read the selection's keys, ask the context the first one's colour, open the picker once, hand the answer back."""
        context = self._section()
        if context is None or self.cat_list is None:
            return
        names = [context.sidebar_key(index)    # ASK THE CONTEXT what a row is keyed by: a category's STORED name in three sections, a registered folder PATH in File. A colour written under the DISPLAYED name ("_WIP" shows as "WIP") is one nothing ever reads
                 for index in self.cat_list.selectedIndexes()]
        names = [name for name in names    # All is skipped: it is a view, not a category, and colouring it would mean colouring everything
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
            context.set_sidebar_colour(name, colour)    # what a colour IS - which store, which models repaint - is the context's (Section.set_sidebar_colour)


    def _favourite_badge_clicked(self, index) -> None:
        """The tile's star button: flip the whole SELECTION when the clicked tile is in it - the press that preceded this release has already selected a lone tile, so one gesture stars a multi-selection - and just the clicked tile when it somehow is not."""
        selmodel = self.thumblist.selectionModel()
        rows = grid_columns.selected_rows(selmodel) \
            if selmodel is not None else []
        if index not in rows:
            rows = [index]
        self.grid_toggle_favourite(rows)

    def grid_toggle_favourite(self, indexes) -> None:
        """Flip the star on the grid's selection - one entry point for every section's menu, and all it decides is which selection to act on and to refresh the details form."""
        context = self._section()
        if context is None:
            return
        context.toggle_favourite(list(indexes))    # the flip is the context's own verb, and re-mapping a favourites-only grid after it is the proxy's own invariant (grid_proxy.py) - nothing to force from here
        self.update_details_view()

    def _selection_has_redshift(self) -> bool:
        """Whether any currently-selected material is Redshift - gates showing `Convert to Karma` in the right-click menu."""
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
        """Right-click `Convert to Karma`: node-graph conversion of the selected Redshift materials to Karma/MaterialX, silently skipping non-Redshift items in a mixed selection."""
        if not self.material_model:
            return
        indexes = grid_columns.selected_rows(self.material_selection_model)
        if not indexes:
            return
        all_lines = []    # ONE summary dialog for successes and skips alike: a "successful" conversion can still have approximated or skipped inputs worth reviewing, and no result is claimed to be a faithful reproduction
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
                        self.material_model.convert_redshift_to_karma(idx))    # what is and isn't handled: core/library.py's convert_redshift_to_karma() and render/material_converter.py
                except Exception as exc:    # one bad material must not take the rest of the selection down, nor the summary the others earned - it becomes a line in that summary instead
                    all_lines.append(f'"{mat.name}": crashed - {exc}')
                    continue
                if ok:
                    converted_count += 1
                all_lines.extend(report.summary_lines())
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(
                f"Converted {converted_count} of {redshift_count} Redshift "
                "material(s) to Karma.\n\n" + "\n".join(all_lines)
            )

    def show_prefs(self) -> None:
        """Show the Preferences Dialog - NON-MODAL, floating above the main window, and opening with or without a library set (its Library tab is the only way to set one). A second open while the window exists just fronts it."""
        if self._thumbsize_save_timer.isActive():    # flush a pending debounced thumbsize save first: prefs.load() at close re-reads settings.json, and a still-pending write would silently revert the newest slider value
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
        try:
            dlg.setParent(    # plain Dialog flags on the main window: floats over Houdini without blocking it. Keep it non-modal - the native confirmation/summary dialogs Preferences launches (cleanup, set library) land UNDER a modal one, invisible and once fatal (wiki: Qt facts)
                hou.qt.mainWindow(), QtCore.Qt.WindowType.Dialog
            )
        except AttributeError:
            pass
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)    # or repeated opens accumulate hidden instances
        self._prefs_dialog = dlg
        applied = {"done": False}    # `finished` fires on every close path (closeEvent calls done()) and `destroyed` is DeleteOnClose insurance, so this makes double delivery apply once

        def _closed(*_a, od=old_dir):
            if applied["done"]:
                return
            applied["done"] = True
            self._prefs_dialog_closed(od)

        dlg.finished.connect(_closed)
        dlg.destroyed.connect(_closed)
        self.destroyed.connect(dlg.close)    # the dialog must not outlive the panel it applies to
        dlg.show()

    def _prefs_dialog_closed(self, old_dir) -> None:
        """Apply everything Preferences changed, once the non-modal dialog reports it closed."""
        try:
            self.isVisible()    # a non-modal dialog can outlive its panel (the pane tab closed with Preferences open), so confirm the C++ side is still there before touching anything
        except RuntimeError:
            return
        self._prefs_dialog = None

        if not self.material_model or not self.category_model:    # still no library after the dialog - nothing below applies
            return

        self.apply_view_mode()    # mode-aware: respects grid vs list
        self.update_renderer_toggles()
        self.prefs.load()
        debug.configure(self.prefs.debug_mode)
        hostos.set_cache_override(self.prefs.cache_dir)
        if self.prefs.dir != old_dir:    # only a changed library DIRECTORY needs the models rebuilt: rebuilding unconditionally re-reads the json, drops the per-id usd/shader caches and re-loads every thumbnail PNG, well over a thousand file reads per Preferences close
            self.switch_all_models()
        accent = theme.accent(self.prefs.accent_color)
        self.click_slider.set_accent_color(accent)
        self.texture_progress.set_accent_color(accent)
        for tile_delegate in self.tile_delegates():
            tile_delegate.DIM = accent    # the tile subtitle line ("Redshift:Standard", "HDR", ...) tracks the accent too
        self._sync_notes_button_pixmaps()
        self.sidebar_delegate.set_drag_color(accent)
        self.sidebar_delegate.show_counts = self.prefs.sidebar_counts
        thumbnails.engine.set_budget_mb(self.prefs.ram_cache_mb)
        for _sidebar_proxy in self.sidebar_proxies():    # EVERY sidebar proxy, and via sidebar_proxies() rather than a hand-written list: one left out keeps its construction-time hide_empty for the rest of the run
            _sidebar_proxy.hide_empty = self.prefs.hide_empty_categories
        self._refresh_sidebar_categories()
        self._ensure_sidebar_selection(self.current_section)    # if hiding empties just hid the category the user was standing in, fall back to All the way a filter switch does
        self.cat_list.viewport().update()
        grid.visible_view(self).viewport().update()
        section = self._section()
        if section is not None:
            section.prefs_changed()    # geometry look prefs (shading mode / background) are in the cache key, but nothing re-runs the folder scan while the section shows, so the current selection is re-run here
        if self.current_section == "file":    # ONLY while File shows: this refresh can start the BLOCKING geometry render pass, and a Delete Local Cache from another tab must not freeze Houdini rendering tiles nobody is looking at. Nothing is lost - FolderSection.activate() rescans on every File activation
            self.file_files_model.refresh_current_folder()
        self._apply_enabled_sections()    # visible section tabs may have changed in Preferences

    def update_renderer_toggles(self):
        """A renderer was enabled or disabled - in Preferences, or by saving a material of a new one - so the Filter menu is rebuilt whole: MaterialSection.filter_entries re-reads the same prefs flags, and build_filter_menu falls back to All for any section whose remembered choice is no longer on offer. Under its own name because its three callers mean that event, not merely a menu redraw."""
        if getattr(self, "menu_filter", None) is None:
            return
        self.build_filter_menu()

    def import_package_file(self, path: str, restore: bool = False) -> dict:
        """ACT half of the whole-package import: every asset lands in its own section (fresh ids, `Import` category; `restore=True` adopts by original id), plain files land in the library's `import/` folder which registers as a location - answering the core summary."""
        summary = packages.import_package(self._package_models(),
                                          self.prefs, path,
                                          restore=restore)
        self._absorb_package_summary(summary)
        return summary

    def import_amaze_package(self) -> None:
        """Package Import: the read-mode picker, then the act door; the summary speaks once, dialog-free when headless."""
        ui = getattr(hou, "ui", None)
        if not self.prefs.dir:
            if ui is not None:
                ui.displayMessage("Please set a library first.")
            return
        picked = ui.selectFile(
            title="Import Amaze Package",
            file_type=hou.fileType.Any,
            pattern="*" + packages.SUFFIX,
            chooser_mode=hou.fileChooserMode.Read,
        ) if ui is not None else ""
        picked = (picked or "").strip()
        if not picked:
            return
        try:
            summary = self.import_package_file(
                hou.text.expandString(picked))
        except packages.PackageError as exc:
            if ui is not None:
                ui.displayMessage(str(exc))
            return
        if ui is not None:
            ui.displayMessage(
                "Imported %d asset(s) and %d file(s) into the Import "
                "category." % (summary["imported"], summary["files"]))

    def ask_package_destination(self) -> str:
        """The write-mode picker for an `.amazepkg` export - "" when headless or cancelled, the suffix appended when the user leaves it off."""
        ui = getattr(hou, "ui", None)
        if ui is None:
            return ""
        picked = ui.selectFile(
            title="Export Amaze Package",
            file_type=hou.fileType.Any,
            pattern="*" + packages.SUFFIX,
            default_value="package" + packages.SUFFIX,
            chooser_mode=hou.fileChooserMode.Write,
        )
        picked = (picked or "").strip()
        if not picked:
            return ""
        picked = hou.text.expandString(picked)
        if not picked.endswith(packages.SUFFIX):
            picked += packages.SUFFIX
        return picked

    def import_galleries(self) -> None:
        """Gallery Import: every material preset in a .gal file becomes a library material through the same save funnel a hand-saved one takes. Thumbnails are NOT rendered during the run - the summary says how to render them afterwards."""
        ui = getattr(hou, "ui", None)
        if not self.material_model:
            if ui is not None:
                ui.displayMessage("Please set a library first.")
            return
        picked = ui.selectFile(
            start_directory=gallery_import.default_gallery_dir(),    # opens where Houdini keeps its galleries; a .gal picked anywhere else works just as well
            title="Import Gallery (.gal)",
            file_type=hou.fileType.Any,
            pattern="*.gal",
            chooser_mode=hou.fileChooserMode.Read,
        ) if ui is not None else ""
        picked = (picked or "").strip()
        if not picked:
            return
        picked = hou.text.expandString(picked)
        entries = gallery_import.entries_from_file(picked)
        if not entries:
            if ui is not None:
                ui.displayMessage(
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
        choice = ui.displayMessage(
            "Import %d material presets from\n%s\n\n%s\n\n"
            "Thumbnails are NOT rendered during the import - select the "
            "new materials afterwards and use Update Preview."
            % (len(entries), os.path.basename(picked), listing),
            buttons=("Import", "Cancel"),
            default_choice=0, close_choice=1,
        ) if ui is not None else 1    # no screen to ask, so the answer is the close_choice - Cancel
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
        if ui is not None:
            ui.displayMessage(
                "Gallery import finished.\n\n"
                "Imported: %d\nSkipped: %d\nFailed: %d\n\n"
                "Select the new materials and use Update Preview to "
                "generate their previews."
                % (summary.get("imported", 0), summary.get("skipped", 0),
                   summary.get("failed", 0))
            )

    def cleanup_db(self) -> None:
        """Cleans the WHOLE v2 estate in one pass, one combined report: the material library, the COP library (the same integrity passes over cops.json), registered folder pointers whose directory is gone, and favorites pointing at files that are gone."""
        ui = getattr(hou, "ui", None)
        if not self.material_model:
            if ui is not None:
                ui.displayMessage("Please open a library first")
            return

        if ui is None or ui.displayMessage(
            "Clean Library?",
            help="Removes index rows whose files are gone, deletes "
                 "orphaned files that no library references, and drops "
                 "folder pointers and favourites that no longer exist.\n\n"
                 "Files are deleted from disk. This cannot be undone.",
            buttons=("Clean Library", "Cancel"),    # confirm BEFORE, because this DELETES: it unlinks .mat/.interface/.png files and drops folder pointers and favourites, and two one-click entry points reach it
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
            if ui is not None:
                ui.displayMessage(
                    "Library cleanup removed:\n\n" + "\n\n".join(sections)    # the RECORD of an irreversible act, not a notification that work ended: the grid cannot show an unlinked file or a dropped pointer
                )
        else:
            debug.event("cleanup", "nothing to clean")    # no dialog - nothing changed, and the log keeps the record

    @staticmethod
    def _volume_unreachable(path: str) -> bool:
        """The path's VOLUME is not mounted - unreachable, as opposed to the path being gone from a volume that is right here, which os.path.isdir cannot tell apart. A path under an absent /Volumes/<name> root, or on an absent Windows drive letter, is unreachable."""
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
        """The File section's cleanup: drops registered folder pointers whose directory no longer exists and favorites whose file is gone. Only pointers and prefs entries are touched - never anything on disk."""
        lines = []

        removed_folders = []
        skipped_unmounted = 0
        folders = list(self.prefs.file_folders)    # the LIVE file_* keys only: the dormant pre-merge texture_*/geometry_*/hip_* quartets are left alone, because they are what an older build on another machine still reads
        for index in range(len(folders) - 1, -1, -1):    # highest row first, so removing one never shifts the row of another not yet examined
            path = folders[index]
            if os.path.isdir(path):
                continue
            if self._volume_unreachable(path):    # unreachable is not gone: an unmounted share answers isdir exactly like a deleted folder, and pruning on that deletes the user's folder list every time the network blinks
                skipped_unmounted += 1
                debug.event("cleanup", "folder pointer kept - its volume "
                            "is not mounted", path=path)
                continue
            debug.event("cleanup", "folder pointer removed", path=path)
            self.file_folders_model.remove_folder(index + 1)    # through the MODEL, never through prefs: remove_folder wraps the same prefs write in beginRemoveRows and drops the count cache with it. Row 0 is the synthetic "All" entry, hence +1
            removed_folders.append(path)
        if removed_folders:
            lines.append(    # NAMES, not a count - a count is a sentence nobody can check
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
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage("Please open a library first")
            return
        lib_dir = self.prefs.dir
        hostos.open_path(lib_dir)

    def add_file_folder_user(self) -> None:
        """Register a new folder pointer for the File section. Only stores the path - never scans or copies anything until the folder is actually selected in the list."""
        ui = getattr(hou, "ui", None)
        path = ui.selectFile(file_type=hou.fileType.Directory) if ui else ""
        if not path:
            return
        self.file_folders_model.add_folder(hou.expandString(path))

    def remove_file_folder_user(self) -> None:
        """Unregister the selected folder pointer(s). Only removes the pointer from the list - never touches anything on disk."""
        rows = sorted(
            (i.row() for i in self.cat_list.selectedIndexes()), reverse=True
        )
        for row in rows:
            self.file_folders_model.remove_folder(row)

    ALL_SECTIONS = sections.all_sections()    # fixed section order + DISPLAY labels, of which the enabled_sections pref chooses which appear. The KEYS are STORAGE, not display: "cop" and "gradient" are what enabled_sections and the per-section state remember, so they stay put while labels change, and renaming one would silently reset which sections a user has enabled. Delegates to sections.all_sections() because the sections own their own labels - three copies of this list once existed and two silently disagreed

    def _online_segments(self) -> list:
        """The ONLINE strip: one tab per source, in source order. A parallel world, not a filtered version of the local one - no File tab, and the enabled_sections preference does not apply, because a source is not a section."""
        return [(source.name, source.name)    # all_sources() is already the one list of them, so a new source is one entry there and appears here on its own
                for source in matx_sources.all_sources()]

    def _build_section_tabs(self) -> None:
        """(Re)build the tab strip: ONE strip over two lists - the enabled local sections, or the online sources while the online browser is showing. Switching worlds reuses this path rather than keeping a second strip in sync."""
        if self._is_online():
            segments = self._online_segments()
        else:
            enabled = self.prefs.enabled_sections
            segments = [(k, lbl) for (k, lbl) in self.ALL_SECTIONS
                        if k in enabled]
        if not segments:
            segments = [("material", "Material")]
        if getattr(self, "section_tabs", None) is not None:    # replace any existing strip; it lives at layout index 1, under the toolbar row
            if self._central_layout is not None:
                self._central_layout.removeWidget(self.section_tabs)
            self.section_tabs.deleteLater()
        self.section_tabs = ui_helpers.SectionTabBar(segments)
        self.section_tabs.segmentClicked.connect(
            lambda key: self._on_tab_toggled(key, True)
        )
        self.section_tabs.cancelClicked.connect(self._on_cancel_conversions)
        bar = getattr(self, "texture_progress", None)
        self.section_tabs.set_cancel_visible(    # a rebuild mid-batch: the chip's state is READ from the bar, the one source, so the new strip cannot disagree with it
            bar is not None and not bar.isHidden())
        if self._central_layout is not None:
            self._central_layout.insertWidget(1, self.section_tabs)
        keys = [k for k, _ in segments]
        current = (getattr(self, "online_source", None) if self._is_online()
                   else getattr(self, "current_section", "material"))
        self.section_tabs.setChecked(
            current if current in keys else keys[0], emit=False    # keep the current tab checked if it survived, else the first available; emit=False because setup() activates explicitly, and the models may not exist yet at construction
        )


    def _apply_enabled_sections(self) -> None:
        """After Preferences may have changed enabled_sections: rebuild the strip, and if the section that was showing got hidden, switch to the first still-enabled one."""
        enabled = self.prefs.enabled_sections
        self._build_section_tabs()
        if self.current_section not in enabled and self.material_model:
            keys = [k for k, _ in self.ALL_SECTIONS if k in enabled] or [
                "material"
            ]
            if self._is_online():
                self._section_before_online = keys[0]    # a SECTION KEY IS NOT A SOURCE NAME: `_on_tab_toggled` would forward it to `open_online_source`, so the section behind the online world is only re-pointed here and switched when it is actually shown again
            else:
                self._on_tab_toggled(keys[0], True)

    def _on_tab_toggled(self, key: str, checked: bool) -> None:
        """A tab in the strip was clicked. In the online world a tab is a SOURCE; otherwise it switches the local section, and a key whose section is not built yet leaves the view underneath unchanged."""
        if not checked:
            return
        if self._is_online():
            self.open_online_source(key)    # in the online world a tab is a SOURCE, not a section
            return
        if self.material_model is None:    # setup() never ran - no library configured yet - and init_ui() builds and enables the tab strip regardless, so a click can land here first
            return
        self._capture_section_state()    # the OUTGOING section's view state, before anything changes: current_section still names it here
        self.current_section = key
        debug.event("section", "switched", to=key, online=self._is_online())
        section = self.sections.get(key)
        if section is None:
            debug.event("section", "section not built yet - the view "
                        "below will not change", section=key)
            return
        self._apply_context(section, key)

    def _apply_context(self, context, key: str) -> None:
        """Activate a context and do everything that MUST follow it - the ONE path every section takes, and the online world with it, so the toolbar, the filter widgets, the restored view state and the Comments subject cannot drift from what is showing."""
        context.activate()
        self._sync_toolbar(context)    # EVERY toolbar control, from the one table - Capture included
        self._sync_filters_to_section(context)
        self._restore_section_state(key)
        self._refresh_notes_subject()
        empty_state.track(self)    # a switch swaps the MODEL under a view that has not changed, so the blank has to re-attach here or it keeps watching the context you left

    def _sync_filters_to_section(self, section) -> None:
        """Push the SHARED filter widgets into the incoming section: line_filter and cb_favsonly are one pair serving every section while each section filters on its own proxy, so syncing on entry is what makes the visible widgets always describe the visible grid."""
        text = self.line_filter.text() if self.line_filter else ""
        favourites = bool(self.cb_favsonly and self.cb_favsonly.isChecked())
        section.filter_text(text)
        section.filter_favorites(favourites)
        self.build_filter_menu()    # the third shared control, and the one that does NOT carry its setting across: each section keeps its own (a renderer means nothing to Colors), so this rebuilds the menu from what the section offers and ends by applying what it was left on

    def _capture_section_state(self) -> None:
        """Remember the current section's sidebar choice and grid scroll position (keyed by section) for _restore_section_state."""
        state = {}
        current = ui_helpers.live_current_index(self.cat_list)    # a FRESH index from the live model, so `.data()` below is safe: the sidebar's stored currentIndex is a PROXY index, and see ui_helpers.live_current_index for why isValid() is no guard on one
        if current is not None:
            state["cat_text"] = current.data()
        state["scroll"] = grid.visible_view(self).verticalScrollBar().value()
        self._section_view_state[self.current_section] = state

    def _restore_section_state(self, key: str) -> None:
        """Re-select the sidebar entry the section had when last left (overriding the activation method's default) and bring the grid scroll back. Matching is by display TEXT, so a category rename or reordering between visits degrades to the default instead of selecting the wrong row."""
        state = self._section_view_state.get(key)
        if not state:
            return
        cat_text = state.get("cat_text")
        if (
            cat_text
            and key not in ("file",)    # the File section skips the sidebar part: its folder restore is prefs-based, survives relaunches, and already ran in FolderSection.activate()
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
                        self.update_selected_cat()    # the same handler a real click runs, so the right filter re-applies for whichever section this is
                        break
        scroll = state.get("scroll")
        if scroll:
            QtCore.QTimer.singleShot(    # deferred one event-loop turn: the view has just swapped models and relaid itself out, and an immediate setValue is clamped or overridden by that layout pass
                0,
                lambda: grid.visible_view(self)
                .verticalScrollBar().setValue(scroll),
            )

    TOOLBAR_CONTROLS = (    # THE TOOLBAR, AS DATA: which control follows which fact about the context showing, and whether that fact governs enabled-ness or visibility. This was five sync methods that could disagree, each carrying its own idea of which context it was in - three chips disabled by asking `_is_online()` twice in one method, and the Capture button governed from inside the activation path by `key == "file"`. A control's rule is one row here and the context answers it; a disabled chip paints at half opacity, so it reads as switched off rather than broken
        ("cb_favsonly", "takes_favourites", "enabled"),
        ("btn_notes", "takes_comments", "enabled"),
        ("btn_filter", "takes_filter_menu", "enabled"),
        ("btn_hip_capture", "takes_capture", "shown"),
    )

    def _sync_toolbar(self, context) -> None:
        """Walk the table. No toolbar path asks which WORLD it is in - the online world is a context like any other, and what a context does not offer it declares."""
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
        """The old entry point, kept because two call sites reach the toolbar without a context in hand."""
        context = self._section()
        if context is not None:
            self._sync_toolbar(context)

    def _sync_filter_placeholder(self) -> None:
        """Set the Filter Box's placeholder from the ACTIVE context's own search_hint - one box serves every tab and the online browser, so it is set from here, which runs on every section AND mode change. The online browser is not a branch: it declares a hint like any other context."""
        if self.line_filter is None:
            return
        self.line_filter.setPlaceholderText(
            getattr(self._section(), "search_hint",
                    sections.Section.search_hint))

    def _section(self):
        """The active CONTEXT - a Section, or the online world, which is NOT a section: it is not in `sections` and never appears in `enabled_sections`. It drives the same four areas, so every area path asks for it the same way and never has to know which world it is in."""
        if getattr(self, "online_mode", False):
            return getattr(self, "online_context", None)
        return getattr(self, "sections", {}).get(self.current_section)

    def tile_delegates(self) -> tuple:
        """EVERY tile delegate, once, for the sites that have to reach all of them - the accent sweep and the column widths among them. Built from the SECTIONS rather than written out here, so a section that arrives with a delegate of its own joins by existing."""
        found = []
        for section in getattr(self, "sections", {}).values():
            name = getattr(section, "delegate_attr", "")
            delegate = getattr(self, name, None) if name else None
            if delegate is not None and delegate not in found:
                found.append(delegate)
        online = getattr(self, "matx_delegate", None)    # by name, because the online world is not a section and so is not in `sections` for the loop above to find - its delegate is its own, carrying only the roles matx_library has
        if online is not None and online not in found:
            found.append(online)
        return tuple(found)

    def _is_online(self) -> bool:
        """Is the online world showing? The mode alone answers it - the online world is its own world with its own tab strip of sources, not a view mode over one section, so no section key is part of the question. ONE predicate, so no handler works it out for itself."""
        return bool(getattr(self, "online_mode", False))    # current_section goes on naming the LOCAL section underneath, untouched while you are away, and that is what leaving puts you back on

    def _on_online_source(self, action) -> None:
        """A View menu material-source entry was clicked. Material Library returns to the local library; an online source enters its browser."""
        if action is self.action_material_library:
            self.leave_online_world()
            if self.current_section != "material":
                self.section_tabs.setChecked("material")
        elif action.isChecked():    # the entries share one exclusive group, so Qt keeps exactly one checked
            self.open_online_source(action.text())

    def enter_online_world(self) -> None:
        """Switch to the online world: its own tab strip, one tab per source, nothing to do with the local sections. Where you came FROM is remembered, because leaving puts you back there - you dipped into the online browser, you did not change what you were working on."""
        if self._is_online():
            return
        self._capture_section_state()    # capture on the way IN as well, or leaving (through `_apply_context` -> `_restore_section_state`) puts you back on the category stored at the last TAB SWITCH rather than what you were looking at
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
        section = self._section()    # entering repointed every shared widget at the online models, so leaving has to repoint them back, and nothing else will: on the plain path `back` is a section we never left, so setChecked emits nothing and no _on_tab_toggled or activate() follows. WATCH: `_apply_enabled_sections` re-points `_section_before_online` while online, and on THAT path back != current_section and setChecked does emit - this repoint has to be correct either way
        if section is not None:
            self._apply_context(section, section.key)    # THE ONE PATH, as entering already takes - `activate()` alone would leave the toolbar to a separate call

    def open_online_source(self, source_name: str) -> None:
        """Show one source in the online world - a tab click, now that the strip IS the sources."""
        self.online_mode = True
        self.online_source = source_name
        act = self.online_source_actions.get(source_name)
        if act is not None and not act.isChecked():
            act.setChecked(True)
        debug.event("online", "source opened", source=source_name)
        if self.section_tabs is not None:    # NO TAB FORCING: the strip IS the sources in this world, so the tab to check is the source just picked - never a local section
            self.section_tabs.setChecked(source_name, emit=False)
        self.matx_online_model.set_source(source_name)
        self.enter_online()
        self._select_online_all()    # an explicit source-pick starts you on "All", never a stale category from the previous source; kept here rather than in the activation path so switching tabs away and back does not reset the category you were browsing

    def _select_online_all(self) -> None:
        """Select the online sidebar's "All" row (row 0) and clear any category filter, so the grid shows the whole source."""
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
        """Leave the online browser, back to the local library (Material Library)."""
        self.online_mode = False
        if getattr(self, "action_material_library", None) is not None:
            self.action_material_library.setChecked(True)    # exclusive group, so checking this unchecks any source
        debug.event("online", "exited")    # WHERE YOU LAND is the caller's business: the toolbar button remembers the section you left from, and the Material Library menu entry means the material library. Forcing a tab from in here is the coupling the online world was taken out of

    def enter_online(self) -> None:
        """Enter the online world through the SAME path a section takes: `OnlineContext.activate()`, and then everything `_apply_context` must do after it - the Capture button, the search box and the Comments subject follow the online world the way they follow every section."""
        self._apply_context(self.online_context, self.online_context.key)    # not an `_activate_*` method on a section, because the online world is deliberately not a Section and never appears in `enabled_sections`; a ban test keeps the old shape from coming back


    _IMPORT_PROGRESS_SCALE = 1000    # sub-steps per material for the download bar: a smooth 0..N*SCALE range folds each material's own 0..1 download fraction into the overall multi-import progress

    @contextlib.contextmanager
    def _download_bar(self, records):
        """The download bar, for the length of a multi-record import, and ONE frame for both online importers. Yields `progress_for(i)` - the per-record 0..1 callback for record `i` of the batch, folded into the overall 0..N*SCALE range. The bar is shown only when something actually has to be downloaded, and is always taken down again."""
        total = len(records)
        scale = self._IMPORT_PROGRESS_SCALE
        pump = QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents    # the download is synchronous and blocks the UI thread, so the byte callback pumps events per chunk; excluding user input is what stops a second click re-entering mid-import (the geometry thumbnail pass does the same)
        self._online_download_active = True    # the event pumping can deliver a late preview-worker signal, and this flag keeps that from repainting the bar with preview counts while the download owns it
        show_bar = self._needs_download(records)
        if show_bar:
            self.set_conversion_bar_visible(True)
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
                self.set_conversion_bar_visible(False)

    def _import_online_records(self, records) -> None:
        """Import one or more online records into the LIBRARY."""
        if not len(records):
            return
        total = len(records)
        failures = []
        with self._download_bar(records) as progress_for:
            for i, rec in enumerate(records):
                on_progress = progress_for(i)
                try:    # ONE BAD RECORD MUST NOT ABANDON THE BATCH: matx_import.import_record has only try/finally, so build_karma_material and library.add_asset raise straight through it, and without this the remaining records go unimported and `failures` never reaches its dialog
                    ok, reason = self.import_online_material(
                        rec, on_progress=on_progress
                    )
                except Exception as exc:                  # noqa: BLE001
                    debug.exception("online import", exc, record=rec.title)
                    ok, reason = False, str(exc)
                if not ok:
                    failures.append("%s: %s" % (rec.title, reason))
        ui = getattr(hou, "ui", None)
        if failures and ui is not None:    # ONE dialog for the batch, never one per record
            ui.displayMessage(
                "Amaze: %d of %d could not be imported:\n\n%s"
                % (len(failures), total, "\n".join(failures[:10]))
            )

    def import_online_material(self, record, on_progress=None):
        """Download (if needed) and register one online material as a normal library material with renderer Karma; on_progress(frac) is called with a 0..1 fraction during the download when given. Returns (ok, reason) - the CALLER reports, never this."""
        if record is None or not self.material_model:
            return (False, "No library to import into.")
        source, resolution, error = self._online_source_for(record)
        if error:
            return (False, error)
        if source is None:
            return (False, "Unknown source")
        if getattr(record, "kind", "") == "amazepkg":
            return self._import_amaze_package_record(
                record, source, restore=False, on_progress=on_progress)
        with ui_helpers.relayout(self.material_model):
            ok, reason = matx_import.import_record(
                record, source, resolution, self.material_model, self.prefs,
                progress=on_progress,
            )
        if not ok:
            return (False, reason or "Import failed.")
        self.category_model.check_add_category(record.category)    # no relayout wrapper here: check_add_category announces itself with begin/endInsertRows, and pairing the two segfaults H21 (research.md)
        self._refresh_sidebar_categories()
        return (True, "")

    def _package_models(self) -> dict:
        """{section key: library model} for every asset section that has one."""
        models = {}
        for cls in sections.SECTION_CLASSES:
            attr = getattr(cls, "model_attr", "")
            model = getattr(self, attr, None) if attr else None
            if model is not None and getattr(cls, "key", "") != "file":
                models[cls.key] = model
        return models

    def _absorb_package_summary(self, summary) -> None:
        """The panel's half of a package import: register the touched categories on their sidebars, and the import folder as a location when files landed."""
        for key, names in summary.get("categories", {}).items():
            section = self.sections.get(key)
            st = section.stack() if section is not None else None
            if st is None:
                continue
            for name in sorted(names):
                st.categories.check_add_category(name)
        if summary.get("files"):
            folder = os.path.join(self.prefs.dir, "import")
            self.prefs.add_file_folder(folder)
            self.prefs.set_file_folder_name(folder, "Import")

    def _import_amaze_package_record(self, record, source, restore,
                                     on_progress=None):
        """One TILE into the library - its entry read straight out of the hosted package by member, fresh or restore - answering (ok, reason) like the material path beside it."""
        try:
            entry = record.payload.get("entry")
            if not entry:
                return (False, "the record carries no manifest entry")
            bundle = source._open_package(record.payload["package"])
            summary = packages.import_entries(
                self._package_models(), self.prefs, bundle, [entry],
                restore=restore)
            self._absorb_package_summary(summary)
            if on_progress is not None:
                on_progress(1.0)
            if summary.get("refused"):
                return (False, "; ".join(summary.get("problems") or ())
                               or "the tile could not be imported")
            if restore and summary.get("skipped"):
                return (True, "")
            if not summary.get("imported") and not summary.get("files"):
                return (False, "nothing in this tile could be imported")
            return (True, "")
        except Exception as exc:                          # noqa: BLE001
            debug.exception("package import", exc, record=record.title)
            return (False, str(exc))

    def restore_amaze_packages(self, records) -> dict:
        """Restore-mode import for the SELECTED tiles: adopt-only by curated tag / original id, one summary for the batch."""
        totals = {"imported": 0, "skipped": 0, "files": 0, "refused": 0}
        failures = []
        for record in records:
            source, _resolution, error = self._online_source_for(record)
            if error or source is None:
                failures.append("%s: %s" % (record.title,
                                            error or "Unknown source"))
                continue
            try:
                entry = record.payload.get("entry")
                if not entry:
                    raise ValueError("no manifest entry on the record")
                bundle = source._open_package(record.payload["package"])
                summary = packages.import_entries(
                    self._package_models(), self.prefs, bundle, [entry],
                    restore=True)
                self._absorb_package_summary(summary)
                for key in totals:
                    totals[key] += summary.get(key, 0)
            except Exception as exc:                      # noqa: BLE001
                debug.exception("package restore", exc,
                                record=record.title)
                failures.append("%s: %s" % (record.title, exc))
        ui = getattr(hou, "ui", None)
        if ui is not None:
            lines = ["Restored %d, %d already present."
                     % (totals["imported"], totals["skipped"])]
            if failures:
                lines += [""] + failures[:10]
            ui.displayMessage("\n".join(lines))
        return totals

    def _needs_download(self, records) -> bool:
        """True when importing these records will actually fetch bytes, answered WITHOUT touching the network - the source is looked up DIRECTLY here, never through _online_source_for, which also resolves the download RESOLUTION at one main-thread HTTP GET per package. Asked because the progress bar sits ABOVE the grid, so showing it for a value source (RGL, PhysicallyBased) that carries its numbers in the catalogue and downloads nothing shifts every tile down and back for no work at all."""
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
        """The Source object a record came from, and the resolution to fetch it at: (source, resolution, error)."""
        source = next(
            (s for s in self.matx_online_model.sources
             if s.name == record.source),
            None,
        )
        if source is None:
            return (None, None, "Unknown source %s" % record.source)
        if not source.needs_download(record):    # ASK THE SOURCE, never re-spell its answer as `record.kind == "values"`: that is the BASE class's answer and RGL overrides it, because a uid its shipped table has never seen still costs a measurement download
            return (source, None, "")     # nothing to download
        if record.kind in ("values", "amazepkg"):
            return (source, None, "")     # downloads, but picks no RESOLUTION - store tiles fetch exact members; the mocked-away version of this line refused every Amaze tile in production
        resolution = matx_sources.pick_resolution(
            source.resolutions(record), self.prefs.matx_resolution
        )
        if resolution is None:
            return (None, None,
                    '"%s" has no downloadable package.' % record.title)
        return (source, resolution, "")

    def _import_online_records_to_scene(self, records) -> None:
        """Build online records straight into the scene - the current LOP material library (or /mat) - without adding them to the library; amazepkg records split off to the LIBRARY door, a store tile being library data of ANY section (palette, snippet, material row) with no scene-build path of its own."""
        packages_only = [r for r in records
                         if getattr(r, "kind", "") == "amazepkg"]
        if packages_only:
            self._import_online_records(packages_only)
            records = [r for r in records
                       if getattr(r, "kind", "") != "amazepkg"]
        total = len(records)
        if not total:
            return
        built, failures, last = [], [], None
        ui = getattr(hou, "ui", None)
        with self._download_bar(records) as progress_for:
            with hou.undos.group("Amaze Import to Scene"):    # ONE undo step INCLUDING the destination resolution, which may itself create a material library: a material moved into a library that an undo then removes would have nothing coherent to undo to
                destination = nodes.karma_destination(self.prefs)
                if destination is None:
                    if ui is not None:
                        ui.displayMessage(
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
                        debug.exception("import to scene", exc,
                                        title=rec.title)
                        builder, reason = None, str(exc)    # one bad record must not abandon the batch; only DOWNLOAD failures come back as a `reason`, anything else raises
                    if builder is None:
                        failures.append("%s: %s" % (rec.title, reason))
                        continue
                    built.append(builder.name())
                    last = builder
                if last is not None:
                    last.setCurrent(True, True)    # front the new material like any hand-created node - a menu action IS the user asking for it
        debug.event("import", "to scene finished", built=len(built),
                    failed=len(failures))
        if ui is None:
            return
        if failures:
            ui.displayMessage(
                "Amaze: %d of %d could not be built:\n\n%s"
                % (len(failures), total, "\n".join(failures[:10]))
            )
        elif last is not None:
            ui.setStatusMessage(
                "Amaze: %s in %s" % (", ".join(built[:3]),
                                     last.parent().path())
            )


    def _select_default_sidebar_row(self, sidebar_proxy):
        """Select the sidebar's first row and return its RAW name - the caller must then apply the filter itself, FROM that name rather than from an assumption about what sorts first, because a programmatic select fires no clicked()."""
        if self.cat_list is None or sidebar_proxy is None:
            return None
        if sidebar_proxy.rowCount() <= 0:
            return None
        selection_model = self.cat_list.selectionModel()
        if selection_model is None:
            return None
        target = sidebar_proxy.index(0, 0)
        selection_model.select(    # `cat_list` has no persistent selection model of its own the way thumblist does, so a `setModel()` in an activate leaves it with nothing selected
            target, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.cat_list.setCurrentIndex(target)
        return self._raw_category_name(target)

    def edit_tile_icon(self, model, proxy, proxy_indexes) -> None:
        """"Edit Icon" on any tile, in any section that has tiles - one handler for all of them, needing only tile_icon()/set_tile_icon() from the model, and applying to the WHOLE selection (one icon for twelve LOP setups is the case it exists for)."""
        if model is None or not proxy_indexes:
            return
        held = []    # IDENTITY, not row numbers and not Qt indexes: this dialog is non-modal, so the library can move while it is open - a save appends, a delete shifts every row after it, a RELOAD renumbers the lot - and a QPersistentModelIndex is no better, because endResetModel() invalidates every one of them even when nothing moved
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

        existing = getattr(self, "_icon_dialog", None)    # NON-modal, so the Custom Color button can open Houdini's own picker (a native modal lands UNDER a Qt exec loop); one instance at a time, a second Edit Icon fronting the open dialog instead of stacking another
        if existing is not None:
            try:
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                pass                      # already deleted underneath
        single = len(rows) == 1    # the Name field rides along only where the model can rename, and is greyed on a multi-selection per the selection law - File has no rename, a file's name being the file on disk, so its dialog shows no field at all
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
                    rows = [row for row in range(model.rowCount())    # resolved HERE and not at open: where the held tiles are NOW, in one scan of the model on OK. A tile that went away during the dialog simply is not found
                            if model.tile_key(row) in held]
                    if not rows:
                        return
                    self._apply_icon_spec(model, rows, dialog.spec)
                    new_name = getattr(dialog, "new_tile_name", None)
                    if new_name and len(rows) == 1 and \
                            hasattr(model, "set_tile_name"):
                        model.set_tile_name(rows[0], new_name)
            finally:
                dialog.deleteLater()    # the panel is its C++ parent and outlives every dialog, so dropping the Python name frees nothing - 287 buttons and ~6.5MB stay alive per open otherwise

        dialog.finished.connect(_finished)
        dialog.show()
        return

    def _apply_icon_spec(self, model, rows, spec) -> None:

        failed = 0
        for row in rows:
            if not model.set_tile_icon(row, spec, save=False):
                failed += 1
        model.commit_tile_icons(rows)    # ONE save for the whole selection: set_tile_icon saves the index per call, so Ctrl-A over 546 materials would be 546 full database writes of a cloud-synced file at ~10ms each, freezing the panel for five seconds
        ui = getattr(hou, "ui", None)
        if failed and ui is not None:
            ui.displayMessage(
                "%d tile icon%s could not be saved - check that the "
                "library folder is writable."
                % (failed, "" if failed == 1 else "s")    # a real plural, never "icon(s)" - this one is a MODAL the user cannot look away from
            )


    def import_cop_assets(self) -> None:
        """Import every selected Nodes-section asset, reporting failures in one summary dialog (same shape as the material importer)."""
        failures = []
        with hou.undos.group("Amaze Import Nodes Asset"):    # one user action, one undo: the container and whatever is loaded into it must revert as a single step, never as separate entries
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
        ui = getattr(hou, "ui", None)
        if failures and ui is not None:
            ui.displayMessage(
                "Some node assets could not be imported:\n\n"
                + "\n".join(failures)
            )


    def get_code_category_names(self) -> list[str]:
        return self._category_names_from(self.code_category_model)

    def _current_code_category(self) -> str:
        """The category selected in the sidebar when the Code section is showing, "" for All - the save/new dialog's default category."""
        if self.current_section != "code":
            return ""
        return self._selected_category_name()

    def _add_code_snippet(
        self, code: str, language: str, default_name: str
    ) -> None:
        """Shared save flow for both Save-from-Node and New Snippet: open the Code dialog prefilled, then register the snippet."""
        if not self.code_model:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(
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
        self.code_model.add_asset(    # no layout wrapper: add_asset announces itself with begin/endInsertRows, and pairing the two segfaults H21
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
        """Node right-click `Save Code to <app>`: grab the node's code/snippet parm and open the save dialog prefilled."""
        if node is None:
            sel = hou.selectedNodes()
            node = sel[0] if len(sel) == 1 else None
        ui = getattr(hou, "ui", None)
        if node is None:
            if ui is not None:
                ui.displayMessage(
                    "Right-click a wrangle (or other node with a code "
                    "parameter) to save its snippet."
                )
            return
        parm = helpers.find_code_parm(node)
        if parm is None:
            if ui is not None:
                ui.displayMessage(
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

    def click_on_row(self, section, index, payload=None) -> None:    # THE CLICK WALKER: the second half of the interaction engine, with sections.DropRule carrying the declarations. It replaced FIVE hand-written double-click handlers that answered one question five ways - three carried a selection VETO, where a selected node that could not take the payload refused instead of creating, and two never consulted the selection at all. The drag walker has read these same declarations since the behaviour table shipped; this is the aiming method it was missing
        """A click door on `index` in `section` - aimed by the SELECTION, executed from the section's own declaration. BOTH DOORS COME THROUGH HERE: the double-click, and the menu entry labelled with the same verb."""
        if index is None or not index.isValid():
            return
        rule = sections.drop_rule(section, self, index)    # THE DRAG WALKER'S READER, not a second one - both doors read the one declaration through it
        if rule is None:
            self._cannot_load_here()
            return
        try:
            with helpers.preserving_selection_and_current():
                landed = self._apply_click_rule(section, rule, index,
                                                payload)    # `payload` is the menu's extra word where an entry carries one (Color's Apply as names a ramp basis); it reaches only the verbs that declare they take it
        except hou.PermissionError as refusal:    # ONLY this class, the same absorption the drag door carries: a click into a locked network is the app being told no, where any other exception is a defect that must still raise
            debug.exception("click refused", refusal,
                            section=getattr(section, "key", ""))
            debug.refuse(str(refusal),    # ▸p/refusal-sink
                         section=getattr(section, "key", ""))
            return
        if not landed:
            self._cannot_load_here()

    def _apply_click_rule(self, section, rule, index, payload=None) -> bool:
        """ONE precedence for every section's click door. THE SELECTION IS A HINT, NOT A VETO: a single visible selected node is offered the payload first, and a node that cannot take it FALLS THROUGH to the creation walk - the host's own rule, where a selection never blocks a creation and wiring to the current node is a separate, explicit gesture."""
        extra = {"basis": payload} if payload else {}    # the menu's extra word, handed on ONLY when there is one, so no verb ever sees a keyword it does not declare
        sel = self._visible_selected_nodes()
        if rule.click_on_node and len(sel) == 1:
            hint = sections.drop_verb(section, rule.click_on_node)    # the verbs a rule names resolve on the SECTION, never on the panel
            if bool(hint(index, sel[0], **extra)):
                return True
            debug.event("interact", "click hint declined - falling "
                        "through to the network",
                        verb=rule.click_on_node, node=sel[0].path())
        if rule.click_resolve:
            verb = sections.drop_verb(section, rule.click_resolve)
            return bool(verb(index, **extra))
        if rule.on_space:
            create = sections.drop_verb(section, rule.on_space)
            for network in self._view_create_networks():
                if create(index, network, **extra):
                    return True
        return False

    def get_cop_category_names(self) -> list[str]:
        return self._category_names_from(self.cop_category_model)

    def save_cop_from_node(self, node: hou.Node | None = None) -> None:
        """Node right-click `Save Network/Selection to <app>` (rc_calls.save_cop passes the clicked node through). Works in any context the Nodes section supports - SOP, COP, LOP and the rest; the asset records which one."""
        ui = getattr(hou, "ui", None)
        if not self.cop_model:
            if ui is not None:
                ui.displayMessage(
                    "Please set a library first. Use the %s panel - "
                    "Library/Open Dialog." % branding.APP_NAME
                )
            return
        if node is None:
            sel = hou.selectedNodes()
            node = sel[0] if len(sel) == 1 else None
        if node is None:
            if ui is not None:
                ui.displayMessage(
                    "Right-click the network - or the nodes - you want to save."
                )
            return
        net = node.parent()
        items = [i for i in hou.selectedItems() if i.parent() == net]
        if not any(i == node for i in items):
            items.append(node)
        if len(items) == 1 and self.cop_model.saves_whole_network(node):    # container vs selection: a network container right-clicked ON ITS OWN (a geo, a copnet, a lopnet, a subnet) saves the WHOLE network, anything else saves the selection inside the network that holds it and is named after the clicked node - and a multi-selection wins over the container reading, two geos selected meaning those two nodes rather than one of their interiors
            items = None

        current_cat = ""    # pre-select the category active in the panel when the Cop section is showing (mirrors the material save dialog)
        if self.current_section == "cop":
            current_cat = self._selected_category_name()

        dialog = save_dialog.SaveDialog(    # v1 keeps standard-new semantics only - no Overwrite flow yet
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
        save_error = None    # NO LAYOUT WRAPPER around the add_asset below: it announces itself with begin/endInsertRows, and pairing the two segfaults H21 (research.md, measured 2026-08-04)
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
            if ui is not None:
                ui.displayMessage(
                    '"%s" could not be saved: %s' % (node.name(), save_error)
                )
            return
        if not result and ui is not None:
            ui.displayMessage(
                '"%s" could not be saved.' % node.name()
            )

    def _active_network_pwd(self) -> hou.Node | None:
        """The network the user is most likely looking at: the visible (current-tab) network editor's pwd, falling back to any open editor - the same preference get_active_network_editor uses on the material side."""
        ui = getattr(hou, "ui", None)
        if ui is None:
            return None
        editors = [
            pt
            for pt in ui.paneTabs()
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
        """True for anything whose children are SOPs - a geo object, a SOP Create LOP, a plain sopnet - i.e. a valid drop-INTO target for a geometry file."""
        try:
            category = node.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return False
        return category is not None and category.name() == "Sop"

    @staticmethod
    def _create_loader_inside(container: hou.Node, loader_type: str):
        """Create the loader in the DEEPEST SOP network in/under the container, falling outward on failure - whichever level actually accepts the node wins."""
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
        for _depth, net in sorted(candidates, key=lambda c: -c[0]):    # deepest first, then try-per-candidate: a SOP Create LOP is a locked HDA whose EDITABLE network sits at sopcreate/sopnet/create, so a shallower SOP-children network can refuse with hou.PermissionError ("Cannot create a node inside a locked asset")
            try:
                return net.createNode(loader_type)
            except hou.Error as exc:
                last_error = exc
        raise last_error or hou.OperationFailed("no SOP network found")

    def import_geo_asset(self, index: QtCore.QModelIndex) -> None:
        """Double-click/right-click import for a geometry file, CONTEXT-AWARE per network (the branches of _import_geo_in_context spell out which). The drag imports the same way at the release point (drop_geo_at_release)."""
        path = index.data(self.file_files_model.PathRole)
        if not path:
            return
        with helpers.preserving_selection_and_current():    # WRAPPED HERE and not at each caller, so the door, the drag and any later caller inherit it instead of having to remember - like every other scene-importing verb, this one leaves the artist's current node and display flag as it found them
            self._import_geo_in_context(path, self._active_network_pwd())

    def _import_geo_in_context(
        self, path: str, dest: hou.Node | None
    ) -> hou.Node | None:
        ui = getattr(hou, "ui", None)
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
            if category == "Sop":    # already inside a SOP network (a geo node's innards, a SOP Create's) - a new loader SOP in place
                loader = dest.createNode(loader_type)
            elif category == "Lop":    # a LOP network gets a new SOP Create holding the loader, so geometry lives directly in the stage and never as a stray /obj export
                anchor = None
                try:
                    anchor = dest.displayNode()
                except (AttributeError, hou.OperationFailed):
                    anchor = None
                if anchor is not None:
                    container = anchor.createOutputNode("sopcreate", name)    # chained onto the current tree the way Houdini's own tab menu chains a light or a render node - createOutputNode() is that built-in, wiring the new node to the display node's output; the else below is the loose node an empty stage gets
                else:
                    container = dest.createNode("sopcreate", name)
                loader = self._create_loader_inside(container, loader_type)
            elif category == "Object":    # an OBJ network gets a new geo named after the file, with the right loader SOP inside
                container = dest.createNode("geo", name)
                loader = container.createNode(loader_type)
            else:    # not a network that can hold geometry (mat/cop/...) - fall back to a fresh geo at /obj
                obj = hou.node("/obj")
                if obj is None:
                    raise hou.OperationFailed("no /obj network")
                container = obj.createNode("geo", name)
                loader = container.createNode(loader_type)
        except hou.Error as exc:    # hou.Error, NOT just OperationFailed: the locked-asset case raises hou.PermissionError, a SIBLING class, and catching too narrowly leaves a dead sopcreate in the scene behind a silent traceback
            if container is not None:
                try:
                    container.destroy()
                except (hou.OperationFailed, hou.ObjectWasDeleted):
                    pass
            debug.event("import", "geometry import failed",
                        file=base, error=str(exc))
            if ui is not None:
                ui.displayMessage(
                    f"Could not import {base}: {exc}"
                )
            return
        parm = helpers.find_file_parm(loader)
        if parm is None:
            try:
                (container or loader).destroy()
            except (hou.OperationFailed, hou.ObjectWasDeleted):
                pass
            if ui is not None:
                ui.displayMessage(
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
            try:
                container.setDisplayFlag(True)    # what you just added is what you want to see: createOutputNode wires but does not flag, so a Solaris import would otherwise land downstream of the display node and show nothing
            except (AttributeError, hou.Error):
                pass
        return container or loader    # the import seam: the caller receives what was created - the container when one was built, else the loader itself

    def _drop_context_under_cursor(
        self, matcher, include_viewports: bool = False    # matcher = a type-name substring like "materiallibrary"/"copnet", or a callable(node) -> bool such as geometry's SOP-container test
    ) -> hou.Node | None:
        """Resolve where a drag was RELEASED, for drops Houdini's native handling ignores. Returns the node to import against - the node under the cursor when it matches, else the editor's own pwd (which is itself the target when the user is working inside one) - and None when the release wasn't over anything import-worthy."""
        pane_tab, pane_type = self._pane_and_kind_under_cursor()
        if pane_tab is None:
            return None
        if (
            include_viewports    # geometry drops: a release over a Scene Viewer resolves to the network the VIEWPORT is showing (its pwd - /obj for the object view, /stage for the Solaris view, a geo node's innards at SOP level), so the same context rules apply as everywhere else. Materials deliberately keep this off: their viewport releases are the Drag Engine's own (viewport_release_target picks the actual prim/node under the cursor), so resolving a network here would double-handle them
            and pane_type == hou.paneTabType.SceneViewer
        ):
            try:
                return pane_tab.pwd()
            except AttributeError:
                return None
        if pane_type != hou.paneTabType.NetworkEditor:    # the network canvas takes no native node drops (DRAGTEST log, 2026-07-19), which is the whole reason this resolution exists
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

    def _import_material_builder(self, asset_id, target, context_node=None):
        """One import shape for every release bridge: import a library material by id, report failures, return the builder VOP or None. Creation happens at the drop, nowhere before."""
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
            debug.event("import", "import failed",    # every failed import leaves a NAMED reason in the log, never a bare "imported: 0"
                        material=mat.name, target=target,
                        reason=reason or "(no reason reported)")
            ui = getattr(hou, "ui", None)
            if reason and ui is not None:
                ui.displayMessage(reason)
            return None
        return handler.builder_node

    def import_material_into_container(self, asset_id, container):
        """LOP-release bridge: import into the given materiallibrary."""
        return self._import_material_builder(
            asset_id, "lop", context_node=container
        )

    def assign_material_to_obj(self, asset_ids, obj_node) -> bool:
        """OBJ-viewport release: import to /mat - the OBJ world's home - and assign the FIRST material to the picked object; extra selected materials import beside it unassigned."""
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
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(
                    "'%s' has no material parameter - imported to /mat "
                    "without assigning." % obj_node.name()
                )
            return False
        parm.set(builder.path())
        return True

    def _selected_material_ids(self, index) -> list:
        """Asset ids of the selection, the pressed tile first."""
        row = self.material_sorted_model.mapToSource(index).row()    # isValid() does NOT catch a stale row: a proxy index built when the model was longer still reports valid, and mapToSource then returns -1, which indexes assets[] from the END and hands back the WRONG material silently, or raises IndexError on an empty library, inside a release slot
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

    def _material_lop_viewport_drop(self, ids, viewer, primpath) -> bool:
        """LOP-viewport release: our ancestor-prim menu, then import into a materiallibrary resolved by Houdini's STOCK helper and assign with its stock assignMat - SideFX semantics, Amaze law."""
        ui = getattr(hou, "ui", None)
        stock = dragengine.stock_lop()
        if stock is None:
            if ui is not None:
                ui.displayMessage(
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
        choices = lop_assign.drop_choices(stage, primpath)    # WHAT to offer is USD reasoning and lives in core/lop_assign; this only renders it. No "Import only" entry, because a drop aimed at a specific object always means assign - network drops are the import-only path
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
        cmenu.deleteLater()    # a QMenu parented to the panel outlives the gesture and the panel outlives the session - the same measured leak `grid._open` pays a deleteLater() for. The choice is read out FIRST because the dict is keyed by the menu's own QActions
        if chosen is None:
            return False    # menu dismissed, so nothing happens and no outcome icon either way: the dispatcher reports "menu" for this whole path, the menu itself having been the feedback
        kind, payload = actions[chosen]
        assign_path = payload if kind == "assign" else None
        swap_targets = payload if kind == "swap" else None
        undo_label = (    # the undo group opens BEFORE the container policy, not just around the import: creating the materiallibrary, wiring it, moving it and moving the display flag all ran OUTSIDE the group, so one Ctrl+Z undid the assignment and the VOP and left an EMPTY library wired into the display chain with the flag still moved. Verified through hou.undos.undoLabels(); that orphan library is what the container policy then picks up for every later drop
            "Amaze Swap Material" if swap_targets is not None
            else "Amaze Assign Material"
        )
        with hou.undos.group(undo_label), dragengine.keep_editor_focus():
            liblop = dragengine.first_materiallibrary(    # CONTAINER POLICY, the anti-clutter rule: the network's FIRST existing materiallibrary takes every drop and only a library-less network gets a new one, assignments reusing the first existing assignmaterial the same way, so repeated drops converge on ONE library and ONE assign node. Viewport drops prefer a library IN THE DISPLAY CHAIN, because an assignment into a disconnected one silently does not display, then any first, then create WIRED into the chain - the placement law being that viewport-created libraries join the display and network-created ones stay unwired
                lopnet, connected_to=target_lop
            )
            if liblop is None and not (assign_path or swap_targets):
                liblop = dragengine.first_materiallibrary(lopnet)    # the unconditional fallback is only safe when nothing will be ASSIGNED: with an assignment pending, an unwired leftover library silently does not display, so the material imports, the binding is written and the viewport does not change. Better to create one wired into the chain below
            created = False
            if liblop is None:
                try:
                    liblop = lopnet.createNode("materiallibrary")
                    if target_lop is not None:
                        liblop.setInput(0, target_lop)
                    helpers.auto_place(liblop)
                    liblop.setDisplayFlag(True)
                    created = True
                except hou.Error as refusal:    # hou.Error, NOT hou.OperationFailed: a locked digital asset answers `Cannot create a node inside a locked asset` as hou.PermissionError, a SIBLING of OperationFailed, which went straight past this handler - 12 tracebacks in the real log with this message one line away and unreachable. The network-drop path already catches it this way (research.md > hou.PermissionError is a SIBLING)
                    debug.event("drag", "the network refused a material "
                                "library", dest=lopnet.path(),
                                error=str(refusal))
                    if ui is not None:
                        ui.displayMessage(
                            "Amaze: %s cannot take a Material Library, so "
                            "the material was not imported.\n\n%s"
                            % (lopnet.name(), refusal)
                        )
                    return False
            assign_node = dragengine.find_assignmaterial(    # prefers one in the display chain, exactly as the library lookup above does: unfiltered this took the first assignmaterial in CREATION order, so a leftover disconnected one won over the live node and the binding was written where nothing displays it, silently
                lopnet, connected_to=target_lop
            ) or dragengine.find_assignmaterial(lopnet)
            if assign_node is not None:    # stock.assignMat REUSES an assignmaterial passed as the node (multiparm dedupe) and otherwise creates a fresh one chained onto what we pass, so that anchor must sit AT OR BELOW the library - chaining onto the old display node when the library was JUST created put the assign in a parallel branch UPSTREAM of its own material
                node2 = assign_node
            elif created:
                node2 = liblop
            else:
                node2 = target_lop if target_lop is not None else liblop
            if swap_targets is not None:
                ids = list(ids)[:1]    # a swap replaces ONE material; importing the rest of a multi-selection would recreate the dead-material pile the swap exists to prevent
            vops = []
            imported = []    # PAIRED with their asset id: vops[0] was assumed to be the pressed tile, but the list only collects SUCCESSFUL imports, so a pressed material that failed - a missing plugin or node type, a real reported class - made vops[0] a DIFFERENT material, and that is what got assigned, with no warning
            for aid in ids:
                vop = self.import_material_into_container(aid, liblop)
                if vop is not None:
                    imported.append((aid, vop))
                    vops.append(vop)
            pressed_vop = None
            if imported and ids and imported[0][0] == ids[0]:
                pressed_vop = imported[0][1]
            elif imported and ui is not None:
                ui.displayMessage(
                    "The material you dropped could not be imported, so "
                    "nothing was assigned. The others in the selection "
                    "were still added to the library."
                )
            debug.event("drag", "lop viewport drop", imported=len(vops),
                        amaze=liblop.path(), assign=str(assign_path),
                        swap=bool(swap_targets))
            if pressed_vop is not None and swap_targets is not None:
                reason = lop_assign.swap_assignments(    # the module does the USD and REPORTS; the panel owns the dialog, being the half with a screen
                    stock, lopnet, liblop, node2, swap_targets,
                    pressed_vop
                )
                if reason and ui is not None:
                    ui.displayMessage("Amaze: " + reason)
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
                    if ui is not None:
                        ui.displayMessage(
                            "Amaze: imported, but assigning failed: %s" % exc
                        )
        return bool(vops)





    def _import_materials_into_context(self, context, ids,
                                       position=None) -> None:
        """Network-release import for the material section, in ONE undo group so the whole multi-drop reverts as one step. Placement rides the import seam - the import RETURNS what it created and `helpers.place_nodes` is the one placement rule - so a position lands each copy at the release point, a multi-drop cascading from it."""
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
                debug.refuse(reason, net=context.path())    # the door marks library damage, which picks the dialog ▸p/refusal-sink
                break    # ONE refusal per multi-drop, never one per asset ▸p/dialogs-are-a-bill
            if position is not None:
                helpers.place_nodes(created, hou.Vector2(
                    position.x() + offset * 0.6,
                    position.y() - offset * 0.9))

    def _category_under_cursor(self):
        return sidebar.category_under_cursor(self)

    def _set_drag_hover_row(self, row: int) -> None:
        """Highlight (row) or clear (row=-1) the sidebar row being dragged over. Logic in panel/sidebar.py."""
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
        """Droppable items under the cursor in a network editor, arriving as (item, ...) tuples - via the editor's OWN coordinate chain (cursorPosition -> posToScreen -> networkItemsInBox, all documented in the same screen space; wiki: Node graph)."""
        try:
            if not editor.isUnderCursor():    # isUnderCursor() gates out the pane's chrome (toolbars/controls)
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

    def _pane_and_kind_under_cursor(self):
        """The pane tab under the cursor and its type, or (None, None) - compare the type at the CALL SITE, never here."""
        pane_tab = dragengine.pane_tab_under_cursor()
        if pane_tab is None:
            return None, None
        try:
            return pane_tab, pane_tab.type()
        except AttributeError:
            return None, None

    def _node_under_cursor(self, pane_tab=None,
                           pane_type=None) -> hou.Node | None:
        """The scene node the cursor is over: in a network editor the node under the mouse (native cursor chain, see _network_items_at_cursor), over a Parameter Editor the node whose parameters that pane is showing. `pane_tab`/`pane_type` skip the pane lookup where the caller already tracked it ▸p/drag-move-cost."""
        if pane_tab is None:
            pane_tab, pane_type = self._pane_and_kind_under_cursor()
        if pane_tab is None:
            return None
        if pane_type == hou.paneTabType.Parm:    # dropping a gradient on the parm pane you are already looking at beats hunting the node, especially for ramps
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

    def save_gradient_from_node(self, node: hou.Node | None = None) -> None:
        """`Save Gradient to <app>` (node right-click, or any caller with a ramp-bearing node): serializes the node's first color ramp and registers it as a user gradient in the Gradients section, in a category chosen (or created) in the save dialog. With no node it falls back to the single selected one, as the material save flow does."""
        ui = getattr(hou, "ui", None)
        if not self.material_model:
            if ui is not None:
                ui.displayMessage(
                    "Please set a library first. Use the %s panel - "
                    "Library/Open Dialog." % branding.APP_NAME
                )
            return
        if node is None:
            sel = hou.selectedNodes()
            if len(sel) != 1:
                if ui is not None:
                    ui.displayMessage(
                        "Select a single node with a color ramp first."
                    )
                return
            node = sel[0]
        parm = helpers.find_color_ramp_parm(node)
        if parm is None:
            if ui is not None:
                ui.displayMessage(
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
        if dialog.category:
            self.gradient_categories_model.check_add_category(    # the shared verb, which brackets its own insert - not switch_model_data(), which belongs to a library switch and only ever runs through switch_all_models()
                dialog.category)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """Any splitter drag records BOTH side panes' widths; the debounced save timer writes them. The construction's law - side panes hold their width - only works if each side pane KNOWS its width."""
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
        """Flip the Notes pane via its toolbar button, so the chip's lit state can never disagree with the pane - the TESTS' door to the pane (eight sites drive it) while the product's own door is the chip (R52 keep-verdict 2026-08-20)."""
        button = getattr(self, "btn_notes", None)
        if button is not None:
            button.setChecked(not button.isChecked())

    def _on_notes_toggled(self, checked: bool) -> None:
        """Show or hide the pane, nothing more: the one-flexible-pane construction (see _build_splitter_and_sidebar) makes the grid absorb the change on its own - no width bookkeeping here."""
        panel = getattr(self, "notes_panel", None)
        if panel is None:
            return
        panel.setVisible(bool(checked))
        self.prefs.show_notes = bool(checked)
        self.prefs.save()
        if checked:
            self._refresh_notes_subject()

    def _sync_notes_button_pixmaps(self) -> None:
        """The chip's four states, in the TOOLBAR's own colours: the glyph wears the icon family's own blue, IDLE_BODY, in ALL FOUR of them, the state being carried by the chip's BACKGROUND, which is what a chip is for."""
        button = getattr(self, "btn_notes", None)
        if button is None:
            return
        button.set_art(
            self._ui_icon_path("icon_comments.svg"),
            lighten_on_hover=False,    # the glyph is the section's blue as drawn, and it does not whiten when on
            recolour={notes_panel.COMMENT_INK:    # the tint map keys on the ART's colour, replacing a literal - so a map left keyed on a colour the drawing no longer contains matches NOTHING and the untinted art shows through in all four states instead
                      ui_helpers.IconMenuButton.IDLE_BODY})

    def _on_note_saved(self, _key: str) -> None:
        """A page was written - repaint the grid so the tile's note badge appears or clears with it."""
        grid.visible_view(self).viewport().update()    # THE VISIBLE view, whichever mode is up: `NotesRole` is answered live from the store with no `dataChanged`, so this repaint is the whole signal

    def _notes_subject(self):
        """What the Comments pane points at, or None. Two things happen here and nothing else: find the live current index, and ask the section context what that index means - so a section that arrives with tiles of its own gets a Comments pane by writing `Section.comment_subject`, not by being remembered here."""
        index = ui_helpers.live_current_index(self.thumblist)    # the LIVE current index, never a stored proxy index - the one selection source every handler uses
        if index is None or not index.isValid():
            return None
        context = self._section()
        if context is None or not context.takes_comments:    # ASK THE CONTEXT, do not test which world this is: the online world answers no because an online record is not a library asset, a fact that belongs on it rather than in a branch here
            return None
        return context.comment_subject(index)

    def _refresh_notes_subject(self, *_args) -> None:
        """Point the Notes pane at the current selection. Cheap when the pane is hidden (returns immediately), called from every selection change and tab switch."""
        panel = getattr(self, "notes_panel", None)
        if panel is None or panel.isHidden():
            return
        subject = self._notes_subject()
        if subject is None:
            panel.clear_subject()
        else:
            panel.set_subject(subject)

    def _on_folder_progress(self, section: str, done: int, total: int) -> None:
        """The conversion bar, but only while its OWN section is showing and the local world is up: the bar sits ABOVE the grid, so drawing it for a batch whose section you have left shifts every tile of whatever is on screen down and back up again."""
        if self._is_online() or self.current_section != section:    # `current_section` deliberately keeps naming the LOCAL section while the online world is showing (see _is_online), so the section test alone cannot see that the user has left
            return
        self._on_texture_progress(done, total)

    def set_conversion_bar_visible(self, visible: bool) -> None:
        """The ONE door to the conversion bar's visibility - the Section Tab Strip's Cancel chip shows exactly when the bar shows, so both move here or not at all. test_cancel_conversions pins this as the package's only site setting the bar visible or hidden."""
        self.texture_progress.setVisible(visible)
        tabs = getattr(self, "section_tabs", None)    # None during init_ui: the bar is hidden before the strip is built, and _build_section_tabs re-applies the bar's state
        if tabs is not None:
            tabs.set_cancel_visible(visible)

    def _on_cancel_conversions(self) -> None:
        """The Cancel chip's verb: stop the File batch. The model owns the pair and its order (file_library.cancel_conversions)."""
        model = self.file_files_model
        if model is not None:
            model.cancel_conversions()

    def _on_texture_progress(self, done: int, total: int) -> None:
        """Shows/updates the thin progress bar above the thumbnail grid while texture thumbnails are generating for the selected folder. Hidden when there's nothing to do (fully cached / empty folder) or once generation completes."""
        if total <= 0 or done >= total:
            self.set_conversion_bar_visible(False)
            return
        self.set_conversion_bar_visible(True)
        self.texture_progress.set_progress(done, total)

    def _on_online_preview_progress(self, done: int, total: int) -> None:
        """Same bar, for the online preview pool - but only while the online browser is actually showing. Previews load lazily, so a worker finishing after you've switched away must not flash the bar over another section."""
        if not self._is_online():
            return
        if getattr(self, "_online_download_active", False):
            return  # a download import owns the bar right now
        self._on_texture_progress(done, total)

    def _active_asset_stack(self):
        """(model, proxy, selection model, category model) of whichever curated-library section is showing (Materials / Cop / Code), or None for a folder/gradient section or before setup. The section object owns this - see panel/sections.py AssetSection.stack."""
        section = self._section()
        return section.stack() if section is not None else None

    def filter_thumb_view(self) -> None:
        """Search box changed - the active context applies it."""
        section = self._section()
        if section is not None:
            section.filter_text(self.line_filter.text())    # online browsing searches the SOURCE's API rather than a local model, the whole catalogue never being resident - that is `OnlineContext.filter_text`, reached through this one path like any other section's

    def filter_favs(self) -> None:
        """Favourites star toggled - the active context applies it: a stale checked state cannot filter the material proxy while the online grid shows, the star being disabled there and `OnlineContext.filter_favorites` a no-op by declaration."""
        section = self._section()
        if section is not None:
            section.filter_favorites(self.cb_favsonly.isChecked())

    def build_filter_menu(self) -> None:
        """Fill the Filter menu with the ACTIVE section's entries - one menu and one button serve every tab, so the section says what it offers (sections.py ▸ filter_entries) and what an entry MEANS (apply_filter); this never looks inside a value. Runs on every section change, and again whenever Preferences may have changed what is on offer."""
        section = self._section()
        entries = tuple(section.filter_entries()) if section is not None else ()
        self.menu_filter.clear()
        self.filter_action_group = QtGui.QActionGroup(self.menu_filter)    # a QActionGroup owns its actions, so a fresh group with the fresh menu is what keeps a stale action from staying checked and answering for a section that is no longer showing
        self.filter_action_group.setExclusive(True)
        self.filter_actions = {}
        self.filter_values = {}
        button = getattr(self, "btn_filter", None)
        if button is not None:
            if (section is not None
                    and not getattr(section, "takes_filter_menu", True)):
                button.setVisible(True)    # offered-but-off is the toolbar table's business, and it DISABLES the button (half opacity, like Favourites and Comments beside it) rather than hiding it - one owner for the control
            else:
                button.setVisible(bool(entries))    # no entries, no menu: a button that opens an empty popup is worse than no button (nothing shipped hits this - all five sections filter - but a new section gets it free)
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
            entries[0][0]]    # a remembered choice that is no longer offered falls back to entries[0], the everything-entry (sections.py puts it first), so a renderer switched off in Preferences needs no case of its own
        act.setChecked(True)
        self.filter_action_group.triggered.connect(self.filter_menu_changed)
        self.apply_section_filter()

    def filter_menu_changed(self, action) -> None:
        """An entry was picked: apply it and remember it for this tab."""
        self.apply_section_filter()
        self.prefs.set_section_filter(self.current_section, action.text())
        self.prefs.save()

    def apply_section_filter(self) -> None:
        """Push the menu's checked entry into the active section - separate from filter_menu_changed because the same push has to happen with nobody clicking anything: entering a section, rebuilding the menu, or opening the panel."""
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
        """Re-evaluate empty-category hiding and counts after anything that changed which materials/COPs exist, what they belong to, or which renderer filter is active. For the flows that do NOT emit category_model.layoutChanged themselves (deletes, overwrite, renderer switch); the ones that do refilter automatically."""
        for cats_model in (
            getattr(self, "category_model", None),
            getattr(self, "cop_category_model", None),
            getattr(self, "code_category_model", None),
            getattr(self, "gradient_categories_model", None),
        ):
            if cats_model is not None:
                cats_model.drop_count_cache()
        for proxy in self.sidebar_proxies():
            proxy.invalidateFilter()
        if self.cat_list is not None:
            self.cat_list.viewport().update()

    SIDEBAR_PROXY_ATTRS = {    # the sidebar proxy each asset section's categories are shown through, named ONCE: they were enumerated correctly in setup() and _refresh_sidebar_categories, and INCOMPLETELY in the Preferences push (Code missing) and the filter-to-sidebar path (only Material had one at all)
        "material": "category_sorted_model",
        "cop": "cop_category_sorted_model",
        "code": "code_category_sorted_model",
        "gradient": "gradient_category_sorted_model",    # Colors is on the shared proxy too, unsorted like the rest; nothing ever hides here because no renderer filter is pushed
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
        """If the filter just hid the sidebar category the user was standing in, fall back to All and refilter the grid - the sidebar must never sit with an empty/hidden selection. Takes the section KEY because all three asset sections that push a renderer filter run it, through the shared AssetSection.apply_filter."""
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
            return    # the selected category survived the refilter - proxy selections track items, not row numbers
        self._stand_on_all_category()

    def _stand_on_all_category(self) -> None:
        """Point the sidebar at All and refilter - one owner for the row walk, shared by the hidden-category fallback above and the empty state's Show All button."""
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

    def clear_favourites_filter(self) -> None:
        """The favourites blank's Show All button: uncheck the star chip and its own `toggled` handler carries the change to the active context - `toggled` fires on a programmatic setChecked, unlike the filter box's `textEdited` one verb up."""
        chip = getattr(self, "cb_favsonly", None)
        if chip is not None:
            chip.setChecked(False)

    def clear_filter_box(self) -> None:
        """The empty state's Clear Search button."""
        box = getattr(self, "line_filter", None)
        if box is None or not box.text():
            return
        box.clear()
        self.filter_thumb_view()    # BY HAND and not redundant: the box is wired on `textEdited`, which Qt does not emit for a programmatic change (Qt's own clear button emits it explicitly for the same reason)

    def user_update_asset(self) -> None:
        """User modifies an assete in the detailview"""
        if not self.material_model or not self.category_model:
            return
        indexes = grid_columns.selected_rows(self.material_selection_model)
        single = len(indexes) == 1    # about/license are per-material provenance, so a multi-selection passes None for both (set_assetdata reads None as leave-alone) rather than stamping one material's credits over everyone's
        about = self.text_about.toPlainText() if single else None
        license_ = self.line_license.text() if single else None
        name = self.line_name.text()
        tags = self.line_tags.text()
        cats = self.cat_combo.currentText()
        state = self.box_fav.checkState()    # THE TRI-STATE, READ AS THREE: `isChecked()` is True for PartiallyChecked, the state update_details_view sets when the selected rows disagree, so a mixed selection must pass fav=None and set_assetdata reads that as leave-alone
        fav = (None if state == QtCore.Qt.CheckState.PartiallyChecked
               else state == QtCore.Qt.CheckState.Checked)
        self.category_model.check_add_category(cats)    # OUTSIDE the relayout wrapper: this announces itself with begin/endInsertRows and pairing the two segfaults H21 (research.md, measured 2026-08-04). Hoisted out of the loop with the other widget reads, which are the same on every pass
        with ui_helpers.relayout(self.material_model):
            for index in indexes:
                idx = self.material_model.index(
                    self.material_sorted_model.mapToSource(index).row(), 0
                )
                self.material_model.set_assetdata(
                    idx, name, cats, tags, fav, about=about,
                    license=license_, save=False    # one index write after the loop, not one per selected row
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
        cats_clean = [str(c).strip() for c in sel_cats if c and str(c).strip()]
        mixed = len(set(cats_clean)) > 1 or (    # a MIXED selection must SAY so, through the MULTIPLE_VALUES sentinel that name and tags use too and set_assetdata reads as leave-alone; otherwise pressing Update refiles every selected asset into the first one's category, with no undo
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
                self.cat_combo.setCurrentIndex(-1)    # no stale text: the PREVIOUS asset's category left showing is how a single asset gets silently refiled

        if sel_tags:
            msg = ", ".join(dict.fromkeys(filter(None, sel_tags[0])))    # dict.fromkeys dedupes and KEEPS order, where a plain set() reshuffles the displayed tags
            if len(sel_tags) > 1:
                for elem in sel_tags:
                    if elem != sel_tags[0]:
                        msg = MULTIPLE_VALUES
            self.line_tags.setText(msg)
        else:
            self.line_tags.setText("")

        if len(indexes) == 1:    # provenance is per-material: shown for a single selection and blanked for many, so nothing reads as shared that isn't, and user_update_asset leaves it alone
            src_row = self.material_sorted_model.mapToSource(indexes[0]).row()
            asset = self.material_model.assets[src_row]
            self.line_license.setText(asset.license)
            self.text_about.setPlainText(asset.about)
        else:
            self.line_license.setText("")
            self.text_about.setPlainText("")

    def update_selected_cat(self) -> None:
        """Update thumb view on change of category (Materials) or browse the selected folder's images (Textures)."""
        indexes = self.cat_list.selectedIndexes()
        if not indexes:    # a ctrl-click DEselecting the current row is re-selected in place, in every world including online: Qt has no "single selection but never empty" mode, and the active category never changed, so nothing else runs
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

    def grid_update_preview(self, indexes) -> None:
        """Re-render the grid selection's thumbnails - one entry point for every section's menu. No layout-change pair is needed: the models emit their own dataChanged and the proxy re-tests on it (grid_proxy.py). No "updated" dialog either - the fresh thumbnail on screen is the confirmation."""
        context = self._section()
        if context is None:
            return
        context.update_preview(list(indexes))

    def grid_delete(self, indexes) -> None:
        """Delete the grid selection - one entry point for every section's menu: it counts the DISTINCT source rows and asks, while the SENTENCE (`Section.delete_prompt`) and the removal (`delete_rows`) are both the context's, because what a row IS differs. A cancelled dialog leaves everything alone, and so does a section whose `deletes_rows` is False - File's rows are files on disk."""
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
        name = sources[0].data(QtCore.Qt.ItemDataRole.DisplayRole) or ""    # the first row's NAME rides along for the one section whose approved wording quotes it; the others ignore it
        ui = getattr(hou, "ui", None)
        if ui is None or ui.displayMessage(
            context.delete_prompt(len(sources), name),
            buttons=("Delete", "Cancel"),
            default_choice=1, close_choice=1,
        ) != 0:
            return
        context.delete_rows(sources)

    def generate_random_material(self) -> None:
        """The Generator Engine's first output: one random plausible material, built INTO THE SCENE where the user is working - the current LOP material library (or one created per the drop placement law) when the context is LOP, else /mat. A generated material is a scene node, not a library entry: keeping one is a deliberate `Save to <app>`, exactly like any other material the user builds by hand."""
        builder = None
        destination = None
        ui = getattr(hou, "ui", None)
        with hou.undos.group("Amaze Generate Material"):    # the whole gesture is ONE undo step, staging AND the destination resolution that may itself create a material library: a move whose source parent was destroyed outside the group has nothing coherent to undo to, and a library created outside it survives the undo as an orphan
            destination = nodes.karma_destination(self.prefs)
            if destination is None:
                if ui is not None:
                    ui.displayMessage(
                        "Amaze: no place to create the material - open a "
                        "LOP or /mat network first."
                    )
                return
            staging = hou.node("/obj").createNode("matnet")    # built in /obj staging and moved in ONE step, because structure changes inside a live material library retranslate the whole thing (wiki)
            try:
                builder, spec = generator.generate_random_material(staging)
                if builder is None:
                    if ui is not None:
                        ui.displayMessage(
                            "Generation failed - see the debug log."
                        )
                    return
                moved = hou.moveNodesTo((builder,), destination)
                if not moved:
                    builder = None
                    debug.event("generate", "move failed",
                                destination=destination.path())
                    if ui is not None:
                        ui.displayMessage(
                            "Amaze: the generated material could not be "
                            "moved into %s." % destination.path()
                        )
                    return
                builder = moved[0]
                helpers.auto_place(builder)
                registered = True
                if destination.type().name() == "materiallibrary":    # registered the way an import is: in a library whose wildcard was narrowed or disabled the material would otherwise sit there as a node that renders nowhere
                    registered = nodes.register_in_materiallibrary(
                        destination, builder
                    )
                builder.setCurrent(True, True)    # fronted like any hand-created node: a menu action IS the user asking for it, unlike a drop, where keep_editor_focus applies
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
                if not registered and ui is not None:
                    ui.displayMessage(
                        '"%s" was created in %s but no material entry '
                        "covers it - check the library node's material "
                        "list." % (builder.name(), destination.path())
                    )
            except hou.Error as exc:
                builder = None
                debug.event("generate", "failed", error=str(exc))
                if ui is not None:
                    ui.displayMessage(
                        "Amaze: generation failed (%s)." % exc
                    )
            finally:
                staging.destroy()
        if builder is not None and ui is not None:
            ui.setStatusMessage(
                "Amaze: generated %s in %s"
                % (builder.name(), destination.path())
            )

    def save_asset(self) -> None:
        """Saves the selected nodes (Network Editor) to the Library, with standard file-save semantics at ANY selection size: nodes matching an EXISTING library material - by the id stamp a previous save/import left on them, or by a unique name match - raise one save-over / Save New / Cancel choice for the whole selection, with the save-over button offered only where the library allows it; anything else goes straight to the normal new-material dialog."""
        ui = getattr(hou, "ui", None)
        sel = hou.selectedNodes()
        debug.event("save", "save_asset entry", selected=len(sel))
        if not sel:
            if ui is not None:
                ui.displayMessage("No material selected")
            return
        if not self.material_model:
            if ui is not None:
                ui.displayMessage(
                    "Please set a library first. Use the %s panel - "
                    "Library/Open Dialog." % branding.APP_NAME
                )
            return
        existing = []    # which of the dropped nodes already exist, so the choice is offered ONCE for the whole drop rather than per node or not at all
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
            may_overwrite = library_policy.allow_overwrite(
                self.material_model.preferences.dir)    # the LIBRARY decides, not this machine's preferences - a switch only one machine can see protects nobody. The stored key stays allow_overwrite (keys are identifiers, never names) while the UI calls it Material Versions, because that is what saying yes DOES: a save-over archives a version first and destroys nothing
            if may_overwrite:
                buttons = ("Save Version", "Save New", "Cancel")
                cancel_at, overwrite_at = 2, 0
            else:
                message += (
                    "\n\nMaterial Versions is off for this library, "
                    "so the existing material stays as it is. Saving "
                    "will add a new material."
                )
                buttons = ("Save New", "Cancel")    # with Material Versions off the save-over button is not offered at all: an option that always fails is worse than an option that is not there
                cancel_at, overwrite_at = 1, -1
            choice = ui.displayMessage(
                message,
                buttons=buttons,
                default_choice=0,
                close_choice=cancel_at,
                title="Save to " + branding.APP_NAME,
            ) if ui is not None else cancel_at    # no screen to ask, so the answer is the close_choice - Cancel
            if choice == cancel_at:
                return
            if choice == overwrite_at:
                for row, node in existing:    # an overwrite neither inserts nor removes rows, so the collected row indexes stay valid through the loop
                    self._update_existing_asset(row, node)
                    QtWidgets.QApplication.processEvents()
                if new_nodes:
                    self.get_material_info_user(new_nodes)
                return
        self.get_material_info_user(sel)    # Save as New falls through to here with the FULL selection

    def _find_existing_asset_row(self, node: hou.Node) -> int:
        """Source-model row of the library material this node came from, or -1. The id stamp (setUserData on save/import) is authoritative; a UNIQUE name match is the fallback for nodes carrying no stamp."""
        mat_id = node.userData("assetlib_id")
        if mat_id:
            row = self.material_model.find_asset_row_by_id(mat_id)
            if row >= 0:
                return row
        return self.material_model.find_asset_row_by_name(node.name())

    def _update_existing_asset(self, row: int, node: hou.Node) -> None:
        """Overwrite an existing library entry's content from the scene node: same entry/metadata, new node files + thumbnail + type."""
        with ui_helpers.relayout(self.material_model):
            renderer = self.material_model.update_asset_content(row, node)
        self._refresh_sidebar_categories()    # an overwrite can re-detect a different renderer, so counts and renderer-aware hiding may shift
        if not renderer:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(
                    "Update failed - the library material was not changed."
                )
            return
        self.enable_renderer_on_add(renderer)
        self.prefs.save()
        self.update_renderer_toggles()

    def get_material_info_user(self, sel: list[hou.Node]) -> None:
        if not self.material_model or not self.category_model:
            return
        """Query user for input upon material-save"""
        self.save_dialog_category_model = QtCore.QSortFilterProxyModel()
        self.save_dialog_category_model.setSourceModel(self.category_model)    # the SOURCE model, never the sidebar proxy: the sidebar hides empty categories and the save dialog must offer every one of them (this proxy does its own sorting and All-filtering regardless)
        usd_filter = "^(?!All).*$"
        self.save_dialog_category_model.setFilterRegularExpression(usd_filter)
        self.save_dialog_category_model.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)  # type: ignore
        self.save_dialog_category_model.sort(0)

        cats = []
        for elem in range(self.save_dialog_category_model.rowCount()):
            idx = self.save_dialog_category_model.index(elem, 0)
            cats.append(self.save_dialog_category_model.data(idx))

        current_cat = self._selected_category_name()    # defaults the dialog to the category selected in the panel, skipping the "All" pseudo-category and empty selections - ONE helper for all three save dialogs, and it falls back to live_current_index, the state _restore_section_state leaves behind by calling setCurrentIndex without a select

        dialog = save_dialog.SaveDialog(cats, current_cat)
        r = dialog.exec_()

        debug.event(
            "save", "save dialog closed",
            accepted=bool(r and not dialog.canceled),
            category=dialog.categories, preselected=current_cat,
        )
        if dialog.canceled or not r:
            return

        if dialog.categories:
            self.category_model.check_add_category(dialog.categories)
        if dialog.tags:
            self.material_model.check_add_tags(dialog.tags)

        renderers = []
        failures = []
        for asset in sel:
            try:    # a read-only or unreachable library directory raises out of the save chain (IsADirectoryError on the .interface, verified), and debug.guarded LOGS AND RE-RAISES rather than absorbing it, so the per-material failure report needs this catch of its own
                renderer = self.material_model.add_asset(
                    asset, dialog.categories, dialog.tags, dialog.fav
                )
            except Exception as exc:                    # noqa: BLE001
                debug.exception("save_asset", exc, node=asset.path())
                failures.append('"%s": %s' % (asset.name(), exc))
                continue
            if not renderer:    # add_asset answers "" for a refused save, and two of the three causes have already shown their own dialog naming the reason, so this line only has to say WHICH material of the batch never made it
                failures.append('"%s": the save did not complete'
                                % asset.name())
                continue
            renderers.append(renderer)
            QtWidgets.QApplication.processEvents()    # lets the fresh tile PAINT before the next material's blocking render starts: with add_asset emitting real row-insert signals, this flush is what makes a long multi-save appear one material at a time

        ui = getattr(hou, "ui", None)
        if failures and ui is not None:
            ui.displayMessage(
                "Some materials could not be saved:\n\n"
                + "\n".join(failures)
            )
        for renderer in renderers:
            self.enable_renderer_on_add(renderer)
        self.prefs.save()
        self.update_renderer_toggles()
        self._refresh_sidebar_categories()

    def enable_renderer_on_add(self, renderer: str) -> None:
        """Switch a renderer's Filter entry on when its first material is saved, so the thing the user just saved is visible in the tab they saved it from. Walks the ONE renderer table (sections.renderer_prefs) rather than repeating it as another if/elif chain."""
        if material.is_karma_renderer(renderer):    # Karma is asked by name and FIRST: is_karma_renderer covers the legacy stored labels (MaterialX, MtlX) that no substring match against the table would
            self.prefs.renderer_matx_enabled = True
        else:
            for label, attr in sections.renderer_prefs():
                if label != "Karma" and label in renderer:
                    setattr(self.prefs, attr, True)
                    break
        self.prefs.save()

    def import_asset(self, target: str = "auto"):
        """Import the selected materials. target: "auto" lets MatLib decide from the active network editor (double-click); "mat" forces /mat; "lop" forces a LOP materiallibrary. Materials that cannot live in the requested context are skipped and collected into a single summary dialog."""
        if not self.material_model or not self.category_model:
            return
        failures = []
        with hou.undos.group("Amaze Import Materials"):    # ONE undo entry for the whole import, as at every other import entry point: ungrouped, the destination container, the staging matnet, the builder, the move and the materiallibrary entry are separate entries, so one Ctrl+Z leaves a stray matnet and a half-imported builder behind
            self._import_selected_materials(target, failures)
        ui = getattr(hou, "ui", None)
        if failures and ui is not None:
            ui.displayMessage(
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
            except Exception as e:    # an unexpected failure (corrupt .interface file, unusual node structure) joins the normal per-material failure report instead of surfacing as a raw traceback, so the rest of the selection still gets its chance
                try:
                    name = self.material_model.assets[source_index.row()].name
                except Exception:
                    name = "material"
                failures.append(f'"{name}" failed to import: {e}')
                continue
            if not ok and reason:
                failures.append(reason)

    def import_asset_auto(self, index: QtCore.QModelIndex | None = None):
        """Double-click handler, shared across sections since thumblist is reused for all of them, and answered by the section itself (Section.double_click): Materials import context-aware, with the index never reaching the "auto"/"mat"/"lop" target argument import_asset() expects a string for; Textures push the double-clicked file's path onto a selected texture node's image parm, and there the index IS what says which file was clicked."""
        if index is not None and index.isValid():
            index = index.siblingAtColumn(0)    # THE ROW, not the clicked cell: in list mode the double-click lands on a visible column >= 1, where the models answer roles with None (research.md > Row selection over a table view)
        section = self._section()
        if section is not None:
            section.double_click(index)

    CANNOT_LOAD_HERE = "This content can not be loaded into this context."    # the ONE double-click refusal, everywhere; an exact copy lives in the UI text register. The drag door never dialogs - it has the miss indicator

    def _cannot_load_here(self) -> None:
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(self.CANNOT_LOAD_HERE)  # type: ignore

    def _network_under_release(self) -> hou.Node | None:
        """The network a no-node release happened INSIDE - the editor under the cursor answers with its pwd. None off any editor."""
        return self._drop_context_under_cursor(lambda _node: False)

    def _release_position_in(self, net):
        """The release position, ONLY when the editor under the cursor is showing `net` itself - a cross-space release answers None and the carrier auto-places, exactly like the import seam's gate."""
        pane_tab = dragengine.pane_tab_under_cursor()
        if pane_tab is None or net is None:
            debug.event("interact", "no drop point - no editor under "
                        "the cursor", net=net.path() if net else None)
            return None
        try:
            if pane_tab.type() != hou.paneTabType.NetworkEditor:
                return None
            if pane_tab.pwd() != net:    # the cross-space case: a release over a container resolves INSIDE it while the cursor's coordinates stay in the OUTER editor's plane, and stage coordinates applied inside a material library put the node anywhere but the cursor
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
        """The double-click doors' idea of THE SELECTION: only nodes the user can SEE - children of a visible editor's network. Houdini tags imported nodes selected (research.md - moveNodesTo), so the global hou.selectedNodes() carries invisible leftovers of the previous import. Menu verbs keep the global read: their sentences name the selection explicitly."""
        networks = self._view_create_networks()
        every = hou.selectedNodes()
        sel = [node for node in every if node.parent() in networks]
        debug.event("interact", "click door selection",
                    visible=len(sel), total=len(every),
                    networks=len(networks))
        return sel

    def _view_create_networks(self) -> list:
        """The click doors' aim when nothing is selected: every visible network editor's pwd, current tabs first. The caller creates in the FIRST network that can hold the carrier - one resolver for every door, so a payload finds the network that supports it instead of failing on whichever editor happens to be listed first."""
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
        """Create `type_name` inside `dest` when that network can hold one - the type existing in the network's child category IS the capability test - or answer None. The carrier half of the matrix's creation rule; the caller loads the payload and owns the undo group. A position places the node where the release happened; without one it auto-places."""
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
        except hou.Error as refusal:    # HOUDINI IS THE AUTHORITY on whether a network can take a node and it answers in one sentence - a locked digital asset says `Cannot create a node inside a locked asset`, and only the nodes an asset MARKS editable are exempt (a SOP Create's `create` subnet is, its sopnet is not) - so the reason is LOGGED, never re-derived here, the walk moves on to a network that can take it, and unlocking the user's asset (allowEditingOfContents) is never ours to do
            debug.event("interact", "the network refused the carrier",
                        carrier=type_name, dest=dest.path(),
                        error=str(refusal))
            return None
        if name:
            try:
                node.setName(name, unique_name=True)
            except hou.OperationFailed:
                pass
        if position is None:    # a given position IS the placement, and auto-place is the no-position fallback only: moveToGoodPosition may shove unconnected siblings aside to make room, which reads on screen as every other node moving away from the drop
            helpers.auto_place(node)
        else:
            helpers.place_nodes([node], position)
        debug.event("interact", "carrier created", carrier=type_name,
                    dest=dest.path())
        return node

    def import_asset_to_mat(self):
        """Explicitly import the selected materials into /mat."""
        self.import_asset("mat")

    def import_asset_to_lop(self):
        """Explicitly import the selected materials into a LOP materiallibrary."""
        self.import_asset("lop")

    def slide(self) -> None:
        """Set IconSize via Slider - writes to the ACTIVE view mode's own persisted size (grid and list are independent)."""
        if not self.material_model or not self.category_model:
            return
        if self.prefs.view_mode == "list":
            return    # list has one size and a greyed slider, so a stray value change must not become a stored size
        value = self.click_slider.value()
        self.prefs.thumbsize = value
        self._thumbsize_save_timer.start()    # persisted debounced (500ms after the last slider tick): writing settings.json on every pixel of a drag would thrash a file that lives in the cloud-synced install folder
        self.material_model.thumbsize = value

        self.apply_view_mode()    # sizing for the active mode - grid grows icons, list grows rows
        self.material_model.set_custom_iconsize(QtCore.QSize(value, value))    # and the images themselves

    def box_fav_clicktoggle(self):
        if self.box_fav.checkState() == QtCore.Qt.CheckState.PartiallyChecked:
            self.box_fav.nextCheckState()
