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
from amaze.core import library_files, material  # noqa: E402

MATERIALS_KEY = library_files.SECTION_FOLDERS[library_files.MATERIALS] + "/"    # "materials/"


class TestMaterialLibrary(unittest.TestCase):
    """Test suite for MaterialLibrary class"""

    def setUp(self):
        """Set up test fixtures and mocks; the patches stop even when setUp fails part way."""
        self.addCleanup(patch.stopall)
        self.prefs_patcher = patch("amaze.core.library.prefs.Prefs")
        self.material_patcher = patch("amaze.core.library.material.Material")
        self.thumbs_patcher = patch("amaze.render.thumbs.ThumbNailRenderer")
        self.nodes_patcher = patch("amaze.actions.materials.nodes.NodeHandler")
        self.qimage_patcher = patch("PySide6.QtGui.QImage")

        self.mock_prefs_cls = self.prefs_patcher.start()
        self.mock_material_cls = self.material_patcher.start()
        self.mock_thumbs_cls = self.thumbs_patcher.start()
        self.mock_nodes_cls = self.nodes_patcher.start()
        self.mock_hou = Mock()
        self.mock_qimage_cls = self.qimage_patcher.start()

        self.mock_prefs = Mock()
        self._library_dir = tempfile.mkdtemp(prefix="amaze_testlib_own_")  # a real folder with a real materials.json; only .dir is real
        self.addCleanup(shutil.rmtree, self._library_dir, True)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.mock_prefs.dir = self._library_dir + os.sep
        self.mock_prefs.library_user = test_support.FIXTURE_USER
        self.mock_prefs.img_dir = os.path.join(self._library_dir, "img", "")    # absolute, inside temp
        self.mock_prefs.ext = ".mat"
        self.mock_prefs.img_ext = ".png"
        self.mock_prefs.render_on_import = False
        self.mock_prefs_cls.return_value = self.mock_prefs

        self.asset_data = {
            "id": "mat_001",
            "name": "TestMaterial",
            "categories": ["metal", "rough"],
            "tags": ["test", "sample"],
            "renderer": "karma",
            "date": "2026-02-08",
        }
        with open(os.path.join(self._library_dir, library_files.MATERIALS), "w",
                  encoding="utf-8") as handle:
            json.dump({"assets": {"mat_001": self.asset_data}}, handle)

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
        """Decoration returns None until the thumbnail is ready; the delegate paints a dark tile."""
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
        """The role returns `locations.is_favourite`, keyed by asset id: never the shared record."""
        from amaze.core import library as library_mod
        index = self.library.index(0, 0)
        mat_id = self.library._assets[0].mat_id
        with patch.object(library_mod.locations, "is_favourite",
                          return_value=False) as asked:
            self.assertFalse(
                self.library.data(index, self.library.FavoriteRole))
        asked.assert_called_once_with(self.mock_prefs, mat_id, library_files.MATERIALS)
        with patch.object(library_mod.locations, "is_favourite",
                          return_value=True):
            self.assertTrue(self.library.data(index,
                                              self.library.FavoriteRole))

    def test_sanitize_tags_trims_and_drops_duplicates(self):
        tags = set(self.library.sanitize_tags("tag1, tag2 , tag1, tag3").split(","))
        self.assertEqual({"tag1", "tag2", "tag3"}, tags)
        self.assertEqual("", self.library.sanitize_tags(""))

    def test_a_toggle_flips_the_star_through_set_favourites(self):
        """Keyed by the asset's id in the library store, so two users' stars cannot collide."""
        from amaze.core import library as library_mod
        mat_id = self.library._assets[0].mat_id
        for starred in (False, True):
            with self.subTest(starred=starred), \
                    patch.object(library_mod.locations, "is_favourite",
                                 return_value=starred), \
                    patch.object(library_mod.locations, "set_favourites") as wrote:
                self.library.toggle_fav(0)
            wrote.assert_called_once_with(self.mock_prefs, {mat_id: not starred},
                                          library_files.MATERIALS)

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

    def test_remove_asset(self):
        """Every file the asset owns moves to the library's trash with its row, and nothing else."""
        index = self.library.index(0, 0)
        initial_count = self.library.rowCount()
        mat_id = self.library._assets[0].mat_id
        owned = sorted(self.library.asset_files(mat_id).values())
        for path in owned:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"x")
        bystander = os.path.join(os.path.dirname(owned[0]), "OTHER.mat")
        with open(bystander, "wb") as handle:
            handle.write(b"x")

        self.library.remove_asset(index)

        self.assertEqual([], [path for path in owned if os.path.exists(path)],
                         "remove_asset left files the asset owns")
        self.assertTrue(os.path.exists(bystander), "remove_asset removed another asset's file")
        trash = os.path.join(self._library_dir, "trash")
        self.assertEqual(len(owned), sum(len(files) for _r, _d, files in os.walk(trash)),
                         "the owned files were not moved to the library's trash")
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
        new_mat.get_as_dict.return_value = {"id": "mat_002", "name": "NewMaterial"}
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
        new_mat.get_as_dict.return_value = {"id": "mat_named", "name": "Chosen"}
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
        """Every `add_asset` returns a renderer name only when saved, an empty string when not."""
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
            "a failed save returned a renderer, which every "
            "caller reads as success")
        self.assertEqual(
            before, len(self.library.assets),
            "a failed save still added a row")

    def test_flags(self):
        """Test flags returns correct item flags"""
        index = self.library.index(0, 0)
        flags = self.library.flags(index)

        self.assertTrue(flags & QtCore.Qt.ItemFlag.ItemIsDragEnabled)

    def test_render_thumbnail(self):
        """render_thumbnail passes that one asset to the renderer, as a batch of one."""
        index = self.library.index(0, 0)
        material_actions.render_thumbnail(self.library, index.row())

        self.mock_thumbs_cls.render_assets.assert_called_once_with(
            self.library.preferences, [self.mock_material])

    def test_import_asset_to_scene(self):
        """Test import_asset_to_scene imports asset to Houdini"""
        mock_importer = Mock()
        mock_importer.import_asset_to_scene.return_value = (True, "", [])    # the real method's return shape
        self.mock_nodes_cls.return_value = mock_importer

        index = self.library.index(0, 0)
        material_actions.import_asset_to_scene(self.library, index)

        mock_importer.import_asset_to_scene.assert_called_once_with(
            self.mock_material, "auto", context_node=None
        )


