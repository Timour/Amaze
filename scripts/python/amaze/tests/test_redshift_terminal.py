"""The renders-black invariant, on the renderer that holds most of it.

Redshift ends a material in a terminal NODE rather than a named
`surface` connector, so the Karma-shaped check answered False for every
Redshift asset in the real library (research.md > Redshift terminal
shape). Skipped where the plugin is absent, which is every H22
session on this machine.
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

from amaze.render import nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


def _redshift_available():
    try:
        return hou.vopNodeTypeCategory().nodeType("redshift_vopnet") is not None
    except Exception:                                        # noqa: BLE001
        return False


@unittest.skipUnless(_redshift_available(),
                     "the Redshift plugin is not loaded (H22 has no build)")
class RedshiftMaterialsHoldTheTerminalInvariant(unittest.TestCase):
    """ROADMAP 19. Both polarities, so a green cannot mean `always True`."""

    def setUp(self):
        self.parent = hou.node("/mat") or hou.node("/").createNode("mat")
        self.builder = self.parent.createNode("redshift_vopnet")
        self.addCleanup(self.builder.destroy)

    def _terminal(self):
        for child in self.builder.children():
            if child.type().name() in nodes.REDSHIFT_TERMINALS:
                return child
        self.fail("no Redshift terminal among %r"
                  % [c.type().name() for c in self.builder.children()])

    def test_a_stock_redshift_material_reads_as_wired(self):
        """A freshly created vopnet ships wired, and used to read False."""
        self.assertTrue(
            nodes.surface_terminal_wired(self.builder),
            "a stock redshift_vopnet must not report as renders-black")

    def test_an_unwired_terminal_is_caught(self):
        """The polarity that matters: this is the pitch-black material."""
        terminal = self._terminal()
        for index, connected in enumerate(terminal.inputs()):
            if connected is not None:
                terminal.setInput(index, None)
        self.assertFalse(
            nodes.surface_terminal_wired(self.builder),
            "a Redshift terminal with nothing wired must be caught")


if __name__ == "__main__":
    unittest.main()
