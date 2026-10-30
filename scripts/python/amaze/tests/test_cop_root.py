"""The COP companion's scene root, and what a refused import leaves behind in `/obj` - driven against REAL nodes, because a leaked container is a scene-graph fact a mocked `hou` cannot show. `restore_cop_companion` runs BEFORE the material, so anything it abandons leaves the material's `op:` references dangling."""

import os
import shutil
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou  # noqa: E402

from amaze.core import material  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log

ROOT = "/obj/Amaze"


class TheCopRootCase(unittest.TestCase):

    def setUp(self):
        existing = hou.node(ROOT)    # a root left by an earlier test would make every assertion here read the wrong scene
        if existing is not None:
            existing.destroy()
        self.addCleanup(self._sweep)
        self.handler = nodes.NodeHandler.__new__(nodes.NodeHandler)

    def _sweep(self):
        leftover = hou.node(ROOT)
        if leftover is not None:
            leftover.destroy()

    def _make_root(self):
        """The root exactly as restore_cop_companion makes it."""
        root = hou.node("/obj").createNode("subnet")
        root.setName("Amaze")
        self.handler._created_cop_root = root
        return root

    def test_a_rollback_takes_the_root_it_made_back_out(self):
        root = self._make_root()
        net = root.createNode("copnet", "companion")
        self.handler._created_cop_net = net

        self.handler._undo_cop_companion()

        self.assertIsNone(
            hou.node(ROOT),
            "the refused import left an empty /obj/Amaze in the scene")

    def test_a_root_holding_another_material_s_network_stays(self):
        """The guard that makes this safe: a network another material restored is somebody's, and the root is its home."""
        root = self._make_root()
        theirs = root.createNode("copnet", "someone_elses")
        mine = root.createNode("copnet", "mine")
        self.handler._created_cop_net = mine

        self.handler._undo_cop_companion()

        surviving = hou.node(ROOT)
        self.assertIsNotNone(surviving, "a root still in use was removed")
        self.assertEqual(
            [theirs.name()], [c.name() for c in surviving.children()])

    def test_a_root_this_import_did_not_make_is_never_touched(self):
        """Reuse is not ownership: the root was already there, so it outlives this import whatever happens to the network."""
        root = hou.node("/obj").createNode("subnet")
        root.setName("Amaze")
        self.handler._created_cop_root = None
        net = root.createNode("copnet", "companion")
        self.handler._created_cop_net = net

        self.handler._undo_cop_companion()

        self.assertIsNotNone(
            hou.node(ROOT),
            "a root this import merely reused was destroyed")

    def test_nothing_created_means_nothing_removed(self):
        """The ordinary success path calls this too."""
        self.handler._created_cop_net = None
        self.handler._created_cop_root = None
        self.handler._undo_cop_companion()      # must not raise
        self.assertIsNone(hou.node(ROOT))


class ACompanionThatOnlyWarnedIsKept(unittest.TestCase):
    """`hou.LoadWarning` is raised on a load that SUCCEEDED, and this restore runs BEFORE the material - so destroying the network it filled leaves every `op:` reference in the material pointing at nothing."""

    def setUp(self):
        existing = hou.node(ROOT)
        if existing is not None:
            existing.destroy()
        self.addCleanup(self._sweep)
        self.handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
        self.handler._created_cop_root = None
        self.handler._created_cop_net = None

    def _sweep(self):
        leftover = hou.node(ROOT)
        if leftover is not None:
            leftover.destroy()

    def test_LoadWarning_really_is_caught_by_the_broad_clause(self):
        """The premise: without its own branch above, `except (OSError, hou.Error)` swallows the warning - so the fix is an ordering fix, not an added class."""
        try:
            raise hou.LoadWarning("Bad node type found: probe")
        except (OSError, hou.Error) as caught:
            swallowed = isinstance(caught, hou.LoadWarning)
        self.assertTrue(
            swallowed,
            "hou.LoadWarning is no longer caught by hou.Error, so the "
            "ordering this fix depends on has changed")

    def test_the_handler_catches_the_warning_before_hou_Error(self):
        """Source-derived, because the ORDER is the fix: `except hou.LoadWarning` has to sit above `except hou.Error`, or the subclass never gets its own branch."""
        import inspect
        source = inspect.getsource(nodes.NodeHandler.restore_cop_companion)
        warning_at = source.find("except hou.LoadWarning")
        error_at = source.find("except (OSError, hou.Error)")
        self.assertGreater(
            warning_at, -1,
            "restore_cop_companion does not catch hou.LoadWarning, so a "
            "companion that loaded with warnings is destroyed")
        self.assertLess(
            warning_at, error_at,
            "the LoadWarning branch sits BELOW hou.Error, which catches "
            "the subclass first and makes it unreachable")


