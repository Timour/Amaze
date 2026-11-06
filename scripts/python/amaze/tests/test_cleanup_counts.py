"""Check Library counts a missing render only where a tile can hold one, in the section's noun."""
import json
import os
import unittest

from amaze.core import database, repair
from amaze.tests import test_support


class TheThumbnailCountKnowsItsSectionTest(unittest.TestCase):
    """A LOP setup has no render to miss, a SOP setup does, and the count says node."""

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

    def test_lop_setups_are_not_counted_and_a_sop_setup_is(self):
        rows = [self._row("LOPSETUP1", "LOP"), self._row("LOPSETUP2", "LOP"),
                self._row("SOPSETUP1", "SOP")]
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All", "Main"], "tags": [], "assets": rows}, handle)
        findings = repair.survey(self.prefs.dir, self.prefs.asset_dir, self.prefs.img_dir)
        self.assertEqual(["SOPSETUP1"],
                         [one for one, _name in findings["missing_renders"]["cops.json"]],
                         "the two LOP setups were counted as missing a render")
        thumbnails = [line for line in repair.report_lines(findings)
                      if line.startswith("No thumbnail image yet")]
        self.assertEqual(1, len(thumbnails), thumbnails)
        self.assertIn("No thumbnail image yet for 1 node ", thumbnails[0],
                      "the two LOP setups were counted, or the noun is wrong")
        self.assertNotIn("material", thumbnails[0])

    def test_each_section_counts_in_its_own_noun(self):
        self.assertEqual("material", database.section_noun("library.json", 1))
        self.assertEqual("node", database.section_noun("cops.json", 1))
        self.assertEqual("2 nodes", repair._counted(2, "cops.json"))
        self.assertEqual("1 material", repair._counted(1, "library.json"))


if __name__ == "__main__":
    unittest.main()
