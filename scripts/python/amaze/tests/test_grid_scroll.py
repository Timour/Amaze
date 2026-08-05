"""Selecting a tile never moves the grid.

Qt's autoScroll (on by default for every item view) re-scrolls on
EVERY currentChanged - a mouse click on a half-cut tile included. In
the panel that read as the grid jumping under the cursor the moment a
partly-visible tile was selected, and it was reported as exactly that
(2026-07-31: "i dont want any nudge or movement").

The behavioural test drives the real panel's real view through the
same internal path a click takes (current-index change on the view's
selection model - the code Qt gates on autoScroll), because a test of
a COPY of the setting proves nothing about the shipped view. The
second test pins the property through the grid/list switch:
setViewMode() has form here - it silently re-applies the movement
mode and disarmed dragging once (recorded) - so "set at construction"
needs proof that a view-mode flip does not quietly turn it back on.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.panel import dragdrop_widgets  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class TheWheelIsONEEngineForBothViews(unittest.TestCase):
    """One scroll path, two views, both axes.

    The handler was Y-ONLY once, letting X fall through to Qt's own
    per-item stepping. That was invisible until list rows grew wider
    than the panel, and then sideways felt accelerated beside up and
    down - because only one of the two applied the user's
    `scroll_speed` to a pixel delta.

    Nothing pinned any of it. Before 2026-08-04 no test in this suite
    constructed a `QWheelEvent` at all, for either view, so the shared
    engine that step 2a of the table migration created was never
    exercised on the view it was created for.

    Built on BARE views, not the panel: with no panel above them the
    handler falls back to `SCROLL_SPEED`, so the arithmetic is a fixed
    number rather than whatever this machine's preference happens to
    be - and the numbers below are the contract, not a direction.
    """

    VIEWS = ("DragDropListView", "DragDropTableView")

    SPEED = dragdrop_widgets.GridGestureMixin.SCROLL_SPEED
    NOTCH = dragdrop_widgets.GridGestureMixin.WHEEL_NOTCH_PX

    def _view(self, name):
        """A real view with genuinely more content than viewport."""
        view = getattr(dragdrop_widgets, name)()
        self.addCleanup(view.deleteLater)
        model = QtGui.QStandardItemModel(400, 6)
        for row in range(400):
            for column in range(6):
                model.setItem(row, column, QtGui.QStandardItem(
                    "row %d column %d, wide enough to overflow" % (row, column)))
        self._model = model                      # keep alive
        view.setModel(model)
        view.resize(200, 150)
        view.show()
        self.addCleanup(view.hide)
        QtWidgets.QApplication.processEvents()
        return view

    @staticmethod
    def _wheel(pixel=(0, 0), angle=(0, 0)):
        at = QtCore.QPointF(10, 10)
        return QtGui.QWheelEvent(
            at, at, QtCore.QPoint(*pixel), QtCore.QPoint(*angle),
            QtCore.Qt.MouseButton.NoButton,
            QtCore.Qt.KeyboardModifier.NoModifier,
            QtCore.Qt.ScrollPhase.NoScrollPhase, False)

    def test_a_TRACKPAD_delta_moves_the_bar_by_the_scroll_speed(self):
        for name in self.VIEWS:
            with self.subTest(view=name):
                view = self._view(name)
                bar = view.verticalScrollBar()
                self.assertTrue(
                    bar.maximum(),
                    "the view has nothing to scroll - not a test")
                bar.setValue(0)
                view.wheelEvent(self._wheel(pixel=(0, -40)))
                self.assertEqual(
                    round(40 * self.SPEED), bar.value(),
                    "a pixel delta is not the user's speed applied to it")

    def test_a_CLASSIC_NOTCH_is_the_notch_size_not_Qts_own_step(self):
        """A mouse with no pixel data reports 120-unit notches only.
        A trackpad never reaches this branch, so it is exactly the
        path that goes untested on a laptop."""
        for name in self.VIEWS:
            with self.subTest(view=name):
                view = self._view(name)
                bar = view.verticalScrollBar()
                bar.setValue(0)
                view.wheelEvent(self._wheel(angle=(0, -120)))
                self.assertEqual(
                    round(self.NOTCH * self.SPEED), bar.value(),
                    "one notch is not WHEEL_NOTCH_PX at the user's speed")

    def test_a_SIDEWAYS_gesture_never_moves_the_view_DOWN(self):
        """The axis is a choice of scrollbar, and only that. The table
        is where it can be seen - a list of single-column items has no
        horizontal range - but the wrong-axis bug is worth pinning on
        BOTH, because falling through to the vertical bar is what a
        Y-only handler did."""
        for name in self.VIEWS:
            with self.subTest(view=name):
                view = self._view(name)
                vertical = view.verticalScrollBar()
                horizontal = view.horizontalScrollBar()
                vertical.setValue(0)
                horizontal.setValue(0)
                view.wheelEvent(self._wheel(pixel=(-40, 0)))
                self.assertEqual(
                    0, vertical.value(),
                    "a sideways gesture scrolled the view downwards")
                if horizontal.maximum():
                    self.assertEqual(
                        round(40 * self.SPEED), horizontal.value(),
                        "a sideways gesture did not move the sideways "
                        "bar by the user's speed")

    def test_the_TABLE_really_does_have_a_sideways_range(self):
        """Anti-vacuity for the test above: its horizontal assertion is
        conditional, so something has to prove the condition is met on
        at least one view, or the whole axis case could pass by never
        being reached."""
        view = self._view("DragDropTableView")
        self.assertTrue(
            view.horizontalScrollBar().maximum(),
            "the table fixture has no horizontal range, so the "
            "sideways assertion never ran anywhere")


class SelectingNeverScrollsTheGridTest(unittest.TestCase):
    """Built against the REAL panel, like the menu wiring tests: the
    thing being pinned is a property of the shipped thumblist, and a
    view built by the test would happily pass with the panel broken."""

    @classmethod
    def setUpClass(cls):
        # The ISOLATED panel: its own settings, its own library, its own
        # caches, no network, and - the reason this stopped using
        # _protect_live_settings on 2026-08-02 - NO registered file
        # locations. That guard only protected the settings file and the
        # log; the panel still opened the real library and the real File
        # locations, which on this machine are personal photograph and
        # texture archives. fixture_panel asserts every one of those
        # paths is inside the tempdir before it returns.
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_selecting_a_half_cut_tile_leaves_the_view_where_it_was(self):
        """The report, replayed: a small viewport, a tile that does not
        fully fit, current moved onto it - the scrollbar must not move.
        With autoScroll back on, Qt scrolls right here and this reads
        a changed value."""
        view = self.panel.thumblist
        model = view.model()
        if model is None or model.rowCount() < 2:
            self.skipTest("library too small to overflow a viewport")

        self.panel.resize(420, 320)
        self.panel.show()
        self.addCleanup(self.panel.hide)
        QtWidgets.QApplication.processEvents()
        view.scrollToTop()
        QtWidgets.QApplication.processEvents()

        viewport = view.viewport().rect()
        target = None
        for row in range(model.rowCount()):
            rect = view.visualRect(model.index(row, 0))
            if rect.isValid() and not viewport.contains(rect):
                target = model.index(row, 0)
                break
        if target is None:
            self.skipTest("every tile fits - nothing is half-cut")

        bar = view.verticalScrollBar()
        before = bar.value()
        view.selectionModel().setCurrentIndex(
            target, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            target, view.selectionModel().currentIndex(),
            "the selection did not land - the test is not testing")
        self.assertEqual(
            before, bar.value(),
            "the grid moved under the selection - the jump is back")

    def test_the_view_stays_put_through_the_view_mode_switch(self):
        """setViewMode() re-applies state behind the caller's back (it
        disarmed dragging once - recorded). Both modes must leave the
        no-self-scrolling contract standing."""
        view = self.panel.thumblist
        kept = self.panel.prefs.view_mode
        self.addCleanup(setattr, self.panel.prefs, "view_mode", kept)
        self.addCleanup(self.panel.apply_view_mode)
        for mode in ("grid", "list"):
            self.panel.prefs.view_mode = mode
            self.panel.apply_view_mode()
            self.assertFalse(
                view.hasAutoScroll(),
                "view mode %r turned autoScroll back on - selecting a "
                "half-cut tile jumps the grid again" % (mode,))


if __name__ == "__main__":
    unittest.main()
