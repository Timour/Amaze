"""The tab strip: S01's height, Houdini's QML tab bar with the section icons, its bottom line."""

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


def _shown(bar):
    """`bar` shown off screen, so its tab bar is laid out."""
    bar.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
    bar.show()
    QtWidgets.QApplication.processEvents()
    return bar


class TheTabStripMatchesItsDesignFrame(unittest.TestCase):
    """The strip is S01's height, each section tab has its art at its drawn size, the line is on top."""

    def setUp(self):
        self.px = theme.ui_px
        self.frame = amazetheme.DIALOG_LAYOUT["S01"]
        self.icons = amazetheme.drawn_by_owner("S01", "icon")
        labels = {key: n[5] for key, n in amazetheme.drawn_by_owner("S01", "label").items()}
        self.keys = sorted(self.icons, key=lambda k: self.icons[k][1])
        self.bar = ui_helpers.SectionTabBar([(k, labels[k]) for k in self.keys])
        self.bar.resize(self.px(self.frame["frame"][0]), self.bar.HEIGHT)
        self.addCleanup(self.bar.deleteLater)

    def test_the_strip_is_its_drawn_height(self):
        height = self.px(self.frame["frame"][1])
        self.assertEqual((height, height),
                         (self.bar.minimumHeight(), self.bar.maximumHeight()))

    def test_the_strip_is_29_high_as_drawn(self):
        self.assertEqual((840, 29), tuple(self.frame["frame"]))
        self.assertEqual(self.px(29), self.bar.height())

    def test_the_line_is_the_bottom_row_the_full_width_over_the_tab_bar(self):
        _shown(self.bar)
        line, tabs = self.bar._line, self.bar._tabs
        self.assertEqual(QtCore.QRect(0, self.bar.HEIGHT - self.px(1), self.bar.width(), self.px(1)),
                         line.geometry())
        self.assertEqual(self.bar.HEIGHT, tabs.geometry().bottom() + 1, "the tab bar ends above the line")
        self.assertIs(line, self.bar.children()[-1], "the line is not above the tab bar")
        self.assertTrue(line.testAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_each_section_tab_has_its_art_at_its_drawn_size_and_room_for_its_outline(self):
        room = self.px(amazetheme.TAB_ICON_BLEED)
        self.assertGreater(room, 0)
        rows = self.bar._tabs.rootObject().property("tabs")
        for (key, _label), row in zip(self.bar._segments, rows):
            with self.subTest(tab=key):
                _kind, _x, _y, width, height, _text = self.icons[key]
                self.assertEqual((self.px(width) + 2 * room, self.px(height) + 2 * room, room),
                                 (row["iconWidth"], row["iconHeight"], row["bleed"]))
                self.assertEqual("image://sectiontab/" + key, row["icon"])
                self.assertTrue(os.path.exists(amaze.package_file("ui", amazetheme.drawn_name(self.icons[key])[2])))

    def test_the_icon_is_its_art_at_the_asked_device_size(self):
        provider = ui_helpers._TabIcons(ui_helpers.SectionTabBar.ICONS, self.px(amazetheme.TAB_ICON_BLEED))
        _kind, _x, _y, width, height, _text = self.icons["material"]
        room = self.px(amazetheme.TAB_ICON_BLEED)
        want = QtCore.QSize(2 * (self.px(width) + 2 * room), 2 * (self.px(height) + 2 * room))
        size = QtCore.QSize()
        pixmap = provider.requestPixmap("material", size, want)
        self.assertEqual((want, want), (pixmap.size(), size))

    def test_a_tab_with_no_art_has_no_icon(self):
        bar = ui_helpers.SectionTabBar([("GPUOpen", "GPUOpen"), ("RGL", "RGL")])
        self.addCleanup(bar.deleteLater)
        for row in bar._tabs.rootObject().property("tabs"):
            with self.subTest(tab=row["label"]):
                self.assertEqual("", row["icon"])


class TheTabsSwitchTheSection(unittest.TestCase):
    """A click or `setChecked` switches once and says so; `emit=False` says nothing."""

    def setUp(self):
        self.bar = ui_helpers.SectionTabBar([("material", "Material"), ("file", "File")])
        self.addCleanup(self.bar.deleteLater)
        self.said = []
        self.bar.segmentClicked.connect(self.said.append)

    def test_a_click_and_set_checked_emit_once_per_change(self):
        _shown(self.bar)
        self.bar.setChecked("material", emit=False)
        tabs = self.bar._tabs
        at = QtCore.QPointF(self.bar.tab_rect(1).center() - tabs.pos())
        for kind, buttons in ((QtCore.QEvent.Type.MouseButtonPress, QtCore.Qt.MouseButton.LeftButton),
                              (QtCore.QEvent.Type.MouseButtonRelease, QtCore.Qt.MouseButton.NoButton)):
            QtWidgets.QApplication.sendEvent(tabs, QtGui.QMouseEvent(
                kind, at, at, QtCore.Qt.MouseButton.LeftButton, buttons, QtCore.Qt.KeyboardModifier.NoModifier))
        self.assertEqual(["file"], self.said)
        self.assertEqual(("file", 1), (self.bar._checked_key, tabs.rootObject().property("currentIndex")))
        self.bar.setChecked("file")
        self.bar.setChecked("material")
        self.assertEqual(["file", "material"], self.said)

    def test_set_checked_without_emit_says_nothing(self):
        self.bar.setChecked("file", emit=False)
        self.assertEqual([], self.said)
        self.assertEqual(("file", 1), (self.bar._checked_key, self.bar._tabs.rootObject().property("currentIndex")))


if __name__ == "__main__":
    unittest.main()
