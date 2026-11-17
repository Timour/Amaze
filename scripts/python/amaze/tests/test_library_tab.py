"""Preferences ▸ Library: a library and its user are picked together; Apply switches both."""

import json
import os
import shutil
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtWidgets

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
    """A user is this computer's by its id in the open library; in any other library, pick or create."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.library_user = users.create(self.prefs, "Plum")
        self.dialog = _dialog(self, self.prefs)

    def test_the_open_library_shows_this_computers_user(self):
        self.dialog.pick_library(self.prefs.dir)
        self.assertEqual(self.prefs.library_user, self.dialog.cbb_library_user.currentData())

    def test_a_user_of_the_same_name_in_another_library_is_not_picked(self):
        other, _made = _library_with(self, "Sage", "Plum")
        self.dialog.pick_library(other)
        self.assertEqual(-1, self.dialog.cbb_library_user.currentIndex(),
                         "a user was picked because the name matched")

    def test_the_only_user_of_another_library_is_not_picked(self):
        other, _made = _library_with(self, "Sage")
        self.dialog.pick_library(other)
        self.assertEqual(-1, self.dialog.cbb_library_user.currentIndex(),
                         "a user was picked because it was the only one")

    def test_nobody_is_picked_among_several_without_a_match(self):
        other, _made = _library_with(self, "Sage", "Fern")
        self.dialog.pick_library(other)
        self.assertEqual(-1, self.dialog.cbb_library_user.currentIndex())
        self.assertFalse(self.dialog._btn_apply_library.isEnabled(),
                         "Apply runs without a user")

    def test_a_folder_with_no_library_offers_only_a_new_user(self):
        self.dialog.pick_library(_empty_folder(self))
        combo = self.dialog.cbb_library_user
        self.assertEqual([user_dialog.CREATE],
                         [combo.itemData(row) for row in range(combo.count())])
        self.assertEqual("Format: v2.0", self.dialog._lbl_library_format.text())


class WhatApplyingDoesIsSaidFirst(unittest.TestCase):
    """The Format line and the line beside Apply, per library version and when out of reach."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.dialog = _dialog(self, self.prefs)

    def _picked_at(self, version):
        other, _made = _library_with(self, "Sage")
        test_support.set_library_version(other, version)
        self.dialog.pick_library(other)
        combo = self.dialog.cbb_library_user
        combo.setCurrentIndex(combo.findText("Sage"))
        return self.dialog._lbl_library_format.text(), self.dialog._lbl_library_apply.text()

    def test_an_older_library_says_apply_upgrades_it(self):
        known = library_policy.LIBRARY_VERSION
        self.assertEqual((amazetheme.LABEL_LIBRARY_FORMAT % (known - 1),
                          amazetheme.LABEL_UPGRADES_LIBRARY % "2.0"), self._picked_at(known - 1))
        self.assertTrue(self.dialog._btn_apply_library.isEnabled())
        self.assertTrue(self.dialog._lbl_library_apply.alignment()
                        & QtCore.Qt.AlignmentFlag.AlignRight,
                        "the line does not end at Apply")

    def test_a_newer_library_says_update_amaze_and_does_not_apply(self):
        newer = library_policy.LIBRARY_VERSION + 1
        self.assertEqual((amazetheme.LABEL_LIBRARY_FORMAT % "2.1",
                          amazetheme.LABEL_LIBRARY_TOO_NEW), self._picked_at(newer))
        self.assertFalse(self.dialog._btn_apply_library.isEnabled())
        self.assertFalse(self.dialog._btn_accept_library.isEnabled())

    def test_this_amazes_version_says_nothing(self):
        self.assertEqual(
            (amazetheme.LABEL_LIBRARY_FORMAT % "2.0", ""),
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
        buttons = (dialog._btn_check, dialog._btn_reload, dialog._btn_show_folder,
                   dialog._btn_edit_user, dialog._btn_delete_user)
        self.assertTrue(all(button.isEnabled() for button in buttons))
        other, _made = _library_with(self, "Plum")
        dialog.pick_library(other)
        self.assertEqual([], [button.text() for button in buttons if button.isEnabled()],
                         "these act on a library that is only picked")


class TheDatabasesRowShowsOneCheck(unittest.TestCase):
    """Grey lights until Check is pressed; then each light's colour and count, and a red Repair."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.library_user = users.create(self.prefs, "Plum")
        self.folder = test_support.scratch_dir("amaze_check_row_")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.prefs.add_file_folder(self.folder)
        self.dialog = _dialog(self, self.prefs)

    def row(self):
        dialog = self.dialog
        return ([light.fill for light in dialog._check_lights],
                [count.text() for count in dialog._check_counts],
                dialog._lbl_check_info.toolTip(), dialog._btn_check.text())

    def dead_favorite(self):
        star = os.path.join(self.folder, "shot.exr")
        with open(star, "wb") as handle:
            handle.write(b"x")
        self.prefs.add_file_favorite(star)
        os.remove(star)
        return star

    def assert_unchecked(self):
        self.assertEqual(([amazetheme.P01_LIGHT_IDLE] * 3, [""] * 3, "", "Check"), self.row())
        self.assertEqual("", self.dialog._btn_check.styleSheet())

    def test_nothing_is_checked_until_the_button_is_pressed(self):
        self.dead_favorite()
        self.assert_unchecked()
        self.assertEqual(["Errors", "Files", "Ref"],
                         [label.text() for label in self.dialog._check_heads])
        self.assertEqual("Databases", self.dialog._lbl_databases.text())

    def test_a_check_fills_the_lights_and_turns_the_button_into_a_red_repair(self):
        self.dead_favorite()
        self.dialog._btn_check.click()
        fills, counts, info, button = self.row()
        self.assertEqual(amazetheme.P01_LIGHT_CLEAN, fills[0])
        self.assertEqual("0", counts[0])
        self.assertEqual((amazetheme.P01_LIGHT_FOUND, "1"), (fills[2], counts[2]))
        self.assertNotIn(amazetheme.P01_LIGHT_IDLE, fills)
        self.assertTrue(info, "the row says nothing about what it found")
        self.assertEqual("Repair", button)
        sheet = self.dialog._btn_check.styleSheet()
        self.assertIn(amazetheme.P01_REPAIR_FILL, sheet)
        self.assertIn(amazetheme.P01_REPAIR_INK, sheet)
        self.assertIn("QPushButton:hover { background-color: %s; }" % amazetheme.P01_REPAIR_HOVER, sheet)
        self.assertIn(
            "QPushButton:pressed { background-color: %s; }" % amazetheme.P01_REPAIR_PRESSED, sheet)
        self.assertIn("border:", sheet, "Qt paints no background on a button whose rule sets no border")
        self.dialog._btn_check.resize(75, 22)
        middle = self.dialog._btn_check.grab().toImage().pixelColor(6, 11).name()
        self.assertEqual(amazetheme.P01_REPAIR_FILL, middle, "the Repair button is not drawn red")

    def test_repair_opens_the_dialog_and_checks_again_after_the_fix(self):
        star = self.dead_favorite()
        self.dialog._btn_check.click()
        asked = []

        def display(text, **kwargs):
            asked.append((text, tuple(kwargs.get("buttons") or ())))
            return list(kwargs["buttons"]).index("Fix Safe") if kwargs.get("buttons") else 0

        with mock.patch.object(hou, "ui", mock.Mock(displayMessage=display), create=True):
            self.dialog._btn_check.click()
        self.assertTrue(asked[0][0].startswith("Check Library found:\n\n"))
        self.assertIn("1 favorite is of a file that is gone.", asked[0][0])
        self.assertEqual("Fix Safe", asked[0][1][-2])
        self.assertIn("1 favorite removed.", asked[1][0])
        self.assertNotIn(star, self.prefs.file_favorites)
        fills, counts, _info, _button = self.row()
        self.assertEqual((amazetheme.P01_LIGHT_CLEAN, "0"), (fills[2], counts[2]),
                         "the row still shows what the repair fixed")

    def test_a_clean_part_is_green_and_the_button_stays_check(self):
        self.dialog._btn_check.click()
        fills, counts, _info, _button = self.row()
        self.assertEqual((amazetheme.P01_LIGHT_CLEAN, "0"), (fills[2], counts[2]))
        if amazetheme.P01_LIGHT_FOUND not in fills:
            self.assertEqual(messages.CHECK_NOTHING_TO_REPAIR, self.row()[2])
        from amaze.core import library_check, repair
        if not library_check.summary(repair.survey(self.prefs))["lines"]:
            self.assertEqual("Check", self.dialog._btn_check.text())
            self.assertEqual("", self.dialog._btn_check.styleSheet())

    def test_a_part_that_cannot_be_judged_is_amber_with_a_dash(self):
        from amaze.core import guard
        with mock.patch.object(guard.Guard, "_waiting", lambda self: True):
            self.dialog._btn_check.click()
        fills, counts, _info, button = self.row()
        self.assertEqual([amazetheme.P01_LIGHT_UNJUDGED] * 3, fills)
        self.assertEqual([amazetheme.LABEL_UNJUDGED] * 3, counts)
        self.assertEqual("Check", button)

    def test_picking_another_library_empties_the_row(self):
        self.dead_favorite()
        self.dialog._btn_check.click()
        other, _made = _library_with(self, "Plum")
        self.dialog.pick_library(other)
        self.assert_unchecked()
        self.assertFalse(self.dialog._btn_check.isEnabled())


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
        self.assertTrue(test_support.apply_library(self, self.panel, other, user="Sage"))
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
        self.assertTrue(os.path.isfile(os.path.join(folder, "DataBase.json")))
        self.assertEqual({self.panel.prefs.library_user: "Fern"},
                         users.all_users(self.panel.prefs))

    def test_accept_applies_then_closes(self):
        other, made = _library_with(self, "Sage")
        self.panel.show_prefs()
        dialog = self.panel._prefs_dialog
        dialog.pick_library(other)
        combo = dialog.cbb_library_user    # another library: its user is picked by hand
        combo.setCurrentIndex(combo.findText("Sage"))
        with _real_saves():
            dialog.accept_library()
        QtWidgets.QApplication.processEvents()
        self.assertIsNone(self.panel._prefs_dialog, "Accept left Preferences open")
        self.assertEqual(made["Sage"], self.panel.prefs.library_user)


class AStartWithoutAUserOpensNoLibrary(unittest.TestCase):
    """At start a library opens only with this computer's user; without one, the pane asks."""

    def _reopened_with(self, user):
        first = test_support.fixture_panel(self)
        settings = os.path.join(first.prefs.path, "settings.json")
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
            panel.ensure_library_user()
        return asked

    def test_with_its_user_the_library_opens_and_nothing_is_asked(self):
        panel = test_support.fixture_panel(self)
        self.assertIsNotNone(panel.material_model)
        self.assertEqual([], self._asking(panel, 1))

    def test_without_a_user_no_library_opens_and_the_pane_asks(self):
        panel = self._reopened_with("")
        self.assertIsNone(panel.material_model, "a library opened with nobody picked")
        self.assertEqual([(messages.NO_USER_PICKED, messages.BUTTONS_OPEN_PREFERENCES)],
                         self._asking(panel, 1))
        self.assertIsNone(getattr(panel, "_prefs_dialog", None), "Close opened Preferences")

    def test_open_preferences_shows_the_library_tab(self):
        panel = self._reopened_with("")
        self._asking(panel, 0)
        dialog = panel._prefs_dialog
        self.addCleanup(dialog.close)
        self.assertIs(dialog.frame_page("P01"), dialog._tabs.currentWidget())

    def test_apply_with_the_user_opens_the_library(self):
        panel = self._reopened_with("")
        self.assertTrue(test_support.apply_library(self, panel, panel.prefs.dir,
                                                   user=test_support.FIXTURE_USER_NAME))
        self.assertIsNotNone(panel.material_model, "Apply left the library closed")
        self.assertEqual(test_support.FIXTURE_USER, panel.prefs.library_user)


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
        prefs.note_library_opened(prefs.dir)
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
        self.assertEqual([prefs.dir], [dialog.cbb_library.itemData(row)
                                            for row in range(dialog.cbb_library.count())])


if __name__ == "__main__":
    unittest.main()
