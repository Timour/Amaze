"""The Material section: saved materials, their renderers, conversion and the drop."""

from __future__ import annotations

import hou

from amaze import messages
from amaze.actions import materials as material_actions
from amaze.core import debug, library, renderers, section_list
from amaze.render import cop_nodes, nodes as nodes_mod
from amaze.sections import base


class MaterialSection(base.AssetSection):
    key = "material"
    label = section_list.label(key)
    empty_noun = "material"

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
        base.MenuEntry("Load Asset to", handler="menu_copy_to", children="copy_to_targets"),
        base.MenuEntry("Convert", handler="menu_convert_to",
                  children="convert_targets",
                  needs="selection_is_convertible"),
        base.SEPARATOR,
    ) + base.GRID_MENU_TAIL

    DROP = base.DropRule(resolve="drop_material_at_release",    # a material import finds its own destination at the release
                    click_resolve="click_import_material",
                    context="Vop")    # only a network that holds Vop nodes accepts the drop

    def click_import_material(self, _index) -> bool:
        """The material import reads the selection and the network under the cursor itself."""
        self.pane.loading.import_materials("auto")
        return True

    def drop_material_at_release(self, index) -> bool:
        """Import a dropped material; True on a target, False on none, `menu` if a menu showed."""
        from amaze.core import dragengine
        pane = self.pane
        if not pane.material_model or index is None or not index.isValid():
            return False
        ids = pane.loading.selected_material_ids(index)
        target = dragengine.viewport_release_target(pane)
        if target is not None:
            kind, viewer, data = target
            debug.event("drag", "material release", target=kind,
                        data=str(data), count=len(ids))
            if kind == "lop":
                if not data:
                    return self.reject_drop()    # empty viewport space is a MISS, not an import offer
                shown = pane.drop_placement.material_lop_viewport_drop(ids, viewer, data)
                return "menu" if shown is not False else False    # "menu" only when a menu was shown: it suppresses the miss icon
            if kind == "obj" and data is not None:
                with dragengine.drop_group("Amaze Assign Material"):
                    return bool(pane.loading.assign_material_to_obj(ids, data))    # False when the picked object has no shop_materialpath
            return self.reject_drop()
        context = pane.drop_placement.context_under_cursor("materiallibrary")
        if context is None or not cop_nodes.accepts_context(
                context, self.DROP.context):    # the wrong network is a miss and creates nothing; DROP.context decides
            debug.event("drag", "material release", target="miss",
                        context=context.path() if context else "")
            return self.reject_drop()
        debug.event("drag", "material release", target="network",
                    context=context.path(), count=len(ids))
        position = pane.drop_placement.release_position_in(context)
        pane.drop_placement.import_materials_into_context(context, ids, position)
        return True

    def copy_to_targets(self, indexes, current) -> tuple:
        """Where the saved material is loaded, named the way Houdini writes the path: /stage."""
        return (("/mat", "mat", "", True),
                ("/stage/materiallibrary", "lop", "", True))    # names the DESTINATION: the copy goes INSIDE a material library under /stage, never stage root

    def menu_copy_to(self, indexes, current, payload=None) -> None:
        self.pane.loading.import_materials("lop" if payload == "lop" else "mat")

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
            for renderer in renderers.offered(self.pane.prefs)
            if renderer.key in conversion_engine.targets())

    def menu_convert_to(self, indexes, current, payload=None) -> None:
        self.pane.assets.convert_selected(payload or renderers.INTERMEDIATE.key)

    library_model_attrs = ("material_model", "category_model")
    model_attr = "material_model"
    proxy_attr = "material_sorted_model"
    selection_attr = "material_selection_model"
    category_attr = "category_model"
    sidebar_attr = "category_sorted_model"
    delegate_attr = "thumb_delegate"
    tile_badges = ("favourite", "versions", "comment")
    list_columns = ("name", "type", "category", "favorite", "version", "comments", "tags",
                    "license", "date", "id")
    filter_tooltip = "Show materials for one renderer."

    FILTER_ALL_ICON = "filter_all"

    def filter_entries(self) -> tuple:
        """Rebuilt, never hidden: the pane uses All for a saved choice no longer offered."""
        return (base.FilterEntry(self.ALL_ID, self.ALL_LABEL, None, self.FILTER_ALL_ICON),) + tuple(
            base.FilterEntry(renderer.key, renderer.label, renderer.key, renderer.icon)
            for renderer in renderers.offered(self.pane.prefs))

    def can_save(self, nodes) -> bool:
        return bool(nodes) and all(    # a fresh handler per node: it remembers the last renderer
            nodes_mod.NodeHandler(self.pane.prefs).get_renderer_from_node(n)
            for n in nodes)

    def commit_save(self, nodes, node, answer) -> None:
        if answer.categories:
            self.pane.category_model.check_add_category(answer.categories)

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
                            self.pane.material_model, asset, answer.categories, answer.tags,
                            answer.fav, name=answer.name or None
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
                        unlisted.append(answer.name or asset.name())    # the name the add gave it
        except hou.OperationInterrupted:
            debug.status(messages.SAVE_STOPPED % (done, total))

        ui = getattr(hou, "ui", None)
        if failures and ui is not None:
            ui.displayMessage(
                messages.MATERIALS_SAVE_FAILURES, details="\n".join(failures),
                title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
        for renderer in renderers:
            self.pane.saving.enable_renderer_on_add(renderer)
        self.pane.prefs.save()
        self.pane.refresh_filter()
        self.pane.sidebar.refresh()
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
