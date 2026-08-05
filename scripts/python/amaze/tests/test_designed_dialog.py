"""The first dialog built from an HTML handover (2026-08-02).

His design arrives as a Framer page; the numbers are read off it with
computed styles and land in DesignedDialog, which is the SHELL - the
shape his designs describe - rather than anything specific to
Versions. These tests hold the shell to those numbers, because a
design handover that drifts silently is worse than no handover: he
would have to re-measure the panel by eye to find out.

The sizes are in PIXELS and go straight across. He designs in Source
Sans 3 because it matches Houdini's own UI font, so a 23px label in
the page is a 23px label here, and the colours are literal rather than
mapped to theme tokens (practice.md).
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

import amaze  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402


def _px(n):
    """HIS pixels, converted the way the dialog converts them.

    His pages are drawn on a Retina screen, so a design number is a
    DEVICE pixel and Qt sizes in logical pixels - two device pixels
    each here. Asserting the raw number pinned a dialog that opened at
    twice the size he asked for, and the suite was green while he was
    looking at it.

    This used to be theme.ui_px, which multiplies by Houdini's UI
    scale - so the test agreed with the dialog at any scale and said
    nothing about the design. He opened it at a scale of 2.0 and got a
    1024px window from a 512px design; the test was green throughout.
    A design handover test that follows the code instead of the design
    is not a handover test."""
    return ui_helpers.DesignedDialog.d(n)


class TheIconIsNotClipped(unittest.TestCase):
    """His glyph's stroke reaches past its own path bounds - 6 wide, so
    3 beyond on every side - and a viewBox tight to the paths cut the
    top and bottom points clean off. He spotted it as "clipped top and
    bottom"."""

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
        """What clipping looks like, rendered.

        Ink reaching the edge of the box is not clipping - a viewBox
        bounding the stroke exactly is correct. Clipping shows as a
        FLAT CUT: his glyph is a diamond over two chevrons, so its
        first and last rows are narrow points, and a clipped one has a
        wide flat row instead. That is the shape he saw."""
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
    """The SHELL is the design - frame, header band, the inset column
    and the colours. The CONTROLS inside it are Houdini's: the boxes
    in his page mark where they go, not what they look like, so
    nothing here asserts a field's size or colour."""


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
        """Standard LOOK, his geometry: 202 x 42 each, filling the 442
        column with a 38 gap. Left at their natural size they huddled
        in the corner."""
        dialog, _c, _f = self._dialog()
        buttons = dialog.findChildren(QtWidgets.QPushButton)
        self.assertEqual(2, len(buttons))
        left, right = sorted(
            (self._at(dialog, b) for b in buttons), key=lambda g: g[0])
        for name, geom in (("cancel", left), ("Apply", right)):
            self.assertEqual(
                (_px(202), _px(42)), (geom[2], geom[3]),
                "%s is not the design's size" % name)
        self.assertEqual(_px(35), left[0], "the pair is not at the "
                                           "column's left edge")
        # 35 BELOW THE FIELD - read off the page: field bottom 334,
        # buttons top 369. A stretch instead floated them to the
        # bottom, which is a different gap at every dialog height.
        _fx, fy, _fw, fh = self._at(dialog, _f)
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
            # The column BETWEEN the insets, not d(442). At a ratio of
            # 2 the inset 35 halves to 18 (17.5 rounded up) and the
            # column is 220 where d(442) is 221 - a rounding, not a
            # drift. The property is that the field spans exactly what
            # the two insets leave.
            self.assertEqual(
                dialog.width() - 2 * _px(35), w,
                "%s does not span the column between the insets" % name)
            self.assertEqual(_px(60), h, "%s is not 60 tall" % name)

    def test_the_controls_are_NOT_restyled(self):
        """His call: standard Houdini controls. The shell gives them
        the design's geometry and nothing else."""
        _dialog, combo, field = self._dialog()
        for name, widget in (("dropdown", combo), ("name field", field)):
            self.assertEqual("", widget.styleSheet(),
                             "%s has been restyled" % name)

    def test_the_frame_is_the_size_he_asked_for(self):
        """512 x 435 LITERALLY, at any Houdini UI scale."""
        dialog, _c, _f = self._dialog()
        self.assertEqual((_px(512), _px(435)),
                         (dialog.width(), dialog.height()))
        # AND the physical size is his: whatever the ratio, the window
        # occupies 512 x 435 of his screen's own pixels.
        screen = QtGui.QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen else 1.0
        self.assertAlmostEqual(512, dialog.width() * ratio, delta=2)
        self.assertAlmostEqual(435, dialog.height() * ratio, delta=2)

    def test_the_design_does_not_go_through_the_UI_SCALE(self):
        """The panel's chrome scales with Houdini's UI preference; a
        design given in final pixels does not. At his scale of 2.0
        every number here doubled and the window opened twice the size
        he asked for."""
        import inspect
        body = inspect.getsource(ui_helpers.DesignedDialog)
        self.assertNotIn(
            "ui_px(", body,
            "the designed dialog is scaling his measurements again - "
            "512 becomes 1024 on a 2.0 UI scale")

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
        self.assertEqual((_px(60), _px(60)),
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
