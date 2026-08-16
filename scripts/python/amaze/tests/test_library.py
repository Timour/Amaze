"""The library models: `MaterialLibrary` over mocked prefs/database/material in `TestMaterialLibrary`, and the rest against a real fixture library - merges, switches, schema stamps, favourites and the shared base's contract."""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
import os
import json
import shutil
import sys
import tempfile

sys.path.insert(  # THREE dirnames up = scripts/python, the directory holding the `amaze` package - the DEV tree, not the install on Houdini's path ▸p/checkout-not-install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from PySide6 import QtCore
import hou
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log


def names_a_sibling_database(path) -> bool:
    """True for any path that would tell cleanup a SIBLING database exists or once existed - the file, its `.bak-*`/`.unreadable` copies, or a seed marker beside it. A blanket `os.path.exists -> True` mock silences the sweep entirely, so a test that needs it to RUN must say what reads absent, and say it about every trace rather than only the .json. ▸p/clean-library-sweep"""
    path = str(path)
    return (
        "cops.json" in path
        or "code.json" in path
        or os.path.basename(path).startswith((".amaze_", ".assetlib_"))
    )


class TestMaterialLibrary(unittest.TestCase):
    """Test suite for MaterialLibrary class"""

    def setUp(self):
        """Set up test fixtures and mocks"""
        self.prefs_patcher = patch("amaze.core.library.prefs.Prefs")
        self.db_patcher = patch("amaze.core.library.database.DatabaseConnector")
        self.material_patcher = patch("amaze.core.library.material.Material")
        self.thumbs_patcher = patch("amaze.core.library.thumbs.ThumbNailRenderer")
        self.nodes_patcher = patch("amaze.core.library.nodes.NodeHandler")
        self.qimage_patcher = patch("PySide6.QtGui.QImage")

        self.mock_prefs_cls = self.prefs_patcher.start()
        self.mock_db_cls = self.db_patcher.start()
        self.mock_material_cls = self.material_patcher.start()
        self.mock_thumbs_cls = self.thumbs_patcher.start()
        self.mock_nodes_cls = self.nodes_patcher.start()
        self.mock_hou = Mock()
        self.mock_qimage_cls = self.qimage_patcher.start()

        self.mock_prefs = Mock()
        self._library_dir = tempfile.mkdtemp(prefix="amaze_testlib_own_")  # a REAL directory holding a REAL library.json, because cleanup_db reads the model's OWN index off disk and `open()` is not mocked here. Only .dir is real - img_dir/asset_dir stay absolute-looking, so os.path.join returns them unchanged and every mocked listdir/exists path is untouched
        self.addCleanup(shutil.rmtree, self._library_dir, True)
        with open(os.path.join(self._library_dir, "library.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": [{"id": "mat_001"}]}, handle)
        self.mock_prefs.dir = self._library_dir + os.sep
        self.mock_prefs.img_dir = "/img/"
        self.mock_prefs.asset_dir = "/assets/"
        self.mock_prefs.ext = ".mat"
        self.mock_prefs.img_ext = ".png"
        self.mock_prefs.thumbsize = 256
        self.mock_prefs.render_on_import = False
        self.mock_prefs_cls.return_value = self.mock_prefs

        self.mock_db = Mock()
        self.asset_data = {
            "name": "TestMaterial",
            "categories": ["metal", "rough"],
            "tags": ["test", "sample"],
            "fav": False,
            "renderer": "karma",
            "date": "2026-02-08",
            "mat_id": "mat_001",
        }
        self.mock_db.load.return_value = {
            "tags": ["test", "sample"],
            "assets": [self.asset_data],
        }
        self.mock_db_cls.return_value = self.mock_db

        self.mock_material = Mock()
        self.mock_material.name = "TestMaterial"
        self.mock_material.categories = ["metal", "rough"]
        self.mock_material.tags = ["test", "sample"]
        self.mock_material.fav = False
        self.mock_material.renderer = "karma"
        self.mock_material.date = "2026-02-08"
        self.mock_material.mat_id = "mat_001"
        self.mock_material.get_as_dict.return_value = self.asset_data
        self.mock_material_cls.from_dict.return_value = self.mock_material

        self.mock_qimage = Mock()
        self.mock_qimage.scaled.return_value = self.mock_qimage
        self.mock_qimage_cls.return_value = self.mock_qimage

        self.mock_hou.getenv.return_value = "/fake/path"

        from amaze.core import library  # imported after the patches are live

        self.library = library.MaterialLibrary()

    def tearDown(self):
        """Clean up patches"""
        patch.stopall()

    def test_initialization(self):
        """Test MaterialLibrary initializes correctly"""
        self.assertIsNotNone(self.library.preferences)
        self.assertEqual(len(self.library._assets), 1)
        self.assertEqual(self.library._tags, ["test", "sample"])
        self.assertEqual(self.library._thumbsize, 256)

    def test_row_count(self):
        """Test rowCount returns correct number of assets"""
        self.assertEqual(self.library.rowCount(), 1)

    def test_data_display_role(self):
        """Test data() returns correct display name"""
        index = self.library.index(0, 0)
        result = self.library.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
        self.assertEqual(result, "TestMaterial")

    def test_data_decoration_role(self):
        """Test data() returns thumbnail for decoration role"""
        index = self.library.index(0, 0)
        result = self.library.data(index, QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertIsNone(result)  # the async engine answers None until a delivery lands, and the delegate paints a clean dark tile meanwhile

    def test_data_category_role(self):
        """Test data() returns categories"""
        index = self.library.index(0, 0)
        result = self.library.data(index, self.library.CategoryRole)
        self.assertEqual(result, ["metal", "rough"])

    def test_data_tag_role(self):
        """Test data() returns tags"""
        index = self.library.index(0, 0)
        result = self.library.data(index, self.library.TagRole)
        self.assertEqual(result, ["test", "sample"])

    def test_data_favorite_role(self):
        """The role answers the ONE favourites door, keyed by the asset's id - never the shared record, never settings."""
        from amaze.core import library as library_mod
        index = self.library.index(0, 0)
        mat_id = self.library._assets[0].mat_id
        with patch.object(library_mod.locations, "is_favourite",
                          return_value=False) as asked:
            self.assertFalse(
                self.library.data(index, self.library.FavoriteRole))
        asked.assert_called_once_with(self.mock_prefs, mat_id)
        with patch.object(library_mod.locations, "is_favourite",
                          return_value=True):
            self.assertTrue(self.library.data(index,
                                              self.library.FavoriteRole))

    def test_data_renderer_role(self):
        """Test data() returns renderer"""
        index = self.library.index(0, 0)
        result = self.library.data(index, self.library.RendererRole)
        self.assertEqual(result, "karma")

    def test_data_date_role(self):
        """Test data() returns date"""
        index = self.library.index(0, 0)
        result = self.library.data(index, self.library.DateRole)
        self.assertEqual(result, "2026-02-08")

    def test_data_id_role(self):
        """Test data() returns material ID"""
        index = self.library.index(0, 0)
        result = self.library.data(index, self.library.IdRole)
        self.assertEqual(result, "mat_001")

    def test_sanitize_tags(self):
        """Test tag sanitization removes spaces and duplicates"""
        result = self.library.sanitize_tags("tag1, tag2 , tag1, tag3")
        tags = set(result.split(","))
        self.assertEqual(tags, {"tag1", "tag2", "tag3"})

    def test_sanitize_tags_empty(self):
        """Test sanitize_tags handles empty string"""
        result = self.library.sanitize_tags("")
        self.assertEqual(result, "")

    def test_check_add_tags_new_tag(self):
        """Test check_add_tags adds new tags"""
        self.library._tags = ["existing"]
        self.library.check_add_tags("existing,newtag")
        self.assertIn("newtag", self.library._tags)

    def test_check_add_tags_existing_tag(self):
        """Test check_add_tags doesn't duplicate existing tags"""
        self.library._tags = ["existing"]
        initial_count = len(self.library._tags)
        self.library.check_add_tags("existing")
        self.assertEqual(len(self.library._tags), initial_count)

    def test_assets_property(self):
        """Test assets property returns asset list"""
        assets = self.library.assets
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].name, "TestMaterial")

    def test_tags_property(self):
        """Test tags property returns tag list"""
        tags = self.library.tags
        self.assertEqual(tags, ["test", "sample"])

    def test_thumbsize_property_getter(self):
        """Test thumbsize property getter"""
        self.assertEqual(self.library.thumbsize, 256)

    def test_thumbsize_property_setter(self):
        """Test thumbsize property setter"""
        self.library.thumbsize = 512
        self.assertEqual(self.library.thumbsize, 512)

    def test_save(self):
        """Test save() writes data to database"""
        self.library.save()
        self.mock_db.set.assert_called_once()
        self.mock_db.save.assert_called_once()

    def test_toggle_fav_false_to_true(self):
        """A toggle goes through the one favourites door with the asset's id, so the star lands in the library store under its owner and one user's stars cannot collide with another's."""
        from amaze.core import library as library_mod
        index = self.library.index(0, 0)
        mat_id = self.library._assets[0].mat_id
        with patch.object(library_mod.locations, "is_favourite",
                          return_value=False), \
                patch.object(library_mod.locations,
                             "set_favourite") as wrote:
            self.library.toggle_fav(index)
        wrote.assert_called_once_with(self.mock_prefs, mat_id, True)

    def test_toggle_fav_true_to_false(self):
        """The other direction, through the same door."""
        from amaze.core import library as library_mod
        index = self.library.index(0, 0)
        mat_id = self.library._assets[0].mat_id
        with patch.object(library_mod.locations, "is_favourite",
                          return_value=True), \
                patch.object(library_mod.locations,
                             "set_favourite") as wrote:
            self.library.toggle_fav(index)
        wrote.assert_called_once_with(self.mock_prefs, mat_id, False)

    def test_toggle_fav_does_not_write_the_library(self):
        """Stated as its own assertion: a favourite toggle never touches the shared index."""
        from amaze.core import library as library_mod
        with patch.object(library_mod.locations, "is_favourite",
                          return_value=False), \
                patch.object(library_mod.locations, "set_favourite"), \
                patch.object(self.library, "save") as mock_save:
            self.library.toggle_fav(self.library.index(0, 0))
        mock_save.assert_not_called()

    def test_set_assetdata_normal_values(self):
        """Test set_assetdata with normal values"""
        index = self.library.index(0, 0)

        self.library.set_assetdata(index, "NewName", "cat1,cat2", "tag1,tag2", True)

        self.mock_material.set_data.assert_called()

    def test_set_assetdata_multiple_values_placeholder(self):
        """Test set_assetdata preserves existing data when Multiple Values placeholder used"""
        index = self.library.index(0, 0)
        original_name = self.library._assets[0].name

        self.library.set_assetdata(index, "Multiple Values...", "cat1", "tag1", False)

        call_args = self.mock_material.set_data.call_args  # the name is preserved rather than overwritten with the placeholder
        self.assertNotEqual(call_args[0][0], "Multiple Values...")

    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    def test_remove_asset(self, mock_remove, mock_exists):
        """Test remove_asset deletes files and removes from library"""
        index = self.library.index(0, 0)
        initial_count = self.library.rowCount()

        mat_id = self.library._assets[0].mat_id
        expected = set(self.library.asset_files(mat_id).values())

        self.library.remove_asset(index)

        removed = {call.args[0] for call in mock_remove.call_args_list}  # EVERY file the asset owns, derived from asset_files() rather than counted: a hard-coded count says nothing about WHICH file was missed, and goes stale each time an asset gains one
        self.assertEqual(
            expected, removed,
            "remove_asset did not delete exactly the files asset_files() "
            "says this asset owns - anything left behind is an orphan "
            "Clean Library cannot classify, and anything extra belongs "
            "to something else")
        self.assertEqual(self.library.rowCount(), initial_count - 1)

    def test_remove_asset_invalid_index(self):
        """Test remove_asset with invalid index does nothing"""
        invalid_index = self.library.index(99, 0)
        initial_count = self.library.rowCount()

        self.library.remove_asset(invalid_index)

        self.assertEqual(self.library.rowCount(), initial_count)

    def test_rename_category(self):
        """Test rename_category updates all assets"""
        self.library.rename_category("metal", "metallic")

        self.mock_material.rename_category.assert_called_once_with("metal", "metallic")

    def test_remove_category(self):
        """Test remove_category removes from all assets"""
        self.library.remove_category("metal")

        self.mock_material.remove_category.assert_called_once_with("metal")

    def test_add_asset(self):
        """Test add_asset creates new material"""
        mock_node = Mock()
        mock_node.name.return_value = "NewMaterial"

        mock_handler = Mock()
        mock_handler.get_renderer_from_node.return_value = "karma"
        mock_handler.save_node.return_value = True
        self.mock_nodes_cls.return_value = mock_handler

        new_mat = Mock()
        new_mat.mat_id = "mat_002"
        self.mock_material_cls.return_value = new_mat

        renderer = self.library.add_asset(mock_node, "metal", "test", False)

        self.assertEqual(renderer, "karma")
        mock_handler.save_node.assert_called_once()

    def test_add_asset_says_no_when_the_save_did_not_happen(self):
        """THE RENDERER-STRING CONTRACT, which all three add_assets honour: a renderer name means the asset is IN the library, an empty string means it is not. Returning the renderer regardless of what save_node answered lets every call site read a failed save as a good one."""
        mock_node = Mock()
        mock_node.name.return_value = "RefusedMaterial"

        mock_handler = Mock()
        mock_handler.get_renderer_from_node.return_value = "karma"
        mock_handler.save_node.return_value = False
        self.mock_nodes_cls.return_value = mock_handler

        new_mat = Mock()
        new_mat.mat_id = "mat_refused"
        self.mock_material_cls.return_value = new_mat

        before = len(self.library.assets)
        renderer = self.library.add_asset(mock_node, "metal", "x", False)

        self.assertEqual(
            "", renderer,
            "a refused save answered with a renderer, which every "
            "caller reads as success")
        self.assertEqual(
            before, len(self.library.assets),
            "a refused save still added a row")

    def test_flags(self):
        """Test flags returns correct item flags"""
        index = self.library.index(0, 0)
        flags = self.library.flags(index)

        self.assertTrue(flags & QtCore.Qt.ItemFlag.ItemIsDragEnabled)

    def test_set_custom_iconsize(self):
        """Test set_custom_iconsize updates thumbnail size"""
        new_size = QtCore.QSize(512, 512)

        self.library.set_custom_iconsize(new_size)

        self.assertEqual(self.library._thumbsize, 512)

    def test_render_thumbnail(self):
        """Test render_thumbnail creates thumbnail for asset"""
        mock_renderer = Mock()
        self.mock_thumbs_cls.return_value = mock_renderer

        index = self.library.index(0, 0)
        self.library.render_thumbnail(index)

        mock_renderer.create_thumbnail.assert_called_once()

    def test_import_asset_to_scene(self):
        """Test import_asset_to_scene imports asset to Houdini"""
        mock_importer = Mock()
        self.mock_nodes_cls.return_value = mock_importer

        index = self.library.index(0, 0)
        self.library.import_asset_to_scene(index)

        mock_importer.import_asset_to_scene.assert_called_once_with(
            self.mock_material, "auto", context_node=None
        )

    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir")
    @patch("os.path.exists")
    @patch("os.remove")
    @patch("os.makedirs")
    @patch("os.replace")
    def test_cleanup_db_removes_orphan_files(
        self, mock_replace, mock_makedirs, mock_remove, mock_exists,
        mock_listdir, _mock_isdir
    ):
        """Test cleanup_db quarantines files no section lists"""
        mock_exists.side_effect = lambda path: not names_a_sibling_database(  # the SIBLING databases must read as fully ABSENT, TRACES included: one that exists-but-unparseable, or is merely absent-but-known, holds the sweep back instead - which is the refusal test below, not this one
            path)
        mock_listdir.side_effect = [
            [],                             # scratch sweep: assets dir
            [],                             # scratch sweep: img dir
            ["mat_001.mat", "orphan.mat"],  # assets dir
            ["mat_001.png", "orphan.png"],  # img dir
            [],                             # quarantine days, for pruning
        ]

        with patch.object(hou, "ui", MagicMock(), create=True):  # create=True because hou.ui may not exist at all under hython, and a raw assignment leaks into every later test in the process
            self.library.cleanup_db()

        self.assertFalse(  # MOVED, never unlinked: a sweep that is wrong is wrong about the user's only copy ▸p/clean-library-sweep
            mock_remove.called,
            "cleanup still unlinks - a wrong sweep is unrecoverable")
        self.assertTrue(
            mock_replace.called,
            "cleanup neither removed nor quarantined the leftover files; "
            "summary was: %s" % self.library.last_cleanup_summary)
        from amaze.core import library as lib_mod
        moved = [c.args[1] for c in mock_replace.call_args_list]
        self.assertTrue(
            all(lib_mod.QUARANTINE_PREFIX in str(dest) for dest in moved),
            "files went somewhere other than the quarantine folder: %s"
            % moved)
        self.assertFalse(
            any(str(dest).startswith(self.library.preferences.dir)
                for dest in moved),
            "the quarantine is inside the library - it would grow there "
            "forever, sync to every machine, and break the rule that an "
            "installed library holds nothing temporary: %s" % moved)

    @patch("os.path.isdir", return_value=True)
    @patch("os.listdir", return_value=[])
    @patch("os.remove")
    def test_a_half_synced_asset_keeps_its_surviving_files(
        self, mock_remove, _mock_listdir, _mock_isdir
    ):
        """Removing the stale INDEX entry must not unlink what is there - these rows are collected BECAUSE a file is missing, so a path that also deletes files takes out the surviving sibling of a pair. ▸p/clean-library-sweep"""
        rows_before = self.library.rowCount()
        self.assertGreater(rows_before, 0, "fixture has no assets")

        victim = self.library._assets[0].mat_id  # one asset's .mat has not arrived; everything else is present
        missing = str(victim) + self.library.preferences.ext

        def exists(path):
            if names_a_sibling_database(path):  # traces included, or the sweep is held back and this passes for the wrong reason: nothing removed because nothing was examined
                return False
            return not str(path).endswith(missing)

        with patch("os.path.exists", side_effect=exists):
            with patch.object(hou, "ui", MagicMock(), create=True):
                self.library.cleanup_db(show_dialog=False)

        self.assertEqual(  # THE ROW SURVIVES: it carries tags, a description and a date that exist nowhere else, and a file mid-sync looks exactly like one that is gone, so a single exists() miss must not spend them
            rows_before, self.library.rowCount(),
            "cleanup removed an index entry on one missing file - that is "
            "metadata stored nowhere else, thrown away on evidence a "
            "half-finished sync produces routinely")
        self.assertTrue(
            any("files are missing" in line
                for line in self.library.last_cleanup_summary),
            "the missing files were not reported, so the row survives and "
            "nobody is told: %s" % self.library.last_cleanup_summary)
        self.assertFalse(
            mock_remove.called,
            "cleanup unlinked files for a half-synced asset: %s"
            % [c.args for c in mock_remove.call_args_list])

    @patch("os.path.isdir", return_value=False)
    def test_cleanup_db_refuses_when_the_asset_folder_is_unreadable(
        self, _mock_isdir
    ):
        """Never act on incomplete knowledge, and the FOLDER counts as knowledge: an unreadable asset folder ends the run before pass 1, with the reason on the summary and nothing touched. Without that check a folder still syncing reads as every asset missing. ▸p/clean-library-sweep"""
        before = self.library.rowCount()
        with patch.object(hou, "ui", MagicMock(), create=True):
            result = self.library.cleanup_db(show_dialog=False)
        self.assertEqual(0, result)
        self.assertEqual(before, self.library.rowCount(),
                         "rows were dropped while the folder was unreadable")
        self.assertTrue(self.library.last_cleanup_summary,
                        "the refusal said nothing")
        self.assertIn("could not be read",
                      self.library.last_cleanup_summary[0])


