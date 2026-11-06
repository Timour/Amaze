"""Absent + evidence (.bak or seed marker) must not seed; absent alone must."""

import contextlib
import errno
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(  # THREE dirnames up = scripts/python, the DEV tree - not the install on Houdini's path
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import messages                                # noqa: E402
from amaze.core import database, debug, material          # noqa: E402
from amaze.core import gradient_library                   # noqa: E402
from amaze.core import library as library_mod             # noqa: E402
from amaze.helpers import hostos                          # noqa: E402
from amaze.tests import test_support                      # noqa: E402

SCHEMA = database.SCHEMA_VERSION  # read, never typed - a literal goes stale at the next bump and turns the fixture into a silent test of the migration (practice.md ▸ A TEST OF A DROP-ON-READ RULE MUST BEAT THE MIGRATION TO THE ROW)


class _Prefs:  # never a real Prefs: one built under hython resolves $AMAZE to the live install, and that is how a test overwrote the real settings once
    """The attributes the family model reads."""

    asset_dir = "mat/"
    img_dir = "img/"
    img_ext = ".png"
    ext = ".mat"
    thumbsize = 128
    library_user = "absent-fixture-uid"  # Colors reads the shared model surface since the rebase, so the stub carries it

    def __init__(self, directory):
        self.dir = directory.rstrip(os.sep) + os.sep  # trailing separator: the shape `Prefs.save()` forces on the real field
        self.directory = self.dir


class _NoteWatcher:
    """Records every debug.note AND lets the real one run."""

    def __init__(self, testcase):
        self.notes = []  # the STRUCTURED note - only written to the log when Debug Mode is on
        real = debug.note

        def spy(message, /, **data):
            self.notes.append((message, data))
            return real(message, **data)  # the real one still runs: its `Amaze: ...` print is all a user with Debug Mode off has to go on

        patcher = patch.object(debug, "note", spy)
        patcher.start()
        testcase.addCleanup(patcher.stop)

    @property
    def text(self) -> str:
        return "\n".join(message for message, _ in self.notes)

    def __len__(self) -> int:
        return len(self.notes)


def _stdout_of(func):
    """(return value, everything printed) - the refusal must be readable, not only logged."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = func()
    return result, buffer.getvalue()


def _until_idle(done) -> None:
    for _ in range(20):    # the zero-interval timers that wait for an idle Qt
        QtWidgets.QApplication.processEvents()
        if done():
            return


class TheUnreadableIndexDialogTest(unittest.TestCase):  # sabotage: drop `_build`'s index check and it asks mid-build
    """An unparseable library.json at panel open gets ONE dialog, never a traceback."""

    def _panel_over_broken_index(self, answer):
        """Build a panel, break its index, reopen it with hou.ui scripted to `answer`."""
        first = test_support.fixture_panel(self)
        index_path = os.path.join(first.prefs.dir, "library.json")
        first.material_model.save()  # a SAVE is what writes stamps - _StampWriter refreshes after a successful index write, never before
        test_support.settle_stamps()    # the stamps a save did not change are written on a worker
        premise = os.path.join(
            first.prefs.dir, first.prefs.asset_dir)
        mine = {str(a.mat_id) for a in first.material_model.assets}  # MATERIAL stamps only: mat/ is shared with Nodes and Code, so "does ANY stamp exist" was satisfied by the shipped Code starter alone
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
            building = list(calls)
            _until_idle(lambda: calls)
        return second, calls, index_path, building  # (panel, dialogs, index path, asked while building)

    def test_nothing_is_asked_while_the_pane_builds(self):
        panel, calls, _, building = self._panel_over_broken_index(1)
        self.assertEqual([], building,
                         "asked inside onCreateInterface, where a modal draws black")
        self.assertTrue(calls, "the offer never came once Qt was idle")

    def test_repair_reopens_the_recovered_library(self):
        panel, calls, index_path, _ = self._panel_over_broken_index(0)
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
        panel, calls, index_path, _ = self._panel_over_broken_index(1)
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
        _until_idle(lambda: False)
        self.assertIsNone(second.material_model)


def _point_settings(panel, directory) -> None:
    settings = os.path.join(panel.prefs.path, "settings.json")
    with open(settings, encoding="utf-8") as handle:
        data = json.load(handle)
    data["directory"] = directory
    with open(settings, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


class AMissingListOpensNoLibrary(unittest.TestCase):
    """A library folder with no list opens no library; a switch onto one keeps the open library."""

    def _reopened_on(self, directory):
        """A second panel built over `directory`; (panel, dialogs, dialogs shown while it built)."""
        _point_settings(test_support.fixture_panel(self), directory)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        calls = []
        ui = MagicMock()
        ui.displayMessage.side_effect = lambda message, **_kw: calls.append(str(message))
        with patch.object(hou, "ui", create=True, new=ui), \
                patch.object(debug, "_alerted", set()):
            second = test_support.reopened_panel(self)
            building = list(calls)
            _until_idle(lambda: calls)
        return second, calls, building

    def _held(self):
        held = test_support.fresh_library(self)
        os.remove(os.path.join(held, "library.json"))    # mat/ and img/ stay: it has held a library
        return held

    def test_the_root_of_a_disk_opens_no_library(self):
        panel, calls, _building = self._reopened_on(os.path.abspath(os.sep))
        self.assertIsNone(panel.material_model, "a library opened on the root of the disk")
        self.assertEqual([], calls)

    def test_a_list_that_has_not_arrived_is_said_after_the_pane_draws(self):
        held = self._held()
        panel, calls, building = self._reopened_on(held)
        self.assertEqual([], building, "said inside onCreateInterface, where a modal draws black")
        self.assertEqual([messages.STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY], calls)
        self.assertIsNone(panel.material_model)
        self.assertFalse(os.path.exists(os.path.join(held, "library.json")),
                         "a starter list was seeded over the library")

    def test_a_switch_onto_it_keeps_the_open_library(self):
        panel = test_support.fixture_panel(self)
        before = panel.prefs.dir
        _point_settings(panel, self._held())
        panel.open()    # Reload Library re-reads the settings, which now name the held folder
        self.assertEqual(before, panel.prefs.dir, "the library stayed on a folder with no list")
        self.assertEqual(before, panel._models_dir, "the open library was left")

    def test_a_pane_opened_without_its_library_still_says_it_is_ready(self):
        _point_settings(test_support.fixture_panel(self), self._held())
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        with test_support.captured_log() as log, \
                patch.object(debug, "configure", lambda *a, **k: None):    # keeps the log on
            test_support.reopened_panel(self)
        self.assertIn("panel ready", log.messages("session"),
                      "a pane that opened without its library left no sign it finished building")


class AListWithoutItsContainersStillOpensTest(unittest.TestCase):
    """`{}` parses and passes `wrong_shape`, so the load supplies what every model reads first."""

    def setUp(self):
        self.dir = test_support.fresh_library(self)
        for name in ("library.json", "cops.json"):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = _Prefs(self.dir)

    def test_every_model_over_it_builds(self):
        from amaze.core import category, cop_library
        for name, build in (
                ("Categories", category.Categories),
                ("CopCategories", cop_library.CopCategories),
                ("MaterialLibrary", lambda p: library_mod.MaterialLibrary(preferences=p)),
                ("CopLibrary", lambda p: cop_library.CopLibrary(preferences=p))):
            try:
                build(self.prefs)
            except KeyError as exc:
                self.fail("%s raised KeyError %s over a list with no containers" % (name, exc))
        for name in ("library.json", "cops.json"):
            data = database.DatabaseConnector(name)._data
            self.assertEqual((["_All"], []), (data["categories"], data["assets"]), name)


class AListThatWillNotOpenIsNotOneToRepairTest(unittest.TestCase):
    """Present but refused at OPEN: a saved copy put over it would lose a list that is fine elsewhere."""

    def setUp(self):
        self.dir = test_support.fresh_library(self)
        self.index = os.path.join(self.dir, "library.json")

    def _refused(self, error):
        return test_support.refused_at_open(self.index, error)

    def test_a_list_this_account_may_not_read_is_said_and_kept_from_repair(self):
        from amaze.actions import library as library_actions
        with self._refused(PermissionError(errno.EACCES, "Permission denied", self.index)):
            why = library_actions.index_unopenable(self.dir)
            unreadable = library_actions.index_unreadable(self.dir)
        self.assertTrue(why, "a list that will not open was answered as one that opens")
        self.assertNotIn("read-only", why,
                         "a refused READ was blamed on a read-only folder, the wrong thing to fix")
        self.assertIn(self.index, why, "the sentence does not say which file")
        self.assertFalse(unreadable, "the list was offered to Repair, which would put a copy over it")

    def test_another_refusal_says_what_the_disk_said(self):
        from amaze.actions import library as library_actions
        with self._refused(OSError(errno.EIO, "Input/output error", self.index)):
            why = library_actions.index_unopenable(self.dir)
        self.assertIn("Input/output error", why)

    def test_a_list_that_opens_or_is_not_there_answers_nothing(self):
        from amaze.actions import library as library_actions
        self.assertEqual("", library_actions.index_unopenable(self.dir))
        os.remove(self.index)
        self.assertEqual("", library_actions.index_unopenable(self.dir))
        self.assertEqual("", library_actions.index_unopenable(""))


class AListThatWillNotOpenOpensNoLibraryTest(unittest.TestCase):
    """r7 at panel open: the pane builds without the list, then says why once Qt is idle."""

    def test_the_pane_builds_closed_and_says_why(self):
        from amaze.actions import library as library_actions
        first = test_support.fixture_panel(self)
        library = first.prefs.dir
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        calls = []
        ui = MagicMock()
        ui.displayMessage.side_effect = lambda message, **_kw: calls.append(str(message))
        with test_support.refused_at_open(os.path.join(library, "library.json")), \
                patch.object(hou, "ui", create=True, new=ui):
            second = test_support.reopened_panel(self)    # the refusal used to escape the build
            building = list(calls)
            _until_idle(lambda: calls)
            why = library_actions.index_unopenable(library)
        self.assertIsNone(second.material_model, "a list that will not open was opened")
        self.assertEqual([], building, "said inside onCreateInterface, where a modal draws black")
        self.assertEqual([messages.LIBRARY_NOT_OPENED % why], calls,
                         "not the one sentence naming the list - Repair would put a copy over it")


class SecondaryDatabaseAbsenceTest(unittest.TestCase):
    """database.py load(): absent + evidence must not seed and save."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_absent_db_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "cops.json")
        test_support.reset_database_singletons()  # one connector per FILENAME, cached process-wide - a leftover answers from another test's _data and carries its _write_blocked latch
        self.addCleanup(test_support.reset_database_singletons)

    def _connector(self, filename="cops.json"):
        return database.DatabaseConnector(filename)

    def _load(self, filename="cops.json"):
        db = self._connector(filename)
        return db, db.load(self.dir + os.sep)

    def _write_bak(self):
        """The trace snapshot_before_write leaves - it can only exist because cops.json did."""
        with open(self.path + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": "COP1"}]}, handle)

    def test_an_absent_database_with_a_backup_is_not_recreated(self):  # ---- the guard FIRES ----
        self._write_bak()
        self.assertFalse(os.path.exists(self.path),
                         "premise: cops.json must be absent")
        before = sorted(os.listdir(self.dir))
        db, data = self._load()
        self.assertFalse(
            os.path.exists(self.path),
            "an empty cops.json was created over a database that a .bak "
            "beside it says was here - this is the 8-records-to-0 bug")
        self.assertEqual([], data["assets"])
        self.assertTrue(getattr(db, "_write_blocked", False),  # getattr, not attribute access: a missing latch must read as a FAILED guard with this message, not an AttributeError
                        "writes were not blocked, so the next save "
                        "recreates the file the load refused to")
        db.save()                       # the save the panel does anyway
        db.save()                       # and the second, which historically overwrote the preserved file
        self.assertEqual(before, sorted(os.listdir(self.dir)),
                         "the refusal path touched the directory")

    def test_code_json_is_guarded_by_its_seed_marker_with_no_backup(self):
        """THE TRAP: code.json's only trace is its seed marker, so a backup-only guard fails OPEN."""
        code = os.path.join(self.dir, "code.json")  # 17 records and NO .bak-* at all on the real library (measured 2026-07-29)
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

    def test_the_refusal_is_loud(self):
        """The note names the file, the trace it went on, and the way out of it."""
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
        self.assertIn("remove cops.json.bak-1 as well", said,  # the FILE to remove, not just the words "on purpose" - a mangled sentence still contained that phrase and passed; the refusal lasts as long as the trace, so without this the guard is a dead end
                      "the note does not say how to proceed if the "
                      "database was removed deliberately")
        if not hostos.is_windows():  # Windows suppresses every print on purpose (any print pops the Houdini Console over the user's scene), so there the log record above is the whole channel
            self.assertIn("cops.json", printed,
                          "nothing reached the user - only the log, "
                          "which is off unless Debug Mode is on")

    def test_a_genuinely_new_library_still_gets_its_database(self):  # ---- the guard must NOT fire ----
        """A fresh install - no file, no backup, no marker - must still seed."""
        self.assertEqual([], os.listdir(self.dir), "premise: empty dir")
        db, data = self._load()
        self.assertTrue(
            os.path.isfile(self.path),
            "a brand-new library was refused its cops.json - the guard "
            "fires always, which is an outage, not a guard")
        self.assertEqual(["_All"], data["categories"])
        self.assertFalse(getattr(db, "_write_blocked", False))
        db.set({"assets": [{"id": "NEW1"}], "categories": ["_All"],
                "tags": []})
        db.save()
        with open(self.path, encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(["NEW1"], [a["id"] for a in on_disk["assets"]])

    def test_an_existing_database_still_loads_and_saves(self):
        """Evidence AND the file present - the ordinary launch; nothing may be refused."""
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
            self.assertIn("COP1",  # reached disk is the claim, not "and nothing else did" - set() unions, so a row this caller did not mention stays
                          [a["id"] for a in json.load(handle)["assets"]],
                          "an ordinary save was refused")


def _survey(prefs):
    from amaze.core import repair
    return repair.survey(prefs.dir, prefs.asset_dir, prefs.img_dir)


def _list_entry(findings, filename):
    return next(entry for entry in findings["lists"] if entry["filename"] == filename)


class SiblingAbsenceHoldsTheMoveAsideBackTest(unittest.TestCase):
    """An absent-but-known list holds every unlisted file back, exactly as an unreadable one does."""

    ORPHAN = "ORPHANTEST1"    # absent was once read as owning nothing, and its files went

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        self.orphan = os.path.join(self.mat_dir, self.ORPHAN + ".mat")
        with open(self.orphan, "w", encoding="utf-8") as handle:
            handle.write("not owned by any index\n")
        self.cops = os.path.join(self.prefs.dir, "cops.json")
        self.assertFalse(os.path.exists(self.cops),
                         "premise: the fixture has no cops.json")

    def test_nothing_unlisted_moves_while_a_sibling_is_absent_but_known(self):
        from amaze.core import repair
        from amaze.dialogs import repair_dialog
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"assets": [{"id": self.ORPHAN}]}, handle)
        findings = _survey(self.prefs)
        self.assertEqual("absent-but-known", _list_entry(findings, "cops.json")["state"])
        self.assertFalse(findings["complete"])
        self.assertIn(self.ORPHAN + ".mat", findings["unaccounted"][self.prefs.asset_dir])
        self.assertEqual(len(findings["leftovers"]), repair.files_to_move_aside(findings),
                         "unlisted files were counted to move while cops.json had not arrived")
        with self.assertRaises(ValueError):
            repair.move_aside(findings, "unlisted")
        self.assertTrue(os.path.exists(self.orphan),
                        "a file was moved while cops.json was merely not-yet-arrived")
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("Node: there is no list for it in the library folder, though Amaze "
                      "can see there was one here before.", text,
                      "the report does not name the section it is waiting for")
        self.assertIn("run Check Library again", text)
        self.assertIn("Amaze could not check the Node list either", text)
        self.assertIn("Node: saved copies - from ", text,
                      "nothing says the trace is a saved copy that can be put back")
        self.assertNotIn("cops.json", text, "the report names the storage file, never seen")
        self.assertNotIn("not on disk", text)
        _labels, keys = repair_dialog._choices(findings, may_change=True)
        self.assertIn("restore", keys, "the way out, putting the saved copy back, is not offered")
        self.assertNotIn("quarantine", keys)

    def test_the_move_still_runs_for_a_genuinely_absent_sibling(self):
        """The accept path: a library that never had a Node list still gets its strays moved."""
        from amaze.core import repair
        self.assertEqual([], glob.glob(self.cops + ".bak-*"),
                         "premise: nothing may say cops.json was ever here")
        findings = _survey(self.prefs)
        self.assertEqual("absent", _list_entry(findings, "cops.json")["state"])
        self.assertTrue(findings["complete"])
        repair.move_aside(findings, "unlisted")
        self.assertFalse(os.path.exists(self.orphan),
                         "the move was refused though nothing says a Node list was here")


class ANodeListNotYetHereKeepsItsFilesTest(unittest.TestCase):
    """Node files sit in the shared mat/ folder, so a missing Node list holds them all back."""

    COP_ID = "COPOWNED1"    # a node setup stores its .mat and .interface in mat/ like a material

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.cops = os.path.join(self.prefs.dir, "cops.json")
        self.assertFalse(os.path.exists(self.cops),
                         "premise: the fixture has no cops.json")
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        self.owned = os.path.join(self.mat_dir, self.COP_ID + ".mat")
        self.owned_interface = os.path.join(self.mat_dir, self.COP_ID + ".interface")
        for path in (self.owned, self.owned_interface):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("owned by a node setup that has not arrived\n")

    def _seed_a_new_node_list(self):
        """A brand-new section seeds its list empty, as opening the Nodes tab does."""
        from amaze.core import cop_library
        cop_library.CopLibrary(preferences=self.prefs)
        self.assertTrue(os.path.isfile(self.cops), "premise: a new library seeds its database")
        test_support.reset_database_singletons()    # an action refuses a library this process holds

    def test_the_node_files_stay_while_the_node_list_is_absent_but_known(self):
        from amaze.core import repair
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": self.COP_ID}]}, handle)
        findings = _survey(self.prefs)
        self.assertFalse(findings["complete"])
        with self.assertRaises(ValueError):
            repair.move_aside(findings, ("unlisted", "leftovers"))
        self.assertTrue(os.path.exists(self.owned) and os.path.exists(self.owned_interface),
                        "files the absent Node list owns were moved")
        self.assertIn("Amaze could not check the Node list either",
                      "\n".join(repair.report_lines(findings)),
                      "files were spared but the user was told nothing")

    def test_a_node_list_that_reads_keeps_its_files_and_the_rest_move(self):
        """The accept path: a healthy Node list keeps its files and a stray still goes."""
        from amaze.core import repair
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"categories": ["_All"], "tags": [],
                       "assets": [{"id": self.COP_ID}]}, handle)
        genuine = os.path.join(self.mat_dir, "GENUINEORPHAN.mat")
        with open(genuine, "w", encoding="utf-8") as handle:
            handle.write("in no index at all\n")
        findings = _survey(self.prefs)
        self.assertTrue(findings["complete"])
        repair.move_aside(findings, "unlisted")
        self.assertTrue(os.path.exists(self.owned), "a file the Node list owns was moved")
        self.assertFalse(os.path.exists(genuine), "a stray was left beside a healthy Node list")

    def test_a_brand_new_node_list_still_lets_a_stray_move(self):
        """No cops.json and no trace of one: the new list is seeded and a stray still goes."""
        from amaze.core import repair
        self.assertEqual([], glob.glob(self.cops + ".bak-*"),
                         "premise: nothing may say cops.json was here")
        for path in (self.owned, self.owned_interface):
            os.remove(path)
        leftover = os.path.join(self.prefs.dir, self.prefs.img_dir, "GONEMATERIAL9.png")
        with open(leftover, "wb") as handle:
            handle.write(b"a thumbnail whose material is gone")
        self._seed_a_new_node_list()
        findings = _survey(self.prefs)
        self.assertIn("GONEMATERIAL9.png", findings["unaccounted"][self.prefs.img_dir])
        repair.move_aside(findings, "unlisted")
        self.assertFalse(os.path.exists(leftover), "a stray stayed beside a brand-new Node list")

    def test_a_brand_new_node_list_with_files_left_behind_is_asked_about(self):
        """An empty list cannot tell an unarrived node from a leftover, so the report asks."""
        from amaze.core import repair
        from amaze.dialogs import repair_dialog
        self.assertEqual([], glob.glob(self.cops + ".bak-*"),
                         "premise: nothing may say cops.json was here")
        self._seed_a_new_node_list()
        findings = _survey(self.prefs)
        self.assertEqual("empty", _list_entry(findings, "cops.json")["state"])
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("Node: the list is there and holds nothing.", text)
        self.assertIn("Amaze will not decide on its own which it is", text)
        self.assertIn(self.COP_ID + ".mat", text, "the files left behind are not named")
        _labels, keys = repair_dialog._choices(findings, may_change=True)
        self.assertIn("reattach", keys, "nothing offers to put the node files back on a list")
        for path in (self.owned, self.owned_interface):
            self.assertTrue(os.path.exists(path),
                            "%s moved before anyone chose to move it" % os.path.basename(path))


