"""The node right-click menu's Amaze submenu: the converts, the swaps, Save."""

import os
import sys
import textwrap
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import messages  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.render.material_conversion import engine  # noqa: E402
from amaze.tests import test_support  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
MENU = os.path.join(REPO, "OPmenu.xml")
KINDS = '("Sop", "Cop", "Lop", "Dop", "Top", "Chop", "Object", "Vop")'
CONVERTS = (("amazeConvertToRedshift", "Convert to Redshift", "Redshift"),
            ("amazeConvertToKarma", "Convert to Karma", "Karma"))
SWAPS = (("amazeSwapToRedshift", "Convert and Swap to Redshift", "Redshift"),
         ("amazeSwapToKarma", "Convert and Swap to Karma", "Karma"))
REDSHIFT = test_support.renderer_loaded("Redshift")
REDSHIFT_TYPE = hou.vopNodeTypeCategory().nodeTypes().get("redshift_vopnet") is not None


def _submenu():
    return ET.parse(MENU).getroot().find("menu").find("subMenu")


def _expression(element):
    return element.find("context").find("expression").text


def _run(expression, kwargs):
    """A context expression run as Houdini runs a multi-line one: a function body that returns."""
    scope = {}
    exec("def _f(kwargs, hou):\n" + textwrap.indent(expression.strip("\n"), "    "), scope)
    return scope["_f"](kwargs, hou)


def _gone(path):
    """Whatever holds `path` now destroyed: after a swap the twin holds the source's path."""
    node = hou.node(path)
    if node is not None:
        node.destroy()


def _materialx(test, name="menu_mtlx"):
    """A MaterialX material in /mat, its standard surface wired, as the converter tests build one."""
    made = nodes.build_karma_material(
        hou.node("/mat"), name,
        lambda builder: builder.createNode("mtlxstandard_surface"))
    test.addCleanup(_gone, made.builder.path())
    return made.builder


def _redshift(test, name="menu_rs"):
    """A classic Redshift builder holding a standard material wired to its terminal."""
    source = hou.node("/mat").createNode("redshift_vopnet", name)
    test.addCleanup(_gone, source.path())
    for child in list(source.children()):
        if child.type().name() != "redshift_material":
            child.destroy()
    shader = source.createNode("redshift::StandardMaterial")
    next(c for c in source.children() if c.type().name() == "redshift_material"
         ).setNamedInput("Surface", shader, 0)
    return source


def _select(*chosen):
    """Exactly `chosen` selected, as a drag-select in the network editor leaves them."""
    for node in hou.selectedNodes():
        node.setSelected(False)
    for node in chosen:
        node.setSelected(True)


def _geo(test, name="menu_geo"):
    geo = hou.node("/obj").createNode("geo", name)
    test.addCleanup(geo.destroy)
    return geo


def _speakers(test):
    """`hou.ui` patched to record its dialogs in `test.said` and its status line in `test.bar`."""
    test.said, test.bar, test.details = [], [], []
    ui = types.SimpleNamespace(
        displayMessage=lambda text, *a, **k: test.said.append(text)
        or test.details.append(k.get("details", "")) or 0,
        setStatusMessage=lambda text, *a, **k: test.bar.append(text))
    patcher = mock.patch.object(hou, "ui", ui, create=True)
    patcher.start()
    test.addCleanup(patcher.stop)
    test.addCleanup(hou.undos.clear)


def _overlaps(a, b):
    """Whether two nodes' tiles share any area in the network editor."""
    (ax, ay), (aw, ah) = a.position(), a.size()
    (bx, by), (bw, bh) = b.position(), b.size()
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


