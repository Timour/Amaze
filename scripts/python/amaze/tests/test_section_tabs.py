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
import amaze  # noqa: E402
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
        self.icons = amazetheme.drawn_by_owner("S01", "icon")
        self.keys = [amazetheme.drawn_name(c)[1] for c in self.chips]
        self.bar = ui_helpers.SectionTabBar([(k, labels[k]) for k in self.keys])
        self.bar.resize(self.px(self.frame["frame"][0]), self.bar.HEIGHT)
        self.addCleanup(self.bar.deleteLater)

    def test_the_frame_is_one_strip_the_code_can_follow(self):
        """Tabs at one gap, icon then name between one pad on each side; the tray its tabs' width."""
        gaps = {b[1] - (a[1] + a[3]) for a, b in zip(self.chips, self.chips[1:])}
        self.assertEqual(1, len(gaps), "the tabs sit at gaps %s" % sorted(gaps))
        pads = {self.icons[k][1] - c[1] for k, c in zip(self.keys, self.chips)}
        self.assertEqual(1, len(pads), "the tabs pad their icon by %s" % sorted(pads))
        for key, chip in zip(self.keys, self.chips):
            box, icon = self.boxes[key], self.icons[key]
            with self.subTest(tab=key):
                self.assertEqual(icon[1] - chip[1], (chip[1] + chip[3]) - (box[1] + box[3]),
                                 "the pad after the name is not the pad before the icon")
                self.assertLess(icon[1] + icon[3], box[1], "the icon is not left of the name")
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
        want = self.bar.TRAY_COLOR.name()    # the tabs' background, from Houdini's theme
        self.assertEqual(theme.color_hex("surface_low"), want)
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
        pad = self.px(self.icons[self.keys[0]][1] - self.chips[0][1])
        gap = self.px(self.chips[1][1] - (self.chips[0][1] + self.chips[0][3]))
        for (key, label), rect in self.bar._chip_rects():
            chip = self.chips[self.keys.index(key)]
            with self.subTest(tab=key):
                self.assertEqual((self.px(chip[2]), self.px(chip[4])), (rect.y(), rect.height()))
                icon, box = self.icons[key], self.boxes[key]
                room = self.px(icon[3]) + self.px(box[1] - (icon[1] + icon[3]))
                self.assertEqual(2 * pad + room, rect.width() - metrics.horizontalAdvance(label),
                                 "the tab is not its pads, its icon, the drawn gap and its name")
        for a, b in zip(rects, rects[1:]):
            self.assertEqual(gap, b.x() - (a.x() + a.width()), "two tabs have another gap")

    def test_every_icon_is_where_it_is_drawn_in_its_own_colours_selected_or_not(self):
        self.bar.show()
        QtWidgets.QApplication.processEvents()

        def painted(checked):
            self.bar.setChecked(checked, emit=False)
            image = self.bar.grab().toImage()
            scale = image.width() // self.bar.width()
            out = {}
            for (key, _label), rect in self.bar._chip_rects():
                box = self.bar.icon_rect(key, rect)
                out[key] = [image.pixelColor(int(x * scale), int(y * scale)).name()
                            for x in range(int(box.left()), int(box.right()))
                            for y in range(int(box.top()), int(box.bottom()))]
            return out

        for (key, _label), rect in self.bar._chip_rects():
            chip, icon = self.chips[self.keys.index(key)], self.icons[key]
            box = self.bar.icon_rect(key, rect)
            with self.subTest(tab=key):
                self.assertEqual((self.px(icon[1] - chip[1]), self.px(icon[2] - chip[2]), self.px(icon[3]), self.px(icon[4])),
                                 (box.x() - rect.x(), box.y() - rect.y(), box.width(), box.height()))
                self.assertTrue(os.path.exists(amaze.package_file("ui", amazetheme.drawn_name(icon)[2])))
        first, second = painted(self.keys[0]), painted(self.keys[1])
        for key in self.keys[2:]:
            with self.subTest(tab=key):
                self.assertGreater(len(set(first[key])), 2, "no icon is painted")
                self.assertEqual(first[key], second[key])

    def test_a_tab_with_no_icon_is_its_name_between_the_pads(self):
        bar = ui_helpers.SectionTabBar([("GPUOpen", "GPUOpen"), ("RGL", "RGL")])
        self.addCleanup(bar.deleteLater)
        metrics, pad = bar.fontMetrics(), self.px(self.icons[self.keys[0]][1] - self.chips[0][1])
        for (key, label), rect in bar._chip_rects():
            with self.subTest(tab=key):
                self.assertIsNone(bar.icon_rect(key, rect))
                self.assertEqual(2 * pad, rect.width() - metrics.horizontalAdvance(label))

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
