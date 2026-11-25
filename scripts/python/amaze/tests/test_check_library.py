"""Check Library: one test per requirement in docs/requirements/check-library.md."""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

from amaze import messages  # noqa: E402
from amaze.core import asset_record, check_library, guard, library_db, library_files  # noqa: E402
from amaze.core import library_policy, locations, users  # noqa: E402
from amaze.tests import test_support  # noqa: E402

try:
    import hou
    HOUDINI = True
except ImportError:    # without Houdini: the dialog imports it, and every test here gives it a fake ui
    sys.modules["hou"] = hou = types.SimpleNamespace()
    HOUDINI = False
from amaze.dialogs import check_dialog  # noqa: E402

put, state = test_support.put, test_support.library_state
MATERIALS, NODES, CODE = library_files.MATERIALS, library_files.NODES, library_files.CODE
USER = test_support.FIXTURE_USER
WALLS, RIGS, EXAMPLES = ("c-walls", "Walls"), ("c-rigs", "Rigs"), ("c-examples", "Examples")
WOOD, METAL = ("c-wood-oak", "Wood, Oak"), ("c-metal", "Metal")    # categories by (id, name)
AUDIT = os.path.join(os.path.dirname(__file__), *[os.pardir] * 4, "tools", "library-audit.py")


def record(name: str, *categories) -> bytes:
    """An asset's record, its `categories` (id, name) pairs: their ids, their names beside."""
    found = {"format": asset_record.FORMAT, asset_record.METADATA: {
        "name": name, "categories": [key for key, _named in categories]}}
    return asset_record.encode(dict(found, **({asset_record.NAMES: dict(categories)}
                                               if categories else {})))


def listed(*categories) -> dict:
    return {key: {"name": named, "order": order} for order, (key, named) in enumerate(categories)}


