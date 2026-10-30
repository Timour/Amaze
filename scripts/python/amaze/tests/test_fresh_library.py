"""Every door that creates a library must make a WHOLE one. ▸p/library-creation-doors"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import amaze
from amaze import branding
from amaze.core import database
from amaze.core import material
from amaze.helpers import hostos
from amaze.prefs import prefs as prefs_mod
from amaze.tests import test_support


class TheTestLibraryDoorMakesAWholeLibrary(unittest.TestCase):
    """`seed_test_folder` is a creation door in its own right, and it built half a library."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="amaze_fresh_seed_")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.lib = os.path.join(self.folder, prefs_mod.TEST_LIB_SUBDIR)

    def _index(self):
        with open(os.path.join(self.lib, "library.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_it_creates_the_asset_folder(self):
        """Without `mat/` the first save raises FileNotFoundError out of mkstemp, uncaught."""
        prefs_mod.seed_test_folder(self.folder)
        for tail in ("mat", "img"):
            self.assertTrue(
                os.path.isdir(os.path.join(self.lib, tail)),
                "%s/ was not created, so the library is half made" % tail)

    def test_its_index_is_born_at_the_current_schema(self):
        """A versionless index reads as legacy 1, and _MIGRATIONS has no step below 4 to climb."""
        prefs_mod.seed_test_folder(self.folder)
        index = self._index()
        self.assertEqual(database.SCHEMA_VERSION, index.get("version"))
        self.assertEqual(branding.LIBRARY_FORMAT, index.get("format"))

    def test_it_still_adds_only_what_is_missing(self):
        """Existing files are never touched - the door's own promise, and a second run must keep it."""
        prefs_mod.seed_test_folder(self.folder)
        with open(os.path.join(self.lib, "library.json"), "rb") as handle:
            before = handle.read()
        ok, _what = prefs_mod.seed_test_folder(self.folder)
        with open(os.path.join(self.lib, "library.json"), "rb") as handle:
            self.assertTrue(ok)
            self.assertEqual(before, handle.read(), "the index was rewritten")


class TheStarterCarriesNoPhantomAsset(unittest.TestCase):
    """The shipped starter held one blank record inherited from the fork, and every library made from it opened with a phantom asset that nothing removed and every save re-emitted."""

    def test_the_shipped_starter_seeds_no_assets(self):
        """The starter `prepare()` seeds holds no asset; a guard under its own name."""
        with open(amaze.package_file("res", "def", "library.json"),
                  encoding="utf-8") as handle:
            starter = json.load(handle)
        self.assertEqual([], starter.get("assets"),
                         "the starter still ships a placeholder asset")
        self.assertNotIn("version", starter,
                         "the starter now carries a literal version - a "
                         "second source of truth that goes stale at the "
                         "next bump")


class TheShippedStarterDoorBirthsAStampedIndex(unittest.TestCase):
    """`prepare()`'s door: the starter has no `version`, so it is stamped on the way in."""

    def setUp(self):
        self.lib = tempfile.mkdtemp(prefix="amaze_fresh_starter_")
        self.addCleanup(shutil.rmtree, self.lib, ignore_errors=True)

    def _born(self):
        prefs_mod.seed_starter_index(self.lib)
        with open(os.path.join(self.lib, "library.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def test_it_keeps_everything_the_starter_ships(self):
        """The stamp is added to the shipped defaults, never written instead of them."""
        with open(amaze.package_file("res", "def", "library.json"),
                  encoding="utf-8") as handle:
            starter = json.load(handle)
        born = self._born()
        for key in starter:
            self.assertEqual(starter[key], born.get(key),
                             "the starter's '%s' did not survive the seed" % key)
        self.assertEqual(database.SCHEMA_VERSION, born.get("version"))
        self.assertEqual(branding.LIBRARY_FORMAT, born.get("format"))

    def test_it_adds_only_what_is_missing(self):
        """An index already in place is never rewritten - the seeding door's standing promise."""
        self._born()
        index = os.path.join(self.lib, "library.json")
        with open(index, "rb") as handle:
            before = handle.read()
        prefs_mod.seed_starter_index(self.lib)
        with open(index, "rb") as handle:
            self.assertEqual(before, handle.read(), "the index was rewritten")

    def test_panel_load_seeds_through_this_door(self):
        """Pinned from SOURCE: every opening seeds through prepare(); a bare shutil.copy goes red."""
        import inspect
        from amaze.actions import library as library_actions
        source = inspect.getsource(library_actions.prepare)
        self.assertIn("seed_starter_index", source,
                      "prepare() no longer seeds through the stamping "
                      "door, so a fresh library is born unstamped again")
        self.assertNotIn("shutil.copy", source,
                         "prepare() copies the starter verbatim again - "
                         "that copy is bug B")


class TheAssetWriterMakesItsFolderInsideTheLibraryOnly(unittest.TestCase):
    """The scoped defensive writer: a missing library folder is made, a destination outside the library is refused rather than manufactured."""

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
        handler.save_asset_pair(
            os.path.join(folder, "7.interface"), os.path.join(folder, "7.mat"),
            "interface", self._write_mat)

    def test_a_first_save_into_a_library_with_no_asset_folder_succeeds(self):
        """The reported crash: three logged exceptions, all mkstemp on an absent mat/."""
        self._save(os.path.join(self.root, "mat"))
        self.assertTrue(os.path.isfile(os.path.join(self.root, "mat", "7.mat")))

    def test_a_refused_destination_is_not_created(self):
        """Refusing after making the folder would be the same bug with a better error message."""
        with self.assertRaises(hostos.PathEscape):
            self._save(os.path.join(self.outside, "elsewhere"))
        self.assertFalse(os.path.exists(os.path.join(self.outside, "elsewhere")))

    def test_a_handler_with_no_library_creates_nothing(self):
        """The `__new__` fixture shape has no root to contain against, so it must make no folder rather than guess one."""
        handler = self.nodes.NodeHandler.__new__(self.nodes.NodeHandler)
        target = os.path.join(self.root, "unmade")
        with self.assertRaises(FileNotFoundError):
            handler.save_asset_pair(
                os.path.join(target, "7.interface"),
                os.path.join(target, "7.mat"), "interface", self._write_mat)
        self.assertFalse(os.path.exists(target))


class TheBuilderFieldDiesAtSchemaSeven(unittest.TestCase):
    """The 6 -> 7 step strips the record's `builder` - written by every save since the fork, read by nothing since 2026-08-14, so it comes off the format; the record class must retire the key too, or `_extra` carries it back on the next save."""

    FILENAME = "library.json"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_v7_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, self.FILENAME)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _write(self, data):
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=4)

    def _load(self):
        db = database.DatabaseConnector(self.FILENAME)
        return db, db.load(self.dir + os.sep)

    def _v6_document(self):
        return {
            "version": 6, "categories": ["_All"], "tags": [],
            "assets": [
                {"id": "B0", "name": "one", "builder": 1,
                 "renderer": "Karma", "usd": 1},
                {"id": "B1", "name": "two", "builder": 0},
            ],
        }

    def test_a_v6_document_climbs_to_seven_and_loses_builder(self):
        """The literal 7 is the subject here, not a stray constant."""
        self._write(self._v6_document())
        _db, data = self._load()
        self.assertEqual(database.SCHEMA_VERSION, data["version"],
                         "premise: the chain reaches the current schema")
        self.assertGreaterEqual(
            data["version"], 7,
            "SCHEMA_VERSION is still below 7 - the bump has not landed")
        for row in data["assets"]:
            self.assertNotIn("builder", row,
                             "the dead field survived the step")
        row = data["assets"][0]    # the rest is user data, which a migration never assumes away
        self.assertEqual("one", row.get("name"))
        self.assertEqual("Karma", row.get("renderer"))
        self.assertEqual(1, row.get("usd"))

    def test_a_v4_document_climbs_the_whole_chain(self):
        """`code.json` in the real library is a schema-4 document, so the chain must still carry one all the way up."""
        self._write({
            "version": 4, "categories": ["_All"], "tags": [],
            "assets": [{"id": "A0", "name": "old", "favorite": True,
                        "icon": {"name": "box"}, "builder": 1}],
        })
        _db, data = self._load()
        self.assertEqual(database.SCHEMA_VERSION, data["version"])
        row = data["assets"][0]
        for gone in ("favorite", "icon", "builder"):
            self.assertNotIn(gone, row,
                             "a retired field outlived its step")
        self.assertEqual("old", row.get("name"))

    def test_the_record_class_retires_builder_everywhere(self):
        """`from_dict` -> `get_as_dict` must DROP the key - unknown instead of retired, it rides `_extra` verbatim and the next save undoes the migration."""
        mat = material.Material.from_dict(
            {"id": "B7", "name": "n", "builder": 1})
        self.assertNotIn(
            "builder", mat.get_as_dict(),
            "the record still emits `builder` - the next save undoes the step")


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
        data["directory"] = self.empty    # what each door re-reads before it opens the folder
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def _assert_ready(self):
        for name in ("library.json", "img", "mat"):
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
