"""Where a released Node asset lands, and the verb that puts it there. ▸r/drop-resolution"""

import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import debug, dragengine  # noqa: E402
from amaze.helpers import helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _cop_node_type() -> str:
    """A simple COP type this build has - the names moved with Copernicus."""
    kinds = hou.copNodeTypeCategory().nodeTypes()
    for wanted in ("ramp", "gradient", "color", "constant", "noise"):
        if wanted in kinds:
            return wanted
    return sorted(kinds)[0]


def _fake_editor(net, items=(), cursor=(0.0, 0.0), under_cursor=True):
    """A Network View answering the four questions the resolver asks it."""
    return types.SimpleNamespace(
        type=lambda: hou.paneTabType.NetworkEditor,
        pwd=lambda: net,
        isUnderCursor=lambda: under_cursor,
        cursorPosition=lambda: hou.Vector2(*cursor),
        posToScreen=lambda pos: hou.Vector2(100.0, 100.0),
        networkItemsInBox=lambda a, b, for_drop=False: tuple(items),
    )


class _ReleaseCase(unittest.TestCase):
    """Shared harness: a real panel, and the pane handed in rather than found."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        self.addCleanup(self._clear_obj)

    def _clear_obj(self):
        """Object level back to empty, whatever a test built there."""
        for child in hou.node("/obj").children():
            try:
                child.destroy()
            except hou.OperationFailed:
                pass

    def _patch(self, editor):
        """Serve `editor` as the pane under the pointer for this test."""
        patch = mock.patch.object(dragengine, "pane_tab_under_cursor",
                                  return_value=editor)
        patch.start()
        self.addCleanup(patch.stop)


class TheReleaseResolvesToTheNetworkUnderThePointer(_ReleaseCase):
    """`_drop_context_under_cursor`: which network a release belongs to."""

    def setUp(self):
        super().setUp()
        self.matcher = self.panel.cop_model.is_container

    def test_empty_space_resolves_to_the_network_being_shown(self):
        """The plain case: blank canvas means the Network View's own network."""
        net = hou.node("/obj").createNode("copnet", "resolve_cop")
        self._patch(_fake_editor(net))
        self.assertEqual(
            net, self.panel._drop_context_under_cursor(self.matcher),
            "a release on blank canvas missed the network being shown")

    def test_a_container_under_the_pointer_takes_the_release(self):
        """Released ON a copnet, the nodes go inside it, not beside it."""
        net = hou.node("/obj").createNode("copnet", "target_cop")
        self._patch(_fake_editor(hou.node("/obj"), items=[(net,)]))
        self.assertEqual(
            net, self.panel._drop_context_under_cursor(self.matcher),
            "a release over a container landed beside it")

    def test_a_node_the_rule_rejects_falls_back_to_the_editor(self):
        """A node this section cannot fill is not a target."""
        obj = hou.node("/obj")
        geo = obj.createNode("geo", "not_a_target")
        self._patch(_fake_editor(obj, items=[(geo,)]))
        self.assertEqual(
            obj, self.panel._drop_context_under_cursor(lambda _node: False),
            "a rejected node swallowed the release")

    def test_a_bare_item_is_walked_like_a_tuple(self):
        """Hits arrive as tuples, and a bare item has to survive the walk too."""
        net = hou.node("/obj").createNode("copnet", "bare_cop")
        self._patch(_fake_editor(hou.node("/obj"), items=[net]))
        self.assertEqual(
            net, self.panel._drop_context_under_cursor(self.matcher))

    def test_a_pane_that_is_not_a_network_view_resolves_to_nothing(self):
        """A Parameter pane is a miss, and a miss is a normal drag outcome."""
        self._patch(types.SimpleNamespace(
            type=lambda: hou.paneTabType.Parm,
            pwd=lambda: hou.node("/obj")))
        self.assertIsNone(
            self.panel._drop_context_under_cursor(self.matcher))

    def test_no_pane_under_the_pointer_resolves_to_nothing(self):
        """Released over the desktop, nothing is consulted."""
        self._patch(None)
        self.assertIsNone(
            self.panel._drop_context_under_cursor(self.matcher))

    def test_the_chrome_of_a_pane_is_not_its_canvas(self):
        """Over a toolbar there are no items, so the shown network still wins."""
        net = hou.node("/obj").createNode("copnet", "chrome_cop")
        self._patch(_fake_editor(net, items=[(net,)], under_cursor=False))
        self.assertEqual(
            net, self.panel._drop_context_under_cursor(self.matcher))


class TheNodeDropLandsWhereItWasReleased(_ReleaseCase):
    """`drop_cop_at_release`: the Node section's release verb, end to end."""

    def setUp(self):
        super().setUp()
        self.section = self.panel.sections["cop"]

    def _saved_cop_asset(self):
        """A real COP network registered in the panel's own library."""
        source = hou.node("/obj").createNode("copnet", "drop_source")
        source.createNode(_cop_node_type(), "the_pixel")
        self.assertEqual("COP", self.panel.cop_model.add_asset(
            source, "", "", False, name="dropped_network"))
        source.destroy()
        return self.panel.cop_sorted_model.mapFromSource(
            self.panel.cop_model.index(
                len(self.panel.cop_model.assets) - 1, 0))

    def test_the_network_lands_in_the_editors_network_at_the_cursor(self):
        """The body centres on the release point - the host's own convention."""
        index = self._saved_cop_asset()
        dest = hou.node("/obj").createNode("copnet", "drop_dest")
        self._patch(_fake_editor(dest, cursor=(4.0, -2.5)))
        self.assertTrue(self.section.drop_cop_at_release(index))
        landed = dest.children()
        self.assertTrue(landed, "the release created nothing")
        anchor = helpers.centred_on(hou.Vector2(4.0, -2.5))
        self.assertAlmostEqual(
            anchor.x(), sum(n.position().x() for n in landed) / len(landed),
            msg="the nodes did not land where the release happened")
        self.assertAlmostEqual(
            anchor.y(), sum(n.position().y() for n in landed) / len(landed))

    def test_an_invalid_index_lands_nothing(self):
        """A drag armed on blank grid space arrives invalid, and row -1 indexes the LAST asset."""
        self._saved_cop_asset()
        dest = hou.node("/obj").createNode("copnet", "untouched")
        self._patch(_fake_editor(dest))
        self.assertFalse(
            self.section.drop_cop_at_release(QtCore.QModelIndex()))
        self.assertEqual((), dest.children(),
                         "an invalid index still built a network")

    def test_a_release_over_nothing_is_silent(self):
        """A miss builds nothing and reports no error."""
        index = self._saved_cop_asset()
        self._patch(None)
        self.assertFalse(self.section.drop_cop_at_release(index))

    def test_a_refused_context_goes_to_the_status_line_with_the_network(self):
        """A wrong context is bad AIM, so it takes the quiet door. ▸p/refusal-sink"""
        index = self._saved_cop_asset()
        dest = hou.node("/obj").createNode("matnet", "vop_dest")
        self._patch(_fake_editor(dest))
        with mock.patch.object(debug, "refuse") as refused:
            self.assertTrue(self.section.drop_cop_at_release(index))
        self.assertTrue(refused.call_args_list,
                        "premise: a VOP network refuses this asset")
        reason, data = (refused.call_args.args[0],
                        refused.call_args.kwargs)
        self.assertNotIsInstance(
            reason, debug.Damage,
            "a mismatched context was reported as library damage, which "
            "opens a dialog mid-gesture")
        self.assertEqual(dest.path(), data.get("net"),
                         "the refusal did not record WHICH network refused")


if __name__ == "__main__":
    unittest.main()
