"""The Keyed Store Engine: one guarded side table, for every store.

BATCH 2 of the four-areas restructure. Three stores were the same store
implemented three times - notes.json, icons.json and the four
per-location preference dicts - each with its own copy of a guard set,
and each copy missing a different part of it. `notes.py`'s docstring
said its guards were icons.json's, "copied deliberately"; they were
not, and the tuple it passed to prove the one guard it did have was a
no-op.

What is tested here is the ENGINE's guarantees, not a store's shape:

* absence is a VERDICT the engine resolves, never a value a caller gets;
* a read hands out a COPY, a write STAGES and commits only on success;
* the registry is the ONE enumeration, so Repair cannot be one short;
* a key lifecycle (a folder moved, a location is gone) is announced by
  its owner and fanned out by the engine.

Every path here is inside a temp dir. Nothing reads the machine's own

are real photograph archives.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import keyed_store, locations, notes, tile_icons  # noqa: E402
from amaze.helpers import hostos  # noqa: E402


class _Prefs:
    """Only what a store reads: where the library is."""

    def __init__(self, directory):
        self.dir = directory


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


class TestModeKeepsItsLocationsToItself(StoreCase):
    """A test library gets its OWN locations, in both directions.

    The settings copy is a MIGRATION SEED. Pointing at another library
    is indistinguishable from the two accidents that seeding exists
    for - a restored snapshot, a hand-deleted `locations.json` - so on
    2026-08-08 the very first switch handed the test library the real
    library's registered folders, and the mirror would then have
    carried the test set back into the copy, arming a future repair of
    the REAL library with test data.
    """

    def _switched(self, keep_calls):
        """A prefs the way the switch leaves one: Test Mode on, a copy
        of the real library's folders still in settings, and a library
        that has never held a locations.json."""
        p = _Prefs(self.dir)
        p.test_mode = True
        p.test_dir = self.dir
        p.data = {locations.MIGRATED_KEY: True}
        p.last_known_folders = ["/Users/someone/Real/Textures"]
        p.last_known_records = {
            "/Users/someone/Real/Textures": {"registered": True}}
        p.keep_last_known = lambda *a: keep_calls.append(a)
        # The migration persists, and the shared stub is deliberately
        # minimal - so this supplies what only that path needs.
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
        """The dangerous direction: the copy is what a later repair of
        the REAL library reads."""
        calls = []
        p = self._switched(calls)
        locations.register(p, os.path.join(self.dir, "probe"))

        self.assertEqual(
            [], calls,
            "the test library rewrote the settings copy, which is the "
            "seed a repair of the real library reads")

    def test_its_own_locations_still_work(self):
        """Isolated, not disabled - the test library keeps what is
        registered in it."""
        calls = []
        p = self._switched(calls)
        folder = os.path.join(self.dir, "probe")
        locations.register(p, folder)

        self.assertIn(folder, locations.registered_paths(p))

    def test_a_normal_library_still_migrates(self):
        """The isolation is keyed on Test Mode alone: with it off, the
        seeding that recovers a restored snapshot is untouched."""
        calls = []
        p = self._switched(calls)
        p.test_mode = False

        self.assertEqual(["/Users/someone/Real/Textures"],
                         locations.paths(p),
                         "the migration stopped running for ordinary "
                         "libraries too")


class AbsenceIsAVerdict(StoreCase):
    """`if os.path.exists(path):` with no `else` is what icons.json
    was: a missing file read as "this library has no chosen icons", so
    one pick rewrote the whole table as a one-key file. There is no
    such branch in any store now, because absence is resolved once, by
    the engine, into an answer a caller cannot mistake for data."""

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
        """The 178-black-tiles shape, one level down: a sync
        placeholder still arriving, a conflict rename or a partial
        restore all look like an empty library for one instant."""
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
        """THE FINDING, in one test. icons.json had no absent-but-known
        branch at all - and it did not get one by having a branch
        written for it. It got one by being declared."""
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
    """snapshot_before_write copies what is ALREADY on disk and rightly
    declines when there is nothing there - so a store written exactly
    once had no trace of any kind, and absent-but-known cannot find
    evidence that was never written.

    Measured on the real library 2026-08-03: notes.json has all four
    tiers and icons.json is absent with none, so the first icon ever
    picked was also the one write with nothing behind it."""

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
        """A permanent floor made of garbage is worse than no floor: a
        single half-synced launch used to mint the one copy that never
        rotates from a truncated file.

        The file has to EXIST for this to reach the guard - the first
        version of this test pointed at a path that was not there, so
        it returned False before the parse check and was green with
        the guard deleted."""
        target = self.path("icons.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("{ truncated")
        self.assertFalse(hostos.seed_restore_floor(target))
        self.assertFalse(os.path.exists(target + ".bak-first"))

    def test_calling_it_twice_never_replaces_the_floor(self):
        """Directly, because the caller only reaches it on a CREATE -
        so the write-once rule inside it has no other way to be held."""
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
    """The engine's own rule is that the cache moves only on success,
    and `_table` obeys it. `_foreign` does not: `_commit` adopts the
    peer's foreign entries and pops the caller's keys BEFORE the write,
    and the `except OSError` returns without putting them back.

    A foreign entry is a value a NEWER build wrote that this one's
    normaliser cannot read - held verbatim so a rewrite never erases
    it. Losing it from memory means the next successful write of any
    other key serialises the file without it."""

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
        """What the memory state costs on disk - the question the user
        would actually notice."""
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
        """The accept path: a key the user SET stops being foreign, or
        the unreadable copy shadows the value just chosen."""
        store = self._with_a_foreign_entry()
        self.assertTrue(store.set("material:K", self.page("mine")))
        self.assertNotIn("material:K", store._foreign)
        self.assertEqual(self.page("mine"),
                         self.on_disk()["notes"]["material:K"])


class ReleasingONELibrarysTablesActuallyDropsThem(StoreCase):
    """`release(preferences)` compared `os.path.dirname(<dir>/notes.json)`,
    which carries no trailing separator, against `preferences.dir`, which
    `prefs._normalised_dir` guarantees ends with one - so the per-library
    branch could never match and the call released nothing at all.

    Latent when found: all three production callers pass no argument and
    take the clear-everything path. It reads as the library-switch hook
    and is the one live requirement the two retired `forget_*` wrappers
    each half-expressed, so it will be wired up as one."""

    def test_the_named_librarys_tables_are_dropped(self):
        """THE PRODUCT'S OWN SPELLING, deliberately. `prefs.dir` is
        passed through `prefs._normalised_dir`, which guarantees a
        trailing `/` - and `os.path.dirname` of the store path never has
        one, so the comparison could not match for any real Prefs.

        `StoreCase`'s `_Prefs` hands out a bare `mkdtemp` path, which is
        why every other test in this file happens to sit on the one
        spelling that worked (practice.md ▸ *A FIXTURE MUST WRITE FILES
        THE WAY THE PRODUCT DOES* - the same shape, pointed at an
        argument rather than a file)."""
        self.store().set("material:1", self.page())
        self.assertTrue(keyed_store._open, "premise: a table is cached")
        keyed_store.release(_Prefs(self.dir + os.sep))
        self.assertFalse(
            keyed_store._open,
            "release named a library and dropped nothing - the previous "
            "library's tables stay resident with their state, their "
            "unreadable entries and their disk fingerprint")

    def test_the_separatorless_spelling_matches_too(self):
        """Both spellings name one library, and the store must not care
        which one the caller happens to hold."""
        self.store().set("material:1", self.page())
        keyed_store.release(_Prefs(self.dir))
        self.assertFalse(keyed_store._open,
                         "the bare-path spelling matched nothing")

    def test_another_librarys_tables_are_KEPT(self):
        """The accept path: release names ONE library. Dropping every
        table whatever the argument is the same outage as dropping none,
        wearing the opposite face."""
        self.store().set("material:1", self.page())
        keyed_store.release(_Prefs(os.path.join(self.dir, "elsewhere")))
        self.assertTrue(
            keyed_store._open,
            "a release aimed at another library took this one's tables")


class AReadHandsOutACopy(StoreCase):
    """`notes()` used to return the live cache. A caller holding that
    could mutate the table without writing anything - so a REFUSED save
    still lit the tile's comment badge, and a later sweep read the
    phantom back and wrote its text a second time."""

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
        """A bare False could not tell a read-only folder from a file
        that would not parse - and the panel guessed, telling the user
        to check the folder was writable when the folder was fine."""
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
        """`wrong_table_shape` reads a MISSING payload key as a valid
        empty table, so icons.json copied over notes.json parses, reads
        as zero notes, and the next note written replaces the file."""
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump({"icons": {"/a.exr": {"name": "box"}}}, handle)
        store = self.store()
        self.assertEqual(keyed_store.BLIND, store.state)
        self.assertFalse(store.set("material:1", self.page()))

    def test_a_byte_order_mark_is_read_not_latched(self):
        """A BOM is what a Windows editor leaves behind. Reading plain
        utf-8 made that file "damaged" and latched the whole store."""
        with open(self.path(), "wb") as handle:
            handle.write(b"\xef\xbb\xbf" + json.dumps(
                {"notes": {"material:1": self.page("from windows")}}
            ).encode("utf-8"))
        store = self.store()
        self.assertEqual(keyed_store.READ, store.state)
        self.assertTrue(store.has("material:1"))


class TheRegistryIsTheOneEnumeration(StoreCase):

    def test_it_can_be_read_without_qt_or_houdini(self):
        """Repair must be able to name these files on a machine where
        Houdini will not start, and `tile_icons`' normaliser pulls in
        Qt - so WHICH files exist is declared apart from what a valid
        value of one is."""
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
        """The SURVEY, not just the helper that names them. Asserting
        the helper alone left the survey free to loop over the four
        databases and ignore it - which is what it did for a day."""
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
        """`tools/library-audit.py` keeps its OWN literal, on purpose -
        it promises to run with no import from the package, in a hook,
        on a machine where Houdini will not start. A second list is
        allowed only when a test makes drift RED, which is what this
        is: the audit's copy grew the side tables on 2026-08-02 and
        Repair's copy stayed narrow, silently, for a day."""
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

    def test_a_side_table_can_be_counted_by_the_restore_picker(self):
        """It counted a 40-note notes.json as "1 settings", so the
        restore refusal that compares record counts never fired."""
        from amaze.helpers import restore as restore_lib

        store = self.store()
        for n in range(7):
            store.set("material:%d" % n, self.page("n%d" % n))
        facts = restore_lib.info(self.path())
        self.assertEqual(7, facts["count"])
        self.assertEqual("comments", facts["noun"])


