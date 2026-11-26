"""Drop into the scene: one test per requirement in docs/requirements/drop-into-scene.md."""

import contextlib
import functools
import os
import shutil
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtQuick, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import messages  # noqa: E402
from amaze.tests import test_support  # noqa: E402

try:    # without Houdini every test here skips
    import hou
    from pxr import UsdShade
    from amaze.core import debug, dragengine, lop_assign, scene_captures
    from amaze.helpers import helpers
    from amaze.pane import drag_session, drop_placement, loading, menus
    from amaze.qml import pane as qml_pane
    from amaze.render import nodes
    from amaze.sections import code as code_section, file as file_section, material as material_section
except ImportError:
    hou = None

CUBE = os.path.join(test_support.FILES_FIXTURE_DIR, "cube.bgeo")


def _host_insert(conn, chain, _every, remove_existing_connections=False):
    """What `insertItemsIntoWire` does for one chain, in its own group; the real one needs `hou.ui`."""
    with hou.undos.group("Insert items"):
        chain[0].setInput(0, conn.inputItem(), conn.inputItemOutputIndex())
        conn.outputItem().setInput(conn.inputIndex(), chain[-1])


class _Snippets(QtCore.QAbstractListModel):
    """The part of the code model a drop reads: one row per snippet, keyed by its id."""

    def __init__(self, assets):
        super().__init__()
        self.assets = assets

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self.assets)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        return self.assets[index.row()].name if role == QtCore.Qt.ItemDataRole.DisplayRole else None

    def tile_key(self, row: int) -> str:
        return self.assets[row].mat_id


HOUDINI_QT = types.SimpleNamespace(    # hou.qt, absent headless: what Houdini's drop script reads of it
    Icon=lambda *args, **kwargs: None,
    mimeType=types.SimpleNamespace(nodePath="application/sidefx-houdini-node.path",
                                   asset="application/sidefx-houdini-asset",
                                   usdPrimitivePath="application/sidefx-houdini-usd-primitive-path",
                                   galleryEntry="application/sidefx-houdini-gallery.entry.name"))


def _nodegraph(insert=None):
    """`nodegraphutils`, which needs `hou.ui`: no overlap moves, and `insert` for a wire splice."""
    module = types.ModuleType("nodegraphutils")
    module.insertItemsIntoWire, module.moveNodesToAvoidOverlap = insert, lambda *args, **kwargs: None
    return module


@functools.cache
def _houdini_drop_script():
    """Houdini's own `lop_dragdrop.py`, loaded once with the `hou.qt` its imports read."""
    with mock.patch.object(hou, "qt", HOUDINI_QT, create=True):
        return dragengine._load_stock_lop.__wrapped__()    # not the engine's cached load, made with none


class _Viewer:
    """A scene viewer showing `network`, the cursor at one point of it, over `under` there or nothing."""

    LOCAL, HEIGHT = QtCore.QPoint(40, 100), 300    # the cursor in the viewer's window, top-left origin
    POINT = (40, 200)    # the same point from the bottom left, as Houdini's picks take it

    def __init__(self, network, under=None, chosen=()):
        self.network, self.under, self.lit, self.chosen = network, under, [], list(chosen)
        window = types.SimpleNamespace(mapFromGlobal=lambda _cursor: self.LOCAL, height=lambda: self.HEIGHT)
        self.qtWindow = lambda: window
        self.viewport = types.SimpleNamespace(geometry=lambda: (0, 0, 400, self.HEIGHT),
                                              queryNodeAtPixel=self.node_at)

    def pwd(self):
        return self.network

    def viewports(self):
        return (self.viewport,)

    def curViewport(self):
        return self.viewport

    def locateSceneGraphPrim(self, x, y):
        hit = (x, y) == self.POINT and isinstance(self.under, str)
        return (1.0, self.under + "[3]") if hit else (-1.0, "")    # Houdini's own: a point instance's ids

    def node_at(self, x, y):
        return self.under if (x, y) == self.POINT and isinstance(self.under, hou.Node) else None

    def setSceneGraphHighlight(self, prims):
        self.lit.append(list(prims))

    def currentSceneGraphSelection(self):
        return list(self.chosen)    # the prims selected in the viewer


