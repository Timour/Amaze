"""The grid engine: one data() for every grid model, which sorts its own rows. ▸p/grid-engine"""

import os
import random
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import grid_columns, grid_engine, multifilterproxy_model  # noqa: E402
from amaze.tests import test_support  # noqa: E402

DISPLAY = QtCore.Qt.ItemDataRole.DisplayRole
NAME = grid_columns.KEYS.index("name")
TYPE = grid_columns.KEYS.index("type")
DOWN = QtCore.Qt.SortOrder.DescendingOrder


class Names(grid_engine.GridEngine, QtCore.QAbstractTableModel):
    """The smallest grid model: a name and a kind per row, counting every row read."""

    KindRole = QtCore.Qt.ItemDataRole.UserRole + 6
    COLUMN_ROLES = {"name": DISPLAY, "type": "KindRole"}
    GRID_ROWS = ("_names", "_kinds")

    def __init__(self, names, kinds=None):
        super().__init__()
        self._names = list(names)
        self._kinds = list(kinds or ["x"] * len(self._names))
        self.reads = 0
        self.order_rows()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._names)

    def row_data(self, row, role):
        self.reads += 1
        if role == DISPLAY:
            return self._names[row]
        if role == self.KindRole:
            return self._kinds[row]
        return None

    def append(self, name, kind="x"):
        row = len(self._names)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self._names.append(name)
        self._kinds.append(kind)
        self.endInsertRows()

    def rename(self, row, name):
        self._names[row] = name
        self.row_changed(row, [DISPLAY])


def _grid(names, kinds=None):
    model = Names(names, kinds)
    proxy = multifilterproxy_model.MultiFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.setDynamicSortFilter(False)
    return model, proxy


def _shown(proxy):
    return [proxy.index(row, 0).data(DISPLAY) for row in range(proxy.rowCount())]


def _settle():
    QtWidgets.QApplication.processEvents()


class EveryGridModelAnswersThroughTheEngine(unittest.TestCase):
    """One `data()` for Materials, Nodes, Code, Colors, File and Online, and none of their own."""

    def test_no_grid_model_has_a_data_of_its_own(self):
        from amaze.core import (code_library, cop_library, file_library,
                                gradient_library, library, matx_library)
        for cls in (library.MaterialLibrary, cop_library.CopLibrary,
                    code_library.CodeLibrary, gradient_library.GradientLibrary,
                    file_library.FileFiles, matx_library.MatxOnlineLibrary):
            with self.subTest(model=cls.__name__):
                self.assertIs(
                    grid_engine.GridEngine.data, cls.data,
                    "%s answers the grid with its own data() - a second answer "
                    "the engine's columns and sort cannot see" % cls.__name__)

    def test_a_later_column_is_ONE_data_call(self):
        """A Name cell is one data() and one row read - the sort pays it per row, the list per paint."""
        model = Names(["b", "a", "c"])
        model.reads = 0
        asked = []
        real = model.data

        def counted(index, role=DISPLAY):
            asked.append(index.column())
            return real(index, role)

        model.data = counted    # an engine re-entering data() would land here too
        for row in range(3):
            self.assertEqual(model._names[row],
                             model.data(model.index(row, NAME), DISPLAY))
        self.assertEqual([NAME] * 3, asked,
                         "3 Name cells cost these data() calls, by column: %s" % asked)
        self.assertEqual(3, model.reads, "%d row reads for 3 Name cells" % model.reads)


