"""Preferences ▸ Library: a library and its user are picked together; Apply switches both."""

import json
import os
import shutil
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
import shiboken6
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze import amazetheme, messages  # noqa: E402
from amaze.core import users  # noqa: E402
from amaze.dialogs import prefs_window, user_dialog  # noqa: E402
from amaze.prefs import persistence  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402


LIBRARY, USER = prefs_window.LIBRARY, prefs_window.USER


def _state(preferences, pane=None):
    return prefs_window.AmazePrefsState(preferences, pane=pane)


def _library_with(case, *names):
    """A fresh library holding users called `names`; (folder, {name: uid})."""
    folder = test_support.fresh_library(case)
    holder = test_support.fixture_prefs(case)
    holder.dir = folder
    return folder, {name: users.create(holder, name) for name in names}


def _empty_folder(case):
    folder = test_support.scratch_dir("amaze_new_library_")
    case.addCleanup(shutil.rmtree, folder, True)
    return test_support.posix_path(folder) + "/"


def _real_saves():
    return mock.patch.object(prefs_mod.Prefs, "save", persistence._Persistence.save)


def _assert_on_the_library_page(case, window):
    """Preferences is open on its Library page; closed and deleted after the test."""
    case.addCleanup(test_support.close_window, window)
    root = window.rootObject()
    case.assertTrue(test_support.pump_until(
        lambda: str(root.property("currentUrl")).endswith("/LibraryPage.qml"), timeout=5),
        "Preferences is open on %s" % root.property("currentUrl"))


class TheUserIsPickedByTheRule(unittest.TestCase):
    """A user is this computer's by its id in the open library; in any other library, pick or create."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.library_user = users.create(self.prefs, "Plum")
        self.state = _state(self.prefs)

    def test_the_open_library_shows_this_computers_user(self):
        self.state.pick_library(self.prefs.dir)
        self.assertEqual(self.prefs.library_user, self.state.getPref(USER))

    def test_a_library_pick_shows_its_first_user_or_a_new_default_one(self):
        self.state.pick_library(_empty_folder(self))
        self.assertEqual(prefs_window.NEW_USER + user_dialog.DEFAULT_NAME, self.state.getPref(USER))
        other, _made = _library_with(self, "Sage", "Fern")
        self.state.pick_library(other)
        self.assertEqual("Fern", users.all_users(self.prefs, library=other)[self.state.getPref(USER)])
        self.state.apply()
        self.assertEqual(other, self.prefs.dir, "Apply did not open the picked library")


class WhatApplyingDoesIsShownBeforeApply(unittest.TestCase):
    """The Format line and the line beside Apply, per library version and when unreachable."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.state = _state(self.prefs)

    def _applies(self):
        """Apply, then whether the pick was opened rather than kept pending."""
        before = self.prefs.dir
        self.state.apply()
        return self.prefs.dir != before and not self.state.changeCount

    def test_an_unreachable_library_says_so_and_does_not_apply(self):
        self.state.pick_library(_empty_folder(self).rstrip("/") + "-gone/")
        self.assertEqual(amazetheme.LABEL_LIBRARY_UNREACHABLE, self.state.applyLine)
        self.assertFalse(self._applies())


class LibraryButtonsAreDisabledUntilApply(unittest.TestCase):
    """With another library picked, the buttons that act on a library are disabled until Apply."""

    def test_the_library_buttons_are_disabled_for_a_picked_library(self):
        prefs = test_support.fixture_prefs(self)
        prefs.library_user = users.create(prefs, "Plum")
        state = _state(prefs)
        self.assertEqual((True, True), (state.libraryOpen, state.userEditable),
                         "premise: Check, Reload, Show Folder, Rename and Delete work")
        other, _made = _library_with(self, "Plum")
        state.pick_library(other)
        self.assertEqual((False, False), (state.libraryOpen, state.userEditable),
                         "these act on a library that is only picked")


class AddPutsAFolderInTheList(unittest.TestCase):

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.state = _state(self.prefs)
        self.said, self.chosen = [], []

    def _adding(self, folder):
        def select_file(*_args, **_kwargs):
            self.chosen.append(folder)
            return folder

        fake = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: self.said.append(text),
            selectFile=select_file)
        with mock.patch.object(hou, "ui", fake, create=True):
            self.state.addLibrary()

    def test_an_added_folder_is_picked_and_not_yet_listed(self):
        folder = _empty_folder(self)
        self._adding(folder)
        self.assertEqual(folder, self.state.getPref(LIBRARY))
        self.assertEqual([], self.said)
        self.assertNotIn(folder, self.prefs.libraries, "Add listed it before Apply")

    def test_a_full_list_shows_library_list_full_and_opens_no_chooser(self):
        for number in range(prefs_mod.LIBRARY_LIST_LIMIT):
            self.prefs.note_library_opened(_empty_folder(self) + "L%d/" % number)
        self._adding(_empty_folder(self))
        self.assertEqual([messages.LIBRARY_LIST_FULL % prefs_mod.LIBRARY_LIST_LIMIT], self.said)
        self.assertEqual([], self.chosen, "the chooser opened on a full list")