class _MenuHost:
    """The drop menu's host: it picks `label` (None dismisses) at once, as a modal one, or on `pick()`."""

    def __init__(self, label, at_once=True):
        self.label, self.at_once, self.offered, self.pick = label, at_once, [], None

    def ask_drop_choice(self, labels, then, at):
        self.offered, self.at = list(labels), at
        self.pick = lambda: then(labels.index(self.label) if self.label in labels else None)
        if self.at_once:
            self.pick()


class _Marks:
    """The name tag and the red X a drag shows, with no widgets: the red X is counted."""

    def __init__(self):
        self.misses = 0

    def show_tag(self, name):
        pass

    def move_tag(self):
        pass

    def tag_shown(self, shown):
        pass

    def hide_tag(self):
        pass

    def show_miss(self):
        self.misses += 1

    @staticmethod
    def tag_picture(name):
        return QtGui.QPixmap()


class _Editor:
    """A network editor whose drop radius holds `found()`: (item, connector name, index) each."""

    def __init__(self, found) -> None:
        self.found = found

    @staticmethod
    def posToScreen(position):
        return position

    @staticmethod
    def lengthToScreen(length):
        return length

    def networkItemsInBox(self, low, high, for_drop=False):
        return self.found()

    @staticmethod
    def itemRect(item, adjusted=True):
        return types.SimpleNamespace(contains=lambda position: False)


