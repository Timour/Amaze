"""The Node section: node setups saved from any context, loaded where the context allows."""

from __future__ import annotations

import hou

from amaze import messages
from amaze.actions import nodes as node_actions
from amaze.core import debug, library, section_list
from amaze.render import cop_nodes
from amaze.sections import base


class CopSection(base.AssetSection):
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
    GRID_MENU = (    # the material menu without renderer-specific entries; Load Asset is enabled on a multi-selection
        base.MenuEntry("Load Asset", handler="menu_load"),
        base.SEPARATOR,
    ) + base.GRID_MENU_TAIL

    DROP = base.DropRule(resolve="drop_cop_at_release",    # a saved network is built where its context allows, so the method finds the destination
                    click_resolve="click_import_cop")

    def click_import_cop(self, _index) -> bool:
        self.pane.loading.import_cop_assets()
        return True

    def drop_cop_at_release(self, index) -> bool:
        """Load a dropped Nodes asset into the network under the cursor, if its context matches."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        pane = self.pane
        if not pane.cop_model:
            return False
        if index is None or not index.isValid():
            return False    # a drag started on empty grid space has an invalid index
        context = pane.drop_placement.context_under_cursor(
            cop_nodes.is_container)
        if context is None:
            return self.reject_drop()
        try:
            source_index = pane.cop_sorted_model.mapToSource(index)
        except Exception:
            return False
        with dragengine.drop_group("Amaze Import COP Network"):
            ok, reason, created = node_actions.import_asset_to_scene(
                pane.cop_model, source_index, context_node=context
            )
        if not ok and reason:
            debug.refuse(reason, net=context.path())    # the import marks library damage, so a dialog shows, not the status line ▸p/refuse-vs-alert
        if ok:
            helpers.place_nodes(created,
                                pane.drop_placement.release_position_in(context))
        return True

    def menu_load(self, indexes, current, payload=None) -> None:
        self.pane.loading.import_cop_assets()
    library_model_attrs = ("cop_model", "cop_category_model")
    model_attr = "cop_model"
    proxy_attr = "cop_sorted_model"
    selection_attr = "cop_selection_model"
    category_attr = "cop_category_model"
    sidebar_attr = "cop_category_sorted_model"
    delegate_attr = "asset_delegate"    # not thumb_delegate, which paints a Version column
    tile_badges = ("favourite", "comment")
    list_columns = ("name", "type", "category", "favorite", "comments", "tags", "license", "date",
                    "id")
    filter_tooltip = "Show setups saved from one context."

    FILTER_CHOICES = (    # the contexts cop_nodes.SAVE_CONTEXTS saves, spelled as Houdini's network tabs show them
        base.FilterEntry("SOP", "SOP", "Sop"),
        base.FilterEntry("COP", "COP", "Cop"),
        base.FilterEntry("LOP", "LOP", "Lop"),
        base.FilterEntry("DOP", "DOP", "Dop"),
        base.FilterEntry("TOP", "TOP", "Top"),
        base.FilterEntry("CHOP", "CHOP", "Chop"),
        base.FilterEntry("Object", "Object", "Object"),
    )

    def can_save(self, nodes) -> bool:
        return (bool(nodes) and len({n.parent() for n in nodes}) == 1
                and cop_nodes.can_save(nodes[0]))

    def commit_save(self, nodes, node, answer) -> None:
        """Works in any context the Nodes section supports; the asset records which one."""
        ui = getattr(hou, "ui", None)
        net = node.parent()
        items = [i for i in hou.selectedItems() if i.parent() == net]
        if not any(i == node for i in items):
            items.append(node)
        if len(items) == 1 and cop_nodes.saves_whole_network(node):    # a container alone saves its network
            items = None

        if answer.categories:
            self.pane.cop_category_model.check_add_category(answer.categories)

        result = None
        save_error = None    # no layout wrapper: add_asset emits its own row-insert signals
        try:
            result = node_actions.add_asset(
                self.pane.cop_model,
                node,
                answer.categories,
                answer.tags,
                answer.fav,
                items=items,
                name=answer.name,
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
            debug.refuse(messages.ASSET_ADDED_LIBRARY_NOT_SAVED % (answer.name.strip() or node.name()))

    def update_preview(self, indexes) -> None:
        """Update Render on Node tiles: each network's thumbnail re-rendered by `node_actions`."""
        model, rows = self._model_and_rows(indexes)
        if rows:
            node_actions.render_thumbnails(model, rows)

    @classmethod
    def save_rank(cls, nodes) -> int:
        return 3
