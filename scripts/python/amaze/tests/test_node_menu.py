"""Node menu: one test per requirement in docs/requirements/node-menu.md."""

import os
import textwrap
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import branding, messages  # noqa: E402
from amaze.tests import test_support  # noqa: E402

try:    # without Houdini every test here skips
    import hou
    from amaze.render import nodes
    from amaze.render.material_conversion import engine
    from amaze.utils import rc_calls
except ImportError:
    hou = None

MENU = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))), "OPmenu.xml")


def _offered(item_id: str, node) -> bool:
    """A context expression run as Houdini runs a multi-line one: a function body that returns."""
    item = ET.parse(MENU).getroot().find(".//scriptItem[@id='%s']" % item_id)
    body = textwrap.indent(item.find("context").find("expression").text.strip("\n"), "    ")
    scope = {}
    exec("def _f(kwargs, hou):\n" + body, scope)
    return scope["_f"]({"node": node}, hou)


def _overlaps(a, b) -> bool:
    (ax, ay), (aw, ah) = a.position(), a.size()
    (bx, by), (bw, bh) = b.position(), b.size()
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


@unittest.skipUnless(hou, "Houdini is not loaded")
class _Menu(unittest.TestCase):
    """`hou.ui` recording what is said, Redshift loaded, and test materials in /mat."""

    def setUp(self):
        self.said, self.bar = [], []
        ui = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: self.said.append((text, k.get("details", ""))),
            setStatusMessage=lambda text, *a, **k: self.bar.append(text), paneTabs=lambda: ())
        for patcher in (mock.patch.object(hou, "ui", ui, create=True),
                        test_support.plugins_loaded("Redshift")):
            patcher.__enter__()
            self.addCleanup(patcher.__exit__, None, None, None)
        self.addCleanup(hou.undos.clear)
        self.addCleanup(lambda: [test_support.drop_node(node) for node in hou.node("/mat").children()
                                 if node.name().startswith("nm")])

    def material(self, name: str, parent=None):
        """A MaterialX material, its surface wired, in /mat or `parent`."""
        return nodes.build_karma_material(parent or hou.node("/mat"), name, lambda builder:
                                          builder.createNode("mtlxstandard_surface")).builder

    def converter(self, outcome: str = "whole"):
        """The converter builds a real copy, then: whole, unwired, no shader, or raises."""
        def convert(container, source, target, parent, name, report=None):
            copy = parent.createNode("subnet", name)
            copy.createNode("null")
            if outcome == "raises":
                raise hou.OperationFailed("the converter failed")
            shader = None if outcome == "no shader" else copy
            return engine.Converted(copy, shader, outcome != "unwired", report)
        patcher = mock.patch.object(engine, "convert", convert)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def inside(path: str) -> list:
        return sorted(child.name() for child in hou.node(path).children())

    def children(self) -> list:
        return sorted(child.name() for child in hou.node("/mat").children())


class SwapTest(_Menu):

    def test_nm01_a_swap_keeps_the_old_node_when_its_copy_fails_at_any_step(self):
        for outcome in ("unwired", "no shader", "raises"):
            with self.subTest(outcome):
                source = self.material("nm01_" + outcome.replace(" ", "_"))
                path, inside = source.path(), self.inside(source.path())
                self.converter(outcome)
                self.said = []
                rc_calls.convert(source, "Redshift", swap=True)
                self.assertEqual(inside, self.inside(path), "the old node was replaced")
                copy = hou.node(path + "_redshift")
                self.assertEqual(outcome == "unwired", copy is not None, "a failed copy was left")
                self.assertEqual(1, len(self.said), "the failure was not shown")

    def test_nm02_one_undo_puts_the_scene_back_after_a_convert_or_a_swap(self):
        for swap in (False, True):
            with self.subTest(swap=swap):
                source = self.material("nm02_%d" % swap)
                source.setPosition(hou.Vector2(3, -2))
                after = hou.node("/mat").createNode("null", "nm02_after_%d" % swap)
                after.setInput(0, source)
                path, before = source.path(), self.children()
                inside = self.inside(path)
                self.converter()
                hou.undos.clear()
                rc_calls.convert(source, "Redshift", swap=swap)
                self.assertNotEqual((before, inside), (self.children(), self.inside(path)),
                                    "premise: nothing was made")
                hou.undos.performUndo()
                back = hou.node(path)
                self.assertEqual(before, self.children(), "a copy was left, or a node lost")
                self.assertEqual((inside, hou.Vector2(3, -2)), (self.inside(path), back.position()))
                self.assertEqual([back], list(after.inputs()), "the old node's wire was lost")

    def test_nm03_a_broken_install_or_a_missing_plugin_never_breaks_the_menu(self):
        source = self.material("nm03")
        with mock.patch.object(rc_calls, "convertible", side_effect=ImportError("broken install")):
            self.assertFalse(_offered("amazeSwapToRedshift", source), "a broken install showed it")
        with test_support.plugins_loaded():
            self.assertFalse(_offered("amazeSwapToRedshift", source), "offered with no plugin")
        self.converter("raises")
        rc_calls.convert(source, "Redshift", swap=True)    # a raise out of it stops the menu
        self.assertEqual(1, len(self.said), "the failure was not shown")


