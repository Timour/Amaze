"""Library storage: one test per requirement in docs/requirements/library-storage.md."""

import datetime
import json
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

from amaze import branding
from amaze.actions import library as library_actions
from amaze.core import asset_record, category_conversion, documents, guard, library_db
from amaze.core import layout_conversion, library_files, library_policy, library_settings
from amaze.core import material, texstore, tile_icons
from amaze.core import versions
from amaze.helpers import hostos
from amaze.prefs import prefs as prefs_mod
from amaze.tests import faults, test_support

MATERIALS, NODES, CODE, COLORS = "materials.json", "nodes.json", "code.json", "colors.json"
ASSETS, STARS = "assets", "favorites"
ANNA, ERIK = "u-anna", "u-erik"


class Clock:
    """A fake clock that a test moves on with `forward`."""

    def __init__(self) -> None:
        self.at = datetime.datetime(2026, 11, 16, 10, 0, 0)

    def __call__(self):
        return self.at

    def forward(self, **how) -> None:
        self.at += datetime.timedelta(**how)


put, state = test_support.put, test_support.library_state


def assets(count: int, word: str = "brick") -> dict:
    return {ASSETS: {"A%03d" % n: {"name": "%s %d" % (word, n)} for n in range(count)}}


def lay_out(folder: str) -> None:
    """A small 2.0 library: its master, a materials database, and asset files of each kind."""
    put(folder, guard.MASTER, {guard.MANIFEST: {MATERIALS: {"created": "x", "by": "u1"}},
                               "users": {"u1": {"name": "Anna"}}})
    put(folder, MATERIALS, assets(6))
    put(folder, "materials/A001.mat", b"nodes of A001")
    put(folder, "materials/A001.json", b'{"metadata": {}}')
    put(folder, "materials/A002.mat", b"nodes of A002")
    put(folder, "materials/A003.png", b"picture of A003")


