"""The list of libraries, most recent first, and Manage Libraries (D15), which removes from it."""

import json
import os
import shutil
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

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


def painted_texts(view, row, selected=False):
    """(x, y, w, h, text, colour) of each text the list's delegate paints for `row`."""
    painted = []

    class _Recorder(QtGui.QPainter):
        def drawText(self, rect, align, text):
            painted.append((rect.x(), rect.y(), rect.width(), rect.height(), text,
                            self.pen().color().name()))
            return super().drawText(rect, align, text)

    surface = QtGui.QPixmap(view.viewport().size())
    painter = _Recorder(surface)
    option = QtWidgets.QStyleOptionViewItem()
    option.font = view.font()
    option.rect = view.visualItemRect(view.item(row))
    if selected:
        option.state |= QtWidgets.QStyle.StateFlag.State_Selected
    try:
        view.itemDelegate().paint(painter, option, view.model().index(row, 0))
    finally:
        painter.end()
    return painted


def colours_down(view, x):
    """The viewport's colour at each y of column `x`, top to bottom, as the list paints it."""
    picture = view.viewport().grab().toImage()
    ratio = picture.devicePixelRatio()
    return [QtGui.QColor(picture.pixel(int(x * ratio), int(y * ratio))).name()
            for y in range(view.viewport().height())]


