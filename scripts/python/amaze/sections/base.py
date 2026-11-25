"""The Section base every tab builds on: the declarations and the shared menu rows. ▸o/section-api"""

from __future__ import annotations

import collections
import functools
import hashlib
import os

import hou
from PySide6 import QtCore

from amaze import amazetheme, messages
from amaze.core import category, category_list, debug, file_info, grid_columns
from amaze.core import multifilterproxy_model, notes

AssetStack = collections.namedtuple(
    "AssetStack", "model proxy selection categories")


CommentSubject = collections.namedtuple("CommentSubject", "key name type")


FilterEntry = collections.namedtuple(    # `id` is what the remembered choice saves, so a label can change
    "FilterEntry", "id label value icon", defaults=(None,))


DropRule = collections.namedtuple(
    "DropRule",
    "on_node on_space resolve click_on_node click_resolve "
    "holder_node_type context native_drag "    # native_drag: a handler; DragSession switches to Qt's drag by it
    "on_viewer",    # a handler for a release over a scene viewer; the drag highlights the object or prim
    defaults=(None, None, None, None, None, "", "", None, None),
)    # context: the childTypeCategory a network must have to accept this drop ("" = any network)


MenuEntry = collections.namedtuple(    # opens: the asks.Asks window the row opens, greyed where a host lacks it
    "MenuEntry",
    "label handler needs shown children count_suffix checkable opens glyph chip_glyph",
    defaults=("", "any", "", "", False, "", "", "", ""),
)    # glyph: the row's Phosphor glyph by name; chip_glyph: its colour rows' glyph, "" a square


SEPARATOR = MenuEntry("")  # the empty label is what makes it a divider


GRID_MENU_TAIL = (    # the tile's picture rows, Render Image only where one renders, as in C01
    MenuEntry("Render Image", handler="menu_update_preview", shown="menu_offers_preview",
              glyph="film_slate"),
    MenuEntry("Capture Image", handler="menu_capture", needs="menu_capture_enabled",
              glyph="rectangle_dashed"),
    MenuEntry("Customize", handler="menu_customize", opens="open_customize", glyph="toggle_left"),
    SEPARATOR,
    MenuEntry("Favorite", handler="menu_favourite", glyph="heart"),
    MenuEntry("Delete", handler="menu_delete", shown="deletes_rows", glyph="trash"),
)


def _disconnect(signal, slot, *_destroyed) -> None:
    """Drop a connection a section made; one already gone is no error."""
    try:
        signal.disconnect(slot)
    except (RuntimeError, TypeError):
        pass


