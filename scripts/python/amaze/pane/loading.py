"""Library assets put into the scene: a click on a row, Load Asset, a generated material."""

import hou

from amaze import messages
from amaze.actions import materials as material_actions
from amaze.actions import nodes as node_actions
from amaze.core import debug, grid_columns
from amaze.sections import base as section_base
from amaze.render import nodes


class Loading:
    """What a double-click and Load Asset do in the scene; the pane holds it as `loading`."""

    def __init__(self, pane) -> None:
        self.pane = pane

    def click_on_row(self, section, index, payload=None) -> None:
        """A double-click or its menu entry on `index`, applied per `section`'s rule."""
        if index is None or not index.isValid():
            return
        rule = section_base.drop_rule(section, self.pane, index)    # the same rule lookup a drag uses
        if rule is None:
            self._cannot_load_here()
            return
        try:
            applied = self._apply_click_rule(section, rule, index,
                                             payload)    # the menu entry's extra argument
        except hou.PermissionError as refusal:    # only this class; anything else still raises
            debug.exception("click failed - permission error", refusal,
                            section=getattr(section, "key", ""))
            debug.refuse(str(refusal),    # ▸p/refuse-vs-alert
                         section=getattr(section, "key", ""))
            return
        if not applied:
            self._cannot_load_here()

    def _apply_click_rule(self, section, rule, index, payload=None) -> bool:
        """One selected node gets the payload first; if it cannot use it, a node is created."""
        extra = {"basis": payload} if payload else {}    # only when there is one
        sel = self._visible_selected_nodes()
        if rule.click_on_node and len(sel) == 1:
            hint = section_base.drop_handler(section, rule.click_on_node)    # the handlers a rule names resolve on the SECTION
            if bool(hint(index, sel[0], **extra)):
                return True
            debug.event("interact", "the selected node did not accept the payload - "
                        "trying the network",
                        handler=rule.click_on_node, node=sel[0].path())
        if rule.click_resolve:
            handler = section_base.drop_handler(section, rule.click_resolve)
            return bool(handler(index, **extra))
        if rule.on_space:
            create = section_base.drop_handler(section, rule.on_space)
            for network in self._view_create_networks():
                if create(index, network, **extra):
                    return True
        return False

    def _cannot_load_here(self) -> None:
        ui = getattr(hou, "ui", None)
        if ui is not None:
            ui.displayMessage(messages.CANNOT_LOAD_HERE,
                              title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)  # type: ignore

    def _visible_selected_nodes(self) -> list:
        """Selected nodes in a visible editor's network, for the click actions ▸r/matlib-entries"""
        networks = self._view_create_networks()
        every = hou.selectedNodes()
        sel = [node for node in every if node.parent() in networks]
        debug.event("interact", "click_on_row selection",
                    visible=len(sel), total=len(every),
                    networks=len(networks))
        return sel

    def _view_create_networks(self) -> list:
        """Every visible network editor's pwd, current tabs first; create in the first that can hold it."""
        networks = []
        for editor in nodes.NodeHandler.network_editors():
            try:
                pwd = editor.pwd()
            except AttributeError:
                continue
            if pwd is not None and pwd not in networks:
                networks.append(pwd)
        return networks

    def _active_network_pwd(self) -> hou.Node | None:
        """The pwd of the network editor the user most likely looks at, or None."""
        editors = nodes.NodeHandler.network_editors()
        try:
            return editors[0].pwd() if editors else None
        except AttributeError:
            return None

    def import_materials(self, target: str = "auto") -> None:
        """Import the selected materials: `target` "auto" follows the network, "mat"/"lop" force one."""
        pane = self.pane
        if not pane.material_model or not pane.category_model:
            return
        self._import_selection(
            pane.material_sorted_model, pane.material_model,
            lambda model, index: material_actions.import_asset_to_scene(model, index, target),
            "Amaze Import Materials", messages.NAMELESS_MATERIAL,
            messages.MATERIALS_IMPORT_FAILURES)

    def import_cop_assets(self) -> None:
        """Import every selected Node tile; failures are listed in one dialog."""
        pane = self.pane
        self._import_selection(
            pane.cop_sorted_model, pane.cop_model, node_actions.import_asset_to_scene,
            "Amaze Import Nodes Asset", messages.NAMELESS_NODE_ASSET,
            messages.NODE_ASSETS_IMPORT_FAILURES)

    def _import_selection(self, proxy, model, import_asset, label: str, noun: str, summary: str) -> None:
        """Each selected tile through `import_asset(model, source_index)`: ONE undo entry, one dialog."""
        context = self.pane.active_section()
        selection = context.grid_selection_model() if context is not None else None    # the grid's
        failures = []
        with hou.undos.group(label):    # the containers and what loads into them revert as one step
            for index in grid_columns.selected_rows(selection):
                source_index = proxy.mapToSource(index)
                try:
                    ok, reason, _created = import_asset(model, source_index)
                except Exception as e:    # a failing tile is added to the report; the rest still import
                    try:
                        name = model.assets[source_index.row()].name
                    except Exception:
                        name = noun
                    failures.append(messages.ASSET_FAILED_TO_IMPORT_LINE % (name, e))
                    continue
                if not ok and reason:
                    failures.append(reason)
        ui = getattr(hou, "ui", None)
        if failures and ui is not None:
            ui.displayMessage(summary, details="\n".join(failures),
                              title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)

    def import_geo_asset(self, index) -> None:
        """Import a geometry file into the network editor's current network, per its kind."""
        path = index.data(self.pane.file_files_model.PathRole)
        if not path:
            return
        self.pane.drop_placement.import_geo_in_context(path, self._active_network_pwd())

    def _import_material_builder(self, asset_id, target, context_node=None):
        """Import a library material by id on a drop; the builder VOP, or None once reported."""
        pane = self.pane
        if not pane.material_model:
            return None
        row = pane.material_model.find_asset_row_by_id(str(asset_id))
        if row < 0:
            return None
        mat = pane.material_model.assets[row]
        handler = nodes.NodeHandler(pane.prefs)
        ok, reason, _created = handler.import_asset_to_scene(
            mat, target, context_node=context_node
        )
        if not ok:
            debug.event("import", "import failed",    # always a named reason
                        material=mat.name, target=target,
                        reason=reason or "(no reason reported)")
            if reason:
                debug.refuse(reason)    # the import marks library damage, which shows the dialog ▸p/refuse-vs-alert
            return None
        return handler.builder_node

    def import_material_into_container(self, asset_id, container):
        """For a drop in a LOP viewport: import into the given materiallibrary."""
        return self._import_material_builder(
            asset_id, "lop", context_node=container
        )

    def assign_material_to_obj(self, asset_ids, obj_node) -> bool:
        """Drop in an OBJ viewport: import to /mat, assigning the first material to `obj_node`."""
        if not self.pane.material_model or not asset_ids:
            return False
        builder = None
        for i, aid in enumerate(asset_ids):
            vop = self._import_material_builder(aid, "mat")
            if i == 0 and vop is not None:
                builder = vop
        if builder is None:
            return False
        parm = obj_node.parm("shop_materialpath")
        if parm is None:
            debug.refuse(messages.OBJECT_HAS_NO_MATERIAL_PARM % obj_node.name())
            return False
        parm.set(builder.path())
        return True

    def selected_material_ids(self, index) -> list:
        """Asset ids of the selection, the pressed tile first."""
        pane = self.pane
        row = pane.material_sorted_model.mapToSource(index).row()    # may be -1 for a stale index ▸r/model-contracts
        if not 0 <= row < len(pane.material_model.assets):
            return []
        pressed_id = pane.material_model.assets[row].mat_id
        ids = [pressed_id]
        try:
            for sel in grid_columns.selected_rows(
                    pane.material_selection_model):
                src_row = pane.material_sorted_model.mapToSource(sel).row()
                if not 0 <= src_row < len(pane.material_model.assets):
                    continue      # same stale-row check, per selected row
                aid = pane.material_model.assets[src_row].mat_id
                if aid != pressed_id:
                    ids.append(aid)
        except Exception:
            pass
        return ids

    def import_materials_into_context_grouped(self, context, ids,
                                               position=None) -> None:
        """Import materials `ids` into `context`, cascading from `position`; one failure stops it."""
        from amaze.helpers import helpers
        model = self.pane.material_model
        for offset, aid in enumerate(ids):
            row = model.find_asset_row_by_id(aid)
            if row < 0:
                continue
            idx = model.index(row, 0)
            ok, reason, created = material_actions.import_asset_to_scene(
                model, idx, "auto", context_node=context
            )
            if not ok and reason:
                debug.refuse(reason, net=context.path())    # library damage shows the dialog ▸p/refuse-vs-alert
                break    # ONE failure message per multi-drop, never one per asset ▸p/dialogs-interrupt
            if position is not None:
                helpers.place_nodes(created, hou.Vector2(
                    position.x() + offset * 0.6,
                    position.y() - offset * 0.9))

    def generate_random_material(self) -> None:
        """One random plausible material, built in the scene's material network, not the library."""
        from amaze.render import generator
        builder = None
        destination = None
        ui = getattr(hou, "ui", None)
        with hou.undos.group("Amaze Generate Material"):    # ONE undo step with the library it may create ▸r/node-items
            destination = nodes.karma_destination(self.pane.prefs)
            if destination is None:
                if ui is not None:
                    ui.displayMessage(
                        messages.NO_MATERIAL_DESTINATION_NETWORK,
                        title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                    )
                return
            staging = hou.node("/obj").createNode("matnet")    # built in staging, moved in one step ▸r/matlib-entries
            try:
                builder, spec = generator.generate_random_material(staging)
                if builder is None:
                    if ui is not None:
                        ui.displayMessage(
                            messages.MATERIAL_GENERATION_FAILED,
                            title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                        )
                    return
                builder, registered = nodes.place_built(builder, destination)    # as an import is
                if builder is None:
                    debug.event("generate", "move failed",
                                destination=destination.path())
                    if ui is not None:
                        ui.displayMessage(
                            messages.GENERATED_MATERIAL_MOVE_FAILED % destination.path(),
                            title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                        )
                    return
                builder.setCurrent(True, True)    # current and selected, as a node from the Tab menu is
                debug.event("generate", "random material",
                            name=builder.name(),
                            destination=destination.path(),
                            registered=registered,
                            spec={
                                k: ([round(c, 3) for c in v]
                                    if isinstance(v, (list, tuple))
                                    else round(v, 3))
                                for k, v in spec.items()
                            },
                            provenance=builder.comment())
                if not registered and ui is not None:
                    ui.displayMessage(
                        messages.GENERATED_MATERIAL_NOT_REGISTERED % (builder.name(), destination.path()),
                        title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                    )
            except hou.Error as exc:
                builder = None
                debug.event("generate", "failed", error=str(exc))
                if ui is not None:
                    ui.displayMessage(
                        messages.MATERIAL_GENERATION_ERROR % exc,
                        title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                    )
            finally:
                staging.destroy()
        if builder is not None and ui is not None:
            ui.setStatusMessage(
                "Amaze: generated %s in %s"
                % (builder.name(), destination.path())
            )
