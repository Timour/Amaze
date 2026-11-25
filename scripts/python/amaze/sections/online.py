"""The Online context: the online catalogue, with a Section's interface; not a section."""

from __future__ import annotations

from amaze.core import debug, renderers
from amaze.sections import base


class OnlineContext(base.Section):
    """The online section: a Section's interface, not in SECTION_CLASSES; shown by activate()."""

    key = "online"
    label = "Online"
    tile_badges = ("favourite",)    # an indicator with no click: the list keeps its Favourite column
    tile_badge_clicks = False
    sidebar_attr = "matx_source_model"
    proxy_attr = "matx_sorted_model"
    selection_attr = "matx_selection_model"
    delegate_attr = "matx_delegate"    # its own delegate, carrying only the roles matx_library has
    search_hint = ""    # empty, as on every tab; the tooltip explains the tag search

    def after_views_bound(self) -> None:
        self.pane.matx_online_model.reload()    # the catalogue of the source the tabs show

    def shown_sidebar_key(self) -> str:
        role = self.pane.matx_online_model.CategoryRole
        return self.pane.matx_sorted_model.filter_value(role) or ""

    def filter_text(self, text: str) -> None:
        """The online search is set on the SOURCE model, not a proxy."""
        self.pane.matx_online_model.set_search(text)

    def filter_favorites(self, on: bool) -> None:
        """Nothing to do: an online record carries no favourite state."""

    def select_category(self, index) -> None:
        pane = self.pane    # All, keyed "", is the everything-row: remove the filter
        category = self.sidebar_key(index)
        role = pane.matx_online_model.CategoryRole
        if not category:
            pane.matx_sorted_model.removeFilter(role)
        else:
            pane.matx_sorted_model.setFilter(role, category)
        pane.scroll_grid_to_top()

    def double_click(self, index) -> None:
        """The primary action: puts the material into the scene, not into the library."""
        if index is None or not index.isValid():
            return
        pane = self.pane
        source = pane.matx_sorted_model.mapToSource(index)
        record = pane.matx_online_model.record(source.row())
        if record is not None:
            pane.online_import.import_records_to_scene([record])

    def stack(self):
        return None

    GRID_MENU = (    # named for where the material goes, a submenu for its renderer, as in C06/C06a/C06b
        base.MenuEntry("Import to Materials", handler="menu_import_to_library",
                       children="import_targets", count_suffix=True, glyph="upload_simple"),
        base.MenuEntry("Import to Scene", handler="menu_import_to_scene",
                       children="import_targets", count_suffix=True, glyph="upload_simple"),
        base.MenuEntry("Restore", handler="menu_restore_packages",
                       shown="selection_is_amaze_packages", count_suffix=True,
                       glyph="clock_clockwise"),
        base.MenuEntry("Refresh", handler="menu_refresh", needs="always", glyph="arrows_clockwise"),
    )

    def _records(self, indexes) -> list:
        """The catalogue records behind these rows, read through the menu's own indexes."""
        model = self.pane.matx_online_model
        proxy = self.pane.matx_sorted_model
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
            for renderer in renderers.offered(self.pane.prefs)
            if renderer.key in conversion_engine.targets())

    def menu_import_to_library(self, indexes, current, payload=None) -> None:
        self.pane.online_import.import_records(self._records(indexes),
                                               renderer=payload or renderers.INTERMEDIATE.key)

    def menu_import_to_scene(self, indexes, current, payload=None) -> None:
        self.pane.online_import.import_records_to_scene(    # this method does the editor restore for both of its callers
            self._records(indexes), renderer=payload or renderers.INTERMEDIATE.key)

    def selection_is_amaze_packages(self, indexes, current) -> bool:
        """Every selected record is an amazepkg - Restore means nothing for a material source."""
        records = self._records(indexes)
        return bool(records) and all(
            getattr(r, "kind", "") == "amazepkg" for r in records)

    def menu_restore_packages(self, indexes, current, payload=None) -> None:
        self.pane.package_import.restore(self._records(indexes))

    def menu_refresh(self, indexes, current, payload=None) -> None:
        """Refresh queries the live site, even for sources that browse from a shipped table."""
        for source in self.pane.matx_online_model.sources:
            try:
                source.refresh()
            except Exception as exc:                     # noqa: BLE001
                debug.exception("refresh source", exc, source=source.name)
        self.pane.matx_online_model.reload(force=True)    # force, or a loaded catalogue just re-filters and the user's explicit Refresh did nothing

    takes_comments = False    # the three the online section does not offer; the toolbar reads them
    takes_info = False
    takes_favourites = False
    takes_filter_menu = False
    takes_capture = False    # an online tile is not in the library: nowhere to keep a capture
    kind_filter_menu = True
