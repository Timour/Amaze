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
        view, _proxy, _source = _proxied_view(["All", "Metal", "Fabric"])
        view.setCurrentIndex(view.model().index(1, 0))
        live = ui_helpers.live_current_index(view)
        self.assertIsNotNone(live, "a valid current index was refused")
        self.assertEqual("Metal", live.data())

    def test_the_returned_index_is_freshly_built_by_the_live_model(self):
        """Not the stored one handed back. The point is to re-derive."""
        view, proxy, _source = _proxied_view(["All", "Metal"])
        view.setCurrentIndex(view.model().index(1, 0))
        live = ui_helpers.live_current_index(view)
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

    def test_qt_keeps_current_index_consistent_through_every_shrink(self):
        """A NEGATIVE result: Qt leaves no out-of-bounds current index."""
        cases = {}  # red here means a Qt/PySide change reopened the stale-index theory ▸r/model-contracts

        view, proxy, source = _proxied_view(["All", "Metal", "Fabric"])
        view.setCurrentIndex(proxy.index(2, 0))
        source.removeRows(1, 2)
        cases["removeRows"] = (view.currentIndex(), proxy)

        view, proxy, source = _proxied_view(["All", "Metal", "Fabric"])
        view.setCurrentIndex(proxy.index(2, 0))
        source.clear()
        cases["clear"] = (view.currentIndex(), proxy)

        view, proxy, source = _proxied_view(["All", "Metal", "Fabric"])
        view.setCurrentIndex(proxy.index(2, 0))
        proxy.setFilterFixedString("All")
        cases["filter shrinks"] = (view.currentIndex(), proxy)

        view, proxy, source = _proxied_view(["All", "Metal", "Fabric"])
        view.setCurrentIndex(proxy.index(2, 0))
        for row in reversed(range(3)):
            source.takeRow(row)
        cases["takeRow, no reset"] = (view.currentIndex(), proxy)

        for name, (index, proxy) in cases.items():
            if index.isValid():
                self.assertLess(
                    index.row(), proxy.rowCount(),
                    "%s left a VALID current index past rowCount - the "
                    "stale-index theory this file rejects would be live "
                    "again, and reading it would segfault" % name)

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

    def test_a_view_with_no_model_is_refused(self):
        self.assertIsNone(
            ui_helpers.live_current_index(QtWidgets.QListView()))

    def test_no_view_at_all_is_refused(self):
        """cat_list is None before setup(), and a tab click gets here."""
        self.assertIsNone(ui_helpers.live_current_index(None))

    def test_no_selection_is_refused_rather_than_guessed(self):
        view, _proxy, _source = _proxied_view(["All", "Metal"])
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

    def test_no_selection_on_a_plain_python_model_is_refused(self):
        self.assertIsNone(
            ui_helpers.live_current_index(self._view(["All"])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
