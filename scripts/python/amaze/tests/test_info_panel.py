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
             "first_row": 0, "label_x": 12, "value_x": 109, "text_y": 2, "divider_x": 100},
            amazetheme.drawn_info())

    def test_the_pane_asks_for_the_drawn_width_under_the_comments_key(self):
        self.assertEqual(self.px(450), self.pane.sizeHint().width())
        self.pane._preferences.notes_panel_width = 333
        self.assertEqual(333, self.pane.sizeHint().width(), "the width is not the shared one")

    def test_the_header_is_where_it_is_drawn(self):
        header, icon, name = self.node("header"), self.node("icon", "header"), self.node("text", "name")
        self.assertEqual(self.px(header[4]), self.pane.header_widget.height())
        self.assertEqual(self.px(icon[3]), self.pane._icon_label.pixmap().deviceIndependentSize().width())
        self.assertEqual(self.px(icon[1]), self._at(self.pane._icon_label).x())
        self.assertEqual(self.px(name[1]), self._at(self.pane.name_label).x())

    def test_the_preview_is_where_it_is_drawn(self):
        drawn, preview = self.node("preview"), self.pane.preview
        self.assertTrue(preview.isVisible())
        self.assertEqual(tuple(self.px(v) for v in drawn[1:5]),
                         (self._at(preview).x(), self._at(preview).y(), preview.width(), preview.height()))

    def test_every_drawn_row_is_where_the_table_paints_it(self):
        body = self.node("body")
        self.assertEqual(self.px(body[2]), self._at(self.table).y(), "the table does not start below the preview")
        for row in amazetheme.drawn_nodes("N02", "row"):
            index = int(amazetheme.drawn_name(row)[1]) - 1
            with self.subTest(row=index + 1):
                self.assertEqual(self.px(row[2] - body[2]), self.table._row_top(index))
                self.assertEqual(self.px(row[4]), self.table._row_top(index + 1) - self.table._row_top(index))

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
        self.table.render(image)
        return image

    def test_odd_rows_are_filled_and_the_divider_is_two_pixels_on_its_x(self):
        image = self._painted()
        row_bg, page = (QtGui.QColor(c).name() for c in (amazetheme.INFO_ROW_BG, amazetheme.COMMENT_PAGE_BG))
        divider = QtGui.QColor(amazetheme.INFO_DIVIDER).name()
        first, second = (self.table._row_top(i) + self.px(1) for i in (0, 1))
        x = self.px(self.node("divider")[1])
        self.assertEqual(row_bg, image.pixelColor(self.px(5), first).name(), "row 1 is not filled")
        self.assertEqual(page, image.pixelColor(self.px(5), second).name(), "row 2 is filled")
        line = self.px(amazetheme.INFO_DIVIDER_WIDTH)
        self.assertEqual(2, amazetheme.INFO_DIVIDER_WIDTH)
        start = x - line // 2    # centred: 99 and 100 for a 2px line on x 100
        across = [image.pixelColor(at, first).name() for at in range(start - 1, start + line + 1)]
        self.assertEqual([row_bg] + [divider] * line + [row_bg], across,
                         "the divider is not %dpx centred on x %d" % (line, x))


    def test_the_filled_rows_and_the_divider_run_on_to_the_bottom(self):
        image = self._painted()
        row_bg, page = (QtGui.QColor(c).name() for c in (amazetheme.INFO_ROW_BG, amazetheme.COMMENT_PAGE_BG))
        divider = QtGui.QColor(amazetheme.INFO_DIVIDER).name()
        body, x = self.node("body"), self.px(self.node("divider")[1])
        self.assertEqual(self.px(body[4]), self.table.height(), "the table does not reach the pane's bottom")
        below = [row for row in amazetheme.drawn_nodes("N02", "row")
                 if int(amazetheme.drawn_name(row)[1]) > len(self.table.rows())]
        self.assertEqual(2, len(below), "the frame draws two filled rows below the last one")
        for row in below:
            top = self.px(row[2] - body[2])
            with self.subTest(row=row[0]):
                self.assertEqual(row_bg, image.pixelColor(self.px(5), top + self.px(1)).name())
                self.assertEqual(page, image.pixelColor(self.px(5), top + self.px(row[4]) + self.px(1)).name(),
                                 "the row after it is filled too")
                self.assertEqual(divider, image.pixelColor(x - 1, top + self.px(1)).name(),
                                 "the divider stops above this row")
        drawn = self.node("divider")
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
        width = round(self.pane.body_widget.viewport().width() * theme.screen_ratio(self.pane))
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
        self.assertEqual(self.pane.body_widget.viewport().width(), preview.width())
        self.assertEqual(round(preview.width() * 200 / 800), preview.height())
        self.assertEqual(self.pane.header_widget.height() + preview.height(),
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
        swaps = [call.args[3] for call in made.call_args_list]
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
                             (self.table._row_top(index) + self.table._row_top(index + 1)) // 2)

    def test_it_is_elided_in_the_middle_and_keeps_both_ends(self):
        shown = self.table.shown_text(1)[1]
        self.assertNotEqual(self.LONG, shown)
        self.assertIn("…", shown)
        self.assertTrue(shown.startswith("/Pro") and shown.endswith(".exr"), shown)

    def test_its_row_has_the_whole_value_as_a_tooltip_a_short_one_none(self):
        self.assertEqual(self.LONG, self.table.tooltip_at(self._centre(1)))
        self.assertEqual("", self.table.tooltip_at(self._centre(2)), "a value that fits has a tooltip")
        self.assertEqual("", self.table.tooltip_at(self._centre(0)))

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

    def test_the_pane_is_in_the_splitter_after_comments_and_does_not_stretch(self):
        splitter = self.panel.notes_panel.parentWidget()
        info = splitter.indexOf(self.panel.info_panel)
        self.assertEqual(splitter.indexOf(self.panel.notes_panel) + 1, info)
        stretch = [splitter.widget(i).sizePolicy().horizontalStretch() for i in range(splitter.count())]
        self.assertEqual(0, stretch[info])
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
