"""The library models: `MaterialLibrary` on mocks, the rest against a real fixture library."""

import unittest
from unittest.mock import Mock, MagicMock, patch
import os
import json
import shutil
import sys
import tempfile

sys.path.insert(  # three dirnames up is scripts/python: the dev tree, not the install ▸p/checkout-not-install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from PySide6 import QtCore, QtWidgets

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])    # ▸p/first-app-picks-the-platform

import hou  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log
from amaze.actions import materials as material_actions  # noqa: E402


class TestMaterialLibrary(unittest.TestCase):
    """Test suite for MaterialLibrary class"""

    def setUp(self):
        """Set up test fixtures and mocks; the patches stop even when setUp fails part way."""
        self.addCleanup(patch.stopall)
        self.prefs_patcher = patch("amaze.core.library.prefs.Prefs")
        self.db_patcher = patch("amaze.core.library.database.DatabaseConnector")
        self.material_patcher = patch("amaze.core.library.material.Material")
        self.thumbs_patcher = patch("amaze.render.thumbs.ThumbNailRenderer")
        self.nodes_patcher = patch("amaze.actions.materials.nodes.NodeHandler")
        self.qimage_patcher = patch("PySide6.QtGui.QImage")

        self.mock_prefs_cls = self.prefs_patcher.start()
        self.mock_db_cls = self.db_patcher.start()
        self.mock_material_cls = self.material_patcher.start()
        self.mock_thumbs_cls = self.thumbs_patcher.start()
        self.mock_nodes_cls = self.nodes_patcher.start()
        self.mock_hou = Mock()
        self.mock_qimage_cls = self.qimage_patcher.start()

        self.mock_prefs = Mock()
        self._library_dir = tempfile.mkdtemp(prefix="amaze_testlib_own_")  # a real folder with a real library.json; only .dir is real
        self.addCleanup(shutil.rmtree, self._library_dir, True)
        with open(os.path.join(self._library_dir, "library.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": [{"id": "mat_001"}]}, handle)
        self.mock_prefs.dir = self._library_dir + os.sep
        self.mock_prefs.img_dir = os.path.join(self._library_dir, "img", "")    # absolute, inside temp
        self.mock_prefs.asset_dir = os.path.join(self._library_dir, "assets", "")
        self.mock_prefs.ext = ".mat"
        self.mock_prefs.img_ext = ".png"
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
        self.mock_material.about = ""    # a bare Mock is truthy here, and the About sweep would take it for credit text
        self.mock_material.get_as_dict.return_value = self.asset_data
        self.mock_material_cls.from_dict.return_value = self.mock_material

        self.mock_qimage = Mock()
        self.mock_qimage.scaled.return_value = self.mock_qimage
        self.mock_qimage_cls.return_value = self.mock_qimage

        self.mock_hou.getenv.return_value = "/fake/path"

        from amaze.core import library  # imported after the patches are live

        self.library = library.MaterialLibrary(self.mock_prefs)

    def test_a_positional_prefs_is_the_preferences(self):
        """`preferences` is first and positional, so the plain call binds it. ▸p/duplication-third-verb"""
        from amaze.core import library

        self.mock_prefs_cls.return_value = Mock()  # not `self.mock_prefs`, else the assertion compares the mock to itself

        model = library.MaterialLibrary(self.mock_prefs)

        self.assertIs(
            self.mock_prefs, model.preferences,
            "the model did not take the Prefs it was GIVEN - a positional "
            "argument no longer resolves to `preferences`")

    def test_omitting_preferences_raises_instead_of_reading_the_machine(self):
        """Omitting it must raise, never default to the machine's own library."""
        from amaze.core import library

        with patch("amaze.core.library.prefs.Prefs"):  # a restored fallback gets a mock, so a failing run cannot reach the machine's settings
            with self.assertRaises(TypeError):
                library.MaterialLibrary()

    def test_each_role_answers_the_records_field(self):
        """Decoration answers None until the async engine delivers; the delegate paints a dark tile."""
        self.assertEqual(1, self.library.rowCount())
        self.assertEqual("TestMaterial", self.library.assets[0].name)
        index = self.library.index(0, 0)
        for role, expected in ((QtCore.Qt.ItemDataRole.DisplayRole, "TestMaterial"),
                               (QtCore.Qt.ItemDataRole.DecorationRole, None),
                               (self.library.CategoryRole, ["metal", "rough"]),
                               (self.library.TagRole, ["test", "sample"]),
                               (self.library.RendererRole, "karma"),
                               (self.library.DateRole, "2026-02-08"),
                               (self.library.IdRole, "mat_001")):
            with self.subTest(role=role):
                self.assertEqual(expected, self.library.data(index, role))

    def test_data_favorite_role(self):
        """The role answers the one favourites door, keyed by asset id: never the shared record."""
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

    def test_sanitize_tags_trims_and_drops_duplicates(self):
        tags = set(self.library.sanitize_tags("tag1, tag2 , tag1, tag3").split(","))
        self.assertEqual({"tag1", "tag2", "tag3"}, tags)
        self.assertEqual("", self.library.sanitize_tags(""))

    def test_a_toggle_flips_the_star_through_the_one_favourites_door(self):
        """Keyed by the asset's id in the library store, so two users' stars cannot collide."""
        from amaze.core import library as library_mod
        mat_id = self.library._assets[0].mat_id
        for starred in (False, True):
            with self.subTest(starred=starred), \
                    patch.object(library_mod.locations, "is_favourite",
                                 return_value=starred), \
                    patch.object(library_mod.locations, "set_favourites") as wrote:
                self.library.toggle_fav(0)
            wrote.assert_called_once_with(self.mock_prefs, {mat_id: not starred})

    def test_toggle_fav_does_not_write_the_library(self):
        """Stated as its own assertion: a favourite toggle never touches the shared index."""
        from amaze.core import library as library_mod
        with patch.object(library_mod.locations, "is_favourite",
                          return_value=False), \
                patch.object(library_mod.locations, "set_favourites"), \
                patch.object(self.library, "save") as mock_save:
            self.library.toggle_fav(0)
        mock_save.assert_not_called()

    def test_set_assetdata_multiple_values_placeholder(self):
        """Test set_assetdata preserves existing data when Multiple Values placeholder used"""
        index = self.library.index(0, 0)
        original_name = self.library._assets[0].name

        self.library.set_assetdata(index, "Multiple Values...", "cat1", "tag1", False)

        call_args = self.mock_material.set_data.call_args  # the name is preserved rather than overwritten with the placeholder
        self.assertEqual(original_name, call_args[0][0])

    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    def test_remove_asset(self, mock_remove, mock_exists):
        """Test remove_asset deletes files and removes from library"""
        index = self.library.index(0, 0)
        initial_count = self.library.rowCount()

        mat_id = self.library._assets[0].mat_id
        expected = set(self.library.asset_files(mat_id).values())

        self.library.remove_asset(index)

        removed = {call.args[0] for call in mock_remove.call_args_list}  # every file the asset owns, from `asset_files()` rather than a count
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

        renderer = material_actions.add_asset(self.library, mock_node, "metal", "test", False)

        self.assertEqual(renderer, "karma")
        mock_handler.save_node.assert_called_once()

    def test_add_asset_records_the_name_it_was_given(self):
        """The dialog names a single material; a multi-selection passes none and keeps node names."""
        mock_node = Mock()
        mock_node.name.return_value = "NodeName"

        mock_handler = Mock()
        mock_handler.get_renderer_from_node.return_value = "karma"
        mock_handler.save_node.return_value = True
        self.mock_nodes_cls.return_value = mock_handler

        new_mat = Mock()
        new_mat.mat_id = "mat_named"
        self.mock_material_cls.return_value = new_mat

        material_actions.add_asset(self.library, mock_node, "metal", "", False, name="Chosen")
        self.assertEqual(
            "Chosen", new_mat.set_data.call_args[0][0],
            "the name the dialog collected was dropped, so a renamed "
            "save comes back named after its node")

        material_actions.add_asset(self.library, mock_node, "metal", "", False)
        self.assertEqual(
            "NodeName", new_mat.set_data.call_args[0][0],
            "a save that names nothing no longer falls back to the node")

    def test_add_asset_says_no_when_the_save_did_not_happen(self):
        """Every `add_asset` answers a renderer name only when saved, an empty string when not."""
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
        renderer = material_actions.add_asset(self.library, mock_node, "metal", "x", False)

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

    def test_render_thumbnail(self):
        """render_thumbnail hands that one asset to the renderer, as a batch of one."""
        index = self.library.index(0, 0)
        material_actions.render_thumbnail(self.library, index.row())

        self.mock_thumbs_cls.render_assets.assert_called_once_with(
            self.library.preferences, [self.mock_material])

    def test_import_asset_to_scene(self):
        """Test import_asset_to_scene imports asset to Houdini"""
        mock_importer = Mock()
        mock_importer.import_asset_to_scene.return_value = (True, "", [])    # the seam's shape
        self.mock_nodes_cls.return_value = mock_importer

        index = self.library.index(0, 0)
        material_actions.import_asset_to_scene(self.library, index)

        mock_importer.import_asset_to_scene.assert_called_once_with(
            self.mock_material, "auto", context_node=None
        )


