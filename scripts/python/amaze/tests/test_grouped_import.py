"""The multi-drop material import: the first failed import stops it. ▸p/refuse-vs-alert"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou

from amaze.actions import materials as material_actions
from amaze.core import debug
from amaze.panel import panel as panel_module
from amaze.tests import test_support                      # noqa: F401


class _Model:
    """Fakes the three model calls the import loop makes, recording each row it imports."""

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


class TheGroupedImportStopsAtTheFirstFailureTest(unittest.TestCase):
    """The `break` keeps it to one dialog: N failed assets must not open N dialogs."""

    def setUp(self):
        self.panel = panel_module.AmazePanel.__new__(
            panel_module.AmazePanel)
        self.context = hou.node("/obj").createNode("geo", "dest")
        self.addCleanup(self.context.destroy)

    def _run(self, answers, ids):
        self.panel.material_model = _Model(answers)
        with mock.patch.object(debug, "refuse") as refused, \
                mock.patch.object(material_actions, "import_asset_to_scene",
                                  lambda model, idx, target, context_node=None:
                                  model.import_asset_to_scene(idx, target, context_node)):
            self.panel.import_materials_into_context_grouped(
                self.context, ids)
        return self.panel.material_model, refused

    def test_a_failure_stops_the_loop(self):
        model, refused = self._run(
            {"a": (0, (True, "", [])),
             "b": (1, (False, "gone", [])),
             "c": (2, (True, "", []))},
            ["a", "b", "c"])
        self.assertEqual(
            [0, 1], model.attempted,
            "the import loop went on past a failed import, so a "
            "multi-drop can open one dialog per asset")
        self.assertEqual(1, refused.call_count)

    def test_every_asset_is_imported_when_none_fails(self):
        model, refused = self._run(
            {"a": (0, (True, "", [])), "b": (1, (True, "", []))},
            ["a", "b"])
        self.assertEqual([0, 1], model.attempted)
        self.assertEqual([], refused.call_args_list,
                         "a multi-drop with no failure still called `debug.refuse`")

    def test_an_id_the_model_does_not_hold_is_skipped_and_the_loop_continues(self):
        """A missing row is `continue`, never `break`: one stale id must not stop the assets still there."""
        model, refused = self._run(
            {"gone": (-1, None), "b": (1, (True, "", []))},
            ["gone", "b"])
        self.assertEqual([1], model.attempted,
                         "a stale id was imported, or stopped the import loop")
        self.assertEqual([], refused.call_args_list)

    def test_a_failure_with_no_reason_does_not_call_debug_refuse(self):
        """`not ok` with an empty reason does not call `debug.refuse`, and still stops the loop."""
        model, refused = self._run(
            {"a": (0, (False, "", [])), "b": (1, (True, "", []))},
            ["a", "b"])
        self.assertEqual([], refused.call_args_list)
        self.assertEqual([0, 1], model.attempted)

    def test_the_failure_names_the_network_it_was_imported_into(self):
        _model, refused = self._run(
            {"a": (0, (False, "gone", []))}, ["a"])
        self.assertEqual(self.context.path(),
                         refused.call_args.kwargs.get("net"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
