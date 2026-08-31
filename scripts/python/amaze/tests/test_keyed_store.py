"""The ENGINE's guarantees, not a store's shape; every path here is inside a temp dir. ▸p/store-guards"""

import ast
import copy
import inspect
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import keyed_store, locations, notes, tile_icons  # noqa: E402

SECOND_USER = "f0e1d2c3b4a5968778695a4b3c2d1e0f"  # a second minted-shaped uid beside test_support.FIXTURE_USER
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class _Prefs:
    """Only what a store reads: where the library is, and WHO this is - both, or tagged entries vanish silently."""

    def __init__(self, directory, library_user=test_support.FIXTURE_USER):
        self.dir = directory
        self.library_user = library_user


class StoreCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_keyed_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.prefs = _Prefs(self.dir)
        keyed_store.release()
        self.addCleanup(keyed_store.release)

    def path(self, name="notes.json"):
        return os.path.join(self.dir, name)

    def store(self, spec=None):
        return keyed_store.open_store(spec or notes.SPEC, self.prefs)

    def page(self, text="a note"):
        return {"items": [{"t": "text", "text": text}]}

    def on_disk(self, name="notes.json"):
        with open(self.path(name), encoding="utf-8") as handle:
            return json.load(handle)


class OneFileIsOneTable(StoreCase):
    """ONE file, ONE table, every reader the same rows - the red is earned portably with a `/./` spelling. ▸p/one-file-one-table"""

    def _other_spelling(self):
        """The same directory spelled so `os.path.join` cannot collapse it - a trailing separator alone will not do."""
        other = os.path.join(self.dir, ".", "")
        self.assertNotEqual(
            os.path.join(self.dir, "notes.json"),
            os.path.join(other, "notes.json"),
            "the two spellings collapsed before the cache saw them")
        return _Prefs(other)

    def test_a_write_through_one_spelling_is_seen_through_the_other(self):
        """The failure exactly as it happened: the stale reader opens FIRST, and the write lands after."""
        stale = self.store()
        self.assertEqual({}, stale.all())

        writer = keyed_store.open_store(notes.SPEC, self._other_spelling())
        self.assertTrue(writer.update({"a": self.page("written once")}))

        self.assertIn(
            "a", stale.all(),
            "two Store instances are open on one file, so a row written "
            "through one is invisible through the other - the reader is "
            "serving a table it loaded before the write")

    def test_the_two_spellings_resolve_to_one_instance(self):
        """The mechanism under the behaviour above, asserted directly so a failure says which broke."""
        self.assertIs(
            self.store(),
            keyed_store.open_store(notes.SPEC, self._other_spelling()),
            "one file resolved to two Store objects")


class TestModeKeepsItsLocationsToItself(StoreCase):
    """A test library gets its OWN locations, in both directions - the settings copy is a migration SEED."""

    def _switched(self, keep_calls):
        """A prefs the way the switch leaves one: Test Mode on, the real library's folders still in settings."""
        p = _Prefs(self.dir)
        p.test_mode = True
        p.test_dir = self.dir
        p.data = {locations.MIGRATED_KEY: True}
        p.last_known_folders = ["/Users/someone/Real/Textures"]
        p.last_known_records = {
            "/Users/someone/Real/Textures": {"registered": True}}
        p.keep_last_known = lambda *a: keep_calls.append(a)
        p.save = lambda: None
        return p

    def test_the_real_folders_are_not_seeded_into_it(self):
        calls = []
        p = self._switched(calls)

        self.assertEqual([], locations.paths(p),
                         "the real library's folders were copied into "
                         "the test library")
        self.assertFalse(
            os.path.exists(self.path("locations.json")),
            "a locations.json was written into the test library")

    def test_the_settings_copy_is_never_written_from_it(self):
        """The dangerous direction: the copy is what a later repair of the REAL library reads."""
        calls = []
        p = self._switched(calls)
        locations.register(p, os.path.join(self.dir, "probe"))

        self.assertEqual(
            [], calls,
            "the test library rewrote the settings copy, which is the "
            "seed a repair of the real library reads")

    def test_its_own_locations_still_work(self):
        """Isolated, not disabled - the test library keeps what is registered in it."""
        calls = []
        p = self._switched(calls)
        folder = os.path.join(self.dir, "probe")
        locations.register(p, folder)

        self.assertIn(test_support.posix_path(folder),
                      locations.registered_paths(p))

    def test_a_normal_library_still_migrates(self):
        """The isolation is keyed on Test Mode alone - with it off, the recovery seeding is untouched."""
        calls = []
        p = self._switched(calls)
        p.test_mode = False

        self.assertEqual(["/Users/someone/Real/Textures"],
                         locations.paths(p),
                         "the migration stopped running for ordinary "
                         "libraries too")


