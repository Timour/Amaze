"""A database that is momentarily ABSENT is not a new one.

Two reproduced data-loss bugs, one shape. Both loaders treated "the
file is not there right now" as "this is a fresh library", and both
then wrote that emptiness to disk:

* `database.py load()` SEEDED an empty secondary database and saved it
  immediately. cops.json 5,537 bytes / 8 records -> 96 bytes / 0. Clean
  Library then read the 21 files those 8 live assets owned as orphans
  and `os.remove`d them, because an EMPTY sibling parses perfectly and
  contributes zero ids - the existing "sibling will not parse" guard
  never fired.
* `gradient_library.py _load_user()` returned silently, leaving `_user`
  empty with `_load_failed` False, and the next `_save_user()`
  serialised that. 290,454 bytes / 388 gradients / 12 categories -> 39
  bytes / 0 / 0.

The file only has to be gone for the instant a model is constructed - a
sync placeholder still arriving, a conflict rename, a partial restore -
and panel.py constructs CopLibrary on EVERY panel open.

THE TRAP THIS FILE EXISTS TO PIN: the obvious evidence is a `.bak-*`
beside the file, and it is not enough. Measured on the real library
2026-07-29 - gradients.json has NO backups at all (388 gradients, 12
categories, and not one `.bak`), and neither does code.json (17
records). A `.bak`-only guard fails OPEN on exactly those two while
looking fixed. Their evidence is the SEED MARKER. Every refusal test
below therefore states which trace it is going on, and the gradient
ones assert that no `.bak` exists first.

And a guard that always fires is an outage, not a guard: a genuinely
new library - no marker, no backup, no file - must still initialise,
seed and save. That is tested as hard as the refusal.
"""

import contextlib
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# THREE dirnames up = scripts/python, the directory holding the `amaze`
# package - the DEV tree, not the install on Houdini's path.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou                                                # noqa: E402
from PySide6 import QtWidgets                             # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import database, debug                    # noqa: E402
from amaze.core import gradient_library                   # noqa: E402
from amaze.core import library as library_mod             # noqa: E402
from amaze.helpers import hostos                          # noqa: E402
from amaze.tests import test_support                      # noqa: E402


class _Prefs:
    """The two attributes gradient_library reads. Deliberately NOT a
    real Prefs: one constructed under hython resolves $AMAZE to the live
    install, and that is how a test overwrote the real settings once."""

    def __init__(self, directory):
        self.dir = directory
        self.directory = directory


class _NoteWatcher:
    """Records every debug.note AND lets the real one run, so a test can
    assert on the structured note and on what the user actually saw.

    Both matter and they are not the same thing: debug.note only writes
    the log record when Debug Mode is on, while the `Amaze: ...` print
    is what a user with Debug Mode off has to go on."""

    def __init__(self, testcase):
        self.notes = []
        real = debug.note

        def spy(message, /, **data):
            self.notes.append((message, data))
            return real(message, **data)

        patcher = patch.object(debug, "note", spy)
        patcher.start()
        testcase.addCleanup(patcher.stop)

    @property
    def text(self) -> str:
        return "\n".join(message for message, _ in self.notes)

    def __len__(self) -> int:
        return len(self.notes)


