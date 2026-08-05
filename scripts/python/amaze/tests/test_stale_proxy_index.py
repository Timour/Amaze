"""Reading a stored index through a proxy - and the theory this KILLED.

2026-07-30 00:13, Houdini 22.0.394, signal 11. A section-tab
click reached _capture_section_state, which called `.data()` on the
sidebar's stored currentIndex. The sidebar's model is a
QSortFilterProxyModel, so that call went straight into
mapToSource -> proxy_to_source and died there:

    9  QSortFilterProxyModel::data
    8  QSortFilterProxyModelWrapper::mapToSource
    7  QSortFilterProxyModelPrivate::proxy_to_source   <- SEGV

Nothing reached the debug log, because a SIGSEGV is not a Python
exception - @debug.guarded and the excepthook both see it and can do
nothing. The crash was localised by which log line was MISSING: the
`switched` event two statements later never appeared.

`isValid()` is a weak check either way - row >= 0, column >= 0 and a
non-null model POINTER, nothing about whether the model still holds that
row. That much is true and is why the helper does not rely on it.

*** THE FIRST DIAGNOSIS WAS WRONG, AND THIS FILE IS WHY. ***
The crash was blamed on a shrinking model leaving the view's
currentIndex valid-but-out-of-bounds. Writing the test below disproved
it in one run: Qt maintains currentIndex through removeRows, clear,
reset, setSourceModel, a filter change and takeRow-without-reset. So
currentIndex is NOT the vector, the research.md entry claiming it was
has been corrected, and THE CAUSE OF THE CRASH REMAINS UNKNOWN.

`live_current_index` is kept anyway: refusing an index that belongs to a
model the view no longer shows is correct on its own merits and costs
four comparisons. It is defence in depth, NOT a proven fix - and it must
never be described as one.

The one shape that IS still refused, and matters: an index from a
PREVIOUS model after a section switch replaces the view's model. That is
a real bug the drag path already hit once, where an ONLINE index read
through the MATERIAL proxy dragged whichever local material sat at that
row.
"""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

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
        """Guards the guard. A helper that always returns None would pass
        every refusal test below while breaking the whole sidebar."""
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

    def test_qt_keeps_current_index_consistent_through_every_shrink(self):
        """A NEGATIVE result, pinned deliberately.

        This test was written to prove that a shrinking model leaves the
        view's currentIndex valid-but-out-of-bounds, which is what the
        crash was first blamed on. It disproved that immediately, and the
        wiki entry asserting it has been corrected. Measured on 22.0.395:
        Qt maintains currentIndex through all six shapes below - so
        currentIndex is NOT the vector for a proxy_to_source segfault.

        Kept because the conclusion rests on it: if a future Qt or PySide
        ever DOES leave an out-of-bounds current index, this goes red and
        the reasoning above needs revisiting.
        """
        cases = {}

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
        """A section switch replaces the model outright, and mapping an
        old proxy's index through the new one is the bug the drag path
        already hit once."""
        view, _proxy, _source = _proxied_view(["All", "Metal"])
        view.setCurrentIndex(view.model().index(1, 0))
        stale = view.currentIndex()
        other_source = _model(["Wood", "Stone"])
        other = QtCore.QSortFilterProxyModel()
        other.setSourceModel(other_source)
        view.setModel(other)
        self.assertIsNot(stale.model(), view.model())
        self.assertIsNone(
            ui_helpers.live_current_index(view),
            "an index belonging to a model the view no longer shows was "
            "accepted")

    def test_a_view_with_no_model_is_refused(self):
        self.assertIsNone(
            ui_helpers.live_current_index(QtWidgets.QListView()))

    def test_no_view_at_all_is_refused(self):
        """cat_list is None before setup() runs, and a tab click is
        reachable before that."""
        self.assertIsNone(ui_helpers.live_current_index(None))

    def test_no_selection_is_refused_rather_than_guessed(self):
        view, _proxy, _source = _proxied_view(["All", "Metal"])
        self.assertIsNone(ui_helpers.live_current_index(view))


class NoStoredProxyIndexIsReadInThePanelTest(unittest.TestCase):
    """Source-derived, because the fix is a HABIT and a sixth site would
    reintroduce the crash silently. Five sites were converted; this fails
    if a new `.currentIndex()` appears without going through the helper.
    """

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
            # A read on a plain (non-proxy) model is safe; the sidebar and
            # the grid are the proxied ones. Anything else must say so.
            if "# not a proxy" in line:
                continue
            offenders.append("%d: %s" % (n, line.strip()))
        self.assertEqual(
            [], offenders,
            "a stored index is read directly - route it through "
            "ui_helpers.live_current_index, or mark the line "
            "'# not a proxy' if its model genuinely is not one:\n  "
            + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class WorksOnAPlainPythonModelTest(unittest.TestCase):
    """THE SHIPPED BUG, 2026-07-30. The helper called `rowCount()` and
    `columnCount()` with no argument. That works on a C++ proxy, whose
    binding supplies the default parent, and RAISES on a Python model
    whose binding does not:

        TextureFolders.columnCount() takes exactly one argument (0 given)

    It fired on every switch to a section whose sidebar is a plain list
    model rather than a proxy - eight times across two sessions before
    the debug log was read. Every earlier test in this file used a proxy,
    which is exactly why none of them caught it.
    """

    class _ListModel(QtCore.QAbstractListModel):
        """A sidebar-shaped model: rowCount takes parent=None, and
        columnCount is inherited rather than defined - the shape
        FolderListModel has."""

        def __init__(self, rows):
            super().__init__()
            self._rows = list(rows)

        def rowCount(self, parent=None) -> int:
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
        live = ui_helpers.live_current_index(view)   # raised TypeError
        self.assertIsNotNone(live, "a valid index on a plain list model "
                                   "was refused")
        self.assertEqual("HDR", live.data())

    def test_no_selection_on_a_plain_python_model_is_refused(self):
        self.assertIsNone(
            ui_helpers.live_current_index(self._view(["All"])))
