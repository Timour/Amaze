"""Database-layer hardening: the read, the migration and the merge."""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import database
from amaze.helpers import hostos                             # noqa: E402
from amaze.tests import test_support                        # noqa: E402

SCHEMA = database.SCHEMA_VERSION


class _Case(unittest.TestCase):
    """A private library directory and a clean connector registry."""

    FILENAME = "cops.json"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_dbhard_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, self.FILENAME)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _document(self, count=3, version=None):
        # Today's stamp by default: an older one lands on the refusal path.
        return {
            "version": (database.SCHEMA_VERSION if version is None
                        else version),
            "categories": ["_All", "Wood"],
            "tags": ["rough"],
            "assets": [{"id": "ASSET%d" % i, "name": "mat %d" % i}
                       for i in range(count)],
        }

    def _write(self, data, encoding="utf-8", path=None):
        # A fixture that lays a file down differently from the product is none.
        with open(path or self.path, "w", encoding=encoding,
                  newline="\n") as handle:
            json.dump(data, handle, indent=4)

    def _connector(self):
        return database.DatabaseConnector(self.FILENAME)

    def _load(self):
        db = self._connector()
        return db, db.load(self.dir + os.sep)

    def _on_disk(self, path=None):
        with open(path or self.path, encoding="utf-8-sig") as handle:
            return json.load(handle)


class TheSmallBatchTest(_Case):
    """The version-key guards, every-trace refusals, and the SVG cache."""

    def test_a_malformed_version_key_is_read_as_legacy(self):
        """`int(None)` raises `TypeError`, which no caller here catches."""
        for broken in (None, [], {}, "not a number"):
            with self.subTest(version=broken):
                document = self._document()
                document["version"] = broken
                self._write(document)
                test_support.reset_database_singletons()
                db, data = self._load()
                self.assertEqual(3, len(data["assets"]),
                                 "a malformed version cost the rows")

    def test_a_library_switch_forgets_the_old_schema_number(self):
        """The seed branch skips `_migrate`, and a stamped file never migrates."""
        ahead = self._document()
        ahead["version"] = 99
        self._write(ahead)
        db, _ = self._load()
        self.assertEqual(99, db._loaded_version, "premise")
        second = tempfile.mkdtemp(prefix="amaze_dbhard2_")
        self.addCleanup(shutil.rmtree, second, ignore_errors=True)
        db.reload_with_path(second + os.sep)
        self.assertEqual(
            SCHEMA, db._loaded_version,
            "the new library inherited the old one's schema number")

    def test_a_refusal_names_every_trace_not_the_first(self):
        """One refusal for every trace, or each run spends a recovery copy."""
        self._write(self._document())
        for tier in ("bak-1", "bak-2", "bak-3"):
            shutil.copyfile(self.path, "%s.%s" % (self.path, tier))
        os.remove(self.path)
        with test_support.captured_log() as log:
            self._load()
        notes = [str(record.get("msg", "")) for record in log.records()]
        named = [note for note in notes
                 if all("%s.%s" % (self.FILENAME, tier) in note
                        for tier in ("bak-1", "bak-2", "bak-3"))]
        self.assertTrue(
            named,
            "no single sentence names all three traces, so following "
            "it costs a run and a recovery copy each time: %s" % notes)

    def test_the_online_search_takes_a_tags_only_prefix(self):
        from amaze.core import matx_library
        self.assertEqual(("stone", False),
                         matx_library.split_search("stone"))
        self.assertEqual(("stone", True),
                         matx_library.split_search(":stone"))
        self.assertEqual(("stone", True),
                         matx_library.split_search(": stone "))
        self.assertEqual(
            ("", False), matx_library.split_search(""),
            "an empty box is not a search")
        self.assertEqual(
            "", matx_library.split_search(":")[0],
            "a bare colon is mid-typing - an empty needle, so the "
            "grid is not narrowed to nothing between keystrokes")


class LoadDoesNotMarryCachedDataToANewPathTest(unittest.TestCase):
    """`load` takes the switch door itself when the path moves under a singleton."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.a = tempfile.mkdtemp(prefix="amaze_marry_a_")
        self.b = tempfile.mkdtemp(prefix="amaze_marry_b_")
        for folder in (self.a, self.b):
            self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        for folder, row in ((self.a, "ROW_A"), (self.b, "ROW_B")):
            with open(os.path.join(folder, "library.json"), "w",
                      encoding="utf-8") as handle:
                json.dump({"version": SCHEMA,
                           "categories": ["_All"], "tags": [],
                           "assets": [{"id": row, "name": row}]},
                          handle)

    def test_a_switched_path_answers_the_new_disk(self):
        db = database.DatabaseConnector("library.json")
        first = db.load(self.a + os.sep)
        self.assertEqual(["ROW_A"],
                         [r["id"] for r in first["assets"]],
                         "premise: library A loads")
        second = db.load(self.b + os.sep)
        self.assertEqual(
            ["ROW_B"], [r["id"] for r in second["assets"]],
            "load() answered the previous library's cached rows under "
            "the new path")

    def test_a_switched_path_cannot_write_the_old_rows_into_the_new_file(self):
        db = database.DatabaseConnector("library.json")
        db.load(self.a + os.sep)
        db.load(self.b + os.sep)
        db.save()
        with open(os.path.join(self.b, "library.json"),
                  encoding="utf-8") as handle:
            ids = [r["id"] for r in json.load(handle)["assets"]]
        self.assertNotIn(
            "ROW_A", ids,
            "library A's rows were written into library B's file - the "
            "clobber serves() exists to refuse, reached through load()")


class TheLibraryFormatStampTest(_Case):
    """A stamp ahead of `branding.LIBRARY_FORMAT` latches the session read-only."""

    def test_a_save_stamps_todays_format(self):
        from amaze import branding
        self._write(self._document())
        db, loaded = self._load()
        self.assertTrue(loaded)
        db.set(self._document(count=4))
        self.assertTrue(db.save())
        self.assertEqual(branding.LIBRARY_FORMAT,
                         self._on_disk().get("format"))

    def test_a_format_ahead_library_reads_but_never_writes(self):
        document = self._document()
        document["format"] = 99
        self._write(document)
        with open(self.path, "rb") as handle:
            frozen = handle.read()
        db, data = self._load()
        self.assertEqual(
            3, len(data["assets"]),
            "an ahead-format library must still READ - refusing to "
            "open it helps nobody")
        db.set(self._document(count=5))
        self.assertFalse(db.save(),
                         "a save into a newer format must refuse")
        with open(self.path, "rb") as handle:
            self.assertEqual(frozen, handle.read(),
                             "the refusal wrote bytes anyway")

    def test_a_newer_machines_write_arriving_mid_session_latches(self):
        self._write(self._document())
        db, _loaded = self._load()
        db.set(self._document(count=4))
        self.assertTrue(db.save(), "premise: this session can write")
        foreign = self._document(count=6)
        foreign["format"] = 99
        self._write(foreign)
        db.set(self._document(count=5))
        self.assertFalse(
            db.save(),
            "the other machine upgraded mid-session - stamping our "
            "old format over its file must refuse, not merge")
        self.assertEqual(99, self._on_disk().get("format"),
                         "the newer machine's stamp was overwritten")


class BomPrefixedDatabaseLoadsTest(_Case):
    """A byte-order mark is an ordinary artifact and must not cost the library."""

    def test_a_bom_prefixed_database_loads_at_full_record_count(self):
        self._write(self._document(5), encoding="utf-8-sig")
        with open(self.path, "rb") as handle:
            self.assertTrue(
                handle.read(3) == b"\xef\xbb\xbf",
                "premise: the fixture must actually carry a BOM, or this "
                "test is reading an ordinary file and proving nothing")
        _, data = self._load()
        self.assertEqual(
            5, len(data["assets"]),
            "a BOM-prefixed database did not load - json.load raised on "
            "the marker and the section came up empty")
        self.assertEqual(["_All", "Wood"], data["categories"])

    def test_the_primary_database_is_read_the_same_way(self):
        """The primary has no recovery path and takes its own branch in `load`."""
        self.FILENAME = "library.json"
        self.path = os.path.join(self.dir, "library.json")
        self._write(self._document(4), encoding="utf-8-sig")
        _, data = self._load()
        self.assertEqual(4, len(data["assets"]))

    def test_a_bom_less_database_round_trips_byte_identical(self):
        """The accept path: an ordinary file must not change by one byte."""
        from amaze import branding
        document = self._document(3)
        document["format"] = branding.LIBRARY_FORMAT
        document["version"] = database.SCHEMA_VERSION
        self._write(document)
        with open(self.path, "rb") as handle:
            before = handle.read()
        db, _ = self._load()
        db.save()
        with open(self.path, "rb") as handle:
            after = handle.read()
        self.assertEqual(
            before, after,
            "an ordinary save rewrote the bytes of a BOM-less database - "
            "every no-op save now looks like a change to the sync client")

    def test_nothing_writes_a_bom_back(self):
        """On the read only: a written marker becomes every other reader's problem."""
        self._write(self._document(2), encoding="utf-8-sig")
        db, _ = self._load()
        db.set({"assets": [{"id": "ASSET0"}], "categories": ["_All"],
                "tags": []})
        db.save()
        with open(self.path, "rb") as handle:
            self.assertFalse(
                handle.read(3) == b"\xef\xbb\xbf",
                "the save wrote a byte-order mark of its own")

    def test_a_bom_prefixed_peer_document_merges(self):
        """A parse failure on the merge read latches this session's writes."""
        self._write(self._document(2))
        db, _ = self._load()
        peer = self._document(2)
        peer["assets"].append({"id": "THEIRS1", "name": "theirs"})
        self._write(peer, encoding="utf-8-sig")
        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET1"}],
                "categories": ["_All"], "tags": []})
        db.save()
        self.assertFalse(
            db._write_blocked,
            "a BOM in the other session's file latched this session's "
            "writes - the merge read could not parse it")
        self.assertIn(
            "THEIRS1", [a["id"] for a in self._on_disk()["assets"]],
            "the other session's row was not adopted")


class MigrationFailureLeavesNothingCommittedTest(_Case):
    """A raising migration must not leave a half-document behind."""

    def setUp(self):
        super().setUp()
        self._original = dict(database._MIGRATIONS)
        self.addCleanup(self._restore_migrations)

    def _restore_migrations(self):
        database._MIGRATIONS.clear()
        database._MIGRATIONS.update(self._original)

    def _break_the_migration(self):
        """A step that mutates and then raises: half-applied, not clean."""
        def half_then_raise(data):
            data["categories"] = ["ruined"]
            raise ValueError("migration step blew up halfway")

        database._MIGRATIONS[1] = half_then_raise

    def _v1_document(self):
        """No version key is the implicit legacy schema, so a step runs."""
        return {"categories": ["_All", "Wood"], "tags": ["rough"],
                "assets": [{"id": "ASSET0"}, {"id": "ASSET1"}]}

    def test_a_raising_migration_commits_nothing(self):
        self._write(self._v1_document())
        self._break_the_migration()
        db = self._connector()
        with self.assertRaises(ValueError):
            db.load(self.dir + os.sep)
        self.assertFalse(
            db._data,
            "the connector kept a half-migrated document - save() would "
            "write it as if it were the whole library")
        self.assertIsNone(
            db._disk_stat,
            "premise: the stale-write baseline is not armed on this path, "
            "which is exactly why holding partial data is unsafe")

    def test_the_file_is_untouched_by_the_failed_load(self):
        self._write(self._v1_document())
        with open(self.path, "rb") as handle:
            before = handle.read()
        self._break_the_migration()
        db = self._connector()
        with self.assertRaises(ValueError):
            db.load(self.dir + os.sep)
        db.save()               # the save the panel does anyway
        with open(self.path, "rb") as handle:
            self.assertEqual(before, handle.read(),
                             "a failed migration reached disk")

    def test_a_clean_read_afterwards_re_arms_the_guard(self):
        """Leaving `_data` falsy is why the next load retries rather than answers."""
        self._write(self._v1_document())
        self._break_the_migration()
        db = self._connector()
        with self.assertRaises(ValueError):
            db.load(self.dir + os.sep)
        self._restore_migrations()
        data = db.load(self.dir + os.sep)
        self.assertEqual(
            2, len(data["assets"]),
            "the retry did not read the file - the connector was stuck "
            "holding its failure")
        self.assertEqual(["_All", "Wood"], data["categories"],
                         "the half-applied step's mutation survived into "
                         "the successful load")
        self.assertIsNotNone(db._disk_stat,
                             "the stale-write baseline was never armed")
        db.set({"assets": [{"id": "ASSET0"}], "categories": ["_All"],
                "tags": []})
        db.save()
        self.assertIn("ASSET0", [a["id"] for a in self._on_disk()["assets"]],
                      "an ordinary save after the recovery was refused")


