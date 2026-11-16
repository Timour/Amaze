"""The guard: tickets, one-unit changes proven by stopping the disk at every step, backups, trash."""

import datetime
import json
import os
import shutil
import tempfile
import unittest

from amaze import branding
from amaze.core import guard
from amaze.helpers import hostos
from amaze.tests import test_support  # noqa: F401 - arms the sandbox for a run on its own

MATERIALS = "materials.json"
NODES = "nodes.json"


class Stop(Exception):
    """The disk died at the chosen step."""


class StoppingDisk(guard.Disk):
    """A real disk that dies at step `at`: before the step, or halfway through a write."""

    def __init__(self, at: int = 0, torn: bool = False) -> None:
        self.at, self.torn, self.steps, self.dead = at, torn, 0, False

    def _dies(self) -> bool:
        if self.dead:
            raise Stop()
        self.steps += 1
        self.dead = self.steps == self.at
        return self.dead

    def write(self, path, data):
        if self._dies():
            if self.torn:
                super().write(path, data[: len(data) // 2])
            raise Stop()
        super().write(path, data)

    def swap(self, scratch, target):
        if self._dies():
            raise Stop()
        super().swap(scratch, target)

    def move(self, source, target):
        if self._dies():
            raise Stop()
        super().move(source, target)

    def remove(self, path):
        if self._dies():
            raise Stop()
        super().remove(path)

    def remove_folder(self, path):
        if self._dies():
            raise Stop()
        super().remove_folder(path)


class Clock:
    """A clock a test moves by hand."""

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
    return {"assets": {"A%03d" % n: {"name": "%s %d" % (word, n)} for n in range(count)}}


class _Library(unittest.TestCase):
    """A small 2.0 library in a temp folder, a clock, and a guard on the real disk."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_guard_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.clock = Clock()
        self.lay_out(self.dir)
        self.guard = guard.Guard(self.dir, now=self.clock)

    def lay_out(self, folder: str) -> None:
        put(folder, guard.MASTER, {guard.MANIFEST: {MATERIALS: {"created": "x", "by": "u1"}},
                                   "users": {"u1": {"name": "Anna"}}})
        put(folder, MATERIALS, assets(6))
        put(folder, "materials/A001.mat", b"nodes of A001")
        put(folder, "materials/A001.json", b'{"metadata": {}}')
        put(folder, "materials/A002.mat", b"nodes of A002")
        put(folder, "materials/A003.png", b"picture of A003")

    def at(self, *parts) -> str:
        return os.path.join(self.dir, *parts)

    def save(self, name: str, document: dict, user: str = "u1") -> dict:
        reading = self.guard.read(name)
        change = self.guard.change(user)
        change.put(reading.ticket, document)
        return change.commit()


class StoppedAtEveryStepTest(unittest.TestCase):
    """Each operation, stopped at each step in turn: the library reopens all old or all new."""

    OPERATIONS = ("one_database", "a_new_database", "many_files", "a_restore", "a_taken_file")

    def one_database(self, g):
        reading = g.read(MATERIALS)
        change = g.change("u1")
        change.put(reading.ticket, assets(7, "stone"))
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

    def library(self) -> str:
        folder = tempfile.mkdtemp(prefix="amaze_guard_stop_")
        self.addCleanup(shutil.rmtree, folder, True)
        _Library.lay_out(self, folder)
        put(folder, "backup/%s.2026-11-01_090000.bak" % MATERIALS, assets(5, "older"))
        return folder

    def run_one(self, operation: str, disk) -> str:
        folder = self.library()
        clock = Clock()
        try:
            getattr(self, operation)(guard.Guard(folder, disk=disk, now=clock))
        except Stop:
            pass
        return folder

    def test_the_library_is_whole_after_any_stop(self):
        for operation in self.OPERATIONS:
            before = state(self.library())
            counting = StoppingDisk()
            after = state(self.run_one(operation, counting))
            self.assertNotEqual(before, after, "%s changed nothing" % operation)
            self.assertGreater(counting.steps, 0)
            for torn in (False, True):
                for step in range(1, counting.steps + 1):
                    folder = self.run_one(operation, StoppingDisk(step, torn))
                    reopened = guard.Guard(folder, now=Clock())
                    found = state(folder)
                    where = "%s stopped at step %d of %d%s" % (
                        operation, step, counting.steps, " mid-write" if torn else "")
                    self.assertIn(found, (before, after), where + ": neither old nor new")
                    self.assertFalse(os.path.exists(os.path.join(folder, guard.JOURNAL)), where)
                    for reading in reopened.health():
                        self.assertIn(reading.verdict, (guard.FINE, guard.FRESH),
                                      "%s: %s reads %s" % (where, reading.name, reading.verdict))

    def test_a_stop_after_the_journal_lands_gives_the_new_state(self):
        before = state(self.library())
        counting = StoppingDisk()
        after = state(self.run_one("many_files", counting))
        last = self.run_one("many_files", StoppingDisk(counting.steps))
        self.assertTrue(os.path.exists(os.path.join(last, guard.JOURNAL)),
                        "the last step is the journal's removal, so it should still be there")
        self.assertTrue(guard.Guard(last, now=Clock()).recover() is False)
        self.assertEqual(after, state(last))
        self.assertNotEqual(before, after)


class NoTicketNoWriteTest(_Library):
    """Only a database that read fine, or is new, can be written."""

    def test_a_corrupt_database_gives_no_ticket_and_keeps_one_copy(self):
        put(self.dir, MATERIALS, b'{"assets": {"A001": ')
        reading = self.guard.read(MATERIALS)
        self.assertEqual((guard.CORRUPT, None, None), (reading.verdict, reading.ticket,
                                                       reading.document))
        self.guard.read(MATERIALS)
        kept = [name for name in os.listdir(self.at(guard.BACKUP_DIR))
                if guard.UNREADABLE_MARK in name]
        self.assertEqual(1, len(kept), "one copy per content, however often it is read")
        change = self.guard.change("u1")
        with self.assertRaises(guard.Refused):
            change.put(reading.ticket, assets(1))
        self.assertEqual(b'{"assets": {"A001": ', open(self.at(MATERIALS), "rb").read())

    def test_an_empty_file_is_corrupt_and_is_not_copied(self):
        put(self.dir, MATERIALS, b"")
        self.assertEqual(guard.CORRUPT, self.guard.read(MATERIALS).verdict)
        self.assertFalse(os.path.isdir(self.at(guard.BACKUP_DIR)))

    def test_a_section_that_is_no_table_is_corrupt(self):
        put(self.dir, MATERIALS, {"assets": ["a", "list"]})
        reading = self.guard.read(MATERIALS)
        self.assertEqual(guard.CORRUPT, reading.verdict)
        self.assertIn("assets", reading.why)

    def test_a_newer_format_is_shown_and_not_written(self):
        put(self.dir, MATERIALS, dict(assets(2), format=branding.LIBRARY_FORMAT + 1))
        reading = self.guard.read(MATERIALS)
        self.assertEqual(guard.NEWER, reading.verdict)
        self.assertEqual(2, len(reading.document["assets"]))
        self.assertIsNone(reading.ticket)

    def test_missing_and_listed_in_the_manifest_is_not_a_fresh_start(self):
        os.remove(self.at(MATERIALS))
        reading = self.guard.read(MATERIALS)
        self.assertEqual((guard.MISSING, None), (reading.verdict, reading.ticket))

    def test_only_the_manifest_says_a_database_existed(self):
        put(self.dir, "backup/%s.2026-11-01_090000.bak" % NODES, assets(3))
        self.assertEqual(guard.FRESH, self.guard.read(NODES).verdict,
                         "a backup file was taken as proof where the manifest names nothing")

    def test_a_missing_master_beside_other_databases_is_known(self):
        os.remove(self.at(guard.MASTER))
        self.assertEqual(guard.MISSING, self.guard.read(guard.MASTER).verdict)

    def test_absent_and_unknown_is_fresh_and_writable(self):
        reading = self.guard.read(NODES)
        self.assertEqual(guard.FRESH, reading.verdict)
        self.assertTrue(reading.writable)

    def test_a_verdict_is_judged_again_at_the_next_read(self):
        good = open(self.at(MATERIALS), "rb").read()
        put(self.dir, MATERIALS, b"not json")
        self.assertEqual(guard.CORRUPT, self.guard.read(MATERIALS).verdict)
        put(self.dir, MATERIALS, good)
        reading = self.guard.read(MATERIALS)
        self.assertEqual(guard.FINE, reading.verdict)
        self.assertTrue(reading.writable)

    def test_an_unknown_name_is_refused(self):
        with self.assertRaises(guard.Refused):
            self.guard.read("library.json")

    def test_a_database_is_never_written_as_a_plain_file(self):
        change = self.guard.change("u1")
        with self.assertRaises(guard.Refused):
            change.put_file(MATERIALS, b"{}")


class AChangeMeetsTheFileAsItIsTest(_Library):

    def test_a_file_changed_since_the_read_refuses_the_write(self):
        reading = self.guard.read(MATERIALS)
        theirs = put(self.dir, MATERIALS, assets(9, "theirs"))
        change = self.guard.change("u1")
        change.put(reading.ticket, assets(1, "ours"))
        with self.assertRaises(guard.Moved):
            change.commit()
        self.assertEqual(guard.encode(assets(9, "theirs")), open(theirs, "rb").read())

    def test_a_database_that_appeared_refuses_a_fresh_ticket(self):
        reading = self.guard.read(NODES)
        put(self.dir, NODES, assets(2, "theirs"))
        change = self.guard.change("u1")
        change.put(reading.ticket, assets(1, "ours"))
        with self.assertRaises(guard.Moved):
            change.commit()

    def test_an_identical_save_touches_nothing(self):
        counting = StoppingDisk()
        watched = guard.Guard(self.dir, disk=counting, now=self.clock)
        reading = watched.read(MATERIALS)
        change = watched.change("u1")
        change.put(reading.ticket, reading.document)
        self.assertEqual({}, change.commit())
        self.assertEqual(0, counting.steps)

    def test_the_new_ticket_writes_again_without_a_read(self):
        tickets = self.save(MATERIALS, assets(2, "first"))
        change = self.guard.change("u1")
        change.put(tickets[MATERIALS], assets(3, "second"))
        change.commit()
        self.assertEqual(3, len(self.guard.read(MATERIALS).document["assets"]))

    def test_a_new_database_is_named_in_the_manifest_by_the_same_change(self):
        self.save(NODES, assets(2, "node"))
        manifest = self.guard.read(guard.MASTER).document[guard.MANIFEST]
        self.assertEqual("u1", manifest[NODES]["by"])
        os.remove(self.at(NODES))
        self.assertEqual(guard.MISSING, self.guard.read(NODES).verdict)

    def test_no_database_is_added_to_a_master_that_does_not_read(self):
        put(self.dir, guard.MASTER, b"broken")
        change = self.guard.change("u1")
        change.put(self.guard.read(NODES).ticket, assets(1))
        with self.assertRaises(guard.Refused):
            change.commit()
        self.assertFalse(os.path.exists(self.at(NODES)))

    def test_a_path_out_of_the_library_is_refused_and_nothing_is_written(self):
        before = state(self.dir)
        change = self.guard.change("u1")
        change.put_file("materials/ok.mat", b"fine")
        change.put_file("../outside.mat", b"escaped")
        with self.assertRaises(hostos.PathEscape):
            change.commit()
        self.assertEqual(before, state(self.dir))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.dir), "outside.mat")))


class BackupsTest(_Library):
    """A backup is the old bytes, spaced, never a repeat, and pruned to the rule."""

    def stamps(self) -> list:
        return [when.strftime("%m-%d %H:%M") for _name, when in self.guard.backups(MATERIALS)]

    def test_the_first_replace_backs_up_exactly_the_old_bytes(self):
        old = open(self.at(MATERIALS), "rb").read()
        self.save(MATERIALS, assets(2, "new"))
        name, _when = self.guard.backups(MATERIALS)[0]
        self.assertEqual(old, open(self.at(guard.BACKUP_DIR, name), "rb").read())

    def test_saves_close_together_make_one_backup(self):
        self.save(MATERIALS, assets(2, "one"))
        self.clock.forward(minutes=5)
        self.save(MATERIALS, assets(2, "two"))
        self.assertEqual(1, len(self.guard.backups(MATERIALS)))
        self.clock.forward(minutes=40)
        self.save(MATERIALS, assets(2, "three"))
        self.assertEqual(2, len(self.guard.backups(MATERIALS)))

    def test_content_the_newest_backup_already_holds_is_not_backed_up_again(self):
        first = self.guard.read(MATERIALS).document
        self.save(MATERIALS, assets(2, "changed"))
        self.clock.forward(hours=1)
        self.save(MATERIALS, first)
        self.clock.forward(hours=1)
        self.save(MATERIALS, assets(2, "changed"))
        self.clock.forward(hours=1)
        self.save(MATERIALS, first)
        self.assertEqual(3, len(self.guard.backups(MATERIALS)))

    def test_the_newest_three_and_one_a_day_for_thirty_days_are_kept(self):
        for day in range(40):
            for hour in (0, 2, 4):
                self.save(MATERIALS, assets(2, "day %d hour %d" % (day, hour)))
                self.clock.forward(hours=2)
            self.clock.forward(hours=18)
        kept = self.guard.backups(MATERIALS)
        newest = [when for _name, when in kept[:3]]
        self.assertEqual(1, len({when.date() for when in newest}), "the newest three are one day's")
        days = [when.date() for _name, when in kept]
        self.assertEqual(len(set(days)) + 2, len(days), "one a day, plus the newest day's other two")
        oldest = (self.clock.at.date() - min(days)).days
        self.assertLessEqual(oldest, guard.DAILY_BACKUP_DAYS)
        self.assertGreaterEqual(len(set(days)), guard.DAILY_BACKUP_DAYS - 1)

    def test_a_database_under_half_of_its_backup_is_reported_shrunk(self):
        self.save(MATERIALS, assets(12))
        self.clock.forward(hours=1)
        self.save(MATERIALS, assets(2))
        self.assertEqual((2, 12), self.guard.read(MATERIALS).shrunk)
        self.clock.forward(hours=1)
        self.save(MATERIALS, assets(11))
        self.assertIsNone(self.guard.read(MATERIALS).shrunk)


class RestoreTest(_Library):

    def test_a_backup_goes_back_and_what_was_there_is_kept_to_undo(self):
        old = open(self.at(MATERIALS), "rb").read()
        self.save(MATERIALS, assets(2, "mistake"))
        mistake = open(self.at(MATERIALS), "rb").read()
        self.clock.forward(minutes=1)
        self.guard.restore(MATERIALS, self.guard.backups(MATERIALS)[0][0])
        self.assertEqual(old, open(self.at(MATERIALS), "rb").read())
        undo = [name for name, _when in self.guard.backups(MATERIALS)
                if name.endswith(guard.UNDO_TAIL)]
        self.assertEqual(1, len(undo))
        self.assertEqual(mistake, open(self.at(guard.BACKUP_DIR, undo[0]), "rb").read())

    def test_a_restore_writes_over_a_corrupt_database(self):
        self.save(MATERIALS, assets(2, "good"))
        put(self.dir, MATERIALS, b"ruined")
        self.guard.restore(MATERIALS, self.guard.backups(MATERIALS)[0][0])
        self.assertEqual(guard.FINE, self.guard.read(MATERIALS).verdict)

    def test_what_is_no_backup_or_cannot_be_read_is_refused(self):
        with self.assertRaises(guard.Refused):
            self.guard.restore(MATERIALS, "materials.json")
        put(self.dir, "backup/%s.2026-11-01_090000.bak" % MATERIALS, b"not json")
        before = open(self.at(MATERIALS), "rb").read()
        with self.assertRaises(guard.Refused):
            self.guard.restore(MATERIALS, "%s.2026-11-01_090000.bak" % MATERIALS)
        self.assertEqual(before, open(self.at(MATERIALS), "rb").read())


class TrashTest(_Library):

    def trash(self, relative: str) -> None:
        change = self.guard.change("u1")
        change.trash(relative)
        change.commit()

    def test_a_trashed_file_keeps_its_path_under_the_day(self):
        self.trash("materials/A003.png")
        self.assertFalse(os.path.exists(self.at("materials", "A003.png")))
        landed = self.at(guard.TRASH_DIR, "2026-11-16", "materials", "A003.png")
        self.assertEqual(b"picture of A003", open(landed, "rb").read())

    def test_a_second_file_of_the_same_name_gets_a_number(self):
        self.trash("materials/A003.png")
        put(self.dir, "materials/A003.png", b"another")
        self.trash("materials/A003.png")
        day = self.at(guard.TRASH_DIR, "2026-11-16", "materials")
        self.assertEqual(["A003 2.png", "A003.png"], sorted(os.listdir(day)))

    def test_days_older_than_the_days_kept_are_removed(self):
        self.trash("materials/A003.png")
        self.clock.forward(days=guard.TRASH_DAYS - 1)
        self.assertEqual(0, self.guard.expire_trash())
        self.clock.forward(days=2)
        self.assertEqual(1, self.guard.expire_trash())
        self.assertEqual([], os.listdir(self.at(guard.TRASH_DIR)))

    def test_a_folder_goes_whole_and_the_trash_counts_what_it_holds(self):
        put(self.dir, "materials/versions/A001/1.mat", b"first")
        put(self.dir, "materials/versions/A001/versions.json", b"{}")
        self.trash("materials/versions/A001")
        self.assertFalse(os.path.exists(self.at("materials", "versions", "A001")))
        held = self.guard.trash_held()
        self.assertEqual(2, held["files"])
        self.assertEqual([("2026-11-16", "2026-12-17", 2, 7)], held["days"])


class TakenFileTest(_Library):
    """A file Houdini already wrote lands with the rest of a change, or not at all."""

    def test_a_scratch_inside_the_library_is_moved_into_place(self):
        written = put(self.dir, "materials/A007.mat.h" + guard.SCRATCH, b"from Houdini")
        change = self.guard.change("u1")
        change.put(self.guard.read(MATERIALS).ticket, assets(8))
        change.take("materials/A007.mat", written)
        change.commit()
        self.assertEqual(b"from Houdini", open(self.at("materials", "A007.mat"), "rb").read())
        self.assertFalse(os.path.exists(written))

    def test_a_file_outside_the_library_is_copied_in_and_left_alone(self):
        outside = tempfile.mkdtemp(prefix="amaze_guard_out_")
        self.addCleanup(shutil.rmtree, outside, True)
        written = put(outside, "A007.mat", b"from a temp folder")
        change = self.guard.change("u1")
        change.take("materials/A007.mat", written)
        change.commit()
        self.assertEqual(b"from a temp folder",
                         open(self.at("materials", "A007.mat"), "rb").read())
        self.assertTrue(os.path.exists(written))

    def test_a_moved_database_takes_no_file_either(self):
        written = put(self.dir, "materials/A007.mat.h" + guard.SCRATCH, b"from Houdini")
        reading = self.guard.read(MATERIALS)
        put(self.dir, MATERIALS, assets(9, "peer"))
        change = self.guard.change("u1")
        change.put(reading.ticket, assets(8))
        change.take("materials/A007.mat", written)
        with self.assertRaises(guard.Moved):
            change.commit()
        self.assertFalse(os.path.exists(self.at("materials", "A007.mat")))
        self.assertTrue(os.path.exists(written), "kept for the merge and the second try")

    def test_a_database_is_never_taken_as_a_file(self):
        with self.assertRaises(guard.Refused):
            self.guard.change("u1").take(MATERIALS, self.at("materials", "A001.mat"))


class HealthTest(_Library):

    def test_every_database_is_judged_in_one_report(self):
        put(self.dir, "code.json", b"{")
        put(self.dir, "colors.json", dict(assets(1), format=branding.LIBRARY_FORMAT + 3))
        found = {reading.name: reading.verdict for reading in self.guard.health()}
        self.assertEqual({guard.MASTER: guard.FINE, MATERIALS: guard.FINE, NODES: guard.FRESH,
                          "code.json": guard.CORRUPT, "colors.json": guard.NEWER,
                          "files.json": guard.FRESH}, found)

    def test_what_is_written_reads_back_as_written(self):
        self.save(MATERIALS, assets(4, "żółć"))
        document = self.guard.read(MATERIALS).document
        self.assertEqual("żółć 3", document["assets"]["A003"]["name"])
        self.assertEqual(branding.LIBRARY_FORMAT, document["format"])
        self.assertEqual(json.loads(open(self.at(MATERIALS), encoding="utf-8").read()), document)
