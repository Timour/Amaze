"""Clean Up Library counts a missing render only where a tile can hold one, in the section's noun."""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

import hou

from amaze.core import cop_library, library as library_mod
from amaze.tests import test_support


class TheThumbnailCountKnowsItsSectionTest(unittest.TestCase):
    """A LOP setup has no render to miss, a SOP setup does, and the count says node setup."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        self.cops = os.path.join(self.prefs.dir, "cops.json")
        self.assertFalse(os.path.exists(self.cops), "premise: the fixture has no cops.json")

    def _row(self, asset_id: str, context: str) -> dict:
        for suffix in (".mat", ".interface"):    # both halves present, no render
            with open(os.path.join(self.mat_dir, asset_id + suffix), "w",
                      encoding="utf-8") as handle:
                handle.write("a node setup\n")
        return {"id": asset_id, "name": asset_id, "renderer": context,
                "categories": ["Main"], "tags": []}

    def _summary(self, model) -> str:
        with patch.object(hou, "ui", MagicMock(), create=True):
            model.cleanup_db()
        return " ".join(model.last_cleanup_summary)

    def test_lop_setups_are_not_counted_and_a_sop_setup_is(self):
        rows = [self._row("LOPSETUP1", "LOP"), self._row("LOPSETUP2", "LOP"),
                self._row("SOPSETUP1", "SOP")]
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All", "Main"], "tags": [], "assets": rows}, handle)
        summary = self._summary(cop_library.CopLibrary(preferences=self.prefs))
        self.assertIn("No thumbnail image yet for 1 node setup ", summary,
                      "the two LOP setups were counted, or the noun is wrong")
        self.assertNotIn("material", summary)

    def test_each_section_counts_in_its_own_noun(self):
        self.assertEqual("material", library_mod.AssetLibrary.ROW_NOUN)
        self.assertEqual("node setup", cop_library.CopLibrary.ROW_NOUN)
        self.assertEqual("2 node setups", library_mod._count(2, cop_library.CopLibrary.ROW_NOUN))
        self.assertEqual("1 material", library_mod._count(1, library_mod.AssetLibrary.ROW_NOUN))


if __name__ == "__main__":
    unittest.main()
