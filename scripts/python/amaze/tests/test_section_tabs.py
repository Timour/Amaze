"""The tab strip matches frame S01: height, tray, chips and bottom line. ▸r/tabs-from-frame"""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze import amazetheme  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401


class TheTabStripMatchesItsDesignFrame(unittest.TestCase):
    """Every tab, the tray and the strip are placed where S01 draws them, in any font."""

    def setUp(self):
        self.px = theme.ui_px
        self.frame = amazetheme.DIALOG_LAYOUT["S01"]
        self.chips = sorted(amazetheme.drawn_nodes("S01", "chip"), key=lambda n: n[1])
        self.boxes = amazetheme.drawn_by_owner("S01", "text box")
        labels = {key: n[5] for key, n in amazetheme.drawn_by_owner("S01", "label").items()}
        self.tray = amazetheme.drawn_node("S01", "tray")
        self.line = amazetheme.drawn_node("S01", "Line 3")
        self.keys = [amazetheme.drawn_name(c)[1] for c in self.chips]
        self.bar = ui_helpers.SectionTabBar([(k, labels[k]) for k in self.keys])
        self.bar.resize(self.px(self.frame["frame"][0]), self.bar.HEIGHT)
        self.addCleanup(self.bar.deleteLater)

    def test_the_frame_is_one_strip_the_code_can_follow(self):
        """Tabs edge to edge at one gap, one pad, centred in the tray; the tray its tabs' width."""
        gaps = {b[1] - (a[1] + a[3]) for a, b in zip(self.chips, self.chips[1:])}
        self.assertEqual(1, len(gaps), "the tabs sit at gaps %s" % sorted(gaps))
        pads = {self.boxes[k][1] - c[1] for k, c in zip(self.keys, self.chips)}
        self.assertEqual(1, len(pads), "the tabs pad their text by %s" % sorted(pads))
        for key, chip in zip(self.keys, self.chips):
            box = self.boxes[key]
            with self.subTest(tab=key):
                self.assertEqual(box[1] - chip[1], (chip[1] + chip[3]) - (box[1] + box[3]),
                                 "the text box is not centred in its tab")
                self.assertEqual(chip[2] - self.tray[2], (self.tray[4] - chip[4]) / 2,
                                 "the tab is not centred in the tray")
        inset = self.chips[0][1] - self.tray[1]
        self.assertEqual(self.tray[1] + self.tray[3], self.chips[-1][1] + self.chips[-1][3] + inset,
                         "the tray does not end one inset past the last tab")
        self.assertEqual(self.line[2] - 0.5, self.tray[2] + self.tray[4],
                         "the tray does not end where the bottom line starts")
        self.assertEqual((0, self.frame["frame"][0], self.frame["frame"][1] - 0.5),
                         (self.line[1], self.line[3], self.line[2]),
                         "the line is not the strip's bottom pixel row, the full width")

    def test_the_strip_is_its_drawn_height(self):
        height = self.px(self.frame["frame"][1])
        self.assertEqual((height, height),
                         (self.bar.minimumHeight(), self.bar.maximumHeight()))

    def test_the_strip_is_29_high_as_drawn(self):
        self.assertEqual((840, 29), tuple(self.frame["frame"]))
        self.assertEqual(self.px(29), self.bar.height())

    def test_the_bottom_pixel_row_is_the_line_across_the_full_width(self):
        line_px = self.px(1)
        image = self.bar.grab().toImage()
        scale = image.width() // self.bar.width()
        want = QtGui.QColor(amazetheme.TAB_STRIP_LINE).name()
        self.assertEqual("#1b1b1b", want)
        for row in range(image.height() - line_px * scale, image.height()):
            with self.subTest(row=row):
                self.assertEqual({want}, {image.pixelColor(x, row).name()
                                          for x in range(image.width())})
        above = image.height() - line_px * scale - 1
        self.assertEqual({self.bar.STRIP_COLOR.name()},
                         {image.pixelColor(x, above).name()
                          for x in range(image.width() - 10, image.width())},
                         "the line is thicker than one pixel")

    def test_every_tab_is_where_it_is_drawn(self):
        rects = [rect for _segment, rect in self.bar._chip_rects()]
        self.assertEqual(len(self.chips), len(rects))
        self.assertEqual(self.px(self.chips[0][1]), rects[0].x(), "the first tab is not at its drawn x")
        metrics = self.bar.fontMetrics()
        pad = self.px(self.boxes[self.keys[0]][1] - self.chips[0][1])
        gap = self.px(self.chips[1][1] - (self.chips[0][1] + self.chips[0][3]))
        for (key, label), rect in self.bar._chip_rects():
            chip = self.chips[self.keys.index(key)]
            with self.subTest(tab=key):
                self.assertEqual((self.px(chip[2]), self.px(chip[4])), (rect.y(), rect.height()))
                self.assertEqual(2 * pad, rect.width() - metrics.horizontalAdvance(label),
                                 "the tab does not pad its label by the drawn pad")
        for a, b in zip(rects, rects[1:]):
            self.assertEqual(gap, b.x() - (a.x() + a.width()), "two tabs have another gap")

    def test_the_tray_is_where_it_is_drawn(self):
        tray = self.bar._tray_rect()
        last = self.bar._chip_rects()[-1][1]
        inset = self.px(self.chips[0][1] - self.tray[1])
        self.assertEqual((self.px(self.tray[1]), self.px(self.tray[2]), self.px(self.tray[4])),
                         (tray.x(), tray.y(), tray.height()))
        self.assertEqual(last.x() + last.width() + inset, tray.x() + tray.width(),
                         "the tray does not end one inset past the last tab")


