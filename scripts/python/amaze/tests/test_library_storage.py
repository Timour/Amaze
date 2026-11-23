"""Library storage: one test per requirement in docs/requirements/library-storage.md."""

import datetime
import json
import os
import shutil
import tempfile
import types
import unittest

from amaze import branding
from amaze.core import asset_record, documents, guard, library_db, library_files, library_policy
from amaze.core import library_settings
from amaze.helpers import hostos
from amaze.prefs import prefs as prefs_mod
from amaze.tests import faults, test_support

MATERIALS, NODES = "materials.json", "nodes.json"
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


def put(folder: str, relative: str, content) -> str:
    path = os.path.join(folder, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = content if isinstance(content, bytes) else (
        content.encode("utf-8") if isinstance(content, str) else guard.encode(content))
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def state(folder: str) -> dict:
    """Every file of the library and its bytes, without backups, scratches and the journal."""
    found = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            relative = os.path.relpath(os.path.join(root, name), folder).replace(os.sep, "/")
            if relative.startswith(guard.BACKUP_DIR + "/") or name.endswith(guard.SCRATCH):
                continue
            with open(os.path.join(root, name), "rb") as handle:
                found[relative] = handle.read()
    return found


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
        g.restore(MATERIALS, g.backups(MATERIALS)[0][0])

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
        self.guard.restore(MATERIALS, self.guard.backups(MATERIALS)[0][0])
        self.assertEqual(old, self.bytes_of(MATERIALS))
        undo = [name for name, _when in self.guard.backups(MATERIALS)
                if name.endswith(guard.UNDO_TAIL)]
        self.assertEqual(1, len(undo))
        self.assertEqual(mistake, self.bytes_of(guard.BACKUP_DIR, undo[0]))
        put(self.dir, "backup/%s.2026-11-01_090000.bak" % MATERIALS, b"not json")
        with self.assertRaises(guard.Refused):
            self.guard.restore(MATERIALS, "%s.2026-11-01_090000.bak" % MATERIALS)
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

    def test_ls13_data_a_newer_amaze_wrote_is_kept_by_a_save(self):
        raw = self.on_disk()
        raw["later"] = {"new": 1}
        raw[ASSETS]["A1"]["later_field"] = [1, 2]
        with open(os.path.join(self.dir, MATERIALS), "w", encoding="utf-8") as handle:
            json.dump(raw, handle)
        document = self.open(ANNA).document(MATERIALS)
        document.edit(ASSETS, "A2", name="Touched")
        self.assertTrue(document.save())
        after = self.on_disk()
        self.assertEqual(({"new": 1}, [1, 2]), (after["later"], after[ASSETS]["A1"]["later_field"]))

    def test_ls30_with_no_user_selected_the_library_takes_no_change(self):
        nobody = self.open("").document(MATERIALS)
        self.assertFalse(nobody.put(ASSETS, "A9", {"name": "Ghost"}))
        self.assertFalse(nobody.put_mine(STARS, "A1", True))
        self.assertEqual(documents.UNCHANGED, nobody.save().reason)
        self.assertNotIn("A9", self.on_disk()[ASSETS])

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


class ThroughThePreferencesTest(_Settings):
    """Requirements met through `library_db` and `library_settings`."""

    def test_ls14_a_rows_changes_reach_its_record_in_the_same_save(self):
        record = os.path.join(self.dir, library_files.SECTION_FOLDERS[MATERIALS], "A1.json")
        put(os.path.dirname(record), "A1.json", asset_record.encode(
            {"format": asset_record.FORMAT, asset_record.METADATA: {"name": "old"}}))
        held = library_db.document(self.prefs, MATERIALS)
        held.put(ASSETS, "A1", {"name": "Brick", "renderer": "Karma"})
        library_db.flush(self.prefs)
        self.assertEqual({"name": "Brick", "renderer": "Karma"},
                         asset_record.read(record)[asset_record.METADATA])
        self.assertEqual("Brick", library_db.guard_of(self.prefs).read(
            MATERIALS).document[ASSETS]["A1"]["name"])

    def test_ls20_saving_over_an_asset_is_refused_when_the_policy_cannot_be_read(self):
        self.assertTrue(library_settings.allow_overwrite(self.prefs))
        self.assertTrue(library_settings.set_allow_overwrite(self.prefs, False))
        self.assertFalse(library_settings.allow_overwrite(self.prefs))
        test_support.reset_database_singletons()
        with open(os.path.join(self.dir, library_files.MASTER), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")
        self.assertFalse(library_settings.allow_overwrite(self.prefs))
        self.assertFalse(library_settings.set_allow_overwrite(self.prefs, True))

    def test_ls34_the_library_records_this_amazes_format_and_shows_it_as_2_x(self):
        self.assertEqual((library_policy.LIBRARY_VERSION, branding.LIBRARY_FORMAT,
                          asset_record.FORMAT), library_settings.THIS_AMAZE,
                         "library_policy.py names a number the code does not write")
        self.assertTrue(prefs_mod.create_library(self.dir))
        self.assertEqual(library_policy.FORMAT_2_0, library_settings.library_formats(self.dir))
        self.assertEqual("2.0", library_settings.version_label(
            library_settings.library_formats(self.dir)))
        version, database, record = library_policy.FORMAT_2_0
        for found, shown in (((version, database + 1, record), "2.1"),
                             ((version + 1, database + 1, record + 2), "2.4"),
                             ((version - 1, 0, 0), "3")):
            self.assertEqual(shown, library_settings.version_label(found), found)

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
