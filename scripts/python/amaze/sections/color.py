"""The Color section: palettes applied as ramps, their swatches, and their size filter."""

from __future__ import annotations

import hou
from PySide6 import QtCore, QtGui

from amaze import messages
from amaze.core import category, debug, section_list
from amaze.helpers import wording
from amaze.sections import base


class GradientSection(base.AssetSection):
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
    library_model_attrs = ("gradient_model", "gradient_categories_model")    # the raw models; sidebar_attr names the proxy over them
    model_attr = "gradient_model"
    category_attr = "gradient_categories_model"
    sidebar_attr = "gradient_category_sorted_model"    # the same CategoriesSidebarProxy the asset sidebars use
    delegate_attr = "gradient_delegate"
    tile_badges = ("favourite", "comment")
    list_columns = ("name", "type", "category", "favorite", "comments")
    proxy_attr = "gradient_sorted_model"
    selection_attr = "gradient_selection_model"

    offers_preview_update = False  # drawn from its ramp; nothing to re-render
    GRID_MENU = (  # both submenus are built per entry, so `children` names a method
        base.MenuEntry("Load Asset", handler="menu_apply_ramp", needs="one"),
        base.MenuEntry("Load Asset as", handler="menu_apply_ramp", children="ramp_bases",
                  needs="one"),
        base.MenuEntry("Copy Color", handler="menu_copy_swatch",
                  children="palette_swatches", needs="one"),
        base.SEPARATOR,
    ) + base.GRID_MENU_TAIL

    DROP = base.DropRule(on_node="apply_gradient_to_node",  # to a node with a ramp; on empty space a MaterialX ramp node, where supported
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
        from amaze.helpers import helpers
        name = wording.sanitize_usd_path(str(entry.get("name") or "")) or "gradient"
        return self.pane.drop_placement.create_holder_node(
            dest, "hmtlxrampc", name, position, helpers.find_color_ramp_parm,
            self._entry_ramp(entry, basis), "Amaze Create Gradient Node")

    def _copy_gradient_swatch(self, color: dict) -> None:
        """Put one swatch's hex code on the system clipboard; it assigns nothing."""
        hex_code = str(color.get("hex", "")).strip()
        if not hex_code:
            return
        if not hex_code.startswith("#"):
            hex_code = "#" + hex_code
        hex_code = hex_code.upper()
        clipboard = QtGui.QGuiApplication.clipboard()
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
        return name in dict(self.pane.gradient_model.user_categories())    # no synthetic row

    SIDEBAR_MENU = (  # everything below All is a real user category, so the per-category entries exist only on such a row
        base.MenuEntry("Add", handler="menu_add_category", needs="always", opens="ask_name"),
        base.MenuEntry("Rename", handler="menu_rename_category", needs="one", opens="ask_name",
                  shown="on_a_category"),
        base.MenuEntry("Delete", handler="menu_remove_category",
                  shown="on_a_category"),
        base.SEPARATOR,
        base.MenuEntry("Sort by name", handler="menu_sort_categories",
                  needs="always"),
        base.SEPARATOR,
        base.MenuEntry("Label", handler="menu_label_colour", children="label_colours",
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
        source = self.pane.gradient_sorted_model.mapToSource(index)
        return self.pane.gradient_model.entry(source.row())

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
        self.pane.loading.click_on_row(self, current, payload or None)    # Apply and Apply as through `click_on_row`; the payload is the ramp basis

    def menu_copy_swatch(self, indexes, current, payload=None) -> None:
        if payload is not None:
            self._copy_gradient_swatch(payload)
    search_hint = ""  # this proxy also matches the colour NAMES inside a palette
    filter_tooltip = "Show palettes of one size."

    FILTER_CHOICES = (  # value (fewest, most); `most` None is the open end of "5+"
        base.FilterEntry("1 color", "1 color", (1, 1)),
        base.FilterEntry("2 colors", "2 colors", (2, 2)),
        base.FilterEntry("3 colors", "3 colors", (3, 3)),
        base.FilterEntry("4 colors", "4 colors", (4, 4)),
        base.FilterEntry("5+ colors", "5+ colors", (5, None)),
    )

    def apply_filter(self, value) -> None:
        self.pane.gradient_sorted_model.set_size_filter(value)    # filters by size; never through set_renderer_filter

    def can_save(self, nodes) -> bool:
        from amaze.helpers import helpers
        return (len(nodes) == 1
                and helpers.find_color_ramp_parm(nodes[0]) is not None)

    def save_categories(self) -> tuple:
        categories = self.pane.gradient_model.user_categories()
        return categories, (categories[0][0] if categories else "")

    def commit_save(self, nodes, node, answer) -> None:
        """The node's first color ramp, registered as a user gradient."""
        from amaze.helpers import helpers
        parm = helpers.find_color_ramp_parm(node)
        ramp_data = helpers.ramp_to_data(parm.evalAsRamp())
        self.pane.gradient_model.add_user_gradient(
            answer.name or node.name(), answer.categories, ramp_data,
            tags=answer.tags
        )

    @classmethod
    def save_rank(cls, nodes) -> int:
        return 2
