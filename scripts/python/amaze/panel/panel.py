"""The Amaze panel: the Python panel widget and its views onto the models."""

import time

_BODY_T0 = time.perf_counter()    #: when THIS module body began - stamped BEFORE the import block and reload chain, which are what `module_body_ms` exists to measure; NOT reload-survival state, every open runs it again

import os
import importlib
import contextlib
import sys

from PySide6 import QtWidgets, QtGui, QtCore
import hou

import amaze
from amaze.actions import library as library_actions
from amaze.core import grid_columns, grid_engine
from amaze.panel import (dragdrop_widgets, empty_state, grid, notes_panel,
                         sections, sidebar)
from amaze.core import debug, keyed_store, locations
from amaze.core import versions
from amaze.core import notes
from amaze.core import captures, scene_captures
from amaze.core import (
    folders,
    material,
    texstore,
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
    matx_sources,
    model_registry,
)
from amaze import amazetheme
from amaze import branding
from amaze import messages
from amaze import tooltips
from amaze.prefs import prefs
from amaze.helpers import bytecode, hostos, theme, ui_helpers
from amaze.utils import rc_calls
from amaze.core import database, renderers, tile_icons, users
from amaze.render import husk_job, nodes

_DEV_RELOAD = bool(os.environ.get("AMAZE_DEV_RELOAD"))    # the reload chain below is OFF by default: it re-runs on every panel open to serve a reopen-to-refresh the live-test loop forbids anyway ▸r/module-reload


def _reload(module):
    """importlib.reload, unless the dev switch is off."""
    if _DEV_RELOAD:
        importlib.reload(module)


def _reload_loaded(name):
    """`_reload` for a module imported where it is used, so only once something has loaded it."""
    if _DEV_RELOAD and name in sys.modules:
        importlib.reload(sys.modules[name])


_reload(keyed_store)    # FIRST: eleven modules read their stores through it, so a stale engine keeps old tables while every caller gets new code; a re-register keeps existing bindings, so binder modules outside this chain stay whole
_reload(locations)      # right after the engine it binds two stores into - and the switch door calls locations.forget()
_reload(hostos)    # before library: the models import the shared thumbnail engine
_reload(bytecode)
_reload(debug)
_reload_loaded("amaze.core.dragengine")
_reload_loaded("amaze.core.lop_assign")
_reload(thumbnails)
_reload(database)
_reload_loaded("amaze.core.library_policy")    # before library, which gates overwriting on it
_reload(versions)
_reload(notes)
_reload(users)    # before versions and the dialogs showing a user: both resolve a UID through it, so a stale one answers from the previous library's people
_reload(renderers)
_reload(material)
_reload(texstore)    # before nodes and library, which adopt and resolve through it
if _DEV_RELOAD and "amaze.preview" in sys.modules:
    sys.modules["amaze.preview"].reload_engine()    # the package reloads itself ▸r/package-reload
_reload_loaded("amaze.render.material_converter")
_reload(nodes)
_reload(husk_job)    # before thumbs, which submits to its queue
_reload_loaded("amaze.render.thumbs")
_reload(tile_icons)    # before gradient_library and the Node Info dialog, which read its facts
_reload(grid_columns)    # BEFORE the engine, which reads its column order
_reload(grid_engine)    # BEFORE library and its siblings, which mix it in
_reload(captures)    # before library, file_library and scene_captures, which read it
_reload(library)
_reload(category)
_reload_loaded("amaze.core.repair")
_reload(folders)
_reload(prefs)
_reload(library_actions)    # after captures, database and prefs, which its steps call
_reload(messages)      # the wording every dialog shows; reloaded like `branding`, so a reworded message reaches an already-open Houdini ▸p/messages-need-one-home
_reload(tooltips)      # the same for every hover text, and before the dialogs, the delegates and the models that read its constants
_reload(amazetheme)    # before theme and ui_helpers: their class bodies read the DESIGN's values at definition time, so a stale one draws yesterday's design ▸p/one-design-document
_reload(theme)    # before ui_helpers, whose class bodies read theme colours
_reload(branding)    # FIRST of the ones below: everything reads its constants, and a stale branding produced 38 unhandled AttributeErrors live when APP_VERSION was added
_reload(ui_helpers)
_reload(rc_calls)    # after debug and messages: it hands the log the dialogs they word
_reload_loaded("amaze.helpers.helpers")
_reload(texture_library)
_reload(gradient_library)
_reload(cop_library)    # after library/category, so its subclasses bind to the freshly reloaded material classes
_reload(geo_library)    # after texture_library, whose ThumbnailCache/proxy it reuses
_reload(scene_captures)
_reload(file_library)    # after texture/geo/hip: it composes all three engines
_reload_loaded("amaze.helpers.vex_syntax")    # before code_library/code_dialog, which consume its palette and tokenizer
_reload(code_library)    # after library/category: it subclasses the material machinery
_reload(model_registry)    # LAST of the models: it names all ten classes, so a stale one hands the next panel the previous build's classes

_reload_loaded("amaze.dialogs.base_dialog")    # FIRST of the dialogs: user_dialog binds its AssetDialog class
_reload_loaded("amaze.dialogs.prefs_dialog")
_reload_loaded("amaze.dialogs.save_dialog")
_reload_loaded("amaze.dialogs.icon_dialog")
_reload_loaded("amaze.dialogs.gradient_dialog")
_reload_loaded("amaze.dialogs.code_dialog")
_reload_loaded("amaze.dialogs.user_dialog")
_reload(dragdrop_widgets)
_reload(grid)    # BEFORE sections, which imports it: every section's menu table reads the Grid area's builder and ListColumns
_reload(sidebar)
_reload(sections)
_reload(empty_state)    # after grid AND sections: it imports the first and reads the second's EMPTY declarations
_reload(notes_panel)
_reload(multifilterproxy_model)
_reload(matx_sources)    # the online stack, which was never in this chain at all
_reload_loaded("amaze.core.matx_translate")
_reload_loaded("amaze.core.matx_icon")
_reload_loaded("amaze.core.matx_import")
_reload(matx_library)
_reload_loaded("amaze.core.gallery_import")    # reachable from the Online menu
_reload_loaded("amaze.core.packages")
_reload_loaded("amaze.render.generator")



from amaze.panel import delegates            # noqa: E402 - re-exported below because every section constructs them by these names

_reload(delegates)
AssetItemDelegate = delegates.AssetItemDelegate

SidebarItemDelegate = delegates.SidebarItemDelegate

FILTER_DEBOUNCE_MS = 180    #: the search box's pause before it filters - a pass measures ~24ms, so a keystroke each is felt, and a pause between words is not ▸p/filter-pass-cost

MIN_PANEL_WIDTH = 500    #: design px through `theme.ui_px` at use. ONE constant, never computed: a floor that moves under the user is worse than a narrow grid, and THE GRID PANE CARRIES NO MINIMUM because a child minimum propagates into the window's own ▸r/qt-windows-macos




