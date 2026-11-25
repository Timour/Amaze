"""The drop placement: where a drop or a click creates nodes in Houdini, for one pane."""

import os

import hou

from amaze import messages
from amaze.core import debug, geo_library
from amaze.helpers import helpers, theme, wording


class DropPlacement:
    """Where one pane's drops create nodes; the pane holds it as `drop_placement`."""

    def __init__(self, pane) -> None:
        self.pane = pane

    @staticmethod
    def tile_index(section, key: str):
        """The section's grid index of the tile `key` names, or None; the rules read that index."""
        model, proxy = section.tile_models() if section is not None else (None, None)
        if model is None or proxy is None or not key:
            return None
        for row in range(model.rowCount()):
            if model.tile_key(row) == key:
                index = proxy.mapFromSource(model.index(row, 0))
                return index if index.isValid() else None
        return None

    def release(self, section_key: str, key: str, pane_tab=None, pane_kind=None) -> bool:
        """Tile `key` released over Houdini: True, or False for a miss; one undo step."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        from amaze.sections import base as section_base
        section = self.pane.sections.get(section_key)
        index = self.tile_index(section, key)
        rule = section_base.drop_rule(section, self.pane, index) if index is not None else None
        if rule is None:
            return False
        helpers.forget_placed()
        try:
            with dragengine.holding_drop_group():    # the handler, its placement and the splice
                outcome = self._apply_drop_rule(rule, section, index, pane_tab, pane_kind)
                if outcome:
                    self._splice_if_on_a_wire(pane_tab)
        except hou.PermissionError as refusal:    # a locked network; any other error is a bug and raises
            return self._refused(refusal, section_key)
        return outcome

    @staticmethod
    def _refused(refusal, section_key: str) -> bool:
        """A locked network refused the drop: logged, and shown in Houdini's own words; False, a miss."""
        debug.exception("drop failed - permission error", refusal, section=section_key)
        debug.refuse(str(refusal), section=section_key)    # ▸p/refuse-vs-alert
        return False

    def _apply_drop_rule(self, rule, section, index, pane_tab, pane_kind) -> bool:
        """One order for every DropRule: on_node (result final), resolve, on_space ▸o/section-api"""
        from amaze.sections import base as section_base
        if rule.on_node is not None:
            node = self.node_under_cursor(pane_tab, pane_kind)
            if node is not None:
                return bool(section_base.drop_handler(section, rule.on_node)(index, node))
        if rule.resolve is not None:
            return bool(section_base.drop_handler(section, rule.resolve)(index))
        if rule.on_space is not None:
            net = self.network_under_release()
            if net is None:
                return section.reject_drop()
            create = section_base.drop_handler(section, rule.on_space)
            return bool(create(index, net, self.release_position_in(net)))
        return section.reject_drop()

    def _splice_if_on_a_wire(self, pane_tab=None) -> None:
        """Insert the nodes the drop placed into the wire under the cursor, else a free connector."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        placed = helpers.placed_nodes()
        if not placed:
            return
        editor = pane_tab or dragengine.pane_tab_under_cursor()
        net = self.network_under_release()
        spot = self.release_position_in(net) if net is not None else None
        wire, _name, _index = dragengine.wire_under_cursor(editor, spot, exclude=placed)
        if wire is not None:
            dragengine.splice_into_wire(wire, placed, editor)
            return
        dragengine.connect_to_neighbour(    # a lone node or a chain's end has a connector near the cursor
            dragengine.connector_under_cursor(editor, spot, exclude=placed), placed, editor)

    def scene_path(self, path: str) -> str:
        """A path Amaze writes into the scene, spelled per Write Paths As; never for loads."""
        return helpers.houdini_path(
            path, getattr(self.pane.prefs, "path_style", "home"))

    @staticmethod
    def is_sop_container(node: hou.Node) -> bool:
        """True for anything whose children are SOPs: a drop-into target for a geometry file."""
        try:
            category = node.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return False
        return category is not None and category.name() == "Sop"

    @staticmethod
    def create_loader_inside(container: hou.Node, loader_type: str):
        """Create the loader in the deepest SOP network under the container, else a higher one."""
        candidates = []

        def walk(node, depth):
            try:
                category = node.childTypeCategory()
            except (AttributeError, hou.OperationFailed):
                category = None
            if category is not None and category.name() == "Sop":
                candidates.append((depth, node))
            if depth < 3:
                for child in node.children():
                    walk(child, depth + 1)

        walk(container, 0)
        last_error = None
        for _depth, net in sorted(candidates, key=lambda c: -c[0]):    # deepest first; a locked level raises
            try:
                return net.createNode(loader_type)
            except hou.Error as exc:
                last_error = exc
        raise last_error or hou.OperationFailed("no SOP network found")

    @staticmethod
    def _network_items_at_cursor(editor):
        """Droppable items under the cursor in a network editor, as (item, ...) tuples."""
        try:
            if not editor.isUnderCursor():    # isUnderCursor() excludes the pane's own toolbars and controls
                return ()
            p = editor.posToScreen(editor.cursorPosition())
            r = theme.ui_px(2)
            return editor.networkItemsInBox(
                hou.Vector2(p.x() - r, p.y() - r),
                hou.Vector2(p.x() + r, p.y() + r),
                for_drop=True,
            )
        except (AttributeError, TypeError, hou.OperationFailed):
            return ()

    @staticmethod
    def pane_and_kind_under_cursor():
        """The pane tab under the cursor and its type, or (None, None); the caller compares the type."""
        from amaze.core import dragengine
        pane_tab = dragengine.pane_tab_under_cursor()
        if pane_tab is None:
            return None, None
        try:
            return pane_tab, pane_tab.type()
        except AttributeError:
            return None, None

    def node_under_cursor(self, pane_tab=None, pane_type=None) -> hou.Node | None:
        """The node under the cursor, or a Parameter Editor's node; pass the pane ▸p/drag-move-cost"""
        if pane_tab is None:
            pane_tab, pane_type = self.pane_and_kind_under_cursor()
        if pane_tab is None:
            return None
        if pane_type == hou.paneTabType.Parm:    # the node that pane shows
            try:
                return pane_tab.currentNode()
            except (AttributeError, hou.OperationFailed):
                return None
        if pane_type != hou.paneTabType.NetworkEditor:
            return None
        return self.first_node_at_cursor(pane_tab)

    def first_node_at_cursor(self, pane_tab) -> hou.Node | None:
        """The first hou.Node under the cursor, or None; the drop and click resolvers share it."""
        for item in self._network_items_at_cursor(pane_tab):
            candidates = (
                item if isinstance(item, (tuple, list)) else (item,)
            )
            for candidate in candidates:
                if isinstance(candidate, hou.Node):
                    return candidate
        return None

    def import_geo_in_context(
        self, path: str, dest: hou.Node | None
    ) -> hou.Node | None:
        from amaze.helpers import helpers
        base = os.path.basename(path)
        name = wording.sanitize_usd_path(os.path.splitext(base)[0]) or "geo"
        loader_type = geo_library.loader_sop_for(path)

        category = ""
        if dest is not None:
            try:
                cat_obj = dest.childTypeCategory()
                category = cat_obj.name() if cat_obj is not None else ""
            except (AttributeError, hou.OperationFailed):
                category = ""

        container = None  # created here; cleaned up if the import fails
        try:
            if category == "Sop":    # inside a SOP network: a loader SOP in place
                loader = dest.createNode(loader_type)
            elif category == "Lop":    # a new SOP Create holding the loader
                anchor = None
                try:
                    anchor = dest.displayNode()
                except (AttributeError, hou.OperationFailed):
                    anchor = None
                if anchor is not None:
                    container = anchor.createOutputNode("sopcreate", name)    # chained onto the display node
                else:
                    container = dest.createNode("sopcreate", name)
                loader = self.create_loader_inside(container, loader_type)
            elif category == "Object":    # a new geo named after the file
                container = dest.createNode("geo", name)
                loader = container.createNode(loader_type)
            else:    # a network that holds no geometry: a fresh geo at /obj
                obj = hou.node("/obj")
                if obj is None:
                    raise hou.OperationFailed("no /obj network")
                container = obj.createNode("geo", name)
                loader = container.createNode(loader_type)
        except hou.Error as exc:    # hou.Error: a locked asset raises PermissionError, not OperationFailed
            if container is not None:
                try:
                    container.destroy()
                except (hou.OperationFailed, hou.ObjectWasDeleted):
                    pass
            debug.event("import", "geometry import failed",
                        file=base, error=str(exc))
            debug.refuse(messages.GEOMETRY_IMPORT_FAILED % (base, exc))    # ▸p/refuse-vs-alert
            return
        parm = helpers.find_file_parm(loader)
        if parm is None:
            try:
                (container or loader).destroy()
            except (hou.OperationFailed, hou.ObjectWasDeleted):
                pass
            debug.refuse(messages.LOADER_SOP_HAS_NO_FILE_PARM % loader_type)
            return
        parm.set(self.scene_path(path))
        try:
            loader.setName(name, unique_name=True)
        except hou.OperationFailed:
            pass
        loader.setDisplayFlag(True)
        try:
            loader.setRenderFlag(True)
        except AttributeError:
            pass
        helpers.auto_place(loader)
        if container is not None:
            helpers.auto_place(container)
            try:
                container.setDisplayFlag(True)    # createOutputNode wires but does not flag
            except (AttributeError, hou.Error):
                pass
        made = container or loader
        made.setCurrent(True, True)    # current and selected, as a node from the Tab menu is
        return made

    def context_under_cursor(
        self, matcher, include_viewports: bool = False    # a type-name substring, or a callable(node) -> bool
    ) -> hou.Node | None:
        """Where a drag was released: the matching node under the cursor, else the pwd, else None."""
        pane_tab, pane_type = self.pane_and_kind_under_cursor()
        if pane_tab is None:
            return None
        if (
            include_viewports    # a drop on a Scene Viewer returns the viewer's pwd
            and pane_type == hou.paneTabType.SceneViewer
        ):
            try:
                return pane_tab.pwd()
            except AttributeError:
                return None
        if pane_type != hou.paneTabType.NetworkEditor:    # only a network editor takes node drops
            return None
        node = self.first_node_at_cursor(pane_tab)
        if node is not None:
            hit = (
                matcher(node)
                if callable(matcher)
                else matcher in node.type().name()
            )
            if hit:
                return node
        try:
            return pane_tab.pwd()
        except AttributeError:
            return None

    def import_materials_for_viewer(self, viewer, world: str, ids):
        """Materials dragged into an "obj" or "lop" viewer, where its own drop finds them; the pressed one."""
        try:
            with hou.undos.group("Amaze Import Materials"):    # a library made for them and the imports: one step
                if world == "obj":
                    return self.pane.loading.import_materials_to_mat(ids)
                return self._import_for_lop_viewer(viewer, ids)
        except hou.PermissionError as refusal:    # a locked network, as at a release
            self._refused(refusal, "material")
            return None

    def _import_for_lop_viewer(self, viewer, ids):
        """Into the library LOP Houdini's drop picks for the node the viewer shows ▸r/solaris-material-drag"""
        from amaze.core import dragengine
        stock = dragengine.stock_lop()
        if stock is None:
            debug.refuse(messages.STOCK_LOP_HELPERS_UNAVAILABLE)    # ▸p/refuse-vs-alert
            return None
        lopnet = viewer.pwd()
        shown = lopnet.displayNode()
        if shown is None:
            children = lopnet.children()
            shown = children[-1] if children else None
        imported = self._import_into_library_lop(stock, lopnet, shown, ids)
        return imported[2] if imported is not None else None

    def _import_into_library_lop(self, stock, lopnet, target_lop, ids):
        """`ids` imported into Houdini's own pick of library LOP: (anchor, library, pressed VOP), or None."""
        from amaze.helpers import helpers
        before = set(lopnet.children())
        try:    # Houdini's own library picker ▸r/houdini-after-create
            if target_lop is not None:
                anchor, liblop, _vop = stock.getMaterialLibraryLop(target_lop)
            else:    # an empty network: a Material Library LOP as Houdini's code makes it, unwired
                liblop = lopnet.createNode("materiallibrary")
                helpers.auto_place(liblop)
                liblop.setDisplayFlag(True)
                liblop.setCurrent(True, True)
                anchor = liblop
        except hou.Error as refusal:    # a locked asset raises PermissionError, not OperationFailed
            debug.event("drag", "material library not created "
                        "in the network", dest=lopnet.path(),
                        error=str(refusal))
            debug.refuse(messages.NETWORK_REFUSED_MATERIAL_LIBRARY
                         % (lopnet.name(), refusal))
            return None
        pressed_vop = self.pane.loading.import_material_into_container(ids[0], liblop)
        if pressed_vop is None:    # its reason is shown; a library made for it goes too
            for made in set(lopnet.children()) - before:
                made.destroy()
            return None
        for aid in ids[1:]:
            self.pane.loading.import_material_into_container(aid, liblop)
        debug.event("drag", "materials imported into a library LOP", imported=len(ids),
                    library=liblop.path())
        return anchor, liblop, pressed_vop

    def swap_material(self, viewer, ids, obj, prim: str) -> None:
        """The pressed material in place of the one on `obj`, else bound to `prim`: one undo step."""
        from amaze.core import dragengine, lop_assign
        try:
            with hou.undos.group("Amaze Swap Material"):
                if obj is not None:    # its Material parameter, the material imported into /mat
                    self.pane.loading.assign_material_to_obj(ids[:1], obj)
                    return
                stock = dragengine.stock_lop()
                if stock is None:
                    debug.refuse(messages.STOCK_LOP_HELPERS_UNAVAILABLE)    # ▸p/refuse-vs-alert
                    return
                lopnet = viewer.pwd()
                children = lopnet.children()
                shown = lopnet.displayNode() or (children[-1] if children else None)
                bound = lop_assign.bound_materials_under(    # the nearest binding and every one below
                    shown.stage() if shown is not None else None, prim)
                if not bound:    # checked first: nothing is imported for a prim with no material
                    debug.refuse(messages.NOTHING_TO_SWAP % prim)
                    return
                self._assign_dropped(stock, lopnet, shown, ids, ("swap", "", bound))
        except hou.PermissionError as refusal:    # a locked network, as at a release
            self._refused(refusal, "material")

    def _assign_dropped(self, stock, lopnet, target_lop, ids, choice) -> bool:
        """A `drop_choices` row: import into a library LOP, then assign or swap; for Swap Material."""
        from amaze.core import lop_assign
        kind, _label, payload = choice
        assign_path = payload if kind == "assign" else None
        swap_targets = payload if kind == "swap" else None
        undo_label = (
            "Amaze Swap Material" if swap_targets is not None
            else "Amaze Assign Material"
        )
        with hou.undos.group(undo_label):    # the library, the import and the assign revert as one step
            ids = list(ids)[:1] if swap_targets is not None else list(ids)    # a swap replaces one
            imported = self._import_into_library_lop(stock, lopnet, target_lop, ids)
            if imported is None:
                return False
            node2, liblop, pressed_vop = imported
            debug.event("drag", "lop assign", assign=str(assign_path),
                        swap=bool(swap_targets))
            if swap_targets is not None:
                reason = lop_assign.swap_assignments(    # lop_assign edits the USD and returns a reason; the pane shows it
                    stock, lopnet, liblop, node2, swap_targets,
                    pressed_vop
                )
                if reason:
                    debug.refuse(reason)
            elif assign_path:
                try:
                    matpath = stock.getMaterialPrimPathForNode(
                        liblop, pressed_vop
                    )
                    before = {
                        n for n in lopnet.children()
                        if n.type().name() == "assignmaterial"
                    }
                    stock.assignMat(assign_path, str(matpath), node2)
                    lop_assign.name_new_assign(lopnet, before, assign_path)
                except Exception as exc:
                    debug.event("drag", "lop assign failed", error=str(exc))
                    debug.refuse(messages.MATERIAL_ASSIGN_FAILED % exc)
        return True

    def import_materials_into_context(self, context, ids,
                                      position=None) -> None:
        """Network-release material import, one undo step; a `position` cascades the copies from it."""
        from amaze.core import dragengine
        with dragengine.drop_group("Amaze Import Materials"):
            self.pane.loading.import_materials_into_context_grouped(
                context, ids, position)

    def network_under_release(self) -> hou.Node | None:
        """The network of a drop that hit no node, or None outside a network editor."""
        return self.context_under_cursor(lambda _node: False)

    def release_position_in(self, net):
        """The release position, only when the editor under the cursor shows `net`; else None."""
        from amaze.core import dragengine
        pane_tab = dragengine.pane_tab_under_cursor()
        if pane_tab is None or net is None:
            debug.event("interact", "no drop point - no editor under "
                        "the cursor", net=net.path() if net else None)
            return None
        try:
            if pane_tab.type() != hou.paneTabType.NetworkEditor:
                return None
            if pane_tab.pwd() != net:    # the editor under the cursor shows another network
                debug.event("interact", "no drop point - the editor "
                            "shows another network",
                            showing=pane_tab.pwd().path(),
                            destination=net.path())
                return None
            spot = dragengine.ghost_snap_position() \
                or pane_tab.cursorPosition()    # the drag preview showed the snapped point, so the node goes there
            debug.event("interact", "drop point",
                        at=[round(spot.x(), 3), round(spot.y(), 3)],
                        net=net.path())
            return spot
        except AttributeError:
            return None

    def create_holder_node(self, dest, type_name: str, name: str, position, find_parm, value,
                           label: str) -> bool:
        """A `type_name` node in `dest` holding `value` in its `find_parm` parm, one undo step."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        try:
            category = dest.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return False
        if category is None or hou.nodeType(category, type_name) is None:
            debug.event("interact", "no holder node type for this network",
                        holder=type_name, dest=dest.path())
            return False
        with dragengine.drop_group(label):
            try:
                node = dest.createNode(type_name)
            except hou.Error as refusal:    # a locked network raises PermissionError
                debug.refuse(messages.HOLDER_NOT_MADE % (type_name, dest.path(), refusal))
                return False
            parm = find_parm(node)
            try:
                if parm is None:
                    raise hou.OperationFailed("it has no parameter to hold it")
                parm.set(value)
            except hou.Error as refusal:    # the node it made is not left behind
                node.destroy()
                debug.refuse(messages.HOLDER_NOT_MADE % (type_name, dest.path(), refusal))
                return False
            if name:
                try:
                    node.setName(name, unique_name=True)
                except hou.OperationFailed:
                    pass
            if position is None:    # auto-place only without a position
                helpers.auto_place(node)
            else:
                helpers.place_nodes([node], position)
        debug.event("interact", "holder node created", holder=type_name, dest=dest.path())
        return True