def _without_the_legacy_row(prefs) -> None:
    """The fixture's id -1 row, which has no files, removed: checks start on a healthy library."""
    index = os.path.join(prefs.dir, library_files.MATERIALS)
    with open(index, encoding="utf-8-sig") as handle:
        document = json.load(handle)
    document["assets"].pop("-1", None)
    with open(index, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=4)


class CheckLibraryMovesAndNeverDeletesTest(unittest.TestCase):
    """Check Library on a real library: moves files no database lists, keeps every listed row."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = self.prefs.dir
        self.mat_dir = material.section_folder(self.dir, library_files.MATERIALS)
        self.img_dir = os.path.join(self.dir, self.prefs.img_dir)
        self.index = os.path.join(self.dir, library_files.MATERIALS)
        _without_the_legacy_row(self.prefs)
        with open(self.index, encoding="utf-8-sig") as handle:
            self.first_id = sorted(json.load(handle)["assets"])[0]

    def _survey(self):
        from amaze.core import repair
        return repair.survey(self.dir, self.prefs.img_dir)

    def _write(self, path, text="x"):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_unlisted_files_go_to_the_librarys_trash(self):
        """A wrong move can be undone from the trash; a deleted file cannot."""
        from amaze.core import repair
        stray = [self._write(os.path.join(self.mat_dir, "orphan.mat")),
                 self._write(os.path.join(self.mat_dir, "orphan.png"))]
        findings = self._survey()
        self.assertTrue(findings["complete"], "premise: every database is readable")
        self.assertIn("orphan.mat", findings["unaccounted"][MATERIALS_KEY])
        self.assertIn("orphan.png", findings["unaccounted"][MATERIALS_KEY])
        result = repair.move_aside(findings, "unlisted")
        self.assertIn("orphan.mat", result["moved"])
        self.assertIn("orphan.png", result["moved"])
        for path in stray:
            self.assertFalse(os.path.exists(path), path)
        import datetime
        root = os.path.join(self.dir, "trash", datetime.date.today().isoformat())
        self.assertTrue(os.path.isfile(os.path.join(root, MATERIALS_KEY, "orphan.mat")))

    def test_a_half_synced_asset_keeps_its_row_and_its_surviving_file(self):
        """A file still syncing looks like one that is gone, so the row and its other file stay."""
        from amaze.core import repair
        os.remove(os.path.join(self.mat_dir, self.first_id + ".mat"))
        with open(self.index, encoding="utf-8-sig") as handle:
            rows_before = json.load(handle)["assets"]
        findings = self._survey()
        self.assertIn(self.first_id,
                      [one for one, _name in findings["missing_files"][library_files.MATERIALS]])
        self.assertIn("files are missing", "\n".join(repair.report_lines(findings)),
                      "the row is kept and the report does not list its missing file")
        if findings["complete"]:
            repair.move_aside(findings, ("unlisted", "leftovers"))
        with open(self.index, encoding="utf-8-sig") as handle:
            self.assertEqual(rows_before, json.load(handle)["assets"],
                             "a row was dropped on one missing file")
        self.assertTrue(os.path.exists(os.path.join(self.mat_dir,
                                                    self.first_id + material.RECORD_SUFFIX)),
                        "the remaining file of a partly synced asset was moved")

    def test_an_unreadable_asset_folder_holds_everything_back(self):
        """A folder still syncing would read as every asset missing, so the survey is incomplete."""
        from amaze.core import repair
        shutil.rmtree(self.mat_dir)
        with open(self.index, "rb") as handle:
            before = handle.read()
        findings = self._survey()
        self.assertEqual([MATERIALS_KEY], findings["unreadable_folders"])
        self.assertFalse(findings["complete"])
        self.assertEqual(len(findings["leftovers"]), repair.files_to_move_aside(findings))
        with self.assertRaises(ValueError):
            repair.move_aside(findings, "unlisted")
        self.assertIn("could not look inside", "\n".join(repair.report_lines(findings)))
        with open(self.index, "rb") as handle:
            self.assertEqual(before, handle.read(), "the database changed while a folder could not be read")


class TheLibraryKeepsNoTagList(unittest.TestCase):
    """Tags are stored on each asset; nothing read the library-wide list, so no file keeps one."""

    @staticmethod
    def _read(path):
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    @staticmethod
    def _write(path, document):
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)

    def test_new_tags_stay_on_the_asset_and_nowhere_else(self):
        panel = test_support.fixture_panel(self)
        model = panel.material_model
        path = os.path.join(panel.prefs.dir, library_files.MATERIALS)
        index = model.index(1, 0)
        asset_id = str(model.assets[1].mat_id)
        model.set_assetdata(index, model.assets[1].name, "", "freshtag", None)
        test_support.settle_stamps()
        document = self._read(path)
        self.assertNotIn("tags", document)
        self.assertIn("freshtag", document["assets"][asset_id].get("tags") or [])


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
            "the sentinel is written outside core/material.py - import "
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
    """The rename dialog allows a comma in a name; code moving an asset INTO it passes a list."""

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
        index = os.path.join(self.prefs.dir, library_files.MATERIALS)
        with open(index, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        document["assets"][str(self.asset.mat_id)]["categories"] = [self.NAME]
        with open(index, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)
        test_support.reset_database_singletons()    # an action does not run on a library this process has open
        findings = repair.survey(self.prefs.dir, self.prefs.img_dir)
        self.assertNotIn(self.asset.mat_id,
                         [one for one, _name in findings["uncategorised"][library_files.MATERIALS]],
                         "a name holding a comma was read as no category")
        repair.rescue_uncategorised(findings)
        with open(index, encoding="utf-8-sig") as handle:
            after = json.load(handle)["assets"][str(self.asset.mat_id)]
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
        """A multi-selection edit that leaves Category alone keeps each asset's own."""
        from amaze.core import material
        self.asset.categories = [self.NAME]
        row = self.model.find_asset_row_by_id(self.asset.mat_id)
        self.model.set_assetdata(self.model.index(row, 0), self.asset.name,
                                 material.MULTIPLE_VALUES, "", None, save=False)
        self.assertEqual([self.NAME], self.asset.categories,
                         "an edit that left Category alone split the name at its comma")


