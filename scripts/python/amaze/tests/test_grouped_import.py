"""The multi-drop material import: one refusal ends it. ▸p/refusal-sink"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou                                                # noqa: E402

from amaze.core import debug                              # noqa: E402
from amaze.panel import panel as panel_module             # noqa: E402
from amaze.tests import test_support                      # noqa: E402,F401


class _Model:
    """Answers the three calls the walk makes, recording what it was asked."""

    def __init__(self, answers):
        self._answers = answers
        self.attempted = []

    def find_asset_row_by_id(self, aid):
        return self._answers[aid][0]

    def index(self, row, _column):
        return row

    def import_asset_to_scene(self, idx, _target, context_node=None):
        self.attempted.append(idx)
        for aid, (row, outcome) in self._answers.items():
            if row == idx:
                return outcome
        raise AssertionError("the walk asked for a row nobody declared")


class TheGroupedImportStopsAtTheFirstRefusalTest(unittest.TestCase):
    """The `break` is the aggregation: N assets must not mean N dialogs."""

    def setUp(self):
        self.panel = panel_module.MatLibPanel.__new__(
            panel_module.MatLibPanel)
        self.context = hou.node("/obj").createNode("geo", "dest")
        self.addCleanup(self.context.destroy)

    def _run(self, answers, ids):
        self.panel.material_model = _Model(answers)
        with mock.patch.object(debug, "refuse") as refused:
            self.panel._import_materials_into_context_grouped(
                self.context, ids)
        return self.panel.material_model, refused

    def test_a_refusal_stops_the_walk(self):
        model, refused = self._run(
            {"a": (0, (True, "", [])),
             "b": (1, (False, "gone", [])),
             "c": (2, (True, "", []))},
            ["a", "b", "c"])
        self.assertEqual(
            [0, 1], model.attempted,
            "the walk carried on past a refusal, so a multi-drop can "
            "raise one dialog per asset")
        self.assertEqual(1, refused.call_count)

    def test_every_asset_lands_when_none_refuses(self):
        model, refused = self._run(
            {"a": (0, (True, "", [])), "b": (1, (True, "", []))},
            ["a", "b"])
        self.assertEqual([0, 1], model.attempted)
        self.assertEqual([], refused.call_args_list,
                         "a clean multi-drop still spoke to the user")

    def test_an_id_the_model_does_not_hold_is_skipped_not_refused(self):
        """A missing row is `continue`, never `break`: one stale id must not stop the assets still there."""
        model, refused = self._run(
            {"gone": (-1, None), "b": (1, (True, "", []))},
            ["gone", "b"])
        self.assertEqual([1], model.attempted,
                         "a stale id was imported, or stopped the walk")
        self.assertEqual([], refused.call_args_list)

    def test_a_refusal_with_no_reason_does_not_speak(self):
        """`not ok` with an empty reason says nothing, and still stops the walk."""
        model, refused = self._run(
            {"a": (0, (False, "", [])), "b": (1, (True, "", []))},
            ["a", "b"])
        self.assertEqual([], refused.call_args_list)
        self.assertEqual([0, 1], model.attempted)

    def test_the_refusal_names_the_network_it_landed_in(self):
        _model, refused = self._run(
            {"a": (0, (False, "gone", []))}, ["a"])
        self.assertEqual(self.context.path(),
                         refused.call_args.kwargs.get("net"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