def lay_out(folder: str) -> None:
    """A 3.0 library holding one of each thing Check Library reports, and things it must leave."""
    put(folder, guard.MASTER, {"policy": {"library": {"version": library_policy.LIBRARY_VERSION}},
                               "users": {USER: {"name": test_support.FIXTURE_USER_NAME}},
                               guard.MANIFEST: {name: {"created": "x", "by": ""}
                                                for name in (MATERIALS, NODES, CODE)}})
    put(folder, MATERIALS, {"assets": {"A1": {"name": "Brick", "categories": [WALLS[0]]},
                                       "A2": {"name": "Gone", "categories": [WALLS[0]]},
                                       "A3": {"name": "Loose"}},
                            "categories": listed(WALLS)})
    put(folder, NODES, {"assets": {"N1": {"name": "Rig", "categories": [RIGS[0]],
                                          "renderer": "LOP"}}, "categories": listed(RIGS)})
    put(folder, CODE, {"assets": {"C1": {"name": "Snippet", "categories": [EXAMPLES[0]]}},
                       "categories": listed(EXAMPLES)})
    for asset_id, name, categories in (("A1", "Brick", (WALLS,)), ("A3", "Loose", ())):
        for suffix, data in ((".mat", b"nodes"), (".json", record(name, *categories)),
                             (".png", b"picture")):
            put(folder, "materials/%s__%s/%s%s" % (name, asset_id, asset_id, suffix), data)
    put(folder, "nodes/Rig__N1/N1.mat", b"nodes")
    put(folder, "nodes/Rig__N1/N1.json", record("Rig", RIGS))
    put(folder, "materials/Found__U1/U1.mat", b"nodes")
    put(folder, "materials/Found__U1/U1.json", record("Found", WOOD))
    put(folder, "materials/Bare__U2/U2.mat", b"nodes")    # no record: it cannot be recovered
    put(folder, "materials/notes.txt", b"mine")    # a file Amaze does not write
    put(folder, "stuff/thing.bin", b"?")    # a folder Amaze does not write
    put(folder, "import/yarn.lock", b"the user's")
    put(folder, "materials/Brick__A1/comments/%s.png" % ("a" * 32), b"pasted")
    put(folder, "files/comments/%s.png" % ("b" * 32), b"pasted")
    put(folder, "colors/Old__K9/K9.png", b"picture")    # a color's folder no database lists
    put(folder, "materials/Icon\r", b"")
    put(folder, "materials/Brick__A1/versions/versions.json", json.dumps({"versions": [{"n": 1}]}))
    put(folder, "materials/Brick__A1/versions/A1_1.mat", b"first")
    put(folder, "materials/Brick__A1/versions/A1_9.mat", b"no ledger row")
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

    def named(self, name: str = MATERIALS) -> dict:
        """{row id: the names of its categories} of a database on disk."""
        document = guard.Guard(self.dir).read(name).document
        return {asset_id: [document["categories"][key]["name"] for key in row.get("categories", ())
                           if key in document["categories"]]
                for asset_id, row in document["assets"].items()}

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

    def test_cl07_unknown_files_and_unlisted_code_or_colors_folders_go_only_once_named(self):
        unnamed = ("materials/notes.txt", "stuff/thing.bin",
                   "materials/Brick__A1/versions/A1_9.mat", "colors/Old__K9/K9.png")
        shown = check_library.survey(self.dir)
        offered = {key[1] for key, _label in check_library.confirmable(shown)}
        self.assertNotIn("materials/Bare__U2", offered, "a folder Recover lists was offered")
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
            {"assets": {"A1": {"name": "Brick", "categories": [WALLS[0]]}},
             "categories": listed(WALLS)})
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
                     "materials/Brick__A1/versions/A1_1.mat", "materials/Brick__A1/versions/versions.json",
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

    def test_cl21_the_report_names_each_kind_of_finding_and_what_the_trash_holds(self):
        prefs, said = self.prefs(), check_library.messages
        gone, kept = self.at("import", "shots"), self.at("import")
        os.makedirs(gone)
        for path in (gone, kept):
            self.assertTrue(locations.register(prefs, path))
        self.assertTrue(locations.set_favourite(prefs, os.path.join(kept, "lost.png"), True))
        shutil.rmtree(gone)
        put(self.dir, "%s/2026-11-20/materials/old.png" % guard.TRASH_DIR, b"trashed")
        found = check_library.survey(self.dir, prefs)
        lines = check_library.report_lines(found)
        missing = [path for path in locations.registered_paths(prefs) if not os.path.isdir(path)]
        for line in (said.CHECK_ROWS_WITHOUT_FILES % ("Gone", "Materials", "has"),
                     said.CHECK_NO_CATEGORY % "1 material",
                     said.CHECK_UNLISTED_FOLDERS % ("3 asset folders", 1),
                     said.CHECK_LEFTOVERS_FOUND % "2 files", said.CHECK_CONFLICTS_KEPT % "1 copy",
                     said.CHECK_LOCATIONS_GONE % missing[0],
                     said.CHECK_FAVORITES_GONE % "1 favorite"):
            self.assertIn(line, lines)
        self.assertIn(said.CHECK_UNKNOWN_FOUND % "stuff and materials/notes.txt", lines)
        self.assertEqual(said.CHECK_TRASH_HOLDS % ("1 file", "7 bytes", "2026-12-21"),
                         check_library.trash_line(found))

    def test_cl22_fix_all_recovers_each_folder_from_its_record_or_as_recovered(self):
        self.assertEqual(2, self.fix_all(named=True)["recovered"])
        rows, named = self.rows(), self.named()
        self.assertEqual(("Found", [WOOD[0]], ["Wood, Oak"]),
                         (rows["U1"]["name"], rows["U1"]["categories"], named["U1"]))
        self.assertEqual(("Recovered U2", ["Recovered"]), (rows["U2"]["name"], named["U2"]))
        self.assertTrue(os.path.exists(self.at("materials", "Bare__U2", "U2.mat")), "it was trashed")
        put(self.dir, "nodes/Lost__N7/N7.mat", b"nodes")    # the one folder Recover can list, with no record
        houdini = Houdini()
        with mock.patch.object(check_dialog, "hou", houdini):
            check_dialog.show(self.dir)
        self.assertIn(check_library.messages.BUTTON_FIX_SAFE, houdini.asked[0][1], "no Fix Safe")

    def test_cl23_a_sync_copy_is_a_leftover_only_when_it_matches_and_a_scratch_once_old(self):
        put(self.dir, "materials/Loose__A3/A3.png.y2" + guard.SCRATCH, b"a live write")
        found = check_library.survey(self.dir)
        self.assertIn("materials/Brick__A1/A1 2.png", found["leftovers"])
        self.assertIn(("materials/Brick__A1/A1 2.mat", "differs"), found["conflicts"])
        self.assertEqual(1, sum(1 for path in found["leftovers"] if path.endswith(guard.SCRATCH)))

    def test_cl24_a_version_file_its_ledger_does_not_list_is_an_orphan(self):
        found = check_library.survey(self.dir)["orphans"]
        self.assertIn("materials/Brick__A1/versions/A1_9.mat", found)
        self.assertNotIn("materials/Brick__A1/versions/A1_1.mat", found)

    def test_cl25_uncategorized_fills_rows_without_a_category_and_their_records(self):
        self.assertEqual(1, check_library.uncategorized(self.dir, USER))
        key, = self.rows()["A3"]["categories"]
        found = asset_record.read(self.at("materials", "Loose__A3", "A3.json"))
        self.assertEqual((["Uncategorized"], [key], {key: "Uncategorized"}), (
            self.named()["A3"], found[asset_record.METADATA]["categories"],
            found[asset_record.NAMES]))

    def test_cl31_a_restore_or_a_rebuild_keeps_each_asset_in_its_records_category(self):
        put(self.dir, "materials/Steel__A4/A4.mat", b"nodes")    # saved after the backup, in Metal
        put(self.dir, "materials/Steel__A4/A4.json", record("Steel", METAL))
        put(self.dir, "%s/%s.2026-11-01_090000.bak" % (guard.BACKUP_DIR, MATERIALS),
            {"assets": {"A1": {"name": "Brick", "categories": [WALLS[0]]}},
             "categories": listed(WALLS)})
        check_library.restore(self.dir, MATERIALS, "%s.2026-11-01_090000.bak" % MATERIALS, USER)
        self.assertEqual({"A1": ["Walls"], "A3": [], "U1": ["Wood, Oak"], "A4": ["Metal"]},
                         self.named())
        put(self.dir, MATERIALS, b"{ not a database")
        check_library.rebuild(self.dir, MATERIALS, USER)
        self.assertEqual({"A1": ["Walls"], "A3": [], "U1": ["Wood, Oak"], "A4": ["Metal"],
                          "U2": ["Recovered"]}, self.named())

    def test_cl32_a_row_whose_category_is_not_listed_counts_as_none_and_fix_files_it(self):
        document = guard.Guard(self.dir).read(MATERIALS).document
        document["assets"]["A1"]["categories"] = ["c-gone"]    # its category is not in the list
        put(self.dir, MATERIALS, document)
        self.assertEqual([("A1", "Brick"), ("A3", "Loose")],
                         check_library.survey(self.dir)["no_category"][MATERIALS])
        check_library.fix_light(self.dir, USER)
        key, = self.rows()["A1"]["categories"]
        self.assertEqual((["Uncategorized"], ["Uncategorized"], {key: "Uncategorized"}), (
            self.named()["A1"], self.named()["A3"], asset_record.read(self.at(
                "materials", "Brick__A1", "A1.json"))[asset_record.NAMES]))

    def test_cl28_the_audit_tool_lists_what_does_not_belong_by_kind_and_changes_nothing(self):
        def whole():    # scratch files and backups too
            return {path: path.read_bytes() for path in pathlib.Path(self.dir).rglob("*")
                    if path.is_file()}

        before = whole()
        done = subprocess.run([test_support.plain_python(), "-I", AUDIT, self.dir],
                              capture_output=True, text=True, timeout=60)    # -I: no Amaze, no hou
        self.assertEqual(0, done.returncode, done.stderr)
        listed = {tuple(line.split(None, 1)) for line in done.stdout.splitlines()
                  if line.startswith("    ")}
        self.assertLessEqual({("unknown", "materials/notes.txt"), ("unknown", "stuff/"),
                              ("duplicate", "materials/Brick__A1/A1 2.png"),
                              ("scratch", "materials/Brick__A1/A1.mat.x1" + guard.SCRATCH)},
                             listed, done.stdout)
        self.assertEqual(before, whole())

    def test_cl29_a_folder_holding_only_scratch_or_nothing_is_a_leftover(self):
        spent = {"materials/Half__S1": ("S1.mat.x1", "textures/brick.png.x2"),
                 "nodes/Half__S2": ("S2.json.x3",), "materials/Bare__S3": ()}
        for folder, names in spent.items():
            os.makedirs(self.at(*folder.split("/")), exist_ok=True)
            for name in names:
                put(self.dir, "%s/%s%s" % (folder, name, guard.SCRATCH), b"a save cut off")
            old = time.time() - 2 * check_library.SCRATCH_MIN_AGE
            for here, _folders, files in os.walk(self.at(*folder.split("/")), topdown=False):
                for path in [os.path.join(here, name) for name in files] + [here]:
                    os.utime(path, (old, old))
        live = put(self.dir, "materials/Live__S4/S4.mat.x4" + guard.SCRATCH, b"another first save")
        self.fix_all(named=False)
        rows = set(self.rows()) | set(self.rows(NODES))
        self.assertFalse({"S1", "S2", "S3", "S4"} & rows, "a folder holding no asset became a row")
        for folder in spent:
            self.assertFalse(os.path.exists(self.at(*folder.split("/"))), folder + " stayed")
        trashed = pathlib.Path(self.at(guard.TRASH_DIR)).glob("*/materials/Half__S1/textures/*")
        self.assertTrue(list(trashed), "the folder did not go to the trash whole")
        self.assertTrue(os.path.exists(live), "a scratch younger than an hour was trashed")
        put(self.dir, MATERIALS, b"{ not a database")
        check_library.rebuild(self.dir, MATERIALS, USER)
        self.assertNotIn("S4", self.rows(), "a rebuild made a row of a folder holding no asset")


    def test_cl30_the_check_row_offers_fix_for_light_findings_and_repair_for_the_rest(self):
        light = tempfile.mkdtemp(prefix="amaze_check_light_")
        self.addCleanup(shutil.rmtree, light, True)
        put(light, guard.MASTER, {"policy": {"library": {"version": library_policy.LIBRARY_VERSION}},
                                  "users": {USER: {"name": test_support.FIXTURE_USER_NAME}},
                                  guard.MANIFEST: {MATERIALS: {"created": "x", "by": ""}}})
        put(light, MATERIALS, {"assets": {"A1": {"name": "Brick"}}})    # no category, its one finding
        put(light, "materials/Brick__A1/A1.mat", b"nodes")
        put(light, "materials/Brick__A1/A1.json", record("Brick"))
        prefs = Prefs(dir=light, library_user=USER)
        shown = check_library.summary(check_library.survey(light, prefs))
        self.assertTrue(shown["lines"], "premise: the check found the row with no category")
        self.assertEqual((check_library.UNCHECKED, check_library.FIX),
                         (shown["state"], shown["button"]), "a light finding was not offered Fix")
        check_library.fix_light(light, USER)
        shown = check_library.summary(check_library.survey(light, prefs))
        self.assertEqual((check_library.CLEAN, check_library.CHECK, []),
                         (shown["state"], shown["button"], shown["lines"]), "Fix left a finding")
        shown = check_library.summary(check_library.survey(self.dir, self.prefs()))
        self.assertEqual((check_library.FOUND, check_library.REPAIR), (shown["state"], shown["button"]))