class WriteBlockBelongsToTheFileTest(unittest.TestCase):
    """A refusal must not follow the user into a different library."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_absent_switch_")  # one connector per FILENAME for the whole process, repointable at any time (panel.switch_model_data -> library.reload_with_path -> db.reload_with_path); that reset _data and not _write_blocked, so a hiccup in A left healthy B silently unsaveable
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
        """Clearing the latch must not weaken it: the refusal is re-derived from disk, not remembered."""
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
    """A dropped save has to be audible."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_absent_quiet_")  # save() reported the refusal with debug.event, which is Debug-Mode gated and never prints; load() can now latch _write_blocked from a sync hiccup at panel open, so this is the ordinary path
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
        first = len(watcher)    # said once: save() runs on ordinary sidebar use
        db.save()
        db.save()
        self.assertEqual(first, len(watcher),
                         "every save repeated the whole refusal")

    def test_an_ordinary_save_says_nothing(self):
        """The accept path for a MESSAGE: a healthy library must not narrate its saves."""
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
    """database.py's own copy of the section labels must never drift from the panel's."""

    def test_every_label_matches_the_one_source(self):  # core must not import the UI package, hence the copy; a copy that can drift silently is worse than the coupling it avoids
        from amaze.core import section_list
        labels = dict(section_list.SECTIONS)
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

    def test_a_side_table_is_named_by_its_declaration_and_an_unknown_file_by_itself(self):
        """Side-table alerts send the user to Repair by name; a file with none keeps its filename."""
        self.assertEqual("policy.json", database.section_name("policy.json"))
        self.assertEqual("Comments (notes.json)",
                         database.section_name("notes.json"))
        self.assertEqual("Tile icons (icons.json)",
                         database.section_name("icons.json"))
        self.assertEqual("comments", database.section_noun("notes.json", 2))
        self.assertEqual(
            ("Tile icons", "user", "policy.json", "saved thing"),
            (database.section_label("icons.json"),
             database.section_noun("users.json", 1),
             database.section_label("policy.json"),
             database.section_noun("policy.json", 1)))