class TheMenuIsOneAmazeSubmenu(unittest.TestCase):
    """One submenu, three items in a fixed order, every id stable because ids map to hotkeys."""

    def test_the_submenu_holds_the_converts_the_swaps_and_save(self):
        root = ET.parse(MENU).getroot()
        submenus = list(root.iter("subMenu"))
        self.assertEqual(["amaze"], [s.get("id") for s in submenus])
        submenu = submenus[0]
        self.assertEqual("Amaze", submenu.find("label").text)
        self.assertIn("KINDS = " + KINDS, _expression(submenu),
                      "the submenu no longer offers itself where any section can take the node")
        children = [(c.tag, c.get("id"), c.findtext("label")) for c in submenu
                    if c.tag in ("scriptItem", "separatorItem")]
        self.assertEqual([
            ("scriptItem", "amazeConvertToRedshift", "Convert to Redshift"),
            ("scriptItem", "amazeConvertToKarma", "Convert to Karma"),
            ("separatorItem", "amazeSeparator", None),
            ("scriptItem", "amazeSwapToRedshift", "Convert and Swap to Redshift"),
            ("scriptItem", "amazeSwapToKarma", "Convert and Swap to Karma"),
            ("separatorItem", "amazeSeparator2", None),
            ("scriptItem", "amazeSave", "Save")], children)

    def test_each_item_calls_its_door(self):
        submenu = _submenu()
        for item_id, _label, target in CONVERTS:
            with self.subTest(item_id):
                item = submenu.find("scriptItem[@id='%s']" % item_id)
                self.assertIn('rc_calls.convertible(kwargs.get("node", None), "%s")' % target,
                              _expression(item))
                self.assertIn('rc_calls.convert(kwargs.get("node", None), "%s")' % target,
                              item.findtext("scriptCode"))
        for item_id, _label, target in SWAPS:
            with self.subTest(item_id):
                item = submenu.find("scriptItem[@id='%s']" % item_id)
                self.assertIsNotNone(item, "no %s item" % item_id)
                self.assertIn('rc_calls.convertible(kwargs.get("node", None), "%s")' % target,
                              _expression(item))
                self.assertIn('rc_calls.convert(kwargs.get("node", None), "%s", swap=True)'
                              % target, item.findtext("scriptCode"))
        save = submenu.find("scriptItem[@id='amazeSave']")
        self.assertIn('rc_calls.save(kwargs.get("node", None))', save.findtext("scriptCode"))

    def test_a_click_reloads_rc_calls_only_behind_the_dev_switch(self):
        """As the pypanel: a reload reruns the module body each click, so only the dev switch asks."""
        import importlib
        from amaze.utils import rc_calls
        items = list(_submenu().iter("scriptItem"))
        self.assertEqual(5, len(items))
        for switched in ("", "1"):
            for item in items:
                with self.subTest(item.get("id"), switched=switched), \
                        mock.patch.dict(os.environ, {"AMAZE_DEV_RELOAD": switched}), \
                        mock.patch.object(importlib, "reload") as reload, \
                        mock.patch.object(rc_calls, "convert"), \
                        mock.patch.object(rc_calls, "save"):
                    if not switched:
                        os.environ.pop("AMAZE_DEV_RELOAD")
                    exec(item.findtext("scriptCode"), {"kwargs": {}, "hou": hou})
                    self.assertEqual(bool(switched), reload.called,
                                     "the reload does not follow the dev switch")

    def test_no_label_is_computed(self):
        self.assertEqual([], list(ET.parse(MENU).getroot().iter("labelExpression")))


