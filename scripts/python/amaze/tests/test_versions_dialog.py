"""The Versions dialog (D01) checked against its design frame, and the shared widgets it uses."""

import contextlib
import inspect
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

import amaze  # noqa: E402
from amaze import amazetheme  # noqa: E402
from amaze.dialogs import base_dialog, versions_dialog  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401
from amaze.tests.test_library_list import (colours_down, filled_rows_expected,  # noqa: E402
                                           painted_texts)

LISTED = [    # the stored version list's order: oldest first
    {"n": 1, "name": "Version 1", "date": "2026-10-21 09:00"},
    {"n": 2, "name": "Look Development test", "date": "2026-10-22 10:30"},
    {"n": 3, "name": "", "date": "2026-10-23 11:45"},
]


def _dialog(case, active=2):
    dialog = versions_dialog.VersionsDialog("brushed_steel", LISTED, active)
    case.addCleanup(dialog.deleteLater)
    dialog.show()
    case.addCleanup(dialog.hide)
    QtWidgets.QApplication.processEvents()
    return dialog


class _ScreenAt(QtWidgets.QWidget):
    """A parent with a set device pixel ratio; offscreen Qt has one screen at 1.0 ▸r/screen-dpr"""

    def __init__(self, ratio) -> None:
        super().__init__()
        self._ratio = ratio

    def devicePixelRatioF(self):
        return self._ratio


class TheIconIsNotClipped(unittest.TestCase):
    """A viewBox tight to the paths cuts off the stroke's points at top and bottom."""

    def test_the_top_and_bottom_are_POINTS_not_flat_cuts(self):
        """A clip is a flat cut: the glyph's first and last rows are narrow points."""
        path = os.path.join(os.path.dirname(amaze.__file__), "ui",
                            "icon_versions_dialog.svg")
        image = ui_helpers.render_svg_pixmap(path, 120).toImage()

        def painted_width(y):
            xs = [x for x in range(image.width())
                  if image.pixelColor(x, y).alpha() > 30]
            return (xs[-1] - xs[0] + 1) if xs else 0

        rows = [y for y in range(image.height()) if painted_width(y)]
        self.assertTrue(rows, "the glyph rendered nothing")
        widest = max(painted_width(y) for y in rows)
        for edge, y in (("top", rows[0]), ("bottom", rows[-1])):
            self.assertLess(
                painted_width(y), widest * 0.5,
                "the %s row spans %s of a %s-wide glyph - that is a "
                "flat cut, so the stroke is being clipped"
                % (edge, painted_width(y), widest))