class AnInlineSectionHasNoFilesToMissTest(unittest.TestCase):
    """Code and Colors keep their content IN their database: no row of theirs has files."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        _without_the_legacy_row(self.prefs)

    def _rows(self, filename):
        with open(os.path.join(self.prefs.dir, filename), encoding="utf-8-sig") as handle:
            return json.load(handle)["assets"]

    def _checked(self, model):
        from amaze.core import repair
        filename = model.DB_FILENAME
        test_support.reset_database_singletons()    # saved and closed: an action does not run on one held open
        before = self._rows(filename)
        self.assertTrue(before, "premise: the database has no rows to keep")
        findings = repair.survey(self.prefs.dir, self.prefs.img_dir)
        self.assertEqual({library_files.MATERIALS, library_files.NODES},
                         set(findings["missing_files"]),
                         "an inline database was checked for files it never has")
        self.assertNotIn(filename, findings["missing_renders"])
        self.assertEqual([], [line for line in repair.report_lines(findings)
                              if "missing" in line],
                         "Check Library reported inline content as files that are missing")
        if findings["complete"]:
            repair.move_aside(findings, ("unlisted", "leftovers"))
        self.assertEqual(before, self._rows(filename), "Check Library changed the database's rows")

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
        import ast
        import re

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()

        reloaded = set(re.findall(
            r"(?:importlib\.reload|_reload)\((\w+)\)", source))
        reloaded |= set(re.findall(r"(\w+)\.reload_engine\(\)", source))  # a package reloads through its own entry point ▸r/package-reload
        imported = {alias.asname or alias.name    # parsed, so a comment on the line hides no module
                    for node in ast.parse(source).body    # module level only, as the chain is
                    if isinstance(node, ast.ImportFrom)
                    and (node.module or "").startswith("amaze")
                    for alias in node.names}
        self.assertTrue(imported, "the scan found no amaze import at all, so it checks nothing")

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
            "a category was removed with no rowsRemoved signal")

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
            self.skipTest("add_asset did not add this snippet")
        self.assertEqual(
            1, len(inserted),
            "a snippet appeared with no rowsInserted signal")


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
    """A row carrying a retired key loses it at the next save: `_KNOWN_KEYS` drops it."""

    def test_neither_field_survives_the_record(self):
        row = material.Material.from_dict({"id": "R1", "name": "n", "favorite": True,
                                           "icon": {"name": "box"}}).get_as_dict()
        self.assertNotIn("favorite", row, "the retired favourite is written back to the database")
        self.assertNotIn("icon", row, "the retired icon is written back to the database")


class AMaterialStarLivesInTheLibraryStoreTest(unittest.TestCase):
    """A star goes to the materials database, in the user's own `stars` entry."""

    def setUp(self):
        from amaze.core import library as library_mod
        self.library_mod = library_mod
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

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
            "the toggle did not set the star through the store")
        test_support.settle_stamps()
        with open(os.path.join(self.prefs.dir, library_files.MATERIALS), encoding="utf-8") as fh:
            stars = json.load(fh).get("favorites", {}).get(test_support.FIXTURE_USER, {})
        self.assertTrue(
            stars.get(mat_id),
            "the star is set but the database does not hold it - "
            "the role is reading something machine-local again")
        self.assertNotIn(
            mat_id, list(getattr(self.prefs, "material_favorites", ()) or ()),
            "the toggle wrote settings.json - the star was stored per "
            "machine, so the same user's other machine cannot see it")

        # And a fresh model reading the store returns it.
        test_support.reset_database_singletons()
        again =self.library_mod.MaterialLibrary(preferences=self.prefs)
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
            "a machine with no user picked set a star - the store saved "
            "it under a blank name, which is an ABSENT user, not a "
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
        """_extra is written back, but must never override a known field."""
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
            "_KNOWN_KEYS and get_as_dict no longer match")
        self.assertFalse(
            emitted & set(Material._RETIRED_KEYS),
            "a retired key is still being written, so the schema step "
            "that strips it is undone by the next save")


