"""The Library list, most recent first, and Manage Libraries (D15), which takes them off it."""

import json
import os
import shutil
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

from amaze import amazetheme  # noqa: E402
from amaze.dialogs import library_dialog  # noqa: E402
from amaze.helpers import theme  # noqa: E402
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

    def test_nothing_drops_off(self):
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

    def test_the_list_survives_a_save(self):
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
        self.assertEqual(self.panel.prefs.real_dir, self.panel.prefs.libraries[0])

    def test_a_switch_puts_the_new_library_first(self):
        first = self.panel.prefs.real_dir
        other = test_support.fresh_library(self)
        self.panel.prefs.dir = other
        path = os.path.join(self.panel.prefs.path, "settings.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data.update(directory=other, libraries=[first])    # the saves the fixture panel switches off
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.assertTrue(self.panel.open_library())
        self.assertEqual([other, first], self.panel.prefs.libraries[:2])

    def test_the_test_library_is_not_listed(self):
        from amaze.dialogs import prefs_dialog
        folder = test_support.scratch_dir("amaze_listed_test_lib_")
        self.addCleanup(shutil.rmtree, folder, True)
        listed = self.panel.prefs.libraries
        self.panel.prefs.test_dir = folder
        dialog = prefs_dialog.PrefsDialog(self.panel.prefs, panel=self.panel)
        self.addCleanup(dialog.deleteLater)
        dialog.set_test_mode(True)
        self.assertEqual(listed, self.panel.prefs.libraries,
                         "turning Test Library on changed the Library list")


class ManageLibrariesTest(unittest.TestCase):

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.a, self.b = _folder(self, "Studio"), _folder(self, "Archive")
        self.gone = self.b.rstrip("/") + "-gone/"
        for folder in (self.gone, self.b, self.a):
            self.prefs.note_library_opened(folder)
        self.dialog = library_dialog.ManageLibrariesDialog(self.prefs, open_library=self.a)
        self.addCleanup(self.dialog.deleteLater)

    def _rows(self):
        view = self.dialog._list
        return [view.item(row) for row in range(view.count())]

    def _select(self, folder):
        for item in self._rows():
            item.setSelected(item.data(library_dialog.FOLDER_ROLE) == folder)

    def test_it_lists_the_libraries_most_recent_first(self):
        self.assertEqual(["Studio", "Archive", "Archive-gone"],
                         [item.text() for item in self._rows()])

    def test_the_open_library_cannot_be_selected(self):
        self.dialog._list.selectAll()
        self.assertNotIn(self.a, [item.data(library_dialog.FOLDER_ROLE)
                                  for item in self.dialog._list.selectedItems()])

    def test_remove_waits_for_a_selection(self):
        self.assertFalse(self.dialog._remove.isEnabled())
        self._select(self.b)
        self.assertTrue(self.dialog._remove.isEnabled())

    def test_remove_takes_the_selection_off_and_saves_the_list(self):
        self._select(self.b)
        self.dialog._remove.click()
        self.assertEqual([self.a, self.gone], self.prefs.libraries)
        self.assertEqual([self.a, self.gone], _reloaded(self.prefs).libraries,
                         "the removal was not saved")
        self.assertEqual([self.b], self.dialog.removed)
        self.assertEqual(["Studio", "Archive-gone"], [item.text() for item in self._rows()])

    def test_a_removed_library_keeps_its_folder(self):
        marker = os.path.join(self.b, "library.json")
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("{}")
        self._select(self.b)
        self.dialog._remove.click()
        self.assertTrue(os.path.isfile(marker), "Remove from List touched the folder")

    def test_no_band_sits_over_the_list(self):
        self.assertIsNone(self.dialog.findChild(QtWidgets.QLabel, "amaze_header_band_text"))

    def test_a_folder_that_cannot_be_reached_is_marked(self):
        reached = {item.text(): item.data(library_dialog.REACHED_ROLE) for item in self._rows()}
        self.assertEqual({"Studio": True, "Archive": True, "Archive-gone": False}, reached)


class TheManageWindowStandsOnItsFrame(unittest.TestCase):
    """D15's window, list, buttons and rows land where the frame draws them."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        for name in ("C", "B", "A"):
            self.prefs.note_library_opened(_folder(self, name))
        self.dialog = library_dialog.ManageLibrariesDialog(self.prefs)
        self.addCleanup(self.dialog.deleteLater)
        self.dialog.show()
        self.addCleanup(self.dialog.hide)
        QtWidgets.QApplication.processEvents()

    def _box(self, widget):
        corner = widget.mapTo(self.dialog, widget.rect().topLeft())
        return (corner.x(), corner.y(), widget.width(), widget.height())

    def test_the_window_is_the_drawn_frame(self):
        self.assertEqual(tuple(theme.ui_px(n) for n in amazetheme.DIALOG_LAYOUT["D15"]["frame"]),
                         (self.dialog.width(), self.dialog.height()))

    def test_the_list_and_the_buttons_land_where_drawn(self):
        boxes = amazetheme.drawn_boxes("D15")
        for widget, key in ((self.dialog._list, ("QListWidget", None)),
                            (self.dialog._remove, ("QPushButton", amazetheme.BTN_REMOVE_FROM_LIST)),
                            (self.dialog._cancel, ("QPushButton", amazetheme.BTN_CANCEL))):
            drawn = boxes[key][0] if key[1] is None else boxes[key]
            with self.subTest(widget=key):
                self.assertEqual(tuple(theme.ui_px(n) for n in drawn), self._box(widget))

    def test_a_selected_row_is_painted_in_its_drawn_box(self):
        rows = amazetheme.drawn_list_rows()
        px = theme.ui_px
        self.dialog._list.item(1).setSelected(True)
        QtWidgets.QApplication.processEvents()
        picture = self.dialog._list.viewport().grab().toImage()
        ratio = picture.devicePixelRatio()
        top = px(rows["pitch"]) + px(rows["box_y"])

        def ink(x, y):
            return QtGui.QColor(picture.pixel(int(x * ratio), int(y * ratio))).name()

        selected = QtGui.QColor(amazetheme.D15_SELECTED_INK).name()
        self.assertEqual(selected, ink(px(rows["box_x"]) + 1, top + 1),
                         "the selected row is not painted where it is drawn")
        self.assertNotEqual(selected, ink(px(rows["box_x"]) + 1, top - 1),
                            "the selection fills the gap the frame leaves above the row")
        self.assertNotEqual(selected, ink(px(rows["box_x"]) - 1, top + 1),
                            "the selection fills the inset the frame leaves beside the row")
        self.assertNotEqual(selected, ink(px(rows["box_x"]), top),
                            "the selected row's corner is square; the frame rounds it")

    def test_the_list_ground_is_houdinis_list_colour_with_round_corners(self):
        picture = self.dialog.grab().toImage()
        ratio = picture.devicePixelRatio()
        x, y, _wide, high = self._box(self.dialog._list)

        def ink(at_x, at_y):
            return QtGui.QColor(picture.pixel(int(at_x * ratio), int(at_y * ratio))).name()

        ground = theme.list_ground().name()
        self.assertEqual(ground, ink(x + 10, y + high - 3), "the bare list is not the list colour")
        self.assertNotEqual(ground, ink(x, y), "the list's corner is square; the frame rounds it")


if __name__ == "__main__":
    unittest.main()