class TheRecordStopsCarryingAFavouriteAndAnIconTest(_Case):
    """A favourite is per-user and a tile icon lives in `icons.json`, not the row."""

    def _v4_document(self):
        return {
            "version": 4, "categories": ["_All"], "tags": [],
            "assets": [
                {"id": "A0", "name": "one", "favorite": True,
                 "icon": {"name": "box", "bg": "#4af2a1"}},
                {"id": "A1", "name": "two", "favorite": False},
            ],
        }

    def test_both_fields_come_off_every_row(self):
        self._write(self._v4_document())
        _db, data = self._load()
        self.assertEqual(SCHEMA, data["version"],
                         "premise: the step ran")
        for row in data["assets"]:
            self.assertNotIn("favorite", row, "the shared favourite "
                             "survived - my star still toggles yours")
            self.assertNotIn("icon", row, "the record icon survived, so "
                             "there are two answers free to drift")

    def test_everything_else_on_the_row_is_untouched(self):
        """A migration must COMPARE, never assume: this is user data."""
        self._write(self._v4_document())
        _db, data = self._load()
        self.assertEqual(["A0", "A1"], [r["id"] for r in data["assets"]])
        self.assertEqual(["one", "two"], [r["name"] for r in data["assets"]])


    def test_a_junk_row_does_not_stop_the_step(self):
        document = self._v4_document()
        document["assets"].append(42)
        self._write(document)
        _db, data = self._load()
        self.assertNotIn("favorite", data["assets"][0],
                         "one junk row cost the rest of the migration")


class NoUpgradeStepsFromBeforeTheFirstReleaseTest(_Case):
    """An older document is refused, asserted through a connector, never the registry."""

    def _pre_release_document(self):
        """Version 1 is the implicit legacy schema, written before any release."""
        return {"version": 1, "categories": ["_All"], "tags": [],
                "assets": [{"id": "ASSET0", "name": "mat 0"}]}

    def test_a_pre_release_document_keeps_its_own_version(self):
        self._write(self._pre_release_document())
        db, data = self._load()
        self.assertEqual(
            1, data["version"],
            "a document was carried forward by a step this build no "
            "longer ships, so something is still upgrading from a "
            "shape that predates the first release")
        self.assertTrue(
            db._migration_incomplete,
            "the chain stopped short and did not record it, so save() "
            "has nothing to consult and will stamp the document as "
            "current")

    def test_it_is_not_stamped_as_current_by_an_ordinary_save(self):
        """A wrong stamp is permanent: a document marked current never migrates."""
        self._write(self._pre_release_document())
        db, data = self._load()
        db.set({"assets": data["assets"], "categories": data["categories"],
                "tags": data["tags"]})
        db.save()
        on_disk = self._on_disk()
        self.assertEqual(
            1, on_disk["version"],
            "an ordinary save stamped the current schema over a document "
            "that no step ever touched")
        self.assertIn(
            "ASSET0", [a["id"] for a in on_disk["assets"]],
            "holding the stamp back also held the records back - only "
            "the version claim is refused, never the user's edit")

    def test_a_current_document_is_not_flagged(self):
        """The accept path: a flag that fires on every load proves nothing."""
        self._write(self._document(1))
        db, data = self._load()
        self.assertEqual(SCHEMA, data["version"])
        self.assertFalse(
            db._migration_incomplete,
            "a document already at the current schema was reported as "
            "an incomplete chain")


class ARepairedFileCanBeSavedAgainTest(unittest.TestCase):
    """The unreadable latch must not outlive the problem it was set for."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="amaze_relatch_")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.settings = os.path.join(self.home, "settings.json")

    def _prefs(self):
        from amaze.prefs import prefs as prefs_mod
        p = prefs_mod.Prefs()
        p.path = self.home
        return p

    def _good_settings(self):
        library = os.path.join(self.home, "library")
        os.makedirs(library, exist_ok=True)
        with open(self.settings, "w", encoding="utf-8") as handle:
            json.dump({"directory": library + os.sep,
                       "accent_color": "#ff8800"}, handle, indent=4)
        return library + os.sep

    def _truncate(self):
        with open(self.settings, "w", encoding="utf-8") as handle:
            handle.write('{"directory": "/x", ')

    def test_prefs_saves_again_once_the_file_reads(self):
        library = self._good_settings()
        self._truncate()
        prefs = self._prefs()
        with io.StringIO() as sink:
            import contextlib
            with contextlib.redirect_stdout(sink):
                prefs.load()
        self.assertTrue(
            getattr(prefs, "_load_failed", False),
            "premise: the truncated file must latch, or this test is not "
            "exercising the case it was written for")
        self._good_settings()               # the sync finishes
        prefs.load()                        # the SAME object re-reads
        self.assertFalse(
            getattr(prefs, "_load_failed", False),
            "the latch survived a clean read, so every preference save is "
            "refused for the rest of the session even though the file is "
            "fine now")
        prefs.dir = library
        prefs._accent_color = "#00ff00"
        prefs.save()
        with open(self.settings, encoding="utf-8") as handle:
            self.assertEqual("#00ff00", json.load(handle)["accent_color"],
                             "the save was still refused after the repair")

    def test_prefs_still_refuses_while_the_file_is_broken(self):
        """A second failed read latches again: the guard is re-derived."""
        self._good_settings()
        self._truncate()
        prefs = self._prefs()
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            prefs.load()
            prefs.load()                    # and again, still broken
        self.assertTrue(getattr(prefs, "_load_failed", False),
                        "a second failed read did not latch")
        before = open(self.settings, encoding="utf-8").read()
        prefs.save()
        self.assertEqual(
            before, open(self.settings, encoding="utf-8").read(),
            "defaults were written over a settings file we could not read")

    def test_gradients_save_again_once_the_file_reads(self):
        from amaze.core import gradient_library

        class _Prefs:
            """A stub, never a real `Prefs`: one under hython finds the install."""

            asset_dir = "mat/"
            img_dir = "img/"
            img_ext = ".png"
            ext = ".mat"
            thumbsize = 128
            library_user = "relatch-fixture-uid"

            def __init__(self, directory):
                self.dir = directory.rstrip(os.sep) + os.sep

            def load(self):
                # The switch path re-reads settings; a stub has none.
                return True

        library = tempfile.mkdtemp(prefix="amaze_relatch_grad_")
        self.addCleanup(shutil.rmtree, library, ignore_errors=True)
        path = os.path.join(library, "gradients.json")
        # A marker so no seeding runs and the test stays about the latch.
        with open(os.path.join(
                library, gradient_library.GradientLibrary._SEED_MARKER),
                "w", encoding="utf-8") as handle:
            handle.write("seeded\n")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"gradients": [')            # truncated
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            lib = gradient_library.GradientLibrary(
                preferences=_Prefs(library))
        self.assertTrue(lib._load_failed,
                        "premise: the truncated file must latch")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": SCHEMA, "categories": ["Warm"],
                       "assets": [{"name": "theirs",
                                   "id": "theirsuid"}]}, handle)
        with contextlib.redirect_stdout(io.StringIO()):
            lib.switch_model_data()
        self.assertFalse(
            lib._load_failed,
            "the latch survived a clean read - the Colors section can "
            "never be saved again this session")
        with contextlib.redirect_stdout(io.StringIO()):
            lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        with open(path, encoding="utf-8") as handle:
            names = [g["name"] for g in json.load(handle)["assets"]]
        self.assertIn("mine", names,
                      "the save was still refused after the repair")


class SettingsGetTheirOwnRestoreFloor(unittest.TestCase):
    """A restore floor, but no absence verdict: this file is per-machine."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="amaze_absent_prefs_")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.settings = os.path.join(self.home, "settings.json")

    def _prefs(self):
        from amaze.prefs import prefs as prefs_mod
        p = prefs_mod.Prefs()
        p.path = self.home
        return p

    def _configured(self):
        """A settings.json written the way the product writes one."""
        library = os.path.join(self.home, "library")
        os.makedirs(library, exist_ok=True)
        p = self._prefs()
        p.load()
        p.dir = library + os.sep
        p.save()
        return library + os.sep

    def test_a_first_launch_still_opens_and_saves(self):
        """The accept path: a machine that has never run Amaze opens and saves."""
        prefs = self._prefs()
        prefs.load()
        self.assertFalse(getattr(prefs, "_load_failed", False),
                         "a first launch was refused its first save")
        prefs.save()
        self.assertTrue(os.path.exists(self.settings),
                        "the first save never landed")

    def test_a_first_save_leaves_evidence_it_was_here(self):
        self._configured()
        self.assertTrue(
            os.path.exists(self.settings + ".bak-first"),
            "settings written once leave no trace at all, so nothing "
            "can tell a late file from a new machine")

    def test_the_floor_survives_a_later_write(self):
        """Write-once: a later save must not roll the floor forward."""
        self._configured()
        floor = self.settings + ".bak-first"
        first = open(floor, encoding="utf-8").read()
        prefs = self._prefs()
        prefs.load()
        prefs._accent_color = "#00ff00"
        prefs.save()
        self.assertEqual(first, open(floor, encoding="utf-8").read(),
                         "the write-once floor was replaced")

    def test_deleting_the_settings_still_starts_fresh(self):
        """Removing the file is how a machine starts over, and the save lands."""
        self._configured()
        os.remove(self.settings)
        prefs = self._prefs()
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            prefs.load()
        self.assertFalse(
            getattr(prefs, "_load_failed", False),
            "starting fresh was refused because a restore copy sat "
            "beside the file the user deleted")
        prefs.save()
        self.assertTrue(os.path.isfile(self.settings),
                        "the fresh start never reached disk")


class MergeRefusesJsonOfTheWrongShapeTest(_Case):
    """Valid JSON is not a valid database, and takes the same refusal path."""

    SHAPES = (
        ("a bare list", []),
        ("null", None),
        ("a number", 7),
        ("a string", "library"),
        ("assets is null", {"categories": ["_All"], "tags": [],
                            "assets": None}),
        ("assets is an object", {"categories": ["_All"], "tags": [],
                                 "assets": {"a": 1}}),
        ("categories is a string", {"categories": "Wood", "tags": [],
                                    "assets": []}),
        ("tags is a number", {"categories": ["_All"], "tags": 3,
                              "assets": []}),
    )

    def _loaded_connector(self):
        """A real stale-write baseline: the merge only runs on a changed file."""
        self._write(self._document(2))
        db, _ = self._load()
        self.assertIsNotNone(db._disk_stat, "premise: the guard is armed")
        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET1"}],
                "categories": ["_All"], "tags": []})
        return db

    def _replace_behind_it(self, payload):
        """What another session leaves on disk, written raw so null is null."""
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_no_exception_escapes_a_save_over_any_of_them(self):
        for label, payload in self.SHAPES:
            with self.subTest(shape=label):
                self.setUp()                # a private dir per shape
                db = self._loaded_connector()
                self._replace_behind_it(payload)
                try:
                    db.save()
                except Exception as exc:                    # noqa: BLE001
                    self.fail("save() raised on %s: %s: %s"
                              % (label, type(exc).__name__, exc))

    def test_the_session_is_latched_for_every_one_of_them(self):
        """Not raising is half the fix; the same refusal path is the other."""
        for label, payload in self.SHAPES:
            with self.subTest(shape=label):
                self.setUp()
                db = self._loaded_connector()
                self._replace_behind_it(payload)
                db.save()
                self.assertTrue(
                    db._write_blocked,
                    "writes were not blocked after %s - the next save "
                    "puts our copy over a file we could not read" % label)

    def test_the_peer_document_is_left_untouched_and_preserved(self):
        db = self._loaded_connector()
        self._replace_behind_it([])
        with open(self.path, "rb") as handle:
            before = handle.read()
        db.save()
        db.save()               # the SECOND save is the historic killer
        with open(self.path, "rb") as handle:
            self.assertEqual(before, handle.read(),
                             "our copy was written over the peer document")
        self.assertTrue(
            os.path.exists(self.path + ".unreadable"),
            "no copy was preserved beside it, so the evidence is gone as "
            "soon as anything does write")

    def test_a_normal_peer_document_still_merges(self):
        """The accept path: a shape check too strict stops every merge there is."""
        db = self._loaded_connector()
        peer = self._document(2)
        peer["assets"].append({"id": "THEIRS1", "name": "theirs"})
        peer["categories"].append("Metal")
        peer["tags"].append("shiny")
        self._replace_behind_it(peer)
        db.save()
        self.assertFalse(db._write_blocked,
                         "an ordinary peer document was refused")
        on_disk = self._on_disk()
        self.assertIn("THEIRS1", [a["id"] for a in on_disk["assets"]],
                      "their row was not adopted")
        self.assertIn("Metal", on_disk["categories"])
        self.assertIn("shiny", on_disk["tags"])

    def test_the_load_refuses_the_same_shapes_in_a_class_callers_catch(self):
        """The front door raises the class its callers catch, like a truncated file."""
        for label, payload in self.SHAPES:
            with self.subTest(shape=label):
                self.setUp()
                self._replace_behind_it(payload)
                db = self._connector()
                with self.assertRaises(ValueError, msg=(
                        "load() did not refuse %s as a ValueError, so no "
                        "caller can catch it" % label)):
                    db.load(self.dir + os.sep)
                self.assertFalse(
                    db._data,
                    "%s was committed to memory, and the next save writes "
                    "it back over the file" % label)

    def test_the_load_still_accepts_an_ordinary_document(self):
        """The accept path: too strict at the front door stops the panel opening."""
        self._write(self._document(3))
        db, data = self._load()
        self.assertEqual(3, len(data["assets"]),
                         "an ordinary database was refused by the load")
        self.assertFalse(db._write_blocked)

    def test_one_bad_row_does_not_cost_the_session_its_writes(self):
        """A junk row is skipped, not escalated into a session-wide refusal."""
        db = self._loaded_connector()
        peer = self._document(2)
        peer["assets"].append("not a row at all")
        peer["assets"].append({"id": "THEIRS1"})
        self._replace_behind_it(peer)
        db.save()
        self.assertFalse(
            db._write_blocked,
            "a single unreadable row latched the whole session")
        self.assertIn("THEIRS1", [a["id"] for a in self._on_disk()["assets"]],
                      "the good row beside the bad one was lost")


