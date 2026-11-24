"""Code versions use `versions.py`, as materials do: `versions/` in the asset folder, one ledger."""

import json
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import code_library, library_files, versions  # noqa: E402
from amaze.tests import test_support  # noqa: E402

FIRST, SECOND, THIRD = "@P.y += 1;\n", "@P.y += 2;\r\n", "@P.y += 3;\n"


def _read(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


class _Case(unittest.TestCase):

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = code_library.CodeLibrary(preferences=self.prefs)
        self.assertTrue(self.model.add_asset(FIRST, "helper", "VEX", "Examples", "", False))
        self.row = len(self.model.assets) - 1
        self.mat_id = str(self.model.assets[self.row].mat_id)

    def _save(self, number, code, name):
        return self.model.save_version(self.row, number, code, name, "VEX", "Examples", "")

    def _listed(self):
        return [(v["n"], v["name"]) for v in
                versions.list_versions(self.prefs, self.mat_id, versions.CODE)]

    def _on_disk(self):
        from amaze.core import library_db
        library_db.flush()
        with open(os.path.join(self.prefs.dir, library_files.CODE), encoding="utf-8") as handle:
            return json.load(handle)["assets"][self.mat_id]


class TheEditorSavesVersions(_Case):

    def test_the_first_new_version_keeps_the_snippet_as_version_1(self):
        self.assertTrue(self._save(self.model.NEW_VERSION, SECOND, "helper fast"))
        self.assertEqual([(1, "helper"), (2, "helper fast")], self._listed())
        self.assertEqual(2, versions.active_version(self.prefs, self.mat_id, versions.CODE))
        self.assertEqual(FIRST, self.model.version_text(self.row, 1))
        self.assertEqual(SECOND, self.model.version_text(self.row, 2),
                         "the version's text lost its line endings")
        self.assertEqual(("helper fast", SECOND),
                         (self._on_disk()["name"], self._on_disk()["code"]),
                         "code.json does not hold the active version")

    def test_apply_rewrites_the_version_it_shows(self):
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        self.assertTrue(self._save(2, THIRD, "helper faster"))
        self.assertEqual([(1, "helper"), (2, "helper faster")], self._listed())
        self.assertEqual(THIRD, self.model.version_text(self.row, 2))
        self.assertEqual(FIRST, self.model.version_text(self.row, 1))

    def test_apply_on_an_older_version_makes_it_the_active_one(self):
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        self.assertTrue(self._save(1, THIRD, "helper"))
        self.assertEqual(1, versions.active_version(self.prefs, self.mat_id, versions.CODE))
        self.assertEqual(THIRD, self.model.version_text(self.row, 1))
        self.assertEqual(SECOND, self.model.version_text(self.row, 2),
                         "saving version 1 wrote over version 2")
        self.assertEqual(THIRD, self._on_disk()["code"])

    def test_saving_a_missing_version_returns_false_and_changes_nothing(self):
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        self.assertFalse(self._save(9, THIRD, "nine"))
        self.assertEqual(SECOND, self._on_disk()["code"])
        self.assertEqual([(1, "helper"), (2, "helper fast")], self._listed())


class SelectSwitchesTheSnippet(_Case):

    def test_select_puts_the_versions_text_and_name_on_the_snippet(self):
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        self.assertTrue(self.model.switch_version(self.row, 1))
        self.assertEqual(("helper", FIRST), (self._on_disk()["name"], self._on_disk()["code"]))
        self.assertEqual(1, versions.active_version(self.prefs, self.mat_id, versions.CODE))
        self.assertEqual(2, len(self._listed()), "an archived base was archived again")

    def test_an_edit_no_version_holds_is_kept_before_the_switch(self):
        """An older build edits code.json alone; switching must not lose that edit."""
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        self.model.update_asset(self.row, THIRD, "edited elsewhere", "VEX", "Examples", "")
        self.assertTrue(self.model.switch_version(self.row, 1))
        kept = [v for v in versions.list_versions(self.prefs, self.mat_id, versions.CODE)
                if self.model.version_text(self.row, v["n"]) == THIRD]
        self.assertEqual(["edited elsewhere"], [v["name"] for v in kept],
                         "the edit that no version held was lost by the switch")


class AFailedCodeJsonWriteShowsOnlyTheLibraryAlert(_Case):
    """A snippet whose code.json write fails stays in memory; only the library's alert is shown."""

    def _with_code_json_write_failing(self, act):
        from amaze.core import library_db
        with test_support.full_disk_for(os.path.join(self.prefs.dir, library_files.CODE)), \
                test_support.captured_log() as log:
            act()
            library_db.flush()
        self.assertEqual(["could not save the library"],
                         ["could not save the library" for text in log.messages("alert")
                          if "could not save the library" in text][:1],
                         "the library's own alert was not logged")
        self.assertEqual([], [text for text in log.messages("alert")
                              if "could not save the library" not in text],
                         "an alert beside the library's own was shown")
        self.assertEqual([], log.messages("refuse"), "a status line was shown beside the library's alert")
        held = library_db.document(self.prefs, library_files.CODE)
        self.assertTrue(held.dirty, "the unsaved snippet was dropped, not kept for the next save")

    def test_a_new_snippet_is_kept_for_the_next_save(self):
        self._with_code_json_write_failing(lambda: self.model.add_asset(SECOND, "probe", "VEX", "Examples", "", False))
        row = next(asset for asset in self.model.assets if asset.name == "probe")
        self.mat_id = str(row.mat_id)
        self.assertEqual(SECOND, self._on_disk()["code"], "the kept snippet was never written")

    def test_a_saved_version_is_kept_for_the_next_save(self):
        self._with_code_json_write_failing(lambda: self._save(self.model.NEW_VERSION, SECOND, "helper fast"))
        self.assertEqual("helper fast", self._on_disk()["name"], "the kept version was never written")

    def test_a_switched_version_is_kept_for_the_next_save(self):
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        self._with_code_json_write_failing(lambda: self.model.switch_version(self.row, 1))
        self.assertEqual("helper", self._on_disk()["name"], "the kept switch was never written")


class TheModelHoldsCodeVersions(_Case):

    def test_the_badge_roles_read_the_code_store(self):
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        index = self.model.index(self.row, 0)
        self.assertEqual(2, self.model.data(index, self.model.VersionsRole))
        self.assertEqual("helper fast", self.model.data(index, self.model.ActiveVersionRole))

    def test_the_badge_roles_follow_a_save_and_a_select(self):
        """Both roles are cached per id, so each method that changes versions clears that id."""
        index = self.model.index(self.row, 0)

        def shown():
            return tuple(self.model.data(index, role) for role in
                         (self.model.VersionsRole, self.model.ActiveVersionRole))

        self.assertEqual((0, ""), shown(), "premise: the roles were not read before the save")
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        self.assertEqual((2, "helper fast"), shown(), "after a save the row still read its cached roles")
        self.assertTrue(self.model.switch_version(self.row, 1))
        self.assertEqual((2, "helper"), shown(), "after a select the row still read its cached roles")


class TheEditorWindowKeepsVersions(unittest.TestCase):
    """D11 opened by the Code section's `_edit_code_row`: Apply saves and the window stays open."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.pane.code_model
        self.mat_id = self.model.add_snippet(FIRST, "helper", "VEX", "Examples", "")
        self.assertTrue(self.mat_id)

    def _row(self):
        return self.model.find_asset_row_by_id(self.mat_id)

    def _through_code_dialog(self, steps, opening=None):
        from amaze.dialogs import code_dialog

        def driving(dialog):
            steps(dialog)
            return 0

        with patch.object(code_dialog.CodeDialog, "exec", driving):
            (opening or (lambda: self.panel.pane.sections["code"]._edit_code_row(self._row())))()

    def _listed(self):
        return [(v["n"], v["name"]) for v in
                versions.list_versions(self.panel.pane.prefs, self.mat_id, versions.CODE)]

    def test_new_version_then_apply_keeps_the_old_one_too(self):
        def steps(dialog):
            self.assertTrue(dialog._plus.isEnabled(), "a saved snippet offers no + menu")
            dialog._new_version()
            self.assertEqual("Version 2", dialog._line_name.text())
            dialog._editor.setPlainText(THIRD)
            dialog._apply()
            self.assertEqual(2, dialog.version, "the window lost the version it saved")
        self._through_code_dialog(steps)
        self.assertEqual([(1, "helper"), (2, "Version 2")], self._listed())
        self.assertEqual(THIRD, self.model.assets[self._row()].code)

    def test_a_picked_version_opens_and_apply_saves_into_it(self):
        self.model.save_version(self._row(), self.model.NEW_VERSION, SECOND, "helper fast",
                                "VEX", "Examples", "")

        def steps(dialog):
            dialog._show_version(1)
            self.assertEqual((FIRST, "helper"),
                             (dialog._editor.toPlainText(), dialog._line_name.text()))
            dialog._editor.setPlainText(THIRD)
            dialog._apply()
        self._through_code_dialog(steps)
        self.assertEqual(1, versions.active_version(self.panel.pane.prefs, self.mat_id, versions.CODE))
        self.assertEqual(THIRD, self.model.version_text(self._row(), 1))
        self.assertEqual(SECOND, self.model.version_text(self._row(), 2))

    def test_the_menu_is_new_version_then_the_versions_newest_first(self):
        self.model.save_version(self._row(), self.model.NEW_VERSION, SECOND, "helper fast",
                                "VEX", "Examples", "")
        seen = {}

        def steps(dialog):
            dialog._fill_version_menu()
            seen["menu"] = [(a.text(), a.isChecked()) for a in dialog._version_menu.actions()]
        self._through_code_dialog(steps)
        from amaze import amazetheme
        self.assertEqual([(amazetheme.MENU_NEW_VERSION, False), ("", False),
                          ("helper fast", True), ("helper", False)], seen["menu"])

    def test_each_version_opens_in_its_own_tab_and_keeps_its_edits(self):
        self.model.save_version(self._row(), self.model.NEW_VERSION, THIRD, "helper fast",
                                "VEX", "Examples", "")
        seen = {}

        def steps(dialog):
            self.assertEqual(["helper fast"], dialog._tabbar.names(), "it opened on no tab")
            dialog._editor.setPlainText("// edited, not saved")
            dialog._show_version(1)
            seen["two"] = (dialog._tabbar.names(), dialog._editor.toPlainText())
            dialog._show_version(1)    # its tab is selected, no second tab opens
            dialog._select_tab(0)
            seen["back"] = (len(dialog._tabbar.names()), dialog._editor.toPlainText())
            dialog._close_tab(1)
            seen["closed"] = dialog._tabbar.names()
            dialog._close_tab(0)    # the last tab stays
            seen["last"] = dialog._tabbar.names()
        self._through_code_dialog(steps)
        self.assertEqual((["helper fast", "helper"], FIRST), seen["two"])
        self.assertEqual((2, "// edited, not saved"), seen["back"], "a tab lost its edits")
        self.assertEqual((["helper fast"], ["helper fast"]), (seen["closed"], seen["last"]))
        self.assertEqual([(1, "helper"), (2, "helper fast")], self._listed(),
                         "closing a tab removed a version")

    def test_new_version_opens_a_tab_and_apply_keeps_the_others(self):
        def steps(dialog):
            dialog._new_version()
            self.assertEqual(["helper", "Version 2"], dialog._tabbar.names())
            dialog._editor.setPlainText(THIRD)
            dialog._apply()
            dialog._select_tab(0)
            self.assertEqual(1, dialog.version, "the snippet's own tab is not version 1 now")
            self.assertEqual(FIRST, dialog._editor.toPlainText())
        self._through_code_dialog(steps)
        self.assertEqual([(1, "helper"), (2, "Version 2")], self._listed())

    def test_the_versions_badge_opens_the_window_and_select_switches(self):
        from amaze.dialogs import versions_dialog
        self.model.save_version(self._row(), self.model.NEW_VERSION, THIRD, "helper fast",
                                "VEX", "Examples", "")
        proxy = self.panel.pane.code_sorted_model
        index = next(proxy.index(r, 0) for r in range(proxy.rowCount())
                     if proxy.mapToSource(proxy.index(r, 0)).row() == self._row())
        seen = {}

        def picking(dialog):
            seen["rows"] = dialog._list.count()
            dialog.chosen = 1
            return QtWidgets.QDialog.DialogCode.Accepted

        with patch.object(versions_dialog.VersionsDialog, "exec", picking):
            self.panel.pane.sections["code"].menu_versions([index], index)
        self.assertEqual(2, seen.get("rows"), "the badge opened no window, or another asset's")
        asset = self.model.assets[self._row()]
        self.assertEqual((FIRST, "helper"), (asset.code, asset.name))

    def test_with_versions_off_apply_saves_the_snippet_alone(self):
        from amaze.core import library_settings
        self.model.save_version(self._row(), self.model.NEW_VERSION, SECOND, "helper fast",
                                "VEX", "Examples", "")
        self.assertTrue(library_settings.set_allow_overwrite(self.panel.pane.prefs, False))

        def steps(dialog):
            self.assertTrue(dialog._plus.isHidden(), "Versions is off and the + is still there")
            self.assertFalse(dialog._plus.isEnabled(), "Versions is off and the + still works")
            dialog._editor.setPlainText(THIRD)
            dialog._apply()
            self.assertFalse(dialog._plus.isEnabled(), "an Apply turned the + back on")
        self._through_code_dialog(steps)
        self.assertEqual(THIRD, self.model.assets[self._row()].code)
        self.assertEqual([(1, "helper"), (2, "helper fast")], self._listed())
        self.assertEqual(SECOND, self.model.version_text(self._row(), 2),
                         "with Versions off an Apply still wrote into a version")

    def test_a_new_snippet_is_added_once_and_then_offers_versions(self):
        before = len(self.model.assets)

        def steps(dialog):
            self.assertFalse(dialog._plus.isEnabled(), "versions offered before the snippet exists")
            dialog._line_name.setText("fresh")
            dialog._editor.setPlainText(FIRST)
            dialog._apply()
            self.assertTrue(dialog._plus.isEnabled(), "the saved snippet still offers no versions")
            dialog._editor.setPlainText(THIRD)
            dialog._apply()
        self._through_code_dialog(
            steps, lambda: self.panel.pane.saving.new_code_snippet())
        added = [a for a in self.model.assets if a.name == "fresh"]
        self.assertEqual((before + 1, 1), (len(self.model.assets), len(added)),
                         "a second Apply added the snippet again")
        self.assertEqual(THIRD, added[0].code)


if __name__ == "__main__":
    unittest.main()
