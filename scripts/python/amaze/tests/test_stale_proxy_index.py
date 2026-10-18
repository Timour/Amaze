"""`live_current_index` is defence in depth, NOT a proven crash fix."""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets       # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.helpers import ui_helpers                      # noqa: E402
from amaze.tests import test_support                      # noqa: E402,F401


def _model(rows):
    model = QtGui.QStandardItemModel()
    for text in rows:
        model.appendRow(QtGui.QStandardItem(text))
    return model


def _proxied_view(rows):
    """A view over a proxy, exactly the sidebar's shape."""
    source = _model(rows)
    proxy = QtCore.QSortFilterProxyModel()
    proxy.setSourceModel(source)
    view = QtWidgets.QListView()
    view.setModel(proxy)
    return view, proxy, source


class LiveCurrentIndexTest(unittest.TestCase):

    def test_a_healthy_current_index_comes_back(self):
        """Guards the guard - always-None would pass every refusal test."""
        view, proxy, _source = _proxied_view(["All", "Metal", "Fabric"])
        view.setCurrentIndex(view.model().index(1, 0))
        live = ui_helpers.live_current_index(view)
        self.assertIsNotNone(live, "a valid current index was refused")
        self.assertEqual("Metal", live.data())
        self.assertIs(live.model(), proxy)

    def test_a_TABLE_current_index_comes_back_at_column_ZERO(self):
        """The helper answers THE ROW: column 0, wherever the click landed."""
        model = QtGui.QStandardItemModel(3, 5)
        view = QtWidgets.QTableView()
        view.setModel(model)
        view.setCurrentIndex(model.index(1, 3))  # a click lands on the CELL, and grid_columns answers roles only on the owning column ▸r/row-selection
        live = ui_helpers.live_current_index(view)
        self.assertIsNotNone(live)
        self.assertEqual(1, live.row())
        self.assertEqual(
            0, live.column(),
            "the helper hands back the clicked cell, and every role "
            "read through it answers None")

    def test_an_index_from_a_previous_model_is_refused(self):
        """The one shape refused: an index built by the PREVIOUS model."""
        view, _proxy, _source = _proxied_view(["All", "Metal"])
        view.setCurrentIndex(view.model().index(1, 0))
        stale = view.currentIndex()
        other_source = _model(["Wood", "Stone"])
        other = QtCore.QSortFilterProxyModel()
        other.setSourceModel(other_source)
        view.setModel(other)  # a section switch replaces the model outright; the drag path hit this once
        self.assertIsNot(stale.model(), view.model())
        self.assertIsNone(
            ui_helpers.live_current_index(view),
            "an index belonging to a model the view no longer shows was "
            "accepted")

    def test_no_view_model_or_selection_is_refused(self):
        unselected, _proxy, _source = _proxied_view(["All", "Metal"])
        for case, view in (("no view - cat_list before setup()", None),
                           ("no model", QtWidgets.QListView()),
                           ("no selection", unselected)):
            with self.subTest(case):
                self.assertIsNone(ui_helpers.live_current_index(view))


class NoStoredProxyIndexIsReadInThePanelTest(unittest.TestCase):
    """Source-derived: the fix is a HABIT, and a sixth site would be silent."""

    def test_every_current_index_read_goes_through_the_helper(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
        offenders = []
        for n, line in enumerate(lines, 1):
            if ".currentIndex()" not in line:
                continue
            if "live_current_index" in line:
                continue
            if "# not a proxy" in line:  # a read on a plain model is safe; the sidebar and the grid are the proxied ones
                continue
            offenders.append("%d: %s" % (n, line.strip()))
        self.assertEqual(
            [], offenders,
            "a stored index is read directly - route it through "
            "ui_helpers.live_current_index, or mark the line "
            "'# not a proxy' if its model genuinely is not one:\n  "
            + "\n  ".join(offenders))


class WorksOnAPlainPythonModelTest(unittest.TestCase):
    """The helper works on a PLAIN Python model, not only on a C++ proxy."""

    class _ListModel(QtCore.QAbstractListModel):
        """Sidebar-shaped: rowCount(parent=None), columnCount inherited."""

        def __init__(self, rows):
            super().__init__()
            self._rows = list(rows)

        def rowCount(self, parent=None) -> int:  # the shape FolderListModel has
            return len(self._rows)

        def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
            if role == QtCore.Qt.ItemDataRole.DisplayRole:
                return self._rows[index.row()]
            return None

    def _view(self, rows):
        model = self._ListModel(rows)
        view = QtWidgets.QListView()
        view.setModel(model)
        view._amaze_keepalive = model      # outlive the method
        return view

    def test_a_plain_python_model_does_not_raise(self):
        view = self._view(["All", "HDR", "IMG"])
        view.setCurrentIndex(view.model().index(1, 0))
        live = ui_helpers.live_current_index(view)   # raised TypeError: a bare columnCount() works on a C++ proxy and not on a Python model ▸r/model-contracts
        self.assertIsNotNone(live, "a valid index on a plain list model "
                                   "was refused")
        self.assertEqual("HDR", live.data())


if __name__ == "__main__":
    unittest.main(verbosity=2)
