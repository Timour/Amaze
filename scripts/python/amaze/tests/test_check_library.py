"""Check Library 2.0: the guard's judgement in the report, and every fix acting through the guard."""

import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import asset_record, guard, library_files, repair  # noqa: E402
from amaze.tests import test_support  # noqa: E402

MATERIALS = library_files.MATERIALS
NODES = library_files.NODES
BUILDER = {"type": "subnet", "interface": "", "values": {}}


def _write(directory: str, name: str, document: dict) -> None:
    with open(os.path.join(directory, name), "wb") as handle:
        handle.write(guard.encode(document))


def _read(directory: str, name: str) -> dict:
    with open(os.path.join(directory, name), encoding="utf-8") as handle:
        return json.load(handle)


class _Library(unittest.TestCase):
    """A small 2.0 library: two materials with their files and metadata, no session holding it."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_check_") + os.sep
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.materials = os.path.join(self.dir, "materials")
        os.makedirs(self.materials)
        _write(self.dir, library_files.MASTER, {"manifest": {MATERIALS: {"by": ""}},
                                                "users": {}})
        rows = {}
        for asset_id, name in (("AAA1", "Brick"), ("AAA2", "Oak")):
            row = {"id": asset_id, "name": name, "categories": ["Walls"], "renderer": "Karma"}
            rows[asset_id] = row
            self.asset(asset_id, row)
        _write(self.dir, MATERIALS, {"assets": rows, "categories": {"Walls": {"order": 0}}})

    def asset(self, asset_id: str, metadata=None, folder=None) -> None:
        """An asset's `.mat`, `.png` and `<id>.json` in `folder`, the metadata when given."""
        folder = folder or self.materials
        os.makedirs(folder, exist_ok=True)
        for suffix in (".mat", ".png"):
            with open(os.path.join(folder, asset_id + suffix), "wb") as handle:
                handle.write(b"x")
        document = {"format": asset_record.FORMAT, asset_record.BUILDER: BUILDER}
        if metadata is not None:
            document[asset_record.METADATA] = dict(metadata)
        with open(os.path.join(folder, asset_id + ".json"), "wb") as handle:
            handle.write(asset_record.encode(document))

    def survey(self):
        return repair.survey(self.dir, "img/")

    def trash_holds(self, relative: str) -> bool:
        day = datetime.date.today().isoformat()
        return os.path.exists(os.path.join(self.dir, "trash", day, *relative.split("/")))


