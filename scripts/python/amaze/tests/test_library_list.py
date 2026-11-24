"""The list of libraries, most recent first, and Manage Libraries, which removes from it."""

import json
import os
import shutil
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

from amaze import amazetheme  # noqa: E402
from amaze.dialogs import library_dialog, prefs_window  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _folder(case, name="Studio"):
    """A real folder named `name`, spelled as `prefs.dir` spells one: with a trailing slash."""
    parent = test_support.scratch_dir("amaze_listed_")
    case.addCleanup(shutil.rmtree, parent, True)
    folder = os.path.join(parent, name)
    os.makedirs(folder)
    return test_support.posix_path(folder) + "/"


def _reloaded(preferences):
    again = prefs_mod.Prefs()
    again.path = preferences.path
    again.load()
    return again


class TheListKeepsTheMostRecentFirst(unittest.TestCase):

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.a, self.b = _folder(self, "A"), _folder(self, "B")

    def test_an_opened_library_goes_first_and_is_listed_once(self):
        for folder in (self.a, self.b, self.a):
            self.prefs.note_library_opened(folder)
        self.assertEqual([self.a, self.b], self.prefs.libraries)

    def test_a_second_spelling_is_the_same_library(self):
        self.prefs.note_library_opened(self.a)
        self.prefs.note_library_opened(self.b)
        self.prefs.note_library_opened(self.a.rstrip("/"))
        self.assertEqual([self.a, self.b], self.prefs.libraries)

    def test_opening_the_first_again_is_no_change(self):
        self.prefs.note_library_opened(self.a)
        self.assertFalse(self.prefs.note_library_opened(self.a),
                         "the list reported a change, so every open would save it")

    def test_no_library_is_dropped_from_a_long_list(self):
        folders = [_folder(self, "L%d" % n) for n in range(25)]
        for folder in folders:
            self.prefs.note_library_opened(folder)
        self.assertEqual(folders[::-1], self.prefs.libraries,
                         "a library dropped off the list by itself")

    def test_remove_takes_off_only_what_it_names(self):
        for folder in (self.a, self.b):
            self.prefs.note_library_opened(folder)
        self.assertFalse(self.prefs.remove_libraries([_folder(self, "C")]))
        self.assertTrue(self.prefs.remove_libraries([self.b]))
        self.assertEqual([self.a], self.prefs.libraries)

    def test_the_list_is_kept_by_a_save(self):
        for folder in (self.a, self.b):
            self.prefs.note_library_opened(folder)
        self.prefs.save()
        self.assertEqual([self.b, self.a], _reloaded(self.prefs).libraries)

    def test_a_junk_list_reads_as_what_it_holds_of_folders(self):
        self.prefs.save()
        path = os.path.join(self.prefs.path, "settings.json")
        for stored, wanted in (({"a": 1}, []), ("A", []),
                               ([3, None, self.a, self.a], [self.a])):
            with self.subTest(stored=stored):
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
                data["libraries"] = stored
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(data, handle)
                self.assertEqual(wanted, _reloaded(self.prefs).libraries)


class OpeningALibraryPutsItFirst(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_the_open_library_is_listed_first(self):
        self.assertEqual(self.panel.pane.prefs.dir, self.panel.pane.prefs.libraries[0])

    def test_a_switch_puts_the_new_library_first(self):
        first = self.panel.pane.prefs.dir
        other = test_support.with_fixture_user(test_support.fresh_library(self))    # opens with a user only
        self.panel.pane.prefs.dir = other
        path = os.path.join(self.panel.pane.prefs.path, "settings.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data.update(directory=other, libraries=[first])    # the fixture panel does not save
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.assertTrue(self.panel.pane.library.open_library())
        self.assertEqual([other, first], self.panel.pane.prefs.libraries[:2])


class ManageLibrariesRemovesThroughTheState(unittest.TestCase):
    """Remove from List as Preferences' state does it: off the list and saved, the open one kept."""

    def test_removed_libraries_leave_the_list_saved_and_a_removed_pick_goes_back_to_the_open_one(self):
        prefs = test_support.fixture_prefs(self)
        a, b = _folder(self, "Studio"), _folder(self, "Archive")
        gone = b.rstrip("/") + "-gone/"
        for folder in (gone, b, a, prefs.dir):
            prefs.note_library_opened(folder)
        state = prefs_window.AmazePrefsState(prefs)
        state.listLibraries()    # what the dialog asks as it opens
        model = state.libraryRows
        rows = model.rows
        self.assertEqual([prefs.dir, a, b, gone], [row["folder"] for row in rows])
        self.assertEqual([True, False, False, False], [row["isOpen"] for row in rows])
        self.assertEqual([False, False, False, True], [row["dim"] for row in rows])
        self.assertEqual("%s, %s" % (library_dialog.shown_path(gone), amazetheme.LABEL_NOT_CONNECTED),
                         rows[3]["shown"])
        self.assertEqual([False, True, True, True], [bool(
            model.flags(model.index(row, 0)) & QtCore.Qt.ItemFlag.ItemIsSelectable) for row in range(4)])
        with open(os.path.join(b, "library.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        state.setPref(prefs_window.LIBRARY, b)    # Archive picked, not applied

        # what Remove from List sends: the current row, here the open one, and the rows selected
        state.removeLibraries(model.index(0, 0), [model.index(2, 0), model.index(3, 0)])
        self.assertEqual([prefs.dir, a], prefs.libraries, "the open library left the list")
        self.assertEqual([prefs.dir, a], _reloaded(prefs).libraries, "the removal was not saved")
        self.assertEqual([prefs.dir, a], [row["folder"] for row in model.rows])
        self.assertEqual([prefs.dir, a], [row["value"] for row in state.libraryOptions])
        self.assertEqual(prefs.dir, state.getPref(prefs_window.LIBRARY), "the removed pick is shown")
        self.assertTrue(os.path.isfile(os.path.join(b, "library.json")), "the folder was changed")


if __name__ == "__main__":
    unittest.main()
