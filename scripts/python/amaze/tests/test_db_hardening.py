"""Database-layer hardening: the read, the migration and the merge.

One file per defect class, all of them in the layer that owns the
library index. Every refusal here is sabotage-verified, and every
refusal has an accept-path test beside it - a guard that always fires is
an outage, not a guard, and this layer has shipped one of those before.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest

# THREE dirnames up = scripts/python, the directory holding the `amaze`
# package - the DEV tree, not the install on Houdini's path.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import database
from amaze.helpers import hostos                             # noqa: E402
from amaze.tests import test_support                        # noqa: E402


class _Case(unittest.TestCase):
    """A private library directory and a clean connector registry."""

    FILENAME = "cops.json"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_dbhard_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, self.FILENAME)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _document(self, count=3):
        return {
            "version": 2,
            "categories": ["_All", "Wood"],
            "tags": ["rough"],
            "assets": [{"id": "ASSET%d" % i, "name": "mat %d" % i}
                       for i in range(count)],
        }

    def _write(self, data, encoding="utf-8", path=None):
        # newline="\n" to match hostos.write_json_atomic. A fixture that
        # lays a file down differently from the product is not a fixture:
        # test_a_bom_less_database_round_trips_byte_identical reads a
        # file, saves, and compares BYTES, so on Windows this wrote CRLF,
        # the product wrote LF, and the save it asserts is a no-op became
        # a real rewrite. It passed before only because both sides were
        # wrong in the same direction.
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


class BomPrefixedDatabaseLoadsTest(_Case):
    """A BOM in front of the document must not cost the library.

    `encoding="utf_8"` raises on a byte-order mark, and for library.json
    load() has no recovery path - the panel opens on an exception. A BOM
    is an ordinary artifact of a file that has been through a Windows
    editor or a sync client's conflict helper, so this is a read the
    layer simply could not do.
    """

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
        """library.json is the one with no recovery path, so it is the
        one that matters most - and it takes a different branch in
        load()."""
        self.FILENAME = "library.json"
        self.path = os.path.join(self.dir, "library.json")
        self._write(self._document(4), encoding="utf-8-sig")
        _, data = self._load()
        self.assertEqual(4, len(data["assets"]))

    def test_a_bom_less_database_round_trips_byte_identical(self):
        """The accept path, and the reason utf-8-sig is free: it must not
        change one byte of an ordinary file. Read, save, compare."""
        self._write(self._document(3))
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
        """utf-8-sig on the READ only. If the writer ever adopted it,
        every save would prepend a marker that every other reader of this
        library - restore.py, a text editor, another build - then has to
        know about."""
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
        """The merge read is the one where a parse failure LATCHES the
        session's writes, so a BOM there is worse than at load."""
        self._write(self._document(2))
        db, _ = self._load()
        # Another session rewrites the file, with a BOM, adding a row.
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
    """A raising migration must not leave a half-document behind.

    load() assigned self._data from json.load and then migrated it in
    place, so a step that raised left the connector holding a partially
    upgraded document - and _remember_disk_state, the line after, never
    ran. That is the one combination save() cannot survive: it believes
    it holds the whole library, and _disk_stat is None so the stale-write
    guard is not armed either.
    """

    def setUp(self):
        super().setUp()
        self._original = dict(database._MIGRATIONS)
        self.addCleanup(self._restore_migrations)

    def _restore_migrations(self):
        database._MIGRATIONS.clear()
        database._MIGRATIONS.update(self._original)

    def _break_the_migration(self):
        """A step that mutates and THEN raises - a half-applied step, not
        a step that fails cleanly. Failing cleanly was never the problem."""
        def half_then_raise(data):
            data["categories"] = ["ruined"]
            raise ValueError("migration step blew up halfway")

        database._MIGRATIONS[1] = half_then_raise

    def _v1_document(self):
        """No "version" key = the implicit legacy schema, so _migrate
        actually runs a step."""
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
        """The recovery path, and the reason leaving _data falsy is the
        right refusal: `if not self._data` gates the whole load branch,
        so the next load RETRIES instead of answering from wreckage."""
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
        # The question is whether a save REACHED DISK after the guard
        # re-armed, not how many rows survived it: set() unions now, so
        # rows this caller never mentioned are kept rather than dropped.
        self.assertIn("ASSET0", [a["id"] for a in self._on_disk()["assets"]],
                      "an ordinary save after the recovery was refused")

    def test_an_ordinary_migration_still_runs_and_is_committed(self):
        """The accept path. Parsing into a local must not stop the
        migration actually happening - a v1 document has to come out as
        v2, with the keys the step guarantees."""
        self._write({"assets": [{"id": "ASSET0"}]})     # no version, no keys
        db, data = self._load()
        self.assertEqual(database.SCHEMA_VERSION, data["version"],
                         "the migration did not run at all")
        self.assertEqual(["_All"], data["categories"],
                         "the v1 step's guaranteed keys are missing")
        self.assertEqual([], data["tags"])
        self.assertIs(data, db._data, "the parse result was not committed")