class ConvertTest(_Menu):

    def test_nm20_only_a_renderer_the_material_can_reach_here_is_offered(self):
        source = self.material("nm20")
        self.assertTrue(_offered("amazeConvertToRedshift", source))
        self.assertFalse(_offered("amazeConvertToKarma", source), "offered the renderer it is")
        with test_support.plugins_loaded():
            self.assertFalse(_offered("amazeConvertToRedshift", source), "offered with no plugin")
        self.assertFalse(_offered("amazeConvertToRedshift", hou.node("/obj")), "offered on no material")

    def test_nm21_convert_builds_the_copy_beside_the_source(self):
        source = self.material("nm21")
        source.setPosition(hou.Vector2(7, -3))
        neighbour = hou.node("/mat").createNode("null", "nm21_neighbour")
        neighbour.setPosition(source.position() + hou.Vector2(2.5236, -0.9624))    # the next free tile
        inside = sorted(child.name() for child in source.children())
        self.converter()
        rc_calls.convert(source, "Redshift")
        copy = hou.node("/mat/nm21_redshift")
        self.assertFalse(_overlaps(copy, source) or _overlaps(copy, neighbour), "the copy lies on a node")
        self.assertLess((copy.position() - source.position()).length(), 8, "the copy is far away")
        self.assertTrue(copy.isCurrent() and copy.isSelected())
        self.assertEqual(inside, sorted(child.name() for child in source.children()))

    def test_nm22_swap_puts_the_copy_at_the_old_nodes_name_path_and_position(self):
        source = self.material("nm22")
        source.setPosition(hou.Vector2(4, 1))
        geo = hou.node("/obj").createNode("geo", "nm22_geo")
        self.addCleanup(test_support.drop_node, geo)
        geo.parm("shop_materialpath").set(source.path())
        self.converter()
        rc_calls.convert(source, "Redshift", swap=True)
        copy = hou.node(geo.parm("shop_materialpath").eval())
        self.assertEqual((True, "nm22", hou.Vector2(4, 1)),
                         ("null1" in self.inside(copy.path()), copy.name(), copy.position()))

    def test_nm23_a_right_click_acts_on_the_selection_in_the_network_shown(self):
        a, b, c = self.material("nm23_a"), self.material("nm23_b"), self.material("nm23_c")
        hidden_net = hou.node("/obj").createNode("matnet", "nm23_net")
        self.addCleanup(test_support.drop_node, hidden_net)
        hidden = self.material("nm23_hidden", hidden_net)
        for node in (a, b, hidden):
            node.setSelected(True, clear_all_selected=node is a)
        self.converter()
        rc_calls.convert(b, "Redshift")
        self.assertEqual(["nm23_a_redshift", "nm23_b_redshift"],
                         [name for name in self.children() if name.endswith("_redshift")])
        self.assertEqual(["nm23_hidden"], [child.name() for child in hidden_net.children()],
                         "a material selected in a network not shown was converted")
        rc_calls.convert(c, "Redshift")
        self.assertEqual(["nm23_a_redshift", "nm23_b_redshift", "nm23_c_redshift"],
                         [name for name in self.children() if name.endswith("_redshift")])

    def test_nm24_each_command_is_one_undo_step_named_after_it(self):
        for swap, label in ((False, "Convert to Redshift"), (True, "Convert and Swap to Redshift")):
            with self.subTest(label):
                source = self.material("nm24_%d" % swap)
                self.converter()
                hou.undos.clear()
                rc_calls.convert(source, "Redshift", swap=swap)
                self.assertEqual((label,), hou.undos.undoLabels())

    def test_nm25_a_node_that_cannot_convert_is_skipped_and_the_rest_convert(self):
        a, b = self.material("nm25_a"), self.material("nm25_b")
        plain = hou.node("/mat").createNode("null", "nm25_null")
        for node in (a, plain, b):
            node.setSelected(True, clear_all_selected=node is a)
        self.converter()
        rc_calls.convert(a, "Redshift")
        self.assertIn("nm25_b_redshift", self.children(), "the rest stopped at the skipped node")
        (text, details), = self.said
        self.assertIn("2 of 3", text)
        self.assertIn(messages.NODE_NOT_A_MATERIAL % "nm25_null", details)
        self.said = []
        rc_calls.convert(self.material("nm25_clean"), "Redshift")
        self.assertEqual(([], ["Amaze: " + messages.NODE_CONVERTED % ("nm25_clean", "Redshift")]),
                         (self.said, self.bar))

    def test_nm26_save_with_no_amaze_panel_open_tells_the_user_and_changes_nothing(self):
        source, other = self.material("nm26"), self.material("nm26_other")
        other.setSelected(True, clear_all_selected=True)
        rc_calls.save(source)
        self.assertEqual([messages.PANEL_NOT_OPEN % branding.APP_NAME],
                         [text for text, _details in self.said])
        self.assertEqual([other], list(hou.selectedNodes()))


if __name__ == "__main__":
    unittest.main()