class _Library(unittest.TestCase):
    """A small library in a temp folder, a clock, and a guard on the real disk."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_storage_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.clock = Clock()
        lay_out(self.dir)
        self.guard = guard.Guard(self.dir, now=self.clock)

    def at(self, *parts) -> str:
        return os.path.join(self.dir, *parts)

    def bytes_of(self, *parts) -> bytes:
        with open(self.at(*parts), "rb") as handle:
            return handle.read()

    def save(self, name: str, document: dict, user: str = "u1") -> dict:
        change = self.guard.change(user)
        change.put(self.guard.read(name).ticket, document)
        return change.commit()

    def journal(self, steps) -> None:
        put(self.dir, guard.JOURNAL, json.dumps({"steps": steps}))


class CutOffTest(unittest.TestCase):
    """Each kind of change, cut off at each of its steps in turn."""

    def one_database(self, g):
        change = g.change("u1")
        change.put(g.read(MATERIALS).ticket, assets(7, "stone"))
        change.commit()

    def a_new_database(self, g):
        change = g.change("u1")
        change.put(g.read(NODES).ticket, assets(2, "node"))
        change.commit()

    def many_files(self, g):
        change = g.change("u1")
        change.put(g.read(MATERIALS).ticket, assets(3, "tile"))
        change.put_file("materials/A009.mat", b"nodes of A009")
        change.put_file("materials/A001.json", b'{"metadata": {"name": "new"}}')
        change.remove("materials/A002.mat")
        change.trash("materials/A003.png")
        change.commit()

    def a_restore(self, g):
        g.restore(MATERIALS, g.backups(MATERIALS)[0][0], "u1")

    def a_taken_file(self, g):
        written = put(g.dir, "materials/A009.mat.houdini" + guard.SCRATCH, b"nodes Houdini wrote")
        change = g.change("u1")
        change.put(g.read(MATERIALS).ticket, assets(7, "saved"))
        change.take("materials/A009.mat", written)
        change.put_file("materials/A009.json", b'{"metadata": {"name": "saved 6"}}')
        change.commit()

    def a_trashed_path_written_again(self, g):
        change = g.change("u1")
        change.trash("materials/A001.json")
        change.put_file("materials/A001.json", b'{"metadata": {"name": "written again"}}')
        change.put_file("materials/A009.mat", b"nodes of A009")
        change.commit()

    OPERATIONS = ("one_database", "a_new_database", "many_files", "a_restore", "a_taken_file",
                  "a_trashed_path_written_again")

    def library(self) -> str:
        folder = tempfile.mkdtemp(prefix="amaze_storage_cut_")
        self.addCleanup(shutil.rmtree, folder, True)
        lay_out(folder)
        put(folder, "backup/%s.2026-11-01_090000.bak" % MATERIALS, assets(5, "older"))
        return folder

    def run_one(self, operation: str, disk) -> str:
        folder = self.library()
        try:
            getattr(self, operation)(guard.Guard(folder, disk=disk, now=Clock()))
        except faults.Cut:
            pass
        return folder

    def test_ls01_a_write_cut_off_anywhere_leaves_every_file_old_or_new(self):
        for operation in self.OPERATIONS:
            before = state(self.library())
            counting = faults.FaultDisk()
            after = state(self.run_one(operation, counting))
            self.assertNotEqual(before, after, "%s changed nothing" % operation)
            for torn in (False, True):
                for step in range(1, counting.steps + 1):
                    folder = self.run_one(operation, faults.FaultDisk(cut_at=step, torn=torn))
                    reopened = guard.Guard(folder, now=Clock())
                    where = "%s cut at step %d of %d%s" % (
                        operation, step, counting.steps, " mid-write" if torn else "")
                    self.assertIn(state(folder), (before, after), where + ": neither old nor new")
                    for reading in reopened.health():
                        self.assertIn(reading.verdict, (guard.FINE, guard.FRESH),
                                      "%s: %s reads %s" % (where, reading.name, reading.verdict))

    def test_ls02_a_change_cut_off_halfway_is_finished_at_the_next_open(self):
        before = state(self.library())
        counting = faults.FaultDisk()
        after = state(self.run_one("many_files", counting))
        last = self.run_one("many_files", faults.FaultDisk(cut_at=counting.steps))
        self.assertTrue(os.path.exists(os.path.join(last, guard.JOURNAL)),
                        "the cut fell before the journal was removed, so the change is half done")
        guard.Guard(last, now=Clock())
        self.assertFalse(os.path.exists(os.path.join(last, guard.JOURNAL)))
        self.assertEqual(after, state(last))
        self.assertNotEqual(before, after)


PASTED = "a" * 32 + ".png"    # a picture pasted into a comment


def lay_out_2_0(folder: str) -> dict:
    """A 2.0 library: flat files, version stores, `matX/` folders and a comment picture, each shared."""
    put(folder, guard.MASTER, {"policy": {"library": {"version": library_policy.LAYOUT_2_0}}})
    shown = {"items": [{"t": "image", "src": "materials/comments/" + PASTED}]}
    put(folder, MATERIALS, {ASSETS: {
        "A1": {"name": "Brick", "textures": ["$AMAZELIB/matX/Brick__a1/textures/brick.png"]},
        "A2": {"name": "Brick Red", "textures": ["$AMAZELIB/matX/Brick__a1/textures/brick.png",
                                                 "$AMAZELIB/matX/Dl__x/textures/d.png"]}},
        "comments": {"A1": shown, "A2": shown}})
    put(folder, NODES, {ASSETS: {"N1": {"name": "Rig"}}})
    put(folder, CODE, {ASSETS: {"C1": {"name": "Loop"}}})
    put(folder, COLORS, {ASSETS: {"K1": {"name": "Sunset"}, "K2": {"name": "Plain"}}})
    files = {"materials/A1.mat": b"nodes of A1", "materials/A1.png": b"picture of A1",
             "materials/A2.mat": b"nodes of A2", "materials/versions/A1/A1_1.mat": b"A1 before",
             "nodes/N1.mat": b"nodes of N1", "matX/Brick__a1/textures/brick.png": b"brick",
             "matX/Dl__x/d.mtlx": b"<materialx/>", "matX/Dl__x/textures/d.png": b"d",
             "matX/Unused__z/textures/u.png": b"unused", "materials/comments/" + PASTED: b"pasted",
             "code/C1.png": b"picture of C1", "code/versions/C1/C1_1.txt": b"print(0)",
             "colors/K1.png": b"picture of K1"}
    for relative, data in files.items():
        put(folder, relative, data)
    return files


class ConversionTest(unittest.TestCase):
    """The 2.0 library converted to 3.0, and cut off at each of its steps."""

    def library(self) -> str:
        folder = tempfile.mkdtemp(prefix="amaze_storage_convert_")
        self.addCleanup(shutil.rmtree, folder, True)
        self.files = lay_out_2_0(folder)
        return folder

    def converted(self, folder: str, disk=None) -> dict:
        try:
            layout_conversion.convert(guard.Guard(folder, disk=disk, now=Clock()), "u1")
        except faults.Cut:
            pass
        return state(folder)

    def test_ls18_a_2_0_library_converts_whole_and_a_cut_off_conversion_finishes(self):
        counting = faults.FaultDisk()
        whole = self.converted(self.library(), counting)
        own = {path: data for path, data in whole.items() if not path.startswith("trash/")}
        self.assertEqual({
            "materials/Brick__A1/A1.mat": b"nodes of A1", "materials/Brick__A1/A1.png": b"picture of A1",
            "materials/Brick__A1/versions/A1_1.mat": b"A1 before",
            "materials/Brick__A1/textures/brick.png": b"brick",
            "materials/Brick Red__A2/A2.mat": b"nodes of A2",
            "materials/Brick Red__A2/textures/brick.png": b"brick",
            "materials/Brick Red__A2/textures/Dl__x/d.mtlx": b"<materialx/>",
            "materials/Brick Red__A2/textures/Dl__x/textures/d.png": b"d",
            "materials/Brick__A1/comments/" + PASTED: b"pasted",
            "materials/Brick Red__A2/comments/" + PASTED: b"pasted",
            "nodes/Rig__N1/N1.mat": b"nodes of N1",
            "code/Loop__C1/C1.png": b"picture of C1", "code/Loop__C1/versions/C1_1.txt": b"print(0)",
            "colors/Sunset__K1/K1.png": b"picture of K1"},
            {path: data for path, data in own.items() if path not in library_files.DATABASES})
        self.assertEqual([b"unused"], [found for path, found in whole.items() if path.startswith(
            "trash/") and path.endswith("matX/Unused__z/textures/u.png")])
        pages = json.loads(whole[MATERIALS])["comments"]
        self.assertEqual({texstore.OWN_PREFIX + "comments/" + PASTED}, {
            item["src"] for page in pages.values() for item in page["items"]})
        for step in range(1, counting.steps + 1):
            folder = self.library()
            cut = self.converted(folder, faults.FaultDisk(cut_at=step))
            self.assertLessEqual(set(self.files.values()), set(cut.values()),
                                 "a file was lost when the conversion was cut at step %d" % step)
            self.assertEqual(whole, self.converted(folder), "cut at step %d" % step)

    def test_ls19_a_2_0_library_is_not_opened_until_it_is_converted(self):
        self.assertTrue(layout_conversion.needs_conversion(self.library()))
        fresh = tempfile.mkdtemp(prefix="amaze_storage_3_")
        self.addCleanup(shutil.rmtree, fresh, True)
        self.assertTrue(prefs_mod.create_library(fresh))
        self.assertFalse(layout_conversion.needs_conversion(fresh), "a new library is 3.0")


WOOD_RED = "#aa5500"
BUILT = {"type": "subnet", "interface": "", "values": {}}
RECORDS = {"materials/Oak__A1/A1": ("Oak", "Wood"), "materials/Steel__A2/A2": ("Steel", "Metal"),
           "nodes/Rig__N1/N1": ("Rig", "Rigs")}


def by_name(document: dict) -> bytes:
    """A database or record as an Amaze before category ids wrote it, its format as given."""
    return (json.dumps(document, indent=1, sort_keys=True) + "\n").encode("utf-8")


def bytes_at(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def lay_out_by_name(folder: str) -> None:
    """A 3.0 library that names its categories, with a backup saved a minute before the clock."""
    put(folder, guard.MASTER, by_name({"format": 5, "policy": {"library": {
        "version": 5, "database": 5, "record": 1}}, "users": {"u1": {"name": "Anna"}}}))
    put(folder, MATERIALS, by_name({"format": 5, "categories": {
        "Metal": {"order": 0}, "Wood": {"order": 1, "color": WOOD_RED}, "Empty": {"order": 2}},
        ASSETS: {"A1": {"name": "Oak", "categories": ["Wood"]},
                 "A2": {"name": "Steel", "categories": ["Metal"]},
                 "A3": {"name": "Slate", "categories": ["Stone"]}}}))
    put(folder, NODES, by_name({"format": 5, "categories": {"Rigs": {"order": 0}},
                                ASSETS: {"N1": {"name": "Rig", "categories": ["Rigs"]}}}))
    for relative, (name, named) in RECORDS.items():
        put(folder, relative + ".mat", b"nodes of " + name.encode())
        put(folder, relative + ".json", by_name({"format": 1, "builder": BUILT, "metadata": {
            "name": name, "categories": [named]}}))
    put(folder, "backup/%s.2026-11-16_095900.bak" % MATERIALS, by_name({"format": 5}))


class CategoryIdsTest(unittest.TestCase):
    """A library whose categories are stored by name given ids, and cut off at each step."""

    def library(self) -> str:
        folder = tempfile.mkdtemp(prefix="amaze_storage_ids_")
        self.addCleanup(shutil.rmtree, folder, True)
        lay_out_by_name(folder)
        return folder

    def converted(self, folder: str, disk=None) -> dict:
        try:
            category_conversion.convert(guard.Guard(folder, disk=disk, now=Clock()), "u1")
        except faults.Cut:
            pass
        return state(folder)

    def test_ls21_converting_categories_to_ids_keeps_them_whole_and_finishes_when_cut_off(self):
        folder, key = self.library(), category_conversion.id_for
        old, counting = state(folder), faults.FaultDisk()
        whole = self.converted(folder, counting)
        lists = {name: json.loads(whole[name]) for name in (MATERIALS, NODES)}
        self.assertEqual({key("Metal"): ("Metal", 0, None), key("Wood"): ("Wood", 1, WOOD_RED),
                          key("Empty"): ("Empty", 2, None), key("Stone"): ("Stone", 3, None)}, {
            found: (entry["name"], entry["order"], entry.get("color"))
            for found, entry in lists[MATERIALS]["categories"].items()})
        self.assertEqual({"A1": "Wood", "A2": "Metal", "A3": "Stone", "N1": "Rigs"}, {
            asset_id: listed["categories"][row["categories"][0]]["name"]
            for listed in lists.values() for asset_id, row in listed[ASSETS].items()})
        for relative, (name, named) in RECORDS.items():
            self.assertEqual({"format": 2, "builder": BUILT, "category_names": {key(named): named},
                              "metadata": {"name": name, "categories": [key(named)]}},
                             json.loads(whole[relative + ".json"]), relative)
        self.assertEqual({path: data for path, data in old.items() if not path.endswith(".json")},
                         {path: data for path, data in whole.items() if not path.endswith(".json")})
        self.assertIn(old[MATERIALS], [bytes_at(os.path.join(folder, "backup", name))
                                       for name in os.listdir(os.path.join(folder, "backup"))],
                      "the list as it was is kept, however recent the last backup")
        for step in range(1, counting.steps + 1):
            folder = self.library()
            cut = self.converted(folder, faults.FaultDisk(cut_at=step))
            for path, data in old.items():
                self.assertIn(cut.get(path), (data, whole[path]),
                              "cut at step %d: %s" % (step, path))
            self.assertEqual(whole, self.converted(folder), "cut at step %d" % step)

    def test_ls22_an_older_amaze_does_not_open_a_library_with_category_ids(self):
        folder = self.library()
        test_support.with_fixture_user(folder)
        preferences = types.SimpleNamespace(dir=folder, library_user=test_support.FIXTURE_USER)
        self.addCleanup(library_db.release, preferences)
        self.assertTrue(library_actions.update(preferences))
        self.assertEqual(library_settings.THIS_AMAZE, library_settings.library_formats(folder))
        with mock.patch.object(library_policy, "LIBRARY_VERSION", library_policy.FORMAT_3_0[0]):
            self.assertEqual(library_settings.THIS_AMAZE[0], library_actions.newer_version(
                preferences), "an Amaze of format 3.0 would open it, and offer no update")
        with mock.patch.object(branding, "LIBRARY_FORMAT", library_policy.FORMAT_3_0[1]):
            self.assertEqual([guard.NEWER] * 2, [guard.Guard(folder).read(name).verdict
                                                 for name in (MATERIALS, NODES)])

    def test_ls23_a_list_or_record_by_name_from_an_older_amaze_gets_the_conversions_ids(self):
        folder = self.library()
        old = state(folder)
        whole = self.converted(folder)
        held = documents.Library(folder, "u1", now=Clock()).document(MATERIALS)
        record = os.path.join(folder, "materials", "Oak__A1", "A1.json")
        put(folder, MATERIALS, old[MATERIALS])    # synced back from an Amaze before ids
        put(folder, "materials/Oak__A1/A1.json", old["materials/Oak__A1/A1.json"])
        held.refresh()
        converted, key = json.loads(whole[MATERIALS]), category_conversion.id_for
        self.assertEqual({key(name) for name in ("Metal", "Wood", "Empty", "Stone")},
                         set(converted["categories"]), "premise: the conversion gave these ids")
        self.assertEqual((converted["categories"], converted[ASSETS]), (
            held.table("categories"), held.table(ASSETS)))
        self.assertEqual(([key("Wood")], {key("Wood"): "Wood"}), (
            asset_record.read(record)[asset_record.METADATA]["categories"],
            asset_record.read(record)[asset_record.NAMES]))
        backup = [name for name in os.listdir(os.path.join(folder, "backup"))
                  if bytes_at(os.path.join(folder, "backup", name)) == old[MATERIALS]]
        guard.Guard(folder, now=Clock()).restore(MATERIALS, backup[0], "u1")
        self.assertEqual(converted["categories"], guard.Guard(folder).read(MATERIALS).document[
            "categories"], "an old backup restored")


class LibraryFilesTest(_Library):
    """Requirements read and written at the level of the library's files."""

    def test_ls05_an_unreadable_database_is_never_written_over_and_one_copy_is_kept(self):
        for broken in (b'{"assets": {"A001": ', guard.encode({ASSETS: ["a", "list"]})):
            put(self.dir, MATERIALS, broken)
            reading = self.guard.read(MATERIALS)
            self.guard.read(MATERIALS)
            self.assertEqual((guard.CORRUPT, None), (reading.verdict, reading.ticket))
            kept = [name for name in os.listdir(self.at(guard.BACKUP_DIR))
                    if guard.UNREADABLE_MARK in name and broken[:8] in self.bytes_of(
                        guard.BACKUP_DIR, name)]
            self.assertEqual(1, len(kept), "one copy per content, however often it is read")
            document = documents.Library(self.dir, "u1", now=self.clock).document(MATERIALS)
            self.assertFalse(document.put(ASSETS, "A9", {"name": "lost"}))
            self.assertFalse(document.save(also=lambda change: change.put_file("x.mat", b"x")))
            self.assertEqual(broken, self.bytes_of(MATERIALS))
            self.assertFalse(os.path.exists(self.at("x.mat")))
        put(self.dir, NODES, b"")
        self.assertEqual(guard.CORRUPT, self.guard.read(NODES).verdict)
        self.assertFalse(any(name.startswith(NODES) for name in os.listdir(
            self.at(guard.BACKUP_DIR))), "an empty file is not worth a copy")

    def test_ls06_what_a_newer_amaze_saved_is_never_written_by_this_one(self):
        put(self.dir, MATERIALS, dict(assets(2), format=branding.LIBRARY_FORMAT + 1))
        reading = self.guard.read(MATERIALS)
        self.assertEqual((guard.NEWER, None, 2),
                         (reading.verdict, reading.ticket, len(reading.document[ASSETS])))
        document = documents.Library(self.dir, "u1", now=self.clock).document(MATERIALS)
        self.assertEqual("brick 1", document.get(ASSETS, "A001")["name"])
        self.assertFalse(document.put(ASSETS, "A001", {"name": "changed"}))
        self.journal([{"op": "move", "from": "materials/A003.png", "to": "trash/x/A003.png"},
                      {"op": "link", "from": "materials/A001.mat", "to": "materials/A011.mat"}])
        before = state(self.dir)
        held = guard.Guard(self.dir, now=self.clock)
        self.assertEqual(guard.HELD, held.read(NODES).verdict)
        change = held.change("u1")
        change.put_file("materials/A009.mat", b"nodes of A009")
        with self.assertRaises(OSError):
            change.commit()
        self.assertEqual(before, state(self.dir), "a newer Amaze's waiting change was touched")

    def test_ls07_a_database_that_is_gone_shows_missing_and_is_not_started_again(self):
        self.assertEqual(guard.FRESH, self.guard.read(NODES).verdict, "never there: a fresh start")
        put(self.dir, "backup/%s.2026-11-01_090000.bak" % NODES, assets(3))
        self.assertEqual(guard.FRESH, self.guard.read(NODES).verdict, "a backup alone proves nothing")
        self.save(NODES, assets(2, "node"))
        os.remove(self.at(NODES))
        self.assertEqual((guard.MISSING, None),
                         (self.guard.read(NODES).verdict, self.guard.read(NODES).ticket))
        document = documents.Library(self.dir, "u1", now=self.clock).document(MATERIALS)
        document.put(ASSETS, "A9", {"name": "mine"})
        os.remove(self.at(MATERIALS))
        saved = document.save()
        self.assertEqual((False, guard.MISSING), (saved.ok, saved.reason))
        self.assertFalse(os.path.exists(self.at(MATERIALS)), "it was made again from memory")
        put(self.dir, MATERIALS, assets(1))
        os.remove(self.at(guard.MASTER))
        self.assertEqual(guard.MISSING, self.guard.read(guard.MASTER).verdict,
                         "the master is known to have existed beside the other databases")
        older = tempfile.mkdtemp(prefix="amaze_storage_old_")
        self.addCleanup(shutil.rmtree, older, True)
        put(older, "code.json", {"format": 3, "assets": [{"id": "C1"}], "categories": ["_All"]})
        self.assertEqual(guard.FRESH, guard.Guard(older, now=Clock()).read(guard.MASTER).verdict,
                         "an older library's code.json does not prove a master existed")

    def test_ls08_backups_keep_the_newest_three_and_one_a_day_for_thirty_days(self):
        old = self.bytes_of(MATERIALS)
        self.save(MATERIALS, assets(2, "one"))
        name, _when = self.guard.backups(MATERIALS)[0]
        self.assertEqual(old, self.bytes_of(guard.BACKUP_DIR, name))
        self.clock.forward(minutes=5)
        self.save(MATERIALS, assets(2, "two"))
        self.assertEqual(1, len(self.guard.backups(MATERIALS)), "saves close together make one")
        self.clock.forward(minutes=40)
        self.save(MATERIALS, assets(2, "three"))
        self.assertEqual(2, len(self.guard.backups(MATERIALS)))
        for day in range(40):
            for hour in (0, 2, 4):
                self.save(MATERIALS, assets(2, "day %d hour %d" % (day, hour)))
                self.clock.forward(hours=2)
            self.clock.forward(hours=18)
        kept = self.guard.backups(MATERIALS)
        self.assertEqual(1, len({when.date() for _name, when in kept[:3]}),
                         "the newest three are one day's")
        days = [when.date() for _name, when in kept]
        self.assertEqual(len(set(days)) + 2, len(days), "one a day, plus the newest day's two")
        self.assertLessEqual((self.clock.at.date() - min(days)).days, guard.DAILY_BACKUP_DAYS)
        self.assertGreaterEqual(len(set(days)), guard.DAILY_BACKUP_DAYS - 1)

    def test_ls09_a_database_under_half_of_its_newest_backup_is_reported(self):
        self.save(MATERIALS, assets(12))
        self.clock.forward(hours=1)
        self.save(MATERIALS, assets(2))
        self.assertEqual((2, 12), self.guard.read(MATERIALS).shrunk)
        self.clock.forward(hours=1)
        self.save(MATERIALS, assets(11))
        self.assertIsNone(self.guard.read(MATERIALS).shrunk)

    def test_ls10_a_restore_keeps_the_file_it_replaces_as_an_undo_copy(self):
        old = self.bytes_of(MATERIALS)
        self.save(MATERIALS, assets(2, "mistake"))
        mistake = self.bytes_of(MATERIALS)
        self.clock.forward(minutes=1)
        self.guard.restore(MATERIALS, self.guard.backups(MATERIALS)[0][0], "u1")
        self.assertEqual(old, self.bytes_of(MATERIALS))
        undo = [name for name, _when in self.guard.backups(MATERIALS)
                if name.endswith(guard.UNDO_TAIL)]
        self.assertEqual(1, len(undo))
        self.assertEqual(mistake, self.bytes_of(guard.BACKUP_DIR, undo[0]))
        put(self.dir, "backup/%s.2026-11-01_090000.bak" % MATERIALS, b"not json")
        with self.assertRaises(guard.Refused):
            self.guard.restore(MATERIALS, "%s.2026-11-01_090000.bak" % MATERIALS, "u1")
        self.assertEqual(old, self.bytes_of(MATERIALS), "an unreadable backup replaced the file")

    def test_ls11_a_deleted_file_goes_to_the_days_trash_and_leaves_after_thirty_days(self):
        def trash(relative):
            change = self.guard.change("u1")
            change.trash(relative)
            change.commit()
        trash("materials/A003.png")
        self.assertFalse(os.path.exists(self.at("materials", "A003.png")))
        day = self.at(guard.TRASH_DIR, "2026-11-16", "materials")
        self.assertEqual(b"picture of A003", self.bytes_of(day, "A003.png"))
        put(self.dir, "materials/A003.png", b"another")
        trash("materials/A003.png")
        self.assertEqual(["A003 2.png", "A003.png"], sorted(os.listdir(day)))
        self.clock.forward(days=guard.TRASH_DAYS - 1)
        self.assertEqual(0, self.guard.expire_trash())
        self.clock.forward(days=2)
        self.assertEqual(1, self.guard.expire_trash())
        self.assertEqual([], os.listdir(self.at(guard.TRASH_DIR)))

    def test_ls12_nothing_is_written_moved_or_removed_outside_the_library(self):
        before = state(self.dir)
        change = self.guard.change("u1")
        change.put_file("materials/ok.mat", b"fine")
        change.put_file("../outside.mat", b"escaped")
        with self.assertRaises(hostos.PathOutsideBase):
            change.commit()
        self.assertEqual(before, state(self.dir))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.dir), "outside.mat")))
        self.journal([{"op": "remove", "to": "../outside"}])
        guard.Guard(self.dir, now=self.clock)
        self.assertFalse(os.path.exists(self.at(guard.JOURNAL)), "the journal was not set aside")
        self.assertEqual(guard.FINE, self.guard.read(MATERIALS).verdict)
        from amaze.core import notes
        prefs = types.SimpleNamespace(dir=self.dir, library_user="u1")
        shot = put(self.dir, "shot.png", b"pasted")
        before = state(self.dir)
        for unsafe in ("..", "../..", "../../outside", "a/b"):
            for path_of in (lambda: material.asset_dir(prefs, CODE, unsafe),
                            lambda: versions.versions_dir(prefs, unsafe),
                            lambda: material.payload_path(prefs, unsafe, ".mat", MATERIALS),
                            lambda: tile_icons.thumbnail_path(prefs, unsafe, COLORS)):
                with self.assertRaises(hostos.PathOutsideBase, msg=unsafe):
                    path_of()
            self.assertEqual("", notes.copy_image_into_library(prefs, shot, "material:" + unsafe))
        self.assertEqual(before, state(self.dir))

    def test_ls15_two_sessions_on_one_computer_never_write_at_the_same_moment(self):
        before = state(self.dir)
        change = self.guard.change("u1")
        change.put_file("materials/A009.mat", b"nodes of A009")
        with hostos.file_lock(self.at(guard.JOURNAL)) as other_session:
            self.assertTrue(other_session)
            with self.assertRaises(OSError):
                change.commit()
        self.assertEqual(before, state(self.dir))
        change.commit()
        self.assertEqual(b"nodes of A009", self.bytes_of("materials", "A009.mat"))

    def test_ls16_a_file_another_program_holds_delays_the_change_without_losing_it(self):
        disk = faults.FaultDisk(busy="materials/A002.mat")
        held = guard.Guard(self.dir, disk=disk, now=self.clock)
        before = state(self.dir)
        alone = held.change("u1")
        alone.remove("materials/A002.mat")
        with self.assertRaises(OSError):
            alone.commit()
        self.assertEqual(before, state(self.dir), "a one-file change failed and changed something")
        change = held.change("u1")
        change.put(held.read(MATERIALS).ticket, assets(3, "tile"))
        change.put_file("materials/A009.mat", b"nodes of A009")
        change.remove("materials/A002.mat")
        tickets = change.commit()
        self.assertTrue(change.waiting)
        self.assertEqual(guard.HELD, held.read(MATERIALS).verdict)
        disk.free = True
        reading = held.read(MATERIALS)
        self.assertEqual((guard.FINE, tickets[MATERIALS].raw), (reading.verdict, reading.ticket.raw))
        self.assertFalse(os.path.exists(self.at("materials", "A002.mat")))
        self.assertFalse(os.path.exists(self.at(guard.JOURNAL)))

    def test_ls17_a_failed_write_leaves_the_library_as_it_was_and_says_so(self):
        for full_from in (2, 3, 4):
            held = guard.Guard(self.dir, disk=faults.FaultDisk(full_from=full_from), now=self.clock)
            before = state(self.dir)
            change = held.change("u1")
            change.put(held.read(MATERIALS).ticket, assets(3, "tile"))
            change.put_file("materials/A009.mat", b"nodes of A009")
            change.put_file("materials/A010.mat", b"nodes of A010")
            with self.assertRaises(OSError):
                change.commit()
            scratches = [name for _root, _dirs, names in os.walk(self.dir)
                         for name in names if name.endswith(guard.SCRATCH)]
            self.assertEqual([], scratches, "write %d failed and left a scratch" % full_from)
            self.assertEqual(before, state(self.dir))
        library = documents.Library(self.dir, "u1", now=self.clock,
                                    disk=faults.FaultDisk(full_from=1))
        document = library.document(MATERIALS)
        document.put(ASSETS, "A9", {"name": "mine"})
        saved = document.save()
        self.assertEqual((False, documents.DENIED), (saved.ok, saved.reason))
        self.assertIn("No space", saved.detail)