class PrefsKeepsKeysItDoesNotKnowTest(unittest.TestCase):
    """A save must not delete the settings this build has never heard of."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="amaze_prefs_keys_")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.settings = os.path.join(self.home, "settings.json")

    def _prefs(self):
        from amaze.prefs import prefs as prefs_mod
        p = prefs_mod.Prefs()
        p.path = self.home
        return p

    def _seed(self, **extra):
        library = os.path.join(self.home, "library")
        os.makedirs(library, exist_ok=True)
        document = {"directory": library + os.sep, "thumbsize": 128}
        document.update(extra)
        with open(self.settings, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)
        return library + os.sep

    def _saved(self):
        with open(self.settings, encoding="utf-8") as handle:
            return json.load(handle)

    def test_an_unknown_key_survives_a_save(self):
        self._seed(gradient_favorites=["wada:132", "klee:7"])
        prefs = self._prefs()
        prefs.load()
        prefs.save()
        self.assertEqual(
            ["wada:132", "klee:7"], self._saved().get("gradient_favorites"),
            "a key this build does not name was deleted by an ordinary "
            "save - on a second machine that is the newer build's "
            "settings, silently reverted")

    def test_a_falsy_unknown_value_survives_too(self):
        """A truthiness-based carry-through drops ordinary setting values."""
        self._seed(future_flag=False, future_count=0, future_name="",
                   future_list=[])
        prefs = self._prefs()
        prefs.load()
        prefs.save()
        saved = self._saved()
        for key, value in (("future_flag", False), ("future_count", 0),
                           ("future_name", ""), ("future_list", [])):
            with self.subTest(key=key):
                self.assertIn(key, saved, "the key was dropped entirely")
                self.assertEqual(value, saved[key],
                                 "the value was rewritten")

    def test_a_known_key_is_still_the_build_s_own_value(self):
        """The carried-through document must not win over what the build holds."""
        self._seed(thumbsize=128, gradient_favorites=["wada:1"])
        prefs = self._prefs()
        prefs.load()
        self.assertEqual(128, prefs.thumbsize, "premise: the stored value")
        prefs.thumbsize = 64
        prefs.save()
        saved = self._saved()
        self.assertEqual(64, saved["thumbsize"],
                         "the stale document overwrote the live edit")
        self.assertEqual(["wada:1"], saved["gradient_favorites"],
                         "and the unknown key was lost anyway")

    def test_a_reload_does_not_accumulate_a_previous_library_s_keys(self):
        """Replaced per read, or a switch writes another machine's settings here."""
        self._seed(gradient_favorites=["wada:1"])
        prefs = self._prefs()
        prefs.load()
        other = tempfile.mkdtemp(prefix="amaze_prefs_keys_b_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        with open(os.path.join(other, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"thumbsize": 32}, handle)
        prefs.path = other
        prefs.load()
        prefs.save()
        with open(os.path.join(other, "settings.json"),
                  encoding="utf-8") as handle:
            self.assertNotIn(
                "gradient_favorites", json.load(handle),
                "the previous settings file's unknown keys followed the "
                "user into a different one")


class TheSchemaStampMustNotLieTest(_Case):
    """A version stamp is a promise to every other machine, and permanent."""

    def setUp(self):
        super().setUp()
        self._real_version = database.SCHEMA_VERSION
        self._real_migrations = dict(database._MIGRATIONS)
        self.addCleanup(self._restore)

    def _restore(self):
        database.SCHEMA_VERSION = self._real_version
        database._MIGRATIONS.clear()
        database._MIGRATIONS.update(self._real_migrations)

    def _target_with_a_gap(self):
        """A build whose `SCHEMA_VERSION` is 3 but which ships no step 2."""
        database.SCHEMA_VERSION = 3
        database._MIGRATIONS.pop(2, None)

    def test_a_save_does_not_stamp_a_migration_that_did_not_run(self):
        self._write(self._document(2, version=2))   # version 2 on disk
        self._target_with_a_gap()
        db, data = self._load()
        # The premise in memory, not on disk: `load` does not write either way.
        self.assertEqual(
            2, data["version"],
            "premise: _migrate must stop at 2 - if it has stopped "
            "refusing, this test is not exercising the case")
        self.assertTrue(
            db._migration_incomplete,
            "premise: the incomplete chain must be recorded, or save() has "
            "nothing to consult")
        db.set({"assets": data["assets"], "categories": data["categories"],
                "tags": data["tags"]})
        db.save()
        self.assertEqual(
            2, self._on_disk()["version"],
            "an ordinary save stamped 3 over a document that is still at "
            "2 - no build will ever migrate it again")

    def test_the_records_are_still_written(self):
        """Holding the stamp back must not hold the save back."""
        self._write(self._document(2, version=2))
        self._target_with_a_gap()
        db, _ = self._load()
        db.set({"assets": [{"id": "EDITED1"}], "categories": ["_All"],
                "tags": []})
        db.save()
        on_disk = self._on_disk()
        self.assertIn("EDITED1", [a["id"] for a in on_disk["assets"]],
                      "the edit was dropped along with the stamp")
        self.assertEqual(2, on_disk["version"])

    def test_a_complete_chain_still_stamps_the_new_version(self):
        """The accept path, or the migration re-runs on every launch forever."""
        self._write(self._document(2, version=2))
        database.SCHEMA_VERSION = 3
        database._MIGRATIONS[2] = lambda data: data.setdefault("moods", [])
        db, data = self._load()
        self.assertEqual(3, data["version"],
                         "premise: a complete chain migrates on load")
        self.assertFalse(db._migration_incomplete,
                         "premise: a complete chain is not incomplete")
        db.set({"assets": data["assets"], "categories": data["categories"],
                "tags": data["tags"]})
        db.save()
        self.assertEqual(
            3, self._on_disk()["version"],
            "a completed migration was not stamped, so it re-runs forever")
        self.assertIn("moods", self._on_disk(),
                      "the step's own change did not survive the save")

    def test_a_newer_build_s_file_is_still_not_downgraded(self):
        """The other direction: a newer document keeps its own number."""
        document = self._document(2)
        document["version"] = 99
        self._write(document)
        db, data = self._load()
        db.set({"assets": data["assets"], "categories": data["categories"],
                "tags": data["tags"]})
        db.save()
        self.assertEqual(99, self._on_disk()["version"],
                         "a newer build's file was stamped down to ours")

    def test_a_newer_peer_version_survives_the_merge_path(self):
        """The merge runs when another session wrote, which may be a newer build."""
        self._write(self._document(2))
        db, _ = self._load()
        peer = self._document(2)
        peer["version"] = 99
        peer["assets"].append({"id": "THEIRS1"})
        self._write(peer)
        db.set({"assets": [{"id": "ASSET0"}], "categories": ["_All"],
                "tags": []})
        db.save()
        self.assertFalse(db._write_blocked, "premise: the merge succeeded")
        self.assertEqual(
            99, self._on_disk()["version"],
            "our version was stamped over a newer build's file during a "
            "merge - that machine now re-runs its whole chain over data "
            "it has already migrated")

    def test_a_peer_version_is_not_carried_past_a_gap_in_our_chain(self):
        """Stamping low costs a re-run; stamping high loses which rows migrated."""
        self._write(self._document(2, version=2))
        self._target_with_a_gap()
        db, data = self._load()
        self.assertTrue(db._migration_incomplete, "premise: our chain has a "
                        "gap, so save() stamps _loaded_version")
        self.assertEqual(2, data["version"], "premise: we stopped at 2")
        peer = self._document(2, version=2)
        peer["version"] = 3
        for row in peer["assets"]:
            row["moods"] = []                # what step 2 would have added
        self._write(peer)
        db.set({"assets": data["assets"], "categories": data["categories"],
                "tags": data["tags"]})
        db.save()
        self.assertFalse(db._write_blocked, "premise: the merge succeeded, "
                         "or the stamp was never reached")
        on_disk = self._on_disk()
        self.assertEqual(
            2, on_disk["version"],
            "the peer's version 3 was stamped over our own rows, which the "
            "missing step never touched - the file now claims a shape two "
            "of its rows do not have, and no build will migrate them again")
        self.assertTrue(
            [row for row in on_disk["assets"] if "moods" not in row],
            "premise: at least one row must still be at the old shape, or "
            "the stamp would not be a lie")

    def test_a_peer_version_is_still_carried_through_a_whole_chain(self):
        """With no gap, a peer's newer version survives the merge."""
        self._write(self._document(2))
        db, data = self._load()
        self.assertFalse(db._migration_incomplete,
                         "premise: our chain is whole")
        peer = self._document(2)
        peer["version"] = 99
        self._write(peer)
        db.set({"assets": data["assets"], "categories": data["categories"],
                "tags": data["tags"]})
        db.save()
        self.assertEqual(
            99, self._on_disk()["version"],
            "the guard fires even with a complete chain, so every merge "
            "now downgrades a newer machine's file")

    def test_the_flag_does_not_follow_the_user_to_another_library(self):
        """A latch belongs to the file, not the session."""
        self._write(self._document(2, version=2))
        self._target_with_a_gap()
        db, _ = self._load()
        self.assertTrue(db._migration_incomplete, "premise: A has a gap")
        database._MIGRATIONS[2] = lambda data: None      # B's build is whole
        other = tempfile.mkdtemp(prefix="amaze_dbhard_b_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self._write(self._document(1, version=2),
                    path=os.path.join(other, self.FILENAME))
        data = db.reload_with_path(other + os.sep)
        self.assertFalse(db._migration_incomplete,
                         "the gap followed the connector into a library it "
                         "was never about")
        db.set({"assets": data["assets"], "categories": data["categories"],
                "tags": data["tags"]})
        db.save()
        with open(os.path.join(other, self.FILENAME),
                  encoding="utf-8-sig") as handle:
            self.assertEqual(3, json.load(handle)["version"],
                             "library B was left unstamped because library "
                             "A had an incomplete chain")


class TheRescueSlotIsNotSpentOnNothingTest(unittest.TestCase):
    """One `.unreadable` copy per file, forever, and never spent on no bytes."""

    def setUp(self):
        from amaze.helpers import hostos
        self.hostos = hostos
        self.dir = tempfile.mkdtemp(prefix="amaze_rescue_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        self.keep = self.path + ".unreadable"

    def _write(self, text, path=None):
        with open(path or self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_a_zero_byte_source_preserves_nothing(self):
        self._write("")
        self.assertEqual(0, os.path.getsize(self.path), "premise: 0 bytes")
        result = self.hostos.preserve_unreadable(self.path, why="test")
        self.assertEqual(
            "", result,
            "a 0-byte placeholder was reported as preserved, so the caller "
            "tells the user to go and look at a copy of nothing")
        self.assertFalse(
            os.path.exists(self.keep),
            "the one rescue copy was spent on an empty placeholder")

    def test_the_slot_is_still_free_for_the_real_thing(self):
        """The placeholder arrives first; the truncated file is worth keeping."""
        self._write("")
        self.hostos.preserve_unreadable(self.path, why="placeholder")
        self._write('{"gradients": [{"name": "real"')      # truncated
        result = self.hostos.preserve_unreadable(self.path, why="truncated")
        self.assertEqual(self.keep, result,
                         "the genuinely damaged file was not preserved")
        with open(self.keep, encoding="utf-8") as handle:
            self.assertEqual('{"gradients": [{"name": "real"', handle.read(),
                             "the preserved copy is not the damaged file")

    def test_an_empty_existing_copy_is_replaced(self):
        """A copy holding no bytes is not the evidence write-once protects."""
        self._write("", path=self.keep)
        self._write('{"gradients": [{"name": "real"')
        result = self.hostos.preserve_unreadable(self.path, why="truncated")
        self.assertEqual(self.keep, result)
        self.assertGreater(
            os.path.getsize(self.keep), 0,
            "an empty .unreadable kept the slot shut, so nothing can ever "
            "be preserved for this file again")

    def test_a_real_existing_copy_is_never_replaced(self):
        """Write-once: the first copy is the one that holds the original."""
        self._write("the first, genuine failure", path=self.keep)
        self._write("a later, already-defaulted rewrite")
        result = self.hostos.preserve_unreadable(self.path, why="second")
        self.assertEqual(self.keep, result,
                         "an existing copy must still be reported, so the "
                         "caller can name it")
        with open(self.keep, encoding="utf-8") as handle:
            self.assertEqual(
                "the first, genuine failure", handle.read(),
                "the second failure overwrote the good evidence")

    def test_an_absent_source_preserves_nothing(self):
        self.assertEqual("", self.hostos.preserve_unreadable(self.path))
        self.assertFalse(os.path.exists(self.keep))

    def test_an_ordinary_damaged_file_is_still_preserved(self):
        """The accept path: the guard must not have become never-preserve."""
        self._write('{"gradients": [')
        self.assertEqual(self.keep,
                         self.hostos.preserve_unreadable(self.path))
        self.assertTrue(os.path.isfile(self.keep))


class TheRefusalOnlyClaimsACopyThatExistsTest(_Case):
    """A refusal may only promise a copy that was actually made."""

    def _watch_notes(self):
        from amaze.core import debug
        from unittest.mock import patch
        notes = []
        real = debug.note

        def spy(message, /, **data):
            notes.append(message)
            return real(message, **data)

        patcher = patch.object(debug, "note", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        return notes

    def _refused_save(self, peer_bytes):
        self._write(self._document(2))
        db, _ = self._load()
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(peer_bytes)
        db.set({"assets": [{"id": "ASSET0"}], "categories": ["_All"],
                "tags": []})
        notes = self._watch_notes()
        db.save()
        self.assertTrue(db._write_blocked, "premise: the save must refuse")
        return [n for n in notes if "could not read the other session" in n]

    def test_it_names_the_copy_when_there_is_one(self):
        said = self._refused_save('{"assets": [')       # truncated, non-empty
        self.assertTrue(said, "the refusal said nothing")
        self.assertTrue(
            os.path.isfile(self.path + ".unreadable"),
            "premise: a truncated file must actually be preserved")
        self.assertIn(
            "cops.json.unreadable", said[0],
            "the refusal does not name the copy, so the user cannot find "
            "the only surviving version of the other session's work")

    def test_it_claims_no_copy_when_there_is_none(self):
        """Nothing preserved, nothing promised; the refusal still happens."""
        said = self._refused_save("")
        self.assertTrue(said, "the refusal stopped happening")
        self.assertFalse(
            os.path.exists(self.path + ".unreadable"),
            "premise: a 0-byte file must not be preserved")
        self.assertNotIn(
            ".unreadable", said[0],
            "the refusal promised a copy that was never made - the user "
            "goes looking for a file that is not there")

    def test_the_policy_write_only_claims_a_copy_that_exists_too(self):
        """The same sentence in a second place: one policy, two voices."""
        from amaze.core import library_policy

        notes = self._watch_notes()
        path = library_policy.path_for(self.dir)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("")                     # 0 bytes: nothing to keep
        library_policy.set_allow_overwrite(self.dir, True)
        said = [n for n in notes if "could not be read" in n]
        self.assertTrue(said, "the unreadable policy file was not reported")
        self.assertFalse(
            os.path.exists(path + ".unreadable"),
            "premise: a 0-byte file must not be preserved")
        self.assertNotIn(".unreadable", said[0],
                         "the policy note promised a copy that was never "
                         "made")

    def test_the_policy_write_does_name_a_copy_it_did_make(self):
        """When there is a copy the note names it, or it is unfindable."""
        from amaze.core import library_policy

        notes = self._watch_notes()
        path = library_policy.path_for(self.dir)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"allow_overwrite": tr')          # truncated
        library_policy.set_allow_overwrite(self.dir, True)
        said = [n for n in notes if "could not be read" in n]
        self.assertTrue(said, "the unreadable policy file was not reported")
        self.assertIn("policy.json.unreadable", said[0],
                      "the note does not name the copy that was kept")


class ASnapshotSlotIsNotSpentOnGarbageTest(unittest.TestCase):
    """The permanent floor is written once, so it is never minted from garbage."""

    def setUp(self):
        from amaze.helpers import hostos
        self.hostos = hostos
        self.dir = tempfile.mkdtemp(prefix="amaze_snapshot_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        # The once-per-path marker is module-level and outlives one test.
        hostos._session_snapshots.pop(self.path, None)
        self.addCleanup(hostos._session_snapshots.pop, self.path, None)

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _good(self, count=3):
        # Today's shape: a fixture in a shape we no longer ship is not one.
        self._write(json.dumps(
            {"version": SCHEMA,
             "categories": ["Warm"],
             "assets": [{"id": "SNAP%d" % i, "name": "g%d" % i}
                        for i in range(count)]}))

    def _tiers(self):
        return sorted(n for n in os.listdir(self.dir) if ".bak-" in n)

    def test_a_truncated_file_creates_no_tier_at_all(self):
        self._write('{"gradients": [{"name": "g0"')
        self.hostos.snapshot_before_write(self.path)
        self.assertEqual(
            [], self._tiers(),
            "the one permanent restore point was minted from bytes that "
            "do not parse - restore.py will refuse to put it back, so it "
            "is a floor made of nothing")

    def test_a_read_that_fails_outright_does_not_burn_the_slot_either(self):
        """A failed read is the transient branch, so it may not burn the slot."""
        if self.hostos.is_windows() or os.geteuid() == 0:
            self.skipTest("an unreadable file needs POSIX bits and a "
                          "non-root reader")
        self._good(12)
        os.chmod(self.path, 0o000)
        self.addCleanup(os.chmod, self.path, 0o644)
        self.hostos.snapshot_before_write(self.path)
        os.chmod(self.path, 0o644)
        self.assertEqual([], self._tiers(),
                         "premise: the read must have failed")
        self.assertNotIn(
            self.path, self.hostos._session_snapshots,
            "the failed read kept the once-per-session marker, so the "
            "healthy save a second later takes no copy at all")
        self.hostos.snapshot_before_write(self.path)
        self.assertTrue(
            os.path.exists(self.path + ".bak-first"),
            "a transient read failure cost the file its whole session's "
            "restore point")

    def test_a_later_good_save_still_gets_its_own_first_tier(self):
        """The marker has to be released, or the one chance is already spent."""
        self._write('{"gradients": [{"name": "g0"')
        self.hostos.snapshot_before_write(self.path)
        self._good(40)
        self.hostos.snapshot_before_write(self.path)
        first = self.path + ".bak-first"
        self.assertTrue(
            os.path.exists(first),
            "the failed snapshot burned the once-per-session marker, so "
            "the file spent its whole session with no restore point")
        with open(first, encoding="utf-8") as handle:
            self.assertEqual(40, len(json.load(handle)["assets"]),
                             "the permanent copy is not the healthy file")

    def test_a_good_file_is_still_snapshotted(self):
        """The accept path: a parse check too strict switches backups off."""
        self._good(5)
        self.hostos.snapshot_before_write(self.path)
        self.assertTrue(os.path.exists(self.path + ".bak-first"),
                        "no snapshot was taken of a perfectly good file")
        self.assertTrue(os.path.exists(self.path + ".bak-1"))

    def test_a_bom_prefixed_file_is_still_snapshotted(self):
        """A document the reader accepts must not read as garbage here."""
        with open(self.path, "w", encoding="utf-8-sig") as handle:
            json.dump({"assets": [{"name": "g0"}]}, handle)
        self.hostos.snapshot_before_write(self.path)
        self.assertTrue(
            os.path.exists(self.path + ".bak-first"),
            "a byte-order mark was treated as corruption")

    def test_a_good_rotation_is_not_disturbed(self):
        """The ring still rolls, and an identical rewrite consumes no slot."""
        self._good(3)
        self.hostos.snapshot_before_write(self.path)
        self.hostos._session_snapshots.pop(self.path, None)
        self._good(4)
        self.hostos.snapshot_before_write(self.path)
        self.hostos._session_snapshots.pop(self.path, None)
        with open(self.path + ".bak-2", encoding="utf-8") as handle:
            self.assertEqual(3, len(json.load(handle)["assets"]),
                             "the older state did not rotate down")
        with open(self.path + ".bak-1", encoding="utf-8") as handle:
            self.assertEqual(4, len(json.load(handle)["assets"]))
        self.hostos.snapshot_before_write(self.path)
        with open(self.path + ".bak-2", encoding="utf-8") as handle:
            self.assertEqual(
                3, len(json.load(handle)["assets"]),
                "an identical rewrite consumed a rotation slot")

    def test_a_corrupt_file_does_not_rotate_a_good_tier_out(self):
        """Rotating garbage in pushes the oldest good state off the end."""
        self._good(40)
        self.hostos.snapshot_before_write(self.path)
        self.hostos._session_snapshots.pop(self.path, None)
        self._write("{ not json at all")
        self.hostos.snapshot_before_write(self.path)
        with open(self.path + ".bak-1", encoding="utf-8") as handle:
            self.assertEqual(
                40, len(json.load(handle)["assets"]),
                "garbage was rotated into the newest slot, pushing the "
                "good states one step closer to falling off the end")


class ARefusalLeavesTheDocumentWhole(unittest.TestCase):
    """A refused write leaves the shared document whole, not only the model."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        from amaze.core import library as library_mod
        self.library_mod = library_mod

    def _own_path(self):
        return os.path.join(self.prefs.dir, "library.json")

    def test_a_declined_delete_is_not_committed_by_another_model(self):
        from unittest.mock import patch
        from amaze.core import category as category_mod
        from amaze.core import database

        model = self.library_mod.MaterialLibrary(preferences=self.prefs)
        # A real id: the fixture's damaged row answers -1 and never appears.
        row = next(i for i, a in enumerate(model.assets)
                   if str(a.mat_id) not in ("", "-1"))
        asset = model.assets[row]
        doomed = str(asset.mat_id)
        with patch.object(database.DatabaseConnector, "save",
                          return_value=False):
            model.remove_asset(model.index(row, 0))
        self.assertEqual(doomed, str(model.assets[row].mat_id),
                         "premise: the refusal restored the model row")

        cats = category_mod.Categories(preferences=self.prefs)
        cats.save()
        with open(self._own_path(), encoding="utf-8") as handle:
            ids = [str(row.get("id"))
                   for row in json.load(handle)["assets"]]
        self.assertIn(
            doomed, ids,
            "the declined delete reached disk through a save that "
            "writes only categories - the document still carried it")

    def test_a_refused_category_save_reports_False(self):
        from unittest.mock import patch
        from amaze.core import category as category_mod
        from amaze.core import database

        cats = category_mod.Categories(preferences=self.prefs)
        with patch.object(database.DatabaseConnector, "save",
                          return_value=False):
            self.assertFalse(
                cats.save(),
                "a refused write reported success while the in-memory "
                "list had already moved")

    def test_the_edit_info_star_never_touches_the_shared_record(self):
        from amaze.core import keyed_store, locations
        keyed_store.release()
        self.addCleanup(keyed_store.release)
        model = self.library_mod.MaterialLibrary(preferences=self.prefs)
        row = next(i for i, a in enumerate(model.assets)
                   if str(a.mat_id) not in ("", "-1"))
        asset = model.assets[row]
        frozen = asset.fav
        model.set_assetdata(model.index(row, 0), asset.name,
                            ", ".join(asset.categories),
                            ", ".join(asset.tags), True)
        self.assertEqual(
            frozen, asset.fav,
            "the Edit Info checkbox wrote the frozen shared field - it "
            "wins the field merge and seeds favourite adoption on "
            "machines that have not migrated")
        self.assertTrue(
            locations.is_favourite(self.prefs, asset.mat_id),
            "the star never reached the library's favourites store")


class ANoOpSaveCostsOneRead(unittest.TestCase):
    """A save that changes nothing pays one read, not three and a scan."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        from amaze.core import library as library_mod
        self.library_mod = library_mod

    def test_an_identical_skip_reads_once_and_scans_no_stamps(self):
        from unittest.mock import patch
        from amaze.core import database

        model = self.library_mod.MaterialLibrary(preferences=self.prefs)
        self.assertTrue(model.save())          # baseline write or skip

        calls = []
        real_stat = database.DatabaseConnector._stat_file

        def counting(connector):
            calls.append(1)
            return real_stat(connector)

        with patch.object(database.DatabaseConnector, "_stat_file",
                          counting), \
                patch.object(self.library_mod._StampWriter,
                             "refresh") as refresh:
            self.assertTrue(model.save())      # nothing changed
        refresh.assert_not_called()
        self.assertLessEqual(
            len(calls), 1,
            "a no-op save read and hashed the document %d times"
            % len(calls))


class QuarantineCrossesVolumes(unittest.TestCase):
    """`os.replace` cannot cross a volume, so the fallback copies then unlinks."""

    def test_a_cross_device_move_still_lands(self):
        from unittest.mock import patch
        from amaze.core import quarantine

        # `fixture_prefs` first: it redirects the config root into the temp tree.
        test_support.fixture_prefs(self)
        library = tempfile.mkdtemp(prefix="amaze_qxdev_")
        self.addCleanup(shutil.rmtree, library, ignore_errors=True)
        stray = os.path.join(library, "leftover.tmp")
        with open(stray, "w", encoding="utf-8") as handle:
            handle.write("scratch")

        with patch("amaze.core.quarantine.os.replace",
                   side_effect=OSError(18, "Invalid cross-device link")):
            target = quarantine.quarantine_file(library, stray)
        self.assertTrue(
            target and os.path.isfile(target),
            "the cross-device quarantine silently did nothing - the "
            "sweep reports the file as still present forever")
        self.assertFalse(os.path.exists(stray),
                         "the source survived the move")


class _CleanupCase(unittest.TestCase):
    """A fixture library copy plus the Clean Library call site."""

    def setUp(self):
        from unittest.mock import MagicMock, patch
        import hou
        self._hou = hou
        self._patch = patch
        self._MagicMock = MagicMock
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        from amaze.core import library as library_mod
        self.library_mod = library_mod
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        self.img_dir = os.path.join(self.prefs.dir, self.prefs.img_dir)

    def _model(self):
        return self.library_mod.MaterialLibrary(preferences=self.prefs)

    def _cleanup(self, model):
        # `create=True`: `hou.ui` may not exist under hython at all.
        with self._patch.object(self._hou, "ui", self._MagicMock(),
                                create=True):
            model.cleanup_db(show_dialog=False)

    def _own_path(self):
        return os.path.join(self.prefs.dir, "library.json")

    def _read_own(self):
        with open(self._own_path(), encoding="utf-8-sig") as handle:
            return json.load(handle)

    def _write_own(self, document):
        with open(self._own_path(), "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

    def _files_for(self, asset_id):
        """Both halves present, so only pass 3's judgement is under test."""
        paths = [os.path.join(self.mat_dir, asset_id + ".mat"),
                 os.path.join(self.mat_dir, asset_id + ".interface")]
        for path in paths:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("owned by " + asset_id + "\n")
        return paths

    def _drop_rows_with_no_files(self):
        """Keep only rows with files, or pass 2 saves and the merge masks this."""
        document = self._read_own()
        keep = [row for row in document["assets"]
                if os.path.exists(os.path.join(
                    self.mat_dir, str(row.get("id")) + ".mat"))]
        self.assertTrue(keep, "premise: the fixture must have intact rows")
        document["assets"] = keep
        self._write_own(document)

    def _ids_known_at_the_decision(self, model):
        """The in-memory ids at the moment the orphan pass actually asks."""
        seen = {}
        real = model._all_known_asset_ids

        def spy():
            seen["memory"] = {str(a.mat_id) for a in model.assets}
            return real()

        model._all_known_asset_ids = spy
        return seen


class CleanupReadsItsOwnDatabaseFromDiskTest(_CleanupCase):
    """In-memory means as at our load, so the sweep re-reads its own index."""

    NEWCOMER = "OTHERSESSION1"

    def test_a_row_another_session_added_protects_its_files(self):
        self._drop_rows_with_no_files()
        model = self._model()
        owned = self._files_for(self.NEWCOMER)
        document = self._read_own()
        document["assets"].append({
            "id": self.NEWCOMER, "name": "theirs", "categories": ["Wood"],
            "tags": [], "favorite": False, "renderer": "Karma",
        })
        self._write_own(document)
        known = self._ids_known_at_the_decision(model)
        self._cleanup(model)
        # The premise at the moment of the decision, not before the call.
        self.assertIn("memory", known,
                      "premise: the orphan pass never ran at all")
        self.assertNotIn(
            self.NEWCOMER, known["memory"],
            "premise: the model must still NOT know the row when the "
            "orphan pass decides - if it does, this test is measuring the "
            "adoption path instead of the disk read")
        for path in owned:
            self.assertTrue(
                os.path.exists(path),
                "Clean Library deleted %s - a file belonging to a material "
                "another session had already written to the index"
                % os.path.basename(path))

    def test_a_genuine_orphan_is_still_swept(self):
        """The accept path: reading the own file must not make the pass a no-op."""
        model = self._model()
        genuine = os.path.join(self.mat_dir, "GENUINEORPHAN1.mat")
        with open(genuine, "w", encoding="utf-8") as handle:
            handle.write("in no index at all\n")
        self._cleanup(model)
        self.assertFalse(
            os.path.exists(genuine),
            "the orphan pass did not run - a file in no index survived")

    def test_a_row_this_session_added_is_still_protected(self):
        """The union keeps both sides: a new row may not have reached disk."""
        model = self._model()
        owned = self._files_for("INMEMORY1")
        document = self._read_own()
        model._assets.append(self.library_mod.material.Material.from_dict({
            "id": "INMEMORY1", "name": "mine", "categories": ["Wood"],
            "tags": [], "favorite": False, "renderer": "Karma",
        }))
        self._write_own(document)
        self._cleanup(model)
        for path in owned:
            self.assertTrue(
                os.path.exists(path),
                "a file belonging to a material held only in memory was "
                "deleted - that is the material the user just saved")

    def test_a_malformed_own_database_does_not_kill_the_sweep(self):
        """A wrong-shaped own index must not kill the sweep mid-run."""
        for payload in ([], None, {"assets": None}):
            with self.subTest(payload=payload):
                self.setUp()
                model = self._model()
                owned = self._files_for("SHAPED1")
                with open(self._own_path(), "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                try:
                    self._cleanup(model)
                except Exception as exc:                    # noqa: BLE001
                    self.fail("cleanup_db raised on %r: %s: %s"
                              % (payload, type(exc).__name__, exc))
                for path in owned:
                    self.assertTrue(
                        os.path.exists(path),
                        "files were swept while the index could not be "
                        "read at all")
                summary = " ".join(model.last_cleanup_summary)
                self.assertIn("Amaze could not check", summary,
                              "nothing was said about the sweep that did "
                              "not run")


class AnEmptySectionWithFilesLeftBehindStopsTheSweepTest(_CleanupCase):
    """Listing nothing is not owning nothing; the unaccounted files separate them."""

    COP_ID = "COPOWNED1"

    def setUp(self):
        super().setUp()
        self.cops = os.path.join(self.prefs.dir, "cops.json")
        self.code = os.path.join(self.prefs.dir, "code.json")
        self.owned = self._files_for(self.COP_ID)

    def _empty_cops(self):
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": []}, handle)

    def _no_backups_premise(self):
        """It must work with no copy of the emptied file anywhere."""
        self.assertEqual(
            [], [n for n in os.listdir(self.prefs.dir)
                 if n.startswith("cops.json.")],
            "premise: no copy beside cops.json, or this test is not "
            "measuring the case the trace-based guard could not see")

    def _skip_line(self, model):
        lines = [line for line in model.last_cleanup_summary
                 if line.startswith("Nothing was deleted: Amaze could not "
                                    "check")]
        return lines[0] if lines else ""

    def test_an_empty_section_with_files_left_behind_stops_the_sweep(self):
        self._empty_cops()
        self._no_backups_premise()
        model = self._model()
        self._cleanup(model)
        for path in self.owned:
            self.assertTrue(
                os.path.exists(path),
                "%s was deleted while the Nodes list held nothing and the "
                "file itself was sitting in the asset folder unaccounted "
                "for - this is the 21-file loss, through the door the "
                "trace-based guard could not close"
                % os.path.basename(path))
        self.assertTrue(
            self._skip_line(model),
            "files were spared and the user was told nothing")

    def test_the_refusal_says_how_many_files_and_where(self):
        """A count and a folder they can open, never 32-hex filenames."""
        self._empty_cops()
        model = self._model()
        self._cleanup(model)
        self.assertTrue(self._skip_line(model),
                        "premise: the sweep must have been held back")
        why = [line for line in model.last_cleanup_summary
               if line.startswith("Node (cops.json):")]
        self.assertTrue(why,
                        "the refusal names only the storage file, or says "
                        "nothing about why this section could not be "
                        "checked")
        self.assertIn("2 files", why[0],
                      "the refusal does not say how much is unaccounted "
                      "for, so its severity cannot be judged")
        self.assertIn("the mat folder", why[0],
                      "the refusal does not name the folder to look in")
        self.assertNotIn(
            "mat/ folder", why[0],
            "the folder is named with the path separator prefs stores it "
            "with, which reads as a typo in a sentence")

    def test_the_refusal_names_the_repair_tool_and_how_to_reach_it(self):
        """A refusal names the way out, including the per-machine shelf step."""
        self._empty_cops()
        model = self._model()
        self._cleanup(model)
        route = [line for line in model.last_cleanup_summary
                 if "Repair" in line]
        self.assertTrue(route, "the refusal reports the problem and stops")
        self.assertEqual(1, len(route),
                         "one next step, said once - three lines saying it "
                         "is three interruptions")
        self.assertIn("Amaze shelf", route[0],
                      "the way out does not say where the tool is")
        self.assertIn("Shelves", route[0],
                      "nothing says how to get the Amaze tab, and adding "
                      "it is a per-machine step")
        self.assertIn("quit Houdini", route[0],
                      "the way out does not mention the restart Repair "
                      "needs before it can put anything right")
        self.assertIn("before you open Amaze", route[0],
                      "nothing says Repair has to run before the panel is "
                      "opened again")

    def test_the_refusal_explains_that_both_causes_look_alike(self):
        """Teach before you warn: damaged and unused look the same."""
        self._empty_cops()
        model = self._model()
        self._cleanup(model)
        lines = [line for line in model.last_cleanup_summary
                 if line.startswith("Node:")]
        self.assertTrue(lines, "the refusal states a fact and leaves the "
                               "reader to guess what it means")
        self.assertEqual(1, len(lines), "one section, one line")
        self.assertIn("nothing was ever saved there", lines[0])
        self.assertIn("failed to load", lines[0])

    def test_two_empty_sections_get_one_explanation_between_them(self):
        """Aggregate before interrupting: one explanation, not one per section."""
        self._empty_cops()
        self._write_own({"version": 2, "categories": ["_All"], "tags": [],
                         "assets": []})
        model = self._model()
        self._cleanup(model)
        explanations = [line for line in model.last_cleanup_summary
                        if "looks the same whether" in line]
        self.assertEqual(1, len(explanations),
                         "one dialog carried the same explanation twice")
        self.assertIn("Material and Node", explanations[0],
                      "the one line does not name both sections, so a "
                      "reader cannot tell which are empty")

    def test_a_live_model_agreeing_it_is_empty_does_not_override_files(self):
        """A model cannot talk unaccounted files out of existence; only the user can."""
        from amaze.core import cop_library

        self._empty_cops()
        cops_model = cop_library.CopLibrary(preferences=self.prefs)
        self.assertEqual(
            [], list(cops_model.assets),
            "premise: the live Nodes model must genuinely hold nothing")
        connector = database.DatabaseConnector._instances.get("cops.json")
        self.assertIsNotNone(connector, "premise: the Nodes section is open")
        self.assertFalse(
            getattr(connector, "_write_blocked", False),
            "premise: its load was NOT refused - a refused load was "
            "already rejected as confirmation, and this test is about the "
            "load that succeeded and found nothing")
        model = self._model()
        self._cleanup(model)
        for path in self.owned:
            self.assertTrue(
                os.path.exists(path),
                "%s was deleted because the Nodes section's own model "
                "agreed it was empty - which is what a failed load looks "
                "like from inside the panel that failed it"
                % os.path.basename(path))

    def test_the_union_of_every_section_decides_what_is_unaccounted_for(self):
        """Orphanhood is relative to every list sharing the directory."""
        self._empty_cops()
        with open(self.code, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": [{"id": self.COP_ID}]}, handle)
        model = self._model()
        self._cleanup(model)
        self.assertFalse(
            self._skip_line(model),
            "the sweep was held back although the only files in question "
            "are accounted for by the Code list - the union was read as "
            "one list instead of all of them")
        for path in self.owned:
            self.assertTrue(
                os.path.exists(path),
                "%s belongs to a listed asset and was deleted anyway"
                % os.path.basename(path))

    def test_an_unused_section_with_nothing_left_behind_still_sweeps(self):
        """The accept path: the guard weighs the asset folder, never the images."""
        self._empty_cops()
        for path in self.owned:
            os.remove(path)
        model = self._model()
        self.assertEqual(
            [], model._files_no_section_accounts_for(
                {str(a.mat_id) for a in model.assets}),
            "premise: nothing in the asset folder may be unaccounted for, "
            "or this is the refuse path wearing the accept path's name")
        leftover = os.path.join(self.img_dir, "GONEMATERIAL1.png")
        with open(leftover, "wb") as handle:
            handle.write(b"a thumbnail whose material is gone")
        self._cleanup(model)
        self.assertFalse(
            self._skip_line(model),
            "the sweep was held back for an ordinary unused Nodes section "
            "- the guard fires always, which is an outage")
        self.assertFalse(
            os.path.exists(leftover),
            "the sweep did not actually run: a file no section lists "
            "survived a Clean Library that reported no refusal")

    def test_an_empty_code_list_does_not_hold_the_asset_folder_back(self):
        """A section storing inline text owns nothing in the asset folder."""
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": [{"id": self.COP_ID}]}, handle)
        with open(self.code, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": []}, handle)
        genuine = os.path.join(self.mat_dir, "GENUINELEFTOVER3.mat")
        with open(genuine, "w", encoding="utf-8") as handle:
            handle.write("in no list at all\n")
        model = self._model()
        self._cleanup(model)
        self.assertFalse(
            self._skip_line(model),
            "the sweep was held back by an empty Code list, which cannot "
            "own a file in the asset folder - the guard fires where it "
            "protects nothing")
        self.assertFalse(os.path.exists(genuine),
                         "the sweep reported no refusal and still did not "
                         "run")

    def test_an_empty_code_list_is_still_read_into_the_union(self):
        """The narrowing is about emptiness as evidence, not about reading."""
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": [{"id": self.COP_ID}]}, handle)
        with open(self.code, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": [{"id": "CODEASSET1"}]}, handle)
        icon = os.path.join(self.img_dir, "CODEASSET1_icon.png")
        with open(icon, "wb") as handle:
            handle.write(b"a Code tile's own icon")
        model = self._model()
        self._cleanup(model)
        self.assertTrue(os.path.exists(icon),
                        "a Code asset's icon was deleted - the Code list's "
                        "ids are not in the union any more")

    def test_the_refusal_carries_no_parse_position(self):
        """No raw exception text on screen, no errno, no parse position."""
        with open(self.cops, "w", encoding="utf-8") as handle:
            handle.write('{"assets": [{"id": "COPOWNED1"}')      # truncated
        model = self._model()
        self._cleanup(model)
        summary = " ".join(model.last_cleanup_summary)
        for jargon in ("Expecting", "line 1", "column", "char ", "Errno"):
            self.assertNotIn(jargon, summary,
                             "the refusal shows '%s', which is the parser "
                             "talking to itself" % jargon)
        self.assertIn("Node (cops.json)", summary,
                      "the unreadable entry names the bare storage file "
                      "while the others say Nodes (cops.json) - one dialog "
                      "with two names for one thing")

    def test_the_dialog_says_whether_anything_was_cleaned(self):
        """The first line may not read as finished when nothing was touched."""
        self._empty_cops()
        model = self._model()
        with self._patch.object(self._hou, "ui", self._MagicMock(),
                                create=True):
            model.cleanup_db(show_dialog=True)
            shown = str(self._hou.ui.displayMessage.call_args_list[0])
        self.assertIn("Clean Library stopped before deleting any files",
                      shown,
                      "the dialog announces a finished cleanup above a "
                      "list of reasons nothing was done")
        self.assertNotIn("Library cleanup finished", shown)

    def test_a_healthy_library_still_sweeps(self):
        """With every section listing its own assets, a leftover still goes."""
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": [{"id": self.COP_ID}]}, handle)
        genuine = os.path.join(self.mat_dir, "GENUINELEFTOVER1.mat")
        with open(genuine, "w", encoding="utf-8") as handle:
            handle.write("in no list at all\n")
        model = self._model()
        self._cleanup(model)
        self.assertFalse(
            os.path.exists(genuine),
            "the sweep did not run on a library where every list reads "
            "perfectly well")
        for path in self.owned:
            self.assertTrue(
                os.path.exists(path),
                "%s was deleted although the Nodes list that owns it reads "
                "perfectly well" % os.path.basename(path))

    def test_the_refusal_does_not_contradict_itself(self):
        """Could-not-be-checked, since could-not-be-read fights the entry."""
        self._empty_cops()
        model = self._model()
        self._cleanup(model)
        summary = " ".join(model.last_cleanup_summary)
        self.assertNotIn("could not be read", summary)
        self.assertIn("could not check", summary)

    def test_nothing_is_called_unaccounted_for_while_a_list_is_unreadable(self):
        """A half-built union may not accuse anybody in a sentence to act on."""
        self._empty_cops()
        with open(self.code, "w", encoding="utf-8") as handle:
            handle.write('{"assets": [{"id": "SOMETHING"}')      # truncated
        model = self._model()
        self._cleanup(model)
        skip = self._skip_line(model)
        self.assertTrue(skip, "the sweep must still be held back")
        self.assertIn("code.json", skip,
                      "the refusal does not name the list that would not "
                      "parse")
        self.assertNotIn(
            "in the mat folder", " ".join(model.last_cleanup_summary),
            "files were counted as unaccounted for against a union that "
            "was known to be incomplete")
        for path in self.owned:
            self.assertTrue(os.path.exists(path),
                            "%s was deleted" % os.path.basename(path))

    def test_a_byte_order_mark_on_a_sibling_does_not_abort_the_sweep(self):
        """This read decides whether deleting is safe, so it reads like the others."""
        with open(self.cops, "w", encoding="utf-8-sig") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": [{"id": self.COP_ID}]}, handle)
        with open(self.cops, "rb") as handle:
            self.assertTrue(handle.read(3) == b"\xef\xbb\xbf",
                            "premise: the sibling must really carry a BOM")
        genuine = os.path.join(self.mat_dir, "GENUINELEFTOVER2.mat")
        with open(genuine, "w", encoding="utf-8") as handle:
            handle.write("in no list at all\n")
        model = self._model()
        self._cleanup(model)
        self.assertFalse(
            self._skip_line(model),
            "a byte-order mark on the Nodes file aborted the whole sweep")
        self.assertFalse(os.path.exists(genuine),
                         "the sweep did not run for a healthy library")
        for path in self.owned:
            self.assertTrue(
                os.path.exists(path),
                "%s was deleted although the BOM'd list that owns it reads "
                "perfectly well" % os.path.basename(path))

    def test_a_folder_that_cannot_be_listed_is_not_read_as_all_clear(self):
        """Fail closed: an empty list is the answer that lets the sweep delete."""
        model = self._model()
        shutil.rmtree(self.mat_dir)
        self.assertIsNone(
            model._files_no_section_accounts_for({"WHATEVER"}),
            "a folder that could not be listed was reported as holding "
            "nothing unaccounted for")

    def test_the_guard_and_the_sweep_share_one_classifier(self):
        """A guard counting a different set than the sweep touches is a second opinion."""
        pair = (".mat", ".interface")
        self.assertEqual(
            "ABC", database.asset_id_for_file("ABC_cop.mat", pair, "_cop"))
        self.assertEqual(
            "ABC", database.asset_id_for_file("ABC.interface", pair, "_cop"))
        self.assertIsNone(
            database.asset_id_for_file("ABC.mat.writing", pair, "_cop"),
            "a scratch file is not an asset file, and the sweep does not "
            "take it - so the guard must not count it as unaccounted for")
        self.assertEqual(
            "ABC",
            database.asset_id_for_file("ABC_icon.png", (".png",), "_icon"))


class SaveReportsWhetherItReachedDiskTest(_Case):
    """The files are written before the index, so a save has to state its verdict."""

    def test_a_completed_save_says_so(self):
        """First, so the verdict cannot be satisfied by always failing."""
        self._write(self._document())
        db, _loaded = self._load()
        db.set(self._document(count=4))
        self.assertTrue(db.save(), "an ordinary save reported failure")

    def test_a_write_blocked_session_says_no(self):
        self._write(self._document())
        db, _loaded = self._load()
        db.set(self._document(count=4))
        db._write_blocked = True
        self.assertFalse(db.save(),
                         "a refused save reported success, so a caller "
                         "that already wrote content cannot tell")

    def test_an_empty_document_says_no(self):
        db = self._connector()
        db.set({})
        self.assertFalse(db.save())

    def test_a_held_file_says_no(self):
        """The held-file path: the only exit that reports through a dialog."""
        self._write(self._document())
        db, _loaded = self._load()
        db.set(self._document(count=4))

        def boom(*args, **kwargs):
            raise OSError(28, "No space left on device")

        from amaze.helpers import hostos
        original = hostos.write_json_atomic
        hostos.write_json_atomic = boom
        self.addCleanup(setattr, hostos, "write_json_atomic", original)

        self.assertFalse(db.save(),
                         "a save that could not write the file reported "
                         "success")

    def test_no_exit_from_save_returns_none(self):
        """From source: a bare return reads as a completed save at the call site."""
        import ast
        import inspect
        source = inspect.getsource(database)
        bare = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.name == "save":
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Return) and sub.value is None:
                        bare.append(sub.lineno)
        self.assertEqual([], bare,
                         "DatabaseConnector.save() has exits that return "
                         "None, which a caller cannot tell from success")


class TheWriteBlockHealsTest(_Case):
    """The recovery the message prescribes has to actually clear the latch."""

    def _latch(self):
        self._write(self._document())
        db, _ = self._load()
        db.set(self._document(count=4))
        # An unparseable file with a moved clock, so the stale-write guard fires.
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ half a document")
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))
        self.assertFalse(db.save(), "premise: the save was refused")
        self.assertTrue(getattr(db, "_write_blocked", False),
                        "premise: the latch is set")
        return db

    def test_a_repaired_file_can_be_saved_again(self):
        db = self._latch()
        # The user fixes the file - or the sync finishes arriving.
        self._write(self._document(count=5))
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 9_000_000_000))
        self.assertTrue(
            db.save(),
            "the save is still refused after the file was repaired - the "
            "latch has no way to clear, so this session can never write "
            "again")
        self.assertFalse(getattr(db, "_write_blocked", True),
                         "the latch survived a successful merge")

    def test_a_still_broken_file_stays_refused(self):
        """So healing cannot be satisfied by clearing the latch blindly."""
        db = self._latch()
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 9_000_000_000))
        self.assertFalse(db.save(),
                         "a file that still does not parse was written over")


class AFailedLibrarySwitchRollsBackTest(_Case):
    """A failed switch rolls back, or the connector discards every later save."""

    def test_switching_to_an_empty_directory_is_not_a_failure(self):
        """A missing database seeds an empty one, which is how a new library starts."""
        self._write(self._document())
        db, _ = self._load()
        empty = tempfile.mkdtemp(prefix="amaze_noswitch_")
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        db.reload_with_path(empty + os.sep)
        self.assertTrue(db.save(),
                        "a switch to a fresh directory left a connector "
                        "that cannot write")

    def test_the_previous_library_survives_a_failed_switch(self):
        """The path the rollback is for: a load that genuinely raises."""
        self._write(self._document())
        db, _ = self._load()
        before = json.loads(json.dumps(db._data))

        real_load = database.DatabaseConnector.load

        def boom(self, path):
            raise OSError(13, "Permission denied")

        database.DatabaseConnector.load = boom
        self.addCleanup(setattr, database.DatabaseConnector, "load",
                        real_load)
        with self.assertRaises(OSError):
            db.reload_with_path("/nowhere/at/all/")
        database.DatabaseConnector.load = real_load

        self.assertEqual(before, db._data,
                         "the connector lost the library it was holding")
        db.set(self._document(count=6))
        self.assertTrue(
            db.save(),
            "the connector can no longer save after a failed switch - "
            "every later save is discarded and nothing says so")
        self.assertEqual(6, len(self._on_disk()["assets"]))


class TheMergeMustNotDetachAModelsListTest(_Case):
    """The models alias the connector's lists, so rebinding detaches them."""

    def test_the_alias_survives_SET(self):
        """The alias is taken at construction while `set` runs on every save."""
        self._write(self._document())
        db, _ = self._load()
        alias_cats = db._data.setdefault("categories", [])
        alias_tags = db._data.setdefault("tags", [])
        alias_assets = db._data.setdefault("assets", [])
        alias_colours = db._data.setdefault("category_colors", {})

        db.set({"categories": ["_All", "Wood", "New"], "tags": ["rough"],
                "assets": [{"id": "X"}],
                "category_colors": {"Wood": "#ff0000"}})

        self.assertIs(alias_cats, db._data["categories"],
                      "set() swapped the categories list, so every model "
                      "holding it is now writing to an orphan")
        self.assertIs(alias_tags, db._data["tags"])
        self.assertIs(alias_assets, db._data["assets"])
        self.assertIs(alias_colours, db._data["category_colors"])
        self.assertIn("New", alias_cats,
                      "the alias survived but the new value never "
                      "reached it")
        self.assertEqual({"Wood": "#ff0000"}, alias_colours)

    def test_set_handles_being_given_its_own_containers(self):
        """Callers hand back the object they were given, so emptying first wipes it."""
        self._write(self._document())
        db, _ = self._load()
        db._data["category_colors"] = {"Wood": "#123456"}
        db.set({"category_colors": db._data["category_colors"],
                "categories": db._data["categories"]})
        self.assertEqual({"Wood": "#123456"}, db._data["category_colors"],
                         "set() erased the colours it was handed")
        self.assertIn("_All", db._data["categories"])

    def test_the_alias_survives_a_merge(self):
        self._write(self._document())
        db, _ = self._load()
        db.set(self._document(count=4))
        # After `set`, because that is what a model does with its state.
        alias = db._data["categories"]

        theirs = self._document()
        theirs["categories"] = ["_All", "Wood", "Theirs"]
        self._write(theirs)
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                               stat.st_mtime_ns + 5_000_000_000))

        self.assertTrue(db.save())

        self.assertIn("Theirs", alias,
                      "the merge rebound the list, so anything still "
                      "holding the old one never sees the adopted "
                      "category - and overwrites it on the next save")
        self.assertIs(alias, db._data["categories"],
                      "the connector is holding a different list object "
                      "than the model")

    def test_it_survives_two_further_saves(self):
        self.test_the_alias_survives_a_merge()
        db = self._connector()
        for _ in range(2):
            self.assertTrue(db.save())
        self.assertIn("Theirs", self._on_disk()["categories"],
                      "the adopted category was erased by a later save")


class OnePaneMustNotDropAnothersRowTest(_Case):
    """Two panes share one connector, so `set` unions rather than replaces."""

    def test_a_row_the_caller_never_saw_survives_its_save(self):
        self._write(self._document(count=2))
        db, _ = self._load()

        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET1"},
                           {"id": "PANE1_NEW"}],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        # Pane 2 was built earlier and has never heard of the new row.
        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET1"}],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        ids = [a["id"] for a in self._on_disk()["assets"]]
        self.assertIn("PANE1_NEW", ids,
                      "a second pane's save deleted the material the "
                      "first pane had just added, and nothing said so")

    def test_the_callers_version_of_a_row_it_holds_still_wins(self):
        """A union must not ignore the caller: their edit still has to land."""
        self._write(self._document(count=2))
        db, _ = self._load()
        db.set({"assets": [{"id": "ASSET0", "name": "renamed"}],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())
        rows = {a["id"]: a for a in self._on_disk()["assets"]}
        self.assertEqual("renamed", rows["ASSET0"].get("name"),
                         "the caller's edit was discarded by the union")

    def test_forget_is_how_a_row_actually_goes(self):
        """Absence stopped meaning delete, so delete has to be said."""
        self._write(self._document(count=3))
        db, _ = self._load()
        db.forget("ASSET1")
        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET2"}],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())
        ids = [a["id"] for a in self._on_disk()["assets"]]
        self.assertNotIn("ASSET1", ids, "forget() did not remove the row")
        self.assertIn("ASSET0", ids)
        self.assertIn("ASSET2", ids)

    def test_forget_does_not_persist_past_the_set_it_applies_to(self):
        """A forgotten id must not suppress a row somebody re-adds later."""
        self._write(self._document(count=2))
        db, _ = self._load()
        db.forget("ASSET1")
        db.set({"assets": [{"id": "ASSET0"}], "categories": ["_All"],
                "tags": []})
        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET1"}],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())
        self.assertIn("ASSET1", [a["id"] for a in self._on_disk()["assets"]],
                      "a forgotten id stayed forgotten, so re-adding it "
                      "silently did nothing")


class AMovedConnectorMustNotBeWrittenThroughTest(_Case):
    """A switch in one pane repoints the shared connector under all of them."""

    FILENAME = "library.json"

    def test_it_reports_whether_it_still_serves_a_directory(self):
        self._write(self._document())
        db, _ = self._load()
        self.assertTrue(db.serves(self.dir + os.sep))

        other = tempfile.mkdtemp(prefix="amaze_otherlib_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.assertFalse(
            db.serves(other + os.sep),
            "the connector claims to serve a library it was never "
            "pointed at")

    def test_a_switch_moves_it_away_from_the_first_library(self):
        self._write(self._document())
        db, _ = self._load()
        other = tempfile.mkdtemp(prefix="amaze_otherlib_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        with open(os.path.join(other, self.FILENAME), "w",
                  encoding="utf-8") as handle:
            json.dump(self._document(count=1), handle)

        db.reload_with_path(other + os.sep)
        self.assertTrue(db.serves(other + os.sep))
        self.assertFalse(
            db.serves(self.dir + os.sep),
            "after a switch the connector still claims the OLD library - "
            "a pane holding that library's rows would write them into "
            "the new one")

    def test_a_trailing_separator_is_not_a_different_library(self):
        """The comparison is on canonical paths, or every save refuses."""
        self._write(self._document())
        db, _ = self._load()
        self.assertTrue(db.serves(self.dir))
        self.assertTrue(db.serves(self.dir + os.sep))


class ContentFingerprintGuardTest(_Case):
    """A stat guard misses a same-size edit and invents an identical-rewrite conflict."""

    def _arm(self):
        self._write(self._document())
        db, _ = self._load()
        db.set(self._document(count=4))
        return db

    def test_a_same_size_edit_is_seen(self):
        """The blind spot: flip one byte, restore the mtime, keep the size."""
        db = self._arm()
        with open(self.path, encoding="utf-8") as handle:
            raw = handle.read()
        stat_before = os.stat(self.path)
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(raw.replace("ASSET2", "ASSEX2", 1))
        os.utime(self.path, ns=(stat_before.st_atime_ns,
                                stat_before.st_mtime_ns))

        self.assertTrue(db.save(), "the save itself should complete")
        ids = [a["id"] for a in self._on_disk()["assets"]]
        self.assertIn("ASSEX2", ids,
                      "the same-size edit was invisible - the peer's "
                      "change was overwritten without a merge")

    def test_a_byte_identical_rewrite_is_not_a_conflict(self):
        """A peer's no-op rewrite must not send an ordinary save down the merge."""
        db = self._arm()
        with open(self.path, "rb") as handle:
            raw = handle.read()
        with open(self.path, "wb") as handle:
            handle.write(raw)               # same bytes, new mtime
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))
        with test_support.captured_log() as log:
            self.assertTrue(db.save())
        self.assertEqual([], log.matching("merged concurrent changes",
                                          "database"),
                         "a byte-identical rewrite was treated as a "
                         "conflict and merged for nothing")

    def test_two_noop_saves_leave_the_file_untouched(self):
        """Sync hygiene: a save that changes nothing is a no-op on disk too."""
        db = self._arm()
        self.assertTrue(db.save())
        stat_first = os.stat(self.path)
        self.assertTrue(db.save())
        self.assertTrue(db.save())
        stat_after = os.stat(self.path)
        self.assertEqual(
            (stat_first.st_mtime_ns, stat_first.st_ino),
            (stat_after.st_mtime_ns, stat_after.st_ino),
            "a no-op save rewrote the file - every one costs a snapshot "
            "rotation and a sync upload for nothing")

    def test_a_reloaded_model_writes_the_fixture_byte_identically(self):
        """Through a real model, because a key reorder is invisible to the others."""
        from amaze.core import library as library_mod
        from amaze.tests import test_support as ts
        prefs_obj = ts.fixture_prefs(self)
        ts.reset_database_singletons()
        self.addCleanup(ts.reset_database_singletons)
        model = library_mod.MaterialLibrary(preferences=prefs_obj)
        source = os.path.join(prefs_obj.dir, "library.json")
        with open(source, "rb") as handle:
            before = handle.read()
        self.assertTrue(model.save())
        with open(source, "rb") as handle:
            after = handle.read()
        if before != after:
            self.assertTrue(model.save())
            with open(source, "rb") as handle:
                third = handle.read()
            self.assertEqual(after, third,
                             "two saves of identical state produced "
                             "different bytes - serialisation is not "
                             "deterministic and the no-op skip never "
                             "fires")


