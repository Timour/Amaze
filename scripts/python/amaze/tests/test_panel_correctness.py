"""One engine guard left from the panel tests: a stale versions badge opens no window."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

from amaze.tests import test_support  # noqa: E402


class AStaleVersionsBadgeOpensNothing(unittest.TestCase):
    """An index that maps to no row is no material: row -1 indexes the LAST asset."""

    def test_an_index_with_no_row_opens_no_versions_window(self):
        from amaze.dialogs import versions_dialog
        panel = test_support.fixture_panel(self)
        model, opened = panel.pane.material_model, []
        self.assertTrue(model.assets, "premise: the fixture library holds materials")

        def dialog(name, *_args, **_kwargs):
            opened.append(name)
            return mock.Mock(exec=lambda: QtWidgets.QDialog.DialogCode.Rejected)

        with mock.patch.object(versions_dialog, "VersionsDialog", dialog), \
                mock.patch.object(model, "version_list", lambda row: (["v1", "v2"], "v1")):
            panel.pane.assets.open_versions(QtCore.QModelIndex(), panel.pane.material_sorted_model,
                                            model)
        self.assertEqual([], opened, "a stale badge opened another material's versions")


if __name__ == "__main__":
    unittest.main()