class GradientAbsenceTest(unittest.TestCase):
    """gradients.json absent + its SEED MARKER alone must refuse, with no `.bak` anywhere."""

    def setUp(self):  # every test here asserts no `.bak` first: the real library's gradients.json has none, so a backup-leaning guard passes its own tests and leaves the bug where it was
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = tempfile.mkdtemp(prefix="amaze_absent_grad_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        self.marker = os.path.join(
            self.dir, gradient_library.GradientLibrary._SEED_MARKER)

    def _seeded_before(self):
        """A library that HAS been seeded - the marker is written only after a successful save."""
        with open(self.marker, "w", encoding="utf-8") as handle:
            handle.write("seeded 388 curated palettes\n")

    def _assert_no_backup(self):
        self.assertEqual(
            [], glob.glob(self.path + ".bak-*"),
            "premise: this test only proves anything with NO backup "
            "present - the real library's gradients.json has none")

    def _library(self):
        return gradient_library.GradientLibrary(
            preferences=_Prefs(self.dir))

    def _names(self, lib):
        return [(lib.entry(row) or {}).get("name")
                for row in range(lib.rowCount())]

    def _seed(self, lib):
        lib.seed_curated_palettes(gradient_library.GradientCategories(
            preferences=_Prefs(self.dir)))

    def test_the_seed_marker_alone_stops_the_empty_load(self):  # ---- the guard FIRES ----
        self._seeded_before()
        self._assert_no_backup()
        self.assertFalse(os.path.exists(self.path),
                         "premise: gradients.json must be absent")
        before = sorted(os.listdir(self.dir))
        lib = self._library()
        self.assertTrue(
            lib._load_failed,
            "the absent file was read as an empty library - _load_failed "
            "stayed False, so the next save serialises 0 gradients over "
            "388")
        lib.add_user_gradient("mine", "Warm", {"values": [], "keys": []})  # the SAVE after the load was the bug
        lib.save()
        self.assertFalse(
            os.path.exists(self.path),
            "a 39-byte gradients.json was written where 290KB belongs")
        self.assertEqual(before, sorted(os.listdir(self.dir)),
                         "the refusal path touched the directory")

    def test_the_curated_palettes_are_not_reseeded_over_it(self):
        """A seed refused mid-save must burn neither the palettes nor the permanent marker."""
        if not os.path.exists(gradient_library._def_path("sanzo_wada.json")):
            self.skipTest("curated defs unreachable ($AMAZE not resolved) "
                          "- seeding cannot be exercised here")
        with open(self.path + ".bak-1", "w", encoding="utf-8") as handle:  # driven from .bak evidence deliberately: with the marker present the seed returns on the marker check and this passes without the latch being consulted at all
            json.dump({"version": SCHEMA, "categories": [],
                       "assets": []}, handle)
        self.assertFalse(os.path.exists(self.marker),
                         "premise: no marker, or the seed never runs and "
                         "this test proves nothing")
        lib = self._library()
        self._seed(lib)
        self.assertEqual([], self._names(lib),
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
        self.assertIn(self.path, said,  # ONE text, printed AND recorded: on Windows note() suppresses the print, so the record must carry the actionable half too - the two used to differ and the log kept only "saving disabled"
                      "the record does not say where the file belongs")
        self.assertIn(
            "remove " + gradient_library.GradientLibrary._SEED_MARKER
            + " as well", said,
            "the record does not say how to proceed if gradients.json "
            "was removed deliberately - the refusal lasts as long as the "
            "marker does, so this is the only way out of it")
        if not hostos.is_windows():  # same guard as the database refusal test - the asymmetry was real: one test asserted a print the other platform never makes
            self.assertIn("gradients.json", printed,
                          "nothing reached the user - the print is the "
                          "channel a user without Debug Mode has")
            self.assertIn("restart", printed.lower(),
                          "the message does not say what to do about it")

    def test_a_backup_alone_also_fires_it(self):
        """The other trace still counts: hostos writes a .bak the moment it saves twice differently."""
        with open(self.path + ".bak-1", "w", encoding="utf-8") as handle:
            json.dump({"version": SCHEMA, "categories": [],
                       "assets": []}, handle)
        self.assertFalse(os.path.exists(self.marker),
                         "premise: no marker - the .bak is doing the work")
        lib = self._library()
        self.assertTrue(lib._load_failed)
        self.assertFalse(os.path.exists(self.path))

    def test_a_fresh_install_still_saves(self):  # ---- the guard must NOT fire ----
        """A first run - no file, no marker, no backup - must still be able to save gradients."""
        self.assertEqual([], os.listdir(self.dir), "premise: empty dir")
        lib = self._library()
        self.assertFalse(
            lib._load_failed,
            "a brand-new library was latched as unreadable - the guard "
            "fires always, which is an outage, not a guard")
        lib.add_user_gradient("first", "", {"values": [], "keys": []})
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
        self._seed(lib)
        self.assertGreater(
            lib.rowCount(), 0,
            "a new library seeded nothing - the curated palettes are the "
            "first thing a new user sees")
        self.assertTrue(os.path.isfile(self.marker),
                        "the seed marker was not written, so the palettes "
                        "duplicate on the next launch")
        self.assertTrue(os.path.isfile(self.path),
                        "the seeded palettes never reached disk")

    def test_a_present_file_still_loads_and_saves(self):
        """Marker AND file present - every launch of a real library, and nothing may be refused."""
        self._seeded_before()
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"version": SCHEMA, "categories": ["Warm"],
                       "assets": [{"name": "ours", "id": "oursid"}]}, handle)
        lib = self._library()
        self.assertFalse(lib._load_failed)
        self.assertEqual(["ours"], self._names(lib))
        lib.add_user_gradient("edited", "", {"values": [], "keys": []})
        with open(self.path, encoding="utf-8") as handle:
            names = [g["name"] for g in json.load(handle)["assets"]]
        self.assertIn("edited", names, "an ordinary save was refused")  # assertIn, not an exact list: the connector UNIONS, so a row the caller did not mention is kept - this is about the save landing at all


