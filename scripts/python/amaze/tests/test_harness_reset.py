"""The test harness has to be able to go red.

`reset_database_singletons()` is the first line of almost every
integration test in this suite, and it was REBINDING the connector
registry (`DatabaseConnector._instances = {}`) instead of clearing it.

That matters because the registry deliberately lives OUTSIDE the class
body, as `database._INSTANCES`: panel.py reloads the module on every
panel open, reload re-executes the `class` statement, and the class
attribute pointing back at the surviving global is the only thing that
keeps a live connector - its path, its stale-write baseline, its latches
- from being replaced by an empty one. A rebind detaches the class from
that global, so the reset drops nothing the reloaded module can see.

Measured: latch `_write_blocked`, reset through the rebind, reload the
module, ask for the same filename - and the PRE-RESET connector comes
back with its latch still set. Every sabotage-verified refusal test in
every other module was reporting on a resurrected object instead of the
one its own fix had built.

THE OBVIOUS TEST PASSES WITH THE FIX REMOVED. "A connector survives a
reload" is true either way - the rebind leaves the global holding it,
which is the whole bug. The test that actually goes red is the one
asserting the returned connector is NOT the latched one and that
`_write_blocked` is False. Both are below, and the second is the reason
this file exists.
"""

import importlib
import json
import os
import shutil
import sys
import tempfile
import unittest

# THREE dirnames up = scripts/python, the directory holding the `amaze`
# package - the DEV tree, not the install on Houdini's path.
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
        """Put the registry back the way PRODUCTION holds it: the class
        attribute IS the module global, and the global is empty.

        Deliberately not `reset_database_singletons()` - that is the
        function under test, and calling it here is how the reload test
        below quietly stopped reproducing anything. Reset first, then
        latch: a rebinding reset detaches the class, so the connector the
        test latches lands in a private dictionary the reload can never
        see, and the test passes with the fix removed. Assigning the SAME
        object restores the invariant rather than breaking it.
        """
        database.DatabaseConnector._instances = database._INSTANCES
        database._INSTANCES.clear()

    def _latched(self):
        """A connector with `_write_blocked` set the way production sets
        it: cops.json absent, a .bak-1 beside it saying it was here. Set
        by hand it would prove nothing about the real latch."""
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

    def test_the_registry_is_still_the_module_global_after_a_reset(self):
        """The check that catches the rebind on the spot. Its symptom is
        otherwise silent - the tests keep passing, they just stop testing
        what they say they do."""
        self._latched()
        test_support.reset_database_singletons()
        self.assertIs(
            database.DatabaseConnector._instances, database._INSTANCES,
            "the reset handed the class a private dictionary - every "
            "reload-survival mechanism reads database._INSTANCES, so "
            "nothing it drops is actually gone")

    def test_a_reset_connector_does_not_come_back_after_a_reload(self):
        """THE ONE THAT GOES RED. A reload is not exotic here: panel.py
        does it on every panel open, and it re-executes the `class`
        statement, which re-reads `_INSTANCES`. If the reset only emptied
        a detached copy, the latched connector is still in the global and
        walks straight back in."""
        latched = self._latched()
        test_support.reset_database_singletons()
        importlib.reload(database)
        # The registry the RELOADED class points at, cleaned up whichever
        # way this assertion goes.
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
        """The accept path. A reset that cleared nothing would be caught
        above; a reset that somehow cleared too little for an ordinary,
        unlatched connector would not - and the point of the reset is
        that the next construction reads the test's OWN fixture path."""
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
