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


@unittest.skipUnless(test_support.renderer_loaded("Redshift"),
                     "the Redshift plugin is not loaded (H22 has no build)")
class RedshiftMaterialsHoldTheTerminalInvariant(unittest.TestCase):
    """ROADMAP 19. Both polarities, so a green cannot mean `always True`."""

    def setUp(self):
        self.parent = hou.node("/mat") or hou.node("/").createNode("mat")
        self.builder = self.parent.createNode("redshift_vopnet")
        self.addCleanup(self.builder.destroy)

    def _terminal(self):
        for child in self.builder.children():
            if child.type().name() in material.REDSHIFT_TERMINALS:
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

    def test_each_terminals_spelling_is_found_and_nothing_wired_is_none(self):
        """The USD bump spelling was red before the table existed."""
        for inputs, role in (({"BumpMap": self.SENTINEL}, "bump"),
                             ({"Bump Map": self.SENTINEL}, "bump"),
                             ({"Displacement": self.SENTINEL}, "displacement")):
            with self.subTest(inputs=list(inputs), role=role):
                self.assertIs(self.SENTINEL, material.terminal_input(inputs, role))
        self.assertIsNone(material.terminal_input({"Surface": self.SENTINEL}, "bump"))

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


@unittest.skipUnless(test_support.renderer_loaded("Redshift"),
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


class AContainerWithNoTerminalAnswersNone(unittest.TestCase):
    """The shared lookups on a container with no Redshift node in it; needs no plugin."""

    def test_neither_lookup_finds_anything(self):
        with hou.undos.disabler():
            subnet = hou.node("/obj").createNode("subnet")
        self.addCleanup(subnet.destroy)
        self.assertIsNone(material.redshift_terminal(subnet))
        self.assertIsNone(material.redshift_surface_shader(subnet))


@unittest.skipUnless(test_support.renderer_loaded("Redshift"),
                     "the Redshift plugin is not installed")
class OneLookupFindsTheTerminalAndTheShader(unittest.TestCase):
    """Both terminal forms and the stock shader, found by the helpers in `core/material.py`."""

    def _container(self, parent, builder_type):
        with hou.undos.disabler():
            builder = parent.createNode(builder_type)
        self.addCleanup(builder.destroy)
        return builder

    def test_both_terminal_forms_are_found(self):
        classic = self._container(hou.node("/mat") or hou.node("/").createNode("mat"),
                                  "redshift_vopnet")
        lib = self._container(hou.node("/stage"), "materiallibrary")
        usd = self._container(lib, "rs_usd_material_builder")
        for builder, terminal in ((classic, "redshift_material"), (usd, "redshift_usd_material")):
            with self.subTest(terminal=terminal):
                self.assertEqual(terminal, material.redshift_terminal(builder).type().name())

    def test_the_stock_shader_is_found_and_no_terminal_is_taken_for_it(self):
        parent = hou.node("/mat") or hou.node("/").createNode("mat")
        builder = self._container(parent, "redshift_vopnet")
        shader = material.redshift_surface_shader(builder)
        self.assertNotIn(shader.type().name(), material.REDSHIFT_TERMINALS)
        self.assertTrue(material.is_surface_shader_type(shader.type().name()))


if __name__ == "__main__":
    unittest.main()
