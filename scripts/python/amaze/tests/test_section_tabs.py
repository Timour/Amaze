"""The tab strip stands on its S01 frame: height, tray and chip spacing. ▸r/tabs-from-frame"""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze import amazetheme  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402


class TheTabStripStandsOnItsFrame(unittest.TestCase):
    """Every tab, the tray and the strip land where S01 draws them, in whatever font."""

    def setUp(self):
        self.px = theme.ui_px
        self.frame = amazetheme.DIALOG_LAYOUT["S01"]
        nodes = self.frame["nodes"]
        self.chips = sorted((n for n in nodes if n[0].startswith("chip ▸ ")),
                            key=lambda n: n[1])
        self.boxes = {n[0].split(" ▸ ")[1]: n for n in nodes
                      if n[0].startswith("text box ▸ ")}
        labels = {n[0].split(" ▸ ")[1]: n[5] for n in nodes
                  if n[0].startswith("label ▸ ")}
        self.tray = next(n for n in nodes if n[0] == "tray")
        self.keys = [c[0].split(" ▸ ")[1] for c in self.chips]
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
        self.assertEqual(self.frame["frame"][1], self.tray[2] + self.tray[4],
                         "the tray does not sit on the strip's bottom")

    def test_the_strip_is_its_drawn_height(self):
        height = self.px(self.frame["frame"][1])
        self.assertEqual((height, height),
                         (self.bar.minimumHeight(), self.bar.maximumHeight()))

    def test_every_tab_lands_where_it_is_drawn(self):
        rects = [rect for _segment, rect in self.bar._chip_rects()]
        self.assertEqual(len(self.chips), len(rects))
        self.assertEqual(self.px(self.chips[0][1]), rects[0].x(), "the first tab moved")
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
            self.assertEqual(gap, b.x() - (a.x() + a.width()), "two tabs sit at another gap")

    def test_the_tray_is_where_it_is_drawn(self):
        tray = self.bar._tray_rect()
        last = self.bar._chip_rects()[-1][1]
        inset = self.px(self.chips[0][1] - self.tray[1])
        self.assertEqual((self.px(self.tray[1]), self.px(self.tray[2]), self.px(self.tray[4])),
                         (tray.x(), tray.y(), tray.height()))
        self.assertEqual(last.x() + last.width() + inset, tray.x() + tray.width(),
                         "the tray does not end one inset past the last tab")


if __name__ == "__main__":
    unittest.main()