def _stdout_of(func):
    """(return value, everything printed). The refusal has to be LOUD,
    and "loud" means a line the user can read, not only a log record."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = func()
    return result, buffer.getvalue()


class TheUnreadableIndexDialogTest(unittest.TestCase):
    """An unparseable library.json at panel open gets ONE dialog -
    Repair or open without a library - never a traceback, and never
    the old promise that reopening would help. Sabotage: remove the
    narrow catch in the constructor and every case here dies on the
    raw ValueError instead."""

    def _panel_over_broken_index(self, answer):
        """Build a panel, break its index, build a second panel with
        hou.ui scripted to `answer` the dialog. Returns (panel,
        calls, index_path)."""
        first = test_support.fixture_panel(self)
        index_path = os.path.join(first.prefs.dir, "library.json")
        # A SAVE is what writes stamps - _StampWriter refreshes after a
        # successful index write, never before. The fixture builds its
        # materials without one, so nothing here was stamped and the
        # recovery below had nothing of its own to rebuild from.
        first.material_model.save()
        premise = os.path.join(
            first.prefs.dir, first.prefs.asset_dir)
        # MATERIAL stamps, counted against the index. `mat/` is shared
        # with Nodes and Code, so a premise asking only whether ANY
        # stamp file exists was satisfied by the shipped Code starter
        # alone: this test passed for as long as it did because the
        # rebuild claimed those 15 snippets as materials, and the
        # assertion that the library recovered was reading them.
        mine = {str(a.mat_id) for a in first.material_model.assets}
        stamps = [name for name in os.listdir(premise)
                  if name.endswith(".stamp.json")
                  and name[: -len(".stamp.json")] in mine]
        self.assertTrue(stamps, "premise: the first build must have "
                        "stamped its own materials")
        with open(index_path, "wb") as handle:
            handle.write(b"{ this is not json")
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        calls = []

        def scripted(message, **_kw):
            calls.append(str(message))
            return answer

        ui = MagicMock()
        ui.displayMessage.side_effect = scripted
        with patch.object(hou, "ui", create=True, new=ui):
            second = test_support.reopened_panel(self)
        return second, calls, index_path

    def test_repair_reopens_the_recovered_library(self):
        panel, calls, index_path = self._panel_over_broken_index(0)
        self.assertTrue(calls, "no dialog was offered")
        self.assertIn("could not be read", calls[0])
        self.assertIsNotNone(panel.material_model,
                             "repair accepted but no library opened")
        self.assertTrue(
            panel.material_model.assets,
            "the recovered library holds no assets")
        with open(index_path, encoding="utf-8-sig") as handle:
            json.load(handle)

    def test_declining_opens_without_a_library_and_touches_nothing(self):
        panel, calls, index_path = self._panel_over_broken_index(1)
        self.assertTrue(calls, "no dialog was offered")
        self.assertIsNone(panel.material_model,
                          "declined, yet a library opened")
        with open(index_path, "rb") as handle:
            self.assertEqual(b"{ this is not json", handle.read(),
                             "declining still modified the file")

    def test_headless_opens_without_a_library_and_never_raises(self):
        first = test_support.fixture_panel(self)
        index_path = os.path.join(first.prefs.dir, "library.json")
        with open(index_path, "wb") as handle:
            handle.write(b"{ this is not json")
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        second = test_support.reopened_panel(self)
        self.assertIsNone(second.material_model)


class SecondaryDatabaseAbsenceTest(unittest.TestCase):
    """database.py load(): absent + evidence must not seed and save."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_absent_db_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "cops.json")
        # One connector per FILENAME, cached across the whole process -
        # a leftover instance would answer from another test's _data and
        # carry its _write_blocked latch with it.
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _connector(self, filename="cops.json"):
        return database.DatabaseConnector(filename)

    def _load(self, filename="cops.json"):
        db = self._connector(filename)
        return db, db.load(self.dir + os.sep)

    def _write_bak(self):
        """The trace snapshot_before_write leaves. It returns early for a
        path that does not exist, so this can only be here because
        cops.json was."""
        with open(self.path + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": "COP1"}]}, handle)

    # -- the guard FIRES ----------------------------------------------

    def test_an_absent_database_with_a_backup_is_not_recreated(self):
        self._write_bak()
        self.assertFalse(os.path.exists(self.path),
                         "premise: cops.json must be absent")
        db, data = self._load()
        self.assertFalse(
            os.path.exists(self.path),
            "an empty cops.json was created over a database that a .bak "
            "beside it says was here - this is the 8-records-to-0 bug")
        self.assertEqual([], data["assets"])
        # getattr, not attribute access: a missing latch must read as a
        # FAILED guard with this message, not as an AttributeError that
        # says nothing about what went wrong.
        self.assertTrue(getattr(db, "_write_blocked", False),
                        "writes were not blocked, so the next save "
                        "recreates the file the load refused to")

    def test_code_json_is_guarded_by_its_seed_marker_with_no_backup(self):
        """THE TRAP, in the database layer. code.json on the real library
        has 17 records and NO .bak-* at all (measured 2026-07-29) - its
        only trace is the starter-snippet marker. A backup-only guard
        would sail straight past this case."""
        code = os.path.join(self.dir, "code.json")
        with open(os.path.join(self.dir, ".amaze_code_starter_v1"),
                  "w", encoding="utf-8") as handle:
            handle.write("seeded\n")
        self.assertEqual(
            [], glob.glob(code + ".bak-*"),
            "premise: this test is worthless unless NO backup exists - "
            "that is the whole point of it")
        db, _ = self._load("code.json")
        self.assertFalse(
            os.path.exists(code),
            "an empty code.json was created although the starter marker "
            "beside it says the database was here")
        self.assertTrue(getattr(db, "_write_blocked", False),
                        "writes were not blocked for the session")

    def test_nothing_at_all_is_written_when_the_guard_fires(self):
        """Not "the database was not created" - NOTHING was created. A
        scratch file, a .bak of the emptiness, a version stamp: any of
        them means a writer ran when it should not have."""
        self._write_bak()
        before = sorted(os.listdir(self.dir))
        db, _ = self._load()
        db.save()                       # the save the panel does anyway
        db.save()                       # and the second one, which is
        #                                 the one that historically
        #                                 overwrote the preserved file
        self.assertEqual(before, sorted(os.listdir(self.dir)),
                         "the refusal path touched the directory")

    def test_the_refusal_is_loud(self):
        self._write_bak()
        watcher = _NoteWatcher(self)
        _, printed = _stdout_of(lambda: self._load())
        self.assertTrue(watcher.notes, "the refusal fired no debug.note")
        said = watcher.text
        self.assertIn("cops.json", said, "the note does not name the file")
        self.assertIn("cops.json.bak-1", said,
                      "the note does not say which trace it went on")
        self.assertIn("restart", said.lower(),
                      "the note does not tell the user what to do")
        # The refusal lasts as long as the trace does, so the message
        # has to name the way out for a deliberate delete - otherwise
        # the guard is a dead end for anyone who meant it. The assertion
        # names the FILE to remove, not just the words "on purpose": a
        # mangled sentence still contained that phrase and passed.
        self.assertIn("remove cops.json.bak-1 as well", said,
                      "the note does not say how to proceed if the "
                      "database was removed deliberately")
        if not hostos.is_windows():
            # Windows suppresses every print on purpose (any print pops
            # the Houdini Console in front of the user's scene); there
            # the log record above is the whole channel.
            self.assertIn("cops.json", printed,
                          "nothing reached the user - only the log, "
                          "which is off unless Debug Mode is on")

    # -- the guard must NOT fire --------------------------------------

    def test_a_genuinely_new_library_still_gets_its_database(self):
        """A fresh install: no file, no backup, no marker. Seeding is the
        CORRECT behaviour there and must survive the fix."""
        self.assertEqual([], os.listdir(self.dir), "premise: empty dir")
        db, data = self._load()
        self.assertTrue(
            os.path.isfile(self.path),
            "a brand-new library was refused its cops.json - the guard "
            "fires always, which is an outage, not a guard")
        self.assertEqual(["_All"], data["categories"])
        self.assertFalse(getattr(db, "_write_blocked", False))

    def test_a_new_database_can_still_be_saved_afterwards(self):
        """The accept path all the way through: seeded, then written."""
        db, _ = self._load()
        db.set({"assets": [{"id": "NEW1"}], "categories": ["_All"],
                "tags": []})
        db.save()
        with open(self.path, encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(["NEW1"], [a["id"] for a in on_disk["assets"]])

    def test_an_existing_database_still_loads_and_saves(self):
        """Evidence present AND the file present - the ordinary case on
        every launch of a real library. Nothing may be refused here."""
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": "COP1"}, {"id": "COP2"}]}, handle)
        self._write_bak()
        db, data = self._load()
        self.assertEqual(2, len(data["assets"]),
                         "an existing database was not read")
        self.assertFalse(getattr(db, "_write_blocked", False),
                         "writes were blocked for a database that is "
                         "right there and parsed fine")
        db.set({"assets": [{"id": "COP1"}], "categories": ["_All"],
                "tags": []})
        db.save()
        with open(self.path, encoding="utf-8") as handle:
            # Reached disk is the claim, not "and nothing else did":
            # set() unions, so a row this caller did not mention stays.
            self.assertIn("COP1",
                          [a["id"] for a in json.load(handle)["assets"]],
                          "an ordinary save was refused")


class SiblingAbsenceStopsTheOrphanPassTest(unittest.TestCase):
    """The second half of bug 1, and the half that actually deletes.

    Blocking the empty seed is not enough on its own: with cops.json
    simply GONE, `_all_known_asset_ids` said "absent is fine - it owns
    nothing", so pass 3 still could not tell its files from orphans and
    still removed them. Deleting on incomplete knowledge is never the
    safe default, and an absent-but-known sibling is exactly as
    incomplete as an unparseable one."""

    ORPHAN = "ORPHANTEST1"

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        self.orphan = os.path.join(self.mat_dir, self.ORPHAN + ".mat")
        with open(self.orphan, "w", encoding="utf-8") as handle:
            handle.write("not owned by any index\n")
        self.cops = os.path.join(self.prefs.dir, "cops.json")
        self.assertFalse(os.path.exists(self.cops),
                         "premise: the fixture has no cops.json")

    def _cleanup(self):
        # patch.object with create=True: hou.ui may not exist under
        # hython at all, and a raw assignment leaks into later tests.
        with patch.object(hou, "ui", MagicMock(), create=True):
            self.model.cleanup_db(show_dialog=False)

    def test_the_orphan_pass_is_skipped_when_a_sibling_is_absent_but_known(self):
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"assets": [{"id": self.ORPHAN}]}, handle)
        self._cleanup()
        self.assertTrue(
            os.path.exists(self.orphan),
            "Clean Library deleted a file while cops.json was merely "
            "not-yet-arrived - this is how 21 files belonging to 8 live "
            "COP assets were removed")
        summary = " ".join(self.model.last_cleanup_summary)
        self.assertIn("Amaze could not check", summary,
                      "the refusal said nothing to the user")
        self.assertIn("cops.json", summary,
                      "the refusal does not name the sibling it is "
                      "waiting for")

    def test_the_refusal_names_the_way_out(self):
        """A deliberate delete leaves the trace behind, and the trace
        goes on answering "it was here" forever - so the orphan pass is
        disabled for good unless this sentence exists. Both load-time
        refusals name their way out; this one reported the problem and
        stopped, which reads as a dead end."""
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"assets": [{"id": self.ORPHAN}]}, handle)
        self._cleanup()
        # The way-out SENTENCE, not the summary as a whole. Asserting on
        # the joined text passed with the sentence deleted: "cops.json"
        # and "cops.json.bak-1" are both already in the refusal above it,
        # and "remove" is in the unrelated "were removed from the
        # library" line. A test that cannot fail proves nothing.
        way_out = [line for line in self.model.last_cleanup_summary
                   if "on purpose" in line]
        self.assertTrue(
            way_out,
            "the summary reports the refusal and stops - a user who "
            "deleted the database deliberately has the orphan pass "
            "disabled for good with nothing saying how to re-enable it")
        self.assertIn("cops.json.bak-1", way_out[0],
                      "the way out does not name the trace to delete, "
                      "so the user cannot act on it")
        self.assertIn("Node", way_out[0],
                      "the way out does not name the section that was "
                      "removed, in the word the panel uses for it")
        # THE COST OF FOLLOWING IT, said in the same sentence. On the real
        # library the trace named here is usually a .bak copy - which is
        # the copy Repair would put the section back from - so a message
        # that says "delete it" and stops there spends the evidence to
        # silence the warning about the evidence.
        self.assertIn("saved copy", way_out[0],
                      "nothing says the file it tells the user to delete "
                      "is also what Repair would restore from")
        self.assertIn("Repair", way_out[0],
                      "the sentence does not offer the look-first step")

    def test_the_refusal_does_not_contradict_itself(self):
        """The shared sentence ends in "could not be read". Saying "not
        on disk" in the same breath fights it - the reader cannot tell
        whether the file is there or not."""
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"assets": [{"id": self.ORPHAN}]}, handle)
        self._cleanup()
        summary = " ".join(self.model.last_cleanup_summary)
        self.assertNotIn("not on disk", summary)
        self.assertIn("not there yet", summary)
        # And it says which SECTION, because "cops.json" is not a word
        # that appears anywhere in the interface.
        self.assertIn("Node", summary,
                      "the summary names only the storage file, which "
                      "the user has never seen")

    def test_the_orphan_pass_still_runs_for_a_genuinely_absent_sibling(self):
        """The accept path. A library that never had a COP section must
        still get its orphans cleaned, or Clean Library quietly stops
        working for everyone."""
        self.assertEqual(
            [], glob.glob(self.cops + ".bak-*"),
            "premise: nothing may say cops.json was ever here")
        self._cleanup()
        self.assertFalse(
            os.path.exists(self.orphan),
            "the orphan pass was skipped although nothing suggests a "
            "COP database ever existed - the guard fires always")