class TheVersionsWindowMatchesItsDesignFrame(unittest.TestCase):
    """D01's window, list, buttons and rows have the positions and sizes the design frame gives."""

    def setUp(self):
        self.dialog = _dialog(self)

    def _box(self, widget):
        corner = widget.mapTo(self.dialog, widget.rect().topLeft())
        return (corner.x(), corner.y(), widget.width(), widget.height())

    def test_the_window_is_the_drawn_frame(self):
        self.assertEqual(tuple(theme.ui_px(n) for n in amazetheme.DIALOG_LAYOUT["D01"]["frame"]),
                         (self.dialog.width(), self.dialog.height()))

    def test_the_list_and_the_buttons_are_placed_where_drawn(self):
        boxes = amazetheme.drawn_boxes("D01")
        for widget, key in ((self.dialog._list, ("QListWidget", None)),
                            (self.dialog._select, ("QPushButton", amazetheme.BTN_SELECT)),
                            (self.dialog._cancel, ("QPushButton", amazetheme.BTN_CANCEL))):
            drawn = boxes[key][0] if key[1] is None else boxes[key]
            with self.subTest(widget=key):
                self.assertEqual(tuple(theme.ui_px(n) for n in drawn), self._box(widget))

    def test_no_band_sits_over_the_list_and_the_title_names_the_material(self):
        self.assertIsNone(self.dialog.findChild(QtWidgets.QLabel, "amaze_header_band_text"))
        self.assertEqual("brushed_steel", self.dialog.windowTitle())

    def test_each_row_is_19_px_from_the_list_top(self):
        names = sorted(n[2] for n in amazetheme.DIALOG_LAYOUT["D01"]["nodes"]
                       if n[0] == "QListWidget ▸ item")
        self.assertEqual(19, names[1] - names[0], "premise: the frame draws 19 px rows")
        view = self.dialog._list
        for row in range(view.count()):
            with self.subTest(row=row):
                rect = view.visualItemRect(view.item(row))
                self.assertEqual((0, theme.ui_px(19 * row), view.viewport().width(),
                                  theme.ui_px(19)),
                                 (rect.x(), rect.y(), rect.width(), rect.height()))

    def test_the_name_and_the_day_sit_where_the_frame_draws_them(self):
        px = theme.ui_px
        for row in range(self.dialog._list.count()):
            name, day = painted_texts(self.dialog._list, row)
            with self.subTest(row=row):
                self.assertEqual((px(19 - 8), px(19 * row + 2), px(15)),
                                 (name[0], name[1], name[3]))
                self.assertEqual((px(19 * row + 2), px(15)), (day[1], day[3]))
                self.assertEqual(px(250 - 8), day[0] + day[2],
                                 "the day does not end where the frame's dates end")

    def test_the_filled_rows_and_the_bar_run_to_the_bottom_of_the_list(self):
        view = self.dialog._list    # the active version, the second row, is selected
        self.assertEqual(filled_rows_expected("D01", view.viewport().height(), 1,
                                              amazetheme.D01_SELECTED_BACKGROUND),
                         colours_down(view, view.viewport().width() - 2))
        self.assertEqual(("#383838", "#2d2d2d"), (amazetheme.FILLED_ROW, amazetheme.LIST_BACKGROUND))

    def test_the_filled_rows_follow_the_rows_when_the_list_scrolls(self):
        many = [{"n": n, "name": "Version %d" % n, "date": "2026-10-21 09:00"}
                for n in range(1, 41)]
        dialog = versions_dialog.VersionsDialog("brushed_steel", many, 1)    # the last row
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.addCleanup(dialog.hide)
        QtWidgets.QApplication.processEvents()
        view = dialog._list
        self.assertGreater(view.verticalScrollBar().value(), 0, "premise: the list is scrolled")
        column = colours_down(view, view.viewport().width() - 2)
        filled, ground = (QtGui.QColor(c).name()
                          for c in (amazetheme.FILLED_ROW, amazetheme.LIST_BACKGROUND))
        for row in range(view.count() - 1):    # the last one is the picked, green bar
            rect = view.visualItemRect(view.item(row))
            if rect.top() >= 0:
                with self.subTest(row=row):
                    self.assertEqual(filled if row % 2 == 0 else ground, column[rect.top()])

    def test_the_picked_row_is_a_green_bar_over_the_whole_row(self):
        green = QtGui.QColor(amazetheme.D01_SELECTED_BACKGROUND).name()
        px, view = theme.ui_px, self.dialog._list
        for x in (0, view.viewport().width() - 1):
            with self.subTest(x=x):
                column = colours_down(view, x)
                self.assertEqual([green] * px(19), column[px(19):px(38)])
                self.assertNotEqual(green, column[px(19) - 1])
                self.assertNotEqual(green, column[px(38)])
        self.assertEqual("#297d54", green)

    def test_the_text_on_the_green_bar_keeps_its_usual_colours(self):
        plain = [text[5] for text in painted_texts(self.dialog._list, 1)]
        picked = [text[5] for text in painted_texts(self.dialog._list, 1, selected=True)]
        self.assertEqual([theme.color("text_bright").name(), theme.color("text").name()], plain)
        self.assertEqual(plain, picked)


class TheDayIsNeverCut(unittest.TestCase):
    """The date has a fixed short format and gets its full width, even when the font is wider."""

    def test_every_row_draws_its_whole_date(self):
        dialog = _dialog(self)
        drawn = []

        class _Recorder(QtGui.QPainter):
            def drawText(self, *args):
                drawn.append(args[-1])
                return super().drawText(*args)

        surface = QtGui.QPixmap(dialog._list.viewport().size())
        painter = _Recorder(surface)
        option = QtWidgets.QStyleOptionViewItem()
        option.font = dialog._list.font()
        delegate = dialog._list.itemDelegate()
        try:
            for row in range(dialog._list.count()):
                option.rect = dialog._list.visualItemRect(dialog._list.item(row))
                delegate.paint(painter, option, dialog._list.model().index(row, 0))
        finally:
            painter.end()
        for day in ("2026-10-23", "2026-10-22", "2026-10-21"):
            self.assertIn(day, drawn, "a row's date was cut short")