def _without_the_legacy_row(prefs) -> None:
    """The fixture's odd row with no files taken out, so a check starts from a healthy library."""
    index = os.path.join(prefs.dir, "library.json")
    with open(index, encoding="utf-8-sig") as handle:
        document = json.load(handle)
    document["assets"] = [row for row in document["assets"] if str(row.get("id")) != "-1"]
    with open(index, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=4)


class CheckLibraryMovesAndNeverDeletesTest(unittest.TestCase):
    """Check Library on a real library: moves what no list holds, keeps every listed row."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = self.prefs.dir
        self.mat_dir = os.path.join(self.dir, self.prefs.asset_dir)
        self.img_dir = os.path.join(self.dir, self.prefs.img_dir)
        self.index = os.path.join(self.dir, "library.json")
        _without_the_legacy_row(self.prefs)
        with open(self.index, encoding="utf-8-sig") as handle:
            self.first_id = str(json.load(handle)["assets"][0]["id"])

    def _survey(self):
        from amaze.core import repair
        return repair.survey(self.dir, self.prefs.asset_dir, self.prefs.img_dir)

    def _write(self, path, text="x"):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_unlisted_files_go_to_a_holding_folder_outside_the_library(self):
        """A move aside that is wrong is undone from the holding folder; an unlink is not."""
        from amaze.core import quarantine, repair
        stray = [self._write(os.path.join(self.mat_dir, "orphan.mat")),
                 self._write(os.path.join(self.img_dir, "orphan.png"))]
        findings = self._survey()
        self.assertTrue(findings["complete"], "premise: every list reads")
        self.assertIn("orphan.mat", findings["unaccounted"][self.prefs.asset_dir])
        with patch("os.remove") as removed, patch("os.unlink") as unlinked:
            result = repair.move_aside(findings, "unlisted")
        self.assertFalse(removed.called or unlinked.called,
                         "a move aside unlinked a file, and a wrong one is unrecoverable")
        self.assertIn("orphan.mat", result["moved"])
        self.assertIn("orphan.png", result["moved"])
        for path in stray:
            self.assertFalse(os.path.exists(path), path)
        root = quarantine.quarantine_folder(self.dir)
        self.assertIn(quarantine.QUARANTINE_PREFIX, root)
        self.assertTrue(os.path.isfile(os.path.join(root, self.prefs.asset_dir, "orphan.mat")))
        self.assertFalse(os.path.realpath(root).startswith(os.path.realpath(self.dir)),
                         "the holding folder is inside the library, so it would sync")

    def test_a_half_synced_asset_keeps_its_row_and_its_surviving_file(self):
        """A file still syncing looks like one that is gone, so the row and its other half stay."""
        from amaze.core import repair
        os.remove(os.path.join(self.mat_dir, self.first_id + ".mat"))
        with open(self.index, encoding="utf-8-sig") as handle:
            rows_before = json.load(handle)["assets"]
        findings = self._survey()
        self.assertIn(self.first_id,
                      [one for one, _name in findings["missing_files"]["library.json"]])
        self.assertIn("files are missing", "\n".join(repair.report_lines(findings)),
                      "the row survives and nobody is told its file is missing")
        if findings["complete"]:
            repair.move_aside(findings, ("unlisted", "leftovers"))
        with open(self.index, encoding="utf-8-sig") as handle:
            self.assertEqual(rows_before, json.load(handle)["assets"],
                             "a row was dropped on one missing file")
        self.assertTrue(os.path.exists(os.path.join(self.mat_dir, self.first_id + ".interface")),
                        "the surviving half of a half-synced asset was moved")

    def test_an_unreadable_asset_folder_holds_everything_back(self):
        """A folder still syncing would read as every asset missing, so it is not all clear."""
        from amaze.core import repair
        shutil.rmtree(self.mat_dir)
        with open(self.index, "rb") as handle:
            before = handle.read()
        findings = self._survey()
        self.assertEqual([self.prefs.asset_dir], findings["unreadable_folders"])
        self.assertFalse(findings["complete"])
        self.assertEqual(len(findings["leftovers"]), repair.files_to_move_aside(findings))
        with self.assertRaises(ValueError):
            repair.move_aside(findings, "unlisted")
        self.assertIn("could not look inside", "\n".join(repair.report_lines(findings)))
        with open(self.index, "rb") as handle:
            self.assertEqual(before, handle.read(), "the list changed while a folder was unread")


class TheLibraryKeepsNoTagList(unittest.TestCase):
    """Tags live on each asset; the library-wide list was read by nothing, so no file keeps one."""

    @staticmethod
    def _read(path):
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    @staticmethod
    def _write(path, document):
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)

    def test_a_loaded_list_is_gone_after_the_next_save(self):
        from amaze.core import database
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        folder = test_support.fresh_library(self)
        path = os.path.join(folder, "library.json")
        document = self._read(path)
        document["tags"] = ["old", "list"]
        self._write(path, document)
        db = database.DatabaseConnector("library.json")
        db.load(folder)
        self.assertNotIn("tags", db._data)
        self.assertTrue(db.save())
        self.assertNotIn("tags", self._read(path))

    def test_a_peer_list_is_not_adopted(self):
        panel = test_support.fixture_panel(self)
        model = panel.material_model
        path = os.path.join(panel.prefs.dir, "library.json")
        self.assertTrue(model.save(), "premise: the first save")
        document = self._read(path)
        document["tags"] = ["from", "an", "older", "build"]
        self._write(path, document)
        self.assertTrue(model.save())
        self.assertNotIn("tags", self._read(path))

    def test_new_tags_stay_on_the_asset_and_nowhere_else(self):
        panel = test_support.fixture_panel(self)
        model = panel.material_model
        path = os.path.join(panel.prefs.dir, "library.json")
        index = model.index(1, 0)
        asset_id = str(model.assets[1].mat_id)
        model.set_assetdata(index, model.assets[1].name, "", "freshtag", None)
        document = self._read(path)
        self.assertNotIn("tags", document)
        row = next(r for r in document["assets"] if str(r.get("id")) == asset_id)
        self.assertIn("freshtag", row.get("tags") or [])


class TheSentinelHasOneHome(unittest.TestCase):
    """The mixed-selection sentinel is compared against: one `material.MULTIPLE_VALUES`, imported."""

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
    """A multi-selection edit leaves each field showing the sentinel alone; others apply to all."""

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
    """One asset, one category, in the source and not only the data; tags are the many-to-many."""

    @staticmethod
    def _asset():
        from amaze.core.material import Material
        return Material()

    def test_any_spelling_keeps_only_the_first_category(self):
        """A string is one name, its commas included; a list keeps its first."""
        for given, kept in (("Metal, Rough, Worn", ["Metal, Rough, Worn"]),
                            (["Metal", "Rough"], ["Metal"]),
                            ("  rs material ", ["rs material"]), ("", [])):
            with self.subTest(given=given):
                asset = self._asset()
                asset.categories = given
                self.assertEqual(kept, asset.categories)

    def test_set_data_cannot_smuggle_a_second_one_in(self):
        """set_data is the path every save and every edit goes through."""
        for given, kept in (("Wood, Oak", ["Wood, Oak"]), (["Metal", "Rough"], ["Metal"])):
            with self.subTest(given=given):
                asset = self._asset()
                asset.set_data("n", given, "", False, "Karma")
                self.assertEqual(kept, asset.categories)


class ACommaInsideOneCategoryNameStaysWholeTest(unittest.TestCase):
    """The rename dialog keeps a comma in a name; a door moving an asset INTO it hands over a list."""

    NAME = "Wood, Oak"

    def setUp(self):
        from amaze.core import library as library_mod
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.asset = next(a for a in self.model.assets if a.name == "Metal")

    def test_customize_moves_the_asset_into_the_whole_name(self):
        row = self.model.find_asset_row_by_id(self.asset.mat_id)
        self.assertTrue(self.model.set_tile_category(row, self.NAME))
        self.assertEqual([self.NAME], self.asset.categories,
                         "Customize split the category name at its comma")

    def test_check_library_leaves_the_whole_name_on_the_asset(self):
        from amaze.core import repair
        index = os.path.join(self.prefs.dir, "library.json")
        with open(index, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        row = next(one for one in document["assets"] if str(one.get("id")) == self.asset.mat_id)
        row["categories"] = [self.NAME]
        with open(index, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)
        test_support.reset_database_singletons()    # an action refuses a library this process holds
        findings = repair.survey(self.prefs.dir, self.prefs.asset_dir, self.prefs.img_dir)
        self.assertNotIn(self.asset.mat_id,
                         [one for one, _name in findings["uncategorised"]["library.json"]],
                         "a name holding a comma was read as no category")
        repair.rescue_uncategorised(findings)
        with open(index, encoding="utf-8-sig") as handle:
            after = next(one for one in json.load(handle)["assets"]
                         if str(one.get("id")) == self.asset.mat_id)
        self.assertEqual([self.NAME], after["categories"],
                         "Check Library split the category name at its comma")

    def test_assigning_the_whole_name_keeps_it_whole(self):
        """The sidebar drop and the info edit both write through set_assetdata."""
        row = self.model.find_asset_row_by_id(self.asset.mat_id)
        self.model.set_assetdata(self.model.index(row, 0), self.asset.name, self.NAME,
                                 "", None, save=False)
        self.assertEqual([self.NAME], self.asset.categories,
                         "assigning the category split its name at the comma")

    def test_an_edit_leaving_multiple_values_keeps_the_name(self):
        """A multi-selection edit that leaves Category alone hands back each asset's own."""
        from amaze.core import material
        self.asset.categories = [self.NAME]
        row = self.model.find_asset_row_by_id(self.asset.mat_id)
        self.model.set_assetdata(self.model.index(row, 0), self.asset.name,
                                 material.MULTIPLE_VALUES, "", None, save=False)
        self.assertEqual([self.NAME], self.asset.categories,
                         "an edit that left Category alone split the name at its comma")