class _TwoUsers(unittest.TestCase):
    """One library folder opened by two users, each in a session of their own."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_storage_two_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.now = datetime.datetime(2026, 11, 16, 10, 0, 0)
        seed = self.open(ANNA).document(MATERIALS)
        seed.put(ASSETS, "A1", {"name": "Brick", "tags": ["wall"], "renderer": "Karma"})
        seed.put(ASSETS, "A2", {"name": "Oak", "renderer": "Redshift"})
        self.assertTrue(seed.save())
        self.anna = self.open(ANNA).document(MATERIALS)
        self.erik = self.open(ERIK).document(MATERIALS)

    def open(self, user, **how) -> documents.Library:
        return documents.Library(self.dir, user, now=lambda: self.now, **how)

    def on_disk(self) -> dict:
        with open(os.path.join(self.dir, MATERIALS), encoding="utf-8") as handle:
            return json.load(handle)

    def both_save(self) -> dict:
        self.assertTrue(self.anna.save())
        self.assertTrue(self.erik.save())
        return self.on_disk()


class TwoSessionsTest(_TwoUsers):
    """Requirements on what two users or two sessions do to one database."""

    def test_ls03_a_save_never_overwrites_what_another_session_saved_since_its_read(self):
        self.anna.put(ASSETS, "A3", {"name": "Anna's"})
        self.erik.edit(ASSETS, "A1", renderer="Octane")
        saved = self.both_save()[ASSETS]
        self.assertEqual({"A1", "A2", "A3"}, set(saved))
        self.assertEqual("Octane", saved["A1"]["renderer"])
        disk = faults.FaultDisk()
        racing = self.open(ERIK, disk=disk).document(MATERIALS)
        racing.put(ASSETS, "E9", {"name": "Erik's"})
        disk.racing = MATERIALS
        outcome = racing.save()
        self.assertEqual((False, documents.MOVED), (outcome.ok, outcome.reason))
        self.assertNotIn("E9", self.on_disk()[ASSETS], "a save overwrote a file that kept changing")
        self.assertIn("R%d" % disk.races, self.on_disk()[ASSETS])

    def test_ls04_one_field_changed_by_two_users_keeps_one_and_names_the_other(self):
        self.anna.edit(ASSETS, "A1", name="Anna's name")
        self.erik.edit(ASSETS, "A1", name="Erik's name")
        self.assertEqual("Erik's name", self.both_save()[ASSETS]["A1"]["name"])
        self.assertEqual([documents.Collision(MATERIALS, ASSETS, "A1", "name", ANNA)],
                         self.erik.take_collisions())

    def test_ls30_with_no_user_selected_the_library_takes_no_change(self):
        nobody = self.open("").document(MATERIALS)
        self.assertFalse(nobody.put(ASSETS, "A9", {"name": "Ghost"}))
        self.assertFalse(nobody.put_mine(STARS, "A1", True))
        self.assertEqual(documents.UNCHANGED, nobody.save().reason)
        self.assertNotIn("A9", self.on_disk()[ASSETS])
        held, outside = guard.Guard(self.dir), tempfile.mkdtemp(prefix="amaze_storage_nobody_")
        self.addCleanup(shutil.rmtree, outside, True)
        for name, data in ((guard.MASTER, {"users": {}}), (MATERIALS, {ASSETS: {}})):
            put(self.dir, "%s/%s.2026-11-01_090000.bak" % (guard.BACKUP_DIR, name), data)
        before, own = state(self.dir), os.path.join(self.dir, "materials", "Brick__A1")
        change = held.change("")
        change.put_file("materials/Brick__A1/A1.mat", b"nodes")
        with self.assertRaises(guard.Refused):
            change.commit()
        with self.assertRaises(OSError):
            held.put_whole(os.path.join(own, "A1.png"), data=b"picture")
        prefs = types.SimpleNamespace(dir=self.dir, library_user="")
        self.assertEqual(0, versions.create_version(
            prefs, "A1", source_paths={".mat": put(outside, "A1.mat", b"nodes")}))
        with self.assertRaises(guard.Refused):
            held.restore(MATERIALS, "%s.2026-11-01_090000.bak" % MATERIALS)
        self.assertEqual(before, state(self.dir), "a write with no user changed the library")
        held.restore(guard.MASTER, "%s.2026-11-01_090000.bak" % guard.MASTER)    # its users list
        self.assertTrue(prefs_mod.create_library(outside), "a new library is set up with no user")

    def test_ls31_favorites_are_each_users_own_and_follow_their_file_moved_or_deleted(self):
        self.erik.put_mine(STARS, "A2", True)
        self.erik.put_mine(STARS, "old", True)
        self.assertTrue(self.erik.save())
        self.anna.put_mine(STARS, "A1", True)
        self.anna.put_mine(STARS, "A2", None)
        self.anna.put_mine(STARS, "old", True)
        self.assertTrue(self.anna.save())
        self.assertEqual({"A2": True, "old": True}, self.on_disk()[STARS][ERIK])
        self.assertEqual(2, self.anna.rekey_everyones(STARS, "old", "new"))
        self.assertEqual({ERIK: True}, self.anna.take_everyones(STARS, "A2"))
        self.assertTrue(self.anna.save())
        stars = self.on_disk()[STARS]
        self.assertEqual(({"A1": True, "new": True}, {"new": True}), (stars[ANNA], stars[ERIK]))

    def test_ls32_every_shared_entry_records_who_changed_it_last_and_when(self):
        entry = self.on_disk()[ASSETS]["A1"]
        self.assertEqual((ANNA, "2026-11-16_100000"), (entry[documents.BY], entry[documents.AT]))
        self.now += datetime.timedelta(hours=1)
        self.erik.edit(ASSETS, "A1", name="Red Brick")
        self.assertTrue(self.erik.save())
        entry = self.on_disk()[ASSETS]["A1"]
        self.assertEqual((ERIK, "2026-11-16_110000"), (entry[documents.BY], entry[documents.AT]))

    def test_ls33_what_another_session_saved_appears_without_a_restart(self):
        self.anna.edit(ASSETS, "A1", name="Changed")
        self.assertTrue(self.anna.save())
        self.assertTrue(self.erik.refresh())
        self.assertEqual("Changed", self.erik.get(ASSETS, "A1")["name"])
        self.assertFalse(self.erik.refresh(), "nothing changed on disk since")


class _Settings(unittest.TestCase):
    """A library reached the way the pane reaches it: through its preferences."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = tempfile.mkdtemp(prefix="amaze_storage_lib_") + os.sep
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.prefs = types.SimpleNamespace(dir=self.dir, library_user=test_support.FIXTURE_USER)
        prefs_mod.create_library(self.dir)
        test_support.with_fixture_user(self.dir)    # a library takes changes from its own users