class Section:
    """Base protocol: built with the pane engine, reads its models by attribute name. ▸o/section-api"""

    key = ""
    label = ""            # the tab's human label, read from section_list by key

    takes_comments = True    # a comment needs a library asset; online has none
    takes_info = True    # the info pane describes a library item or a file; online has neither
    takes_favourites = True  # online rows return False, so the favourites filter empties the grid
    takes_filter_menu = True  # the entries describe the LOCAL section under it
    kind_filter_menu = False  # True for online: the filter menu offers All/Materials/Colors/Nodes/Code there
    takes_capture = True    # Capture saves the Scene View image as a tile's thumbnail ▸r/tile-captures
    exports_categories = False    # the View menu's Export Category is enabled where the sidebar holds categories

    empty_noun = "items"  # the noun the shared empty-state texts use for these

    sidebar_attr = ""     # the list the sidebar shows
    proxy_attr = ""       # the grid's proxy, which `activate` binds to the grid views
    delegate_attr = ""
    tile_badges: tuple = ()    # the badge IDs this section's tile shows ▸r/tile-from-frame
    tile_badge_clicks = True    # its tile badges are buttons; where False they only show a state
    list_columns: tuple = ("name", "type")    # what its list shows where its model fills it ▸p/list-columns
    library_model_attrs: tuple = ()  # re-pointed on a library switch; () is a valid value
    selection_attr = ""   # a menu acts on THIS section's selection
    GRID_MENU: tuple = ()     # MenuEntry rows; empty = no menu opens
    SIDEBAR_MENU: tuple = ()  # same shape, same builder
    DROP = None           # one DropRule, or None for a section that never drags
    DROP_BY_KIND: dict = {}  # File declares per row KIND; non-empty takes precedence over DROP

    holder_node_type = ""     # the node type a drop on empty network space creates, when constant
    holder_node_type_method = ""  # names a method instead, where it is not
    search_hint = ""      # per-ARCHETYPE: the archetype decides what is MATCHED
    FILTER_CHOICES: tuple = ()  # FilterEntry rows after the everything-entry
    ALL_ID = "All"        # the everything-entry's id
    ALL_LABEL = "All"     # the everything-entry, and the stale-choice fallback
    filter_tooltip = ""   # per SECTION: what the menu narrows by

    def __init__(self, pane) -> None:
        self.pane = pane
        sidebar = self._p(self.sidebar_attr)
        if sidebar is None:
            return
        self._reselect_timer = QtCore.QTimer(pane)    # restarted by every signal, so it fires once per event loop pass
        self._reselect_timer.setSingleShot(True)
        self._reselect_timer.setInterval(0)
        self._reselect_timer.timeout.connect(self._reselect_sidebar_row_if_shown)
        for moved in (sidebar.modelReset, sidebar.layoutChanged, sidebar.rowsRemoved):
            self.follow(moved, self._sidebar_rows_changed)

    def follow(self, signal, slot) -> None:
        """`signal` calls `slot` until the pane is deleted: Qt cannot disconnect a section."""
        signal.connect(slot)
        self.pane.destroyed.connect(functools.partial(_disconnect, signal, slot))

    def reject_drop(self) -> bool:
        """A drop no target accepts: the red cross and a status line that it was canceled; False."""
        debug.refuse(messages.DROP_CANCELED)
        return False

    def activate(self) -> None:
        """Show this section's models on the pane's views, then select its sidebar row. ▸o/section-api"""
        self.before_sidebar_shown()
        self.pane.bind(self)
        self.after_views_bound()
        self.restore_sidebar_selection()

    def before_sidebar_shown(self) -> None:
        """Runs first on entering, before the list is set on the sidebar. Default: nothing."""

    def after_views_bound(self) -> None:
        """Runs on entering, once the sidebar and grid show this section's models. Default: nothing."""

    def restore_sidebar_selection(self) -> None:
        """Select this section's sidebar row on entering; a `setModel` leaves none. Default: nothing."""

    def grid_selection(self) -> list:
        """This section's grid selection as its own proxy's indexes, one per row."""
        return grid_columns.selected_rows(self.grid_selection_model())

    def grid_selection_model(self):
        """This section's grid selection MODEL, for a query about one row."""
        return self._p(self.selection_attr)

    def shown_list_columns(self) -> tuple:
        """The `grid_columns.KEYS` its list shows, in that order: those it names that its model fills."""
        proxy = self._p(self.proxy_attr)
        fills = getattr(proxy.sourceModel() if proxy is not None else None, "_column_role", None)
        return tuple(key for key in grid_columns.KEYS
                     if key in self.list_columns and fills is not None and fills(key) is not None)

    def tile_models(self):
        """(model, proxy) for the tile a menu is acting on - what the shared Customize handler needs."""
        return None, None

    def _model_and_rows(self, indexes):
        """(tile model, SOURCE rows) behind proxy indexes; one that no longer maps is skipped."""
        model, proxy = self.tile_models()
        if model is None or proxy is None:
            return None, []
        sources = (proxy.mapToSource(index) for index in indexes if index is not None)
        return model, [source.row() for source in sources if source.isValid()]

    def sidebar_selection(self) -> list:
        """The Sidebar's selected rows, one index each."""
        return list(self.pane.sidebar.rows())

    def prefs_changed(self) -> None:
        """Preferences just closed: re-scan live filesystem or render state here. Default: nothing."""
        pass

    takes_language = False    # D09's Language row is enabled only for a section that stores one

    def can_save(self, nodes) -> bool:
        """Whether these scene nodes can be saved into this section. ▸p/save-section-row"""
        return False

    def save_categories(self) -> tuple:
        """(the categories this section's save offers, the one pre-selected)."""
        return [], ""

    def commit_save(self, nodes, node, dialog) -> None:
        """Save into this section from an accepted D09; `node` is the target node, among `nodes`."""
        raise NotImplementedError

    @classmethod
    def save_rank(cls, nodes) -> int:
        """Lowest opens first when several sections can take a save."""
        return 99

    def stack(self):
        """The AssetStack of the asset-library models, or None for sections that do not use them."""
        return None

    def library_switched(self) -> None:
        """The models now hold another library: a grid they do not re-point is refreshed here."""

    exports_selection = False    # the View menu's Export Package is enabled on this grid's selection

    def export_selection(self, indexes) -> None:
        """Grid export: the user picks the destination, then `export_package_to` writes it."""
        path = self.pane.package_import.ask_destination()
        if path:
            self._export_and_report(lambda: self.export_package_to(list(indexes), path), path)

    def _export_and_report(self, export, path: str) -> None:
        """Run one export and show what it wrote, that it wrote nothing, or why it failed."""
        from amaze.core import packages
        warning = hou.severityType.Warning
        try:
            count = export()
        except (packages.PackageError, OSError) as exc:
            debug.exception("package export", exc, path=path)
            text, severity = messages.PACKAGE_NOT_SAVED % exc, warning
        else:
            name = os.path.basename(path)
            if not count:
                text, severity = messages.PACKAGE_EXPORT_EMPTY, warning
            elif count == 1:
                text, severity = messages.PACKAGE_EXPORTED_ONE % name, hou.severityType.Message
            else:
                text, severity = messages.PACKAGE_EXPORTED % (count, name), hou.severityType.Message
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(text, title=messages.TITLE_AMAZE, severity=severity)

    def filter_text(self, text: str) -> None:
        pass

    def filter_favorites(self, on: bool) -> None:
        pass

    def filter_entries(self) -> tuple:
        """FilterEntry rows, everything-entry first; value None removes the filter."""
        if not self.FILTER_CHOICES:
            return ()
        return (FilterEntry(self.ALL_ID, self.ALL_LABEL, None),) + tuple(self.FILTER_CHOICES)

    def apply_filter(self, value) -> None:
        """Narrow this section to one Filter-menu value; the section defines what an entry means."""
        pass

    def select_category(self, index) -> None:
        pass

    def shown_sidebar_key(self) -> str:
        """The sidebar key the GRID shows, "" for All; a right press moves only the sidebar."""
        return ""

    def reselect_sidebar_row(self) -> None:
        """Re-highlight the sidebar row the grid is filtered to; both go to All once it is gone."""
        model = self._shown_sidebar()
        if model is None:
            return
        key = self.shown_sidebar_key()
        target = self._row_keyed(model, key) if key else model.index(0, 0)
        if target is None:
            self.select_sidebar_key(key)
            return
        self.pane.sidebar.highlight(target)

    def _sidebar_rows_changed(self, *_args) -> None:
        """Sidebar rows reset, moved or removed, maybe by another pane: queue `reselect_sidebar_row`."""
        self._reselect_timer.start()

    def _reselect_sidebar_row_if_shown(self) -> None:
        """Run `reselect_sidebar_row` only while this section is shown."""
        if self.pane.active_section() is self:
            self.reselect_sidebar_row()

    def reselect_after_removal(self, removed) -> None:
        """Rows in `removed` left the sidebar: reselect the grid's row in both, or All if gone."""
        shown = self.shown_sidebar_key()
        self.select_sidebar_key("" if shown in removed else shown)

    def select_sidebar_key(self, key: str) -> None:
        """Select the row keyed `key` in sidebar and grid; All when no row has that key."""
        model = self._shown_sidebar()
        if model is None:
            return
        target = self._row_keyed(model, key) if key else None
        if target is None:
            target = model.index(0, 0)    # All is the first row of every sidebar
        self.pane.sidebar.highlight(target)
        self.select_category(target)

    def _shown_sidebar(self):
        """The sidebar's model while it shows this section's rows, else None."""
        model = self.pane.sidebar.model
        if model is None or model is not self._p(self.sidebar_attr) or not model.rowCount():
            return None
        return model

    @staticmethod
    def _row_keyed(model, key: str):
        """The sidebar row keyed `key`, or None: a category, a folder already read, an online category."""
        index = model.index_of(key)
        return index if index.isValid() else None

    def double_click(self, index) -> None:
        """Run `click_on_row` with the row's own DropRule; the online section overrides this."""
        self.pane.loading.click_on_row(self, index)

    def menu_import(self, indexes, current, payload=None) -> None:
        self.pane.loading.click_on_row(self, current)    # `click_on_row`, the same call as a double-click

    deletes_rows = False  # False for File: its rows are files it only browses

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        """The delete prompt for `count` rows in this section's terms; `name` is one row's display name."""
        return ""

    def delete_rows(self, indexes) -> None:
        """Remove these source rows, highest first; never wrap in layoutAboutToBeChanged/layoutChanged."""

    colour_title = "Category Color"  # the colour picker's title, defined only here

    def label_colours(self, indexes, current) -> tuple:
        """Label ▸: the four chips, then Custom (the picker) and Remove (no colour)."""
        chips = tuple((name, colour, colour, True)
                      for name, colour in amazetheme.LABEL_COLOURS)
        return chips + (None, ("Custom", True, "", True), ("Remove", "", "", True))

    def menu_label_colour(self, indexes, current, payload=None) -> None:
        if payload is True:    # Custom: the pane's `sidebar.set_colour` asks for a colour
            self.pane.sidebar.set_colour(True)
        else:
            self.pane.sidebar.set_colour(False, payload or "")

    takes_category_drops = False  # a tile dropped on a row RECATEGORISES it; AssetSection sets it
    takes_file_drops = False  # a tile dropped on a folder row MOVES its file there; FolderSection sets it

    def accepts_category_drop(self, index, name: str) -> bool:
        """Whether this category row accepts a drop; called after the shared checks."""
        return True

    def sidebar_key(self, index) -> str:
        """The key of this row, never its label: a category's id; "" on All."""
        return self.pane.sidebar.raw_category_name(index)

    def colour_key(self, index) -> str:
        """The key this row's Label colour is stored under; "" for a row that takes none."""
        return self.sidebar_key(index)

    def sidebar_colour(self, name: str) -> str:
        """This row's colour, "" for none, as the sidebar list keeps it; `name` is the row's key."""
        listed = self._p(self.sidebar_attr)
        return listed.color_of(name) if listed is not None else ""

    def set_sidebar_colour(self, name: str, colour: str) -> None:
        """Colour one sidebar row or clear it with ""; the list stores it, then the grid repaints."""
        listed = self._p(self.sidebar_attr)
        if listed is None:
            return
        listed.set_color(name, colour)
        self.repaint_grid_colours()

    def repaint_grid_colours(self) -> None:
        """A sidebar colour changed: repaint the tiles that show it. Default: nothing."""

    def toggle_favourite(self, indexes) -> None:
        """Toggle the favourite on each row in `indexes` (this section's proxy). Base: nothing."""

    offers_preview_update = False  # False where a preview is DERIVED, not rendered

    def update_preview(self, indexes) -> None:
        """Re-render the thumbnail for every row in `indexes`."""

    def menu_offers_preview(self, indexes, current) -> bool:
        """Whether the selection has anything to re-render, per `offers_preview_update`."""
        return bool(self.offers_preview_update)

    def menu_update_preview(self, indexes, current, payload=None) -> None:
        self.pane.assets.update_preview(indexes)

    def menu_customize(self, indexes, current, payload=None) -> None:
        model, proxy = self.tile_models()
        if model is None or proxy is None:
            return
        self.pane.assets.edit_tile_icon(model, proxy, indexes,
                                        categories=self.save_categories()[0])    # THIS section's list

    def menu_capture_enabled(self, indexes, current) -> bool:
        """One tile at a time: a capture is one image."""
        return len(indexes) == 1

    def menu_capture(self, indexes, current, payload=None) -> None:
        self.pane.tile_capture.onto_tile(self, current)

    def menu_favourite(self, indexes, current, payload=None) -> None:
        self.pane.assets.toggle_favourite(indexes)

    def menu_versions(self, indexes, current, payload=None) -> None:
        self.pane.assets.open_versions(current, self._p(self.proxy_attr),
                                       self._p(self.model_attr))

    def menu_comments(self, indexes, current, payload=None) -> None:
        self.pane.ui.show_comments()    # as the toolbar Comments button does, so the two never differ

    def menu_delete(self, indexes, current, payload=None) -> None:
        self.pane.assets.delete(indexes)

    def comment_subject(self, index):
        """A CommentSubject for `index` (this section's proxy), or None to clear the pane."""
        return None

    def info_subject(self, index):
        """A file_info.Subject for one row (`index` in this section's proxy), or None to clear the pane."""
        model, rows = self._model_and_rows([index]) if self.takes_info else (None, [])
        key = model.tile_key(rows[0]) if rows else ""
        if not key:
            return None
        name, kind = model.info_header(rows[0])
        before, after, request = model.info_rows(rows[0])
        return file_info.Subject(key="%s:%s" % (self.key, key), name=name, type=kind,
                                 before=before, after=after, request=request)

    def info_subject_for(self, indexes):
        """A file_info.Subject for several rows: their count, and the read that adds up their sizes."""
        model, rows = self._model_and_rows(indexes) if self.takes_info else (None, [])
        if not rows:
            return None
        keys = "\n".join(sorted(model.tile_key(row) for row in rows))
        paths = dict.fromkeys(path for row in rows for path in model.info_paths(row))    # a shared texture once
        return file_info.Subject(
            key="%s:%d:%s" % (self.key, len(rows), hashlib.sha1(keys.encode("utf-8")).hexdigest()),
            name="%d items selected" % len(rows), type="", before=(("Items", str(len(rows))),),
            request=file_info.request_for_sizes(paths))

    def _p(self, attr):
        return getattr(self.pane, attr, None) if attr else None