class AnInlineSectionHasNoFilesToMissTest(unittest.TestCase):
    """Code and Colors keep their content IN their list: no row of theirs has files to miss."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        _without_the_legacy_row(self.prefs)

    def _rows(self, filename):
        with open(os.path.join(self.prefs.dir, filename), encoding="utf-8-sig") as handle:
            return json.load(handle)["assets"]

    def _checked(self, model):
        from amaze.core import database, repair
        filename = model.DB_FILENAME
        before = self._rows(filename)
        self.assertTrue(before, "premise: the list holds nothing to keep")
        test_support.reset_database_singletons()    # an action refuses a library this process holds
        findings = repair.survey(self.prefs.dir, self.prefs.asset_dir, self.prefs.img_dir)
        self.assertEqual(set(database.ASSET_FILE_OWNERS), set(findings["missing_files"]),
                         "an inline list was checked for files it never has")
        self.assertNotIn(filename, findings["missing_renders"])
        self.assertEqual([], [line for line in repair.report_lines(findings)
                              if "missing" in line],
                         "Check Library reported inline content as files that are missing")
        if findings["complete"]:
            repair.move_aside(findings, ("unlisted", "leftovers"))
        self.assertEqual(before, self._rows(filename), "Check Library changed the list's rows")

    def test_check_library_keeps_every_snippet(self):
        from amaze.core import code_library
        model = code_library.CodeLibrary(preferences=self.prefs)
        self.assertTrue(model.add_snippet("int x = 1;", "One", "VEX", "Mine", ""))
        self._checked(model)

    def test_check_library_keeps_every_palette(self):
        from amaze.core import gradient_library
        model = gradient_library.GradientLibrary(preferences=self.prefs)
        model.add_user_gradient("Two", "Mine", {"keys": [0.0], "values": [[1, 0, 0]],
                                                "bases": ["Constant"]})
        self._checked(model)


class ReloadChainTest(unittest.TestCase):
    """Every amaze module the panel imports is in its reload chain. ▸p/source-derived-tests"""

    def test_every_imported_amaze_module_is_reloaded(self):
        import re

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()

        reloaded = set(re.findall(
            r"(?:importlib\.reload|_reload)\((\w+)\)", source))
        reloaded |= set(re.findall(r"(\w+)\.reload_engine\(\)", source))  # a package reloads through its own entry point ▸r/package-reload
        imported = set()
        for match in re.finditer(  # parenthesised imports span lines, so the pattern must cross newlines
                r"^from amaze[\w.]* import \(([^)]*)\)", source, re.M | re.S):
            for name in match.group(1).split(","):
                name = name.split(" as ")[-1].strip()    # `x as y` binds y, the name the chain reloads
                if name and name.isidentifier():
                    imported.add(name)
        for match in re.finditer(
                r"^from amaze[\w.]* import ([^(\n]+)$", source, re.M):
            for name in match.group(1).split(","):
                name = name.split(" as ")[-1].strip()
                if name and name.isidentifier():
                    imported.add(name)

        self.assertEqual(
            set(), imported - reloaded,
            "panel.py imports these without reloading them; a stale one "
            "keeps old code while its callers get new")


class ModelSignalTest(unittest.TestCase):
    """Row inserts and removals fire their own signals, not `layoutChanged`. ▸r/model-contracts"""

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
        """A displayed name with its leading underscore stripped must not raise out of the slot."""
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
    """A save never stamps a newer build's database with an older schema version."""

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


