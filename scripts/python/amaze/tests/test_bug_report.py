"""Report a Bug opens the new-issue page, machine facts in query parameters; nothing is sent."""

import os
import platform
import unittest
import urllib.parse

from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze import branding  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class TheBugReportIncludesTheVersions(unittest.TestCase):
    def test_the_url_is_the_new_issue_page_with_the_three_facts(self):
        """Amaze, Houdini and OS versions, one per line, intact in the `QUrl` the button opens."""
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
        self.assertIn("%0A", parts.query,    # urlsplit strips raw newlines; only the encoded form shows them
                      "the newlines were lost in the encoding")
        self.assertEqual(
            expected, urllib.parse.parse_qs(parts.query)["body"][0])
        qurl = QtCore.QUrl(url)
        self.assertTrue(qurl.isValid())
        self.assertEqual(
            "body=" + expected,
            qurl.query(QtCore.QUrl.ComponentFormattingOption.FullyDecoded),
            "QUrl passes the OS a different query from the one built")

    def test_the_button_opens_exactly_that_url(self):
        """Clicks the real button, so its connection is tested; only `_open_url` is stubbed."""
        from amaze.dialogs import prefs_dialog
        prefs = test_support.fixture_prefs(self)
        dlg = prefs_dialog.PrefsDialog(prefs, panel=None)
        self.addCleanup(dlg.deleteLater)
        with mock.patch.object(prefs_dialog, "_open_url") as open_url:
            dlg._btn_report.click()
        open_url.assert_called_once_with(prefs_dialog.bug_report_url())


if __name__ == "__main__":
    unittest.main()