class CreditGoesToTheRowWithTheIdTest(_Case):
    """A save can adopt a peer's row, so the last row is not ours by position."""

    FILENAME = "library.json"

    def test_an_adopted_row_lands_after_ours(self):
        """The premise: adoption appends, so position is not identity."""
        self._write(self._document(count=2))
        db, _ = self._load()

        theirs = self._document(count=2)
        theirs["assets"].append({"id": "FOREIGN", "name": "theirs"})
        self._write(theirs)
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))

        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET1"},
                           {"id": "OURS_NEW"}],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())
        ids = [a["id"] for a in db._data["assets"]]
        self.assertIn("FOREIGN", ids)
        self.assertNotEqual("OURS_NEW", ids[-1],
                            "adoption did not append after ours - the "
                            "premise this guard exists for has changed; "
                            "re-check matx_import")

    def test_the_call_site_uses_the_id(self):
        """From source: the call site resolves by id and may not slide back."""
        import inspect
        from amaze.core import matx_import
        source = inspect.getsource(matx_import.import_record)
        self.assertIn("find_asset_row_by_id", source,
                      "matx_import no longer resolves the credited row "
                      "by id")
        self.assertNotIn("assets[-1]", source,
                         "matx_import credits by position again - an "
                         "adopted row takes someone else's credit")