class OpeningALibraryComposesOnePathPerAssetTest(unittest.TestCase):
    """Loading stats each asset's `.mat` and composes no other path. ▸r/pane-open-cost"""

    def test_a_load_composes_one_contained_path_per_asset(self):
        from amaze.core import library as library_mod
        from amaze.helpers import hostos
        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        with patch.object(hostos, "contained_join", wraps=hostos.contained_join) as spy:
            model = library_mod.MaterialLibrary(preferences=prefs)
        self.assertTrue(model.assets, "premise: the fixture has assets")
        self.assertLessEqual(
            spy.call_count, len(model.assets) + 4,
            "opening composed %d contained paths for %d assets, where the stale-write "
            "baseline needs one each" % (spy.call_count, len(model.assets)))


class ARetiredFieldDoesNotComeBackOnASaveTest(unittest.TestCase):
    """Stamped at the current schema so no migration strips the retired keys before `_KNOWN_KEYS`."""

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
    """A star goes to the library store per user; `material_favorites` is a migration source only."""

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

        model.toggle_fav(index.row())
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
        model.toggle_fav(index.row())
        self.assertFalse(
            model.data(index, model.FavoriteRole),
            "a machine with nobody picked lit a star - the store filed "
            "it under a blank tag, which is an ABSENT user, not a "
            "shared one")


