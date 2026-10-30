"""The harness has to be able to go red. The connector registry lives OUTSIDE the class body, so a reset must CLEAR it, never rebind - a rebind detaches the class from the global and the pre-reset connector walks back in on the next reload, latches and all. ▸archive/test_harness_reset.py
"""

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import database                             # noqa: E402
from amaze.tests import test_support                        # noqa: E402


class ConnectorResetDetachesNothingTest(unittest.TestCase):
    """The reset must clear the shared registry, not replace it."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_harness_reset_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "cops.json")
        self._attach_and_clear()
        self.addCleanup(self._attach_and_clear)

    @staticmethod
    def _attach_and_clear():
        """Puts the registry back the way PRODUCTION holds it - the class attribute IS the module global. Deliberately not the function under test, and reset BEFORE latching, or the latched connector lands in a private dictionary the reload never sees and everything passes with the fix removed."""
        database.DatabaseConnector._instances = database._INSTANCES
        database._INSTANCES.clear()

    def _latched(self):
        """A connector latched the way PRODUCTION latches it - set by hand it would prove nothing about the real one."""
        with open(self.path + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": "OLD1"}]}, handle)
        db = database.DatabaseConnector("cops.json")
        db.load(self.dir + os.sep)
        self.assertTrue(
            db._write_blocked,
            "premise: the load must latch, or this test is not exercising "
            "the case it was written for")
        return db

    def test_a_reset_connector_does_not_come_back_after_a_reload(self):
        """THE ONE THAT GOES RED - a reload happens on every panel open and re-reads the global, so a reset that emptied a detached copy lets the latched connector walk straight back in."""
        latched = self._latched()
        test_support.reset_database_singletons()
        self.assertIs(
            database.DatabaseConnector._instances, database._INSTANCES,
            "the reset handed the class a private dictionary - every "
            "reload-survival mechanism reads database._INSTANCES, so "
            "nothing it drops is actually gone")
        importlib.reload(database)
        self.addCleanup(test_support.reset_database_singletons)
        fresh = database.DatabaseConnector("cops.json")
        self.assertIsNot(
            fresh, latched,
            "the connector the reset dropped was handed back after a "
            "reload - every test that resets and rebuilds has been "
            "measuring the previous test's object")
        self.assertFalse(
            getattr(fresh, "_write_blocked", False),
            "the resurrected connector brought its write-blocked latch "
            "with it, so a save refusal from an earlier test refuses "
            "here too and any test asserting a refusal passes for the "
            "wrong reason")

    def test_a_reset_really_drops_a_healthy_connector_too(self):
        """The accept path - the point of the reset is that the next construction reads the test's OWN fixture path."""
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": "FIRST1"}]}, handle)
        first = database.DatabaseConnector("cops.json")
        self.assertEqual(["FIRST1"],
                         [a["id"] for a in first.load(self.dir + os.sep)["assets"]])
        test_support.reset_database_singletons()

        second_dir = tempfile.mkdtemp(prefix="amaze_harness_reset_b_")
        self.addCleanup(shutil.rmtree, second_dir, ignore_errors=True)
        with open(os.path.join(second_dir, "cops.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": "SECOND1"}]}, handle)
        second = database.DatabaseConnector("cops.json")
        self.assertIsNot(second, first, "the reset returned the cached "
                                       "connector for the same filename")
        self.assertEqual(
            ["SECOND1"],
            [a["id"] for a in second.load(second_dir + os.sep)["assets"]],
            "the new connector answered from the previous fixture's data "
            "- which is how a test once mutated the real library")


class PinEnvSetsOnlyWhatTheProductReadsAsUnset(unittest.TestCase):
    """`pin_env` gives a variable its value where the product's gate would refuse it, then restores it."""

    NAME = "AMAZE_PIN_ENV_PROBE"

    def _through_a_pin(self, start):
        """(before, inside, after) a pin to "/pinned" ends; `start` None leaves the variable unset."""
        import hou
        self.addCleanup(hou.unsetenv, self.NAME)
        if start is None:
            hou.unsetenv(self.NAME)
        else:
            hou.putenv(self.NAME, start)
        before = hou.getenv(self.NAME)
        scope = unittest.TestCase()
        test_support.pin_env(scope, self.NAME, "/pinned")
        inside = hou.getenv(self.NAME)
        scope.doCleanups()
        return before, inside, hou.getenv(self.NAME)

    def test_unset_and_empty_are_pinned_then_put_back(self):
        for start in (None, ""):
            with self.subTest(start=start):
                before, inside, after = self._through_a_pin(start)
                self.assertEqual("/pinned", inside, "the product reads %r as unset" % start)
                self.assertEqual(before, after, "the session's own state did not come back")

    def test_a_value_of_its_own_is_left_alone(self):
        self.assertEqual(("/its/own",) * 3, self._through_a_pin("/its/own"))


class RendererLoadedAsksTheProductsProbe(unittest.TestCase):
    """`renderer_loaded` reads the conversion engine's answer, so `plugins_loaded` reaches it."""

    def test_it_follows_the_answer_plugins_loaded_fakes(self):
        for loaded in ("Redshift", "Octane"):
            with self.subTest(loaded=loaded), test_support.plugins_loaded(loaded):
                self.assertEqual(
                    {"Redshift": loaded == "Redshift", "Octane": loaded == "Octane"},
                    {key: test_support.renderer_loaded(key) for key in ("Redshift", "Octane")})


class SceneCleanupsTakeWhatATestBuilt(unittest.TestCase):

    def test_drop_node_takes_the_node_and_a_second_drop_is_quiet(self):
        import hou
        node = hou.node("/obj").createNode("null", "amaze_drop_probe")
        path = node.path()
        test_support.drop_node(node)
        self.assertIsNone(hou.node(path), "the node is still there")
        test_support.drop_node(node)

    def test_clear_obj_empties_object_level(self):
        import hou
        for name in ("amaze_clear_a", "amaze_clear_b"):
            hou.node("/obj").createNode("null", name)
        test_support.clear_obj()
        self.assertEqual([], [child.name() for child in hou.node("/obj").children()])


if __name__ == "__main__":
    unittest.main(verbosity=2)
