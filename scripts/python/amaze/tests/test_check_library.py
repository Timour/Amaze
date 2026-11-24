"""Check Library: one test per requirement in docs/requirements/check-library.md."""

import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

from amaze.core import asset_record, check_library, guard, library_db, library_files
from amaze.core import library_policy, locations
from amaze.tests import test_support

try:
    import hou    # noqa: F401
except ImportError:    # without Houdini: the dialog imports it, and every test here gives it a fake ui
    sys.modules["hou"] = types.SimpleNamespace()
from amaze.dialogs import check_dialog    # noqa: E402

put, state = test_support.put, test_support.library_state
MATERIALS, NODES, CODE = library_files.MATERIALS, library_files.NODES, library_files.CODE
USER = test_support.FIXTURE_USER


def record(name: str, *categories) -> bytes:
    return asset_record.encode({"format": asset_record.FORMAT, asset_record.METADATA: {
        "name": name, "categories": list(categories)}})


def lay_out(folder: str) -> None:
    """A 3.0 library holding one of each thing Check Library reports, and things it must leave."""
    put(folder, guard.MASTER, {"policy": {"library": {"version": library_policy.LIBRARY_VERSION}},
                               guard.MANIFEST: {name: {"created": "x", "by": ""}
                                                for name in (MATERIALS, NODES, CODE)}})
    put(folder, MATERIALS, {"assets": {"A1": {"name": "Brick", "categories": ["Walls"]},
                                       "A2": {"name": "Gone", "categories": ["Walls"]},
                                       "A3": {"name": "Loose"}},
                            "categories": {"Walls": {"order": 0}}})
    put(folder, NODES, {"assets": {"N1": {"name": "Rig", "categories": ["Rigs"], "renderer": "LOP"}}})
    put(folder, CODE, {"assets": {"C1": {"name": "Snippet", "categories": ["Examples"]}}})
    for asset_id, name, categories in (("A1", "Brick", ("Walls",)), ("A3", "Loose", ())):
        for suffix, data in ((".mat", b"nodes"), (".json", record(name, *categories)),
                             (".png", b"picture")):
            put(folder, "materials/%s__%s/%s%s" % (name, asset_id, asset_id, suffix), data)
    put(folder, "nodes/Rig__N1/N1.mat", b"nodes")
    put(folder, "nodes/Rig__N1/N1.json", record("Rig", "Rigs"))
    put(folder, "materials/Found__U1/U1.mat", b"nodes")
    put(folder, "materials/Found__U1/U1.json", record("Found", "Wood, Oak"))
    put(folder, "materials/Bare__U2/U2.mat", b"nodes")    # no record: it cannot be recovered
    put(folder, "materials/notes.txt", b"mine")    # a file Amaze does not write
    put(folder, "stuff/thing.bin", b"?")    # a folder Amaze does not write
    put(folder, "import/yarn.lock", b"the user's")
    put(folder, "materials/Brick__A1/comments/%s.png" % ("a" * 32), b"pasted")
    put(folder, "files/comments/%s.png" % ("b" * 32), b"pasted")
    put(folder, "colors/Old__K9/K9.png", b"picture")    # a color's folder no database lists
    put(folder, "materials/Icon\r", b"")
    put(folder, "code/Snippet__C1/versions/versions.json", json.dumps({"versions": [{"n": 1}]}))
    put(folder, "code/Snippet__C1/versions/C1_1.txt", b"first")
    put(folder, "code/Snippet__C1/versions/C1_9.txt", b"no ledger row")
    put(folder, "materials/Brick__A1/A1 2.png", b"picture")    # a sync copy that matches
    put(folder, "materials/Brick__A1/A1 2.mat", b"other nodes")    # a sync copy that differs
    old = put(folder, "materials/Brick__A1/A1.mat.x1" + guard.SCRATCH, b"half")
    os.utime(old, (time.time() - 2 * check_library.SCRATCH_MIN_AGE,) * 2)


class Houdini:
    """`hou` for the dialog: each message is answered with the next of `answers`, else Cancel."""

    def __init__(self, *answers) -> None:
        self.answers, self.asked = list(answers), []
        self.severityType = types.SimpleNamespace(Message=0, Warning=1, Error=2)
        self.ui = types.SimpleNamespace(displayMessage=self._message)

    def _message(self, text, buttons=("OK",), **_how):
        self.asked.append((text, tuple(buttons)))
        return self.answers.pop(0) if self.answers else len(buttons) - 1


