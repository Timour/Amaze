"""Integration tests against a REAL hou session (run via hython) - categories over a private fixture copy, plus a scene-load smoke test. - Every test resets the DatabaseConnector cache and injects preferences already pointing at its own fixture copy (see test_support) - the pre-2026-07-25 versions constructed models FIRST, which made them read and mutate the user's real library through the connector singleton."""

import unittest

import os
import sys

sys.path.insert(   # THREE dirnames up = scripts/python, the directory holding the `amaze` package - the DEV tree, not the install on Houdini's path
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
        """The fixture scene opens and brings its materials with it - `assertEqual(1, 1)` passed for any file that merely did not raise, and passed while this read a scene from a different tree entirely."""
        filepath = os.path.join(   # THIS tree, the way test_support resolves its own fixtures: `hou.getenv("AMAZE")` is set by the Houdini package and points at the LIVE install, so under the suite's scratch install this test was loading a scene the run had never seen
            os.path.dirname(os.path.abspath(__file__)),
            "assets", "houdini", "Materials.hiplc")
        self.assertTrue(os.path.exists(filepath),
                        "the fixture scene is missing: %s" % filepath)
        hou.hipFile.load(filepath, suppress_save_prompt=True)
        materials = [n for n in (hou.node("/mat").children()
                                 if hou.node("/mat") else ())
                     if n.isGenericFlagSet(hou.nodeFlag.Material)]
        self.assertTrue(
            materials,
            "the scene loaded with no materials in /mat, so a render "
            "test built on it would have nothing to render")

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