class AmazePanel(QtWidgets.QWidget):
    """The panel widget: shell, sections and the views onto their models."""

    def __init__(self) -> None:
        super(AmazePanel, self).__init__()
        self._construct_t0 = time.perf_counter()    # stamped before any work, so "panel ready" can report the two spans separately: everything the module body did before this point, and the construction itself
        self._first_show_logged = False
        rc_calls.start()    # before the log writes anything, so its header knows the Houdini
        debug.install()    # arm the always-on crash recorder before anything else, so a failure during construction lands in the log even with Debug Mode off (see core/debug.py)
        try:
            self._build()
        except Exception as exc:
            debug.exception("panel construction", exc)
            raise

    def _build(self) -> None:
        self.prefs = prefs.Prefs()

        loaded = self.prefs.load()    # False means only that there was nothing usable on disk - no settings.json, an unreadable one, or a library directory that is gone - and the preferences object is populated either way, so the debug engine, the settings snapshot (the designated restore source) and the cache override must all run on BOTH paths: the session right after a settings loss is exactly the one whose record matters most
        debug.configure(self.prefs.debug_mode)    # configured before anything else runs: a crash during setup() is precisely the case a debug log has to survive
        debug.prefs_snapshot(self.prefs)
        hostos.set_cache_override(self.prefs.cache_dir)    # custom thumbnail-cache location, set before any cache is touched - everything downstream resolves hostos.cache_root()
        if loaded:
            self.init_ui()
            if (library_actions.index_unreadable(self.prefs.dir)
                    or library_actions.list_not_arrived(self.prefs.dir)):
                self._defer_open_library()
                opened = False    # the pane opens without a library; what it says follows
            else:
                opened = self.open_library()
            if not opened:
                self._open_libraryless()    # still a finished construction, so it says ready
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
        self.cop_model = None    # a right-click save asks every model before one is built
        self.cop_category_model = None
        self.code_model = None
        self.code_category_model = None
        self.file_files_model = None    # the File models too: show_prefs hands file_files_model to the Preferences dialog (which takes None), and Preferences is the ONLY way to configure a library, so an unset attribute makes the gear an AttributeError on the machine that needs it most - the first run
        self.file_folders_model = None
        self.matx_online_model = None    # setup() builds the online world; its door refuses without it
        self._sync_online_chip()

    def _defer_open_library(self) -> None:
        """Open the library once Qt is idle, where its question draws. ▸r/modal-in-pane-build"""
        timer = self._open_library_timer = QtCore.QTimer(self)    # owned, so it dies with the panel
        timer.setSingleShot(True)
        timer.setInterval(0)
        timer.timeout.connect(self.open_library)
        timer.start()

    def _repaired(self, folder: str) -> bool:
        """Ask about the list in `folder` that will not read; True once Repair put a readable one back."""
        from amaze.core import repair
        switching = getattr(self, "material_model", None) is not None    # a library is open
        debug.event("session", "library index unreadable", dir=folder, switching=switching)
        ui = getattr(hou, "ui", None)
        if ui is None:
            return False
        choice = ui.displayMessage(
            messages.LIBRARY_INDEX_UNREADABLE_SWITCHING if switching
            else messages.LIBRARY_INDEX_UNREADABLE,
            buttons=messages.BUTTONS_REPAIR_OR_CANCEL if switching
            else messages.BUTTONS_REPAIR_OR_OPEN_WITHOUT,
            severity=hou.severityType.Warning,
            default_choice=0, close_choice=1,
            title=messages.TITLE_AMAZE)
        if choice != 0:
            debug.event("session", "index repair declined")
            return False
        ok, how = repair.repair_index(folder, self.prefs.asset_dir)
        if not ok:
            ui.displayMessage(
                messages.REPAIR_COULD_NOT_FIX_THE_LIST_SWITCHING % how if switching
                else messages.REPAIR_COULD_NOT_FIX_THE_LIST % how,
                severity=hou.severityType.Warning,
                title=messages.TITLE_AMAZE)
            return False
        if library_actions.index_unreadable(folder):
            debug.event("session", "index still unreadable after repair", dir=folder)
            ui.displayMessage(
                messages.INDEX_UNREADABLE_AFTER_REPAIR_SWITCHING if switching
                else messages.INDEX_UNREADABLE_AFTER_REPAIR,
                severity=hou.severityType.Warning,
                title=messages.TITLE_AMAZE)
            return False
        ui.setStatusMessage("Amaze: %s." % how)
        debug.event("session", "index repaired", how=how, dir=folder)
        return True

    MENU_ICON_FILES = {    # menu title -> icon asset, each with a baked-in corner triangle as the "opens a menu" hint. The EYE belongs on the Filter menu, which is what you can see, and the 3D box on the View menu, whose items are the library and the material sources. The gear (icon_library.svg) is NOT here: it is a plain ACTION button straight into Preferences, its triangle removed from the SVG, and the Library menu's items live on the Preferences Library tab
        "View": "icon_renderer.svg",
        "Filter": "icon_view.svg",
    }

    def _ui_icon_path(self, filename: str) -> str:
        """An icon in ui/, or "" for no filename (callers degrade). ▸p/adoption"""
        if not filename:
            return ""
        return amaze.package_file("ui", filename)

    def _make_menu_button(self, menu: QtWidgets.QMenu) -> "ui_helpers.IconMenuButton":
        """Opens `menu` from an icon button, standing in for a real QMenuBar item: QMainWindow reserves its menu bar a dock area that cannot share a row with other widgets, so the real menu bar (self.menu) stays alive and owns these QMenu objects but is hidden, and the button pops the same QMenu instance"""
        icon_path = self._ui_icon_path(
            self.MENU_ICON_FILES.get(menu.title(), "")
        )
        name = "btn_menu_" + "".join(c for c in menu.title().lower() if c.isalnum())
        return ui_helpers.IconMenuButton(menu, icon_path, name=name)    # stable: B01 and the snapshots key on it

    def _grid_proxy(self, proxy, model) -> tuple:
        """`proxy` set up over `model` the one way grid proxies are, and its selection model."""
        proxy.setSourceModel(model)
        proxy.setFilterCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        proxy.setDynamicSortFilter(False)    # the base class re-filters ▸r/proxy-invariant
        proxy.layoutChanged.connect(self._follow_sort_arrow)    # another panel may sort the model
        return proxy, QtCore.QItemSelectionModel(proxy, self)

    def _follow_sort_arrow(self, *_args) -> None:
        grid.sync_sort_indicator(self)

    def _sidebar_proxy(self, model):
        """A sidebar proxy over `model`: never sorted, as the stored order is the sidebar's."""
        proxy = category.CategoriesSidebarProxy(self)
        proxy.setSourceModel(model)
        proxy.hide_empty = self.prefs.hide_empty_categories
        return proxy

    def setup(self):
        for attr, model in model_registry.models_for(self.prefs).items():
            setattr(self, attr, model)    # SHARED with every other panel on this library; only the proxies, selections and delegates below are this panel's own
        self._note_models_library()

        self.category_sorted_model = self._sidebar_proxy(self.category_model)
        self.material_sorted_model, self.material_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(self), self.material_model)
        self.thumb_delegate = AssetItemDelegate(
            self.material_model.RendererLabelRole,
            self.thumblist,
            category_role=self.material_model.CategoryRole,
            tag_role=self.material_model.TagRole,
            licence_role=self.material_model.LicenceRole,
            category_color_role=self.material_model.CategoryColorRole,
            active_version_role=self.material_model.ActiveVersionRole,
            date_role=self.material_model.DateRole,
            id_role=self.material_model.IdRole,
            crop_role=self.material_model.CropRole,
            tile_badges=sections.MaterialSection.tile_badges,
            tile_model=library.MaterialLibrary,
            on_badge=self._badge_verb,
        )

        node_roles = dict(
            category_role=self.material_model.CategoryRole,
            tag_role=self.material_model.TagRole,
            licence_role=self.material_model.LicenceRole,
            category_color_role=self.material_model.CategoryColorRole,
            date_role=self.material_model.DateRole,
            id_role=self.material_model.IdRole,
            crop_role=self.material_model.CropRole,
            on_badge=self._badge_verb,
        )
        self.asset_delegate = AssetItemDelegate(    # Node and Code get their OWN delegate, without the version roles. `grid.sync_table_columns` decides a column exists from the active delegate's roles, so borrowing thumb_delegate painted a "Version" column reading "none" on every row, floored at the width of "Version 99". Latent and worse: editorEvent and _sync_versions_hover run against that delegate too, and _open_versions_dialog maps through the MATERIAL proxy and indexes material_model.assets - so a Node or Code asset with a versions ledger would open an unrelated MATERIAL. overview.md §2 and ListColumnHeader.COLUMNS both say Version is materials-only and Open is File-only; this is what delivers it
            self.material_model.RendererLabelRole, self.thumblist,
            tile_badges=sections.CopSection.tile_badges,
            tile_model=cop_library.CopLibrary, **node_roles)
        self.code_delegate = AssetItemDelegate(
            self.material_model.RendererLabelRole, self.thumblist,
            tile_badges=sections.CodeSection.tile_badges,
            tile_model=code_library.CodeLibrary, **node_roles)

        self.file_sorted_model, self.file_selection_model = self._grid_proxy(
            texture_library.TextureFilterProxyModel(self), self.file_files_model)
        self.file_delegate = AssetItemDelegate(
            self.file_files_model.FormatRole,
            self.thumblist,
            category_role=self.file_files_model.FolderRole,
            category_color_role=self.file_files_model.CategoryColorRole,
            crop_role=self.file_files_model.CropRole,
            tile_badges=sections.FileSection.tile_badges,
            tile_model=file_library.FileFiles,
            on_badge=self._badge_verb,
        )
        self._sync_notes_button_pixmaps()
        self.sidebar_delegate.show_counts = self.prefs.sidebar_counts
        thumbnails.engine.set_budget_mb(self.prefs.ram_cache_mb)
        self.file_files_model.progress_changed.connect(
            self._on_file_folder_progress)    # a BOUND method, never a lambda: the model outlives a closed pane tab (it stays wired to the reload-stable thumbnails relay), and a lambda receiver survives the widget's death to drive a deleted progress bar

        self.gradient_category_sorted_model = self._sidebar_proxy(
            self.gradient_categories_model)
        self.gradient_sorted_model, self.gradient_selection_model = self._grid_proxy(
            gradient_library.GradientFilterProxyModel(self), self.gradient_model)
        self.gradient_delegate = AssetItemDelegate(
            self.gradient_model.RendererLabelRole,
            self.thumblist,
            category_role=self.gradient_model.CategoryLabelRole,
            category_color_role=self.gradient_model.CategoryColorRole,
            crop_role=self.gradient_model.CropRole,
            tile_badges=sections.GradientSection.tile_badges,
            tile_model=gradient_library.GradientLibrary,
            on_badge=self._badge_verb,
        )

        self.cop_category_sorted_model = self._sidebar_proxy(self.cop_category_model)
        self.cop_sorted_model, self.cop_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(self), self.cop_model)
        self.code_category_sorted_model = self._sidebar_proxy(self.code_category_model)
        self.code_sorted_model, self.code_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(self), self.code_model)

        for _model in (self.material_model, self.cop_model, self.code_model):    # multi-category was removed, so every asset collapses to its first category; idempotent, so this one-time migration no-ops on every subsequent launch
            try:
                _model.collapse_multicategory()
            except Exception as exc:
                debug.event("session", "category collapse failed",    # event, not note, at all four panel sites: the panel's user-facing channel here is a dialog, and each of these lines is an internal fallback the user cannot act on
                            error=str(exc))

        self.matx_online_model = matx_library.MatxOnlineLibrary(    # the online MaterialX browser is NOT a section but a VIEW MODE over the Materials grid (View > Online Materials); it uses the same role numbers as MaterialLibrary, so the existing delegate and filter proxy serve it unchanged
            preferences=self.prefs
        )
        self.matx_sorted_model, self.matx_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(self), self.matx_online_model)
        self.matx_source_model = matx_library.MatxSidebarModel(
            self.matx_online_model
        )
        self.matx_delegate = AssetItemDelegate(    # the online world gets its own delegate, with only the roles its model has: matx_library exposes seven and none is licence, versions, notes or category colour, so borrowing a local delegate gave the online grid columns that can never carry a value on any row. Same defect shape as Node and Code borrowing the Materials delegate, one world over
            self.matx_online_model.RendererLabelRole,
            self.thumblist,
            category_role=self.matx_online_model.CategoryRole,
            tag_role=self.matx_online_model.TagRole,
            tile_badges=sections.OnlineContext.tile_badges,
            tile_model=matx_library.MatxOnlineLibrary,
        )
        self.matx_online_model.progress_changed.connect(    # preview downloads drive the same thin bar as texture/geo thumbs
            self._on_online_preview_progress
        )
        self.online_mode = False
        self.online_source = None
        self.online_context = sections.OnlineContext(self)    # the online world as a context object with a Section's interface. NOT in `sections` and not in `enabled_sections` - it is a parallel world, not a section - but every area path reaches it through `_section()` like any other

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

        first_key = next(    # start on the first ENABLED section - usually Materials, but a user may have hidden it; the models all exist regardless of which tabs are shown
            (k for k, _ in self.ALL_SECTIONS if k in self.prefs.enabled_sections),
            "material",
        )
        self.current_section = first_key
        self._apply_context(self.sections[first_key], first_key)    # the path a tab click takes
        self.section_tabs.setChecked(first_key, emit=False)
        self.click_slider.setValue(grid.active_thumbsize(self))
        self.slide()
        self.apply_view_state()
        self._sync_online_chip()    # the online world exists from here on

    def open(self) -> None:
        """Open the currently in preferences specified library"""
        if not self.material_model or not self.category_model:
            return
        self.material_model.save()
        self.prefs.load()
        self.open_library()

        debug.event("session", "library reloaded")

    def set_library(self) -> None:
        """User Sets library via Menu Option so we have to reroute"""
        if self.prefs.get_dir_from_user(accept=self._takes_library):
            self.prefs.load()
            self.open_library()

    def _takes_library(self, folder: str) -> bool:
        """A picked folder is taken once its list reads: Repair first, or nothing is written to it."""
        if library_actions.list_not_arrived(folder):
            debug.event("session", "library not taken - its list has not arrived", dir=folder)
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(
                    messages.STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY,
                    severity=hou.severityType.Warning,
                    title=messages.TITLE_AMAZE)
            return False
        return not library_actions.index_unreadable(folder) or self._repaired(folder)

    def open_library(self) -> bool:
        """Every way onto a library, in one order; False when it stays closed."""
        if self._library_too_new():
            return False    # the models stay on the library they serve
        if (library_actions.index_unreadable(self.prefs.dir)
                and not self._repaired(self.prefs.dir)):
            return self._stay_closed()
        library_actions.prepare(self.prefs)
        if not library_actions.index_present(self.prefs.dir):    # prepare could not set one up
            return self._stay_closed()
        if getattr(self, "material_model", None) is None:
            self.setup()    # the libraryless shape has no models to switch
        else:
            self.switch_all_models()
        texstore.publish_env(self.prefs)    # $AMAZELIB names the library the models now serve
        self._update_library()    # before any tile paints
        self._seed_curated_content()    # once per library, marker-guarded
        if not self.prefs.test_mode and self.prefs.note_library_opened(self.prefs.real_dir):
            self.prefs.save()    # the Library list, the most recently opened first
        return True

    def _stay_closed(self) -> bool:
        """False; an open library is kept, and its Library Path and Test Library are put back."""
        if getattr(self, "material_model", None) is not None:
            real, test_mode, test_dir = self._models_pointers
            self.prefs.test_dir = test_dir
            self.prefs.dir = real
            self.prefs.test_mode = test_mode    # last, so the shared settings adopted are that library's
            self.prefs.save()
            debug.event("session", "library kept", dir=self.prefs.dir)
        return False

    def _note_models_library(self) -> None:
        """The library the models now serve, for closing Preferences and for a Cancel."""
        self._models_dir = self.prefs.dir
        self._models_pointers = (self.prefs.real_dir, self.prefs.test_mode, self.prefs.test_dir)

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
        """The models' step of `open_library`: every library-backed model re-pointed at `prefs.dir`."""
        pane = getattr(self, "notes_panel", None)
        if pane is not None:
            pane.clear_subject()    # a pending edit goes to its own library; the switch selects nothing
        locations.forget()    # drop EVERY cached store table first (keyed_store.release inside), so a switch BACK to a library re-reads what is on disk instead of serving the session's old rows - sync can land another machine's edits behind the cache (test_switch_rereads is the pin) - and re-arm the migration retry guards, since a switch is exactly the change that earns another try
        models = self.library_models()
        if not models:
            return
        with ui_helpers.relayout(*models), database.one_read_per_file():    # grid and sidebar share one read
            for m in models:
                m.switch_model_data()
            model_registry.rebind(self.prefs, self.material_model)    # the shared set now serves another tree, so it is re-filed under it - left under the old key, the next panel opened there is handed this library's rows
            self.click_slider.setValue(grid.active_thumbsize(self))
        self._note_models_library()
        debug.event("session", "library switched", dir=self._models_dir)
        section = self._section()
        if section is not None:
            section.library_switched()

    def _update_library(self) -> None:
        """The library to this Amaze's version before any tile paints; nothing asks first."""
        try:
            if library_actions.update(self.prefs):
                self._refresh_open_prefs()
        except Exception as exc:                          # noqa: BLE001 - never blocks the panel
            debug.exception("library update", exc)

    def _refresh_open_prefs(self) -> None:
        """An open Preferences window shows the library's new version."""
        dialog = getattr(self, "_prefs_dialog", None)
        if dialog is None:
            return
        try:
            dialog.refresh_library_version()
        except RuntimeError:    # closed and deleted
            self._prefs_dialog = None

    def _library_too_new(self) -> bool:
        """A library a newer Amaze updated is not opened; the update is offered once Qt is idle."""
        from amaze.core import library_policy
        found = library_actions.newer_version(self.prefs)
        if not found:
            return False
        debug.event("session", "library is newer than this Amaze - not opened",
                    found=found, known=library_policy.LIBRARY_VERSION)
        timer = getattr(self, "_update_offer_timer", None)
        if timer is None:    # owned, so it dies with the panel ▸r/model-parent
            timer = self._update_offer_timer = QtCore.QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(0)    # a modal inside onCreateInterface draws black
            timer.timeout.connect(self._offer_amaze_update)
        timer.start()
        return True

    def _offer_amaze_update(self) -> None:
        """Update Amaze or Cancel, for the library left closed; headless, nothing is asked."""
        from amaze.core import library_policy, updater
        from amaze.dialogs import update_dialog
        ui = getattr(hou, "ui", None)
        if ui is None:
            return
        library_dir = str(self.prefs.dir or "")
        if ui.displayMessage(
                messages.LIBRARY_NEEDS_NEWER_AMAZE % library_policy.library_version(library_dir),
                buttons=messages.BUTTONS_UPDATE_AMAZE, default_choice=0, close_choice=1,
                severity=hou.severityType.Warning, title=messages.TITLE_AMAZE) != 0:
            return
        found = updater.check()
        if not found:
            ui.displayMessage(found.sentence, title=messages.TITLE_AMAZE)
        elif update_dialog.confirmed(found, library_dir):
            update_dialog.install_and_say(found)

    def _seed_curated_content(self) -> None:
        """The shipped starters through one door for construction and a switch. ▸archive/actions/library.py"""
        code_model = getattr(self, "code_model", None)    # the libraryless shape leaves models None
        gradient_model = getattr(self, "gradient_model", None)
        library_actions.seed_starters(
            code_model, self.code_category_model if code_model is not None else None,
            gradient_model, self.gradient_categories_model if gradient_model is not None else None)

    def toggle_catview(self) -> None:
        """Show and Hide the Category View via Menu"""
        self.cat_wrapper.setVisible(self.action_catview.isChecked())
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

    def _sync_online_chip(self) -> None:
        """Live only where the online world can open, and checked only while it is open."""
        button = getattr(self, "btn_online", None)
        if button is None:
            return
        button.setEnabled(getattr(self, "matx_online_model", None) is not None)
        if button.isChecked() != self._is_online():
            was = button.blockSignals(True)
            button.setChecked(self._is_online())
            button.blockSignals(was)

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
        grid.sync_sort_indicator(self)    # the arrow is one header's state and the sort is this proxy's, so they only agree if a bind says so
        if delegate is not None:
            self.thumblist.setItemDelegate(delegate)
            grid.bind_table_cell_delegates(self, delegate)    # THE TABLE DOES NOT WEAR THE TILE DELEGATE: that one paints a whole TILE per index, right where an index is a tile and catastrophic where a row is ten of them. Qt paints every text cell itself; only the picture and the tick columns get a delegate, and those are per COLUMN

    _LIST = amazetheme.drawn_list()    # header, heading inset and column widths are L01's ▸r/list-from-frame
    _TOOLBAR = amazetheme.drawn_toolbar()    # the toolbar's height, edges, gaps and sizes are B01's
    _SIDEBAR = amazetheme.drawn_sidebar()    # the sidebar's width and its splitter handle are G01's
    CELL_PAD = theme.ui_px(_LIST["cell_pad"])    #: a heading's inset from its column edge; row text is the style's
    HEADER_BG = QtGui.QColor(amazetheme.LIST_HEADER_BG)    #: the strip's own colours and height, kept so the table matches the painted header it replaced - a QHeaderView picks up none of them. The LABEL colour is the rows' ink, read from the delegate
    HEADER_DIVIDER = QtGui.QColor(amazetheme.LIST_HEADER_DIVIDER)
    HEADER_HEIGHT = theme.ui_px(_LIST["header_h"])

    def sync_list_columns(self) -> None:
        """Re-fit list mode's columns for the context now showing - THE SECTIONS' entry point, called from every `activate()`."""
        return grid.sync_table_columns(self)

    COLUMN_DEFAULT_WIDTH = dict(_LIST["widths"], thumb=24)    #: starting widths; "thumb" is never shown, so L01 draws no column for it

    COLUMN_MIN_WIDTH = 24    #: the floor for ANY column: `minimumSectionSize` is global rather than per-column, so License cannot be given one of its own; small enough that a tick column is not forced wide

    def apply_view_mode(self) -> None:
        grid.apply_view_mode(self)
        empty_state.track(self)    # the other view is up now, so the blank re-attaches to ITS model rather than relying on the two sharing a proxy

    def showEvent(self, event):
        """Record construct-to-painted on the FIRST show only - reopening a tab must not look like a fresh open - and after the event loop turns once, so the number includes the first paint: "panel ready" fires while the widget is still unparented and unpainted, before Houdini shows it and Qt polishes it under the Houdini stylesheet, lays it out and paints the first page of tiles"""
        super(AmazePanel, self).showEvent(event)
        if self._first_show_logged:
            return
        self._first_show_logged = True
        QtCore.QTimer.singleShot(0, self.ensure_library_user)    # after the first paint, never during construction: a modal dialog raised from a half-built panel blocks the paint it is sitting on top of
        QtCore.QTimer.singleShot(self.FILL_DELAY_MS, self.fill_compiled_files)
        t0 = getattr(self, "_construct_t0", None)
        if t0 is None:
            return

        def _record():
            debug.event(
                "session", "panel visible",
                construct_to_painted_ms=round(
                    (time.perf_counter() - t0) * 1000, 1))

        QtCore.QTimer.singleShot(0, _record)

    FILL_DELAY_MS = 5000    #: well after the first paint: the compile holds Python's lock ▸r/pane-open-cost

    def fill_compiled_files(self):
        """Compiles, in the background, Amaze's own files an update left uncompiled ▸r/pane-open-cost"""
        started = time.perf_counter()

        def _done(written):
            if written:
                debug.event("session", "compiled files written", count=written,
                            ms=round((time.perf_counter() - started) * 1000))

        return bytecode.compile_missing_in_background(amaze.PACKAGE_ROOT, _done)

    def ensure_library_user(self, chooser=None) -> str:
        """Ask WHICH user this machine is, and ONLY where the library already has some and this one is not among them (`users.ASK`): a library with nobody in it mints silently, a machine whose pointer already resolves is never questioned, and cancelling is allowed - it leaves no user, so nothing is keyed under a blank this session and the question comes back next time. `chooser` takes `{uid: name}` and answers `(uid, new_name)`, both empty for a cancel, so the decision can be driven without a dialog on screen"""
        preferences = self.prefs
        if users.first_run_state(preferences) != users.ASK:
            return users.current(preferences) or ""
        known = users.all_users(preferences)
        if chooser is None:
            def chooser(entries):
                from amaze.dialogs import user_dialog
                dialog = user_dialog.UserPickerDialog(entries, parent=self)
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
            timer = getattr(self, "_thumbsize_save_timer", None)
            if timer is not None and timer.isActive():    # the 500ms debounce dies with its parent - flushed, or the last slider/splitter change silently reverts on the next open (show_prefs flushes the same timer for the same reason)
                timer.stop()
                self.prefs.save()
        return super(AmazePanel, self).event(event)

    def eventFilter(self, watched, event):
        """Hover tracking for the grid's button badges, and nothing else: `thumblist` is hidden the whole time list mode is up, and the table sizes its own rows and columns in `grid.show_table` and `grid.sync_table_columns`"""
        if (getattr(self, "thumblist", None) is not None
                and watched is self.thumblist.viewport()
                and hasattr(self, "thumb_delegate")):
            kind = event.type()
            if kind in (QtCore.QEvent.Type.MouseMove,
                        QtCore.QEvent.Type.MouseButtonPress,
                        QtCore.QEvent.Type.MouseButtonRelease):
                self._sync_badge_hover(
                    event.position().toPoint(),
                    bool(event.buttons() & QtCore.Qt.MouseButton.LeftButton))
            elif kind == QtCore.QEvent.Type.Leave:
                self._sync_badge_hover(None)
        return False

    def _sync_badge_hover(self, point, down=False) -> None:
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
                    candidate, self.thumblist.visualRect(candidate), point)
                if badge is not None:
                    index = candidate
        previous = delegate._button_hover
        if delegate.set_button_hover(
                badge.name if badge is not None else None, index, down):
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
            tooltips.PANEL_TILE_SIZE if grid else
            tooltips.PANEL_TILE_SIZE_LIST))
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
        self.click_slider.setMaximumWidth(theme.ui_px(self._TOOLBAR["slider_w"]))    # ▸r/toolbar-from-frame
        self.click_slider.setFixedHeight(theme.ui_px(self._TOOLBAR["slider_h"]))
        if self.toolbar_layout is not None:
            idx = getattr(    # the design's order is [Filter box] [slider] [star] [toggle] [menus] but this block runs AFTER the star/toggle blocks, so the slider goes in at the spot remembered right after the filter box was added; both slider-side gaps are 20 design px
                self, "_after_filter_index", self.toolbar_layout.count()
            )
            self.toolbar_layout.insertSpacing(idx, theme.ui_px(self._TOOLBAR["slider_gap"]))
            self.toolbar_layout.insertWidget(idx + 1, self.click_slider)
            self.toolbar_layout.insertSpacing(idx + 2, theme.ui_px(self._TOOLBAR["slider_gap"]))
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
            self.btn_notes = ui_helpers.ChipToggleButton(name="btn_notes")    # built first; the row is mirrored after
            self.btn_notes.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_COMMENTS))
            self._sync_notes_button_pixmaps()
            self.btn_notes.setChecked(bool(self.prefs.show_notes))
            self.btn_notes.toggled.connect(self._on_notes_toggled)    # connected AFTER the initial state, so restoring a saved "open" does not re-save preferences mid-construction
            self.toolbar_layout.addWidget(self.btn_notes)
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))
            self.btn_online = ui_helpers.ChipToggleButton(name="btn_online")    # amber is its state: no hover lift
            self.btn_online.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_ONLINE))
            self._sync_online_button_pixmaps()
            self.btn_online.setChecked(self._is_online())
            self.btn_online.toggled.connect(self._on_online_button)
            self.toolbar_layout.addWidget(self.btn_online)
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))
            self.btn_filter = self._make_menu_button(self.menu_filter)    # held on self, unlike the other two menu buttons: this one is disabled online and its tooltip is rewritten on every section change, so the layout is no longer the only thing that needs to reach it
            self.toolbar_layout.addWidget(self.btn_filter)
            if menu_view is not None:
                self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))
                btn_view = self._make_menu_button(menu_view)
                btn_view.setToolTip(ui_helpers.tooltip_text(
                    tooltips.PANEL_VIEW_MENU))
                self.toolbar_layout.addWidget(btn_view)
                self.online_view_menu = QtWidgets.QMenu(self.ui)    # the ONLINE eye's menu: _sync_toolbar swaps it onto btn_filter when the context offers the kind filter
                kind_group = QtGui.QActionGroup(self.online_view_menu)
                kind_group.setExclusive(True)
                for label, section in (("All", None),
                                       ("Materials", "material"),
                                       ("Colors", "gradient"),
                                       ("Nodes", "cop"),
                                       ("Code", "code")):
                    act = self.online_view_menu.addAction(label)
                    act.setCheckable(True)
                    kind_group.addAction(act)
                    act.triggered.connect(
                        lambda _c=False, s=section:
                        self.matx_online_model.set_kind_filter(s))
                self.online_view_menu.actions()[0].setChecked(True)
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))
            btn_prefs = ui_helpers.IconMenuButton(    # held by the layout alone, never on self
                None,
                self._ui_icon_path("icon_library.svg"),
                on_click=self.show_prefs,
                fallback_label="Preferences",
                name="btn_prefs",
            )
            btn_prefs.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_PREFERENCES))
            self.toolbar_layout.addWidget(btn_prefs)
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))
            self.btn_categories = ui_helpers.ChipToggleButton(name="btn_categories")    # drives action_catview
            self.btn_categories.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_CATEGORIES))
            self._sync_categories_button_pixmaps()
            self.btn_categories.setChecked(
                bool(self.prefs.show_categories))
            self.btn_categories.toggled.connect(
                self._on_categories_button)
            self.toolbar_layout.addWidget(self.btn_categories)
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))
            self.btn_hip_capture = ui_helpers.IconMenuButton(    # every section: onto the selected tile
                None,
                self._ui_icon_path("icon_screenshot.svg"),
                on_click=self.capture_from_toolbar,
                fallback_label="Capture",
                name="btn_hip_capture",
            )
            self.btn_hip_capture.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_CAPTURE))
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
        self.cb_favsonly = ui_helpers.ChipToggleButton(name="cb_favsonly")
        self.cb_favsonly.setToolTip(ui_helpers.tooltip_text(
            tooltips.PANEL_FAVORITES))
        try:
            self.cb_favsonly.set_art(
                self._ui_icon_path("favourite.svg"),
                self._ui_icon_path("favourite_on.svg"),
                lighten_on_hover=False,    # the yellow fill IS the on/off signal; hover must not whiten it
            )
        except (TypeError, AttributeError):
            pass
        self.cb_favsonly.toggled.connect(self.filter_favs)
        if self.toolbar_layout is not None:
            self.toolbar_layout.addWidget(self.cb_favsonly)
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))    # B01's gap between buttons

        self.ui.cb_ViewMode.setVisible(False)  # type: ignore
        self.cb_viewmode = ui_helpers.ChipToggleButton(name="cb_viewmode")    # its icon is the CURRENT mode
        self.cb_viewmode.setToolTip(ui_helpers.tooltip_text(
            tooltips.PANEL_VIEW_MODE))
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
            splitter.setHandleWidth(theme.ui_px(self._SIDEBAR["handle"]))    # width only; Houdini draws the grip ▸r/sidebar-from-frame
        self.cat_wrapper = ui_helpers.HeldPane(    # the sidebar OWNS its width like the notes pane does: the remembered drag, or the 220 design width, asked of the splitter rather than left to cat_list's bare size hint
            self.prefs, "sidebar_width", theme.ui_px(self._SIDEBAR["width"]))
        self.cat_wrapper.setMaximumWidth(theme.ui_px(self._SIDEBAR["width"]))    # the pane's cap ▸r/sidebar-from-frame
        self.cat_list.setMaximumWidth(theme.ui_px(self._SIDEBAR["width"]))    # and the list's, at UI scale
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
        self.ui = ui_helpers.load_ui(
            amaze.package_file("ui", "amaze.ui"),
            dragdrop_widgets.DragDropCentralWidget,
            dragdrop_widgets.DragDropListView)

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
            self.toolbar_row.setFixedHeight(theme.ui_px(self._TOOLBAR["height"]))    # ▸r/toolbar-from-frame
            self.toolbar_layout = QtWidgets.QHBoxLayout(self.toolbar_row)
            self.toolbar_layout.setContentsMargins(0, 0, theme.ui_px(self._TOOLBAR["edge"]), 0)
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
        self.thumblist.clicked.connect(self._refresh_notes_subject)    # a click that changes nothing still has to reach the Notes pane, and this handler is idempotent
        thumblist_palette = self.thumblist.palette()    # grid and details unify on the `surface_high` token via QPalette (Base, the role QListView paints its viewport from) rather than setStyleSheet(), consistent with the cat_list fix above
        thumblist_palette.setColor(QtGui.QPalette.ColorRole.Base, theme.color("surface_high"))
        self.thumblist.setPalette(thumblist_palette)

        self.texture_progress = ui_helpers.ThinProgressBar()    # thin bar for texture thumbnail generation, docked above thumbview in verticalLayout_7 - which wraps thumbview ALONE, isolated from catview/details in the splitter. Built in code rather than the .ui; hidden until a folder with work to do is selected (see _on_texture_progress)
        self.texture_progress.set_accent_color(theme.accent(self.prefs.accent_color))
        self.set_conversion_bar_visible(False)
        husk_job.jobs.progressed.connect(self._on_render_progress)    # bound: jobs outlive the pane
        husk_job.jobs.activeChanged.connect(self._on_render_active)
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
        self._filter_timer = QtCore.QTimer(self)    # OWNED, so Qt takes it when the panel goes; `textEdited` only starts it, and Qt does not emit that for setText/clear, which is why the clear button hand-calls the filter ▸p/filter-pass-cost
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self.filter_thumb_view)
        self.line_filter.textEdited.connect(
            lambda _text: self._filter_timer.start())
        self.line_filter.setPlaceholderText(sections.Section.search_hint)    # the box is EMPTY by decree (2026-08-01): the "Search" label and the magnifier already name the control. The search_hint machinery stays for the day a section needs a word again, but every hint is "" and the tooltip is where :tag gets taught
        self.line_filter.setToolTip(ui_helpers.tooltip_text(
            tooltips.PANEL_SEARCH))
        self.line_filter.setStyleSheet(    # borderless box on the `field` token with the magnifier inside the left edge; the sheet goes on the widget ITSELF, never an ancestor, which is the rule the whole file follows to avoid the details-panel regression class. padding-left reserves room so typed text does not start under the icon
            "QLineEdit { border: none; background-color: "
            + theme.color_hex("field")
            + "; padding-left: %dpx; }" % theme.ui_px(20)
        )
        self.line_filter.setFixedHeight(theme.ui_px(self._TOOLBAR["field_h"]))    # ▸r/toolbar-from-frame
        self.line_filter.setMinimumWidth(theme.ui_px(38))    # overrides the .ui's own 80 minimum - setMinimumWidth wins at runtime
        self.line_filter.setMaximumWidth(theme.ui_px(self._TOOLBAR["field_w"]))
        try:    # the magnifier is an overlay QLabel + SideIconPinner, NOT a QLineEdit addAction() icon: that API does not expose the exact margin, and this design asks for one
            filter_icon_path = self._ui_icon_path("icon_search.svg")
            if filter_icon_path and os.path.exists(filter_icon_path):
                icon_size = theme.ui_px(self._TOOLBAR["search_icon"])
                pixmap = ui_helpers.render_svg_pixmap(    # through the package's one SVG rasteriser, so this icon obeys the same size and dpr rule as the rest ▸r/qicon-svg-engine
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
                    theme.ui_px(self._TOOLBAR["search_pad"]), side="left"
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
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["label_gap"]))
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
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))

        self.ui.details_widget.setParent(None)  # type: ignore  -- the Material Info form retired with D03: its nine fields all have better homes. OUT OF THE SPLITTER, not merely hidden - a hidden pane is still a pane and still takes a stretch, which is the invariant `test_one_flexible_pane_is_the_construction` holds. The widget stays in the externally-maintained .ui rather than being cut out of it ▸p/d03-retired

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
        self.click_slider.stepped = self.prefs.step_size
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

        edge = theme.ui_px(self._TOOLBAR["edge"])    # both edges hold a control once the capture button is back at the end
        self.toolbar_layout.setContentsMargins(edge, 0, edge, 0)

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
        """Every STORED category name, empty ones in and All out, sorted by the label a row shows."""
        names = []
        if not model:
            return names
        for elem in range(model.rowCount()):    # pass the SOURCE model, never the sidebar proxy: the proxy hides empty categories, and every ASSIGNMENT surface (the save dialog, the Edit Info dialog's Category dropdown) must still offer the complete list
            cidx = model.index(elem, 0)
            name = model.data(cidx, model.CatSortRole)    # STORED: "_WIP" displays as WIP
            if name and not category.is_all(name):
                names.append(str(name))
        return sorted(names, key=lambda name: category.display_name(name).lower())

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
        ids = [model.tile_key(proxy.mapToSource(index).row())
               for index in grid_columns.selected_rows(selmodel)]
        if not ids:
            return
        catmodel.check_add_category(category)    # outside the pair (it inserts), and its save can move rows
        with ui_helpers.relayout(model):
            for row in (model.find_asset_row_by_id(mat_id) for mat_id in ids):
                if row < 0:
                    continue    # deleted on another machine meanwhile
                asset = model.assets[row]
                model.set_assetdata(
                    model.index(row, 0), asset.name, category,
                    ", ".join(asset.tags),
                    None, save=False    # fav=None: never the per-user star; save=False: one write below
                )
        model.save()    # AFTER the pair: a save adopts a peer's rows, and an insert in it segfaults H21
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

        dialog = ui_helpers.DesignedDialog(self, title=mat.name)    # the name goes in at CONSTRUCTION because it fills the drawn band as well as the title bar ▸p/one-design-document

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
            if int(version.get("n", 0)) == active:
                label += "   active"    # the drawn row says which one is live, so a closed dropdown answers it too
            picker.addItem(label, int(version.get("n", 0)))
        current_row = next(
            (i for i, v in enumerate(listed)
             if int(v.get("n", 0)) == active), 0)
        picker.setCurrentIndex(current_row)
        picker.setToolTip(ui_helpers.tooltip_text(tooltips.PANEL_VERSION_ROW))
        dialog.add_field(picker)

        name_field = QtWidgets.QLineEdit(dialog)
        name_field.setToolTip(ui_helpers.tooltip_text(
            tooltips.PANEL_VERSION_ROW))
        name_field.setPlaceholderText(amazetheme.PLACEHOLDER_VERSION_NAME)
        name_field.setText(listed[current_row].get("name") or "")
        dialog.add_field(name_field, label=amazetheme.LABEL_CHANGE_NAME)

        def _sync_field(combo_row):
            name_field.setText(listed[combo_row].get("name") or "")

        picker.currentIndexChanged.connect(_sync_field)

        dialog.add_buttons(amazetheme.BTN_CANCEL, amazetheme.BTN_APPLY)

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
                paths.append(self._scene_path(path))    # the one home for the spelling, so pasted paths match what the session writes into parms
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
                    messages.NO_FOLDER_SELECTED_TO_RELOCATE
                )
            return
        path = ui.selectFile(file_type=hou.fileType.Directory) if ui else ""
        if not path:
            return
        rewritten = folders_model.relocate_folder(
            row, hou.text.expandString(path))    # the model rewrites its favorites onto the new path so they survive the move; a negative answer means the location is not a folder
        if rewritten < 0:
            if ui is not None:
                ui.displayMessage(
                    messages.RELOCATE_TARGET_NOT_A_FOLDER
                )
            return
        if rewritten:
            debug.event("folders", "relocated", favorites=rewritten)
        self.update_selected_cat()    # rescan under the new path


    def locate_unreadable_folder(self) -> None:
        """The unreachable-folder blank's Locate button: re-point the folder the MESSAGE names. It selects that folder in the sidebar first, because the blank can be up while the sidebar sits on All - and then the shared picker would move whichever folder happened to be current, not the one the user was just told about."""
        model = getattr(self, "file_folders_model", None)
        path = empty_state.unreadable_folder(self)
        if model is None or not path:
            return
        row = model.row_of(path)
        view_model = self.cat_list.model() if self.cat_list else None
        if row is None or view_model is None:
            return
        self.cat_list.setCurrentIndex(view_model.index(row, 0))
        self._locate_folder_user(model)

    def capture_from_toolbar(self) -> None:
        """Toolbar Capture: the one selected tile; in File with nothing selected, the open scene."""
        context = self._section()
        indexes = context.grid_selection() if context is not None else []
        if len(indexes) == 1 and getattr(context, "takes_capture", False):
            self.capture_onto_tile(context, indexes[0])
        elif not indexes and getattr(context, "key", "") == "file":
            self._capture_and_report()    # "" = the scene the viewport is showing
        else:
            self._report_capture_refused(messages.CAPTURE_SELECT_ONE_TILE)

    def capture_onto_tile(self, context, proxy_index) -> None:
        """The Scene View as one tile's picture, the tile then showing it. Never automatic ▸r/tile-captures"""
        model, proxy = context.tile_models()
        if model is None or proxy_index is None or not proxy_index.isValid():
            return
        source = proxy.mapToSource(proxy_index) if proxy is not None else proxy_index
        row = source.row()
        scene = self._hip_path_for(proxy_index) if getattr(context, "key", "") == "file" else ""
        if scene:
            captured = self._capture_and_report(scene)    # a scene only while it is the one open
        else:
            captured = self._run_capture(
                lambda: scene_captures.capture_tile(model.capture_path(row), model.tile_key(row)),
                model.tile_key(row))
        if captured:
            self._apply_icon_spec(model, [row], {"face": "capture"})

    def _hip_path_for(self, index):
        """The scene path behind a File-grid index, or '' - also '' for a row that is not a scene, so every hip-only path stays inert on other kinds."""
        if index is None or not index.isValid():
            return ""
        if index.data(self.file_files_model.KindRole) != \
                file_library.KIND_HIP:
            return ""
        return index.data(self.file_files_model.PathRole) or ""

    def _capture_and_report(self, target: str = "") -> bool:
        """The open scene onto its File tile; "" means whatever is open. Answers whether it landed."""
        return self._run_capture(
            lambda: scene_captures.capture_open_scene(self.prefs, target), target)

    def _run_capture(self, capture, label: str) -> bool:
        """Run one capture and SAY WHY it refused: a silent refusal reads as a broken feature."""
        try:
            capture()
        except scene_captures.CaptureRefused as exc:
            debug.event("hip", "capture refused", file=label, reason=str(exc))
            self._report_capture_refused(str(exc))
            return False
        return True

    def _report_capture_refused(self, text: str) -> None:
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(text)

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
        return "" if category.is_all(name) else name

    DEFAULT_SIDEBAR_COLOUR = amazetheme.SIDEBAR_PICKER_START

    def ask_category_name(self, title: str, default: str = ""):
        """The category-name dialog, once, so no caller unpacks CategoryDialog's two-field answer itself: None means CANCELLED, "" means the user cleared the field, and the two are NOT the same thing."""
        from amaze.dialogs import gradient_dialog
        dialog = gradient_dialog.CategoryDialog(title, default, parent=self)
        dialog.exec()
        if dialog.canceled:
            return None
        return dialog.name or ""    # "" is a real answer: a cleared Rename goes back to the folder's name

    def sidebar_set_colour(self, pick: bool, preset: str = "") -> None:
        """Label ▸ on the sidebar selection: `preset`, or "" for none; `pick` asks the picker once."""
        context = self._section()
        if context is None or self.cat_list is None:
            return
        names = [context.sidebar_key(index)    # ASK THE CONTEXT what a row is keyed by: a category's STORED name in three sections, a registered folder PATH in File. A colour written under the DISPLAYED name ("_WIP" shows as "WIP") is one nothing ever reads
                 for index in self.cat_list.selectedIndexes()]
        names = [name for name in names    # All is skipped: it is a view, not a category, and colouring it would mean colouring everything
                 if name and not category.is_all(name)]
        if not names:
            return

        colour = preset
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


    def _badge_verb(self, verb):
        """A badge click as the active section's verb: on the selection when the tile is in it."""
        def click(index):
            context = self._section()
            if context is None or not hasattr(context, verb):
                return
            selmodel = self.thumblist.selectionModel()
            rows = grid_columns.selected_rows(selmodel) if selmodel is not None else []
            getattr(context, verb)(rows if index in rows else [index], index)
        return click

    def grid_toggle_favourite(self, indexes) -> None:
        """Flip the star on the grid's selection - one entry point for every section's menu, and all it decides is which selection to act on."""
        context = self._section()
        if context is None:
            return
        context.toggle_favourite(list(indexes))    # the flip is the context's own verb, and re-mapping a favourites-only grid after it is the proxy's own invariant (grid_proxy.py) - nothing to force from here

    def convert_selected(self, target: str) -> None:
        """Right-click `Convert to`: each selected material with a route to `target` gets a twin."""
        from amaze.render.material_conversion import engine as conversion_engine
        if not self.material_model or target not in conversion_engine.targets():
            return
        indexes = grid_columns.selected_rows(self.material_selection_model)
        if not indexes:
            return
        model = self.material_model
        ids = [model.tile_key(self.material_sorted_model.mapToSource(index).row())
               for index in indexes]    # by ID, with no layout pair: each twin inserts and saves
        lines, converted, eligible, sources = [], 0, 0, set()
        for row in (model.find_asset_row_by_id(mat_id) for mat_id in ids):
            if row < 0:
                continue
            mat = model.assets[row]
            if not conversion_engine.has_route(mat.renderer, target):
                continue
            eligible += 1
            sources.add(renderers.normalized(mat.renderer))
            try:
                ok, report = model.convert(model.index(row, 0), target)
            except Exception as exc:                          # noqa: BLE001
                lines.append(f'"{mat.name}": crashed - {exc}')
                continue
            converted += 1 if ok else 0
            lines.extend(report.summary_lines())
        shown = " and ".join(renderers.label(source)
                             for source in conversion_engine.targets() if source in sources)
        ui = getattr(hou, "ui", None)
        if ui is not None and eligible:
            ui.displayMessage(messages.CONVERSION_SUMMARY % (
                converted, eligible, shown, renderers.label(target), "\n".join(lines)))

    def show_prefs(self) -> None:
        """Show the Preferences Dialog - NON-MODAL, floating above the main window, and opening with or without a library set (its Library tab is the only way to set one). A second open while the window exists just fronts it."""
        if self._thumbsize_save_timer.isActive():    # flush a pending debounced thumbsize save first: prefs.load() at close re-reads settings.json, and a still-pending write would silently revert the newest slider value
            self._thumbsize_save_timer.stop()
            self.prefs.save()
        from amaze.dialogs import prefs_dialog
        existing = getattr(self, "_prefs_dialog", None)
        if existing is not None:
            try:
                existing.show()
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                self._prefs_dialog = None
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

        def _closed(*_a):
            if applied["done"]:
                return
            applied["done"] = True
            self._prefs_dialog_closed()

        dlg.finished.connect(_closed)
        dlg.destroyed.connect(_closed)
        self.destroyed.connect(dlg.close)    # the dialog must not outlive the panel it applies to
        dlg.show()

    def _prefs_dialog_closed(self) -> None:
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
        switched = self.prefs.dir != self._models_dir
        if switched:    # only a library the models are not on yet earns their full re-read
            self.open_library()
        accent = theme.accent(self.prefs.accent_color)
        self.click_slider.set_accent_color(accent)
        self.click_slider.stepped = self.prefs.step_size
        if self.prefs.view_mode != "list":
            self.click_slider.setValue(grid.active_thumbsize(self))    # Step Size on: onto the nearest mark
        self.texture_progress.set_accent_color(accent)
        self._sync_notes_button_pixmaps()
        self.sidebar_delegate.set_drag_color(accent)
        self.sidebar_delegate.show_counts = self.prefs.sidebar_counts
        thumbnails.engine.set_budget_mb(self.prefs.ram_cache_mb)
        for _sidebar_proxy in self.sidebar_proxies():    # EVERY sidebar proxy, and via sidebar_proxies() rather than a hand-written list: one left out keeps its construction-time hide_empty for the rest of the run
            _sidebar_proxy.hide_empty = self.prefs.hide_empty_categories
        self._refresh_sidebar_categories()    # ends in the fall-back to All, should hiding hide its row
        self.cat_list.viewport().update()
        grid.visible_view(self).viewport().update()
        section = self._section()
        if section is not None and not switched:    # a switch has just shown it afresh
            section.prefs_changed()
        self._apply_enabled_sections()    # visible section tabs may have changed in Preferences

    def update_renderer_toggles(self):
        """A renderer was enabled or disabled - in Preferences, or by saving a material of a new one - so the Filter menu is rebuilt whole: MaterialSection.filter_entries re-reads the same prefs flags, and build_filter_menu falls back to All for any section whose remembered choice is no longer on offer. Under its own name because its three callers mean that event, not merely a menu redraw."""
        if getattr(self, "menu_filter", None) is None:
            return
        self.build_filter_menu()

    def import_package_file(self, path: str, restore: bool = False) -> dict:
        """ACT half of the whole-package import: every asset lands in its own section (fresh ids, `Import` category; `restore=True` adopts by original id), plain files land in the library's `import/` folder which registers as a location - answering the core summary."""
        from amaze.core import packages
        summary = packages.import_package(self._package_models(),
                                          self.prefs, path,
                                          restore=restore)
        self._absorb_package_summary(summary)
        return summary

    def import_amaze_package(self) -> None:
        """Package Import: the read-mode picker, then the act door; the summary speaks once, dialog-free when headless."""
        from amaze.core import packages
        ui = getattr(hou, "ui", None)
        if not self.prefs.dir:
            if ui is not None:
                ui.displayMessage(messages.NO_LIBRARY_CONFIGURED)
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
                messages.PACKAGE_IMPORT_SUMMARY % (summary["imported"], summary["files"]))

    def ask_package_destination(self) -> str:
        """The write-mode picker for an `.amazepkg` export - "" when headless or cancelled, the suffix appended when the user leaves it off."""
        from amaze.core import packages
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
        from amaze.core import gallery_import
        ui = getattr(hou, "ui", None)
        if not self.material_model:
            if ui is not None:
                ui.displayMessage(messages.NO_LIBRARY_CONFIGURED)
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
                    messages.MATERIAL_PRESETS_FOUND % picked
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
            messages.IMPORT_MATERIAL_PRESETS_FROM
            % (len(entries), os.path.basename(picked), listing),
            buttons=messages.BUTTONS_IMPORT,
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
                messages.GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED
                % (summary.get("imported", 0), summary.get("skipped", 0),
                   summary.get("failed", 0))
            )

    def cleanup_db(self) -> None:
        """Cleans the WHOLE v2 estate in one pass, one combined report: the material library, the COP library (the same integrity passes over cops.json), registered folder pointers whose directory is gone, and favorites pointing at files that are gone."""
        ui = getattr(hou, "ui", None)
        if not self.material_model:
            if ui is not None:
                ui.displayMessage(messages.NO_LIBRARY_OPEN)
            return

        if ui is None or ui.displayMessage(
            messages.CLEAN_LIBRARY_CONFIRM,
            help=messages.HELP_CLEAN_LIBRARY,
            buttons=messages.BUTTONS_CLEAN_LIBRARY,    # BEFORE: it moves files aside and drops dead locations, from two one-click doors
            default_choice=1, close_choice=1,
            severity=hou.severityType.Warning,
            title=messages.TITLE_AMAZE,
        ) != 0:
            debug.event("cleanup", "cancelled at the confirm dialog")
            return
        from amaze.actions import clean
        sections = clean.clean_library(
            self.prefs, self.material_model, self.category_model,
            getattr(self, "cop_model", None), getattr(self, "cop_category_model", None),
            self.file_folders_model)

        if sections:
            if ui is not None:
                ui.displayMessage(    # the RECORD: the grid cannot show a moved file or a dropped location
                    messages.CLEANUP_SUMMARY % "\n\n".join(sections))
        else:
            debug.event("cleanup", "nothing to clean")    # no dialog - nothing changed, and the log keeps the record

    def open_usdlib_folder(self) -> None:
        """Open the Library Folder in the System explorer"""
        if not self.material_model:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(messages.NO_LIBRARY_OPEN)
            return
        lib_dir = self.prefs.dir
        hostos.open_path(lib_dir)

    def add_file_folder_user(self) -> None:
        """Register a new folder pointer for the File section. Only stores the path - never scans or copies anything until the folder is actually selected in the list."""
        ui = getattr(hou, "ui", None)
        path = ui.selectFile(file_type=hou.fileType.Directory) if ui else ""
        if not path:
            return
        self.file_folders_model.add_folder(hou.text.expandString(path))

    def remove_file_folder_user(self) -> list:
        """Unregister the selected folder pointer(s), answering the paths removed; disk is untouched."""
        folders = self.file_folders_model
        rows = sorted(
            (i.row() for i in self.cat_list.selectedIndexes()), reverse=True
        )
        removed = []
        for row in rows:
            path = folders.data(folders.index(row, 0), folders.PathRole)
            if folders.remove_folder(row):
                removed.append(path)
        return removed

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
                self.current_section = keys[0]    # a tab here is a SOURCE; leaving Online shows this one
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
        proxy = context.tile_models()[1]
        with proxy.one_pass() if proxy is not None else contextlib.nullcontext():    # every filter set below shares one pass ▸p/filter-pass-cost
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
        ("btn_hip_capture", "takes_capture", "enabled"),
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
        btn_filter = getattr(self, "btn_filter", None)
        if btn_filter is not None:    # THE EYE IS THE FILTER BUTTON (icon_view.svg): online it carries the KIND filter and overrides the table row's disable; every section keeps its own filter menu and tooltip machinery
            if getattr(context, "kind_filter_menu", False):
                btn_filter.set_menu(self.online_view_menu)
                btn_filter.setEnabled(True)
                btn_filter.setToolTip(ui_helpers.tooltip_text(
                    tooltips.PANEL_KIND_FILTER))
            else:
                btn_filter.set_menu(self.menu_filter)
        self._sync_filter_placeholder()

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
        """EVERY tile delegate, once, derived from the sections - the tests' way to reach them all."""
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

    def tile_icon_models(self) -> tuple:
        """Every model whose tiles can wear an icon, once, from each section's own `tile_models()`."""
        found = []
        for section in getattr(self, "sections", {}).values():
            model = section.tile_models()[0]
            if model is not None and model not in found:
                found.append(model)
        return tuple(found)

    def _is_online(self) -> bool:
        """Is the online world showing? The mode alone answers it - the online world is its own world with its own tab strip of sources, not a view mode over one section, so no section key is part of the question. ONE predicate, so no handler works it out for itself."""
        return bool(getattr(self, "online_mode", False))    # `current_section` still names the local section underneath

    def _on_online_source(self, action) -> None:
        """A View menu material-source entry was clicked. Material Library returns to the local library; an online source enters its browser."""
        if action is self.action_material_library:
            self.leave_online_world()
            if self.current_section != "material":
                self.section_tabs.setChecked("material")
        elif action.isChecked():    # the entries share one exclusive group, so Qt keeps exactly one checked
            self.open_online_source(action.text())

    def enter_online_world(self, source: str = "") -> None:
        """Switch to the online world: its own tab strip, one tab per source, nothing to do with the local sections. Where you came FROM is remembered, because leaving puts you back there - you dipped into the online browser, you did not change what you were working on."""
        if self._is_online():
            return
        if getattr(self, "matx_online_model", None) is None:    # THE door: no online model, no entry
            self._sync_online_chip()
            return
        self._capture_section_state()    # capture on the way IN as well, or leaving (through `_apply_context` -> `_restore_section_state`) puts you back on the category stored at the last TAB SWITCH rather than what you were looking at
        self.online_mode = True
        first = source or self._online_segments()[0][0]
        self._build_section_tabs()
        self.open_online_source(first)
        self._sync_online_chip()

    def leave_online_world(self) -> None:
        """Back to the local sections, on the one left from, or the first shown if it was hidden."""
        if not self._is_online():
            return
        self.exit_online_materials()
        self._build_section_tabs()    # checks the tab of `current_section`, emitting nothing
        section = self._section()    # the section underneath: no tab click re-points the widgets here
        if section is not None:
            self._apply_context(section, section.key)    # THE ONE PATH, as entering already takes - `activate()` alone would leave the toolbar to a separate call

    def open_online_source(self, source_name: str) -> None:
        """Show one source in the online world - a tab click, now that the strip IS the sources."""
        if not self._is_online():
            self.enter_online_world(source_name)    # entering is the door's job, whoever asks
            return
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
        self._sync_online_chip()
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

    def _import_online_records(self, records, renderer=renderers.HUB.key) -> None:
        """Import online records into the LIBRARY, built as `renderer` through the conversion engine."""
        if not len(records):
            return
        total = len(records)
        failures = []
        with self._download_bar(records) as progress_for:
            for i, rec in enumerate(records):
                on_progress = progress_for(i)
                try:    # ONE BAD RECORD MUST NOT ABANDON THE BATCH: matx_import.import_record has only try/finally, so build_karma_material and library.add_asset raise straight through it, and without this the remaining records go unimported and `failures` never reaches its dialog
                    ok, reason = self.import_online_material(
                        rec, on_progress=on_progress, renderer=renderer
                    )
                except Exception as exc:                  # noqa: BLE001
                    debug.exception("online import", exc, record=rec.title)
                    ok, reason = False, str(exc)
                if not ok:
                    failures.append("%s: %s" % (rec.title, reason))
        ui = getattr(hou, "ui", None)
        if failures and ui is not None:    # ONE dialog for the batch, never one per record
            ui.displayMessage(
                messages.AMAZE_COULD_NOT
                % (len(failures), total, "\n".join(failures[:10]))
            )

    def import_online_material(self, record, on_progress=None,
                               renderer=renderers.HUB.key):
        """Download and save one online material as `renderer`, calling on_progress(0..1): (ok, reason)."""
        from amaze.core import matx_import
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
        ok, reason = matx_import.import_record(    # NO layout pair: it ends in add_asset, an insert
            record, source, resolution, self.material_model, self.prefs,
            progress=on_progress, renderer=renderer,
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
            folder = hostos.canonical_path_key(
                os.path.join(self.prefs.dir, "import"))
            folders = getattr(self, "file_folders_model", None)
            listed = {hostos.canonical_path_key(path)
                      for path in self.prefs.file_folders}
            if folder not in listed:
                self.prefs.set_file_folder_name(folder, "Import")    # before the row lands, and only here: a rename stays
                self.prefs.set_file_folder_kinds(folder, file_library.EVERY_KIND)
                if folders is None:
                    self.prefs.add_file_folder(folder)
                else:
                    folders.add_folder(folder)
            elif folders is not None:
                folders.refresh_counts()    # already listed: files landed in it, so its number moved
                row = folders.row_of(folder)
                if row is not None:
                    folders.dataChanged.emit(folders.index(0),
                                             folders.index(row))

    def _import_amaze_package_record(self, record, source, restore,
                                     on_progress=None):
        """One TILE into the library - its entry read straight out of the hosted package by member, fresh or restore - answering (ok, reason) like the material path beside it. The ranged reads report per-block progress into `on_progress`, whose pump is what keeps Houdini ALIVE through a slow transfer."""
        from amaze.core import packages
        url = record.payload.get("package")
        debug.event("import", "package tile start", title=record.title,
                    package=str(url), restore=bool(restore))
        self._last_package_summary = None    # the restore batch reads its totals here - one import door, one summary shape
        try:
            entry = record.payload.get("entry")
            if not entry:
                return (False, "the record carries no manifest entry")
            notify = None if on_progress is None else (
                lambda done, total:
                on_progress(min(done / float(max(total, 1)), 1.0)))
            bundle = source.import_reader(url, notify=notify)    # its own: a preview may hold the shared one
            summary = packages.import_entries(
                self._package_models(), self.prefs, bundle, [entry],
                restore=restore)
            self._last_package_summary = summary
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
        """Restore-mode import for the SELECTED tiles: adopt-only by curated tag / original id, one summary for the batch - inside the download bar, whose pump keeps the UI alive through the ranged reads."""
        totals = {"imported": 0, "skipped": 0, "files": 0, "refused": 0}
        failures = []
        with self._download_bar(records) as progress_for:
            for i, record in enumerate(records):
                source, _resolution, error = self._online_source_for(
                    record)
                if error or source is None:
                    failures.append("%s: %s" % (record.title,
                                                error or "Unknown source"))
                    continue
                try:
                    ok, reason = self._import_amaze_package_record(
                        record, source, restore=True,
                        on_progress=progress_for(i))
                except Exception as exc:                  # noqa: BLE001
                    debug.exception("package restore", exc,
                                    record=record.title)
                    failures.append("%s: %s" % (record.title, exc))
                    continue
                summary = self._last_package_summary or {}
                for key in totals:
                    totals[key] += summary.get(key, 0)
                if not ok and reason:
                    failures.append("%s: %s" % (record.title, reason))
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
            source = self.matx_online_model.source_for(record)
            if source is None:
                continue
            try:
                if source.needs_download(record):
                    return True
            except Exception:                          # noqa: BLE001
                return True          # unknown = assume it downloads
        return False

    def _online_source_for(self, record):
        """The record's source and the resolution to fetch it at: (source, resolution, error)."""
        source = self.matx_online_model.source_for(record)
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

    def _import_online_records_to_scene(self, records,
                                        renderer=renderers.HUB.key) -> None:
        """Build online records straight into the scene - the current LOP material library (or /mat) - without adding them to the library; amazepkg records split off to the LIBRARY door, a store tile being library data of ANY section (palette, snippet, material row) with no scene-build path of its own."""
        from amaze.core import matx_import
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
                            messages.NO_MATERIAL_DESTINATION_NETWORK
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
                            progress=on_progress, renderer=renderer,
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
                messages.SCENE_BUILD_PARTIAL_FAILURE
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

    def edit_tile_icon(self, model, proxy, proxy_indexes,
                       categories=()) -> None:
        """Customize on any tile: one handler for every section, applied to the WHOLE selection."""
        from amaze.dialogs import icon_dialog
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
        tile_tags = None    # a section whose model cannot hold tags shows no field at all; a multi-selection opens EMPTY but stays editable, and what is typed lands on every row
        if hasattr(model, "set_tile_tags"):
            tile_tags = model.tile_tags(rows[0]) if single else ""
        offered = None    # no field at all where the model cannot hold a category
        tile_category = ""
        if hasattr(model, "set_tile_category"):
            offered = list(categories)    # the OWNING section's list, handed in by its menu
            shared = {model.tile_category(row) for row in rows}
            tile_category = shared.pop() if len(shared) == 1 else ""    # mixed: the dialog opens blank
        faces = {"preview": model.preview_image(rows[0]),    # what the preview square shows per face
                 "capture": model.capture_image(rows[0]),
                 "generic": tile_icons.generic_image(model.tile_face_art(rows[0]))}
        dialog = icon_dialog.IconDialog(
            model.tile_icon(rows[0]),
            tile_icons.stroke_for(self.prefs),
            self,
            tile_name=tile_name,
            tile_name_enabled=single,
            tile_tags=tile_tags,
            categories=offered,
            tile_category=tile_category,
            face=tile_icons.face_for(model, rows[0]),
            faces=faces,
            can_preview=any(model.can_preview(row) for row in rows),
            can_capture=any(model.has_capture(row) for row in rows),
        )
        self._icon_dialog = dialog

        def _apply_edits(dialog=dialog, held=frozenset(held), model=model):
            rows = [row for row in range(model.rowCount())    # resolved HERE and not at open: where the held tiles are NOW, in one scan of the model on commit. A tile that went away during the dialog simply is not found
                    if model.tile_key(row) in held]
            if not rows:
                return
            self._apply_icon_spec(model, rows, dialog.spec)
            edited = set()    # keys of the records changed below - nothing saves until the one commit
            new_name = getattr(dialog, "new_tile_name", None)
            if new_name and len(rows) == 1 and \
                    hasattr(model, "set_tile_name"):
                if model.set_tile_name(rows[0], new_name, save=False):
                    edited.add(model.tile_key(rows[0]))
            new_tags = getattr(dialog, "new_tags", None)
            if new_tags is not None and hasattr(model, "set_tile_tags"):
                if len(rows) == 1:
                    if model.set_tile_tags(rows[0], new_tags, save=False):    # "" CLEARS the tags
                        edited.add(model.tile_key(rows[0]))
                else:
                    for row in rows:    # ADDS across a selection: each tile keeps its own tags
                        if model.add_tile_tags(row, new_tags, save=False):
                            edited.add(model.tile_key(row))
            new_category = getattr(dialog, "new_category", None)
            if new_category and hasattr(model, "set_tile_category"):
                for row in rows:    # EVERY selected tile, unlike the name and the tags
                    if model.set_tile_category(row, new_category, save=False):
                        edited.add(model.tile_key(row))
            if edited:
                model.commit_tile_edits(edited)

        def _finished(_result=0, dialog=dialog):
            self._icon_dialog = None
            try:
                if not dialog.canceled:
                    _apply_edits()
            finally:
                dialog.deleteLater()    # the panel is its C++ parent and outlives every dialog, so dropping the Python name frees nothing - 287 buttons and ~6.5MB stay alive per open otherwise

        dialog.applied.connect(_apply_edits)    # Apply commits and stays open; Accept closes and commits through _finished
        dialog.finished.connect(_finished)
        dialog.show()
        return

    def _apply_icon_spec(self, model, rows, spec) -> None:

        failed = model.set_tile_icons(rows, spec)    # one icon-store write for the whole selection
        model.commit_tile_icons(rows)    # once per selection, never per row
        ui = getattr(hou, "ui", None)
        if failed and ui is not None:
            ui.displayMessage(
                messages.TILE_ICON_SAVE_FAILED
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
                messages.NODE_ASSETS_IMPORT_FAILURES % "\n".join(failures))


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
        from amaze.dialogs import code_dialog
        if not self.code_model:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(
                    messages.NO_LIBRARY_CONFIGURED_2
                )
            return
        dialog = code_dialog.CodeDialog(
            self.get_code_category_names(),
            name=default_name,
            language=language or "VEX",
            category=self._current_code_category(),
            code=code,
            parent=self,
        )
        dialog.exec()
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
        )
        self._refresh_sidebar_categories()

    def _commit_code_save(self, node: hou.Node, dialog) -> None:
        """The snippet is the node's code parm as it reads now."""
        from amaze.helpers import helpers
        parm = helpers.find_code_parm(node)
        if dialog.categories:
            self.code_category_model.check_add_category(dialog.categories)
        self.code_model.add_asset(    # no layout wrapper: add_asset announces its own insert
            parm.eval(),
            dialog.name or node.name(),
            dialog.language or helpers.code_parm_language(parm),
            dialog.categories,
            dialog.tags,
            False,
        )
        self._refresh_sidebar_categories()

    def new_code_snippet(self) -> None:
        """Create a snippet by typing/pasting into an empty editor."""
        self._add_code_snippet("", "VEX", "")

    def click_on_row(self, section, index, payload=None) -> None:    # THE CLICK WALKER: the second half of the interaction engine, with sections.DropRule carrying the declarations. It replaced FIVE hand-written double-click handlers that answered one question five ways - three carried a selection VETO, where a selected node that could not take the payload refused instead of creating, and two never consulted the selection at all. The drag walker has read these same declarations since the behaviour table shipped; this is the aiming method it was missing
        """A click door on `index` in `section` - aimed by the SELECTION, executed from the section's own declaration. BOTH DOORS COME THROUGH HERE: the double-click, and the menu entry labelled with the same verb."""
        from amaze.helpers import helpers
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

    def _commit_cop_save(self, node: hou.Node, dialog) -> None:
        """Works in any context the Nodes section supports; the asset records which one."""
        ui = getattr(hou, "ui", None)
        net = node.parent()
        items = [i for i in hou.selectedItems() if i.parent() == net]
        if not any(i == node for i in items):
            items.append(node)
        if len(items) == 1 and self.cop_model.saves_whole_network(node):    # container vs selection: a network container right-clicked ON ITS OWN (a geo, a copnet, a lopnet, a subnet) saves the WHOLE network, anything else saves the selection inside the network that holds it and is named after the clicked node - and a multi-selection wins over the container reading, two geos selected meaning those two nodes rather than one of their interiors
            items = None

        if dialog.categories:
            self.cop_category_model.check_add_category(dialog.categories)

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
            debug.exception("_commit_cop_save", exc, node=node.path())
            save_error = str(exc)
        if save_error is not None:
            if ui is not None:
                ui.displayMessage(
                    messages.NODE_SAVE_FAILED_WITH_REASON % (node.name(), save_error)
                )
            return
        if not result and ui is not None:
            ui.displayMessage(
                messages.NODE_SAVE_FAILED % node.name()
            )

    def _active_network_pwd(self) -> hou.Node | None:
        """The pwd of the network editor the user most likely looks at, or None."""
        editors = nodes.NodeHandler.network_editors()
        try:
            return editors[0].pwd() if editors else None
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
        from amaze.helpers import helpers
        path = index.data(self.file_files_model.PathRole)
        if not path:
            return
        with helpers.preserving_selection_and_current():    # WRAPPED HERE and not at each caller, so the door, the drag and any later caller inherit it instead of having to remember - like every other scene-importing verb, this one leaves the artist's current node and display flag as it found them
            self._import_geo_in_context(path, self._active_network_pwd())

    def _import_geo_in_context(
        self, path: str, dest: hou.Node | None
    ) -> hou.Node | None:
        from amaze.helpers import helpers
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
                    messages.GEOMETRY_IMPORT_FAILED % (base, exc))
            return
        parm = helpers.find_file_parm(loader)
        if parm is None:
            try:
                (container or loader).destroy()
            except (hou.OperationFailed, hou.ObjectWasDeleted):
                pass
            if ui is not None:
                ui.displayMessage(
                    messages.LOADER_SOP_HAS_NO_FILE_PARM % loader_type)
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
        node = self._first_node_at_cursor(pane_tab)
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
                    messages.OBJECT_HAS_NO_MATERIAL_PARM % obj_node.name()
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
        from amaze.core import dragengine, lop_assign
        from amaze.helpers import helpers
        ui = getattr(hou, "ui", None)
        stock = dragengine.stock_lop()
        if stock is None:
            if ui is not None:
                ui.displayMessage(
                    messages.STOCK_LOP_HELPERS_UNAVAILABLE
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
        chosen = cmenu.exec(QtGui.QCursor.pos())    # `QCursor.pos()` is a static screen-coordinate read, not the deprecated mouse-event `pos()`
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
                            messages.NETWORK_REFUSED_MATERIAL_LIBRARY
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
                    messages.DROPPED_MATERIAL_IMPORT_FAILED
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
                            messages.MATERIAL_ASSIGN_FAILED % exc
                        )
        return bool(vops)





    def _import_materials_into_context(self, context, ids,
                                       position=None) -> None:
        """Network-release import for the material section, in ONE undo group so the whole multi-drop reverts as one step. Placement rides the import seam - the import RETURNS what it created and `helpers.place_nodes` is the one placement rule - so a position lands each copy at the release point, a multi-drop cascading from it."""
        from amaze.core import dragengine
        with dragengine.drop_group("Amaze Import Materials"):
            self._import_materials_into_context_grouped(
                context, ids, position)

    def _import_materials_into_context_grouped(self, context, ids,
                                               position=None) -> None:
        from amaze.helpers import helpers
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
        from amaze.core import dragengine
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
        return self._first_node_at_cursor(pane_tab)

    def _first_node_at_cursor(self, pane_tab) -> hou.Node | None:
        """The first hou.Node among the network items under the cursor, or None - the ONE reading the drop resolver and the click resolver share, so the two agree on what is under the cursor."""
        for item in self._network_items_at_cursor(pane_tab):
            candidates = (
                item if isinstance(item, (tuple, list)) else (item,)
            )
            for candidate in candidates:
                if isinstance(candidate, hou.Node):
                    return candidate
        return None

    def _commit_gradient_save(self, node: hou.Node, dialog) -> None:
        """The node's first color ramp, registered as a user gradient."""
        from amaze.helpers import helpers
        parm = helpers.find_color_ramp_parm(node)
        ramp_data = helpers.ramp_to_data(parm.evalAsRamp())
        self.gradient_model.add_user_gradient(
            dialog.name or node.name(), dialog.categories, ramp_data,
            tags=dialog.tags
        )
        if dialog.categories:
            self.gradient_categories_model.check_add_category(    # the shared verb, which brackets its own insert - not switch_model_data(), which belongs to a library switch and only ever runs through switch_all_models()
                dialog.categories)

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
        """The chip's glyph: IDLE_BODY blue while the pane is closed, COMMENT_INK while it is open."""
        button = getattr(self, "btn_notes", None)
        if button is None:
            return
        button.set_art(
            self._ui_icon_path("icon_comments.svg"),
            lighten_on_hover=False,    # the glyph is the section's blue as drawn, and it does not whiten when on
            recolour={notes_panel.COMMENT_INK:    # the tint map keys on the ART's colour, replacing a literal - so a map left keyed on a colour the drawing no longer contains matches NOTHING and the untinted art shows through in all four states instead
                      ui_helpers.IconMenuButton.IDLE_BODY},
            recolour_on={notes_panel.COMMENT_INK: notes_panel.COMMENT_INK})

    def _on_note_saved(self, _key: str) -> None:
        """A page was written - repaint the grid so the tile's note badge appears or clears with it."""
        grid.visible_view(self).viewport().update()    # THE VISIBLE view, whichever mode is up: `NotesRole` is answered live from the store with no `dataChanged`, so this repaint is the whole signal

    def _notes_subject(self):
        """What the Comments pane points at, or None - the section says what its selected tile is."""
        context = self._section()
        if context is None or not context.takes_comments:    # ASK THE CONTEXT, do not test which world this is: the online world answers no because an online record is not a library asset, a fact that belongs on it rather than in a branch here
            return None
        index = grid.selected_current_in(    # a SELECTED row: Qt keeps the current one after a deselect
            self.thumblist, context.grid_selection_model())
        if index is None:
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

    def _on_file_folder_progress(self, done: int, total: int) -> None:
        """The File model's progress: the bar shows only while File shows, in the local world."""
        if self._is_online() or self.current_section != "file":    # online, it still names File
            return
        self._on_texture_progress(done, total)

    def set_conversion_bar_visible(self, visible: bool) -> None:
        """The ONE door to the conversion bar's visibility - the Section Tab Strip's Cancel chip shows exactly when the bar shows, so both move here or not at all. test_cancel_conversions pins this as the package's only site setting the bar visible or hidden."""
        self.texture_progress.setVisible(visible)
        tabs = getattr(self, "section_tabs", None)    # None during init_ui: the bar is hidden before the strip is built, and _build_section_tabs re-applies the bar's state
        if tabs is not None:
            tabs.set_cancel_visible(visible)

    def _on_cancel_conversions(self) -> None:
        """The Cancel chip's verb: stop a background render, else the File batch's conversions."""
        if husk_job.jobs.busy():    # a background thumbnail render owns the bar
            husk_job.jobs.cancel()
            return
        model = self.file_files_model
        if model is not None:
            model.cancel_conversions()    # the model owns the pair and its order

    def _on_render_progress(self, done: int, total: int) -> None:
        """A background thumbnail render's progress, on the bar whichever tab shows."""
        self.set_conversion_bar_visible(True)
        self.texture_progress.set_progress(done, total)

    def _on_render_active(self, active: bool) -> None:
        """The bar comes up as a background render starts and goes as the last one ends."""
        self.set_conversion_bar_visible(active)
        if active:
            self.texture_progress.set_progress(0, 100)

    def _on_texture_progress(self, done: int, total: int) -> None:
        """Shows/updates the thin progress bar above the thumbnail grid while texture thumbnails are generating for the selected folder. Hidden when there's nothing to do (fully cached / empty folder) or once generation completes."""
        if husk_job.jobs.busy():    # a background thumbnail render owns the bar
            return
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
        self.menu_filter.clear()    # deletes the menu's actions, emptying the group, never the group itself
        if self.filter_action_group is None:
            self.filter_action_group = QtGui.QActionGroup(self.menu_filter)    # ONE, for the session
            self.filter_action_group.setExclusive(True)
            self.filter_action_group.triggered.connect(self.filter_menu_changed)
        self.filter_actions = {}
        self.filter_values = {}
        button = getattr(self, "btn_filter", None)
        if button is not None:
            if (section is not None
                    and not getattr(section, "takes_filter_menu", True)):
                button.setVisible(True)    # offered-but-off is the toolbar table's business, and it DISABLES the button (half opacity, like Favourites and Comments beside it) rather than hiding it - one owner for the control
            else:
                button.setVisible(bool(entries))    # no entries, no menu: a button that opens an empty popup is worse than no button (nothing shipped hits this - all five sections filter - but a new section gets it free)
            if section is not None and not getattr(
                    section, "kind_filter_menu", False):    # online the eye belongs to the KIND filter - _sync_toolbar owns its menu and tooltip there, and this function must not be a second owner
                button.setToolTip(ui_helpers.tooltip_text(
                    section.filter_tooltip))
        if not entries:
            return
        for entry_id, label, value, icon in entries:
            act = self.menu_filter.addAction(label)
            if icon:
                act.setIcon(ui_helpers.menu_icon(icon, self))
            act.setCheckable(True)
            act.setData(entry_id)
            self.filter_action_group.addAction(act)
            self.filter_actions[entry_id] = act
            self.filter_values[entry_id] = value
            if icon and entry_id == entries[0].id:
                self.menu_filter.addSeparator()    # a menu with icons sets the everything-entry apart
        remembered = self.prefs.section_filter(self.current_section)
        act = self.filter_actions.get(remembered) or self.filter_actions[
            entries[0][0]]    # a remembered choice that is no longer offered falls back to entries[0], the everything-entry (sections.py puts it first), so a renderer switched off in Preferences needs no case of its own
        act.setChecked(True)
        self.apply_section_filter()

    def filter_menu_changed(self, action) -> None:
        """An entry was picked: apply it and remember it for this tab."""
        self.apply_section_filter()
        self.prefs.set_section_filter(self.current_section, action.data())
        self.prefs.save()

    def apply_section_filter(self) -> None:
        """Push the menu's checked entry into the active section - separate from filter_menu_changed because the same push has to happen with nobody clicking anything: entering a section, rebuilding the menu, or opening the panel."""
        section = self._section()
        if section is None or not self.filter_actions:
            return
        checked = (self.filter_action_group.checkedAction()
                   if self.filter_action_group is not None else None)
        entry_id = checked.data() if checked is not None else ""
        value = self.filter_values.get(entry_id)
        section.apply_filter(value)
        debug.event(
            "filter", "section filter applied",
            section=self.current_section, entry=entry_id, value=str(value),
            visible=self.thumblist.model().rowCount()
            if self.thumblist.model() is not None else -1,
        )

    def _refresh_sidebar_categories(self) -> None:
        """Re-evaluate empty-category hiding and counts after anything that changed which materials/COPs exist, what they belong to, or which renderer filter is active. For the flows that do NOT emit category_model.layoutChanged themselves (deletes, overwrite, renderer switch); the ones that do refilter automatically."""
        for proxy in self.sidebar_proxies():
            proxy.sourceModel().drop_count_cache()
            proxy.invalidateFilter()
        if self.cat_list is not None:
            self.cat_list.viewport().update()
        self._ensure_sidebar_selection(self.current_section)    # the refilter can hide the row the user stands on - a delete emptying its category - and the view's current index then slides onto the row below while the grid stays filtered on a category the sidebar no longer shows

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
        section = self._section()
        stack = section.stack() if section is not None else None
        if stack is None:
            return
        standing = stack.proxy.filter_value(stack.model.CategoryRole)    # WHERE THE USER STANDS is the grid's filter, never the sidebar's selection: when a row hides, Qt slides both the current index and the selection onto the row below, so `selectedIndexes()` answers a category nobody chose
        if not standing:
            return    # All: every category is a row, and All is always one
        row = self._sidebar_row_stored(proxy, standing)
        if row is None:
            self._stand_on_all_category()
            return
        current = ui_helpers.live_current_index(self.cat_list)
        if current is None or current.row() != row.row():
            self._stand_on_category(row.data())    # the row is still there and the selection slid off it

    @staticmethod
    def _sidebar_row_stored(proxy, stored: str):
        """The sidebar row whose STORED name is `stored`, or None - keyed on the name the grid filters by, which a displayed label with its underscore stripped is not."""
        source = proxy.sourceModel()
        role = getattr(source, "CatSortRole", None)
        if role is None:
            return None
        for row in range(proxy.rowCount()):
            index = proxy.index(row, 0)
            if str(index.data(role) or "") == stored:
                return index
        return None

    def _stand_on_all_category(self) -> None:
        """Point the sidebar at All and refilter - the hidden-category fallback."""
        self._stand_on_category("All")

    def _stand_on_category(self, label: str) -> bool:
        """Point the sidebar at the row reading `label` and refilter, answering whether that row exists - ONE owner for the row walk, so the All fallback and the sort's restore cannot drift. The label is the DISPLAYED name, which is what a sidebar row answers."""
        view = getattr(self, "cat_list", None)
        proxy = view.model() if view is not None else None
        if proxy is None:
            return False
        selection_model = view.selectionModel()
        found = False
        for row in range(proxy.rowCount()):
            idx = proxy.index(row, 0)
            if idx.data() == label:
                view.setCurrentIndex(idx)
                if selection_model is not None:
                    selection_model.select(
                        idx,
                        QtCore.QItemSelectionModel.SelectionFlag
                        .ClearAndSelect,
                    )
                found = True
                break
        self.update_selected_cat()
        return found

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
            buttons=messages.BUTTONS_DELETE,
            default_choice=1, close_choice=1,
        ) != 0:
            return
        context.delete_rows(sources)

    def generate_random_material(self) -> None:
        """The Generator Engine's first output: one random plausible material, built INTO THE SCENE where the user is working - the current LOP material library (or one created per the drop placement law) when the context is LOP, else /mat. A generated material is a scene node, not a library entry: keeping one is a deliberate `Save to <app>`, exactly like any other material the user builds by hand."""
        from amaze.helpers import helpers
        from amaze.render import generator
        builder = None
        destination = None
        ui = getattr(hou, "ui", None)
        with hou.undos.group("Amaze Generate Material"):    # the whole gesture is ONE undo step, staging AND the destination resolution that may itself create a material library: a move whose source parent was destroyed outside the group has nothing coherent to undo to, and a library created outside it survives the undo as an orphan
            destination = nodes.karma_destination(self.prefs)
            if destination is None:
                if ui is not None:
                    ui.displayMessage(
                        messages.NO_MATERIAL_DESTINATION_NETWORK
                    )
                return
            staging = hou.node("/obj").createNode("matnet")    # built in /obj staging and moved in ONE step, because structure changes inside a live material library retranslate the whole thing (wiki)
            try:
                builder, spec = generator.generate_random_material(staging)
                if builder is None:
                    if ui is not None:
                        ui.displayMessage(
                            messages.MATERIAL_GENERATION_FAILED
                        )
                    return
                moved = hou.moveNodesTo((builder,), destination)
                if not moved:
                    builder = None
                    debug.event("generate", "move failed",
                                destination=destination.path())
                    if ui is not None:
                        ui.displayMessage(
                            messages.GENERATED_MATERIAL_MOVE_FAILED % destination.path()
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
                        messages.GENERATED_MATERIAL_NOT_REGISTERED % (builder.name(), destination.path())
                    )
            except hou.Error as exc:
                builder = None
                debug.event("generate", "failed", error=str(exc))
                if ui is not None:
                    ui.displayMessage(
                        messages.MATERIAL_GENERATION_ERROR % exc
                    )
            finally:
                staging.destroy()
        if builder is not None and ui is not None:
            ui.setStatusMessage(
                "Amaze: generated %s in %s"
                % (builder.name(), destination.path())
            )

    def save_from_node(self, node: hou.Node | None = None,
                       prefer: str = "") -> None:
        """THE door a scene node is saved through: right-click and drop. ▸p/save-section-row"""
        ui = getattr(hou, "ui", None)
        selected = hou.selectedNodes()
        node = node or (selected[0] if selected else None)
        if node is None:
            if ui is not None:
                ui.displayMessage(messages.NO_NODE_TO_SAVE)
            return
        nodes = selected if node in selected else [node]
        keys = self._save_targets(nodes)
        debug.event("save", "save door", node=node.path(), offered=keys,
                    prefer=prefer)
        if not keys:
            if ui is not None:
                ui.displayMessage(messages.NODE_CANNOT_BE_SAVED % node.name())
            return
        key = sections.save_guess(keys, nodes, prefer)
        if key == "material":
            self.save_asset()    # the already-in-the-library question comes first
            return
        self._save_new(nodes, key, node)

    def _save_targets(self, nodes: list) -> list:
        """The keys of the sections, in tab order, that could take these nodes."""
        able = [key for key, _ in self.ALL_SECTIONS
                if key in self.sections
                and getattr(self, getattr(self.sections[key], "model_attr", ""),
                            None) is not None
                and self.sections[key].can_save(nodes)]
        shown = [key for key in able if key in self.prefs.enabled_sections]
        return shown or able    # a hidden tab is still a place to save

    def _save_new(self, nodes: list, key: str,
                  node: hou.Node | None = None) -> None:
        """D09 for these nodes, opened on section `key`, then that section's save."""
        from amaze.dialogs import save_dialog
        from amaze.helpers import helpers
        node = node or nodes[0]
        keys = self._save_targets(nodes) or [key]
        cats, current = self.sections[key].save_categories()
        one = nodes[0] if len(nodes) == 1 else None
        code_parm = helpers.find_code_parm(one) if one is not None else None
        dialog = save_dialog.SaveDialog(
            cats, current, name=one.name() if one is not None else "",
            name_enabled=one is not None, parent=self,
            sections=[(k, self.sections[k].label) for k in keys],
            section=key,
            categories_for=lambda k: self.sections[k].save_categories(),
            language=(helpers.code_parm_language(code_parm)
                      if code_parm is not None else ""),
            language_sections=[k for k in keys
                               if self.sections[k].takes_language])
        r = dialog.exec()
        chosen = getattr(dialog, "section", "") or key
        debug.event(
            "save", "save dialog closed",
            accepted=bool(r and not dialog.canceled), section=chosen,
            category=dialog.categories, preselected=current,
        )
        if dialog.canceled or not r:
            return
        if chosen == "material":
            self._commit_material_save(nodes, dialog)
        elif chosen == "cop":
            self._commit_cop_save(node, dialog)
        elif chosen == "gradient":
            self._commit_gradient_save(node, dialog)
        elif chosen == "code":
            self._commit_code_save(node, dialog)

    def save_asset(self) -> None:
        """Saves the selected nodes (Network Editor) to the Library, with standard file-save semantics at ANY selection size: nodes matching an EXISTING library material - by the id stamp a previous save/import left on them, or by a unique name match - raise one save-over / Save New / Cancel choice for the whole selection, with the save-over button offered only where the library allows it; anything else goes straight to the normal new-material dialog."""
        from amaze.core import library_policy
        ui = getattr(hou, "ui", None)
        sel = hou.selectedNodes()
        debug.event("save", "save_asset entry", selected=len(sel))
        if not sel:
            if ui is not None:
                ui.displayMessage(messages.NO_MATERIAL_SELECTED)
            return
        if not self.material_model:
            if ui is not None:
                ui.displayMessage(
                    messages.NO_LIBRARY_CONFIGURED_2
                )
            return
        existing = []    # (asset id, node) per node held: ONE choice for all; ids, as saves move rows
        new_nodes = []
        for node in sel:
            row = self._find_existing_asset_row(node)
            if row >= 0:
                existing.append((self.material_model.tile_key(row), node))
            else:
                new_nodes.append(node)
        debug.event("save", "overwrite check",
                    existing=len(existing), new=len(new_nodes))
        if existing:
            if len(sel) == 1:
                name = self.material_model.data(
                    self.material_model.index(
                        self.material_model.find_asset_row_by_id(existing[0][0]), 0),
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
                for mat_id, node in existing:
                    self._update_existing_asset(mat_id, node)
                    QtWidgets.QApplication.processEvents(
                        QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
                    )
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

    def _update_existing_asset(self, mat_id: str, node: hou.Node) -> None:
        """Overwrite asset `mat_id`'s content from the scene node: same entry and metadata, new files."""
        model = self.material_model
        renderer = model.update_asset_content(    # NO layout pair: it saves, which adopts rows
            model.find_asset_row_by_id(mat_id), node)
        if renderer:
            model.row_changed(model.find_asset_row_by_id(mat_id))    # renderer and date changed IN PLACE
        self._refresh_sidebar_categories()    # a re-detected renderer can shift counts and hiding
        if not renderer:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(
                    messages.MATERIAL_UPDATE_FAILED
                )
            return
        self.enable_renderer_on_add(renderer)
        self.prefs.save()
        self.update_renderer_toggles()

    def get_material_info_user(self, sel: list[hou.Node]) -> None:
        """The new-material save: D09 opened on Material, any section still choosable."""
        if not self.material_model or not self.category_model or not sel:
            return
        self._save_new(sel, "material")

    def _commit_material_save(self, sel: list[hou.Node], dialog) -> None:
        if dialog.categories:
            self.category_model.check_add_category(dialog.categories)

        renderers = []
        failures = []
        for asset in sel:
            try:    # a read-only or unreachable library directory raises out of the save chain (IsADirectoryError on the .interface, verified), and debug.guarded LOGS AND RE-RAISES rather than absorbing it, so the per-material failure report needs this catch of its own
                renderer = self.material_model.add_asset(
                    asset, dialog.categories, dialog.tags, dialog.fav,
                    name=dialog.name or None
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
            QtWidgets.QApplication.processEvents(    # lets the fresh tile PAINT before the next material's blocking render starts: with add_asset emitting real row-insert signals, this flush is what makes a long multi-save appear one material at a time
                QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
            )

        ui = getattr(hou, "ui", None)
        if failures and ui is not None:
            ui.displayMessage(
                messages.MATERIALS_SAVE_FAILURES % "\n".join(failures))
        for renderer in renderers:
            self.enable_renderer_on_add(renderer)
        self.prefs.save()
        self.update_renderer_toggles()
        self._refresh_sidebar_categories()

    def enable_renderer_on_add(self, renderer: str) -> None:
        """Switch a renderer on when its first material is saved, so the save shows in its own tab."""
        found = renderers.get(renderer)
        if found is not None:
            setattr(self.prefs, found.switch, True)
        self.prefs.save()

    def import_asset(self, target: str = "auto"):
        """Import the selected materials: `target` "auto" follows the network, "mat"/"lop" force one."""
        if not self.material_model or not self.category_model:
            return
        failures = []
        with hou.undos.group("Amaze Import Materials"):    # ONE undo entry for the whole import, as at every other import entry point: ungrouped, the destination container, the staging matnet, the builder, the move and the materiallibrary entry are separate entries, so one Ctrl+Z leaves a stray matnet and a half-imported builder behind
            self._import_selected_materials(target, failures)
        ui = getattr(hou, "ui", None)
        if failures and ui is not None:
            ui.displayMessage(
                messages.MATERIALS_IMPORT_FAILURES % "\n".join(failures))

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
        from amaze.core import dragengine
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
            spot = dragengine.ghost_snap_position() \
                or pane_tab.cursorPosition()    # the ghost promised the SNAPPED point, so the release lands there
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
        networks = []
        for editor in nodes.NodeHandler.network_editors():
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
        from amaze.helpers import helpers
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
        self.apply_view_mode()    # sizing for the active mode - grid grows icons, list grows rows