class PackageDirectoriesCarryIdentityTest(unittest.TestCase):
    """Two sources offering one title must not extract into one directory."""

    class _R:
        def __init__(self, source, uid, title):
            self.source, self.uid, self.title = source, uid, title

    def test_colliding_titles_get_distinct_directories(self):
        from amaze.core import matx_import
        records = [self._R("polyhaven", "brick_01", "Red Brick"),
                   self._R("gpuopen", "0451", "Red Brick"),
                   self._R("polyhaven", "brick_02", "Red Brick")]
        names = [matx_import.package_dirname(r) for r in records]
        self.assertEqual(len(names), len(set(names)),
                         "two different records extract into one "
                         "directory: %s" % names)

    def test_the_same_record_maps_to_the_same_directory(self):
        """Identity must be stable, or a re-download never finds what it fetched."""
        from amaze.core import matx_import
        a = matx_import.package_dirname(self._R("polyhaven", "x", "Moss"))
        b = matx_import.package_dirname(self._R("polyhaven", "x", "Moss"))
        self.assertEqual(a, b)

    def test_the_title_still_leads_the_name(self):
        """The directory a user browses still starts with the words they know."""
        from amaze.core import matx_import
        name = matx_import.package_dirname(
            self._R("polyhaven", "u1", "Old Oak"))
        self.assertTrue(name.startswith("Old_Oak") or
                        name.startswith("OldOak") or
                        name.startswith("Old Oak"),
                        name)


