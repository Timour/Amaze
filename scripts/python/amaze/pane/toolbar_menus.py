"""The toolbar's View and Filter menus as tables on the pane; the menu engine makes their rows."""

from amaze.pane import menus
from amaze.sections import base

KIND_FILTER = (("All", None, base.ALL_GLYPH), ("Materials", "material", base.Glyph("sphere")),
               ("Colors", "gradient", base.Glyph("swatches")), ("Nodes", "cop", base.Glyph("git_fork")),
               ("Code", "code", base.Glyph("code")))    # online: (label, section key, glyph) the Filter button offers


class ToolbarMenus:
    """What a toolbar menu button opens: one table entry, as the old menu bar held it, and its rows."""

    VIEW = base.MenuEntry("View", needs="always", children=(    # C11, the cube button
        base.MenuEntry("Generate Material", handler="menu_generate_material", needs="always",
                       glyph="sphere"),
        base.MenuEntry("Gallery Import (.gal)", handler="menu_import_galleries", needs="always",
                       glyph="arrow_square_in"),
        base.MenuEntry("Import Package (.amazepkg)", handler="menu_import_package", needs="always",
                       glyph="arrow_square_in"),
        base.MenuEntry("Export Asset (.amazepkg)", handler="menu_export_asset", needs="exports_asset",
                       glyph="arrow_square_out"),
        base.MenuEntry("Export Category (.amazepkg)", handler="menu_export_category",
                       needs="exports_category", glyph="arrow_square_out"),
    ))
    FILTER = base.MenuEntry("Filter", handler="menu_choose_filter", needs="always",
                            children="filter_choices")    # C13-C17, the eye button
    KINDS = base.MenuEntry("Filter", handler="menu_choose_kind", needs="always",
                           children="kind_choices")    # C12, the eye button online

    def __init__(self, pane) -> None:
        self.pane = pane

    def menu(self, name: str, host=None) -> menus.Menu:
        """The engine's menu for button `name`, "view" or "filter"; its first row holds the rows to show."""
        return menus.Menu(self, (self.entry(name),), [], None, host=host)

    def entry(self, name: str):
        """The table entry behind button `name`; online, the Filter button narrows the kind."""
        if name == "view":
            return self.VIEW
        return self.KINDS if self.kinds_shown() else self.FILTER

    def kinds_shown(self) -> bool:
        """Whether the Filter button opens the online kind filter."""
        section = self.pane.active_section()
        return (bool(getattr(section, "kind_filter_menu", False))
                and getattr(self.pane, "matx_online_model", None) is not None)

    def filter_offered(self) -> bool:
        """Whether the Filter button has a menu: online, or where the shown section lists entries."""
        if self.kinds_shown():
            return True
        section = self.pane.active_section()
        return bool(getattr(section, "takes_filter_menu", True)) and bool(self.pane.filter_entries())

    def filter_choices(self, indexes, current) -> list:
        """The shown section's entries, the one in force checked; SVG icons after All set it apart (C13)."""
        entries, choice = self.pane.filter_entries(), self.pane.filter_choice()
        rows = [(entry.label, entry.id, entry.icon or "", True, entry.id == choice) for entry in entries]
        if len(entries) > 1 and entries[1].icon and not isinstance(entries[1].icon, base.Glyph):
            rows.insert(1, None)
        return rows

    def kind_choices(self, indexes, current) -> list:
        """The online kinds, the one the grid is narrowed to checked."""
        shown = self.pane.matx_online_model.kind_filter()
        return [(label, key, glyph, True, key == shown) for label, key, glyph in KIND_FILTER]

    def exports_asset(self, indexes, current) -> bool:
        return bool(self.pane.assets.exportable_selection()[1])

    def exports_category(self, indexes, current) -> bool:
        return self.pane.assets.exportable_category() is not None

    def menu_choose_filter(self, indexes, current, payload) -> None:
        entry_id, _checked = payload    # a choice, not a toggle: picking the checked row keeps it
        self.pane.choose_filter(entry_id)

    def menu_choose_kind(self, indexes, current, payload) -> None:
        key, _checked = payload
        self.pane.matx_online_model.set_kind_filter(key)

    def menu_generate_material(self, indexes, current, payload=None) -> None:
        self.pane.loading.generate_random_material()

    def menu_import_galleries(self, indexes, current, payload=None) -> None:
        self.pane.saving.import_galleries()

    def menu_import_package(self, indexes, current, payload=None) -> None:
        self.pane.package_import.import_package()

    def menu_export_asset(self, indexes, current, payload=None) -> None:
        self.pane.assets.export_package()

    def menu_export_category(self, indexes, current, payload=None) -> None:
        self.pane.assets.export_category()
