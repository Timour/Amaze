"""The File sidebar's `$HIP` row: the scene's folder, browsed by the engine every folder uses."""

import os
import shutil
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze.core import category  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.panel import sidebar  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - arms the sandbox
from amaze.tests.test_folder_tree import _shown  # noqa: E402


def _hip() -> str:
    return hostos.canonical_path_key(hou.getenv("HIP")).rstrip("/") + "/"


class _SceneCase(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.folders = self.panel.file_folders_model
        self.files = self.panel.file_files_model
        self.section = self.panel.sections["file"]
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.loc = self.folders.registered_at(self.folders._offset())

    def _stand(self, index):
        view = self.panel.cat_list
        view.selectionModel().setCurrentIndex(
            index, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.panel.update_selected_cat()
        QtWidgets.QApplication.processEvents()

    def _row(self):
        return self.folders.index(1, 0)


class TheSceneRowInTheFileTab(_SceneCase):
    """Row 1 reads the scene's folder, browses it, and refuses every location verb."""

    def test_it_reads_the_pinned_scene_folder_at_row_1(self):
        row = self._row()
        self.assertEqual("$HIP", row.data())
        self.assertEqual(_hip(), row.data(self.folders.BrowseRole))
        self.assertEqual(_hip(), row.data(QtCore.Qt.ItemDataRole.ToolTipRole))
        self.assertEqual(["notes.txt", "shot.hip"], sorted(os.listdir(_hip())),
                         "premise: the fixture did not pin its own scene folder")
        self.assertEqual(self.loc, self.panel.file_files_model.browsing(),
                         "the tab no longer opens on the remembered location")

    def test_no_drag_and_no_location_entry_reaches_it(self):
        row, section = self._row(), self.section
        self.assertFalse(section.sidebar_movable(row), "the scene row can be dragged")
        self.assertTrue(section.sidebar_movable(self.folders.index(self.folders._offset(), 0)),
                        "premise: a location can be dragged")
        self.assertFalse(section.on_a_location([row], row),
                         "Locate, Rename, Remove, Show and Label stay live on the scene row")
        needs = {entry.label: entry.needs for entry in section.SIDEBAR_MENU}
        self.assertEqual("always", needs["Add"])

    def test_remove_and_locate_leave_every_location_alone(self):
        before = list(self.folders._folders())
        self._stand(self._row())
        self.assertEqual([], self.panel.remove_file_folder_user(), "the scene row was removed")
        picked, said = [], []
        ui = mock.MagicMock()
        ui.selectFile.side_effect = lambda *a, **k: picked.append(1) or self.loc
        ui.displayMessage.side_effect = lambda *a, **k: said.append(a)
        with mock.patch.object(hou, "ui", ui, create=True):
            self.panel._locate_folder_user(self.folders)
        self.assertEqual([], picked, "Locate opened a folder picker on the scene row")
        self.assertEqual(1, len(said), "Locate said nothing on the scene row")
        self.assertEqual(before, list(self.folders._folders()), "a location's pointer changed")
        self.assertEqual(_hip(), self.folders.scene_folder())

    def test_a_click_browses_the_scene_folder_and_remembers_it_by_its_token(self):
        self._stand(self._row())
        self.assertEqual(_hip(), self.files.browsing())
        self.assertEqual("$HIP", self.panel.prefs.last_file_folder)

    def test_the_tab_reopens_on_the_scene_row(self):
        self.panel.section_tabs.setChecked("material")
        self.panel.prefs.last_file_folder = "$HIP"
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.assertEqual(1, self.panel.cat_list.currentIndex().row())
        self.assertFalse(self.panel.cat_list.currentIndex().parent().isValid())
        self.assertEqual(_hip(), self.files.browsing())

    def test_a_remembered_scene_subfolder_reopens_under_the_scene_row(self):
        sub = _hip() + "plates"
        os.makedirs(sub)
        self.panel.section_tabs.setChecked("material")
        self.panel.prefs.last_file_folder = sub
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.assertEqual(sub, self.files.browsing(), "the grid shows another folder")
        view = self.panel.cat_list
        self.assertTrue(self.folders.is_scene_row(sidebar.top_level(view.currentIndex())),
                        "the sidebar stands outside the scene row")
        self.folders.data(self._row(), category.SIDEBAR_COUNT_ROLE)    # a paint asks; headless, ask as it would
        self.assertTrue(test_support.pump_until(
            lambda: view.currentIndex().data(self.folders.BrowseRole) == sub),
            "the sidebar never stood on the remembered scene subfolder")

    def test_a_tile_dragged_onto_it_is_accepted(self):
        self.assertTrue(self.section.accepts_file_drop(self._row()))


class TheSceneRowFollowsTheScene(_SceneCase):
    """Save, Open and New move the row; a grid on the row follows, one on a location stays."""

    def _save(self) -> str:
        folder = test_support.scratch_dir("amaze_test_saved_scene_")
        self.addCleanup(shutil.rmtree, folder, True)
        self.addCleanup(hou.hipFile.clear, suppress_save_prompt=True)
        self.addCleanup(self.panel.unwatch_scene)    # first: the clear moves no grid onto the runner's folder
        hou.hipFile.save(os.path.join(folder, "moved.hip"), save_to_recent_files=False)
        QtWidgets.QApplication.processEvents()
        return hostos.canonical_path_key(folder).rstrip("/") + "/"

    def test_the_panel_adds_one_callback_and_unwatch_takes_it_back(self):
        watch = self.panel._scene_watch
        self.assertIn(watch, hou.hipFile.eventCallbacks())
        self.assertEqual(1, list(hou.hipFile.eventCallbacks()).count(watch))
        before = len(hou.hipFile.eventCallbacks())
        self.panel.unwatch_scene()
        self.assertNotIn(watch, hou.hipFile.eventCallbacks())
        self.assertEqual(before - 1, len(hou.hipFile.eventCallbacks()))
        self.panel.unwatch_scene()
        self.assertEqual(before - 1, len(hou.hipFile.eventCallbacks()))

    def test_a_save_moves_a_grid_standing_on_the_scene_row(self):
        self._stand(self._row())
        moved = self._save()
        self.assertEqual(moved, _hip(), "premise: the save did not move $HIP")
        self.assertEqual(moved, self.folders.scene_folder())
        self.assertEqual(moved, self.files.browsing(), "the grid stayed on the old scene folder")
        self.assertEqual("$HIP", self.panel.prefs.last_file_folder)
        self.assertEqual(self._row(), self.panel.cat_list.currentIndex())

    def test_a_save_moves_a_grid_standing_in_a_scene_subfolder(self):
        old = _hip()
        os.makedirs(old + "plates")
        _shown(self.folders, old)
        self.assertTrue(test_support.pump_until(lambda: self.folders.rowCount(self._row()) == 1),
                        "premise: the scene folder's subfolder never arrived")
        self._stand(self.folders.index(0, 0, self._row()))
        self.assertEqual(old + "plates", self.files.browsing(), "premise: not on the subfolder")
        moved = self._save()
        test_support.pump_until(lambda: False, timeout=0.05)
        self.assertEqual(moved, self.files.browsing(), "the grid stayed in the old scene folder")
        self.assertEqual(self._row(), self.panel.cat_list.currentIndex(),
                         "the sidebar does not stand on the scene row")

    def test_a_save_leaves_a_grid_on_a_location_alone(self):
        self._stand(self.folders.index(self.folders._offset(), 0))
        self.assertEqual(self.loc, self.files.browsing(), "premise: not on the location")
        moved = self._save()
        self.assertEqual(moved, self.folders.scene_folder(), "premise: the row did not move")
        test_support.pump_until(lambda: False, timeout=0.05)
        self.assertEqual(self.loc, self.files.browsing(), "the grid left its location")
        self.assertEqual(self.loc, self.panel.cat_list.currentIndex().data(self.folders.PathRole))

    def test_a_new_scene_reads_hip_again(self):
        moved = self._save()
        self.assertEqual(moved, self.folders.scene_folder(), "premise: the row did not move")
        hou.hipFile.clear(suppress_save_prompt=True)
        self.assertEqual(_hip(), self.folders.scene_folder())
        self.assertNotEqual(moved, self.folders.scene_folder())


class TheSceneWatchItself(unittest.TestCase):
    """What the watch reads from Houdini, and a removal the manual says may refuse."""

    def test_no_hip_reads_no_scene_folder(self):
        from amaze.actions import files as files_actions
        with mock.patch.object(hou, "getenv", lambda name, default=None: None):
            self.assertEqual("", files_actions.scene_folder())

    def test_removing_a_callback_houdini_no_longer_holds_is_no_error(self):
        from amaze.actions import files as files_actions

        def refused(_callback):
            raise hou.OperationFailed("not registered")
        with mock.patch.object(hou.hipFile, "removeEventCallback", refused):
            files_actions.unwatch_scene(lambda *a, **k: None)


if __name__ == "__main__":
    unittest.main()