class AbsentIsNotBrokenElsewhereTest(unittest.TestCase):
    """An ABSENT file must not be latched as a BROKEN one - the failure mode this guard ships with."""

    def test_a_first_launch_can_still_save_its_preferences(self):
        """A first launch with no settings.json must still persist the library folder it picks."""
        from amaze.prefs import prefs as prefs_mod  # FileNotFoundError IS an OSError, so the unreadable-settings handler latched _load_failed and save() refused for the whole session

        settings_dir = tempfile.mkdtemp(prefix="amaze_absent_prefs_")
        self.addCleanup(shutil.rmtree, settings_dir, ignore_errors=True)
        p = prefs_mod.Prefs()
        p.path = settings_dir
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
        self.assertEqual(  # expanduser + normcase on BOTH sides, never a substring: Prefs stores the library home-collapsed ("~/..."), and on Windows the temp dir IS under $HOME so the raw path never appears, while on macOS tempfile lands under /var/folders outside $HOME and the same code stores it verbatim
            os.path.normcase(os.path.normpath(library_dir)),
            os.path.normcase(os.path.normpath(os.path.expanduser(stored))),
            "the chosen library was not persisted")

    def test_deleting_the_broken_file_UNLATCHES_the_session(self):
        """Deleting the unreadable file mid-session must clear the latch, as a healthy read does."""
        from amaze.prefs import prefs as prefs_mod  # load() runs again when Preferences closes and re-derives the latch on every read; only the SUCCESS path used to clear it, so the fresh start could never persist

        settings_dir = tempfile.mkdtemp(prefix="amaze_absent_prefs_gone_")
        self.addCleanup(shutil.rmtree, settings_dir, ignore_errors=True)
        target = os.path.join(settings_dir, "settings.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write('{"directory": "/somewhere"')      # truncated
        p = prefs_mod.Prefs()
        p.path = settings_dir
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(p.load())
        self.assertTrue(getattr(p, "_load_failed", False),
                        "an unreadable settings file no longer refuses "
                        "to be overwritten")

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
        """A seed marker must never outlive a failed save - it is code.json's ONLY trace."""
        from amaze.core import code_library  # database.save() reports an OSError to the user instead of raising, so a save held off by a full disk or a sync lock reaches the marker write looking successful

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
        """The accept path: without the marker the starter snippets duplicate on every launch."""
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
    """The shared evidence rule: loaders and Clean Library ask it the same question and must agree."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_evidence_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "cops.json")

    def test_each_trace_is_named_back_and_nothing_else_counts(self):
        """The caller puts the trace in the refusal, so "" versus a NAME is the whole contract."""
        marker = ".amaze_gradient_seed_v1"
        for present, markers, expected in (
                ((), (".marker",), ""),                       # an empty directory says nothing
                (("cops.json.bak-1",), (), "cops.json.bak-1"),
                (("cops.json.bak-first",), (), "cops.json.bak-first"),
                (("cops.json.unreadable",), (), "cops.json.unreadable"),
                ((marker,), (), ""),                          # a marker counts only when offered
                ((marker,), (marker,), marker),
                (("library.json.bak-1",), (), "")):           # no evidence about cops.json
            with self.subTest(present=present, markers=markers):
                for name in present:
                    open(os.path.join(self.dir, name), "w").close()
                try:
                    self.assertEqual(expected,
                                     hostos.existed_before(self.path, markers))
                finally:
                    for name in present:
                        os.remove(os.path.join(self.dir, name))

    def test_a_directory_with_glob_characters_is_not_a_pattern(self):
        """A user-chosen directory name must not be read as a glob pattern - that fails OPEN."""
        odd = os.path.join(self.dir, "lib [v2]")  # WORLD FACT: `[` makes a glob pattern that matches nothing at all, so the evidence check silently found none
        os.makedirs(odd)
        path = os.path.join(odd, "cops.json")
        open(path + ".bak-1", "w").close()
        self.assertEqual("cops.json.bak-1", hostos.existed_before(path))


class TheLibraryFoldersAreEnsuredNotAssumed(unittest.TestCase):
    """`img/` and `mat/` are each ENSURED, never assumed from the presence of the other."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_libdirs_")  # one guard asked only about img/: with mat/ present the second bare os.mkdir raised FileExistsError, which _build catches as OSError, finds library.json healthy and re-raises - the panel refuses to open on a library that is fine
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    class _Prefs:
        img_dir = "img/"
        asset_dir = "mat/"

        def __init__(self, directory):
            self.dir = directory

    def _ensure(self):
        from amaze.actions import library as library_actions
        library_actions.ensure_library_dirs(self._Prefs(self.dir))

    def _exists(self, name):
        return os.path.isdir(os.path.join(self.dir, name))

    def test_each_folder_is_ensured_whichever_is_already_there(self):
        for present in (("mat",), ("img",), ()):
            with self.subTest(present=present):
                for name in ("img", "mat"):
                    if self._exists(name):
                        os.rmdir(os.path.join(self.dir, name))
                for name in present:
                    os.mkdir(os.path.join(self.dir, name))
                self._ensure()
                self._ensure()    # a second run changes nothing
                self.assertTrue(self._exists("img"), "img/ was not created")
                self.assertTrue(
                    self._exists("mat"),
                    "mat/ was never created, so every material save would fail")