class OwnDatabaseAbsenceStopsItsOwnOrphanPassTest(unittest.TestCase):
    """The half the first fix missed, and the half that still deleted.

    `_all_known_asset_ids` skipped `self.DB_FILENAME` outright, so the
    absent-but-known check never ran for the database the model is
    itself built on. With cops.json mid-sync that reads: the COP model
    loads (refused, so honestly empty), library.json and code.json both
    parse, nothing is reported unreadable - and pass 3 runs with the COP
    ids missing. panel.cleanup_db() calls the material model's cleanup
    and then the COP model's on ONE click, so the first refused
    correctly and the second deleted the same 23 files. Measured against
    a copy of the real library: byte for byte the loss the guard was
    written to stop.
    """

    COP_ID = "COPOWNED1"

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.cops = os.path.join(self.prefs.dir, "cops.json")
        self.assertFalse(os.path.exists(self.cops),
                         "premise: the fixture has no cops.json")
        # The files the ABSENT database owns. A COP asset stores
        # "<id>.mat" + "<id>.interface" in the SHARED asset directory,
        # exactly like a material - which is the whole reason one
        # section's cleanup can delete another's files, and what the 23
        # lost files were. (The "_cop" suffix pass 3 strips is something
        # else entirely: a COP companion saved beside a MATERIAL.)
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        self.owned = os.path.join(self.mat_dir, self.COP_ID + ".mat")
        self.owned_interface = os.path.join(
            self.mat_dir, self.COP_ID + ".interface")
        for path in (self.owned, self.owned_interface):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("owned by a COP asset that has not arrived\n")

    def _model(self):
        from amaze.core import cop_library
        return cop_library.CopLibrary(preferences=self.prefs)

    def _cleanup(self, model):
        with patch.object(hou, "ui", MagicMock(), create=True):
            model.cleanup_db(show_dialog=False)

    def test_a_model_does_not_delete_while_its_own_database_is_absent(self):
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": self.COP_ID}]}, handle)
        model = self._model()
        # ASSERT THE PREMISE. If the load ever stops being refused this
        # test silently becomes a test of nothing.
        self.assertEqual(
            [], list(model._assets),
            "premise: the refused load must leave the model empty - "
            "that emptiness is what made pass 3 unsafe")
        self._cleanup(model)
        self.assertTrue(
            os.path.exists(self.owned) and os.path.exists(
                self.owned_interface),
            "the COP section's own Clean Library deleted files its own "
            "absent database owns - this is the 23-file loss, moved from "
            "one model to another rather than fixed")
        summary = " ".join(model.last_cleanup_summary)
        self.assertIn("Amaze could not check", summary,
                      "files were spared but the user was told nothing")
        self.assertIn("cops.json", summary,
                      "the refusal does not name the database it is "
                      "waiting for")

    def test_a_model_with_its_own_database_present_still_cleans(self):
        """The accept path, and the one that matters most here: if this
        fired for a normal COP library, Clean Library would never remove
        an orphan from the Nodes section again."""
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": self.COP_ID}]}, handle)
        genuine = os.path.join(self.mat_dir, "GENUINEORPHAN.mat")
        with open(genuine, "w", encoding="utf-8") as handle:
            handle.write("in no index at all\n")
        model = self._model()
        self.assertEqual([self.COP_ID], [str(a.mat_id) for a in model._assets],
                         "premise: the COP database must have loaded")
        self._cleanup(model)
        self.assertTrue(os.path.exists(self.owned),
                        "a file the COP database owns was deleted")
        self.assertFalse(os.path.exists(genuine),
                         "the orphan pass did not run for a healthy COP "
                         "library - the guard fires always")

    def test_a_brand_new_cop_section_still_cleans(self):
        """No cops.json and no trace of one: load() seeds it, and the
        pass must run normally afterwards.

        The leftover proving it ran is an IMAGE, and it used to be one of
        this class's .mat files. That changed with DB-HARDENING step 10:
        a freshly seeded list holds nothing, and a list holding nothing
        now holds the sweep back while files in the asset folder are
        unaccounted for - see the sibling test below, which is the same
        setup with those files left in place. The two together are the
        whole rule: the emptiness alone decides nothing, the files decide.
        """
        self.assertEqual([], glob.glob(self.cops + ".bak-*"),
                         "premise: nothing may say cops.json was here")
        for path in (self.owned, self.owned_interface):
            os.remove(path)
        leftover = os.path.join(
            self.prefs.dir, self.prefs.img_dir, "GONEMATERIAL9.png")
        with open(leftover, "wb") as handle:
            handle.write(b"a thumbnail whose material is gone")
        model = self._model()
        self.assertTrue(os.path.isfile(self.cops),
                        "premise: a new library seeds its database")
        self._cleanup(model)
        self.assertFalse(
            os.path.exists(leftover),
            "the orphan pass was skipped on a brand-new COP section")

    def test_a_brand_new_cop_section_with_files_left_behind_does_not(self):
        """The same brand-new section, with the two unclaimed files still
        in the asset folder - and now it must NOT sweep.

        This is the case the trace-based guard could not see at all:
        nothing beside cops.json says it was ever here, so there was no
        evidence to be suspicious with, and the files went. They are
        either a COP asset whose list never arrived or genuine leftovers,
        and nothing on disk can tell the two apart - so Amaze asks instead
        of guessing, which is what Repair is for."""
        self.assertEqual([], glob.glob(self.cops + ".bak-*"),
                         "premise: nothing may say cops.json was here")
        model = self._model()
        self.assertTrue(os.path.isfile(self.cops),
                        "premise: a new library seeds its database")
        self._cleanup(model)
        for path in (self.owned, self.owned_interface):
            self.assertTrue(
                os.path.exists(path),
                "%s was deleted on the strength of a list that was seeded "
                "empty seconds earlier" % os.path.basename(path))
        summary = " ".join(model.last_cleanup_summary)
        self.assertIn("Repair", summary,
                      "the sweep was held back with no way out named")


