"""The Amaze panel: the Python panel widget and its views onto the models."""

import time

_BODY_T0 = time.perf_counter()    #: when this module body began, before the imports and the reload chain

import os
import importlib
import contextlib
import functools
import sys

from PySide6 import QtWidgets, QtGui, QtCore
import hou

import amaze
from amaze.actions import files as files_actions
from amaze.actions import library as library_actions
from amaze.actions import materials as material_actions
from amaze.actions import nodes as node_actions
from amaze.core import grid_columns, grid_engine
from amaze.panel import (dragdrop_widgets, empty_state, grid, notes_panel,
                         sections, sidebar)
from amaze.core import debug, keyed_store, locations, section_list
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
from amaze.helpers import helpers, hostos, theme, ui_helpers, wording
from amaze.utils import rc_calls
from amaze.core import database, renderers, tile_icons, users
from amaze.render import cop_nodes, husk_job, nodes

_DEV_RELOAD = bool(os.environ.get("AMAZE_DEV_RELOAD"))    # the reload chain below is off by default ▸r/module-reload


def _reload(module):
    """importlib.reload, unless the dev switch is off."""
    if _DEV_RELOAD:
        importlib.reload(module)


def _reload_loaded(name):
    """`_reload` for a module imported where it is used, so only once something has loaded it."""
    if _DEV_RELOAD and name in sys.modules:
        importlib.reload(sys.modules[name])


_reload(keyed_store)    # first: eleven modules read their stores through it
_reload(locations)      # right after the engine it binds two stores into - and the switch door calls locations.forget()
_reload(hostos)    # before library: the models import the shared thumbnail engine
_reload(wording)    # before library, nodes and sections, which name things through it
_reload(debug)
_reload(section_list)    # before sections, prefs and the dialog, which read the list
_reload_loaded("amaze.core.dragengine")
_reload_loaded("amaze.core.lop_assign")
_reload_loaded("amaze.core.workers")    # before the engines that stop their threads through it
_reload(thumbnails)
_reload(database)
_reload_loaded("amaze.core.library_policy")    # before library, which gates overwriting on it
_reload(versions)
_reload(notes)
_reload(users)    # before versions and the dialogs showing a user: both resolve a UID through it
_reload(renderers)
_reload(material)
_reload_loaded("amaze.core.material_files")    # before nodes and library, which read saved materials by it
_reload(texstore)    # before nodes and library, which adopt and resolve through it
if _DEV_RELOAD and "amaze.preview" in sys.modules:
    sys.modules["amaze.preview"].reload_engine()    # the package reloads itself ▸r/package-reload
_reload_loaded("amaze.render.material_converter")
_reload(cop_nodes)    # before nodes, which builds Node assets with it
_reload(nodes)
_reload(husk_job)    # before thumbs, which submits to its queue
_reload_loaded("amaze.render.thumbs")
_reload(tile_icons)    # before gradient_library and the Node Info dialog, which read its facts
_reload(grid_columns)    # BEFORE the engine, which reads its column order
_reload(grid_engine)    # BEFORE library and its siblings, which mix it in
_reload(captures)    # before library, file_library and scene_captures, which read it
_reload_loaded("amaze.core.file_moves")    # after captures and locations, which it carries keys through
_reload(library)
_reload(category)
_reload_loaded("amaze.core.repair")
_reload(folders)
_reload(prefs)
_reload(library_actions)    # after captures, database and prefs, which its steps call
_reload(messages)      # the wording every dialog shows ▸p/messages-need-one-home
_reload(tooltips)      # every hover text; before the dialogs, delegates and models that read it
_reload(amazetheme)    # before theme and ui_helpers, whose class bodies read it ▸p/one-design-document
_reload(theme)    # before ui_helpers, whose class bodies read theme colours
_reload(branding)    # first of the ones below: everything reads its constants
_reload(ui_helpers)
_reload(rc_calls)    # after debug and messages: it hands the log the dialogs they word
_reload(helpers)
_reload_loaded("amaze.actions.code")    # after helpers, which it calls; before sections, which calls it
_reload(texture_library)
_reload(gradient_library)
_reload(cop_library)    # after library/category, so its subclasses bind to the freshly reloaded material classes
_reload(node_actions)    # after nodes and cop_nodes, which it calls; before sections, which calls it
_reload(material_actions)    # after library, nodes and husk_job, which it calls; before sections
_reload(geo_library)    # after texture_library, whose ThumbnailCache/proxy it reuses
_reload(scene_captures)
_reload_loaded("amaze.core.scene_files")    # before file_library, which reads scenes by it
_reload(file_library)    # after texture/geo/hip: it composes all three engines
_reload(files_actions)    # after file_library and helpers, which it hands in; before sections
_reload_loaded("amaze.helpers.vex_syntax")    # before code_library/code_dialog, which consume its palette and tokenizer
_reload(code_library)    # after library/category: it subclasses the material machinery
_reload(model_registry)    # last of the models: it names all ten classes

_reload_loaded("amaze.dialogs.base_dialog")    # FIRST of the dialogs: each binds its AssetDialog class
_reload_loaded("amaze.dialogs.library_dialog")
_reload_loaded("amaze.dialogs.prefs_dialog")
_reload_loaded("amaze.dialogs.save_dialog")
_reload_loaded("amaze.dialogs.icon_dialog")
_reload_loaded("amaze.dialogs.gradient_dialog")
_reload_loaded("amaze.dialogs.code_dialog")
_reload_loaded("amaze.dialogs.user_dialog")
_reload(dragdrop_widgets)
_reload(grid)    # before sections, which imports it
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



from amaze.panel import delegates            # noqa: E402

_reload(delegates)

FILTER_DEBOUNCE_MS = 180    #: the search box's pause before it filters ▸p/filter-pass-cost

MIN_PANEL_WIDTH = 500    #: design px through `theme.ui_px` at use; the grid pane has none ▸r/qt-windows-macos




class _FirstPaint(QtCore.QObject):
    """Calls `done` once, after `viewport`'s first paint has RETURNED, then lets go of it."""

    def __init__(self, viewport, done) -> None:
        super().__init__(viewport)    # dies with the viewport
        self._done = done
        self._painting = False
        viewport.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if self._painting or event.type() != QtCore.QEvent.Type.Paint:
            return False
        self._painting = True
        try:
            QtCore.QCoreApplication.sendEvent(watched, event)    # the paint, every filter included
        finally:
            self._painting = False
            watched.removeEventFilter(self)    # safe inside eventFilter, says the Qt manual
        self._done()
        return True    # painted above: the original stops here


