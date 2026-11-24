"""The Amaze panel: the Python panel widget and its views onto the models."""

import time

_BODY_T0 = time.perf_counter()    #: when this module body began, before the imports and the reload chain

import os
import importlib
import sys

from PySide6 import QtWidgets, QtGui, QtCore
import hou

import amaze
from amaze.actions import files as files_actions
from amaze.actions import library as library_actions
from amaze.actions import materials as material_actions
from amaze.actions import nodes as node_actions
from amaze.core import grid_columns, grid_engine
from amaze.panel import (dragdrop_widgets, empty_state, grid, info_panel, notes_panel, side_pane,
                         sidebar)
from amaze import sections
from amaze.sections import (base as section_base, code as code_section, color as color_section,
                            file as file_section, material as material_section,
                            node as node_section, online as online_section)
from amaze.core import debug, documents, library_db, library_files, locations, section_list
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
from amaze.core import renderers, tile_icons, users
from amaze.render import cop_nodes, husk_job, nodes
from amaze.pane import asks
from amaze.pane import files as pane_files
from amaze.pane import (assets as pane_assets, drop_placement, empty_state as pane_empty_state,
                        library as pane_library, loading as pane_loading, online_import,
                        package_import, pane as pane_mod, saving as pane_saving,
                        sidebar as pane_sidebar, tile_capture)

_DEV_RELOAD = bool(os.environ.get("AMAZE_DEV_RELOAD"))    # the reload chain below is off by default ▸r/module-reload


def _reload(module):
    """importlib.reload, unless the dev switch is off."""
    if _DEV_RELOAD:
        importlib.reload(module)


def _reload_loaded(name):
    """`_reload` for a module imported where it is used, so only once something has loaded it."""
    if _DEV_RELOAD and name in sys.modules:
        importlib.reload(sys.modules[name])


_reload_loaded("amaze.core.guard")    # first: every database is read and written through it
_reload(library_files)
_reload(documents)
_reload(library_db)    # keeps its open databases across the reload
_reload(locations)      # the library switch calls locations.forget()
_reload(hostos)    # before library: the models import the shared thumbnail engine
_reload(wording)    # before library, nodes and sections, which build names with it
_reload(debug)
_reload(section_list)    # before sections, prefs and the dialog, which read the list
_reload_loaded("amaze.core.dragengine")
_reload_loaded("amaze.core.lop_assign")
_reload_loaded("amaze.core.workers")    # before the engines that stop their threads through it
_reload(thumbnails)
_reload_loaded("amaze.core.library_settings")    # before library, which gates overwriting on it
_reload(versions)
_reload(notes)
_reload(users)    # before versions and the dialogs showing a user: both resolve a UID through it
_reload(renderers)
_reload(material)
_reload_loaded("amaze.core.material_files")    # before nodes and library, which read saved materials by it
_reload(texstore)    # before nodes and library, which copy textures in and resolve them through it
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
_reload_loaded("amaze.core.file_moves")    # after captures and locations, whose keys it updates for moved files
_reload(library)
_reload(category)
_reload_loaded("amaze.core.check_library")
_reload(folders)
_reload(prefs)
_reload(library_actions)    # after captures and prefs, which its steps call
_reload(messages)      # the wording every dialog shows ▸p/messages-in-three-places
_reload(tooltips)      # every hover text; before the dialogs, delegates and models that read it
_reload(amazetheme)    # before theme and ui_helpers, whose class bodies read it ▸p/one-design-document
_reload(theme)    # before ui_helpers, whose class bodies read theme colours
_reload(branding)    # first of the ones below: everything reads its constants
_reload(ui_helpers)
_reload(rc_calls)    # after debug and messages: it logs the dialogs whose texts they hold
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
_reload(files_actions)    # after file_library and helpers, which it passes in; before sections
_reload_loaded("amaze.helpers.vex_syntax")    # before code_library/code_dialog, which consume its palette and tokenizer
_reload(code_library)    # after library/category: it subclasses the material library classes
_reload(model_registry)    # last of the models: it lists all ten classes

_reload_loaded("amaze.dialogs.base_dialog")    # FIRST of the dialogs: each binds its AssetDialog class
_reload_loaded("amaze.dialogs.library_dialog")
_reload_loaded("amaze.dialogs.prefs_window")
_reload_loaded("amaze.dialogs.save_dialog")
_reload_loaded("amaze.dialogs.icon_dialog")
_reload_loaded("amaze.dialogs.gradient_dialog")
_reload_loaded("amaze.dialogs.code_dialog")
_reload_loaded("amaze.dialogs.user_dialog")
_reload(dragdrop_widgets)
_reload(grid)
_reload(sidebar)
_reload(asks)    # before sections, which build their questions with it
_reload(pane_files)    # before sections, which call its clipboard and file browser
_reload(section_base)    # before every section, which builds on it
_reload(material_section)
_reload(node_section)
_reload(code_section)
_reload(color_section)
_reload(file_section)
_reload(online_section)
_reload(sections)    # the registry, after the sections it lists
_reload(empty_state)    # after grid: it shows its page in the grid pane
_reload(side_pane)
_reload(notes_panel)
_reload(info_panel)
_reload(multifilterproxy_model)
_reload(matx_sources)    # the online stack, which was never in this chain at all
_reload_loaded("amaze.core.matx_translate")
_reload_loaded("amaze.core.matx_icon")
_reload_loaded("amaze.core.matx_import")
_reload(matx_library)
_reload_loaded("amaze.core.gallery_import")    # reachable from the Online menu
_reload_loaded("amaze.core.packages")
_reload_loaded("amaze.render.generator")
_reload(online_import)    # after matx_sources, nodes and material_actions, which it calls
_reload(package_import)    # after sections, whose SECTION_CLASSES it reads
_reload(drop_placement)    # after geo_library, helpers and wording, which it calls
_reload(tile_capture)    # after scene_captures, which it calls
_reload(pane_library)    # after sections: it builds them
_reload(pane_sidebar)
_reload(pane_assets)
_reload(pane_loading)    # after sections, whose drop rules it reads
_reload(pane_saving)
_reload(pane_empty_state)
_reload(pane_mod)    # last of the engine: it holds every part above



from amaze.panel import delegates            # noqa: E402

_reload(delegates)

SIDEBAR_KEY_PAUSE_MS = pane_sidebar.KEY_PAUSE_MS    #: the engine's, which the QML pane waits too

MIN_PANEL_WIDTH = 500    #: design px through `theme.ui_px` at use; the grid pane has none ▸r/qt-windows-macos


class _AfterFirstPaint(QtCore.QObject):
    """Calls `done` once, after `viewport`'s first paint has RETURNED, then removes its filter."""

    def __init__(self, viewport, done) -> None:
        super().__init__(viewport)    # deleted with the viewport
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
        return True    # already painted above: the original event goes no further