class DrawRingMatchesTheHandWrittenRingsTest(unittest.TestCase):
    """`draw_ring` draws what each of the three hand-written chip rings drew, at any width."""

    RECT = QtCore.QRectF(3, 4, 30, 20)
    RING_COLOR = QtGui.QColor("#43506d")
    FILL = QtGui.QColor("#2d4075")
    WIDTHS = (1, 1.0, 1.25, 1.5, 2)

    @staticmethod
    def _canvas():
        image = QtGui.QImage(40, 30, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        return image, painter

    def _drawn_by_draw_ring(self, width, radius, fill):
        image, painter = self._canvas()
        try:
            ui_helpers.draw_ring(painter, self.RECT, self.RING_COLOR, width, radius, fill)
        finally:
            painter.end()
        return image

    def test_the_tab_ring_and_the_toolbar_chip_ring_over_its_fill(self):
        for radius, fill in ((4, QtCore.Qt.BrushStyle.NoBrush), (5, self.FILL)):
            for width in self.WIDTHS:
                with self.subTest(radius=radius, width=width):
                    want, painter = self._canvas()
                    half = width / 2.0
                    painter.setPen(QtGui.QPen(self.RING_COLOR, width))
                    painter.setBrush(fill)
                    painter.drawRoundedRect(
                        self.RECT.adjusted(half, half, -half, -half), radius, radius)
                    painter.end()
                    self.assertEqual(want, self._drawn_by_draw_ring(width, radius, fill))


class BothChipRingsAreOneWholePixelWidth(unittest.TestCase):
    """The tab ring and the toolbar chip ring share one width; an int `ui_px` rounds at any scale."""

    def test_the_tab_ring_is_the_toolbar_chip_ring(self):
        from unittest import mock
        widths = []
        with mock.patch.object(ui_helpers, "draw_ring",
                               lambda _painter, _rect, _ink, width, *_rest:
                               widths.append(width)):
            ui_helpers.draw_chip(None, QtCore.QRectF(0, 0, 20, 20),
                                 QtGui.QColor("#000000"),
                                 QtGui.QColor("#ffffff"))
        tab = ui_helpers.SectionTabBar.CHIP_RING_W
        self.assertEqual([tab], widths)
        self.assertIsInstance(widths[0], int, "the toolbar chip ring is not whole pixels")
        self.assertIsInstance(tab, int, "the tab ring is not whole pixels")


if __name__ == "__main__":
    unittest.main()
