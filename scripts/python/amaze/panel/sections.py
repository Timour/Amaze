"""One Section per library tab, like a small node type: it says how its section drives the panel's shared widgets, so a new section is a new class here rather than edits to a dozen handlers. Archetypes, hooks, and the DropRule/MenuEntry fields ▸o/section-api"""

from __future__ import annotations

import collections
import os

import hou
from PySide6 import QtCore, QtWidgets

from amaze.core import (debug, dragengine, file_library, grid_columns, packages,
                        scene_captures, notes)
from amaze.dialogs import code_dialog
from amaze.helpers import helpers, hostos, ui_helpers
from amaze.panel import grid


AssetStack = collections.namedtuple(
    "AssetStack", "model proxy selection categories")

CommentSubject = collections.namedtuple(
    "CommentSubject", "key section name type category colour",
    defaults=("", ""),
)

FileLocation = collections.namedtuple(
    "FileLocation", "path label colour")

DropRule = collections.namedtuple(
    "DropRule",
    "on_node on_space resolve outside click_on_node click_resolve "
    "carrier_type",
    defaults=(None, None, None, None, None, None, ""),
)


MenuEntry = collections.namedtuple(
    "MenuEntry",
    "label verb needs shown children count_suffix checkable",
    defaults=("", "any", "", "", False, ""),
)

SEPARATOR = MenuEntry("")  # the empty label is what makes it a divider

GRID_MENU_TAIL = (
    MenuEntry("Update Preview", verb="menu_update_preview",
              shown="menu_offers_preview"),
    MenuEntry("Customize", verb="menu_customize"),
    MenuEntry("Favorite", verb="menu_favourite"),
    MenuEntry("Export Package", verb="menu_export_package"),
    MenuEntry("Delete", verb="menu_delete", shown="deletes_rows"),
)


class Section:
    """Base protocol: constructed with the panel, reads the panel's already-built models by attribute NAME. Every hook and declaration below ▸o/section-api"""

    key = ""
    label = ""            # the tab's human label; the ONE (key, label) list

    takes_comments = True    # a comment needs a library asset; online has none
    takes_favourites = True  # online rows answer False, so the star empties it
    takes_filter_menu = True  # the entries describe the LOCAL section under it
    takes_capture = False    # Capture acts on the open SCENE

    empty_noun = "items"  # what the shared empty-state blanks call these
    EMPTY: dict = {}      # `nothing-yet`: (headline, sentence, button, verb)

    sidebar_attr = ""
    delegate_attr = ""
    library_model_attrs: tuple = ()  # re-pointed on a library switch; () is real
    selection_attr = ""   # a menu acts on THIS section's selection
    activate_method = ""  # panel method pointing the widgets at these models
    GRID_MENU: tuple = ()     # MenuEntry rows; empty = no menu opens
    SIDEBAR_MENU: tuple = ()  # same shape, same builder
    DROP = None           # one DropRule, or None for a section that never drags
    DROP_BY_KIND: dict = {}  # File declares per row KIND; non-empty wins over DROP

    carrier_type = ""     # what the space door creates, when that is a constant
    carrier_type_verb = ""  # names a method instead, where it is not
    search_hint = ""      # per-ARCHETYPE: the archetype decides what is MATCHED
    FILTER_CHOICES: tuple = ()  # ((label, value), ...) after the everything-entry
    ALL_LABEL = "All"     # the everything-entry, and the stale-choice fallback
    filter_tooltip = ""   # per SECTION: what the menu narrows by

    def __init__(self, panel) -> None:
        self.panel = panel

    def activate(self) -> None:
        getattr(self.panel, self.activate_method)()

    def rc_menu(self) -> None:
        """Build and exec this section's grid right-click menu: ONE builder over GRID_MENU."""
        grid.open_grid_menu(self.panel, self)

    def grid_selection(self) -> list:
        """This section's grid selection as ITS OWN proxy's indexes, ONE per row - a menu asks the SECTION, not the widget, so a test can drive one without switching to it."""
        return grid_columns.selected_rows(self._p(self.selection_attr))

    def tile_models(self):
        """(model, proxy) for the tile a menu is acting on - what the shared Customize handler needs."""
        return None, None

    def catlist_menu(self) -> None:
        """Build and exec this section's sidebar right-click menu, over SIDEBAR_MENU."""
        grid.open_catlist_menu(self.panel, self)

    def sidebar_selection(self) -> list:
        """The Sidebar's selected rows; its selection lives on the shared `cat_list`, which has no per-section selection model as the Grid does."""
        cat_list = getattr(self.panel, "cat_list", None)
        if cat_list is None:
            return []
        return list(cat_list.selectedIndexes())

    def edit_dialog(self) -> None:
        """Open this section's edit dialog, if it has one - a section owns its dialog like it owns its menu. Default: none."""
        pass

    def prefs_changed(self) -> None:
        """Preferences just closed: a section showing live filesystem or render state re-scans here. Default: nothing."""
        pass

    def save_node(self, node) -> None:
        """A scene node was handed in while this section is active; each section routes to its own save flow so the right dialog opens."""
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(
                "This section browses files on disk - a scene node can't "
                "be saved into it. Switch to Material, Color, Node or "
                "Code first."
            )

    def stack(self):
        """The AssetStack for the curated machinery, or None for sections that do not use it."""
        return None

    def menu_export_package(self, indexes, current, payload=None) -> None:
        """ASK half of the grid export: the panel picks the destination, `export_package_to` does the work - headless tests drive that door directly."""
        path = self.panel.ask_package_destination()
        if path:
            self.export_package_to(list(indexes), path)

    def filter_text(self, text: str) -> None:
        pass

    def filter_favorites(self, on: bool) -> None:
        pass

    def filter_entries(self) -> tuple:
        """((label, value), ...) for the Filter menu, everything-entry first; its value is None, which every apply_filter reads as REMOVE the filter rather than a sentinel accepting every row."""
        if not self.FILTER_CHOICES:
            return ()
        return ((self.ALL_LABEL, None),) + tuple(self.FILTER_CHOICES)

    def apply_filter(self, value) -> None:
        """Narrow this section to one Filter-menu value; the panel owns the menu and this owns what an entry MEANS, which is how five sections share one button over five unrelated dimensions."""
        pass

    def select_category(self, index) -> None:
        pass

    reorders_sidebar = False  # the five below are the CATEGORY form; File overrides

    def _sidebar_categories(self):
        """(proxy, source Categories) behind this context's sidebar, or (None, None) where the sidebar is not that shape."""
        proxy = self._p(self.sidebar_attr)
        source = getattr(proxy, "sourceModel", lambda: None)()
        if source is None or not hasattr(source, "move_category"):
            return None, None
        return proxy, source

    def sidebar_movable(self, index) -> bool:
        """May THIS row be picked up? Everything below All may."""
        if not self.reorders_sidebar:
            return False
        if index is None or not index.isValid() or index.row() < 1:
            return False
        proxy, source = self._sidebar_categories()
        if proxy is None:
            return False
        raw = proxy.index(index.row(), 0).data(source.CatSortRole)
        return bool(raw) and raw != "_All"

    def move_sidebar_row(self, index, to_view_row: int) -> bool:
        """Move the row at `index` to VIEW row `to_view_row`, never above All - clamped, so a drag past the top parks the row at row 1 rather than refusing to follow the hand."""
        proxy, source = self._sidebar_categories()
        if proxy is None or index is None or not index.isValid():
            return False
        to_view_row = max(1, min(int(to_view_row), proxy.rowCount() - 1))
        from_source = proxy.mapToSource(
            proxy.index(index.row(), 0)).row()
        to_source = proxy.mapToSource(
            proxy.index(to_view_row, 0)).row()
        return source.move_category(from_source, to_source)

    def sidebar_order_snapshot(self):
        """The order before the gesture - what Esc puts back."""
        _proxy, source = self._sidebar_categories()
        return None if source is None else source.order_snapshot()

    def restore_sidebar_order(self, snapshot) -> None:
        _proxy, source = self._sidebar_categories()
        if source is not None and snapshot is not None:
            source.restore_order(snapshot)

    def commit_sidebar_order(self) -> None:
        """One write per gesture, on release."""
        _proxy, source = self._sidebar_categories()
        if source is not None:
            source.save()

    def double_click(self, index) -> None:
        pass

    deletes_rows = False  # File says no: its rows are files it only browses

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        """What deleting `count` rows costs in this section's terms - a material's files, a node asset's networks, a snippet's applied code, a palette's applied ramps - and it names the COUNT, because `the selected material(s)` never told anyone how many. `name` is the single row's display name, quoted by the one section whose approved copy asks for it (the UI text register is the source for every user-facing string). STATIC on purpose: depending on nothing but the count is what makes the four sentences readable side by side and testable without building a panel."""
        return ""

    def delete_rows(self, indexes) -> None:
        """Remove these SOURCE rows, HIGHEST FIRST - a removal shifts every row below it, so ascending order deletes neighbours. Never wrap a structural removal in layoutAboutToBeChanged/layoutChanged: that hands the proxy dangling persistent indexes and segfaults natively."""

    colour_title = "Category Color"  # the colour picker's title, the one place

    def menu_set_colour(self, indexes, current, payload=None) -> None:
        self.panel.sidebar_set_colour(True)  # both entries, the panel's ONE gesture

    def menu_clear_colour(self, indexes, current, payload=None) -> None:
        self.panel.sidebar_set_colour(False)

    takes_category_drops = False  # a tile dropped on a row RECATEGORISES it. Only AssetSection sets it True: the File family keeps this default deliberately, because its sidebar lists filesystem FOLDERS, so a drop there would mean moving files on disk rather than changing metadata

    def accepts_category_drop(self, index, name: str) -> bool:
        """Is THIS row a legal drop target, beyond being a category? Asked after the shared rules (a real row, not "All")."""
        return True

    def sidebar_key(self, index) -> str:
        """What this row is KEYED by, never its label: a category shown "WIP" is stored "_WIP", and a location shows a custom name over the path it is keyed by."""
        return ""

    def sidebar_colour(self, name: str) -> str:
        """This row's colour, "" for none. `name` is the STORED name; a colour written under the displayed one is never read."""
        return ""

    def set_sidebar_colour(self, name: str, colour: str) -> None:
        """Colour one sidebar row, or clear it with "". The context writes its own store AND repaints its own models - the colour paints twice, on the row and on every tile filed under it."""

    def toggle_favourite(self, indexes) -> None:
        """Flip the star on every row in `indexes` (this section's own proxy indexes). Base: nothing to flip."""

    offers_preview_update = False  # False where a preview is DERIVED, not rendered

    def update_preview(self, indexes) -> None:
        """Re-render the thumbnail for every row in `indexes`."""

    def menu_offers_preview(self, indexes, current) -> bool:
        """Does THIS SELECTION have anything to re-render? A second question beside `offers_preview_update`, which answers for the SECTION with nothing selected; they agree everywhere but File."""
        return bool(self.offers_preview_update)

    def menu_update_preview(self, indexes, current, payload=None) -> None:
        self.panel.grid_update_preview(indexes)

    def menu_customize(self, indexes, current, payload=None) -> None:
        model, proxy = self.tile_models()
        if model is None or proxy is None:
            return
        self.panel.edit_tile_icon(model, proxy, indexes)

    def menu_favourite(self, indexes, current, payload=None) -> None:
        self.panel.grid_toggle_favourite(indexes)

    def menu_delete(self, indexes, current, payload=None) -> None:
        self.panel.grid_delete(indexes)

    def comment_subject(self, index):
        """A CommentSubject for `index`, or None to clear the pane - only this context can answer, since the index belongs to ITS proxy and every field comes from ITS roles."""
        return None

    def _p(self, attr):
        return getattr(self.panel, attr, None)


