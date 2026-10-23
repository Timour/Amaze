"""Preferences ▸ Library: a library and its user are picked together; Apply switches both."""

import os
import shutil
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze import amazetheme, messages  # noqa: E402
from amaze.core import library_policy, users  # noqa: E402
from amaze.dialogs import prefs_dialog, user_dialog  # noqa: E402
from amaze.prefs import persistence  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _dialog(case, preferences, panel=None):
    dialog = prefs_dialog.PrefsDialog(preferences, panel=panel)
    case.addCleanup(dialog.deleteLater)
    return dialog


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


class TheUserIsPickedByTheRule(unittest.TestCase):
    """The same name as this computer's user, else the only user, else pick or create."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.library_user = users.create(self.prefs, "Plum")
        self.dialog = _dialog(self, self.prefs)

    def test_the_same_name_is_picked_in_another_library(self):
        other, made = _library_with(self, "Sage", "Plum")
        self.dialog.pick_library(other)
        self.assertEqual(made["Plum"], self.dialog.cbb_library_user.currentData())

    def test_the_only_user_is_picked_when_no_name_matches(self):
        other, made = _library_with(self, "Sage")
        self.dialog.pick_library(other)
        self.assertEqual(made["Sage"], self.dialog.cbb_library_user.currentData())

    def test_nobody_is_picked_among_several_without_a_match(self):
        other, _made = _library_with(self, "Sage", "Fern")
        self.dialog.pick_library(other)
        self.assertEqual(-1, self.dialog.cbb_library_user.currentIndex())
        self.assertFalse(self.dialog._btn_apply_library.isEnabled(),
                         "Apply runs without a user")

    def test_a_folder_with_no_library_offers_only_a_new_user(self):
        self.dialog.pick_library(_empty_folder(self))
        combo = self.dialog.cbb_library_user
        self.assertEqual([user_dialog.UserPickerDialog.CREATE],
                         [combo.itemData(row) for row in range(combo.count())])
        self.assertEqual(amazetheme.LABEL_LIBRARY_FORMAT % library_policy.LIBRARY_VERSION,
                         self.dialog._lbl_library_format.text())


class WhatApplyingDoesIsSaidFirst(unittest.TestCase):
    """The Format line and the line beside Apply, per library version and when out of reach."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.dialog = _dialog(self, self.prefs)

    def _picked_at(self, version):
        other, _made = _library_with(self, "Sage")
        library_policy.set_library_version(other, version)
        self.dialog.pick_library(other)
        return self.dialog._lbl_library_format.text(), self.dialog._lbl_library_apply.text()

    def test_an_older_library_says_apply_upgrades_it(self):
        known = library_policy.LIBRARY_VERSION
        self.assertEqual((amazetheme.LABEL_LIBRARY_FORMAT % (known - 1),
                          amazetheme.LABEL_UPGRADES_LIBRARY % known), self._picked_at(known - 1))
        self.assertTrue(self.dialog._btn_apply_library.isEnabled())
        self.assertTrue(self.dialog._lbl_library_apply.alignment()
                        & QtCore.Qt.AlignmentFlag.AlignRight,
                        "the line does not end at Apply")

    def test_a_newer_library_says_update_amaze_and_does_not_apply(self):
        newer = library_policy.LIBRARY_VERSION + 1
        self.assertEqual((amazetheme.LABEL_LIBRARY_FORMAT % newer,
                          amazetheme.LABEL_LIBRARY_TOO_NEW), self._picked_at(newer))
        self.assertFalse(self.dialog._btn_apply_library.isEnabled())
        self.assertFalse(self.dialog._btn_accept_library.isEnabled())

    def test_this_amazes_version_says_nothing(self):
        self.assertEqual(
            (amazetheme.LABEL_LIBRARY_FORMAT % library_policy.LIBRARY_VERSION, ""),
            self._picked_at(library_policy.LIBRARY_VERSION))

    def test_an_unreachable_library_says_so_and_does_not_apply(self):
        self.dialog.pick_library(_empty_folder(self).rstrip("/") + "-gone/")
        self.assertEqual(amazetheme.LABEL_LIBRARY_UNREACHABLE,
                         self.dialog._lbl_library_apply.text())
        self.assertFalse(self.dialog._btn_apply_library.isEnabled())


class WhatActsOnALibraryWaitsForIt(unittest.TestCase):
    """With another library picked, the buttons that act on a library rest until Apply."""

    def test_the_library_buttons_rest_on_a_picked_library(self):
        prefs = test_support.fixture_prefs(self)
        prefs.library_user = users.create(prefs, "Plum")
        dialog = _dialog(self, prefs)
        buttons = (dialog._btn_clean_up, dialog._btn_reload, dialog._btn_show_folder,
                   dialog._btn_edit_user, dialog._btn_delete_user)
        self.assertTrue(all(button.isEnabled() for button in buttons))
        other, _made = _library_with(self, "Plum")
        dialog.pick_library(other)
        self.assertEqual([], [button.text() for button in buttons if button.isEnabled()],
                         "these act on a library that is only picked")