@unittest.skipUnless(HOUDINI, "Houdini is not loaded")
class InThePaneTest(unittest.TestCase):
    """Repair as a pane on a fixture library offers it, and what the pane shows after a fix."""

    def setUp(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.pane = test_support.fixture_pane(self)

    def answering(self, *answers):
        """`hou.ui` answering each message with the next of `answers`; the buttons asked, kept."""
        self.asked, left = [], list(answers)

        def message(text, buttons=("OK",), **_how):
            self.asked.append(tuple(buttons))
            return left.pop(0) if left else len(buttons) - 1
        return mock.patch.object(hou, "ui", types.SimpleNamespace(displayMessage=message),
                                 create=True)

    def test_cl26_a_corrupt_materials_or_nodes_database_is_offered_repair_at_open_or_switch(self):
        other = test_support.seeded_library(self)
        users.create(types.SimpleNamespace(dir=other, library_user=""), "Sage", library=other)
        library_db.release(types.SimpleNamespace(dir=other))
        kept = guard.Guard(other).read(MATERIALS).document
        put(other, "%s/%s.2026-11-01_090000.bak" % (guard.BACKUP_DIR, MATERIALS), kept)
        put(other, MATERIALS, b"{ not a database")
        with self.answering(0, 0):    # Repair, then Restore Backup
            self.assertTrue(test_support.apply_library(self, types.SimpleNamespace(
                pane=self.pane), other, user="Sage"), "the switch did not open it")
        self.assertEqual([messages.BUTTONS_REPAIR_OR_CANCEL, messages.BUTTONS_RESTORE_OR_REBUILD],
                         self.asked)
        self.assertEqual(set(kept["assets"]), test_support.asset_ids(self.pane.material_model))
        put(other, NODES, b"{ not a database")
        opening = type(self.pane)(type(self.pane.ui)())    # a second pane, opening at start
        self.addCleanup(test_support.dispose_panel, opening)
        self.addCleanup(test_support.stop_panel_workers, types.SimpleNamespace(pane=opening))
        with self.answering(0, 0):    # Repair, then Rebuild: no backup
            opening.library.start()
            test_support.pump_until(lambda: opening.library.serves(other), 5)
        self.assertEqual([messages.BUTTONS_REPAIR_OR_OPEN_WITHOUT, messages.BUTTONS_REBUILD_ONLY],
                         self.asked)
        self.assertNotEqual(guard.CORRUPT, guard.Guard(other).read(NODES).verdict)

    def test_cl27_after_a_fix_the_pane_shows_the_library_as_it_is_now(self):
        from amaze.dialogs import prefs_window
        model, shown = self.pane.material_model, prefs_window.AmazePrefsState(
            self.pane.prefs, pane=self.pane)
        self.assertNotEqual(-1, model.find_asset_row_by_id("-1"), "premise: a row with no files")
        shown.checkOrRepair()    # Check
        with self.answering(0, 0):    # Repair runs Fix All, which removes the row it names
            shown.checkOrRepair()
        self.assertEqual(-1, model.find_asset_row_by_id("-1"), "the pane shows a removed row")
        self.assertEqual([], [asset.name for asset in model.assets if not asset.categories])

if __name__ == "__main__":
    unittest.main()
