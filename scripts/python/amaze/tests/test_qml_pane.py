"""The Amaze pane builds on the main thread and Qt deletes all of it when it closes."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # the first QApplication picks the platform ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtQuick, QtTest, QtWidgets
import shiboken6

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.tests import test_support  # noqa: E402


class TheQmlPaneOpensAndCloses(unittest.TestCase):

    def test_qm15_qt_deletes_the_pane_and_its_engine_on_the_main_thread(self):
        panel = test_support.fixture_qml_pane(self)
        self.assertIsNotNone(panel.view.rootObject(), "the pane's QML did not load")

        parts = (panel, panel.view, panel.state, panel.pane)
        main = QtWidgets.QApplication.instance().thread()
        self.assertTrue(all(part.thread() == main for part in parts), "a part lives off the main thread")
        panel.close()
        panel.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)    # Qt's own loop, no collector
        self.assertEqual([False] * len(parts), [shiboken6.isValid(part) for part in parts],
                         "the pane, its QML view, its state or its engine outlived the close")

    def test_qm16_qt_acts_once_on_a_click_on_a_sidebar_row(self):
        panel = test_support.fixture_qml_pane(self)
        tree = next(item for item in panel.view.rootObject().findChildren(QtQuick.QQuickItem)
                    if item.metaObject().className().startswith("SidebarTree"))
        taps = []    # the tree's drag scrolling each time Qt's own tap handler reports the release
        tree.findChild(QtCore.QObject, "tableViewTapHandler").singleTapped.connect(
            lambda *_point: taps.append(tree.property("interactive")))
        at = tree.mapToScene(QtCore.QPointF(tree.width() - 30, 1.5 * 20)).toPoint()    # the second row
        QtTest.QTest.mouseClick(panel.view, QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.KeyboardModifier.NoModifier, at)
        self.assertEqual(([False], 1), (taps, panel.state.sidebarSelection.currentIndex().row()),
                         "(drag scrolling at Qt's tap, the current row): on, Qt acts on the release too")

    def test_qm17_show_tooltips_off_in_preferences_shows_no_tip_anywhere(self):
        """Every QML tip reads `tipsShown` first (check-code's `tips_follow_the_switch`)."""
        from unittest import mock
        from amaze.dialogs import versions_window
        from amaze.prefs import persistence, prefs as prefs_mod
        panel = test_support.fixture_qml_pane(self)
        self.assertTrue(panel.state.tipsShown, "a pane with Show Tooltips on hides its tips")
        panel.state.show_prefs()
        prefs = panel.state._prefs_window.sharedState()
        prefs.setPref("show_tooltips", "0")
        with mock.patch.object(prefs_mod.Prefs, "save", persistence._Persistence.save):    # Apply re-reads it
            prefs.apply()
        self.assertFalse(panel.state.tipsShown, "Show Tooltips off and applied, the pane still tips")
        window = versions_window.ask(panel.state, "Wood", [{"n": 1}], 1, lambda _number: None)
        self.assertFalse(window.sharedState().tipsShown, "a window opened after it shows tips")
        with mock.patch("hutil.qt.tooltip.displayHtml") as houdini_tip:
            prefs.showHelpTip("", "", "sidebar_counts")
            self.assertFalse(houdini_tip.called, "a Preferences row showed its tip")
            prefs.ctrlHeld = True    # as Houdini's window: Control held shows a row's tip at once
            prefs.showHelpTip("", "", "sidebar_counts")
            self.assertTrue(houdini_tip.called, "Control held, the row's tip did not show")


if __name__ == "__main__":
    unittest.main()