class AssetSection(Section):
    """Material, Node and Code: an AssetLibrary-family model + a Categories sidebar behind the MultiFilterProxyModel, differing only in which models they name and what a double-click does."""

    reorders_sidebar = True

    model_attr = ""
    proxy_attr = ""
    selection_attr = ""
    category_attr = ""
    sidebar_attr = ""   # the categories PROXY, not `category_attr` under it
    delegate_attr = ""
    search_hint = ""    # ":tag" is the only way to reach tags from this box

    def activate(self) -> None:
        """Point the four shared widgets at THIS section's models; the attributes above are the whole difference between sections. ▸o/section-api"""
        panel = self.panel
        sidebar = self._p(self.sidebar_attr)
        if panel.cat_list and sidebar is not None:
            panel.cat_list.setModel(sidebar)
        panel.bind_grid_views(self._p(self.proxy_attr),
                              self._p(self.selection_attr),
                              self._p(self.delegate_attr))
        panel.set_conversion_bar_visible(False)  # may be another section's
        panel.sync_list_columns()  # different section = different names

        selected_name = panel._select_default_sidebar_row(sidebar)  # the filter follows the row actually selected; the programmatic select fires no clicked()
        model = self._p(self.model_attr)
        proxy = self._p(self.proxy_attr)
        if model is not None and proxy is not None:
            proxy.setFilter(
                model.CategoryRole,
                "" if selected_name in (None, "All", "_All")
                else selected_name,
            )

    takes_category_drops = True

    SIDEBAR_MENU = (  # the spine shared by Material, Node and Code. Rename acts on ONE category and greys beside the others, which act on the whole selection
        MenuEntry("Add Category", verb="menu_add_category",
                  needs="always"),
        MenuEntry("Rename", verb="menu_rename_category", needs="one"),
        MenuEntry("Remove", verb="menu_remove_category"),
        SEPARATOR,
        MenuEntry("Set Color", verb="menu_set_colour"),
        MenuEntry("Clear Color", verb="menu_clear_colour"),
        SEPARATOR,
        MenuEntry("Export Category", verb="menu_export_category",
                  needs="one"),
    )

    def menu_add_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        name = self.panel.ask_category_name("Add Category")
        if st is None or not name:
            return
        st.categories.check_add_category(name)    # NO relayout wrapper: this announces itself with begin/endInsertRows and pairing the two segfaults H21 (research.md, measured 2026-08-04), the same hoist panel.assign_category_active carries

    def menu_rename_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        new_name = self.panel.ask_category_name("Rename Category")
        if st is None or not new_name:
            return
        with ui_helpers.relayout(st.model, st.categories):
            for index in indexes:
                name = self.sidebar_key(index)    # the STORED name: the sidebar strips a leading underscore for display, so renaming "_WIP" by its label matches no asset and no entry and silently does nothing
                if not name or name in ("All", "_All"):
                    continue
                st.model.rename_category(name, new_name)
                st.categories.rename_category(name, new_name)
            st.model.save()
        self._refilter_from_sidebar()    # the rename rewrites every asset and the sidebar row, leaving the proxy narrowed to a name nothing carries any more: without this the row reads correctly, stays highlighted, and the grid is permanently empty with nothing said until another row is clicked. Through the ONE route a sidebar click uses, never a second place that knows how a category becomes a filter

    def export_package_to(self, indexes, path: str) -> int:
        """ACT half: the selected rows (proxy indexes) leave as one `.amazepkg` - record, existing family files and note per asset - answering the entry count."""
        st = self.stack()
        if st is None:
            return 0
        items = []
        for index in indexes:
            if index is None or not index.isValid():
                continue
            source = (st.proxy.mapToSource(index)
                      if st.proxy is not None else index)
            asset = st.model.assets[source.row()]
            items.append(packages.collect_asset(st.model, asset.mat_id))
        if not items:
            return 0
        return packages.write_package(path, items)

    def export_category_to(self, category, path: str) -> int:
        """ACT half of the sidebar export: every asset carrying `category` (None means the whole section) leaves as one package."""
        st = self.stack()
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

    def menu_export_category(self, indexes, current, payload=None) -> None:
        """ASK half: the clicked sidebar row names the category (All exports the whole section), the panel picks the destination."""
        name = self.sidebar_key(current) if current is not None else None
        if name in ("All", "_All", ""):
            name = None
        path = self.panel.ask_package_destination()
        if path:
            self.export_category_to(name, path)

    def _refilter_from_sidebar(self) -> None:
        """Point the grid at whatever the sidebar is standing on now: both category verbs change what the current row MEANS, and the proxy holds the value it was given when the row was clicked."""
        cat_list = getattr(self.panel, "cat_list", None)
        if cat_list is None:
            return
        current = cat_list.currentIndex()
        if current.isValid():
            self.select_category(current)

    def menu_remove_category(self, indexes, current, payload=None) -> None:
        st = self.stack()
        if st is None:
            return
        names = []    # STORED names, same reason as the rename above: remove_category returns early on its own `cat not in self._categories` guard, so removing by the label leaves the row exactly where it was
        for index in indexes:
            name = self.sidebar_key(index)
            if name and name not in ("All", "_All"):
                names.append(name)
        if not names:
            return
        if st.selection is not None:
            st.selection.clearSelection()
        with ui_helpers.relayout(st.model):
            for name in names:
                st.model.remove_category(name)
            st.model.save()
        for name in names:
            st.categories.remove_category(name)    # OUTSIDE the relayout wrapper: this announces itself with begin/endRemoveRows and pairing the two segfaults H21 (research.md, measured 2026-08-04). The asset rows changed inside the wrapper; the sidebar rows change here, bracketed by their own signals
        self.panel._ensure_sidebar_selection(self.key)    # the row is gone and the filter is not: without this the grid stays narrowed to a category that no longer exists - zero tiles, nothing highlighted, no message - because the sidebar must never sit with an empty selection
        self._refilter_from_sidebar()    # covers the case where the fallback lands somewhere other than All

    def tile_models(self):
        st = self.stack()
        return ((st.model, st.proxy) if st is not None
                else (None, None))

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
        st = self.stack()
        if st is None:
            return
        for index in indexes:
            source = st.proxy.mapToSource(index)
            if source.isValid():
                st.model.toggle_fav(source.row())

    deletes_rows = True

    def delete_rows(self, indexes) -> None:
        st = self.stack()
        if st is None:
            return
        model = st.model
        for index in sorted(indexes, key=lambda i: i.row(), reverse=True):
            model.remove_asset(index)
        self.panel._refresh_sidebar_categories()

    def sidebar_key(self, index) -> str:
        return self.panel._raw_category_name(index)    # the ONE reader of a category row's stored name; the underscore strip lives in Categories.data

    def sidebar_colour(self, name: str) -> str:
        st = self.stack()
        if st is None:
            return ""
        return st.categories.color_of(name)

    def set_sidebar_colour(self, name: str, colour: str) -> None:
        st = self.stack()
        if st is None:
            return
        st.categories.set_color(name, colour)
        if st.model is not None and st.model.rowCount():    # the grid reads the colour through a role on the ASSET model, which shares the category model's data dict, so a repaint is all that is needed - role-scoped, because a roles-less emit over every row sends the list view into an O(rows) column re-measure that a colour can never change, which the panel's own tripwire logs as a "column re-measure storm"
            st.model.dataChanged.emit(
                st.model.index(0, 0), st.model.index(st.model.rowCount() - 1, 0),
                [st.model.CategoryColorRole])

    offers_preview_update = True

    def update_preview(self, indexes) -> None:
        st = self.stack()    # Materials and Nodes re-render, the UI blocking for it, while Code repaints from content - all three reach it the same way, which is what stops Code being the one that forgot
        if st is None:
            return
        sources = (st.proxy.mapToSource(i) for i in indexes)
        rows = [source.row() for source in sources if source.isValid()]
        if not rows:
            return
        st.model.render_thumbnails(rows)    # ONE Karma scaffold for the whole selection: the stage composition is identical per material, so a per-row call pays it again for every tile (core/library.py > render_thumbnails)

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
        categories = source.data(st.model.CategoryRole)  # a LIST; the header has room for one, and the first is the one the sidebar sorts it under
        if isinstance(categories, (list, tuple)):
            category = str(categories[0]) if categories else ""
        else:
            category = str(categories or "")
        return CommentSubject(
            key=notes.note_key(st.model.NOTES_SECTION, asset_id),  # the MODEL's store name, not this class's key: three sections share these models
            section=self.label.lower(),
            name=source.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
            type=source.data(st.model.RendererLabelRole) or "",
            category=category,
            colour=str(source.data(st.model.CategoryColorRole) or ""),
        )

    def filter_text(self, text: str) -> None:
        st = self.stack()
        if st is None:
            return
        if text.startswith(":"):    # NEITHER invalidate() NOR sort() around these calls: setFilter/removeFilter invalidate the proxy and re-sort inside GridProxyModel.refilter(), which is the whole reason that method exists (core/grid_proxy.py), so a caller-side pair runs the filter pass 2-3x and sorts every row twice per keystroke
            st.proxy.removeFilter(QtCore.Qt.ItemDataRole.DisplayRole)    # ":tag" searches the TagRole instead of the name
            if len(text) > 1:
                st.proxy.setFilter(st.model.TagRole, text[1:])
            else:
                st.proxy.removeFilter(st.model.TagRole)    # a BARE COLON is a tag search with no tag yet, so it must narrow nothing; falling through here instead leaves the grid on the previous tag while the box shows only a colon, which is what backspacing a tag search one character at a time does
        else:
            st.proxy.removeFilter(st.model.TagRole)
            st.proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, text)

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
            st.proxy.removeFilter(st.model.RendererRole)    # REMOVE, never an accept-all value: a stored filter costs an index.data() per row forever and blocks the proxy's no-filters fast path
        else:
            st.proxy.setFilter(st.model.RendererRole, value)    # all three asset sections keep their kind in this one field - renderer for Materials, saved-from context for Nodes, language for Code - and MultiFilterProxyModel matches hard-coded role NUMBERS, silently ignoring a filter set on any other role
        st.categories.set_renderer_filter(value or "")    # the sidebar too, or a category of three hidden LOP setups still reads "MyCat (3)" and opens empty; the PROXY's value and never the menu's label, because Categories lowercases what it is given and substring-matches it, so "All" matches no renderer at all and "" is the honest mirror of what the grid does with it
        self.panel._refresh_sidebar_categories()
        self.panel._ensure_sidebar_selection(self.key)

    def select_category(self, index) -> None:
        """Narrow the grid to the clicked row's category, always by the STORED name."""
        st = self.stack()
        if st is None:
            return
        stored = self.panel._raw_category_name(index)    # the one home for this question, never index.data(): Categories.data returns elem[1:] for DisplayRole on a leading "_" - the mechanism that sorts the stored _All first and reads it as "All" - so a category stored _WIP displays "WIP", which no asset carries, and the grid empties under a still-highlighted row
        st.proxy.setFilter(st.model.CategoryRole,
                        "" if stored in ("All", "_All") else stored)    # "" keeps _All meaning everything rather than a literal category nobody has


