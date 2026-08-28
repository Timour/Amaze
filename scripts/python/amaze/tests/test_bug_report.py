"""The Report a Bug button: the repo's new-issue page with the three machine facts pre-filled - GitHub's documented query parameters carry them, so no token, no server, and nothing is sent by opening the page."""

import os
import platform
import unittest
import urllib.parse

from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

from amaze import branding  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class TheBugReportCarriesTheMachine(unittest.TestCase):
    def test_the_url_is_the_new_issue_page_with_the_three_facts(self):
        """Amaze version, Houdini build and OS - the three facts a report is useless without, correct for THIS machine, on their own lines, through the same `QUrl` the click hands the OS."""
        from PySide6 import QtCore
        from amaze.core import updater
        from amaze.dialogs import prefs_dialog
        url = prefs_dialog.bug_report_url()
        self.assertTrue(url.startswith(updater.NEW_ISSUE_URL + "?body="),
                        "not the new-issue page: %r" % url)
        parts = urllib.parse.urlsplit(url)
        expected = ("Amaze: %s\nHoudini: %s\nOS: %s\n\nWhat happened:\n"
                    % (branding.APP_VERSION,
                       hou.applicationVersionString(),
                       platform.platform()))
        self.assertIn("%0A", parts.query,    # urlsplit STRIPS raw newlines silently, so only the encoded form proves the lines survived
                      "the newlines were lost in the encoding")
        self.assertEqual(
            expected, urllib.parse.parse_qs(parts.query)["body"][0])
        qurl = QtCore.QUrl(url)
        self.assertTrue(qurl.isValid())
        self.assertEqual(
            "body=" + expected,
            qurl.query(QtCore.QUrl.ComponentFormattingOption.FullyDecoded),
            "QUrl hands the OS something other than what was built")

    def test_the_button_opens_exactly_that_url(self):
        """Through the real button, so the wiring is what is proven - only the browser door itself is stubbed."""
        from amaze.dialogs import prefs_dialog
        prefs = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(prefs, panel=None)
        self.addCleanup(dlg.deleteLater)
        with mock.patch.object(prefs_dialog, "_open_url") as door:
            dlg._btn_report.click()
        door.assert_called_once_with(prefs_dialog.bug_report_url())


if __name__ == "__main__":
    unittest.main()