class UnreadableSiblingIsNotOverwrittenTest(unittest.TestCase):
    """A database file changed elsewhere and unparseable is not overwritten; a copy is kept."""

    def setUp(self):
        from amaze.core import library as library_mod, library_db
        self.library_db = library_db
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.db_path = os.path.join(self.prefs.dir, library_files.MATERIALS)

    def _save(self):
        """One change of ours, saved."""
        held = self.library_db.document(self.prefs, library_files.MATERIALS)
        held.edit("assets", str(self.model.assets[0].mat_id), name="ours %d" % id(held))
        return self.library_db.save(self.prefs, library_files.MATERIALS)

    def _their_file_changed_and_is_unparseable(self):
        with open(self.db_path, "w", encoding="utf-8") as handle:
            handle.write('{"assets": {"THEIRS": ')   # truncated

    def _text(self):
        with open(self.db_path, encoding="utf-8") as handle:
            return handle.read()

    def test_their_unparseable_file_is_not_overwritten(self):
        self._their_file_changed_and_is_unparseable()
        before = self._text()
        self._save()
        self.assertEqual(before, self._text(),
                         "we overwrote a database we could not read - another session's work")

    def test_a_copy_of_their_file_is_kept(self):
        self._their_file_changed_and_is_unparseable()
        self._save()
        kept = [name for name in os.listdir(os.path.join(self.prefs.dir, "backup"))
                if name.startswith(library_files.MATERIALS + ".unreadable-")]
        self.assertTrue(kept, "no copy was kept, so there is nothing to recover from")

    def test_the_refusal_holds_for_the_REST_of_the_session(self):
        """Skipping one write is not enough: the next save would overwrite what the first kept."""
        self._their_file_changed_and_is_unparseable()
        self._save()
        before = self._text()
        self._save()
        self.assertEqual(before, self._text(), "a later save in the same session overwrote it")

    def test_an_ordinary_save_still_works(self):
        """Skipping the write must not be the normal path."""
        self.assertTrue(self._save())
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
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.db_path = os.path.join(self.prefs.dir, library_files.MATERIALS)

    def _disk(self):
        with open(self.db_path, encoding="utf-8") as handle:
            return self.json.load(handle)

    def _write_disk(self, data):
        with open(self.db_path, "w", encoding="utf-8") as handle:
            self.json.dump(data, handle)

    def _other_machine_adds_a_material(self):
        import copy
        data = self._disk()
        row = copy.deepcopy(next(iter(data["assets"].values())))
        row["id"] = "FROM_OTHER_MAC"
        row["name"] = "from_other_mac"
        data["assets"]["FROM_OTHER_MAC"] = row
        self._write_disk(data)

    def _ours(self):
        """A change of this session's, saved: a merge, since another write changed the file."""
        self.model.set_assetdata(self.model.index(0, 0), "ours", "", "", None)
        test_support.settle_stamps()

    def test_an_adopted_row_survives_the_next_save(self):
        """Checks the result on disk, not the code path."""
        self._other_machine_adds_a_material()
        self._ours()
        self.model.save()                              # a SECOND save
        ids = list(self._disk()["assets"])
        self.assertIn(
            "FROM_OTHER_MAC", ids,
            "a material added on the other machine was deleted by this "
            "machine's second save")

    def test_another_sessions_category_colours_survive(self):
        data = self._disk()
        data.setdefault("categories", {}).setdefault("Karma_Mats", {})["color"] = "#ff0000"
        self._write_disk(data)
        self._ours()
        self.assertEqual("#ff0000", self._disk()["categories"]["Karma_Mats"].get("color"),
                         "another session's category colour was removed by an unrelated save")

    def test_an_unknown_top_level_key_is_carried_through(self):
        """A newer build's key must not be dropped by an older one."""
        data = self._disk()
        data["something_a_newer_build_wrote"] = {"keep": "me"}
        self._write_disk(data)
        self._ours()
        self.assertEqual({"keep": "me"}, self._disk().get("something_a_newer_build_wrote"),
                         "an unrecognised top-level key was dropped on save")

    def test_a_sparse_adopted_row_is_kept_not_dropped(self):
        """A row carrying only an id is kept: `from_dict` fills defaults rather than raising."""
        data = self._disk()
        data["assets"]["SPARSE_ROW"] = {"id": "SPARSE_ROW"}
        self._write_disk(data)
        try:
            self._ours()
        except Exception as exc:                       # noqa: BLE001
            self.fail("a sparse adopted row aborted the save: %s" % exc)
        self.assertIn("SPARSE_ROW", self._disk()["assets"])


