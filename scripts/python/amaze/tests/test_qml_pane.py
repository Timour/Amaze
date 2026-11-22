"""The Amaze (QML) pane builds, loads its QML silently, and Qt deletes it on the main thread."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # the first QApplication picks the platform ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtWidgets
import shiboken6

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.qml import pane as qml_pane  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class TheQmlPaneOpensAndCloses(unittest.TestCase):

    def test_it_builds_with_no_qml_warning_and_qt_deletes_it_on_the_main_thread(self):
        widget_panel = test_support.fixture_panel(self)    # the fixture library, and a second pane on it
        said = []

        def hear(_kind, context, text):
            if ".qml" in text or context.category in ("qml", "js"):
                said.append(text)

        previous = QtCore.qInstallMessageHandler(hear)
        try:
            panel = qml_pane.QmlPanel()
            self.addCleanup(test_support.stop_panel_workers, panel)
            panel.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
            panel.resize(840, 420)
            panel.show()
            QtWidgets.QApplication.processEvents()
        finally:
            QtCore.qInstallMessageHandler(previous)

        self.assertEqual([], said, "the pane's QML reported errors or warnings while it loaded")
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


if __name__ == "__main__":
    unittest.main()
