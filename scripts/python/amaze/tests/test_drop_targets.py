"""What a release over a network editor may wire itself to - every scripted sequence's measurements are ▸r/drop-targets."""

import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(    # THREE dirnames: tests/ -> amaze/ -> python/.
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import dragengine  # noqa: E402


class ScriptedEditor(object):
    """Answers exactly what it is told to, and keeps the box it was asked with so a test can pin the RADIUS."""

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


class ScriptedPane(object):
    """A pane tab answering a fixed kind and screen rect, so the pane-tracking tests need no desktop."""

    def __init__(self, rect):
        self._rect = rect

    def type(self):
        return "kind-probe"

    def qtScreenGeometry(self):
        return self._rect


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
        # released dead centre, a neighbour's input sorting first must not get wired: containment outranks the whole list ▸r/drop-targets
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
        # a node body vetoes only where the cursor is INSIDE it; a neighbour standing nearby is stepped over
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
        # placement runs before this question, so the fresh node under the cursor must not answer about itself ▸r/drop-targets
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
        # its stubs sit OUTSIDE its body, so a release near its own edge would wire it to itself
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
        # the guard is the CALLER's to pass; a forgotten one fails here rather than silently in someone's network
        landed = self.node("unexcluded")
        target = self.node("unreachable_target")
        point = hou.Vector2(0.0, -0.30)
        editor = ScriptedEditor(
            [(landed, "node", 0), (target, "output", 0)],
            {landed: _rect(0.0, -0.30), target: _rect(0.0, 0.0)})
        self.assertEqual(
            dragengine.connector_under_cursor(editor, point),
            (None, "", -1))


class TestTheWiringSurvivesAStaleConnectorIndex(DropTargetTest):
    """A connector index is picked during the hover and spent at the RELEASE, so the network has a whole gesture in which to lose it - `setInput` answers a gone index with `hou.InvalidInput`, and a drop that lets that out dies mid-gesture instead of landing quietly. ▸r/drop-targets"""

    def test_a_live_output_index_still_wires(self):
        # the degrade tests below mean nothing unless this path really reaches `setInput`
        target = self.node("live_output_target")
        landed = self.node("live_output_landed")
        self.assertTrue(
            dragengine.connect_to_neighbour((target, "output", 0), [landed]))
        self.assertEqual(landed.inputs(), (target,))

    def test_a_live_input_index_still_wires(self):
        target = self.node("live_input_target")
        landed = self.node("live_input_landed")
        self.assertTrue(
            dragengine.connect_to_neighbour((target, "input", 0), [landed]))
        self.assertEqual(target.inputs(), (landed,))

    def test_a_stale_output_index_drops_without_wiring(self):
        target = self.node("stale_output_target")
        landed = self.node("stale_output_landed")
        stale = len(target.outputConnectors())    # one past the end - the index the hit test reported before the node lost an output
        with self.assertRaises(hou.InvalidInput):
            landed.setInput(0, target, stale)    # the host's own documented answer, pinned here so this cannot pass for want of a raise
        self.assertFalse(
            dragengine.connect_to_neighbour((target, "output", stale),
                                            [landed]))
        self.assertEqual(landed.inputs(), ())

    def test_a_stale_input_index_drops_without_wiring(self):
        target = self.node("stale_input_target")
        landed = self.node("stale_input_landed")
        stale = len(target.inputConnectors())
        with self.assertRaises(hou.InvalidInput):
            target.setInput(stale, landed)
        self.assertFalse(
            dragengine.connect_to_neighbour((target, "input", stale),
                                            [landed]))
        self.assertEqual(target.inputs(), ())


class TestTheGhostTick(DropTargetTest):
    """The outline follows every move; the expensive target questions run on the engine's tick - a saturated loop reads as an outline that freezes and then leaps. ▸p/drag-move-cost"""

    def setUp(self):
        super().setUp()
        dragengine.begin("material")

    def tearDown(self):
        dragengine.end()
        super().tearDown()

    def test_the_tick_passes_once_per_interval(self):
        editor = ScriptedEditor([], {})
        t0 = 1000.0
        self.assertTrue(dragengine.ghost_tick(editor, now=t0),
                        "a fresh gesture's first move must resolve")
        self.assertFalse(dragengine.ghost_tick(editor, now=t0 + 0.001),
                         "the second move re-asked inside the interval")
        self.assertTrue(dragengine.ghost_tick(    # 1.01: float subtraction lands a hair under the interval at the exact boundary, and the pin is the cadence, not the boundary
            editor, now=t0 + dragengine.PICK_INTERVAL * 1.01))

    def test_an_editor_change_forces_a_fresh_resolve(self):
        one = ScriptedEditor([], {})
        two = ScriptedEditor([], {})
        t0 = 1000.0
        self.assertTrue(dragengine.ghost_tick(one, now=t0))
        self.assertTrue(
            dragengine.ghost_tick(two, now=t0 + 0.001),
            "crossing into another editor must not serve the old "
            "editor's answers for the rest of the interval")

    def test_a_new_gesture_forgets_the_previous_answers(self):
        editor = ScriptedEditor([], {})
        dragengine.ghost_tick(editor, now=1000.0)
        dragengine.set_ghost_answers(True, (None, "x", 3), "copnet")
        dragengine.begin("material")
        blocked, target, type_name = dragengine.ghost_answers()
        self.assertFalse(blocked)
        self.assertEqual((None, "", -1), tuple(target))
        self.assertEqual("", type_name)
        self.assertTrue(
            dragengine.ghost_tick(ScriptedEditor([], {}), now=1000.001),
            "a fresh gesture must resolve on its first move")

    def test_forbidden_drop_on_wire_skips_the_hit_test(self):
        editor = ScriptedEditor([], {})
        stub = types.SimpleNamespace(
            allowDropOnWireNetworkSpecific=lambda _e, _i: False)
        with mock.patch.dict(sys.modules, {"nodegraphprefs": stub}):
            found = dragengine.wire_under_cursor(
                editor, hou.Vector2(0.0, 0.0))
        self.assertEqual((None, "", -1), found)
        self.assertIsNone(
            editor.asked_with,
            "the box was queried for an answer the preference had "
            "already refused")

    def test_the_pane_is_looked_up_once_and_held_by_its_rect(self):
        from PySide6 import QtCore, QtGui
        looked = []
        pane = ScriptedPane(QtCore.QRect(0, 0, 100, 100))
        with mock.patch.object(dragengine, "pane_tab_under_cursor",
                               side_effect=lambda: looked.append(1) or pane), \
             mock.patch.object(QtGui.QCursor, "pos",
                               return_value=QtCore.QPoint(50, 50)):
            t0 = 1000.0
            tab, kind, fresh = dragengine.pane_under_cursor_tracked(now=t0)
            self.assertTrue(fresh)
            self.assertIs(tab, pane)
            self.assertEqual("kind-probe", kind)
            tab, kind, fresh = dragengine.pane_under_cursor_tracked(
                now=t0 + 0.01)
            self.assertFalse(fresh, "inside the rect, within the "
                             "revalidate window, the cache answers")
            self.assertEqual(1, len(looked),
                             "the cursor never left the pane and the "
                             "desktop was walked again anyway")

    def test_leaving_the_rect_forces_an_immediate_lookup(self):
        from PySide6 import QtCore, QtGui
        looked = []
        pane = ScriptedPane(QtCore.QRect(0, 0, 100, 100))
        with mock.patch.object(dragengine, "pane_tab_under_cursor",
                               side_effect=lambda: looked.append(1) or pane), \
             mock.patch.object(QtGui.QCursor, "pos",    # only read once a rect exists, so one OUTSIDE point serves both calls
                               return_value=QtCore.QPoint(500, 50)):
            t0 = 1000.0
            dragengine.pane_under_cursor_tracked(now=t0)
            _tab, _kind, fresh = dragengine.pane_under_cursor_tracked(
                now=t0 + 0.001)
            self.assertTrue(fresh, "the cursor left the cached rect and "
                            "the stale pane was served anyway")
            self.assertEqual(2, len(looked))

    def test_the_hold_expires_on_the_revalidate_interval(self):
        from PySide6 import QtCore, QtGui
        looked = []
        pane = ScriptedPane(QtCore.QRect(0, 0, 100, 100))
        with mock.patch.object(dragengine, "pane_tab_under_cursor",
                               side_effect=lambda: looked.append(1) or pane), \
             mock.patch.object(QtGui.QCursor, "pos",
                               return_value=QtCore.QPoint(50, 50)):
            t0 = 1000.0
            dragengine.pane_under_cursor_tracked(now=t0)
            dragengine.pane_under_cursor_tracked(
                now=t0 + dragengine.PANE_REVALIDATE * 1.01)
            self.assertEqual(
                2, len(looked),
                "a pane covered by a floating window mid-gesture would "
                "never be noticed without the slow revalidate")

    def test_a_new_gesture_forgets_the_held_pane(self):
        from PySide6 import QtCore, QtGui
        looked = []
        pane = ScriptedPane(QtCore.QRect(0, 0, 100, 100))
        with mock.patch.object(dragengine, "pane_tab_under_cursor",
                               side_effect=lambda: looked.append(1) or pane), \
             mock.patch.object(QtGui.QCursor, "pos",
                               return_value=QtCore.QPoint(50, 50)):
            dragengine.pane_under_cursor_tracked(now=1000.0)
            dragengine.begin("material")
            dragengine.pane_under_cursor_tracked(now=1000.001)
            self.assertEqual(2, len(looked))

    def test_the_node_shape_is_resolved_once_per_type(self):
        calls = []
        real = hou.nodeType

        def counting(category, name):
            calls.append(name)
            return real(category, name)

        with mock.patch.object(hou, "nodeType", side_effect=counting):
            first = dragengine._shape_for("amaze_ghost_cache_probe")
            before = len(calls)
            second = dragengine._shape_for("amaze_ghost_cache_probe")
        self.assertEqual(first, second)
        self.assertEqual(
            before, len(calls),
            "the second ask went back to the host for a shape that "
            "cannot change within a session")


class TestTheReachIsTheHostsOwn(DropTargetTest):

    def test_it_asks_at_the_drop_radius(self):
        # the connector snap radius reaches twice the drop radius and put a neighbour's stub in the answer ▸r/drop-targets
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
        # source-derived: the snap radius is the obvious-looking call and the wrong one, so it must not creep back
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
