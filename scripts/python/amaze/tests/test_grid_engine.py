"""The grid engine never sorts row lists out of step, which would pair a row with another's data."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import grid_columns, grid_engine, multifilterproxy_model  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401

DISPLAY = QtCore.Qt.ItemDataRole.DisplayRole


class Names(grid_engine.GridEngine, QtCore.QAbstractTableModel):
    """The smallest grid model: a name and a kind per row."""

    KindRole = QtCore.Qt.ItemDataRole.UserRole + 6
    COLUMN_ROLES = {"name": DISPLAY, "type": "KindRole"}
    GRID_ROWS = ("_names", "_kinds")

    def __init__(self, names):
        super().__init__()
        self._names = list(names)
        self._kinds = ["x"] * len(self._names)
        self.order_rows()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._names)

    def row_data(self, row, role):
        if role == DISPLAY:
            return self._names[row]
        return self._kinds[row] if role == self.KindRole else None


class TheOrderHoldsHoweverRowsChange(unittest.TestCase):

    def test_qm14_a_row_list_out_of_step_is_never_moved(self):
        model = Names(["b", "a"])
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(model)
        proxy.setDynamicSortFilter(False)
        model._kinds.append("orphan")    # one entry too many
        proxy.sort(grid_columns.KEYS.index("name"), QtCore.Qt.SortOrder.DescendingOrder)
        self.assertEqual(["a", "b"], model._names,
                         "rows moved while a row list was out of step")


if __name__ == "__main__":
    unittest.main()