class AmazePanel(QtWidgets.QWidget, asks.Asks):
    """The panel widget: the widgets that show one pane engine, and the dialogs it asks for."""

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
        vex_syntax.use_syntax_colors(theme.syntax_colors())    # Houdini's syntax colours, tiles and editor alike
        self.pane = pane_mod.Pane(self, self)    # reads the settings; the library opens below, after the widgets
        self.init_ui()
        self._follow_pane()
        if self.pane.library.start():
            debug.event(    # a header without 'panel ready' means logging died during construction
                "session", "panel ready",
                module_body_ms=round(    # the imports and the reload chain, before construction
                    (self._construct_t0 - _BODY_T0) * 1000, 1),
                construction_ms=round(
                    (time.perf_counter() - self._construct_t0) * 1000, 1),
                **debug.probe())

    def _follow_pane(self) -> None:
        """Every engine signal to the widget that shows it."""
        pane = self.pane
        pane.models_built.connect(self._on_models_built)
        pane.library_shown.connect(self._on_library_shown)
        pane.library_switching.connect(self._on_library_switching)
        pane.library_switched.connect(self._on_library_switched)
        pane.library_updated.connect(self._refresh_open_prefs)
        pane.context_leaving.connect(self._on_context_leaving)
        pane.context_bound.connect(self._on_context_bound)
        pane.context_shown.connect(self._on_context_shown)
        pane.tabs_changed.connect(self._build_section_tabs)
        pane.online_changed.connect(self._on_online_changed)
        pane.filter_changed.connect(self.build_filter_menu)
        pane.sidebar_highlight.connect(self.cat_list.highlight)
        pane.sidebar_reveal.connect(self.cat_list.reveal)
        pane.sidebar_changed.connect(self._on_sidebar_changed)
        pane.grid_reordered.connect(self._follow_sort_arrow)
        pane.grid_to_top.connect(self._on_grid_to_top)
        pane.progress_shown.connect(self.set_conversion_bar_visible)
        pane.progress.connect(self.texture_progress.set_progress)
        pane.empty_changed.connect(self._on_empty_changed)

    def _on_models_built(self) -> None:
        """A library's models exist: the tile delegates, and the side panes follow the selections."""
        pane = self.pane
        self.thumb_delegate = delegates.AssetItemDelegate(
            pane.material_model.TileSubtitleRole,
            self.thumblist,
            renderer_icon_role=pane.material_model.RendererIconRole,
            category_role=pane.material_model.CategoryRole,
            tag_role=pane.material_model.TagRole,
            licence_role=pane.material_model.LicenceRole,
            category_color_role=pane.material_model.CategoryColorRole,
            active_version_role=pane.material_model.ActiveVersionRole,
            date_role=pane.material_model.DateRole,
            id_role=pane.material_model.IdRole,
            crop_role=pane.material_model.CropRole,
            tile_model=library.MaterialLibrary,
            **self._tile_badges(material_section.MaterialSection),
        )

        node_roles = dict(
            category_role=pane.material_model.CategoryRole,
            tag_role=pane.material_model.TagRole,
            licence_role=pane.material_model.LicenceRole,
            category_color_role=pane.material_model.CategoryColorRole,
            date_role=pane.material_model.DateRole,
            id_role=pane.material_model.IdRole,
            crop_role=pane.material_model.CropRole,
        )
        self.asset_delegate = delegates.AssetItemDelegate(    # Node and Code: their own delegate, without the version roles
            pane.material_model.RendererLabelRole, self.thumblist,
            tile_model=cop_library.CopLibrary, **node_roles, **self._tile_badges(node_section.CopSection))
        self.code_delegate = delegates.AssetItemDelegate(
            pane.material_model.RendererLabelRole, self.thumblist,
            tile_model=code_library.CodeLibrary, **node_roles, **self._tile_badges(code_section.CodeSection))

        self.file_delegate = delegates.AssetItemDelegate(
            pane.file_files_model.FormatRole,
            self.thumblist,
            category_role=pane.file_files_model.FolderRole,
            category_color_role=pane.file_files_model.CategoryColorRole,
            crop_role=pane.file_files_model.CropRole,
            tile_model=file_library.FileFiles,
            **self._tile_badges(file_section.FileSection),
        )

        self.gradient_delegate = delegates.AssetItemDelegate(
            pane.gradient_model.RendererLabelRole,
            self.thumblist,
            category_role=pane.gradient_model.CategoryLabelRole,
            category_color_role=pane.gradient_model.CategoryColorRole,
            crop_role=pane.gradient_model.CropRole,
            tile_model=gradient_library.GradientLibrary,
            **self._tile_badges(color_section.GradientSection),
        )

        self.matx_delegate = delegates.AssetItemDelegate(    # the online section's own delegate, with only the roles its model has
            pane.matx_online_model.RendererLabelRole,
            self.thumblist,
            category_role=pane.matx_online_model.CategoryRole,
            tag_role=pane.matx_online_model.TagRole,
            tile_model=matx_library.MatxOnlineLibrary,
            **self._tile_badges(online_section.OnlineContext),
        )
        self._sync_notes_button_pixmaps()
        self._sync_info_button_pixmaps()
        self.sidebar_delegate.show_counts = pane.prefs.sidebar_counts
        for selection in (    # keyboard selection changes update the side panes too
            pane.material_selection_model,
            pane.cop_selection_model,
            pane.code_selection_model,
            pane.file_selection_model,
            pane.gradient_selection_model,
        ):
            selection.selectionChanged.connect(self._refresh_notes_subject)
            selection.selectionChanged.connect(self._refresh_info_subject)

    def _on_library_shown(self) -> None:
        """A newly opened library's first section shows: the tile size, view mode and colours."""
        self.click_slider.setValue(self.pane.tile_size())
        self.slide()
        self.apply_view_state()
        self._apply_theme_colours()

    def _on_library_switching(self) -> None:
        """Another library is about to be read: a pending comment is saved to its own library."""
        pane = getattr(self, "notes_panel", None)
        if pane is not None:
            pane.clear_subject()    # the switch selects nothing
        info = getattr(self, "info_panel", None)
        if info is not None:
            info.clear_subject()

    def _on_library_switched(self) -> None:
        self.click_slider.setValue(self.pane.tile_size())

    def _on_context_leaving(self) -> None:
        """Remember the grid's scroll for the section being left; the pane keeps its sidebar row."""
        self._section_scroll[self.pane.current_section] = (
            grid.visible_view(self).verticalScrollBar().value())

    def _engine_model(self, attr: str):
        return getattr(self.pane, attr, None) if attr else None

    def _on_context_bound(self, section) -> None:
        """The sidebar and both grid views show `section`'s models, with its own delegate."""
        listed = self._engine_model(section.sidebar_attr)
        if self.cat_list and listed is not None:
            self.cat_list.setModel(listed)    # a fresh selection, made after the view's own connections
            self.pane.sidebar.use_selection(self.cat_list.selectionModel())
        self.bind_grid_views(self._engine_model(section.proxy_attr),
                             self._engine_model(section.selection_attr),
                             getattr(self, section.delegate_attr, None) if section.delegate_attr else None)
        self.sync_list_columns()    # another section, other column names

    def _on_context_shown(self, context) -> None:
        """The shown context's tab, toolbar, Filter menu, scroll, side panes and empty state."""
        self.section_tabs.setChecked(self.pane.current_tab(), emit=False)
        self._sync_toolbar(context)    # EVERY toolbar control, from the one table - Capture included
        self.build_filter_menu()
        scroll = self._section_scroll.get(context.key)
        if scroll:
            QtCore.QTimer.singleShot(    # after the relayout, which would clamp it
                0, lambda: grid.visible_view(self).verticalScrollBar().setValue(scroll))
        self._refresh_notes_subject()
        self._refresh_info_subject()

    def _on_online_changed(self) -> None:
        """The Online chip follows the pane; out of online, Material Library is the checked source."""
        self._sync_online_chip()
        action = getattr(self, "action_material_library", None)
        if action is not None and not self.pane.is_online():
            action.setChecked(True)    # exclusive group, so checking this unchecks any source

    def _on_sidebar_changed(self) -> None:
        if self.cat_list is not None:
            self.cat_list.viewport().update()

    def _on_empty_changed(self) -> None:
        empty_state.refresh(self)

    def _on_grid_to_top(self) -> None:
        grid.visible_view(self).scrollToTop()

    def ask_name(self, title: str, default: str, then) -> None:
        """The name dialog, modal: `then` gets the name, "" for a cleared field, None for Cancel."""
        from amaze.dialogs import gradient_dialog
        dialog = gradient_dialog.CategoryDialog(title, default, parent=self)
        dialog.exec()
        then(None if dialog.canceled else (dialog.name or ""))    # a cleared Rename restores the folder's name

    def ask_colour(self, start: str, title: str, then) -> None:
        """The colour picker, modal: `then` gets "#rrggbb", None for Cancel."""
        chosen = ui_helpers.pick_color(start, self, title)
        then(chosen.name() if chosen is not None else None)

    def ask_drop_choice(self, labels: list, then) -> None:
        """A menu at the cursor, modal: `then` gets the picked row's place in `labels`, None if dismissed."""
        menu = QtWidgets.QMenu(self)
        places = {}
        for place, label in enumerate(labels):
            if label:
                places[menu.addAction(label)] = place
            else:
                menu.addSeparator()
        chosen = menu.exec(QtGui.QCursor.pos())    # screen coordinates
        menu.deleteLater()    # parented to the panel, so deleted; `places` keeps its keys until then
        then(places.get(chosen))

    def open_versions(self, name: str, listed: list, active: int, then) -> None:
        """The Versions dialog, modal: `then` gets the picked version on Select, None on Cancel."""
        from amaze.dialogs import versions_dialog
        dialog = versions_dialog.VersionsDialog(name, listed, active, parent=self)
        accepted = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
        then(dialog.chosen if accepted else None)

    def open_save(self, question, then) -> None:
        """D09, modal: `then` gets a SaveAnswer, None on Cancel."""
        from amaze.dialogs import save_dialog
        dialog = save_dialog.SaveDialog(
            question.categories, question.current, name=question.name,
            name_enabled=question.name_enabled, parent=self,
            sections=question.sections, section=question.section,
            categories_for=question.categories_for, language=question.language,
            language_sections=question.language_sections)
        accepted = dialog.exec()
        if dialog.canceled or not accepted:
            then(None)
            return
        then(asks.SaveAnswer(section=getattr(dialog, "section", ""), name=dialog.name,
                             categories=dialog.categories, tags=dialog.tags, fav=dialog.fav,
                             language=dialog.language))

    def open_code(self, question, apply) -> None:
        """D11, modal: each Apply hands the fields to `apply`, which saves the snippet."""
        from amaze.dialogs import code_dialog
        fields = {name: value for name, value in question._asdict().items() if value is not None}
        dialog = code_dialog.CodeDialog(fields.pop("categories"), parent=self, **fields)

        def applied():
            apply(asks.CodeAnswer(code=dialog.code, name=dialog.name, language=dialog.language,
                                  category=dialog.category, tags=dialog.tags))

        dialog.applied.connect(applied)
        dialog.exec()

    def open_customize(self, question, apply) -> None:
        """D02, one at a time and not modal: Apply and Accept hand `apply` the edits."""
        from amaze.dialogs import icon_dialog
        existing = getattr(self, "_icon_dialog", None)
        if existing is not None:
            try:
                existing.raise_()
                existing.activateWindow()
                return
            except RuntimeError:
                pass                      # already deleted underneath
        dialog = icon_dialog.IconDialog(
            question.icon, question.stroke, self,
            tile_name=question.tile_name,
            tile_name_enabled=question.tile_name_enabled,
            tile_tags=question.tile_tags,
            categories=question.categories,
            tile_category=question.tile_category,
            face=question.face,
            faces=question.faces,
            can_preview=question.can_preview,
        )
        self._icon_dialog = dialog

        def edits():
            return asks.CustomizeAnswer(
                spec=dialog.spec, name=getattr(dialog, "new_tile_name", None),
                tags=getattr(dialog, "new_tags", None), category=getattr(dialog, "new_category", None))

        def finished(_result=0):
            self._icon_dialog = None
            try:
                if not dialog.canceled:
                    apply(edits())
            finally:
                dialog.deleteLater()    # the panel parents it, so it must be deleted

        dialog.applied.connect(lambda: apply(edits()))    # Apply commits and stays open; Accept commits at the close
        dialog.finished.connect(finished)
        dialog.show()

    def show_comments(self) -> None:
        """The Comments pane, through its toolbar button's own click, so the two never differ."""
        self.btn_notes.click()

    os_file_icon = staticmethod(delegates.os_file_icon)    # held by the shared File model, never by the panel

    MENU_ICON_FILES = {    # menu title -> icon asset with a baked-in "opens a menu" triangle
        "View": "icon_renderer.svg",
        "Filter": "icon_view.svg",
    }

    def _ui_icon_path(self, filename: str) -> str:
        """An icon in ui/, or "" for no filename (callers fall back). ▸p/reuse"""
        if not filename:
            return ""
        return amaze.package_file("ui", filename)

    def _make_menu_button(self, menu: QtWidgets.QMenu) -> "ui_helpers.IconMenuButton":
        """An icon button that opens `menu`, replacing the hidden menu bar's item."""
        icon_path = self._ui_icon_path(
            self.MENU_ICON_FILES.get(menu.title(), "")
        )
        name = "btn_menu_" + "".join(c for c in menu.title().lower() if c.isalnum())
        return ui_helpers.IconMenuButton(menu, icon_path, name=name)    # stable: B01 and the snapshots key on it

    def _follow_sort_arrow(self, *_args) -> None:
        grid.sync_sort_indicator(self)

    def _refresh_open_prefs(self) -> None:
        """An open Preferences window shows the library's new version."""
        window = getattr(self, "_prefs_window", None)
        if window is None:
            return
        try:
            window.sharedState().refresh_library_version()
        except RuntimeError:    # closed and deleted
            self._prefs_window = None

    def toggle_catview(self) -> None:
        """Show and Hide the Category View via Menu"""
        self.cat_wrapper.setVisible(self.action_catview.isChecked())
        self.pane.prefs.show_categories = self.action_catview.isChecked()    # remembered across sessions
        self.pane.prefs.save()
        button = getattr(self, "btn_categories", None)    # the toolbar button, kept in sync whichever changed
        if button is not None and button.isChecked() != (
                self.action_catview.isChecked()):
            was = button.blockSignals(True)
            button.setChecked(self.action_catview.isChecked())
            button.blockSignals(was)

    def _on_categories_button(self, checked: bool) -> None:
        """The button changed: update the action, which handles the rest."""
        if self.action_catview.isChecked() != checked:
            self.action_catview.setChecked(checked)
        self.toggle_catview()

    def _on_online_button(self, checked: bool) -> None:
        if checked:
            self.pane.enter_online()
        else:
            self.pane.leave_online()

    def _sync_online_chip(self) -> None:
        """Enabled only where the online section can open, and checked only while it is open."""
        button = getattr(self, "btn_online", None)
        if button is None:
            return
        button.setEnabled(getattr(self.pane, "matx_online_model", None) is not None)
        if button.isChecked() != self.pane.is_online():
            was = button.blockSignals(True)
            button.setChecked(self.pane.is_online())
            button.blockSignals(was)

    def _sync_online_button_pixmaps(self) -> None:
        """ONLINE_ICON_COLOR while the online world is open, the toolbar icons' blue when not."""
        button = getattr(self, "btn_online", None)
        if button is None:
            return
        button.set_art(
            self._ui_icon_path("icon_online.svg"),
            lighten_on_hover=False,
            recolour_on={ui_helpers.IconMenuButton.IDLE_BODY: amazetheme.ONLINE_ICON_COLOR})

    def _sync_categories_button_pixmaps(self) -> None:
        """The button's four states, in the toolbar icons' own colours."""
        button = getattr(self, "btn_categories", None)
        if button is None:
            return
        button.set_art(self._ui_icon_path("icon_categories.svg"),
                       lighten_on_hover=False)

    def apply_view_state(self) -> None:
        """Apply the persisted category/details visibility from preferences"""
        self.action_catview.setChecked(self.pane.prefs.show_categories)
        self.cat_wrapper.setVisible(self.pane.prefs.show_categories)
        self.apply_view_mode()

    def bind_grid_views(self, proxy, selection, delegate) -> None:
        """Point both grid views at one context's proxy, selection model and delegate."""
        for view in (self.thumblist, getattr(self, "thumbrows", None)):
            if view is None:
                continue
            view.setModel(proxy)
            if selection is not None:
                view.setSelectionModel(selection)
        grid.sync_sort_indicator(self)    # the header's sort arrow matches this proxy's sort
        if delegate is not None:
            self.thumblist.setItemDelegate(delegate)
            grid.bind_row_cell_delegates(self, delegate)    # per column, image and tick columns only; never the tile delegate

    _LIST = amazetheme.drawn_list()    # header, heading inset and column widths are L01's ▸r/list-from-frame
    _TOOLBAR = amazetheme.drawn_toolbar()    # the toolbar's height, edges, gaps and sizes are B01's
    _SIDEBAR = amazetheme.drawn_sidebar()    # the sidebar's width and its splitter handle are G01's
    HEADER_HEIGHT = theme.ui_px(_LIST["header_h"])    #: the headline's height; the style paints it

    def sync_list_columns(self) -> None:
        """Re-fit list mode's columns for the context now showing; every `activate()` calls it."""
        return grid.sync_row_columns(self)

    COLUMN_DEFAULT_WIDTH = dict(_LIST["widths"], thumb=24)    #: starting widths; "thumb" is never shown, so L01 draws no column for it

    COLUMN_MIN_WIDTH = 24    #: the floor for every column; Qt has no per-column minimum

    def apply_view_mode(self) -> None:
        grid.apply_view_mode(self)
        empty_state.refresh(self)    # the empty page stays up over the view now shown

    def showEvent(self, event):
        """On the FIRST show only: `panel visible` is written once the grid's first paint returned."""
        super(AmazePanel, self).showEvent(event)
        if self._first_show_logged:
            return
        self._first_show_logged = True
        QtCore.QTimer.singleShot(0, self.pane.library.ensure_library_user)    # after the first paint: a modal blocks a half-built paint
        t0 = getattr(self, "_construct_t0", None)
        if t0 is None:
            return

        def _record():
            debug.event(
                "session", "panel visible",
                construct_to_painted_ms=round(
                    (time.perf_counter() - t0) * 1000, 1))

        _AfterFirstPaint(grid.visible_view(self).viewport(), _record)

    def event(self, event):
        """DeferredDelete flushes the panes and size save; a theme switch re-colours. ▸r/theme-switch"""
        if event.type() == QtCore.QEvent.Type.ApplicationPaletteChange:    # Houdini set a new theme's palette
            self._apply_theme_colours()
        if event.type() == QtCore.QEvent.Type.DeferredDelete:    # children get no hide
            pane = getattr(self, "notes_panel", None)
            if pane is not None:
                pane.flush()
            info = getattr(self, "info_panel", None)
            if info is not None:
                info.stop_reading()
            timer = getattr(self, "_thumbsize_save_timer", None)
            if timer is not None and timer.isActive():    # the debounce timer is deleted with the panel, so save now
                timer.stop()
                self.pane.prefs.save()
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
        """Highlight the button badge under the cursor; repaints only when that changed."""
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






    def _sync_slider_for_mode(self) -> None:
        """The slider sizes grid tiles only; in list it is disabled and set to its minimum."""
        grid = self.pane.prefs.view_mode != "list"
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
        self.pane.set_view_mode(mode)
        self.click_slider.setValue(self.pane.tile_size())    # the new mode's remembered size; fires slide() only on a change
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
            self._toolbar_controls.append(self.click_slider)
        self._thumbsize_save_timer = QtCore.QTimer(self)    # debounces saving the per-mode icon size during a drag
        self._thumbsize_save_timer.setSingleShot(True)
        self._thumbsize_save_timer.setInterval(500)
        self._thumbsize_save_timer.timeout.connect(self.pane.prefs.save)
        self.click_slider.valueChanged.connect(self.slide)

        self._lay_out_toolbar()    # after every builder made its controls

        self.thumblist.customContextMenuRequested.connect(self.thumblist_rc_menu)
        self.cat_list.customContextMenuRequested.connect(self.catlist_rc_menu)

        mainlayout = QtWidgets.QVBoxLayout()
        mainlayout.addWidget(self.ui)
        mainlayout.setContentsMargins(0, 0, 0, 0)  # Remove Margins

        self.setLayout(mainlayout)

    def _build_menus(self) -> None:
        """The View and Renderer menus, and the toolbar buttons that open them."""
        self.menu.addMenu(self.menu_filter)
        if self.toolbar_layout is not None:
            menu_view = self.ui.findChild(QtWidgets.QMenu, "menuView")
            self.btn_notes = ui_helpers.ChipToggleButton(name="btn_notes")
            self.btn_notes.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_COMMENTS))
            self._sync_notes_button_pixmaps()
            self.btn_notes.setChecked(bool(self.pane.prefs.show_notes))
            self.btn_notes.toggled.connect(self._on_notes_toggled)    # after the initial state, so restoring it saves nothing
            self._toolbar_controls.append(self.btn_notes)
            self.btn_online = ui_helpers.ChipToggleButton(name="btn_online")    # colour shows its state: no hover highlight
            self.btn_online.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_ONLINE))
            self._sync_online_button_pixmaps()
            self.btn_online.setChecked(self.pane.is_online())
            self.btn_online.toggled.connect(self._on_online_button)
            self._toolbar_controls.append(self.btn_online)
            self.btn_filter = self._make_menu_button(self.menu_filter)    # on self: disabled online, its tooltip per section
            self._toolbar_controls.append(self.btn_filter)
            if menu_view is not None:
                btn_view = self._make_menu_button(menu_view)
                btn_view.setToolTip(ui_helpers.tooltip_text(
                    tooltips.PANEL_VIEW_MENU))
                self._toolbar_controls.append(btn_view)
                self.online_view_menu = QtWidgets.QMenu(self.ui)    # the online filter menu; _sync_toolbar sets it on btn_filter
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
                        self.pane.matx_online_model.set_kind_filter(s))
                self.online_view_menu.actions()[0].setChecked(True)
            btn_prefs = ui_helpers.IconMenuButton(    # held by the layout alone, never on self
                None,
                self._ui_icon_path("icon_library.svg"),
                on_click=self.show_prefs,
                fallback_label="Preferences",
                name="btn_prefs",
            )
            btn_prefs.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_PREFERENCES))
            self._toolbar_controls.append(btn_prefs)
            self.btn_info = ui_helpers.ChipToggleButton(name="btn_info")
            self.btn_info.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_INFO))
            self._sync_info_button_pixmaps()
            self.btn_info.setChecked(bool(self.pane.prefs.show_info))
            self.btn_info.toggled.connect(self._on_info_toggled)    # after the initial state
            self._toolbar_controls.append(self.btn_info)
            self.btn_categories = ui_helpers.ChipToggleButton(name="btn_categories")    # toggles action_catview
            self.btn_categories.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_CATEGORIES))
            self._sync_categories_button_pixmaps()
            self.btn_categories.setChecked(
                bool(self.pane.prefs.show_categories))
            self.btn_categories.toggled.connect(
                self._on_categories_button)
            self._toolbar_controls.append(self.btn_categories)
            self.btn_hip_capture = ui_helpers.IconMenuButton(    # every section: captures onto the selected tile
                None,
                self._ui_icon_path("icon_screenshot.svg"),
                on_click=self.pane.tile_capture.from_toolbar,
                fallback_label="Capture",
                name="btn_hip_capture",
            )
            self.btn_hip_capture.setToolTip(ui_helpers.tooltip_text(
                tooltips.PANEL_CAPTURE))
            self._toolbar_controls.append(self.btn_hip_capture)
        self.filter_action_group = None    # build_filter_menu fills the Filter menu on every section change
        self.filter_actions = {}

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
            self.action_generate = self.online_menu.addAction("Generate Material")
            self.action_generate.triggered.connect(self.pane.loading.generate_random_material)
            self.action_gallery_import = self.online_menu.addAction(
                "Gallery Import (.gal)"
            )
            self.action_gallery_import.triggered.connect(
                self.pane.saving.import_galleries
            )
            self.action_package_import = self.online_menu.addAction(
                "Import Package (.amazepkg)"
            )
            self.action_package_import.triggered.connect(
                self.pane.package_import.import_package
            )
            self.action_package_export = self.online_menu.addAction(
                "Export Asset (.amazepkg)"
            )
            self.action_package_export.triggered.connect(self.pane.assets.export_package)
            self.action_category_export = self.online_menu.addAction(
                "Export Category (.amazepkg)"
            )
            self.action_category_export.triggered.connect(self.pane.assets.export_category)
            menu_view.aboutToShow.connect(self.sync_package_export)    # each enabled only when it has something to export
            menu_view.removeAction(self.action_catview)    # the action stays, toggled by the toolbar button; only its menu row is removed
            self.online_source_group.triggered.connect(self._on_online_source)


    def sync_package_export(self) -> None:
        """Disable the View menu's two exports unless the shown context has what each writes."""
        assets = self.pane.assets
        self.action_package_export.setEnabled(bool(assets.exportable_selection()[1]))
        self.action_category_export.setEnabled(assets.exportable_category() is not None)

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
        self.cb_favsonly.toggled.connect(self.pane.show_favourites_only)
        if self.toolbar_layout is not None:
            self._toolbar_controls.append(self.cb_favsonly)

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
        self._section_scroll = {}    # per-section grid scroll, in memory only; the pane keeps the sidebar row
        splitter = self.cat_list.parentWidget()
        cat_index = -1
        if isinstance(splitter, QtWidgets.QSplitter):
            cat_index = splitter.indexOf(self.cat_list)
            if self.pane.prefs.show_notes and self.pane.prefs.show_info:
                self.pane.prefs.show_info = False    # one side pane at a time: the comments pane stays
            self.side_pane = side_pane.Pane(    # the splitter's rightmost pane: sidebar | grid | side pane
                self.pane.prefs, "notes_panel_width", theme.ui_px(amazetheme.drawn_comments()["width"]))
            self.side_pane.setMinimumWidth(theme.ui_px(side_pane.MIN_WIDTH))
            self.side_pane.hide()
            splitter.addWidget(self.side_pane)
            splitter.splitterMoved.connect(self._on_splitter_moved)
            self.notes_panel = notes_panel.NotesPanel(self.pane.prefs)    # its two pages: one shows at a time
            self.side_pane.add_page(self.notes_panel)
            self.notes_panel.copy_font_and_text_color(self.cat_list)
            self.notes_panel.changed.connect(self._on_note_saved)
            self.info_panel = info_panel.InfoPanel(self.pane.prefs)
            self.side_pane.add_page(self.info_panel)
            self.info_panel.copy_font(self.cat_list)
            self.info_panel.shown.connect(self._refresh_info_subject)    # hiding forgot the subject
            self._show_side_page()
            splitter.setHandleWidth(theme.ui_px(self._SIDEBAR["handle"]))    # width only; Houdini draws the grip ▸r/sidebar-from-frame
        width = theme.ui_px(self._SIDEBAR["width"])    # the last dragged width, never wider ▸r/sidebar-from-frame
        self.cat_wrapper = side_pane.Pane(self.pane.prefs, "sidebar_width", width, width)
        self.cat_list.setMaximumWidth(width)    # and the list's, at UI scale
        categories = side_pane.SidePage(side_pane.Page(    # no header; the category tree is its body
            None, None, (side_pane.Widget("tree", lambda: self.cat_list),)))
        self.cat_wrapper.add_page(categories)
        self.cat_wrapper.show_page(categories)
        if splitter is not None and cat_index >= 0:
            splitter.insertWidget(cat_index, self.cat_wrapper)    # the grid is the only flexible pane; the other two keep their width
            fixed_width = (self.cat_wrapper, getattr(self, "side_pane", None))
            for i in range(splitter.count()):
                flexible = splitter.widget(i) not in fixed_width
                splitter.setStretchFactor(i, 1 if flexible else 0)

    def _apply_theme_colours(self) -> None:
        """Every palette and stylesheet the panel sets from the theme; run at build and on a theme switch."""
        for view, role in ((self.cat_list, "surface_low"), (self.thumblist, "surface")):
            palette = view.palette()
            palette.setColor(QtGui.QPalette.ColorRole.Base, theme.color(role))
            view.setPalette(palette)
        if getattr(self, "toolbar_row", None) is not None:
            self.toolbar_row.setStyleSheet("background-color: %s; border: none; border-bottom: 1px solid %s;"
                                           % (theme.color_hex("surface"), theme.color_hex("field")))
        self.line_filter.setStyleSheet("QLineEdit { border: none; background-color: %s; padding-left: %dpx; }"
                                       % (theme.color_hex("field"), theme.ui_px(20)))
        if getattr(self, "filter_label", None) is not None:
            self.filter_label.setStyleSheet("color: %s;" % theme.color_hex("text_bright"))

    def _build_sidebar_palette(self) -> None:
        """The category list's palette and selection colours."""
        self.cat_list = self.ui.catview  # type: ignore
        cat_list_palette = self.cat_list.palette()    # palette, never a stylesheet: the viewport paints from Base/Text
        cat_list_palette.setColor(
            QtGui.QPalette.ColorRole.Text, delegates.AssetItemDelegate.TEXT_COLOR
        )
        self.cat_list.setPalette(cat_list_palette)    # no selection colours: Houdini's style sheet paints them
        self.sidebar_delegate = delegates.SidebarItemDelegate(self.cat_list)    # the name and its count

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
            self.ui.setFont(theme.ui_font(hou.qt.mainWindow().font()))    # only theme sets the minimum size; no `hou.qt` under hython
        except AttributeError:
            pass

        self.menu = self.ui.findChild(QtWidgets.QMenuBar, "menubar")    # hidden below; never styled
        self.action_catview = self.ui.action_show_cat  # type: ignore
        self.action_catview.triggered.connect(self.toggle_catview)

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
            self.toolbar_row.setFixedHeight(theme.ui_px(self._TOOLBAR["height"]))    # ▸r/toolbar-from-frame
            self.toolbar_layout = QtWidgets.QHBoxLayout(self.toolbar_row)
            self.toolbar_layout.setSpacing(0)
            self._toolbar_controls = []    # every control the builders make; _lay_out_toolbar orders them

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
        self.thumblist.viewport().setMouseTracking(True)    # mouse moves with no button down highlight the badges
        self.thumblist.viewport().installEventFilter(self)
        self.thumblist.doubleClicked.connect(self.import_asset_auto)
        self.thumblist.clicked.connect(self._refresh_notes_subject)    # idempotent
        self.thumblist.clicked.connect(self._refresh_info_subject)

        self.texture_progress = ui_helpers.ThinProgressBar()    # the thin bar above thumbview, hidden until there is work
        self.texture_progress.set_accent_color(theme.accent(self.pane.prefs.accent_color))
        self.set_conversion_bar_visible(False)
        thumb_layout = self.ui.findChild(QtWidgets.QVBoxLayout, "verticalLayout_7")
        if thumb_layout is not None:
            thumb_layout.insertWidget(0, self.texture_progress)

        self.thumbrows = dragdrop_widgets.DragDropRowsView()    # list mode: a second view sharing the grid's proxy and selection model
        self.thumbrows.setObjectName("thumbrows")
        self.thumbrows.setHeader(    # before `grid.set_up_rows_header` sets it up
            ui_helpers.GridHeaderView(
                QtCore.Qt.Orientation.Horizontal, self.thumbrows))
        self.thumbrows.setVisible(False)
        if thumb_layout is not None:
            thumb_layout.addWidget(self.thumbrows)
        grid.set_up_rows_header(self)
        self.thumbrows.setContextMenuPolicy(    # the grid's menu and primary action
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbrows.customContextMenuRequested.connect(
            self.thumblist_rc_menu)
        self.thumbrows.doubleClicked.connect(self.import_asset_auto)

        self._build_sidebar_palette()
        self.sidebar_delegate.set_drag_color(
            theme.accent(self.pane.prefs.accent_color)
        )
        self.cat_list.setItemDelegate(self.sidebar_delegate)
        self.cat_list.row_chosen.connect(self._on_category_chosen)    # mouse, keyboard or the view: one way in
        self._key_choice = None    # the row the arrow keys stopped on, shown once they pause
        self._key_choice_timer = QtCore.QTimer(self)
        self._key_choice_timer.setSingleShot(True)
        self._key_choice_timer.setInterval(SIDEBAR_KEY_PAUSE_MS)
        self._key_choice_timer.timeout.connect(self._show_key_choice)

        self.line_filter = self.ui.line_filter  # type: ignore
        self.line_filter.textEdited.connect(self.pane.type_search)    # only typing, never setText ▸p/filter-pass-cost
        self.line_filter.setPlaceholderText(section_base.Section.search_hint)    # every hint is ""
        self.line_filter.setToolTip(ui_helpers.tooltip_text(
            tooltips.PANEL_SEARCH))
        self.line_filter.setFixedHeight(theme.ui_px(self._TOOLBAR["field_h"]))    # ▸r/toolbar-from-frame
        self.line_filter.setMinimumWidth(theme.ui_px(38))    # overrides the .ui's own 80 minimum - setMinimumWidth takes precedence at runtime
        self.line_filter.setMaximumWidth(theme.ui_px(self._TOOLBAR["field_w"]))
        try:    # the magnifier: an overlay QLabel placed at an exact margin
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
            self._toolbar_controls += [self.filter_label, self.line_filter]

        self._build_splitter_and_sidebar()    # catview moves into a new wrapper, in its old place
        self.section_tabs = None
        self._build_section_tabs()    # the strip below the toolbar, rebuilt when enabled_sections changes
        self.ui.cb_FavsOnly.setVisible(False)  # type: ignore  -- unused; the chip below replaces it
        self._build_view_toggles()
        self.cb_viewmode.toggled.connect(self.on_viewmode_button)
        if self.toolbar_layout is not None:
            self._toolbar_controls.append(self.cb_viewmode)

        self.ui.details_widget.setParent(None)  # type: ignore  -- out of the splitter, not hidden ▸p/d03-retired

        self.menu_filter = QtWidgets.QMenu("Filter", self.menu)    # each section fills it
        self._build_menus()

        self.ui.slide_iconSize.setVisible(False)  # type: ignore  -- the ClickSlider below replaces it

        self.click_slider = ui_helpers.ClickSlider()
        self.click_slider.setObjectName("click_slider")    # _sync_slider_for_mode sets its tooltip
        self.click_slider.setOrientation(QtCore.Qt.Horizontal)  # type: ignore
        self.click_slider.setRange(64, 512)    # grid only; a tile below 64 is smaller than its badges
        self.click_slider.setValue(ui_helpers.ClickSlider.DEFAULT_VALUE)
        self.click_slider.setSingleStep(50)
        self.click_slider.setPageStep(50)
        self.click_slider.set_accent_color(theme.accent(self.pane.prefs.accent_color))
        self.click_slider.setMinimumWidth(theme.ui_px(38))    # same sizing rule as the filter box: 400px rendered max, 75px min
        self.click_slider.stepped = self.pane.prefs.step_size
        self._build_slider_and_layout()

    def _lay_out_toolbar(self) -> None:
        """Lay the row out left to right as frame B01 draws it, every gap read off the frame."""
        if self.toolbar_layout is None:
            return
        drawn, px = self._TOOLBAR, theme.ui_px
        controls = {widget.objectName(): widget for widget in self._toolbar_controls}
        layout = self.toolbar_layout
        layout.setContentsMargins(px(drawn["edge"]), 0, px(drawn["right_edge"]), 0)

        placed = set(drawn["left"] + drawn["right"]) | {"click_slider", "filter_label", "line_filter"}
        for name in sorted(set(controls) - placed):
            debug.event("toolbar", "control not in frame B01, so not shown", control=name)

        def buttons(names):
            present = [controls[name] for name in names if name in controls]
            for index, widget in enumerate(present):
                if index:
                    layout.addSpacing(px(drawn["gap"]))
                layout.addWidget(widget)

        buttons(drawn["left"])
        layout.addSpacing(px(drawn["slider_gap"]))
        layout.addWidget(controls["click_slider"], 1)    # these two fill to their widths first ▸r/toolbar-tabs-840
        layout.addSpacing(px(drawn["search_gap"]))
        layout.addWidget(controls["filter_label"])
        layout.addSpacing(px(drawn["label_gap"]))
        layout.addWidget(controls["line_filter"], 1)
        layout.addSpacing(px(amazetheme.TOOLBAR_SEARCH_END_GAP))    # kept when the panel is narrow
        layout.addStretch()
        buttons(drawn["right"])    # pinned to the right edge by the stretch

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
            grid.open_grid_menu(self, self.pane.active_section())    # the online section too
        finally:
            if watch is not None:
                after = self._grid_geometry()
                if after != watch:
                    debug.event("grid", "geometry changed by right-click",
                                before=watch, after=after)

    def catlist_rc_menu(self) -> None:
        """Sidebar right-click - the active context builds its own menu."""
        grid.open_catlist_menu(self, self.pane.active_section())    # the online section has no SIDEBAR_MENU


    def locate_unreadable_folder(self) -> None:
        """Locate in the unreachable-folder empty state: the folder it names is re-pointed."""
        self.pane.files.locate_unreadable(self.pane.empty_state.unreadable_folder())

    def _tile_badges(self, section) -> dict:
        """A tile delegate's badges and whether they take clicks, as the section declares them."""
        return dict(tile_badges=section.tile_badges,
                    on_badge=self._badge_click_handler if section.tile_badge_clicks else None)

    def _badge_click_handler(self, handler):
        """A badge click runs the section's `handler` method, by the engine's one rule for it."""
        return lambda index: self.pane.assets.click_badge(handler, index)

    def show_prefs(self, page: str = "") -> None:
        """Show Preferences, made as Houdini's own: one window per panel, a second open raises it."""
        if self._thumbsize_save_timer.isActive():    # flush a pending size save first
            self._thumbsize_save_timer.stop()
            self.pane.prefs.save()
        from amaze.dialogs import prefs_window
        window = getattr(self, "_prefs_window", None)
        try:
            open_now = window is not None and window.isVisible()
        except RuntimeError:    # closed: the window deleted itself, as Houdini's does
            open_now = False
        if not open_now:
            window = self._prefs_window = prefs_window.AmazePrefsWindow(self.pane.prefs, pane=self.pane)
            window.sharedState().applied.connect(self._apply_preferences)    # Apply, and Accept
            window.closed.connect(self._apply_preferences)    # any close: a library chosen behind it opens
            self.destroyed.connect(window.close)    # the window must not outlive the panel it applies to
        window.show()
        window.raise_()
        window.requestActivate()
        if page:
            window.setPageName(page)

    def _apply_preferences(self) -> None:
        """Apply everything Preferences changed: on the window's Apply or Accept, and at its close."""
        try:
            self.isVisible()    # the panel may be deleted already
        except RuntimeError:
            return

        if not self.pane.material_model or not self.pane.category_model:    # still no library after the dialog - nothing below applies
            return

        self.apply_view_mode()    # mode-aware: respects grid vs list
        self.pane.apply_preferences()
        accent = theme.accent(self.pane.prefs.accent_color)
        self.click_slider.set_accent_color(accent)
        self.click_slider.stepped = self.pane.prefs.step_size
        if self.pane.prefs.view_mode != "list":
            self.click_slider.setValue(self.pane.tile_size())    # with Step Size on, snapped to the nearest step
        self.texture_progress.set_accent_color(accent)
        self._sync_notes_button_pixmaps()
        self._sync_info_button_pixmaps()
        self.sidebar_delegate.set_drag_color(accent)
        self.sidebar_delegate.show_counts = self.pane.prefs.sidebar_counts
        grid.visible_view(self).viewport().update()

    def _build_section_tabs(self) -> None:
        """(Re)build the one tab strip: the enabled sections, or the online sources while online."""
        segments = self.pane.tabs()
        if getattr(self, "section_tabs", None) is not None:    # replaces the strip at layout index 1
            if self._central_layout is not None:
                self._central_layout.removeWidget(self.section_tabs)
            self.section_tabs.deleteLater()
        self.section_tabs = ui_helpers.SectionTabBar(segments)
        self.section_tabs.segmentClicked.connect(self.pane.choose_tab)
        self.section_tabs.cancelClicked.connect(self.pane.cancel_work)
        bar = getattr(self, "texture_progress", None)
        self.section_tabs.set_cancel_visible(    # read from the bar, so a rebuild during a batch matches it
            bar is not None and not bar.isHidden())
        if self._central_layout is not None:
            self._central_layout.insertWidget(1, self.section_tabs)
        self.section_tabs.setChecked(self.pane.current_tab(), emit=False)    # setup() activates; models may not exist yet


    TOOLBAR_CONTROLS = (    # (control, context fact, "enabled" or "shown")
        ("cb_favsonly", "takes_favourites", "enabled"),
        ("btn_notes", "takes_comments", "enabled"),
        ("btn_info", "takes_info", "enabled"),
        ("btn_filter", "takes_filter_menu", "enabled"),
        ("btn_hip_capture", "takes_capture", "enabled"),
    )

    def _sync_toolbar(self, context) -> None:
        """Set every toolbar control from TOOLBAR_CONTROLS and what `context` declares."""
        for name, fact, effect in self.TOOLBAR_CONTROLS:
            control = getattr(self, name, None)
            if control is None:
                continue
            offered = bool(getattr(context, fact, True))
            if effect == "shown":
                control.setVisible(offered)
            else:
                control.setEnabled(offered)
        btn_filter = getattr(self, "btn_filter", None)
        if btn_filter is not None:    # online it opens the kind filter
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
            getattr(self.pane.active_section(), "search_hint",
                    section_base.Section.search_hint))

    def tile_delegates(self) -> tuple:
        """EVERY tile delegate, once, from the sections; the tests use it to reach them all."""
        found = []
        for section in self.pane.sections.values():
            name = getattr(section, "delegate_attr", "")
            delegate = getattr(self, name, None) if name else None
            if delegate is not None and delegate not in found:
                found.append(delegate)
        online = getattr(self, "matx_delegate", None)    # by name: the online section is not in `sections`
        if online is not None and online not in found:
            found.append(online)
        return tuple(found)

    def _on_online_source(self, action) -> None:
        """A source entry: Material Library leaves online, an online source opens its browser."""
        if action is self.action_material_library:
            self.pane.leave_online()
            if self.pane.current_section != "material":
                self.section_tabs.setChecked("material")
        elif action.isChecked():    # the entries share one exclusive group, so Qt keeps exactly one checked
            self.pane.open_online_source(action.text())

    def _category_under_cursor(self):
        return sidebar.category_under_cursor(self)

    def _folder_under_cursor(self):
        return sidebar.folder_under_cursor(self)

    def _set_drag_hover_row(self, row) -> None:
        """Highlight a sidebar row by its index, or clear with -1. Logic in panel/sidebar.py."""
        sidebar.set_hover_row(self, row)

    def _update_category_drag_hover(self, pos) -> None:
        sidebar.update_hover(self, pos)

    def _update_category_drag_hover_global(self) -> None:
        sidebar.update_hover_global(self)

    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """A splitter drag records both side panes' widths; the debounced save writes them."""
        pane = getattr(self, "side_pane", None)
        if pane is None:
            return
        splitter = pane.parentWidget()
        if not isinstance(splitter, QtWidgets.QSplitter):
            return
        panes = [widget for widget in (pane, getattr(self, "cat_wrapper", None)) if widget is not None]
        recorded = [widget.remember_width(splitter) for widget in panes]
        if any(recorded):
            self._thumbsize_save_timer.start()

    def toggle_notes_panel(self) -> None:
        """Toggle the Notes pane through its toolbar button, so the two always match."""
        button = getattr(self, "btn_notes", None)
        if button is not None:
            button.setChecked(not button.isChecked())

    def _on_notes_toggled(self, checked: bool) -> None:
        """Show or hide the pane and remember it; the grid takes up the width."""
        if getattr(self, "notes_panel", None) is None:
            return
        self.pane.prefs.show_notes = bool(checked)
        self._show_side_page(self.notes_panel if checked else None)
        self.pane.prefs.save()
        if checked:
            self._close_other_pane("btn_info")
            self._refresh_notes_subject()

    def toggle_info_panel(self) -> None:
        """Toggle the info pane through its toolbar button, so the two always match."""
        button = getattr(self, "btn_info", None)
        if button is not None:
            button.setChecked(not button.isChecked())

    def _on_info_toggled(self, checked: bool) -> None:
        """Show or hide the info pane and remember it; opening it closes the comments pane."""
        if getattr(self, "info_panel", None) is None:
            return
        self.pane.prefs.show_info = bool(checked)
        self._show_side_page(self.info_panel if checked else None)
        self.pane.prefs.save()
        if checked:
            self._close_other_pane("btn_notes")
            self._refresh_info_subject()

    def _show_side_page(self, opened=None) -> None:
        """Show the side pane's page: the one just `opened`, else the one the settings have on."""
        page = opened
        if page is None and self.pane.prefs.show_notes:
            page = self.notes_panel
        if page is None and self.pane.prefs.show_info:
            page = self.info_panel
        self.side_pane.show_page(page)

    def _close_other_pane(self, button_name: str) -> None:
        """Uncheck the other side pane's button; its own handler hides the pane and saves."""
        button = getattr(self, button_name, None)
        if button is not None and button.isChecked():
            button.setChecked(False)

    def _sync_info_button_pixmaps(self) -> None:
        """The button's icon: its art's own colour while closed, INFO_ICON_COLOR while open."""
        button = getattr(self, "btn_info", None)
        if button is None:
            return
        button.set_art(
            self._ui_icon_path("icon_info.svg"),
            lighten_on_hover=False,
            recolour_on={amazetheme.INFO_ICON_ART_COLOR: amazetheme.INFO_ICON_COLOR})

    def _sync_notes_button_pixmaps(self) -> None:
        """The button's icon: its art's own colour while closed, COMMENT_ICON_COLOR while open."""
        button = getattr(self, "btn_notes", None)
        if button is None:
            return
        button.set_art(
            self._ui_icon_path("icon_comments.svg"),
            lighten_on_hover=False,
            recolour_on={amazetheme.COMMENT_ICON_ART_COLOR: amazetheme.COMMENT_ICON_COLOR})

    def _on_note_saved(self, _key: str) -> None:
        """A note was saved: repaint the grid so the tile's note badge appears or disappears."""
        grid.visible_view(self).viewport().update()    # `NotesRole` emits no `dataChanged`

    def _notes_subject(self):
        """What the Comments pane points at, or None; the section returns its selected tile's."""
        context = self.pane.active_section()
        if context is None or not context.takes_comments:    # the context decides
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

    def _info_subject(self):
        """What the info pane shows, or None: one selected row's, or several rows' together."""
        context = self.pane.active_section()
        if context is None or not context.takes_info:    # the context decides
            return None
        indexes = grid_columns.selected_rows(    # grid and list share this selection
            context.grid_selection_model())
        if not indexes:
            return None
        if len(indexes) == 1:
            return context.info_subject(indexes[0])
        return context.info_subject_for(indexes)

    def _refresh_info_subject(self, *_args) -> None:
        """Point the info pane at the current selection; returns at once while it is hidden."""
        panel = getattr(self, "info_panel", None)
        if panel is None or panel.isHidden():
            return
        subject = self._info_subject()
        if subject is None:
            panel.clear_subject()
        else:
            panel.set_subject(subject)

    def set_conversion_bar_visible(self, visible: bool) -> None:
        """The only setter of the conversion bar's visibility, and the Cancel button's with it."""
        self.texture_progress.setVisible(visible)
        tabs = getattr(self, "section_tabs", None)    # None during init_ui
        if tabs is not None:
            tabs.set_cancel_visible(visible)

    def build_filter_menu(self) -> None:
        """Fill the Filter menu from the pane's entries and check the one in force."""
        section = self.pane.active_section()
        entries = self.pane.filter_entries()
        self.menu_filter.clear()    # deletes the menu's actions, emptying the group, never the group itself
        if self.filter_action_group is None:
            self.filter_action_group = QtGui.QActionGroup(self.menu_filter)    # ONE, for the session
            self.filter_action_group.setExclusive(True)
            self.filter_action_group.triggered.connect(self.filter_menu_changed)
        self.filter_actions = {}
        button = getattr(self, "btn_filter", None)
        if button is not None:
            if (section is not None
                    and not getattr(section, "takes_filter_menu", True)):
                button.setVisible(True)    # the toolbar table disables it
            else:
                button.setVisible(bool(entries))    # no entries, no button
            if section is not None and not getattr(
                    section, "kind_filter_menu", False):    # online, _sync_toolbar sets the tooltip
                button.setToolTip(ui_helpers.tooltip_text(
                    section.filter_tooltip))
        if not entries:
            return
        for entry_id, label, _value, icon in entries:
            act = self.menu_filter.addAction(label)
            if icon:
                act.setIcon(ui_helpers.menu_icon(icon, self))
            act.setCheckable(True)
            act.setData(entry_id)
            self.filter_action_group.addAction(act)
            self.filter_actions[entry_id] = act
            if icon and entry_id == entries[0].id:
                self.menu_filter.addSeparator()    # a menu with icons separates the everything-entry
        self.filter_actions[self.pane.filter_choice()].setChecked(True)

    def filter_menu_changed(self, action) -> None:
        """An entry was picked: the pane applies it and remembers it for this tab."""
        self.pane.choose_filter(action.data())

    def clear_favourites_filter(self) -> None:
        """Favourites empty state's Show All: unchecks `cb_favsonly`; `toggled` does the rest."""
        chip = getattr(self, "cb_favsonly", None)
        if chip is not None:
            chip.setChecked(False)

    def clear_filter_box(self) -> None:
        """The empty state's Clear Search button."""
        box = getattr(self, "line_filter", None)
        if box is None or not box.text():
            return
        box.clear()
        self.pane.search("")    # by hand: clear() emits no `textEdited`

    def _on_category_chosen(self, index) -> None:
        """The user made another sidebar row current; a right press only moves the highlight."""
        buttons = QtWidgets.QApplication.mouseButtons()
        if buttons & QtCore.Qt.MouseButton.RightButton:
            return
        self._key_choice_timer.stop()
        if buttons == QtCore.Qt.MouseButton.NoButton:    # the keyboard: each step would list a File folder, so wait for a pause
            self._key_choice = QtCore.QPersistentModelIndex(index)
            self._key_choice_timer.start()
            return
        self._key_choice = None
        self.pane.sidebar.show_row(index)

    def _show_key_choice(self) -> None:
        """The arrow keys paused: show the row they stopped on, if it is still there."""
        index, self._key_choice = self._key_choice, None
        if index is not None and index.isValid() and index.model() is self.cat_list.model():
            self.pane.sidebar.show_row(QtCore.QModelIndex(index))

    def import_asset_auto(self, index: QtCore.QModelIndex | None = None):
        """The grid's double-click: the pane's, as the QML pane's."""
        self.pane.double_click(index)

    def slide(self) -> None:
        """The slider's value as the grid's persisted tile size; list mode ignores it."""
        if not self.pane.material_model or not self.pane.category_model:
            return
        if self.pane.prefs.view_mode == "list":
            return    # list has one size
        value = self.click_slider.value()
        self.pane.prefs.thumbsize = value
        self._thumbsize_save_timer.start()    # saved once the drag stops
        self.apply_view_mode()    # sizing for the active mode - grid grows icons, list grows rows