class AWholeNetworkSaveKeepsItsDots(unittest.TestCase):
    """A network DOT is not a child, so a save built from `children()` drops it and every wire routed through it - the material comes back with missing inputs. ▸r/node-items"""

    def setUp(self):
        self.parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.parent.destroy)

    def _wired_through_a_dot(self):
        builder = self.parent.createNode("subnet", "builder")
        upstream = builder.createNode("null", "upstream")
        downstream = builder.createNode("null", "downstream")
        dot = builder.createNetworkDot()
        dot.setInput(0, upstream)
        downstream.setInput(0, dot)
        return builder, dot

    def test_the_dot_is_not_a_child_but_is_an_item(self):
        """The premise, measured rather than assumed - if Houdini ever makes dots children, the fix below stops being needed."""
        builder, dot = self._wired_through_a_dot()
        self.assertNotIn(dot, builder.children())
        self.assertIn(dot, builder.allItems())

    def test_the_staged_save_asks_for_every_item(self):
        """Source-derived: the whole-network save must hand `saveItemsToFile` the items, never the children."""
        import inspect
        source = inspect.getsource(
            nodes.NodeHandler._save_staged_with_cop_companion)
        self.assertIn("allItems()", source,
                      "the Redshift/Octane save still collects children, "
                      "so a wire through a dot is dropped")
        self.assertNotIn(
            "save_node.children()", source,
            "children() is still what the save collects")

    def test_a_saved_file_carries_the_dot_back(self):
        builder, _dot = self._wired_through_a_dot()
        scratch = test_support.scratch_dir("amaze_test_dot_")
        self.addCleanup(shutil.rmtree, scratch, True)
        path = os.path.join(scratch, "with_a_dot.mat")
        builder.saveItemsToFile(builder.allItems(), path)
        restored = self.parent.createNode("subnet", "restored")
        restored.loadItemsFromFile(path)
        dots = [i for i in restored.allItems()
                if i not in restored.children()]
        self.assertTrue(
            dots,
            "the saved file carried no dot back, so the wire through it "
            "is gone from the restored network")


class ALooseSurfaceSaveKeepsAWireThroughADot(unittest.TestCase):
    """A surface saved on its own (`save_node_collect`) comes back fed as it was. ▸r/node-items"""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.home = hou.node("/mat").createNode("subnet", "dot_probe_home")
        self.addCleanup(self.home.destroy)

    def test_the_image_behind_a_dot_still_feeds_base_colour(self):
        image = self.home.createNode("mtlximage", "probe_image")
        surface = self.home.createNode("mtlxstandard_surface", "probe_surface")
        dot = self.home.createNetworkDot()
        dot.setInput(image, 0)
        surface.setInput(surface.inputIndex("base_color"), dot, 0)
        self.assertNotIn(dot, self.home.children(), "premise: the dot is a child")
        handler = nodes.NodeHandler(self.prefs)
        handler._renderer = "Karma"
        self.assertTrue(handler.save_node(surface, "dotprobe", False), "premise: no save")
        restored = self.home.createNode("subnet", "restored")
        restored.loadItemsFromFile(material.payload_path(self.prefs, "dotprobe", self.prefs.ext))
        copy = next(c for c in restored.children() if c.type().name() == "mtlxstandard_surface")
        fed = copy.input(copy.inputIndex("base_color"))
        self.assertEqual("mtlximage", fed.type().name() if fed is not None else None,
                         "the saved surface lost the wire that ran through a dot")

    def test_the_premise_copyNodesTo_drops_a_wire_through_a_dot(self):
        """Measured: if Houdini ever keeps the wire, the dot copy is no longer needed."""
        image = self.home.createNode("mtlximage", "premise_image")
        surface = self.home.createNode("mtlxstandard_surface", "premise_surface")
        dot = self.home.createNetworkDot()
        dot.setInput(image, 0)
        surface.setInput(surface.inputIndex("base_color"), dot, 0)
        self.assertEqual(image, surface.inputs()[surface.inputIndex("base_color")],
                         "inputs() no longer sees through a dot")
        scratch = self.home.createNode("subnet", "premise_copy")
        copy = next(c for c in hou.copyNodesTo([image, surface], scratch)
                    if c.type().name() == "mtlxstandard_surface")
        self.assertIsNone(copy.input(copy.inputIndex("base_color")),
                          "copyNodesTo now keeps the wire through an uncopied dot")