class TheListShowsTheSavedVersions(unittest.TestCase):
    """Newest first, each row shows name and save date; the active version is selected on open."""

    def test_the_rows_are_newest_first_with_the_day_saved(self):
        dialog = _dialog(self)
        rows = [(dialog._list.item(i).text(),
                 dialog._list.item(i).data(versions_dialog.DATE_ROLE))
                for i in range(dialog._list.count())]
        self.assertEqual([("Version 3", "2026-10-23"),
                          ("Look Development test", "2026-10-22"),
                          ("Version 1", "2026-10-21")], rows)

    def test_the_active_version_is_picked_at_open(self):
        picked = _dialog(self, active=1)._list.selectedItems()
        self.assertEqual([1], [item.data(versions_dialog.NUMBER_ROLE) for item in picked])


class SelectAndCancel(unittest.TestCase):
    """Select sets `chosen` to the selected version's number; Cancel sets it to the active one."""

    def test_select_accepts_with_the_picked_version(self):
        dialog = _dialog(self)
        dialog._list.setCurrentRow(0)
        dialog._select.click()
        self.assertEqual(QtWidgets.QDialog.DialogCode.Accepted, dialog.result())
        self.assertEqual(3, dialog.chosen)

    def test_cancel_keeps_the_active_version(self):
        dialog = _dialog(self)
        dialog._list.setCurrentRow(0)
        dialog._cancel.click()
        self.assertEqual(QtWidgets.QDialog.DialogCode.Rejected, dialog.result())
        self.assertEqual(2, dialog.chosen)


class ADropdownIsAsWideAsItsBox(unittest.TestCase):
    """Qt sizes a dropdown to its widest item; ours keeps the box's width ▸r/combo-popup-width"""

    LONG = "A category name a great deal longer than the box"

    def _shown(self, combo):
        holder = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(combo)
        combo.setFixedWidth(118)
        holder.resize(400, 40)
        holder.show()
        self.addCleanup(holder.close)
        combo.addItem("Dark")
        combo.addItem(self.LONG)
        combo.showPopup()
        self.addCleanup(combo.hidePopup)
        _app.processEvents()
        return combo.view().window()

    def test_the_designed_one_holds_the_box_width(self):
        popup = self._shown(ui_helpers.DesignedComboBox())
        self.assertEqual(
            118, popup.width(),
            "the dropdown is not the width of the box it drops from")


class ADialogIsSizedTheWayTheHostSizesEverything(unittest.TestCase):
    """One logical size per Houdini UI scale, whatever the screen's ratio. ▸r/houdini-ui-scale"""

    PROFILES = (    # (machine, device ratio, UI scale, frame width), the widths written out
        ("retina mac",       2.0, 1.0, 269),
        ("plain linux",      1.0, 1.0, 269),
        ("a 2.0 UI scale",   1.0, 2.0, 538),
    )

    @contextlib.contextmanager
    def _at(self, scale):
        real = theme.UI_SCALE
        theme.UI_SCALE = scale
        try:
            yield
        finally:
            theme.UI_SCALE = real

    def test_the_frame_is_one_size_per_UI_SCALE_on_every_machine(self):
        for machine, ratio, scale, expected in self.PROFILES:
            with self.subTest(machine=machine):
                parent = _ScreenAt(ratio)
                self.addCleanup(parent.deleteLater)
                with self._at(scale):
                    dialog = versions_dialog.VersionsDialog("brushed_steel", LISTED, 2,
                                                            parent=parent)
                    self.addCleanup(dialog.deleteLater)
                    dialog.adjustSize()
                    self.assertEqual(
                        expected, dialog.width(),
                        "%s: the dialog is not the size Houdini's own scale "
                        "gives it" % machine)


class NothingThatSizesReadsTheScreen(unittest.TestCase):
    """No sizing path in the dialog shell reads a device ratio. ▸r/houdini-ui-scale"""

    SIZING_READS = ("screen_ratio", "devicePixelRatio", "devicePixelRatioF")

    def test_asset_dialog_and_versions_dialog_read_no_screen(self):
        for name, source in (("AssetDialog", inspect.getsource(base_dialog.AssetDialog)),
                             ("versions_dialog", inspect.getsource(versions_dialog))):
            with self.subTest(source=name):
                self.assertIn("class ", source, "premise: the scanned source holds a class")
                for spelling in self.SIZING_READS:
                    self.assertNotIn(
                        spelling, source,
                        "%s sizes from the screen: Houdini's scale is fixed at "
                        "startup, and a live ratio renders 2x chrome at dpr 1.0" % name)


if __name__ == "__main__":
    unittest.main()
