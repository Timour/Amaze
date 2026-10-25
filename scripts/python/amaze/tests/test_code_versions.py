"""Code versions go through the material version engine: code/versions/<id>/, the same ledger."""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import code_library, repair, versions  # noqa: E402
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
        self.store = os.path.join(self.prefs.dir, "code", "versions", self.mat_id)

    def _save(self, number, code, name):
        return self.model.save_version(self.row, number, code, name, "VEX", "Examples", "")

    def _listed(self):
        return [(v["n"], v["name"]) for v in
                versions.list_versions(self.prefs, self.mat_id, versions.CODE)]

    def _on_disk(self):
        with open(os.path.join(self.prefs.dir, "code.json"), encoding="utf-8") as handle:
            rows = json.load(handle)["assets"]
        return next(row for row in rows if str(row.get("id")) == self.mat_id)


class TheStoreSitsBesideTheMaterialStore(_Case):

    def test_a_code_version_is_one_text_file_with_the_ledger(self):
        self.assertTrue(self._save(self.model.NEW_VERSION, SECOND, "helper fast"))
        names = sorted(os.listdir(self.store))
        self.assertIn(versions.LEDGER, names)
        texts = [name for name in names if name.endswith(versions.CODE_SUFFIX)]
        self.assertEqual(2, len(texts), "the original and the new version: %s" % names)
        self.assertFalse(os.path.exists(os.path.join(
            self.prefs.dir, self.prefs.asset_dir, "versions", self.mat_id)),
            "a code version landed in the material store")

    def test_the_material_store_has_not_moved(self):
        self.assertEqual(
            os.path.join(self.prefs.dir, self.prefs.asset_dir, "versions", "X1"),
            versions.versions_dir(self.prefs, "X1"))

    def test_a_text_file_the_ledger_lacks_is_adopted(self):
        """A sync can lose a ledger row; the file is still a version."""
        os.makedirs(self.store)
        with open(os.path.join(self.store, "Other-4.txt"), "w", encoding="utf-8") as handle:
            handle.write(SECOND)
        with open(os.path.join(self.store, "Other-5.mat"), "w", encoding="utf-8") as handle:
            handle.write("not code")
        self.assertEqual([(4, "Version 4")], self._listed(),
                         "the adoption read a file that is not a code version, or none")


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
                         "the list does not hold the active version")

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

    def test_a_missing_version_is_refused_and_nothing_moves(self):
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
                         "the edit no version held was lost to the switch")


class TheModelCarriesCodeVersions(_Case):

    def test_the_badge_roles_read_the_code_store(self):
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        index = self.model.index(self.row, 0)
        self.assertEqual(2, self.model.data(index, self.model.VersionsRole))
        self.assertEqual("helper fast", self.model.data(index, self.model.ActiveVersionRole))

    def test_deleting_the_snippet_takes_its_versions(self):
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        with patch.object(hou, "ui", MagicMock(), create=True):
            self.assertEqual(1, self.model.remove_rows([self.row]))
        self.assertFalse(os.path.exists(self.store), "the snippet's versions outlived it")


class TheEditorWindowKeepsVersions(unittest.TestCase):
    """D11 through the Code section's own door: Apply saves and the window stays open."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.code_model
        self.mat_id = self.model.add_snippet(FIRST, "helper", "VEX", "Examples", "")
        self.assertTrue(self.mat_id)

    def _row(self):
        return self.model.find_asset_row_by_id(self.mat_id)

    def _through_the_door(self, steps, opening=None):
        from amaze.dialogs import code_dialog

        def driving(dialog):
            steps(dialog)
            return 0

        with patch.object(code_dialog.CodeDialog, "exec", driving):
            (opening or (lambda: self.panel.sections["code"]._edit_code_row(self._row())))()

    def _listed(self):
        return [(v["n"], v["name"]) for v in
                versions.list_versions(self.panel.prefs, self.mat_id, versions.CODE)]

    def test_new_version_then_apply_keeps_the_old_one_too(self):
        def steps(dialog):
            self.assertTrue(dialog._plus.isEnabled(), "a saved snippet offers no + menu")
            dialog._new_version()
            self.assertEqual("Version 2", dialog._line_name.text())
            dialog._editor.setPlainText(THIRD)
            dialog._apply()
            self.assertEqual(2, dialog.version, "the window lost the version it saved")
        self._through_the_door(steps)
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
        self._through_the_door(steps)
        self.assertEqual(1, versions.active_version(self.panel.prefs, self.mat_id, versions.CODE))
        self.assertEqual(THIRD, self.model.version_text(self._row(), 1))
        self.assertEqual(SECOND, self.model.version_text(self._row(), 2))

    def test_the_menu_is_new_version_then_the_versions_newest_first(self):
        self.model.save_version(self._row(), self.model.NEW_VERSION, SECOND, "helper fast",
                                "VEX", "Examples", "")
        seen = {}

        def steps(dialog):
            dialog._fill_version_menu()
            seen["menu"] = [(a.text(), a.isChecked()) for a in dialog._version_menu.actions()]
        self._through_the_door(steps)
        from amaze import amazetheme
        self.assertEqual([(amazetheme.MENU_NEW_VERSION, False), ("", False),
                          ("helper fast", True), ("helper", False)], seen["menu"])

    def test_with_versions_off_apply_saves_the_snippet_alone(self):
        from amaze.core import library_policy
        self.model.save_version(self._row(), self.model.NEW_VERSION, SECOND, "helper fast",
                                "VEX", "Examples", "")
        self.assertTrue(library_policy.set_allow_overwrite(self.panel.prefs.dir, False))

        def steps(dialog):
            self.assertFalse(dialog._plus.isEnabled(), "Versions is off and the + still works")
            dialog._editor.setPlainText(THIRD)
            dialog._apply()
            self.assertFalse(dialog._plus.isEnabled(), "an Apply turned the + back on")
        self._through_the_door(steps)
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
        self._through_the_door(
            steps, lambda: self.panel._add_code_snippet("", "VEX", ""))
        added = [a for a in self.model.assets if a.name == "fresh"]
        self.assertEqual((before + 1, 1), (len(self.model.assets), len(added)),
                         "a second Apply added the snippet again")
        self.assertEqual(THIRD, added[0].code)


class TheSweepsLeaveCodeVersionsAlone(_Case):
    """Clean Library and Repair list mat/ and img/ only. ▸r/version-store"""

    def test_repair_moves_a_stray_and_leaves_the_code_store(self):
        self._save(self.model.NEW_VERSION, SECOND, "helper fast")
        stray = os.path.join(self.prefs.dir, self.prefs.asset_dir, "STRAYCODE.mat")
        with open(stray, "w", encoding="utf-8") as handle:
            handle.write("listed by nothing\n")
        before = sorted(os.listdir(self.store))
        test_support.reset_database_singletons()    # Repair refuses a library this process holds
        findings = repair.survey(self.prefs.dir, self.prefs.asset_dir, self.prefs.img_dir)
        repair.quarantine(findings)
        self.assertFalse(os.path.exists(stray), "premise: the quarantine did not run")
        self.assertEqual(before, sorted(os.listdir(self.store)))


if __name__ == "__main__":
    unittest.main()