class AssetSection(Section):
    """Material, Node and Code: an AssetLibrary model and a Categories sidebar behind the proxy."""


    model_attr = ""
    proxy_attr = ""
    selection_attr = ""
    category_attr = ""
    sidebar_attr = ""   # the categories PROXY, not `category_attr` under it
    delegate_attr = ""
    search_hint = ""    # ":tag" is the only way to reach tags from this box

    def library_switched(self) -> None:
        self.restore_sidebar_selection()

    def restore_sidebar_selection(self) -> None:
        """Select the sidebar's first row and filter the grid to it; a select from code fires no click."""
        selected_name = self.pane.sidebar.select_default_row(self._p(self.sidebar_attr))
        model = self._p(self.model_attr)
        proxy = self._p(self.proxy_attr)
        if model is not None and proxy is not None:
            proxy.setFilter(
                model.CategoryRole,
                "" if selected_name is None or category_list.is_all(selected_name)
                else selected_name,
            )

    takes_category_drops = True

    SIDEBAR_MENU = (  # shared by Material, Node and Code; Rename acts on one category, the rest on the selection
        MenuEntry("Add", handler="menu_add_category", needs="always", opens="ask_name"),
        MenuEntry("Rename", handler="menu_rename_category", needs="one", opens="ask_name"),
        MenuEntry("Delete", handler="menu_remove_category"),
        SEPARATOR,
        MenuEntry("Sort by name", handler="menu_sort_categories",
                  needs="always"),
        SEPARATOR,
        MenuEntry("Label", handler="menu_label_colour", children="label_colours"),
    )

    def menu_add_category(self, indexes, current, payload=None) -> None:
        st = self.stack()

        def add(name):
            if st is None or not name:
                return
            st.categories.check_add_category(name)    # no relayout wrapper: begin/endInsertRows notify the view

        self.pane.ui.ask_name("Add Category", "", add)

    def menu_rename_category(self, indexes, current, payload=None) -> None:
        keys = [self.sidebar_key(index) for index in indexes]    # read now: rows move before an OK
        st = self.stack()
        old = st.categories.name_of(keys[0]) if st is not None and keys else ""
        self.pane.ui.ask_name(
            "Rename Category", category_list.display_name(old),    # the field starts with the name
            lambda new_name: self._rename_categories(keys, new_name))

    def _rename_categories(self, keys, new_name) -> None:
        """Name the categories keyed `keys` `new_name`, joined to one already of that name."""
        st = self.stack()
        if st is None or not new_name:
            return
        shown = self.shown_sidebar_key()    # the grid's row: a right press moved only the sidebar
        kept = category.rename(st.model, st.categories, keys, new_name)
        if not kept:
            return
        self.select_sidebar_key(kept if shown in keys else shown)    # a joined row: the one kept
        self.pane.sidebar.refresh()    # updates counts and empty-category hiding after the rename

    exports_selection = True

    def export_package_to(self, indexes, path: str) -> int:
        """Write the selected rows into one `.amazepkg`; returns the entry count."""
        from amaze.core import packages
        model, rows = self._model_and_rows(indexes)
        return packages.write_package(
            path, [packages.collect_asset(model, model.assets[row].mat_id) for row in rows])

    def export_category_to(self, category, path: str) -> int:
        """Sidebar export: write the assets in `category` (None: all) into one package."""
        st = self.stack()
        from amaze.core import packages
        if st is None:
            return 0
        return packages.write_package(path, [
            packages.collect_asset(st.model, asset.mat_id) for asset in st.model.assets
            if category is None or category in asset.categories])

    exports_categories = True

    def selected_category(self):
        """The one category selected in the sidebar, or None for All, no row, or several."""
        rows = self.sidebar_selection()
        name = self.sidebar_key(rows[0]) if len(rows) == 1 else None
        return None if not name or category_list.is_all(name) else name

    def export_category(self, name) -> None:
        """Export `name`'s category (None: the whole section) to a path the user picks."""
        path = self.pane.package_import.ask_destination()
        if path:
            self._export_and_report(lambda: self.export_category_to(name, path), path)

    def menu_remove_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        if st is None:
            return
        names = [name for name in map(self.sidebar_key, indexes) if not category_list.is_all(name)]
        if not any(names):
            return
        if st.selection is not None:
            st.selection.clearSelection()
        if category.remove(st.model, st.categories, names):
            self.reselect_after_removal(names)

    def menu_sort_categories(self, indexes, current, payload=None) -> None:
        """The one-off Sort by name: sorts every row below All, whichever row was clicked."""
        st = self.stack()
        if st is None:
            return
        shown = self.shown_sidebar_key()    # the grid's row: a right press moved only the sidebar
        st.categories.sort_categories()    # a model reset, which clears the sidebar's selection
        self.select_sidebar_key(shown)

    def tile_models(self):
        st = self.stack()
        return ((st.model, st.proxy) if st is not None
                else (None, None))

    def save_categories(self) -> tuple:
        """(this section's (key, name) choices, the sidebar's row while it shows this section)."""
        st = self.stack()
        if st is None:
            return [], ""
        pane = self.pane
        current = pane.sidebar.selected_category_name() if pane.active_section() is self else ""
        return st.categories.choices(), current

    def stack(self):
        model = self._p(self.model_attr)
        category = self._p(self.category_attr)
        if not model or not category:
            return None
        return AssetStack(
            model=model,
            proxy=self._p(self.proxy_attr),
            selection=self._p(self.selection_attr),
            categories=category,
        )

    def toggle_favourite(self, indexes) -> None:
        model, rows = self._model_and_rows(indexes)
        if model is not None:
            model.toggle_favs(rows)

    deletes_rows = True

    def delete_rows(self, indexes) -> None:
        st = self.stack()
        if st is None:
            return
        st.model.remove_rows([index.row() for index in indexes])    # ONE save for the selection
        self.pane.sidebar.refresh()

    def repaint_grid_colours(self) -> None:
        model = self._p(self.model_attr)
        if model is not None:
            model.repaint_category_colours()    # the grid reads the colour from the same document

    offers_preview_update = True

    def comment_subject(self, index):
        st = self.stack()
        if st is None:
            return None
        source = st.proxy.mapToSource(index)
        if not source.isValid():
            return None
        asset_id = source.data(st.model.IdRole)
        if not asset_id:
            return None
        return CommentSubject(
            key=notes.note_key(st.model.NOTES_SECTION, asset_id),    # the MODEL's notes section: shared by three sections
            name=source.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
            type=source.data(st.model.RendererLabelRole) or "",
        )

    def filter_text(self, text: str) -> None:
        st = self.stack()
        if st is None:
            return
        needle, tags_only = multifilterproxy_model.split_search(text)    # no invalidate() or sort() around these; `one_pass` limits them to one pass ▸p/filter-pass-cost
        with st.proxy.one_pass():
            if tags_only:
                st.proxy.removeFilter(QtCore.Qt.ItemDataRole.DisplayRole)
                if needle:
                    st.proxy.setFilter(st.model.TagRole, needle)
                else:
                    st.proxy.removeFilter(st.model.TagRole)    # a BARE COLON is a tag search with no tag yet, so it must filter nothing
            else:
                st.proxy.removeFilter(st.model.TagRole)
                st.proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, needle)

    def filter_favorites(self, on: bool) -> None:
        st = self.stack()
        if st is None:
            return
        st.proxy.setFilter(st.model.FavoriteRole, True if on else "")

    def apply_filter(self, value) -> None:
        st = self.stack()
        if st is None:
            return
        if value is None:
            st.proxy.removeFilter(st.model.RendererRole)    # remove, never an accept-all value, which costs a data() call per row
        else:
            st.proxy.setFilter(st.model.RendererRole, value)    # every asset section keeps its kind in this role; a filter on any other role is ignored
        st.categories.set_renderer_filter(value)    # the sidebar too, with the proxy's value, never the menu's label
        self.pane.sidebar.refresh()

    def select_category(self, index) -> None:
        """Filter the grid to the clicked row's category, always by its key."""
        st = self.stack()
        if st is None:
            return
        stored = self.sidebar_key(index)    # never index.data(), its name
        st.proxy.setFilter(st.model.CategoryRole,
                        "" if category_list.is_all(stored) else stored)    # `""` makes All match everything, not a literal category no asset has

    def shown_sidebar_key(self) -> str:
        st = self.stack()
        return (st.proxy.filter_value(st.model.CategoryRole) or "") if st is not None else ""


def drop_rule(section, pane, index):
    """The rule this row declares, or None: DROP, or DROP_BY_KIND picked by the row's KindRole."""
    if section is None:
        return None
    by_kind = getattr(section, "DROP_BY_KIND", None)
    if by_kind:
        kind = index.data(pane.file_files_model.KindRole) or ""
        return by_kind.get(kind)
    return getattr(section, "DROP", None)


def drop_handler(section, name):
    """The bound method a DropRule names, always the section's own; an unknown name raises."""
    return getattr(section, name)
