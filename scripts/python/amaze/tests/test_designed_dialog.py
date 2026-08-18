"""The shell of the first dialog built from an HTML handover, held to the design's literal pixels. ▸p/designed-dialog"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

import amaze  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402


def _px(dialog, n):
    """A design pixel, converted the way the dialog converts it - NEVER through `theme.ui_px`, which would make the test agree with the code at any UI scale. ▸p/designed-dialog"""
    return dialog.d(n)


class _ScreenAt(QtWidgets.QWidget):
    """A parent that STATES the ratio of the screen it sits on; offscreen Qt invents ONE screen at 1.0, so a real widget cannot pose the question. ▸r/screen-dpr"""

    def __init__(self, ratio) -> None:
        super().__init__()
        self._ratio = ratio

    def devicePixelRatioF(self):   # Qt declares it non-virtual, so a Python override answers PYTHON callers only - which is every reader on the drawing path; probed on both majors, ▸r/screen-dpr
        return self._ratio


class TheIconIsNotClipped(unittest.TestCase):
    """The glyph's stroke reaches 3 past its own path bounds on every side, so a viewBox tight to the paths cuts the top and bottom points off."""

    def test_the_viewbox_leaves_room_for_the_stroke(self):
        path = os.path.join(os.path.dirname(amaze.__file__), "ui",
                            "icon_versions_dialog.svg")
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        import re
        box = re.search(r'viewBox="([-\d.\s]+)"', body)
        self.assertIsNotNone(box, "the glyph has no viewBox")
        x, y, w, h = [float(v) for v in box.group(1).split()]
        stroke = float(re.search(r'stroke-width="([\d.]+)"',
                                 body).group(1))
        self.assertLessEqual(
            x, -stroke / 2,
            "the viewBox starts at the path bounds, so the stroke is "
            "clipped on the left and top")
        self.assertGreaterEqual(
            w, 60 + stroke,
            "the viewBox is not wide enough for the stroke")
        self.assertGreaterEqual(h, 60 + stroke)

    def test_the_top_and_bottom_are_POINTS_not_flat_cuts(self):
        """Ink at the box edge is not clipping; clipping is a FLAT CUT - the glyph is a diamond over two chevrons, so its first and last rows are narrow points and a clipped one is a wide flat row."""
        path = os.path.join(os.path.dirname(amaze.__file__), "ui",
                            "icon_versions_dialog.svg")
        image = ui_helpers.render_svg_pixmap(path, 120).toImage()

        def ink_width(y):
            xs = [x for x in range(image.width())
                  if image.pixelColor(x, y).alpha() > 30]
            return (xs[-1] - xs[0] + 1) if xs else 0

        rows = [y for y in range(image.height()) if ink_width(y)]
        self.assertTrue(rows, "the glyph rendered nothing")
        widest = max(ink_width(y) for y in rows)
        for edge, y in (("top", rows[0]), ("bottom", rows[-1])):
            self.assertLess(
                ink_width(y), widest * 0.5,
                "the %s row spans %s of a %s-wide glyph - that is a "
                "flat cut, so the stroke is being clipped"
                % (edge, ink_width(y), widest))