class ASuspiciousShrinkIsSaidOutLoudTest(_Case):
    """Report-only: a shrink can be deliberate, but a human sees both numbers."""

    def setUp(self):
        super().setUp()
        database.DatabaseConnector._integrity_notes.clear()
        self.addCleanup(database.DatabaseConnector._integrity_notes.clear)

    def test_a_halved_list_leaves_a_retrievable_note(self):
        with open(self.path + ".bak-1", "w", encoding="utf-8") as fh:
            json.dump(self._document(count=40), fh)
        self._write(self._document(count=1))
        with open(self.path, "rb") as fh:
            before = fh.read()

        self._load()
        notes = database.DatabaseConnector.take_integrity_notes()
        self.assertEqual(1, len(notes), notes)
        self.assertIn("1", notes[0])
        self.assertIn("40", notes[0])
        self.assertIn("Repair", notes[0],
                      "the note does not name the way out")
        with open(self.path, "rb") as fh:
            self.assertEqual(before, fh.read(),
                             "a report-only check modified the file")

    def test_taking_the_notes_clears_them(self):
        self.test_a_halved_list_leaves_a_retrievable_note()
        self.assertEqual([], database.DatabaseConnector
                         .take_integrity_notes(),
                         "the same finding would be reported forever")

    def test_an_ordinary_ratio_says_nothing(self):
        with open(self.path + ".bak-1", "w", encoding="utf-8") as fh:
            json.dump(self._document(count=5), fh)
        self._write(self._document(count=4))
        self._load()
        self.assertEqual([], database.DatabaseConnector
                         .take_integrity_notes(),
                         "an unremarkable difference fired the alarm - "
                         "it will be ignored the day it matters")