class MaterialRoundTripTest(unittest.TestCase):
    """The dict round-trip keeps unknown keys and survives a missing one."""

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

    def test_a_record_built_in_code_carries_an_empty_extra(self):
        """A new record, not read from a row, has `_extra` too, so no reader needs a default."""
        asset = self._material()()
        self.assertEqual({}, asset._extra)
        asset._extra["source"] = "PolyHaven"
        self.assertEqual("PolyHaven", asset.get_as_dict().get("source"))

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
        """`_KNOWN_KEYS` is what `get_as_dict` emits plus the retired keys, which are dropped."""
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
    """A sibling file changed underneath and unparseable survives our saves, with a copy kept."""

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
        """Refusing once is not enough: the next save would overwrite what the first preserved."""
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
    """Rows and top-level keys another machine wrote survive the merge and every later save."""

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
        self.model.toggle_fav(0)
        self.assertEqual(
            {"keep": "me"},
            self._disk().get("something_a_newer_build_wrote"),
            "an unrecognised top-level key was dropped on save")

    def test_a_sparse_adopted_row_is_kept_not_dropped(self):
        """A row carrying only an id is adopted: `from_dict` fills defaults rather than raising."""
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
            self.model.toggle_fav(0)
        except Exception as exc:                       # noqa: BLE001
            self.fail("a malformed adopted row aborted the save: %s" % exc)


