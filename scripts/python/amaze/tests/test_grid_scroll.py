"""Selecting a tile never moves the grid: Qt autoScroll re-scrolls on every currentChanged."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.panel import dragdrop_widgets  # noqa: E402
from amaze.panel import grid  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - redirects the log


class OneWheelHandlerServesBothViews(unittest.TestCase):
    """One wheel handler for both views and axes; a view without prefs uses `SCROLL_SPEED`."""

    VIEWS = ("DragDropListView", "DragDropRowsView")

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
                    "a pixel delta did not move the bar by delta times the scroll speed")
                bar.setValue(0)    # a mouse with no pixel data: 120-unit notches only
                view.wheelEvent(self._wheel(angle=(0, -120)))
                self.assertEqual(
                    round(self.NOTCH * self.SPEED), bar.value(),
                    "one notch is not WHEEL_NOTCH_PX at the user's speed")

    def test_a_SIDEWAYS_gesture_never_moves_the_view_DOWN(self):
        """The gesture's axis decides which scrollbar moves; checked on both views."""
        for name in self.VIEWS:
            with self.subTest(view=name):
                view = self._view(name)
                vertical = view.verticalScrollBar()
                horizontal = view.horizontalScrollBar()
                if name == "DragDropRowsView":    # otherwise the horizontal check below never runs
                    self.assertTrue(horizontal.maximum(),
                                    "the table fixture has no horizontal range")
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


class SelectingNeverScrollsTheGridTest(unittest.TestCase):
    """Uses the real panel, so the check runs on the panel's own `thumblist` view."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))  # an isolated panel, every path in the tempdir

    def test_selecting_a_partly_visible_tile_does_not_move_the_scrollbar(self):
        """A partly visible tile made current in a small viewport does not move the scrollbar."""
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
            self.skipTest("every tile fits - no tile is partly visible")

        bar = view.verticalScrollBar()
        before = bar.value()
        view.selectionModel().setCurrentIndex(
            target, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            target, view.selectionModel().currentIndex(),
            "the current index was not set - the test checks nothing")
        self.assertEqual(
            before, bar.value(),
            "the scrollbar moved when the current index changed")

    def test_the_scrollbar_does_not_move_when_the_view_mode_switches(self):
        """`setViewMode()` re-applies view state, so both modes must keep the view from self-scrolling."""
        kept = self.panel.prefs.view_mode
        self.addCleanup(setattr, self.panel.prefs, "view_mode", kept)
        self.addCleanup(self.panel.apply_view_mode)
        for mode in ("grid", "list"):
            self.panel.prefs.view_mode = mode
            self.panel.apply_view_mode()
            view = grid.visible_view(self.panel)  # the visible view; `thumblist` is hidden in list mode
            self.assertFalse(
                view.hasAutoScroll(),
                "view mode %r turned autoScroll back on - selecting a "
                "partly visible tile scrolls the grid again" % (mode,))


if __name__ == "__main__":
    unittest.main()
