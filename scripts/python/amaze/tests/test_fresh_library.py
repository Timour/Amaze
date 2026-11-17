"""Every function that creates a library must make a complete one. ▸p/library-creation"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from amaze import branding
from amaze.core import library_policy
from amaze.core import material
from amaze.helpers import hostos
from amaze.prefs import prefs as prefs_mod
from amaze.tests import test_support


class EveryNewLibraryIsBornThroughCreateLibrary(unittest.TestCase):
    """`create_library` writes the library's own database and nothing else."""

    def setUp(self):
        self.lib = tempfile.mkdtemp(prefix="amaze_fresh_starter_")
        self.addCleanup(shutil.rmtree, self.lib, ignore_errors=True)

    def test_it_is_born_at_this_amazes_version(self):
        """A library with no version recorded is treated as one to convert."""
        prefs_mod.create_library(self.lib)
        with open(os.path.join(self.lib, "DataBase.json"), encoding="utf-8") as handle:
            master = json.load(handle)
        self.assertEqual(library_policy.LIBRARY_VERSION,
                         master["policy"]["library"]["version"])
        self.assertEqual(branding.LIBRARY_FORMAT, master.get("format"))

    def test_it_writes_only_the_librarys_database(self):
        self.assertTrue(prefs_mod.create_library(self.lib))
        self.assertEqual(["DataBase.json"],
                         [name for name in os.listdir(self.lib) if name.endswith(".json")])

    def test_it_adds_only_what_is_missing(self):
        prefs_mod.create_library(self.lib)
        path = os.path.join(self.lib, "DataBase.json")
        with open(path, "rb") as handle:
            before = handle.read()
        self.assertTrue(prefs_mod.create_library(self.lib))
        with open(path, "rb") as handle:
            self.assertEqual(before, handle.read(), "the library's database was rewritten")

    def test_panel_load_creates_through_create_library(self):
        """Read from SOURCE: every opening creates through prepare(); a plain copy fails it."""
        import inspect
        from amaze.actions import library as library_actions
        source = inspect.getsource(library_actions.prepare)
        self.assertIn("create_library", source)
        self.assertNotIn("shutil.copy", source)


class TheAssetWriterMakesItsFolderInsideTheLibraryOnly(unittest.TestCase):
    """The scoped writer makes a missing library folder and raises for a destination outside it."""

    def setUp(self):
        from amaze.render import nodes
        self.nodes = nodes
        self.root = tempfile.mkdtemp(prefix="amaze_fresh_write_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.outside = tempfile.mkdtemp(prefix="amaze_fresh_outside_")
        self.addCleanup(shutil.rmtree, self.outside, ignore_errors=True)
        self.prefs = prefs_mod.Prefs()
        self.prefs.path = tempfile.mkdtemp(prefix="amaze_fresh_settings_")
        self.addCleanup(shutil.rmtree, self.prefs.path, ignore_errors=True)
        self.prefs.dir = self.root + os.sep     # the connectors concatenate ▸r/atomic-writes

    @staticmethod
    def _write_mat(path):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("material")

    def _save(self, folder):
        handler = self.nodes.NodeHandler(self.prefs)
        handler.save_asset_pair(os.path.join(folder, "7.mat"), self._write_mat)

    def test_a_first_save_into_a_library_with_no_asset_folder_succeeds(self):
        """The reported crash: three logged exceptions, all mkstemp on an absent asset folder."""
        self._save(os.path.join(self.root, "materials"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "materials", "7.mat")))

    def test_a_first_save_makes_the_builder_record_beside_it(self):
        """The `<id>.json` is written to the section folder the same first save just made."""
        import hou
        from amaze.core import asset_record
        staging = hou.node("/obj").createNode("subnet", "fresh_builder")
        self.addCleanup(staging.destroy)
        handler = self.nodes.NodeHandler(self.prefs)
        handler.save_asset_pair(os.path.join(self.root, "materials", "7.mat"),
                                self._write_mat, staging, "7")
        record = asset_record.read(os.path.join(self.root, "materials", "7.json"))
        self.assertEqual("subnet", record["builder"].get("type"),
                         "the first save left no builder beside its .mat")

    def test_a_refused_destination_is_not_created(self):
        """Raising after making the folder would be the same bug with a better error message."""
        with self.assertRaises(hostos.PathOutsideBase):
            self._save(os.path.join(self.outside, "elsewhere"))
        self.assertFalse(os.path.exists(os.path.join(self.outside, "elsewhere")))

    def test_a_handler_with_no_library_creates_nothing(self):
        """The `__new__` fixture has no library root to check against, so it must make no folder."""
        handler = self.nodes.NodeHandler.__new__(self.nodes.NodeHandler)
        target = os.path.join(self.root, "unmade")
        with self.assertRaises(FileNotFoundError):
            handler.save_asset_pair(os.path.join(target, "7.mat"), self._write_mat)
        self.assertFalse(os.path.exists(target))


class TheBuilderFieldIsRetired(unittest.TestCase):
    """The record class drops `builder`, or `_extra` writes it back into the database."""

    def test_the_record_class_retires_builder_everywhere(self):
        """`from_dict` -> `get_as_dict` must drop the key, or `_extra` writes it on the next save."""
        mat = material.Material.from_dict(
            {"id": "B7", "name": "n", "builder": 1})
        self.assertNotIn(
            "builder", mat.get_as_dict(),
            "the record still emits `builder` - the next save writes it back")


class EveryWayIntoAnEmptyFolderReadiesIt(unittest.TestCase):
    """Opening the pane, Reload Library and Preferences' Apply each give an empty folder a library."""

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.panel = test_support.fixture_panel(self)
        self.empty = test_support.posix_path(test_support.scratch_dir("amaze_empty_lib_")) + "/"
        self.addCleanup(shutil.rmtree, self.empty, True)
        settings = os.path.join(self.panel.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data["directory"] = self.empty    # what each of the three ways re-reads before it opens the folder
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def _assert_ready(self):
        for name in ("DataBase.json", "materials", "nodes"):
            self.assertTrue(os.path.exists(os.path.join(self.empty, name)),
                            "the empty folder was opened without its %s" % name)

    def test_a_pane_opened_on_it(self):
        test_support.reopened_panel(self)
        self._assert_ready()

    def test_reload_library(self):
        self.panel.open()
        self._assert_ready()

    def test_preferences_apply(self):
        self.assertTrue(test_support.apply_library(self, self.panel, self.empty, user="Tester"))
        self._assert_ready()


if __name__ == "__main__":
    unittest.main()