class TheModelSortsItsOwnRows(unittest.TestCase):
    """A header click reaches the model through the proxy; the proxy never sorts."""

    def test_a_sort_reads_each_row_once_not_per_comparison(self):
        names = ["material %04d" % n for n in range(1000)]
        random.Random(7).shuffle(names)    # jumbled, the way SimReady's archives list
        model, proxy = _grid(names)
        model.reads = 0
        proxy.sort(NAME, DOWN)
        self.assertEqual(sorted(names, reverse=True), _shown(proxy))
        self.assertLessEqual(
            model.reads, 2 * len(names),
            "a Z-A sort of %d rows read %d cells - a read per comparison, the "
            "cost that froze SimReady for a second" % (len(names), model.reads))

    def test_the_proxy_keeps_the_models_order(self):
        model, proxy = _grid(["b", "C", "a"])
        self.assertEqual(["a", "b", "C"], _shown(proxy), "A to Z, case aside")
        proxy.sort(NAME, DOWN)
        self.assertEqual(-1, proxy.sortColumn(),
                         "the proxy sorted itself - every comparison a call into Python")
        self.assertEqual((NAME, DOWN), (model.sort_column(), model.sort_order()))
        self.assertEqual(["C", "b", "a"], _shown(proxy))

    def test_another_column_sorts_with_names_breaking_no_ties(self):
        """Equal kinds keep the order they had - the sort is stable, both ways."""
        model, proxy = _grid(["d", "c", "b", "a"], ["y", "x", "y", "x"])
        proxy.sort(TYPE, QtCore.Qt.SortOrder.AscendingOrder)
        self.assertEqual(["a", "c", "b", "d"], _shown(proxy))

    def test_a_selection_follows_its_row(self):
        model, proxy = _grid(["alpha", "beta", "gamma"])
        selection = QtCore.QItemSelectionModel(proxy)
        selection.select(proxy.index(0, 0),
                         QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        proxy.sort(NAME, DOWN)
        picked = [index.data(DISPLAY) for index in selection.selectedIndexes()]
        self.assertEqual(["alpha"], picked, "the selection stayed on the row number")


class TheOrderHoldsHoweverRowsChange(unittest.TestCase):
    """Inserts, renames and filters keep the model's order; what reads nothing it sorts by is free."""

    def test_a_burst_of_new_rows_lands_in_order_with_ONE_sort(self):
        model, proxy = _grid(["zulu"])
        sorts = []
        model.layoutChanged.connect(lambda *a: sorts.append(1))
        for name in ("bravo", "alpha", "charlie"):
            model.append(name)
        _settle()
        self.assertEqual(["alpha", "bravo", "charlie", "zulu"], _shown(proxy))
        self.assertEqual(1, len(sorts), "%d sorts for one burst" % len(sorts))

    def test_rows_a_filter_brings_back_come_back_in_order(self):
        model, proxy = _grid(["zulu", "bravo", "alpha"])
        proxy.setFilter(DISPLAY, "a")
        self.assertEqual(["alpha", "bravo"], _shown(proxy))
        proxy.removeFilter(DISPLAY)
        self.assertEqual(["alpha", "bravo", "zulu"], _shown(proxy))

    def test_a_rename_moves_its_row(self):
        model, proxy = _grid(["alpha", "bravo"])
        model.rename(0, "zulu")
        _settle()
        self.assertEqual(["bravo", "zulu"], _shown(proxy))

    def test_a_picture_landing_costs_no_sort(self):
        model, proxy = _grid(["alpha", "bravo"])
        model._names.reverse()    # out of order on purpose, so a sort would show
        model.reads = 0
        model.row_changed(0, [QtCore.Qt.ItemDataRole.DecorationRole])
        _settle()
        self.assertEqual(0, model.reads, "a thumbnail landing re-sorted the grid")

    def test_a_row_list_out_of_step_is_never_moved(self):
        model, proxy = _grid(["b", "a"])
        model._kinds.append("orphan")    # one entry too many
        proxy.sort(NAME, DOWN)
        self.assertEqual(["a", "b"], model._names,
                         "rows moved while a row list was out of step")


class ASavedAssetHoldsItsSortedRow(unittest.TestCase):
    """The insert door sorts at once, so its caller is never left holding a row about to move."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_the_row_handed_back_holds_the_record(self):
        from amaze.core import material
        model = self.panel.code_model
        self.assertTrue(model.rowCount(), "premise: the fixture has snippets to sort among")
        record = material.Material()
        record.set_data("!first by name", "", "", False, "VEX")
        row = model._append_record(record)
        self.assertIs(record, model._assets[row])
        self.assertEqual(0, row, "a name sorting first did not land first")
        model._take_back_refused_append(record)


if __name__ == "__main__":
    unittest.main()