class StarterMustNotSeedOverALibraryTest(unittest.TestCase):
    """A momentarily missing library.json must not let the 1-asset starter seed over a full library."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_seed_guard_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _decide(self):
        """THE OPENING'S OWN decision function, never a private re-derivation of it."""
        from amaze.actions import library as library_actions  # a copy here stayed green under sabotage
        return not library_actions.starter_would_overwrite(self.dir)

    def test_load_actually_consults_the_decision(self):
        """Source-derived: extracting the function is worthless if prepare() stops calling it."""
        import inspect
        from amaze.actions import library as library_actions
        source = inspect.getsource(library_actions.prepare)
        self.assertIn("starter_would_overwrite", source,
                      "prepare() no longer consults the seed guard - "
                      "the starter can overwrite a library again")
        self.assertIn("ensure_library_dirs", source,
                      "prepare() no longer calls the folder guard")

    def test_only_a_library_with_no_trace_and_no_files_is_seeded(self):
        """An empty mat/ is what the panel itself creates a moment later, not evidence of a library."""
        root = self.dir
        for case, files, seeds in (
                ("a .bak-first: its index had not arrived", ("library.json.bak-first",), False),
                ("a mat/ holding files", ("mat/a.mat",), False),
                ("a brand-new empty directory", (), True),
                ("an EMPTY mat/", ("mat/",), True)):
            with self.subTest(case):
                self.dir = tempfile.mkdtemp(dir=root)
                for name in files:
                    path = os.path.join(self.dir, name)
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    if not name.endswith("/"):
                        with open(path, "w", encoding="utf-8") as handle:
                            handle.write("{}")
                self.assertEqual(seeds, self._decide(),
                                 "the starter seed decided wrongly over %s" % case)