class WriteBlockBelongsToTheFileTest(unittest.TestCase):
    """A refusal must not follow the user into a different library.

    One connector instance exists per FILENAME for the whole process,
    and Preferences can repoint it at any time (panel.switch_model_data
    -> library.reload_with_path -> db.reload_with_path). That reset
    _data and not _write_blocked, so a sync hiccup in library A left
    library B - healthy, loaded, edited all session - silently
    unsaveable. Measured: B's second asset never reached disk."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_absent_switch_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _library(self, name, healthy):
        directory = os.path.join(self.root, name)
        os.makedirs(directory)
        path = os.path.join(directory, "cops.json")
        if healthy:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"categories": ["_All"], "tags": [],
                           "assets": [{"id": "GOOD1"}]}, handle)
        else:
            with open(path + ".bak-1", "w", encoding="utf-8") as handle:
                json.dump({"categories": ["_All"], "tags": [],
                           "assets": [{"id": "OLD1"}]}, handle)
        return directory + os.sep, path

    def test_a_healthy_library_can_still_be_saved_after_a_refusal(self):
        broken, _ = self._library("A", healthy=False)
        good, good_path = self._library("B", healthy=True)
        db = database.DatabaseConnector("cops.json")
        db.load(broken)
        self.assertTrue(db._write_blocked,
                        "premise: library A must be refused, or this "
                        "test is not exercising the case")
        data = db.reload_with_path(good)
        self.assertEqual(["GOOD1"], [a["id"] for a in data["assets"]],
                         "premise: library B must load normally")
        self.assertFalse(db._write_blocked,
                         "the refusal followed the user to a library it "
                         "was never about")
        db.set({"categories": ["_All"], "tags": [],
                "assets": [{"id": "GOOD1"}, {"id": "GOOD2"}]})
        db.save()
        with open(good_path, encoding="utf-8") as handle:
            on_disk = [a["id"] for a in json.load(handle)["assets"]]
        self.assertEqual(
            ["GOOD1", "GOOD2"], on_disk,
            "a whole session's work in a healthy library was dropped "
            "because a DIFFERENT library was mid-sync")

    def test_switching_into_another_broken_library_refuses_again(self):
        """Clearing the latch must not weaken it: the refusal is
        re-derived from what is on disk, not remembered."""
        broken_a, _ = self._library("A", healthy=False)
        broken_b, path_b = self._library("B", healthy=False)
        db = database.DatabaseConnector("cops.json")
        db.load(broken_a)
        db.reload_with_path(broken_b)
        self.assertTrue(db._write_blocked,
                        "the second library's own evidence was ignored "
                        "because the latch had been cleared")
        self.assertFalse(os.path.exists(path_b),
                         "an empty cops.json was seeded in library B")


class ARefusedSaveSaysSoTest(unittest.TestCase):
    """The dropped save has to be audible.

    save() reported the refusal with debug.event, which is Debug-Mode
    gated and never prints - so the user edited, saved, and got no line
    anywhere. That was tolerable while _write_blocked needed a
    two-session merge failure; load() can now latch it from a sync
    hiccup at panel open, so it is on the ordinary path."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_absent_quiet_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "cops.json")
        with open(self.path + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": "OLD1"}]}, handle)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _blocked(self):
        db = database.DatabaseConnector("cops.json")
        db.load(self.dir + os.sep)
        self.assertTrue(db._write_blocked, "premise: the load must refuse")
        db.set({"categories": ["_All"], "tags": [],
                "assets": [{"id": "EDITED1"}]})
        return db

    def test_the_dropped_save_is_reported(self):
        db = self._blocked()
        watcher = _NoteWatcher(self)
        db.save()
        self.assertTrue(
            watcher.notes,
            "the save was dropped with only a debug.event, which is off "
            "unless Debug Mode is on - the user's edit vanished in "
            "silence")
        said = watcher.text
        self.assertIn("cops.json", said, "the note does not say which "
                      "database was not written")
        self.assertIn("not on disk", said.lower(),
                      "the note does not say the change failed to reach "
                      "disk, which is the only part that matters")

    def test_it_is_said_once_not_once_per_save(self):
        """save() is called from ordinary sidebar use - a line per save
        is a wall of text, and a wall of text is not read."""
        db = self._blocked()
        watcher = _NoteWatcher(self)
        db.save()
        first = len(watcher)
        db.save()
        db.save()
        self.assertEqual(first, len(watcher),
                         "every save repeated the whole refusal")

    def test_an_ordinary_save_says_nothing(self):
        """The accept path for a MESSAGE: a healthy library must not
        start narrating its saves."""
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": "OLD1"}]}, handle)
        db = database.DatabaseConnector("cops.json")
        db.load(self.dir + os.sep)
        self.assertFalse(db._write_blocked, "premise: nothing is wrong here")
        watcher = _NoteWatcher(self)
        db.set({"categories": ["_All"], "tags": [],
                "assets": [{"id": "OLD1"}, {"id": "NEW1"}]})
        db.save()
        self.assertEqual([], watcher.notes,
                         "a healthy save produced a refusal message")


class SectionLabelsMatchThePanelTest(unittest.TestCase):
    """core must not import the UI package, so database.py keeps its own
    copy of the section labels. A copy that can drift silently is worse
    than the coupling it avoids - this is what stops it."""

    def test_every_label_matches_the_one_source(self):
        from amaze.panel import sections
        labels = dict(sections.all_sections())
        for filename, key in (("library.json", "material"),
                              ("cops.json", "cop"),
                              ("code.json", "code"),
                              ("gradients.json", "gradient")):
            with self.subTest(filename=filename):
                self.assertIn(key, labels,
                              "the panel no longer has this section")
                self.assertEqual(
                    "%s (%s)" % (labels[key], filename),
                    database.section_name(filename),
                    "the refusal messages call this section something "
                    "the interface does not")

    def test_an_unknown_file_falls_back_to_its_name(self):
        """RE-KEYED 2026-08-03. This used `icons.json` as its example of
        a file nothing has a name for - and icons.json now HAS one,
        because the Keyed Store Engine declares the side tables and
        Repair reads that registry rather than a list of four. A
        detector keyed on a token that has moved goes vacuous, not red,
        so the example moves with it."""
        self.assertEqual("policy.json", database.section_name("policy.json"))

    def test_the_side_tables_DO_have_a_name_now(self):
        """The other half. Both stores' unreadable alerts send the user
        to Repair by name; Repair could not say either name."""
        self.assertEqual("Comments (notes.json)",
                         database.section_name("notes.json"))
        self.assertEqual("Tile icons (icons.json)",
                         database.section_name("icons.json"))
        self.assertEqual("comments", database.section_noun("notes.json", 2))


class GradientAbsenceTest(unittest.TestCase):
    """gradient_library._load_user(): absent + the seed marker.

    Every test here asserts there is no `.bak` first. That is not
    decoration - the real library's gradients.json has none, so a guard
    that leans on backups passes its own tests and leaves this bug
    exactly where it was."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_absent_grad_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        self.marker = os.path.join(
            self.dir, gradient_library.GradientLibrary._SEED_MARKER)

    def _seeded_before(self):
        """A library that HAS been seeded: the marker is written only
        after the seeded gradients were successfully saved, so it means
        gradients.json was here."""
        with open(self.marker, "w", encoding="utf-8") as handle:
            handle.write("seeded 388 curated palettes\n")

    def _assert_no_backup(self):
        self.assertEqual(
            [], glob.glob(self.path + ".bak-*"),
            "premise: this test only proves anything with NO backup "
            "present - the real library's gradients.json has none")

    def _library(self):
        lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        if lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        return lib

    # -- the guard FIRES ----------------------------------------------

    def test_the_seed_marker_alone_stops_the_empty_load(self):
        self._seeded_before()
        self._assert_no_backup()
        self.assertFalse(os.path.exists(self.path),
                         "premise: gradients.json must be absent")
        lib = self._library()
        self.assertTrue(
            lib._load_failed,
            "the absent file was read as an empty library - _load_failed "
            "stayed False, so the next save serialises 0 gradients over "
            "388")

    def test_the_first_save_writes_nothing(self):
        """The bug was never the load on its own; it was the save that
        followed it. Drive a real user action, not just the flag."""
        self._seeded_before()
        self._assert_no_backup()
        before = sorted(os.listdir(self.dir))
        lib = self._library()
        lib.add_user_category("Warm")       # an ordinary panel action
        lib._save_user()                    # and the direct call
        self.assertFalse(
            os.path.exists(self.path),
            "a 39-byte gradients.json was written where 290KB belongs")
        self.assertEqual(before, sorted(os.listdir(self.dir)),
                         "the refusal path touched the directory")

    def test_the_curated_palettes_are_not_reseeded_over_it(self):
        """Seeding calls _save_user() and THEN writes the marker, which
        is permanent - so a seed that runs while saving is refused burns
        the marker for gradients that never reached disk, and the
        palettes never seed again on that machine.

        Driven from the .bak evidence deliberately: with the marker
        present, _seed_curated_once returns on the marker check and this
        would pass without the latch being consulted at all."""
        if not os.path.exists(gradient_library._def_path("sanzo_wada.json")):
            self.skipTest("curated defs unreachable ($AMAZE not resolved) "
                          "- seeding cannot be exercised here")
        with open(self.path + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"categories": [], "gradients": []}, handle)
        self.assertFalse(os.path.exists(self.marker),
                         "premise: no marker, or the seed never runs and "
                         "this test proves nothing")
        lib = self._library()
        self.assertEqual([], lib._user,
                         "the curated palettes were seeded into a library "
                         "whose real gradients simply have not arrived")
        self.assertFalse(
            os.path.exists(self.marker),
            "the permanent seed marker was written for a save that was "
            "refused - the palettes can now never seed on this library")

    def test_the_refusal_is_loud(self):
        self._seeded_before()
        watcher = _NoteWatcher(self)
        _, printed = _stdout_of(self._library)
        self.assertTrue(watcher.notes, "the refusal fired no debug.note")
        said = watcher.text
        self.assertIn(gradient_library.GradientLibrary._SEED_MARKER, said,
                      "the note does not say which trace it went on")
        self.assertIn("nothing will be saved", said.lower())
        # ONE text, printed and recorded. On Windows note() suppresses
        # the print, so the RECORD has to carry the actionable half too
        # - the two used to differ and the log kept only "saving
        # disabled", which tells a Windows user nothing they can act on.
        self.assertIn(self.path, said,
                      "the record does not say where the file belongs")
        self.assertIn(
            "remove " + gradient_library.GradientLibrary._SEED_MARKER
            + " as well", said,
            "the record does not say how to proceed if gradients.json "
            "was removed deliberately - the refusal lasts as long as the "
            "marker does, so this is the only way out of it")
        if not hostos.is_windows():
            # Same guard as the database refusal test. The asymmetry
            # between the two was real: one test asserted a print the
            # other platform never makes.
            self.assertIn("gradients.json", printed,
                          "nothing reached the user - the print is the "
                          "channel a user without Debug Mode has")
            self.assertIn("restart", printed.lower(),
                          "the message does not say what to do about it")

    def test_a_backup_alone_also_fires_it(self):
        """The other trace still counts. gradients.json has no backups
        today, but hostos writes one the moment it is saved twice with
        different contents, and that is evidence too."""
        with open(self.path + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"categories": [], "gradients": []}, handle)
        self.assertFalse(os.path.exists(self.marker),
                         "premise: no marker - the .bak is doing the work")
        lib = self._library()
        self.assertTrue(lib._load_failed)
        self.assertFalse(os.path.exists(self.path))

    # -- the guard must NOT fire --------------------------------------

    def test_a_fresh_install_still_saves(self):
        """No file, no marker, no backup: a first run. Refusing here
        would mean gradients could never be saved on a new machine."""
        self.assertEqual([], os.listdir(self.dir), "premise: empty dir")
        lib = self._library()
        self.assertFalse(
            lib._load_failed,
            "a brand-new library was latched as unreadable - the guard "
            "fires always, which is an outage, not a guard")
        lib._user = [{"name": "first", "type": "user", "points": []}]
        lib._save_user()
        self.assertTrue(os.path.isfile(self.path),
                        "a fresh install cannot save gradients at all")
        with open(self.path, encoding="utf-8") as handle:
            names = [g["name"] for g in json.load(handle)["assets"]]
        self.assertIn("first", names)

    def test_a_fresh_install_still_seeds_the_curated_palettes(self):
        if not os.path.exists(gradient_library._def_path("sanzo_wada.json")):
            self.skipTest("curated defs unreachable ($AMAZE not resolved) "
                          "- seeding cannot be exercised here")
        lib = self._library()
        self.assertGreater(
            len(lib._user), 0,
            "a new library seeded nothing - the curated palettes are the "
            "first thing a new user sees")
        self.assertTrue(os.path.isfile(self.marker),
                        "the seed marker was not written, so the palettes "
                        "duplicate on the next launch")
        self.assertTrue(os.path.isfile(self.path),
                        "the seeded palettes never reached disk")

    def test_a_present_file_still_loads_and_saves(self):
        """Marker AND file present - every launch of a real library."""
        self._seeded_before()
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["Warm"],
                       "gradients": [{"name": "ours"}]}, handle)
        lib = self._library()
        self.assertFalse(lib._load_failed)
        self.assertEqual(["ours"], [g["name"] for g in lib._user])
        lib._user = [{"name": "edited", "type": "user"}]
        lib._save_user()
        with open(self.path, encoding="utf-8") as handle:
            names = [g["name"] for g in json.load(handle)["assets"]]
        # assertIn, not an exact list: the connector UNIONS, so a row
        # the caller simply did not mention is kept rather than
        # deleted. This test is about the save landing at all.
        self.assertIn("edited", names, "an ordinary save was refused")


class AbsentIsNotBrokenElsewhereTest(unittest.TestCase):
    """The same confusion, found in two more places while fixing these
    two. Both fail the other way round from the bugs above - they treat
    an ABSENT file as a BROKEN one - and both make a fresh library
    unusable rather than losing data, which is the failure mode a guard
    like this is most likely to ship with."""

    def test_a_first_launch_can_still_save_its_preferences(self):
        """settings.json does not exist on a new machine, and
        FileNotFoundError is an OSError - so the unreadable-settings
        handler latched _load_failed and save() refused for the session.
        The library folder picked in Preferences was never persisted and
        the next launch was in the same state."""
        from amaze.prefs import prefs as prefs_mod

        settings_dir = tempfile.mkdtemp(prefix="amaze_absent_prefs_")
        self.addCleanup(shutil.rmtree, settings_dir, ignore_errors=True)
        p = prefs_mod.Prefs()
        p.path = settings_dir
        # Blanked for the reason test_support blanks it: under hython
        # the legacy path is the LIVE install, and load() migrates from
        # it - which would both pollute this test and read real data.
        p.legacy_path = ""
        self.assertFalse(
            os.path.exists(os.path.join(settings_dir, "settings.json")),
            "premise: a first launch has no settings file")
        self.assertFalse(p.load(), "an unconfigured Amaze must report so")
        self.assertFalse(
            getattr(p, "_load_failed", False),
            "a first launch was latched as 'settings unreadable', so "
            "every preference save is refused for the session - the "
            "user can never point Amaze at a library")
        library_dir = tempfile.mkdtemp(prefix="amaze_absent_prefslib_")
        self.addCleanup(shutil.rmtree, library_dir, ignore_errors=True)
        p.dir = library_dir
        p.save()
        written = os.path.join(settings_dir, "settings.json")
        self.assertTrue(os.path.isfile(written),
                        "the first preference save never reached disk")
        with open(written, encoding="utf-8") as handle:
            stored = json.load(handle).get("directory", "")
        # expanduser + normcase on BOTH sides, rather than a substring.
        # Prefs stores the library home-collapsed ("~/..."), and on
        # Windows the temp dir IS under $HOME, so the raw path never
        # appears in the file - while on macOS tempfile lands under
        # /var/folders, outside $HOME, and the very same code stores it
        # verbatim. The substring form therefore asked "did it store
        # this SPELLING", which is not what the test means.
        self.assertEqual(
            os.path.normcase(os.path.normpath(library_dir)),
            os.path.normcase(os.path.normpath(os.path.expanduser(stored))),
            "the chosen library was not persisted")

    def test_a_genuinely_unreadable_settings_file_still_latches(self):
        """The accept path for the refusal: broken must still refuse, or
        this fix has simply removed the guard."""
        from amaze.prefs import prefs as prefs_mod

        settings_dir = tempfile.mkdtemp(prefix="amaze_absent_prefs_bad_")
        self.addCleanup(shutil.rmtree, settings_dir, ignore_errors=True)
        with open(os.path.join(settings_dir, "settings.json"), "w",
                  encoding="utf-8") as handle:
            handle.write('{"directory": "/somewhere"')      # truncated
        p = prefs_mod.Prefs()
        p.path = settings_dir
        p.legacy_path = ""
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(p.load())
        self.assertTrue(getattr(p, "_load_failed", False),
                        "an unreadable settings file no longer refuses "
                        "to be overwritten")

    def test_deleting_the_broken_file_UNLATCHES_the_session(self):
        """The "start fresh" route the refusal implies: delete the
        unreadable file mid-session. load() runs again when Preferences
        closes, and the latch is re-derived from the file on every
        read - so an ABSENT file must clear it exactly as a healthy one
        does, or save() refuses for the life of the panel and the fresh
        start can never persist. Only the success path cleared it."""
        from amaze.prefs import prefs as prefs_mod

        settings_dir = tempfile.mkdtemp(prefix="amaze_absent_prefs_gone_")
        self.addCleanup(shutil.rmtree, settings_dir, ignore_errors=True)
        target = os.path.join(settings_dir, "settings.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write('{"directory": "/somewhere"')      # truncated
        p = prefs_mod.Prefs()
        p.path = settings_dir
        p.legacy_path = ""
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(p.load())
        self.assertTrue(getattr(p, "_load_failed", False), "premise")

        if os.path.exists(target):
            os.remove(target)               # the user starts fresh
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(p.load())      # Preferences closed
        self.assertFalse(
            getattr(p, "_load_failed", False),
            "an absent settings file left the broken-file latch set")
        p.save()
        self.assertTrue(
            os.path.isfile(target),
            "the fresh start's first save never reached disk")

    def test_the_snippet_marker_is_not_written_without_its_database(self):
        """code.json's marker is its ONLY trace (no .bak on the real
        library), so a marker with no database behind it refuses the
        Code section on every future launch. database.save() reports an
        OSError to the user instead of raising, so a save held off by a
        full disk or a sync lock reaches the marker write looking
        successful."""
        from amaze.core import code_library

        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        starter = os.path.join(
            hou.getenv("AMAZE") or "", "scripts/python/amaze",
            code_library._STARTER_DEF)
        if not os.path.exists(starter):
            self.skipTest("starter snippet defs unreachable ($AMAZE not "
                          "resolved) - seeding cannot be exercised here")
        model = code_library.CodeLibrary(preferences=prefs)
        categories = code_library.CodeCategories(preferences=prefs)
        code_json = os.path.join(prefs.dir, code_library.CodeLibrary.DB_FILENAME)
        marker = os.path.join(prefs.dir, code_library._STARTER_MARKER)
        os.remove(code_json)
        if os.path.exists(marker):
            os.remove(marker)
        with patch("amaze.helpers.hostos.write_json_atomic",
                   side_effect=OSError("no space left on device")):
            with patch.object(hou, "ui", MagicMock(), create=True):
                with contextlib.redirect_stdout(io.StringIO()):
                    model.seed_starter_snippets(categories)
        self.assertFalse(
            os.path.exists(code_json),
            "premise: the save must have failed, or this test proves "
            "nothing about the marker")
        self.assertFalse(
            os.path.exists(marker),
            "the starter marker was written although code.json never "
            "reached disk - every future launch now refuses the Code "
            "section and blocks its saves, curable only by deleting a "
            "dotfile")

    def test_the_snippet_marker_is_still_written_on_a_normal_seed(self):
        """The accept path. Without the marker the starter snippets
        duplicate on every launch, which is what it exists to stop."""
        from amaze.core import code_library

        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        starter = os.path.join(
            hou.getenv("AMAZE") or "", "scripts/python/amaze",
            code_library._STARTER_DEF)
        if not os.path.exists(starter):
            self.skipTest("starter snippet defs unreachable ($AMAZE not "
                          "resolved) - seeding cannot be exercised here")
        model = code_library.CodeLibrary(preferences=prefs)
        categories = code_library.CodeCategories(preferences=prefs)
        marker = os.path.join(prefs.dir, code_library._STARTER_MARKER)
        if os.path.exists(marker):
            os.remove(marker)
        with contextlib.redirect_stdout(io.StringIO()):
            model.seed_starter_snippets(categories)
        self.assertTrue(
            os.path.isfile(marker),
            "a healthy seed did not record itself, so the starter "
            "snippets duplicate on every launch")


class ExistedBeforeTest(unittest.TestCase):
    """The shared evidence rule, on its own. Both loaders and Clean
    Library ask it the same question, and they must never disagree."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_evidence_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "cops.json")

    def test_an_empty_directory_says_nothing(self):
        self.assertEqual("", hostos.existed_before(self.path, (".marker",)))

    def test_each_trace_is_named_back(self):
        """The caller puts the trace in the refusal, so "" versus a name
        is the whole contract - a truthy-but-anonymous answer would make
        the message useless."""
        for trace in ("cops.json.bak-1", "cops.json.bak-first",
                      "cops.json.unreadable"):
            with self.subTest(trace=trace):
                full = os.path.join(self.dir, trace)
                open(full, "w").close()
                self.assertEqual(trace,
                                 hostos.existed_before(self.path))
                os.remove(full)

    def test_a_marker_counts_when_no_backup_does(self):
        open(os.path.join(self.dir, ".amaze_gradient_seed_v1"), "w").close()
        self.assertEqual("", hostos.existed_before(self.path),
                         "a marker that was not offered must not count")
        self.assertEqual(
            ".amaze_gradient_seed_v1",
            hostos.existed_before(self.path, (".amaze_gradient_seed_v1",)))

    def test_an_unrelated_backup_does_not_count(self):
        """library.json.bak-1 says nothing about cops.json, and treating
        it as evidence would refuse every secondary database on every
        real library there is."""
        open(os.path.join(self.dir, "library.json.bak-1"), "w").close()
        self.assertEqual("", hostos.existed_before(self.path))

    def test_a_directory_with_glob_characters_is_not_a_pattern(self):
        """The library directory is user-chosen. `[` in its name once
        made a glob match nothing at all - here that would fail OPEN."""
        odd = os.path.join(self.dir, "lib [v2]")
        os.makedirs(odd)
        path = os.path.join(odd, "cops.json")
        open(path + ".bak-1", "w").close()
        self.assertEqual("cops.json.bak-1", hostos.existed_before(path))