class AddPutsAFolderInTheList(unittest.TestCase):

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.dialog = _dialog(self, self.prefs)
        self.said, self.chosen = [], []

    def _adding(self, folder):
        def select_file(*_args, **_kwargs):
            self.chosen.append(folder)
            return folder

        fake = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: self.said.append(text),
            selectFile=select_file)
        with mock.patch.object(hou, "ui", fake, create=True):
            self.dialog.add_library()

    def test_an_added_folder_is_picked_and_not_yet_listed(self):
        folder = _empty_folder(self)
        self._adding(folder)
        self.assertEqual(folder, self.dialog._picked_library())
        self.assertEqual([], self.said)
        self.assertNotIn(folder, self.prefs.libraries, "Add listed it before Apply")

    def test_a_full_list_asks_for_room_in_manage_first(self):
        for number in range(prefs_mod.LIBRARY_LIST_LIMIT):
            self.prefs.note_library_opened(_empty_folder(self) + "L%d/" % number)
        self._adding(_empty_folder(self))
        self.assertEqual([messages.LIBRARY_LIST_FULL % prefs_mod.LIBRARY_LIST_LIMIT], self.said)
        self.assertEqual([], self.chosen, "the chooser opened on a full list")


class NothingSwitchesBeforeApply(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.before_dir = self.panel.prefs.dir
        self.before_user = self.panel.prefs.library_user

    def test_closing_preferences_with_a_pick_switches_nothing(self):
        other, _made = _library_with(self, "Sage")
        self.panel.show_prefs()
        dialog = self.panel._prefs_dialog
        dialog.pick_library(other)
        dialog.close()
        QtWidgets.QApplication.processEvents()
        self.assertEqual(self.before_dir, self.panel.prefs.dir)
        self.assertEqual(self.before_dir, self.panel._models_dir)
        self.assertEqual(self.before_user, self.panel.prefs.library_user)

    def test_apply_switches_the_library_and_the_user_together(self):
        other, made = _library_with(self, "Sage")
        self.assertTrue(test_support.apply_library(self, self.panel, other))
        self.assertEqual(other, self.panel._models_dir)
        self.assertEqual(made["Sage"], self.panel.prefs.library_user)
        self.assertEqual(other, self.panel.prefs.libraries[0],
                         "the applied library is not first in the list")

    def test_a_library_that_stays_closed_keeps_the_user(self):
        other, _made = _library_with(self, "Sage")
        with mock.patch.object(self.panel, "open_library", self.panel._stay_closed):
            self.assertFalse(test_support.apply_library(self, self.panel, other))
        self.assertEqual(self.before_dir, self.panel.prefs.dir)
        self.assertEqual(self.before_user, self.panel.prefs.library_user,
                         "the user moved to a library that did not open")

    def test_a_new_library_is_made_with_its_user_on_apply(self):
        folder = _empty_folder(self)
        self.assertTrue(test_support.apply_library(self, self.panel, folder, user="Fern"))
        self.assertTrue(os.path.isfile(os.path.join(folder, "library.json")))
        self.assertEqual({self.panel.prefs.library_user: "Fern"},
                         users.all_users(self.panel.prefs))

    def test_accept_applies_then_closes(self):
        other, made = _library_with(self, "Sage")
        self.panel.show_prefs()
        dialog = self.panel._prefs_dialog
        dialog.pick_library(other)
        with _real_saves():
            dialog.accept_library()
        QtWidgets.QApplication.processEvents()
        self.assertIsNone(self.panel._prefs_dialog, "Accept left Preferences open")
        self.assertEqual(made["Sage"], self.panel.prefs.library_user)


class TestLibraryKeepsTheUserByName(unittest.TestCase):
    """The test library uses the user of the same name, made there when missing, and back."""

    def test_on_and_off_keep_the_name(self):
        prefs = test_support.fixture_prefs(self)
        mine = prefs.library_user = users.create(prefs, "Plum")
        folder = test_support.scratch_dir("amaze_tab_test_lib_")
        self.addCleanup(shutil.rmtree, folder, True)
        prefs.test_dir = folder
        dialog = _dialog(self, prefs)
        dialog.set_test_mode(True)
        self.assertNotEqual(mine, prefs.library_user)
        self.assertEqual("Plum", users.name_for(prefs, prefs.library_user),
                         "the test library has no Plum")
        dialog.set_test_mode(False)
        self.assertEqual(mine, prefs.library_user, "turning it off left the test user")


class SetLibraryOpensTheLibraryTab(unittest.TestCase):

    def test_set_library_shows_preferences_on_library(self):
        panel = test_support.fixture_panel(self)
        panel.set_library()
        dialog = panel._prefs_dialog
        self.addCleanup(dialog.close)
        self.assertIs(dialog.frame_page("P01"), dialog._tabs.currentWidget())


class ManageUpdatesTheList(unittest.TestCase):

    def test_a_removed_library_leaves_the_list(self):
        prefs = test_support.fixture_prefs(self)
        other, _made = _library_with(self, "Sage")
        prefs.note_library_opened(other)
        prefs.note_library_opened(prefs.real_dir)
        dialog = _dialog(self, prefs)
        self.assertEqual(2, dialog.cbb_library.count())

        class Removing:
            removed = [other]

            def __init__(self, *_a, **_k):
                pass

            def exec(self):
                prefs.remove_libraries([other])

        with mock.patch.object(prefs_dialog.library_dialog, "ManageLibrariesDialog", Removing):
            dialog.manage_libraries()
        self.assertEqual([prefs.real_dir], [dialog.cbb_library.itemData(row)
                                            for row in range(dialog.cbb_library.count())])


if __name__ == "__main__":
    unittest.main()