class CheckLibraryRefusesOnIncompleteKnowledgeTest(unittest.TestCase):
    """Materials and Nodes share mat/ and img/, so every list's ids decide what no list holds."""

    def setUp(self):
        from amaze.tests import test_support

        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _write_sibling(self, name, text):
        path = os.path.join(self.prefs.dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def _survey(self):
        from amaze.core import repair
        return repair.survey(self.prefs.dir, self.prefs.asset_dir, self.prefs.img_dir)

    def _entry(self, findings, filename):
        return next(entry for entry in findings["lists"] if entry["filename"] == filename)

    def test_an_unreadable_sibling_is_reported_not_skipped(self):
        from amaze.core import repair
        self._write_sibling("cops.json", '{"assets": [{"id": "COPASSET1"}')
        self._write_sibling(os.path.join(self.prefs.asset_dir, "COPASSET1.mat"), "x")
        findings = self._survey()
        self.assertEqual("unreadable", self._entry(findings, "cops.json")["state"])
        self.assertFalse(findings["complete"],
                         "an unreadable sibling was skipped, so its files look unlisted")
        self.assertEqual(len(findings["leftovers"]), repair.files_to_move_aside(findings))
        with self.assertRaises(ValueError):
            repair.move_aside(findings, "unlisted")
        self.assertIn("Node: the list is there and Amaze cannot read it. It has not been changed.",
                      repair.report_lines(findings))

    def test_a_readable_sibling_contributes_its_ids(self):
        self._write_sibling("cops.json", '{"assets": [{"id": "COPASSET1"}]}')
        self._write_sibling(os.path.join(self.prefs.asset_dir, "COPASSET1.mat"), "x")
        findings = self._survey()
        self.assertIn("COPASSET1", findings["ids"],
                      "a sibling's ids did not reach the unlisted check")
        self.assertNotIn("COPASSET1.mat", findings["unaccounted"][self.prefs.asset_dir])

    def test_an_absent_sibling_is_not_an_error(self):
        """Absent owns nothing; only present-but-unparseable is unsafe."""
        path = os.path.join(self.prefs.dir, "cops.json")
        if os.path.exists(path):
            os.remove(path)
        findings = self._survey()
        self.assertEqual("absent", self._entry(findings, "cops.json")["state"])
        self.assertTrue(findings["complete"])


def _empty_library_dir(testcase) -> str:
    """A valid assetless library, auto-removed; a missing library.json would make the switch raise."""
    import json
    import shutil
    import tempfile

    tmp = tempfile.mkdtemp(prefix="amaze_empty_lib_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    with open(os.path.join(tmp, "library.json"), "w", encoding="utf-8") as handle:
        json.dump({"categories": ["_All"], "tags": [], "assets": []}, handle)
    return tmp + os.sep


class LibrarySwitchTest(unittest.TestCase):
    """A library switch resets the model, or a proxy keeps stale rows and segfaults. ▸r/model-contracts"""

    def setUp(self):
        from amaze.core import library as library_mod
        from amaze.tests import test_support

        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)

        self.proxy = QtCore.QSortFilterProxyModel()  # a proxy and a selection model make a missing reset fatal, as in the panel
        self.proxy.setSourceModel(self.model)
        self.selection = QtCore.QItemSelectionModel(self.proxy)

    def _switch_to_an_empty_library(self):
        """Point the model's Prefs at a library with no assets and switch."""
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
        """A failed switch still ends the reset, asserted on the signal pair. ▸r/model-contracts"""
        from unittest.mock import patch

        began, ended = [], []
        self.model.modelAboutToBeReset.connect(lambda: began.append(1))
        self.model.modelReset.connect(lambda: ended.append(1))

        from amaze.core import database
        with patch.object(database, "load_survivable",    # fail INSIDE the reset window, at the read
                          side_effect=OSError("library unreadable")):
            with self.assertRaises(OSError):
                self.model.switch_model_data()

        self.assertEqual(1, len(began), "the switch never began a reset")
        self.assertEqual(
            len(began), len(ended),
            "switch_model_data raised and left the model mid-reset - "
            "endResetModel must be in a finally")

    def test_a_switch_drops_the_content_labels_once(self):
        """The USD and shader-type labels read from the files go on a switch, in one drop."""
        from unittest.mock import patch

        self.model._usd_cache = {"stale": True}
        self.model._shader_type_cache = {"stale": "PBR"}
        real = self.model._drop_content_label_caches
        with patch.object(self.model, "_drop_content_label_caches",
                          wraps=real) as dropped:
            self._switch_to_an_empty_library()
        self.assertEqual(({}, {}), (self.model._usd_cache,
                                    self.model._shader_type_cache))
        self.assertEqual(1, dropped.call_count,
                         "a library switch drops the content labels twice")


class GradientSwitchTest(unittest.TestCase):
    """Colors resets on a switch, and `db.serves()` refuses a save aimed at another library."""

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
        """An unswitched model must not write its colours into another library: `db.serves()`."""
        model = self._model()
        from amaze.core import database
        connector = database.DatabaseConnector(model.DB_FILENAME)
        self.assertTrue(connector.serves(self.prefs.dir),
                        "premise: the connector serves this library")

        self.prefs.dir = _empty_library_dir(self)  # move the library under the model without switching it
        self.assertFalse(
            model.save(),
            "the gradient model saved colours from library A into "
            "library B - nothing refused the write")


class TheColorsSidebarFollowsTheLibraryTest(unittest.TestCase):
    """The Colors sidebar names the new library's categories after a switch, not the old ones."""

    RAMP = {"values": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]}  # a two-key ramp, the shape add_user_gradient reads

    def _library_with_category(self, prefs, name):
        """A library with one user palette in category `name`, written by `add_user_gradient`."""
        from amaze.core import gradient_library

        folder = _empty_library_dir(self)
        prefs.dir = folder
        prefs.save()
        writer = gradient_library.GradientLibrary(preferences=prefs)
        writer.add_user_gradient("P " + name, name, self.RAMP)
        gradient_library.GradientCategories(
            preferences=prefs).check_add_category(name)
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
    """Every library-backed model class answers `switch_model_data`; the list is `test_area_bindings`."""

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
    """Every section keeps favourites per user, never on the shared record."""

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
        model.toggle_fav(0)
        with open(index_path, "rb") as fh:
            after = fh.read()
        self.assertEqual(before, after,
                         "a favourite toggle wrote the shared index - "
                         "my star still collides with yours")
        self.assertTrue(model.data(model.index(0, 0), model.FavoriteRole))