class TheStoreSpeaksPortableSpelling(StoreCase):
    """Path keys are stored VARIABLE-RELATIVE - `$AMAZE/...` under the
    install tree, `~/...` under home, absolute only when neither covers
    it - so one entry resolves on every machine that shares the library
    (the 2026-08-06 unification, devlog #416).

    The API keeps speaking absolutes: callers pass whatever spelling
    they hold, the store converts at its own boundary, and every legacy
    spelling is absorbed on LOAD - the real favourites held the same
    file under three spellings at once, which is the disease, measured."""

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
        """Three spellings of ONE file - the absolute, the home form,
        and an uncollapsed dot-dot absolute - are one entry after a
        load, first in wins, and a lookup by any spelling finds it."""
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
        """The sidebar and the scanner need paths `os.walk` can open;
        the FILE needs paths the other machine can resolve. The store
        holds the portable spelling, the reader hands back the
        absolute."""
        home = self._fake_home("plates/a.exr")
        absolute = home + "/plates"
        locations.register(self.prefs, absolute)
        locations.set_favourite(self.prefs, absolute + "/a.exr", True)
        stored = self.on_disk(keyed_store.LOCATIONS)["locations"]
        self.assertEqual(["~/plates"], list(stored),
                         "locations.json carries the machine's spelling")
        self.assertEqual([absolute],
                         locations.registered_paths(self.prefs),
                         "the reader hands back a spelling the scanner "
                         "cannot walk")
        self.assertTrue(
            locations.is_favourite(self.prefs, absolute + "/a.exr"))
        self.assertEqual([absolute + "/a.exr"],
                         locations.favourite_paths(self.prefs))


