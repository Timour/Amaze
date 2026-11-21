"""One Section per library tab: how it drives the panel's shared widgets. ▸o/section-api"""

from __future__ import annotations

import collections
import hashlib
import os

import hou
from PySide6 import QtCore, QtWidgets

from amaze import amazetheme
from amaze.actions import code as code_actions
from amaze.actions import materials as material_actions
from amaze.actions import nodes as node_actions
from amaze.core import (category, debug, file_info, file_library, file_moves,
                        grid_columns, library, library_settings, locations, multifilterproxy_model,
                        renderers, scene_captures, notes, section_list)
from amaze.helpers import hostos, ui_helpers, wording
from amaze import messages
from amaze.panel import grid, sidebar
from amaze.render import cop_nodes
from amaze.render import nodes as nodes_mod


AssetStack = collections.namedtuple(
    "AssetStack", "model proxy selection categories")

CommentSubject = collections.namedtuple("CommentSubject", "key name type")

FilterEntry = collections.namedtuple(    # `id` is what the remembered choice saves, so a label can change
    "FilterEntry", "id label value icon", defaults=(None,))

DropRule = collections.namedtuple(
    "DropRule",
    "on_node on_space resolve click_on_node click_resolve "
    "holder_node_type context",
    defaults=(None, None, None, None, None, "", ""),
)    # context: the childTypeCategory a network must have to accept this drop ("" = any network)


MenuEntry = collections.namedtuple(
    "MenuEntry",
    "label handler needs shown children count_suffix checkable",
    defaults=("", "any", "", "", False, ""),
)

SEPARATOR = MenuEntry("")  # the empty label is what makes it a divider

GRID_MENU_TAIL = (
    MenuEntry("Thumbnail", handler="menu_thumbnail", children="thumbnail_actions"),    # the tile's thumbnail: render, capture, customize
    MenuEntry("Favorite", handler="menu_favourite"),
    MenuEntry("Delete", handler="menu_delete", shown="deletes_rows"),
)

UNDO_MOVE = (    # first in both File menus while the last move can be undone
    MenuEntry("Undo Move", handler="menu_undo_move", needs="always", shown="can_undo_move"),
    SEPARATOR,
)


def _file_count(count: int) -> str:
    """`1 file` or `3 files`, for the move messages."""
    return messages.MOVE_ONE_FILE if count == 1 else messages.MOVE_FILES % count


class Section:
    """Base protocol: built with the panel, reads its models by attribute name. ▸o/section-api"""

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
    EMPTY: dict = {}      # `nothing-yet`: (headline, sentence, button, handler)

    sidebar_attr = ""     # the list the sidebar shows
    proxy_attr = ""       # the grid's proxy, which `activate` binds to the grid views
    delegate_attr = ""
    tile_badges: tuple = ()    # the badge IDs this section's tile shows ▸r/tile-from-frame
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

    def __init__(self, panel) -> None:
        self.panel = panel
        sidebar = self._p(self.sidebar_attr)
        if sidebar is None:
            return
        self._reselect_timer = QtCore.QTimer(panel)    # restarted by every signal, so it fires once per event loop pass
        self._reselect_timer.setSingleShot(True)
        self._reselect_timer.setInterval(0)
        self._reselect_timer.timeout.connect(self._reselect_sidebar_row_if_shown)
        for moved in (sidebar.modelReset, sidebar.layoutChanged, sidebar.rowsRemoved):
            moved.connect(self._sidebar_rows_changed)

    def reject_drop(self) -> bool:
        """A drop no target accepts: the red cross and a status line that it was canceled; False."""
        debug.refuse(messages.DROP_CANCELED)
        return False

    def activate(self) -> None:
        """Point the shared widgets at this section's models, then select its sidebar row. ▸o/section-api"""
        panel = self.panel
        self.before_sidebar_shown()
        listed = self._p(self.sidebar_attr)
        if panel.cat_list and listed is not None:
            panel.cat_list.setModel(listed)
        panel.bind_grid_views(self._p(self.proxy_attr),
                              self._p(self.selection_attr),
                              self._p(self.delegate_attr))
        panel.set_conversion_bar_visible(False)  # may be another section's
        self.before_columns_synced()
        panel.sync_list_columns()  # different section = different names
        self.restore_sidebar_selection()

    def before_sidebar_shown(self) -> None:
        """Runs first on entering, before the list is set on the sidebar. Default: nothing."""

    def before_columns_synced(self) -> None:
        """Runs on entering, before the list columns are synced. Default: nothing."""

    def restore_sidebar_selection(self) -> None:
        """Select this section's sidebar row on entering; a `setModel` leaves none. Default: nothing."""

    def rc_menu(self) -> None:
        """Build and exec this section's grid right-click menu: ONE builder over GRID_MENU."""
        grid.open_grid_menu(self.panel, self)

    def grid_selection(self) -> list:
        """This section's grid selection as its own proxy's indexes, one per row."""
        return grid_columns.selected_rows(self.grid_selection_model())

    def grid_selection_model(self):
        """This section's grid selection MODEL, for a query about one row."""
        return self._p(self.selection_attr)

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

    def catlist_menu(self) -> None:
        """Build and exec this section's sidebar right-click menu, over SIDEBAR_MENU."""
        grid.open_catlist_menu(self.panel, self)

    def sidebar_selection(self) -> list:
        """The Sidebar's selected rows, read from the shared `cat_list`."""
        cat_list = getattr(self.panel, "cat_list", None)
        if cat_list is None:
            return []
        return list(cat_list.selected_rows())

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
        path = self.panel.package_import.ask_destination()
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

    def shows_empty_state(self, source) -> bool:
        """Whether to show the first-run empty state: `source`, the grid's model, is empty."""
        return not (source.rowCount() if source is not None else 0)

    def select_category(self, index) -> None:
        pass

    def shown_sidebar_key(self) -> str:
        """The sidebar key the GRID shows, "" for All; a right press moves only the sidebar."""
        return ""

    def reselect_sidebar_row(self) -> None:
        """Re-highlight the sidebar row the grid is filtered to; both go to All once it is gone."""
        view, model = self._sidebar_view()
        if model is None:
            return
        key = self.shown_sidebar_key()
        target = self._row_keyed(model, key) if key else model.index(0, 0)
        if target is None:
            self.select_sidebar_key(key)
            return
        self._highlight(view, target)

    def _sidebar_rows_changed(self, *_args) -> None:
        """Sidebar rows reset, moved or removed, maybe by another panel: queue `reselect_sidebar_row`."""
        try:
            self._reselect_timer.start()
        except RuntimeError:    # the panel was deleted, and File's shared model outlives it
            pass

    def _reselect_sidebar_row_if_shown(self) -> None:
        """Run `reselect_sidebar_row` only while this section is shown."""
        if self.panel.active_section() is self:
            self.reselect_sidebar_row()

    def reselect_after_removal(self, removed) -> None:
        """Rows in `removed` left the sidebar: reselect the grid's row in both, or All if gone."""
        shown = self.shown_sidebar_key()
        self.select_sidebar_key("" if shown in removed else shown)

    def select_sidebar_key(self, key: str) -> None:
        """Select the row keyed `key` in sidebar and grid; All when no row has that key."""
        view, model = self._sidebar_view()
        if model is None:
            return
        target = self._row_keyed(model, key) if key else None
        if target is None:
            target = model.index(0, 0)    # All is the first row of every sidebar
        self._highlight(view, target)
        self.select_category(target)

    def _sidebar_view(self):
        """(the sidebar, its model) while it shows this section's rows, else (None, None)."""
        view = getattr(self.panel, "cat_list", None)
        model = view.model() if view is not None else None
        if model is None or model is not self._p(self.sidebar_attr) or not model.rowCount():
            return None, None
        return view, model

    @staticmethod
    def _highlight(view, index) -> None:
        view.highlight(index)

    @staticmethod
    def _row_keyed(model, key: str):
        """The sidebar row keyed `key`, or None: a category, a folder already read, an online category."""
        index = model.index_of(key)
        return index if index.isValid() else None

    def double_click(self, index) -> None:
        """Run `click_on_row` with the row's own DropRule; the online section overrides this."""
        self.panel.click_on_row(self, index)

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
        if payload is True:    # Custom: the panel's `sidebar_set_colour` opens the colour picker
            self.panel.sidebar_set_colour(True)
        else:
            self.panel.sidebar_set_colour(False, payload or "")

    takes_category_drops = False  # a tile dropped on a row RECATEGORISES it; AssetSection sets it
    takes_file_drops = False  # a tile dropped on a folder row MOVES its file there; FolderSection sets it

    def accepts_category_drop(self, index, name: str) -> bool:
        """Whether this category row accepts a drop; called after the shared checks."""
        return True

    def sidebar_key(self, index) -> str:
        """The key of this row, never its label: a category shown "WIP" is stored "_WIP"; "" on All."""
        return self.panel.raw_category_name(index)

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
        self.panel.grid_update_preview(indexes)

    def menu_customize(self, indexes, current, payload=None) -> None:
        model, proxy = self.tile_models()
        if model is None or proxy is None:
            return
        self.panel.edit_tile_icon(model, proxy, indexes,
                                  categories=self.save_categories()[0])    # THIS section's list

    def menu_capture_enabled(self, indexes, current) -> bool:
        """One tile at a time: a capture is one image."""
        return len(indexes) == 1

    def menu_capture(self, indexes, current, payload=None) -> None:
        self.panel.tile_capture.onto_tile(self, current)

    def thumbnail_actions(self, indexes, current) -> tuple:
        """The Thumbnail submenu's rows, each naming its method; Render Image only where one renders."""
        rows = []
        if self.menu_offers_preview(indexes, current):
            rows.append(("Render Image", "menu_update_preview", "", bool(indexes)))
        rows.append(("Capture Scene", "menu_capture", "",
                     self.menu_capture_enabled(indexes, current)))
        rows.append(("Customize", "menu_customize", "", bool(indexes)))
        return tuple(rows)

    def menu_thumbnail(self, indexes, current, payload=None) -> None:
        if payload:
            getattr(self, payload)(indexes, current)

    def menu_favourite(self, indexes, current, payload=None) -> None:
        self.panel.grid_toggle_favourite(indexes)

    def menu_versions(self, indexes, current, payload=None) -> None:
        self.panel.open_versions_dialog(current, self._p(self.proxy_attr),
                                        self._p(self.model_attr))

    def menu_comments(self, indexes, current, payload=None) -> None:
        self.panel.btn_notes.click()    # the toolbar Comments button's own click, so the two never differ

    def menu_delete(self, indexes, current, payload=None) -> None:
        self.panel.grid_delete(indexes)

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
        return getattr(self.panel, attr, None)


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
        selected_name = self.panel.select_default_sidebar_row(self._p(self.sidebar_attr))
        model = self._p(self.model_attr)
        proxy = self._p(self.proxy_attr)
        if model is not None and proxy is not None:
            proxy.setFilter(
                model.CategoryRole,
                "" if selected_name is None or category.is_all(selected_name)
                else selected_name,
            )

    takes_category_drops = True

    SIDEBAR_MENU = (  # shared by Material, Node and Code; Rename acts on one category, the rest on the selection
        MenuEntry("Add", handler="menu_add_category", needs="always"),
        MenuEntry("Rename", handler="menu_rename_category", needs="one"),
        MenuEntry("Delete", handler="menu_remove_category"),
        SEPARATOR,
        MenuEntry("Sort by name", handler="menu_sort_categories",
                  needs="always"),
        SEPARATOR,
        MenuEntry("Label", handler="menu_label_colour", children="label_colours"),
    )

    def menu_add_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        name = self.panel.ask_category_name("Add Category")
        if st is None or not name:
            return
        name = ",".join(st.categories.stored_name(part) for part in name.split(","))    # WIP is `_WIP`
        st.categories.check_add_category(name)    # no relayout wrapper: begin/endInsertRows notify the view, and pairing the two segfaults

    def menu_rename_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        old = self.sidebar_key(indexes[0]) if indexes else ""    # the field starts with the current name
        new_name = self.panel.ask_category_name(
            "Rename Category", "" if category.is_all(old) else category.display_name(old))
        if st is None or not new_name:
            return
        new_name = st.categories.stored_name(new_name)    # a typed WIP maps to the existing `_WIP`
        if category.is_all(new_name):
            return    # the All row is a view of everything, never a category to rename onto
        names = []    # STORED names: `_WIP` displays as WIP, and that label matches no asset
        for index in indexes:
            name = self.sidebar_key(index)
            if name and not category.is_all(name):
                names.append(name)
        shown = self.shown_sidebar_key()    # the grid's row: a right press moved only the sidebar
        with ui_helpers.relayout(st.model):    # the asset rows change IN PLACE, the only case for this pair
            for name in names:
                st.model.rename_category(name, new_name)
        st.model.save()    # AFTER the pair: a save merges rows another Houdini wrote, and an insert inside segfaults H21
        for name in names:
            st.categories.rename_category(name, new_name)    # after the rows: its save must not undo them
        self.select_sidebar_key(new_name if shown in names else shown)    # a renamed row is found by its new name
        self.panel.refresh_sidebar_categories()    # updates counts and empty-category hiding after the rename

    exports_selection = True

    def export_package_to(self, indexes, path: str) -> int:
        """Write the selected rows into one `.amazepkg`; returns the entry count."""
        from amaze.core import packages
        model, rows = self._model_and_rows(indexes)
        items = [packages.collect_asset(model, model.assets[row].mat_id) for row in rows]
        if not items:
            return 0
        return packages.write_package(path, items)

    def export_category_to(self, category, path: str) -> int:
        """Sidebar export: write the assets in `category` (None: all) into one package."""
        st = self.stack()
        from amaze.core import packages
        if st is None:
            return 0
        items = []
        for asset in st.model.assets:
            cats = asset.categories
            if isinstance(cats, str):    # the record field is "" for none and may be a single name - `in` on a string would substring-match
                cats = [cats] if cats else []
            if category is None or category in cats:
                items.append(packages.collect_asset(st.model,
                                                    asset.mat_id))
        if not items:
            return 0
        return packages.write_package(path, items)

    exports_categories = True

    def selected_category(self):
        """The one category selected in the sidebar, or None for All, no row, or several."""
        rows = self.sidebar_selection()
        name = self.sidebar_key(rows[0]) if len(rows) == 1 else None
        return None if not name or category.is_all(name) else name

    def export_category(self, name) -> None:
        """Export `name`'s category (None: the whole section) to a path the user picks."""
        path = self.panel.package_import.ask_destination()
        if path:
            self._export_and_report(lambda: self.export_category_to(name, path), path)

    def menu_remove_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        if st is None:
            return
        names = []    # stored names: removing by the label would leave the row in place
        for index in indexes:
            name = self.sidebar_key(index)
            if name and not category.is_all(name):
                names.append(name)
        if not names:
            return
        if st.selection is not None:
            st.selection.clearSelection()
        with ui_helpers.relayout(st.model):    # the asset rows change IN PLACE, the only case for this pair
            for name in names:
                st.model.remove_category(name)
        st.model.save()    # AFTER the pair: a save merges rows another Houdini wrote, and an insert inside segfaults H21
        for name in names:
            st.categories.remove_category(name)    # outside the relayout wrapper: begin/endRemoveRows notify the view; pairing them segfaults
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
        """(this section's STORED categories, the sidebar's row - only while it shows this section)."""
        st = self.stack()
        if st is None:
            return [], ""
        panel = self.panel
        current = panel.selected_category_name() if panel.active_section() is self else ""
        return panel.category_names_from(st.categories), current

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
        self.panel.refresh_sidebar_categories()

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
        st.categories.set_renderer_filter(value or "")    # the sidebar too, with the proxy's value, never the menu's label
        self.panel.refresh_sidebar_categories()

    def select_category(self, index) -> None:
        """Filter the grid to the clicked row's category, always by the STORED name."""
        st = self.stack()
        if st is None:
            return
        stored = self.sidebar_key(index)    # never index.data(): a category stored `_WIP` displays `WIP`
        st.proxy.setFilter(st.model.CategoryRole,
                        "" if category.is_all(stored) else stored)    # `""` makes All match everything, not a literal category no asset has

    def shown_sidebar_key(self) -> str:
        st = self.stack()
        return (st.proxy.filter_value(st.model.CategoryRole) or "") if st is not None else ""


