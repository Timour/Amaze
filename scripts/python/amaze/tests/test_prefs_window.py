"""Preferences as Houdini's own QML window: it loads, its page list, a Look setting applied."""

import os
import shutil
import sys
import types
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtQuick, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.dialogs import prefs_window  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PAGES = (("Library", "LibraryPage.qml"), ("Render", "RenderPage.qml"),
         ("Show/Hide", "ShowHidePage.qml"), ("Look", "LookPage.qml"),
         ("Add-On", "AddOnPage.qml"), ("About", "AboutPage.qml"))
NO_PICTURE = "Failed to get image from provider"    # headless, Houdini's icon providers give none


def _scratch_prefs(testcase):
    """Prefs with no library, saved in a folder of its own."""
    prefs = prefs_mod.Prefs()
    prefs.path = test_support.scratch_dir("amaze_prefs_window_")
    testcase.addCleanup(shutil.rmtree, prefs.path, True)
    return prefs


class TheWindowLoads(unittest.TestCase):
    """The window, its root and each of its pages load with no QML error."""

    @classmethod
    def setUpClass(cls):
        cls.messages = []
        QtCore.qInstallMessageHandler(lambda _mode, _context, text: cls.messages.append(text))
        cls.addClassCleanup(QtCore.qInstallMessageHandler, None)
        cls.window = prefs_window.AmazePrefsWindow(_scratch_prefs(test_support.class_scope(cls)))
        cls.addClassCleanup(cls._close)
        cls.window.show()
        cls.root = cls.window.rootObject()

    @classmethod
    def _close(cls):
        cls.window.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)

    def _qml_messages(self):
        return [text for text in self.messages if ".qml" in text and NO_PICTURE not in text]

    def test_the_root_and_every_page_load_with_no_qml_error(self):
        self.assertEqual(QtQuick.QQuickView.Status.Ready, self.window.status(),
                         [error.toString() for error in self.window.errors()])
        for name, page_file in PAGES:
            with self.subTest(page=name):
                self.window.setPageName(page_file[:-len("Page.qml")])
                shown = test_support.pump_until(
                    lambda: self.root.property("currentPage") is not None
                    and self.root.property("currentUrl").endswith("/" + page_file))
                self.assertTrue(shown, "the page did not load: %s" % self._qml_messages())
        self.assertEqual([], self._qml_messages())

    def test_the_page_list_holds_the_six_pages_in_order(self):
        rows = self.root.property("pageModel").toVariant()
        self.assertEqual(list(PAGES), [(row["text"], os.path.basename(row["url"].toLocalFile()))
                                       for row in rows])


class ALookSettingIsAppliedLikeTheOldDialog(unittest.TestCase):
    """A change waits for Apply, as in Houdini's window; then it is saved and its side effect runs."""

    def test_system_file_icons_reaches_the_prefs_on_apply_and_the_file_tab_relists(self):
        prefs = test_support.fixture_prefs(self)
        prefs.save()
        files = mock.Mock(preferences=prefs_mod.Prefs())    # the File model's own Prefs ▸p/one-model-set
        state = prefs_window.AmazePrefsState(prefs, types.SimpleNamespace(file_files_model=files))
        self.assertTrue(prefs.system_file_icons, "premise: on")

        state.setPref("system_file_icons", "0")    # what the row's switch sends
        self.assertTrue(prefs.system_file_icons, "the change reached the prefs before Apply")
        files.refresh_current_folder.assert_not_called()

        state.apply()
        self.assertFalse(prefs.system_file_icons)
        saved = prefs_mod.Prefs()
        saved.path = prefs.path
        saved.load()
        self.assertFalse(saved.system_file_icons, "Apply did not save it")
        self.assertFalse(files.preferences.system_file_icons)
        files.refresh_current_folder.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
