"""The COP companion's scene root, and what a refused import leaves.

`restore_cop_companion` runs BEFORE the material loads, because the
material's `op:` references need the network to exist. So every
refusal after that point has to take the scaffolding back out - and
the rollback only ever removed the NETWORK, leaving `/obj/Amaze`
standing empty. The user was told nothing could be rebuilt and got a
container they never asked for, which is the complaint the network
rollback was written for, one level up.

Real nodes: the leak is a scene-graph fact, and a mocked hou proves
nothing about what is left in `/obj`.
"""

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
        # A root left by an earlier test would make every assertion
        # here read the wrong scene.
        existing = hou.node(ROOT)
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
        """The guard that makes this safe: a network another material
        restored is somebody's, and the root is its home."""
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
        """Reuse is not ownership: the root was already there, so it
        outlives this import whatever happens to the network."""
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


if __name__ == "__main__":
    unittest.main()