class Prefs(types.SimpleNamespace):
    """The preferences Check Library reads: the library, the user, the File section's locations."""

    def remove_file_folder(self, path: str) -> None:
        locations.unregister(self, path)


class _Library(unittest.TestCase):

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = tempfile.mkdtemp(prefix="amaze_check_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        lay_out(self.dir)

    def at(self, *parts) -> str:
        return os.path.join(self.dir, *parts)

    def rows(self, name: str = MATERIALS) -> dict:
        return guard.Guard(self.dir).read(name).document["assets"]

    def fix_all(self, named: bool, prefs=None) -> dict:
        shown = check_library.survey(self.dir, prefs)
        keys = [key for key, _label in check_library.confirmable(shown)] if named else []
        return check_library.fix_all(self.dir, prefs, shown, keys, USER)

    def prefs(self) -> Prefs:
        return Prefs(dir=self.dir, library_user=USER)


class NothingIsLostTest(_Library):

    def test_cl01_checking_changes_nothing(self):
        before = state(self.dir)
        found = check_library.survey(self.dir)
        self.assertTrue(check_library.report_lines(found), "premise: the library holds findings")
        self.assertEqual(before, state(self.dir))

    def test_cl02_a_fix_moves_to_the_trash_and_keeps_a_replaced_database_in_backup(self):
        before = state(self.dir)
        self.fix_all(named=True)
        after = state(self.dir)
        trashed = {path.split("/", 2)[2]: data for path, data in after.items()
                   if path.startswith(guard.TRASH_DIR + "/")}
        gone = {path: data for path, data in before.items() if path not in after}
        self.assertTrue(gone, "premise: the fix took files away")
        for path, data in gone.items():
            if path not in (MATERIALS,):
                self.assertEqual(data, trashed.get(path), "%s was not kept in the trash" % path)
        put(self.dir, NODES, b"{ not a database")
        self.fix_all(named=True)
        kept = [name for name in os.listdir(self.at(guard.BACKUP_DIR)) if name.startswith(NODES)]
        self.assertTrue(any(pathlib.Path(self.at(guard.BACKUP_DIR, name)).read_bytes() == b"{ not a database"
                            for name in kept), "the unreadable database was not kept in backup/")

    def test_cl03_a_fix_acts_only_on_what_the_check_showed(self):
        shown = check_library.survey(self.dir)
        late = put(self.dir, "materials/late.txt", b"made after the check")
        keys = [key for key, _label in check_library.confirmable(check_library.survey(self.dir))]
        check_library.fix_all(self.dir, None, shown, keys, USER)
        self.assertTrue(os.path.exists(late), "a file the check never showed was trashed")

    def test_cl04_nothing_is_trashed_while_the_check_is_incomplete(self):
        put(self.dir, NODES, b"{ not a database")
        shown = check_library.survey(self.dir)
        self.assertTrue(shown["holding_back"])
        keys = [key for key, _label in check_library.confirmable(shown)]
        with self.assertRaises(check_library.Refused):
            check_library.trash(self.dir, shown, keys, USER)
        with self.assertRaises(check_library.Refused):
            check_library.remove_rows(self.dir, keys, USER)
        self.assertTrue(os.path.exists(self.at("materials", "notes.txt")))
        self.assertIn("A2", self.rows())

    def test_cl05_a_listed_or_recoverable_asset_folder_is_never_trashed(self):
        self.fix_all(named=True)
        for folder in ("Brick__A1", "Loose__A3", "Found__U1"):
            self.assertTrue(os.path.isdir(self.at("materials", folder)), folder)
        self.assertIn("U1", self.rows(), "the recoverable folder was not recovered")

    def test_cl06_a_row_whose_files_are_missing_goes_only_once_named(self):
        self.fix_all(named=False)
        self.assertIn("A2", self.rows(), "a row was removed without being named")
        self.fix_all(named=True)
        self.assertNotIn("A2", self.rows())

    def test_cl07_unknown_and_unlisted_files_are_trashed_only_once_named(self):
        unnamed = ("materials/notes.txt", "stuff/thing.bin", "materials/Bare__U2/U2.mat",
                   "code/Snippet__C1/versions/C1_9.txt", "colors/Old__K9/K9.png")
        self.fix_all(named=False)
        for path in unnamed:
            self.assertTrue(os.path.exists(self.at(*path.split("/"))), path + " went unnamed")
        self.assertFalse(os.path.exists(self.at("materials", "Brick__A1", "A1 2.png")),
                         "Amaze's own leftover stayed")
        self.fix_all(named=True)
        for path in unnamed:
            self.assertFalse(os.path.exists(self.at(*path.split("/"))), path + " stayed")

    def test_cl08_no_fix_runs_unless_chosen_and_cancel_changes_nothing(self):
        before = state(self.dir)
        for answers in ((), (0,)):    # Cancel at the report; Fix All, then Cancel at the named list
            houdini = Houdini(*answers)
            with mock.patch.object(check_dialog, "hou", houdini):
                self.assertFalse(check_dialog.show(self.dir))
            self.assertEqual(before, state(self.dir), answers)
            self.assertTrue(houdini.asked)

    def test_cl09_a_library_this_houdini_has_open_is_only_reported(self):
        prefs = self.prefs()
        library_db.use(prefs)
        library_db.document(prefs, MATERIALS)
        self.assertTrue(check_library.held_here(self.dir))
        before, houdini = state(self.dir), Houdini(0, 0)
        with mock.patch.object(check_dialog, "hou", houdini):
            check_dialog.run(prefs)
        self.assertEqual([("OK",)], [buttons for _text, buttons in houdini.asked])
        self.assertEqual(before, state(self.dir))

    def test_cl10_a_restore_brings_back_what_was_saved_after_the_backup(self):
        put(self.dir, "%s/%s.2026-11-01_090000.bak" % (guard.BACKUP_DIR, MATERIALS),
            {"assets": {"A1": {"name": "Brick", "categories": ["Walls"]}}})
        check_library.restore(self.dir, MATERIALS, "%s.2026-11-01_090000.bak" % MATERIALS, USER)
        rows = self.rows()
        self.assertEqual("Loose", rows["A3"]["name"], "an asset saved after the backup is lost")
        self.assertEqual("Found", rows["U1"]["name"])

    def test_cl11_a_rebuild_keeps_every_asset_whose_record_reads(self):
        put(self.dir, MATERIALS, b"{ not a database")
        check_library.rebuild(self.dir, MATERIALS, USER)
        rows = self.rows()
        self.assertEqual({"A1", "A3", "U1", "U2"}, set(rows))
        self.assertEqual(("Brick", "Found"), (rows["A1"]["name"], rows["U1"]["name"]))
        self.assertNotIn("N1", rows, "a node's record was read into Materials")

    def test_cl12_repairing_another_library_never_writes_the_open_one(self):
        other = tempfile.mkdtemp(prefix="amaze_check_open_")
        self.addCleanup(shutil.rmtree, other, True)
        lay_out(other)
        os.remove(os.path.join(other, "materials", "Loose__A3", "A3.mat"))
        shutil.rmtree(os.path.join(other, "materials", "Found__U1"))
        opened = Prefs(dir=other, library_user=USER)
        self.assertTrue(locations.register(opened, os.path.join(other, "gone")))
        library_db.use(opened)
        before = state(other)
        self.fix_all(named=True, prefs=opened)
        self.assertEqual(before, state(other))

    def test_cl13_only_the_file_sections_favorites_are_checked(self):
        prefs = self.prefs()
        here = os.path.join(self.dir, "import")
        self.assertTrue(locations.register(prefs, here))
        gone = os.path.join(here, "gone.png")
        self.assertTrue(locations.set_favourite(prefs, gone, True))
        self.assertTrue(locations.set_favourite(prefs, "A1", True, MATERIALS))
        self.assertEqual([gone], check_library.survey(self.dir, prefs)["favorites_gone"])
        check_library.fix_safe(self.dir, prefs, check_library.survey(self.dir, prefs), USER)
        self.assertEqual((False, True), (locations.is_favourite(prefs, gone),
                                         locations.is_favourite(prefs, "A1", MATERIALS)))

    def test_cl14_a_location_not_here_is_set_aside_with_its_annotations(self):
        prefs = self.prefs()
        folder, drive = os.path.join(self.dir, "import", "shots"), os.path.join(self.dir, "unplugged")
        os.makedirs(folder)
        for path in (folder, drive):
            self.assertTrue(locations.register(prefs, path))
        lid = locations.location_id(prefs, folder)
        self.assertTrue(locations.set_favourite(prefs, os.path.join(folder, "a.png"), True))
        shutil.rmtree(folder)
        real = check_library.hostos.volume_unreachable
        with mock.patch.object(check_library.hostos, "volume_unreachable",
                               lambda path: path == drive or real(path)):
            check_library.fix_safe(self.dir, prefs, check_library.survey(self.dir, prefs), USER)
        self.assertEqual([drive], locations.registered_paths(prefs), "the unplugged drive was set aside")
        self.assertEqual(lid, locations.location_id(prefs, folder), "the location's id was lost")
        os.makedirs(folder)
        self.assertTrue(locations.register(prefs, folder))
        self.assertTrue(locations.is_favourite(prefs, os.path.join(folder, "a.png")))

    def test_cl15_the_users_and_amazes_own_kept_files_are_never_leftovers_or_unknown(self):
        found = check_library.survey(self.dir)
        flagged = set(found["leftovers"]) | set(found["unknown"]) | set(found["orphans"])
        for kept in ("import/yarn.lock", "materials/Brick__A1/comments/%s.png" % ("a" * 32),
                     "files/comments/%s.png" % ("b" * 32),
                     "code/Snippet__C1/versions/C1_1.txt", "code/Snippet__C1/versions/versions.json",
                     "materials/Icon\r"):
            self.assertNotIn(kept, flagged)

    def test_cl16_code_and_colors_rows_are_never_checked_or_changed(self):
        found = check_library.survey(self.dir)
        self.assertNotIn(CODE, found["missing_files"])
        before = pathlib.Path(self.at(CODE)).read_bytes()
        self.fix_all(named=True)
        self.assertEqual(before, pathlib.Path(self.at(CODE)).read_bytes())


class WhatTheReportSaysTest(_Library):

    def test_cl20_the_report_gives_each_databases_trouble_and_a_shrunk_one(self):
        put(self.dir, NODES, b"{ not a database")
        put(self.dir, "%s/%s.2026-11-01_090000.bak" % (guard.BACKUP_DIR, MATERIALS),
            {"assets": {"B%d" % n: {"name": "b"} for n in range(10)}})
        lines = check_library.report_lines(check_library.survey(self.dir))
        self.assertTrue(any(line.startswith(check_library.messages.CHECK_DATABASE_CORRUPT % "Nodes")
                            for line in lines), lines)
        self.assertIn(check_library.messages.CHECK_DATABASE_SHRUNK % ("Materials", 3, 10), lines)

    def test_cl22_recover_names_each_folder_from_its_record_or_as_recovered(self):
        self.assertEqual(2, check_library.recover(self.dir, USER))
        rows = self.rows()
        self.assertEqual(("Found", ["Wood, Oak"]), (rows["U1"]["name"], rows["U1"]["categories"]))
        self.assertEqual(("Recovered U2", ["Recovered"]), (rows["U2"]["name"], rows["U2"]["categories"]))

    def test_cl23_a_sync_copy_is_a_leftover_only_when_it_matches_and_a_scratch_once_old(self):
        put(self.dir, "materials/Loose__A3/A3.png.y2" + guard.SCRATCH, b"a live write")
        found = check_library.survey(self.dir)
        self.assertIn("materials/Brick__A1/A1 2.png", found["leftovers"])
        self.assertIn(("materials/Brick__A1/A1 2.mat", "differs"), found["conflicts"])
        self.assertEqual(1, sum(1 for path in found["leftovers"] if path.endswith(guard.SCRATCH)))

    def test_cl24_a_version_file_its_ledger_does_not_list_is_an_orphan(self):
        found = check_library.survey(self.dir)["orphans"]
        self.assertIn("code/Snippet__C1/versions/C1_9.txt", found)
        self.assertNotIn("code/Snippet__C1/versions/C1_1.txt", found)

    def test_cl25_uncategorized_fills_rows_without_a_category_and_their_records(self):
        self.assertEqual(1, check_library.uncategorized(self.dir, USER))
        self.assertEqual(["Uncategorized"], self.rows()["A3"]["categories"])
        self.assertEqual(["Uncategorized"], asset_record.read(self.at(
            "materials", "Loose__A3", "A3.json"))[asset_record.METADATA]["categories"])


if __name__ == "__main__":
    unittest.main()
