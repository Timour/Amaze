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
        url = updater.bug_report_url()
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
        """The press the Report a Bug button makes; only `open_url` is stubbed."""
        from amaze.core import updater
        from amaze.dialogs import prefs_window
        from amaze.helpers import ui_helpers
        state = prefs_window.AmazePrefsState(test_support.fixture_prefs(self), pane=None)
        with mock.patch.object(ui_helpers, "open_url") as open_url:
            state.reportBug()
        open_url.assert_called_once_with(updater.bug_report_url())


if __name__ == "__main__":
    unittest.main()