class UnmountedVolumesAreNotGoneTest(unittest.TestCase):
    """An unreachable volume is not a deleted folder - the pruner must not act on a blinking network."""

    def _check(self, path):
        return hostos.volume_unreachable(path)  # an unmounted share answers isdir like a deleted folder

    @staticmethod
    def _absent_volume_path():
        """A path whose VOLUME is absent, in this platform's own spelling."""
        if sys.platform == "win32":  # WORLD FACT: on Windows os.path.abspath("/Volumes/...") resolves to C:\\Volumes\\... - a perfectly mounted drive - so the macOS spelling reported the guard broken when it was right
            for letter in "ZYXWVU":
                if not os.path.exists(letter + ":\\"):
                    return letter + ":\\NoSuchShare-xyzzy\\textures"
            raise unittest.SkipTest(
                "every drive letter probed is mounted, so there is no "
                "absent volume to point at")
        return "/Volumes/NoSuchShare-xyzzy/textures"

    def test_another_platforms_pointer_is_left_alone(self):
        """Neither platform can judge the other's spelling, and a guess either way drops the row."""
        for windows, path in ((True, "/Volumes/StudioShare/textures"),    # abspath grafts it onto C:
                              (False, "C:\\StudioShare\\textures")):
            with self.subTest(windows=windows):
                with patch.object(hostos, "is_windows", lambda w=windows: w):
                    self.assertTrue(
                        self._check(path),
                        "a pointer written on another platform was judged "
                        "here and unregistered")

    UNC = ("//server/share/textures", "\\\\server\\share\\textures")

    def test_a_UNC_share_is_native_on_WINDOWS_and_left_alone_on_POSIX(self):
        """Windows reads a UNC path as native, so Clean can prune a folder deleted from a share."""
        for path in self.UNC:
            with self.subTest(path=path):
                with patch.object(hostos, "is_windows", lambda: True):
                    self.assertFalse(
                        hostos.foreign_path(path),
                        "%s was read as another platform's path on Windows, "
                        "so Clean keeps it forever as unmounted" % path)
                with patch.object(hostos, "is_windows", lambda: False):
                    self.assertTrue(
                        self._check(path),
                        "%s, written on Windows, was judged on this platform "
                        "and would be unregistered" % path)

    def test_only_a_path_on_an_absent_volume_is_unreachable(self):
        self.assertFalse(
            self._check(os.path.join(tempfile.gettempdir(), "definitely-gone-xyzzy")),    # native: `/tmp` on Windows is another platform's spelling, left alone by design
            "a deleted path on a mounted volume read as unreachable - "
            "nothing would ever be pruned")
        mounted = [v for v in glob.glob("/Volumes/*") if os.path.isdir(v)]
        if mounted:
            self.assertFalse(self._check(os.path.join(mounted[0], "gone.exr")),
                             "a path on a mounted volume read as unreachable")
        self.assertTrue(
            self._check(self._absent_volume_path()),
            "a path on an absent volume read as gone rather than "
            "unreachable")