class TheKeyLifecycle(StoreCase):
    """The owner announces; the ENGINE fans out. A caller that
    enumerates the stores is a list someone can write short, and both
    of the callers that did had already been written short - the
    relocate hook named four preferences and neither side table, the
    removal hook named two of those same four."""

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
        """notes.json holds `material:<id>` beside `file:<path>` in ONE
        file, and the on-disk format cannot change. Which keys a folder
        move may rewrite is therefore the declared PREFIX - get it
        wrong and either every File note is orphaned or every asset id
        is rewritten."""
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
        """
        comments and icons". Removal means removal; re-adding the
        folder gives a clean slate.

        This reverses the behaviour ui-text.md documented since
        2026-07-31 ("captures and favorites are kept"), which is why
        the wording moved in the same change."""
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
        """The other half, and the one that matters more: forgetting a
        folder must not reach an asset's comment or another folder."""
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
        """The bug this pins, found by driving the real thing rather
        than by a test: `relocate` stripped the `file:` prefix before
        comparing and `retire_prefix` did not, so a removal swept the
        locations and the icons and silently left every comment behind.
        Two places asking one question, one of them wrong - which is
        the shape this whole engine exists to end, grown inside the
        engine itself within the hour."""
        key = notes.note_key("file", "/gone/a.exr")
        self.assertTrue(keyed_store._under(notes.SPEC, key, "/gone/"))
        self.assertTrue(keyed_store._under(notes.SPEC, key, "/gone"))
        self.assertFalse(keyed_store._under(notes.SPEC, key, "/go/"))
        self.assertFalse(
            keyed_store._under(notes.SPEC,
                               notes.note_key("material", "/gone/a.exr"),
                               "/gone/"),
            "an asset id shaped like a path was swept by a folder removal")
        # ASSERT THE CALL, NOT THE TEXT. This read
        # `"_bare_path(" in inspect.getsource(func)` - and getsource
        # returns COMMENTS, so an inlined copy of the rule with the
        # words `_bare_path(...)` left behind in a comment satisfied
        # it. Proved 2026-08-03: inlining the rule in both functions
        # made `_bare_path` dead code and the test stayed green.
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

    def test_favourites_are_in_the_registry_too(self):
        """They were swept by hand in the base folder model - a second
        list, with the same failure mode as the first two.

        A real library file since 2026-08-05, so this now reads the
        store rather than a settings attribute: it used to seed a plain
        list on the stub and assert against that same list, which the
        engine could only satisfy while it was reaching into prefs.
        """
        store = keyed_store.open_store(locations.FAVOURITES_SPEC, self.prefs)
        store.update({"/gone/a.exr": True, "/kept/b.exr": True})
        keyed_store.retire_prefix(self.prefs, "/gone/")
        self.assertEqual(["/kept/b.exr"], sorted(store.all()),
                         "a removed location's favourites outlived it")

    def test_a_store_created_by_its_own_write_reports_READ(self):
        """`state` was set once at load and never moved, so a store that
        wrote itself into existence went on answering FRESH - "absent,
        and nothing says it was ever here" - for the rest of the
        session. Any caller telling "no file at all" apart from "a file
        holding nothing" got the wrong answer, and one did: a rule keyed
        on FRESH fired after the last key was removed and put it back.
        """
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
        """The case that matters: removing the last key writes a real
        file holding an empty table. That is READ - a file that is
        there - and NOT the same thing as no file at all."""
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
    """An entry the CURRENT build's normaliser rejects is not junk to
    delete - it is usually a NEWER build's data: an icon name this
    build's Feather set lacks, a record shape from next year. The load
    keeps it aside verbatim, invisible to readers, and every commit
    writes it back - an older build must not erase what a newer one
    wrote into the shared file."""

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


