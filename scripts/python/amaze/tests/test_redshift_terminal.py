"""The renders-black invariant on Redshift, which ends a material in a terminal NODE rather than a named connector - so a Karma-shaped check answers False for every Redshift asset. The plugin cases skip where Redshift is absent; the spelling cases never do. ▸archive/test_redshift_terminal.py
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

from amaze.core import material  # noqa: E402
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


class TheTwoTerminalsDoNotSpellTheirInputsAlike(unittest.TestCase):
    """`inputNames()` names the terminal inputs; `inputLabels()` answers the generic ones. The two Redshift terminals SPELL A BUMP DIFFERENTLY, so asking for one form drops it on every material of the other. Needs no plugin - the roles are a table."""

    SENTINEL = object()

    def test_the_usd_terminals_bump_spelling_is_found(self):
        """The polarity that was red before the table existed."""
        self.assertIs(
            self.SENTINEL,
            material.terminal_input({"BumpMap": self.SENTINEL}, "bump"))

    def test_the_classic_terminals_bump_spelling_is_found(self):
        self.assertIs(
            self.SENTINEL,
            material.terminal_input({"Bump Map": self.SENTINEL}, "bump"))

    def test_displacement_is_one_spelling_on_both(self):
        self.assertIs(
            self.SENTINEL,
            material.terminal_input(
                {"Displacement": self.SENTINEL}, "displacement"))

    def test_a_role_with_nothing_wired_answers_none(self):
        self.assertIsNone(
            material.terminal_input({"Surface": self.SENTINEL}, "bump"))

    def test_a_role_the_table_does_not_name_is_a_programming_error(self):
        """Silence here would be a lookup that never fires - the bug."""
        with self.assertRaises(KeyError):
            material.terminal_input({}, "diffuse")


class NoTerminalInputIsLookedUpByHand(unittest.TestCase):
    """The spellings have ONE home, and the hand-written form is made to stop working so it cannot come back."""

    def test_the_package_asks_through_terminal_input(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for base, _dirs, files in os.walk(root):
            if os.path.basename(base) == "tests":
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                for spellings in material.TERMINAL_INPUTS.values():
                    for spelling in spellings:
                        if 'get("%s")' % spelling in text:
                            offenders.append(
                                (os.path.relpath(path, root), spelling))
        self.assertEqual(
            [], offenders,
            "a terminal input is looked up by hand - go through "
            "material.terminal_input so both spellings are tried")


@unittest.skipUnless(_redshift_available(),
                     "the Redshift plugin is not installed")
class TheSpellingTableIsWhatThePluginSays(unittest.TestCase):
    """The table is a MEASUREMENT, so the plugin gets to refute it - runs on any host carrying Redshift."""

    def _terminal(self, parent, builder_type, terminal_type):
        builder = parent.createNode(builder_type)
        self.addCleanup(builder.destroy)
        for child in builder.children():
            if child.type().name() == terminal_type:
                return child
        self.fail("no %s among %r" % (
            terminal_type, [c.type().name() for c in builder.children()]))

    def _classic(self):
        parent = hou.node("/mat") or hou.node("/").createNode("mat")
        return self._terminal(parent, "redshift_vopnet", "redshift_material")

    def _usd(self):
        lib = hou.node("/stage").createNode("materiallibrary")
        self.addCleanup(lib.destroy)
        return self._terminal(
            lib, "rs_usd_material_builder", "redshift_usd_material")

    def test_the_classic_terminal_names_every_role_the_table_claims(self):
        names = self._classic().inputNames()
        self.assertIn("Surface", names)
        self.assertIn("Displacement", names)
        self.assertIn("Bump Map", names)

    def test_the_usd_terminal_spells_bump_without_a_space(self):
        names = self._usd().inputNames()
        self.assertIn("BumpMap", names)
        self.assertNotIn("Bump Map", names)
        self.assertIn("Displacement", names)

    def test_the_generic_Input_N_strings_are_the_LABELS(self):
        """The misreading that sent batch 4 after the wrong half."""
        terminal = self._classic()
        self.assertEqual("Surface", terminal.inputNames()[0])
        self.assertEqual("Input 1", terminal.inputLabels()[0])


if __name__ == "__main__":
    unittest.main()