class AnImportCarriesNoOneElsesStamp(unittest.TestCase):
    """`assetlib_id` on an INNER node survives save and reload, so an imported copy would offer to update whichever library entry that inner node was once saved as. ▸r/inherited-stamps"""

    def setUp(self):
        self.parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.parent.destroy)
        self.scratch = test_support.scratch_dir("amaze_test_stamp_")
        self.addCleanup(shutil.rmtree, self.scratch, True)

    def _saved_with_a_stale_inner_stamp(self):
        """A material file whose inner node carries another entry's id, two levels deep."""
        builder = self.parent.createNode("subnet", "builder")
        deep = builder.createNode("subnet", "deep")
        leaf = deep.createNode("null", "leaf")
        leaf.setUserData("assetlib_id", "SOMEBODY-ELSES-ID")
        path = os.path.join(self.scratch, "stale.mat")
        builder.saveItemsToFile(builder.allItems(), path)
        builder.destroy()
        return path

    def test_the_premise_a_stamp_survives_the_round_trip(self):
        """Measured rather than assumed - if Houdini ever stops carrying userData through a save, the sweep stops being needed."""
        path = self._saved_with_a_stale_inner_stamp()
        raw = self.parent.createNode("subnet", "raw")
        raw.loadItemsFromFile(path)
        stamps = [n.userData("assetlib_id") for n in raw.allSubChildren()
                  if n.userData("assetlib_id")]
        self.assertIn(
            "SOMEBODY-ELSES-ID", stamps,
            "the stamp no longer survives a save, so this guard is moot")

    def test_a_strict_load_clears_every_inherited_stamp(self):
        path = self._saved_with_a_stale_inner_stamp()
        target = self.parent.createNode("subnet", "target")

        problem = nodes.load_items_strict(target, path)
        self.assertEqual("", problem, "the fixture did not load")

        left = [n.path() for n in target.allSubChildren()
                if n.userData("assetlib_id")]
        self.assertEqual(
            [], left,
            "an imported material still carries another entry's id, so a "
            "Save to Amaze on that inner node offers to overwrite it")

    def test_the_sweep_reaches_a_NESTED_node(self):
        """The stale stamp sits two subnets down; a children()-only sweep would miss it."""
        path = self._saved_with_a_stale_inner_stamp()
        target = self.parent.createNode("subnet", "nested")
        nodes.load_items_strict(target, path)
        depths = [n.path().count("/") for n in target.allSubChildren()]
        self.assertTrue(
            depths and max(depths) >= 5,
            "the fixture is not actually nested, so this proves nothing")

    def test_a_loose_node_has_its_OWN_stamp_cleared_too(self):
        """A network-destination import drops loose nodes into the user's own network, and each carries whatever stamp it was saved with."""
        loose = self.parent.createNode("subnet", "loose")
        loose.setUserData("assetlib_id", "STALE-TOP")
        inner = loose.createNode("null", "inner")
        inner.setUserData("assetlib_id", "STALE-INNER")

        nodes.clear_inherited_stamps(loose, include_self=True)

        self.assertIsNone(loose.userData("assetlib_id"))
        self.assertIsNone(inner.userData("assetlib_id"))

    def test_a_container_keeps_its_own_stamp_by_default(self):
        """The container sites stamp it themselves right after, so the default must not reach it - and must not touch the user's other nodes."""
        keeper = self.parent.createNode("subnet", "keeper")
        keeper.setUserData("assetlib_id", "THE-REAL-ONE")
        inner = keeper.createNode("null", "inner")
        inner.setUserData("assetlib_id", "STALE")

        nodes.clear_inherited_stamps(keeper)

        self.assertEqual("THE-REAL-ONE", keeper.userData("assetlib_id"))
        self.assertIsNone(inner.userData("assetlib_id"))

    def test_a_dot_in_the_network_does_not_stop_the_sweep(self):
        """Dots carry no userData at all, so a walk that touches it must tolerate them. ▸r/inherited-stamps"""
        holder = self.parent.createNode("subnet", "holder")
        holder.createNetworkDot()
        stamped = holder.createNode("null", "stamped")
        stamped.setUserData("assetlib_id", "STALE")

        cleared = nodes.clear_inherited_stamps(holder)

        self.assertEqual(1, cleared)
        self.assertIsNone(stamped.userData("assetlib_id"))


