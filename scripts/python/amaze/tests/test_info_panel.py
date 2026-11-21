"""The info pane: its N02 sizes, its subject and read, and its toggle, selection and menu wiring."""

import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import amazetheme  # noqa: E402
from amaze.core import file_info, image_preview  # noqa: E402
from amaze.helpers import theme  # noqa: E402
from amaze.panel import info_panel  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class _Reader(QtCore.QObject):
    """A reader that records what it is asked; the test emits `ready` itself."""

    ready = QtCore.Signal(str, list)

    def __init__(self):
        super().__init__()
        self.asked = []
        self.stops = 0

    def ask(self, key, request):
        self.asked.append((key, request))

    def stop(self):
        self.stops += 1


class _Pictures(QtCore.QObject):
    """A picture reader that records what it is asked and answers at once when it has an `image`."""

    ready = QtCore.Signal(str, object)

    def __init__(self):
        super().__init__()
        self.asked = []
        self.stops = 0
        self.image = None

    def ask(self, path, width):
        self.asked.append((path, width))
        if self.image is not None:
            self.ready.emit(path, self.image)

    def stop(self):
        self.stops += 1


def _picture(width=900, height=600):
    image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGB888)
    image.fill(QtGui.QColor("#ff0000"))
    return image


def _prefs():
    return types.SimpleNamespace(notes_panel_width=0)


def _subject(key="k1", request=True, before=(("Name", "steel"),),
             after=(("Folder", "/library/textures"),)):
    read = file_info.Request(file_info.KIND_IMAGE, ("/library/textures/steel.exr",))
    return file_info.Subject(key, "steel", "EXR", before, after, read if request else None)


class _PaneCase(unittest.TestCase):

    def setUp(self):
        self.reader = _Reader()
        self.pictures = _Pictures()
        self.pane = info_panel.InfoPanel(_prefs(), self.reader, pictures=self.pictures)
        self.addCleanup(self.pane.deleteLater)
        self.addCleanup(self.pane.hide)
        width, height = amazetheme.DIALOG_LAYOUT["N02"]["frame"]
        self.pane.resize(theme.ui_px(width), theme.ui_px(height))
        self.pane.show()
        QtWidgets.QApplication.processEvents()