class AStampedAssetIsNotAStrayTest(unittest.TestCase):
    """A pair with a READABLE recovery stamp is not a leftover: it is an asset that can be put back."""

    STAMPED = "STAMPEDASSET1"    # a refused index write leaves this shape: files and stamp, no row
    LEFTOVER = "LEFTOVER1"    # the control: no stamp, so it must still move

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        self.img_dir = os.path.join(self.prefs.dir, self.prefs.img_dir)
        os.makedirs(self.img_dir, exist_ok=True)
        self.files = {}
        for suffix in (".mat", ".interface", material.STAMP_SUFFIX):
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
        self.leftover = os.path.join(self.mat_dir, self.LEFTOVER + ".mat")
        with open(self.leftover, "w", encoding="utf-8") as handle:
            handle.write("nothing owns this\n")
        self.assertNotIn(self.STAMPED, _survey(self.prefs)["ids"],
                         "premise: no row anywhere claims the stamped asset")

    def _write_stamp(self, record):
        path = os.path.join(self.mat_dir, self.STAMPED + material.STAMP_SUFFIX)
        with open(path, "w", encoding="utf-8") as handle:
            if isinstance(record, str):
                handle.write(record)
            else:
                json.dump(record, handle)

    def _move_aside(self):
        from amaze.core import repair
        findings = _survey(self.prefs)
        self.assertTrue(findings["complete"], "premise: every list reads")
        repair.move_aside(findings, "unlisted")
        return findings

    def test_a_stamped_unlisted_asset_survives_the_move(self):
        from amaze.core import repair
        findings = self._move_aside()
        self.assertEqual([self.STAMPED], repair.stamped_unlisted(findings))
        for suffix, path in sorted(self.files.items()):
            self.assertTrue(os.path.exists(path),
                            "Move Aside took the %s of an asset with a readable stamp" % suffix)
        self.assertTrue(os.path.exists(self.icon),
                        "the stamped asset stayed but its thumbnail was moved out of img/")
        self.assertFalse(os.path.exists(self.leftover),
                         "a file with no stamp beside it stayed: Move Aside has stopped moving")
        said = [part for part in " ".join(repair.report_lines(findings)).split(". ")
                if "can still be put back" in part]
        self.assertEqual(1, len(said), "the spared files are not named once: %s" % said)
        for guess in ("material", "node", "snippet"):    # no list claims it: a section is a guess
            self.assertNotIn(guess, said[0].lower(),
                             "the sentence guesses a section for something no list claims")
        self.assertNotIn(self.STAMPED, said[0], "the sentence shows the raw id")

    def test_a_damaged_stamp_is_not_protection(self):
        """An unparseable stamp protects nothing: nothing can be put back from it."""
        self._write_stamp("{ this will not parse")
        self._move_aside()
        self.assertFalse(os.path.exists(self.files[".mat"]),
                         "a stamp that cannot be parsed kept its asset for a put back that never runs")

    def test_a_stamp_with_no_payload_beside_it_is_spared_too(self):
        """A lone stamp is the normal shape for a Code snippet or a palette, not a leftover."""
        for suffix in (".mat", ".interface"):
            os.remove(self.files[suffix])    # Code and Colors keep their content inline
        stamp = self.files[material.STAMP_SUFFIX]
        self.assertTrue(os.path.exists(stamp), "premise: the stamp is there")
        self._move_aside()
        self.assertTrue(os.path.exists(stamp),
                        "a lone readable stamp was moved aside, the only record of a snippet")