class CheckLibraryRefusesOnIncompleteKnowledgeTest(unittest.TestCase):
    """Materials and Nodes share img/, so every database's ids decide which files none lists."""

    NODES = library_files.SECTION_FOLDERS[library_files.NODES]

    def setUp(self):
        from amaze.tests import test_support

        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _write_sibling(self, name, text):
        path = os.path.join(self.prefs.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def _survey(self):
        from amaze.core import repair
        return repair.survey(self.prefs.dir, self.prefs.img_dir)

    def _entry(self, findings, filename):
        return next(entry for entry in findings["lists"] if entry["filename"] == filename)

    def test_an_unreadable_sibling_is_reported_not_skipped(self):
        from amaze.core import repair
        self._write_sibling(library_files.NODES, '{"assets": {"COPASSET1": {"id": "COPASSET1"}')
        self._write_sibling(os.path.join(self.NODES, "COPASSET1.mat"), "x")
        findings = self._survey()
        self.assertEqual("unreadable", self._entry(findings, library_files.NODES)["state"])
        self.assertFalse(findings["complete"],
                         "an unreadable sibling was skipped, so its files look unlisted")
        self.assertEqual(len(findings["leftovers"]), repair.files_to_move_aside(findings))
        with self.assertRaises(ValueError):
            repair.move_aside(findings, "unlisted")
        self.assertTrue(any(line.startswith("Nodes: the database is corrupt/unreadable.")
                            for line in repair.report_lines(findings)))

    def test_a_readable_sibling_contributes_its_ids(self):
        self._write_sibling(library_files.NODES, '{"assets": {"COPASSET1": {"id": "COPASSET1"}}}')
        self._write_sibling(os.path.join(self.NODES, "COPASSET1.mat"), "x")
        self._write_sibling(os.path.join(self.NODES, "COPASSET1.json"), "{}")
        findings = self._survey()
        self.assertIn("COPASSET1", findings["ids"],
                      "a sibling's ids were not used by the unlisted check")
        self.assertEqual([], findings["unaccounted"][self.NODES + "/"])

    def test_an_absent_sibling_is_not_an_error(self):
        """An absent file lists no assets; only present-but-unparseable is unsafe."""
        path = os.path.join(self.prefs.dir, library_files.NODES)
        if os.path.exists(path):
            os.remove(path)
        findings = self._survey()
        self.assertEqual("absent", self._entry(findings, library_files.NODES)["state"])
        self.assertTrue(findings["complete"])


def _empty_library_dir(testcase) -> str:
    """A valid assetless library, auto-removed."""
    import shutil
    import tempfile
    from amaze.prefs import prefs as prefs_mod

    tmp = tempfile.mkdtemp(prefix="amaze_empty_lib_")
    testcase.addCleanup(shutil.rmtree, tmp, True)
    prefs_mod.create_library(tmp)
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

        last = self.proxy.index(rows - 1, 0)  # put the selection on the LAST row, the one a smaller library cannot have
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

        from amaze.core import library as library_mod
        with patch.object(library_mod.MaterialLibrary, "_read_rows",    # fail BETWEEN the reset's begin and end
                          side_effect=OSError("library unreadable")):
            with self.assertRaises(OSError):
                self.model.switch_model_data()

        self.assertEqual(1, len(began), "the switch never began a reset")
        self.assertEqual(
            len(began), len(ended),
            "switch_model_data raised and left the model mid-reset - "
            "endResetModel must be in a finally")

    def test_a_switch_drops_the_content_labels_once(self):
        """A switch clears the USD and shader-type labels read from the files, in one call."""
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
                         "a library switch clears the content labels twice")