class TheMenuOffersWhatTheNodeCanBecome(unittest.TestCase):
    """The expressions run as Houdini runs them: a MaterialX material offers Redshift, never itself."""

    def _offered(self, kwargs):
        submenu = _submenu()
        converts = {target: _run(_expression(submenu.find("scriptItem[@id='%s']" % item_id)),
                                 kwargs)
                    for item_id, _label, target in CONVERTS}
        swaps = {}
        for item_id, _label, target in SWAPS:
            item = submenu.find("scriptItem[@id='%s']" % item_id)
            self.assertIsNotNone(item, "no %s item" % item_id)
            swaps[target] = _run(_expression(item), kwargs)
        self.assertEqual(converts, swaps, "a swap is offered where its convert is not, or the reverse")
        return bool(_run(_expression(submenu), kwargs)), converts

    def test_a_materialx_material_offers_redshift(self):
        shown, converts = self._offered({"node": _materialx(self)})
        self.assertTrue(shown, "the submenu is hidden on a material")
        self.assertFalse(converts["Karma"], "a MaterialX material is offered Karma")
        if REDSHIFT:
            self.assertTrue(converts["Redshift"], "a MaterialX material is not offered Redshift")
        else:
            self.assertFalse(converts["Redshift"], "Redshift is offered with no plugin loaded")

    @unittest.skipUnless(REDSHIFT_TYPE, "the Redshift plugin is not loaded")
    def test_a_redshift_material_offers_karma(self):
        shown, converts = self._offered({"node": _redshift(self)})
        self.assertTrue(shown, "the submenu is hidden on a Redshift material")
        self.assertEqual({"Redshift": False, "Karma": True}, converts)

    def test_a_geo_offers_save_alone(self):
        shown, converts = self._offered({"node": _geo(self)})
        self.assertTrue(shown, "the submenu is hidden on a geo network")
        self.assertEqual({"Redshift": False, "Karma": False}, converts)

    def test_no_node_offers_nothing(self):
        shown, converts = self._offered({})
        self.assertFalse(shown)
        self.assertEqual({"Redshift": False, "Karma": False}, converts)


class AConvertBuildsTheTwinBesideTheNode(unittest.TestCase):
    """One menu command, one undo step: the twin is current and selected, the source as it was."""

    def setUp(self):
        _speakers(self)

    def _convert(self, source, target):
        from amaze.core import renderers
        from amaze.utils import rc_calls
        parent = source.parent()
        before = set(parent.children())
        inside = sorted(c.name() for c in source.children())
        hou.undos.clear()    # the fixture's own steps are not the conversion's
        rc_calls.convert(source, target)
        made = [c for c in parent.children() if c not in before]
        for node in made:
            self.addCleanup(node.destroy)
        self.assertEqual(1, len(made), "not one twin: %s; said %s" % (made, self.said))
        twin, = made
        label = renderers.get(target).engine    # the menu's word: Karma, never the library's MaterialX
        self.assertEqual("%s_%s" % (source.name(), label.lower()), twin.name())
        self.assertTrue(twin.isCurrent(), "the twin is not the current node")
        self.assertTrue(twin.isSelected(), "the twin is not selected")
        self.assertEqual(inside, sorted(c.name() for c in source.children()),
                         "the conversion changed the source")
        self.assertEqual(("Convert to %s" % label,), hou.undos.undoLabels(),
                         "the conversion is not one undo step")
        return twin

    @unittest.skipUnless(REDSHIFT, "the Redshift plugin is not loaded")
    def test_a_materialx_material_becomes_redshift(self):
        source = _materialx(self, "menu_to_rs")
        twin = self._convert(source, "Redshift")
        self.assertEqual("Redshift", nodes.NodeHandler(None).get_renderer_from_node(twin))
        self.assertEqual([], self.said, "a clean conversion opened a dialog")
        self.assertEqual(['Amaze: ' + messages.NODE_CONVERTED % ("menu_to_rs", "Redshift")],
                         self.bar)

    @unittest.skipUnless(REDSHIFT_TYPE and REDSHIFT, "the Redshift plugin is not loaded")
    def test_a_redshift_material_becomes_karma(self):
        source = _redshift(self, "menu_to_mtlx")
        twin = self._convert(source, "Karma")
        self.assertEqual("Karma", nodes.NodeHandler(None).get_renderer_from_node(twin))
        self.assertEqual(1, len(self.said) + len(self.bar), "said nothing, or twice")

    def test_a_node_with_no_route_says_why(self):
        from amaze.utils import rc_calls
        geo = _geo(self, "menu_no_route")
        before = set(geo.parent().children())
        hou.undos.clear()
        rc_calls.convert(geo, "Karma")
        self.assertEqual(before, set(geo.parent().children()), "a geo was converted")
        self.assertEqual([messages.NODE_NOT_A_MATERIAL % "menu_no_route"], self.said)
        self.assertEqual((), hou.undos.undoLabels())

    def test_no_node_does_nothing(self):
        from amaze.utils import rc_calls
        rc_calls.convert(None, "Karma")
        self.assertEqual(([], []), (self.said, self.bar))

    @unittest.skipUnless(REDSHIFT, "the Redshift plugin is not loaded")
    def test_the_twin_lands_beside_the_source(self):
        source = _materialx(self, "menu_placed")
        source.setPosition(hou.Vector2(7, -3))
        twin = self._convert(source, "Redshift")
        self.assertNotEqual(hou.Vector2(0, 0), twin.position(), "the twin landed at the origin")
        self.assertNotEqual(source.position(), twin.position(), "the twin sits on the source")
        self.assertFalse(_overlaps(source, twin), "the twin overlaps the source")
        for axis in (0, 1):
            self.assertLessEqual(abs(twin.position()[axis] - source.position()[axis]), 4,
                                 "the twin is far from the source: %s" % twin.position())

    @unittest.skipUnless(REDSHIFT, "the Redshift plugin is not loaded")
    def test_the_twin_avoids_a_neighbour_on_its_tile(self):
        source = _materialx(self, "menu_crowded")
        source.setPosition(hou.Vector2(7, -3))
        neighbour = hou.node("/mat").createNode("subnet", "menu_neighbour")
        self.addCleanup(neighbour.destroy)
        neighbour.setPosition(source.position() + hou.Vector2(2.5236, -0.9624))    # the measured free tile
        twin = self._convert(source, "Redshift")
        self.assertFalse(_overlaps(source, twin), "the twin overlaps the source")
        self.assertFalse(_overlaps(neighbour, twin), "the twin overlaps the neighbour")
        for axis in (0, 1):    # far away overlaps nothing; the next free tile measured 5.05 across
            self.assertLessEqual(abs(twin.position()[axis] - source.position()[axis]), 8,
                                 "the twin is far from the source: %s" % twin.position())