class EverySaveLeavesExactlyOneRecordTest(_Case):
    """A wrapper logs in `finally`, so every exit leaves exactly one record."""

    def _save_records(self, log):
        return [r for r in log.records("database")
                if r.get("msg") == "save"]

    def _drive(self, prepare, expected_outcome):
        self._write(self._document())
        db, _ = self._load()
        db.set(self._document(count=4))
        prepare(db)
        with test_support.captured_log() as log:
            db.save()
        records = self._save_records(log)
        self.assertEqual(1, len(records),
                         "%d records for one save() call (outcome %s)"
                         % (len(records), expected_outcome))
        self.assertEqual(expected_outcome,
                         records[0]["data"].get("outcome"))
        return records[0]

    def test_stored(self):
        self._drive(lambda db: None, "stored")

    def test_write_blocked(self):
        self._drive(lambda db: setattr(db, "_write_blocked", True),
                    "write-blocked")

    def test_identical_skip(self):
        self._write(self._document())
        db, _ = self._load()
        db.set(self._document(count=4))
        self.assertTrue(db.save())
        with test_support.captured_log() as log:
            db.save()                                  # nothing changed
        records = self._save_records(log)
        self.assertEqual(1, len(records))
        self.assertEqual("identical-skip",
                         records[0]["data"].get("outcome"))

    def test_a_raise_still_leaves_its_record(self):
        self._write(self._document())
        db, _ = self._load()
        db.set(self._document(count=4))
        real = hostos.write_json_atomic

        def boom(*a, **k):
            raise RuntimeError("not an OSError - escapes the handler")

        hostos.write_json_atomic = boom
        self.addCleanup(setattr, hostos, "write_json_atomic", real)
        with test_support.captured_log() as log:
            with self.assertRaises(RuntimeError):
                db.save()
        records = self._save_records(log)
        self.assertEqual(1, len(records),
                         "the raising path left no record - the one "
                         "moment telemetry matters most")
        self.assertEqual("unrecorded", records[0]["data"].get("outcome"))

    def test_no_record_carries_the_library_path(self):
        record = self._drive(lambda db: None, "stored")
        flat = json.dumps(record)
        self.assertNotIn(self.dir, flat,
                         "the save record carries the library path raw - "
                         "the exported log is personal-data territory")
        self.assertIn("dir_key", record["data"])


