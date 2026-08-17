"""The Categories model, with PySide6, prefs and the database connector mocked out."""

import unittest
from unittest.mock import MagicMock, patch, call

import os
import sys

sys.path.insert(  # THREE dirnames up = scripts/python, the directory holding the `amaze` package - the DEV tree, not the install on Houdini's path ▸p/checkout-not-install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import category
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log


class TestCategories(unittest.TestCase):
    """Test suite for the Categories model class."""

    def setUp(self):
        """Set up mocks before each test."""
        self.mock_qtcore = MagicMock()
        self.mock_qtcore.Qt.ItemDataRole.UserRole = 256
        self.mock_qtcore.Qt.ItemDataRole.DisplayRole = 0
        self.mock_qtcore.QAbstractListModel = MagicMock

        self.mock_prefs_instance = MagicMock()
        self.mock_prefs_instance.dir = "/mock/path"
        self.mock_prefs_class = MagicMock(return_value=self.mock_prefs_instance)

        self.mock_db_instance = MagicMock()
        self.mock_db_instance.load.return_value = {
            "categories": ["Cat1", "_Hidden", "Cat2"]
        }
        self.mock_db_instance.reload_with_path.return_value = {
            "categories": ["New1", "New2"]
        }
        self.mock_db_class = MagicMock(return_value=self.mock_db_instance)

        self.mock_index = MagicMock()

        self.patcher_qtcore = patch("PySide6.QtCore", self.mock_qtcore)
        self.patcher_prefs = patch("amaze.prefs.prefs.Prefs", self.mock_prefs_class)
        self.patcher_db = patch(
            "amaze.core.database.DatabaseConnector", self.mock_db_class
        )

        self.patcher_qtcore.start()
        self.patcher_prefs.start()
        self.patcher_db.start()
        self.category_module = category  # bound after patching

    def tearDown(self):
        """Clean up patches after each test."""
        self.patcher_qtcore.stop()
        self.patcher_prefs.stop()
        self.patcher_db.stop()

    def test_init_loads_preferences_and_categories(self):
        """Test that __init__ takes the given preferences and loads categories from database."""
        model = self.category_module.Categories(self.mock_prefs_instance)

        self.assertIs(self.mock_prefs_instance, model.preferences)
        self.mock_prefs_instance.load.assert_not_called()  # the model shares the panel's Prefs OBJECT, so a load() here would re-read settings.json under the panel and revert its unsaved edits; switch_model_data reloads deliberately, construction must not
        self.mock_db_instance.load.assert_called_once_with("/mock/path")
        self.assertEqual(model._categories, ["Cat1", "_Hidden", "Cat2"])
        self.assertEqual(model.CatSortRole, 256)

    def test_row_count(self):
        """Test that rowCount returns the correct number of categories."""
        model = self.category_module.Categories(self.mock_prefs_instance)

        self.assertEqual(model.rowCount(), 3)

    def test_data_with_cat_sort_role(self):
        """Test data method with CatSortRole returns raw category."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        self.mock_index.row.return_value = 1

        result = model.data(self.mock_index, role=256)

        self.assertEqual(result, "_Hidden")

    def test_data_with_display_role_strips_underscore(self):
        """Test data method with DisplayRole strips leading underscore."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        self.mock_index.row.return_value = 1

        result = model.data(self.mock_index, role=0)

        self.assertEqual(result, "Hidden")

    def test_data_with_display_role_no_underscore(self):
        """Test data method with DisplayRole for category without underscore."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        self.mock_index.row.return_value = 0

        result = model.data(self.mock_index, role=0)

        self.assertEqual(result, "Cat1")

    def test_reload(self):
        """Test reload method reloads categories from database."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        self.mock_db_instance.load.reset_mock()
        self.mock_db_instance.load.return_value = {
            "categories": ["Reloaded1", "Reloaded2"]
        }

        model.reload()

        self.mock_db_instance.load.assert_called_once_with("/mock/path")
        self.assertEqual(model._categories, ["Reloaded1", "Reloaded2"])

    def test_switch_model_data(self):
        """Test switch_model_data reloads preferences and uses reload_with_path."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        self.mock_prefs_instance.load.reset_mock()

        model.switch_model_data()

        self.mock_prefs_instance.load.assert_called_once()
        self.mock_db_instance.reload_with_path.assert_called_once_with("/mock/path")
        self.assertEqual(model._categories, ["New1", "New2"])

    def test_remove_category(self):
        """Test remove_category removes category and saves."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        model.save = MagicMock()

        model.remove_category("Cat1")

        self.assertNotIn("Cat1", model._categories)
        self.assertEqual(model._categories, ["_Hidden", "Cat2"])
        model.save.assert_called_once()

    def test_rename_category(self):
        """Test rename_category renames all instances and saves."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        model._categories = ["OldName", "Cat2", "OldName"]
        model.save = MagicMock()

        model.rename_category("OldName", "NewName")

        self.assertEqual(model._categories, ["NewName", "Cat2", "NewName"])
        model.save.assert_called_once()

    def test_rename_category_no_match(self):
        """Test rename_category when category doesn't exist still calls save."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        model.save = MagicMock()
        original_categories = model._categories.copy()

        model.rename_category("NonExistent", "NewName")

        self.assertEqual(model._categories, original_categories)
        model.save.assert_called_once()

    def test_check_add_category_ignores_multiple_values(self):
        """Test check_add_category ignores 'Multiple Values...' string."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        model.save = MagicMock()
        original_categories = model._categories.copy()

        model.check_add_category("Multiple Values...")

        self.assertEqual(model._categories, original_categories)
        model.save.assert_not_called()

    def test_check_add_category_adds_new_category(self):
        """Test check_add_category adds new category."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        model.save = MagicMock()

        model.check_add_category("NewCat")

        self.assertIn("NewCat", model._categories)
        model.save.assert_called_once()

    def test_check_add_category_ignores_existing(self):
        """Test check_add_category doesn't add existing category."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        model.save = MagicMock()
        original_count = len(model._categories)

        model.check_add_category("Cat1")

        self.assertEqual(len(model._categories), original_count)
        model.save.assert_not_called()

    def test_check_add_category_handles_comma_separated(self):
        """Test check_add_category handles comma-separated values."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        model.save = MagicMock()

        model.check_add_category("NewCat1, NewCat2, NewCat3")

        self.assertIn("NewCat1", model._categories)
        self.assertIn("NewCat2", model._categories)
        self.assertIn("NewCat3", model._categories)
        model.save.assert_called_once()

    def test_check_add_category_strips_spaces(self):
        """Test check_add_category strips spaces from category names."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        model.save = MagicMock()

        model.check_add_category("  SpacedCat  ")

        self.assertIn("SpacedCat", model._categories)
        model.save.assert_called_once()

    def test_check_add_category_ignores_empty_strings(self):
        """Test check_add_category ignores empty strings."""
        model = self.category_module.Categories(self.mock_prefs_instance)
        model.save = MagicMock()
        original_categories = model._categories.copy()

        model.check_add_category("  ,  ,  ")

        self.assertEqual(model._categories, original_categories)
        model.save.assert_not_called()

    def test_save(self):
        """Test save method writes categories to database."""
        model = self.category_module.Categories(self.mock_prefs_instance)

        model.save()

        self.mock_db_instance.set.assert_called_with(  # save() writes the COLOURS alongside the names: same json, so a colour travels with the library it belongs to
            {"categories": ["Cat1", "_Hidden", "Cat2"], "category_colors": {}}
        )
        self.mock_db_instance.save.assert_called_once()


class NormalizeBracketsItsResetTest(unittest.TestCase):
    """normalize_categories REPLACES the row set, so it must bracket the change - and the honest observable is the SIGNAL PAIR, never the row count, because a model left mid-reset is invisible through a proxy. ▸r/model-contracts"""

    def _model(self, entries):
        from amaze.core import category as category_mod
        from amaze.tests import test_support
        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        model = category_mod.Categories(preferences=prefs)
        model._categories = list(entries)
        return model

    def test_it_emits_a_matched_reset_pair(self):
        model = self._model(["Metal", "metal ", "", "Wood", "Metal"])
        seen = []
        model.modelAboutToBeReset.connect(lambda: seen.append("about"))
        model.modelReset.connect(lambda: seen.append("done"))
        changed = model.normalize_categories()
        self.assertGreater(changed, 0, "the fixture needed no cleaning")
        self.assertEqual(
            ["about", "done"], seen,
            "the row set was replaced without a matched reset pair")

    def test_a_clean_list_resets_nothing(self):
        """The bracket must not fire when no rows change."""
        model = self._model(["Metal", "Wood"])
        seen = []
        model.modelAboutToBeReset.connect(lambda: seen.append("about"))
        self.assertEqual(0, model.normalize_categories())
        self.assertEqual([], seen, "a no-op reset the whole model")

    def test_the_model_stays_ALIASED_to_the_connectors_list(self):
        """`Categories.__init__` aliases `_categories` to the connector's own `_data["categories"]`, and the two-writer merge APPENDS a peer machine's new categories to that list IN PLACE - so a normalize that REBINDS instead of mutating detaches the model, the merge updates a list nobody shows, and the next save writes the document without the adopted names."""
        from amaze.core import category as category_mod
        from amaze.core import database
        from amaze.tests import test_support

        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = category_mod.Categories(preferences=prefs)
        shared = database.DatabaseConnector(
            category_mod.Categories.DB_FILENAME).load(prefs.dir)
        self.assertIs(model._categories, shared["categories"],
                      "premise: the model aliases the connector's list")
        shared["categories"].append("  Needs Cleaning  ")
        self.assertGreater(model.normalize_categories(), 0,
                           "the dirty entry was not cleaned")
        self.assertIs(
            model._categories, shared["categories"],
            "normalize_categories rebound the list - the model is "
            "detached from the document the merge repairs, and the "
            "next save erases whatever a peer machine added")


if __name__ == "__main__":
    unittest.main()
