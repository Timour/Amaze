"""Two Amaze panels open at once must not damage the library. ▸p/one-model-set"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from PySide6 import QtWidgets

from amaze.core import category, model_registry
from amaze.helpers import hostos
from amaze.prefs import persistence, prefs
from amaze.tests import test_support

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])    # ▸p/first-app-picks-the-platform


def _document(panel, filename="materials.json"):
    """The section database as it is ON DISK right now, read without the app."""
    with open(os.path.join(panel.pane.prefs.dir, filename),
              encoding="utf-8-sig") as handle:
        return json.load(handle)


def _rows(panel, filename="materials.json"):
    """Disk rows by id as a string, the form `Material.mat_id` uses."""
    return {str(key): row for key, row in _document(panel, filename)["assets"].items()}


def _second_panel(testcase):
    """A second panel on the fixture panel's settings, as two open pane tabs are."""
    return test_support.reopened_panel(testcase)


class TwoPanelsShareOneLibraryTest(unittest.TestCase):
    """One process, two panels, one library: neither may lose the other's work."""

    def setUp(self):
        self.a = test_support.fixture_panel(self)
        self.b = _second_panel(self)

    def _named_asset(self, panel):
        """A row with a real name - the fixture's row 0 is an id -1 sentinel."""
        model = panel.pane.material_model
        for row in range(model.rowCount()):
            if model._assets[row].name:
                return model.index(row, 0), model
        self.fail("premise: the fixture library holds no named asset")

    def test_a_rename_is_kept_after_the_other_panels_save(self):
        index, model = self._named_asset(self.a)
        asset = model._assets[index.row()]
        target = asset.mat_id
        model.set_assetdata(index, "renamed by panel A",
                            ", ".join(asset.categories),
                            ", ".join(asset.tags), None)

        self.assertTrue(self.b.pane.material_model.save(),
                        "premise: the second panel's save failed")

        self.assertEqual(
            "renamed by panel A", _rows(self.a)[target].get("name"),
            "the second panel's save reverted the first panel's rename")

    def test_a_delete_is_not_restored_by_the_other_panels_save(self):
        index, model = self._named_asset(self.a)
        target = model._assets[index.row()].mat_id
        model.remove_asset(index)
        self.assertNotIn(target, _rows(self.a),
                         "premise: the delete was never written to disk")

        self.assertTrue(self.b.pane.material_model.save(),
                        "premise: the second panel's save failed")

        self.assertNotIn(
            target, _rows(self.a),
            "the second panel's save brought the deleted asset back, and its "
            "files are gone - a row pointing at nothing")

    def test_both_panels_read_one_set_of_rows(self):
        self.assertIs(
            self.a.pane.material_model, self.b.pane.material_model,
            "each panel built its own library model over the same file, so "
            "one panel's save writes the other's copy of the rows")

    def test_h8_a_pending_delete_is_cleared_by_the_save_that_marked_it(self):
        """One model per library, so no second model's save can clear the mark."""
        index, model = self._named_asset(self.a)
        target = model._assets[index.row()].mat_id
        model._unlist_row(index.row())
        self.assertIn(str(target), model._removed_ids, "premise: the mark was not made")

        self.assertTrue(self.b.pane.material_model.save(),
                        "the other panel's save failed")

        self.assertNotIn(
            target, _rows(self.a),
            "the delete mark was cleared by a save that did not set it, so "
            "the row survived on disk")

    def test_h9_a_switch_and_back_leaves_both_panels_saving(self):
        first = self.a.pane.prefs.dir
        other = test_support.fresh_library(self)

        self.a.pane.prefs.dir = other
        self.a.pane.library.switch_all_models()
        self.a.pane.prefs.dir = first
        self.a.pane.library.switch_all_models()

        self.assertTrue(self.a.pane.material_model.save(),
                        "the panel that switched cannot save after coming back")
        self.assertTrue(self.b.pane.material_model.save(),
                        "the other panel was left detached by the switch")

    def test_h9_a_panel_opened_after_a_switch_joins_the_same_models(self):
        """Not re-registered, the models stay under the old path; the next panel builds a second set."""
        other = test_support.fresh_library(self)
        self.a.pane.prefs.dir = other
        self.a.pane.library.switch_all_models()

        joined = model_registry.models_for(self.a.pane.prefs)

        self.assertIs(
            self.a.pane.material_model, joined["material_model"],
            "a panel opening on this library is handed a second, separate "
            "set of models - which is the divergence phase 1 removed")

    def test_a_closed_panel_leaves_no_listener_on_the_shared_models(self):
        """Qt deletes a parented proxy with its widget; unparented, a closed tab still gets signals."""
        import shiboken6

        doomed = [self.b.pane.material_sorted_model, self.b.pane.material_selection_model,
                  self.b.pane.category_sorted_model, self.b.pane.file_sorted_model,
                  self.b.pane.cop_sorted_model, self.b.pane.code_sorted_model,
                  self.b.pane.gradient_sorted_model]
        self.assertTrue(all(shiboken6.isValid(o) for o in doomed),
                        "premise: the second panel's proxies are not built")

        shiboken6.delete(self.b)

        alive = [o for o in doomed if shiboken6.isValid(o)]
        self.assertEqual(
            [], alive,
            "%d of the closed panel's proxies outlived it, still connected to the "
            "shared models" % len(alive))
        self.assertTrue(self.a.pane.material_model.rowCount(),
                        "the surviving panel lost its rows when the other closed")

    def test_a_pending_resort_does_not_run_after_its_panel_is_deleted(self):
        """A re-sort is deferred to the next event loop pass; closing the panel must not leave it queued."""
        from PySide6 import QtCore

        proxy = self.b.pane.material_sorted_model
        ran = []
        proxy._pass_now = lambda: ran.append(True)    # patched BEFORE scheduling, so this is the callable the timer holds
        proxy._schedule_pass()
        self.assertTrue(proxy._pass_scheduled,
                        "premise: no pass was queued, so nothing is tested here")

        test_support.stop_panel_workers(self.b)
        self.b.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete)    # what Houdini's own loop does when the tab closes; processEvents alone never delivers it
        QtWidgets.QApplication.processEvents()

        self.assertEqual([], ran,
                         "the queued re-sort ran after its panel was deleted, "
                         "on a proxy Qt had already destroyed")

    def test_a_category_removed_in_one_panel_updates_the_other_sidebar(self):
        """Both sidebars share one list: the second panel loses a row with no signal. ▸p/one-model-set"""
        categories = self.a.pane.category_model
        before = categories.rowCount()
        self.assertTrue(before > 1,
                        "premise: the fixture has no category to remove")
        self.assertIs(categories._categories, self.b.pane.category_model._categories,
                      "premise: the two sidebars do not share a list, so this "
                      "is no longer the hazard the audit measured")

        heard = []
        self.b.pane.category_model.modelReset.connect(lambda: heard.append("reset"))
        self.b.pane.category_model.rowsRemoved.connect(
            lambda *a: heard.append("removed"))
        self.b.pane.category_model.layoutChanged.connect(
            lambda *a: heard.append("layout"))

        name = categories.data(categories.index(before - 1, 0),
                               category.SIDEBAR_KEY_ROLE)
        categories.remove_category(name)    # the SIDEBAR's method; the library model's same-named one only strips the category off assets

        self.assertEqual(before - 1, self.b.pane.category_model.rowCount(),
                         "premise: the row was not removed from the shared list")
        self.assertTrue(
            heard,
            "a category disappeared from the second panel's sidebar and the "
            "model emitted no signal - its view paints rows that are gone")

    def test_a_location_reorder_in_the_panel_opened_first_is_saved(self):
        """The shared folder list saves the settings its move staged the order in."""
        folders = self.a.pane.file_folders_model
        self.assertIs(folders, self.b.pane.file_folders_model,
                      "premise: the two panels do not share the folder list")
        self.assertIs(folders.preferences, self.b.pane.prefs,
                      "premise: the shared list does not hold the second panel's settings")
        with mock.patch.object(prefs.Prefs, "save", persistence._Persistence.save):    # the fixture saves nothing
            for name in ("one", "two"):
                folder = tempfile.mkdtemp(prefix="amaze_order_%s_" % name)
                self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
                self.assertTrue(
                    folders.add_folder(hostos.canonical_path_key(folder).rstrip("/") + "/"),
                    "premise: the location was not added")
            before = list(folders._folders())
            section = self.a.pane.sections["file"]
            last = folders.index(folders.rowCount() - 1, 0)
            self.assertTrue(folders.move_row(last, folders._offset()),
                            "premise: the last location did not move to the first row")
            folders.commit_order()
            saved = prefs.Prefs()
            saved.load()
        self.assertEqual([before[-1]] + before[:-1], list(saved.file_folders),
                         "a reorder made in the first of two panels is not in the saved settings")