class TheLibraryFoldersAreEnsuredNotAssumed(unittest.TestCase):
    """`img/` and `mat/` were created together under a guard that only
    asked about `img/`.

    With `mat/` present and `img/` gone - a sync mid-arrival, or
    thumbnails deleted on the reasoning that they regenerate - the
    second `os.mkdir` raised `FileExistsError`, which `_build` catches
    as `OSError`, finds `library.json` healthy, and re-raises: the
    panel refuses to open on a library that is fine. The other way
    round, `mat/` was never created at all and every material save
    failed. These were the package's only two bare `os.mkdir`."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_libdirs_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    class _Prefs:
        img_dir = "img/"
        asset_dir = "mat/"

        def __init__(self, directory):
            self.dir = directory

    def _ensure(self):
        from amaze.panel.panel import MatLibPanel
        MatLibPanel.ensure_library_dirs(self._Prefs(self.dir))

    def _exists(self, name):
        return os.path.isdir(os.path.join(self.dir, name))

    def test_a_missing_img_beside_a_present_mat_does_not_raise(self):
        os.mkdir(os.path.join(self.dir, "mat"))
        self._ensure()
        self.assertTrue(self._exists("img"), "img/ was not created")
        self.assertTrue(self._exists("mat"), "mat/ was destroyed")

    def test_a_missing_mat_beside_a_present_img_is_created(self):
        os.mkdir(os.path.join(self.dir, "img"))
        self._ensure()
        self.assertTrue(
            self._exists("mat"),
            "mat/ was never created, so every material save would fail")

    def test_running_twice_changes_nothing(self):
        self._ensure()
        self._ensure()
        self.assertTrue(self._exists("img") and self._exists("mat"))

    def test_load_actually_calls_it(self):
        """Source-derived: extracting it is worthless if load() keeps
        its own pair of bare mkdirs."""
        import inspect
        from amaze.panel.panel import MatLibPanel
        source = inspect.getsource(MatLibPanel.load)
        self.assertIn("ensure_library_dirs", source,
                      "panel.load() no longer calls the folder guard")
        self.assertNotIn("os.mkdir", source,
                         "load() still creates a folder by hand")


class StarterMustNotSeedOverALibraryTest(unittest.TestCase):
    """panel.load() guarded only on library.json's absence. Any of the
    causes _refuse_absent exists for - a sync mid-arrival, a selective
    sync hole - leaves a directory FULL of assets with a momentarily
    missing index, and the 1-asset starter was seeded straight over it
    on every panel open."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_seed_guard_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _decide(self):
        """THE PANEL'S OWN decision function, not a private re-derivation
        of it. The first version copied the logic here, and sabotaging
        the panel left it green - it was testing its own copy.
        Driving full panel.load() needs a UI; calling its extracted
        decision does not, and the test below pins load() to it."""
        from amaze.panel.panel import MatLibPanel
        return not MatLibPanel.starter_would_overwrite(self.dir)

    def test_load_actually_consults_the_decision(self):
        """Source-derived: extracting the function is worthless if
        load() stops calling it."""
        import inspect
        from amaze.panel.panel import MatLibPanel
        source = inspect.getsource(MatLibPanel.load)
        self.assertIn("starter_would_overwrite", source,
                      "panel.load() no longer consults the seed guard - "
                      "the starter can overwrite a library again")

    def test_a_backup_trace_refuses_the_seed(self):
        with open(os.path.join(self.dir, "library.json.bak-first"), "w",
                  encoding="utf-8") as handle:
            handle.write("{}")
        self.assertFalse(self._decide(),
                         "a directory with a .bak-first was seeded over - "
                         "its index simply had not arrived")

    def test_populated_asset_folders_refuse_the_seed(self):
        os.makedirs(os.path.join(self.dir, "mat"))
        with open(os.path.join(self.dir, "mat", "a.mat"), "w") as handle:
            handle.write("x")
        self.assertFalse(self._decide(),
                         "a directory whose mat/ holds files was seeded "
                         "over")

    def test_a_genuinely_new_directory_still_seeds(self):
        self.assertTrue(self._decide(),
                        "a brand-new empty directory was refused - nobody "
                        "can ever create a library")

    def test_an_EMPTY_mat_folder_still_seeds(self):
        """mat/ existing but empty is what the panel itself creates a
        moment later - it is not evidence of a library."""
        os.makedirs(os.path.join(self.dir, "mat"))
        self.assertTrue(self._decide())