class NothingSwitchesBeforeApply(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.before_dir = self.panel.pane.prefs.dir
        self.before_user = self.panel.pane.prefs.library_user

    def test_closing_preferences_with_a_pick_switches_nothing(self):
        other, _made = _library_with(self, "Sage")
        self.panel.show_prefs()
        window = self.panel._prefs_window
        window.sharedState().pick_library(other)
        test_support.close_window(window)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(self.before_dir, self.panel.pane.prefs.dir)
        self.assertEqual(self.before_dir, self.panel.pane.library.models_dir)
        self.assertEqual(self.before_user, self.panel.pane.prefs.library_user)

    def test_apply_switches_the_library_and_the_user_together(self):
        other, made = _library_with(self, "Sage")
        self.assertTrue(test_support.apply_library(self, self.panel, other, user="Sage"))
        self.assertEqual(other, self.panel.pane.library.models_dir)
        self.assertEqual(made["Sage"], self.panel.pane.prefs.library_user)
        self.assertEqual(other, self.panel.pane.prefs.libraries[0],
                         "the applied library is not first in the list")

    def test_a_library_that_stays_closed_keeps_the_user(self):
        other, _made = _library_with(self, "Sage")
        with mock.patch.object(self.panel.pane.library, "open_library", self.panel.pane.library._stay_closed):
            self.assertFalse(test_support.apply_library(self, self.panel, other))
        self.assertEqual(self.before_dir, self.panel.pane.prefs.dir)
        self.assertEqual(self.before_user, self.panel.pane.prefs.library_user,
                         "the user was switched to a library that did not open")

    def test_a_new_library_is_made_with_its_user_on_apply(self):
        folder = _empty_folder(self)
        self.assertTrue(test_support.apply_library(self, self.panel, folder, user="Fern"))
        self.assertTrue(os.path.isfile(os.path.join(folder, "DataBase.json")))
        self.assertEqual({self.panel.pane.prefs.library_user: "Fern"},
                         users.all_users(self.panel.pane.prefs))

    def test_accept_applies_then_closes(self):
        other, made = _library_with(self, "Sage")
        self.panel.show_prefs()
        window = self.panel._prefs_window
        self.addCleanup(test_support.close_window, window)
        state = window.sharedState()
        state.pick_library(other)
        test_support.pick_user(state, "Sage")    # another library: its user is picked by hand
        with _real_saves():
            state.accept()
        QtWidgets.QApplication.processEvents()
        self.assertFalse(shiboken6.isValid(window) and window.isVisible(),
                         "Accept left Preferences open")
        self.assertEqual(made["Sage"], self.panel.pane.prefs.library_user)


class AStartWithoutAUserOpensNoLibrary(unittest.TestCase):
    """At start a library opens only with this computer's user; without one, the pane asks."""

    def _reopened_with(self, user):
        first = test_support.fixture_panel(self)
        settings = os.path.join(first.pane.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data["library_user"] = user
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return test_support.reopened_panel(self)

    def _asking(self, panel, answer):
        asked = []

        def displayed(text, **kwargs):
            asked.append((text, kwargs.get("buttons")))
            return answer

        ui = mock.MagicMock()
        ui.displayMessage.side_effect = displayed
        with mock.patch.object(hou, "ui", ui, create=True):
            panel.pane.library.ensure_library_user()
        return asked

    def test_with_its_user_the_library_opens_and_nothing_is_asked(self):
        panel = test_support.fixture_panel(self)
        self.assertIsNotNone(panel.pane.material_model)
        self.assertEqual([], self._asking(panel, 1))

    def test_without_a_user_no_library_opens_and_the_pane_asks(self):
        panel = self._reopened_with("")
        self.assertIsNone(panel.pane.material_model, "a library opened with nobody picked")
        self.assertEqual([(messages.NO_USER_PICKED, messages.BUTTONS_OPEN_PREFERENCES)],
                         self._asking(panel, 1))
        self.assertIsNone(getattr(panel, "_prefs_window", None), "Close opened Preferences")

    def test_open_preferences_shows_the_library_tab(self):
        panel = self._reopened_with("")
        self._asking(panel, 0)
        _assert_on_the_library_page(self, panel._prefs_window)

    def test_apply_with_the_user_opens_the_library(self):
        panel = self._reopened_with("")
        self.assertTrue(test_support.apply_library(self, panel, panel.pane.prefs.dir,
                                                   user=test_support.FIXTURE_USER_NAME))
        self.assertIsNotNone(panel.pane.material_model, "Apply left the library closed")
        self.assertEqual(test_support.FIXTURE_USER, panel.pane.prefs.library_user)


class AskingForTheLibraryPageShowsIt(unittest.TestCase):

    def test_preferences_asked_for_on_library_show_it(self):
        """What the no-user prompt asks the host for: Preferences, open already, turns to Library."""
        panel = test_support.fixture_panel(self)
        panel.show_prefs(page="About")    # open on another page, so the switch to Library shows
        root = panel._prefs_window.rootObject()
        self.assertTrue(test_support.pump_until(
            lambda: str(root.property("currentUrl")).endswith("/AboutPage.qml"), timeout=5))
        panel.pane.ui.show_prefs(page="Library")
        _assert_on_the_library_page(self, panel._prefs_window)


if __name__ == "__main__":
    unittest.main()