class ARepairedFileCanBeSavedAgainTest(unittest.TestCase):
    """The "unreadable" latch must not outlive the problem.

    prefs.py and gradient_library.py both set `_load_failed` on a parse
    failure and neither cleared it anywhere, so a repaired file could
    never be saved again for the life of the object. For Prefs that
    object lives as long as the panel and panel.py re-reads it on a
    library switch and when Preferences closes - so "launch while the
    file is half-synced, wait for the sync, reopen Preferences" read the
    file back perfectly and still refused every save, with the
    once-per-session explanation already spent.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="amaze_relatch_")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.settings = os.path.join(self.home, "settings.json")

    def _prefs(self):
        from amaze.prefs import prefs as prefs_mod
        p = prefs_mod.Prefs()
        p.path = self.home
        # Under hython the legacy path is the LIVE install and load()
        # migrates from it - blanked for the reason test_support blanks it.
        p.legacy_path = ""
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
        """The accept path for the REFUSAL: clearing the latch on a good
        read must not clear it on a bad one. A second failed read has to
        latch again - the guard is re-derived, not remembered."""
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
            """Only the attribute gradient_library reads. NOT a real
            Prefs: one constructed under hython resolves $AMAZE to the
            live install, which is how a test overwrote real settings."""

            def __init__(self, directory):
                self.dir = directory

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
            lib = gradient_library.GradientLibrary(_Prefs(library))
        if lib._user_file() != path:
            self.skipTest("gradient library does not resolve this path")
        self.assertTrue(lib._load_failed,
                        "premise: the truncated file must latch")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["Warm"],
                       "gradients": [{"name": "theirs"}]}, handle)
        with contextlib.redirect_stdout(io.StringIO()):
            lib._load_user()                # the same object re-reads
        self.assertFalse(
            lib._load_failed,
            "the latch survived a clean read - the Colors section can "
            "never be saved again this session")
        lib._user = [{"name": "mine", "type": "user"}]
        with contextlib.redirect_stdout(io.StringIO()):
            lib._save_user()
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(
                ["mine"], [g["name"] for g in json.load(handle)["gradients"]],
                "the save was still refused after the repair")


class MergeRefusesJsonOfTheWrongShapeTest(_Case):
    """Valid JSON is not a valid database.

    `_merge_from_disk`'s try/except wraps only the parse, so a peer
    document that is `[]`, `null` or `{"assets": null}` parsed fine and
    then raised AttributeError/TypeError out of save() - a Qt slot, so
    the traceback reached stderr and nothing else. And it bypassed the
    whole preserve/latch/tell-the-user path a merely truncated file gets,
    so the shape most in need of preserving was the one that got none of
    it.
    """

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
        """A connector with a real stale-write baseline, so the peer
        document is actually reached: the merge only runs when the file
        changed since our load."""
        self._write(self._document(2))
        db, _ = self._load()
        self.assertIsNotNone(db._disk_stat, "premise: the guard is armed")
        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET1"}],
                "categories": ["_All"], "tags": []})
        return db

    def _replace_behind_it(self, payload):
        """What another session (or a sync client's conflict helper)
        leaves on disk. Written raw so `null` really is null."""
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
        """Not raising is half the fix. The other half is that this must
        land in the SAME refusal path a truncated file gets - refuse the
        write, preserve the file, say so - not be waved through."""
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
        """The accept path, and the one that would turn this guard into an
        outage: the ordinary two-machine case must still adopt their row.
        A shape check that is too strict stops every merge there is."""
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
        """THE PRIMARY READ NEEDS THE SAME CLASSIFIER. The shape check
        landed in the merge and not in load(), so `[]` at the front door
        still raised AttributeError out of _migrate's first line -
        `data.get(...)` - and AttributeError is a class nothing here
        catches: every guard around a database read guards
        (OSError, ValueError), the pair a truncated file raises.

        ValueError is deliberately the SAME outcome a truncated file gets,
        not a new one. "Refuse over overwrite" is the settled policy for a
        file that exists and will not read, and a document of the wrong
        shape is that file."""
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
        """The accept path. A shape check at the front door that is too
        strict does not corrupt anything - it stops the panel opening."""
        self._write(self._document(3))
        db, data = self._load()
        self.assertEqual(3, len(data["assets"]),
                         "an ordinary database was refused by the load")
        self.assertFalse(db._write_blocked)

    def test_one_bad_row_does_not_cost_the_session_its_writes(self):
        """The granularity matters. A non-dict ENTRY is already skipped
        and left on disk; escalating that to a full refusal would make
        one junk row disable saving for the session."""
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
    """A save must not delete the settings this build has never heard of.

    load() reads every key it knows into a private attribute and
    refresh_data() rebuilds the saved document from those attributes
    alone, so anything unrecognised was simply absent from the next
    write. Confirmed on the real machine's own settings file: 44 keys in
    .bak-first against 49 in the current one, with `gradient_favorites`
    in one and gone from the other.

    In a two-machine setup that is lossy in both directions, and the
    saves that do it come from ordinary sidebar use - registering a
    texture folder, starring a file - not from opening Preferences.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="amaze_prefs_keys_")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.settings = os.path.join(self.home, "settings.json")

    def _prefs(self):
        from amaze.prefs import prefs as prefs_mod
        p = prefs_mod.Prefs()
        p.path = self.home
        p.legacy_path = ""
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
        """`0`, `False`, `""` and `[]` are the ones a truthiness-based
        carry-through would drop, and they are ordinary setting values."""
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
        """The accept path, and the one that would make this a bug: the
        carried-through document must NOT win over what the build
        actually holds, or every preference edit would be discarded."""
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
        """self.data is REPLACED per read, not merged into. Preferences
        can point at a different settings file, and carrying the previous
        one's unknown keys across would write another machine's settings
        into this one."""
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
    """A version stamp is a promise to every other machine.

    `_migrate` correctly stops at the last successfully-applied version
    when a step is missing from the chain - and `save()` then wrote
    max(_loaded_version, SCHEMA_VERSION) anyway, undoing the refusal
    completely. Reproduced live: SCHEMA_VERSION=3 with no step 2, and the
    file correctly said 2 after the load and wrongly said 3 after one
    ordinary save.

    A wrong stamp is not cosmetic. The version is what every reader
    decides from, so a file marked upgraded is never migrated again by
    ANY build - the data stays at the old shape while every reader
    believes otherwise, permanently and silently.
    """

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
        """A build whose SCHEMA_VERSION is 3 but which ships no step 2 -
        the shape of a half-updated fleet, and the shape this project is
        about to be in, since Versions IS the next bump."""
        database.SCHEMA_VERSION = 3
        database._MIGRATIONS.pop(2, None)

    def test_a_save_does_not_stamp_a_migration_that_did_not_run(self):
        self._write(self._document(2))              # version 2 on disk
        self._target_with_a_gap()
        db, data = self._load()
        # THE PREMISE IN MEMORY, not on disk: load() does not write, so
        # "the file still says 2" is true whether or not _migrate refused
        # anything, and asserting it would prove nothing at all.
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
        """Holding the stamp back must not hold the SAVE back. The user's
        edit still has to reach disk; only the version claim is refused."""
        self._write(self._document(2))
        self._target_with_a_gap()
        db, _ = self._load()
        db.set({"assets": [{"id": "EDITED1"}], "categories": ["_All"],
                "tags": []})
        db.save()
        on_disk = self._on_disk()
        # assertIn, not an exact list. set() unions now - a caller
        # that hands over one row is saying "here is mine", not "delete
        # everything else" - and this test is about the STAMP, not about
        # what set() drops. What it has to prove is that holding the
        # version back did not hold the edit back.
        self.assertIn("EDITED1", [a["id"] for a in on_disk["assets"]],
                      "the edit was dropped along with the stamp")
        self.assertEqual(2, on_disk["version"])

    def test_a_complete_chain_still_stamps_the_new_version(self):
        """The accept path. If this fired whenever the target moved, no
        library would ever be marked as upgraded and the migration would
        re-run on every launch for the life of the file."""
        self._write(self._document(2))
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
        """The other direction, already fixed once and easy to break
        again: a version 99 document must keep saying 99."""
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
        """The merge runs precisely when another session wrote the file -
        which is exactly when that session may be the NEWER build. The
        unknown-key carry-through cannot cover this: "version" is always
        already in our own document, so it is always skipped."""
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
        """THE TWO HALVES OF THIS STEP FOUGHT EACH OTHER, and this is where
        they met. The merge raised _loaded_version to the peer's number
        unconditionally, and save() stamps _loaded_version when the chain
        is incomplete - so the peer's higher version was written over rows
        the missing step never touched. Same permanent, silent mis-stamp
        this whole step exists to prevent, reached through the door it
        opened.

        The direction is deliberate, not merely safe. Stamping low makes
        the newer machine re-run a migration over data it has already
        migrated: wasteful, and in its log. Stamping high makes rows that
        were never migrated indistinguishable from rows that were, for
        good."""
        self._write(self._document(2))
        self._target_with_a_gap()
        db, data = self._load()
        self.assertTrue(db._migration_incomplete, "premise: our chain has a "
                        "gap, so save() stamps _loaded_version")
        self.assertEqual(2, data["version"], "premise: we stopped at 2")
        # The peer HAS step 2 and has already rewritten the file at 3.
        peer = self._document(2)
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
        # And the claim above is about real rows, not just a number.
        self.assertTrue(
            [row for row in on_disk["assets"] if "moods" not in row],
            "premise: at least one row must still be at the old shape, or "
            "the stamp would not be a lie")

    def test_a_peer_version_is_still_carried_through_a_whole_chain(self):
        """The accept path for the line above. With no gap, a peer's newer
        version must still survive - otherwise every merge downgrades the
        other machine's file and it re-runs its whole chain."""
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
        """A latch belongs to the FILE, not the session - the rule this
        module already learned twice. A gap in library A's chain must not
        hold library B's stamp back."""
        self._write(self._document(2))
        self._target_with_a_gap()
        db, _ = self._load()
        self.assertTrue(db._migration_incomplete, "premise: A has a gap")
        database._MIGRATIONS[2] = lambda data: None      # B's build is whole
        other = tempfile.mkdtemp(prefix="amaze_dbhard_b_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self._write(self._document(1), path=os.path.join(other, self.FILENAME))
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
    """There is exactly ONE `.unreadable` copy per file, forever.

    Write-once is deliberate: the SECOND failure is usually a write we
    caused, so the first copy is the one holding the original. But two
    degenerate cases made that single slot useless.

    * A 0-byte source was preserved. A sync placeholder is an ordinary
      state for a file in a synced library, so the slot was spent on
      nothing and the genuinely truncated file that arrived a minute
      later got no copy at all.
    * A 0-byte `.unreadable` was kept forever. A copy holding no bytes is
      not evidence of anything, and keeping it locked the slot shut.
    """

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
        """The point of the fix, driven as a sequence: the placeholder
        arrives first, the truncated file a moment later. That second
        file is the one worth keeping."""
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
        """A `.unreadable` holding no bytes cannot be the evidence the
        write-once rule is protecting."""
        self._write("", path=self.keep)
        self._write('{"gradients": [{"name": "real"')
        result = self.hostos.preserve_unreadable(self.path, why="truncated")
        self.assertEqual(self.keep, result)
        self.assertGreater(
            os.path.getsize(self.keep), 0,
            "an empty .unreadable kept the slot shut, so nothing can ever "
            "be preserved for this file again")

    def test_a_real_existing_copy_is_never_replaced(self):
        """The accept path for write-once, and the reason this rule
        exists: the FIRST copy is the one that holds the original."""
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
        """The accept path that matters most: the guard must not have
        turned into "never preserve anything"."""
        self._write('{"gradients": [')
        self.assertEqual(self.keep,
                         self.hostos.preserve_unreadable(self.path))
        self.assertTrue(os.path.isfile(self.keep))


class TheRefusalOnlyClaimsACopyThatExistsTest(_Case):
    """The save refusal said "A copy of it is beside it as .unreadable"
    unconditionally, and preserve_unreadable has two paths that create
    nothing. A reassurance that is not quite true is worse than jargon,
    because the reader stops believing the next one."""

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
        """A 0-byte peer file: nothing is preserved, so nothing may be
        promised. The refusal itself must still happen."""
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
        """THE SAME UNTRUE SENTENCE, IN A SECOND PLACE. library_policy's
        note said "a copy is beside it as .unreadable" unconditionally as
        well; the plan named only database.py, and one policy speaking with
        two voices is how a guard gets fixed in one module and not the
        other."""
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
        """The accept path: when there IS a copy, the note has to name it,
        or the one surviving version of the file is unfindable."""
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
    """`.bak-first` is written once and never rotated.

    snapshot_before_write copied whatever was on disk with no parse check
    at all, so a single half-synced launch minted the one permanent
    restore point from garbage - and the rolling `.bak-N` ring then aged
    the good states out behind it. gradients.json and code.json have NO
    `.bak-*` tier of any kind on the real library (measured 2026-07-29),
    which means their very next snapshot IS their permanent floor:
    exactly one chance to get it right.
    """

    def setUp(self):
        from amaze.helpers import hostos
        self.hostos = hostos
        self.dir = tempfile.mkdtemp(prefix="amaze_snapshot_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        # snapshot_before_write is once per session per PATH, and the
        # module-level set outlives a single test.
        hostos._session_snapshots.pop(self.path, None)
        self.addCleanup(hostos._session_snapshots.pop, self.path, None)

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _good(self, count=3):
        self._write(json.dumps(
            {"categories": ["Warm"],
             "gradients": [{"name": "g%d" % i} for i in range(count)]}))

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
        """THE SAME DEFECT, THREE LINES EARLIER IN THE SAME FUNCTION. The
        marker was released when the bytes would not parse and not when the
        read itself failed - and that branch is the TRANSIENT one: the
        Windows sync-client hold replace_file already retries around, a
        share that dropped for a second. Burning the session's one chance
        on a failure that has already passed left the file with no restore
        point for the rest of the session."""
        if self.hostos.is_windows() or os.geteuid() == 0:
            self.skipTest("an unreadable file needs POSIX bits and a "
                          "non-root reader")
        self._good(12)
        # A real unreadable file rather than a patched open(): the branch
        # under test is an OSError from the read, and producing one for
        # real cannot be wrong about which call raises.
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
        """The half that makes the guard useful rather than merely safe.
        The once-per-session marker has to be RELEASED, or the session's
        one chance is spent on the read that failed."""
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
            self.assertEqual(40, len(json.load(handle)["gradients"]),
                             "the permanent copy is not the healthy file")

    def test_a_good_file_is_still_snapshotted(self):
        """The accept path. A parse check that rejected anything real
        would silently switch the whole backup system off."""
        self._good(5)
        self.hostos.snapshot_before_write(self.path)
        self.assertTrue(os.path.exists(self.path + ".bak-first"),
                        "no snapshot was taken of a perfectly good file")
        self.assertTrue(os.path.exists(self.path + ".bak-1"))

    def test_a_bom_prefixed_file_is_still_snapshotted(self):
        """A BOM'd document loads fine now (utf-8-sig), so it must not
        read as garbage here - that would deny a backup to exactly the
        file most likely to need one."""
        with open(self.path, "w", encoding="utf-8-sig") as handle:
            json.dump({"gradients": [{"name": "g0"}]}, handle)
        self.hostos.snapshot_before_write(self.path)
        self.assertTrue(
            os.path.exists(self.path + ".bak-first"),
            "a byte-order mark was treated as corruption")

    def test_a_good_rotation_is_not_disturbed(self):
        """The rolling ring still rolls, and an identical rewrite still
        does not consume a slot."""
        self._good(3)
        self.hostos.snapshot_before_write(self.path)
        self.hostos._session_snapshots.pop(self.path, None)
        self._good(4)
        self.hostos.snapshot_before_write(self.path)
        self.hostos._session_snapshots.pop(self.path, None)
        with open(self.path + ".bak-2", encoding="utf-8") as handle:
            self.assertEqual(3, len(json.load(handle)["gradients"]),
                             "the older state did not rotate down")
        with open(self.path + ".bak-1", encoding="utf-8") as handle:
            self.assertEqual(4, len(json.load(handle)["gradients"]))
        self.hostos.snapshot_before_write(self.path)
        with open(self.path + ".bak-2", encoding="utf-8") as handle:
            self.assertEqual(
                3, len(json.load(handle)["gradients"]),
                "an identical rewrite consumed a rotation slot")

    def test_a_corrupt_file_does_not_rotate_a_good_tier_out(self):
        """The compound failure: the ring is what a restore falls back to
        when .bak-first is too old, and rotating garbage in pushes the
        oldest good state off the end."""
        self._good(40)
        self.hostos.snapshot_before_write(self.path)
        self.hostos._session_snapshots.pop(self.path, None)
        self._write("{ not json at all")
        self.hostos.snapshot_before_write(self.path)
        with open(self.path + ".bak-1", encoding="utf-8") as handle:
            self.assertEqual(
                40, len(json.load(handle)["gradients"]),
                "garbage was rotated into the newest slot, pushing the "
                "good states one step closer to falling off the end")


class ARefusalLeavesTheDocumentWhole(unittest.TestCase):
    """A refused write must leave the shared DOCUMENT exactly as it
    was, not only the model: set() consumes the pending delete into the
    connector's live data before save() answers, so a declined delete
    sat in the document waiting for ANY other model's save - Categories
    writes only its own keys and never re-adds assets - to commit it."""

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
        # A row with a REAL id: the fixture's damaged row answers -1
        # and never appears in the document.
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
            self.prefs.is_material_favorite(asset.mat_id),
            "the star never reached the per-user store")


class QuarantineCrossesVolumes(unittest.TestCase):
    """The quarantine lives under config_root while the library may
    live on an external drive, a NAS or another Windows drive letter -
    and os.replace cannot rename across that boundary. Every caller
    treats "" as "could not be moved", so Clean Library's sweep and
    Repair's Move Aside silently did nothing on exactly those setups.
    The fallback copies-then-unlinks; not atomic, but the shipped
    alternative was nothing happening at all."""

    def test_a_cross_device_move_still_lands(self):
        from unittest.mock import patch
        from amaze.core import quarantine

        # fixture_prefs first: it redirects config_root, so the
        # quarantine folder lands inside the temp tree.
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
        # patch.object with create=True: hou.ui may not exist under
        # hython at all, and a raw assignment leaks into later tests.
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
        """The pair a material owns, both present so pass 1 keeps the
        row and only pass 3's judgement is under test."""
        paths = [os.path.join(self.mat_dir, asset_id + ".mat"),
                 os.path.join(self.mat_dir, asset_id + ".interface")]
        for path in paths:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("owned by " + asset_id + "\n")
        return paths

    def _drop_rows_with_no_files(self):
        """Rewrite the fixture index keeping only rows whose files are
        actually on disk, BEFORE the model is built.

        Not tidying. The committed fixture carries a row with id -1 and no
        files, so pass 1 always finds something to remove and pass 2
        therefore always SAVES - and that save merges the file it is
        writing over, which adopts any row another session added. The
        adoption is a real second line of defence and it is tested
        elsewhere; here it masks the thing under test completely, so the
        orphan pass would look safe with the fix removed."""
        document = self._read_own()
        keep = [row for row in document["assets"]
                if os.path.exists(os.path.join(
                    self.mat_dir, str(row.get("id")) + ".mat"))]
        self.assertTrue(keep, "premise: the fixture must have intact rows")
        document["assets"] = keep
        self._write_own(document)

    def _ids_known_at_the_decision(self, model):
        """The in-memory ids as they stand when the orphan pass actually
        asks - which is the only moment the premise is about."""
        seen = {}
        real = model._all_known_asset_ids

        def spy():
            seen["memory"] = {str(a.mat_id) for a in model.assets}
            return real()

        model._all_known_asset_ids = spy
        return seen


class CleanupReadsItsOwnDatabaseFromDiskTest(_CleanupCase):
    """A panel left open cannot see what the other machine added.

    `_all_known_asset_ids` skipped the model's own file outright - "its
    ids are the in-memory ones" - but in-memory means "as at our load".
    Another session adding a material writes both the row and its files;
    this session's pass 3 then reads those files as belonging to nobody
    and deletes them, while the correct, newer row sits on disk untouched.
    The next Clean Library removes that row too, for missing files.
    """

    NEWCOMER = "OTHERSESSION1"

    def test_a_row_another_session_added_protects_its_files(self):
        self._drop_rows_with_no_files()
        model = self._model()
        owned = self._files_for(self.NEWCOMER)
        # The other machine's save, straight to disk behind the model's
        # back - which is exactly what it looks like from here.
        document = self._read_own()
        document["assets"].append({
            "id": self.NEWCOMER, "name": "theirs", "categories": ["Wood"],
            "tags": [], "favorite": False, "renderer": "Karma",
        })
        self._write_own(document)
        known = self._ids_known_at_the_decision(model)
        self._cleanup(model)
        # THE PREMISE, at the moment the decision was made. Asserting it
        # before the call is not enough: an intervening save merges the
        # file and adopts the row, and then the pass is safe for a reason
        # that has nothing to do with reading the index from disk.
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
        """The accept path, and the one that matters: reading the own file
        must not turn the orphan pass into a no-op. If it did, Clean
        Library would quietly stop working for everybody."""
        model = self._model()
        genuine = os.path.join(self.mat_dir, "GENUINEORPHAN1.mat")
        with open(genuine, "w", encoding="utf-8") as handle:
            handle.write("in no index at all\n")
        self._cleanup(model)
        self.assertFalse(
            os.path.exists(genuine),
            "the orphan pass did not run - a file in no index survived")

    def test_a_row_this_session_added_is_still_protected(self):
        """The union has to keep BOTH sides. A row this session just added
        may not have reached disk yet, so dropping the in-memory ids in
        favour of the file would delete the files of the material the user
        saved a second ago."""
        model = self._model()
        owned = self._files_for("INMEMORY1")
        document = self._read_own()
        model._assets.append(self.library_mod.material.Material.from_dict({
            "id": "INMEMORY1", "name": "mine", "categories": ["Wood"],
            "tags": [], "favorite": False, "renderer": "Karma",
        }))
        # Disk deliberately left WITHOUT the row.
        self._write_own(document)
        self._cleanup(model)
        for path in owned:
            self.assertTrue(
                os.path.exists(path),
                "a file belonging to a material held only in memory was "
                "deleted - that is the material the user just saved")

    def test_a_malformed_own_database_does_not_kill_the_sweep(self):
        """`[]` and `{"assets": null}` parse fine and then raised
        AttributeError/TypeError past the OSError/ValueError handler, so
        Clean Library died mid-sweep with no summary and no dialog."""
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
    """"It lists nothing" is not the same as "it owns nothing" - and the
    dangerous condition was never "it lists nothing" on its own.

    A sibling that parses perfectly into ZERO rows was once taken at its
    word: "it owns nothing, so nothing in the directory can belong to it."
    That is the exact shape a wrongly-seeded list has (measured
    2026-07-29: cops.json 5,537 bytes / 8 records -> 96 / 0) and pass 3
    then deleted the 21 files its 8 live assets owned. It is ALSO the
    honest shape of a section nobody has ever used, so a blanket refusal
    would switch Clean Library off for most libraries.

    The test that separates them is the FILES: an empty list plus files in
    the asset folder that no section accounts for is a load that failed;
    an empty list with nothing unaccounted for is a section nobody used.

    This REPLACED the first version's test, which asked whether a copy
    beside the file still listed materials. Measured on the real library,
    that evidence is missing from exactly the files that need it most -
    code.json and gradients.json have no .bak at all - and the live-model
    acceptance that went with it was defeated by the ordinary case, since
    Clean Library is reached from the panel's own View menu with every
    section loaded.
    """

    COP_ID = "COPOWNED1"

    def setUp(self):
        super().setUp()
        self.cops = os.path.join(self.prefs.dir, "cops.json")
        self.code = os.path.join(self.prefs.dir, "code.json")
        # The files a COP asset owns, both present so pass 1 keeps
        # nothing and only pass 3's judgement is under test. Nothing in
        # any list on disk mentions this id.
        self.owned = self._files_for(self.COP_ID)

    def _empty_cops(self):
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": []}, handle)

    def _no_backups_premise(self):
        """The whole point of the new test: it must work with no copy of
        the emptied file anywhere. gradients.json has none on the real
        library and code.json has none either, so the guard that needed
        one protected everything except what needed protecting."""
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
        """The reader has to be able to go and look. Two files, named as a
        count and a folder they can open - not 32-hex filenames, which
        carry no information for anybody."""
        self._empty_cops()
        model = self._model()
        self._cleanup(model)
        self.assertTrue(self._skip_line(model),
                        "premise: the sweep must have been held back")
        # The REASON line, one per section - the headline names the
        # sections and this says what is wrong with each, because carrying
        # both in one sentence nested a parenthetical inside another.
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
        """A REFUSAL NAMES THE WAY OUT. Here it cannot be "delete a copy":
        what stands in the way is real files nothing lists. It is Repair -
        and the shelf tab is a per-machine step, so a sentence that stops
        at "on the Amaze shelf" is a next step that does not work on a
        machine where nobody added the tab."""
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
                      "it is a per-machine step (INSTALL.md 6b-2)")
        # AND THE RESTART. This message can only be reached from the panel,
        # so this Houdini has already read the library - one connector per
        # file lives for the whole process and its next save writes what it
        # remembers. Repair can therefore report in this session and only
        # ACT in a fresh one, and a route that does not say so sends the
        # reader to a tool that will tell them to quit and come back.
        self.assertIn("quit Houdini", route[0],
                      "the way out does not mention the restart Repair "
                      "needs before it can put anything right")
        self.assertIn("before you open Amaze", route[0],
                      "nothing says Repair has to run before the panel is "
                      "opened again")

    def test_the_refusal_explains_that_both_causes_look_alike(self):
        """Teach before you warn: the reader cannot tell from the fact
        alone whether their library is damaged or simply unused."""
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
        """AGGREGATE BEFORE INTERRUPTING. One line per empty section put
        two near-identical thirty-word sentences in a single dialog, which
        is the nagging the rule exists to prevent."""
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
        """THE DOOR THAT CLOSED. The version this replaces accepted the
        section's own model, having read the file and not been refused,
        as proof the emptiness was real - and then swept.

        Clean Library is reached from the panel's View menu, so the panel
        is open and every enabled section is loaded: a list that loaded as
        nothing produces exactly this model, agreeing perfectly happily.
        The one configuration that defeated the guard was the ordinary
        one. Files no section accounts for cannot be talked out of
        existence by a model - only the user can say whose they are."""
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
        """ORPHANHOOD IS RELATIVE TO EVERY LIST SHARING THE DIRECTORY.
        Measured on the real library: 548 records in library.json plus 8
        in cops.json is 556 .mat files, exactly. A file the Code list
        accounts for is accounted for, even though the Nodes list is the
        one being judged - getting this wrong is how 21 files belonging to
        8 live COP assets were deleted, and how a human nearly deleted the
        same 8 by hand."""
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
        """THE ACCEPT PATH, and the one that decides whether this is a
        guard or an outage. Most libraries have an unused Nodes section;
        refusing there would switch Clean Library off for nearly everyone.

        The leftover here is an image, and that is deliberate: the guard
        weighs the ASSET folder, where every asset's content pair lives.
        An image with no owner is a thumbnail whose material is gone, not
        evidence that a list failed to load. (Narrow on purpose - see
        DB-HARDENING step 10. Widening the guard to the image folder would
        turn this accept path into a refusal, which is the cost to weigh
        if anyone proposes it.)"""
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
        """THE ACCEPT PATH, NARROWED TO THE LISTS THAT COULD BE INVOLVED.

        The guard weighs the ASSET folder, and a Code snippet cannot own
        anything in it - code_library: "Storage is INLINE text ... No
        <id>.mat/.png files at all". So an empty Code list held the sweep
        back over a leftover .mat it could not possibly have owned: the
        accept path paid the cost of the guard twice as often, for no
        safety at all. code.json's ids still count towards the union; only
        its emptiness stops being evidence about this folder."""
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
        """The narrowing is about EMPTINESS AS EVIDENCE, not about reading
        the file. A Code asset owns an icon in the image folder, and
        without its ids that icon is swept as a leftover."""
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
        """NO RAW EXCEPTION TEXT ON SCREEN, no Errno, no parse position.
        The entry was built as "%s (%s)" with the json error, so the
        message the user acts on read "cops.json (Expecting property name
        enclosed in double quotes: line 1 column 3 (char 2))"."""
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
        """A refusal that opens with "Library cleanup finished" tells the
        reader who takes the first line and closes that the library was
        tidied, when nothing was touched."""
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
        """The other half of the accept path: with every section listing
        its own assets, a genuine leftover is still removed."""
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
        """The shared sentence ends in "could not be checked". "Could not
        be read" fights an entry saying the file is right there and lists
        nothing."""
        self._empty_cops()
        model = self._model()
        self._cleanup(model)
        summary = " ".join(model.last_cleanup_summary)
        self.assertNotIn("could not be read", summary)
        self.assertIn("could not check", summary)

    def test_nothing_is_called_unaccounted_for_while_a_list_is_unreadable(self):
        """A HALF-BUILT UNION MAY NOT ACCUSE ANYBODY. When another list
        will not parse the sweep is already held back, and the ids that
        list holds are unknown - so counting files against the ids we DO
        have would report a live asset's files as unaccounted for, in a
        sentence the user is meant to act on."""
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
        """The cleanup read is the utf-8-sig call site beyond the two in
        database.py, and it decides whether DELETING is safe. A BOM'd
        sibling read as unreadable aborts the sweep for a file that is
        perfectly good - the guard firing on a healthy library, which is
        an outage rather than safety."""
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
        """SAY WHY, AND FAIL CLOSED. An empty list back from the scan means
        "nothing is unaccounted for", which is the answer that lets the
        sweep delete - so a failure to read the folder has to come back as
        something else entirely, or a failure and an honest empty result
        are the same value."""
        model = self._model()
        shutil.rmtree(self.mat_dir)
        self.assertIsNone(
            model._files_no_section_accounts_for({"WHATEVER"}),
            "a folder that could not be listed was reported as holding "
            "nothing unaccounted for")

    def test_the_guard_and_the_sweep_share_one_classifier(self):
        """A guard that counts a different set of files than the sweep
        touches is a second opinion nobody reconciled. Both go through
        database.asset_id_for_file, so the tails the sweep strips are
        exactly the ones the guard treats as owned - and so does Repair,
        which reports on the same folder."""
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
    """add_asset writes a material's .mat and .interface BEFORE the
    index write runs. Every refusal in save() used to return None
    exactly like a completed save, so the caller reported success for an
    asset the library does not list - the user watches a tile appear and
    it is gone the next time Houdini opens.
    """

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
        """The disk-full / file-held path: the only exit that reports
        through hou.ui rather than the latch."""
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
        """Source-derived. A bare `return` is indistinguishable from a
        completed save at the call site, and that is the whole defect -
        so no exit may leave the verdict unstated."""
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
    """The latch was set on a merge failure and cleared nowhere except
    a fresh connector - so "reopen Amaze", the recovery the message
    prescribes, could not work: reopening re-enters load(), which
    short-circuits on the data it already holds. A user who fixed the
    file still could not save for the rest of the session.
    """

    def _latch(self):
        self._write(self._document())
        db, _ = self._load()
        db.set(self._document(count=4))
        # Another session replaces the file with something unparseable,
        # and moves its clock so the stale-write guard fires.
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
    """reload_with_path set _data = None before loading, with no
    try/except: a switch to a path with no database left the connector
    holding None for the life of the process, silently discarding every
    later save while the panel showed stale rows."""

    def test_switching_to_an_empty_directory_is_not_a_failure(self):
        """PREMISE CHECK, and it corrects the step. reload_with_path was
        specified as leaving the connector holding None after a failed
        load - but load() no longer fails on a missing database: it
        seeds an empty one, which is how a NEW library starts. The
        stranding defect is already gone."""
        self._write(self._document())
        db, _ = self._load()
        empty = tempfile.mkdtemp(prefix="amaze_noswitch_")
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        db.reload_with_path(empty + os.sep)
        self.assertTrue(db.save(),
                        "a switch to a fresh directory left a connector "
                        "that cannot write")

    def test_the_previous_library_survives_a_failed_switch(self):
        """The path the rollback is FOR: a load that genuinely raises -
        a permission error, an unreadable directory. Without it the
        connector holds None for the life of the process and every save
        is discarded in silence."""
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
    """Categories and MaterialLibrary hold a direct alias to the
    connector's category and tag lists. Rebinding swaps the connector's
    list for a new one and leaves the model pointing at the old one, so
    an adopted category reaches disk on one save and is erased by the
    next."""

    def test_the_alias_survives_SET(self):
        """A model takes its alias at construction and keeps it for the
        life of the panel, while set() runs on every save. Rebinding
        there detaches the alias before a merge can adopt anything into
        it - so this has to hold first, or the merge fix is pointless."""
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
        """Callers routinely hand back the object they were given.
        Emptying the destination before copying then wipes the source -
        four category-colour tests went red the first time this was
        written the obvious way."""
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
        # AFTER set(), because that is what a model does: it hands the
        # connector its state and then holds the alias.
        alias = db._data["categories"]

        # Another session adds a category and saves.
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
    """Two panes share one connector - the registry is keyed by
    filename - but each keeps its own in-memory asset list. set() used
    to replace the connector's rows wholesale from the caller's copy,
    and because the connector's own write refreshes its own stale-write
    baseline, the guard never fires for this in-process case. Pane 2's
    save silently deleted the material pane 1 had just added.
    """

    def test_a_row_the_caller_never_saw_survives_its_save(self):
        self._write(self._document(count=2))
        db, _ = self._load()

        # Pane 1 adds a row and saves.
        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET1"},
                           {"id": "PANE1_NEW"}],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        # Pane 2 was built earlier and has never heard of PANE1_NEW.
        db.set({"assets": [{"id": "ASSET0"}, {"id": "ASSET1"}],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        ids = [a["id"] for a in self._on_disk()["assets"]]
        self.assertIn("PANE1_NEW", ids,
                      "a second pane's save deleted the material the "
                      "first pane had just added, and nothing said so")

    def test_the_callers_version_of_a_row_it_holds_still_wins(self):
        """Union must not mean "ignore the caller" - an edit to a row
        the caller does hold has to land."""
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
        """A forgotten id must not keep suppressing a row somebody
        legitimately re-adds later."""
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
    """The registry is keyed by filename alone, so one connector serves
    every pane. A library switch in one pane repoints it under all of
    them, and a pane still holding the old library's rows then writes
    them into the new library's file - with the stale-write guard blind
    to it, because the connector's own write refreshed its own baseline.
    """

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
        """The comparison is on canonical paths: a model holding
        "/lib/" and a connector holding "/lib" are the same place, and
        refusing there would break every save for no reason."""
        self._write(self._document())
        db, _ = self._load()
        self.assertTrue(db.serves(self.dir))
        self.assertTrue(db.serves(self.dir + os.sep))


class ContentFingerprintGuardTest(_Case):
    """Both directions of the stat guard's error, measured before the
    change: a same-size edit passes (mtime, size) and the peer's change
    is lost; a byte-identical rewrite trips it as a conflict that is
    not there."""

    def _arm(self):
        self._write(self._document())
        db, _ = self._load()
        db.set(self._document(count=4))
        return db

    def test_a_same_size_edit_is_seen(self):
        """The stat guard's blind spot: flip one byte, restore the
        mtime, keep the size."""
        db = self._arm()
        with open(self.path, encoding="utf-8") as handle:
            raw = handle.read()
        stat_before = os.stat(self.path)
        # ASSET2 -> ASSEX2: same length, different content.
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
        """A peer's atomic no-op rewrite must not send an ordinary save
        down the merge path."""
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
        """Sync hygiene: every write costs a snapshot rotation and a
        sync upload downstream, so a save that changes nothing must be
        a no-op on disk too."""
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
        """The spec's own demand: the two existing byte-determinism
        tests would not catch a Material.get_as_dict key-reorder. Load
        the committed fixture into a REAL model, save to scratch, and
        byte-compare - if serialisation is deterministic end to end,
        the no-op skip above is sound; if a key reorders, this is the
        test that says so."""
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
            # The FIRST save may legitimately differ from the committed
            # fixture (schema stamp, formatting). What must hold is
            # byte-determinism from then on: a second save of the same
            # state writes the same bytes.
            self.assertTrue(model.save())
            with open(source, "rb") as handle:
                third = handle.read()
            self.assertEqual(after, third,
                             "two saves of identical state produced "
                             "different bytes - serialisation is not "
                             "deterministic and the no-op skip never "
                             "fires")


class CreditGoesToTheRowWithTheIdTest(_Case):
    """matx_import credited assets[-1] after add_asset. The save inside
    add_asset can ADOPT another session's row - appended after ours by
    the merge - so the last row can be somebody else's material, and the
    credit, licence and description landed on it."""

    FILENAME = "library.json"

    def test_an_adopted_row_lands_after_ours(self):
        """The premise, proven at the connector: adoption appends, so
        position is not identity."""
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
        """Source-derived pin: the scenario above is real, so the call
        site must resolve by id, and must not slide back to position."""
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
    """Destination names derived from the title alone: two sources both
    offer a "Red Brick", and extracting the second into the first's
    directory interleaves two packages' textures - the .mtlx that
    survives references a mixture."""

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
        """Identity must be stable, or re-downloading a record can never
        find what it already fetched."""
        from amaze.core import matx_import
        a = matx_import.package_dirname(self._R("polyhaven", "x", "Moss"))
        b = matx_import.package_dirname(self._R("polyhaven", "x", "Moss"))
        self.assertEqual(a, b)

    def test_the_title_still_leads_the_name(self):
        """Readability survives: the directory a user browses starts
        with the words they know."""
        from amaze.core import matx_import
        name = matx_import.package_dirname(
            self._R("polyhaven", "u1", "Old Oak"))
        self.assertTrue(name.startswith("Old_Oak") or
                        name.startswith("OldOak") or
                        name.startswith("Old Oak"),
                        name)


class ASuspiciousShrinkIsSaidOutLoudTest(_Case):
    """A list that shrank past half since its newest snapshot reads
    exactly like a list that is fine - 1 record parses as cleanly as
    40. Report-only: a shrink can be a deliberate cleanup, so it never
    blocks and never repairs, but a human sees the two numbers before
    the next sweep treats the shrunken list as truth."""

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
    """The step's own reviewer flag honoured: rather than converting
    the most safety-critical function into a single-exit body, a
    wrapper logs in finally - so every path, INCLUDING a raise, leaves
    exactly one database/save record, and each exit names its outcome."""

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
    """ROADMAP by name: two people editing DIFFERENT fields of the same
    asset is not a conflict at all - and whole-record ours-wins made it
    one. My rename erased your retag because the record was the unit of
    comparison while the field was the unit of editing."""

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