class UnmountedVolumesAreNotGoneTest(unittest.TestCase):
    """An unmounted NAS share answers os.path.isdir exactly like a
    deleted folder, and the pruner deleted the user's folder list every
    time the network blinked."""

    def _check(self, path):
        from amaze.panel.panel import MatLibPanel
        return MatLibPanel._volume_unreachable(path)

    @staticmethod
    def _absent_volume_path():
        """A path whose VOLUME is not present, in this platform's own
        spelling - the two branches `_volume_unreachable` documents.

        The macOS spelling was asserted unconditionally, and on Windows
        `os.path.abspath("/Volumes/...")` resolves to `C:\\Volumes\\...`
        - a perfectly mounted drive - so the test reported the guard
        broken when the guard was right.
        """
        if sys.platform == "win32":
            for letter in "ZYXWVU":
                if not os.path.exists(letter + ":\\"):
                    return letter + ":\\NoSuchShare-xyzzy\\textures"
            raise unittest.SkipTest(
                "every drive letter probed is mounted, so there is no "
                "absent volume to point at")
        return "/Volumes/NoSuchShare-xyzzy/textures"

    def test_a_path_on_an_absent_volume_is_unreachable(self):
        self.assertTrue(
            self._check(self._absent_volume_path()),
            "a path on an absent volume read as gone rather than "
            "unreachable")

    def test_a_path_on_the_boot_volume_is_not(self):
        self.assertFalse(
            self._check("/tmp/definitely-gone-xyzzy"),
            "a deleted path on a mounted volume read as unreachable - "
            "nothing would ever be pruned")

    def test_a_mounted_volume_counts_as_reachable(self):
        import glob
        mounted = [v for v in glob.glob("/Volumes/*") if os.path.isdir(v)]
        if not mounted:
            self.skipTest("no mounted volumes to test against")
        self.assertFalse(self._check(os.path.join(mounted[0], "gone.exr")))


