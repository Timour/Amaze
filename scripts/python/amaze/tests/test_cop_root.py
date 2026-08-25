"""The COP companion's scene root, and what a refused import leaves behind in `/obj` - driven against REAL nodes, because a leaked container is a scene-graph fact a mocked `hou` cannot show. `restore_cop_companion` runs BEFORE the material, so anything it abandons leaves the material's `op:` references dangling."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
