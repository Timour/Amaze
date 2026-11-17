"""Check Library counts a missing render only for assets that get one, in the section's noun."""
import json
import os
import unittest

from amaze.core import library_files, material, repair
from amaze.tests import test_support


class TheThumbnailCountIsPerSectionTest(unittest.TestCase):
    """A LOP setup is not counted as missing a render, a SOP setup is, and the count reads node."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.node_dir = material.section_folder(self.prefs.dir, library_files.NODES)
        os.makedirs(self.node_dir, exist_ok=True)
        self.cops = os.path.join(self.prefs.dir, library_files.NODES)
        self.assertFalse(os.path.exists(self.cops), "premise: the fixture has no nodes.json")

    def _row(self, asset_id: str, context: str) -> dict:
        for suffix in (".mat", material.RECORD_SUFFIX):    # both files present, no render
            with open(os.path.join(self.node_dir, asset_id + suffix), "w",
                      encoding="utf-8") as handle:
                handle.write('{"format": 1}\n')
        return {"id": asset_id, "name": asset_id, "renderer": context,
                "categories": ["Main"], "tags": []}

    def test_lop_setups_are_not_counted_and_a_sop_setup_is(self):
        rows = [self._row("LOPSETUP1", "LOP"), self._row("LOPSETUP2", "LOP"),
                self._row("SOPSETUP1", "SOP")]
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"categories": {"Main": {"order": 0}},
                       "assets": {row["id"]: row for row in rows}}, handle)
        findings = repair.survey(self.prefs.dir, self.prefs.img_dir)
        self.assertEqual(["SOPSETUP1"],
                         [one for one, _name in findings["missing_renders"][library_files.NODES]],
                         "the two LOP setups were counted as missing a render")
        thumbnails = [line for line in repair.report_lines(findings)
                      if line.startswith("No thumbnail image yet")]
        self.assertEqual(1, len(thumbnails), thumbnails)
        self.assertIn("No thumbnail image yet for 1 node ", thumbnails[0],
                      "the two LOP setups were counted, or the noun is wrong")
        self.assertNotIn("material", thumbnails[0])

    def test_each_section_counts_in_its_own_noun(self):
        self.assertEqual("material", library_files.section_noun(library_files.MATERIALS, 1))
        self.assertEqual("node", library_files.section_noun(library_files.NODES, 1))
        self.assertEqual("2 nodes", repair._counted(2, library_files.NODES))
        self.assertEqual("1 material", repair._counted(1, library_files.MATERIALS))


if __name__ == "__main__":
    unittest.main()
