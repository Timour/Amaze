"""The pane engine object: what one pane shows, its sections, and the signals its host follows."""

import contextlib

from PySide6 import QtCore

from amaze import amazetheme
from amaze.core import debug, matx_sources, section_list
from amaze.helpers import hostos
from amaze.pane import (assets, drop_placement, empty_state, files, library, loading,
                        online_import, package_import, saving, sidebar, tile_capture)
from amaze.prefs import prefs
from amaze.render import husk_job

FILTER_DEBOUNCE_MS = 180    #: the search box's pause before it filters ▸p/filter-pass-cost


class Pane(QtCore.QObject):
    """One pane's engine: prefs, library models, sections, and the work they do; no widget."""

    models_built = QtCore.Signal()    # a library's models exist: the host builds what shows them
    library_shown = QtCore.Signal()    # the first section of a newly opened library is shown
    library_switching = QtCore.Signal()    # the models are about to read another library
    library_switched = QtCore.Signal()    # the models now read the library in `prefs.dir`
    library_updated = QtCore.Signal()    # the library was updated to this Amaze's version
    context_leaving = QtCore.Signal()    # the shown section is about to change
    context_bound = QtCore.Signal(object)    # this section's models go on the sidebar and grid
    context_shown = QtCore.Signal(object)    # this section, or online, is shown and filtered
    tabs_changed = QtCore.Signal()    # the tab list changed: `tabs()` and `current_tab()`
    online_changed = QtCore.Signal()    # online opened, closed, or became possible
    filter_changed = QtCore.Signal()    # the Filter menu's entries or its choice changed
    sidebar_highlight = QtCore.Signal(QtCore.QModelIndex)    # the app moves the sidebar's highlight
    sidebar_reveal = QtCore.Signal(str)    # unfold the sidebar down to this folder
    sidebar_changed = QtCore.Signal()    # sidebar rows changed without a layout signal
    grid_reordered = QtCore.Signal()    # a grid proxy was sorted, maybe by another pane
    grid_to_top = QtCore.Signal()    # the grid shows its first row
    progress_shown = QtCore.Signal(bool)    # background work's bar shown or hidden
    progress = QtCore.Signal(int, int)    # background work done, of total
    empty_changed = QtCore.Signal()    # the shown grid's rows changed: `empty_state.verdict()` may differ

    ALL_SECTIONS = section_list.SECTIONS    # (key, label) in order; keys are stored, never rename one

    def __init__(self, ui, parent=None) -> None:
        super().__init__(parent)
        self.ui = ui    # the host: an `asks.Asks`
        self.prefs = prefs.Prefs()
        self.prefs_loaded = self.prefs.load()    # False when nothing usable is on disk; populated either way
        debug.configure(self.prefs.debug_mode)    # before the library opens, so a crash there is logged
        debug.prefs_snapshot(self.prefs)
        hostos.set_cache_override(self.prefs.cache_dir)    # set before any cache is touched
        self.sections = {}    # one object per tab, built with the models
        self.online_context = None    # a Section's interface, not in `sections`; `active_section()` returns it
        self.current_section = "material"
        self.online_mode = False
        self.online_source = None
        self.search_text = ""
        self.favourites_only = False
        self._sidebar_choice = {}    # section key -> the sidebar row's shown text when it was left
        self._search_timer = QtCore.QTimer(self)    # only typing starts it ▸p/filter-pass-cost
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(FILTER_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._apply_search)
        self.library = library.Library(self)
        self.sidebar = sidebar.Sidebar(self)
        self.assets = assets.Assets(self)
        self.loading = loading.Loading(self)
        self.saving = saving.Saving(self)
        self.files = files.Files(self)
        self.online_import = online_import.OnlineImport(self)
        self.package_import = package_import.PackageImport(self)
        self.drop_placement = drop_placement.DropPlacement(self)
        self.tile_capture = tile_capture.TileCapture(self)
        self.empty_state = empty_state.EmptyState(self)
        husk_job.jobs.progressed.connect(self._on_render_progress)    # bound: jobs outlive the pane
        husk_job.jobs.activeChanged.connect(self._on_render_active)

    def active_section(self):
        """The active context: a Section, or the online section while it is shown."""
        if self.online_mode:
            return self.online_context
        return self.sections.get(self.current_section)

    def is_online(self) -> bool:
        """Whether the online section is shown; the one check every handler uses."""
        return bool(self.online_mode)    # `current_section` still names the local section underneath

    def tile_icon_models(self) -> tuple:
        """Every model whose tiles can show an icon, once, from each section's `tile_models()`."""
        found = []
        for section in self.sections.values():
            model = section.tile_models()[0]
            if model is not None and model not in found:
                found.append(model)
        return tuple(found)

    def online_tabs(self) -> list:
        """The online strip: one tab per source, in source order; enabled_sections does not apply."""
        return [(source.name, source.name) for source in matx_sources.all_sources()]

    def tabs(self) -> list:
        """The tab strip's (key, label): the enabled sections, or the online sources while online."""
        if self.is_online():
            segments = self.online_tabs()
        else:
            enabled = self.prefs.enabled_sections
            segments = [(k, lbl) for (k, lbl) in self.ALL_SECTIONS if k in enabled]
        return segments or [("material", "Material")]

    def current_tab(self) -> str:
        """The tab shown checked: the source online, else the section, else the first tab."""
        keys = [key for key, _ in self.tabs()]
        current = self.online_source if self.is_online() else self.current_section
        return current if current in keys else keys[0]

    def choose_tab(self, key: str) -> None:
        """A tab was clicked: a source online, else a section; an unbuilt section changes nothing."""
        if self.is_online():
            self.open_online_source(key)
            return
        if self.material_model is None:    # no library yet
            return
        self._leave_context()    # the outgoing section's, before anything changes
        self.current_section = key
        debug.event("section", "switched", to=key, online=self.is_online())
        section = self.sections.get(key)
        if section is None:
            debug.event("section", "section not built yet - the view "
                        "below will not change", section=key)
            return
        self.show_context(section)

    def show_context(self, context) -> None:
        """Show a context and all that follows; the only path, for every section and online."""
        proxy = context.tile_models()[1]
        with proxy.one_pass() if proxy is not None else contextlib.nullcontext():    # one filter pass ▸p/filter-pass-cost
            context.activate()
            context.filter_text(self.search_text)
            context.filter_favorites(self.favourites_only)
            self._apply_filter_choice()    # each section keeps its own menu choice
            self._restore_sidebar_choice(context.key)
        self.context_shown.emit(context)
        self.empty_state.watch()

    def bind(self, section) -> None:
        """Show `section`'s models on the host's sidebar and grid; the bar may be another section's."""
        listed = getattr(self, section.sidebar_attr, None) if section.sidebar_attr else None
        if listed is not None:
            self.sidebar.show_model(listed)
        self.context_bound.emit(section)
        self.show_progress(False)

    def _leave_context(self) -> None:
        """Remember the shown section's sidebar row for `_restore_sidebar_choice`; the host its scroll."""
        current = self.sidebar.current()    # a fresh index, safe for `.data()`
        self._sidebar_choice[self.current_section] = current.data() if current is not None else None
        self.context_leaving.emit()

    def _restore_sidebar_choice(self, key: str) -> None:
        """Re-select the section's last sidebar row by its shown text; File restores its own."""
        text = self._sidebar_choice.get(key)
        model = self.sidebar.model
        if not text or key in ("file",) or model is None:
            return
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            if index.data() == text:
                self.sidebar.highlight(index)
                self.sidebar.show_row(index)    # what a row the user chose runs
                break

    def enter_online(self, source: str = "") -> None:
        """Switch to the online tab strip; leaving returns to the section shown before."""
        if self.is_online():
            return
        if getattr(self, "matx_online_model", None) is None:    # no online model: online cannot open
            self.online_changed.emit()
            return
        self._leave_context()    # what leaving restores
        self.online_mode = True
        first = source or self.online_tabs()[0][0]
        self.tabs_changed.emit()
        self.open_online_source(first)
        self.online_changed.emit()

    def leave_online(self) -> None:
        """Return to the local sections: the one left, or the first shown if it was hidden."""
        if not self.is_online():
            return
        self.online_mode = False
        self.online_changed.emit()
        debug.event("online", "exited")
        self.tabs_changed.emit()    # the strip checks the tab of `current_section`
        section = self.active_section()    # the section underneath: no tab click re-points the views here
        if section is not None:
            self.show_context(section)

    def open_online_source(self, source_name: str) -> None:
        """Show one source in the online section; a tab click, as the tabs are the sources."""
        if not self.is_online():
            self.enter_online(source_name)    # `enter_online` does the entering, for any caller
            return
        self.online_source = source_name
        debug.event("online", "source opened", source=source_name)
        self.matx_online_model.set_source(source_name)
        self.show_context(self.online_context)
        self._select_online_all()    # a source pick starts on "All"

    def _select_online_all(self) -> None:
        """Select the online sidebar's "All" row and clear any category filter."""
        if self.matx_source_model.rowCount() == 0:
            return
        self.sidebar.highlight(self.matx_source_model.index(0, 0))
        self.sidebar.show_row()

    def enabled_sections_changed(self) -> None:
        """The enabled sections changed: new tabs, and a hidden current section gives way to the first."""
        enabled = self.prefs.enabled_sections
        self.tabs_changed.emit()
        if self.current_section not in enabled and self.material_model:
            keys = [k for k, _ in self.ALL_SECTIONS if k in enabled] or ["material"]
            if self.is_online():
                self.current_section = keys[0]    # a tab here is a SOURCE; leaving Online shows this one
            else:
                self.choose_tab(keys[0])

    def set_view_mode(self, mode: str) -> None:
        """Grid or list, saved at once; the host shows it."""
        self.prefs.view_mode = mode
        self.prefs.save()

    def tile_size(self) -> int:
        """The tile size in use: list's one size, else the saved one, on a step under Step Size."""
        if self.prefs.view_mode == "list":
            return amazetheme.LIST_TILE_SIZE
        if self.prefs.step_size:
            return min(amazetheme.TILE_SIZES, key=lambda size: abs(size - self.prefs.thumbsize))
        return self.prefs.thumbsize

    def scroll_grid_to_top(self) -> None:
        self.grid_to_top.emit()

    def type_search(self, text: str) -> None:
        """The search box was typed in: the shown context is filtered once typing pauses."""
        self.search_text = text
        self._search_timer.start()

    def search(self, text: str) -> None:
        """Filter the shown context by `text` now; online, the source's API searches."""
        self.search_text = text
        self._apply_search()

    def _apply_search(self) -> None:
        section = self.active_section()
        if section is not None:
            section.filter_text(self.search_text)

    def show_favourites_only(self, on: bool) -> None:
        """The Favourites star: the shown context shows only favourites, or everything."""
        self.favourites_only = bool(on)
        section = self.active_section()
        if section is not None:
            section.filter_favorites(self.favourites_only)

    def filter_entries(self) -> tuple:
        """The active section's FilterEntry rows, everything-entry first; () for none."""
        section = self.active_section()
        return tuple(section.filter_entries()) if section is not None else ()

    def filter_choice(self) -> str:
        """The id of the Filter entry in force: the one remembered for this tab, else the first."""
        entries = self.filter_entries()
        if not entries:
            return ""
        remembered = self.prefs.section_filter(self.current_section)
        return remembered if any(entry.id == remembered for entry in entries) else entries[0].id

    def choose_filter(self, entry_id: str) -> None:
        """An entry was picked: apply it and remember it for this tab."""
        self._apply_filter_choice(entry_id)
        self.prefs.set_section_filter(self.current_section, entry_id)
        self.prefs.save()

    def refresh_filter(self) -> None:
        """A renderer was enabled or disabled: the choice applied again, the menu rebuilt whole."""
        self._apply_filter_choice()
        self.filter_changed.emit()

    def _apply_filter_choice(self, entry_id=None) -> None:
        """Apply the entry `entry_id`, by default the one in force, to the active section."""
        section = self.active_section()
        entries = self.filter_entries()
        if section is None or not entries:
            return
        entry_id = self.filter_choice() if entry_id is None else entry_id
        value = next((entry.value for entry in entries if entry.id == entry_id), None)
        section.apply_filter(value)
        proxy = getattr(self, section.proxy_attr, None) if section.proxy_attr else None
        debug.event(
            "filter", "section filter applied",
            section=self.current_section, entry=entry_id, value=str(value),
            visible=proxy.rowCount() if proxy is not None else -1,
        )

    def apply_preferences(self) -> None:
        """Preferences applied or closed: the filter, the settings read again, and all that follows."""
        if not self.material_model or not self.category_model:    # still no library: nothing applies
            return
        self.refresh_filter()    # a renderer may have been enabled or disabled
        self.settings_applied(self.library.reread_settings())

    def settings_applied(self, switched: bool) -> None:
        """Preferences applied: the sidebars, the shown section and the tabs follow the settings."""
        from amaze.core import thumbnails
        thumbnails.engine.set_budget_mb(self.prefs.ram_cache_mb)
        for proxy in self.sidebar.proxies():
            proxy.hide_empty = self.prefs.hide_empty_categories
        self.sidebar.refresh()    # selects All if hiding empty categories hid the selected row
        section = self.active_section()
        if section is not None and not switched:    # a switch has just refreshed it
            section.prefs_changed()
        self.enabled_sections_changed()    # visible section tabs may have changed in Preferences

    def show_progress(self, visible: bool) -> None:
        """Background work's bar shown or hidden; the host shows its Cancel button with it."""
        self.progress_shown.emit(bool(visible))

    def cancel_work(self) -> None:
        """The Cancel button: stop a background render, else the File batch's conversions."""
        if husk_job.jobs.busy():    # a background thumbnail render is using the bar
            husk_job.jobs.cancel()
            return
        model = getattr(self, "file_files_model", None)
        if model is not None:
            model.cancel_conversions()    # the model owns the pair and its order

    def _on_render_progress(self, done: int, total: int) -> None:
        """A background thumbnail render's progress, on the bar whichever tab shows."""
        self.show_progress(True)
        self.progress.emit(done, total)

    def _on_render_active(self, active: bool) -> None:
        """The bar is shown when a background render starts and hidden when the last one ends."""
        self.show_progress(active)
        if active:
            self.progress.emit(0, 100)

    def _on_texture_progress(self, done: int, total: int) -> None:
        """The bar over the grid while thumbnails generate; hidden with nothing left to do."""
        if husk_job.jobs.busy():    # a background thumbnail render is using the bar
            return
        if total <= 0 or done >= total:
            self.show_progress(False)
            return
        self.show_progress(True)
        self.progress.emit(done, total)

    def _on_online_preview_progress(self, done: int, total: int) -> None:
        """The same bar for the online preview pool, only while the online browser shows."""
        if not self.is_online() or self.online_import.downloading:    # a download import uses the bar
            return
        self._on_texture_progress(done, total)

    def _on_file_folder_progress(self, done: int, total: int) -> None:
        """The File model's progress: the bar shows only while File is shown, not online."""
        if self.is_online() or self.current_section != "file":    # online, it can still be File
            return
        self._on_texture_progress(done, total)
