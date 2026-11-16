"""Documents: a user's changes, two users merged, bursts as one save, refusals that hold."""

import datetime
import json
import os
import shutil
import tempfile
import unittest

from amaze.core import documents, guard

MATERIALS = "materials.json"
ASSETS, COMMENTS, STARS = "assets", "comments", "stars"
ANNA, ERIK = "u-anna", "u-erik"


class CountingDisk(guard.Disk):
    """A real disk that counts the reads and the swaps of one file name."""

    def __init__(self, name: str) -> None:
        self.name, self.reads, self.swaps = name, 0, 0

    def read(self, path):
        self.reads += os.path.basename(path) == self.name
        return super().read(path)

    def swap(self, scratch, target):
        self.swaps += os.path.basename(target) == self.name
        super().swap(scratch, target)


class _Two(unittest.TestCase):
    """One library folder opened by two users, each in a session of their own."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_documents_")
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

    def reread(self, user=ANNA) -> documents.Document:
        return self.open(user).document(MATERIALS)


class AChangeIsAUsersTest(_Two):

    def test_an_entry_records_who_changed_it_and_when(self):
        entry = self.on_disk()[ASSETS]["A1"]
        self.assertEqual((ANNA, "2026-11-16_100000"), (entry[documents.BY], entry[documents.AT]))
        self.now += datetime.timedelta(hours=1)
        self.erik.edit(ASSETS, "A1", name="Red Brick")
        self.assertTrue(self.erik.save())
        entry = self.on_disk()[ASSETS]["A1"]
        self.assertEqual((ERIK, "2026-11-16_110000", "Red Brick"),
                         (entry[documents.BY], entry[documents.AT], entry["name"]))

    def test_with_nobody_picked_nothing_changes_and_nothing_is_saved(self):
        nobody = self.open("").document(MATERIALS)
        self.assertFalse(nobody.put(ASSETS, "A9", {"name": "Ghost"}))
        self.assertFalse(nobody.put_mine(STARS, "A1", True))
        self.assertFalse(nobody.dirty)
        self.assertEqual(documents.UNCHANGED, nobody.save().reason)
        self.assertNotIn("A9", self.on_disk()[ASSETS])

    def test_the_user_is_asked_at_each_change(self):
        who = [""]
        document = documents.Library(self.dir, lambda: who[0], now=lambda: self.now).document(
            MATERIALS)
        self.assertFalse(document.put(ASSETS, "A9", {"name": "Too early"}))
        who[0] = ERIK
        self.assertTrue(document.put(ASSETS, "A9", {"name": "Picked"}))
        self.assertTrue(document.save())
        self.assertEqual(ERIK, self.on_disk()[ASSETS]["A9"][documents.BY])

    def test_storing_what_is_already_there_is_no_change(self):
        self.assertFalse(self.anna.put(ASSETS, "A2", {"name": "Oak", "renderer": "Redshift"}))
        self.assertFalse(self.anna.dirty)

    def test_a_section_is_changed_only_the_way_it_is_declared(self):
        with self.assertRaises(KeyError):
            self.anna.put(STARS, "A1", {"on": True})
        with self.assertRaises(KeyError):
            self.anna.put_mine(ASSETS, "A1", True)
        with self.assertRaises(TypeError):
            self.anna.put(ASSETS, "A1", "a bare text")


class TwoUsersAtOnceTest(_Two):
    """Both read the same file, both change it, both save: the second save merges."""

    def both_save(self) -> dict:
        self.assertTrue(self.anna.save())
        self.assertTrue(self.erik.save())
        return self.on_disk()

    def test_different_assets_are_both_kept(self):
        self.anna.put(ASSETS, "A3", {"name": "Anna's"})
        self.erik.put(ASSETS, "A4", {"name": "Erik's"})
        assets = self.both_save()[ASSETS]
        self.assertEqual({"A1", "A2", "A3", "A4"}, set(assets))
        self.assertEqual([], self.erik.take_collisions())

    def test_different_fields_of_one_asset_are_both_kept(self):
        self.anna.edit(ASSETS, "A1", name="Red Brick")
        self.erik.edit(ASSETS, "A1", renderer="Octane")
        entry = self.both_save()[ASSETS]["A1"]
        self.assertEqual(("Red Brick", "Octane"), (entry["name"], entry["renderer"]))
        self.assertEqual([], self.erik.take_collisions())

    def test_the_same_field_keeps_the_later_savers_and_names_the_other_user(self):
        self.anna.edit(ASSETS, "A1", name="Anna's name")
        self.erik.edit(ASSETS, "A1", name="Erik's name")
        self.assertEqual("Erik's name", self.both_save()[ASSETS]["A1"]["name"])
        self.assertEqual([documents.Collision(MATERIALS, ASSETS, "A1", "name", ANNA)],
                         self.erik.take_collisions())
        self.assertEqual([], self.erik.take_collisions(), "a collision is handed over once")

    def test_an_edit_outranks_a_removal(self):
        self.anna.drop(ASSETS, "A2")
        self.erik.edit(ASSETS, "A2", name="White Oak")
        self.assertEqual("White Oak", self.both_save()[ASSETS]["A2"]["name"])
        self.assertTrue(self.anna.refresh())
        self.assertEqual("White Oak", self.anna.get(ASSETS, "A2")["name"])

    def test_a_removal_of_what_the_other_left_alone_holds(self):
        self.anna.drop(ASSETS, "A2")
        self.erik.put(ASSETS, "A5", {"name": "New"})
        self.assertEqual({"A1", "A5"}, set(self.both_save()[ASSETS]))
        self.assertNotIn("A2", self.erik.table(ASSETS))

    def test_stars_never_collide(self):
        self.anna.put_mine(STARS, "A1", True)
        self.erik.put_mine(STARS, "A1", True)
        self.erik.put_mine(STARS, "A2", True)
        stars = self.both_save()[STARS]
        self.assertEqual({ANNA: {"A1": True}, ERIK: {"A1": True, "A2": True}}, stars)
        self.anna.refresh()
        self.anna.put_mine(STARS, "A1", None)
        self.assertTrue(self.anna.save())
        self.assertEqual({ERIK: {"A1": True, "A2": True}}, self.on_disk()[STARS])

    def test_a_user_never_writes_into_another_users_stars(self):
        self.erik.put_mine(STARS, "A2", True)
        self.assertTrue(self.erik.save())
        self.anna._data[STARS][ERIK] = {"A1": True}
        self.anna.put_mine(STARS, "A1", True)
        self.assertTrue(self.anna.save())
        self.assertEqual({"A2": True}, self.on_disk()[STARS][ERIK],
                         "what is on disk for another user is theirs alone")

    def test_two_users_comments_on_one_asset_are_both_kept(self):
        self.anna.put(COMMENTS, "A1", {"items": [{"id": "c1", "by": ANNA, "text": "Too red"}]})
        self.erik.put(COMMENTS, "A1", {"items": [{"id": "c2", "by": ERIK, "text": "I like it"}]})
        items = self.both_save()[COMMENTS]["A1"]["items"]
        self.assertEqual({"c1": "Too red", "c2": "I like it"},
                         {item["id"]: item["text"] for item in items})
        self.assertEqual([], self.erik.take_collisions())

    def test_a_removed_comment_stays_removed_while_another_is_added(self):
        self.anna.put(COMMENTS, "A1", {"items": [{"id": "c1", "text": "first"},
                                                 {"id": "c2", "text": "second"}]})
        self.assertTrue(self.anna.save())
        self.erik.refresh()
        self.anna.put(COMMENTS, "A1", {"items": [{"id": "c2", "text": "second"}]})
        self.erik.put(COMMENTS, "A1", {"items": [{"id": "c1", "text": "first"},
                                                 {"id": "c2", "text": "second"},
                                                 {"id": "c3", "text": "third"}]})
        items = self.both_save()[COMMENTS]["A1"]["items"]
        self.assertEqual(["c2", "c3"], sorted(item["id"] for item in items))

    def test_a_refresh_with_nothing_of_ours_takes_theirs_whole(self):
        self.anna.edit(ASSETS, "A1", name="Changed")
        self.assertTrue(self.anna.save())
        self.assertTrue(self.erik.refresh())
        self.assertEqual("Changed", self.erik.get(ASSETS, "A1")["name"])
        self.assertFalse(self.erik.refresh(), "nothing moved since")
        self.assertFalse(self.erik.dirty)


class WhatTheEngineDoesNotKnowIsKeptTest(_Two):

    def test_keys_and_sections_of_a_later_build_survive_a_save(self):
        raw = self.on_disk()
        raw["later"] = {"new": 1}
        raw[ASSETS]["A1"]["later_field"] = [1, 2]
        with open(os.path.join(self.dir, MATERIALS), "w", encoding="utf-8") as handle:
            json.dump(raw, handle)
        document = self.reread()
        document.edit(ASSETS, "A2", name="Touched")
        self.assertTrue(document.save())
        after = self.on_disk()
        self.assertEqual({"new": 1}, after["later"])
        self.assertEqual([1, 2], after[ASSETS]["A1"]["later_field"])


class ABurstIsOneSaveTest(_Two):

    def test_twenty_changes_reach_the_disk_in_one_write_after_one_read(self):
        disk = CountingDisk(MATERIALS)
        asked = []
        library = self.open(ANNA, defer=asked.append, disk=disk)
        document = library.document(MATERIALS)
        disk.reads = 0
        for number in range(20):
            document.put(ASSETS, "B%d" % number, {"name": "burst %d" % number})
        self.assertEqual(20, len(asked), "each change asks the caller's timer")
        self.assertEqual((0, 0), (disk.reads, disk.swaps), "and nothing is written until it fires")
        self.assertTrue(asked[-1]())
        self.assertEqual((1, 1), (disk.reads, disk.swaps))
        self.assertEqual(documents.UNCHANGED, asked[0]().reason, "a second firing has nothing left")
        self.assertEqual(22, len(self.on_disk()[ASSETS]))

    def test_flush_saves_what_is_waiting_and_only_that(self):
        library = self.open(ANNA, defer=lambda save: None)
        document = library.document(MATERIALS)
        library.document("nodes.json")
        document.put(ASSETS, "A7", {"name": "waiting"})
        saved = library.flush()
        self.assertEqual([MATERIALS], list(saved))
        self.assertTrue(saved[MATERIALS])
        self.assertIn("A7", self.on_disk()[ASSETS])


class RefusalsHoldTest(_Two):

    def path(self) -> str:
        return os.path.join(self.dir, MATERIALS)

    def test_a_database_that_does_not_read_takes_no_change(self):
        with open(self.path(), "wb") as handle:
            handle.write(b"{ broken")
        document = self.reread()
        self.assertEqual((guard.CORRUPT, False), (document.verdict, document.writable))
        self.assertFalse(document.put(ASSETS, "A9", {"name": "lost"}))
        self.assertEqual(b"{ broken", open(self.path(), "rb").read())

    def test_a_peer_that_wrote_garbage_is_not_written_over(self):
        self.anna.put(ASSETS, "A9", {"name": "mine"})
        with open(self.path(), "wb") as handle:
            handle.write(b"half a fi")
        saved = self.anna.save()
        self.assertEqual((False, guard.CORRUPT), (saved.ok, saved.reason))
        self.assertEqual(b"half a fi", open(self.path(), "rb").read())
        self.assertEqual("mine", self.anna.get(ASSETS, "A9")["name"], "the change is still held")

    def test_a_file_that_vanished_is_not_made_again_from_memory(self):
        self.anna.put(ASSETS, "A9", {"name": "mine"})
        os.remove(self.path())
        saved = self.anna.save()
        self.assertEqual((False, guard.MISSING), (saved.ok, saved.reason))
        self.assertFalse(os.path.exists(self.path()))

    def test_it_saves_again_by_itself_once_the_file_reads(self):
        good = open(self.path(), "rb").read()
        self.anna.put(ASSETS, "A9", {"name": "mine"})
        with open(self.path(), "wb") as handle:
            handle.write(b"half a fi")
        self.assertFalse(self.anna.save())
        with open(self.path(), "wb") as handle:
            handle.write(good)
        self.anna.refresh()
        self.assertTrue(self.anna.save())
        self.assertEqual({"A1", "A2", "A9"}, set(self.on_disk()[ASSETS]))

    def test_a_newer_format_is_read_and_never_written(self):
        raw = self.on_disk()
        raw["format"] = raw["format"] + 1
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump(raw, handle)
        document = self.reread()
        self.assertEqual(guard.NEWER, document.verdict)
        self.assertEqual("Brick", document.get(ASSETS, "A1")["name"])
        self.assertFalse(document.put(ASSETS, "A1", {"name": "changed"}))