class TheSharedBaseCarriesNothingRendererShaped(unittest.TestCase):
    """`AssetLibrary` is shared; `MaterialLibrary` holds a material's labels, the actions its verbs."""

    RENDERER_SHAPED = (  # checked with `vars()`, since inheritance answers `getattr` for every subclass
        "is_usd_material", "shader_type_label",
    )
    MATERIAL_VERBS = ("add_asset", "update_asset_content", "import_asset_to_scene",
                      "convert", "render_thumbnails")    # actions/materials.py's, on no model
    RENDER_VERBS = ("render_thumbnail", "render_thumbnails")    # Update Render's, on no model at all

    def test_the_verbs_are_the_actions_not_the_models(self):
        from amaze.core import code_library, cop_library, gradient_library, library
        for name in self.MATERIAL_VERBS:
            self.assertIn(name, vars(material_actions), "%s is not a Material verb" % name)
            self.assertNotIn(name, vars(library.MaterialLibrary),
                             "%s came back onto the Material model" % name)
        for name in self.RENDER_VERBS:
            self.assertIn(name, vars(material_actions), "%s is not a Material verb" % name)
            for model in (library.AssetLibrary, cop_library.CopLibrary,
                          code_library.CodeLibrary, gradient_library.GradientLibrary):
                self.assertNotIn(name, vars(model),
                                 "%s is on %s, where no menu reaches it" % (name, model.__name__))

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


