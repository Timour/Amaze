"""The shell of the first dialog built from an HTML handover, held to the design's measurements at the chrome's density. ▸p/designed-dialog"""

import contextlib
import inspect
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

import amaze  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402


def _px(n):
    """One DESIGN pixel in the logical pixels Qt sizes with, computed HERE from the design's own density and Houdini's scale - never by calling the code under test, which would agree with itself at any scale. The pages are drawn at 2x, so a design number is halved and then scaled, which is the 2x rule the chrome has always followed (overview.md §8). ▸p/designed-dialog"""
    return int(round(n / 2 * theme.UI_SCALE))


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
        dialog = ui_helpers.DesignedDialog(None, title="brushed_steel")
        combo = QtWidgets.QComboBox(dialog)
        combo.addItem("Version 2")
        dialog.add_field(combo)
        field = QtWidgets.QLineEdit(dialog)
        dialog.add_field(field, label="Change Name")
        dialog.add_buttons("Cancel", "Apply")
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
        for name, geom in (("Cancel", left), ("Apply", right)):
            self.assertEqual(
                (_px(202), _px(42)), (geom[2], geom[3]),
                "%s is not the design's size" % name)
        self.assertEqual(_px(35), left[0], "the pair is not at "
                                                   "the column's left edge")
        _fx, fy, _fw, fh = self._at(dialog, _f)    # 35 BELOW THE FIELD, read off the page as field bottom 334 against buttons top 369; a stretch instead floats them to the bottom, which is a different gap at every dialog height
        self.assertAlmostEqual(
            _px(35), left[1] - (fy + fh), delta=2,
            msg="the buttons are not 35 below the name field")
        self.assertEqual(
            _px(38), right[0] - (left[0] + left[2]),
            "the gap between the buttons is not the design's 38")
        self.assertAlmostEqual(
            _px(477), right[0] + right[2], delta=2,
            msg="the pair does not end at the column's right edge")

    def test_a_field_fills_the_column_at_the_designs_height(self):
        dialog, combo, field = self._dialog()
        for name, widget in (("dropdown", combo), ("name field", field)):
            x, _y, w, h = self._at(dialog, widget)
            self.assertEqual(_px(35), x, "%s is not inset 35" % name)
            self.assertEqual(    # the column BETWEEN the insets, not d(442): at ratio 2 the inset 35 halves to 18 and the column is 220 where d(442) is 221, a rounding rather than a drift, so the property asserted is that the field spans exactly what the two insets leave
                dialog.width() - 2 * _px(35), w,
                "%s does not span the column between the insets" % name)
            self.assertEqual(_px(60), h, "%s is not 60 tall" % name)

    def test_the_controls_are_NOT_restyled(self):
        """Standard Houdini controls by design: the shell gives them the design's geometry and nothing else. ▸p/designed-dialog"""
        _dialog, combo, field = self._dialog()
        for name, widget in (("dropdown", combo), ("name field", field)):
            self.assertEqual("", widget.styleSheet(),
                             "%s has been restyled" % name)

    def test_the_frame_is_the_designs_size(self):
        """512 x 370 of the design, in the logical pixels Qt sizes with, at whatever Houdini's UI scale is."""
        dialog, _c, _f = self._dialog()
        self.assertEqual((_px(512), _px(370)),
                         (dialog.width(), dialog.height()))

    def test_the_constants_are_stored_at_the_CHROME_density(self):
        """A design number is HALVED at source, then scaled - the 2x rule every chrome constant follows (overview.md §8). Storing the raw 512 is what once opened it as a 1024 window. ▸p/designed-dialog"""
        self.assertEqual(
            (256, 185), ui_helpers.DesignedDialog.FRAME,
            "the frame is back at the design's raw pixels - halve it at "
            "source, the way every chrome constant is halved")

    def test_it_wears_the_DRAWN_header_band(self):
        """The band is drawn INSIDE the dialog and is not the window title bar - the design draws both, and reading one as the other is what deleted this header once. ▸p/one-design-document"""
        from amaze import amazetheme
        dialog, combo, _f = self._dialog()
        band = dialog.findChild(QtWidgets.QWidget, "amaze_header_band")
        self.assertIsNotNone(band, "the drawn header band is missing")
        self.assertEqual(theme.ui_px(amazetheme.HEADER_BAND_H),    # ui_px, NOT `_px`: the design document's numbers are already at chrome density, where `_px` takes a design-density one and halves it
                         band.height())
        self.assertEqual(dialog.width(), band.width(),
                         "the band does not span the dialog")
        self.assertEqual(
            theme.color("surface_low").name(),
            band.palette().color(QtGui.QPalette.ColorRole.Window).name(),
            "the band is not on the design's ground")

        label = dialog.findChild(QtWidgets.QLabel,
                                 "amaze_header_band_text")
        self.assertIsNotNone(label, "the band carries no name")
        self.assertEqual("brushed_steel", label.text(),
                         "the band shows something other than the "
                         "asset's own name")
        self.assertEqual("brushed_steel", dialog.windowTitle(),
                         "the window title lost the name the band shows")
        self.assertTrue(    # the LITERAL Figma reads, not the constant: comparing the constant with itself passes whatever it is set to
            label.font().bold(),
            "D01, D02 and D11 all draw the band's name BOLD")
        self.assertEqual(
            theme.ui_px(amazetheme.HEADER_BAND_TEXT_PX),
            label.font().pixelSize(),
            "the band's name is not the size the design draws")

    def test_the_first_field_sits_below_the_band(self):
        dialog, combo, _f = self._dialog()
        from amaze import amazetheme
        self.assertEqual(
            theme.ui_px(amazetheme.HEADER_BAND_H)
            + theme.ui_px(amazetheme.D01_FIRST_FIELD_Y),
            self._at(dialog, combo)[1],
            "the first field is not the design's distance below the "
            "band")