class AFileTabSwitchReachesBothPanelsTest(unittest.TestCase):
    """The File tab's model is shared; a switch flipped in either panel's Preferences reaches it."""

    def setUp(self):
        self.a = test_support.fixture_panel(self)
        self.b = _second_panel(self)    # opened last: the shared model now reads B's Prefs

    def test_a_switch_flipped_in_the_first_panel_changes_the_shared_file_tab(self):
        from amaze.dialogs import prefs_window
        files = self.a.pane.file_files_model
        self.assertIs(files, self.b.pane.file_files_model, "premise: the panels do not share the File model")
        self.assertIsNot(self.a.pane.prefs, files.preferences, "premise: the model reads the first panel's Prefs")
        state = prefs_window.AmazePrefsState(self.a.pane.prefs, pane=self.a.pane)
        for name in ("system_file_icons", "render_rat_files"):
            to_text, _to_value = prefs_window.SETTINGS[name]
            for value in (not getattr(files.preferences, name), getattr(files.preferences, name)):
                with self.subTest(switch=name, value=value), \
                        mock.patch.object(files, "refresh_current_folder") as refresh:
                    state.setPref(name, to_text(value))    # what the row's switch sends for that value
                    state.apply()
                    self.assertIs(value, getattr(self.a.pane.prefs, name))
                    self.assertIs(value, getattr(files.preferences, name),
                                  "the File tab still reads the other panel's value")
                    refresh.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
