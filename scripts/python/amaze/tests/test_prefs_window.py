"""Preferences as Houdini's own QML window: it loads, its pages, settings applied as before."""

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

PAGES = (("Library", "LibraryPage.qml"), ("Render", "RenderPage.qml"), ("UI", "UiPage.qml"),
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

    def test_the_library_page_holds_both_dialogs_and_each_opens_with_no_qml_error(self):
        self.window.setPageName("Library")
        self.assertTrue(test_support.pump_until(
            lambda: self.root.property("currentUrl").endswith("/LibraryPage.qml")
            and self.root.property("currentPage") is not None))
        page = self.root.property("currentPage")
        for name in ("ManageLibrariesDialog", "UserNameDialog"):
            with self.subTest(dialog=name):
                found = [one for one in page.findChildren(QtCore.QObject)
                         if one.metaObject().className().split("_QMLTYPE_")[0] == name]
                self.assertEqual(1, len(found), "the Library page does not hold %s" % name)
                QtCore.QMetaObject.invokeMethod(found[0], "open")
                self.assertTrue(test_support.pump_until(lambda: found[0].property("opened")))
                QtCore.QMetaObject.invokeMethod(found[0], "close")
                self.assertTrue(test_support.pump_until(lambda: not found[0].property("visible")))
        self.assertEqual([], self._qml_messages())

    def test_the_page_list_holds_the_five_pages_in_order(self):
        rows = self.root.property("pageModel").toVariant()
        self.assertEqual(list(PAGES), [(row["text"], os.path.basename(row["url"].toLocalFile()))
                                       for row in rows])


class TheCheckDatabaseLineSaysWhatTheCheckFound(unittest.TestCase):
    """Check Database: after a check, the line beside the button states its result."""

    def test_after_a_check_the_line_shows_the_result_not_the_format(self):
        panel = test_support.fixture_panel(self)
        window = prefs_window.AmazePrefsWindow(panel.pane.prefs, pane=panel.pane)
        self.addCleanup(QtCore.QCoreApplication.sendPostedEvents, None,
                        QtCore.QEvent.Type.DeferredDelete)
        self.addCleanup(window.close)
        window.show()
        window.setPageName("Library")
        root = window.rootObject()
        self.assertTrue(test_support.pump_until(
            lambda: root.property("currentUrl").endswith("/LibraryPage.qml")
            and root.property("currentPage") is not None))
        state = window.sharedState()

        def items(item):
            yield item
            for child in item.childItems():
                yield from items(child)

        def shown():    # every text on screen: QML's own items, walked as the scene holds them
            return [one.property("text") for one in items(window.contentItem())
                    if one.inherits("QQuickText")]    # Houdini's `Text` is a QML type over Qt's
        test_support.pump_until(lambda: state.libraryFormat in shown())
        self.assertIn(state.libraryFormat, shown(), "premise: before a check the line shows the format")

        state.checkOrRepair()    # the button, as `Check`
        self.assertTrue(state.checkInfo, "premise: the check found nothing to say")
        test_support.pump_until(lambda: state.checkInfo in shown())
        self.assertIn(state.checkInfo, shown(), "the line still shows the format, not the result")


class AUiSettingIsAppliedLikeTheOldDialog(unittest.TestCase):
    """A change waits for Apply, as in Houdini's window; then it is saved and its side effect runs."""

    def test_system_file_icons_reaches_the_prefs_on_apply_and_the_file_tab_relists(self):
        prefs = test_support.fixture_prefs(self)
        prefs.save()
        files = mock.Mock(preferences=prefs_mod.Prefs())    # the File model's own Prefs ▸p/one-model-set
        pane = types.SimpleNamespace(file_files_model=files,
                                     library=types.SimpleNamespace(serves=lambda _folder: True))
        state = prefs_window.AmazePrefsState(prefs, pane)
        self.assertTrue(prefs.system_file_icons, "premise: on")

        state.setPref("system_file_icons", "1")    # Show Generic File Icons switched on
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


class OneSectionAlwaysStaysOn(unittest.TestCase):
    """As the old dialog: the last section switched off turns Material on; Material stays on."""

    def test_the_rule_is_one_undo_step_and_apply_keeps_tab_order_and_unknown_keys(self):
        prefs = _scratch_prefs(self)
        prefs.enabled_sections = ["code", "an_add_on_section"]
        state = prefs_window.AmazePrefsState(prefs)
        code, material = prefs_window.SECTION + "code", prefs_window.MATERIAL

        state.setPref(code, "0")    # what the Code switch sends
        self.assertEqual((False, True), (state.getBool(code), state.getBool(material)))
        state.undo()
        self.assertEqual((True, False), (state.getBool(code), state.getBool(material)),
                         "the rule's change took a second undo step")
        state.redo()
        state.setPref(material, "0")
        self.assertTrue(state.getBool(material), "the last section on was switched off")

        state.apply()
        self.assertEqual(["material", "an_add_on_section"], prefs.enabled_sections)


class TheUpdateButtonChecksThenInstalls(unittest.TestCase):
    """One button: a press checks; a release found turns it to Install Update; a press installs."""

    def test_a_check_offers_the_release_and_the_install_withdraws_the_offer(self):
        from amaze.core import updater
        from amaze.dialogs import update_dialog
        state = prefs_window.AmazePrefsState(_scratch_prefs(self))
        found = updater.Update(updater.NEWER, version="9.9",
                               url="https://example.invalid/r.zip", sentence="newer")

        with mock.patch.object(updater, "check", return_value=found):
            state.pressUpdate()
        self.assertEqual(("Install Update", True, "newer"),
                         (state.updateLabel, state.updateOffered, state.versionLine))

        with mock.patch.object(update_dialog, "confirmed", return_value=True), \
                mock.patch.object(updater, "install") as install:
            state.pressUpdate()
        install.assert_called_once_with(found)
        self.assertEqual(("Check for Updates", False, False),
                         (state.updateLabel, state.updateOffered, state.updateBusy))
        self.assertIn("9.9", state.versionLine)


if __name__ == "__main__":
    unittest.main()