class AbsenceIsAVerdict(StoreCase):
    """Absence is resolved ONCE by the engine into an answer a caller cannot mistake for data. ▸p/store-guards"""

    def test_a_library_with_nothing_yet_is_FRESH_and_writable(self):
        store = self.store()
        self.assertEqual(keyed_store.FRESH, store.state)
        self.assertTrue(store.writable)
        self.assertTrue(store.set("material:1", self.page()))

    def test_a_file_that_is_there_and_parses_is_READ(self):
        self.store().set("material:1", self.page())
        keyed_store.release()
        self.assertEqual(keyed_store.READ, self.store().state)

    def test_ABSENT_WITH_A_TRACE_IS_BLIND_and_refuses_to_write(self):
        """A late file looks like an empty library for one instant, and a key written into that instant is the table."""
        self.store().set("material:1", self.page())
        keyed_store.release()
        os.remove(self.path())                # the file blinks out...
        self.assertTrue(hostos.existed_before(self.path()),
                        "no trace survived, so this proves nothing")

        store = self.store()
        self.assertEqual(keyed_store.BLIND, store.state)
        self.assertFalse(store.writable)
        result = store.set("material:2", self.page("new"))
        self.assertFalse(result)
        self.assertEqual(keyed_store.REASON_ABSENT, result.reason)
        self.assertFalse(
            os.path.exists(self.path()),
            "a one-key file was written over a table that is merely "
            "not arrived yet")

    def test_a_file_that_will_not_parse_is_BLIND_and_is_kept(self):
        with open(self.path(), "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        store = self.store()
        self.assertEqual(keyed_store.BLIND, store.state)
        result = store.set("material:1", self.page())
        self.assertFalse(result)
        self.assertEqual(keyed_store.REASON_LATCHED, result.reason)
        self.assertTrue(
            os.path.exists(self.path() + ".unreadable"),
            "the file that would not parse was not kept beside itself")

    def test_the_icons_store_has_the_guard_it_never_had(self):
        """icons.json got the absent-but-known guard by being DECLARED, not by a branch written for it. ▸p/store-guards"""
        store = self.store(tile_icons.SPEC)
        self.assertTrue(store.set("/tex/a.exr",
                                  {"name": "box", "bg": "#ef8878"}))
        keyed_store.release()
        os.remove(self.path("icons.json"))

        store = self.store(tile_icons.SPEC)
        self.assertEqual(keyed_store.BLIND, store.state)
        self.assertFalse(store.set("/tex/b.exr",
                                   {"name": "box", "bg": "#ef8878"}))
        self.assertFalse(os.path.exists(self.path("icons.json")))


class TheRestoreFloorArrivesOnCreate(StoreCase):
    """A store written exactly once still gets a trace, minted on CREATE. ▸p/store-commit-order"""

    def test_the_first_write_leaves_a_floor(self):
        self.assertTrue(self.store().set("material:1", self.page()))
        self.assertTrue(
            os.path.exists(self.path() + ".bak-first"),
            "a store written once has no restore point and no evidence "
            "it ever existed")

    def test_the_floor_is_never_replaced_by_a_later_write(self):
        store = self.store()
        store.set("material:1", self.page("first"))
        floor = self.path() + ".bak-first"
        before = open(floor, encoding="utf-8").read()
        store.set("material:2", self.page("second"))
        self.assertEqual(before, open(floor, encoding="utf-8").read(),
                         "the write-once floor rotated")

    def test_a_floor_is_not_minted_from_bytes_that_do_not_parse(self):
        """A permanent floor made of garbage is worse than none - the file must EXIST to reach the parse guard."""
        target = self.path("icons.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("{ truncated")
        self.assertFalse(hostos.seed_restore_floor(target))
        self.assertFalse(os.path.exists(target + ".bak-first"))

    def test_calling_it_twice_never_replaces_the_floor(self):
        """Directly, because the caller only reaches it on a CREATE, so the write-once rule has no other guard."""
        target = self.path("icons.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write('{"icons": {}}')
        self.assertTrue(hostos.seed_restore_floor(target))
        floor = target + ".bak-first"
        first = open(floor, encoding="utf-8").read()
        with open(target, "w", encoding="utf-8") as handle:
            handle.write('{"icons": {"/a.exr": {"name": "box"}}}')
        self.assertFalse(hostos.seed_restore_floor(target),
                         "it minted a second floor")
        self.assertEqual(first, open(floor, encoding="utf-8").read(),
                         "the write-once floor was replaced")


class AFailedWriteLeavesTheForeignTableWhereItWas(StoreCase):
    """`_foreign` obeys the cache-moves-only-on-success rule too, or a refused write drops a newer build's value. ▸p/store-commit-order"""

    def _with_a_foreign_entry(self):
        """A store whose file holds one entry this build cannot read."""
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump({"notes": {"material:K": {"from": "a newer build"},
                                 "material:ordinary": self.page("kept")}},
                      handle)
        store = self.store()
        self.assertTrue(store._foreign, "premise: the entry reads as foreign")
        return store

    def test_a_refused_write_does_not_drop_the_newer_builds_value(self):
        from unittest.mock import patch

        store = self._with_a_foreign_entry()
        with patch.object(keyed_store.hostos, "write_json_atomic",
                          side_effect=OSError("read-only")):
            self.assertFalse(store.set("material:K", self.page("mine")))

        self.assertIn(
            "material:K", store._foreign,
            "the newer build's value left memory on a write that was "
            "refused, so the next successful write erases it from the "
            "file")

    def test_the_newer_builds_value_survives_a_later_write(self):
        """What the memory state costs ON DISK - the question the user would actually notice."""
        from unittest.mock import patch

        store = self._with_a_foreign_entry()
        with patch.object(keyed_store.hostos, "write_json_atomic",
                          side_effect=OSError("read-only")):
            store.set("material:K", self.page("mine"))
        self.assertTrue(store.set("material:other", self.page("later")))

        self.assertIn(
            "material:K", self.on_disk()["notes"],
            "a newer build's entry was erased by an unrelated write "
            "that followed a refused one")

    def test_a_successful_write_still_claims_the_key(self):
        """The accept path: a key the user SET stops being foreign, or the unreadable copy shadows it."""
        store = self._with_a_foreign_entry()
        self.assertTrue(store.set("material:K", self.page("mine")))
        self.assertNotIn("material:K", store._foreign)
        self.assertEqual(self.page("mine"),
                         self.on_disk()["notes"]["material:K"])


class ReleasingONELibrarysTablesActuallyDropsThem(StoreCase):
    """Releasing ONE library's tables drops them - both sides compare through the same canonical key."""

    def test_the_named_librarys_tables_are_dropped(self):
        """THE PRODUCT'S OWN SPELLING - `prefs.dir` carries a trailing slash and `dirname` never does."""
        self.store().set("material:1", self.page())
        self.assertTrue(keyed_store._open, "premise: a table is cached")
        keyed_store.release(_Prefs(self.dir + os.sep))
        self.assertFalse(
            keyed_store._open,
            "release named a library and dropped nothing - the previous "
            "library's tables stay resident with their state, their "
            "unreadable entries and their disk fingerprint")

    def test_the_separatorless_spelling_matches_too(self):
        """Both spellings name one library; the store must not care which the caller holds."""
        self.store().set("material:1", self.page())
        keyed_store.release(_Prefs(self.dir))
        self.assertFalse(keyed_store._open,
                         "the bare-path spelling matched nothing")

    def test_another_librarys_tables_are_KEPT(self):
        """The accept path: release names ONE library, and dropping every table is the same outage inverted."""
        self.store().set("material:1", self.page())
        keyed_store.release(_Prefs(os.path.join(self.dir, "elsewhere")))
        self.assertTrue(
            keyed_store._open,
            "a release aimed at another library took this one's tables")


class AStoreLivesWhereItsSpecSays(StoreCase):
    """A machine-local store lives beside settings.json, not in the library it points at. ▸p/store-declarations"""

    def _machine_spec(self, filename="machine.json"):
        return keyed_store.Spec(
            filename=filename, payload="settings",
            keyspace=keyed_store.KEY_ID, label="Machine settings",
            noun="setting", normalise=lambda value: value,
            in_library=False)

    def test_a_machine_local_store_lives_beside_the_settings(self):
        elsewhere = tempfile.mkdtemp(prefix="amaze_config_")
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        prefs = _Prefs(self.dir)
        prefs.path = elsewhere
        store = keyed_store.open_store(self._machine_spec(), prefs)
        self.assertEqual(os.path.join(elsewhere, "machine.json"),
                         store.path,
                         "a machine-local store was written into the "
                         "user's LIBRARY, which is the one place the "
                         "pointer to that library must not live")

    def test_a_library_store_is_where_it_always_was(self):
        """The polarity: asking the question must not move the four."""
        prefs = _Prefs(self.dir)
        prefs.path = tempfile.gettempdir()
        store = keyed_store.open_store(notes.SPEC, prefs)
        self.assertEqual(self.path("notes.json"), store.path)

    def test_a_machine_local_store_outlives_a_library_switch(self):
        """A library switch drops that library's tables; this file is not that library's."""
        elsewhere = tempfile.mkdtemp(prefix="amaze_config_")
        self.addCleanup(shutil.rmtree, elsewhere, ignore_errors=True)
        prefs = _Prefs(self.dir)
        prefs.path = elsewhere
        keyed_store.open_store(self._machine_spec(), prefs)
        keyed_store.open_store(notes.SPEC, prefs)
        keyed_store.release(prefs)
        left = [key[0] for key in keyed_store._open]
        self.assertEqual(
            ["machine.json"], left,
            "a library switch took the machine's own settings with it")

    def test_a_prefs_that_cannot_say_where_is_REFUSED(self):
        """A Prefs with no config path must not quietly mean "the library" - that writes into the synced tree."""
        prefs = _Prefs(self.dir)          # no `path` at all
        with self.assertRaises(ValueError):
            keyed_store.open_store(self._machine_spec(), prefs)


class APeersKeyCanBeFOLDEDInRatherThanRefused(StoreCase):
    """A store declares per key where ours-wins is the wrong answer; a key it does not name is unchanged. ▸p/document-not-table"""

    def _spec(self, rules):
        return keyed_store.Spec(
            filename="doc.json", payload="settings",
            keyspace=keyed_store.KEY_ID, label="A document",
            noun="entry", normalise=lambda value: value,
            merge_rules=rules)

    def _peer_wrote(self, document):
        """The other pane's save, already on disk when ours commits."""
        with open(self.path("doc.json"), "w", encoding="utf-8") as handle:
            json.dump({"settings": document}, handle)

    def _after_a_race(self, rules, ours, theirs):
        spec = self._spec(rules)
        store = keyed_store.open_store(spec, self.prefs)
        for key, value in ours.items():
            store.set(key, value)
        self._peer_wrote(theirs)
        store.set("_touch", 1)          # any write runs the adoption
        return self.on_disk("doc.json")["settings"]

    def test_a_combine_key_takes_BOTH_panes_entries(self):
        """The folder case: two panes, two additions, both kept."""
        after = self._after_a_race(
            {"folders": keyed_store.MERGE_COMBINE},
            ours={"folders": ["/mine"]},
            theirs={"folders": ["/theirs"]})
        self.assertEqual(["/mine", "/theirs"], after["folders"],
                         "one pane's registered folder was flattened by "
                         "the other pane's save")

    def test_a_combine_key_does_not_duplicate_a_shared_entry(self):
        after = self._after_a_race(
            {"folders": keyed_store.MERGE_COMBINE},
            ours={"folders": ["/both", "/mine"]},
            theirs={"folders": ["/both", "/theirs"]})
        self.assertEqual(["/both", "/mine", "/theirs"], after["folders"])

    def test_a_key_with_no_rule_takes_THEIRS_when_we_left_it_alone(self):
        """The scalar default USED to be that the saving pane wins, because a single choice cannot be merged without a clock. There is a base now, so the question is answered rather than guessed: we wrote 128 and have not touched it since, they changed it to 64, so 64 is the later decision. ▸p/merge-needs-a-base"""
        after = self._after_a_race(
            {}, ours={"size": 128}, theirs={"size": 64})
        self.assertEqual(64, after["size"])

    def test_a_fields_key_merges_INSIDE_a_shared_record(self):
        """The location case: a colour from one pane, a name from the other, on one folder."""
        after = self._after_a_race(
            {"records": keyed_store.MERGE_FIELDS},
            ours={"records": {"/a": {"name": "Mine"}}},
            theirs={"records": {"/a": {"color": "#ff8800"}}})
        self.assertEqual({"name": "Mine", "color": "#ff8800"},
                         after["records"]["/a"])

    def test_a_fields_key_keeps_OURS_where_both_wrote_the_same_field(self):
        after = self._after_a_race(
            {"records": keyed_store.MERGE_FIELDS},
            ours={"records": {"/a": {"name": "Mine"}}},
            theirs={"records": {"/a": {"name": "Theirs"}}})
        self.assertEqual("Mine", after["records"]["/a"]["name"])

    def test_a_fields_key_adopts_a_record_we_never_had_whole(self):
        after = self._after_a_race(
            {"records": keyed_store.MERGE_FIELDS},
            ours={"records": {"/a": {"name": "Mine"}}},
            theirs={"records": {"/b": {"name": "Theirs"}}})
        self.assertEqual({"name": "Theirs"}, after["records"]["/b"])

    def test_a_library_store_takes_a_peer_edit_it_is_not_competing_for(self):
        """This pinned the OLD polarity - ours won every collision, so a colleague's comment edit was discarded. With a base the question is who MOVED it: we wrote this page and left it alone, they changed it, so theirs stands. ▸p/merge-needs-a-base"""
        store = self.store()
        store.set("material:1", self.page("mine"))
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump({"notes": {"material:1": self.page("theirs"),
                                 "material:2": self.page("new")}}, handle)
        store.set("material:3", self.page("later"))
        after = self.on_disk()["notes"]
        self.assertEqual("theirs",
                         after["material:1"]["items"][0]["text"])
        self.assertIn("material:2", after)


class AStoreJudgesAgainstWhatItLastSaw(StoreCase):
    """The same three-way rule the databases use: only a key BOTH sides moved is a conflict. ▸p/merge-needs-a-base"""

    def _peer_writes(self, table):
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump({"notes": table}, handle)

    def test_a_peer_edit_to_a_key_we_left_alone_is_adopted(self):
        store = self.store()
        store.set("material:1", self.page("as loaded"))
        self._peer_writes({"material:1": self.page("theirs")})

        store.set("material:9", self.page("ours, elsewhere"))

        self.assertEqual(
            "theirs",
            self.on_disk()["notes"]["material:1"]["items"][0]["text"],
            "we were not editing this comment and their edit was discarded")

    def test_a_peer_delete_of_a_key_we_left_alone_is_honoured(self):
        store = self.store()
        store.set("material:1", self.page("as loaded"))
        store.set("material:2", self.page("also ours"))
        self._peer_writes({"material:2": self.page("also ours")})

        store.set("material:9", self.page("ours, elsewhere"))

        self.assertNotIn(
            "material:1", self.on_disk()["notes"],
            "they cleared this comment and our save brought it back")

    def test_our_edit_beats_a_peer_who_left_it_alone(self):
        store = self.store()
        store.set("material:1", self.page("as loaded"))
        self._peer_writes({"material:1": self.page("as loaded"),
                           "material:2": self.page("their new one")})

        store.set("material:1", self.page("ours now"))

        after = self.on_disk()["notes"]
        self.assertEqual("ours now", after["material:1"]["items"][0]["text"])
        self.assertIn("material:2", after, "their addition was dropped")

    def test_both_editing_one_key_keeps_ours_and_tells_the_user(self):
        store = self.store()
        store.set("material:1", self.page("as loaded"))
        self._peer_writes({"material:1": self.page("theirs")})

        alerts = []
        real = keyed_store.debug.alert
        keyed_store.debug.alert = lambda msg, **kw: alerts.append(str(msg))
        self.addCleanup(setattr, keyed_store.debug, "alert", real)

        store.set("material:1", self.page("ours"))

        self.assertEqual(
            "ours", self.on_disk()["notes"]["material:1"]["items"][0]["text"])
        self.assertTrue(alerts, "a real conflict was resolved in silence")

    def test_our_own_delete_still_stands_when_a_peer_wrote_elsewhere(self):
        store = self.store()
        store.set("material:1", self.page("as loaded"))
        self._peer_writes({"material:1": self.page("as loaded"),
                           "material:7": self.page("theirs")})

        store.set("material:1", "")

        after = self.on_disk()["notes"]
        self.assertNotIn("material:1", after,
                         "our delete was undone by their unrelated write")
        self.assertIn("material:7", after)


class ADocumentCanBeFlatAndItsFalsyValuesReal(StoreCase):
    """A store may declare NO payload and BE the map, and say its falsy values are answers. ▸p/store-declarations"""

    def _flat(self, **kwargs):
        return keyed_store.Spec(
            filename="flat.json", payload="", keyspace=keyed_store.KEY_ID,
            label="A flat document", noun="entry",
            normalise=lambda value: value, **kwargs)

    def _raw(self, name="flat.json"):
        with open(self.path(name), encoding="utf-8") as handle:
            return json.load(handle)

    def test_a_flat_store_writes_the_document_ITSELF(self):
        store = keyed_store.open_store(self._flat(), self.prefs)
        store.set("size", 128)
        self.assertEqual({"size": 128}, self._raw(),
                         "a flat store wrapped its document, which is a "
                         "format change nobody asked for")

    def test_a_flat_store_reads_a_document_written_flat(self):
        with open(self.path("flat.json"), "w", encoding="utf-8") as handle:
            json.dump({"size": 64}, handle)
        store = keyed_store.open_store(self._flat(), self.prefs)
        self.assertEqual(64, store.get("size"))

    def test_a_flat_store_still_refuses_what_is_not_an_object(self):
        """The wrong-file guard survives losing the payload key - a JSON list is not a document."""
        with open(self.path("flat.json"), "w", encoding="utf-8") as handle:
            json.dump([1, 2, 3], handle)
        store = keyed_store.open_store(self._flat(), self.prefs)
        self.assertFalse(store.writable)

    def test_a_wrapped_store_still_carries_its_payload_key(self):
        """The polarity: the four are wrapped and stay wrapped."""
        self.store().set("material:1", self.page())
        self.assertIn("notes", self._raw("notes.json"))

    def test_a_setting_of_False_is_a_VALUE(self):
        store = keyed_store.open_store(
            self._flat(falsy_is_a_value=True), self.prefs)
        store.set("show_all", False)
        self.assertIs(False, store.get("show_all"))
        self.assertEqual({"show_all": False}, self._raw(),
                         "a setting the user turned OFF was read as a "
                         "removal, so it went back to its default")

    def test_a_zero_and_an_empty_string_survive_a_reload(self):
        store = keyed_store.open_store(
            self._flat(falsy_is_a_value=True), self.prefs)
        store.update({"count": 0, "label": ""})
        keyed_store.release()
        again = keyed_store.open_store(
            self._flat(falsy_is_a_value=True), self.prefs)
        self.assertTrue(again.has("count"))
        self.assertEqual(0, again.get("count"))
        self.assertEqual("", again.get("label"))

    def test_only_a_normalise_answering_None_rejects(self):
        """When falsy stops meaning no, the reject channel moves to None and foreign still works."""
        spec = self._flat(falsy_is_a_value=True)
        spec.normalise = lambda value: None if value == "junk" else value
        with open(self.path("flat.json"), "w", encoding="utf-8") as handle:
            json.dump({"good": 0, "bad": "junk"}, handle)
        store = keyed_store.open_store(spec, self.prefs)
        self.assertTrue(store.has("good"))
        self.assertFalse(store.has("bad"))
        store.set("later", 1)
        self.assertIn("bad", self._raw(),
                      "a rejected entry was erased rather than kept")

    def test_a_library_store_still_reads_a_falsy_value_as_a_REMOVAL(self):
        """The polarity, and the older contract: an empty note deletes the note."""
        store = self.store()
        store.set("material:1", self.page())
        store.set("material:1", {})
        self.assertFalse(store.has("material:1"))


class AReadHandsOutACopy(StoreCase):
    """A read hands out a COPY - the live cache lets a caller mutate the table without writing. ▸p/store-guards"""

    def test_mutating_a_get_does_not_reach_the_store(self):
        store = self.store()
        store.set("material:1", self.page("real"))
        page = store.get("material:1")
        page["items"].append({"t": "text", "text": "smuggled"})
        self.assertEqual(1, len(store.get("material:1")["items"]),
                         "a caller mutated the store through a read")

    def test_mutating_all_does_not_reach_the_store(self):
        store = self.store()
        store.set("material:1", self.page())
        table = store.all()
        table["material:2"] = self.page("smuggled")
        self.assertFalse(store.has("material:2"))

    def test_has_is_the_paint_paths_question_and_reads_no_disk(self):
        store = self.store()
        store.set("material:1", self.page())
        opened = []
        real_open = open

        def spy(*a, **kw):
            opened.append(a[0])
            return real_open(*a, **kw)

        import builtins
        with mock.patch.object(builtins, "open", spy):
            for _ in range(50):
                store.has("material:1")
        self.assertEqual([], opened,
                         "has() touched the disk - it is called per tile "
                         "per repaint from three models: %s" % opened[:3])


class AWriteCommitsOnlyOnSuccess(StoreCase):

    def test_a_refused_write_leaves_the_cache_exactly_as_it_was(self):
        store = self.store()
        store.set("material:1", self.page("kept"))
        keyed_store.release()
        os.remove(self.path())                       # -> BLIND
        store = self.store()

        self.assertFalse(store.set("material:9", self.page("lost")))
        self.assertFalse(
            store.has("material:9"),
            "the badge lights for a note that was never saved")

    def test_a_denied_write_leaves_the_cache_exactly_as_it_was(self):
        store = self.store()
        store.set("material:1", self.page("kept"))
        with mock.patch.object(hostos, "write_json_atomic",
                               side_effect=OSError("read-only")):
            result = store.set("material:2", self.page("lost"))
        self.assertFalse(result)
        self.assertEqual(keyed_store.REASON_DENIED, result.reason)
        self.assertFalse(store.has("material:2"))
        self.assertTrue(store.has("material:1"),
                        "a failed write dropped what was already there")

    def test_the_answer_says_WHY_not_just_no(self):
        """A bare False cannot tell a read-only folder from a file that will not parse, so the panel guessed."""
        with open(self.path(), "w", encoding="utf-8") as handle:
            handle.write("nonsense")
        result = self.store().set("material:1", self.page())
        self.assertEqual(keyed_store.REASON_LATCHED, result.reason)
        self.assertIn("could not be read", result.sentence)

    def test_asking_for_what_is_already_there_is_not_a_failure(self):
        store = self.store()
        store.set("material:1", self.page())
        result = store.set("material:1", self.page())
        self.assertTrue(result)
        self.assertEqual(keyed_store.REASON_UNCHANGED, result.reason)


class TheFileMustBeTHISStoresFile(StoreCase):

    def test_a_document_holding_the_other_stores_key_is_refused(self):
        """A missing payload key reads as a valid empty table, so the wrong file parses as zero rows. ▸p/store-commit-order"""
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump({"icons": {"/a.exr": {"name": "box"}}}, handle)
        store = self.store()
        self.assertEqual(keyed_store.BLIND, store.state)
        self.assertFalse(store.set("material:1", self.page()))

    def test_a_byte_order_mark_is_read_not_latched(self):
        """A BOM is what a Windows editor leaves behind; plain utf-8 reads it as damaged and latches."""
        with open(self.path(), "wb") as handle:
            handle.write(b"\xef\xbb\xbf" + json.dumps(
                {"notes": {"material:1": self.page("from windows")}}
            ).encode("utf-8"))
        store = self.store()
        self.assertEqual(keyed_store.READ, store.state)
        self.assertTrue(store.has("material:1"))


class TheRegistryIsTheOneEnumeration(StoreCase):

    def test_it_can_be_read_without_qt_or_houdini(self):
        """WHICH files exist is declared apart from what a valid value is, so Repair runs without Qt. ▸p/store-declarations"""
        source = open(keyed_store.__file__.replace(".pyc", ".py"),
                      encoding="utf-8").read()
        head = source[:source.index('class Written', 0)]
        for banned in ("PySide6", "import hou"):
            self.assertNotIn(banned, head)

    def test_every_library_store_is_declared_with_its_words(self):
        for spec in keyed_store.stores():
            self.assertTrue(spec.label, "%s has no name" % spec.filename)
            self.assertTrue(spec.noun, "%s has no noun" % spec.filename)

    def test_repair_surveys_what_the_registry_declares(self):
        """The SURVEY, not just the helper that names them - asserting the helper left the survey free to ignore it."""
        from amaze.core import repair

        self.assertEqual(set(keyed_store.filenames()),
                         set(repair.side_tables()))
        self.store().set("material:1", self.page())
        surveyed = {entry["filename"]
                    for entry in repair.survey(self.dir)["lists"]}
        for name in ("notes.json", "icons.json"):
            self.assertIn(
                name, surveyed,
                "Repair does not survey %s, although that file's "
                "unreadable alert sends the user to Repair by name"
                % name)
        self.assertEqual(
            "Comments",
            [e for e in repair.survey(self.dir)["lists"]
             if e["filename"] == "notes.json"][0]["label"],
            "Repair surveys it without being able to name it")

    def test_the_audit_tools_list_agrees_with_the_registry(self):
        """The audit keeps its OWN literal so it runs without the package; this test is what makes drift RED. ▸p/store-declarations"""
        import ast

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        source = open(os.path.join(root, "tools", "library-audit.py"),
                      encoding="utf-8").read()
        tree = ast.parse(source)
        listed = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and node.targets
                    and getattr(node.targets[0], "id", "") == "SIDE_TABLES"):
                listed = set(ast.literal_eval(node.value))
        self.assertIsNotNone(listed, "library-audit.py no longer names "
                                     "SIDE_TABLES, so this check is vacuous")
        self.assertEqual(
            set(keyed_store.filenames()), listed,
            "the audit tool and the registry disagree about which keyed "
            "files a library contains")

    def test_the_audit_tools_DATABASE_list_agrees_with_the_package(self):
        """The same guard its neighbour has, for the list beside it - a fifth database must not fail `--strict`."""
        import ast

        from amaze.core import database

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        source = open(os.path.join(root, "tools", "library-audit.py"),
                      encoding="utf-8").read()
        listed = None
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, ast.Assign) and node.targets
                    and getattr(node.targets[0], "id", "") == "DATABASES"):
                listed = set(ast.literal_eval(node.value))
        self.assertIsNotNone(listed, "library-audit.py no longer names "
                                     "DATABASES, so this check is vacuous")
        self.assertEqual(
            set(database._SECTION_LABELS), listed,
            "the audit tool and the package disagree about which lists "
            "a library contains")

    def test_a_side_table_can_be_counted_by_the_restore_picker(self):
        """A 40-note file counted as "1 settings", so the restore refusal comparing record counts never fired."""
        from amaze.helpers import restore as restore_lib

        store = self.store()
        for n in range(7):
            store.set("material:%d" % n, self.page("n%d" % n))
        facts = restore_lib.info(self.path())
        self.assertEqual(7, facts["count"])
        self.assertEqual("comments", facts["noun"])


class TheStoreSpeaksPortableSpelling(StoreCase):
    """Path keys are stored VARIABLE-RELATIVE; the API keeps speaking absolutes and the boundary converts."""

    def _fake_home(self, *made):
        home = tempfile.mkdtemp(prefix="amaze_home_")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        for name in made:
            full = os.path.join(home, name)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as handle:
                handle.write("x")
        patcher = mock.patch.object(
            hostos, "_home_root", lambda: hostos.canonical_path_key(home))
        patcher.start()
        self.addCleanup(patcher.stop)
        return hostos.canonical_path_key(home)

    def test_a_home_path_is_stored_home_relative(self):
        home = self._fake_home("plates/a.exr")
        absolute = home + "/plates/a.exr"
        store = self.store()
        store.set(notes.note_key("file", absolute), self.page("kept"))
        self.assertEqual(["file:~/plates/a.exr"],
                         list(self.on_disk()["notes"]),
                         "the bytes carry the machine's spelling - this "
                         "library cannot travel")
        self.assertTrue(store.has(notes.note_key("file", absolute)),
                        "the caller's absolute no longer finds its own "
                        "entry back")

    def test_an_amaze_path_is_stored_amaze_relative(self):
        self._fake_home()
        amaze = tempfile.mkdtemp(prefix="amaze_root_")
        self.addCleanup(shutil.rmtree, amaze, ignore_errors=True)
        patcher = mock.patch.dict(
            os.environ, {"AMAZE": amaze})
        patcher.start()
        self.addCleanup(patcher.stop)
        absolute = hostos.canonical_path_key(
            os.path.join(amaze, "toolbar", "x.png"))
        store = self.store()
        store.set(notes.note_key("file", absolute), self.page("kept"))
        self.assertEqual(["file:$AMAZE/toolbar/x.png"],
                         list(self.on_disk()["notes"]))
        self.assertTrue(store.has(notes.note_key("file", absolute)))

    def test_legacy_spellings_converge_on_load(self):
        """Three spellings of ONE file are one entry after a load, first in wins, found by any of them."""
        home = self._fake_home("plates/a.exr")
        absolute = home + "/plates/a.exr"
        detour = home + "/plates/sub/../a.exr"
        legacy = {"notes": {
            "file:" + absolute: {"items": [{"t": "text", "text": "one"}]},
            "file:~/plates/a.exr": {"items": [{"t": "text", "text": "two"}]},
            "file:" + detour: {"items": [{"t": "text", "text": "three"}]},
        }}
        with open(self.path(), "w", encoding="utf-8", newline="\n") as f:
            json.dump(legacy, f, indent=4)
        store = self.store()
        self.assertEqual(1, store.count(),
                         "three spellings of one file survived the load "
                         "as separate entries")
        self.assertTrue(store.has(notes.note_key("file", absolute)))
        self.assertTrue(store.has(notes.note_key("file", detour)))

    def test_a_path_under_no_root_stays_absolute(self):
        self._fake_home()
        store = self.store()
        store.set(notes.note_key("file", "/old/a.exr"), self.page("kept"))
        self.assertIn("file:/old/a.exr", self.on_disk()["notes"])

    def test_locations_speak_walkable_absolutes_over_portable_bytes(self):
        """The identity table holds the portable spelling and the record its owner's id; the reader hands back an absolute `os.walk` can open."""
        home = self._fake_home("plates/a.exr")
        absolute = home + "/plates"
        locations.register(self.prefs, absolute)
        locations.set_favourite(self.prefs, absolute + "/a.exr", True)
        lid = locations.location_id(self.prefs, absolute)
        self.assertEqual(
            "~/plates",
            self.on_disk(keyed_store.LOCATION_PATHS)
            ["location_paths"][lid]["path"],
            "the identity table carries the machine's spelling")
        stored = self.on_disk(keyed_store.LOCATIONS)["locations"]
        self.assertEqual(
            [(test_support.FIXTURE_USER, "loc:" + lid)],
            [keyed_store.untagged_key(locations.SPEC, key)
             for key in stored],
            "the record is keyed by something a move would rewrite, or "
            "the row landed under nobody")
        self.assertEqual([absolute],
                         locations.registered_paths(self.prefs),
                         "the reader hands back a spelling the scanner "
                         "cannot walk")
        self.assertTrue(
            locations.is_favourite(
                self.prefs,
                locations.file_ident(self.prefs, absolute + "/a.exr")))
        self.assertEqual([absolute + "/a.exr"],
                         locations.favourite_paths(self.prefs))


class TheKeyLifecycle(StoreCase):
    """The owner announces; the ENGINE fans out - a caller that enumerates the stores writes the list short. ▸p/store-guards"""

    def test_a_relocate_moves_only_path_shaped_keys(self):
        store = self.store()
        store.set(notes.note_key("file", "/old/a.exr"), self.page("file"))
        store.set(notes.note_key("material", "/old/a.exr"), self.page("id"))

        keyed_store.relocate(self.prefs, "/old/", "/new/")

        self.assertTrue(store.has(notes.note_key("file", "/new/a.exr")))
        self.assertFalse(store.has(notes.note_key("file", "/old/a.exr")))
        self.assertTrue(
            store.has(notes.note_key("material", "/old/a.exr")),
            "an asset key that merely LOOKS like a path was rewritten "
            "by a folder move")

    def test_the_path_prefix_is_what_makes_a_key_movable(self):
        """Which keys a folder move may rewrite is the declared PREFIX, not the whole store. ▸p/store-declarations"""
        self.assertEqual(keyed_store.KEY_MIXED, notes.SPEC.keyspace)
        self.assertEqual("file:", notes.SPEC.path_prefix)
        self.assertTrue(notes.SPEC.is_path_key("file:/a/b.exr"))
        self.assertFalse(notes.SPEC.is_path_key("material:12345"))
        self.assertFalse(
            notes.SPEC.is_path_key("material:/a/b.exr"),
            "an asset id shaped like a path is not a path key")

    def test_a_relocate_is_one_write_per_store(self):
        store = self.store()
        for n in range(5):
            store.set(notes.note_key("file", "/old/%d.exr" % n),
                      self.page("n%d" % n))
        writes = []
        real = hostos.write_json_atomic

        def spy(path, data, **kw):
            writes.append(path)
            return real(path, data, **kw)

        with mock.patch.object(hostos, "write_json_atomic", spy):
            keyed_store.relocate(self.prefs, "/old/", "/new/")
        self.assertEqual(
            1, len(writes),
            "five keys moved in %d writes - a half-rewritten keyspace "
            "is worse than the orphaning it fixes" % len(writes))

    def test_an_existing_entry_at_the_destination_is_not_overwritten(self):
        store = self.store()
        store.set(notes.note_key("file", "/old/a.exr"), self.page("old"))
        store.set(notes.note_key("file", "/new/a.exr"), self.page("chosen"))
        keyed_store.relocate(self.prefs, "/old/", "/new/")
        self.assertEqual(
            "chosen",
            store.get(notes.note_key("file", "/new/a.exr"))["items"][0]["text"],
            "a rename overwrote a note that was written for the new path")

    def test_a_sibling_directory_is_not_captured(self):
        store = self.store()
        store.set(notes.note_key("file", "/a/textures/x.exr"), self.page())
        keyed_store.relocate(self.prefs, "/a/tex", "/b/tex")
        self.assertTrue(
            store.has(notes.note_key("file", "/a/textures/x.exr")),
            "relocating /a/tex captured /a/textures")

    def test_a_removal_forgets_EVERYTHING_about_the_location(self):
        """Removal means removal - re-adding the folder gives a clean slate. ▸p/store-declarations"""
        page_store = self.store()
        icon_store = self.store(tile_icons.SPEC)
        page_store.set(notes.note_key("file", "/gone/a.exr"), self.page())
        icon_store.set("/gone/a.exr", {"name": "box", "bg": "#ef8878"})

        keyed_store.retire_prefix(self.prefs, "/gone/")

        self.assertFalse(
            page_store.has(notes.note_key("file", "/gone/a.exr")),
            "removing a location left the comments in it behind")
        self.assertFalse(
            icon_store.has("/gone/a.exr"),
            "removing a location left the custom icons in it behind")

    def test_a_removal_leaves_everything_OUTSIDE_the_location_alone(self):
        """The half that matters more: forgetting a folder must not reach an asset's comment or another folder."""
        page_store = self.store()
        page_store.set(notes.note_key("material", "a1"), self.page("asset"))
        page_store.set(notes.note_key("file", "/kept/a.exr"), self.page())
        page_store.set(notes.note_key("file", "/gone/a.exr"), self.page())

        keyed_store.retire_prefix(self.prefs, "/gone/")

        self.assertTrue(
            page_store.has(notes.note_key("material", "a1")),
            "removing a File location deleted an ASSET's comment")
        self.assertTrue(
            page_store.has(notes.note_key("file", "/kept/a.exr")),
            "removing one location reached into another")

    def test_a_prefixed_key_is_matched_by_the_SAME_rule_both_ways(self):
        """Both halves of the lifecycle strip the `file:` prefix through ONE function, or a sweep leaves comments behind."""
        key = notes.note_key("file", "/gone/a.exr")
        self.assertTrue(keyed_store._under(notes.SPEC, key, "/gone/"))
        self.assertTrue(keyed_store._under(notes.SPEC, key, "/gone"))
        self.assertFalse(keyed_store._under(notes.SPEC, key, "/go/"))
        self.assertFalse(
            keyed_store._under(notes.SPEC,
                               notes.note_key("material", "/gone/a.exr"),
                               "/gone/"),
            "an asset id shaped like a path was swept by a folder removal")
        calls = []
        real = keyed_store._bare_path
        self.addCleanup(setattr, keyed_store, "_bare_path", real)

        def counting(spec, key):
            calls.append(key)
            return real(spec, key)

        keyed_store._bare_path = counting

        page_store = self.store()
        page_store.set(notes.note_key("file", "/old/a.exr"), self.page())
        keyed_store.relocate(self.prefs, "/old/", "/new/")
        self.assertTrue(
            calls, "relocate stopped asking one function how a keyspace "
                   "prefix comes off - an inlined copy is how the two "
                   "halves drifted apart the first time")

        calls.clear()
        keyed_store.retire_prefix(self.prefs, "/new/")
        self.assertTrue(
            calls, "the removal half stopped asking it, which is the "
                   "exact drift that left every comment behind")

    def test_a_removal_takes_EVERY_users_stars_with_it(self):
        """A removal is a SHARED act: every user's keys go, and it works with nobody picked. ▸p/store-declarations"""
        store = keyed_store.open_store(locations.FAVOURITES_SPEC, self.prefs)
        store.set("/gone/a.exr", True)              # the first user's star
        store.set("/kept/b.exr", True)
        self.prefs.library_user = SECOND_USER  # minted shape: the product tags with uuid4().hex only, so a hand-spelled tag is a row it cannot write
        store.set("/gone/a.exr", True)              # the second user's
        self.prefs.library_user = ""                # nobody picked now

        keyed_store.retire_prefix(self.prefs, "/gone/")

        remaining = sorted(
            keyed_store.untagged_key(locations.FAVOURITES_SPEC, stored)[1]
            for stored in store.everyones())
        self.assertEqual(
            ["/kept/b.exr"], remaining,
            "a folder removal left some user's stars under the removed "
            "location - the clean slate went per-user with the tag")

    def test_favourites_are_in_the_registry_too(self):
        """Reads the STORE, not a settings attribute - asserting against a list the stub seeded proved nothing."""
        store = keyed_store.open_store(locations.FAVOURITES_SPEC, self.prefs)
        store.update({"/gone/a.exr": True, "/kept/b.exr": True})
        keyed_store.retire_prefix(self.prefs, "/gone/")
        self.assertEqual(["/kept/b.exr"], sorted(store.all()),
                         "a removed location's favourites outlived it")

    def test_a_store_created_by_its_own_write_reports_READ(self):
        """A store that wrote itself into existence answers READ, never still FRESH. ▸p/store-commit-order"""
        store = self.store()
        self.assertEqual(keyed_store.FRESH, store.state,
                         "a library with no notes.json is not FRESH, so "
                         "this test is not exercising its own case")
        self.assertTrue(store.set("material:1", self.page()))
        self.assertTrue(os.path.exists(self.path()))
        self.assertEqual(
            keyed_store.READ, store.state,
            "the store wrote its own file and still calls itself FRESH")

    def test_emptying_a_store_leaves_it_READ_not_FRESH(self):
        """Removing the last key writes a real file holding an empty table: READ, not no file at all."""
        store = self.store()
        store.set("material:1", self.page())
        self.assertTrue(store.set("material:1", {}))
        self.assertEqual(0, store.count())
        self.assertEqual(
            keyed_store.READ, store.state,
            "an emptied store reports FRESH, so a caller cannot tell it "
            "from a library that never had one")

    def test_survives_forget_is_declared_not_inferred(self):
        for name in ("notes.json", "icons.json", keyed_store.LOCATIONS,
                     keyed_store.FAVOURITES):
            self.assertFalse(
                keyed_store.store_for(name).survives_forget,
                "%s would outlive the location it belongs to" % name)


class ForeignEntriesSurviveTheRewrite(StoreCase):
    """A rejected entry is usually a NEWER build's data - kept verbatim and written back by every commit. ▸p/store-commit-order"""

    def _seed(self, entries):
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump({"notes": entries}, handle)

    def test_a_rejected_entry_survives_a_write(self):
        self._seed({
            "material:good": self.page("keep me"),
            "material:future": {"hologram": True},
        })
        store = self.store()
        self.assertFalse(store.has("material:future"),
                         "a rejected entry answered as readable")
        store.set("material:new", self.page("mine"))
        written = self.on_disk()["notes"]
        self.assertIn(
            "material:future", written,
            "one write from an older build erased the newer build's "
            "entry from the shared file")
        self.assertEqual({"hologram": True}, written["material:future"],
                         "the foreign entry was not kept verbatim")

    def test_a_rejected_PEER_entry_survives_our_write(self):
        self._seed({"material:good": self.page("keep")})
        store = self.store()
        # Another session writes an entry we cannot parse.
        self._seed({
            "material:good": self.page("keep"),
            "material:future": {"hologram": True},
        })
        store.set("material:new", self.page("mine"))
        self.assertIn(
            "material:future", self.on_disk()["notes"],
            "our write erased what the peer session had just written")

    def test_setting_the_same_key_takes_it_over(self):
        self._seed({"material:x": {"hologram": True}})
        store = self.store()
        store.set("material:x", self.page("now real"))
        self.assertEqual(
            self.page("now real"), self.on_disk()["notes"]["material:x"],
            "the foreign copy shadowed the value the user just chose")


class UntaggedRowsAwaitAdoption(StoreCase):
    """A pre-tag row is dropped from every read surface but kept aside for a store that CHOOSES adoption. ▸p/store-commit-order"""

    OTHER = "0f0e0d0c0b0a09080706050403020100"

    def _seed(self, entries):
        with open(self.path(locations.FAVOURITES_FILE),
                  "w", encoding="utf-8") as handle:
            json.dump({"favourites": entries}, handle)

    def _tagged_store(self):
        return keyed_store.open_store(locations.FAVOURITES_SPEC, self.prefs)

    def _mine(self, key):
        return (test_support.FIXTURE_USER + keyed_store.USER_SEP + key)

    def test_untagged_rows_wait_in_the_bucket_and_answer_no_reader(self):
        self._seed({
            "/old/a.exr": {"favourite": True},
            "/old/b.exr": {"favourite": True},
            self._mine("/mine/c.exr"): {"favourite": True},
        })
        store = self._tagged_store()
        self.assertEqual(["/mine/c.exr"], sorted(store.all()),
                         "an ownerless row reached a scoped read")
        self.assertFalse(store.has("/old/a.exr"),
                         "the paint path saw a row nobody owns")
        self.assertEqual(
            {"/old/a.exr": {"favourite": True},
             "/old/b.exr": {"favourite": True}},
            store.orphaned(),
            "the rows from before the store had owners are not waiting "
            "for adoption - a store that chooses to adopt has nothing "
            "to adopt from")
        self.assertEqual(2, store.orphan_count())

    def test_a_commit_drops_orphans_from_disk_and_the_bucket(self):
        self._seed({"/old/a.exr": {"favourite": True}})
        store = self._tagged_store()
        self.assertTrue(store.set("/new/b.exr", True))
        written = self.on_disk(locations.FAVOURITES_FILE)["favourites"]
        self.assertNotIn(
            "/old/a.exr", written,
            "an ownerless row survived a commit - the drop call says "
            "it must not come back")
        self.assertEqual(0, store.orphan_count(),
                         "the bucket outlived the file's own copy, so a "
                         "later adoption would resurrect a removed row")

    def test_adopt_orphans_files_them_under_the_user_in_one_write(self):
        self._seed({
            "/old/a.exr": {"favourite": True},
            "/old/b.exr": {"favourite": True},
        })
        store = self._tagged_store()
        writes = []
        real = hostos.write_json_atomic

        def spy(path, data, **kw):
            writes.append(path)
            return real(path, data, **kw)

        with mock.patch.object(hostos, "write_json_atomic", spy):
            written = store.adopt_orphans()
        self.assertTrue(written)
        self.assertEqual(1, len(writes),
                         "the adoption is not ONE write, so a denial "
                         "mid-way can land the move half done")
        on_disk = self.on_disk(locations.FAVOURITES_FILE)["favourites"]
        self.assertIn(self._mine("/old/a.exr"), on_disk)
        self.assertNotIn("/old/a.exr", on_disk,
                         "the untagged spelling survived the write that "
                         "adopted it - the move must land whole")
        self.assertTrue(store.has("/old/b.exr"))
        self.assertEqual(0, store.orphan_count())

    def test_adoption_only_adds_and_still_clears_the_file(self):
        chosen = {"favourite": True}
        self._seed({
            "/old/a.exr": {"favourite": True},
            self._mine("/old/a.exr"): chosen,
        })
        store = self._tagged_store()
        self.assertTrue(store.adopt_orphans())
        on_disk = self.on_disk(locations.FAVOURITES_FILE)["favourites"]
        self.assertEqual(chosen, on_disk[self._mine("/old/a.exr")],
                         "an orphan overwrote a row its owner already "
                         "holds - adoption can only ADD")
        self.assertNotIn(
            "/old/a.exr", on_disk,
            "nothing new to add, and the untagged spelling stayed on "
            "disk - every session after this one re-reads it forever")

    def test_adoption_refuses_with_nobody_picked_and_loses_nothing(self):
        self._seed({"/old/a.exr": {"favourite": True}})
        self.prefs.library_user = ""
        store = self._tagged_store()
        written = store.adopt_orphans()
        self.assertFalse(written)
        self.assertEqual(keyed_store.REASON_NO_USER, written.reason)
        self.assertIn(
            "/old/a.exr",
            self.on_disk(locations.FAVOURITES_FILE)["favourites"],
            "a refused adoption still rewrote the file - the rows it "
            "could not attribute are gone")
        self.assertEqual(1, store.orphan_count())

    def test_an_untagged_store_has_no_orphans_and_adopts_nothing(self):
        store = self.store()
        store.set("material:x", self.page())
        self.assertEqual(0, store.orphan_count())
        written = store.adopt_orphans()
        self.assertTrue(written)
        self.assertEqual(keyed_store.REASON_UNCHANGED, written.reason)


class EveryDoorSpeaksThePortableSpelling(StoreCase):
    """EVERY door converts at the boundary, or a caller speaking absolutes grows a second spelling of one key."""

    def _table(self, name="locations.json"):
        document = self.on_disk(name)
        return next(iter(document.values()))

    def _bare(self, key):
        # locations are user-tagged: the spelling under test is the PATH half
        return keyed_store.untagged_key(locations.SPEC, key)[1]

    def test_update_rekey_and_retire_match_the_stored_spelling(self):
        target = os.path.join(os.path.expanduser("~"), "amaze-seam-loc")
        moved = os.path.join(os.path.expanduser("~"), "amaze-seam-two")
        store = keyed_store.open_store(locations.SPEC, self.prefs)
        store.set(target, {"registered": True})
        self.assertTrue(
            all(self._bare(key).startswith("~") for key in self._table()),
            "premise: a home path is stored in the portable spelling")

        store.update({target: {"registered": True, "name": "Seam"}})
        self.assertEqual(
            1, len(self._table()),
            "update grew a second spelling of a key the table held")

        store.rekey({target: moved})
        table = self._table()
        self.assertEqual(1, len(table), "rekey grew a second spelling")
        self.assertTrue(self._bare(next(iter(table))).startswith("~"),
                        "rekey stored the raw absolute destination")

        store.retire([moved])
        self.assertEqual(
            {}, self._table(),
            "retire missed the stored spelling - the location's record "
            "outlives the location")


class ARecordCarriesFieldsItDoesNotKnow(StoreCase):
    """Adapters keep foreign FIELDS inside entries they accept - the same reason one level down."""

    def test_locations_normalise_keeps_unknown_fields(self):
        record = locations.normalise({
            "registered": True, "name": "Seam",
            "pinned_by": "future-build"})
        self.assertEqual("Seam", record.get("name"))
        self.assertEqual(
            "future-build", record.get("pinned_by"),
            "an older build's write drops the field a newer one added")

    def test_notes_normalise_keeps_unknown_fields(self):
        page = notes.normalise({
            "items": [{"t": "text", "text": "hello"}],
            "pinned": True})
        self.assertEqual(1, len(page.get("items") or ()))
        self.assertTrue(page.get("pinned"),
                        "the page-level field a newer build added died")

    def test_tile_icons_normalise_keeps_unknown_fields(self):
        record = tile_icons.normalise({
            "name": tile_icons.icon_names()[0], "bg": "#333333",
            "badge": "future"})
        self.assertEqual("future", record.get("badge"))


class ADENIEDWriteSpeaksONLYWhereTheFailureIsInvisible(unittest.TestCase):
    """Who is told when the disk refuses a write and who is not, declared on the Spec. ▸p/speak-when-invisible"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_denied_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        keyed_store.release()
        self.addCleanup(keyed_store.release)

    def _denied(self, filename):
        """Drive a REAL write into a real OSError - the point is that the engine's own commit path reports."""
        prefs = _Prefs(self.dir)
        store = keyed_store.open_store(
            keyed_store.store_for(filename), prefs)
        seen = []
        with mock.patch.object(hostos, "write_json_atomic",
                               side_effect=OSError(2, "No such file")), \
                mock.patch("amaze.core.debug.alert",
                           side_effect=lambda text, key="": seen.append(
                               (text, key)) or True):
            result = store.set(
                "probe-key",
                {"items": [{"t": "text", "text": "a comment"}]}
                if filename == "notes.json" else {"registered": True})
        return result, seen

    def test_a_comment_that_could_not_be_saved_says_so(self):
        result, seen = self._denied("notes.json")
        self.assertFalse(result, "the write reported success")
        self.assertEqual(1, len(seen),
                         "a refused comment said nothing, and nothing "
                         "on screen would say it either")
        text = seen[0][0]
        self.assertIn("comment could not be saved", text)
        # the CAUSE, from the errno - never one guess for every failure
        self.assertIn("cannot be reached", text)

    def test_a_location_that_could_not_be_saved_says_NOTHING(self):
        result, seen = self._denied("locations.json")
        self.assertFalse(result, "the write reported success")
        self.assertEqual([], seen,
                         "a failed location write raised an alert - the "
                         "folder simply never appears in the sidebar, "
                         "so this announces what the user just watched")

    def test_the_reason_still_reaches_the_caller_either_way(self):
        """Silence is not ignorance - the sentence rides on the result, and the log gets it regardless."""
        from amaze.core import keyed_store

        result, _seen = self._denied("locations.json")
        self.assertEqual(keyed_store.REASON_DENIED, result.reason)
        self.assertIn("cannot be reached", result.sentence)


class ARelocateIsONEWrite(unittest.TestCase):
    """A location's move lands whole or not at all - delete-then-add is two trips to disk."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_reloc_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        keyed_store.release()
        self.addCleanup(keyed_store.release)
        self.prefs = _Prefs(self.dir)

    def test_a_move_never_loses_the_record_to_a_half_write(self):
        """THE SECOND write is the one that fails - failing every write proves nothing, since no commit lands."""
        real_write = hostos.write_json_atomic
        calls = []

        def once_then_fail(*args, **kwargs):
            calls.append(1)
            if len(calls) > 1:
                raise OSError(2, "No such file")
            return real_write(*args, **kwargs)

        old = os.path.join(self.dir, "before")
        new = os.path.join(self.dir, "after")
        os.makedirs(old)
        os.makedirs(new)
        locations.register(self.prefs, old)
        locations.set_record(self.prefs, old,
                             dict(locations.record(self.prefs, old),
                                  color="#ff0000", name="Wood"))
        self.assertEqual("#ff0000",
                         locations.record(self.prefs, old).get("color"),
                         "premise: the record carries a colour")

        with mock.patch.object(hostos, "write_json_atomic",
                               side_effect=once_then_fail):
            locations.relocate_record(self.prefs, old, new)

        found = (locations.record(self.prefs, new)
                 or locations.record(self.prefs, old))
        self.assertEqual(
            "#ff0000", found.get("color"),
            "the move was two writes and the second was denied, so the "
            "location is registered nowhere and its colour, name, "
            "recursion and Show All Files went with it")
        self.assertEqual("Wood", found.get("name"))

    def test_a_move_that_lands_carries_the_whole_record(self):
        old = os.path.join(self.dir, "before")
        new = os.path.join(self.dir, "after")
        os.makedirs(old)
        os.makedirs(new)
        locations.register(self.prefs, old)
        locations.set_record(self.prefs, old,
                             dict(locations.record(self.prefs, old),
                                  color="#00ff00", name="Metal"))

        locations.relocate_record(self.prefs, old, new)

        moved = locations.record(self.prefs, new)
        self.assertEqual("#00ff00", moved.get("color"))
        self.assertEqual("Metal", moved.get("name"))
        self.assertTrue(moved.get("registered"))
        self.assertEqual({}, locations.record(self.prefs, old),
                         "the old path is still registered after a move")


class ADocumentIsNotATableOfRows(StoreCase):
    """settings.json is a store, and differs from the library's four in four ways. ▸p/document-not-table"""

    def _spec(self, rules=None, absence_is_fresh=True):
        return keyed_store.Spec(
            filename="doc.json", payload="", keyspace=keyed_store.KEY_ID,
            label="A document", noun="setting",
            normalise=lambda value: value, falsy_is_a_value=True,
            absence_is_fresh=absence_is_fresh, merge_rules=rules)

    def _own(self, spec):
        """A holder's OWN store, the way persistence takes one - two of them keep two baselines."""
        return keyed_store.own_store(spec, self.prefs)

    def _peer_wrote(self, document):
        with open(self.path("doc.json"), "w", encoding="utf-8") as handle:
            json.dump(document, handle)


    def test_a_trace_beside_an_absent_file_does_NOT_latch(self):
        """Its own prescribed recovery is to delete it, so the guard would refuse the fresh start it advised."""
        with open(self.path("doc.json.bak-1"), "w",
                  encoding="utf-8") as handle:
            handle.write("{}")
        store = self._own(self._spec())
        self.assertEqual(keyed_store.FRESH, store.state)
        self.assertTrue(store.writable,
                        "a machine-local store refused to write because "
                        "an earlier rescue copy proved the file existed")

    def test_the_same_trace_DOES_latch_a_library_store(self):
        """The flag is a declaration, not a weakening - without it the verdict is what it always was."""
        with open(self.path("doc.json.bak-1"), "w",
                  encoding="utf-8") as handle:
            handle.write("{}")
        store = self._own(self._spec(absence_is_fresh=False))
        self.assertEqual(keyed_store.BLIND, store.state)
        self.assertFalse(store.writable)


    NESTED = {"users": keyed_store.MERGE_FIELDS,
              "users/*/file_folders": keyed_store.MERGE_COMBINE}

    def test_a_peers_folder_inside_a_shared_user_block_SURVIVES(self):
        """The regression a top-level rule would have shipped: both panes hold it, so a field-wise fold adopts nothing."""
        store = self._own(self._spec(self.NESTED))
        store.replace({"users": {"u1": {"file_folders": ["/mine"],
                                        "sidebar_width": 200}}})
        self._peer_wrote({"users": {"u1": {"file_folders": ["/theirs"],
                                           "sidebar_width": 300}}})
        store.replace({"users": {"u1": {"file_folders": ["/mine"],
                                        "sidebar_width": 200}}})
        block = self.on_disk("doc.json")["users"]["u1"]
        self.assertEqual(["/mine", "/theirs"], block["file_folders"],
                         "the other pane's registered folder was "
                         "flattened by this pane's save")
        self.assertEqual(200, block["sidebar_width"],
                         "a single choice was merged - the saving pane "
                         "owns it")

    def test_a_uid_this_pane_has_never_seen_arrives_whole(self):
        store = self._own(self._spec(self.NESTED))
        store.replace({"users": {"u1": {"file_folders": []}}})
        self._peer_wrote({"users": {"u2": {"file_folders": ["/theirs"]}}})
        store.replace({"users": {"u1": {"file_folders": []}}})
        self.assertEqual({"u1", "u2"},
                         set(self.on_disk("doc.json")["users"]))


    def test_a_retired_key_a_PEER_still_holds_does_not_come_back(self):
        """Sweeping before handing it over looks identical and does nothing - adoption runs after. ▸p/store-commit-order"""
        store = self._own(self._spec())
        store.replace({"kept": 1})
        self._peer_wrote({"kept": 1, "gone": "old"})
        store.replace({"kept": 1}, retire=("gone",))
        self.assertNotIn("gone", self.on_disk("doc.json"),
                         "a retired key was adopted off the peer's copy "
                         "and written straight back")

    def test_a_key_the_document_drops_is_GONE(self):
        """Delete-by-omission is what the callers here do - a migration pops the key it consumed."""
        store = self._own(self._spec())
        store.replace({"a": 1, "b": 2})
        store.replace({"a": 1})
        self.assertEqual({"a": 1}, self.on_disk("doc.json"))

    def test_a_falsy_setting_is_an_ANSWER(self):
        store = self._own(self._spec())
        store.replace({"debug": False, "width": 0, "name": ""})
        self.assertEqual({"debug": False, "width": 0, "name": ""},
                         self.on_disk("doc.json"))


    def test_reread_sees_what_another_writer_left(self):
        """load() runs again when Preferences closes and on a library switch, answering with DISK."""
        store = self._own(self._spec())
        store.replace({"a": 1})
        self._peer_wrote({"a": 99})
        self.assertEqual(1, store.get("a"))
        store.reread()
        self.assertEqual(99, store.get("a"))


def _slate_fields():
    """Every attribute the two slate helpers write, read off their own source. ▸p/keyed-store-slate"""
    found = set()
    for helper in (keyed_store.Store._blank_slate,
                   keyed_store.Store._forget_tables):
        tree = ast.parse(textwrap.dedent(inspect.getsource(helper)))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.ctx, ast.Store)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "self"):
                found.add(node.attr)
    return found