def filled_rows_expected(frame_key, height, selected_row, selected_colour):
    """The colour each y of a list `height` high must show: the drawn filled rows, the bar."""
    drawn, px = amazetheme.drawn_list_rows(frame_key), theme.ui_px
    expected = [QtGui.QColor(amazetheme.LIST_BACKGROUND).name()] * height
    top = px(drawn["filled_top"])
    while top < height:
        for y in range(top, min(height, top + px(drawn["filled_h"]))):
            expected[y] = QtGui.QColor(amazetheme.FILLED_ROW).name()
        top += px(drawn["filled_step"])
    bar = selected_row * px(drawn["pitch"]) + px(drawn["box_y"])
    for y in range(bar, bar + px(drawn["box_h"])):
        expected[y] = QtGui.QColor(selected_colour).name()
    return expected


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
        self.assertEqual(self.panel.prefs.dir, self.panel.prefs.libraries[0])

    def test_a_switch_puts_the_new_library_first(self):
        first = self.panel.prefs.dir
        other = test_support.fresh_library(self)
        self.panel.prefs.dir = other
        path = os.path.join(self.panel.prefs.path, "settings.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        data.update(directory=other, libraries=[first])    # the fixture panel does not save
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.assertTrue(self.panel.open_library())
        self.assertEqual([other, first], self.panel.prefs.libraries[:2])


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
        self.assertTrue(os.path.isfile(marker), "Remove from List changed the folder")

    def test_no_band_sits_over_the_list(self):
        self.assertIsNone(self.dialog.findChild(QtWidgets.QLabel, "amaze_header_band_text"))

    def test_a_folder_that_cannot_be_reached_is_marked(self):
        reached = {item.text(): item.data(library_dialog.REACHED_ROLE) for item in self._rows()}
        self.assertEqual({"Studio": True, "Archive": True, "Archive-gone": False}, reached)


class TheManageWindowMatchesItsDesignFrame(unittest.TestCase):
    """D15's window, list, buttons and rows match the boxes of its design frame."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        self.gone = _folder(self, "Gone").rstrip("/") + "-unplugged/"
        self.prefs.note_library_opened(self.gone)    # the last row: a library not connected
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

    def test_the_list_and_the_buttons_are_where_drawn(self):
        boxes = amazetheme.drawn_boxes("D15")
        for widget, key in ((self.dialog._list, ("QListWidget", None)),
                            (self.dialog._remove, ("QPushButton", amazetheme.BTN_REMOVE_FROM_LIST)),
                            (self.dialog._cancel, ("QPushButton", amazetheme.BTN_CANCEL))):
            drawn = boxes[key][0] if key[1] is None else boxes[key]
            with self.subTest(widget=key):
                self.assertEqual(tuple(theme.ui_px(n) for n in drawn), self._box(widget))

    def _drawn_frame_figures(self):
        """The D15 figures the tests below compare against, read straight from the layout."""
        nodes = amazetheme.DIALOG_LAYOUT["D15"]["nodes"]
        view, = (n for n in nodes if n[0] == "QListWidget")
        return view, nodes

    def test_each_row_is_19_px_from_the_list_top(self):
        view, nodes = self._drawn_frame_figures()
        names = sorted(n[2] for n in nodes if n[0] == "QListWidget ▸ item")
        self.assertEqual(19, names[1] - names[0], "premise: the frame draws 19 px rows")
        for row in range(self.dialog._list.count()):
            with self.subTest(row=row):
                rect = self.dialog._list.visualItemRect(self.dialog._list.item(row))
                self.assertEqual((0, theme.ui_px(19 * row), self.dialog._list.viewport().width(),
                                  theme.ui_px(19)),
                                 (rect.x(), rect.y(), rect.width(), rect.height()))

    def test_the_texts_sit_where_the_frame_draws_them(self):
        view, nodes = self._drawn_frame_figures()
        drawn = [n for n in nodes if n[0] in ("QListWidget ▸ item", "QListWidget ▸ item ▸ path")]
        px = theme.ui_px
        for row in range(3):    # the frame's first three rows, all connected
            name, path = painted_texts(self.dialog._list, row)
            with self.subTest(row=row):
                top = sorted({n[2] for n in drawn})[row] - view[2]
                self.assertEqual((px(19 - 8), px(top), px(15)), (name[0], name[1], name[3]))
                self.assertEqual((px(130 - 8), px(top), px(15)), (path[0], path[1], path[3]))

    def test_the_filled_rows_and_the_bar_run_to_the_bottom_of_the_list(self):
        self.dialog._list.item(1).setSelected(True)
        QtWidgets.QApplication.processEvents()
        view = self.dialog._list
        x = view.viewport().width() - 2    # right of every text
        self.assertEqual(filled_rows_expected("D15", view.viewport().height(), 1,
                                              amazetheme.D15_SELECTED_BACKGROUND),
                         colours_down(view, x))
        self.assertGreater(view.viewport().height(), 19 * view.count(),
                           "premise: the list is taller than its rows")

    def test_the_selected_bar_is_the_whole_row_with_square_corners(self):
        view = self.dialog._list
        view.item(1).setSelected(True)
        QtWidgets.QApplication.processEvents()
        red = QtGui.QColor(amazetheme.D15_SELECTED_BACKGROUND).name()
        px, width = theme.ui_px, view.viewport().width()
        for x in (0, width - 1):
            with self.subTest(x=x):
                column = colours_down(view, x)
                self.assertEqual([red] * px(19), column[px(19):px(38)])
                self.assertNotEqual(red, column[px(19) - 1])
                self.assertNotEqual(red, column[px(38)])
        self.assertEqual("#e0523a", red)

    def test_the_text_on_the_red_bar_is_dark(self):
        name, path = painted_texts(self.dialog._list, 1, selected=True)
        self.assertEqual(("#1b1b1b", "#383838"), (name[5], path[5]))

    def test_a_library_not_connected_keeps_its_dimmed_colours(self):
        last = self.dialog._list.count() - 1
        self.assertEqual(self.gone, self.dialog._list.item(last).data(library_dialog.FOLDER_ROLE))
        painted = {text: colour for *_box, text, colour in painted_texts(self.dialog._list, last)}
        self.assertEqual("#787878", painted.pop(amazetheme.LABEL_NOT_CONNECTED))
        self.assertEqual(["#646464", "#787878"], sorted(painted.values()))


class EveryDrawnListHasTheListBackground(unittest.TestCase):
    """D15 and D01 both build their list with `drawn_list`, so one test covers both."""

    def _dialogs(self):
        from amaze.dialogs import versions_dialog
        prefs = test_support.fixture_prefs(self)
        for name in ("C", "B", "A"):
            prefs.note_library_opened(_folder(self, name))
        listed = [{"n": n, "name": "Version %d" % n, "date": "2026-10-2%d 09:00" % n}
                  for n in (1, 2, 3)]
        return (("D15", library_dialog.ManageLibrariesDialog(prefs)),
                ("D01", versions_dialog.VersionsDialog("brushed_steel", listed, 2)))

    def test_the_list_ground_is_the_drawn_list_colour(self):
        for frame, dialog in self._dialogs():
            with self.subTest(frame=frame):
                self.addCleanup(dialog.deleteLater)
                dialog.show()
                self.addCleanup(dialog.hide)
                QtWidgets.QApplication.processEvents()
                picture = dialog.grab().toImage()
                ratio = picture.devicePixelRatio()
                corner = dialog._list.mapTo(dialog, dialog._list.rect().topLeft())
                x, y, high = corner.x(), corner.y(), dialog._list.height()

                def color_at(at_x, at_y, picture=picture, ratio=ratio):    # bound per subTest
                    return QtGui.QColor(picture.pixel(int(at_x * ratio),
                                                      int(at_y * ratio))).name()

                background = QtGui.QColor(amazetheme.LIST_BACKGROUND).name()
                bare = y + theme.ui_px(19 * 3) + 1    # the fourth row: unfilled, below the items
                self.assertEqual(background, color_at(x + 10, bare),
                                 "the list's ground under its unfilled rows is not the list colour")
                self.assertIn("border-radius: 0", dialog._list.styleSheet(), "the frames draw a square list box")


if __name__ == "__main__":
    unittest.main()