class AmazePanel(QtWidgets.QWidget):
    """The panel widget: shell, sections and the views onto their models."""

    def __init__(self) -> None:
        super(AmazePanel, self).__init__()
        self._construct_t0 = time.perf_counter()    # before any work, so "panel ready" reports module body and construction apart
        self._first_show_logged = False
        rc_calls.start()    # before the log writes anything, so its header knows the Houdini
        debug.install()    # first, so a construction failure is logged even with Debug Mode off
        try:
            self._build()
        except Exception as exc:
            debug.exception("panel construction", exc)
            raise

    def _build(self) -> None:
        from amaze.helpers import vex_syntax
        vex_syntax.use_inks(theme.syntax_inks())    # Houdini's syntax colours, tiles and editor alike
        self.prefs = prefs.Prefs()

        loaded = self.prefs.load()    # False when nothing usable is on disk; the prefs are populated either way
        debug.configure(self.prefs.debug_mode)    # before setup(), so a crash there is logged
        debug.prefs_snapshot(self.prefs)
        hostos.set_cache_override(self.prefs.cache_dir)    # set before any cache is touched
        if loaded:
            self.init_ui()
            if (library_actions.index_unreadable(self.prefs.dir)
                    or library_actions.list_not_arrived(self.prefs.dir)):
                self._defer_open_library()
                opened = False    # the pane opens without a library; what it says follows
            else:
                opened = self._open_at_start()
            if not opened:
                self._open_libraryless()    # still a finished construction, so it says ready
            debug.event(    # a header without 'panel ready' means logging died during construction
                "session", "panel ready",
                module_body_ms=round(    # the imports and the reload chain, before construction
                    (self._construct_t0 - _BODY_T0) * 1000, 1),
                construction_ms=round(
                    (time.perf_counter() - self._construct_t0) * 1000, 1),
                **debug.probe())
        else:
            self.init_ui()
            self._open_libraryless()

    def _open_libraryless(self) -> None:
        """The no-library shape: every model attribute present and None, so the gear still works."""
        self.material_model = None
        self.category_model = None
        self.cop_model = None    # a right-click save asks every model before one is built
        self.cop_category_model = None
        self.code_model = None
        self.code_category_model = None
        self.file_files_model = None    # show_prefs hands it to Preferences, which takes None
        self.file_folders_model = None
        self.matx_online_model = None    # setup() builds the online world; its door refuses without it
        self._sync_online_chip()

    def _defer_open_library(self) -> None:
        """Open the library once Qt is idle, where its question draws. ▸r/modal-in-pane-build"""
        timer = self._open_library_timer = QtCore.QTimer(self)    # owned, so it dies with the panel
        timer.setSingleShot(True)
        timer.setInterval(0)
        timer.timeout.connect(self._open_at_start)
        timer.start()

    def _open_at_start(self) -> bool:
        """Open the library only with this computer's user picked; `ensure_library_user` asks."""
        return self.open_library(needs_user=True)

    def serves(self, folder: str) -> bool:
        """Whether the models are open on `folder`."""
        return (getattr(self, "material_model", None) is not None
                and hostos.comparable_path(str(getattr(self, "_models_dir", "") or ""))
                == hostos.comparable_path(str(folder or "")))

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
        ok, how = repair.repair_index(folder, self.prefs.asset_dir, guard=False)
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
        ui.displayMessage(messages.LIBRARY_INDEX_REPAIRED % how, title=messages.TITLE_AMAZE)
        debug.event("session", "index repaired", how=how, dir=folder)
        return True

    MENU_ICON_FILES = {    # menu title -> icon asset with a baked-in "opens a menu" triangle
        "View": "icon_renderer.svg",
        "Filter": "icon_view.svg",
    }

    def _ui_icon_path(self, filename: str) -> str:
        """An icon in ui/, or "" for no filename (callers degrade). ▸p/adoption"""
        if not filename:
            return ""
        return amaze.package_file("ui", filename)

    def _make_menu_button(self, menu: QtWidgets.QMenu) -> "ui_helpers.IconMenuButton":
        """An icon button that pops `menu`, standing in for the hidden menu bar's item."""
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
            setattr(self, attr, model)    # shared with every panel on this library; the proxies below are this panel's
        files_actions.connect(self.file_files_model, self.file_folders_model,
                              os_icon=delegates.os_file_icon)
        if getattr(self, "_scene_watch", None) is None:    # one callback per panel, however often setup runs
            self._scene_watch = files_actions.watch_scene(self.file_folders_model)
            self.destroyed.connect(    # holds the callback, never the panel
                functools.partial(files_actions.unwatch_scene, self._scene_watch))
        material_actions.connect(self.material_model)
        self._note_models_library()

        self.category_sorted_model = self._sidebar_proxy(self.category_model)
        self.material_sorted_model, self.material_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(self), self.material_model)
        self.thumb_delegate = delegates.AssetItemDelegate(
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
        self.asset_delegate = delegates.AssetItemDelegate(    # Node and Code: their own delegate, without the version roles
            self.material_model.RendererLabelRole, self.thumblist,
            tile_badges=sections.CopSection.tile_badges,
            tile_model=cop_library.CopLibrary, **node_roles)
        self.code_delegate = delegates.AssetItemDelegate(
            self.material_model.RendererLabelRole, self.thumblist,
            tile_badges=sections.CodeSection.tile_badges,
            tile_model=code_library.CodeLibrary, **node_roles)

        self.file_sorted_model, self.file_selection_model = self._grid_proxy(
            texture_library.TextureFilterProxyModel(self), self.file_files_model)
        self.file_delegate = delegates.AssetItemDelegate(
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
            self._on_file_folder_progress)    # a bound method, never a lambda: the model outlives a closed pane tab

        self.gradient_category_sorted_model = self._sidebar_proxy(
            self.gradient_categories_model)
        self.gradient_sorted_model, self.gradient_selection_model = self._grid_proxy(
            gradient_library.GradientFilterProxyModel(self), self.gradient_model)
        self.gradient_delegate = delegates.AssetItemDelegate(
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

        for _model in (self.material_model, self.cop_model, self.code_model):    # every asset keeps its first category only; idempotent
            try:
                _model.collapse_multicategory()
            except Exception as exc:
                debug.event("session", "category collapse failed",
                            error=str(exc))

        self.matx_online_model = matx_library.MatxOnlineLibrary(    # the online MaterialX browser, with MaterialLibrary's role numbers
            preferences=self.prefs
        )
        self.matx_sorted_model, self.matx_selection_model = self._grid_proxy(
            multifilterproxy_model.MultiFilterProxyModel(self), self.matx_online_model)
        self.matx_source_model = matx_library.MatxSidebarModel(
            self.matx_online_model
        )
        self.matx_delegate = delegates.AssetItemDelegate(    # the online world's own delegate, with only the roles its model has
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
        self.online_context = sections.OnlineContext(self)    # a Section's interface, not in `sections`; `_section()` reaches it

        for _notes_selection in (    # keyboard selection moves reach the Notes pane too
            self.material_selection_model,
            self.cop_selection_model,
            self.code_selection_model,
            self.file_selection_model,
            self.gradient_selection_model,
        ):
            _notes_selection.selectionChanged.connect(
                self._refresh_notes_subject)

        self.sections = sections.build_sections(self)    # one object per tab; shared handlers dispatch through self._section()

        self.sidebar_reorder = sidebar.SidebarReorder(self)    # the press-hold sidebar reorder

        first_key = next(    # the first enabled section
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
        """Library ▸ Set Library: Preferences on its Library tab, where a library is picked with its user."""
        self.show_prefs()
        dialog = getattr(self, "_prefs_dialog", None)
        if dialog is not None:
            dialog.show_frame("P01")

    def takes_library(self, folder: str) -> bool:
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

    def open_library(self, needs_user: bool = False) -> bool:
        """Every way onto a library, in one order; False when it stays closed."""
        if self._library_too_new():
            return self._stay_closed()    # the update is offered once Qt is idle
        if (library_actions.index_unreadable(self.prefs.dir)
                and not self._repaired(self.prefs.dir)):
            return self._stay_closed()
        library_actions.prepare(self.prefs)
        if not library_actions.index_present(self.prefs.dir):    # prepare could not set one up
            return self._stay_closed()
        if needs_user and users.current(self.prefs) is None:
            debug.event("session", "library not opened - no user picked", dir=self.prefs.dir)
            return self._stay_closed()    # opened from Preferences, with its user
        why = self._open_models()
        if why:
            return self._stay_closed(why)
        texstore.publish_env(self.prefs)    # $AMAZELIB names the library the models now serve
        self._update_library()    # before any tile paints
        self._seed_curated_content()    # once per library, marker-guarded
        if not self.prefs.test_mode and self.prefs.note_library_opened(self.prefs.real_dir):
            self.prefs.save()    # the Library list, the most recently opened first
        return True

    def _open_models(self) -> str:
        """The models' step of `open_library`: "" once they serve `prefs.dir`, else why not."""
        try:
            if getattr(self, "material_model", None) is None:
                self.setup()    # the libraryless shape has no models to switch
            else:
                self.switch_all_models()
        except (OSError, ValueError, KeyError) as exc:    # a list that is there and will not open
            debug.exception("library open", exc, dir=self.prefs.dir)
            return (library_actions.index_unopenable(self.prefs.dir)
                    or messages.LIBRARY_LIST_NOT_LOADED % exc)
        return ""

    def _stay_closed(self, why: str = "") -> bool:
        """False; an open library is kept, its Library Path and Test Library put back, `why` said."""
        switching = getattr(self, "material_model", None) is not None
        if switching:
            real, test_mode, test_dir = self._models_pointers
            self.prefs.test_dir = test_dir
            self.prefs.dir = real
            self.prefs.test_mode = test_mode    # last, so the shared settings adopted are that library's
            self.prefs.save()
            debug.event("session", "library kept", dir=self.prefs.dir)
        if why:    # deferred by the sink: a modal inside the pane's build draws black ▸r/modal-in-pane-build
            debug.refuse(debug.Damage(messages.LIBRARY_NOT_OPENED_SWITCHING % why if switching
                                      else messages.LIBRARY_NOT_OPENED % why))
        return False

    def _note_models_library(self) -> None:
        """The library the models now serve, for closing Preferences and for a Cancel."""
        self._models_dir = self.prefs.dir
        self._models_pointers = (self.prefs.real_dir, self.prefs.test_mode, self.prefs.test_dir)

    def library_models(self) -> tuple:
        """Every library-backed model that exists now, from each section's `library_model_attrs`."""
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
        locations.forget()    # drops every cached store table and re-arms the migration retries
        models = self.library_models()
        if not models:
            return
        self.prefs.load()    # the switch's one read of the settings; every model takes this Prefs
        with ui_helpers.relayout(*models), database.one_read_per_file():    # grid and sidebar share one read
            for m in models:
                m.preferences = self.prefs    # a shared model may hold another panel's ▸p/one-model-set
                m.switch_model_data()
            model_registry.rebind(self.prefs, self.material_model)    # the shared set, re-filed under the tree it now serves
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
        button = getattr(self, "btn_categories", None)    # the chip, kept in step whichever side moved
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
        """Amber while in the online world, the family blue when not."""
        button = getattr(self, "btn_online", None)
        if button is None:
            return
        button.set_art(
            self._ui_icon_path("icon_online.svg"),
            lighten_on_hover=False,
            recolour_on={ui_helpers.IconMenuButton.IDLE_BODY:
                         theme.color_hex("star")})

    def _sync_categories_button_pixmaps(self) -> None:
        """The chip's four states, in the toolbar icon family's own tints."""
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
        """Point both grid views at one context's proxy, selection model and delegate."""
        for view in (self.thumblist, getattr(self, "thumbtable", None)):
            if view is None:
                continue
            view.setModel(proxy)
            if selection is not None:
                view.setSelectionModel(selection)
        grid.sync_sort_indicator(self)    # the header's arrow follows this proxy's sort
        if delegate is not None:
            self.thumblist.setItemDelegate(delegate)
            grid.bind_table_cell_delegates(self, delegate)    # per column, picture and ticks only; never the tile delegate

    _LIST = amazetheme.drawn_list()    # header, heading inset and column widths are L01's ▸r/list-from-frame
    _TOOLBAR = amazetheme.drawn_toolbar()    # the toolbar's height, edges, gaps and sizes are B01's
    _SIDEBAR = amazetheme.drawn_sidebar()    # the sidebar's width and its splitter handle are G01's
    CELL_PAD = theme.ui_px(_LIST["cell_pad"])    #: a heading's inset from its column edge; row text is the style's
    HEADER_BG = QtGui.QColor(amazetheme.LIST_HEADER_BG)    #: the header strip's own colours and height
    HEADER_DIVIDER = QtGui.QColor(amazetheme.LIST_HEADER_DIVIDER)
    HEADER_HEIGHT = theme.ui_px(_LIST["header_h"])

    def sync_list_columns(self) -> None:
        """Re-fit list mode's columns for the context now showing; every `activate()` calls it."""
        return grid.sync_table_columns(self)

    COLUMN_DEFAULT_WIDTH = dict(_LIST["widths"], thumb=24)    #: starting widths; "thumb" is never shown, so L01 draws no column for it

    COLUMN_MIN_WIDTH = 24    #: the floor for every column; Qt has no per-column minimum

    def apply_view_mode(self) -> None:
        grid.apply_view_mode(self)
        empty_state.track(self)    # the blank re-attaches to the view now up

    def showEvent(self, event):
        """On the FIRST show only: `panel visible` is written once the grid's first paint returned."""
        super(AmazePanel, self).showEvent(event)
        if self._first_show_logged:
            return
        self._first_show_logged = True
        QtCore.QTimer.singleShot(0, self.ensure_library_user)    # after the first paint: a modal from a half-built panel blocks its paint
        t0 = getattr(self, "_construct_t0", None)
        if t0 is None:
            return

        def _record():
            debug.event(
                "session", "panel visible",
                construct_to_painted_ms=round(
                    (time.perf_counter() - t0) * 1000, 1))

        _FirstPaint(grid.visible_view(self).viewport(), _record)

    def ensure_library_user(self) -> str:
        """After the first paint: this computer's user, or the question that opens Preferences on Library."""
        preferences = self.prefs
        uid = users.current(preferences)
        if uid or not library_actions.index_present(preferences.dir):
            return uid or ""    # no library to ask about: the pane's own blank says where to set one
        debug.event("users", "no user picked for this library", dir=preferences.dir)
        ui = getattr(hou, "ui", None)
        if ui is not None and ui.displayMessage(
                messages.NO_USER_PICKED, buttons=messages.BUTTONS_OPEN_PREFERENCES,
                default_choice=0, close_choice=1, title=messages.TITLE_AMAZE) == 0:
            self.set_library()
        return ""

    def event(self, event):
        """On DeferredDelete, flush the Comments pane and the pending size save; children get no hide."""
        if event.type() == QtCore.QEvent.Type.DeferredDelete:
            pane = getattr(self, "notes_panel", None)
            if pane is not None:
                pane.flush()
            timer = getattr(self, "_thumbsize_save_timer", None)
            if timer is not None and timer.isActive():    # the debounce dies with its parent, so it is flushed
                timer.stop()
                self.prefs.save()
        return super(AmazePanel, self).event(event)

    def eventFilter(self, watched, event):
        """Hover tracking for the grid's button badges, and nothing else."""
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
        """Light the button badge under the cursor; repaints only when that changed."""
        delegate = self.thumblist.itemDelegate()    # the active delegate, never thumb_delegate by name
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






    LIST_THUMB_SIZE = 16    # list mode's one size; `thumbsize_list` is still written, never read

    def _sync_slider_for_mode(self) -> None:
        """The slider drives grid only; in list it is greyed and parked at its minimum."""
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
        self.click_slider.setValue(grid.active_thumbsize(self))    # the new mode's remembered size; fires slide() only on a change
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
            idx = getattr(    # the slider goes right after the filter box
                self, "_after_filter_index", self.toolbar_layout.count()
            )
            self.toolbar_layout.insertSpacing(idx, theme.ui_px(self._TOOLBAR["slider_gap"]))
            self.toolbar_layout.insertWidget(idx + 1, self.click_slider)
            self.toolbar_layout.insertSpacing(idx + 2, theme.ui_px(self._TOOLBAR["slider_gap"]))
        self._thumbsize_save_timer = QtCore.QTimer(self)    # debounces saving the per-mode icon size during a drag
        self._thumbsize_save_timer.setSingleShot(True)
        self._thumbsize_save_timer.setInterval(500)
        self._thumbsize_save_timer.timeout.connect(self.prefs.save)
        self.click_slider.valueChanged.connect(self.slide)

        self._mirror_toolbar()    # mirrors the toolbar row: every toolbar_layout addition must be done

        self.thumblist.customContextMenuRequested.connect(self.thumblist_rc_menu)
        self.cat_list.customContextMenuRequested.connect(self.catlist_rc_menu)

        mainlayout = QtWidgets.QVBoxLayout()
        mainlayout.addWidget(self.ui)
        mainlayout.setContentsMargins(0, 0, 0, 0)  # Remove Margins

        self.setLayout(mainlayout)

    def _build_menus(self) -> None:
        """The View and Renderer menus, and the toolbar buttons that own them."""
        self.menu.addMenu(self.menu_filter)
        if self.toolbar_layout is not None:
            menu_view = self.ui.findChild(QtWidgets.QMenu, "menuView")
            self.btn_notes = ui_helpers.ChipToggleButton(name="btn_notes")    # built first; the row is mirrored after
            self.btn_notes.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_COMMENTS))
            self._sync_notes_button_pixmaps()
            self.btn_notes.setChecked(bool(self.prefs.show_notes))
            self.btn_notes.toggled.connect(self._on_notes_toggled)    # after the initial state, so restoring it saves nothing
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
            self.btn_filter = self._make_menu_button(self.menu_filter)    # on self: disabled online, its tooltip per section
            self.toolbar_layout.addWidget(self.btn_filter)
            if menu_view is not None:
                self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))
                btn_view = self._make_menu_button(menu_view)
                btn_view.setToolTip(ui_helpers.tooltip_text(
                    tooltips.PANEL_VIEW_MENU))
                self.toolbar_layout.addWidget(btn_view)
                self.online_view_menu = QtWidgets.QMenu(self.ui)    # the online eye's menu; _sync_toolbar swaps it onto btn_filter
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
        self.filter_action_group = None    # build_filter_menu fills the Filter menu on every section change
        self.filter_actions = {}
        self.filter_values = {}

        self.view_actions = {}    # stays empty: grid.sync_view_mode_controls keeps whatever is in it
        menu_view = self.ui.findChild(QtWidgets.QMenu, "menuView")
        if menu_view is not None:
            for a in list(menu_view.actions()):
                if a.isSeparator():
                    menu_view.removeAction(a)
            self.action_catview.setText("Show Categories")
            self.show_cat_group = QtGui.QActionGroup(self)    # draws a circle, not a checkmark; still a free on/off toggle
            self.show_cat_group.setExclusionPolicy(
                QtGui.QActionGroup.ExclusionPolicy.ExclusiveOptional
            )
            self.show_cat_group.addAction(self.action_catview)

            self.online_source_group = QtGui.QActionGroup(self)    # Material Library and the online sources, one exclusive group
            self.online_source_group.setExclusive(True)
            self.action_material_library = QtGui.QAction(
                "Material Library", self
            )
            self.action_material_library.setCheckable(True)
            self.action_material_library.setChecked(True)
            self.online_source_group.addAction(self.action_material_library)    # not in the menu; the group's default, "the local library"

            self.online_menu = menu_view    # no submenu: the importers below
            self.online_source_actions = {}    # stays empty: open_online_source finds no row to tick
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
            self.online_menu.addSeparator()    # generating gets its own group
            self.action_generate_material = self.online_menu.addAction(
                "Generate Material"
            )
            self.action_generate_material.triggered.connect(
                self.generate_random_material
            )
            menu_view.removeAction(self.action_catview)    # the action stays, driven by the toolbar chip; only its row goes
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
            self.cb_viewmode.set_art(    # both hover variants whiten
                self._ui_icon_path("grid.svg"),
                self._ui_icon_path("list.svg"),
            )
        except (TypeError, AttributeError):
            pass

    def _build_splitter_and_sidebar(self) -> None:
        """The splitter proportions and the category sidebar's palette."""
        self._section_view_state = {}    # per-section sidebar choice and grid scroll, in memory only
        splitter = self.cat_list.parentWidget()
        cat_index = -1
        if isinstance(splitter, QtWidgets.QSplitter):
            cat_index = splitter.indexOf(self.cat_list)
            self.notes_panel = notes_panel.NotesPanel(self.prefs)    # the splitter's rightmost pane: sidebar | grid | notes
            splitter.addWidget(self.notes_panel)
            self.notes_panel.adopt_look(self.cat_list)
            splitter.splitterMoved.connect(self._on_splitter_moved)
            self.notes_panel.changed.connect(self._on_note_saved)
            self.notes_panel.setVisible(bool(self.prefs.show_notes))
            splitter.setHandleWidth(theme.ui_px(self._SIDEBAR["handle"]))    # width only; Houdini draws the grip ▸r/sidebar-from-frame
        self.cat_wrapper = ui_helpers.HeldPane(    # holds its width: the remembered drag, or the design width
            self.prefs, "sidebar_width", theme.ui_px(self._SIDEBAR["width"]))
        self.cat_wrapper.setMaximumWidth(theme.ui_px(self._SIDEBAR["width"]))    # the pane's cap ▸r/sidebar-from-frame
        self.cat_list.setMaximumWidth(theme.ui_px(self._SIDEBAR["width"]))    # and the list's, at UI scale
        self.cat_wrapper.setAutoFillBackground(True)    # backdrop by palette; a stylesheet here would restyle cat_list
        cat_wrapper_palette = self.cat_wrapper.palette()
        cat_wrapper_palette.setColor(QtGui.QPalette.ColorRole.Window, theme.color("surface_low"))
        self.cat_wrapper.setPalette(cat_wrapper_palette)
        cat_wrapper_layout = QtWidgets.QVBoxLayout(self.cat_wrapper)
        cat_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        cat_wrapper_layout.setSpacing(0)

        cat_wrapper_layout.addWidget(self.cat_list)
        if splitter is not None and cat_index >= 0:
            splitter.insertWidget(cat_index, self.cat_wrapper)    # the grid is the only flexible pane; the other two hold their width
            held = (self.cat_wrapper, getattr(self, "notes_panel", None))
            for i in range(splitter.count()):
                flexible = splitter.widget(i) not in held
                splitter.setStretchFactor(i, 1 if flexible else 0)

    def _build_sidebar_palette(self) -> None:
        """The category list's palette and selection colours."""
        self.cat_list = self.ui.catview  # type: ignore
        cat_list_palette = self.cat_list.palette()    # palette, never a stylesheet: the viewport paints from Base/Text
        cat_list_palette.setColor(
            QtGui.QPalette.ColorRole.Base, theme.color("surface_low")
        )
        cat_list_palette.setColor(
            QtGui.QPalette.ColorRole.Text, delegates.AssetItemDelegate.TEXT_COLOR
        )
        self.cat_list.setPalette(cat_list_palette)    # no selection colours: Houdini's style sheet paints them
        self.sidebar_delegate = delegates.SidebarItemDelegate(self.cat_list)    # name, count, colour bar
        self.sidebar_delegate.color_role = category.SIDEBAR_COLOR_ROLE    # only asset sidebars answer it

    def init_ui(self) -> None:
        """Creates the panel-view on load"""
        self.ui = ui_helpers.load_ui(
            amaze.package_file("ui", "amaze.ui"),
            dragdrop_widgets.DragDropCentralWidget,
            dragdrop_widgets.DragDropListView,
            sidebar.SidebarTreeView)

        try:
            self.ui.setStyleSheet(hou.qt.styleSheet())    # standard widgets render as native Houdini
        except AttributeError:
            pass
        self.ui.setMinimumSize(theme.ui_px(MIN_PANEL_WIDTH), 0)    # width only
        self.ui.setSizePolicy(    # vertical Ignored, so the pane clips downward; horizontal keeps the minimum
            QtWidgets.QSizePolicy.Policy.Minimum,
            QtWidgets.QSizePolicy.Policy.Ignored,
        )

        try:
            self.ui.setFont(theme.ui_font(hou.qt.mainWindow().font()))    # the size floor is theme's alone; no `hou.qt` under hython
        except AttributeError:
            pass

        self.menu = self.ui.findChild(QtWidgets.QMenuBar, "menubar")    # hidden below; never styled
        self.action_prefs = self.ui.action_prefs  # type: ignore
        self.action_prefs.triggered.connect(self.show_prefs)

        self.action_catview = self.ui.action_show_cat  # type: ignore
        self.action_catview.triggered.connect(self.toggle_catview)

        self.action_check_library = self.ui.action_check_library  # type: ignore
        self.action_check_library.triggered.connect(self.check_library)

        self.action_open_folder = self.ui.action_open_folder  # type: ignore
        self.action_open_folder.triggered.connect(self.open_usdlib_folder)

        self.action_open = self.ui.action_open  # type: ignore
        self.action_open.triggered.connect(self.open)

        self.action_set_library = self.ui.action_set_library  # type: ignore
        self.action_set_library.triggered.connect(self.set_library)

        self.centralwidget = self.ui.centralwidget  # type: ignore

        self._central_layout = self.centralwidget.layout()
        self.toolbar_layout = None
        if self._central_layout is not None:
            if self.menu is not None:    # hidden; its menus open from the toolbar buttons
                self.menu.setVisible(False)
            filter_row = self.ui.findChild(QtWidgets.QHBoxLayout, "horizontalLayout")
            self.toolbar_row = QtWidgets.QWidget()
            self.toolbar_row.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_StyledBackground, True
            )
            self.toolbar_row.setStyleSheet(    # `border: none` first, or Houdini's sheet adds a border; QSS px are unscaled
                "background-color: " + theme.color_hex("surface")
                + "; border: none;"
                + " border-bottom: 1px solid "
                + theme.color_hex("field") + ";"
            )
            self.toolbar_row.setFixedHeight(theme.ui_px(self._TOOLBAR["height"]))    # ▸r/toolbar-from-frame
            self.toolbar_layout = QtWidgets.QHBoxLayout(self.toolbar_row)
            self.toolbar_layout.setContentsMargins(0, 0, theme.ui_px(self._TOOLBAR["edge"]), 0)
            self.toolbar_layout.setSpacing(0)

            self.toolbar_layout.addStretch()    # pushes the controls to one end

            if filter_row is not None:
                self._central_layout.removeItem(filter_row)
            self._central_layout.insertWidget(0, self.toolbar_row)

        self.thumblist = self.ui.thumbview  # type: ignore
        self.thumblist.setVerticalScrollMode(    # per pixel, not per item
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.thumblist.setHorizontalScrollMode(    # both axes
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.thumblist.setUniformItemSizes(True)    # Qt lays out by arithmetic, not per item
        self.thumblist.setLayoutMode(    # single pass, so a repaint never collapses the scroll range
            QtWidgets.QListView.LayoutMode.SinglePass
        )
        self.thumblist.setSizeAdjustPolicy(    # the size hint does not follow the content
            QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self.thumblist.setMovement(QtWidgets.QListView.Movement.Static)    # tiles are never rearranged
        self.thumblist.setDragDropMode(    # drags out to Houdini only
            QtWidgets.QAbstractItemView.DragDropMode.DragOnly
        )
        self.thumblist.setDragDropOverwriteMode(False)
        self.thumblist.setAutoScroll(False)    # selecting a tile never moves the grid
        self.thumblist.viewport().setMouseTracking(True)    # button-free moves light the badges
        self.thumblist.viewport().installEventFilter(self)
        self.thumblist.doubleClicked.connect(self.import_asset_auto)
        self.thumblist.clicked.connect(self._refresh_notes_subject)    # idempotent
        thumblist_palette = self.thumblist.palette()    # Houdini paints the ground; Base is what ink reads
        thumblist_palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(amazetheme.GRID_GROUND))
        self.thumblist.setPalette(thumblist_palette)

        self.texture_progress = ui_helpers.ThinProgressBar()    # the thin bar above thumbview, hidden until there is work
        self.texture_progress.set_accent_color(theme.accent(self.prefs.accent_color))
        self.set_conversion_bar_visible(False)
        husk_job.jobs.progressed.connect(self._on_render_progress)    # bound: jobs outlive the pane
        husk_job.jobs.activeChanged.connect(self._on_render_active)
        thumb_layout = self.ui.findChild(QtWidgets.QVBoxLayout, "verticalLayout_7")
        if thumb_layout is not None:
            thumb_layout.insertWidget(0, self.texture_progress)

        self.thumbtable = dragdrop_widgets.DragDropTableView()    # list mode: a second view sharing the grid's proxy and selection model
        self.thumbtable.setObjectName("thumbtable")
        self.thumbtable.setHorizontalHeader(    # before `grid.style_table_header` styles it
            ui_helpers.GridHeaderView(
                QtCore.Qt.Orientation.Horizontal, self.thumbtable))
        self.thumbtable.setVisible(False)
        if thumb_layout is not None:
            thumb_layout.addWidget(self.thumbtable)
        grid.style_table_header(self)
        self.thumbtable.setContextMenuPolicy(    # the grid's menu and primary action
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbtable.customContextMenuRequested.connect(
            self.thumblist_rc_menu)
        self.thumbtable.doubleClicked.connect(self.import_asset_auto)

        self._build_sidebar_palette()
        self.sidebar_delegate.set_drag_color(
            theme.accent(self.prefs.accent_color)
        )
        self.cat_list.setItemDelegate(self.sidebar_delegate)
        self.cat_list.clicked.connect(self.update_selected_cat)
        self._cat_drop_filter = dragdrop_widgets.CategoryDropFilter(    # the sidebar as a drop target for recategorising grid assets
            self.cat_list, self
        )

        self.line_filter = self.ui.line_filter  # type: ignore
        self._filter_timer = QtCore.QTimer(self)    # only `textEdited` starts it, never setText ▸p/filter-pass-cost
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self.filter_thumb_view)
        self.line_filter.textEdited.connect(
            lambda _text: self._filter_timer.start())
        self.line_filter.setPlaceholderText(sections.Section.search_hint)    # every hint is ""
        self.line_filter.setToolTip(ui_helpers.tooltip_text(
            tooltips.PANEL_SEARCH))
        self.line_filter.setStyleSheet(    # on the widget itself, never an ancestor; room for the icon
            "QLineEdit { border: none; background-color: "
            + theme.color_hex("field")
            + "; padding-left: %dpx; }" % theme.ui_px(20)
        )
        self.line_filter.setFixedHeight(theme.ui_px(self._TOOLBAR["field_h"]))    # ▸r/toolbar-from-frame
        self.line_filter.setMinimumWidth(theme.ui_px(38))    # overrides the .ui's own 80 minimum - setMinimumWidth wins at runtime
        self.line_filter.setMaximumWidth(theme.ui_px(self._TOOLBAR["field_w"]))
        try:    # the magnifier: an overlay QLabel pinned at an exact margin
            filter_icon_path = self._ui_icon_path("icon_search.svg")
            if filter_icon_path and os.path.exists(filter_icon_path):
                icon_size = theme.ui_px(self._TOOLBAR["search_icon"])
                pixmap = ui_helpers.render_svg_pixmap(    # the package's one SVG rasteriser ▸r/qicon-svg-engine
                    filter_icon_path, icon_size
                )
                self.filter_icon_label = QtWidgets.QLabel(self.line_filter)
                self.filter_icon_label.setPixmap(pixmap)
                self.filter_icon_label.resize(icon_size, icon_size)
                self.filter_icon_label.setAttribute(
                    QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
                )
                self.filter_icon_label.setAttribute(    # with the sheet below, no label background
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
            self.filter_label = QtWidgets.QLabel("Search")    # a real QLabel beside the box
            self.filter_label.setObjectName("filter_label")
            self.filter_label.setStyleSheet(
                "color: " + theme.color_hex("text_bright") + ";"
            )
            self.toolbar_layout.addWidget(self.filter_label)
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["label_gap"]))
            self.toolbar_layout.addWidget(self.line_filter)
            self._after_filter_index = self.toolbar_layout.count()    # where the size slider goes in later

        self.current_section = "material"
        self._build_splitter_and_sidebar()    # catview moves into a new wrapper, in its old place
        self.section_tabs = None
        self._build_section_tabs()    # the strip below the toolbar, rebuilt when enabled_sections changes
        self.ui.cb_FavsOnly.setVisible(False)  # type: ignore  -- unused; the chip below replaces it
        self._build_view_toggles()
        self.cb_viewmode.toggled.connect(self.on_viewmode_button)
        if self.toolbar_layout is not None:
            self.toolbar_layout.addWidget(self.cb_viewmode)
            self.toolbar_layout.addSpacing(theme.ui_px(self._TOOLBAR["gap"]))

        self.ui.details_widget.setParent(None)  # type: ignore  -- out of the splitter, not hidden ▸p/d03-retired

        self.menu_filter = QtWidgets.QMenu("Filter", self.menu)    # each section fills it
        self._build_menus()

        self.ui.slide_iconSize.setVisible(False)  # type: ignore  -- the ClickSlider below replaces it

        self.click_slider = ui_helpers.ClickSlider()
        self.click_slider.setObjectName("click_slider")    # _sync_slider_for_mode owns its tooltip
        self.click_slider.setOrientation(QtCore.Qt.Horizontal)  # type: ignore
        self.click_slider.setRange(64, 512)    # grid only; a tile below 64 is smaller than its badges
        self.click_slider.setValue(ui_helpers.ClickSlider.DEFAULT_VALUE)
        self.click_slider.setSingleStep(50)
        self.click_slider.setPageStep(50)
        self.click_slider.set_accent_color(theme.accent(self.prefs.accent_color))
        self.click_slider.setMinimumWidth(theme.ui_px(38))    # same sizing rule as the filter box: 400px rendered max, 75px min
        self.click_slider.stepped = self.prefs.step_size
        self._build_slider_and_layout()

    def _mirror_toolbar(self) -> None:
        """A trial layout: the toolbar row mirrored to flow from the left; deleting it ends the trial."""
        if self.toolbar_layout is None:
            return
        items = []
        while self.toolbar_layout.count():
            items.append(self.toolbar_layout.takeAt(0))
        for item in reversed(items):
            self.toolbar_layout.addItem(item)
        i_box = self.toolbar_layout.indexOf(self.line_filter)
        i_label = self.toolbar_layout.indexOf(self.filter_label)
        if i_box >= 0 and i_label == i_box + 2:    # the label still reads before its box; strict adjacency only
            label_item = self.toolbar_layout.takeAt(i_label)
            gap_item = self.toolbar_layout.takeAt(i_label - 1)
            self.toolbar_layout.insertItem(i_box, gap_item)
            self.toolbar_layout.insertItem(i_box, label_item)
        self._move_to_toolbar_end(getattr(self, "btn_hip_capture", None))    # capture stays the outermost control
        self._move_to_toolbar_end(self._toolbar_widget("btn_prefs"))    # capture first, then the gear, so the row ends ... stretch, Capture, gear

        edge = theme.ui_px(self._TOOLBAR["edge"])    # both edges hold a control once the capture button is back at the end
        self.toolbar_layout.setContentsMargins(edge, 0, edge, 0)

    def _toolbar_widget(self, name: str):
        """A toolbar widget by objectName, or None."""
        for i in range(self.toolbar_layout.count()):
            item = self.toolbar_layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None and widget.objectName() == name:
                return widget
        return None

    def _move_to_toolbar_end(self, widget) -> None:
        """Move one control and the gap after it to the end of the mirrored row."""
        if widget is None:
            return
        index = self.toolbar_layout.indexOf(widget)
        if index < 0:
            return
        item = self.toolbar_layout.takeAt(index)
        gap_item = None
        if index < self.toolbar_layout.count():    # its gap follows it after the reversal; strict adjacency only
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
        for elem in range(model.rowCount()):    # the source model, never the proxy, which hides empty ones
            cidx = model.index(elem, 0)
            name = model.data(cidx, model.CatSortRole)    # STORED: "_WIP" displays as WIP
            if name and not category.is_all(name):
                names.append(str(name))
        return sorted(names, key=lambda name: category.display_name(name).lower())

    def assign_category_active(self, category: str) -> None:
        """Replace the category of the active section's selected assets; a drop on the sidebar."""
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
        """Move the selected gradients to a category, the seeded palettes included."""
        rows = [
            self.gradient_sorted_model.mapToSource(i).row()
            for i in grid_columns.selected_rows(self.gradient_selection_model)
        ]
        moved = self.gradient_model.set_user_category(rows, category)
        if moved:
            self._refresh_sidebar_categories()

    def _grid_geometry(self) -> dict:
        """The numbers that change when the grid moves: viewport, scroll range, grid step, size hint."""
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
        watch = self._grid_geometry() if debug.is_on() else None    # debug only: logs a right-click that moved the grid
        try:
            self._thumblist_rc_menu()
        finally:
            if watch is not None:
                after = self._grid_geometry()
                if after != watch:
                    debug.event("grid", "geometry changed by right-click",
                                before=watch, after=after)

    def _thumblist_rc_menu(self) -> None:
        """The menu itself, from the active context's `GRID_MENU`."""
        context = self._section()    # the online world too
        if context is not None:
            context.rc_menu()

    def _open_versions_dialog(self, index, proxy, model) -> None:
        """The Versions dialog over `model`'s row at `index`: Select makes the picked one active."""
        from amaze.dialogs import versions_dialog
        row = proxy.mapToSource(index).row()    # `index` is the proxy's
        if not 0 <= row < len(model.assets):    # -1 would index the LAST asset ▸r/model-contracts
            return
        mat = model.assets[row]
        listed, active = model.version_list(row)
        if len(listed) < 2:
            return
        dialog = versions_dialog.VersionsDialog(mat.name, listed, active, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        row = model.find_asset_row_by_id(mat.mat_id)    # the list may have moved under the window
        if dialog.chosen != active and row >= 0:
            model.switch_version(row, dialog.chosen)



    def _scene_path(self, path: str) -> str:
        """A path Amaze writes into the scene, spelled per Write Paths As; never for loads."""
        return helpers.houdini_path(
            path, getattr(self.prefs, "path_style", "home"))

    def copy_file_paths(self, proxy_indexes) -> None:
        """Copy the selection's paths to the clipboard as Houdini paths, one per line."""
        paths = []
        for proxy_index in proxy_indexes:
            path = proxy_index.data(self.file_files_model.PathRole) or ""
            if path:
                paths.append(self._scene_path(path))    # spelled as the session writes parms
        if not paths:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(paths))    # no dialog - the clipboard changing IS the report
        debug.event("file", "paths copied", count=len(paths))

    def catlist_rc_menu(self) -> None:
        """Sidebar right-click - the active context builds its own menu."""
        section = self._section()    # the online world has no SIDEBAR_MENU
        if section is not None:
            section.catlist_menu()


    def _locate_folder_user(self, folders_model) -> None:
        """Sidebar "Locate Folder...": re-point the selected registered folder at a new location."""
        ui = getattr(hou, "ui", None)
        indexes = self.cat_list.selectedIndexes()
        row = indexes[0].row() if indexes and not indexes[0].parent().isValid() else -1    # top rows
        if row <= 0 or not folders_model.registered_at(row):    # nothing selected, All or the scene row: no location
            if ui is not None:
                ui.displayMessage(
                    messages.NO_FOLDER_SELECTED_TO_RELOCATE
                )
            return
        path = ui.selectFile(file_type=hou.fileType.Directory) if ui else ""
        if not path:
            return
        rewritten = folders_model.relocate_folder(
            row, hou.text.expandString(path))    # favorites moved; negative: not a folder
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
        """The unreachable-folder blank's Locate: selects the folder its message names, then re-points it."""
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
        context = self._section()
        if context is not None:
            context.stand_again()    # a Locate cancelled or refused moved only the highlight

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
        """The scene path behind a File-grid index, or '' for a row that is not a scene."""
        if index is None or not index.isValid():
            return ""
        if index.data(self.file_files_model.KindRole) != \
                locations.KIND_HIP:
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
        """The stored name behind a sidebar row, not the displayed one; key every category action on it."""
        if index is None or not index.isValid():
            return ""
        model = self.cat_list.model() if self.cat_list is not None else None
        if model is not None and hasattr(model, "sourceModel"):
            raw = index.data(model.sourceModel().CatSortRole)    # DisplayRole drops a leading "_"
            if raw:
                return str(raw)
        return str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")    # no sourceModel: the displayed name

    def _selected_category_name(self) -> str:
        """The sidebar's category, blank for All: selection, then current index; no section gate."""
        if self.cat_list is None:
            return ""
        indexes = self.cat_list.selectedIndexes()
        index = indexes[0] if indexes else ui_helpers.live_current_index(    # current but not selected after a restore
            self.cat_list)
        name = self._raw_category_name(index)
        return "" if category.is_all(name) else name

    DEFAULT_SIDEBAR_COLOUR = amazetheme.SIDEBAR_PICKER_START

    def ask_category_name(self, title: str, default: str = ""):
        """The category-name dialog: None when cancelled, "" when the field was cleared."""
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
        names = [context.sidebar_key(index)    # stored name, or folder path in File
                 for index in self.cat_list.selectedIndexes()]
        names = [name for name in names    # All is skipped
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
            context.set_sidebar_colour(name, colour)    # the context decides the store and the repaint


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
        """Flip the star on the grid's selection, through the active context's own verb."""
        context = self._section()
        if context is None:
            return
        context.toggle_favourite(list(indexes))

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
        held = {str(mat.mat_id) for mat in model.assets}    # the twins are what arrives after
        for row in (model.find_asset_row_by_id(mat_id) for mat_id in ids):
            if row < 0:
                continue
            mat = model.assets[row]
            if not conversion_engine.has_route(mat.renderer, target):
                continue
            eligible += 1
            sources.add(renderers.normalized(mat.renderer))
            try:
                ok, report = material_actions.convert(model, model.index(row, 0), target,
                                                      render=False)
            except Exception as exc:                          # noqa: BLE001
                lines.append(messages.CONVERSION_CRASHED_LINE % (mat.name, exc))
                continue
            converted += 1 if ok else 0
            lines.extend(report.summary_lines())
        self._render_landed(held)
        shown = " and ".join(renderers.label(source)
                             for source in conversion_engine.targets() if source in sources)
        ui = getattr(hou, "ui", None)
        if ui is not None and eligible:
            ui.displayMessage(messages.CONVERSION_SUMMARY % (
                converted, eligible, shown, renderers.label(target), "\n".join(lines)))

    def _render_landed(self, before: set) -> None:
        """ONE render batch for the materials saved since `before` that have no picture yet."""
        model = self.material_model
        if not model.preferences.render_on_import:    # what a save asked before it rendered alone
            return
        rows = []
        for row, mat in enumerate(model.assets):
            if str(mat.mat_id) in before:
                continue
            path = tile_icons.tile_read_path(model.preferences, str(mat.mat_id), False)
            if path and not os.path.exists(path):    # a hosted picture is already the thumbnail
                rows.append(row)
        material_actions.render_thumbnails(model, rows)    # one husk per renderer ▸r/husk-startup

    def show_prefs(self) -> None:
        """Show Preferences, non-modal, with or without a library; a second open fronts it."""
        if self._thumbsize_save_timer.isActive():    # flush a pending size save first
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
            dlg.setParent(    # floats over Houdini; keep it non-modal
                hou.qt.mainWindow(), QtCore.Qt.WindowType.Dialog
            )
        except AttributeError:
            pass
        dlg.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose, True)    # or repeated opens accumulate hidden instances
        self._prefs_dialog = dlg
        applied = {"done": False}    # `finished` and `destroyed` both arrive; this applies once

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
            self.isVisible()    # the panel may be gone already
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
        for _sidebar_proxy in self.sidebar_proxies():    # every sidebar proxy
            _sidebar_proxy.hide_empty = self.prefs.hide_empty_categories
        self._refresh_sidebar_categories()    # ends in the fall-back to All, should hiding hide its row
        self.cat_list.viewport().update()
        grid.visible_view(self).viewport().update()
        section = self._section()
        if section is not None and not switched:    # a switch has just shown it afresh
            section.prefs_changed()
        self._apply_enabled_sections()    # visible section tabs may have changed in Preferences

    def update_renderer_toggles(self):
        """A renderer was enabled or disabled: the Filter menu is rebuilt whole."""
        if getattr(self, "menu_filter", None) is None:
            return
        self.build_filter_menu()

    def import_package_file(self, path: str, restore: bool = False) -> dict:
        """Import a whole package; `restore=True` keeps original ids. Answers the core summary."""
        from amaze.core import packages
        summary = packages.import_package(self._package_models(),
                                          self.prefs, path,
                                          restore=restore)
        self._absorb_package_summary(summary)
        return summary

    def import_amaze_package(self) -> None:
        """Package Import: the picker, the import, then one summary; no dialog when headless."""
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
        """The `.amazepkg` export path, suffix ensured; "" when headless or cancelled."""
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
        """Every material preset in a .gal file saved as a material; ONE render batch after it."""
        from amaze.core import gallery_import
        ui = getattr(hou, "ui", None)
        if not self.material_model:
            if ui is not None:
                ui.displayMessage(messages.NO_LIBRARY_CONFIGURED)
            return
        picked = ui.selectFile(
            start_directory=gallery_import.default_gallery_dir(),    # opens where Houdini keeps its galleries
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
        renders = self.material_model.preferences.render_on_import    # what import_entries asks
        if renders:
            question = messages.IMPORT_MATERIAL_PRESETS_FROM_RENDERING % (
                len(entries), os.path.basename(picked), listing)
        else:
            question = messages.IMPORT_MATERIAL_PRESETS_FROM % (
                len(entries), os.path.basename(picked), listing)
        choice = ui.displayMessage(
            question, buttons=messages.BUTTONS_IMPORT,
            default_choice=0, close_choice=1,
        ) if ui is not None else 1    # no screen to ask, so the answer is the close_choice - Cancel
        if choice != 0:
            return
        summary, interrupted = {}, False    # import_entries fills OURS, so an Esc keeps what landed
        try:
            with hou.InterruptableOperation(  # type: ignore
                "Importing gallery presets", open_interrupt_dialog=True
            ) as op:
                def progress(index, total, name):
                    op.updateLongProgress(
                        float(index) / max(total, 1),
                        "%d/%d  %s" % (index + 1, total, name),
                    )
                gallery_import.import_entries(
                    functools.partial(material_actions.add_asset, self.material_model),
                    entries, progress=progress, summary=summary,
                    library=self.material_model)    # each save skips its render; ONE batch follows
        except hou.OperationInterrupted:
            interrupted = True
            debug.event("gallery", "import interrupted", **summary)
        for name in sorted(summary.get("categories", {})):
            self.category_model.check_add_category(name)
        self._refresh_sidebar_categories()
        imported, skipped, failed = (summary.get(key, 0) for key in ("imported", "skipped", "failed"))
        if interrupted:
            said = messages.GALLERY_IMPORT_INTERRUPTED % (imported, skipped, failed)
        elif renders:
            said = messages.GALLERY_IMPORT_FINISHED_RENDERING % (imported, skipped, failed)
        else:
            said = messages.GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED % (imported, skipped, failed)
        if ui is not None:
            ui.displayMessage(said)

    def check_library(self) -> None:
        """Library ▸ Check Library…: the report and its actions, every model read again after each."""
        ui = getattr(hou, "ui", None)
        if ui is None:
            return
        if not self.material_model:
            ui.displayMessage(messages.NO_LIBRARY_OPEN)
            return
        from amaze.dialogs import repair_dialog
        repair_dialog.check_in_panel(self)

    def stand_again(self) -> None:
        """The shown section's highlight back on what its grid shows, after the rows were read again."""
        context = self._section()
        if context is not None:
            context.stand_again()

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
        """Register a folder for the File section; stores the path only, nothing is scanned."""
        ui = getattr(hou, "ui", None)
        path = ui.selectFile(file_type=hou.fileType.Directory) if ui else ""
        if not path:
            return
        self.file_folders_model.add_folder(hou.text.expandString(path))

    def unwatch_scene(self) -> None:
        """The scene row stops following the scene; a second call removes nothing."""
        watch, self._scene_watch = getattr(self, "_scene_watch", None), None
        if watch is not None:
            files_actions.unwatch_scene(watch)

    def remove_file_folder_user(self) -> list:
        """Unregister the selected folder pointer(s), answering the paths removed; disk is untouched."""
        folders = self.file_folders_model
        rows = sorted(    # top rows only: a subfolder's row number is no location's
            (i.row() for i in self.cat_list.selectedIndexes() if not i.parent().isValid()),
            reverse=True
        )
        removed = []
        for row in rows:
            path = folders.data(folders.index(row, 0), folders.PathRole)
            if folders.remove_folder(row):
                removed.append(path)
        return removed

    ALL_SECTIONS = section_list.SECTIONS    # (key, label) in order; keys are stored, never rename one

    def _online_segments(self) -> list:
        """The online strip: one tab per source, in source order; enabled_sections does not apply."""
        return [(source.name, source.name)
                for source in matx_sources.all_sources()]

    def _build_section_tabs(self) -> None:
        """(Re)build the one tab strip: the enabled sections, or the online sources while online."""
        if self._is_online():
            segments = self._online_segments()
        else:
            enabled = self.prefs.enabled_sections
            segments = [(k, lbl) for (k, lbl) in self.ALL_SECTIONS
                        if k in enabled]
        if not segments:
            segments = [("material", "Material")]
        if getattr(self, "section_tabs", None) is not None:    # replaces the strip at layout index 1
            if self._central_layout is not None:
                self._central_layout.removeWidget(self.section_tabs)
            self.section_tabs.deleteLater()
        self.section_tabs = ui_helpers.SectionTabBar(segments)
        self.section_tabs.segmentClicked.connect(
            lambda key: self._on_tab_toggled(key, True)
        )
        self.section_tabs.cancelClicked.connect(self._on_cancel_conversions)
        bar = getattr(self, "texture_progress", None)
        self.section_tabs.set_cancel_visible(    # read from the bar, so a rebuild mid-batch agrees
            bar is not None and not bar.isHidden())
        if self._central_layout is not None:
            self._central_layout.insertWidget(1, self.section_tabs)
        keys = [k for k, _ in segments]
        current = (getattr(self, "online_source", None) if self._is_online()
                   else getattr(self, "current_section", "material"))
        self.section_tabs.setChecked(
            current if current in keys else keys[0], emit=False    # setup() activates; models may not exist yet
        )


    def _apply_enabled_sections(self) -> None:
        """Rebuild the strip for enabled_sections; a hidden current section gives way to the first."""
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
        """A tab was clicked: a source online, else a section; an unbuilt section changes nothing."""
        if not checked:
            return
        if self._is_online():
            self.open_online_source(key)
            return
        if self.material_model is None:    # no library yet
            return
        self._capture_section_state()    # the outgoing section's, before anything changes
        self.current_section = key
        debug.event("section", "switched", to=key, online=self._is_online())
        section = self.sections.get(key)
        if section is None:
            debug.event("section", "section not built yet - the view "
                        "below will not change", section=key)
            return
        self._apply_context(section, key)

    def _apply_context(self, context, key: str) -> None:
        """Activate a context and all that follows it; the one path every section and online take."""
        proxy = context.tile_models()[1]
        with proxy.one_pass() if proxy is not None else contextlib.nullcontext():    # every filter set below shares one pass ▸p/filter-pass-cost
            context.activate()
            self._sync_toolbar(context)    # EVERY toolbar control, from the one table - Capture included
            self._sync_filters_to_section(context)
            self._restore_section_state(key)
        self._refresh_notes_subject()
        empty_state.track(self)    # the blank re-attaches to the new model

    def _sync_filters_to_section(self, section) -> None:
        """Push the shared filter box and favourites chip into the incoming section's proxy."""
        text = self.line_filter.text() if self.line_filter else ""
        favourites = bool(self.cb_favsonly and self.cb_favsonly.isChecked())
        section.filter_text(text)
        section.filter_favorites(favourites)
        self.build_filter_menu()    # each section keeps its own menu choice

    def _capture_section_state(self) -> None:
        """Remember the current section's sidebar choice and grid scroll for _restore_section_state."""
        state = {}
        current = ui_helpers.live_current_index(self.cat_list)    # a fresh index, safe for `.data()`
        if current is not None:
            state["cat_text"] = current.data()
        state["scroll"] = grid.visible_view(self).verticalScrollBar().value()
        self._section_view_state[self.current_section] = state

    def _restore_section_state(self, key: str) -> None:
        """Re-select the section's last sidebar entry by display text, and bring its scroll back."""
        state = self._section_view_state.get(key)
        if not state:
            return
        cat_text = state.get("cat_text")
        if (
            cat_text
            and key not in ("file",)    # File restores its folder in activate()
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
                        self.update_selected_cat()    # the handler a real click runs
                        break
        scroll = state.get("scroll")
        if scroll:
            QtCore.QTimer.singleShot(    # after the relayout, which would clamp it
                0,
                lambda: grid.visible_view(self)
                .verticalScrollBar().setValue(scroll),
            )

    TOOLBAR_CONTROLS = (    # (control, context fact, "enabled" or "shown")
        ("cb_favsonly", "takes_favourites", "enabled"),
        ("btn_notes", "takes_comments", "enabled"),
        ("btn_filter", "takes_filter_menu", "enabled"),
        ("btn_hip_capture", "takes_capture", "enabled"),
    )

    def _sync_toolbar(self, context) -> None:
        """Set every toolbar control from TOOLBAR_CONTROLS and what `context` declares."""
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
        if btn_filter is not None:    # online it carries the kind filter
            if getattr(context, "kind_filter_menu", False):
                btn_filter.set_menu(self.online_view_menu)
                btn_filter.setEnabled(True)
                btn_filter.setToolTip(ui_helpers.tooltip_text(
                    tooltips.PANEL_KIND_FILTER))
            else:
                btn_filter.set_menu(self.menu_filter)
        self._sync_filter_placeholder()

    def _sync_filter_placeholder(self) -> None:
        """Set the filter box's placeholder from the active context's `search_hint`."""
        if self.line_filter is None:
            return
        self.line_filter.setPlaceholderText(
            getattr(self._section(), "search_hint",
                    sections.Section.search_hint))

    def _section(self):
        """The active context: a Section, or the online world while that shows."""
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
        online = getattr(self, "matx_delegate", None)    # by name: the online world is not in `sections`
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
        """Whether the online world is showing; the one predicate every handler asks."""
        return bool(getattr(self, "online_mode", False))    # `current_section` still names the local section underneath

    def _on_online_source(self, action) -> None:
        """A material-source entry: Material Library goes local, an online source opens its browser."""
        if action is self.action_material_library:
            self.leave_online_world()
            if self.current_section != "material":
                self.section_tabs.setChecked("material")
        elif action.isChecked():    # the entries share one exclusive group, so Qt keeps exactly one checked
            self.open_online_source(action.text())

    def enter_online_world(self, source: str = "") -> None:
        """Switch to the online world's tab strip; leaving puts you back where you came from."""
        if self._is_online():
            return
        if getattr(self, "matx_online_model", None) is None:    # the door: no online model, no entry
            self._sync_online_chip()
            return
        self._capture_section_state()    # what leaving restores
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
            self._apply_context(section, section.key)    # the one path, as entering takes

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
        if self.section_tabs is not None:    # the source's own tab
            self.section_tabs.setChecked(source_name, emit=False)
        self.matx_online_model.set_source(source_name)
        self.enter_online()
        self._select_online_all()    # a source pick starts on "All"

    def _select_online_all(self) -> None:
        """Select the online sidebar's "All" row and clear any category filter."""
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
        debug.event("online", "exited")    # where you land is the caller's

    def enter_online(self) -> None:
        """Enter the online world through `_apply_context`, the path every section takes."""
        self._apply_context(self.online_context, self.online_context.key)


    @contextlib.contextmanager
    def _download_operation(self, records):
        """The interruptable operation around a multi-record import; yields progress_for(i, name)."""
        total = max(len(records), 1)
        self._online_download_active = True    # a late preview signal must not repaint the bar
        try:
            with hou.InterruptableOperation(    # type: ignore
                messages.IMPORTING_ONLINE_MATERIALS, open_interrupt_dialog=True
            ) as op:
                def progress_for(i, name=""):
                    def on_progress(frac):
                        frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
                        op.updateLongProgress((i + frac) / total,
                                              "%d/%d  %s" % (i + 1, total, name))
                    return on_progress
                yield progress_for
        finally:
            self._online_download_active = False

    def _import_online_records(self, records, renderer=renderers.HUB.key) -> None:
        """Import online records into the LIBRARY, built as `renderer` through the conversion engine."""
        if not len(records):
            return
        total = len(records)
        failures = []
        held = {str(mat.mat_id) for mat in getattr(self.material_model, "assets", ())}
        with self._download_operation(records) as progress_for:
            for i, rec in enumerate(records):
                on_progress = progress_for(i, rec.title)
                try:    # one bad record must not abandon the batch
                    ok, reason = self.import_online_material(
                        rec, on_progress=on_progress, renderer=renderer, render=False
                    )
                except hou.OperationInterrupted:
                    debug.status(messages.ONLINE_IMPORT_STOPPED % (i, total))
                    break
                except Exception as exc:                  # noqa: BLE001
                    debug.exception("online import", exc, record=rec.title)
                    ok, reason = False, str(exc)
                if not ok:
                    failures.append("%s: %s" % (rec.title, reason))
        if self.material_model is not None:
            self._render_landed(held)
        ui = getattr(hou, "ui", None)
        if failures and ui is not None:    # ONE dialog for the batch, never one per record
            ui.displayMessage(
                messages.AMAZE_COULD_NOT
                % (len(failures), total, "\n".join(failures[:10]))
            )

    def import_online_material(self, record, on_progress=None,
                               renderer=renderers.HUB.key, render=True):
        """Download and save one online material as `renderer`, calling on_progress(0..1): (ok, reason)."""
        from amaze.core import matx_import
        if record is None or not self.material_model:
            return (False, messages.NO_LIBRARY_TO_IMPORT_INTO)
        source, resolution, error = self._online_source_for(record)
        if error:
            return (False, error)
        if source is None:
            return (False, messages.ONLINE_SOURCE_UNKNOWN)
        if getattr(record, "kind", "") == "amazepkg":
            return self._import_amaze_package_record(
                record, source, restore=False, on_progress=on_progress)
        ok, reason = matx_import.import_record(    # NO layout pair: it ends in add_asset, an insert
            record, source, resolution, self.material_model, self.prefs,
            progress=on_progress, renderer=renderer,
            save=functools.partial(material_actions.add_asset, self.material_model),
            render=render,    # False: the caller renders its batch once
        )
        if not ok:
            return (False, reason or messages.ONLINE_IMPORT_FAILED)
        self.category_model.check_add_category(record.category)    # no relayout wrapper: it announces its own insert
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
        """Register a package import's categories on their sidebars, and its import folder."""
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
                self.prefs.set_file_folder_kinds(folder, locations.EVERY_KIND)
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
        """One store tile into the library, fresh or restore: (ok, reason); `on_progress` pumps the UI."""
        from amaze.core import packages
        url = record.payload.get("package")
        debug.event("import", "package tile start", title=record.title,
                    package=str(url), restore=bool(restore))
        self._last_package_summary = None    # the restore batch reads its totals here
        try:
            entry = record.payload.get("entry")
            if not entry:
                return (False, messages.STORE_TILE_HAS_NO_ENTRY)
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
                               or messages.STORE_TILE_NOT_IMPORTED)
            if restore and summary.get("skipped"):
                return (True, "")
            if not summary.get("imported") and not summary.get("files"):
                return (False, messages.STORE_TILE_IMPORTED_NOTHING)
            return (True, "")
        except Exception as exc:                          # noqa: BLE001
            debug.exception("package import", exc, record=record.title)
            return (False, str(exc))

    def restore_amaze_packages(self, records) -> dict:
        """Restore the selected store tiles by original id, with one summary for the batch."""
        totals = {"imported": 0, "skipped": 0, "files": 0, "refused": 0}
        failures = []
        with self._download_operation(records) as progress_for:
            for i, record in enumerate(records):
                source, _resolution, error = self._online_source_for(
                    record)
                if error or source is None:
                    failures.append("%s: %s" % (record.title,
                                                error or messages.ONLINE_SOURCE_UNKNOWN))
                    continue
                try:
                    ok, reason = self._import_amaze_package_record(
                        record, source, restore=True,
                        on_progress=progress_for(i, record.title))
                except hou.OperationInterrupted:
                    debug.status(messages.ONLINE_IMPORT_STOPPED % (i, len(records)))
                    break
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
            lines = [messages.STORE_RESTORE_SUMMARY
                     % (totals["imported"], totals["skipped"])]
            if failures:
                lines += [""] + failures[:10]
            ui.displayMessage("\n".join(lines))
        return totals

    def _online_source_for(self, record):
        """The record's source and the resolution to fetch it at: (source, resolution, error)."""
        source = self.matx_online_model.source_for(record)
        if source is None:
            return (None, None, messages.ONLINE_SOURCE_UNKNOWN_NAMED % record.source)
        if not source.needs_download(record):    # ask the source; sources override it
            return (source, None, "")     # nothing to download
        if record.kind in ("values", "amazepkg"):
            return (source, None, "")     # downloads, but picks no resolution
        resolution = matx_sources.pick_resolution(
            source.resolutions(record), self.prefs.matx_resolution
        )
        if resolution is None:
            return (None, None,
                    messages.NO_DOWNLOADABLE_PACKAGE % record.title)
        return (source, resolution, "")

    def _import_online_records_to_scene(self, records,
                                        renderer=renderers.HUB.key) -> None:
        """Build online records into the scene, not the library; store tiles go to the library."""
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
        built, failures, last, stopped_after = [], [], None, None
        ui = getattr(hou, "ui", None)
        with self._download_operation(records) as progress_for:
            with hou.undos.group("Amaze Import to Scene"):    # one undo step, the destination included
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
                    on_progress = progress_for(i, rec.title)

                    try:
                        builder, reason = matx_import.build_in_scene(
                            rec, source, resolution, destination, self.prefs,
                            progress=on_progress, renderer=renderer,
                        )
                    except hou.OperationInterrupted:
                        stopped_after = i
                        break
                    except Exception as exc:           # noqa: BLE001
                        debug.exception("import to scene", exc,
                                        title=rec.title)
                        builder, reason = None, str(exc)    # one bad record must not abandon the batch
                    if builder is None:
                        failures.append("%s: %s" % (rec.title, reason))
                        continue
                    built.append(builder.name())
                    last = builder
                if last is not None:
                    last.setCurrent(True, True)    # fronts the new material
        debug.event("import", "to scene finished", built=len(built),
                    failed=len(failures), stopped_after=stopped_after)
        if ui is not None and failures:
            ui.displayMessage(
                messages.SCENE_BUILD_PARTIAL_FAILURE
                % (len(failures), total, "\n".join(failures[:10]))
            )
        elif ui is not None and last is not None and stopped_after is None:
            ui.setStatusMessage(
                "Amaze: %s in %s" % (", ".join(built[:3]),
                                     last.parent().path())
            )
        if stopped_after is not None:
            debug.status(messages.ONLINE_IMPORT_STOPPED % (stopped_after, total))


    def _select_default_sidebar_row(self, sidebar_proxy):
        """Select the sidebar's first row and return its raw name; the caller applies the filter."""
        if self.cat_list is None or sidebar_proxy is None:
            return None
        if sidebar_proxy.rowCount() <= 0:
            return None
        selection_model = self.cat_list.selectionModel()
        if selection_model is None:
            return None
        target = sidebar_proxy.index(0, 0)
        selection_model.select(    # a `setModel()` leaves nothing selected
            target, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.cat_list.setCurrentIndex(target)
        return self._raw_category_name(target)

    def edit_tile_icon(self, model, proxy, proxy_indexes,
                       categories=()) -> None:
        """Customize on any tile: one handler for every section, applied to the WHOLE selection."""
        from amaze.dialogs import icon_dialog
        if model is None or not proxy_indexes:
            return
        held = []    # tile keys, never rows: the library can move while the dialog is open
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

        existing = getattr(self, "_icon_dialog", None)    # non-modal, one at a time
        if existing is not None:
            try:
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                pass                      # already deleted underneath
        single = len(rows) == 1    # Name only where the model renames, greyed on a multi-selection
        tile_name = None
        if hasattr(model, "set_tile_name"):
            tile_name = model.tile_name(rows[0]) if single else ""
        tile_tags = None    # no field without tags; a multi-selection opens empty
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
            rows = [row for row in range(model.rowCount())    # resolved on commit; a tile gone meanwhile is skipped
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
                dialog.deleteLater()    # the panel parents it, so it must be deleted

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
                % (failed, "" if failed == 1 else "s")    # a real plural
            )


    def import_cop_assets(self) -> None:
        """Import every selected Node tile; what failed is said in one dialog."""
        self._import_selection(
            self.cop_sorted_model, self.cop_model, node_actions.import_asset_to_scene,
            "Amaze Import Nodes Asset", messages.NAMELESS_NODE_ASSET,
            lambda listed: messages.NODE_ASSETS_IMPORT_FAILURES % listed)

    def _import_selection(self, proxy, model, verb, label: str, noun: str, sentence) -> None:
        """Each selected tile through `verb(model, source_index)`: ONE undo entry, one dialog."""
        failures = []
        with hou.undos.group(label):    # the containers and what loads into them revert as one step
            for index in grid_columns.selected_rows(self.thumblist.selectionModel()):
                source_index = proxy.mapToSource(index)
                try:
                    ok, reason, _created = verb(model, source_index)
                except Exception as e:    # one bad tile joins the report; the rest still import
                    try:
                        name = model.assets[source_index.row()].name
                    except Exception:
                        name = noun
                    failures.append(messages.ASSET_FAILED_TO_IMPORT_LINE % (name, e))
                    continue
                if not ok and reason:
                    failures.append(reason)
        ui = getattr(hou, "ui", None)
        if failures and ui is not None:
            ui.displayMessage(sentence("\n".join(failures)))


    def get_code_category_names(self) -> list[str]:
        return self._category_names_from(self.code_category_model)

    def _current_code_category(self) -> str:
        """The sidebar's category while Code shows, "" for All; the code dialog's default."""
        if self.current_section != "code":
            return ""
        return self._selected_category_name()

    def _add_code_snippet(
        self, code: str, language: str, default_name: str
    ) -> None:
        """New Snippet and a node's code: the code dialog, prefilled; each Apply saves the snippet."""
        from amaze.core import library_policy
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
            versions_on=library_policy.allow_overwrite(self.prefs.dir),    # Preferences ▸ Versions
            parent=self,
        )
        self.sections["code"].run_code_dialog(dialog, "")    # the first Apply adds the snippet

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

    def click_on_row(self, section, index, payload=None) -> None:
        """A double-click or its menu entry on `index`, aimed by the selection, per `section`'s rule."""
        if index is None or not index.isValid():
            return
        rule = sections.drop_rule(section, self, index)    # the drag walker's reader
        if rule is None:
            self._cannot_load_here()
            return
        try:
            landed = self._apply_click_rule(section, rule, index,
                                            payload)    # the menu's extra word
        except hou.PermissionError as refusal:    # only this class; anything else still raises
            debug.exception("click refused", refusal,
                            section=getattr(section, "key", ""))
            debug.refuse(str(refusal),    # ▸p/refusal-sink
                         section=getattr(section, "key", ""))
            return
        if not landed:
            self._cannot_load_here()

    def _apply_click_rule(self, section, rule, index, payload=None) -> bool:
        """One selected node is offered the payload first; one that cannot take it falls to creation."""
        extra = {"basis": payload} if payload else {}    # only when there is one
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

    def _commit_cop_save(self, node: hou.Node, dialog) -> None:
        """Works in any context the Nodes section supports; the asset records which one."""
        ui = getattr(hou, "ui", None)
        net = node.parent()
        items = [i for i in hou.selectedItems() if i.parent() == net]
        if not any(i == node for i in items):
            items.append(node)
        if len(items) == 1 and cop_nodes.saves_whole_network(node):    # a container alone saves its network
            items = None

        if dialog.categories:
            self.cop_category_model.check_add_category(dialog.categories)

        result = None
        save_error = None    # no layout wrapper: add_asset announces its own insert
        try:
            result = node_actions.add_asset(
                self.cop_model,
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
        """True for anything whose children are SOPs: a drop-into target for a geometry file."""
        try:
            category = node.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return False
        return category is not None and category.name() == "Sop"

    @staticmethod
    def _create_loader_inside(container: hou.Node, loader_type: str):
        """Create the loader in the deepest SOP network under the container, falling outward."""
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
        for _depth, net in sorted(candidates, key=lambda c: -c[0]):    # deepest first; a locked level refuses
            try:
                return net.createNode(loader_type)
            except hou.Error as exc:
                last_error = exc
        raise last_error or hou.OperationFailed("no SOP network found")

    def import_geo_asset(self, index: QtCore.QModelIndex) -> None:
        """Import a geometry file into the network the user looks at, per its kind."""
        path = index.data(self.file_files_model.PathRole)
        if not path:
            return
        self._import_geo_in_context(path, self._active_network_pwd())

    def _import_geo_in_context(
        self, path: str, dest: hou.Node | None
    ) -> hou.Node | None:
        from amaze.helpers import helpers
        base = os.path.basename(path)
        name = wording.sanitize_usd_path(os.path.splitext(base)[0]) or "geo"
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
            if category == "Sop":    # inside a SOP network: a loader SOP in place
                loader = dest.createNode(loader_type)
            elif category == "Lop":    # a new SOP Create holding the loader
                anchor = None
                try:
                    anchor = dest.displayNode()
                except (AttributeError, hou.OperationFailed):
                    anchor = None
                if anchor is not None:
                    container = anchor.createOutputNode("sopcreate", name)    # chained onto the display node
                else:
                    container = dest.createNode("sopcreate", name)
                loader = self._create_loader_inside(container, loader_type)
            elif category == "Object":    # a new geo named after the file
                container = dest.createNode("geo", name)
                loader = container.createNode(loader_type)
            else:    # a network that holds no geometry: a fresh geo at /obj
                obj = hou.node("/obj")
                if obj is None:
                    raise hou.OperationFailed("no /obj network")
                container = obj.createNode("geo", name)
                loader = container.createNode(loader_type)
        except hou.Error as exc:    # hou.Error: a locked asset raises PermissionError, a sibling
            if container is not None:
                try:
                    container.destroy()
                except (hou.OperationFailed, hou.ObjectWasDeleted):
                    pass
            debug.event("import", "geometry import failed",
                        file=base, error=str(exc))
            debug.refuse(messages.GEOMETRY_IMPORT_FAILED % (base, exc))    # ▸p/refusal-sink
            return
        parm = helpers.find_file_parm(loader)
        if parm is None:
            try:
                (container or loader).destroy()
            except (hou.OperationFailed, hou.ObjectWasDeleted):
                pass
            debug.refuse(messages.LOADER_SOP_HAS_NO_FILE_PARM % loader_type)
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
                container.setDisplayFlag(True)    # createOutputNode wires but does not flag
            except (AttributeError, hou.Error):
                pass
        made = container or loader
        made.setCurrent(True, True)    # current and selected, as a node from the Tab menu is
        return made

    def _drop_context_under_cursor(
        self, matcher, include_viewports: bool = False    # a type-name substring, or a callable(node) -> bool
    ) -> hou.Node | None:
        """Where a drag was released: the matching node under the cursor, else the pwd, else None."""
        pane_tab, pane_type = self._pane_and_kind_under_cursor()
        if pane_tab is None:
            return None
        if (
            include_viewports    # a viewport release resolves to its pwd
            and pane_type == hou.paneTabType.SceneViewer
        ):
            try:
                return pane_tab.pwd()
            except AttributeError:
                return None
        if pane_type != hou.paneTabType.NetworkEditor:    # the canvas takes no native node drops
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
        """Import a library material by id at a release; the builder VOP, or None once reported."""
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
            debug.event("import", "import failed",    # always a named reason
                        material=mat.name, target=target,
                        reason=reason or "(no reason reported)")
            if reason:
                debug.refuse(reason)    # the door marks library damage, which picks the dialog ▸p/refusal-sink
            return None
        return handler.builder_node

    def import_material_into_container(self, asset_id, container):
        """LOP-release bridge: import into the given materiallibrary."""
        return self._import_material_builder(
            asset_id, "lop", context_node=container
        )

    def assign_material_to_obj(self, asset_ids, obj_node) -> bool:
        """OBJ-viewport release: import to /mat, assigning the first material to `obj_node`."""
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
            debug.refuse(messages.OBJECT_HAS_NO_MATERIAL_PARM % obj_node.name())
            return False
        parm.set(builder.path())
        return True

    def _selected_material_ids(self, index) -> list:
        """Asset ids of the selection, the pressed tile first."""
        row = self.material_sorted_model.mapToSource(index).row()    # may be -1 for a stale index ▸r/model-contracts
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
        """LOP-viewport release: the prim menu, then import and assign through Houdini's stock helpers."""
        from amaze.core import dragengine, lop_assign
        from amaze.helpers import helpers
        stock = dragengine.stock_lop()
        if stock is None:
            debug.refuse(messages.STOCK_LOP_HELPERS_UNAVAILABLE)    # ▸p/refusal-sink
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
        choices = lop_assign.drop_choices(stage, primpath)    # what to offer is lop_assign's
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
        chosen = cmenu.exec(QtGui.QCursor.pos())    # screen coordinates
        cmenu.deleteLater()    # parented to the panel, so deleted; `actions` keeps its keys until then
        if chosen is None:
            return False    # dismissed: nothing happens
        kind, payload = actions[chosen]
        assign_path = payload if kind == "assign" else None
        swap_targets = payload if kind == "swap" else None
        undo_label = (
            "Amaze Swap Material" if swap_targets is not None
            else "Amaze Assign Material"
        )
        with hou.undos.group(undo_label):    # the library, the import and the assign revert as one step
            try:    # Houdini's own library picker and its own assign ▸r/houdini-after-create
                if target_lop is not None:
                    node2, liblop, _vop = stock.getMaterialLibraryLop(target_lop)
                else:    # an empty network: the library Houdini's own branch makes, unwired
                    liblop = lopnet.createNode("materiallibrary")
                    helpers.auto_place(liblop)
                    liblop.setDisplayFlag(True)
                    liblop.setCurrent(True, True)
                    node2 = liblop
            except hou.Error as refusal:    # a locked asset raises PermissionError, a sibling
                debug.event("drag", "the network refused a material "
                            "library", dest=lopnet.path(),
                            error=str(refusal))
                debug.refuse(messages.NETWORK_REFUSED_MATERIAL_LIBRARY
                             % (lopnet.name(), refusal))
                return False
            if swap_targets is not None:
                ids = list(ids)[:1]    # a swap replaces one material
            vops = []
            imported = []    # (asset id, vop) for the imports that succeeded
            for aid in ids:
                vop = self.import_material_into_container(aid, liblop)
                if vop is not None:
                    imported.append((aid, vop))
                    vops.append(vop)
            pressed_vop = None
            if imported and ids and imported[0][0] == ids[0]:
                pressed_vop = imported[0][1]
            elif imported:
                debug.refuse(messages.DROPPED_MATERIAL_IMPORT_FAILED)
            debug.event("drag", "lop viewport drop", imported=len(vops),
                        amaze=liblop.path(), assign=str(assign_path),
                        swap=bool(swap_targets))
            if pressed_vop is not None and swap_targets is not None:
                reason = lop_assign.swap_assignments(    # the module does the USD and reports; the panel says it
                    stock, lopnet, liblop, node2, swap_targets,
                    pressed_vop
                )
                if reason:
                    debug.refuse(reason)
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
                    debug.refuse(messages.MATERIAL_ASSIGN_FAILED % exc)
        return bool(vops)





    def _import_materials_into_context(self, context, ids,
                                       position=None) -> None:
        """Network-release material import, one undo step; a `position` cascades the copies from it."""
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
            ok, reason, created = material_actions.import_asset_to_scene(
                self.material_model, idx, "auto", context_node=context
            )
            if not ok and reason:
                debug.refuse(reason, net=context.path())    # library damage picks the dialog ▸p/refusal-sink
                break    # ONE refusal per multi-drop, never one per asset ▸p/dialogs-are-a-bill
            if position is not None:
                helpers.place_nodes(created, hou.Vector2(
                    position.x() + offset * 0.6,
                    position.y() - offset * 0.9))

    def _category_under_cursor(self):
        return sidebar.category_under_cursor(self)

    def _folder_under_cursor(self):
        return sidebar.folder_under_cursor(self)

    def move_files_active(self, folder: str) -> bool:
        """Move the ACTIVE section's selected files into `folder`; True when a move started."""
        context = self._section()
        return bool(context is not None and context.takes_file_drops
                    and context.move_files_to(folder))

    def _set_drag_hover_row(self, row) -> None:
        """Highlight a sidebar row by its index, or clear with -1. Logic in panel/sidebar.py."""
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
        """Droppable items under the cursor in a network editor, as (item, ...) tuples."""
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
        """The pane tab under the cursor and its type, or (None, None); the caller compares the type."""
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
        """The node under the cursor, or a Parameter Editor's node; pass the pane ▸p/drag-move-cost"""
        if pane_tab is None:
            pane_tab, pane_type = self._pane_and_kind_under_cursor()
        if pane_tab is None:
            return None
        if pane_type == hou.paneTabType.Parm:    # the node that pane shows
            try:
                return pane_tab.currentNode()
            except (AttributeError, hou.OperationFailed):
                return None
        if pane_type != hou.paneTabType.NetworkEditor:
            return None
        return self._first_node_at_cursor(pane_tab)

    def _first_node_at_cursor(self, pane_tab) -> hou.Node | None:
        """The first hou.Node under the cursor, or None; the drop and click resolvers share it."""
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
            self.gradient_categories_model.check_add_category(    # brackets its own insert
                dialog.categories)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """A splitter drag records both side panes' widths; the debounced save writes them."""
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
        """Flip the Notes pane through its toolbar chip, so the two always agree."""
        button = getattr(self, "btn_notes", None)
        if button is not None:
            button.setChecked(not button.isChecked())

    def _on_notes_toggled(self, checked: bool) -> None:
        """Show or hide the pane and remember it; the grid absorbs the width."""
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
            recolour={notes_panel.COMMENT_INK:    # keyed on a colour the art contains
                      ui_helpers.IconMenuButton.IDLE_BODY},
            recolour_on={notes_panel.COMMENT_INK: notes_panel.COMMENT_INK})

    def _on_note_saved(self, _key: str) -> None:
        """A page was written - repaint the grid so the tile's note badge appears or clears with it."""
        grid.visible_view(self).viewport().update()    # `NotesRole` emits no `dataChanged`

    def _notes_subject(self):
        """What the Comments pane points at, or None - the section says what its selected tile is."""
        context = self._section()
        if context is None or not context.takes_comments:    # the context answers
            return None
        index = grid.selected_current_in(    # a SELECTED row: Qt keeps the current one after a deselect
            self.thumblist, context.grid_selection_model())
        if index is None:
            return None
        return context.comment_subject(index)

    def _refresh_notes_subject(self, *_args) -> None:
        """Point the Notes pane at the current selection; returns at once while it is hidden."""
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
        """The one door to the conversion bar's visibility, and the Cancel chip's with it."""
        self.texture_progress.setVisible(visible)
        tabs = getattr(self, "section_tabs", None)    # None during init_ui
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
        """The thin bar over the grid while thumbnails generate; hidden with nothing left to do."""
        if husk_job.jobs.busy():    # a background thumbnail render owns the bar
            return
        if total <= 0 or done >= total:
            self.set_conversion_bar_visible(False)
            return
        self.set_conversion_bar_visible(True)
        self.texture_progress.set_progress(done, total)

    def _on_online_preview_progress(self, done: int, total: int) -> None:
        """The same bar for the online preview pool, only while the online browser shows."""
        if not self._is_online():
            return
        if getattr(self, "_online_download_active", False):
            return  # a download import owns the bar right now
        self._on_texture_progress(done, total)

    def _active_asset_stack(self):
        """The showing asset section's stack (model, proxy, selection, categories), or None."""
        section = self._section()
        return section.stack() if section is not None else None

    def filter_thumb_view(self) -> None:
        """Search box changed - the active context applies it."""
        section = self._section()
        if section is not None:
            section.filter_text(self.line_filter.text())    # online, the source's API searches

    def filter_favs(self) -> None:
        """Favourites star toggled - the active context applies it."""
        section = self._section()
        if section is not None:
            section.filter_favorites(self.cb_favsonly.isChecked())

    def build_filter_menu(self) -> None:
        """Fill the Filter menu from the active section's `filter_entries`, and apply the remembered one."""
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
                button.setVisible(True)    # the toolbar table disables it
            else:
                button.setVisible(bool(entries))    # no entries, no button
            if section is not None and not getattr(
                    section, "kind_filter_menu", False):    # online, _sync_toolbar owns the tooltip
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
            entries[0][0]]    # a choice no longer offered falls back to the first
        act.setChecked(True)
        self.apply_section_filter()

    def filter_menu_changed(self, action) -> None:
        """An entry was picked: apply it and remember it for this tab."""
        self.apply_section_filter()
        self.prefs.set_section_filter(self.current_section, action.data())
        self.prefs.save()

    def apply_section_filter(self) -> None:
        """Push the menu's checked entry into the active section."""
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
        """Re-evaluate empty-category hiding and counts, for changes that emit no layoutChanged."""
        for proxy in self.sidebar_proxies():
            proxy.sourceModel().drop_count_cache()
            proxy.invalidateFilter()
        if self.cat_list is not None:
            self.cat_list.viewport().update()
        self._ensure_sidebar_selection(self.current_section)    # the refilter may hide the row stood on

    SIDEBAR_PROXY_ATTRS = {    # section key -> its sidebar proxy attribute
        "material": "category_sorted_model",
        "cop": "cop_category_sorted_model",
        "code": "code_category_sorted_model",
        "gradient": "gradient_category_sorted_model",    # Colors
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
        """Fall back to All when the filter hid the category stood on in section `section_key`."""
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
        standing = stack.proxy.filter_value(stack.model.CategoryRole)    # the grid's filter, never the selection
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
        """The sidebar row whose stored name is `stored`, or None."""
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
        """Point the sidebar at the row showing display name `label` and refilter; whether it exists."""
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
        """The favourites blank's Show All: unchecks the star chip, whose `toggled` does the rest."""
        chip = getattr(self, "cb_favsonly", None)
        if chip is not None:
            chip.setChecked(False)

    def clear_filter_box(self) -> None:
        """The empty state's Clear Search button."""
        box = getattr(self, "line_filter", None)
        if box is None or not box.text():
            return
        box.clear()
        self.filter_thumb_view()    # by hand: clear() emits no `textEdited`

    def update_selected_cat(self) -> None:
        """The sidebar selection changed: the active section shows that category or folder."""
        indexes = self.cat_list.selectedIndexes()
        if not indexes:    # a ctrl-click deselect is re-selected in place
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
        """Re-render the grid selection's thumbnails, through the active context."""
        context = self._section()
        if context is None:
            return
        context.update_preview(list(indexes))

    def grid_delete(self, indexes) -> None:
        """Delete the grid selection after the context's own question; not where `deletes_rows` is off."""
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
        name = sources[0].data(QtCore.Qt.ItemDataRole.DisplayRole) or ""    # for a prompt that quotes it
        ui = getattr(hou, "ui", None)
        if ui is None or ui.displayMessage(
            context.delete_prompt(len(sources), name),
            buttons=messages.BUTTONS_DELETE,
            default_choice=1, close_choice=1,
        ) != 0:
            return
        context.delete_rows(sources)

    def generate_random_material(self) -> None:
        """One random plausible material, built into the scene where the user works, not the library."""
        from amaze.helpers import helpers
        from amaze.render import generator
        builder = None
        destination = None
        ui = getattr(hou, "ui", None)
        with hou.undos.group("Amaze Generate Material"):    # ONE undo step with the library it may create; a move out of staging undoes clean ▸r/node-items
            destination = nodes.karma_destination(self.prefs)
            if destination is None:
                if ui is not None:
                    ui.displayMessage(
                        messages.NO_MATERIAL_DESTINATION_NETWORK
                    )
                return
            staging = hou.node("/obj").createNode("matnet")    # built in staging, moved in one step ▸r/matlib-entries
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
                if destination.type().name() == "materiallibrary":    # registered as an import is
                    registered = nodes.register_in_materiallibrary(
                        destination, builder
                    )
                builder.setCurrent(True, True)    # current and selected, as a node from the Tab menu is
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
        """Save the selected nodes; ones already in the library raise one save-over/new/cancel choice."""
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
                message = messages.MATERIAL_ALREADY_IN_LIBRARY % name
            else:
                message = messages.MATERIALS_ALREADY_IN_LIBRARY % (len(existing), len(sel))
            may_overwrite = library_policy.allow_overwrite(
                self.material_model.preferences.dir)    # the library decides; the UI calls it Material Versions
            if may_overwrite:
                buttons = messages.BUTTONS_SAVE_VERSION_OR_NEW
                cancel_at, overwrite_at = 2, 0
            else:
                message += messages.VERSIONS_OFF_SAVES_NEW
                buttons = messages.BUTTONS_SAVE_NEW    # Versions off: no save-over, an option that would always fail
                cancel_at, overwrite_at = 1, -1
            choice = ui.displayMessage(
                message,
                buttons=buttons,
                default_choice=0,
                close_choice=cancel_at,
                title=messages.TITLE_SAVE_TO % branding.APP_NAME,
            ) if ui is not None else cancel_at    # no screen to ask, so the answer is the close_choice - Cancel
            if choice == cancel_at:
                return
            if choice == overwrite_at:
                total, done = len(existing), 0
                try:
                    with hou.InterruptableOperation(    # type: ignore
                        messages.UPDATING_MATERIALS, open_interrupt_dialog=True
                    ) as op:
                        for mat_id, node in existing:
                            op.updateLongProgress(
                                done / total, "%d/%d  %s" % (done + 1, total, node.name()))
                            self._update_existing_asset(mat_id, node)
                            done += 1
                except hou.OperationInterrupted:
                    debug.status(messages.SAVE_STOPPED % (done, total))
                if new_nodes:
                    self.get_material_info_user(new_nodes)
                return
        self.get_material_info_user(sel)    # Save as New falls through to here with the FULL selection

    def _find_existing_asset_row(self, node: hou.Node) -> int:
        """The source row of the material this node came from, by id stamp, else unique name; or -1."""
        mat_id = node.userData("assetlib_id")
        if mat_id:
            row = self.material_model.find_asset_row_by_id(mat_id)
            if row >= 0:
                return row
        return self.material_model.find_asset_row_by_name(node.name())

    def _update_existing_asset(self, mat_id: str, node: hou.Node) -> None:
        """Overwrite asset `mat_id`'s content from the scene node: same entry and metadata, new files."""
        model = self.material_model
        renderer = material_actions.update_asset_content(    # NO layout pair: it saves, which adopts rows
            model, model.find_asset_row_by_id(mat_id), node)
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
        total, done = len(sel), 0
        try:
            with hou.InterruptableOperation(    # type: ignore
                messages.SAVING_MATERIALS, open_interrupt_dialog=True
            ) as op:
                for asset in sel:
                    op.updateLongProgress(done / total,
                                          "%d/%d  %s" % (done + 1, total, asset.name()))
                    try:    # a raise out of the save chain joins the per-material report
                        renderer = material_actions.add_asset(
                            self.material_model, asset, dialog.categories, dialog.tags,
                            dialog.fav, name=dialog.name or None
                        )
                    except hou.OperationInterrupted:
                        raise
                    except Exception as exc:                    # noqa: BLE001
                        debug.exception("save_asset", exc, node=asset.path())
                        failures.append('"%s": %s' % (asset.name(), exc))
                        done += 1
                        continue
                    done += 1
                    if not renderer:    # "" is a refused save that already spoke; name which one
                        failures.append(messages.SAVE_DID_NOT_COMPLETE_LINE % asset.name())
                        continue
                    renderers.append(renderer)
        except hou.OperationInterrupted:
            debug.status(messages.SAVE_STOPPED % (done, total))

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
        self._import_selection(
            self.material_sorted_model, self.material_model,
            lambda model, index: material_actions.import_asset_to_scene(model, index, target),
            "Amaze Import Materials", messages.NAMELESS_MATERIAL,
            lambda listed: messages.MATERIALS_IMPORT_FAILURES % listed)

    def import_asset_auto(self, index: QtCore.QModelIndex | None = None):
        """The grid's double-click, answered by the active section's `double_click`."""
        if index is not None and index.isValid():
            index = index.siblingAtColumn(0)    # the row, not the clicked cell ▸r/row-selection
        section = self._section()
        if section is not None:
            section.double_click(index)

    def _cannot_load_here(self) -> None:
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(messages.CANNOT_LOAD_HERE)  # type: ignore

    def _network_under_release(self) -> hou.Node | None:
        """The network a no-node release happened inside, or None off any editor."""
        return self._drop_context_under_cursor(lambda _node: False)

    def _release_position_in(self, net):
        """The release position, only when the editor under the cursor shows `net`; else None."""
        from amaze.core import dragengine
        pane_tab = dragengine.pane_tab_under_cursor()
        if pane_tab is None or net is None:
            debug.event("interact", "no drop point - no editor under "
                        "the cursor", net=net.path() if net else None)
            return None
        try:
            if pane_tab.type() != hou.paneTabType.NetworkEditor:
                return None
            if pane_tab.pwd() != net:    # cross-space: the cursor is in another plane
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
        """Selected nodes in a visible editor's network, for the click doors ▸r/matlib-entries"""
        networks = self._view_create_networks()
        every = hou.selectedNodes()
        sel = [node for node in every if node.parent() in networks]
        debug.event("interact", "click door selection",
                    visible=len(sel), total=len(every),
                    networks=len(networks))
        return sel

    def _view_create_networks(self) -> list:
        """Every visible network editor's pwd, current tabs first; create in the first that can hold it."""
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
        """Create `type_name` in `dest` if it can hold one, else None; the caller owns the undo group."""
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
        except hou.Error as refusal:    # Houdini's refusal is logged; the walk moves on
            debug.event("interact", "the network refused the carrier",
                        carrier=type_name, dest=dest.path(),
                        error=str(refusal))
            return None
        if name:
            try:
                node.setName(name, unique_name=True)
            except hou.OperationFailed:
                pass
        if position is None:    # auto-place only without a position
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
        """The slider's value as the grid's persisted tile size; list mode ignores it."""
        if not self.material_model or not self.category_model:
            return
        if self.prefs.view_mode == "list":
            return    # list has one size
        value = self.click_slider.value()
        self.prefs.thumbsize = value
        self._thumbsize_save_timer.start()    # saved once the drag settles
        self.apply_view_mode()    # sizing for the active mode - grid grows icons, list grows rows

