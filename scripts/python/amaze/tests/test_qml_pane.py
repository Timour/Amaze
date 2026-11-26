"""The Amaze (QML) pane builds on the main thread and Qt deletes all of it when it closes."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # the first QApplication picks the platform ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtQuick, QtTest, QtWidgets
import shiboken6

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.qml import pane as qml_pane  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class TheQmlPaneOpensAndCloses(unittest.TestCase):

    def test_qm15_qt_deletes_the_pane_and_its_engine_on_the_main_thread(self):
        widget_panel = test_support.fixture_panel(self)    # the fixture library, and a second pane on it
        panel = qml_pane.QmlPanel()
        self.addCleanup(test_support.stop_panel_workers, panel)
        panel.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        panel.resize(840, 420)
        panel.show()
        QtWidgets.QApplication.processEvents()
        self.assertIsNotNone(panel.view.rootObject(), "the pane's QML did not load")
        self.assertIsNot(widget_panel.pane, panel.pane, "the two panes share one engine")
        self.assertIs(widget_panel.pane.material_model, panel.pane.material_model,
                      "the two panes on one library read separate models")

        parts = (panel, panel.view, panel.state, panel.pane)
        main = QtWidgets.QApplication.instance().thread()
        self.assertTrue(all(part.thread() == main for part in parts), "a part lives off the main thread")
        panel.close()
        panel.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)    # Qt's own loop, no collector
        self.assertEqual([False] * len(parts), [shiboken6.isValid(part) for part in parts],
                         "the pane, its QML view, its state or its engine outlived the close")

    def test_qm16_qt_acts_once_on_a_click_on_a_sidebar_row(self):
        test_support.fixture_panel(self)
        panel = qml_pane.QmlPanel()
        self.addCleanup(test_support.stop_panel_workers, panel)
        self.addCleanup(panel.deleteLater)
        panel.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        panel.resize(840, 420)
        panel.show()
        QtWidgets.QApplication.processEvents()
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


if __name__ == "__main__":
    unittest.main()