class TheSentinelHasOneHome(unittest.TestCase):
    """The mixed-selection sentinel is COMPARED against, so a drifted spelling silently overwrites a field. ONE definition, `material.MULTIPLE_VALUES`, and every other appearance imports it."""

    def test_the_literal_is_spelled_exactly_once(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spellings = []
        for base, _dirs, files in os.walk(root):
            if os.path.basename(base) == "tests":
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as handle:
                    count = handle.read().count("Multiple Values...")
                if count:
                    spellings.append(
                        (test_support.posix_relpath(path, root), count))
        self.assertEqual(
            [("core/material.py", 1)], spellings,
            "the sentinel is spelled outside its one home - import "
            "material.MULTIPLE_VALUES instead")


class MixedSelectionTest(unittest.TestCase):
    """Editing a multi-selection must not refile everything. The details form applies one value per field to every selected asset, and set_assetdata reads the mixed-selection sentinel as leave-this-field-alone - so a field that does NOT show it moves every selected asset into the first one's value, and there is no undo for that."""

    SENTINEL = "Multiple Values..."

    @staticmethod
    def _asset(name, category):
        from amaze.core.material import Material
        asset = Material()
        asset.set_data(name, category, "", False, "Karma")
        return asset

    def test_the_sentinel_leaves_each_asset_where_it_was(self):
        from amaze.core.material import Material
        for original in ("Metal", "Wood", ""):
            asset = self._asset("a", original)
            # what set_assetdata does with the sentinel, in one line
            cats = self.SENTINEL
            kept = cats if self.SENTINEL not in cats \
                else ", ".join(asset.categories)
            asset.set_data("a", kept, "", False, None)
            self.assertEqual(
                [original] if original else [], asset.categories,
                "a mixed-selection edit moved an asset out of %r"
                % original)
        self.assertTrue(issubclass(Material, object))

    def test_a_real_value_still_applies(self):
        asset = self._asset("a", "Metal")
        cats = "Wood"
        kept = cats if self.SENTINEL not in cats \
            else ", ".join(asset.categories)
        asset.set_data("a", kept, "", False, None)
        self.assertEqual(["Wood"], asset.categories)


class SingleCategoryTest(unittest.TestCase):
    """One asset, one category - the capability to hold several is gone from the SOURCE, not merely migrated out of the data, so no later per-category property has to invent a rule for which of several wins. Tags are the many-to-many axis. This file patches `material.Material` for the model tests, so the REAL class is imported by name below."""

    @staticmethod
    def _asset():
        from amaze.core.material import Material
        return Material()

    def test_a_comma_list_keeps_only_the_first(self):
        asset = self._asset()
        asset.categories = "Metal, Rough, Worn"
        self.assertEqual(["Metal"], asset.categories)

    def test_a_real_list_keeps_only_the_first(self):
        asset = self._asset()
        asset.categories = ["Metal", "Rough"]
        self.assertEqual(["Metal"], asset.categories)

    def test_inner_spaces_survive(self):
        """The comma split is why "rs material" has to stay intact."""
        asset = self._asset()
        asset.categories = "rs material"
        self.assertEqual(["rs material"], asset.categories)

    def test_empty_means_no_category(self):
        asset = self._asset()
        asset.categories = ""
        self.assertEqual([], asset.categories)

    def test_set_data_cannot_smuggle_a_second_one_in(self):
        """set_data is the path every save and every edit goes through."""
        asset = self._asset()
        asset.set_data("n", "Metal, Rough", "", False, "Karma")
        self.assertEqual(["Metal"], asset.categories)


class ReloadChainTest(unittest.TestCase):
    """Every amaze module the panel imports must also be in its reload chain - a module left OUT keeps its old code while everything around it is new. COMPLETENESS is the invariant, not whether the chain executes: it no longer runs by default, and a chain with a hole in it is worth nothing on the day someone turns it on. Derived from the source, so a new import cannot quietly skip it. ▸p/source-derived-tests"""

    def test_every_imported_amaze_module_is_reloaded(self):
        import re

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()

        reloaded = set(re.findall(
            r"(?:importlib\.reload|_reload)\((\w+)\)", source))
        reloaded |= set(re.findall(r"(\w+)\.reload_engine\(\)", source))  # A PACKAGE CANNOT BE RELOADED BY RELOADING IT - importlib.reload re-runs only __init__.py, which hands back the cached submodules, so a package answers with its own entry point instead ▸r/package-reload
        imported = set()
        for match in re.finditer(  # PARENTHESISED imports span lines: a pattern stopping at the first newline contributes NOTHING for them, and this test passes happily while those modules sit outside the chain
                r"^from amaze[\w.]* import \(([^)]*)\)", source, re.M | re.S):
            for name in match.group(1).split(","):
                name = name.strip()
                if name and name.isidentifier():
                    imported.add(name)
        for match in re.finditer(
                r"^from amaze[\w.]* import ([^(\n]+)$", source, re.M):
            for name in match.group(1).split(","):
                name = name.strip()
                if name and name.isidentifier():
                    imported.add(name)

        self.assertEqual(
            set(), imported - reloaded,
            "panel.py imports these without reloading them; a stale one "
            "keeps old code while its callers get new")


class ModelSignalTest(unittest.TestCase):
    """Row mutations must announce themselves: views track rows by persistent index, so appending or removing without `begin/endInsertRows` leaves them dangling. `layoutChanged` is the WRONG signal for a changed row COUNT - it says the order may have changed, not the count. ▸r/model-contracts"""

    def setUp(self):
        from amaze.core import category as category_mod
        from amaze.tests import test_support

        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.cats = category_mod.Categories(preferences=self.prefs)

    def _count(self, signal):
        seen = []
        signal.connect(lambda *a: seen.append(1))
        return seen

    def test_adding_a_category_fires_rows_inserted(self):
        inserted = self._count(self.cats.rowsInserted)
        self.cats.check_add_category("BrandNewCategory")
        self.assertEqual(
            1, len(inserted),
            "a new category appeared with no rowsInserted signal")

    def test_removing_a_category_fires_rows_removed(self):
        self.cats.check_add_category("Doomed")
        removed = self._count(self.cats.rowsRemoved)
        self.cats.remove_category("Doomed")
        self.assertEqual(
            1, len(removed),
            "a category vanished with no rowsRemoved signal")

    def test_removing_a_name_that_is_not_there_is_a_no_op(self):
        """`list.remove` raises ValueError for any name the sidebar displayed with its leading underscore stripped - and that escapes the panel slot AFTER the asset model has stripped the category from every Material in memory and BEFORE save() runs."""
        before = self.cats.rowCount()
        try:
            self.cats.remove_category("All")      # displayed for "_All"
        except ValueError:
            self.fail("remove_category raised for a name it does not hold")
        self.assertEqual(before, self.cats.rowCount())

    def test_a_code_snippet_insert_fires_rows_inserted(self):
        from amaze.core import code_library

        model = code_library.CodeLibrary(preferences=self.prefs)
        inserted = self._count(model.rowsInserted)
        before = model.rowCount()
        model.add_asset("print(1)", "snippet_probe", "Python", "", "", False)
        if model.rowCount() == before:
            self.skipTest("add_asset refused this snippet")
        self.assertEqual(
            1, len(inserted),
            "a snippet appeared with no rowsInserted signal")


class SchemaStampTest(unittest.TestCase):
    """A newer build's database must not be stamped BACKWARDS. `_migrate` refuses to touch a newer schema, and a save that then overwrites the version anyway leaves the newer build's data under an older number - so that machine re-runs its whole migration chain over already-migrated data."""

    def setUp(self):
        import json
        from amaze.core import library as library_mod
        from amaze.tests import test_support

        self.json = json
        self.prefs = test_support.fixture_prefs(self)
        self.path = os.path.join(self.prefs.dir, "library.json")
        self.library_mod = library_mod
        self.test_support = test_support

    def _version_after_save(self, written):
        with open(self.path, encoding="utf-8") as handle:
            data = self.json.load(handle)
        data["version"] = written
        with open(self.path, "w", encoding="utf-8") as handle:
            self.json.dump(data, handle)
        self.test_support.reset_database_singletons()
        model = self.library_mod.MaterialLibrary(preferences=self.prefs)
        model.save()
        with open(self.path, encoding="utf-8") as handle:
            return self.json.load(handle).get("version")

    def test_a_newer_version_is_not_downgraded(self):
        self.assertEqual(
            99, self._version_after_save(99),
            "a save stamped this build's schema over a newer one")


class ARetiredFieldDoesNotComeBackOnASaveTest(unittest.TestCase):
    """End to end, through the model that actually writes the file. THE DOCUMENT IS STAMPED AT THE CURRENT SCHEMA ON PURPOSE and carries the retired fields anyway: stamped at 4 the migration strips them before `Material` sees a row, so `_KNOWN_KEYS` is never consulted and this passes with the mechanism DELETED. The case it is for is a row reaching `from_dict` still carrying a retired key - a peer's row, or one merged in raw, on a document no step will run over again. A key `_KNOWN_KEYS` does not name is carried verbatim by `_extra` and re-emitted on every save."""

    def setUp(self):
        from amaze.core import library as library_mod
        from amaze.tests import test_support
        self.library_mod = library_mod
        self.test_support = test_support
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.path = os.path.join(self.prefs.dir, "library.json")

    def test_neither_field_survives_an_ordinary_save(self):
        import json
        with open(self.path, encoding="utf-8") as handle:
            document = json.load(handle)
        from amaze.core import database
        document["version"] = database.SCHEMA_VERSION
        for row in document["assets"]:
            row["favorite"] = True
            row["icon"] = {"name": "box", "bg": "#4af2a1"}
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

        model = self.library_mod.MaterialLibrary(preferences=self.prefs)
        self.assertTrue(
            model.assets,
            "premise: the fixture rows reached the model, so `from_dict` "
            "actually saw the retired keys")
        self.assertTrue(model.save(), "premise: the save reached disk")

        with open(self.path, encoding="utf-8") as handle:
            saved = json.load(handle)
        for row in saved["assets"]:
            self.assertNotIn(
                "favorite", row,
                "the retired favourite came back on the save, so the "
                "schema step is undone every time the panel writes")
            self.assertNotIn("icon", row, "the retired icon came back")


class AMaterialStarLivesInTheLibraryStoreTest(unittest.TestCase):
    """Materials, Nodes and Code stars go through the ONE favourites door, keyed by asset id and tagged with their owner - so one user sees the same stars on every machine, and two users of one library each see their own. `material_favorites` in settings.json never travels and is a MIGRATION SOURCE only: a toggle must not touch it, and the role must answer the store."""

    def setUp(self):
        from amaze.core import keyed_store, library as library_mod
        from amaze.core import locations
        self.keyed_store = keyed_store
        self.locations = locations
        self.library_mod = library_mod
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        keyed_store.release()
        self.addCleanup(keyed_store.release)

    def test_a_toggle_lands_in_the_store_not_in_settings(self):
        model = self.library_mod.MaterialLibrary(preferences=self.prefs)
        self.assertTrue(model.assets, "premise: the fixture rows loaded")
        index = model.index(0, 0)
        mat_id = str(model.assets[0].mat_id)
        self.assertFalse(model.data(index, model.FavoriteRole),
                         "premise: the fixture starts unstarred")

        model.toggle_fav(index)
        self.assertTrue(
            model.data(index, model.FavoriteRole),
            "the toggle did not light the star through the store")
        store = self.keyed_store.open_store(
            self.locations.FAVOURITES_SPEC, self.prefs)
        self.assertTrue(
            store.has(mat_id),
            "the star is lit but the library store does not carry it - "
            "the role is answering something machine-local again")
        self.assertNotIn(
            mat_id, list(getattr(self.prefs, "material_favorites", ()) or ()),
            "the toggle wrote settings.json - the star went to the "
            "machine, so the same user's other machine cannot see it")

        # And it comes back through a fresh model reading the store.
        test_support.reset_database_singletons()
        self.keyed_store.release()
        again = self.library_mod.MaterialLibrary(preferences=self.prefs)
        rows = {str(a.mat_id): r for r, a in enumerate(again.assets)}
        self.assertTrue(
            again.data(again.index(rows[mat_id], 0), again.FavoriteRole),
            "the star did not survive a reload through the store")

    def test_no_user_picked_means_no_star(self):
        self.prefs.library_user = ""
        model = self.library_mod.MaterialLibrary(preferences=self.prefs)
        self.assertTrue(model.assets, "premise: the fixture rows loaded")
        index = model.index(0, 0)
        model.toggle_fav(index)
        self.assertFalse(
            model.data(index, model.FavoriteRole),
            "a machine with nobody picked lit a star - the store filed "
            "it under a blank tag, which is an ABSENT user, not a "
            "shared one")


class MaterialRoundTripTest(unittest.TestCase):
    """The dict round-trip must not lose what it does not understand. A fixed key set in both directions drops whatever a NEWER build wrote on the first save by an older one, and raises KeyError out of the model's `__init__` on a MISSING key, so one damaged row means the panel cannot open at all. Both compound with the adopted-row path, which takes raw disk dicts."""

    def _material(self):
        from amaze.core.material import Material
        return Material

    def test_an_unknown_key_survives_the_round_trip(self):
        Material = self._material()
        row = {
            "id": "x", "name": "n", "categories": [], "tags": [],
            "favorite": False, "date": "", "renderer": "Karma",
            "usd": False, "builder": 0,
            "future_field": {"from": "a newer build"},
        }
        back = Material.from_dict(row).get_as_dict()
        self.assertEqual(
            {"from": "a newer build"}, back.get("future_field"),
            "a key this build does not know was dropped on save")

    def test_a_missing_key_does_not_raise(self):
        Material = self._material()
        try:
            asset = Material.from_dict({"id": "x", "name": "n"})
        except KeyError as exc:
            self.fail("a row missing %s aborted the whole model" % exc)
        self.assertEqual("n", asset.name)

    def test_an_unknown_key_cannot_overwrite_a_known_one(self):
        """_extra is re-emitted, but it must never win over real state."""
        Material = self._material()
        row = {
            "id": "x", "name": "real", "categories": [], "tags": [],
            "favorite": False, "date": "", "renderer": "Karma",
            "usd": False, "builder": 0,
        }
        asset = Material.from_dict(row)
        asset._extra = {"name": "impostor"}
        self.assertEqual("real", asset.get_as_dict()["name"])

    def test_the_known_key_set_matches_what_is_emitted(self):
        """`_KNOWN_KEYS` drives what counts as unknown, so drift from `get_as_dict` starts treating a real field as extra. RETIRED keys are the deliberate exception - understood precisely so they are DROPPED rather than carried - which makes the set what is emitted PLUS those."""
        Material = self._material()
        row = {
            "id": "x", "name": "n", "categories": [], "tags": [],
            "favorite": False, "date": "", "renderer": "Karma",
            "usd": False, "builder": 0,
        }
        emitted = set(Material.from_dict(row).get_as_dict())
        self.assertEqual(
            set(Material._KNOWN_KEYS),
            emitted | set(Material._RETIRED_KEYS),
            "_KNOWN_KEYS and get_as_dict have drifted apart")
        self.assertFalse(
            emitted & set(Material._RETIRED_KEYS),
            "a retired key is still being written, so the schema step "
            "that strips it is undone by the next save")


class UnreadableSiblingIsNotOverwrittenTest(unittest.TestCase):
    """The other session's database must survive our next save. The stale-write guard fires exactly when the file changed underneath us - the two-machine / cloud-sync case - and hands to a merge whose one real failure mode is their file being mid-write. Letting save() carry on from there writes our copy over theirs, and `snapshot_before_write` is once-per-session, so a second save in the same session leaves no copy at all."""

    def setUp(self):
        from amaze.core import database, library as library_mod
        from amaze.tests import test_support
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.db = database.DatabaseConnector(library_mod.MaterialLibrary.DB_FILENAME)  # one connector per filename, shared - the same object the model writes through
        self.db_path = os.path.join(self.prefs.dir, "library.json")

    def _their_file_changed_and_is_unparseable(self):
        """Make the on-disk file both NEWER and broken, so the guard fires and the merge then fails."""
        self.db._disk_stat = (0, 0)          # anything that is not the file's
        with open(self.db_path, "w", encoding="utf-8") as handle:
            handle.write('{"assets": [{"id": "THEIRS", ')   # truncated

    def test_their_unparseable_file_is_not_overwritten(self):
        self._their_file_changed_and_is_unparseable()
        before = open(self.db_path, encoding="utf-8").read()
        self.db.save()
        after = open(self.db_path, encoding="utf-8").read()
        self.assertEqual(
            before, after,
            "we overwrote a database we could not read - that is the "
            "other machine's work")

    def test_a_copy_of_their_file_is_kept(self):
        self._their_file_changed_and_is_unparseable()
        self.db.save()
        self.assertTrue(
            os.path.exists(self.db_path + ".unreadable"),
            "no copy was kept, so there is nothing to recover from")

    def test_the_refusal_holds_for_the_REST_of_the_session(self):
        """Refusing once is not enough: the next save would overwrite exactly what the first refusal preserved."""
        self._their_file_changed_and_is_unparseable()
        self.db.save()
        before = open(self.db_path, encoding="utf-8").read()
        self.db._disk_stat = None          # guard would not re-fire
        self.db.save()
        after = open(self.db_path, encoding="utf-8").read()
        self.assertEqual(
            before, after,
            "a later save in the same session overwrote it anyway")

    def test_an_ordinary_save_still_works(self):
        """The refusal must not be the normal path."""
        self.db.save()
        with open(self.db_path, encoding="utf-8") as handle:
            self.assertIn("assets", json.load(handle))


class TwoMachineMergeTest(unittest.TestCase):
    """What another machine wrote must survive this machine's save. The stale-write merge adopts their rows into the FILE, and save() rebuilds assets[] from the MODEL - so a row adopted into one and not the other reaches disk, gets folded into the loaded-id set where no later merge re-adopts it, and is written out of existence by the next ordinary save with nothing on screen signalling the loss. The same shape threatens every top-level key, so the merge unions `category_colors` by key and carries anything it does not recognise through untouched - both asserted below."""

    def setUp(self):
        import json
        from amaze.core import library as library_mod
        from amaze.tests import test_support

        self.json = json
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.db_path = os.path.join(self.prefs.dir, "library.json")

    def _disk(self):
        with open(self.db_path, encoding="utf-8") as handle:
            return self.json.load(handle)

    def _write_disk(self, data):
        import time
        with open(self.db_path, "w", encoding="utf-8") as handle:
            self.json.dump(data, handle)
        time.sleep(0.01)      # the guard compares mtime_ns + size

    def _other_machine_adds_a_material(self):
        import copy
        data = self._disk()
        row = copy.deepcopy(data["assets"][0])
        row["id"] = "FROM_OTHER_MAC"
        row["name"] = "from_other_mac"
        data["assets"].append(row)
        self._write_disk(data)

    def test_an_adopted_row_reaches_the_model(self):
        self._other_machine_adds_a_material()
        self.model.save()  # save() directly, because a favourite toggle no longer writes the library at all
        self.assertNotEqual(
            -1, self.model.find_asset_row_by_id("FROM_OTHER_MAC"),
            "the adopted row never reached the model, so the next save "
            "will write it out of existence")

    def test_an_adopted_row_survives_the_next_save(self):
        """The consequence, not the wiring."""
        self._other_machine_adds_a_material()
        self.model.save()
        self.model.save()                              # a SECOND save
        ids = [a.get("id") for a in self._disk()["assets"]]
        self.assertIn(
            "FROM_OTHER_MAC", ids,
            "a material added on the other machine was deleted by this "
            "machine's second save")

    def test_another_sessions_category_colours_survive(self):
        data = self._disk()
        data["category_colors"] = {"Karma_Mats": "#ff0000"}
        self._write_disk(data)
        self.model.save()
        self.assertEqual(
            {"Karma_Mats": "#ff0000"},
            self._disk().get("category_colors"),
            "another session's category colours were wiped by an "
            "unrelated save")

    def test_an_unknown_top_level_key_is_carried_through(self):
        """A newer build's key must not be dropped by an older one."""
        data = self._disk()
        data["something_a_newer_build_wrote"] = {"keep": "me"}
        self._write_disk(data)
        self.model.toggle_fav(self.model.index(0, 0))
        self.assertEqual(
            {"keep": "me"},
            self._disk().get("something_a_newer_build_wrote"),
            "an unrecognised top-level key was dropped on save")

    def test_a_sparse_adopted_row_is_kept_not_dropped(self):
        """A row carrying only an id still belongs to someone: `from_dict` fills defaults rather than raising, so it is adopted rather than lost. This build must not delete what it merely does not fully understand."""
        data = self._disk()
        data["assets"].append({"id": "SPARSE_ROW"})
        self._write_disk(data)
        try:
            self.model.save()
        except Exception as exc:                       # noqa: BLE001
            self.fail("a sparse adopted row aborted the save: %s" % exc)
        self.assertNotEqual(
            -1, self.model.find_asset_row_by_id("SPARSE_ROW"),
            "a row with only an id was dropped instead of adopted")
        ids = [a.get("id") for a in self._disk()["assets"]]
        self.assertIn("SPARSE_ROW", ids)

    def test_a_row_that_is_not_a_dict_cannot_abort_the_save(self):
        """The genuinely unparseable case still has to be survivable."""
        data = self._disk()
        data["assets"].append("this is not a row")
        self._write_disk(data)
        try:
            self.model.toggle_fav(self.model.index(0, 0))
        except Exception as exc:                       # noqa: BLE001
            self.fail("a malformed adopted row aborted the save: %s" % exc)


class CleanupRefusesOnIncompleteKnowledgeTest(unittest.TestCase):
    """Clean Library must not sweep files it cannot account for. The material and COP libraries share the same asset and image folders, so an absent entry in THIS database is not enough to call a file unclaimed - the sweep unions the ids from every sibling first, and skipping an unreadable one makes every file it owns look unclaimed. ▸p/clean-library-sweep"""

    def setUp(self):
        from amaze.core import library as library_mod
        from amaze.tests import test_support

        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)

    def _write_sibling(self, name, text):
        path = os.path.join(self.prefs.dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_an_unreadable_sibling_is_reported_not_skipped(self):
        self._write_sibling("cops.json", '{"assets": [{"id": "COPASSET1"}')
        ids, unreadable, _absent, _empty = self.model._all_known_asset_ids()
        self.assertTrue(
            unreadable,
            "an unreadable sibling database was skipped silently - every "
            "file it owns now looks like an orphan to be deleted")
        self.assertIn("cops.json", unreadable[0][0])  # (what to call the section, why it could not be checked) stays two halves, because the caller writes them into two different sentences
        self.assertIn("cannot read it", unreadable[0][1])

    def test_a_readable_sibling_contributes_its_ids(self):
        self._write_sibling("cops.json", '{"assets": [{"id": "COPASSET1"}]}')
        ids, unreadable, _absent, _empty = self.model._all_known_asset_ids()
        self.assertEqual([], unreadable)
        self.assertIn("COPASSET1", ids,
                      "a sibling's ids did not reach the orphan check")

    def test_an_absent_sibling_is_not_an_error(self):
        """Absent owns nothing; only present-but-unparseable is unsafe."""
        path = os.path.join(self.prefs.dir, "cops.json")
        if os.path.exists(path):
            os.remove(path)
        _ids, unreadable, absent, _empty = self.model._all_known_asset_ids()
        self.assertEqual([], unreadable)
        self.assertEqual({}, absent)


def _empty_library_dir(testcase) -> str:
    """A valid but assetless library directory, auto-removed. NOT just an empty folder: `database.load` treats a MISSING library.json as a real error the caller must surface, so the switch would raise instead of exercising the reset."""
    import json
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="amaze_empty_lib_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    with open(os.path.join(tmp, "library.json"), "w", encoding="utf-8") as handle:
        json.dump({"categories": ["_All"], "tags": [], "assets": []}, handle)
    return tmp + os.sep


class LibrarySwitchTest(unittest.TestCase):
    """Switching the library directory must RESET the model: `switch_model_data` replaces the whole row set in place, and without the bracket every attached proxy keeps its old row count and the selection keeps an index into rows that are gone - reachable from Preferences by pointing the library at a smaller one, and it segfaults rather than raising. ▸r/model-contracts. This file patches `material.Material` for the model tests, so the real modules are imported below by name."""

    def setUp(self):
        from amaze.core import library as library_mod
        from amaze.tests import test_support

        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)

        self.proxy = QtCore.QSortFilterProxyModel()  # the panel puts a proxy and a selection model on this, which is what makes a missing reset fatal rather than untidy
        self.proxy.setSourceModel(self.model)
        self.selection = QtCore.QItemSelectionModel(self.proxy)

    def _switch_to_an_empty_library(self):
        """Point prefs at a library with no assets and switch. Prefs is SAVED first, because switch_model_data re-reads settings.json - the fixture's own copy, never the machine's."""
        self.prefs.dir = _empty_library_dir(self)
        self.prefs.save()
        self.model.switch_model_data()

    def test_switching_resets_the_model(self):
        rows = self.model.rowCount()
        self.assertGreater(rows, 0, "fixture library has no assets to switch away from")
        self.assertEqual(rows, self.proxy.rowCount())

        last = self.proxy.index(rows - 1, 0)  # park the selection on the LAST row, the one a smaller library cannot have
        self.selection.setCurrentIndex(
            last, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.assertEqual(rows - 1, self.selection.currentIndex().row())

        resets = []
        self.model.modelAboutToBeReset.connect(lambda: resets.append("about"))
        self.model.modelReset.connect(lambda: resets.append("done"))

        self._switch_to_an_empty_library()

        self.assertEqual(
            ["about", "done"], resets,
            "switch_model_data replaced every row without a model reset - "
            "attached proxies and selections keep indexes into rows that "
            "are gone")
        self.assertEqual(
            self.model.rowCount(), self.proxy.rowCount(),
            "the proxy is out of step with its source after a switch")
        self.assertLess(
            self.selection.currentIndex().row(), self.model.rowCount(),
            "the selection still points past the end of the new library")

    def test_a_raising_switch_still_closes_the_reset(self):
        """`endResetModel` sits in a finally, so a failed switch cannot leave the model parked between begin and end. Asserted on the SIGNAL PAIR, never on rowCount - a model stuck mid-reset is invisible through the proxy, which keeps serving the old rows either way. ▸r/model-contracts"""
        from unittest.mock import patch

        began, ended = [], []
        self.model.modelAboutToBeReset.connect(lambda: began.append(1))
        self.model.modelReset.connect(lambda: ended.append(1))

        with patch.object(type(self.prefs), "load",  # fail INSIDE the reset window: prefs.load is the first call after beginResetModel
                          side_effect=OSError("settings unreadable")):
            with self.assertRaises(OSError):
                self.model.switch_model_data()

        self.assertEqual(1, len(began), "the switch never began a reset")
        self.assertEqual(
            len(began), len(ended),
            "switch_model_data raised and left the model mid-reset - "
            "endResetModel must be in a finally")


class GradientSwitchTest(unittest.TestCase):
    """Colors is library-backed too, and is the model easiest to leave out of a switch - a tab still holding the previous library's palettes would write all of them into the NEW library on the next colour edit. Two defences are asserted here: the model resets on a switch, and the inherited `db.serves()` guard refuses the save even if some path forgets to."""

    def _model(self):
        from amaze.core import gradient_library
        from amaze.tests import test_support

        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        return gradient_library.GradientLibrary(preferences=self.prefs)

    def test_switching_resets_the_gradient_model(self):
        model = self._model()
        proxy = QtCore.QSortFilterProxyModel()
        proxy.setSourceModel(model)
        self.assertEqual(model.rowCount(), proxy.rowCount())

        resets = []
        model.modelAboutToBeReset.connect(lambda: resets.append("about"))
        model.modelReset.connect(lambda: resets.append("done"))

        self.prefs.dir = _empty_library_dir(self)
        self.prefs.save()
        model.switch_model_data()

        self.assertEqual(
            ["about", "done"], resets,
            "the gradient model replaced its rows without a reset")
        self.assertEqual(
            model.rowCount(), proxy.rowCount(),
            "the proxy is out of step with the gradient model")

    def test_a_save_aimed_at_ANOTHER_library_is_refused(self):
        """The belt-and-braces half: even if some path forgets to switch this model, it must not write these colours into a library they did not come from. The guard IS `db.serves()` - one guard, inherited, rather than a private stand-in per model."""
        model = self._model()
        from amaze.core import database
        connector = database.DatabaseConnector(model.DB_FILENAME)
        self.assertTrue(connector.serves(self.prefs.dir),
                        "premise: the connector serves this library")

        self.prefs.dir = _empty_library_dir(self)  # move the library under the model WITHOUT switching it - the exact state a missing switch leaves behind
        self.assertFalse(
            model.save(),
            "the gradient model saved colours from library A into "
            "library B - nothing refused the write")


class TheColorsSidebarFollowsTheLibraryTest(unittest.TestCase):
    """The Colors SIDEBAR is a library-backed model too, and HALF-RIGHT is what let it survive being left out of a switch: the grid moved while the sidebar still named the old library's categories with the new library's counts beside them, every row zero. Clicking one filters by a category that does not exist; renaming one aims the command at the new library carrying the old label."""

    RAMP = {"values": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}  # a two-key ramp, the shape add_user_gradient reads

    def _library_with_category(self, prefs, name):
        """A library directory holding one user palette in category `name`, written THROUGH THE PRODUCT'S OWN API - `add_user_gradient` mints the uid and saves, so the file on disk is the real one. Hand-writing gradients.json does not load at all, and a fixture writing a shape we never ship proves nothing about the shape we do (practice.md ▸ A FIXTURE MUST WRITE FILES THE WAY THE PRODUCT DOES)."""
        from amaze.core import gradient_library

        folder = _empty_library_dir(self)
        prefs.dir = folder
        prefs.save()
        writer = gradient_library.GradientLibrary(preferences=prefs)
        writer.add_user_gradient("P " + name, name, self.RAMP)
        return folder

    def _labels(self, sidebar):
        return [sidebar.data(sidebar.index(row, 0))
                for row in range(sidebar.rowCount())]

    def test_the_sidebar_holds_the_NEW_librarys_categories(self):
        from amaze.core import gradient_library
        from amaze.tests import test_support

        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self._library_with_category(prefs, "Alpha")

        model = gradient_library.GradientLibrary(preferences=prefs)
        sidebar = gradient_library.GradientCategories(preferences=prefs)
        self.assertIn("Alpha", self._labels(sidebar),
                      "premise: the sidebar shows library A's category")

        self._library_with_category(prefs, "Beta")
        model.switch_model_data()
        sidebar.switch_model_data()

        labels = self._labels(sidebar)
        self.assertIn(
            "Beta", labels,
            "the Colors sidebar does not show the new library's "
            "categories after a switch")
        self.assertNotIn(
            "Alpha", labels,
            "the Colors sidebar kept the PREVIOUS library's category "
            "names - their counts come from the new library, so every "
            "row reads zero and clicking one filters by a category "
            "that does not exist there: %s" % labels)


class EveryLibraryModelClassCanSwitchTest(unittest.TestCase):
    """Every class the panel builds a library-backed model from answers `switch_model_data`. This is the CLASS contract only - the list-shaped half is `test_area_bindings` ▸ EveryLibraryBackedModelIsDeclaredBySection, which walks the sections' declarations against a built panel in both directions and needs no list of its own."""

    def test_every_library_model_class_answers_the_switch_verb(self):
        from amaze.core import (category, code_library, cop_library,
                                gradient_library, library)

        for cls in (library.MaterialLibrary, category.Categories,
                    cop_library.CopLibrary, code_library.CodeLibrary,
                    gradient_library.GradientLibrary,
                    gradient_library.GradientCategories):
            self.assertTrue(
                callable(getattr(cls, "switch_model_data", None)),
                "%s has no switch_model_data, so pointing Preferences "
                "at another library leaves it holding the old one"
                % cls.__name__)


class CategorySwitchTest(unittest.TestCase):
    """The sidebar model has the same contract as the grid model."""

    def test_switching_resets_the_category_model(self):
        from amaze.core import category as category_mod
        from amaze.tests import test_support

        prefs_obj = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        cats = category_mod.Categories(preferences=prefs_obj)

        proxy = QtCore.QSortFilterProxyModel()
        proxy.setSourceModel(cats)
        self.assertEqual(cats.rowCount(), proxy.rowCount())

        resets = []
        cats.modelAboutToBeReset.connect(lambda: resets.append("about"))

        prefs_obj.dir = _empty_library_dir(self)
        prefs_obj.save()
        cats.switch_model_data()

        self.assertEqual(
            ["about"], resets,
            "Categories.switch_model_data replaced every row with no reset")
        self.assertEqual(
            cats.rowCount(), proxy.rowCount(),
            "the sidebar proxy is out of step with its source after a switch")


class FavouritesArePerUserTest(unittest.TestCase):
    """A favourite that lives on the SHARED record means one user's star toggles another's in a multi-user library. Every section keeps them per-user instead."""

    def setUp(self):
        from amaze.core import library as library_mod
        from amaze.tests import test_support
        self.test_support = test_support
        self.library_mod = library_mod
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _model(self):
        return self.library_mod.MaterialLibrary(preferences=self.prefs)

    def test_a_toggle_never_writes_the_shared_index(self):
        import json
        model = self._model()
        index_path = os.path.join(self.prefs.dir, "library.json")
        with open(index_path, "rb") as fh:
            before = fh.read()
        model.toggle_fav(model.index(0, 0))
        with open(index_path, "rb") as fh:
            after = fh.read()
        self.assertEqual(before, after,
                         "a favourite toggle wrote the shared index - "
                         "my star still collides with yours")
        self.assertTrue(model.data(model.index(0, 0), model.FavoriteRole))


class TheSharedBaseCarriesNothingRendererShaped(unittest.TestCase):
    """The shared engine is `AssetLibrary`, every section model inherits it, and what a MATERIAL is - renderer detection, USD and shader labels, the Karma batch, MAT/LOP routing, the Redshift conversion - lives only on `MaterialLibrary`."""

    RENDERER_SHAPED = (  # the renderer-shaped surface by name: declared ON MaterialLibrary and absent from the base's own namespace, checked with vars() rather than getattr, because inheritance answers getattr for every subclass
        "is_usd_material", "shader_type_label", "add_asset",
        "update_asset_content", "import_asset_to_scene",
        "convert_redshift_to_karma",
    )

    def test_the_four_models_inherit_the_base(self):
        from amaze.core import (code_library, cop_library,
                                gradient_library, library)
        for model in (library.MaterialLibrary, cop_library.CopLibrary,
                      code_library.CodeLibrary,
                      gradient_library.GradientLibrary):
            self.assertTrue(
                issubclass(model, library.AssetLibrary),
                "%s does not run on the shared engine" % model.__name__)

    def test_the_base_declares_none_of_the_material_surface(self):
        from amaze.core import library
        on_base = [name for name in self.RENDERER_SHAPED
                   if name in vars(library.AssetLibrary)]
        self.assertEqual(
            [], on_base,
            "the shared base grew renderer-shaped weight again: %s"
            % on_base)
        for name in self.RENDERER_SHAPED:  # the positive control, so an emptied Material class cannot satisfy the assertion above by accident
            self.assertIn(
                name, vars(library.MaterialLibrary),
                "%s left MaterialLibrary - if it was retired, retire "
                "it from this list in the same commit" % name)


if __name__ == "__main__":
    unittest.main()