@unittest.skipUnless(hou, "Houdini is not loaded")
class _Drops(unittest.TestCase):
    """The pane's drop placement over a stub pane, what is refused recorded, a geo and a LOP network."""

    def setUp(self):
        self.refused, self.imported = [], []
        patcher = mock.patch.object(debug, "refuse", lambda reason, **k: self.refused.append(str(reason)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pane = types.SimpleNamespace(prefs=types.SimpleNamespace(path_style="home"))
        self.ids = ["dd_mat", "dd_other"]    # the selection a material drag carries, the pressed one first
        self.pane.loading = types.SimpleNamespace(import_material_into_container=self.material_into,
                                                  selected_material_ids=lambda index: list(self.ids))
        self.pane.material_model = _Snippets([types.SimpleNamespace(mat_id=aid, name=aid) for aid in self.ids])
        self.pane.material_sorted_model = QtCore.QIdentityProxyModel()
        self.pane.material_sorted_model.setSourceModel(self.pane.material_model)
        self.pane.category_model = self.pane.material_selection_model = object()
        self.placement = drop_placement.DropPlacement(self.pane)
        self.pane.drop_placement = self.placement
        self.pane.code_model = _Snippets([types.SimpleNamespace(
            mat_id="s1", name="tint", renderer="VEX", code="@Cd = {1, 0, 0};")])
        self.pane.code_sorted_model = QtCore.QIdentityProxyModel()
        self.pane.code_sorted_model.setSourceModel(self.pane.code_model)
        self.pane.code_category_model = self.pane.code_selection_model = object()
        self.pane.sections = {"code": code_section.CodeSection(self.pane),
                              "material": material_section.MaterialSection(self.pane)}
        self.geo = hou.node("/obj").createNode("geo", "dd_geo")
        self.lopnet = hou.node("/stage").createNode("lopnet", "dd_lop")
        self.sphere = self.lopnet.createNode("sphere")
        self.sphere.parm("primpath").set("/world/ball")
        self.sphere.setDisplayFlag(True)
        for node in (self.geo, self.lopnet):
            self.addCleanup(test_support.drop_node, node)
        self.addCleanup(hou.undos.clear)

    def material_into(self, asset_id, library):
        """The material import a drop asks for: a material in `library`, or None for `fails`."""
        self.imported.append(asset_id)
        if asset_id == "fails":
            return None
        made = library.createNode("subnet", asset_id)
        made.setGenericFlag(hou.nodeFlag.Material, True)
        return made

    def release(self, node=None, network=None, spot=None, wire=None):
        """The snippet released over `node`, or network space of `network` at `spot`, or a `wire`."""
        under = (wire, "", 0) if wire is not None else (None, "", -1)
        with mock.patch.object(self.placement, "node_under_cursor", return_value=node), \
                mock.patch.object(self.placement, "network_under_release", return_value=network), \
                mock.patch.object(self.placement, "release_position_in", return_value=spot), \
                mock.patch.object(dragengine, "wire_under_cursor", return_value=under), \
                mock.patch.object(dragengine, "connector_under_cursor", return_value=(None, "", -1)), \
                mock.patch.dict(sys.modules, {"nodegraphutils": _nodegraph(_host_insert)}):
            return self.placement.release("code", "s1", object(), hou.paneTabType.NetworkEditor)

    @contextlib.contextmanager
    def houdini_drop(self):
        """Houdini's own viewport drop script, run with what it needs of a UI headless."""
        script = _houdini_drop_script()    # first: the modules it loads must outlive the patch below
        with mock.patch.object(hou, "qt", HOUDINI_QT, create=True), \
                mock.patch.dict(sys.modules, {"nodegraphutils": _nodegraph()}), \
                mock.patch.object(dragengine, "stock_lop", return_value=script):
            yield

    def drag(self, viewer, host=None) -> int:
        """The material row dragged over `viewer` and released there: the red Xs shown."""
        self.pane.ui = host
        marks, kind = _Marks(), hou.paneTabType.SceneViewer
        session = drag_session.DragSession(QtWidgets.QWidget(), marks)
        self.addCleanup(session.cancel)
        with self.houdini_drop(), \
                mock.patch.object(dragengine, "pane_under_cursor_tracked", return_value=(viewer, kind, True)), \
                mock.patch.object(self.placement, "pane_and_kind_under_cursor", return_value=(viewer, kind)):
            session.begin(self.pane, "material", self.pane.material_sorted_model.index(0, 0), "dd_mat")
            session.move()
            session.release()
        return marks.misses

    @staticmethod
    def names(network) -> list:
        return sorted(child.name() for child in network.children())


class ADropIsWholeOrNothingTest(_Drops):

    def test_dd01_one_undo_takes_back_a_whole_drop(self):
        upstream, downstream = self.geo.createNode("box"), self.geo.createNode("null")
        downstream.setInput(0, upstream)
        hou.undos.clear()
        self.assertTrue(self.release(network=self.geo, spot=hou.Vector2(0, -1),
                                     wire=downstream.inputConnections()[0]))
        self.assertEqual("attribwrangle", downstream.inputs()[0].type().name(), "premise: no splice")
        hou.undos.performUndo()
        self.assertEqual(([upstream], ["box1", "null1"]), (list(downstream.inputs()), self.names(self.geo)))
        before = self.names(self.lopnet)
        hou.undos.clear()
        self.assertEqual(0, self.drag(_Viewer(self.lopnet, "/world/ball"), _MenuHost("Set as Material on ball")))
        made = sorted(child.type().name() for child in self.lopnet.children() if child.name() not in before)
        self.assertEqual(["assignmaterial", "materiallibrary"], made, "premise: not imported and assigned")
        hou.undos.performUndo()
        self.assertEqual(before, self.names(self.lopnet), "one undo left part of the import or the assign")

    def test_dd02_a_drop_that_fails_at_any_step_leaves_no_node_and_says_why(self):
        folder = test_support.scratch_dir("amaze_dd02_")
        self.addCleanup(shutil.rmtree, folder, True)
        hda = os.path.join(folder, "dd02.hda")
        self.addCleanup(hou.hda.uninstallFile, hda)
        locked = self.geo.createNode("subnet").createDigitalAsset(
            name="amaze_dd02_locked", hda_file_name=hda, description="dd02")
        self.addCleanup(test_support.drop_node, locked)
        locked.matchCurrentDefinition()    # its contents locked, as a saved asset's are
        inside, before_geo = self.names(locked), self.names(self.geo)
        wrangle = (locked, "attribwrangle", helpers.find_code_parm, "@Cd = 1;", "Amaze Create Code Node")
        self.assertFalse(self.placement.create_holder_node(*wrangle[:2], "dd02", None, *wrangle[2:]))
        self.assertIsNone(self.placement.import_geo_in_context(CUBE, locked))
        self.assertEqual((inside, 2), (self.names(locked), len(self.refused)))
        real = hou.Parm.set

        def refused(parm, *args, **kwargs):
            if parm.name() == "snippet":
                raise hou.PermissionError("the parameter is locked")
            return real(parm, *args, **kwargs)
        with mock.patch.object(hou.Parm, "set", refused):
            self.assertFalse(self.placement.create_holder_node(
                self.geo, "attribwrangle", "dd02", None, *wrangle[2:]))
        self.assertIn("the parameter is locked", self.refused[-1])
        before, self.ids = self.names(self.lopnet), ["fails", "dd02_other"]
        self.drag(_Viewer(self.lopnet, "/world/ball"), _MenuHost("Set as Material on ball"))    # fails on the pick
        self.assertEqual((before, ["fails"]), (self.names(self.lopnet), self.imported))    # the real import says why
        self.assertEqual(before_geo, self.names(self.geo), "a node the failed drops made was left")


class _Library:
    """A LOP network: two spheres, a library of mat_a and mat_b, the shown branch binding mat_b."""

    def __init__(self, test):
        self.lopnet = hou.node("/stage").createNode("lopnet")
        test.addCleanup(test_support.drop_node, self.lopnet)
        a = self.lopnet.createNode("sphere", "sphere_a")
        b = self.lopnet.createNode("sphere", "sphere_b")
        b.setFirstInput(a)
        self.library = self.lopnet.createNode("materiallibrary")
        self.library.setFirstInput(b)
        for index, name in enumerate(("mat_a", "mat_b"), 1):
            self.library.createNode("subnet", name).setGenericFlag(hou.nodeFlag.Material, True)
            self.library.parm("materials").set(index)
            self.library.parm("matnode%d" % index).set(name)
        self.shown = self.assign(self.library, "/sphere_a", "/materials/mat_b")
        self.shown.setDisplayFlag(True)

    def assign(self, after, prims, material):
        node = after.parent().createNode("assignmaterial")
        node.setFirstInput(after)
        node.parm("nummaterials").set(1)
        node.parm("primpattern1").set(prims)
        node.parm("matspecpath1").set(material)
        return node

    def removed(self) -> bool:
        return lop_assign.remove_unreferenced_material(self.lopnet, self.library, "/materials/mat_a")


class ASwapKeepsAUsedMaterialTest(_Drops):

    def test_dd03_a_swap_never_deletes_a_material_the_scene_still_uses(self):
        def another_branch(scene):
            branch = scene.lopnet.createNode("subnet", "other_branch")
            branch.setFirstInput(scene.library)
            inside = scene.assign(branch.indirectInputs()[0], "/sphere_b", "/materials/mat_a")
            branch.node("output0").setFirstInput(inside)

        def an_object(scene):
            self.geo.parm("shop_materialpath").set(scene.library.node("mat_a").path())

        def a_layer(scene):
            folder = test_support.scratch_dir("amaze_dd03_")
            self.addCleanup(shutil.rmtree, folder, True)
            path = test_support.put(folder, "layer.usda", '#usda 1.0\nover "sphere_b"\n{\n'
                                    '    rel material:binding = </materials/mat_a>\n}\n')
            layer = scene.lopnet.createNode("sublayer")
            layer.setFirstInput(scene.shown)
            layer.parm("filepath1").set(path)
        for use in (another_branch, an_object, a_layer):
            with self.subTest(use.__name__):
                self.geo.parm("shop_materialpath").set("")
                scene = _Library(self)
                use(scene)
                self.assertFalse(scene.removed(), "a material in use was removed")
                self.assertEqual(["mat_a", "mat_b"], self.names(scene.library))
        self.geo.parm("shop_materialpath").set("")
        self.assertTrue(_Library(self).removed(), "a material nothing uses was kept")


def _digest(*roots) -> list:
    """Every node under `roots` and each root: its path, inputs and the raw value of each parm."""
    return [(node.path(), [str(wire) for wire in node.inputs()],
             [(parm.name(), str(parm.rawValue())) for parm in node.parms()])
            for root in roots for node in [root] + list(root.allSubChildren())]


class SwapMaterialTest(_Drops):
    """Swap Material in the tile menu, the one tile's library import making its material in place."""

    def setUp(self):
        super().setUp()
        loads = self.pane.loading = loading.Loading(self.pane)
        loads._import_material_builder = lambda aid, target, context_node=None: self.material_into(
            aid, context_node or hou.node("/mat"))
        kept = set(self.names(hou.node("/mat")))    # by name: an undo brings a node back as a new one
        self.addCleanup(lambda: [test_support.drop_node(node) for node in hou.node("/mat").children()
                                 if node.name() not in kept])
        self.addCleanup(hou.clearAllSelected)

    def swap(self, viewer, tiles=1, pick=True) -> bool:
        """Swap Material on the menu of `tiles` tiles, `viewer` the scene viewer: whether it is offered."""
        section, grid = self.pane.sections["material"], self.pane.material_sorted_model
        chosen = [grid.index(row, 0) for row in range(tiles)]
        entry, = [entry for entry in section.GRID_MENU if entry.handler == "menu_swap_material"]
        with self.houdini_drop(), mock.patch.object(scene_captures, "scene_viewer", return_value=viewer):
            menu = menus.Menu(section, (entry,), chosen, chosen[0])
            if pick and menu.rows[0]["enabled"]:    # a greyed row cannot be picked
                menu.run(menu.rows[0]["key"])
        return menu.rows[0]["enabled"]

    def bound(self):
        """(network, library): /world bound to old_a, /world/ball/cap to old_b, /world/other to old_c."""
        lopnet = hou.node("/stage").createNode("lopnet")
        self.addCleanup(test_support.drop_node, lopnet)
        last = None
        for path in ("/world/ball/body", "/world/ball/cap", "/world/other"):
            sphere = lopnet.createNode("sphere")
            sphere.parm("primpath").set(path)
            sphere.setFirstInput(last)
            last = sphere
        library = lopnet.createNode("materiallibrary")
        library.setFirstInput(last)
        assign = lopnet.createNode("assignmaterial")
        assign.setFirstInput(library)
        bindings = (("/world", "old_a"), ("/world/ball/cap", "old_b"), ("/world/other", "old_c"))
        assign.parm("nummaterials").set(len(bindings))
        for at, (prims, name) in enumerate(bindings, 1):
            nodes.make_karma_builder(library, name)    # lists itself as a dependent ▸r/material-self-dependent
            assign.parm("primpattern%d" % at).set(prims)
            assign.parm("matspecpath%d" % at).set("/materials/" + name)
        assign.setDisplayFlag(True)
        return lopnet, library

    def test_dd04_one_undo_takes_back_a_whole_swap_material(self):
        def an_object():    # the import into /mat, the Material parameter, the old material removed
            nodes.make_karma_builder(hou.node("/mat"), "dd04_old")
            self.geo.parm("shop_materialpath").set("/mat/dd04_old")
            self.geo.setSelected(True, clear_all_selected=True)
            return _Viewer(hou.node("/obj")), (hou.node("/mat"), self.geo), lambda: (
                self.geo.parm("shop_materialpath").eval(), hou.node("/mat/dd04_old")) == ("/mat/dd_mat", None)

        def a_prim_bound_from_a_library():    # the import into it, the binding, its old material removed
            scene = _Library(self)
            return _Viewer(scene.lopnet, chosen=["/sphere_a"]), (scene.lopnet,), lambda: (
                self.names(scene.library) == ["dd_mat", "mat_a"])

        def a_prim_bound_from_a_layer():    # a material library made for the import, the binding
            folder = test_support.scratch_dir("amaze_dd04_")
            self.addCleanup(shutil.rmtree, folder, True)
            layer = self.lopnet.createNode("sublayer")
            layer.setFirstInput(self.sphere)
            layer.parm("filepath1").set(test_support.put(folder, "look.usda", '#usda 1.0\n'
                                        'def Scope "looks"\n{\n    def Material "felt"\n    {\n    }\n}\n'
                                        'over "world"\n{\n    over "ball"\n    {\n'
                                        '        rel material:binding = </looks/felt>\n    }\n}\n'))
            layer.setDisplayFlag(True)
            return _Viewer(self.lopnet, chosen=["/world/ball"]), (self.lopnet,), lambda: sorted(
                node.type().name() for node in self.lopnet.children()) == [
                "assignmaterial", "materiallibrary", "sphere", "sublayer"]
        for scene in (an_object, a_prim_bound_from_a_library, a_prim_bound_from_a_layer):
            with self.subTest(scene.__name__):
                viewer, roots, swapped = scene()
                before = _digest(*roots)
                hou.undos.clear()
                self.swap(viewer)
                self.assertTrue(swapped(), "premise: the swap did not do all of its parts")
                hou.undos.performUndo()
                self.assertEqual(before, _digest(*roots), "one undo left part of the swap")

    def test_dd29_swap_material_replaces_the_material_of_the_one_object_or_prim_selected(self):
        camera = hou.node("/obj").createNode("cam", "dd29_cam")
        self.addCleanup(test_support.drop_node, camera)
        objects, prims = _Viewer(hou.node("/obj")), functools.partial(_Viewer, self.lopnet)
        offered = []
        for tiles, viewer, selected in ((1, objects, [self.geo]), (2, objects, [self.geo]), (1, objects, []),
                                        (1, objects, [self.geo, camera]), (1, None, [self.geo]),
                                        (1, prims(chosen=["/world/ball"]), []), (1, prims(), []),
                                        (1, prims(chosen=["/world/ball", "/world"]), [])):
            hou.clearAllSelected()
            for node in selected:
                node.setSelected(True)
            offered.append(self.swap(viewer, tiles, pick=False))
        self.assertEqual([True, False, False, False, False, True, False, False], offered)
        nodes.make_karma_builder(hou.node("/mat"), "dd29_old")    # lists itself as a dependent
        self.geo.parm("shop_materialpath").set("/mat/dd29_old")
        self.geo.setSelected(True, clear_all_selected=True)
        self.swap(objects)
        self.assertEqual(("/mat/dd_mat", None), (self.geo.parm("shop_materialpath").eval(),
                                                 hou.node("/mat/dd29_old")))
        lopnet, library = self.bound()
        self.swap(_Viewer(lopnet, chosen=["/world/ball"]))    # bound through /world, cap bound below it
        stage, api = lopnet.displayNode().stage(), UsdShade.MaterialBindingAPI
        self.assertEqual(["/materials/dd_mat", "/materials/dd_mat", "/materials/old_c"], [
            str(api(stage.GetPrimAtPath(path)).ComputeBoundMaterial()[0].GetPath())
            for path in ("/world/ball/body", "/world/ball/cap", "/world/other")])
        self.assertEqual(["dd_mat", "old_c"], self.names(library), "an old material nothing uses was kept")
        before, imported = self.names(self.lopnet), len(self.imported)
        self.swap(prims(chosen=["/world/ball"]))    # a prim with no material
        self.assertEqual((before, imported, [messages.NOTHING_TO_SWAP % "/world/ball"]),
                         (self.names(self.lopnet), len(self.imported), self.refused[-1:]))


class WhereADropGoesTest(_Drops):

    def test_dd20_a_tile_goes_to_the_node_under_it_else_into_the_network_shown_else_nowhere(self):
        wrangle = self.geo.createNode("attribwrangle")
        self.assertTrue(self.release(node=wrangle, network=self.geo))
        self.assertEqual("@Cd = {1, 0, 0};", wrangle.parm("snippet").eval())
        self.assertTrue(self.release(network=self.geo, spot=hou.Vector2(5, -5)))
        made, = [node for node in self.geo.children() if node.name() == "tint"]
        self.assertLess((made.position() - hou.Vector2(5, -5)).length(), 1, "not at the outlined spot")
        objects = self.names(hou.node("/obj"))
        self.assertFalse(self.release(network=hou.node("/obj")), "a network that holds no wrangle")
        self.assertFalse(self.release(), "a release over nothing")
        self.assertEqual(objects, self.names(hou.node("/obj")))

    def released_by(self, found) -> bool:
        """The snippet released into network space where the editor's drop radius holds `found()`."""
        editor = _Editor(found)
        with mock.patch.object(self.placement, "node_under_cursor", return_value=None), \
                mock.patch.object(self.placement, "network_under_release", return_value=self.geo), \
                mock.patch.object(self.placement, "release_position_in",
                                  return_value=hou.Vector2(0, -3)), \
                mock.patch.dict(sys.modules, {"nodegraphutils": _nodegraph(_host_insert)}):
            return self.placement.release("code", "s1", editor, hou.paneTabType.NetworkEditor)

    def test_dd21_on_a_wire_or_by_a_free_connector_the_new_nodes_are_wired_never_to_themselves(self):
        upstream, downstream = self.geo.createNode("box"), self.geo.createNode("null")
        downstream.setInput(0, upstream)
        wire = downstream.inputConnections()[0]
        self.assertTrue(self.released_by(lambda: [(wire, "", 0)]))
        made, = helpers.placed_nodes()
        self.assertEqual(([upstream], [made]), (list(made.inputs()), list(downstream.inputs())))
        free = self.geo.createNode("null", "free")
        self.assertTrue(self.released_by(lambda: [(helpers.placed_nodes()[0], "output", 0),
                                                  (free, "input", 0)]))    # its own connector first
        made, = helpers.placed_nodes()
        self.assertEqual(([made], []), (list(free.inputs()), [
            node for node in made.inputs() if node is not None]))

    def test_dd22_a_file_dropped_on_a_node_sets_its_first_file_parameter(self):
        pane = types.SimpleNamespace(file_files_model=file_section.file_library.FileFiles,
                                     drop_placement=self.placement)
        section = file_section.FileSection(pane)
        home = hou.text.expandString("$HOME")
        index = types.SimpleNamespace(data=lambda role: os.path.join(home, "rock.bgeo"))
        loader = self.geo.createNode("file")
        self.assertTrue(section.drop_file_path_on_node(index, loader))
        self.assertEqual("$HOME/rock.bgeo", loader.parm("file").unexpandedString())
        self.assertFalse(section.drop_file_path_on_node(index, self.geo.createNode("null", "plain")))
        self.assertEqual([messages.NODE_HAS_NO_FILE_PARM % ("plain", "rock.bgeo")], self.refused)

    def test_dd23_geometry_becomes_a_loader_a_sop_create_or_a_geo_shown_current_and_selected(self):
        for network, made_in, kind in ((self.geo, self.geo, "file"),
                                       (self.lopnet, self.lopnet, "sopcreate"),
                                       (hou.node("/obj"), hou.node("/obj"), "geo")):
            with self.subTest(kind):
                made = self.placement.import_geo_in_context(CUBE, network)
                self.addCleanup(test_support.drop_node, made)
                self.assertEqual((made_in, kind), (made.parent(), made.type().name()))
                self.assertTrue(made.isDisplayFlagSet() and made.isCurrent() and made.isSelected())
        self.assertEqual([self.sphere], list(hou.node("/stage/dd_lop/cube").inputs()),
                         "the SOP Create is not chained to the display node")
        self.assertEqual("cube", hou.node("/obj/cube").name())

    def test_dd24_a_material_dropped_on_a_prim_offers_its_rows_and_imports_only_on_the_pick(self):
        for at_once in (True, False):    # the widget panel's menu answers at once, the QML pane's later
            with self.subTest(at_once=at_once):
                lopnet = hou.node("/stage").createNode("lopnet")
                self.addCleanup(test_support.drop_node, lopnet)
                sphere = lopnet.createNode("sphere")
                sphere.parm("primpath").set("/world/ball")
                sphere.setDisplayFlag(True)
                viewer, host = _Viewer(lopnet, "/world/ball"), _MenuHost("Set as Material on ../world", at_once)
                self.assertEqual(0, self.drag(viewer, host), "a red X")
                self.assertEqual([["/world/ball"], []], viewer.lit, "the prim not lit while dragging, then off")
                self.assertEqual(["Set as Material on ball", "Set as Material on ../world"], host.offered)
                if not at_once:
                    self.assertEqual(["sphere1"], self.names(lopnet), "imported or assigned before the pick")
                    with self.houdini_drop():
                        host.pick()
                library = lopnet.node("materiallibrary1")
                self.assertEqual(([sphere], ["dd_mat", "dd_other"]), (list(library.inputs()), self.names(library)))
                assign, = [child for child in lopnet.children() if child.type().name() == "assignmaterial"]
                self.assertEqual(("/world", "/materials/dd_mat"),
                                 (assign.parm("primpattern1").eval(), assign.parm("matspecpath1").eval()))
        before, imported, host = self.names(self.lopnet), len(self.imported), _MenuHost(None)
        self.assertEqual(0, self.drag(_Viewer(self.lopnet, "/world/ball"), host))
        self.assertEqual((before, imported), (self.names(self.lopnet), len(self.imported)),
                         "a dismissed menu imported")
        host = _MenuHost("Set as Material on ball")
        self.assertEqual(1, self.drag(_Viewer(self.lopnet), host), "empty space is no miss")
        self.assertEqual((before, [], imported), (self.names(self.lopnet), host.offered, len(self.imported)))

    def test_dd25_a_material_dropped_on_an_object_is_imported_into_mat_and_set_as_its_material(self):
        imported = []

        def into_mat(aid, target):
            imported.append((aid, target))
            made = hou.node("/mat").createNode("subnet", aid)
            self.addCleanup(test_support.drop_node, made)
            return made
        loads = self.pane.loading = loading.Loading(self.pane)
        loads._import_material_builder = into_mat
        loads.selected_material_ids = lambda index: ["dd25_a", "dd25_b"]
        camera = hou.node("/obj").createNode("cam", "dd25_cam")
        self.addCleanup(test_support.drop_node, camera)
        for viewer, why in ((_Viewer(self.geo, self.geo.createNode("null")), "a viewer inside a geo took it"),
                            (_Viewer(hou.node("/obj")), "empty space took it"),
                            (_Viewer(hou.node("/obj"), camera), "an object with no material parameter took it")):
            self.assertEqual((1, []), (self.drag(viewer), imported), why)
        self.assertEqual(0, self.drag(_Viewer(hou.node("/obj"), self.geo)), "a red X")
        self.assertEqual([("dd25_a", "mat"), ("dd25_b", "mat")], imported)
        self.assertEqual("/mat/dd25_a", self.geo.parm("shop_materialpath").eval())

    def test_dd26_placing_dropped_nodes_never_moves_the_users_nodes(self):
        mine = [self.geo.createNode("null") for _ in range(4)]
        for count, node in enumerate(mine):
            node.setPosition(hou.Vector2(count * 0.4, 0))
        before = [node.position() for node in mine]
        self.placement.create_holder_node(self.geo, "attribwrangle", "dd26", hou.Vector2(0.2, 0),
                                          helpers.find_code_parm, "", "Amaze Create Code Node")
        made = self.placement.import_geo_in_context(CUBE, self.geo)
        self.assertIsNotNone(made)
        self.assertEqual(before, [node.position() for node in mine])


def _send(view, kind, at, button, buttons):
    """A mouse event at `at` in the pane's view, as the view holding the mouse gets it."""
    event = QtGui.QMouseEvent(kind, at, QtCore.QPointF(view.mapToGlobal(at.toPoint())), button, buttons,
                              QtCore.Qt.KeyboardModifier.NoModifier)
    QtWidgets.QApplication.sendEvent(view, event)
    QtWidgets.QApplication.processEvents()


def _first_tile(view) -> QtCore.QPointF:
    """The middle of the first tile's picture, in the view's own coordinates."""
    grid = next(item for item in view.rootObject().findChildren(QtQuick.QQuickItem)
                if item.property("hotkeysFirst") and item.isVisible())
    side = grid.property("tileSize") / 2
    found = QtCore.QMetaObject.invokeMethod(grid, "rowAt", QtCore.Qt.ConnectionType.DirectConnection,
                                            QtCore.Q_RETURN_ARG("QVariant"), QtCore.Q_ARG("QVariant", side),
                                            QtCore.Q_ARG("QVariant", side))
    assert found == 0, "no first tile under the point: %r" % (found,)
    return grid.mapToScene(QtCore.QPointF(side, side))


@unittest.skipUnless(hou, "Houdini is not loaded")
class ADragEndedEarlyMakesNothingTest(unittest.TestCase):

    def test_dd27_esc_another_button_or_a_hidden_pane_ends_a_drag_and_its_release_makes_nothing(self):
        test_support.fixture_panel(self)    # the fixture library, which the QML pane opens too
        panel = qml_pane.QmlPanel()
        self.addCleanup(test_support.stop_panel_workers, panel)
        self.addCleanup(panel.deleteLater)
        panel.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        panel.resize(840, 420)
        panel.show()
        QtWidgets.QApplication.processEvents()
        view, kind, left = panel.view, QtCore.QEvent.Type, QtCore.Qt.MouseButton.LeftButton
        right, none = QtCore.Qt.MouseButton.RightButton, QtCore.Qt.MouseButton.NoButton
        at = _first_tile(view)
        ends = {"nothing": lambda: None,
                "Esc": lambda: QtWidgets.QApplication.sendEvent(view, QtGui.QKeyEvent(
                    kind.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier)),
                "a right click": lambda: (_send(view, kind.MouseButtonPress, at, right, left | right),
                                          _send(view, kind.MouseButtonRelease, at, right, left)),
                "the pane hidden": view.hide}
        seen, released = {}, []
        with mock.patch.object(panel.pane.drop_placement, "release",
                               lambda *args, **kwargs: released.append(args) or True):
            for name, end in ends.items():
                _send(view, kind.MouseButtonPress, at, left, left)
                for step in range(1, 7):    # past the drag distance, then out of the pane
                    _send(view, kind.MouseMove, at + QtCore.QPointF(0, step * 6), none, left)
                _send(view, kind.MouseMove, QtCore.QPointF(-400, -300), none, left)
                began = view.drag.running
                end()
                _send(view, kind.MouseButtonRelease, QtCore.QPointF(-400, -300), left, none)
                seen[name] = (began, len(released), view.drag.running)
                released.clear()
                view.show()
        self.assertEqual({name: (True, 1 if name == "nothing" else 0, False) for name in ends}, seen,
                         "per way out: (the drag began, drops made at the release, still running)")


if __name__ == "__main__":
    unittest.main()
