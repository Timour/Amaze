"""The drop placement: where a release or a click lands in Houdini, for one panel."""

import os

from PySide6 import QtWidgets, QtGui
import hou

from amaze import messages
from amaze.core import debug, geo_library
from amaze.helpers import helpers, wording


class DropPlacement:
    """Where one panel's releases land; the panel holds it as `drop_placement`."""

    def __init__(self, panel) -> None:
        self.panel = panel

    def scene_path(self, path: str) -> str:
        """A path Amaze writes into the scene, spelled per Write Paths As; never for loads."""
        return helpers.houdini_path(
            path, getattr(self.panel.prefs, "path_style", "home"))

    @staticmethod
    def is_sop_container(node: hou.Node) -> bool:
        """True for anything whose children are SOPs: a drop-into target for a geometry file."""
        try:
            category = node.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return False
        return category is not None and category.name() == "Sop"

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
                loader = self.panel.create_loader_inside(container, loader_type)
            elif category == "Object":    # a new geo named after the file
                container = dest.createNode("geo", name)
                loader = container.createNode(loader_type)
            else:    # a network that holds no geometry: a fresh geo at /obj
                obj = hou.node("/obj")
                if obj is None:
                    raise hou.OperationFailed("no /obj network")
                container = obj.createNode("geo", name)
                loader = container.createNode(loader_type)
        except hou.Error as exc:    # hou.Error: a locked asset raises PermissionError, a sibling
            if container is not None:
                try:
                    container.destroy()
                except (hou.OperationFailed, hou.ObjectWasDeleted):
                    pass
            debug.event("import", "geometry import failed",
                        file=base, error=str(exc))
            debug.refuse(messages.GEOMETRY_IMPORT_FAILED % (base, exc))    # ▸p/refusal-sink
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
        pane_tab, pane_type = self.panel.pane_and_kind_under_cursor()
        if pane_tab is None:
            return None
        if (
            include_viewports    # a viewport release resolves to its pwd
            and pane_type == hou.paneTabType.SceneViewer
        ):
            try:
                return pane_tab.pwd()
            except AttributeError:
                return None
        if pane_type != hou.paneTabType.NetworkEditor:    # the canvas takes no native node drops
            return None
        node = self.panel.first_node_at_cursor(pane_tab)
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

    def material_lop_viewport_drop(self, ids, viewer, primpath) -> bool:
        """LOP-viewport release: the prim menu, then import and assign through Houdini's stock helpers."""
        from amaze.core import dragengine, lop_assign
        from amaze.helpers import helpers
        stock = dragengine.stock_lop()
        if stock is None:
            debug.refuse(messages.STOCK_LOP_HELPERS_UNAVAILABLE)    # ▸p/refusal-sink
            return False
        try:
            lopnet = viewer.pwd()
        except AttributeError:
            return False
        target_lop = lopnet.displayNode()
        if target_lop is None:
            children = lopnet.children()
            target_lop = children[-1] if children else None

        stage = target_lop.stage() if target_lop is not None else None
        choices = lop_assign.drop_choices(stage, primpath)    # what to offer is lop_assign's
        if not choices:
            return False
        cmenu = QtWidgets.QMenu(self.panel)
        actions = {}
        previous_kind = None
        for kind, label, payload in choices:
            if previous_kind == "swap" and kind != "swap":
                cmenu.addSeparator()
            actions[cmenu.addAction(label)] = (kind, payload)
            previous_kind = kind
        chosen = cmenu.exec(QtGui.QCursor.pos())    # screen coordinates
        cmenu.deleteLater()    # parented to the panel, so deleted; `actions` keeps its keys until then
        if chosen is None:
            return False    # dismissed: nothing happens
        kind, payload = actions[chosen]
        assign_path = payload if kind == "assign" else None
        swap_targets = payload if kind == "swap" else None
        undo_label = (
            "Amaze Swap Material" if swap_targets is not None
            else "Amaze Assign Material"
        )
        with hou.undos.group(undo_label):    # the library, the import and the assign revert as one step
            try:    # Houdini's own library picker and its own assign ▸r/houdini-after-create
                if target_lop is not None:
                    node2, liblop, _vop = stock.getMaterialLibraryLop(target_lop)
                else:    # an empty network: the library Houdini's own branch makes, unwired
                    liblop = lopnet.createNode("materiallibrary")
                    helpers.auto_place(liblop)
                    liblop.setDisplayFlag(True)
                    liblop.setCurrent(True, True)
                    node2 = liblop
            except hou.Error as refusal:    # a locked asset raises PermissionError, a sibling
                debug.event("drag", "the network refused a material "
                            "library", dest=lopnet.path(),
                            error=str(refusal))
                debug.refuse(messages.NETWORK_REFUSED_MATERIAL_LIBRARY
                             % (lopnet.name(), refusal))
                return False
            if swap_targets is not None:
                ids = list(ids)[:1]    # a swap replaces one material
            vops = []
            imported = []    # (asset id, vop) for the imports that succeeded
            for aid in ids:
                vop = self.panel.import_material_into_container(aid, liblop)
                if vop is not None:
                    imported.append((aid, vop))
                    vops.append(vop)
            pressed_vop = None
            if imported and ids and imported[0][0] == ids[0]:
                pressed_vop = imported[0][1]
            elif imported:
                debug.refuse(messages.DROPPED_MATERIAL_IMPORT_FAILED)
            debug.event("drag", "lop viewport drop", imported=len(vops),
                        amaze=liblop.path(), assign=str(assign_path),
                        swap=bool(swap_targets))
            if pressed_vop is not None and swap_targets is not None:
                reason = lop_assign.swap_assignments(    # the module does the USD and reports; the panel says it
                    stock, lopnet, liblop, node2, swap_targets,
                    pressed_vop
                )
                if reason:
                    debug.refuse(reason)
            elif assign_path and pressed_vop is not None:
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
        return bool(vops)

    def import_materials_into_context(self, context, ids,
                                      position=None) -> None:
        """Network-release material import, one undo step; a `position` cascades the copies from it."""
        from amaze.core import dragengine
        with dragengine.drop_group("Amaze Import Materials"):
            self.panel.import_materials_into_context_grouped(
                context, ids, position)

    def network_under_release(self) -> hou.Node | None:
        """The network a no-node release happened inside, or None off any editor."""
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
            if pane_tab.pwd() != net:    # cross-space: the cursor is in another plane
                debug.event("interact", "no drop point - the editor "
                            "shows another network",
                            showing=pane_tab.pwd().path(),
                            destination=net.path())
                return None
            spot = dragengine.ghost_snap_position() \
                or pane_tab.cursorPosition()    # the ghost promised the SNAPPED point, so the release lands there
            debug.event("interact", "drop point",
                        at=[round(spot.x(), 3), round(spot.y(), 3)],
                        net=net.path())
            return spot
        except AttributeError:
            return None

    def create_carrier(self, dest, type_name: str, name: str,
                       position=None):
        """Create `type_name` in `dest` if it can hold one, else None; the caller owns the undo group."""
        from amaze.helpers import helpers
        if dest is None:
            return None
        try:
            category = dest.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return None
        if category is None or hou.nodeType(category, type_name) is None:
            debug.event("interact", "no carrier for this network",
                        carrier=type_name, dest=dest.path())
            return None
        try:
            node = dest.createNode(type_name)
        except hou.Error as refusal:    # Houdini's refusal is logged; the walk moves on
            debug.event("interact", "the network refused the carrier",
                        carrier=type_name, dest=dest.path(),
                        error=str(refusal))
            return None
        if name:
            try:
                node.setName(name, unique_name=True)
            except hou.OperationFailed:
                pass
        if position is None:    # auto-place only without a position
            helpers.auto_place(node)
        else:
            helpers.place_nodes([node], position)
        debug.event("interact", "carrier created", carrier=type_name,
                    dest=dest.path())
        return node