class DifferentFieldsOfOneAssetBothSurviveTest(_Case):
    """The field is the unit of editing, so it is the unit of comparison."""

    def _their_edit(self, **fields):
        theirs = self._document()
        theirs["assets"][0].update(fields)
        self._write(theirs)
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))

    def test_their_description_survives_my_rename(self):
        self._write(self._document())
        db, _ = self._load()
        mine = self._document()
        mine["assets"][0]["name"] = "renamed-by-me"
        db.set(mine)

        self._their_edit(description="written on the other machine")
        self.assertTrue(db.save())

        rows = {str(a["id"]): a for a in self._on_disk()["assets"]}
        row = rows["ASSET0"]
        self.assertEqual("renamed-by-me", row.get("name"),
                         "my own edit was lost")
        self.assertEqual("written on the other machine",
                         row.get("description"),
                         "their edit to a DIFFERENT field was erased by "
                         "whole-record ours-wins")

    def test_the_same_field_keeps_mine_and_records_the_collision(self):
        self._write(self._document())
        db, _ = self._load()
        mine = self._document()
        mine["assets"][0]["name"] = "my-name"
        db.set(mine)
        self._their_edit(name="their-name")

        with test_support.captured_log() as log:
            self.assertTrue(db.save())
        rows = {str(a["id"]): a for a in self._on_disk()["assets"]}
        self.assertEqual("my-name", rows["ASSET0"].get("name"),
                         "the active editor lost its own field")
        self.assertTrue(
            log.matching("field collision", "database"),
            "a same-field collision was silent - the loser's value is "
            "findable in the peer's snapshots only if someone knows to "
            "look")


class ADatabaseWrittenOnceHasAFloor(_Case):
    """A list written exactly once still gets a floor saying it existed."""

    def test_a_seeded_database_gets_a_floor(self):
        self._load()                        # absent, untraced -> seeded
        self.assertTrue(os.path.exists(self.path), "premise: it seeded")
        self.assertTrue(
            os.path.exists(self.path + ".bak-first"),
            "a list written once has no trace, so the next time it is "
            "missing for an instant it reads as a new library again")

    def test_the_floor_makes_absence_answerable(self):
        """Asked through the guard that reads it, not through the filename."""
        self._load()
        os.remove(self.path)
        self.assertTrue(
            database.absent_but_known(self.dir + os.sep, self.FILENAME),
            "the list is gone and nothing says it was ever here, so the "
            "next load seeds an empty one over it")

    def test_the_floor_is_not_rolled_forward(self):
        """Write-once: a restore falls back to the first-seen state."""
        self._load()
        floor = self.path + ".bak-first"
        first = open(floor, encoding="utf-8").read()
        db = self._connector()
        db.set({"assets": [{"id": "LATER", "name": "added after"}]})
        self.assertTrue(db.save())
        self.assertEqual(first, open(floor, encoding="utf-8").read(),
                         "the write-once floor moved with a later save")


class ASnapshotOfTheWrongShapeDoesNotCostTheLoad(_Case):
    """A note that escapes `load` takes the panel down during construction."""

    def _snapshot(self, document):
        with open(self.path + ".bak-1", "w", encoding="utf-8",
                  newline="\n") as handle:
            json.dump(document, handle, indent=4)

    def test_a_list_shaped_snapshot_is_ignored(self):
        self._write(self._document(count=3))
        self._snapshot([])
        db, data = self._load()
        self.assertEqual(3, len(data["assets"]),
                         "the load did not survive a snapshot of the "
                         "wrong shape")

    def test_a_null_snapshot_is_ignored(self):
        self._write(self._document(count=3))
        self._snapshot(None)
        db, data = self._load()
        self.assertEqual(3, len(data["assets"]))

    def test_a_real_shrink_is_still_reported(self):
        """Ignoring an unreadable snapshot must not silence the readable ones."""
        self._write(self._document(count=1))
        self._snapshot(self._document(count=8))
        self._load()
        notes = database.DatabaseConnector.take_integrity_notes()
        self.assertTrue(
            any("most recent saved copy" in line for line in notes),
            "a genuine shrink went unreported: %r" % (notes,))


class TheMembershipBaselineFollowsEverySave(_Case):
    """The baseline tells our deletion from their addition, so every save moves it."""

    def _peer_edits(self):
        """Any real peer change: the guard compares content, so timing is free."""
        theirs = self._on_disk()
        theirs["assets"][0]["name"] = "renamed by the other machine"
        self._write(theirs)
        return theirs

    def test_a_row_saved_this_session_can_still_be_deleted(self):
        self._write(self._document(count=1))
        db, _ = self._load()

        db.set({"assets": [{"id": "ASSET0", "name": "mat 0"},
                           {"id": "MINE", "name": "made this session"}]})
        self.assertTrue(db.save(), "premise: the first save landed")
        self.assertIn("MINE", [str(r["id"]) for r in self._on_disk()["assets"]],
                      "premise: the row reached disk")

        self._peer_edits()

        # Said out loud: absence alone is not a delete.
        db.forget("MINE")
        db.set({"assets": [{"id": "ASSET0", "name": "mat 0"}]})
        self.assertTrue(db.save(), "premise: the second save landed")

        self.assertNotIn(
            "MINE", [str(r["id"]) for r in self._on_disk()["assets"]],
            "the merge read our own deletion as the peer's addition and "
            "put the row back - and remove_asset reads that True as "
            "permission to unlink every file behind it")

    def test_a_row_the_peer_added_after_our_save_is_still_adopted(self):
        """Widening the baseline is only correct while a new peer row still lands."""
        self._write(self._document(count=1))
        db, _ = self._load()

        db.set({"assets": [{"id": "ASSET0", "name": "mat 0"},
                           {"id": "MINE", "name": "made this session"}]})
        self.assertTrue(db.save(), "premise: the first save landed")

        theirs = self._on_disk()
        theirs["assets"].append({"id": "THEIRS", "name": "from theirs"})
        self._write(theirs)

        db.set({"assets": [{"id": "ASSET0", "name": "mat 0"},
                           {"id": "MINE", "name": "made this session"}]})
        self.assertTrue(db.save(), "premise: the second save landed")

        ids = [str(r["id"]) for r in self._on_disk()["assets"]]
        self.assertIn("THEIRS", ids,
                      "the peer's new row was not adopted - the baseline "
                      "swallowed an addition it should never see")
        self.assertIn("MINE", ids, "our own row was dropped by the merge")
        self.assertIn(
            "THEIRS", [str(r["id"]) for r in db.take_adopted()],
            "the row reached disk but was never handed to the model, so "
            "the next save rebuilds assets[] without it")

    def test_a_row_the_peer_deleted_stays_deleted(self):
        """The third direction: in our memory AND the baseline but gone from disk means the peer deleted it - and its files are already unlinked, so writing it back mints a fileless ghost on both machines."""
        self._write(self._document(count=2))
        db, _ = self._load()

        theirs = self._on_disk()
        theirs["assets"] = [r for r in theirs["assets"]
                            if str(r["id"]) != "ASSET1"]
        self._write(theirs)

        db.set({"assets": [{"id": "ASSET0", "name": "mat 0 edited"},
                           {"id": "ASSET1", "name": "mat 1"}]})
        self.assertTrue(db.save(), "premise: the save landed")

        ids = [str(r["id"]) for r in self._on_disk()["assets"]]
        self.assertNotIn(
            "ASSET1", ids,
            "the peer's deletion was undone - the row went back into "
            "library.json with its payload files already unlinked")
        self.assertIn(
            "ASSET1", [str(r["id"]) for r in db.take_dropped()],
            "the deletion never reached the model, so the next save "
            "writes the row straight back")

    def test_an_identical_skip_also_moves_the_baseline(self):
        """A save whose bytes match disk agrees with the file just as much."""
        self._write(self._document(count=1))
        db, _ = self._load()

        db.set({"assets": [{"id": "ASSET0", "name": "mat 0"},
                           {"id": "MINE", "name": "made this session"}]})
        self.assertTrue(db.save(), "premise: the first save landed")
        self.assertTrue(db.save(), "premise: the second save changed nothing")
        self.assertEqual("identical-skip", db._save_outcome,
                         "premise: this is the derived-stat exit")

        self.assertIn("MINE", db._loaded_ids,
                      "the no-op save left the baseline behind, so the "
                      "row is still outside it for every later merge")


if __name__ == "__main__":
    unittest.main(verbosity=2)