class TheFourListsAreEnumeratedOnce(unittest.TestCase):
    """`database.DATABASES` is the ONE enumeration of the four database filenames."""

    MAY_ENUMERATE = {  # every module that may spell all four in one literal - a list, not a count, because the exemption is what has to be argued for; `tools/library-audit.py` is the deliberate duplicate outside the package, since it must run where Houdini will not start
        os.path.join("core", "database.py"),
        os.path.join("core", "library_files.py"),    # imports nothing: the audit tool loads it by path
    }

    def _package_sources(self):
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for root, _dirs, files in os.walk(package):
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(root, name)
                    yield os.path.relpath(path, package), path

    def test_the_table_names_every_database_that_ships(self):
        """Derived from the LIBRARY CLASSES - the one place a filename is a declaration, not a repetition."""
        from amaze.core import code_library, cop_library  # a fifth section arriving with its own list must not leave the table quietly short, which is exactly how gradients.json went missing from _EXISTED_MARKERS and made Repair and the colours loader disagree about the same file

        declared = {
            library_mod.MaterialLibrary.DB_FILENAME,
            cop_library.CopLibrary.DB_FILENAME,
            code_library.CodeLibrary.DB_FILENAME,
            gradient_library.GradientLibrary.DB_FILENAME,
        }
        self.assertEqual(
            declared, set(database.DATABASES),
            "a library class declares a database the one table does "
            "not name, or the other way about")

    def test_nothing_else_writes_the_four_out_by_hand(self):
        """STRUCTURE, not prose: an AST walk for any literal collection naming all four."""
        import ast  # so a docstring mentioning them is not a finding, and a list built in another shape still is

        wanted = set(database.DATABASES)
        offenders = []
        for relative, path in self._package_sources():
            if relative in self.MAY_ENUMERATE:
                continue
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                    strings = {el.value for el in node.elts
                               if isinstance(el, ast.Constant)
                               and isinstance(el.value, str)}
                elif isinstance(node, ast.Dict):
                    strings = {key.value for key in node.keys
                               if isinstance(key, ast.Constant)
                               and isinstance(key.value, str)}
                else:
                    continue
                if wanted <= strings:
                    offenders.append("%s:%d" % (relative, node.lineno))
        self.assertEqual(
            [], sorted(offenders),
            "the four databases are written out by hand at %s - "
            "database.DATABASES is the one enumeration"
            % ", ".join(sorted(offenders)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