class GradientSwitchTest(unittest.TestCase):
    """Colors resets on a switch, and a save aimed at another library fails."""

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
        """An unswitched model must not write its colours into another library."""
        model = self._model()
        self.assertTrue(model.save(), "premise: the model saves into its own library")

        self.prefs.dir = _empty_library_dir(self)  # change the library folder without switching the model
        self.assertFalse(
            model.save(),
            "the gradient model saved colours from library A into "
            "library B - nothing blocked the write")


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
            "row shows zero and clicking one filters by a category "
            "that does not exist there: %s" % labels)


class EveryLibraryModelClassCanSwitchTest(unittest.TestCase):
    """Every library-backed model class has `switch_model_data`; the list is `test_area_bindings`."""

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
        index_path = os.path.join(self.prefs.dir, library_files.MATERIALS)
        with open(index_path, "rb") as fh:
            before = json.load(fh)["assets"]
        model.toggle_fav(0)
        test_support.settle_stamps()
        with open(index_path, "rb") as fh:
            after = json.load(fh)
        self.assertEqual(before, after["assets"],
                         "a favourite toggle wrote the shared rows - "
                         "one user's star still overwrites another's")
        self.assertIn(str(model.assets[0].mat_id),
                      after.get("favorites", {}).get(test_support.FIXTURE_USER, {}))
        self.assertTrue(model.data(model.index(0, 0), model.FavoriteRole))