class TheShellMatchesTheDesign(unittest.TestCase):
    """The SHELL is the design - frame, header band, inset column, colours - while the CONTROLS inside are Houdini's, so nothing here asserts a field's colour. ▸p/designed-dialog"""


    def _dialog(self):
        ui = os.path.join(os.path.dirname(amaze.__file__), "ui")
        dialog = ui_helpers.DesignedDialog(
            None, title="Versions", subtitle="brushed_steel/Metals",
            kind="Karma",
            icon=os.path.join(ui, "icon_versions_dialog.svg"))
        combo = QtWidgets.QComboBox(dialog)
        combo.addItem("Version 2")
        dialog.add_field(combo)
        field = QtWidgets.QLineEdit(dialog)
        dialog.add_field(field, label="Name")
        dialog.add_buttons("cancel", "Apply")
        dialog.show()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.hide)
        QtWidgets.QApplication.processEvents()
        return dialog, combo, field

    def _at(self, dialog, widget):
        p = widget.mapTo(dialog, QtCore.QPoint(0, 0))
        return p.x(), p.y(), widget.width(), widget.height()

    def test_the_buttons_are_the_designs_size_and_place(self):
        """Houdini's LOOK at the design's geometry: 202 x 42 each, filling the 442 column with a 38 gap - at their natural size they huddle in the corner."""
        dialog, _c, _f = self._dialog()
        buttons = dialog.findChildren(QtWidgets.QPushButton)
        self.assertEqual(2, len(buttons))
        left, right = sorted(
            (self._at(dialog, b) for b in buttons), key=lambda g: g[0])
        for name, geom in (("cancel", left), ("Apply", right)):
            self.assertEqual(
                (_px(dialog, 202), _px(dialog, 42)), (geom[2], geom[3]),
                "%s is not the design's size" % name)
        self.assertEqual(_px(dialog, 35), left[0], "the pair is not at "
                                                   "the column's left edge")
        _fx, fy, _fw, fh = self._at(dialog, _f)    # 35 BELOW THE FIELD, read off the page as field bottom 334 against buttons top 369; a stretch instead floats them to the bottom, which is a different gap at every dialog height
        self.assertAlmostEqual(
            _px(dialog, 35), left[1] - (fy + fh), delta=2,
            msg="the buttons are not 35 below the name field")
        self.assertEqual(
            _px(dialog, 38), right[0] - (left[0] + left[2]),
            "the gap between the buttons is not the design's 38")
        self.assertAlmostEqual(
            _px(dialog, 477), right[0] + right[2], delta=2,
            msg="the pair does not end at the column's right edge")

    def test_a_field_fills_the_column_at_the_designs_height(self):
        dialog, combo, field = self._dialog()
        for name, widget in (("dropdown", combo), ("name field", field)):
            x, _y, w, h = self._at(dialog, widget)
            self.assertEqual(_px(dialog, 35), x, "%s is not inset 35" % name)
            self.assertEqual(    # the column BETWEEN the insets, not d(442): at ratio 2 the inset 35 halves to 18 and the column is 220 where d(442) is 221, a rounding rather than a drift, so the property asserted is that the field spans exactly what the two insets leave
                dialog.width() - 2 * _px(dialog, 35), w,
                "%s does not span the column between the insets" % name)
            self.assertEqual(_px(dialog, 60), h, "%s is not 60 tall" % name)

    def test_the_controls_are_NOT_restyled(self):
        """Standard Houdini controls by design: the shell gives them the design's geometry and nothing else. ▸p/designed-dialog"""
        _dialog, combo, field = self._dialog()
        for name, widget in (("dropdown", combo), ("name field", field)):
            self.assertEqual("", widget.styleSheet(),
                             "%s has been restyled" % name)

    def test_the_frame_is_the_designs_size(self):
        """512 x 435 LITERALLY, at any Houdini UI scale."""
        dialog, _c, _f = self._dialog()
        self.assertEqual((_px(dialog, 512), _px(dialog, 435)),
                         (dialog.width(), dialog.height()))
        screen = QtGui.QGuiApplication.primaryScreen()    # AND the PHYSICAL size holds: whatever the ratio, the window occupies 512 x 435 of the screen's own pixels
        ratio = screen.devicePixelRatio() if screen else 1.0
        self.assertAlmostEqual(512, dialog.width() * ratio, delta=2)
        self.assertAlmostEqual(435, dialog.height() * ratio, delta=2)

    def test_the_design_does_not_go_through_the_UI_SCALE(self):
        """The panel's chrome scales with Houdini's UI preference; a design given in final pixels does not - at a UI scale of 2.0 every number here doubled and a 512px design opened as a 1024px window. ▸p/designed-dialog"""
        import inspect
        body = inspect.getsource(ui_helpers.DesignedDialog)
        self.assertNotIn(
            "ui_px(", body,
            "the designed dialog is scaling the design's measurements "
            "again - 512 becomes 1024 on a 2.0 UI scale")

    def test_the_header_carries_the_three_lines_and_the_icon(self):
        dialog, _c, _f = self._dialog()
        texts = {label.text() for label in dialog.findChildren(
            QtWidgets.QLabel) if label.text()}
        for line in ("brushed_steel/Metals", "Versions", "Karma"):
            self.assertIn(line, texts, "the header lost %r" % line)
        from PySide6 import QtSvgWidgets
        glyphs = dialog.findChildren(QtSvgWidgets.QSvgWidget)
        self.assertTrue(
            glyphs,
            "the header icon is not a live vector - it must not be "
            "rasterised to a pixmap")
        self.assertEqual((_px(dialog, 60), _px(dialog, 60)),
                         (glyphs[0].width(), glyphs[0].height()))

    def test_the_title_is_bigger_and_bolder_than_its_neighbours(self):
        """The hierarchy is the design - 32px bold over 23px plain."""
        dialog, _c, _f = self._dialog()
        by_text = {label.text(): label for label in
                   dialog.findChildren(QtWidgets.QLabel) if label.text()}
        title = by_text["Versions"].font()
        kind = by_text["Karma"].font()
        self.assertTrue(title.bold(), "the title is not bold")
        self.assertFalse(kind.bold(), "the kind line should not be bold")
        self.assertGreater(title.pixelSize(), kind.pixelSize())