class TheReportIsTheGuardsJudgementTest(_Library):

    def test_a_corrupt_database_is_named_and_holds_every_move_back(self):
        with open(os.path.join(self.dir, MATERIALS), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")
        self.asset("ORPHAN1")
        findings = self.survey()
        states = {entry["filename"]: entry["state"] for entry in findings["lists"]}
        self.assertEqual("unreadable", states[MATERIALS])
        self.assertFalse(findings["complete"])
        self.assertIn("Materials: the database is corrupt/unreadable.",
                      "\n".join(repair.report_lines(findings)))
        with self.assertRaises(ValueError):
            repair.move_aside(findings, "unlisted", guard=False)
        self.assertTrue(os.path.exists(os.path.join(self.materials, "ORPHAN1.mat")))

    def test_a_newer_database_is_named_and_read_only(self):
        _write(self.dir, NODES, {"assets": {}, "format": 99})
        findings = self.survey()
        self.assertIn("Nodes: the database was saved by a newer Amaze",
                      "\n".join(repair.report_lines(findings)))

    def test_every_database_reads_fine_with_its_count(self):
        text = "\n".join(repair.report_lines(self.survey()))
        self.assertIn("Every database reads fine: 0 users and 2 materials.", text)
        self.assertIn("Nothing is saved yet in Nodes, Code, Colors and Files.", text)
        self.assertIn("The library's trash is empty", text)


class TheFixesActThroughTheGuardTest(_Library):

    def test_restore_a_backup_keeps_the_database_you_have_as_an_undo_copy(self):
        reading = guard.Guard(self.dir).read(MATERIALS)
        change = guard.Guard(self.dir).change("u")
        change.put(reading.ticket, {"assets": {}})
        change.commit()
        findings = self.survey()
        offers = repair.offered_copies(findings)
        self.assertTrue(offers, "the backup of the two materials is not offered")
        filename, backup, _snap, _now = offers[0]
        done = repair.put_back(findings, filename, backup, guard=False)
        self.assertEqual({"AAA1", "AAA2"}, set(_read(self.dir, MATERIALS)["assets"]))
        self.assertTrue(done["undo"].endswith(guard.UNDO_TAIL), "nothing kept to undo")

    def test_orphaned_files_go_to_the_librarys_trash(self):
        with open(os.path.join(self.materials, "STRAY1.png"), "wb") as handle:
            handle.write(b"x")
        findings = self.survey()
        self.assertEqual(["STRAY1.png"], findings["unaccounted"]["materials/"])
        result = repair.move_aside(findings, "unlisted", guard=False)
        self.assertEqual(["STRAY1.png"], result["moved"])
        self.assertFalse(os.path.exists(os.path.join(self.materials, "STRAY1.png")))
        self.assertTrue(self.trash_holds("materials/STRAY1.png"))

    def test_orphaned_materials_are_added_back_from_their_metadata(self):
        self.asset("NEW1", {"id": "NEW1", "name": "Slate", "categories": ["Roofs"],
                            "renderer": "Karma"})
        findings = self.survey()
        self.assertEqual(["NEW1"], [one for one, _record in repair.materials_on_record(findings)])
        result = repair.add_materials_back(findings, guard=False)
        self.assertEqual(["NEW1"], result["added"])
        stored = _read(self.dir, MATERIALS)
        self.assertEqual("Slate", stored["assets"]["NEW1"]["name"])
        self.assertIn("Roofs", stored["categories"])

    def test_orphaned_pairs_go_into_the_section_picked_with_their_files(self):
        self.asset("NODE1")
        findings = self.survey()
        self.assertEqual(["NODE1"], repair.unsorted_pairs(findings))
        result = repair.reattach(findings, NODES, only=["NODE1"], guard=False)
        self.assertEqual(["NODE1"], result["added"])
        self.assertIn("NODE1", _read(self.dir, NODES)["assets"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "nodes", "NODE1.mat")),
                        "the files did not move home with the row")
        self.assertFalse(os.path.exists(os.path.join(self.materials, "NODE1.mat")))

    def test_a_lost_database_is_rebuilt_from_each_assets_metadata(self):
        for asset_id, name in (("AAA1", "Brick"), ("AAA2", "Oak")):
            self.asset(asset_id, {"id": asset_id, "name": name, "categories": ["Walls"],
                                  "renderer": "Karma"})
        with open(os.path.join(self.dir, MATERIALS), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")
        ok, how = repair.repair_index(self.dir, guard=False)
        self.assertTrue(ok, how)
        self.assertIn("rebuilt", how)
        self.assertEqual({"AAA1", "AAA2"}, set(_read(self.dir, MATERIALS)["assets"]))

    def test_rows_with_no_category_are_put_in_uncategorized(self):
        stored = _read(self.dir, MATERIALS)
        stored["assets"]["AAA2"]["categories"] = []
        _write(self.dir, MATERIALS, stored)
        findings = self.survey()
        done = repair.rescue_uncategorised(findings, guard=False)
        self.assertEqual({MATERIALS: 1}, done)
        self.assertEqual([repair.UNCATEGORISED],
                         _read(self.dir, MATERIALS)["assets"]["AAA2"]["categories"])


class EachFixGoesRedWhenItIsBrokenTest(unittest.TestCase):
    """Sabotage: each fix's test fails when the guard step it stands on does nothing."""

    SABOTAGES = (
        ("test_restore_a_backup_keeps_the_database_you_have_as_an_undo_copy",
         "amaze.core.guard.Guard.restore", lambda *_a, **_k: None),
        ("test_orphaned_files_go_to_the_librarys_trash",
         "amaze.core.guard.Change.trash", lambda *_a, **_k: None),
        ("test_orphaned_materials_are_added_back_from_their_metadata",
         "amaze.core.guard.Change.put", lambda *_a, **_k: None),
        ("test_orphaned_pairs_go_into_the_section_picked_with_their_files",
         "amaze.core.guard.Change.take", lambda *_a, **_k: None),
        ("test_a_lost_database_is_rebuilt_from_each_assets_metadata",
         "amaze.core.guard.Change.replace", lambda *_a, **_k: None),
        ("test_rows_with_no_category_are_put_in_uncategorized",
         "amaze.core.guard.Change.put", lambda *_a, **_k: None),
    )

    def test_every_fix_test_catches_its_sabotage(self):
        for name, target, broken in self.SABOTAGES:
            with self.subTest(name=name):
                result = unittest.TestResult()
                with mock.patch(target, broken):
                    TheFixesActThroughTheGuardTest(name).run(result)
                self.assertTrue(result.failures or result.errors,
                                "%s stayed green with %s broken" % (name, target))


if __name__ == "__main__":
    unittest.main()