class EveryDoorSpeaksThePortableSpelling(StoreCase):
    """set/get/has convert keys at the boundary (storage_key); update,
    rekey and retire took raw strings - so a caller speaking absolutes
    grew a SECOND spelling of a key the table already held, and the
    next load kept only the first: the newer entry's data silently
    dropped."""

    def _table(self, name="locations.json"):
        document = self.on_disk(name)
        return next(iter(document.values()))

    def test_update_rekey_and_retire_match_the_stored_spelling(self):
        target = os.path.join(os.path.expanduser("~"), "amaze-seam-loc")
        moved = os.path.join(os.path.expanduser("~"), "amaze-seam-two")
        store = keyed_store.open_store(locations.SPEC, self.prefs)
        store.set(target, {"registered": True})
        self.assertTrue(
            all(key.startswith("~") for key in self._table()),
            "premise: a home path is stored in the portable spelling")

        store.update({target: {"registered": True, "name": "Seam"}})
        self.assertEqual(
            1, len(self._table()),
            "update grew a second spelling of a key the table held")

        store.rekey({target: moved})
        table = self._table()
        self.assertEqual(1, len(table), "rekey grew a second spelling")
        self.assertTrue(next(iter(table)).startswith("~"),
                        "rekey stored the raw absolute destination")

        store.retire([moved])
        self.assertEqual(
            {}, self._table(),
            "retire missed the stored spelling - the location's record "
            "outlives the location")


class ARecordCarriesFieldsItDoesNotKnow(StoreCase):
    """The engine keeps whole foreign ENTRIES; the adapters keep
    foreign FIELDS inside entries they accept - the same reason at the
    next level down. A location record rebuilt from the five known
    fields dropped whatever a newer build had added, on the first write
    from an older one."""

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


if __name__ == "__main__":
    unittest.main()