class ADialogIsSizedTheWayTheHostSizesEverything(unittest.TestCase):
    """One logical size per Houdini UI scale, on every machine; no screen enters the arithmetic. `PROFILES` is (machine, device ratio, UI scale, frame width) with the widths WRITTEN OUT, never derived from the code under test. ▸r/houdini-ui-scale, ▸p/designed-dialog"""

    PROFILES = (
        ("retina mac",       2.0, 1.0, 256),
        ("plain linux",      1.0, 1.0, 256),
        ("windows at 1.5",   1.0, 1.5, 384),
        ("a 2.0 UI scale",   1.0, 2.0, 512),
    )

    @contextlib.contextmanager
    def _at(self, scale):
        real = theme.UI_SCALE
        theme.UI_SCALE = scale
        try:
            yield
        finally:
            theme.UI_SCALE = real

    def _frame_on(self, ratio, scale):
        """A dialog whose PARENT states its screen's ratio - the reader the old code used, kept here so the test can prove the ratio no longer reaches anything."""
        parent = _ScreenAt(ratio)
        with self._at(scale):
            dialog = ui_helpers.DesignedDialog(parent)
        self.addCleanup(parent.deleteLater)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_the_frame_is_one_size_per_UI_SCALE_on_every_machine(self):
        for machine, ratio, scale, expected in self.PROFILES:
            with self.subTest(machine=machine):
                self.assertEqual(
                    expected, self._frame_on(ratio, scale).width(),
                    "%s: the dialog is not the size Houdini's own scale "
                    "gives it" % machine)

    def test_two_monitors_one_session_one_dialog_size(self):
        """THE BUG IN ONE ASSERTION. Same Houdini, same scale, two screens: Houdini cannot rescale mid-session, so neither may a panel of its own accord."""
        retina, plain = _ScreenAt(2.0), _ScreenAt(1.0)   # HELD: a parent that falls out of scope takes its dialog's C++ object with it
        with self._at(1.0):
            on_retina = ui_helpers.DesignedDialog(retina)
            on_plain = ui_helpers.DesignedDialog(plain)
        for widget in (retina, plain, on_retina, on_plain):
            self.addCleanup(widget.deleteLater)
        self.assertEqual(
            on_retina.width(), on_plain.width(),
            "the dialog changes size with the monitor - which is the one "
            "thing Houdini's own UI scale never does")

    def test_a_design_measurement_lands_the_same_through_EITHER_path(self):
        """60 design px is the toolbar bar in `panel.py` (`ui_px(30)`) and the dialog's `FIELD_H`; both sides are computed here. ▸p/designed-dialog"""
        for machine, ratio, scale, _w in self.PROFILES:
            with self.subTest(machine=machine):
                parent = _ScreenAt(ratio)
                with self._at(scale):
                    dialog = ui_helpers.DesignedDialog(parent)
                    field = QtWidgets.QLineEdit(dialog)
                    dialog.add_field(field)
                    chrome = theme.ui_px(30)
                self.addCleanup(parent.deleteLater)
                self.addCleanup(dialog.deleteLater)
                self.assertEqual(
                    chrome, field.height(),
                    "%s: the same 60 design px is %d in the dialog and %d "
                    "in the chrome beside it"
                    % (machine, field.height(), chrome))


class NothingThatSizesReadsTheScreen(unittest.TestCase):
    """No sizing path in the dialog shell reads a device ratio; a re-added one passes every number above on the machine it is written on. ▸r/houdini-ui-scale"""

    SIZING_READS = ("screen_ratio", "devicePixelRatio", "devicePixelRatioF")

    def test_the_dialog_shell_holds_no_screen_read_at_all(self):
        body = inspect.getsource(ui_helpers.DesignedDialog)
        for spelling in self.SIZING_READS:
            self.assertNotIn(
                spelling, body,
                "the designed dialog is sizing from the screen again - "
                "Houdini's scale is one number, fixed at startup, and a "
                "dialog that divides by a live ratio renders at 2x the "
                "chrome on every dpr-1.0 display")

    def test_the_scanner_can_see_a_read_it_should_refuse(self):
        """THE ANTI-VACUOUS HALF: a `not in` over a source string passes just as happily when the source is empty or the spelling has changed. ▸p/vacuous-register"""
        planted = ("class Fake:\n"
                   "    def d(self, v):\n"
                   "        return v / theme.screen_ratio(self)\n")
        for spelling in self.SIZING_READS[:1]:
            self.assertIn(spelling, planted,
                          "the spelling this test greps for has moved")
