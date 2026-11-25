"""The Material section: saved materials, their renderers, conversion and the drop."""

from __future__ import annotations

import hou
from PySide6 import QtCore

from amaze import messages
from amaze.actions import materials as material_actions
from amaze.core import debug, renderers, section_list
from amaze.render import cop_nodes, nodes as nodes_mod
from amaze.sections import base


def node_drag_mime(node) -> QtCore.QMimeData:
    """Houdini's own drag of a node: its path as node path, item path, text ▸r/solaris-material-drag"""
    mime_data = QtCore.QMimeData()
    for kind in (hou.qt.mimeType.nodePath, hou.qt.mimeType.itemPath):
        mime_data.setData(kind, node.path().encode("utf-8"))
    mime_data.setText(node.path())
    return mime_data


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

    GRID_MENU = (    # Import is the double-click: into the network the editor shows
        base.MenuEntry("Import", handler="menu_import", glyph="upload_simple"),
        base.MenuEntry("Convert", handler="menu_convert_to", children="convert_targets",
                       needs="selection_is_convertible", glyph="copy_simple"),
        base.MenuEntry("Swap Material", handler="menu_swap_material", needs="swap_offered",
                       glyph="swap"),
        base.SEPARATOR,
    ) + base.GRID_MENU_TAIL

    DROP = base.DropRule(resolve="drop_material_at_release",    # a material import finds its own destination at the release
                    click_resolve="click_import_material",
                    context="Vop",    # only a network that holds Vop nodes accepts the drop
                    native_drag="material_drag_into_viewer")

    def click_import_material(self, _index) -> bool:
        """The material import reads the selection and the network under the cursor itself."""
        self.pane.loading.import_materials()
        return True

    def material_drag_into_viewer(self, index, viewer, pane_kind):
        """Over an object or Solaris viewer: imported, then Houdini's node drag ▸r/solaris-material-drag"""
        from amaze.core import dragengine
        world = dragengine.viewer_world(viewer) if pane_kind == hou.paneTabType.SceneViewer else None
        if world is None:    # Amaze's own drag goes on: a release here is a miss
            return None
        pane = self.pane
        ids = pane.loading.selected_material_ids(index) if pane.material_model else []
        material = pane.drop_placement.import_materials_for_viewer(viewer, world, ids) if ids else None
        debug.event("drag", "material handed to a viewer", world=world, count=len(ids),
                    material=material.path() if material is not None else "")
        if material is None:    # its reason is shown
            return False
        return node_drag_mime(material), QtCore.Qt.DropAction.MoveAction

    def drop_material_at_release(self, index) -> bool:
        """Import a dropped material into the network under the cursor: True, or False on none."""
        pane = self.pane
        if not pane.material_model or index is None or not index.isValid():
            return False
        ids = pane.loading.selected_material_ids(index)
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

    @staticmethod
    def _viewer_selection():
        """(viewer, object, prim): the ONE object or prim selected in the viewer ▸r/viewer-selection"""
        from amaze.core import dragengine, scene_captures
        viewer = scene_captures.scene_viewer()    # the one Capture Image takes
        world = dragengine.viewer_world(viewer) if viewer is not None else None
        if world == "obj":    # as Houdini's own object tools read it: the selected object nodes
            objects = [node for node in hou.selectedNodes()
                       if node.type().category() == hou.objNodeTypeCategory()]
            return (viewer, objects[0], "") if len(objects) == 1 else None
        if world == "lop":
            prims = viewer.currentSceneGraphSelection()
            return (viewer, None, prims[0]) if len(prims) == 1 else None
        return None

    def swap_offered(self, indexes, current) -> bool:
        """One tile, and one object or prim selected in the scene viewer."""
        return len(indexes) == 1 and self._viewer_selection() is not None

    def menu_swap_material(self, indexes, current, payload=None) -> None:
        chosen = self._viewer_selection()    # read again: the selection may have changed since the menu opened
        ids = self.pane.loading.selected_material_ids(current) if current is not None else []
        if chosen is not None and len(ids) == 1:
            viewer, obj, prim = chosen
            self.pane.drop_placement.swap_material(viewer, ids, obj, prim)

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
        offered = renderers.offered(self.pane.prefs)
        every = None if len(offered) == len(renderers.ALL) else tuple(r.key for r in offered)    # All: the renderers switched on
        return (base.FilterEntry(self.ALL_ID, self.ALL_LABEL, every, self.FILTER_ALL_ICON),) + tuple(
            base.FilterEntry(renderer.key, renderer.label, renderer.key, renderer.icon)
            for renderer in offered)

    def can_save(self, nodes) -> bool:
        return bool(nodes) and all(    # a fresh handler per node: it remembers the last renderer
            nodes_mod.NodeHandler(self.pane.prefs).get_renderer_from_node(n)
            for n in nodes)

    def commit_save(self, nodes, node, answer) -> None:
        renderers = []
        failures = []
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