class MaterialSection(AssetSection):
    key = "material"
    label = "Material"
    empty_noun = "material"
    EMPTY = {    # no button: save_asset needs a selected node and says so when there is none, which is the normal state on an empty library
        "nothing-yet": (
            "No materials saved yet",
            "Right-click a material in the network editor and choose "
            "Save to Amaze. It is kept here, ready to drag back into "
            "any scene.",
            "", ""),
    }

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this material? Its saved files and "
                    "thumbnails go for good. Materials already used in "
                    "a scene are not affected.")
        return ("Delete %d materials? Their saved files and thumbnails "
                "go for good. Materials already used in a scene are "
                "not affected." % count)

    GRID_MENU = (    # Info, the section's work, a divider, then the shared tail; Convert to Karma is the one CONDITIONAL entry, built only when the selection holds a Redshift material, and the builder dispatches through a dict rather than comparing the returned action - a dismissed menu and an unbuilt entry are both None, so a comparison runs the converter on every dismissed right-click
        MenuEntry("Info", verb="menu_info", needs="one"),
        MenuEntry("Copy To", verb="menu_copy_to", children="copy_to_targets"),
        MenuEntry("Convert to Karma", verb="menu_convert_to_karma",
                  shown="selection_has_redshift"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    DROP = DropRule(resolve="drop_material_at_release",    # a material import finds its own landing: the verb checks the release for a material library node or a network itself
                    click_resolve="click_import_material")

    def click_import_material(self, _index) -> bool:
        """Materials aim themselves - the context-aware import reads the selection and the network under the cursor."""
        self.panel.import_asset("auto")
        return True

    def drop_material_at_release(self, index) -> bool:
        """Land a released material drag where it was dropped, nothing having been created before this moment: LOP viewport gets the ancestor-prim menu and an import into a materiallibrary in THAT stage, never /mat; OBJ viewport imports to /mat and assigns to the picked object; a network editor imports into the network under the cursor; anything else is a silent miss. Returns True for a hit, False for a miss, and "menu" when a menu carried the interaction, which the drag widgets map to the outcome icon."""
        panel = self.panel
        if not panel.material_model or index is None or not index.isValid():
            return False
        ids = panel._selected_material_ids(index)
        target = dragengine.viewport_release_target(panel)
        if target is not None:
            kind, viewer, data = target
            debug.event("drag", "material release", target=kind,
                        data=str(data), count=len(ids))
            if kind == "lop":
                if not data:
                    return False    # empty viewport space: no prim picked is a MISS, not an import offer
                shown = panel._material_lop_viewport_drop(ids, viewer, data)
                return "menu" if shown is not False else False    # the menu IS the feedback here, no outcome icon on top of it whether chosen or dismissed - but only when one was SHOWN, because _finish_preview reads "menu" as "suppress the miss icon" and the call returns False in three cases where none ever appeared: no stock LOP helper, a viewer whose pwd() failed, and no choices at all off a stale prim path or a display node whose cook failed
            if kind == "obj" and data is not None:
                with hou.undos.group("Amaze Assign Material"), \
                        dragengine.keep_editor_focus():
                    return bool(panel.assign_material_to_obj(ids, data))    # propagated, never a hard True: the call returns False when the picked object has no shop_materialpath, and success feedback for an assignment that did not happen is a lie
            return False
        context = panel._drop_context_under_cursor("materiallibrary")
        if context is None:
            debug.event("drag", "material release", target="miss")
            return False
        debug.event("drag", "material release", target="network",
                    context=context.path(), count=len(ids))
        position = panel._release_position_in(context)
        panel._import_materials_into_context(context, ids, position)
        return True

    def selection_has_redshift(self, indexes, current) -> bool:
        return self.panel._selection_has_redshift()

    def copy_to_targets(self, indexes, current) -> tuple:
        """WHERE the saved material lands; the entries name the destination the way Houdini writes the PATH - /stage, not the Solaris marketing name."""
        return (("/mat", "mat", "", True),
                ("/stage", "lop", "", True))

    def menu_info(self, indexes, current, payload=None) -> None:
        self.edit_dialog()    # through the Section API's own hook for it, never past it into the panel

    def menu_copy_to(self, indexes, current, payload=None) -> None:
        with helpers.preserving_selection_and_current():    # a menu import leaves the artist where they were, like a drop; the drag and click dispatchers wrap, the menu dispatcher does not, so the scene-importing verbs carry it themselves
            if payload == "lop":
                self.panel.import_asset_to_lop()
            else:
                self.panel.import_asset_to_mat()

    def menu_convert_to_karma(self, indexes, current, payload=None) -> None:
        self.panel.convert_selected_to_karma()

    def activate(self) -> None:
        if getattr(self.panel, "online_mode", False):  # Materials alone remembers the online world: a tab round-trip must not drop out of it
            self.panel.enter_online()
            return
        super().activate()

    library_model_attrs = ("material_model", "category_model")
    model_attr = "material_model"
    proxy_attr = "material_sorted_model"
    selection_attr = "material_selection_model"
    category_attr = "category_model"
    sidebar_attr = "category_sorted_model"
    delegate_attr = "thumb_delegate"
    filter_tooltip = "Show materials for one renderer."

    RENDERER_PREFS = (    # (label, the preference deciding whether it is offered); the labels are also the VALUES, matched against the renderer string stored on the material, so the two cannot drift
        ("Karma", "renderer_matx_enabled"),
        ("Redshift", "renderer_redshift_enabled"),
        ("Octane", "renderer_octane_enabled"),
    )

    def filter_entries(self) -> tuple:
        prefs = self.panel.prefs    # the only section whose entries are not a constant: a renderer switched off in Preferences is not offered here. Rebuilt rather than shown and hidden, so there is one mechanism, and the panel's own fallback to All covers a remembered choice no longer on offer, in every section rather than only this one
        return ((self.ALL_LABEL, None),) + tuple(
            (label, label) for label, flag in self.RENDERER_PREFS
            if getattr(prefs, flag, False)
        )

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)

    def edit_dialog(self) -> None:
        self.panel.edit_material_info()

    def save_node(self, node) -> None:
        self.panel.save_asset()    # materials support multi-selection saves, so the flow is selection-based and the drop handler selects the node first


class CopSection(AssetSection):
    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this node asset? Its saved files and "
                    "thumbnail go for good. Networks already built in "
                    "a scene are not affected.")
        return ("Delete %d node assets? Their saved files and "
                "thumbnails go for good. Networks already built in a "
                "scene are not affected." % count)

    key = "cop"
    label = "Node"
    empty_noun = "node asset"
    EMPTY = {    # no button, for the same reason as Material
        "nothing-yet": (
            "No node assets saved yet",
            "Select nodes in a network, right-click and choose Save to "
            "Amaze. The whole network is kept, ready to build back in.",
            "", ""),
    }
    GRID_MENU = (    # the material menu's essentials without the renderer-specific entries (Copy To targets, Karma conversion) that mean nothing for a saved network; LOAD rather than Import, matching the File section's word for "bring the saved thing into Houdini", but live on a multi-selection because any number of networks can be built
        MenuEntry("Load", verb="menu_load"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    DROP = DropRule(resolve="drop_cop_at_release",    # a saved network builds where the context allows, so the verb resolves the destination itself
                    click_resolve="click_import_cop")

    def click_import_cop(self, _index) -> bool:
        self.panel.import_cop_assets()
        return True

    def drop_cop_at_release(self, index) -> bool:
        """Nodes drag released: the same context rules as double-click, but against the network editor under the RELEASE POINT - released ON a network container (a geo, a copnet, a lopnet...) or INSIDE one, the saved nodes load directly into it, and any other network gets a fresh container. An asset whose context doesn't match where it landed is refused with a message rather than half created, and a release over nothing is silent, a miss being a normal drag outcome rather than an error."""
        panel = self.panel
        if not panel.cop_model:
            return False
        if index is None or not index.isValid():
            return False    # a drag armed on EMPTY grid space arrives with an invalid index, and mapToSource() would return row -1, which Python-indexes to the LAST asset in the model
        context = panel._drop_context_under_cursor(
            panel.cop_model.is_container)
        if context is None:
            return False
        try:
            source_index = panel.cop_sorted_model.mapToSource(index)
        except Exception:
            return False
        with hou.undos.group("Amaze Import COP Network"):
            ok, reason, created = panel.cop_model.import_asset_to_scene(
                source_index, context_node=context
            )
        if not ok and reason:
            debug.refuse(reason, net=context.path())    # the door marks library damage, which is what picks the dialog over the status line ▸p/refusal-sink
        if ok:
            helpers.place_nodes(created,
                                panel._release_position_in(context))
        return True

    def menu_load(self, indexes, current, payload=None) -> None:
        with helpers.preserving_selection_and_current():    # same wrapper as menu_copy_to: a menu import must not move the artist's selection, current node or view
            self.panel.import_cop_assets()
    library_model_attrs = ("cop_model", "cop_category_model")
    model_attr = "cop_model"
    proxy_attr = "cop_sorted_model"
    selection_attr = "cop_selection_model"
    category_attr = "cop_category_model"
    sidebar_attr = "cop_category_sorted_model"
    delegate_attr = "asset_delegate"    # NOT thumb_delegate: Node and Code have no versions, and that shared delegate paints a "Version" column reading "none" on every row
    filter_tooltip = "Show setups saved from one context."

    FILTER_CHOICES = (    # the contexts this section saves, spelled the way Houdini's own network tabs do; CopLibrary.SAVE_CONTEXTS is the same list in Houdini's capitalisation and the match is case-insensitive, so these can read as the user sees them on the node itself. An asset saved before the section learned about contexts carries an empty one and appears under All only - there is nothing truthful to file it under
        ("SOP", "Sop"),
        ("COP", "Cop"),
        ("LOP", "Lop"),
        ("DOP", "Dop"),
        ("TOP", "Top"),
        ("CHOP", "Chop"),
        ("Object", "Object"),
    )

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)

    def save_node(self, node) -> None:
        self.panel.save_cop_from_node(node)


class CodeSection(AssetSection):
    """Saved code snippets, each tagged with a language the Filter menu narrows by, previewed as rendered text rather than a render."""

    offers_preview_update = False    # NO Update Preview, as in Color: this preview is DERIVED, and _preview_key is content-addressed - ("code", id, hash(code), language) - so an edited snippet mints a new key and repaints itself, while a re-render would repaint the same text to the same image

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:
            return ("Delete this snippet? It goes for good. Code "
                    "already applied to a node is not affected.")
        return ("Delete %d snippets? They go for good. Code already "
                "applied to a node is not affected." % count)

    def delete_rows(self, indexes) -> None:
        super().delete_rows(indexes)
        self.panel.code_model.save()    # remove_asset already saves per row like every sibling; this is the belt on the braces for a store keeping every snippet in ONE json, where a half-written removal loses more than one row

    key = "code"
    label = "Code"
    empty_noun = "snippet"
    EMPTY = {    # a button here because New File acts on NOTHING and so always works, the same reason its menu entry stays live over an empty selection
        "nothing-yet": (
            "No snippets yet",
            "Right-click a wrangle and choose Save to Amaze to keep its "
            "code — or start one here and paste into it.",
            "New File", "new_code_snippet"),
    }
    GRID_MENU = (    # Apply and Edit act on one snippet and grey out beside New File, which acts on nothing and stays live; no Update Preview, per offers_preview_update above
        MenuEntry("New File", verb="menu_new_snippet", needs="always"),
        SEPARATOR,
        MenuEntry("Apply", verb="menu_apply", needs="one"),
        MenuEntry("Edit", verb="menu_edit", needs="one"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    DROP = DropRule(on_node="drop_code_at_release",    # a snippet hands to the node under the release; on empty network space the carrier wrangle is created where supported
                    on_space="create_code_node_in",
                    click_on_node="drop_code_at_release")

    carrier_type_verb = "code_carrier_type"    # per language AND per network kind, so the answer is a method

    CODE_CARRIERS = {    # what this section creates per language and per network kind, names from the shipped manual; a pair absent here, or a type this Houdini does not carry, refuses
        "vex": {"Sop": "attribwrangle", "Lop": "attribwrangle",
                "Cop": "wrangle"},
        "opencl": {"Sop": "opencl", "Cop": "opencl"},
        "python": {"Sop": "python"},
    }

    def code_carrier_type(self, index, dest) -> str:
        """WHICH carrier a snippet becomes in `dest` - a wrangle, an opencl, a python - or "" where this network kind has none. ONE ANSWER, TWO READERS: create_code_node_in builds it and the drag ghost draws its shape before the drop happens, so a ghost computing its own type could promise a wrangle and deliver nothing."""
        panel = self.panel
        if index is None or not index.isValid() or not panel.code_model:
            return ""
        source_index = panel.code_sorted_model.mapToSource(index)
        row = source_index.row()
        if not 0 <= row < len(panel.code_model.assets) or dest is None:
            return ""
        asset = panel.code_model.assets[row]
        language = str(getattr(asset, "renderer", "") or "").lower()
        try:
            category = dest.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return ""
        return self.CODE_CARRIERS.get(language, {}).get(
            category.name() if category is not None else "", "")

    def create_code_node_in(self, index, dest, position=None) -> bool:
        """The code creation rule: the language's own carrier - a wrangle, an opencl, a python - wherever the network kind has one, loaded through the same apply the node drop uses."""
        panel = self.panel
        if index is None or not index.isValid() or not panel.code_model:
            return False
        source_index = panel.code_sorted_model.mapToSource(index)
        row = source_index.row()
        if not 0 <= row < len(panel.code_model.assets):
            return False
        asset = panel.code_model.assets[row]
        type_name = self.code_carrier_type(index, dest)
        if not type_name:
            return False
        name = helpers.sanitize_usd_path(
            str(getattr(asset, "name", "") or "")) or "snippet"
        with hou.undos.group("Amaze Create Code Node"):
            node = panel._create_carrier(dest, type_name, name, position)
            if node is None:
                return False
            ok, _reason = panel.code_model.apply_to_node(row, node)
            if not ok:
                node.destroy()
                return False
        return True

    def drop_code_at_release(self, index, node: hou.Node) -> bool:
        """Code snippet drag released (self-managed): apply the snippet to the node under the cursor - the same as a double-click, but targeting where the drag landed. A release over nothing is silent, and a node with no code/snippet parm reports why."""
        panel = self.panel
        if not panel.code_model or index is None or node is None:
            return False
        try:
            source_index = panel.code_sorted_model.mapToSource(index)
        except Exception:
            return False
        with hou.undos.group("Amaze Apply Code Snippet"):
            ok, reason = panel.code_model.apply_to_node(
                source_index.row(), node
            )
        if not ok:
            if reason:
                debug.refuse(reason)    # drag-door rule: the miss indicator carries the refusal and the reason goes to the status line ▸p/refusal-sink
            return False
        return True

    def menu_new_snippet(self, indexes, current, payload=None) -> None:
        self.panel.new_code_snippet()

    def menu_apply(self, indexes, current, payload=None) -> None:
        self.panel.click_on_row(self, current)    # THE CLICK DOOR, never a second reading of the same policy: a body of its own vetoes on a selected node with no snippet parm, where the double-click beside it falls through to the creation walk

    def menu_edit(self, indexes, current, payload=None) -> None:
        if current is None or not current.isValid():
            return
        source = self.panel.code_sorted_model.mapToSource(current)
        if source.isValid():
            self._edit_code_row(source.row())

    def _edit_code_row(self, row: int) -> None:
        panel = self.panel
        asset = panel.code_model.assets[row]
        dialog = code_dialog.CodeDialog(
            panel.get_code_category_names(),
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
            panel.code_category_model.check_add_category(dialog.category)
        with ui_helpers.relayout(panel.code_model,
                                 panel.code_category_model):
            panel.code_model.update_asset(
                row, dialog.code, dialog.name, dialog.language,
                dialog.category, dialog.tags, dialog.description,
            )
        panel._refresh_sidebar_categories()
    library_model_attrs = ("code_model", "code_category_model")
    model_attr = "code_model"
    proxy_attr = "code_sorted_model"
    selection_attr = "code_selection_model"
    category_attr = "code_category_model"
    sidebar_attr = "code_category_sorted_model"
    delegate_attr = "asset_delegate"
    filter_tooltip = "Show snippets in one language."

    FILTER_CHOICES = (    # the same four code_dialog.LANGUAGES offers, "Code" being the catch-all; deliberately not imported from there, because this list is what the STORED strings are and a dialog is free to stop offering one while snippets saved under it are still in the library
        ("VEX", "VEX"),
        ("OpenCL", "OpenCL"),
        ("Python", "Python"),
        ("Code", "Code"),
    )

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)

    def save_node(self, node) -> None:
        self.panel.save_code_from_node(node)


class FolderSection(Section):
    """A folder-pointer list + a files model, filtered by TextureFilterProxyModel: selecting a folder browses its files, and there is no category machinery, so stack() is None. One shipped subclass since the merge, FileSection."""

    files_proxy_attr = ""
    folders_attr = ""
    files_attr = ""
    colour_pref_setter = ""    # prefs method that stores a location's colour
    last_folder_pref = ""
    selection_attr = ""    # the rest of what activate() varies on: the selection model and delegate to point the shared grid at, and the prefs list of registered folders behind last_folder_pref
    delegate_attr = ""
    folders_pref = ""
    search_hint = ""    # these tiles are files on disk with no tags and no categories, so the file name is genuinely all there is to match

    def filter_text(self, text: str) -> None:
        proxy = self._p(self.files_proxy_attr)
        if proxy is not None:
            proxy.set_name_filter(text)

    def filter_favorites(self, on: bool) -> None:
        proxy = self._p(self.files_proxy_attr)
        if proxy is not None:
            proxy.set_favorites_only(on)

    def apply_filter(self, value) -> None:
        proxy = self._p(self.files_proxy_attr)
        if proxy is not None:
            proxy.set_kind_filter(value)

    reorders_sidebar = True    # the sidebar reorder contract in FOLDER terms: same gesture and same one-write-on-release rule as the category form, but the rows are registered locations whose truth moves through FolderListModel's named prefs calls, and the order is this machine's own (locations.py ▸ the ORDER paragraph), so a reorder here never reshuffles another machine's sidebar

    def sidebar_movable(self, index) -> bool:
        model = self._p(self.sidebar_attr)
        if model is None or index is None or not index.isValid():
            return False
        return 1 <= index.row() <= len(model._folders())    # row 0 is the synthetic All row; everything below it is real

    def move_sidebar_row(self, index, to_view_row: int) -> bool:
        model = self._p(self.sidebar_attr)
        if model is None or index is None or not index.isValid():
            return False
        to_view_row = max(1, min(int(to_view_row), model.rowCount() - 1))
        return model.move_folder(index.row(), to_view_row)

    def sidebar_order_snapshot(self):
        model = self._p(self.sidebar_attr)
        return None if model is None else list(model._folders())

    def restore_sidebar_order(self, snapshot) -> None:
        model = self._p(self.sidebar_attr)
        if model is not None and snapshot is not None:
            model.restore_folder_order(snapshot)

    def commit_sidebar_order(self) -> None:
        from amaze.core import locations
        locations.commit_registered_order(self.panel.prefs)

    def activate(self) -> None:
        panel = self.panel
        folders = self._p(self.folders_attr)
        folders.refresh_counts()
        if panel.cat_list:
            panel.cat_list.setModel(folders)
        panel.bind_grid_views(self._p(self.files_proxy_attr),
                              self._p(self.selection_attr),
                              self._p(self.delegate_attr))
        panel.set_conversion_bar_visible(False)  # may be another section's
        panel.sync_list_columns()  # different section = different names

        registered = getattr(panel.prefs, self.folders_pref, []) or []
        target_row = 1 if folders.rowCount() > 1 else 0  # the first REAL folder, never "All": "All" eagerly scans and queues thumbnails for every registered folder at once
        last = getattr(panel.prefs, self.last_folder_pref, "")
        if last == folders.ALL_LABEL:
            target_row = 0
        elif last and last in registered:
            target_row = registered.index(last) + 1
        if panel.cat_list and folders.rowCount() > 0:
            target_index = folders.index(target_row, 0)
            selection_model = panel.cat_list.selectionModel()
            if selection_model is not None:
                selection_model.select(
                    target_index,
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect,
                )
                panel.cat_list.setCurrentIndex(target_index)
            panel.update_selected_cat()

    def _browse(self, path) -> None:
        """Point the files model at a folder path (None = the synthetic 'All' row), remember it, and persist."""
        files = self._p(self.files_attr)
        folders = self._p(self.folders_attr)
        if path is None:
            setattr(self.panel.prefs, self.last_folder_pref, folders.ALL_LABEL)
            files.set_all_folders()
        else:
            setattr(self.panel.prefs, self.last_folder_pref, path)
            files.set_folder(path)
        self.panel.prefs.save()

    def select_category(self, index) -> None:
        folders = self._p(self.folders_attr)
        self._browse(index.data(folders.PathRole))

    def location_for(self, path: str):
        """(location, label, colour) for the registered location covering this path - label per the location's own display rule (custom name, else the path), colour from Set Color. Longest prefix wins, because a location registered INSIDE another one is the more specific answer for a file under it."""
        folders = self._p(self.folders_attr)
        registered = getattr(self.panel.prefs, self.folders_pref, None) or ()
        canonical = hostos.canonical_path_key(path)
        best = ""
        best_len = 0
        for folder in registered:
            prefix = hostos.canonical_path_key(folder).rstrip("/") + "/"
            if canonical.startswith(prefix) and len(prefix) > best_len:    # both lengths are of the CANONICAL prefix: measure one against the raw folder and the longest-prefix rule compares two different strings, so a nested location can lose to its own parent purely on how canonicalising changed it
                best, best_len = folder, len(prefix)
        if not best or folders is None:
            return FileLocation(path="", label="", colour="")
        return FileLocation(path=best,    # display_name and folder_color are the folder model's, the one already answering both for the sidebar
                            label=folders.display_name(best),
                            colour=folders.folder_color(best))

    def tile_models(self):
        return self._p(self.files_attr), self._p(self.files_proxy_attr)

    def _files_and_rows(self, indexes):
        """The files model and the SOURCE rows behind proxy indexes - an index that no longer maps is dropped, and no models yet answers (None, []), so a caller loops over nothing rather than guarding twice."""
        files, proxy = self.tile_models()
        if files is None or proxy is None:
            return None, []
        sources = (proxy.mapToSource(index) for index in indexes)
        return files, [source.row() for source in sources if source.isValid()]

    def selected_kinds(self, indexes) -> set:
        """Every KIND in the selection, read once for the whole Grid menu - the one menu table whose entries depend on the kind of the rows in hand rather than on how many there are."""
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
                    & {file_library.KIND_IMAGE, file_library.KIND_GEO})

    def selection_has_scene(self, indexes, current) -> bool:
        return file_library.KIND_HIP in self.selected_kinds(indexes)

    def menu_offers_preview(self, indexes, current) -> bool:
        return (self.offers_preview_update    # a capture is hand-framed and only a new capture replaces it, and an OS icon has nothing to regenerate, so this section CAN re-render while a particular selection cannot
                and self.selection_has_importable(indexes, current))

    def menu_import_enabled(self, indexes, current) -> bool:
        """An image loads onto ONE node parameter, so images import one at a time; geometry imports the whole selection."""
        kinds = self.selected_kinds(indexes)
        return len(indexes) == 1 or kinds == {file_library.KIND_GEO}

    def menu_capture_enabled(self, indexes, current) -> bool:
        """Only the scene the VIEWPORT is showing can be captured, since the capture photographs the viewport and capturing while another scene is open files that picture under the wrong name - silently, and the result looks perfectly plausible. The SAME test the shared path makes and no more: an extra requirement here that Amaze opened the scene greys the tile out for a scene opened through File > Open, a recent-files entry or a crash recovery while the toolbar still offers it."""
        path = self._path_of(current)
        return (len(indexes) == 1 and bool(path)
                and path == scene_captures.current_scene_path())

    def menu_import(self, indexes, current, payload=None) -> None:
        files = self._p(self.files_attr)
        if files is None:
            return
        if self.selected_kinds(indexes) == {file_library.KIND_IMAGE}:
            self.panel.click_on_row(self, current)    # THE CLICK DOOR, same as a double-click on the row: a body of its own vetoes on a selected node with no file parm
            return
        for index in indexes:
            if index.data(files.KindRole) == file_library.KIND_GEO:
                self.panel.import_geo_asset(index)

    def menu_load_scene(self, indexes, current, payload=None) -> None:
        self.panel.open_hip_scene(current)

    def menu_copy_path(self, indexes, current, payload=None) -> None:
        self.panel.copy_file_paths(indexes)

    def menu_reveal(self, indexes, current, payload=None) -> None:
        path = self._path_of(current)
        if not path:
            return
        try:
            hostos.reveal_path(path)
        except Exception as exc:                         # noqa: BLE001
            debug.event("file", "reveal failed", error=str(exc))

    def menu_capture(self, indexes, current, payload=None) -> None:
        self.panel.capture_hip_thumbnail(current)

    def toggle_favourite(self, indexes) -> None:
        files, rows = self._files_and_rows(indexes)    # keyed by PATH here, so the model takes a row and resolves it itself - the same shape, a different key
        for row in rows:
            files.toggle_favorite(row)

    colour_title = "Location Color"

    def sidebar_key(self, index) -> str:
        folders = self._p(self.folders_attr)    # a location's key is its PATH; the row shows a custom name when one is set, so the label is not it
        if folders is None or index is None or not index.isValid():
            return ""
        return str(index.data(folders.PathRole) or "")

    def sidebar_colour(self, name: str) -> str:
        folders = self._p(self.folders_attr)    # `name` is a registered folder PATH here, the sidebar's key in this archetype, and the folder model already answers this for its own rows
        return folders.folder_color(name) if folders is not None else ""

    def set_sidebar_colour(self, name: str, colour: str) -> None:
        folders = self._p(self.folders_attr)
        files = self._p(self.files_attr)
        setter = getattr(self.panel.prefs, self.colour_pref_setter, None)
        if setter is None:
            return
        setter(name, colour)
        if folders is not None:
            row = folders.row_of(name)
            if row is not None:
                index = folders.index(row, 0)
                folders.dataChanged.emit(index, index)
        if files is not None and files.rowCount():    # every tile from that location repaints, role-scoped
            files.colours_changed()    # drop the paint-path colour cache BEFORE the repaint, which would otherwise re-fill it from the old answer
            files.dataChanged.emit(
                files.index(0, 0), files.index(files.rowCount() - 1, 0),
                [files.CategoryColorRole])

    offers_preview_update = True

    def update_preview(self, indexes) -> None:
        files, rows = self._files_and_rows(indexes)    # the files model re-renders a BATCH - image rows re-convert, scene rows re-read their capture - so the rows go over in one call rather than one at a time
        if rows:
            files.rerender_thumbnails(rows)

    def comment_subject(self, index):
        model, proxy = self.tile_models()    # a row here is a FILE, keyed by its PATH - which is what brings a comment back when the location is removed and registered again
        if model is None or proxy is None:
            return None
        source = proxy.mapToSource(index)
        if not source.isValid():
            return None
        path = model.file_key(source.row())
        if not path:
            return None
        location = self.location_for(path)
        return CommentSubject(
            key=notes.note_key(self.key, path),
            section=self.label.lower(),
            name=source.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
            type=source.data(model.FormatRole) or "",
            category=location.label,  # a file has no category; the header shows its LOCATION, in that location's colour
            colour=location.colour,
        )


class FileSection(FolderSection):
    """One folder list, EVERY file shown, each row behaving as its KIND: image loads onto a node, geometry imports in context, hip opens the scene, other copies its path. ▸o/section-api"""

    key = "file"
    label = "File"
    filter_tooltip = "Show one kind of file."
    empty_noun = "file"
    EMPTY = {  # a button: registering a folder needs nothing selected
        "nothing-yet": (
            "No folders added yet",
            "Add a folder of images, models or scenes and they show up "
            "here, ready to drag onto any parameter. Nothing is copied "
            "or moved.",
            "Add Folder", "add_file_folder_user"),
    }

    FILTER_CHOICES = (  # the kinds it KNOWS, in the order kind_for tests them; KIND_OTHER is the absence of a kind, not a fourth to browse by
        ("Images", file_library.KIND_IMAGE),
        ("Geometry", file_library.KIND_GEO),
        ("Hip", file_library.KIND_HIP),
    )

    GRID_MENU = (  # KIND-aware: the selection's kinds decide which primary actions exist. NO Delete anywhere - these are the user's own files on disk
        MenuEntry("Import", verb="menu_import", needs="menu_import_enabled",
                  shown="selection_has_importable"),
        MenuEntry("Load", verb="menu_load_scene", needs="one",
                  shown="selection_has_scene"),
        MenuEntry("Copy Path", verb="menu_copy_path"),
        SEPARATOR,
        MenuEntry("Show Location", verb="menu_reveal", needs="one"),
        MenuEntry("Capture Preview", verb="menu_capture",
                  needs="menu_capture_enabled", shown="selection_has_scene"),
    ) + GRID_MENU_TAIL

    _PATH_ONLY = DropRule(on_node="drop_file_path_on_node",    # per row KIND: every kind hands its path to the node under the cursor and what differs is the NO-NODE door, the un-kinded "" row behaving like unknown
                          click_resolve="click_copy_path")
    DROP_BY_KIND = {
        file_library.KIND_IMAGE: DropRule(
            on_node="drop_file_path_on_node",
            on_space="create_image_node_in",
            click_on_node="drop_file_path_on_node",
            carrier_type="mtlximage"),  # the ghost draws THIS in the air
        file_library.KIND_GEO: DropRule(
            on_node="drop_file_path_on_node",
            resolve="drop_geo_at_release",
            click_on_node="drop_file_path_on_node",
            click_resolve="click_import_geo"),
        file_library.KIND_HIP: DropRule(
            on_node="drop_file_path_on_node",
            outside="open_hip_scene",
            click_resolve="click_open_hip"),
        file_library.KIND_OTHER: _PATH_ONLY,
        "": _PATH_ONLY,
    }

    def export_package_to(self, indexes, path: str) -> int:    # the File flavour: each selected row's file rides whole under its kind
        items = []
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
        """Geometry drag released: import in context at the release point - on a SOP-capable node (geo, SOP Create) the loader lands inside it, an OBJ network gets a new geo, a LOP network a new SOP Create. A release over nothing is silent, a miss being a normal drag outcome rather than an error."""
        panel = self.panel
        context = panel._drop_context_under_cursor(
            panel._is_sop_container, include_viewports=True
        )
        if context is None:
            return False
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return False
        with hou.undos.group("Amaze Import Geometry"):
            created = panel._import_geo_in_context(path, context)
        if created is not None:
            helpers.place_nodes([created],
                                panel._release_position_in(context))
        return True

    def click_open_hip(self, index) -> bool:
        self.open_hip_scene(index)
        return True

    def open_hip_scene(self, index) -> None:
        """Open a scene file from the grid, leaving Houdini's own save prompt in charge of unsaved changes - re-implementing that dialog is a second, worse copy of a decision the user already has a well-known answer for."""
        path = self.panel._hip_path_for(index)
        if not path:
            return
        if not os.path.isfile(path):
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(
                    "That scene file is no longer there:\n%s" % path,
                    severity=hou.severityType.Warning)
            debug.event("hip", "scene missing", file=path)
            return
        try:
            hou.hipFile.load(path, suppress_save_prompt=False,
                             ignore_load_warnings=False)
        except hou.LoadWarning as warn:    # a scene that loads WITH warnings is still open and still worth a thumbnail: missing assets are the normal state of an old library, not a failure to open
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

    def drop_file_path_on_node(self, index, node) -> bool:
        """A File row released on a node: the node's FIRST file parameter takes the spelled path - the same act as selecting the node and double-clicking the row, aimed by the cursor instead of the selection, and uniform across kinds with unknown files included. A node with no file parameter answers False, so the gesture shows its own refusal - the miss indicator - never a dialog, and the status line carries the why."""
        panel = self.panel
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return False
        parm = helpers.find_file_parm(node)
        if parm is None:
            debug.refuse("%s has no file parameter to take %s"
                         % (node.name(), os.path.basename(path)))
            return False
        with hou.undos.group("Amaze Set File Path"):
            parm.set(panel._scene_path(path))
        return True

    def create_image_node_in(self, index, dest, position=None) -> bool:
        """The image creation rule: a release on empty network space, or a double-click with nothing selected, makes a mtlximage carrying the spelled path wherever the network can hold one."""
        panel = self.panel
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return False
        base = helpers.sanitize_usd_path(
            os.path.splitext(os.path.basename(path))[0]) or "image"
        with hou.undos.group("Amaze Create Image Node"):
            node = panel._create_carrier(dest, "mtlximage", base, position)
            if node is None:
                return False
            parm = helpers.find_file_parm(node)
            if parm is None:
                node.destroy()
                return False
            parm.set(panel._scene_path(path))
        return True

    def click_copy_path(self, index) -> bool:
        """An unknown file has no scene behaviour - its one action."""
        self.panel.copy_file_paths([index])
        return True

    SIDEBAR_MENU = (  # a location's vocabulary. Per-location entries need a REAL row ("All" is synthetic, sidebar_key answers ""); Show All Files alone stays live there, where its tick IS the global preference
        MenuEntry("Add Location", verb="menu_add_location",
                  needs="always"),
        MenuEntry("Remove", verb="menu_remove_location", needs="always"),
        MenuEntry("Locate", verb="menu_locate_location", needs="always"),
        MenuEntry("Label", verb="menu_label", children="label_actions",
                  needs="on_a_location"),
        SEPARATOR,
        MenuEntry("Show Subfolders", verb="menu_set_recursive",
                  needs="on_a_location", checkable="is_recursive"),
        MenuEntry("Show All Files", verb="menu_set_show_all",
                  needs="always", checkable="shows_all_files"),
        SEPARATOR,
        MenuEntry("Set Color", verb="menu_set_colour",
                  needs="on_a_location"),
        MenuEntry("Clear Color", verb="menu_clear_colour",
                  needs="on_a_location"),
    )

    def _selected_location(self, current) -> str:
        return self.sidebar_key(current) if current is not None else ""

    def on_a_location(self, indexes, current) -> bool:
        return bool(self._selected_location(current))

    def is_recursive(self, indexes, current) -> bool:
        path = self._selected_location(current)
        return bool(path) and path in self.panel.prefs.file_recursive_folders

    def shows_all_files(self, indexes, current) -> bool:
        path = self._selected_location(current)
        if path:
            return bool(file_library.shows_all_files(self.panel.prefs, path))
        return bool(self.panel.prefs.file_show_unknown)

    def label_actions(self, indexes, current) -> tuple:
        """Add sets a custom name for the location link and Remove clears it back to the default, which is the path itself, because a rename must be reversible; Remove greys when there is nothing to remove, which is why the children are built per selection."""
        path = self._selected_location(current)
        named = bool(path and self.panel.prefs.file_folder_names.get(path))
        return (("Add", "add", "", True),    # Remove is always OFFERED and greys with nothing to remove, never hidden: an entry that disappears moves the row under the cursor between two right-clicks
                ("Remove", "remove", "", named))

    def menu_label(self, indexes, current, payload=None) -> None:
        path = self._selected_location(current)
        if not path:
            return
        if payload == "remove":
            name = ""
        else:
            name = self.panel.ask_category_name("Add Label")
            if name is None:
                return
        self.panel.prefs.set_file_folder_name(path, name)
        folders = self._p(self.folders_attr)
        row = folders.row_of(path) if folders is not None else None
        if folders is not None and row is not None:
            index = folders.index(row, 0)
            folders.dataChanged.emit(index, index)

    def menu_add_location(self, indexes, current, payload=None) -> None:
        self.panel.add_file_folder_user()

    def menu_remove_location(self, indexes, current, payload=None) -> None:
        self.panel.remove_file_folder_user()

    def menu_locate_location(self, indexes, current, payload=None) -> None:
        self.panel._locate_folder_user(self._p(self.folders_attr))

    def menu_set_recursive(self, indexes, current, payload=None) -> None:
        path = self._selected_location(current)
        if not path:
            return
        self.panel.prefs.set_file_folder_recursive(path, bool(payload))
        self._p(self.folders_attr).refresh_counts()
        # Rescan whatever is showing under the new mode.
        self.panel.update_selected_cat()

    def menu_set_show_all(self, indexes, current, payload=None) -> None:
        path = self._selected_location(current)
        if path:
            self.panel.prefs.set_file_folder_show_all(path, bool(payload))
        else:
            # The All row edits the GLOBAL preference.
            self.panel.prefs.file_show_unknown = bool(payload)
            self.panel.prefs.save()
        self._p(self.folders_attr).refresh_counts()
        self.panel.update_selected_cat()
    files_proxy_attr = "file_sorted_model"
    selection_attr = "file_selection_model"
    delegate_attr = "file_delegate"
    sidebar_attr = "file_folders_model"
    takes_capture = True  # the only context with scene tiles to capture onto
    folders_pref = "file_folders"
    colour_pref_setter = "set_file_folder_color"
    folders_attr = "file_folders_model"
    files_attr = "file_files_model"
    last_folder_pref = "last_file_folder"

    def prefs_changed(self) -> None:
        folders = self._p(self.folders_attr)    # Geometry Shading/Background changed in Preferences must show without re-clicking the folder, since geometry rows still render that way
        if folders is not None:
            folders.refresh_counts()    # Show Unknown Files changes what counts as a row, and the sidebar numbers must agree with the grid
        self.panel.update_selected_cat()

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)


class OnlineContext(Section):
    """The online world, with a Section's interface and none of its identity: a PARALLEL WORLD rather than a view mode over Materials (overview.md §5), driving the same four widgets every section drives, so it shares the interface even though it is not in SECTION_CLASSES and never appears in enabled_sections. Enter it through activate() like any other, or the Capture button, the search box and the Comments pane all keep the state the section you left gave them."""

    key = "online"
    label = "Online"
    sidebar_attr = "matx_source_model"
    proxy_attr = "matx_sorted_model"
    selection_attr = "matx_selection_model"
    delegate_attr = "matx_delegate"    # ITS OWN, carrying only the roles matx_library has: borrowing the Materials delegate gives the online grid a Version, Licence and Comments column no online record can fill
    search_hint = ""    # empty is the standing decree for every tab; the box's tooltip is what teaches the leading-colon tag search, here as everywhere else

    def activate(self) -> None:
        panel = self.panel
        if panel.cat_list:
            panel.cat_list.setModel(self._p(self.sidebar_attr))
        panel.bind_grid_views(self._p(self.proxy_attr),
                              self._p(self.selection_attr),
                              self._p(self.delegate_attr))
        panel.set_conversion_bar_visible(False)
        panel.matx_online_model.reload()
        panel.sync_list_columns()

    def filter_text(self, text: str) -> None:
        """The online search asks the SOURCE, not a proxy."""
        self.panel.matx_online_model.set_search(text)

    def filter_favorites(self, on: bool) -> None:
        """Nothing to do: an online record carries no favourite state, which is why the star is disabled here."""

    def select_category(self, index) -> None:
        panel = self.panel    # row 0 is the everything-row, for which category_at answers None: REMOVE the filter rather than store a sentinel accepting every row, the shape every section's apply_filter uses
        category = panel.matx_source_model.category_at(index.row())
        role = panel.matx_online_model.CategoryRole
        if category is None:
            panel.matx_sorted_model.removeFilter(role)
        else:
            panel.matx_sorted_model.setFilter(role, category)
        grid.visible_view(panel).scrollToTop()

    def double_click(self, index) -> None:
        """The primary action, which here - exactly as for a local material - puts the material INTO THE SCENE rather than into the library. Its own door on purpose: falling through to Materials means import_asset() reads the MATERIAL selection model, still holding whatever was selected before going online, so a double-click imports an unrelated local material."""
        if index is None or not index.isValid():
            return
        panel = self.panel
        source = panel.matx_sorted_model.mapToSource(index)
        record = panel.matx_online_model.record(source.row())
        if record is not None:
            panel._import_online_records_to_scene([record])

    def stack(self):
        return None

    GRID_MENU = (    # named for WHERE the material lands rather than what it is - both entries build the same Karma material and the choice is library entry vs scene node; Refresh acts on nothing selected, so it stays live like Code's New File
        MenuEntry("Import to Materials", verb="menu_import_to_library",
                  count_suffix=True),
        MenuEntry("Import to Scene", verb="menu_import_to_scene",
                  count_suffix=True),
        MenuEntry("Restore", verb="menu_restore_packages",
                  shown="selection_is_amaze_packages", count_suffix=True),
        MenuEntry("Refresh", verb="menu_refresh", needs="always"),
    )

    def _records(self, indexes) -> list:
        """The catalogue records behind THESE rows, read through the indexes the menu was built from rather than a second read of the selection model - two reads can disagree when one of them drops a row whose record does not resolve, and the menu then promises "(3)" and imports two."""
        model = self.panel.matx_online_model
        proxy = self.panel.matx_sorted_model
        records = []
        for index in indexes:
            record = model.record(proxy.mapToSource(index).row())
            if record is not None:
                records.append(record)
        return records

    def menu_import_to_library(self, indexes, current, payload=None) -> None:
        self.panel._import_online_records(self._records(indexes))

    def menu_import_to_scene(self, indexes, current, payload=None) -> None:
        with helpers.preserving_selection_and_current():    # same wrapper as menu_copy_to: a menu import must not move the artist's selection, current node or view
            self.panel._import_online_records_to_scene(
                self._records(indexes))

    def selection_is_amaze_packages(self, indexes, current) -> bool:
        """Every selected record is an amazepkg - Restore means nothing for a material source."""
        records = self._records(indexes)
        return bool(records) and all(
            getattr(r, "kind", "") == "amazepkg" for r in records)

    def menu_restore_packages(self, indexes, current, payload=None) -> None:
        self.panel.restore_amaze_packages(self._records(indexes))

    def menu_refresh(self, indexes, current, payload=None) -> None:
        """Refresh is the user asking us to go and LOOK: sources that browse from a shipped table (RGL, PhysicallyBased) only query the live site on this path."""
        for source in self.panel.matx_online_model.sources:
            try:
                source.refresh()
            except Exception as exc:                     # noqa: BLE001
                debug.exception("refresh source", exc, source=source.name)
        self.panel.matx_online_model.reload(force=True)    # force, or a loaded catalogue just re-filters and the user's explicit Refresh did nothing

    takes_comments = False    # the three the online world does not offer, declared here rather than as _is_online() branches in the panel, and the toolbar reads them
    takes_favourites = False
    takes_filter_menu = False


class GradientSection(AssetSection):
    """Colors on the asset spine: model, sidebar, proxy and verbs are the family's, and what stays its own is what a palette IS - the ramp verbs, the swatch menu, the size filter - plus the one documented keep, apply_filter."""

    @staticmethod
    def delete_prompt(count: int, name: str = "") -> str:
        if count == 1:    # the one section whose approved copy NAMES the thing: a palette's name is what the user picked it by, and this is the only section where the tile label is the whole identity a person has
            return ('Delete "%s"? The gradient goes for good. Ramps '
                    "already applied to a node are not affected."
                    % (name or "this palette"))
        return ("Delete %d gradients? They go for good. Ramps already "
                "applied to a node are not affected." % count)

    key = "gradient"
    label = "Color"
    empty_noun = "palette"
    EMPTY = {  # no button: the gesture belongs to the network editor
        "nothing-yet": (
            "No palettes saved yet",
            "Right-click a node with a color ramp and choose Save to "
            "Amaze. Apply it to any ramp later, in any scene.",
            "", ""),
    }
    library_model_attrs = ("gradient_model", "gradient_categories_model")    # the raw MODELS, where sidebar_attr below names the proxy over them, which is why this cannot be derived from it
    model_attr = "gradient_model"
    category_attr = "gradient_categories_model"
    sidebar_attr = "gradient_category_sorted_model"    # the same CategoriesSidebarProxy the asset sidebars go through; nothing hides here, because no renderer filter is ever pushed at Colors
    delegate_attr = "gradient_delegate"
    proxy_attr = "gradient_sorted_model"
    selection_attr = "gradient_selection_model"

    offers_preview_update = False  # drawn from its ramp; nothing to re-render
    GRID_MENU = (  # both submenus are built PER ENTRY, so `children` names a method. Copy Color COPIES a hex code rather than assigning it - a node has many colour inputs
        MenuEntry("Apply", verb="menu_apply_ramp", needs="one"),
        MenuEntry("Apply as", verb="menu_apply_ramp", children="ramp_bases",
                  needs="one"),
        MenuEntry("Copy Color", verb="menu_copy_swatch",
                  children="palette_swatches", needs="one"),
        SEPARATOR,
    ) + GRID_MENU_TAIL

    DROP = DropRule(on_node="apply_gradient_to_node",  # to a node with a ramp; on space the MaterialX ramp carrier, where supported
                    on_space="create_gradient_node_in",
                    click_on_node="apply_gradient_to_node")

    def apply_gradient_to_node(
        self, index: QtCore.QModelIndex, node: hou.Node,
        basis: str = "",
    ) -> bool:
        """Drag-drop completion for the Gradients section: apply the dragged combination to the node the drag was released over. A node that takes nothing answers False, so the gesture shows its own miss - drag-door rule, the red indicator and the status line, never a dialog."""
        entry = self._entry_at(index)
        if entry is None:
            return False
        parm = helpers.find_color_ramp_parm(node)
        if parm is None:
            debug.refuse("%s has no color ramp to take the gradient"
                         % node.name())
            return False
        with hou.undos.group("Amaze Apply Gradient"):
            parm.set(self._entry_ramp(entry, basis))
        return True

    @staticmethod
    def _entry_ramp(entry: dict, basis: str = "") -> hou.Ramp:
        if basis:    # an explicit basis rebuilds the ramp from the gradient's colours on that one interpolation; otherwise the recorded ramp (bases/keys/values) applies exactly as saved
            return helpers.build_basis_ramp(
                [c["hex"] for c in entry["colors"]], basis)
        ramp = entry.get("ramp")
        if ramp:
            return helpers.data_to_ramp(ramp)
        return helpers.build_stepped_ramp([c["hex"] for c in entry["colors"]])

    def create_gradient_node_in(self, index, dest, position=None,
                                basis: str = "") -> bool:
        """The gradient creation rule: a MtlX colour ramp carrying the combination, wherever the network can hold one. `basis` is Apply as's chosen interpolation arriving through the click door's payload, and empty means the gradient's own recorded ramp, which is every other door."""
        entry = self._entry_at(index)
        if entry is None:
            return False
        return self._create_gradient_carrier(entry, dest, basis,
                                             position=position)

    def _create_gradient_carrier(self, entry, dest, basis: str = "",
                                 position=None) -> bool:
        """The carrier half shared by the drag door (an index) and the double-click and menu doors (an entry, optionally re-based by Apply as)."""
        name = helpers.sanitize_usd_path(
            str(entry.get("name") or "")) or "gradient"
        with hou.undos.group("Amaze Create Gradient Node"):
            node = self.panel._create_carrier(dest, "hmtlxrampc", name,
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
        """Put one swatch's hex code on the system clipboard - deliberately not an assignment, because a material carries many colour inputs (base, specular, coat, emission, subsurface...) and choosing one for the user is a guess, where a hex code pastes into the intended input by their own hand and Houdini's colour fields accept it, as does every other application."""
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

    carrier_type = "hmtlxrampc"  # the MaterialX colour ramp

    def accepts_category_drop(self, index, name: str) -> bool:
        return name in self.panel.gradient_model.user_categories()    # defensive: every gradient category listed is a real editable user category now, the palettes being seeded as such, but the sidebar has listed synthetic rows before

    SIDEBAR_MENU = (  # everything below All is a real user category, so the per-category entries exist only on such a row
        MenuEntry("Add Category", verb="menu_add_category",
                  needs="always"),
        MenuEntry("Rename", verb="menu_rename_category", needs="one",
                  shown="on_a_category"),
        MenuEntry("Remove", verb="menu_remove_category",
                  shown="on_a_category"),
        SEPARATOR,
        MenuEntry("Set Color", verb="menu_set_colour",
                  shown="on_a_category"),
        MenuEntry("Clear Color", verb="menu_clear_colour",
                  shown="on_a_category"),
        SEPARATOR,
        MenuEntry("Export Category", verb="menu_export_category",
                  needs="one"),
    )

    def on_a_category(self, indexes, current) -> bool:
        """Is the row under the cursor a real user category? The STORED name answers, and the everything-marker is not one."""
        if current is None:
            return False
        name = self.sidebar_key(current)
        return bool(name) and name not in ("All", "_All")

    def _entry_at(self, index):
        if index is None or not index.isValid():
            return None
        source = self.panel.gradient_sorted_model.mapToSource(index)
        return self.panel.gradient_model.entry(source.row())

    def ramp_bases(self, indexes, current) -> tuple:
        """Every interpolation, always offered."""
        return tuple((basis, basis, "", True)
                     for basis in helpers.RAMP_BASES)

    def palette_swatches(self, indexes, current) -> tuple:
        """One row per colour in THIS palette, each carrying its own hex as the swatch colour, so the menu doubles as a preview; the pixmap is drawn by panel/grid.py and this only says which colour it is."""
        entry = self._entry_at(current)
        if entry is None:
            return ()
        return tuple(
            ("%s   %s" % (colour["name"], colour["hex"].upper()),
             colour, colour["hex"], True)
            for colour in entry["colors"]
        )

    def menu_apply_ramp(self, indexes, current, payload=None) -> None:
        self.panel.click_on_row(self, current, payload or None)    # Apply and Apply as, through the click door; the payload is the chosen ramp basis and the door hands it to whichever verb runs, so re-basing works on the node AND on the carrier

    def menu_copy_swatch(self, indexes, current, payload=None) -> None:
        if payload is not None:
            self._copy_gradient_swatch(payload)
    search_hint = ""  # this proxy also matches the colour NAMES inside a palette
    filter_tooltip = "Show palettes of one size."

    FILTER_CHOICES = (  # (label, (fewest, most)); `most` None is "5+"'s open end, so the proxy never has to know which entry is last
        ("1 color", (1, 1)),
        ("2 colors", (2, 2)),
        ("3 colors", (3, 3)),
        ("4 colors", (4, 4)),
        ("5+ colors", (5, None)),
    )

    def apply_filter(self, value) -> None:
        self.panel.gradient_sorted_model.set_size_filter(value)    # a documented KEEP, NOT inheritable: a palette's kind field is uniformly "Gradient" so the menu narrows by SIZE, and pushing these colour-COUNT tuples through the base's set_renderer_filter would store "(2, 2)" as a renderer matching nothing, count every category 0 and collapse the sidebar to _All under Hide Empty

    def double_click(self, index) -> None:
        self.panel.click_on_row(self, index)

    def save_node(self, node) -> None:
        self.panel.save_gradient_from_node(node)


SECTION_CLASSES = (    # the section registry in tab order, built by the panel once its models exist; adding a section is one class here

    MaterialSection,
    GradientSection,
    CopSection,
    CodeSection,
    FileSection,
)

SECTION_INDEX = {cls.key: cls for cls in SECTION_CLASSES}    # the same registry keyed for lookup, CLASS-level on purpose: the gesture engine reads declarations (DROP, DROP_BY_KIND), so tests drive the real tables without building a panel's worth of models


def drop_rule(section, panel, index):
    """The rule THIS ROW declares, or None: a section declares one DROP for every row unless its rows are different THINGS - the File section - in which case it declares DROP_BY_KIND and the row's KindRole picks. The ONE reader of that, so the drag walker and the click walker cannot end up disagreeing about the same tile, and a section that gains a third way of declaring changes one place."""
    if section is None:
        return None
    by_kind = getattr(section, "DROP_BY_KIND", None)
    if by_kind:
        kind = index.data(panel.file_files_model.KindRole) or ""
        return by_kind.get(kind)
    return getattr(section, "DROP", None)


def drop_verb(section, name):
    """The bound verb a declaration names, always the SECTION's own - the panel owns the widgets and the shared plumbing, the section owns the meaning, and the pin in test_area_bindings walks every declaration to keep a panel fallback from creeping back. A name that resolves nowhere raises, because a broken declaration must fail loudly rather than miss quietly."""
    return getattr(section, name)


def all_sections() -> tuple:
    """((key, label), ...) in tab order - the ONE source everything that lists the sections reads: the tab strip, the Show/Hide toggles, and the pref that persists them."""
    return tuple((cls.key, cls.label) for cls in SECTION_CLASSES)


def renderer_prefs() -> tuple:
    """((label, preference-attribute), ...) - the ONE renderer table, beside all_sections() and for the same reason. Every reader comes here: add a renderer to this tuple alone and the Filter menu offers it while Preferences has no switch to hide it; add it to Preferences alone and the switch toggles a preference no menu reads; add it to both but not to enable_renderer_on_add and the first material saved of that renderer is invisible in the tab it was saved from, the exact defect that function exists to prevent."""
    return MaterialSection.RENDERER_PREFS


def build_sections(panel) -> dict:
    """Instantiate every section against a constructed panel."""
    return {cls.key: cls(panel) for cls in SECTION_CLASSES}