class TheInfoPaneMatchesItsDesignFrame(_PaneCase):
    """The pane's width, header, preview, rows, columns and divider are what N02 draws."""

    def setUp(self):
        super().setUp()
        self.px = theme.ui_px
        self.node = lambda kind, owner=None: amazetheme.drawn_node("N02", kind, owner)
        rows = []
        for number in range(1, 13):
            rows.append((self.node("label", str(number))[5], self.node("value", str(number))[5]))
        preview = self.node("preview")
        self.pictures.image = _picture(preview[3] * 2, preview[4] * 2)    # the drawn picture's shape
        self.pane.set_subject(file_info.Subject(
            "n02", "brushed_steel", "USD MaterialX", tuple(rows[:5]), tuple(rows[5:]),
            file_info.Request(file_info.KIND_IMAGE, ("/library/textures/steel.exr",))))
        QtWidgets.QApplication.processEvents()
        self.table = self.pane.table

    def _at(self, widget):
        return widget.mapTo(self.pane, QtCore.QPoint(0, 0))

    def test_drawn_info_reads_the_frame(self):
        self.assertEqual(
            {"width": 450, "header": 30, "pad": 10, "gap": 6, "icon": 20, "row": 19,
             "label_x": 12, "value_x": 109, "text_y": 2, "divider_x": 100,
             "preview_button": 15, "preview_button_pad": 8, "preview_height": 298, "drag_line": 2},
            amazetheme.drawn_info())

    def test_the_header_is_where_it_is_drawn(self):
        header, icon, name = self.node("header"), self.node("icon", "header"), self.node("text", "name")
        self.assertEqual(self.px(header[4]), self.pane.header_widget.height())
        self.assertEqual(self.px(icon[3]), self.pane._icon_label.pixmap().deviceIndependentSize().width())
        self.assertEqual(self.px(icon[1]), self._at(self.pane._icon_label).x())
        self.assertEqual(self.px(name[1]), self._at(self.pane.name_label).x())

    def test_the_preview_button_is_where_it_is_drawn(self):
        drawn, button = self.node("icon", "preview"), self.pane.preview_button
        self.assertTrue(button.isVisible())
        self.assertEqual(tuple(self.px(v) for v in drawn[1:5]),
                         (self._at(button).x(), self._at(button).y(), button.width(), button.height()))
        self.assertEqual(self.px(drawn[3]), button.iconSize().width())

    def test_the_picture_is_where_it_is_drawn_whole_and_centred(self):
        drawn, preview = self.node("preview"), self.pane.preview
        self.assertTrue(preview.isVisible())
        picture = preview.picture_rect().translated(self._at(preview))
        self.assertEqual(tuple(self.px(v) for v in drawn[1:5]),
                         (picture.x(), picture.y(), picture.width(), picture.height()))
        self.assertEqual((0, self.pane.width()), (self._at(preview).x(), preview.width()),
                         "the picture's area is not the pane's width")

    def test_the_drag_line_is_where_it_is_drawn(self):
        drawn, line = self.node("line", "drag"), self.pane.drag_line
        self.assertTrue(line.isVisible())
        self.assertEqual((self.px(drawn[2]), self.px(drawn[4])), (self._at(line).y() + line.grab, line.line))
        self.assertEqual(self.pane.width(), line.width())
        painted = QtGui.QImage(line.size(), QtGui.QImage.Format.Format_ARGB32)
        painted.fill(QtCore.Qt.GlobalColor.transparent)
        line.render(painted, QtCore.QPoint(), QtGui.QRegion(), QtWidgets.QWidget.RenderFlag.DrawChildren)
        rows = [painted.pixelColor(5, y).name() if painted.pixelColor(5, y).alpha() else None
                for y in range(line.height())]
        self.assertEqual([None] * line.grab + [amazetheme.DRAG_LINE_COLOR] * line.line + [None] * line.grab, rows)

    def test_every_drawn_row_is_where_the_table_paints_it(self):
        body = self.node("body")
        self.assertEqual(self.px(body[2]), self._at(self.table).y(), "the table does not start below the preview")
        for row in amazetheme.drawn_nodes("N02", "row"):
            index = int(amazetheme.drawn_name(row)[1]) - 1
            with self.subTest(row=index + 1):
                self.assertEqual(self.px(row[2] - body[2]), self.table.row_top(index))
                self.assertEqual(self.px(row[4]), self.table.row_top(index + 1) - self.table.row_top(index))

    def test_every_drawn_text_box_is_where_the_table_paints_it(self):
        body = self.node("body")
        for number in range(1, 13):
            label_rect, value_rect = self.table.text_rects(number - 1)
            for drawn, rect in ((self.node("label", str(number)), label_rect),
                                (self.node("value", str(number)), value_rect)):
                with self.subTest(node=drawn[0]):
                    self.assertEqual((self.px(drawn[1]), self.px(drawn[2] - body[2]), self.px(drawn[4])),
                                     (rect.x(), rect.y(), rect.height()))

    def _painted(self):
        image = QtGui.QImage(self.table.size(), QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor(amazetheme.COMMENT_PAGE_BG))    # the page the table sits on
        self.table.render(image)
        return image

    def test_the_table_is_the_apps_one_kind_of_row_list(self):
        from amaze.helpers import ui_helpers
        table = self.table
        self.assertIsInstance(table, QtWidgets.QTreeView, "the table paints its own rows")
        reference = QtWidgets.QTreeView()
        self.addCleanup(reference.deleteLater)
        ui_helpers.striped_rows(reference)
        for read in ("alternatingRowColors", "isHeaderHidden", "rootIsDecorated", "uniformRowHeights", "isAnimated"):
            with self.subTest(setting=read):
                self.assertEqual(getattr(reference, read)(), getattr(table, read)())
        self.assertTrue(table.alternatingRowColors())

    def test_the_style_stripes_the_rows_and_the_divider_is_two_pixels_on_its_x(self):
        image = self._painted()
        rows = [image.pixelColor(self.px(5), self.table.row_top(i) + self.px(1)).name() for i in range(5)]
        second = rows[1]    # the style's second row colour, whatever the palette is
        self.assertEqual([False, True, False, True, False], [row == second for row in rows],
                         "rows 2 and 4, and only they, take the style's second row colour")
        self.assertEqual(2, amazetheme.INFO_DIVIDER_WIDTH)
        line, x = self.px(amazetheme.INFO_DIVIDER_WIDTH), self.px(self.node("divider")[1])
        start = x - line // 2    # centred: 99 and 100 for a 2px line on x 100
        y = self.table.row_top(1) + self.px(1)    # the line shows on a row of the second colour
        across = [image.pixelColor(at, y).name() == second for at in range(start - 1, start + line + 1)]
        self.assertEqual([True] + [False] * line + [True], across,
                         "the divider is not %dpx centred on x %d" % (line, x))

    def test_the_table_and_the_drawn_divider_reach_the_bottom(self):
        body, drawn = self.node("body"), self.node("divider")
        self.assertEqual(self.px(body[4]), self.table.height(), "the table does not reach the pane's bottom")
        self.assertEqual(body[2] + body[4], drawn[2] + drawn[4], "the drawn divider ends above the frame's bottom")


