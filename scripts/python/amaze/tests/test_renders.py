"""Integration tests against a REAL hou session (run via hython) -
categories over a private fixture copy, plus a scene-load smoke test.

Every test resets the DatabaseConnector cache and injects preferences
already pointing at its own fixture copy (see test_support) - the
pre-2026-07-25 versions constructed models FIRST, which made them read
and mutate the user's real library through the connector singleton.
"""

import unittest

import os
import sys

# THREE dirnames up = scripts/python, the directory holding the
# `amaze` package - the DEV tree, not the install on Houdini's path.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou

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

    def test_load_houdini(self):
        filepath = (
            hou.getenv("AMAZE")
            + "/scripts/python/amaze/tests/assets/houdini/Materials.hiplc"
        )
        hou.hipFile.load(filepath)
        self.assertEqual(1, 1, "Load Houdini - Success!")

    def test_category(self):
        cat_model = self._fixture_categories()
        self.assertEqual(
            cat_model.rowCount(), 3, "fixture has _All/Karma_Mats/usds"
        )

    def test_remove_category(self):
        cat_model = self._fixture_categories()
        cat_model.remove_category("usds")
        self.assertEqual(cat_model.rowCount(), 2)

    def test_add_category(self):
        cat_model = self._fixture_categories()
        cat_model.check_add_category("brand_new_cat")
        self.assertEqual(cat_model.rowCount(), 4)


if __name__ == "__main__":
    unittest.main()
