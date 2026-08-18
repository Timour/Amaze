"""Every door that creates a library must make a WHOLE one. ▸p/library-creation-doors"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import amaze                                            # noqa: E402
from amaze import branding                              # noqa: E402
from amaze.core import database                         # noqa: E402
from amaze.helpers import hostos                        # noqa: E402
from amaze.prefs import prefs as prefs_mod              # noqa: E402


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
        self.assertTrue(
            os.path.isdir(os.path.join(self.lib, "mat")),
            "mat/ was not created, so every save into this library fails")

    def test_it_creates_the_image_folder(self):
        """`img/` is the pair `ensure_library_dirs` makes, and it was made as a pair for a reason."""
        prefs_mod.seed_test_folder(self.folder)
        self.assertTrue(os.path.isdir(os.path.join(self.lib, "img")),
                        "img/ was not created")

    def test_its_index_is_born_at_the_current_schema(self):
        """A versionless index reads as legacy 1, and _MIGRATIONS has no step below 4 to climb."""
        prefs_mod.seed_test_folder(self.folder)
        self.assertEqual(database.SCHEMA_VERSION, self._index().get("version"))

    def test_its_index_carries_the_current_format(self):
        """The format stamp is the connector's other contract, and save() writes both together."""
        prefs_mod.seed_test_folder(self.folder)
        self.assertEqual(branding.LIBRARY_FORMAT, self._index().get("format"))

    def test_it_writes_its_index_through_the_shared_writer(self):
        """One writer owns both stamps, so no door can half-apply them or forget one."""
        import inspect
        self.assertIn("write_fresh_index",
                      inspect.getsource(prefs_mod.seed_test_folder),
                      "this door stamps its index by hand again")

    def test_the_chain_is_complete_so_a_save_cannot_re_assert_one(self):
        """The compounding half: while the chain is incomplete save() holds the stamp back forever."""
        prefs_mod.seed_test_folder(self.folder)
        document = self._index()
        version = int(document.get("version", 1))
        self.assertFalse(
            version < database.SCHEMA_VERSION
            and database._MIGRATIONS.get(version) is None,
            "the index is born in a gap in the migration chain, so save() "
            "will re-assert that version on every write")

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
        """`panel.load()` claims a test pins this and names one that exists nowhere in the tree; this is the guard, under its own name."""
        with open(amaze.package_file("res", "def", "library.json"),
                  encoding="utf-8") as handle:
            starter = json.load(handle)
        self.assertEqual([], starter.get("assets"),
                         "the starter still ships a placeholder asset")


class TheShippedStarterDoorBirthsAStampedIndex(unittest.TestCase):
    """`panel.load()`'s door: the shipped starter carries no `version` key, so it is stamped on the way in rather than copied verbatim. ▸p/library-creation-doors"""

    def setUp(self):
        self.lib = tempfile.mkdtemp(prefix="amaze_fresh_starter_")
        self.addCleanup(shutil.rmtree, self.lib, ignore_errors=True)

    def _born(self):
        prefs_mod.seed_starter_index(self.lib)
        with open(os.path.join(self.lib, "library.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def test_it_is_born_at_the_current_schema(self):
        """A versionless index reads as legacy 1, and _MIGRATIONS has no step below 4 to climb."""
        self.assertEqual(database.SCHEMA_VERSION, self._born().get("version"))

    def test_it_carries_the_current_format(self):
        """The format stamp is the connector's other contract, and save() writes both together."""
        self.assertEqual(branding.LIBRARY_FORMAT, self._born().get("format"))

    def test_the_starter_index_is_not_born_in_a_migration_gap(self):
        """While the chain is incomplete save() holds the stamp back on every write."""
        version = int(self._born().get("version", 1))
        self.assertFalse(
            version < database.SCHEMA_VERSION
            and database._MIGRATIONS.get(version) is None,
            "the index is born in a gap in the migration chain, so save() "
            "will re-assert that version on every write")

    def test_it_keeps_everything_the_starter_ships(self):
        """The stamp is added to the shipped defaults, never written instead of them."""
        with open(amaze.package_file("res", "def", "library.json"),
                  encoding="utf-8") as handle:
            starter = json.load(handle)
        born = self._born()
        for key in starter:
            self.assertEqual(starter[key], born.get(key),
                             "the starter's '%s' did not survive the seed" % key)

    def test_it_adds_only_what_is_missing(self):
        """An index already in place is never rewritten - the seeding door's standing promise."""
        self._born()
        index = os.path.join(self.lib, "library.json")
        with open(index, "rb") as handle:
            before = handle.read()
        prefs_mod.seed_starter_index(self.lib)
        with open(index, "rb") as handle:
            self.assertEqual(before, handle.read(), "the index was rewritten")

    def test_the_stamp_is_derived_and_never_a_literal(self):
        """Source-derived: a hardcoded 6 is a second source of truth that goes stale on the next bump."""
        import inspect
        source = inspect.getsource(prefs_mod.write_fresh_index)
        self.assertIn("SCHEMA_VERSION", source,
                      "the version stamp is not derived from SCHEMA_VERSION")
        self.assertIn("LIBRARY_FORMAT", source,
                      "the format stamp is not derived from LIBRARY_FORMAT")

    def test_the_shipped_starter_still_carries_no_version_of_its_own(self):
        """The shipped file stays versionless on purpose - the stamp belongs to the door."""
        with open(amaze.package_file("res", "def", "library.json"),
                  encoding="utf-8") as handle:
            self.assertNotIn("version", json.load(handle),
                             "the starter now carries a literal version - a "
                             "second source of truth that goes stale at the "
                             "next bump")

    def test_panel_load_seeds_through_this_door(self):
        """Pinned from SOURCE because load() needs a panel; a bare shutil.copy of the starter must go red."""
        import inspect
        from amaze.panel.panel import MatLibPanel
        source = inspect.getsource(MatLibPanel.load)
        self.assertIn("seed_starter_index", source,
                      "panel.load() no longer seeds through the stamping "
                      "door, so a fresh library is born unstamped again")
        self.assertNotIn("shutil.copy", source,
                         "panel.load() copies the starter verbatim again - "
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

    def test_a_destination_outside_the_library_is_refused(self):
        """A bare makedirs would manufacture a wrong tree silently; a typo must still fail loudly."""
        with self.assertRaises(hostos.PathEscape):
            self._save(os.path.join(self.outside, "elsewhere"))

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


if __name__ == "__main__":
    unittest.main()
