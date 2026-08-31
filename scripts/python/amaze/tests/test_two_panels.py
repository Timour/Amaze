"""Two Amaze panels open at once must not damage the library - every case is a reproduction from the two-panel audit, asserting what SHOULD happen. ▸p/one-model-set"""

import json
import os
import unittest

from PySide6 import QtWidgets

from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])    # ▸p/first-app-picks-the-platform


def _document(panel, filename="library.json"):
    """The section database as it is ON DISK right now, read without the app."""
    with open(os.path.join(panel.prefs.dir, filename),
              encoding="utf-8-sig") as handle:
        return json.load(handle)


def _rows(panel, filename="library.json"):
    """Disk rows by id as a STRING - the fixture carries an int id and `Material.mat_id` always answers a str."""
    return {str(row.get("id")): row
            for row in _document(panel, filename)["assets"]}


def _second_panel(testcase):
    """A panel CO-EXISTING with the fixture panel - the singletons are left standing, so both hold the connector the way two pane tabs do."""
    return test_support.reopened_panel(testcase)


class TwoPanelsShareOneLibraryTest(unittest.TestCase):
    """One process, two panels, one library: neither may lose the other's work."""

    def setUp(self):
        self.a = test_support.fixture_panel(self)
        self.b = _second_panel(self)

    def _named_asset(self, panel):
        """A row with a real name - the fixture's row 0 is an id -1 sentinel."""
        model = panel.material_model
        for row in range(model.rowCount()):
            if model._assets[row].name:
                return model.index(row, 0), model
        self.fail("premise: the fixture library holds no named asset")

    def test_a_rename_survives_the_other_panels_save(self):
        index, model = self._named_asset(self.a)
        asset = model._assets[index.row()]
        target = asset.mat_id
        model.set_assetdata(index, "renamed by panel A",
                            ", ".join(asset.categories),
                            ", ".join(asset.tags), None)

        self.assertTrue(self.b.material_model.save(),
                        "premise: the second panel's save was refused")

        self.assertEqual(
            "renamed by panel A", _rows(self.a)[target].get("name"),
            "the second panel's save reverted the first panel's rename")

    def test_a_delete_is_not_resurrected_by_the_other_panels_save(self):
        index, model = self._named_asset(self.a)
        target = model._assets[index.row()].mat_id
        model.remove_asset(index)
        self.assertNotIn(target, _rows(self.a),
                         "premise: the delete never reached disk")

        self.assertTrue(self.b.material_model.save(),
                        "premise: the second panel's save was refused")

        self.assertNotIn(
            target, _rows(self.a),
            "the second panel's save brought the deleted asset back, and its "
            "files are gone - a row pointing at nothing")

    def test_both_panels_read_one_set_of_rows(self):
        self.assertIs(
            self.a.material_model, self.b.material_model,
            "each panel built its own library model over the same file, so "
            "one panel's save writes the other's copy of the rows")

    def test_a_closed_panel_leaves_no_listener_on_the_shared_models(self):
        """Qt takes a parented proxy with its widget - unparented, a closed pane tab goes on receiving the shared model's signals forever. ▸p/one-model-set"""
        import shiboken6

        doomed = [self.b.material_sorted_model, self.b.material_selection_model,
                  self.b.category_sorted_model, self.b.file_sorted_model,
                  self.b.cop_sorted_model, self.b.code_sorted_model,
                  self.b.gradient_sorted_model]
        self.assertTrue(all(shiboken6.isValid(o) for o in doomed),
                        "premise: the second panel's proxies are not built")

        shiboken6.delete(self.b)

        alive = [o for o in doomed if shiboken6.isValid(o)]
        self.assertEqual(
            [], alive,
            "%d of the closed panel's proxies outlived it, still wired to the "
            "shared models" % len(alive))
        self.assertTrue(self.a.material_model.rowCount(),
                        "the surviving panel lost its rows when the other closed")

    def test_a_pending_resort_dies_with_the_panel_that_asked_for_it(self):
        """The grid proxies coalesce a re-sort onto the next event-loop turn; a panel closed inside that window leaves the call queued against a proxy Qt is about to delete."""
        from PySide6 import QtCore

        proxy = self.b.material_sorted_model
        ran = []
        proxy._pass_now = lambda: ran.append(True)    # patched BEFORE scheduling, so this is the callable the timer carries
        proxy._schedule_pass()
        self.assertTrue(proxy._pass_scheduled,
                        "premise: no pass was queued, so nothing races here")

        test_support.stop_panel_workers(self.b)
        self.b.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete)    # what Houdini's own loop does when the tab closes; processEvents alone never delivers it
        QtWidgets.QApplication.processEvents()

        self.assertEqual([], ran,
                         "the queued re-sort ran after its panel was deleted, "
                         "on a proxy Qt had already destroyed")

    def test_a_category_removed_in_one_panel_tells_the_other_sidebar(self):
        """Both sidebars alias ONE list, so the row vanishes from the second panel with no signal and its view repaints only by accident. ▸p/one-model-set"""
        categories = self.a.category_model
        before = categories.rowCount()
        self.assertTrue(before > 1,
                        "premise: the fixture has no category to remove")
        self.assertIs(categories._categories, self.b.category_model._categories,
                      "premise: the two sidebars do not share a list, so this "
                      "is no longer the hazard the audit measured")

        heard = []
        self.b.category_model.modelReset.connect(lambda: heard.append("reset"))
        self.b.category_model.rowsRemoved.connect(
            lambda *a: heard.append("removed"))
        self.b.category_model.layoutChanged.connect(
            lambda *a: heard.append("layout"))

        name = categories.data(categories.index(before - 1, 0),
                               categories.CatSortRole)
        categories.remove_category(name)    # the SIDEBAR's door; the library model's namesake only strips the category off assets

        self.assertEqual(before - 1, self.b.category_model.rowCount(),
                         "premise: the row did not leave the shared list")
        self.assertTrue(
            heard,
            "a category disappeared from the second panel's sidebar and the "
            "model said nothing - its view is painting rows that are gone")


if __name__ == "__main__":
    unittest.main()