class ASwapPutsTheTwinInTheNodesPlace(unittest.TestCase):
    """The old node destroyed, the twin at its exact name, path and position, all one undo step."""

    def setUp(self):
        _speakers(self)

    def _swap(self, source, target):
        from amaze.core import renderers
        from amaze.utils import rc_calls
        parent = source.parent()
        old_path, old_name, old_position = source.path(), source.name(), source.position()
        old_type = source.type().name()
        before = sorted(c.name() for c in parent.children())
        hou.undos.clear()    # the fixture's own steps are not the swap's
        rc_calls.convert(source, target, swap=True)
        twin = hou.node(old_path)
        self.assertIsNotNone(twin, "nothing holds the old path; said %s" % self.said)
        self.assertEqual(before, sorted(c.name() for c in parent.children()),
                         "the swap left a node behind or lost one")
        self.assertNotEqual(old_type, twin.type().name(), "the old node is still there")
        self.assertEqual(target, nodes.NodeHandler(None).get_renderer_from_node(twin))
        self.assertEqual(old_name, twin.name())
        self.assertEqual(old_path, twin.path())
        self.assertEqual(old_position, twin.position(), "the twin is not where the old node was")
        self.assertTrue(twin.isCurrent(), "the twin is not the current node")
        self.assertTrue(twin.isSelected(), "the twin is not selected")
        word = renderers.get(target).engine
        self.assertEqual(("Convert and Swap to %s" % word,), hou.undos.undoLabels(),
                         "the swap is not one undo step")
        return twin, old_type, before

    def _undo_brings_it_back(self, path, old_type, before):
        hou.undos.performUndo()
        back = hou.node(path)
        self.assertIsNotNone(back, "one undo did not bring the old node back")
        self.assertEqual(old_type, back.type().name())
        self.assertEqual(before, sorted(c.name() for c in back.parent().children()),
                         "one undo left the twin behind")

    @unittest.skipUnless(REDSHIFT, "the Redshift plugin is not loaded")
    def test_a_materialx_material_is_swapped_for_redshift(self):
        source = _materialx(self, "menu_swap_rs")
        source.setPosition(hou.Vector2(7, -3))
        path = source.path()
        _twin, old_type, before = self._swap(source, "Redshift")
        self.assertEqual([], self.said, "a clean swap opened a dialog")
        self.assertEqual(['Amaze: ' + messages.NODE_SWAPPED % ("menu_swap_rs", "Redshift")],
                         self.bar)
        self._undo_brings_it_back(path, old_type, before)

    @unittest.skipUnless(REDSHIFT_TYPE and REDSHIFT, "the Redshift plugin is not loaded")
    def test_a_redshift_material_is_swapped_for_karma(self):
        source = _redshift(self, "menu_swap_mtlx")
        path = source.path()
        _twin, old_type, before = self._swap(source, "Karma")
        self.assertEqual(1, len(self.said) + len(self.bar), "said nothing, or twice")
        self._undo_brings_it_back(path, old_type, before)

    @unittest.skipUnless(REDSHIFT, "the Redshift plugin is not loaded")
    def test_a_reference_by_path_reaches_the_new_material(self):
        source = _materialx(self, "menu_swap_ref")
        geo = _geo(self, "menu_swap_ref_geo")
        geo.parm("shop_materialpath").set(source.path())
        self._swap(source, "Redshift")
        reached = hou.node(geo.parm("shop_materialpath").eval())
        self.assertIsNotNone(reached, "the object's material path names nothing after the swap")
        self.assertEqual("Redshift", nodes.NodeHandler(None).get_renderer_from_node(reached))

    def test_a_swap_that_makes_no_shader_keeps_the_old_node(self):
        from amaze.utils import rc_calls
        source = _materialx(self, "menu_swap_none")
        parent, path, old_type = source.parent(), source.path(), source.type().name()
        before = sorted(c.name() for c in parent.children())
        hou.undos.clear()
        with mock.patch.object(engine, "why_not", lambda *a: ""), \
                mock.patch.object(engine, "convert",
                                  lambda node, source, target, parent, name, report=None:
                                  engine.Converted(None, None, False, report)):
            rc_calls.convert(source, "Redshift", swap=True)
        self.assertEqual(path, source.path(), "the old node was renamed or destroyed")
        self.assertEqual(old_type, hou.node(path).type().name())
        self.assertEqual(before, sorted(c.name() for c in parent.children()), "something was made")
        self.assertEqual([], self.bar)
        self.assertEqual((), hou.undos.undoLabels(), "a swap that made nothing left an undo step")
        self.assertEqual(1, len(self.said), "no summary dialog, or more than one")
        self.assertTrue(self.said[0].startswith(messages.CONVERSION_SUMMARY.split("%d")[0]),
                        self.said[0])