class APictureForAnImageFile(_PaneCase):
    """Only an image file the reader can read gets a preview; everything else is the table alone."""

    def _file(self, path, key="f"):
        return file_info.Subject(key, "steel", "EXR", (("Name", "steel"),), (),
                                 file_info.request_for_file(path))

    def test_only_a_readable_image_file_has_a_picture_path(self):
        path = info_panel.InfoPanel.picture_path
        for name in ("a.exr", "a.hdr", "a.jpg", "a.jpeg", "a.png", "a.tif", "a.tiff", "a.tga", "a.tx", "a.EXR"):
            with self.subTest(name=name):
                self.assertEqual("/lib/" + name, path(self._file("/lib/" + name)))
        for name in ("a.rat", "a.pic", "a.bgeo.sc", "a.usd", "a.hip", "a.txt"):
            with self.subTest(name=name):
                self.assertEqual("", path(self._file("/lib/" + name)))
        textures = file_info.Subject("m", "steel", "Material", (), (),
                                     file_info.request_for_textures(("/lib/a.exr",)))
        self.assertEqual("", path(textures), "a material's texture got a preview")
        self.assertEqual("", path(file_info.Subject("n", "steel", "Node")))

    def test_an_image_file_is_asked_for_at_the_panes_width_in_screen_pixels(self):
        self.pane.set_subject(self._file("/lib/a.exr"))
        width = round(self.pane.body_widget.width() * theme.screen_ratio(self.pane))
        self.assertEqual([("/lib/a.exr", width)], self.pictures.asked)
        self.assertFalse(self.pane.preview.isVisible(), "a preview showed before its picture arrived")
        self.assertEqual(self.pane.header_widget.height(),
                         self.pane.table.mapTo(self.pane, QtCore.QPoint(0, 0)).y())

    def test_the_picture_arrives_and_takes_the_width_in_its_own_shape(self):
        self.pane.set_subject(self._file("/lib/a.exr"))
        self.pictures.ready.emit("/lib/a.exr", _picture(800, 200))
        QtWidgets.QApplication.processEvents()
        preview = self.pane.preview
        self.assertTrue(preview.isVisible())
        self.assertEqual(self.pane.body_widget.width(), preview.width())
        self.assertEqual(round(preview.width() * 200 / 800), preview.height(),
                         "a wide picture's area is not exactly as tall as the picture")
        self.assertEqual(self.pane.header_widget.height() + preview.height() + self.pane.drag_line.line,
                         self.pane.table.mapTo(self.pane, QtCore.QPoint(0, 0)).y())

    def test_another_files_picture_is_dropped(self):
        self.pane.set_subject(self._file("/lib/a.exr", "a"))
        self.pane.set_subject(self._file("/lib/b.exr", "b"))
        self.pictures.ready.emit("/lib/a.exr", _picture())
        self.assertIsNone(self.pane.preview.image())

    def test_the_next_selection_never_shows_the_last_picture(self):
        self.pictures.image = _picture()
        self.pane.set_subject(self._file("/lib/a.exr", "a"))
        self.assertIsNotNone(self.pane.preview.image())
        self.pictures.image = None
        for subject in (self._file("/lib/b.exr", "b"), self._file("/lib/c.bgeo.sc", "c")):
            self.pane.set_subject(subject)
            QtWidgets.QApplication.processEvents()
            with self.subTest(key=subject.key):
                self.assertIsNone(self.pane.preview.image())
                self.assertFalse(self.pane.preview.isVisible())

    def test_a_file_without_a_preview_asks_for_no_picture(self):
        self.pane.set_subject(self._file("/lib/c.rat"))
        self.assertEqual([], self.pictures.asked)
        self.assertFalse(self.pane.preview_button.isVisible(), "a button with no picture to hide")

    def test_the_button_shows_only_over_an_image_file_and_goes_with_the_selection(self):
        self.assertFalse(self.pane.preview_button.isVisible())
        self.pane.set_subject(self._file("/lib/a.exr", "a"))
        self.assertTrue(self.pane.preview_button.isVisible())
        self.pane.set_subject(self._file("/lib/c.bgeo.sc", "c"))
        self.assertFalse(self.pane.preview_button.isVisible())
        self.pane.set_subject(self._file("/lib/a.exr", "a"))
        self.pane.clear_subject()
        self.assertFalse(self.pane.preview_button.isVisible())

    def _art(self):
        return self.pane.preview_button.icon().pixmap(64, 64).toImage()

    def test_hide_preview_drops_the_picture_stops_reading_and_is_remembered(self):
        saves = []
        self.pane._preferences.save = lambda: saves.append(self.pane._preferences.info_preview)
        self.pictures.image = _picture()
        self.pane.set_subject(self._file("/lib/a.exr", "a"))
        shown_art = self._art()
        self.assertIn(amazetheme.INFO_HIDE_PREVIEW, self.pane.preview_button.toolTip())
        self.pictures.asked.clear()
        self.pane.preview_button.click()
        QtWidgets.QApplication.processEvents()
        self.assertEqual([False], saves, "the choice was not saved")
        self.assertIsNone(self.pane.preview.image())
        self.assertFalse(self.pane.preview.isVisible())
        self.assertEqual([], self.pictures.asked, "a hidden preview still read the file")
        self.assertEqual(self.pane.header_widget.height(),
                         self.pane.table.mapTo(self.pane, QtCore.QPoint(0, 0)).y())
        self.assertTrue(self.pane.preview_button.isVisible(), "no button to show it again")
        self.assertIn(amazetheme.INFO_SHOW_PREVIEW, self.pane.preview_button.toolTip())
        self.assertNotEqual(shown_art, self._art(), "both states draw the same arrow")
        self.pane.set_subject(self._file("/lib/b.exr", "b"))
        self.assertEqual([], self.pictures.asked, "the next image was read while hidden")

    def test_show_preview_reads_the_picture_again_and_is_remembered(self):
        saves = []
        self.pane._preferences.info_preview = False
        self.pane._preferences.save = lambda: saves.append(self.pane._preferences.info_preview)
        self.pictures.image = _picture()
        self.pane.set_subject(self._file("/lib/a.exr", "a"))
        self.assertIsNone(self.pane.preview.image())
        self.pane.preview_button.click()
        QtWidgets.QApplication.processEvents()
        self.assertEqual([True], saves)
        self.assertEqual(["/lib/a.exr"], [path for path, _width in self.pictures.asked])
        self.assertIsNotNone(self.pane.preview.image())
        self.assertTrue(self.pane.preview.isVisible())

    def test_the_button_art_is_the_drawn_colour(self):
        self.pane.set_subject(self._file("/lib/a.exr", "a"))
        image, wanted = self._art(), QtGui.QColor(amazetheme.INFO_BUTTON_COLOR)
        found = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())
                 if image.pixelColor(x, y).alpha() == 255}
        self.assertEqual({wanted.name()}, found)

    def _show(self, width, height):
        self.pictures.image = _picture(width, height)
        self.pane.set_subject(self._file("/lib/a.exr", "a"))
        QtWidgets.QApplication.processEvents()
        return self.pane.preview, self.pane.body_widget

    def test_a_tall_picture_gets_the_drawn_height_and_is_shown_whole_between_the_side_colour(self):
        preview, body = self._show(400, 1200)
        self.assertEqual(theme.ui_px(amazetheme.drawn_info()["preview_height"]), preview.height())
        picture = preview.picture_rect()
        self.assertEqual((round(preview.height() / 3), preview.height()), (picture.width(), picture.height()))
        self.assertEqual((preview.width() - picture.width()) // 2, picture.x(), "the picture is not centred")
        shown = preview.grab().toImage()
        self.assertEqual(QtGui.QColor(amazetheme.COMMENT_PAGE_BG).name(), shown.pixelColor(3, 3).name())

    def test_dragging_the_line_sets_the_height_and_the_release_remembers_it(self):
        saves = []
        self.pane._preferences.save = lambda: saves.append(self.pane._preferences.info_preview_height)
        preview, body = self._show(400, 1200)
        self.pane.drag_line.moved.emit(200)
        self.assertEqual(200, preview.height())
        self.assertEqual(self.pane.header_widget.height() + 200 + self.pane.drag_line.line,
                         self.pane.table.mapTo(self.pane, QtCore.QPoint(0, 0)).y())
        self.assertEqual([], saves, "the height was saved while the drag was still on")
        self.pane.drag_line.released.emit()
        self.assertEqual([200], saves)

    def test_the_line_stops_where_the_picture_touches_both_sides(self):
        preview, body = self._show(900, 600)
        most = round(preview.width() * 600 / 900)
        self.pane.drag_line.moved.emit(most + 150)
        self.assertEqual(most, preview.height(), "the area grew past the picture's full width")
        self.assertEqual(most, body.wanted_height(), "dragging past the stop was remembered")
        self.assertEqual(preview.rect(), preview.picture_rect(), "there is a band beside or above the picture")

    def _long_page(self):
        self.pictures.image = _picture(900, 600)
        rows = tuple(("Row %d" % n, "value") for n in range(80))
        self.pane.set_subject(file_info.Subject("a", "steel", "EXR", rows, (),
                                                file_info.request_for_file("/lib/a.exr")))
        QtWidgets.QApplication.processEvents()
        return self.pane.body_widget, self.pane.body_widget.scrollbar()

    def _turn(self, widget, delta):
        at = QtCore.QPointF(widget.rect().center())
        event = QtGui.QWheelEvent(at, QtCore.QPointF(widget.mapToGlobal(at.toPoint())), QtCore.QPoint(0, 0),
                                  QtCore.QPoint(0, delta), QtCore.Qt.MouseButton.NoButton,
                                  QtCore.Qt.KeyboardModifier.NoModifier, QtCore.Qt.ScrollPhase.NoScrollPhase, False)
        QtWidgets.QApplication.sendEvent(widget, event)

    def test_the_whole_page_scrolls_and_the_picture_slides_under_the_header(self):
        body, bar = self._long_page()
        preview, table = self.pane.preview, self.pane.table
        self.assertTrue(bar.isVisible(), "a page longer than the pane has no scrollbar")
        self.assertEqual(80 * table.row_height(), table.height(), "the table does not show all its rows")
        self.assertEqual(0, table.verticalScrollBar().maximum(), "the table scrolls by itself")
        self.assertEqual(preview.height() + self.pane.drag_line.line + table.height() - body.height(), bar.maximum())
        self.assertEqual(0, preview.y())
        bar.setValue(bar.maximum())
        self.assertEqual(-bar.maximum(), preview.y(), "the picture did not move with the page")
        self.assertLess(preview.geometry().bottom(), 0, "the picture is still in view at the page's end")
        self.assertEqual(body.height(), table.geometry().bottom() + 1, "the page does not end at the pane's bottom")
        self.assertEqual(0, self.pane.header_widget.y(), "the header scrolled away")

    def test_a_wheel_turn_anywhere_on_the_page_scrolls_it(self):
        body, bar = self._long_page()
        for widget in (self.pane.preview, self.pane.table.viewport(), self.pane.drag_line):
            bar.setValue(0)
            self._turn(widget, -240)
            with self.subTest(over=type(widget).__name__):
                self.assertGreater(bar.value(), 0)
        bar.setValue(0)
        self._turn(self.pane.preview, 240)    # at the top already: nothing moves
        self.assertEqual(0, bar.value())

    def test_the_scrollbar_takes_its_width_from_every_part_and_none_when_the_page_fits(self):
        body, bar = self._long_page()
        wide = body.width() - bar.width()
        self.assertEqual({wide}, {self.pane.preview.width(), self.pane.table.width(), self.pane.drag_line.width()})
        self.assertEqual(body.width() - bar.width(), bar.x())
        self.pane.set_subject(self._file("/lib/b.exr", "b"))
        QtWidgets.QApplication.processEvents()
        self.assertFalse(bar.isVisible(), "a page that fits shows a scrollbar")
        self.assertEqual(body.width(), self.pane.table.width())

    def test_another_selection_starts_at_the_top_of_the_page(self):
        body, bar = self._long_page()
        bar.setValue(bar.maximum())
        rows = tuple(("Row %d" % n, "value") for n in range(80))
        self.pane.set_subject(file_info.Subject("other", "rust", "EXR", rows, (),
                                                file_info.request_for_file("/lib/other.exr")))
        QtWidgets.QApplication.processEvents()
        self.assertEqual(0, bar.value())

    def test_the_line_is_dragged_right_while_the_page_is_scrolled(self):
        self.pictures.image = _picture(400, 1200)
        rows = tuple(("Row %d" % n, "value") for n in range(80))
        self.pane.set_subject(file_info.Subject("a", "steel", "EXR", rows, (),
                                                file_info.request_for_file("/lib/a.exr")))
        QtWidgets.QApplication.processEvents()
        body, bar = self.pane.body_widget, self.pane.body_widget.scrollbar()
        bar.setValue(100)
        self.pane.drag_line.moved.emit(150)    # the line's top as seen: 150 px under the header
        self.assertEqual(250, self.pane.preview.height())

    def test_the_line_never_takes_the_area_under_two_rows(self):
        preview, body = self._show(900, 600)
        self.pane.drag_line.moved.emit(0)
        self.assertEqual(theme.ui_px(amazetheme.INFO_PREVIEW_LEAST), preview.height())

    def test_a_wide_picture_leaves_the_remembered_height_alone(self):
        preview, body = self._show(400, 1200)
        self.pane.drag_line.moved.emit(260)
        self.pictures.image = _picture(800, 200)
        self.pane.set_subject(self._file("/lib/wide.exr", "w"))
        QtWidgets.QApplication.processEvents()
        self.assertEqual(round(preview.width() * 200 / 800), preview.height())
        self.assertEqual(260, body.wanted_height())

    def test_a_saved_height_is_the_one_the_pane_opens_with(self):
        prefs = _prefs()
        prefs.info_preview_height = 180
        pane = info_panel.InfoPanel(prefs, _Reader(), pictures=self.pictures)
        self.addCleanup(pane.deleteLater)
        pane.resize(self.pane.size())
        pane.show()
        self.pictures.image = _picture(400, 1200)
        pane.set_subject(self._file("/lib/a.exr", "a"))
        QtWidgets.QApplication.processEvents()
        self.assertEqual(180, pane.preview.height())

    def test_no_picture_means_no_line_and_the_table_under_the_header(self):
        self.pane.set_subject(self._file("/lib/a.bgeo.sc", "g"))
        QtWidgets.QApplication.processEvents()
        self.assertFalse(self.pane.drag_line.isVisible())
        self.assertFalse(self.pane.preview.isVisible())
        self.assertEqual(self.pane.header_widget.height(),
                         self.pane.table.mapTo(self.pane, QtCore.QPoint(0, 0)).y())

    def test_clearing_and_hiding_stop_the_picture_read_and_drop_the_picture(self):
        self.pictures.image = _picture()
        self.pane.set_subject(self._file("/lib/a.exr"))
        stops = self.pictures.stops
        self.pane.clear_subject()
        self.assertGreater(self.pictures.stops, stops)
        self.assertIsNone(self.pane.preview.image())
        self.pane.set_subject(self._file("/lib/a.exr"))
        self.pane.hide()
        self.assertIsNone(self.pane.preview.image())

    def test_a_pane_dragged_wider_reads_the_picture_wider_once(self):
        self.pictures.image = _picture(200, 100)
        self.pane.set_subject(self._file("/lib/a.exr"))
        self.pictures.asked.clear()
        self.pane.resize(self.pane.width() + 40, self.pane.height())
        self.pane.resize(self.pane.width() + 40, self.pane.height())
        QtWidgets.QApplication.processEvents()
        self.assertEqual([], self.pictures.asked, "the read did not wait for the drag to rest")
        test_support.pump_until(lambda: self.pictures.asked, info_panel.WIDER_READ_MS / 100)
        self.assertEqual(1, len(self.pictures.asked))

    def test_a_picture_that_is_the_whole_file_is_not_read_again(self):
        whole = _picture(200, 100)
        whole.setText(image_preview.WHOLE, "1")
        self.pictures.image = whole
        self.pane.set_subject(self._file("/lib/a.exr"))
        self.pictures.asked.clear()
        self.pane.resize(self.pane.width() + 40, self.pane.height())
        QtWidgets.QApplication.processEvents()
        self.assertFalse(self.pane._wider.isActive())


class NothingSelected(_PaneCase):

    def test_the_header_is_dimmed_and_the_table_empty(self):
        self.assertEqual(amazetheme.COMMENT_DIM_NAME, self.pane.name_label.text())
        self.assertEqual("", self.pane.type_label.text())
        self.assertEqual((), self.pane.rows())
        role = QtGui.QPalette.ColorRole.WindowText
        self.assertAlmostEqual(amazetheme.COMMENT_DIM_TEXT_OPACITY,
                               self.pane.name_label.palette().color(role).alphaF(), delta=0.01)

    def test_the_icon_is_dimmed_and_lit_with_a_subject(self):
        with mock.patch.object(info_panel.ui_helpers, "device_pixmap",
                               wraps=info_panel.ui_helpers.device_pixmap) as made:
            self.pane.clear_subject()
            self.pane.set_subject(_subject())
        swaps = [call.args[3] for call in made.call_args_list if call.args[0].endswith("icon_info.svg")]
        self.assertEqual([{amazetheme.INFO_ICON_ART_COLOR: amazetheme.COMMENT_DIM_ICON_COLOR},
                          {amazetheme.INFO_ICON_ART_COLOR: amazetheme.INFO_ICON_COLOR}], swaps)

    def test_clear_subject_stops_the_read(self):
        self.pane.set_subject(_subject())
        self.pane.clear_subject()
        self.assertEqual(1, self.reader.stops)
        self.assertEqual(amazetheme.COMMENT_DIM_NAME, self.pane.name_label.text())
        self.assertEqual((), self.pane.rows())


class ASubjectAndItsRead(_PaneCase):

    def test_the_header_and_the_rows_known_at_once(self):
        subject = _subject()
        self.pane.set_subject(subject)
        self.assertEqual(("steel", "EXR"), (self.pane.name_label.text(), self.pane.type_label.text()))
        self.assertEqual(subject.before + subject.after, self.pane.rows())
        self.assertEqual([("k1", subject.request)], self.reader.asked)
        role = QtGui.QPalette.ColorRole.WindowText
        self.assertAlmostEqual(1.0, self.pane.name_label.palette().color(role).alphaF(), delta=0.01)

    def test_a_subject_without_a_request_asks_nothing(self):
        self.pane.set_subject(_subject(request=False))
        self.assertEqual([], self.reader.asked)

    def test_the_answer_goes_between_before_and_after(self):
        subject = _subject()
        self.pane.set_subject(subject)
        self.reader.ready.emit("k1", [("Dimensions", "2048 x 2048"), ("Channels", "RGBA")])
        self.assertEqual(subject.before + (("Dimensions", "2048 x 2048"), ("Channels", "RGBA"))
                         + subject.after, self.pane.rows())

    def test_an_answer_for_an_older_key_is_dropped(self):
        self.pane.set_subject(_subject("k1"))
        second = _subject("k2", before=(("Name", "rust"),))
        self.pane.set_subject(second)
        self.reader.ready.emit("k1", [("Dimensions", "2048 x 2048")])
        self.assertEqual(second.before + second.after, self.pane.rows())

    def test_the_same_subject_twice_asks_once(self):
        self.pane.set_subject(_subject())
        self.pane.set_subject(_subject())
        self.assertEqual(1, len(self.reader.asked))

    def test_hiding_stops_the_read_and_showing_asks_again(self):
        self.pane.set_subject(_subject())
        self.pane.hide()
        self.assertEqual(1, self.reader.stops, "hiding did not stop the read")
        self.pane.set_subject(_subject("k3"))
        self.assertEqual(1, len(self.reader.asked), "the hidden pane asked for a read")
        self.pane.show()
        self.pane.set_subject(_subject())
        self.assertEqual(["k1", "k1"], [key for key, _request in self.reader.asked],
                         "the shown pane did not read the same subject again")

    def test_showing_emits_shown(self):
        self.pane.hide()
        seen = []
        self.pane.shown.connect(lambda: seen.append(True))
        self.pane.show()
        self.assertEqual([True], seen)


class ALongValue(_PaneCase):

    LONG = "/Projects/library/textures/" + "metal/" * 30 + "brushed_steel_basecolor.exr"

    def setUp(self):
        super().setUp()
        self.pane.set_subject(_subject(after=(("Folder", self.LONG), ("Size", "840 KB"))))
        QtWidgets.QApplication.processEvents()
        self.table = self.pane.table

    def _centre(self, index):
        return QtCore.QPoint(self.table.width() // 2,
                             (self.table.row_top(index) + self.table.row_top(index + 1)) // 2)

    def test_it_is_elided_in_the_middle_and_keeps_both_ends(self):
        shown = self.table.shown_text(1)[1]
        self.assertNotEqual(self.LONG, shown)
        self.assertIn("…", shown)
        self.assertTrue(shown.startswith("/Pro") and shown.endswith(".exr"), shown)

    def test_its_row_has_the_whole_value_as_a_tooltip_a_short_one_none(self):
        at = lambda index: self.table.viewport().mapFrom(self.table, self._centre(index))    # noqa: E731
        self.assertEqual(self.LONG, self.table.tooltip_at(at(1)))
        self.assertEqual("", self.table.tooltip_at(at(2)), "a value that fits has a tooltip")
        self.assertEqual("", self.table.tooltip_at(at(0)))

    def test_the_tooltip_event_shows_it(self):
        point = self._centre(1)
        event = QtGui.QHelpEvent(QtCore.QEvent.Type.ToolTip, point, self.table.mapToGlobal(point))
        QtWidgets.QApplication.sendEvent(self.table, event)
        self.addCleanup(QtWidgets.QToolTip.hideText)
        self.assertIn("brushed_steel_basecolor.exr", QtWidgets.QToolTip.text())

    def test_the_table_takes_no_focus_and_no_menu(self):
        self.assertEqual(QtCore.Qt.FocusPolicy.NoFocus, self.table.focusPolicy())
        self.assertEqual(QtCore.Qt.FocusPolicy.NoFocus, self.pane.body_widget.focusPolicy())
        self.assertEqual(QtCore.Qt.ContextMenuPolicy.NoContextMenu, self.table.contextMenuPolicy())


class _Context:
    """A stand-in context: the panel reads only these members for the info pane."""

    def __init__(self, selection, takes_info=True):
        self.takes_info = takes_info
        self._selection = selection
        self.info_subject = mock.Mock(return_value=_subject("one", request=False))
        self.info_subject_for = mock.Mock(return_value=_subject("many", request=False))

    def grid_selection_model(self):
        return self._selection


class TheInfoPaneOnThePanel(unittest.TestCase):
    """The real panel: the toggle, one pane at a time, the selection, the View menu."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        panel = self.panel
        self.reader = _Reader()
        real = panel.info_panel._reader
        panel.info_panel._reader = self.reader
        self.addCleanup(setattr, panel.info_panel, "_reader", real)
        self.addCleanup(panel.btn_notes.setChecked, False)
        self.addCleanup(panel.btn_info.setChecked, False)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()

    def test_info_on_turns_comments_off_and_back(self):
        panel = self.panel
        self.assertTrue(panel.info_panel.isHidden(), "the info pane is open before its button was pressed")
        panel.btn_notes.setChecked(True)
        with mock.patch.object(panel, "active_section", return_value=None):
            panel.btn_info.setChecked(True)
        self.assertFalse(panel.info_panel.isHidden(), "the info button did not open its pane")
        self.assertTrue(panel.notes_panel.isHidden(), "the comments pane stayed open")
        self.assertFalse(panel.btn_notes.isChecked())
        self.assertEqual((False, True), (panel.prefs.show_notes, panel.prefs.show_info))
        panel.btn_notes.setChecked(True)
        self.assertFalse(panel.notes_panel.isHidden(), "the comments button did not open its pane")
        self.assertTrue(panel.info_panel.isHidden(), "the info pane stayed open")
        self.assertFalse(panel.btn_info.isChecked())
        self.assertEqual((True, False), (panel.prefs.show_notes, panel.prefs.show_info))

    def test_the_page_is_in_the_one_side_pane_which_does_not_stretch(self):
        pane = self.panel.side_pane
        splitter = pane.parentWidget()
        self.assertEqual(-1, splitter.indexOf(self.panel.info_panel), "the info page has its own place")
        self.assertTrue(pane.isAncestorOf(self.panel.info_panel))
        stretch = [splitter.widget(i).sizePolicy().horizontalStretch() for i in range(splitter.count())]
        self.assertEqual(0, stretch[splitter.indexOf(pane)])
        self.assertEqual(1, stretch.count(1), "the grid is not the one flexible pane: %s" % stretch)

    def test_the_button_art_is_info_icon_color_while_open(self):
        panel = self.panel
        panel._sync_info_button_pixmaps()
        art = QtGui.QColor(amazetheme.INFO_ICON_ART_COLOR).name()
        lit = QtGui.QColor(amazetheme.INFO_ICON_COLOR).name()

        def seen_in(state):
            image = panel.btn_info._pms[state].toImage()
            return {image.pixelColor(x, y).name() for x in range(image.width())
                    for y in range(image.height()) if image.pixelColor(x, y).alpha() == 255}

        for checked in (False, True):
            for hovered in (False, True):
                with self.subTest(checked=checked, hovered=hovered):
                    seen = seen_in((checked, hovered))
                    self.assertIn(lit if checked else art, seen)
                    self.assertNotIn(art if checked else lit, seen)

    def _select(self, rows):
        selection = self.panel.thumblist.selectionModel()
        selection.clearSelection()
        model = self.panel.thumblist.model()
        self.assertGreater(model.rowCount(), max(rows), "the fixture has too few tiles")
        for row in rows:
            selection.select(model.index(row, 0),
                             QtCore.QItemSelectionModel.SelectionFlag.Select
                             | QtCore.QItemSelectionModel.SelectionFlag.Rows)

    def _open_with(self, context):
        patcher = mock.patch.object(self.panel, "active_section", return_value=context)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.panel.thumblist.selectionModel().clearSelection)
        self.panel.btn_info.setChecked(True)

    def test_one_selected_row_asks_info_subject(self):
        context = _Context(self.panel.thumblist.selectionModel())
        self._open_with(context)
        self._select([1])    # the selection model's own signal, as a keyboard or rubber band sends
        context.info_subject.assert_called()
        self.assertEqual(1, context.info_subject.call_args.args[0].row())
        context.info_subject_for.assert_not_called()
        self.assertEqual("one", self.panel.info_panel._subject.key)

    def test_two_selected_rows_ask_info_subject_for(self):
        context = _Context(self.panel.thumblist.selectionModel())
        self._open_with(context)
        self._select([1, 2])
        rows = sorted(index.row() for index in context.info_subject_for.call_args.args[0])
        self.assertEqual([1, 2], rows)
        self.assertEqual("many", self.panel.info_panel._subject.key)

    def test_a_context_without_info_clears(self):
        context = _Context(self.panel.thumblist.selectionModel(), takes_info=False)
        self._open_with(context)
        self._select([1])
        context.info_subject.assert_not_called()
        self.assertEqual(amazetheme.COMMENT_DIM_NAME, self.panel.info_panel.name_label.text())

    def test_a_hidden_pane_asks_nothing(self):
        context = _Context(self.panel.thumblist.selectionModel())
        with mock.patch.object(self.panel, "active_section", return_value=context):
            self._select([1])
            self.panel.thumblist.selectionModel().clearSelection()
        context.info_subject.assert_not_called()

    def test_the_view_menus_first_item_generates_a_material(self):
        from amaze.panel import panel as panel_mod
        menu = self.panel.ui.findChild(QtWidgets.QMenu, "menuView")
        first = menu.actions()[0]
        self.assertEqual("Generate Material", first.text())
        self.assertEqual("Gallery Import (.gal)", menu.actions()[1].text())
        with mock.patch.object(panel_mod.nodes, "karma_destination",
                               return_value=None) as destination, \
                mock.patch.object(panel_mod.hou, "ui", None, create=True):
            first.trigger()    # the generate function's first step: where the material would go
        destination.assert_called_once_with(self.panel.prefs)


if __name__ == "__main__":
    unittest.main()
