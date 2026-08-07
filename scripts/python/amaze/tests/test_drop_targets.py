"""What a release over a network editor may wire itself to.

Three defects shipped here in one afternoon, none visible to a suite
that tested these two functions nowhere; the measurements behind every
scripted sequence below are in research.md - Network editor drop
targets.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

# THREE dirnames: tests/ -> amaze/ -> python/.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import dragengine  # noqa: E402


class ScriptedEditor(object):
    """Answers exactly what it is told to, and keeps the box it was
    asked with so a test can pin the RADIUS."""

    def __init__(self, triples, rects, scale=100.0):
        self._triples = triples
        self._rects = rects
        self._scale = scale
        self.asked_with = None

    def posToScreen(self, pos):
        return hou.Vector2(pos.x() * self._scale, pos.y() * self._scale)

    def lengthToScreen(self, length):
        return length * self._scale

    def networkItemsInBox(self, p1, p2, for_drop=False):
        self.asked_with = (p1, p2, for_drop)
        return list(self._triples)

    def itemRect(self, item, adjusted=True):
        try:
            return self._rects[item]
        except KeyError:
            raise hou.OperationFailed("no rect for this item")


def _rect(x, y, w=0.71, h=0.50):
    """A node body the size H22 draws one, centred on x, y."""
    return hou.BoundingRect(x - w / 2.0, y - h / 2.0,
                            x + w / 2.0, y + h / 2.0)


class DropTargetTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.net = hou.node("/obj").createNode(
            "geo", "amaze_drop_target_probe")

    @classmethod
    def tearDownClass(cls):
        cls.net.destroy()

    def setUp(self):
        self._made = []

    def tearDown(self):
        for node in self._made:
            try:
                node.destroy()
            except hou.ObjectWasDeleted:
                pass

    def node(self, name):
        made = self.net.createNode("null", name)
        self._made.append(made)
        return made


class TestTheConnectorQuestion(DropTargetTest):

    def test_below_a_node_takes_its_output(self):
        target = self.node("below_target")
        point = hou.Vector2(0.0, -0.30)
        editor = ScriptedEditor(
            [(target, "output", 0), (target, "node", 0)],
            {target: _rect(0.0, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point),
            (target, "output", 0))

    def test_above_a_node_takes_its_input(self):
        target = self.node("above_target")
        point = hou.Vector2(0.0, 0.30)
        editor = ScriptedEditor(
            [(target, "input", 0), (target, "node", 0)],
            {target: _rect(0.0, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point),
            (target, "input", 0))

    def test_the_second_input_index_survives(self):
        target = self.node("indexed_target")
        point = hou.Vector2(0.0, 0.30)
        editor = ScriptedEditor(
            [(target, "input", 2)], {target: _rect(0.0, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point),
            (target, "input", 2))

    def test_on_the_body_wires_nothing(self):
        target = self.node("body_target")
        point = hou.Vector2(0.0, 0.0)
        editor = ScriptedEditor(
            [(target, "node", 0), (target, "output", 0),
             (target, "input", 0)],
            {target: _rect(0.0, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point),
            (None, "", -1))

    def test_on_the_body_a_neighbours_stub_does_not_win(self):
        # DEFECT THREE: released dead centre on a node, a neighbour's
        # input sorted first and got wired, so containment has to
        # outrank the whole list rather than the entries before it.
        body = self.node("crowded_body")
        neighbour = self.node("crowded_neighbour")
        point = hou.Vector2(0.0, 0.0)
        editor = ScriptedEditor(
            [(neighbour, "input", 0), (body, "node", 0)],
            {body: _rect(0.0, 0.0), neighbour: _rect(0.0, 0.9)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point),
            (None, "", -1))

    def test_a_neighbour_sorting_first_does_not_steal_the_target(self):
        # A node body in the list vetoes only where the cursor is
        # INSIDE it; a neighbour standing nearby is stepped over.
        aimed = self.node("aimed_at")
        neighbour = self.node("standing_nearby")
        point = hou.Vector2(0.0, -0.30)
        editor = ScriptedEditor(
            [(neighbour, "node", 0), (aimed, "output", 0)],
            {aimed: _rect(0.0, 0.0), neighbour: _rect(0.9, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point),
            (aimed, "output", 0))

    def test_nothing_under_the_cursor_answers_nothing(self):
        editor = ScriptedEditor([], {})
        self.assertEqual(
            dragengine.connector_under_cursor(
                editor, hou.Vector2(0.0, 0.0)),
            (None, "", -1))

    def test_a_missing_rect_does_not_take_the_app_down(self):
        target = self.node("rectless")
        editor = ScriptedEditor([(target, "output", 0)], {})
        self.assertEqual(
            dragengine.connector_under_cursor(
                editor, hou.Vector2(0.0, -0.30)),
            (target, "output", 0))

    def test_a_missing_editor_answers_nothing(self):
        self.assertEqual(
            dragengine.connector_under_cursor(
                None, hou.Vector2(0.0, 0.0)),
            (None, "", -1))
        target = self.node("no_position")
        editor = ScriptedEditor([(target, "output", 0)],
                                {target: _rect(0.0, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, None),
            (None, "", -1))


class TestWhatJustLandedIsNeverTheTarget(DropTargetTest):

    def test_the_landed_node_does_not_answer_about_itself(self):
        # DEFECT TWO: placement runs before this question, so the
        # fresh node is under the cursor and its own body used to make
        # the rule read an ordinary drop and refuse to wire anything.
        landed = self.node("just_landed")
        target = self.node("real_target")
        point = hou.Vector2(0.0, -0.30)
        editor = ScriptedEditor(
            [(landed, "node", 0), (target, "output", 0)],
            {landed: _rect(0.0, -0.30), target: _rect(0.0, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point,
                                              exclude=[landed]),
            (target, "output", 0))

    def test_the_landed_node_never_wires_to_itself(self):
        # Its stubs sit OUTSIDE its body, so a release near its own
        # edge would wire it to itself with nothing else in reach.
        landed = self.node("landed_with_stubs")
        point = hou.Vector2(0.0, -0.30)
        editor = ScriptedEditor(
            [(landed, "output", 0), (landed, "input", 0)],
            {landed: _rect(0.0, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point,
                                              exclude=[landed]),
            (None, "", -1))

    def test_without_the_exclusion_it_still_refuses(self):
        # The guard is the CALLER's to pass; a call site that forgets
        # it fails here rather than silently in someone's network.
        landed = self.node("unexcluded")
        target = self.node("unreachable_target")
        point = hou.Vector2(0.0, -0.30)
        editor = ScriptedEditor(
            [(landed, "node", 0), (target, "output", 0)],
            {landed: _rect(0.0, -0.30), target: _rect(0.0, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point),
            (None, "", -1))


class TestTheReachIsTheHostsOwn(DropTargetTest):

    def test_it_asks_at_the_drop_radius(self):
        # DEFECT ONE: the connector snap radius reaches over twice as
        # far as the drop radius the host's own node drop uses, which
        # put a neighbour's stub in the answer.
        target = self.node("radius_probe")
        editor = ScriptedEditor([(target, "output", 0)],
                                {target: _rect(0.0, 0.0)})
        dragengine.connector_under_cursor(
            editor, hou.Vector2(0.0, -0.30))
        p1, p2, for_drop = editor.asked_with
        self.assertTrue(for_drop, "the box must be a DROP question")
        self.assertAlmostEqual(
            (p2.x() - p1.x()) / 2.0,
            editor.lengthToScreen(dragengine.DROP_TARGET_RADIUS),
            places=6)

    def test_the_wire_question_asks_at_the_same_radius(self):
        editor = ScriptedEditor([], {})
        dragengine.wire_under_cursor(editor, hou.Vector2(0.0, 0.0))
        if editor.asked_with is None:
            self.skipTest("the drop-on-wire preference is off here")
        p1, p2, _for_drop = editor.asked_with
        self.assertAlmostEqual(
            (p2.x() - p1.x()) / 2.0,
            editor.lengthToScreen(dragengine.DROP_TARGET_RADIUS),
            places=6)

    def test_the_engine_does_not_reach_for_the_snap_radius(self):
        # Source-derived: the snap radius is the obvious-looking call
        # and the wrong one, so it must not creep back.
        path = dragengine.__file__.replace(".pyc", ".py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        offenders = [line for line in source.splitlines()
                     if "getConnectorSnapRadius" in line
                     and not line.strip().startswith("#")]
        self.assertEqual(
            offenders, [],
            "the drop question asks at the DROP radius; the connector "
            "snap radius reaches a neighbour's stubs")


if __name__ == "__main__":
    unittest.main()