def _store_methods(*names):
    """The named methods of `Store`, as AST - so a guard reads the shipped source. ▸p/source-derived-tests"""
    tree = ast.parse(inspect.getsource(keyed_store))
    for klass in ast.walk(tree):
        if isinstance(klass, ast.ClassDef) and klass.name == "Store":
            for scope in klass.body:
                if (isinstance(scope, ast.FunctionDef)
                        and scope.name in names):
                    yield scope


class TheStoresBlankSlate(StoreCase):
    """What a Store forgets before a load, at all three doors. ▸p/keyed-store-slate"""

    def _spec(self, normalise):
        return keyed_store.Spec(
            filename="slate.json", payload="slate",
            keyspace=keyed_store.KEY_ID, label="A slate", noun="entry",
            normalise=normalise)

    def _store(self, normalise=lambda value: value):
        return keyed_store.own_store(self._spec(normalise), self.prefs)

    def _wrote(self, table):
        with open(self.path("slate.json"), "w", encoding="utf-8") as handle:
            json.dump({"slate": table}, handle)

    def test_a_latched_load_forgets_what_it_had_already_kept_aside(self):
        """The gap this family closed: an unreadable file emptied two tables and left `_foreign` holding a part-read row."""
        def normalise(value):
            if value == "boom":
                raise ValueError("this row cannot be read")
            return "" if value == "foreign" else value

        self._wrote({"a": "foreign", "b": "boom"})
        store = self._store(normalise)
        self.assertEqual(keyed_store.BLIND, store.state)
        self.assertEqual(
            {}, store._foreign,
            "a file that would not parse left the entries an earlier row "
            "had put aside sitting in memory")

    def test_the_whole_slate_is_written_by_the_helper(self):
        """Derived from the helpers, so a field joining the list is guarded the day it joins."""
        store = self._store()
        store._blank_slate()
        blank = {name: copy.deepcopy(getattr(store, name))
                 for name in _slate_fields()}
        for name in blank:
            setattr(store, name, {"dirty": 1})
        store._blank_slate()
        self.assertEqual(
            blank, {name: getattr(store, name) for name in blank},
            "a field the slate names was not put back by the helper")

    def test_a_reread_writes_the_slate_rather_than_its_own_list(self):
        """Fires when a door stops calling the helper - the failure that left one debug door short of the record counter."""
        self._wrote({"a": {"kept": 1}})
        store = self._store()
        for name in _slate_fields():
            setattr(store, name, {"dirty": 1})
        store.reread()
        self.assertEqual({"a": {"kept": 1}}, store.everyones())
        for name in ("_foreign", "_orphans"):
            self.assertNotIn("dirty", getattr(store, name),
                             "%s survived a reread" % name)

    def test_no_reset_door_keeps_its_own_copy_of_the_list(self):
        """Two hand-kept copies is what let `_foreign` be forgotten at one door and not the other."""
        owned = _slate_fields()
        found = []
        for scope in _store_methods("__init__", "reread"):
            for node in ast.walk(scope):
                if (isinstance(node, ast.Attribute)
                        and isinstance(node.ctx, ast.Store)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "self"
                        and node.attr in owned):
                    found.append("%s assigns %s" % (scope.name, node.attr))
        self.assertEqual(
            [], sorted(found),
            "the slate is written outside the helper: %s"
            % ", ".join(sorted(found)))

    def test_neither_retire_door_stages_its_own_commit(self):
        """Both doors resolve WHICH keys are doomed and hand them to one tail; only the tail commits."""
        found = []
        for scope in _store_methods("retire", "retire_stored"):
            for node in ast.walk(scope):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "_commit"):
                    found.append(scope.name)
        self.assertEqual(
            [], sorted(found),
            "a retire door stages and commits its own write: %s"
            % ", ".join(sorted(found)))

    def test_retiring_nothing_is_unchanged_at_both_doors(self):
        """An empty list is not a failure, and `retire` answers it BEFORE it asks who the user is."""
        spec = self._spec(lambda value: value)
        spec.user_tagged = True
        store = keyed_store.own_store(spec, _Prefs(self.dir, library_user=""))
        for answer in (store.retire(()), store.retire_stored(())):
            self.assertTrue(
                answer, "doing nothing was refused for want of a user")
            self.assertEqual(keyed_store.REASON_UNCHANGED, answer.reason)