class AFailedSaveLeavesNoCompanionScratch(unittest.TestCase):
    """The companion is written to a scratch file first; a save that fails before the pair keeps none."""

    ASSET = "scratchprobe"

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        with hou.undos.disabler():
            cops = hou.node("/obj").createNode("copnet", "scratch_probe_cops")
            cops.createNode("constant", "plate")
        self.addCleanup(cops.destroy)
        self.builder = hou.node("/mat").createNode(
            "subnet", "scratch_probe_mat")
        self.addCleanup(self.builder.destroy)
        image = self.builder.createNode("mtlximage")
        image.parm("file").set("op:/obj/scratch_probe_cops/plate")
        self.builder.createNode("mtlxstandard_surface")

    def _scratches(self):
        folder = os.path.dirname(material.payload_path(
            self.prefs, self.ASSET, self.prefs.ext))
        return [name for name in os.listdir(folder)
                if name.startswith(self.ASSET + "_cop")]

    def test_a_raising_adoption_leaves_no_companion_scratch(self):
        handler = nodes.NodeHandler(self.prefs)
        handler._renderer = "Karma"
        with mock.patch.object(nodes.texstore, "adopt",
                               side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                handler.save_node(self.builder, self.ASSET, False)
        self.assertEqual(
            [], self._scratches(),
            "the companion's scratch file outlived a save that never "
            "reached the pair, and nothing else will ever remove it")
        self.assertIsNone(handler._pending_cop_promote,
                          "the handler still holds the dead companion")


class OneWalkFindsAndRewritesCopReferences(unittest.TestCase):
    """The `op:` parms a save collects are the ones it rewrites, a nested one included."""

    OLD = "op:/obj/cop_refs_probe/null1"
    NEW = "op:/obj/Amaze/probe/null1"

    def setUp(self):
        with hou.undos.disabler():
            self.copnet = hou.node("/obj").createNode("copnet", "cop_refs_probe")
            self.copnet.createNode("null")
            self.matnet = hou.node("/obj").createNode("matnet")
            inner = self.matnet.createNode("subnet")
            self.image = inner.createNode("mtlximage")
        self.addCleanup(self.copnet.destroy)
        self.addCleanup(self.matnet.destroy)
        self.image.parm("file").set(self.OLD)
        self.handler = nodes.NodeHandler.__new__(nodes.NodeHandler)

    def test_the_walk_collects_the_nested_parm_and_rewrites_that_same_parm(self):
        found = [(parm.path(), raw) for parm, raw in nodes.op_path_parms((self.matnet,))]
        self.assertEqual([(self.image.parm("file").path(), self.OLD)], found)
        refs = self.handler._collect_cop_refs((self.matnet,))
        self.assertEqual([(self.image.parm("file").path(), self.copnet.path())],
                         [(parm.path(), container.path()) for parm, _cop, container in refs])
        self.handler.rewrite_cop_refs((self.matnet,), {self.OLD: self.NEW})
        self.assertEqual(self.NEW, self.image.parm("file").unexpandedString())


if __name__ == "__main__":
    unittest.main()
