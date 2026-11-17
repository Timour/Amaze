"""Proves a reset drops every held library and the harness helpers do what they say."""

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

from amaze.core import library_db
from amaze.tests import test_support

try:
    import hou
except ImportError:
    hou = None


class ResetDropsEveryHeldLibraryTest(unittest.TestCase):
    """A reset leaves no library held, even after the module reloads."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_harness_reset_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.addCleanup(test_support.reset_database_singletons)

    def _held(self, rows):
        """The Nodes database of this library holding `rows`, opened as a panel opens it."""
        import types
        with open(os.path.join(self.dir, "nodes.json"), "w", encoding="utf-8") as handle:
            json.dump({"assets": {one: {"id": one} for one in rows}}, handle)
        holder = types.SimpleNamespace(dir=self.dir, library_user="")
        return sorted(library_db.document(holder, "nodes.json").table("assets"))

    def test_a_reset_does_not_come_back_after_a_reload(self):
        self.assertEqual(["FIRST1"], self._held(["FIRST1"]))
        test_support.reset_database_singletons()
        importlib.reload(library_db)
        self.assertEqual([], library_db.held_libraries(),
                         "a library the reset dropped came back after a reload")

    def test_the_next_read_is_the_file_as_it_is_now(self):
        self.assertEqual(["FIRST1"], self._held(["FIRST1"]))
        test_support.reset_database_singletons()
        self.assertEqual(["SECOND1"], self._held(["SECOND1"]),
                         "the held copy returned the previous fixture's data")


@unittest.skipUnless(hou, "Houdini is not loaded")
class PinEnvSetsOnlyWhatTheProductReadsAsUnset(unittest.TestCase):
    """`pin_env` sets a variable the product would read as unset, then restores it."""

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
                self.assertEqual(before, after, "the session's own state was not restored")

    def test_a_value_of_its_own_is_left_alone(self):
        self.assertEqual(("/its/own",) * 3, self._through_a_pin("/its/own"))


@unittest.skipUnless(hou, "Houdini is not loaded")
class RendererLoadedAsksTheProductsProbe(unittest.TestCase):
    """`renderer_loaded` calls the conversion engine's check, so `plugins_loaded` can fake it."""

    def test_it_follows_the_answer_plugins_loaded_fakes(self):
        for loaded in ("Redshift", "Octane"):
            with self.subTest(loaded=loaded), test_support.plugins_loaded(loaded):
                self.assertEqual(
                    {"Redshift": loaded == "Redshift", "Octane": loaded == "Octane"},
                    {key: test_support.renderer_loaded(key) for key in ("Redshift", "Octane")})


@unittest.skipUnless(hou, "Houdini is not loaded")
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
