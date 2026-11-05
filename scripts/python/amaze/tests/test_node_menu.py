"""The node right-click menu's Amaze submenu: Convert to Redshift, Convert to Karma, Save."""

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


def _materialx(test, name="menu_mtlx"):
    """A MaterialX material in /mat, its standard surface wired, as the converter tests build one."""
    made = nodes.build_karma_material(
        hou.node("/mat"), name,
        lambda builder: builder.createNode("mtlxstandard_surface"))
    test.addCleanup(made.builder.destroy)
    return made.builder


def _redshift(test, name="menu_rs"):
    """A classic Redshift builder holding a standard material wired to its terminal."""
    source = hou.node("/mat").createNode("redshift_vopnet", name)
    test.addCleanup(source.destroy)
    for child in list(source.children()):
        if child.type().name() != "redshift_material":
            child.destroy()
    shader = source.createNode("redshift::StandardMaterial")
    next(c for c in source.children() if c.type().name() == "redshift_material"
         ).setNamedInput("Surface", shader, 0)
    return source


def _geo(test, name="menu_geo"):
    geo = hou.node("/obj").createNode("geo", name)
    test.addCleanup(geo.destroy)
    return geo


class TheMenuIsOneAmazeSubmenu(unittest.TestCase):
    """One submenu, three items in a fixed order, every id stable because ids map to hotkeys."""

    def test_the_submenu_holds_the_two_converts_and_save(self):
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
        save = submenu.find("scriptItem[@id='amazeSave']")
        self.assertIn('rc_calls.save(kwargs.get("node", None))', save.findtext("scriptCode"))

    def test_no_label_is_computed(self):
        self.assertEqual([], list(ET.parse(MENU).getroot().iter("labelExpression")))


class TheMenuOffersWhatTheNodeCanBecome(unittest.TestCase):
    """The expressions run as Houdini runs them: a MaterialX material offers Redshift, never itself."""

    def _offered(self, kwargs):
        submenu = _submenu()
        converts = {target: _run(_expression(submenu.find("scriptItem[@id='%s']" % item_id)),
                                 kwargs)
                    for item_id, _label, target in CONVERTS}
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
        self.said, self.bar = [], []
        ui = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: self.said.append(text) or 0,
            setStatusMessage=lambda text, *a, **k: self.bar.append(text))
        patcher = mock.patch.object(hou, "ui", ui, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(hou.undos.clear)

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
        self.assertEqual([engine.why_not("", "Karma")], self.said)
        self.assertEqual((), hou.undos.undoLabels())

    def test_no_node_does_nothing(self):
        from amaze.utils import rc_calls
        rc_calls.convert(None, "Karma")
        self.assertEqual(([], []), (self.said, self.bar))


if __name__ == "__main__":
    unittest.main()
