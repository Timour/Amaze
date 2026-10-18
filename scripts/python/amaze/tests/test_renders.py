"""Categories in a REAL hou session, each case on its own fixture copy and a fresh connector."""

import unittest

import os
import sys

sys.path.insert(   # THREE dirnames up = scripts/python, the directory holding the `amaze` package - the DEV tree, not the install on Houdini's path
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import category
import test_support


class TestLib(unittest.TestCase):

    def _fixture_categories(self):
        test_support.reset_database_singletons()
        model = category.Categories(
            preferences=test_support.fixture_prefs(self)
        )
        self.addCleanup(test_support.reset_database_singletons)
        return model

    def test_category(self):
        """The fixture has _All/Karma_Mats/usds; one removed leaves two, one added makes four."""
        for why, change, rows in (
                ("as loaded", lambda model: None, 3),
                ("usds removed", lambda model: model.remove_category("usds"), 2),
                ("one added",
                 lambda model: model.check_add_category("brand_new_cat"), 4)):
            with self.subTest(why):
                cat_model = self._fixture_categories()
                change(cat_model)
                self.assertEqual(cat_model.rowCount(), rows)


if __name__ == "__main__":
    unittest.main()