class EveryAssetModelIsGivenItsLibrary(unittest.TestCase):
    """Every asset model takes `preferences` first, with no default. ▸p/duplication-third-verb"""

    MODELS = (  # the AssetLibrary and Categories family only ▸r/model-parent
        ("Categories", "amaze.core.category"),
        ("AssetLibrary", "amaze.core.library"),
        ("MaterialLibrary", "amaze.core.library"),
        ("GradientLibrary", "amaze.core.gradient_library"),
        ("GradientCategories", "amaze.core.gradient_library"),
        ("CodeLibrary", "amaze.core.code_library"),
        ("CodeCategories", "amaze.core.code_library"),
        ("CopLibrary", "amaze.core.cop_library"),
        ("CopCategories", "amaze.core.cop_library"),
    )

    def test_preferences_is_first_and_has_no_default(self):
        """Read off the signature, since constructing needs each model's whole fixture."""
        import importlib
        import inspect

        wrong = {}
        for name, module in self.MODELS:
            model = getattr(importlib.import_module(module), name)
            found = list(inspect.signature(model).parameters.values())
            if not found or found[0].name != "preferences":
                wrong[name] = ("takes %r first"
                               % ([p.name for p in found] or None))
            elif found[0].default is not inspect.Parameter.empty:
                wrong[name] = "preferences defaults to %r" % (found[0].default,)

        self.assertEqual(
            {}, wrong,
            "these models can be built without being told which library "
            "they are for, so they would read the machine's own: %s" % wrong)


class RendererDetectionSeesNestedSubnetsTest(unittest.TestCase):
    """A Karma builder's mtlx nodes may sit any number of subnets down (help `vop/subnet`)."""

    def test_mtlx_inside_a_nested_subnet_reads_as_karma(self):
        from amaze.render import nodes as nodes_mod
        outer = hou.node("/mat").createNode("subnet")
        self.addCleanup(outer.destroy)
        inner = outer.createNode("subnet")
        inner.createNode("mtlxstandard_surface")
        handler = nodes_mod.NodeHandler(Mock())
        self.assertEqual("Karma", handler.get_renderer_from_node(outer))


class NoTagsIsAnEmptyListTest(unittest.TestCase):
    """No tags is `[]` on disk at every door: the add, and the row read back. ▸p/no-tags-is-empty"""

    def _saved_tags(self, prefs, name: str) -> list:
        with open(os.path.join(prefs.dir, "library.json"),
                  encoding="utf-8") as handle:
            rows = json.load(handle)["assets"]
        return [row["tags"] for row in rows if row.get("name") == name]

    def test_a_material_added_with_no_tags_saves_an_empty_list(self):
        """Added with blank Tags, saved, read back by a fresh model and saved again untouched."""
        from amaze.core import library as library_mod
        from amaze.tests import make_library_fixture

        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here
        test_support.reset_database_singletons()
        prefs = test_support.fixture_prefs(self)
        prefs.render_on_import = 0
        model = library_mod.MaterialLibrary(preferences=prefs)
        builder = make_library_fixture.build_material(
            hou.node("/mat"), "Untagged", (0.5, 0.5, 0.5))
        self.addCleanup(builder.destroy)
        self.assertTrue(
            material_actions.add_asset(model, builder, "Karma_Mats", "", False, name="Untagged"),
            "premise: the save went through")
        self.assertEqual([[]], self._saved_tags(prefs, "Untagged"))

        test_support.reset_database_singletons()    # a fresh read off disk, not the connector's cached document
        reopened = library_mod.MaterialLibrary(preferences=prefs)
        self.assertTrue(reopened.save(),
                        "premise: the second save went through")
        self.assertEqual(
            [[]], self._saved_tags(prefs, "Untagged"),
            "a row saved with no tags came back from disk carrying a "
            "blank one")

    def test_a_row_read_back_with_no_tags_holds_an_empty_list(self):
        """`[]` off disk is falsy, and the constructor's sentinel must not replace it."""
        from amaze.core.material import Material
        self.assertEqual(
            [], Material.from_dict({"id": "x", "tags": []}).tags,
            "a row with no tags was read back with a blank one")
        self.assertEqual(
            [], Material().tags, "a bare record starts with a blank tag")


class TheContentGuardReadsOneFingerprint(unittest.TestCase):

    def test_the_content_stat_is_the_disk_state_of_the_mat(self):
        """`_content_stat` answers `hostos.disk_state` of the .mat, None with no .mat or a bad id."""
        from amaze.core import library as library_mod
        from amaze.helpers import hostos

        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        prefs = test_support.fixture_prefs(self)
        model = library_mod.MaterialLibrary(preferences=prefs)
        mat = next(model.asset_files(a.mat_id)["mat"] for a in model.assets
                   if os.path.exists(model.asset_files(a.mat_id)["mat"]))
        mat_id = os.path.basename(mat)[:-len(prefs.ext)]
        self.assertEqual(
            (hostos.disk_state(mat), None, None),
            (model._content_stat(mat_id), model._content_stat("absent-id"),
             model._content_stat("../../../Documents/x")),
            "the content guard's stat drifted from the one fingerprint")


if __name__ == "__main__":
    unittest.main()
