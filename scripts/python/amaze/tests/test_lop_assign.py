"""LOP material assignment, tested headlessly for the first time.

This is the USD half of a viewport drop - the app's busiest workflow
(the debug log counts drag as its single largest activity) and the
part that was hardest to check, because reaching it meant dragging a
tile onto a Solaris viewport by hand and looking at the result.

Now that it is plain functions over hou/USD objects, the cases can be
built directly: real stages, real bindings, real assignmaterial nodes.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import lop_assign  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log


class _Scene:
    """A LOP network with two spheres, a material library holding two
    materials, and a binding on the first sphere."""

    def __init__(self, testcase):
        self.lopnet = hou.node("/stage").createNode("lopnet")
        testcase.addCleanup(self.lopnet.destroy)
        self.a = self.lopnet.createNode("sphere", "sphere_a")
        self.b = self.lopnet.createNode("sphere", "sphere_b")
        self.b.setFirstInput(self.a)
        self.liblop = self.lopnet.createNode("materiallibrary")
        self.liblop.setFirstInput(self.b)
        self.mat_a = self.liblop.createNode("subnet", "mat_a")
        self.mat_b = self.liblop.createNode("subnet", "mat_b")
        for node in (self.mat_a, self.mat_b):
            node.setGenericFlag(hou.nodeFlag.Material, True)
        self.liblop.parm("materials").set(2)
        self.liblop.parm("matnode1").set("mat_a")
        self.liblop.parm("matnode2").set("mat_b")
        self.assign = self.lopnet.createNode("assignmaterial")
        self.assign.setFirstInput(self.liblop)
        self.assign.setDisplayFlag(True)

    def bind(self, prim, matpath, index=1):
        self.assign.parm("nummaterials").set(max(index, 1))
        self.assign.parm("primpattern%d" % index).set(prim)
        self.assign.parm("matspecpath%d" % index).set(matpath)

    def stage(self):
        return self.assign.stage()


class TestBoundMaterials(unittest.TestCase):

    def test_reports_the_binding_on_the_picked_prim(self):
        scene = _Scene(self)
        scene.bind("/sphere_a", "/materials/mat_a")
        found = lop_assign.bound_materials_under(scene.stage(), "/sphere_a")
        self.assertTrue(found, "a bound prim reported no material")
        matpath, prims = found[0]
        self.assertIn("mat_a", matpath)
        self.assertIn("/sphere_a", prims)

    def test_unbound_prim_reports_nothing(self):
        """No binding means the drop menu offers assign, not swap - so
        an empty list here is what keeps 'Swap' from appearing."""
        scene = _Scene(self)
        self.assertEqual(
            lop_assign.bound_materials_under(scene.stage(), "/sphere_b"), []
        )

    def test_missing_prim_and_no_stage_are_survivable(self):
        scene = _Scene(self)
        self.assertEqual(
            lop_assign.bound_materials_under(scene.stage(), "/nope"), [])
        self.assertEqual(
            lop_assign.bound_materials_under(None, "/sphere_a"), [])


class TestRemoveUnreferenced(unittest.TestCase):

    def test_removes_a_material_nothing_binds(self):
        scene = _Scene(self)
        scene.bind("/sphere_a", "/materials/mat_a")
        removed = lop_assign.remove_unreferenced_material(
            scene.lopnet, scene.liblop, "/materials/mat_b"
        )
        self.assertTrue(removed, "an unreferenced material survived a swap")
        self.assertIsNone(scene.liblop.node("mat_b"))
        self.assertIsNotNone(scene.liblop.node("mat_a"))

    def test_keeps_a_material_that_is_still_assigned(self):
        """The failure that matters: deleting a material still bound
        somewhere else turns one swap into a scene-wide breakage."""
        scene = _Scene(self)
        scene.bind("/sphere_a", "/materials/mat_a")
        kept = lop_assign.remove_unreferenced_material(
            scene.lopnet, scene.liblop, "/materials/mat_a"
        )
        self.assertFalse(kept, "removed a material that is still assigned")
        self.assertIsNotNone(scene.liblop.node("mat_a"))

    def test_empty_primpattern_does_not_count_as_a_use(self):
        """assignMat empties a pattern when it moves prims away; a
        material left behind by that IS collectable."""
        scene = _Scene(self)
        scene.bind("", "/materials/mat_a")
        removed = lop_assign.remove_unreferenced_material(
            scene.lopnet, scene.liblop, "/materials/mat_a"
        )
        self.assertTrue(removed,
                        "an emptied assignment blocked the cleanup")

    def test_unknown_material_is_a_no_op(self):
        scene = _Scene(self)
        self.assertFalse(lop_assign.remove_unreferenced_material(
            scene.lopnet, scene.liblop, "/materials/nonexistent"))


class TestNameNewAssign(unittest.TestCase):

    def test_names_the_new_assign_after_what_it_drives(self):
        scene = _Scene(self)
        before = list(scene.lopnet.children())
        fresh = scene.lopnet.createNode("assignmaterial")
        lop_assign.name_new_assign(scene.lopnet, before, "/sphere_a")
        self.assertIn("sphere_a", fresh.name(),
                      "assign was not named after its prim")

    def test_leaves_a_reused_assign_alone(self):
        """Only the node just created is renamed - an assign that
        already earned its name keeps it."""
        scene = _Scene(self)
        existing = scene.assign.name()
        lop_assign.name_new_assign(
            scene.lopnet, list(scene.lopnet.children()), "/sphere_a"
        )
        self.assertEqual(scene.assign.name(), existing)


class TestDropChoices(unittest.TestCase):
    """What the viewport drop menu offers - the decision the panel used
    to make inline while building QMenu actions, so it could only be
    checked by dragging onto a viewport and reading the popup."""

    def test_unbound_prim_offers_assign_up_the_ancestor_chain(self):
        scene = _Scene(self)
        choices = lop_assign.drop_choices(scene.stage(), "/sphere_a")
        kinds = [k for k, _l, _p in choices]
        self.assertNotIn("swap", kinds, "nothing is bound - swap offered")
        self.assertIn("assign", kinds)
        labels = [l for _k, l, _p in choices]
        self.assertTrue(labels[0].startswith("Set as Material on sphere_a"),
                        labels[0])

    def test_bound_prim_offers_swap_first(self):
        """Swap before assign: rebinding what is already there beats
        piling another assignment on top and leaving a dead material."""
        scene = _Scene(self)
        scene.bind("/sphere_a", "/materials/mat_a")
        choices = lop_assign.drop_choices(scene.stage(), "/sphere_a")
        self.assertEqual(choices[0][0], "swap", "swap was not offered first")
        self.assertIn("mat_a", choices[0][1])
        self.assertTrue(any(k == "assign" for k, _l, _p in choices),
                        "assign disappeared when a material was bound")

    def test_swap_all_appears_only_with_several_materials(self):
        scene = _Scene(self)
        scene.bind("/sphere_a", "/materials/mat_a")
        labels = [l for _k, l, _p in
                  lop_assign.drop_choices(scene.stage(), "/sphere_a")]
        self.assertNotIn("Swap All Materials", labels,
                         "'Swap All' offered for a single material")

    def test_payloads_are_what_the_actions_need(self):
        """The panel hands these straight to swap_assignments /
        assignMat - a wrong shape here is a crash at click time."""
        scene = _Scene(self)
        scene.bind("/sphere_a", "/materials/mat_a")
        for kind, _label, payload in lop_assign.drop_choices(
                scene.stage(), "/sphere_a"):
            if kind == "swap":
                self.assertIsInstance(payload, list)
                matpath, prims = payload[0]
                self.assertTrue(str(matpath).startswith("/"))
                self.assertIsInstance(prims, list)
            else:
                self.assertTrue(str(payload).startswith("/"))

    def test_no_prim_or_no_stage_offers_nothing(self):
        """A drop on empty viewport space must produce no menu at all -
        an empty list is what makes the caller bail before popping one."""
        scene = _Scene(self)
        self.assertEqual(lop_assign.drop_choices(scene.stage(), ""), [])
        self.assertEqual(lop_assign.drop_choices(None, "/sphere_a"), [])


class TestCollectionBindings(unittest.TestCase):
    """Houdini's assignmaterial writes ONE OF TWO binding styles: a
    plain material:binding relationship, or a collection binding
    (material:binding:collection:<name>). Reading only the first meant
    a material assigned the collection way offered no Swap entry - the
    drop menu had nothing to show for that object while working
    perfectly on its neighbour, which is exactly how it was reported:
    "the drop menu offered nothing for one object".

    Built like a real scene: SOP-created geometry, so the prims are
    /thing_object1/mesh_0 rather than hand-authored xforms.
    """

    def _sop_scene(self, bind_method):
        lopnet = hou.node("/stage").createNode("lopnet")
        self.addCleanup(lopnet.destroy)
        sopc = lopnet.createNode("sopcreate", "torus_object1")
        sopc.node("sopnet/create").createNode("torus")
        lib = lopnet.createNode("materiallibrary")
        lib.setFirstInput(sopc)
        mat = lib.createNode("subnet", "mat_a")
        mat.setGenericFlag(hou.nodeFlag.Material, True)
        lib.parm("materials").set(1)
        lib.parm("matnode1").set("mat_a")
        assign = lopnet.createNode("assignmaterial")
        assign.setFirstInput(lib)
        assign.setDisplayFlag(True)
        assign.parm("nummaterials").set(1)
        assign.parm("primpattern1").set("/torus_object1")
        assign.parm("matspecpath1").set("/materials/mat_a")
        assign.parm("bindmethod1").set(bind_method)
        return assign.stage()

    def test_direct_binding_is_found(self):
        stage = self._sop_scene(0)
        self.assertTrue(
            lop_assign.bound_materials_under(stage, "/torus_object1"))

    def test_collection_binding_is_found(self):
        """The reported bug: bind method 1 authors
        material:binding:collection:<name> with targets
        [collection, material]."""
        stage = self._sop_scene(1)
        found = lop_assign.bound_materials_under(stage, "/torus_object1")
        self.assertTrue(found, "a collection-bound material offered no swap")
        self.assertEqual(found[0][0], "/materials/mat_a")

    def test_collection_binding_offers_swap_in_the_menu(self):
        """End to end: the menu the user actually sees."""
        stage = self._sop_scene(1)
        choices = lop_assign.drop_choices(stage, "/torus_object1")
        self.assertEqual(choices[0][0], "swap",
                         "no Swap entry for a collection-bound material")

    def test_found_from_a_child_prim_too(self):
        """Drops land on /torus_object1/mesh_0 - the binding is on the
        parent, and the ancestor walk has to reach it."""
        stage = self._sop_scene(1)
        self.assertTrue(
            lop_assign.bound_materials_under(stage, "/torus_object1/mesh_0"),
            "an ancestor's collection binding was not found from the mesh")


class TestAssignNodeLookup(unittest.TestCase):
    """A viewport drop must not bind into a node nothing displays.

    first_materiallibrary has always filtered to the display chain,
    because "an assignment into a disconnected one silently does not
    display". find_assignmaterial had no such filter and returned the
    first assignmaterial in CREATION order - so a leftover disconnected
    one won over the live node: the material imported, the binding was
    written where nothing shows it, the menu was accepted, and the
    viewport did not change. No error, no icon."""

    def setUp(self):
        from amaze.core import dragengine

        self.dragengine = dragengine
        self.lopnet = hou.node("/stage").createNode("lopnet")
        self.addCleanup(self.lopnet.destroy)
        self.sphere = self.lopnet.createNode("sphere")

        # A leftover from an earlier session: created FIRST, wired to
        # nothing. Creation order is what the old lookup went by.
        self.stale = self.lopnet.createNode("assignmaterial", "stale_assign")

        # The real one, in the display chain.
        self.live = self.lopnet.createNode("assignmaterial", "live_assign")
        self.live.setInput(0, self.sphere)
        self.live.setDisplayFlag(True)
        self.display = self.lopnet.displayNode()

    def test_the_connected_assign_node_wins(self):
        found = self.dragengine.find_assignmaterial(
            self.lopnet, connected_to=self.display)
        self.assertIsNotNone(found, "no assignmaterial found in the chain")
        self.assertEqual(
            "live_assign", found.name(),
            "the drop picked a disconnected assignmaterial, so the "
            "binding lands where nothing displays it")

    def test_creation_order_still_wins_when_nothing_is_connected(self):
        """The unfiltered lookup stays the fallback - a network with no
        assign node in the chain must still converge on one node rather
        than chaining a new one per drop."""
        orphan_net = hou.node("/stage").createNode("lopnet")
        self.addCleanup(orphan_net.destroy)
        first = orphan_net.createNode("assignmaterial", "first")
        orphan_net.createNode("assignmaterial", "second")
        # By PATH, not identity: hou returns a fresh Python wrapper for
        # the same node on every lookup.
        self.assertEqual(
            first.path(),
            self.dragengine.find_assignmaterial(orphan_net).path())

    def test_an_unconnected_network_finds_nothing_in_the_chain(self):
        lonely = hou.node("/stage").createNode("lopnet")
        self.addCleanup(lonely.destroy)
        sphere = lonely.createNode("sphere")
        lonely.createNode("assignmaterial", "detached")
        self.assertIsNone(
            self.dragengine.find_assignmaterial(lonely, connected_to=sphere),
            "a detached assign node was reported as being in the chain")


class TestLockedContextIsRefused(unittest.TestCase):
    """Dropping into a locked asset must return a reason, not raise.

    _drop_context_under_cursor falls back to the network editor's pwd(),
    which is the locked node when the editor is dived into a locked
    asset. update_context resolves the destination and may CREATE a
    container to reach it, so that raised hou.PermissionError - a
    SIBLING of OperationFailed, not a subclass - straight out of the
    release slot."""

    def test_permission_error_is_not_a_subclass_of_operation_failed(self):
        """The trap itself, pinned: code that catches OperationFailed
        does NOT catch this."""
        self.assertFalse(
            issubclass(hou.PermissionError, hou.OperationFailed),
            "hou.PermissionError became an OperationFailed subclass - "
            "the guards written for this trap can be simplified")
        self.assertTrue(issubclass(hou.PermissionError, hou.Error))

    def test_the_import_reports_instead_of_raising(self):
        from amaze.render import nodes as nodes_mod
        from amaze.core import library as library_mod

        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        model = library_mod.MaterialLibrary(preferences=prefs)
        if not model.rowCount():
            self.skipTest("fixture library is empty")

        handler = nodes_mod.NodeHandler(prefs)

        def refuse(*args, **kwargs):
            raise hou.PermissionError("Cannot create a node inside a "
                                      "locked asset")

        handler.update_context = refuse
        # An asset whose FILES exist: the import now refuses a missing
        # or empty payload before it ever reaches update_context (and
        # rightly so - update_context creates containers), so a
        # file-less fixture row would never reach the case under test.
        asset = None
        for candidate in model.assets:
            payload = os.path.join(
                prefs.dir, prefs.asset_dir, str(candidate.mat_id) + prefs.ext)
            if os.path.exists(payload) and os.path.getsize(payload) > 0:
                asset = candidate
                break
        if asset is None:
            self.skipTest("no fixture asset has a material file on disk")
        try:
            ok, reason, _created = handler.import_asset_to_scene(asset, target="auto")
        except hou.Error as exc:
            self.fail("a locked context raised out of the import instead "
                      "of reporting: %s" % exc)
        self.assertFalse(ok, "a refused context reported success")
        self.assertIn("cannot import here", reason.lower())
        self.assertIsNone(
            handler._context_override,
            "the refused context override leaked into the next import")


if __name__ == "__main__":
    unittest.main()