class TheSharedBaseCarriesNothingRendererShaped(unittest.TestCase):
    """`AssetLibrary` is shared; `MaterialLibrary` holds a material's labels, the actions its verbs."""

    RENDERER_SHAPED = (  # checked with `vars()`, since `getattr` also finds inherited names on every subclass
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
                             "%s is back on the Material model" % name)
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
                "%s does not inherit AssetLibrary" % model.__name__)

    def test_the_base_declares_none_of_the_material_surface(self):
        from amaze.core import library
        on_base = [name for name in self.RENDERER_SHAPED
                   if name in vars(library.AssetLibrary)]
        self.assertEqual(
            [], on_base,
            "the shared base has renderer-specific members again: %s"
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
            "these models can be built without being given the library "
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
    """No tags is `[]` on disk on every path: the add, and the row read back. ▸p/no-tags-is-empty"""

    def _saved_tags(self, prefs, name: str) -> list:
        test_support.settle_stamps()
        with open(os.path.join(prefs.dir, library_files.MATERIALS),
                  encoding="utf-8") as handle:
            rows = json.load(handle)["assets"].values()
        return [row["tags"] for row in rows if row.get("name") == name]

    def test_a_material_added_with_no_tags_saves_an_empty_list(self):
        """Added with blank Tags, saved, read back by a fresh model and saved again untouched."""
        from amaze.core import library as library_mod
        from amaze.tests import make_library_fixture

        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node requires $OCIO; nothing renders here
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

        test_support.reset_database_singletons()    # a fresh read from disk, not library_db's cached document
        reopened = library_mod.MaterialLibrary(preferences=prefs)
        self.assertTrue(reopened.save(),
                        "premise: the second save went through")
        self.assertEqual(
            [[]], self._saved_tags(prefs, "Untagged"),
            "a row saved with no tags was read back from disk with a "
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
        """`_content_stat` returns `hostos.disk_state` of the .mat, None with no .mat or a bad id."""
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
            "the content guard's stat no longer matches `hostos.disk_state`")


if __name__ == "__main__":
    unittest.main()