class AStampedAssetIsNotAnOrphanTest(unittest.TestCase):
    """The sweep meant to tidy AROUND Repair was removing what Repair
    reads.

    Pass 3 calls a file unaccounted for when its id is in no database.
    An asset whose index write was REFUSED is exactly that shape - files
    on disk, no row anywhere - and it is the one case Repair exists for:
    `repair.rebuild_from_stamps` reconstructs the row from the
    `<id>.stamp.json` sidecar sitting beside the asset. So a refused
    save was safe only while the panel that remembered it stayed open,
    and the first Clean Library after a restart carried its recovery
    stamp off to quarantine.

    A file with a READABLE recovery stamp is not a leftover, it is an
    asset awaiting Repair. A damaged stamp is not protection - it cannot
    be rebuilt from, and `rebuild_from_stamps` already counts it
    `damaged` - so the two tools agree by asking one reader."""

    STAMPED = "STAMPEDASSET1"
    LEFTOVER = "LEFTOVER1"

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        self.img_dir = os.path.join(self.prefs.dir, self.prefs.img_dir)
        os.makedirs(self.img_dir, exist_ok=True)
        # A refused save leaves exactly this: the asset's files and its
        # recovery stamp, and no row in any database.
        self.files = {}
        for suffix in (".mat", ".interface", library_mod.STAMP_SUFFIX):
            path = os.path.join(self.mat_dir, self.STAMPED + suffix)
            self.files[suffix] = path
        self._write_stamp({"id": self.STAMPED, "name": "Refused Save",
                           "categories": ["Uncategorized"], "tags": []})
        for suffix in (".mat", ".interface"):
            with open(self.files[suffix], "w", encoding="utf-8") as handle:
                handle.write("asset content\n")
        self.icon = os.path.join(self.img_dir, self.STAMPED + ".png")
        with open(self.icon, "wb") as handle:
            handle.write(b"\x89PNG\r\n")
        # The control: a file with no stamp beside it, which must still
        # be swept or the sweep has simply stopped working.
        self.leftover = os.path.join(self.mat_dir, self.LEFTOVER + ".mat")
        with open(self.leftover, "w", encoding="utf-8") as handle:
            handle.write("nothing owns this\n")
        self.assertEqual(
            [], [a for a in self.model._assets
                 if str(a.mat_id) == self.STAMPED],
            "premise: no row anywhere claims the stamped asset")

    def _write_stamp(self, record):
        path = os.path.join(self.mat_dir,
                            self.STAMPED + library_mod.STAMP_SUFFIX)
        with open(path, "w", encoding="utf-8") as handle:
            if isinstance(record, str):
                handle.write(record)
            else:
                json.dump(record, handle)

    def _cleanup(self):
        with patch.object(hou, "ui", MagicMock(), create=True):
            self.model.cleanup_db(show_dialog=False)

    def test_a_stamped_unindexed_asset_survives_the_sweep(self):
        self._cleanup()
        for suffix, path in sorted(self.files.items()):
            self.assertTrue(
                os.path.exists(path),
                "Clean Library quarantined %s of an asset carrying a "
                "readable recovery stamp - the one shape Repair exists "
                "to rebuild, swept by the pass meant to tidy around it"
                % suffix)

    def test_the_icon_survives_with_it(self):
        """Repair puts the ROW back; if the sweep took the icon in the
        same run, the restored asset comes back blank and the thumbnail
        has to be re-rendered."""
        self._cleanup()
        self.assertTrue(
            os.path.exists(self.icon),
            "the stamped asset survived in mat/ but its icon was "
            "quarantined out of img/, so Repair restores a row whose "
            "thumbnail is gone")

    def test_an_unstamped_leftover_is_still_swept(self):
        """The accept path, tested as hard as the refusal: a guard that
        always fires is an outage. Without this, sparing everything
        would pass every other test in this class."""
        self._cleanup()
        self.assertFalse(
            os.path.exists(self.leftover),
            "a file with no recovery stamp beside it survived the "
            "sweep - Clean Library has stopped cleaning")

    def test_a_damaged_stamp_is_not_protection(self):
        """`rebuild_from_stamps` counts an unparseable stamp `damaged`
        and rebuilds nothing from it, so treating it as protection would
        keep files no tool can ever restore - and would make the two
        readers disagree, which is the defect this shares its reader to
        avoid."""
        self._write_stamp("{ this will not parse")
        self._cleanup()
        self.assertFalse(
            os.path.exists(self.files[".mat"]),
            "a stamp that cannot be parsed protected its asset - "
            "Repair cannot rebuild from it, so the file is kept for a "
            "recovery that can never run")

    def test_a_stamp_with_no_payload_beside_it_is_spared_too(self):
        """A snippet owns no .mat - Code keeps its text inline - so a
        lone stamp is the NORMAL shape for a whole section, not a
        leftover. Measured on the test library: 24 stamps, 7 .mat files,
        and code.json claims all 17 of the difference. Requiring a
        payload here would strip protection from every snippet at the
        moment its own list is what went missing."""
        for suffix in (".mat", ".interface"):
            os.remove(self.files[suffix])
        stamp = self.files[library_mod.STAMP_SUFFIX]
        self.assertTrue(os.path.exists(stamp), "premise: the stamp is there")
        self._cleanup()
        self.assertTrue(
            os.path.exists(stamp),
            "a lone stamp was swept - that is every Code snippet in the "
            "shared folder, and sweeping it removes the only thing "
            "Repair could rebuild the section from")

    def test_the_summary_says_what_it_kept_and_points_at_repair(self):
        """Silence here reads as a clean library while assets sit
        unlisted in the folder. The user cannot act on what the sweep
        does not say."""
        self._cleanup()
        # THE SENTENCE, not the joined summary: asserting on the whole
        # text would pass on the unrelated quarantine line, which also
        # says `your library`, and on _the_repair_route, which names
        # `Repair` for every other cause too.
        kept = [line for line in self.model.last_cleanup_summary
                if "put back" in line]
        self.assertTrue(
            kept,
            "the sweep spared files that can still be recovered and said "
            "nothing, so a user with a refused save reads a clean report "
            "and never learns Repair would put the materials back")
        self.assertIn(
            "Refused Save", kept[0],
            "the sentence does not name what it kept in the words the "
            "user has seen - the stamp carries the asset's name, so "
            "there is no reason to show them an id")
        # NO SECTION NOUN. The shared folder holds materials, nodes and
        # snippets; a file no list claims has no nameable section, so
        # calling it a material is a guess in the sentence that most has
        # to be trustworthy.
        for guess in ("material", "node", "snippet"):
            self.assertNotIn(
                guess, kept[0].lower(),
                "the sentence guesses a section for something no list "
                "claims - a lone stamp is just as likely to be a Code "
                "snippet as a material")
        self.assertNotIn(
            self.STAMPED, kept[0],
            "the sentence shows the raw id, which the user has never "
            "seen anywhere in the panel")
        route = [line for line in self.model.last_cleanup_summary
                 if "Repair tool on the Amaze shelf" in line]
        self.assertEqual(
            1, len(route),
            "the way out is missing or appears twice - one step for "
            "however many findings, per _the_repair_route")


if __name__ == "__main__":
    unittest.main(verbosity=2)