class ASelectionConvertsAsOne(unittest.TestCase):
    """A right-click on a selected node converts the whole selection, as the save door saves it."""

    def setUp(self):
        _speakers(self)

    def _made(self, parent, before):
        made = [c for c in parent.children() if c not in before]
        for node in made:
            self.addCleanup(_gone, node.path())
        return made

    @unittest.skipUnless(REDSHIFT, "the Redshift plugin is not loaded")
    def test_two_selected_materials_both_convert(self):
        from amaze.utils import rc_calls
        a, b = _materialx(self, "menu_sel_a"), _materialx(self, "menu_sel_b")
        before = set(a.parent().children())
        _select(a, b)
        hou.undos.clear()
        rc_calls.convert(b, "Redshift")
        made = self._made(a.parent(), before)
        self.assertEqual(["menu_sel_a_redshift", "menu_sel_b_redshift"],
                         sorted(n.name() for n in made), "said %s" % self.said)
        self.assertEqual([True, True], [n.isSelected() for n in made], "a twin is not selected")
        self.assertEqual(1, sum(n.isCurrent() for n in made), "no twin, or two, is current")
        self.assertEqual(("Convert to Redshift",), hou.undos.undoLabels())
        self.assertEqual([], self.said)
        self.assertEqual(['Amaze: ' + messages.NODES_CONVERTED % (2, "Redshift")], self.bar)

    @unittest.skipUnless(REDSHIFT, "the Redshift plugin is not loaded")
    def test_a_geo_in_the_selection_is_named_in_one_dialog(self):
        from amaze.core import renderers
        from amaze.utils import rc_calls
        a, geo = _materialx(self, "menu_sel_mix"), _geo(self, "menu_sel_geo")
        before = set(a.parent().children())
        _select(a, geo)
        hou.undos.clear()
        rc_calls.convert(a, "Redshift")
        made = self._made(a.parent(), before)
        self.assertEqual(["menu_sel_mix_redshift"], [n.name() for n in made])
        self.assertEqual(("Convert to Redshift",), hou.undos.undoLabels())
        self.assertEqual([], self.bar)
        self.assertEqual(1, len(self.said), "not one dialog: %s" % self.said)
        self.assertTrue(self.said[0].startswith("Converted 1 of 2 %s material(s) to Redshift."
                                                % renderers.label("Karma")), self.said[0])
        self.assertIn(messages.NODE_NOT_A_MATERIAL % "menu_sel_geo", self.details[0])

    @unittest.skipUnless(REDSHIFT, "the Redshift plugin is not loaded")
    def test_a_node_outside_the_selection_converts_alone(self):
        from amaze.utils import rc_calls
        a, b = _materialx(self, "menu_out_a"), _materialx(self, "menu_out_b")
        c = _materialx(self, "menu_out_c")
        before = set(a.parent().children())
        _select(a, b)
        hou.undos.clear()
        rc_calls.convert(c, "Redshift")
        made = self._made(a.parent(), before)
        self.assertEqual(["menu_out_c_redshift"], [n.name() for n in made])
        self.assertEqual(['Amaze: ' + messages.NODE_CONVERTED % ("menu_out_c", "Redshift")],
                         self.bar)

    @unittest.skipUnless(REDSHIFT, "the Redshift plugin is not loaded")
    def test_a_selection_swaps_in_one_undo_step(self):
        from amaze.utils import rc_calls
        a, b = _materialx(self, "menu_sw_a"), _materialx(self, "menu_sw_b")
        old_type = a.type().name()
        parent = a.parent()
        before = sorted(c.name() for c in parent.children())
        _select(a, b)
        hou.undos.clear()
        rc_calls.convert(a, "Redshift", swap=True)
        self.assertEqual(before, sorted(c.name() for c in parent.children()),
                         "the swap left a node behind or lost one")
        twins = [hou.node("/mat/menu_sw_a"), hou.node("/mat/menu_sw_b")]
        self.assertEqual(["Redshift", "Redshift"],
                         [nodes.NodeHandler(None).get_renderer_from_node(t) for t in twins])
        self.assertEqual([True, True], [t.isSelected() for t in twins], "a twin is not selected")
        self.assertEqual(("Convert and Swap to Redshift",), hou.undos.undoLabels())
        self.assertEqual(['Amaze: ' + messages.NODES_SWAPPED % (2, "Redshift")], self.bar)
        hou.undos.performUndo()
        self.assertEqual([old_type, old_type],
                         [hou.node("/mat/menu_sw_a").type().name(),
                          hou.node("/mat/menu_sw_b").type().name()],
                         "one undo did not bring both back")
        self.assertEqual(before, sorted(c.name() for c in parent.children()))


if __name__ == "__main__":
    unittest.main()