class ReRegisterKeepsTheBinding(StoreCase):

    def test_a_module_reload_does_not_unbind_the_store(self):
        """`register` says re-registering is safe for a module reload - so a re-register carrying no normaliser must keep the one already bound, or every store whose BINDER module is not also reloaded opens broken."""
        original = keyed_store._registry[notes.NOTES_FILE]
        self.addCleanup(
            keyed_store._registry.__setitem__, notes.NOTES_FILE, original)
        self.assertIsNotNone(
            original.normalise,
            "notes.json arrived unbound - nothing below tests the "
            "reload survival it is about")
        keyed_store.register(
            filename=notes.NOTES_FILE, payload="notes",
            keyspace=keyed_store.KEY_MIXED, path_prefix="file:",
            label="Comments", noun="comment", category="notes")
        self.assertIs(
            original.normalise,
            keyed_store._registry[notes.NOTES_FILE].normalise,
            "a re-register with no normaliser dropped the binding - a "
            "keyed_store reload would leave every un-reloaded binder's "
            "store opening with spec.normalise None")


class ALocationIsAnIdAndItsPathIsAProperty(unittest.TestCase):
    """The location-id design: state hangs on the id, the path is one shared editable property, so a move is one field edit and no key ever embeds a dead path."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_locid_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        keyed_store.release()
        self.addCleanup(keyed_store.release)
        locations.forget()
        self.addCleanup(locations.forget)
        self.prefs = _Prefs(self.dir)

    def _reg(self, name, prefs=None):
        path = os.path.join(self.dir, name)
        os.makedirs(path, exist_ok=True)
        locations.register(prefs or self.prefs, path)
        return path

    def test_registering_mints_one_id_and_reuse_finds_it(self):
        folder = self._reg("tex")
        lid = locations.location_id(self.prefs, folder)
        self.assertTrue(lid, "registering minted no id")
        self.assertEqual(lid, locations.location_id(self.prefs, folder),
                         "asking twice minted twice")

    def test_loc_keys_are_ids_to_every_store(self):
        self.assertFalse(locations.SPEC.is_path_key("loc:abc123"),
                         "a location-id key reads as a path")
        self.assertFalse(
            locations.FAVOURITES_SPEC.is_path_key("loc:abc123/wood.png"))
        self.assertFalse(notes.SPEC.is_path_key("file:loc:abc123/wood.png"))
        self.assertEqual(
            "loc:abc123/wood.png",
            keyed_store.storage_key(tile_icons.SPEC, "loc:abc123/wood.png"),
            "storage spelling mangled an id key")

    def test_a_star_survives_a_move_untouched(self):
        folder = self._reg("tex")
        ident = locations.file_ident(self.prefs,
                                     os.path.join(folder, "wood.png"))
        self.assertTrue(ident.startswith("loc:"),
                        "premise: the file is owned by its location")
        locations.set_favourite(self.prefs, ident, True)

        new = os.path.join(self.dir, "textures")
        os.makedirs(new)
        locations.relocate_record(self.prefs, folder, new)

        moved = locations.file_ident(self.prefs,
                                     os.path.join(new, "wood.png"))
        self.assertEqual(ident, moved,
                         "the file's identity changed with the path")
        self.assertTrue(locations.is_favourite(self.prefs, moved),
                        "the star was keyed to the path after all")

    def test_the_move_reaches_every_user_at_once(self):
        folder = self._reg("tex")
        ident = locations.file_ident(self.prefs,
                                     os.path.join(folder, "wood.png"))
        other = _Prefs(self.dir, library_user=SECOND_USER)
        self._reg("tex", prefs=other)
        self.assertEqual(locations.location_id(self.prefs, folder),
                         locations.location_id(other, folder),
                         "one folder minted two identities")
        locations.set_favourite(other, ident, True)

        new = os.path.join(self.dir, "textures")
        os.makedirs(new)
        locations.relocate_record(self.prefs, folder, new)

        self.assertIn(hostos.canonical_path_key(new),
                      [hostos.canonical_path_key(p) for p in
                       locations.registered_paths(other)],
                      "the move did not reach the other user's sidebar")
        self.assertTrue(
            locations.is_favourite(
                other, locations.file_ident(
                    other, os.path.join(new, "wood.png"))),
            "the other user's star waited for their own Locate")

    def test_the_innermost_location_owns_the_file(self):
        outer = self._reg("a")
        inner = self._reg(os.path.join("a", "b"))
        ident = locations.file_ident(self.prefs,
                                     os.path.join(inner, "wood.png"))
        self.assertTrue(
            ident.startswith(
                "loc:" + locations.location_id(self.prefs, inner) + "/"),
            "the outer location captured a file the inner one owns")

    def test_legacy_path_keys_convert_on_load(self):
        folder = os.path.join(self.dir, "tex")
        os.makedirs(folder)
        stored = hostos.storage_path_key(folder)
        star = hostos.storage_path_key(os.path.join(folder, "wood.png"))
        tag = test_support.FIXTURE_USER + keyed_store.USER_SEP
        store = keyed_store.open_store(locations.SPEC, self.prefs)
        store.rekey_stored({})    # premise: the door exists
        store._table[tag + stored] = {"registered": True, "name": "Old"}
        favourites = keyed_store.open_store(locations.FAVOURITES_SPEC,
                                            self.prefs)
        favourites._table[tag + star] = {"favourite": True}

        locations.convert_to_ids(self.prefs)

        lid = locations.location_id(self.prefs, folder)
        self.assertTrue(lid, "conversion minted no id for the old record")
        self.assertEqual("Old",
                         locations.record(self.prefs, folder).get("name"))
        ident = locations.file_ident(self.prefs,
                                     os.path.join(folder, "wood.png"))
        self.assertTrue(favourites.has(ident),
                        "the old star was not re-homed onto the id")
        self.assertFalse(favourites.has(star),
                         "the old path key is still there beside it")

    def test_two_minted_ids_collapse_to_one(self):
        folder = self._reg("tex")
        keep = locations.location_id(self.prefs, folder)
        rival = "ffffffffffffffffffffffffffffffff"
        ids = keyed_store.open_store(locations.IDS_SPEC, self.prefs)
        ids._table[rival] = {"path": hostos.storage_path_key(folder)}
        favourites = keyed_store.open_store(locations.FAVOURITES_SPEC,
                                            self.prefs)
        tag = test_support.FIXTURE_USER + keyed_store.USER_SEP
        favourites._table[tag + "loc:" + rival + "/wood.png"] = {
            "favourite": True}

        locations.convert_to_ids(self.prefs)

        self.assertEqual(keep, locations.location_id(self.prefs, folder),
                         "the collapse kept the wrong id")
        self.assertNotIn(rival, ids.all(), "the rival id row survived")
        self.assertTrue(
            favourites.has("loc:" + keep + "/wood.png"),
            "the rival's star did not move to the surviving id")

    def test_a_collapse_never_deletes_a_conflicting_value(self):
        """Two machines minted rival ids offline and BOTH decorated the same thing - the collapse keeps the winner's value AND leaves the rival's row and id in place rather than silently overwriting either."""
        folder = self._reg("tex")
        keep = locations.location_id(self.prefs, folder)
        ident = locations.file_ident(self.prefs,
                                     os.path.join(folder, "wood.png"))
        rival = "ffffffffffffffffffffffffffffffff"
        ids = keyed_store.open_store(locations.IDS_SPEC, self.prefs)
        ids._table[rival] = {"path": hostos.storage_path_key(folder)}
        notes_store = keyed_store.open_store(notes.SPEC, self.prefs)
        notes_store._table["file:" + ident] = {
            "items": [{"t": "text", "text": "mine"}]}
        notes_store._table["file:loc:" + rival + "/wood.png"] = {
            "items": [{"t": "text", "text": "theirs"}]}

        locations.convert_to_ids(self.prefs)

        self.assertEqual(
            [{"t": "text", "text": "mine"}],
            notes_store.get("file:" + ident).get("items"),
            "the winner's comment was overwritten by the rival's")
        self.assertIn(
            "file:loc:" + rival + "/wood.png", notes_store.everyones(),
            "the rival's conflicting comment was silently deleted")
        self.assertIn(rival, ids.all(),
                      "the rival id was retired while a row of its "
                      "could not move - orphaning the comment for good")

    def test_removal_retires_the_identity_and_every_users_keys(self):
        folder = self._reg("tex")
        lid = locations.location_id(self.prefs, folder)
        ident = locations.file_ident(self.prefs,
                                     os.path.join(folder, "wood.png"))
        locations.set_favourite(self.prefs, ident, True)
        other = _Prefs(self.dir, library_user=SECOND_USER)
        locations.set_favourite(other, ident, True)

        keyed_store.retire_location(self.prefs, lid)
        locations.drop_location_id(self.prefs, lid)

        favourites = keyed_store.open_store(locations.FAVOURITES_SPEC,
                                            self.prefs)
        self.assertEqual(
            [], [k for k in favourites.everyones() if lid in k],
            "a removed location's stars survived for some user")
        self.assertEqual("", locations.location_id(self.prefs, folder),
                         "the identity row survived the removal")


class OnlyAUidShapedOwnerCountsAsATagTest(unittest.TestCase):
    """A pipe is legal in a POSIX path, so an untagged path carrying one must not read as somebody's row - only the 32-hex uuid4 shape is an owner."""

    def test_a_pipe_in_an_untagged_path_stays_untagged(self):
        self.assertEqual(
            ("", "/plates/wei|rd"),
            keyed_store.untagged_key(locations.SPEC, "/plates/wei|rd"))

    def test_a_tagged_pipe_path_splits_at_the_tag(self):
        from amaze.tests import test_support
        uid = test_support.FIXTURE_USER
        self.assertEqual(
            (uid, "/plates/wei|rd"),
            keyed_store.untagged_key(
                locations.SPEC, uid + "|/plates/wei|rd"))