class ADesignPixelConvertsOnEveryPlatformTest(unittest.TestCase):
    """`d()` turns one DESIGN pixel into the logical pixels Qt sizes with, reading BOTH the device ratio and `theme.UI_SCALE` - macOS carries Retina in the dpr at scale 1.0, Windows the opposite shape at dpr 1.0 with a real 1.5, and dividing by dpr alone opens the dialog a third small beside `ui_px` chrome. ▸r/screen-dpr"""

    DESIGN = ui_helpers.DesignedDialog.FRAME[0]          # 512

    def _on(self, ratio):
        """A dialog whose PARENT states the ratio - which is the source under test, so nothing here patches the reader itself."""
        parent = _ScreenAt(ratio)
        dialog = ui_helpers.DesignedDialog(parent)
        self.addCleanup(parent.deleteLater)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _d(self, value, ratio, scale):
        real_scale = theme.UI_SCALE
        theme.UI_SCALE = scale
        try:
            return self._on(ratio).d(value)
        finally:
            theme.UI_SCALE = real_scale

    def test_the_ratio_is_the_parents_screen_not_the_primarys(self):
        """THE SOURCE, which no suite figure can otherwise reach: offscreen Qt's one invented screen answers 1.0, so a parent stating 2.0 discriminates - reading the parent halves 512, reading the primary leaves it whole. ▸r/screen-dpr"""
        self.assertEqual(256, self._d(self.DESIGN, ratio=2.0, scale=1.0))

    def test_a_parent_at_1_is_not_overruled_by_a_primary_at_2(self):
        """The INVERSION, and the half that catches a silent fallback - an unrealised widget answers with the primary ratio, so a read that merely LOOKS widget-aware passes the case above and fails this one. ▸r/screen-dpr"""
        screen = mock.Mock()
        screen.devicePixelRatio.return_value = 2.0
        with mock.patch.object(QtGui.QGuiApplication, "primaryScreen",
                               staticmethod(lambda: screen)):
            self.assertEqual(512, self._d(self.DESIGN, ratio=1.0, scale=1.0))

    def test_retina_mac_halves_it(self):
        """The Retina case: the scale factor merely restates the dpr, so theme resolves it to 1.0."""
        self.assertEqual(256, self._d(self.DESIGN, ratio=2.0, scale=1.0))

    def test_windows_applies_the_real_scale(self):
        """dpr 1.0 with a genuine 1.5 scale: 512 must become 768 to sit beside chrome `ui_px` has already multiplied by 1.5."""
        self.assertEqual(768, self._d(self.DESIGN, ratio=1.0, scale=1.5))

    def test_a_plain_display_leaves_it_alone(self):
        self.assertEqual(512, self._d(self.DESIGN, ratio=1.0, scale=1.0))

    def test_ints_stay_ints_and_floats_stay_floats(self):
        self.assertIsInstance(self._d(60, ratio=2.0, scale=1.0), int)
        self.assertIsInstance(self._d(60.0, ratio=2.0, scale=1.0), float)