class MaterialSection(AssetSection):
    key = "material"
    label = section_list.label(key)
    empty_noun = "material"
    EMPTY = amazetheme.EMPTY_MATERIAL    # no button: save_asset needs a selected node and shows a message without one ▸p/one-design-document
    QUOTE = amazetheme.QUOTE_MATERIAL

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this material? Its saved files and "
                    "thumbnails are deleted permanently. Materials already used in "
                    "a scene are not affected.")
        return ("Delete %d materials? Their saved files and thumbnails "
                "are deleted permanently. Materials already used in a scene are "
                "not affected." % count)

    GRID_MENU = (    # the section's entries, a divider, then GRID_MENU_TAIL, as in the C01/C01b frames
        MenuEntry("Load Asset to", handler="menu_copy_to", children="copy_to_targets"),
        MenuEntry("Convert", handler="menu_convert_to",
                  children="convert_targets",
                  needs="selection_is_convertible"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    DROP = DropRule(resolve="drop_material_at_release",    # a material import finds its own destination at the release
                    click_resolve="click_import_material",
                    context="Vop")    # only a network that holds Vop nodes accepts the drop

    def click_import_material(self, _index) -> bool:
        """The material import reads the selection and the network under the cursor itself."""
        self.panel.import_asset("auto")
        return True

    def drop_material_at_release(self, index) -> bool:
        """Import a dropped material; True on a target, False on none, `menu` if a menu showed."""
        from amaze.core import dragengine
        panel = self.panel
        if not panel.material_model or index is None or not index.isValid():
            return False
        ids = panel.selected_material_ids(index)
        target = dragengine.viewport_release_target(panel)
        if target is not None:
            kind, viewer, data = target
            debug.event("drag", "material release", target=kind,
                        data=str(data), count=len(ids))
            if kind == "lop":
                if not data:
                    return self.reject_drop()    # empty viewport space is a MISS, not an import offer
                shown = panel.drop_placement.material_lop_viewport_drop(ids, viewer, data)
                return "menu" if shown is not False else False    # "menu" only when a menu was shown: it suppresses the miss icon
            if kind == "obj" and data is not None:
                with dragengine.drop_group("Amaze Assign Material"):
                    return bool(panel.assign_material_to_obj(ids, data))    # False when the picked object has no shop_materialpath
            return self.reject_drop()
        context = panel.drop_placement.context_under_cursor("materiallibrary")
        if context is None or not cop_nodes.accepts_context(
                context, self.DROP.context):    # the wrong network is a miss and creates nothing; DROP.context decides
            debug.event("drag", "material release", target="miss",
                        context=context.path() if context else "")
            return self.reject_drop()
        debug.event("drag", "material release", target="network",
                    context=context.path(), count=len(ids))
        position = panel.drop_placement.release_position_in(context)
        panel.drop_placement.import_materials_into_context(context, ids, position)
        return True

    def copy_to_targets(self, indexes, current) -> tuple:
        """Where the saved material is loaded, named the way Houdini writes the path: /stage."""
        return (("/mat", "mat", "", True),
                ("/stage/materiallibrary", "lop", "", True))    # names the DESTINATION: the copy goes INSIDE a material library under /stage, never stage root

    def menu_copy_to(self, indexes, current, payload=None) -> None:
        if payload == "lop":
            self.panel.import_asset_to_lop()
        else:
            self.panel.import_asset_to_mat()

    def _convertible_renderers(self, indexes) -> frozenset:
        """The renderers among these rows that convert: one loop over the rows per menu."""
        from amaze.render.material_conversion import engine as conversion_engine
        cached = getattr(self, "_convertible_cache", None)
        if cached is not None and cached[0] is indexes:
            return cached[1]
        wanted = set(conversion_engine.targets())
        found = set()
        st = self.stack()
        for index in (indexes if st is not None else ()):
            renderer = st.model.assets[st.proxy.mapToSource(index).row()].renderer
            if renderers.normalized(renderer) in wanted:
                found.add(renderers.normalized(renderer))
            if found == wanted:
                break
        self._convertible_cache = (indexes, frozenset(found))
        return self._convertible_cache[1]

    def selection_is_convertible(self, indexes, current) -> bool:
        """The parent is disabled when no child is enabled: an empty submenu looks broken."""
        return any(live for *_child, live in self.convert_targets(indexes, current))

    def convert_targets(self, indexes, current) -> tuple:
        """Renderers to convert TO: a child is enabled when a selected material converts to it."""
        from amaze.render.material_conversion import engine as conversion_engine
        convertible = self._convertible_renderers(indexes)
        return tuple(
            (renderer.label, renderer.key, renderer.icon,
             any(conversion_engine.can_convert(source, renderer.key) for source in convertible))
            for renderer in renderers.offered(self.panel.prefs)
            if renderer.key in conversion_engine.targets())

    def menu_convert_to(self, indexes, current, payload=None) -> None:
        self.panel.convert_selected(payload or renderers.INTERMEDIATE.key)

    library_model_attrs = ("material_model", "category_model")
    model_attr = "material_model"
    proxy_attr = "material_sorted_model"
    selection_attr = "material_selection_model"
    category_attr = "category_model"
    sidebar_attr = "category_sorted_model"
    delegate_attr = "thumb_delegate"
    tile_badges = ("favourite", "versions", "comment")
    filter_tooltip = "Show materials for one renderer."

    FILTER_ALL_ICON = "filter_all"

    def filter_entries(self) -> tuple:
        """Rebuilt, never hidden: the panel uses All for a saved choice no longer offered."""
        return (FilterEntry(self.ALL_ID, self.ALL_LABEL, None, self.FILTER_ALL_ICON),) + tuple(
            FilterEntry(renderer.key, renderer.label, renderer.key, renderer.icon)
            for renderer in renderers.offered(self.panel.prefs))

    def can_save(self, nodes) -> bool:
        return bool(nodes) and all(    # a fresh handler per node: it remembers the last renderer
            nodes_mod.NodeHandler(self.panel.prefs).get_renderer_from_node(n)
            for n in nodes)

    def commit_save(self, nodes, node, dialog) -> None:
        if dialog.categories:
            self.panel.category_model.check_add_category(dialog.categories)

        renderers = []
        failures = []
        unlisted = []
        total, done = len(nodes), 0
        try:
            with hou.InterruptableOperation(    # type: ignore
                messages.SAVING_MATERIALS, open_interrupt_dialog=True
            ) as op:
                for asset in nodes:
                    op.updateLongProgress(done / total,
                                          "%d/%d  %s" % (done + 1, total, asset.name()))
                    try:    # an exception from the save is added to the per-material report
                        renderer = material_actions.add_asset(
                            self.panel.material_model, asset, dialog.categories, dialog.tags,
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
                    if not renderer:    # `""` is a failed save that already showed its message; list its name
                        failures.append(messages.SAVE_DID_NOT_COMPLETE_LINE % asset.name())
                        continue
                    renderers.append(renderer)
                    if isinstance(renderer, library.ListNotSaved):
                        unlisted.append(dialog.name or asset.name())    # the name the add gave it
        except hou.OperationInterrupted:
            debug.status(messages.SAVE_STOPPED % (done, total))

        ui = getattr(hou, "ui", None)
        if failures and ui is not None:
            ui.displayMessage(
                messages.MATERIALS_SAVE_FAILURES, details="\n".join(failures),
                title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
        for renderer in renderers:
            self.panel.enable_renderer_on_add(renderer)
        self.panel.prefs.save()
        self.panel.update_renderer_toggles()
        self.panel.refresh_sidebar_categories()
        library.report_unlisted(unlisted)    # the status line, last, so nothing after it overwrites the line

    def update_preview(self, indexes) -> None:
        """Update Render on Material tiles: the whole selection in one render batch."""
        model, rows = self._model_and_rows(indexes)
        if rows:
            material_actions.render_thumbnails(model, rows)

    @classmethod
    def save_rank(cls, nodes) -> int:
        try:
            inside = nodes[0].parent().childTypeCategory().name() == "Vop"
        except (AttributeError, IndexError, hou.OperationFailed):
            inside = False
        return 0 if inside else 4


class CopSection(AssetSection):
    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this node asset? Its saved files and "
                    "thumbnail are deleted permanently. Networks already built in "
                    "a scene are not affected.")
        return ("Delete %d node assets? Their saved files and "
                "thumbnails are deleted permanently. Networks already built in a "
                "scene are not affected." % count)

    key = "cop"
    label = section_list.label(key)
    empty_noun = "node asset"
    EMPTY = amazetheme.EMPTY_NODE    # no button, for the same reason as Material
    QUOTE = amazetheme.QUOTE_NODE
    GRID_MENU = (    # the material menu without renderer-specific entries; Load Asset is enabled on a multi-selection
        MenuEntry("Load Asset", handler="menu_load"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    DROP = DropRule(resolve="drop_cop_at_release",    # a saved network is built where its context allows, so the method finds the destination
                    click_resolve="click_import_cop")

    def click_import_cop(self, _index) -> bool:
        self.panel.import_cop_assets()
        return True

    def drop_cop_at_release(self, index) -> bool:
        """Load a dropped Nodes asset into the network under the cursor, if its context matches."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        panel = self.panel
        if not panel.cop_model:
            return False
        if index is None or not index.isValid():
            return False    # a drag started on empty grid space has an invalid index
        context = panel.drop_placement.context_under_cursor(
            cop_nodes.is_container)
        if context is None:
            return self.reject_drop()
        try:
            source_index = panel.cop_sorted_model.mapToSource(index)
        except Exception:
            return False
        with dragengine.drop_group("Amaze Import COP Network"):
            ok, reason, created = node_actions.import_asset_to_scene(
                panel.cop_model, source_index, context_node=context
            )
        if not ok and reason:
            debug.refuse(reason, net=context.path())    # the import marks library damage, so a dialog shows, not the status line ▸p/refuse-vs-alert
        if ok:
            helpers.place_nodes(created,
                                panel.drop_placement.release_position_in(context))
        return True

    def menu_load(self, indexes, current, payload=None) -> None:
        self.panel.import_cop_assets()
    library_model_attrs = ("cop_model", "cop_category_model")
    model_attr = "cop_model"
    proxy_attr = "cop_sorted_model"
    selection_attr = "cop_selection_model"
    category_attr = "cop_category_model"
    sidebar_attr = "cop_category_sorted_model"
    delegate_attr = "asset_delegate"    # not thumb_delegate, which paints a Version column
    tile_badges = ("favourite", "comment")
    filter_tooltip = "Show setups saved from one context."

    FILTER_CHOICES = (    # the contexts cop_nodes.SAVE_CONTEXTS saves, spelled as Houdini's network tabs show them
        FilterEntry("SOP", "SOP", "Sop"),
        FilterEntry("COP", "COP", "Cop"),
        FilterEntry("LOP", "LOP", "Lop"),
        FilterEntry("DOP", "DOP", "Dop"),
        FilterEntry("TOP", "TOP", "Top"),
        FilterEntry("CHOP", "CHOP", "Chop"),
        FilterEntry("Object", "Object", "Object"),
    )

    def can_save(self, nodes) -> bool:
        return (bool(nodes) and len({n.parent() for n in nodes}) == 1
                and cop_nodes.can_save(nodes[0]))

    def commit_save(self, nodes, node, dialog) -> None:
        """Works in any context the Nodes section supports; the asset records which one."""
        ui = getattr(hou, "ui", None)
        net = node.parent()
        items = [i for i in hou.selectedItems() if i.parent() == net]
        if not any(i == node for i in items):
            items.append(node)
        if len(items) == 1 and cop_nodes.saves_whole_network(node):    # a container alone saves its network
            items = None

        if dialog.categories:
            self.panel.cop_category_model.check_add_category(dialog.categories)

        result = None
        save_error = None    # no layout wrapper: add_asset emits its own row-insert signals
        try:
            result = node_actions.add_asset(
                self.panel.cop_model,
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
                    messages.NODE_SAVE_FAILED_WITH_REASON % (node.name(), save_error),
                    title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                )
            return
        if not result and ui is not None:
            ui.displayMessage(
                messages.NODE_SAVE_FAILED % node.name(),
                title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
            )
        if isinstance(result, library.ListNotSaved):    # the name below is the one the add gave it
            debug.refuse(messages.ASSET_ADDED_LIBRARY_NOT_SAVED % (dialog.name.strip() or node.name()))

    def update_preview(self, indexes) -> None:
        """Update Render on Node tiles: each network's thumbnail re-rendered by `node_actions`."""
        model, rows = self._model_and_rows(indexes)
        if rows:
            node_actions.render_thumbnails(model, rows)

    @classmethod
    def save_rank(cls, nodes) -> int:
        return 3


class CodeSection(AssetSection):
    """Saved code snippets, each tagged with a language, previewed as rendered text."""

    offers_preview_update = False    # no Update Render: the preview key is content-addressed, so an edit redraws it

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this snippet? It is deleted permanently. Code "
                    "already applied to a node is not affected.")
        return ("Delete %d snippets? They are deleted permanently. Code already "
                "applied to a node is not affected." % count)

    key = "code"
    label = section_list.label(key)
    empty_noun = "snippet"
    EMPTY = amazetheme.EMPTY_CODE    # New File needs no selection, so it always works
    GRID_MENU = (    # Load Asset and Edit act on one snippet; New File needs no selection and stays enabled
        MenuEntry("New File", handler="menu_new_snippet", needs="always"),
        SEPARATOR,
        MenuEntry("Load Asset", handler="menu_apply", needs="one"),
        MenuEntry("Edit", handler="menu_edit", needs="one"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    DROP = DropRule(on_node="drop_code_at_release",    # to the node under the cursor; on empty space a holder node is created
                    on_space="create_code_node_in",
                    click_on_node="drop_code_at_release")

    holder_node_type_method = "code_holder_node_type"    # per language AND per network kind, so a method returns it

    CODE_HOLDER_NODE_TYPES = {    # the node type created per language and network kind; an absent pair creates nothing
        "vex": {"Sop": "attribwrangle", "Lop": "attribwrangle",
                "Cop": "wrangle"},
        "opencl": {"Sop": "opencl", "Cop": "opencl"},
        "python": {"Sop": "python"},
    }

    def _code_asset(self, index) -> tuple:
        """(row, snippet) under a grid index, or (None, None) where no snippet is."""
        model = self.panel.code_model
        if not model or index is None or not index.isValid():
            return None, None
        row = self.panel.code_sorted_model.mapToSource(index).row()
        if not 0 <= row < len(model.assets):
            return None, None
        return row, model.assets[row]

    def _holder_node_type_for(self, asset, dest) -> str:
        """The node type `asset` becomes in `dest`, or "" where that network kind has none."""
        if asset is None or dest is None:
            return ""
        language = str(getattr(asset, "renderer", "") or "").lower()
        try:
            category = dest.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return ""
        return self.CODE_HOLDER_NODE_TYPES.get(language, {}).get(
            category.name() if category is not None else "", "")

    def code_holder_node_type(self, index, dest) -> str:
        """WHICH node type a snippet becomes in `dest`: the drag preview shows this type."""
        return self._holder_node_type_for(self._code_asset(index)[1], dest)

    def create_code_node_in(self, index, dest, position=None) -> bool:
        """A holder node for the snippet in `dest`, where that network kind has one, loaded with it."""
        from amaze.core import dragengine
        panel = self.panel
        row, asset = self._code_asset(index)
        type_name = self._holder_node_type_for(asset, dest)
        if not type_name:
            return False
        name = wording.sanitize_usd_path(
            str(getattr(asset, "name", "") or "")) or "snippet"
        with dragengine.drop_group("Amaze Create Code Node"):
            node = panel.drop_placement.create_holder_node(dest, type_name, name, position)
            if node is None:
                return False
            ok, _reason = code_actions.apply_to_node(panel.code_model, row, node)
            if not ok:
                node.destroy()
                return False
        return True

    def drop_code_at_release(self, index, node: hou.Node) -> bool:
        """Apply a dropped snippet to the node under the cursor; no code parm shows a reason."""
        from amaze.core import dragengine
        panel = self.panel
        if not panel.code_model or index is None or node is None:
            return False
        try:
            source_index = panel.code_sorted_model.mapToSource(index)
        except Exception:
            return False
        with dragengine.drop_group("Amaze Apply Code Snippet"):
            ok, reason = code_actions.apply_to_node(
                panel.code_model, source_index.row(), node
            )
        if not ok:
            if reason:
                debug.refuse(reason)    # the miss icon shows the failure, the status line the reason ▸p/refuse-vs-alert
            return False
        return True

    def menu_new_snippet(self, indexes, current, payload=None) -> None:
        self.panel.new_code_snippet()

    def menu_apply(self, indexes, current, payload=None) -> None:
        self.panel.click_on_row(self, current)    # `click_on_row`, the same call as a double-click

    def _code_row(self, current):
        """The code model's row under a grid index, or None."""
        return self._code_asset(current)[0]

    def menu_edit(self, indexes, current, payload=None) -> None:
        row = self._code_row(current)
        if row is not None:
            self._edit_code_row(row)

    def menu_run(self, indexes, current, payload=None) -> None:
        """Run the snippet in this Houdini; a failure is shown on the status line."""
        row = self._code_row(current)
        if row is None:
            return
        asset = self.panel.code_model.assets[row]
        problem = code_actions.run_python(asset.name, asset.code)
        if problem:
            debug.refuse(messages.SNIPPET_RUN_FAILED % (asset.name, problem))

    def _edit_code_row(self, row: int) -> None:
        from amaze.dialogs import code_dialog
        panel = self.panel
        asset = panel.code_model.assets[row]
        model, mat_id = panel.code_model, str(asset.mat_id)
        on = library_settings.allow_overwrite(panel.prefs)    # Preferences ▸ Versions
        listed, active = model.version_list(row) if on else ([], 0)
        dialog = code_dialog.CodeDialog(
            panel.get_code_category_names(),
            name=asset.name,    # the snippet's name is its active version's name
            language=asset.renderer,
            category=asset.categories[0] if asset.categories else "",
            tags=", ".join(asset.tags),
            code=asset.code,
            title="Edit Snippet",
            versions=listed, active=active, saved=True, versions_on=on,
            load_version=lambda n: model.version_text(model.find_asset_row_by_id(mat_id), n),
            parent=panel,
        )
        self.run_code_dialog(dialog, mat_id)

    def run_code_dialog(self, dialog, mat_id: str) -> None:
        """Each Apply saves snippet `mat_id`, a new one while it is empty; the window stays open."""
        panel = self.panel
        saved = {"id": mat_id}

        def apply():
            if dialog.category:
                panel.code_category_model.check_add_category(dialog.category)
            got = panel.code_model.save_from_editor(    # NO layout pair: it emits its own model signals
                saved["id"], dialog.version, dialog.code, dialog.name, dialog.language,
                dialog.category, dialog.tags)
            panel.refresh_sidebar_categories()
            if got:
                saved["id"] = got
                dialog.versions_saved(*panel.code_model.version_list(
                    panel.code_model.find_asset_row_by_id(got)))

        dialog.applied.connect(apply)
        dialog.exec()
    library_model_attrs = ("code_model", "code_category_model")
    model_attr = "code_model"
    proxy_attr = "code_sorted_model"
    selection_attr = "code_selection_model"
    category_attr = "code_category_model"
    sidebar_attr = "code_category_sorted_model"
    delegate_attr = "code_delegate"
    tile_badges = ("favourite", "execute", "versions", "comment")
    filter_tooltip = "Show snippets in one language."

    FILTER_CHOICES = (    # the stored language strings, "Code" the catch-all; not imported from code_dialog
        FilterEntry("VEX", "VEX", "VEX"),
        FilterEntry("OpenCL", "OpenCL", "OpenCL"),
        FilterEntry("Python", "Python", "Python"),
        FilterEntry("Code", "Code", "Code"),
    )

    takes_language = True

    def can_save(self, nodes) -> bool:
        from amaze.helpers import helpers
        parm = helpers.find_code_parm(nodes[0]) if len(nodes) == 1 else None
        return parm is not None and bool(parm.eval().strip())    # an empty snippet saves nothing

    def commit_save(self, nodes, node, dialog) -> None:
        """The snippet is the current value of the node's code parm."""
        from amaze.helpers import helpers
        parm = helpers.find_code_parm(node)
        if dialog.categories:
            self.panel.code_category_model.check_add_category(dialog.categories)
        self.panel.code_model.add_asset(    # no layout wrapper: add_asset emits its own row-insert signals
            parm.eval(),
            dialog.name or node.name(),
            dialog.language or helpers.code_parm_language(parm),
            dialog.categories,
            dialog.tags,
            False,
        )
        self.panel.refresh_sidebar_categories()

    @classmethod
    def save_rank(cls, nodes) -> int:
        return 1


class FolderSection(Section):
    """A folder list and a files model behind TextureFilterProxyModel; stack() is None."""

    files_attr = ""
    last_folder_pref = ""
    selection_attr = ""    # with delegate_attr, what activate() points the shared grid at
    delegate_attr = ""
    search_hint = ""    # files carry no tags or categories, so the name is all there is to match
    library_model_attrs = ("file_folders_model",)    # the folders are stored in the library's files.json ▸p/folders-follow-the-library

    def __init__(self, panel) -> None:
        super().__init__(panel)
        changed = getattr(self._p(self.sidebar_attr), "scene_folder_changed", None)
        if changed is not None:
            changed.connect(self._scene_moved)
        left = getattr(self._p(self.sidebar_attr), "scene_folder_left", None)
        if left is not None:
            left.connect(self._scene_left)

    def _scene_left(self, old: str) -> None:
        """The scene row was removed: a grid showing its folder calls `activate` again."""
        try:
            active = self.panel.active_section() is self
        except RuntimeError:    # the panel was deleted, and the shared model outlives it
            return
        shown = self.shown_sidebar_key()
        if active and shown and (shown.rstrip("/") + "/").startswith(old):
            self.activate()

    def _scene_moved(self, old: str, new: str) -> None:
        """The scene's folder moved: a grid on the scene row, or inside it, shows the new folder."""
        try:
            view, folders = self._sidebar_view()
        except RuntimeError:    # the panel was deleted, and the shared model outlives it
            return
        if folders is None:
            return
        if folders.is_scene_row(sidebar.top_level(view.currentIndex())):
            self._highlight(view, folders.index(folders.scene_row(), 0))
            self._browse(new, remember=folders.SCENE_LABEL)

    def filter_text(self, text: str) -> None:
        proxy = self._p(self.proxy_attr)
        if proxy is not None:
            proxy.set_name_filter(text)

    def filter_favorites(self, on: bool) -> None:
        proxy = self._p(self.proxy_attr)
        if proxy is not None:
            proxy.set_favorites_only(on)

    def apply_filter(self, value) -> None:
        proxy = self._p(self.proxy_attr)
        if proxy is not None:
            proxy.set_kind_filter(value)


    def before_sidebar_shown(self) -> None:
        self._p(self.sidebar_attr).refresh_counts()    # every count is read again on entering

    def restore_sidebar_selection(self) -> None:
        """Select the remembered folder: All, the scene row, a location, or a subfolder inside one."""
        panel = self.panel
        folders = self._p(self.sidebar_attr)
        last = getattr(panel.prefs, self.last_folder_pref, "")
        if last == folders.ALL_LABEL:
            target_row = 0
        elif last == folders.SCENE_LABEL:
            target_row = folders.scene_row()
        else:
            target_row = folders.row_of(last) if last else None
        inside = ""    # a remembered subfolder: the grid shows it, the sidebar expands to it
        if target_row is None and last and last not in (folders.ALL_LABEL, folders.SCENE_LABEL):
            owner = folders.top_of(last)
            if owner.rstrip("/") != last.rstrip("/") and os.path.isdir(last):
                inside, target_row = last, folders.row_of(owner)
        if target_row is None:
            target_row = 1 if folders.rowCount() > 1 else 0    # never All: it scans every location
        if panel.cat_list and folders.rowCount() > 0:
            target_index = folders.index(target_row, 0)
            if panel.cat_list.selectionModel() is not None:
                panel.cat_list.highlight(target_index)
            if inside:
                self._browse(inside)
                reveal = getattr(panel.cat_list, "reveal", None)
                if reveal is not None:
                    reveal(inside)    # selects it once its parent folders have been read
            else:
                panel.update_selected_cat()

    def library_switched(self) -> None:
        self.activate()    # the files model lists a folder, not the library

    def _browse(self, path, remember=None) -> None:
        """Point the files model at a folder path (None = the 'All' row), remember it, and persist."""
        files = self._p(self.files_attr)
        folders = self._p(self.sidebar_attr)
        if path is None:
            setattr(self.panel.prefs, self.last_folder_pref, folders.ALL_LABEL)
            files.set_all_folders()
        else:
            setattr(self.panel.prefs, self.last_folder_pref, path if remember is None else remember)
            files.set_folder(path)
        self.panel.prefs.save()

    def select_category(self, index) -> None:
        folders = self._p(self.sidebar_attr)
        remember = folders.SCENE_LABEL if folders.is_scene_row(index) else None    # by SCENE_LABEL: the scene's folder can change
        self._browse(index.data(folders.BrowseRole), remember)    # a location's path, or a subfolder's

    def shown_sidebar_key(self) -> str:
        files = self._p(self.files_attr)
        return files.browsing() if files is not None else ""

    def select_sidebar_key(self, key: str) -> None:
        """A rowless subfolder selects its location: until its row is read, or always if deleted."""
        view, folders = self._sidebar_view()
        if not (key and folders is not None and self._has_no_row(folders, key)):
            super().select_sidebar_key(key)
            return
        if not os.path.isdir(key):    # deleted from disk: select its location row and show its files
            super().select_sidebar_key(folders.top_of(key))
            return
        self._highlight(view, folders.index(folders.row_of(folders.top_of(key)), 0))
        if self.shown_sidebar_key() != key:
            self._browse(key)
        reveal = getattr(view, "reveal", None)
        if reveal is not None:
            reveal(key)

    @staticmethod
    def _has_no_row(folders, path: str) -> bool:
        """Is `path` a folder inside a top row's folder, with no row of its own?"""
        owner = folders.top_of(path)
        return (owner.rstrip("/") != path.rstrip("/") and folders.row_of(owner) is not None
                and not folders.index_of(path).isValid())

    def shows_empty_state(self, source) -> bool:
        folders = self._p(self.sidebar_attr)    # the grid lists one location; the empty state means none
        return folders is None or not folders._folders()

    def tile_models(self):
        return self._p(self.files_attr), self._p(self.proxy_attr)

    def selected_kinds(self, indexes) -> set:
        """Every kind in the selection, read once for the whole Grid menu."""
        files = self._p(self.files_attr)
        if files is None:
            return set()
        return {index.data(files.KindRole) or "" for index in indexes}

    def _path_of(self, index) -> str:
        files = self._p(self.files_attr)
        if files is None or index is None or not index.isValid():
            return ""
        return str(index.data(files.PathRole) or "")

    def selection_has_importable(self, indexes, current) -> bool:
        return bool(self.selected_kinds(indexes)
                    & {locations.KIND_IMAGE, locations.KIND_GEO})

    def selection_has_scene(self, indexes, current) -> bool:
        return locations.KIND_HIP in self.selected_kinds(indexes)

    def menu_offers_preview(self, indexes, current) -> bool:
        files, rows = self._model_and_rows(indexes)    # a capture, an OS icon and a .rat not rendered cannot re-render
        return bool(self.offers_preview_update and files is not None
                    and any(files.renders_thumbnail(row) for row in rows))

    def menu_import_enabled(self, indexes, current) -> bool:
        """An image loads onto one node parameter, so images import one at a time; geometry imports all."""
        kinds = self.selected_kinds(indexes)
        return len(indexes) == 1 or kinds == {locations.KIND_GEO}

    def menu_capture_enabled(self, indexes, current) -> bool:
        """One tile; a scene only while it is the one open, however it was opened."""
        if len(indexes) != 1:
            return False
        files = self._p(self.files_attr)
        if files is None or current is None or \
                current.data(files.KindRole) != locations.KIND_HIP:
            return True
        path = self._path_of(current)    # with another scene open, the capture would be saved under this one
        return bool(path) and path == scene_captures.current_scene_path()

    def menu_import(self, indexes, current, payload=None) -> None:
        files = self._p(self.files_attr)
        if files is None:
            return
        if self.selected_kinds(indexes) == {locations.KIND_IMAGE}:
            self.panel.click_on_row(self, current)    # `click_on_row`, the same call as a double-click on the row
            return
        for index in indexes:
            if index.data(files.KindRole) == locations.KIND_GEO:
                self.panel.import_geo_asset(index)

    def menu_load_scene(self, indexes, current, payload=None) -> None:
        self.open_hip_scene(current)

    def menu_copy_path(self, indexes, current, payload=None) -> None:
        self.panel.copy_file_paths(indexes)

    def menu_reveal(self, indexes, current, payload=None) -> None:
        path = self._path_of(current)
        if not path:
            return
        try:
            ui_helpers.reveal(path)
        except Exception as exc:                         # noqa: BLE001
            debug.event("file", "reveal failed", error=str(exc))

    def menu_new_enabled(self, indexes, current) -> bool:
        """New Folder and Save Scene act on the folder shown: none while All is showing."""
        return bool(self._shown_folder())

    def _shown_folder(self) -> str:
        files = self._p(self.files_attr)
        return files.browsing() if files is not None else ""

    def _new_name(self, title: str) -> str:
        """The typed name: "" for a cancel, a cleared field, or a name with a slash."""
        name = (self.panel.ask_category_name(title, "") or "").strip()
        if name and ("/" in name or os.sep in name):
            debug.refuse(messages.NEW_NAME_HAS_A_SLASH % name)
            return ""
        return name

    def menu_new_folder(self, indexes, current, payload=None) -> None:
        folder = self._shown_folder()
        name = self._new_name("New Folder") if folder else ""
        if not name:
            return
        path = os.path.join(folder, name)
        if os.path.exists(path):
            debug.refuse(messages.NEW_FOLDER_TAKEN % (name, folder))
            return
        try:
            os.makedirs(path)
        except OSError as exc:
            debug.refuse(messages.NEW_FOLDER_FAILED % (name, exc))
            return
        debug.event("file", "folder made", path=path)
        self._refresh_shown()

    def menu_save_scene(self, indexes, current, payload=None) -> None:
        """Save As of the open scene into the folder shown; the file becomes the open scene."""
        from amaze.core import scene_captures
        folder = self._shown_folder()
        name = self._new_name("Save Scene") if folder else ""
        if not name:
            return
        path = os.path.join(folder, name + scene_captures.scene_extension())
        if os.path.exists(path):
            debug.refuse(messages.SAVE_SCENE_TAKEN % (os.path.basename(path), folder))
            return
        try:
            hou.hipFile.save(path)
        except hou.Error as exc:
            debug.refuse(messages.SAVE_SCENE_FAILED % (path, exc))
            return
        debug.event("hip", "scene saved as new", file=path)
        self._refresh_shown()

    def _refresh_shown(self) -> None:
        """The grid lists the folder again; the sidebar re-reads it, so a new subfolder gets its row."""
        folders, files = self._p(self.sidebar_attr), self._p(self.files_attr)
        if files is not None:
            files.refresh_current_folder()
        if folders is not None:
            folders.refresh_counts()

    def toggle_favourite(self, indexes) -> None:
        files, rows = self._model_and_rows(indexes)    # the model resolves each row to its path key
        if files is not None:
            files.toggle_favorites(rows)

    takes_file_drops = True    # ▸r/cross-volume-move
    _last_move = ()    # (source, destination) per file of the last move, until it is undone

    def accepts_file_drop(self, index) -> bool:
        """A location, or a folder inside one; never All."""
        return bool(self.drop_folder(index))

    def drop_folder(self, index) -> str:
        folders = self._p(self.sidebar_attr)
        return str(index.data(folders.BrowseRole) or "") if folders is not None else ""

    def move_files_to(self, folder: str) -> bool:
        """Move the grid's selected files into `folder`, on a worker; True when a move started."""
        if file_moves.mover.busy():
            debug.refuse(messages.MOVE_BUSY)
            return False
        selection = self._p(self.selection_attr)
        paths = [self._path_of(index) for index in
                 (grid_columns.selected_rows(selection) if selection is not None else ())]
        scene = scene_captures.current_scene_path()
        open_scene = [path for path in paths if path and scene
                      and hostos.canonical_path_key(path) == hostos.canonical_path_key(scene)]
        notices = [messages.MOVE_OPEN_SCENE % os.path.basename(path) for path in open_scene]
        pairs = file_moves.targets([path for path in paths if path not in open_scene], folder)
        if not pairs:
            if notices:
                debug.refuse(" ".join(notices))
            return False
        self._start_move(pairs, folder, notices, undo=False)
        return True

    def can_undo_move(self, indexes, current) -> bool:
        return bool(self._last_move) and not file_moves.mover.busy()

    def menu_undo_move(self, indexes, current, payload=None) -> None:
        pairs = file_moves.back(self._last_move)
        if not pairs or file_moves.mover.busy():
            return
        self._last_move = ()
        self._start_move(pairs, os.path.dirname(pairs[0][1]), [], undo=True)

    def menu_copy(self, indexes, current, payload=None) -> None:
        """The selected files go on the system clipboard, as files."""
        paths = [self._path_of(index) for index in indexes]
        if ui_helpers.copy_files(paths):
            debug.event("file", "files copied", count=len([path for path in paths if path]))

    def menu_paste_enabled(self, indexes, current) -> bool:
        """A folder is shown, the clipboard holds files, and no move or paste is running."""
        return bool(self._shown_folder() and ui_helpers.clipboard_files()
                    and not file_moves.mover.busy())

    def menu_paste(self, indexes, current, payload=None) -> None:
        """Copy the clipboard's files into the folder shown; names in use are asked about once."""
        folder = self._shown_folder()
        paths = ui_helpers.clipboard_files()
        if not folder or not paths or file_moves.mover.busy():
            return
        notices = [messages.PASTE_FOLDER % os.path.basename(path.rstrip("/\\"))
                   for path in paths if os.path.isdir(path)]
        pairs = [(path, os.path.join(folder, os.path.basename(path)))
                 for path in paths if not os.path.isdir(path)]
        taken = [pair for pair in pairs
                 if os.path.lexists(pair[1]) and not file_moves.same_file(*pair)]
        answer = self._ask_overwrite(taken) if taken else "skip"
        if answer == "cancel":
            return
        if answer == "skip":
            pairs = [pair for pair in pairs if pair not in taken]
        if not pairs:
            if notices:
                debug.refuse(" ".join(notices))
            return
        self._move_job = {"count": len(pairs), "name": self._folder_name(folder),
                          "notices": notices, "undo": False, "percent": -1, "paste": True}
        file_moves.mover.start(pairs, self.panel.prefs, self._move_progress, self._move_finished,
                               copying=True, replace=answer == "overwrite")

    def _ask_overwrite(self, taken) -> str:
        """`overwrite`, `skip` or `cancel` for the names already in the folder; `skip` without a UI."""
        ui = getattr(hou, "ui", None)
        if ui is None:
            return "skip"
        lines = self._name_in_use_lines(taken, "asked")
        choice = ui.displayMessage(
            " ".join(lines), buttons=messages.BUTTONS_OVERWRITE_OR_SKIP,
            default_choice=1, close_choice=2,
            title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
        return ("overwrite", "skip", "cancel")[choice]

    def _start_move(self, pairs, folder: str, notices, undo: bool) -> None:
        self._move_job = {"count": len(pairs), "name": self._folder_name(folder),
                          "notices": list(notices), "undo": undo, "percent": -1, "paste": False}
        file_moves.mover.start(pairs, self.panel.prefs, self._move_progress, self._move_finished)

    def _move_progress(self, done, total) -> None:
        """A copy's progress on the status line, once per whole percent."""
        job = self._move_job
        percent = int(done * 100 / total) if total else 100
        if percent != job["percent"]:
            job["percent"] = percent
            count, name = _file_count(job["count"]), job["name"]
            debug.status(messages.PASTE_PROGRESS % (count, name, percent) if job["paste"]
                         else messages.MOVE_PROGRESS % (count, name, percent))

    def _move_finished(self, result) -> None:
        """Refresh the models, offer Undo after a move, and show the result on one line."""
        job = self._move_job
        for attr in (self.files_attr, self.sidebar_attr):
            model = self._p(attr)
            if model is not None:
                (model.refresh_counts if attr == self.sidebar_attr
                 else model.refresh_current_folder)()
        paste = job["paste"]
        if not paste:    # a paste leaves the last move undoable
            self._last_move = () if job["undo"] else tuple(result.moved)
        lines = list(job["notices"])
        if result.moved:
            count = _file_count(len(result.moved))
            if job["undo"]:
                lines.insert(0, messages.MOVE_BACK % count)
            elif paste:
                lines.insert(0, messages.PASTE_DONE % (count, job["name"]))
            else:
                lines.insert(0, messages.MOVE_DONE % (count, job["name"]))
        lines += self._name_in_use_lines(result.skipped, "pasted" if paste else "moved")
        lines += [messages.PASTE_FAILED % (os.path.basename(source), why) if paste
                  else messages.MOVE_FAILED % (os.path.basename(source), why)
                  for source, why in result.failed]
        if job["notices"] or result.skipped or result.failed:
            debug.refuse(" ".join(lines))
        elif lines:
            debug.status(" ".join(lines))

    def _name_in_use_lines(self, skipped, said="moved") -> list:
        """One sentence per folder with names in use, worded as `moved`, `pasted` or `asked`."""
        by_folder = {}
        for _source, dest in skipped:
            by_folder.setdefault(os.path.dirname(dest), []).append(os.path.basename(dest))
        lines = []
        for folder, names in by_folder.items():
            shown = names[:3] + ([messages.MOVE_MORE % (len(names) - 3)] if len(names) > 3 else [])
            listed, name = wording.and_list(shown), self._folder_name(folder)
            one, many = {
                "moved": (messages.MOVE_TAKEN % (listed, name),
                          messages.MOVE_TAKEN_MANY % (listed, name)),
                "pasted": (messages.PASTE_TAKEN % (listed, name),
                           messages.PASTE_TAKEN_MANY % (listed, name)),
                "asked": (messages.PASTE_ASK % (listed, name),
                          messages.PASTE_ASK_MANY % (listed, name)),
            }[said]
            lines.append(one if len(names) == 1 else many)
        return lines

    def _folder_name(self, folder: str) -> str:
        """A folder as the sidebar names it, else its own name."""
        folders = self._p(self.sidebar_attr)
        index = folders.index_of(folder) if folders is not None else QtCore.QModelIndex()
        shown = index.data() if index.isValid() else ""
        return str(shown or os.path.basename(folder.rstrip("/\\")) or folder)

    colour_title = "Location Color"

    def location_key(self, index) -> str:
        """The registered location on this row, by its path; "" on All, the scene row and a subfolder."""
        folders = self._p(self.sidebar_attr)
        if folders is None or index is None or not index.isValid():
            return ""
        return str(index.data(folders.PathRole) or "")

    def colour_key(self, index) -> str:
        return self.location_key(index)    # a colour belongs to a location, never to a subfolder

    def repaint_grid_colours(self) -> None:
        files = self._p(self.files_attr)
        if files is not None and files.rowCount():    # every tile from that location repaints, role-scoped
            files.colours_changed()    # drop the colour cache before the repaint
            files.dataChanged.emit(
                files.index(0, 0), files.index(files.rowCount() - 1, 0),
                [files.CategoryColorRole])

    offers_preview_update = True

    def update_preview(self, indexes) -> None:
        files, rows = self._model_and_rows(indexes)    # ONE batch: images re-convert, scenes re-read
        if rows:
            files.rerender_thumbnails(rows)

    def comment_subject(self, index):
        model, proxy = self.tile_models()    # a row here is a file, keyed by its path
        if model is None or proxy is None:
            return None
        source = proxy.mapToSource(index)
        if not source.isValid():
            return None
        path = model.file_key(source.row())
        if not path:
            return None
        return CommentSubject(
            key=notes.note_key(self.key, path),
            name=source.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
            type=source.data(model.FormatRole) or "",
        )


class FileSection(FolderSection):
    """One folder list, every file shown, each row handled by its kind. ▸o/section-api"""

    key = "file"
    label = section_list.label(key)
    filter_tooltip = "Show one kind of file."
    empty_noun = "file"
    EMPTY = amazetheme.EMPTY_FILE    # a button: registering a folder needs nothing selected

    FILTER_CHOICES = (  # the known kinds, in the order kind_for tests them; KIND_OTHER has no entry
        FilterEntry("Images", "Images", locations.KIND_IMAGE),
        FilterEntry("Geometry", "Geometry", locations.KIND_GEO),
        FilterEntry("Hip", "Hip", locations.KIND_HIP),
    )

    GRID_MENU = UNDO_MOVE + (  # the selection's KINDS decide the actions; no Delete: these are the user's own files
        MenuEntry("New Folder", handler="menu_new_folder", needs="menu_new_enabled"),
        SEPARATOR,
        MenuEntry("Copy", handler="menu_copy"),
        MenuEntry("Paste", handler="menu_paste", needs="menu_paste_enabled"),
        SEPARATOR,
        MenuEntry("Open Scene", handler="menu_load_scene", needs="one",
                  shown="selection_has_scene"),
        MenuEntry("Save Scene", handler="menu_save_scene", needs="menu_new_enabled"),
        SEPARATOR,
        MenuEntry("Load Asset", handler="menu_import", needs="menu_import_enabled",
                  shown="selection_has_importable"),
        MenuEntry("Copy Path", handler="menu_copy_path"),
        SEPARATOR,
        MenuEntry("Show Location", handler="menu_reveal", needs="one"),
    ) + GRID_MENU_TAIL

    _PATH_ONLY = DropRule(on_node="drop_file_path_on_node",    # per row kind: every kind sets its path on a node; a drop off any node differs
                          click_resolve="click_copy_path")
    DROP_BY_KIND = {
        locations.KIND_IMAGE: DropRule(
            on_node="drop_file_path_on_node",
            on_space="create_image_node_in",
            click_on_node="drop_file_path_on_node",
            holder_node_type="mtlximage"),  # the drag preview shows THIS node type
        locations.KIND_GEO: DropRule(
            on_node="drop_file_path_on_node",
            resolve="drop_geo_at_release",
            click_on_node="drop_file_path_on_node",
            click_resolve="click_import_geo"),
        locations.KIND_HIP: DropRule(
            on_node="drop_file_path_on_node",
            click_resolve="click_open_hip"),
        locations.KIND_OTHER: _PATH_ONLY,
        "": _PATH_ONLY,
    }

    exports_selection = True

    def export_package_to(self, indexes, path: str) -> int:    # the File version: each selected file is packaged whole under its kind
        items = []
        from amaze.core import packages
        for index in indexes:
            if index is None or not index.isValid():
                continue
            source = index.data(file_library.FileFiles.PathRole)
            if not source:
                continue
            kind = (index.data(file_library.FileFiles.KindRole)
                    or file_library.kind_for(os.path.basename(source)))
            items.append(packages.collect_file(source, kind))
        if not items:
            return 0
        return packages.write_package(path, items)

    def click_import_geo(self, index) -> bool:
        self.panel.import_geo_asset(index)
        return True

    def drop_geo_at_release(self, index: QtCore.QModelIndex) -> bool:
        """Import dropped geometry into the network under the cursor; quietly False if none."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        panel = self.panel
        context = panel.drop_placement.context_under_cursor(
            panel.drop_placement.is_sop_container, include_viewports=True
        )
        if context is None:
            return False
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return False
        with dragengine.drop_group("Amaze Import Geometry"):
            created = panel.drop_placement.import_geo_in_context(path, context)
        if created is not None:
            helpers.place_nodes([created],
                                panel.drop_placement.release_position_in(context))
        return True

    def click_open_hip(self, index) -> bool:
        self.open_hip_scene(index)
        return True

    def open_hip_scene(self, index) -> None:
        """Open a scene file from the grid; Houdini's own save prompt handles unsaved changes."""
        path = self.panel.hip_path_for(index)
        if not path:
            return
        if not os.path.isfile(path):
            debug.refuse(debug.Damage(messages.SCENE_FILE_MISSING % path))    # ▸p/refuse-vs-alert
            debug.event("hip", "scene missing", file=path)
            return
        try:
            hou.hipFile.load(path, suppress_save_prompt=False,
                             ignore_load_warnings=False)
        except hou.LoadWarning as warn:    # a scene that loads with warnings is still open
            debug.event("hip", "opened with warnings", file=path,
                        warning=str(warn)[:400])
        except Exception as exc:                         # noqa: BLE001
            debug.refuse(debug.Damage(messages.SCENE_OPEN_FAILED % (path, exc)))
            debug.event("hip", "open failed", file=path, error=str(exc))
            return
        debug.event("hip", "scene opened", file=path)

    def drop_file_path_on_node(self, index, node) -> bool:
        """A File row dropped on a node sets its first file parameter; False if it has none."""
        panel = self.panel
        from amaze.core import dragengine
        from amaze.helpers import helpers
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return False
        parm = helpers.find_file_parm(node)
        if parm is None:
            debug.refuse(messages.NODE_HAS_NO_FILE_PARM
                         % (node.name(), os.path.basename(path)))
            return False
        with dragengine.drop_group("Amaze Set File Path"):
            parm.set(panel.drop_placement.scene_path(path))
        return True

    def create_image_node_in(self, index, dest, position=None) -> bool:
        """Create a mtlximage node set to the file's path, where the network can contain one."""
        panel = self.panel
        from amaze.core import dragengine
        from amaze.helpers import helpers
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return False
        base = wording.sanitize_usd_path(
            os.path.splitext(os.path.basename(path))[0]) or "image"
        with dragengine.drop_group("Amaze Create Image Node"):
            node = panel.drop_placement.create_holder_node(dest, "mtlximage", base, position)
            if node is None:
                return False
            parm = helpers.find_file_parm(node)
            if parm is None:
                node.destroy()
                return False
            parm.set(panel.drop_placement.scene_path(path))
        return True

    def click_copy_path(self, index) -> bool:
        """Copy the path: the only click action for a file of unknown kind."""
        self.panel.copy_file_paths([index])
        return True

    SIDEBAR_MENU = UNDO_MOVE + (  # per-location entries need a REAL row: All is no location, its key `""`
        MenuEntry("Add", handler="menu_add_location", needs="always"),
        MenuEntry("Locate", handler="menu_locate_location",
                  needs="on_a_location"),
        MenuEntry("Rename", handler="menu_rename_location",
                  children="rename_actions", needs="on_a_location"),
        MenuEntry("Remove", handler="menu_remove_location",
                  needs="on_a_location"),
        SEPARATOR,
        MenuEntry("Sort by name", handler="menu_sort_locations",
                  needs="always"),
        SEPARATOR,
        MenuEntry("Label", handler="menu_label_colour", children="label_colours",
                  needs="on_a_location"),
    )

    def menu_sort_locations(self, indexes, current, payload=None) -> None:
        """Sort by name, once: the locations below All and the scene row, from any row clicked."""
        folders = self._p(self.sidebar_attr)
        if folders is None:
            return
        shown = self.shown_sidebar_key()    # the grid's folder: a right press moved only the sidebar
        if not folders.sort_folders():    # a model reset, which clears the sidebar's selection
            return
        folders.commit_order()    # one write, as on a drag's release
        self.select_sidebar_key(shown)

    def on_a_location(self, indexes, current) -> bool:
        return bool(self.location_key(current))

    def rename_actions(self, indexes, current) -> tuple:
        """Edit names the location; Set to Default goes back to the folder's own name."""
        path = self.location_key(current)
        named = bool(path and self.panel.prefs.file_folder_names.get(path))
        return (("Edit", "edit", "", True), None,
                ("Set to Default", "default", "", named))    # disabled with no name set, never hidden

    def _repaint_location(self, path: str) -> None:
        folders = self._p(self.sidebar_attr)
        row = folders.row_of(path) if folders is not None else None
        if row is not None:
            index = folders.index(row, 0)
            folders.dataChanged.emit(index, index)

    def menu_rename_location(self, indexes, current, payload=None) -> None:
        path = self.location_key(current)
        if not path:
            return
        if payload == "default":
            name = ""
        else:
            prefs = self.panel.prefs
            name = self.panel.ask_category_name(
                "Rename Location", prefs.file_folder_names.get(path)
                or os.path.basename(path.rstrip("/\\")))    # the field starts with the name, never the path
            if name is None:
                return
        self.panel.prefs.set_file_folder_name(path, name)
        self._repaint_location(path)

    def menu_add_location(self, indexes, current, payload=None) -> None:
        self.panel.add_file_folder_user()

    def menu_remove_location(self, indexes, current, payload=None) -> None:
        self.reselect_after_removal(self.panel.remove_file_folder_user())

    def menu_locate_location(self, indexes, current, payload=None) -> None:
        self.panel.locate_folder_user(self._p(self.sidebar_attr))

    proxy_attr = "file_sorted_model"
    selection_attr = "file_selection_model"
    delegate_attr = "file_delegate"
    tile_badges = ("open", "favourite", "comment")
    sidebar_attr = "file_folders_model"
    files_attr = "file_files_model"
    last_folder_pref = "last_file_folder"

    def prefs_changed(self) -> None:
        folders, files = self._p(self.sidebar_attr), self._p(self.files_attr)
        if folders is not None:
            folders.refresh_counts()    # Show Unknown Files changes what counts as a row
        if files is not None:
            files.refresh_current_folder()    # once, so display preferences apply without a click


class OnlineContext(Section):
    """The online section: a Section's interface, not in SECTION_CLASSES; shown by activate()."""

    key = "online"
    label = "Online"
    tile_badges = ("favourite",)    # an indicator with no click: the list keeps its Favourite column
    sidebar_attr = "matx_source_model"
    proxy_attr = "matx_sorted_model"
    selection_attr = "matx_selection_model"
    delegate_attr = "matx_delegate"    # its own delegate, carrying only the roles matx_library has
    search_hint = ""    # empty, as on every tab; the tooltip explains the tag search

    def before_columns_synced(self) -> None:
        self.panel.matx_online_model.reload()    # the catalogue of the source the tabs show

    def shown_sidebar_key(self) -> str:
        role = self.panel.matx_online_model.CategoryRole
        return self.panel.matx_sorted_model.filter_value(role) or ""

    def filter_text(self, text: str) -> None:
        """The online search is set on the SOURCE model, not a proxy."""
        self.panel.matx_online_model.set_search(text)

    def filter_favorites(self, on: bool) -> None:
        """Nothing to do: an online record carries no favourite state."""

    def select_category(self, index) -> None:
        panel = self.panel    # All, keyed "", is the everything-row: remove the filter
        category = self.sidebar_key(index)
        role = panel.matx_online_model.CategoryRole
        if not category:
            panel.matx_sorted_model.removeFilter(role)
        else:
            panel.matx_sorted_model.setFilter(role, category)
        grid.visible_view(panel).scrollToTop()

    def double_click(self, index) -> None:
        """The primary action: puts the material into the scene, not into the library."""
        if index is None or not index.isValid():
            return
        panel = self.panel
        source = panel.matx_sorted_model.mapToSource(index)
        record = panel.matx_online_model.record(source.row())
        if record is not None:
            panel.online_import.import_records_to_scene([record])

    def stack(self):
        return None

    GRID_MENU = (    # named for where the material goes, a submenu for its renderer, as in C06/C06a/C06b
        MenuEntry("Import to Materials", handler="menu_import_to_library",
                  children="import_targets", count_suffix=True),
        MenuEntry("Import to Scene", handler="menu_import_to_scene",
                  children="import_targets", count_suffix=True),
        MenuEntry("Restore", handler="menu_restore_packages",
                  shown="selection_is_amaze_packages", count_suffix=True),
        MenuEntry("Refresh", handler="menu_refresh", needs="always"),
    )

    def _records(self, indexes) -> list:
        """The catalogue records behind these rows, read through the menu's own indexes."""
        model = self.panel.matx_online_model
        proxy = self.panel.matx_sorted_model
        records = []
        for index in indexes:
            record = model.record(proxy.mapToSource(index).row())
            if record is not None:
                records.append(record)
        return records

    def import_targets(self, indexes, current) -> tuple:
        """The renderer the import CREATES, as in C06a/C06b; disabled without its plugin."""
        from amaze.render.material_conversion import engine as conversion_engine
        intermediate = renderers.INTERMEDIATE.key
        return tuple(
            (renderer.label, renderer.key, renderer.icon,
             renderer.key == intermediate or conversion_engine.can_convert(intermediate, renderer.key))
            for renderer in renderers.offered(self.panel.prefs)
            if renderer.key in conversion_engine.targets())

    def menu_import_to_library(self, indexes, current, payload=None) -> None:
        self.panel.online_import.import_records(self._records(indexes),
                                                renderer=payload or renderers.INTERMEDIATE.key)

    def menu_import_to_scene(self, indexes, current, payload=None) -> None:
        self.panel.online_import.import_records_to_scene(    # this method does the editor restore for both of its callers
            self._records(indexes), renderer=payload or renderers.INTERMEDIATE.key)

    def selection_is_amaze_packages(self, indexes, current) -> bool:
        """Every selected record is an amazepkg - Restore means nothing for a material source."""
        records = self._records(indexes)
        return bool(records) and all(
            getattr(r, "kind", "") == "amazepkg" for r in records)

    def menu_restore_packages(self, indexes, current, payload=None) -> None:
        self.panel.package_import.restore(self._records(indexes))

    def menu_refresh(self, indexes, current, payload=None) -> None:
        """Refresh queries the live site, even for sources that browse from a shipped table."""
        for source in self.panel.matx_online_model.sources:
            try:
                source.refresh()
            except Exception as exc:                     # noqa: BLE001
                debug.exception("refresh source", exc, source=source.name)
        self.panel.matx_online_model.reload(force=True)    # force, or a loaded catalogue just re-filters and the user's explicit Refresh did nothing

    takes_comments = False    # the three the online section does not offer; the toolbar reads them
    takes_info = False
    takes_favourites = False
    takes_filter_menu = False
    takes_capture = False    # an online tile is not in the library: nowhere to keep a capture
    kind_filter_menu = True


class GradientSection(AssetSection):
    """Colors, an AssetSection; its own parts are the ramp actions, swatch menu and size filter."""

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:    # the only section whose prompt names the item
            return ('Delete "%s"? The gradient is deleted permanently. Ramps '
                    "already applied to a node are not affected."
                    % (name or "this palette"))
        return ("Delete %d gradients? They are deleted permanently. Ramps already "
                "applied to a node are not affected." % count)

    key = "gradient"
    label = section_list.label(key)
    empty_noun = "palette"
    EMPTY = amazetheme.EMPTY_COLOR    # no button: a palette is saved from a node in the network editor
    QUOTE = amazetheme.QUOTE_COLOR
    library_model_attrs = ("gradient_model", "gradient_categories_model")    # the raw models; sidebar_attr names the proxy over them
    model_attr = "gradient_model"
    category_attr = "gradient_categories_model"
    sidebar_attr = "gradient_category_sorted_model"    # the same CategoriesSidebarProxy the asset sidebars use
    delegate_attr = "gradient_delegate"
    tile_badges = ("favourite", "comment")
    proxy_attr = "gradient_sorted_model"
    selection_attr = "gradient_selection_model"

    offers_preview_update = False  # drawn from its ramp; nothing to re-render
    GRID_MENU = (  # both submenus are built per entry, so `children` names a method
        MenuEntry("Load Asset", handler="menu_apply_ramp", needs="one"),
        MenuEntry("Load Asset as", handler="menu_apply_ramp", children="ramp_bases",
                  needs="one"),
        MenuEntry("Copy Color", handler="menu_copy_swatch",
                  children="palette_swatches", needs="one"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    DROP = DropRule(on_node="apply_gradient_to_node",  # to a node with a ramp; on empty space a MaterialX ramp node, where supported
                    on_space="create_gradient_node_in",
                    click_on_node="apply_gradient_to_node")

    def apply_gradient_to_node(
        self, index: QtCore.QModelIndex, node: hou.Node,
        basis: str = "",
    ) -> bool:
        """Apply the dropped gradient to the node under the cursor; False with no colour ramp."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        entry = self._entry_at(index)
        if entry is None:
            return False
        parm = helpers.find_color_ramp_parm(node)
        if parm is None:
            debug.refuse(messages.NODE_HAS_NO_COLOR_RAMP % node.name())
            return False
        with dragengine.drop_group("Amaze Apply Gradient"):
            parm.set(self._entry_ramp(entry, basis))
        return True

    @staticmethod
    def _entry_ramp(entry: dict, basis: str = "") -> hou.Ramp:
        from amaze.helpers import helpers
        if basis:    # a basis rebuilds the ramp on that interpolation; otherwise the recorded ramp applies
            return helpers.build_basis_ramp(
                [c["hex"] for c in entry["colors"]], basis)
        ramp = entry.get("ramp")
        if ramp:
            return helpers.data_to_ramp(ramp)
        return helpers.build_stepped_ramp([c["hex"] for c in entry["colors"]])

    def create_gradient_node_in(self, index, dest, position=None,
                                basis: str = "") -> bool:
        """Create a MtlX colour ramp node; empty `basis` means the recorded ramp."""
        entry = self._entry_at(index)
        if entry is None:
            return False
        return self._create_gradient_holder_node(entry, dest, basis,
                                                 position=position)

    def _create_gradient_holder_node(self, entry, dest, basis: str = "",
                                     position=None) -> bool:
        """Node creation shared by the drop (an index) and the click actions (an entry)."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        name = wording.sanitize_usd_path(
            str(entry.get("name") or "")) or "gradient"
        with dragengine.drop_group("Amaze Create Gradient Node"):
            node = self.panel.drop_placement.create_holder_node(dest, "hmtlxrampc", name,
                                                                position)
            if node is None:
                return False
            parm = helpers.find_color_ramp_parm(node)
            if parm is None:
                node.destroy()
                return False
            parm.set(self._entry_ramp(entry, basis))
        return True

    def _copy_gradient_swatch(self, color: dict) -> None:
        """Put one swatch's hex code on the system clipboard; it assigns nothing."""
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
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.setStatusMessage(
                "Amaze: copied %s (%s)" % (hex_code, color.get("name", ""))
            )

    holder_node_type = "hmtlxrampc"  # the MaterialX colour ramp

    def accepts_category_drop(self, index, name: str) -> bool:
        return name in self.panel.gradient_model.user_categories()    # excludes any synthetic sidebar row

    SIDEBAR_MENU = (  # everything below All is a real user category, so the per-category entries exist only on such a row
        MenuEntry("Add", handler="menu_add_category", needs="always"),
        MenuEntry("Rename", handler="menu_rename_category", needs="one",
                  shown="on_a_category"),
        MenuEntry("Delete", handler="menu_remove_category",
                  shown="on_a_category"),
        SEPARATOR,
        MenuEntry("Sort by name", handler="menu_sort_categories",
                  needs="always"),
        SEPARATOR,
        MenuEntry("Label", handler="menu_label_colour", children="label_colours",
                  shown="on_a_category"),
    )

    def on_a_category(self, indexes, current) -> bool:
        """Whether the row under the cursor is a real user category, by its stored name."""
        if current is None:
            return False
        name = self.sidebar_key(current)
        return bool(name) and not category.is_all(name)

    def _entry_at(self, index):
        if index is None or not index.isValid():
            return None
        source = self.panel.gradient_sorted_model.mapToSource(index)
        return self.panel.gradient_model.entry(source.row())

    def ramp_bases(self, indexes, current) -> tuple:
        """Every interpolation, always offered."""
        from amaze.helpers import helpers
        return tuple((basis, basis, "", True)
                     for basis in helpers.RAMP_BASES)

    def palette_swatches(self, indexes, current) -> tuple:
        """One row per colour in this palette, each with its hex as the swatch colour."""
        entry = self._entry_at(current)
        if entry is None:
            return ()
        return tuple(
            ("%s   %s" % (colour["name"], colour["hex"].upper()),
             colour, colour["hex"], True)
            for colour in entry["colors"]
        )

    def menu_apply_ramp(self, indexes, current, payload=None) -> None:
        self.panel.click_on_row(self, current, payload or None)    # Apply and Apply as through `click_on_row`; the payload is the ramp basis

    def menu_copy_swatch(self, indexes, current, payload=None) -> None:
        if payload is not None:
            self._copy_gradient_swatch(payload)
    search_hint = ""  # this proxy also matches the colour NAMES inside a palette
    filter_tooltip = "Show palettes of one size."

    FILTER_CHOICES = (  # value (fewest, most); `most` None is the open end of "5+"
        FilterEntry("1 color", "1 color", (1, 1)),
        FilterEntry("2 colors", "2 colors", (2, 2)),
        FilterEntry("3 colors", "3 colors", (3, 3)),
        FilterEntry("4 colors", "4 colors", (4, 4)),
        FilterEntry("5+ colors", "5+ colors", (5, None)),
    )

    def apply_filter(self, value) -> None:
        self.panel.gradient_sorted_model.set_size_filter(value)    # filters by size; never through set_renderer_filter

    def can_save(self, nodes) -> bool:
        from amaze.helpers import helpers
        return (len(nodes) == 1
                and helpers.find_color_ramp_parm(nodes[0]) is not None)

    def save_categories(self) -> tuple:
        categories = self.panel.gradient_model.user_categories()
        return categories, (categories[0] if categories else "")

    def commit_save(self, nodes, node, dialog) -> None:
        """The node's first color ramp, registered as a user gradient."""
        from amaze.helpers import helpers
        parm = helpers.find_color_ramp_parm(node)
        ramp_data = helpers.ramp_to_data(parm.evalAsRamp())
        self.panel.gradient_model.add_user_gradient(
            dialog.name or node.name(), dialog.categories, ramp_data,
            tags=dialog.tags
        )
        if dialog.categories:
            self.panel.gradient_categories_model.check_add_category(    # emits its own row-insert signals
                dialog.categories)

    @classmethod
    def save_rank(cls, nodes) -> int:
        return 2


SECTION_INDEX = {cls.key: cls for cls in (    # the registry keyed for lookup; a new section is a class here and a line in section_list
    MaterialSection, GradientSection, CopSection, CodeSection, FileSection)}

SECTION_CLASSES = tuple(SECTION_INDEX[key] for key in section_list.keys())    # in tab order, which section_list holds


def drop_rule(section, panel, index):
    """The rule this row declares, or None: DROP, or DROP_BY_KIND picked by the row's KindRole."""
    if section is None:
        return None
    by_kind = getattr(section, "DROP_BY_KIND", None)
    if by_kind:
        kind = index.data(panel.file_files_model.KindRole) or ""
        return by_kind.get(kind)
    return getattr(section, "DROP", None)


def drop_handler(section, name):
    """The bound method a DropRule names, always the section's own; an unknown name raises."""
    return getattr(section, name)


def save_guess(keys, nodes, prefer: str = "") -> str:
    """Which of `keys` the save dialog preselects for `nodes`. ▸p/save-section-row"""
    if prefer in keys:    # a drop onto the open section means that section
        return prefer
    return min(keys, key=lambda key: SECTION_INDEX[key].save_rank(nodes))


def build_sections(panel) -> dict:
    """Instantiate every section against a constructed panel."""
    return {cls.key: cls(panel) for cls in SECTION_CLASSES}