class AnUnreadablePeerIsNotOverwritten(StoreCase):
    """The second read has the first read's refusal, or a peer's work is lost."""

    def _damage(self, text=b'{"notes": {"a": '):
        with open(self.path(), "wb") as handle:
            handle.write(text)
        return text

    def test_a_write_over_an_unparseable_file_is_refused(self):
        store = self.store()
        self.assertTrue(store.set("a", self.page()).ok, "premise: it writes")

        damaged = self._damage()
        written = store.set("b", self.page("second"))

        self.assertFalse(
            written.ok,
            "the store wrote over a file it could not read, so whatever the "
            "other machine put there is gone")
        with open(self.path(), "rb") as handle:
            self.assertEqual(damaged, handle.read(),
                             "the damaged bytes were replaced")

    def test_the_unreadable_file_is_kept_beside_itself(self):
        store = self.store()
        self.assertTrue(store.set("a", self.page()).ok, "premise: it writes")
        damaged = self._damage()

        store.set("b", self.page("second"))

        kept = self.path() + ".unreadable"
        self.assertTrue(os.path.exists(kept),
                        "no copy of the damaged file was kept, and the "
                        "snapshot tier declines one that will not parse")
        with open(kept, "rb") as handle:
            self.assertEqual(damaged, handle.read())

    def test_the_refusal_latches_for_the_session(self):
        store = self.store()
        self.assertTrue(store.set("a", self.page()).ok, "premise: it writes")
        self._damage()
        store.set("b", self.page("second"))

        self.assertFalse(store.writable,
                         "the store stayed writable, so the next edit "
                         "overwrites the damaged file after all")

    def test_this_sessions_own_rows_are_still_readable(self):
        """A refused write keeps the panel's own table - it is not a reload."""
        store = self.store()
        store.set("a", self.page("mine"))
        self._damage()
        store.set("b", self.page("second"))

        self.assertEqual(self.page("mine"), store.get("a"),
                         "the refusal threw away this session's own rows")


if __name__ == "__main__":
    unittest.main()