class ThroughThePreferencesTest(_Settings):
    """Requirements met through `library_db` and `library_settings`."""

    def test_ls14_a_rows_changes_reach_its_record_in_the_same_save(self):
        record = os.path.join(material.claim_asset_dir(self.prefs, MATERIALS, "A1", "Brick"), "A1.json")
        put(os.path.dirname(record), "A1.json", asset_record.encode(
            {"format": asset_record.FORMAT, asset_record.METADATA: {"name": "old"}}))
        held = library_db.document(self.prefs, MATERIALS)
        held.put(ASSETS, "A1", {"name": "Brick", "renderer": "Karma"})
        library_db.flush(self.prefs)
        self.assertEqual({"name": "Brick", "renderer": "Karma"},
                         asset_record.read(record)[asset_record.METADATA])
        self.assertEqual("Brick", library_db.guard_of(self.prefs).read(
            MATERIALS).document[ASSETS]["A1"]["name"])

    def test_ls13_data_a_newer_amaze_wrote_is_kept_by_a_save(self):
        from amaze.core import notes
        newer = {"t": "sketch", "id": "s1", "author": ERIK, "strokes": [[0, 1]]}
        put(self.dir, MATERIALS, {"later": {"new": 1}, notes.SECTION: {"A1": {"items": [
            {"t": "text", "text": "one", "id": "t1", "author": ERIK}, newer,
            {"t": "todo", "label": "two", "id": "t2", "author": ERIK, "due": "12-01"}]}},
            ASSETS: {"A1": {"name": "Brick", "later_field": [1, 2]}, "A2": {"name": "Oak"}}})
        library_db.document(self.prefs, MATERIALS).edit(ASSETS, "A2", name="Touched")
        self.assertTrue(notes.set_note(self.prefs, notes.note_key("material", "A1"), [
            {"t": "text", "text": "one"}, {"t": "todo", "label": "two", "done": True}]))
        library_db.flush(self.prefs)
        after = library_db.guard_of(self.prefs).read(MATERIALS).document
        items = {item["id"]: item for item in after[notes.SECTION]["A1"]["items"]}
        self.assertEqual(({"new": 1}, [1, 2], "Touched"), (
            after["later"], after[ASSETS]["A1"]["later_field"], after[ASSETS]["A2"]["name"]))
        self.assertEqual((["t1", "s1", "t2"], newer, "12-01"),
                         (list(items), items.get("s1"), items["t2"].get("due")))

    def test_ls20_saving_over_an_asset_is_refused_when_the_policy_cannot_be_read(self):
        self.assertTrue(library_settings.allow_overwrite(self.prefs))
        self.assertTrue(library_settings.set_allow_overwrite(self.prefs, False))
        self.assertFalse(library_settings.allow_overwrite(self.prefs))
        self.assertTrue(library_settings.policy_readable(self.prefs),
                        "with Versions off, saving over is refused although the policy reads")
        test_support.reset_database_singletons()
        with open(os.path.join(self.dir, library_files.MASTER), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")
        self.assertFalse(library_settings.policy_readable(self.prefs))
        self.assertFalse(library_settings.allow_overwrite(self.prefs))
        self.assertFalse(library_settings.set_allow_overwrite(self.prefs, True))

    def test_ls34_the_library_records_this_amazes_format_and_shows_it_as_3_x(self):
        self.assertEqual((library_policy.LIBRARY_VERSION, branding.LIBRARY_FORMAT,
                          asset_record.FORMAT), library_settings.THIS_AMAZE,
                         "library_policy.py names a number the code does not write")
        self.assertTrue(prefs_mod.create_library(self.dir))
        self.assertEqual(library_settings.THIS_AMAZE, library_settings.library_formats(self.dir))
        self.assertEqual("3.3", library_settings.version_label(
            library_settings.library_formats(self.dir)), "category ids: three steps above 3.0")
        version, database, record = library_policy.FORMAT_3_0
        for found, shown in (((version, database + 1, record), "3.1"),
                             ((version + 1, database + 1, record + 2), "3.4"),
                             ((library_policy.LAYOUT_2_0, 0, 0), "2.0")):
            self.assertEqual(shown, library_settings.version_label(found), found)

    def test_ls36_each_asset_has_its_own_named_folder_and_a_rename_moves_it(self):
        own = material.claim_asset_dir(self.prefs, MATERIALS, "A1", "Brick")
        self.assertEqual(os.path.join(self.dir, "materials", "Brick__A1"), own)
        self.assertEqual((own, own, os.path.join(own, library_files.VERSIONS)), (
            os.path.dirname(material.payload_path(self.prefs, "A1", ".mat", MATERIALS)),
            os.path.dirname(tile_icons.thumbnail_path(self.prefs, "A1", MATERIALS)),
            versions.versions_dir(self.prefs, "A1")))
        put(own, "A1.mat", b"nodes of A1")
        put(own, "A1.json", asset_record.encode({"format": asset_record.FORMAT,
                                                 asset_record.METADATA: {"name": "Brick"}}))
        held = library_db.document(self.prefs, MATERIALS)
        held.put(ASSETS, "A1", {"name": "Stone"})
        self.assertTrue(library_db.save(self.prefs, MATERIALS))
        moved = os.path.join(self.dir, "materials", "Stone__A1")
        self.assertEqual((False, moved), (os.path.exists(own),
                                          material.asset_dir(self.prefs, MATERIALS, "A1")))
        self.assertEqual("Stone", asset_record.read(os.path.join(moved, "A1.json"))[
            asset_record.METADATA]["name"])
        snippets, row, snippet = self.snippet("Loop")
        loop = os.path.join(snippets.preferences.dir, "code", "Loop__" + snippet)
        self.assertEqual((False, os.path.join(loop, snippet + ".png")),
                         (os.path.exists(loop), snippets.capture_path(row)),
                         "a snippet has no folder before its first file, then one named for it")
        picture = self.pasted(snippets, snippet)
        self.assertEqual(os.path.join(loop, library_files.COMMENT_FOLDER), os.path.dirname(picture))
        self.assertTrue(snippets.save_from_editor(snippet, "print(2)", "Spin", "Python", "", ""))
        spin = os.path.join(snippets.preferences.dir, "code", "Spin__" + snippet)
        self.assertEqual((False, True), (os.path.exists(loop), os.path.isfile(
            os.path.join(spin, library_files.COMMENT_FOLDER, os.path.basename(picture)))))

    def snippet(self, name: str) -> tuple:
        """(the Code model on a fixture library, the row and the id of a new snippet `name`)."""
        from amaze.core import code_library
        model = code_library.CodeLibrary(preferences=test_support.fixture_prefs(self))
        model.add_asset("print(1)", name, "Python", "", "", False)
        row = next(row for row, asset in enumerate(model.assets) if asset.name == name)
        return model, row, str(model.assets[row].mat_id)

    def pasted(self, snippets, snippet: str) -> str:
        """A picture pasted into the snippet's comment: its first file; the picture's path."""
        from amaze.core import notes
        shot = put(tempfile.mkdtemp(prefix="amaze_storage_shot_"), "shot.png", b"pasted")
        self.addCleanup(shutil.rmtree, os.path.dirname(shot), True)
        key = notes.note_key("code", snippet)
        src = notes.copy_image_into_library(snippets.preferences, shot, key)
        return notes.image_path(snippets.preferences.dir, key, src)

    def test_ls39_deleting_an_asset_moves_its_whole_folder_to_the_trash(self):
        snippets, row, snippet = self.snippet("Loop")
        self.pasted(snippets, snippet)
        own = material.asset_dir(snippets.preferences, CODE, snippet)
        held = set(os.listdir(own))
        self.assertEqual(1, snippets.remove_rows([row]))
        self.assertFalse(os.path.exists(own))
        trashed = [os.path.join(root, name) for root, names, _files in os.walk(
            os.path.join(snippets.preferences.dir, guard.TRASH_DIR)) for name in names
            if name == os.path.basename(own)]
        self.assertEqual([held], [set(os.listdir(path)) for path in trashed])

    def test_ls40_a_comment_picture_is_kept_in_its_assets_folder_and_found_after_a_rename(self):
        from amaze.core import notes
        own = material.claim_asset_dir(self.prefs, MATERIALS, "A1", "Brick")
        put(own, "A1.mat", b"nodes of A1")
        held = library_db.document(self.prefs, MATERIALS)
        held.put(ASSETS, "A1", {"name": "Brick"})
        self.assertTrue(library_db.save(self.prefs, MATERIALS))
        shot = put(tempfile.mkdtemp(prefix="amaze_storage_shot_"), "shot.png", b"pasted")
        self.addCleanup(shutil.rmtree, os.path.dirname(shot), True)
        key = notes.note_key("material", "A1")
        src = notes.copy_image_into_library(self.prefs, shot, key)
        self.assertTrue(src.startswith(texstore.OWN_PREFIX + library_files.COMMENT_FOLDER + "/"), src)
        self.assertEqual(os.path.join(own, library_files.COMMENT_FOLDER),
                         os.path.dirname(notes.image_path(self.dir, key, src)))
        held.put(ASSETS, "A1", {"name": "Stone"})
        self.assertTrue(library_db.save(self.prefs, MATERIALS))
        found = notes.image_path(self.dir, key, src)
        self.assertEqual((os.path.join(self.dir, "materials", "Stone__A1"), b"pasted"),
                         (os.path.dirname(os.path.dirname(found)), open(found, "rb").read()))

    def test_ls37_a_saved_material_keeps_its_own_copy_of_each_texture(self):
        other = material.claim_asset_dir(self.prefs, MATERIALS, "B1", "Oak")
        shared = put(other, "textures/oak.png", b"oak grain")
        own = material.claim_asset_dir(self.prefs, MATERIALS, "A1", "Oak copy")
        token = texstore.copy_file_into_library(shared, self.prefs, own)
        self.assertEqual(texstore.OWN_PREFIX + "textures/oak.png", token)
        copy = texstore.resolve(token, self.prefs, own)
        self.assertEqual((os.path.join(own, "textures", "oak.png"), b"oak grain"),
                         (copy, open(copy, "rb").read()))
        self.assertEqual(token, texstore.copy_file_into_library(copy, self.prefs, own))

    def test_ls38_a_texture_path_of_the_2_0_layout_is_read_in_the_materials_folder(self):
        own = material.claim_asset_dir(self.prefs, MATERIALS, "A1", "Brick")
        kept = put(own, "textures/brick.png", b"brick")
        apart = put(own, "textures/Dl__x/textures/brick.png", b"another brick")
        self.assertEqual((kept, apart), tuple(texstore.resolve(
            "$AMAZELIB/matX/%s/textures/brick.png" % folder, self.prefs, own)
            for folder in ("Brick__a1", "Dl__x")))

    def test_ls35_shared_settings_hold_plain_values_one_per_name(self):
        self.assertTrue(library_settings.set_values(self.prefs, {"rendersize": 512,
                                                                 "geometry_bg": "grey"}))
        self.assertEqual({"rendersize": 512, "geometry_bg": "grey"},
                         library_settings.all_values(self.prefs))
        library_settings.clear(self.prefs, ["rendersize"])
        self.assertEqual("absent", library_settings.value_of(self.prefs, "rendersize", "absent"))
        with self.assertRaises(TypeError):
            library_settings.set_values(self.prefs, {"bad": [1, 2]})


if __name__ == "__main__":
    unittest.main()
