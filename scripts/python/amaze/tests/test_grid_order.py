"""The Grid area's invariant: WHAT IS SHOWN AND IN WHAT ORDER, however the rows arrive - a filter change, a category or section switch, a reload, or an INSERT."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import multifilterproxy_model  # noqa: E402


class _Rows(QtCore.QAbstractListModel):
    """A source that appends the way the library does when an asset is saved: a per-row insert at the END of source order."""

    NameRole = QtCore.Qt.ItemDataRole.UserRole

    def __init__(self, names=()):
        super().__init__()
        self._names = list(names)

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._names)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (QtCore.Qt.ItemDataRole.DisplayRole, self.NameRole):
            return self._names[index.row()]
        return None

    def append(self, name):
        row = len(self._names)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self._names.append(name)
        self.endInsertRows()


class _Case(unittest.TestCase):

    def build(self, names):
        source = _Rows(names)
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(source)
        proxy.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)
        proxy.setDynamicSortFilter(False)      # what the panel does; it turns off the re-SORT as well as the re-filter, so a filter change leaves the survivors in SOURCE order and a changed row is not re-tested at all
        proxy.sort(0)
        return source, proxy

    def shown(self, proxy):
        return [proxy.index(r, 0).data(QtCore.Qt.ItemDataRole.DisplayRole)
                for r in range(proxy.rowCount())]

    def settle(self):
        """The re-sort is coalesced onto the event loop, so a test has to let the loop turn before reading the proxy."""
        QtWidgets.QApplication.processEvents()


class ANewRowLandsInOrder(_Case):

    def test_a_saved_asset_does_not_land_at_the_bottom(self):
        """A row the library appends at the END of source order comes back in sorted position, not at the bottom."""
        source, proxy = self.build(["alpha", "gamma", "delta"])
        self.assertEqual(["alpha", "delta", "gamma"], self.shown(proxy),
                         "the fixture is not sorted, so nothing below "
                         "is about ordering")

        source.append("beta")
        self.settle()

        self.assertEqual(
            ["alpha", "beta", "delta", "gamma"], self.shown(proxy),
            "a newly inserted row is not in order - it is wherever the "
            "source put it, which is what reads as 'the grid did not "
            "refresh' with the tile sitting at the bottom of 548")

    def test_it_holds_for_a_row_that_sorts_first(self):
        source, proxy = self.build(["beta", "gamma"])
        source.append("alpha")
        self.settle()
        self.assertEqual(["alpha", "beta", "gamma"], self.shown(proxy))

    def test_it_holds_for_several_saves_in_one_turn(self):
        """A multi-save inserts a row at a time."""
        source, proxy = self.build(["delta"])
        for name in ("charlie", "alpha", "bravo"):
            source.append(name)
        self.settle()
        self.assertEqual(["alpha", "bravo", "charlie", "delta"],
                         self.shown(proxy))

    def test_a_filtered_grid_still_lands_it_in_order(self):
        """The two routes must not fight: a row arriving while a filter is on is still ordered AND still filtered, and the filter has to genuinely narrow or this proves nothing."""
        source, proxy = self.build(["alpha", "zulu"])
        proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, "al")
        self.settle()
        self.assertEqual(["alpha"], self.shown(proxy),
                         "the filter did not narrow, so this test is "
                         "not about filtering")
        source.append("alfa")
        source.append("yankee")
        self.settle()
        self.assertEqual(
            ["alfa", "alpha"], self.shown(proxy),
            "a row arriving while a filter is on is either out of "
            "order or not filtered")


class AFilterChangeReordersWhatComesBack(_Case):
    """A filter change re-tests the rows, and the ones it LEAVES have to come back in order rather than in source order."""

    def test_the_rows_a_filter_LEAVES_are_in_order(self):
        source, proxy = self.build(["zulu", "bravo", "alpha"])
        proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, "a")   # nothing is appended here: the insert route re-sorts on its own, so a test that appends after filtering passes either way
        self.assertEqual(
            ["alpha", "bravo"], self.shown(proxy),
            "the surviving rows are in source order, which is what "
            "'pick a category and go back to All' looked like")

    def test_REMOVING_a_filter_puts_them_all_back_in_order(self):
        source, proxy = self.build(["zulu", "bravo", "alpha"])
        proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, "a")
        proxy.removeFilter(QtCore.Qt.ItemDataRole.DisplayRole)
        self.assertEqual(["alpha", "bravo", "zulu"], self.shown(proxy))


class TheResortIsCoalesced(_Case):
    """`setDynamicSortFilter(False)` is set for performance, and a sort per inserted row would put that cost straight back."""

    def test_a_burst_of_inserts_costs_ONE_sort(self):
        source, proxy = self.build(["zulu"])
        sorts = []
        real = proxy.sort

        def counted(column, order=QtCore.Qt.SortOrder.AscendingOrder):
            sorts.append(column)
            return real(column, order)

        proxy.sort = counted
        for n in range(25):          # a multi-save arrives a row at a time; a 548-asset load is one batch insert
            source.append("row%02d" % n)
        self.settle()
        self.assertEqual(
            1, len(sorts),
            "25 rows arriving in one turn cost %d sorts - that is the "
            "quadratic load setDynamicSortFilter(False) exists to "
            "avoid" % len(sorts))

    def test_it_does_not_sort_before_a_column_is_established(self):
        """`sortColumn() == -1` means nothing has established an order yet, and sorting then would impose one nobody asked for."""
        source = _Rows(["b", "a"])
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(source)
        proxy.setDynamicSortFilter(False)
        sorts = []
        proxy.sort = lambda *a, **k: sorts.append(a)
        source.append("c")
        self.settle()
        self.assertEqual([], sorts,
                         "it sorted a proxy that has no sort column")


class _Flagged(QtCore.QAbstractListModel):
    """A source with a filterable FLAG per row - a favourite - that can be toggled after the fact, emitting `dataChanged` for the role it changed and nothing else."""

    FlagRole = QtCore.Qt.ItemDataRole.UserRole + 2     # 258, FavoriteRole
    ColourRole = QtCore.Qt.ItemDataRole.UserRole + 8   # 264, a colour

    def __init__(self, names, flagged=()):
        super().__init__()
        self._names = list(names)
        self._flags = {name: name in flagged for name in names}

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._names)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        name = self._names[index.row()]
        if role in (QtCore.Qt.ItemDataRole.DisplayRole, 0):
            return name
        if role == self.FlagRole:
            return self._flags[name]
        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            return None
        return None

    def toggle(self, row):
        name = self._names[row]
        self._flags[name] = not self._flags[name]
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [self.FlagRole])   # measured: `library.toggle_fav`, `FileFiles.toggle_favorite` and `Gradients.toggle_favorite` all emit exactly this

    def colour_changed(self):
        """What a sidebar colour pick emits: one role over every row, so the tiles repaint, and nothing filters or sorts on it."""
        self.dataChanged.emit(
            self.index(0, 0), self.index(self.rowCount() - 1, 0),
            [self.ColourRole])

    def rename(self, row, name):
        """A rename changes the SORT key, which is not passive."""
        old = self._names[row]
        self._names[row] = name
        self._flags[name] = self._flags.pop(old)
        index = self.index(row, 0)
        self.dataChanged.emit(index, index,
                              [QtCore.Qt.ItemDataRole.DisplayRole])

    def append_flagged(self, name, flagged):
        row = len(self._names)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        self._names.append(name)
        self._flags[name] = flagged
        self.endInsertRows()

    def thumbnail_arrived(self, row):
        """The high-frequency emission this must NOT pay for: a thumbnail landing on a row changes nothing a filter reads."""
        index = self.index(row, 0)
        self.dataChanged.emit(index, index,
                              [QtCore.Qt.ItemDataRole.DecorationRole])


class AChangedRowIsRETESTED(_Case):
    """A row whose DATA changed is re-tested against the filter: with Favourites-only on, un-favouriting a tile has to take it out of the grid."""

    def build_flagged(self, names, flagged):
        source = _Flagged(names, flagged)
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(source)
        proxy.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)
        proxy.setDynamicSortFilter(False)
        proxy.sort(0)
        proxy.setFilter(_Flagged.FlagRole, True)
        return source, proxy

    def test_unfavouriting_removes_the_row_from_a_favourites_grid(self):
        source, proxy = self.build_flagged(["alpha", "beta"], ["alpha"])
        self.assertEqual(["alpha"], self.shown(proxy),
                         "the favourites filter is not filtering, so "
                         "nothing below is about it")

        source.toggle(0)
        self.settle()

        self.assertEqual(
            [], self.shown(proxy),
            "the row is still in the grid with its star off - the "
            "filter says favourites and the grid shows one that is not")

    def test_favouriting_brings_a_row_IN(self):
        source, proxy = self.build_flagged(["alpha", "beta"], ["alpha"])
        source.toggle(1)
        self.settle()
        self.assertEqual(["alpha", "beta"], self.shown(proxy),
                         "a newly starred row did not appear in the "
                         "favourites grid")

    def test_the_row_that_arrives_lands_IN_ORDER(self):
        """Same rule as an insert: a row coming back into view lands in order, not at the end."""
        source, proxy = self.build_flagged(
            ["gamma", "alpha", "beta"], ["gamma"])
        source.toggle(1)
        source.toggle(2)
        self.settle()
        self.assertEqual(["alpha", "beta", "gamma"], self.shown(proxy))

    def test_a_THUMBNAIL_arriving_costs_no_refilter(self):
        """Every tile's picture lands as a `dataChanged`, 548 of them on a library load, and none of them may cost a re-filter."""
        source, proxy = self.build_flagged(["alpha", "beta"], ["alpha"])
        calls = []
        proxy.invalidateFilter = lambda: calls.append(1)

        for row in range(2):
            source.thumbnail_arrived(row)
        self.settle()

        self.assertEqual([], calls,
                         "a thumbnail arriving re-filtered the whole "
                         "grid, %d times" % len(calls))

    def test_a_burst_of_toggles_costs_ONE_refilter(self):
        source, proxy = self.build_flagged(
            ["alpha", "beta", "gamma"], [])
        calls = []
        real = proxy.invalidateFilter
        proxy.invalidateFilter = lambda: (calls.append(1), real())[1]

        for row in range(3):
            source.toggle(row)
        self.settle()

        self.assertEqual(1, len(calls),
                         "%d re-filters for one burst of changes" % len(calls))


class TheCoalescerDoesNotWAKEItself(_Case):
    """One pass per event-loop turn is the contract: the rows a pass brings back IN emit the proxy's own `rowsInserted`, which must not schedule a second pass."""

    def build_flagged(self, names, flagged):
        source = _Flagged(names, flagged)
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(source)
        proxy.setSortCaseSensitivity(QtCore.Qt.CaseInsensitive)
        proxy.setDynamicSortFilter(False)
        proxy.sort(0)
        proxy.setFilter(_Flagged.FlagRole, True)
        return source, proxy

    def _counting(self, proxy):
        counts = {"sort": 0, "filter": 0, "layout": 0}   # counting `invalidateFilter` alone cannot see a second pass; `sort` and `layoutChanged` are what bite
        real_sort, real_filter = proxy.sort, proxy.invalidateFilter
        proxy.sort = lambda c, o=QtCore.Qt.SortOrder.AscendingOrder: (
            counts.__setitem__("sort", counts["sort"] + 1), real_sort(c, o))[1]
        proxy.invalidateFilter = lambda: (
            counts.__setitem__("filter", counts["filter"] + 1),
            real_filter())[1]
        proxy.layoutChanged.connect(
            lambda *a: counts.__setitem__("layout", counts["layout"] + 1))
        return counts

    def test_rows_coming_IN_do_not_schedule_a_second_pass(self):
        source, proxy = self.build_flagged(
            ["alpha", "bravo", "charlie"], [])
        counts = self._counting(proxy)

        for row in range(3):
            source.toggle(row)          # three rows arrive at once
        self.settle()
        self.settle()                   # a second turn, for any echo

        self.assertEqual(["alpha", "bravo", "charlie"], self.shown(proxy),
                         "the rows did not arrive, so this measures "
                         "nothing")
        self.assertEqual(
            1, counts["filter"],
            "%d re-filters for one burst" % counts["filter"])
        self.assertEqual(
            1, counts["sort"],
            "%d sorts for one burst - the pass woke itself up through "
            "its own rowsInserted" % counts["sort"])

    def test_an_insert_and_a_data_change_MERGE_into_one_pass(self):
        """The queued-pass branch: an insert schedules a pass that only re-sorts, and a toggle in the same turn has to make that SAME pass re-filter too."""
        source, proxy = self.build_flagged(["bravo"], ["bravo"])
        counts = self._counting(proxy)

        source.append_flagged("alpha", True)   # insert: sort only
        source.toggle(0)                       # bravo un-starred: filter
        self.settle()

        self.assertEqual(["alpha"], self.shown(proxy),
                         "the two changes did not both land")
        self.assertEqual(1, counts["sort"], "%d sorts" % counts["sort"])
        self.assertEqual(1, counts["filter"],
                         "%d re-filters" % counts["filter"])

    def test_rows_going_OUT_cost_one_pass_too(self):
        source, proxy = self.build_flagged(
            ["alpha", "bravo", "charlie"], ["alpha", "bravo", "charlie"])
        counts = self._counting(proxy)
        for row in range(3):
            source.toggle(row)
        self.settle()
        self.settle()
        self.assertEqual([], self.shown(proxy))
        self.assertEqual(1, counts["sort"],
                         "%d sorts" % counts["sort"])


class ACOLOURChangeIsNotAReFilter(_Case):
    """A sidebar colour pick emits its role over EVERY row - that is how the tiles repaint - and no grid proxy filters or sorts on a colour."""

    def build_flagged(self, names, flagged):
        source = _Flagged(names, flagged)
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(source)
        proxy.setDynamicSortFilter(False)
        proxy.sort(0)
        proxy.setFilter(_Flagged.FlagRole, True)
        return source, proxy

    def test_a_role_nothing_FILTERS_on_costs_no_pass(self):
        source, proxy = self.build_flagged(["alpha", "bravo"], ["alpha"])
        calls = []
        proxy.invalidateFilter = lambda: calls.append(1)

        source.colour_changed()          # CategoryColorRole over all rows
        self.settle()

        self.assertEqual(
            [], calls,
            "a colour pick re-filtered the whole grid %d time(s)"
            % len(calls))

    def test_a_role_it_DOES_filter_on_still_costs_one(self):
        """The other half: precision, not a blanket refusal."""
        source, proxy = self.build_flagged(["alpha", "bravo"], ["alpha"])
        calls = []
        real = proxy.invalidateFilter
        proxy.invalidateFilter = lambda: (calls.append(1), real())[1]

        source.toggle(1)
        self.settle()

        self.assertEqual(1, len(calls),
                         "the favourite change was ignored too")

    def test_the_SORT_role_still_counts(self):
        """A rename changes where a row sorts, so it must re-pass even though no filter reads it."""
        source, proxy = self.build_flagged(
            ["zulu", "bravo"], ["zulu", "bravo"])
        self.assertEqual(["bravo", "zulu"], self.shown(proxy))
        source.rename(0, "alpha")
        self.settle()
        self.assertEqual(
            ["alpha", "bravo"], self.shown(proxy),
            "a renamed row did not move - the sort role was treated as "
            "passive")


class TheRuleHasOneHome(unittest.TestCase):

    def test_no_caller_sorts_after_saving(self):
        """No caller may `sort()` a proxy beside a mutation - the proxy guarantees its own order."""
        import ast

        BUILDERS = ("setup", "__init__", "_build_models", "_build_ui")   # construction is not a re-sort: the `sort(0)` in `setup()` is what ESTABLISHES the sort column, and without it `sortColumn()` is -1 and nothing sorts at all
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for relative in ("core/library.py", "core/cop_library.py",
                         "core/code_library.py", "panel/panel.py"):
            source = open(os.path.join(root, relative),
                          encoding="utf-8").read()
            tree = ast.parse(source)
            for func in ast.walk(tree):
                if not isinstance(func, ast.FunctionDef):
                    continue
                if func.name in BUILDERS:
                    continue
                for node in ast.walk(func):
                    if not (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "sort"):
                        continue
                    owner = node.func.value
                    name = (getattr(owner, "attr", "")
                            or getattr(owner, "id", ""))
                    if "sorted_model" in name or "proxy" in name:
                        offenders.append(
                            "%s:%d in %s()" % (relative, node.lineno,
                                               func.name))
        self.assertEqual(
            [], offenders,
            "a caller is re-sorting a proxy by hand outside "
            "construction, at %s - the proxy guarantees its own order "
            "now, and a second copy of that rule is how the first one "
            "came to be one route short" % offenders)


class _TenColumns(QtCore.QAbstractTableModel):
    """The shape the grid models share: roles as instance attributes, read off the source by whoever needs the number."""

    FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 61
    KindRole = QtCore.Qt.ItemDataRole.UserRole + 70
    NotesRole = QtCore.Qt.ItemDataRole.UserRole + 10
    CategoryColorRole = QtCore.Qt.ItemDataRole.UserRole + 30

    def __init__(self, names):
        super().__init__()
        self._names = list(names)

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._names)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 1

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self._names[index.row()]
        return None


class PaintOnlyRolesCostNoPass(unittest.TestCase):
    """A sidebar colour pick and a comment badge emit their role over EVERY row - that is how the tiles repaint - and no grid proxy filters or sorts on either."""

    def _proxies(self):
        from amaze.core import gradient_library, texture_library

        for cls in (texture_library.TextureFilterProxyModel,
                    gradient_library.GradientFilterProxyModel):
            proxy = cls()
            proxy.setSourceModel(_TenColumns(["a", "b"]))
            yield proxy

    def test_paint_only_roles_do_not_matter(self):
        for proxy in self._proxies():
            with self.subTest(proxy=type(proxy).__name__):
                model = proxy.sourceModel()
                self.assertFalse(
                    proxy._matters([model.CategoryColorRole]),
                    "a colour pick re-filters the whole section")
                self.assertFalse(
                    proxy._matters([model.NotesRole]),
                    "a comment badge re-filters the whole section")

    def test_the_roles_the_filter_READS_still_matter(self):
        """A role the filter READS still has to matter - a role it reads going quiet is a filter that lies."""
        for proxy in self._proxies():
            with self.subTest(proxy=type(proxy).__name__):
                model = proxy.sourceModel()
                if hasattr(proxy, "setFilter"):
                    proxy.setFilter(model.FavoriteRole, True)   # the family proxy watches exactly its ACTIVE filters, so arm this one the way the section does
                self.assertTrue(
                    proxy._matters([model.FavoriteRole]),
                    "un-favouriting with Favourites-only on would "
                    "leave the row in the grid, star off")
                self.assertTrue(
                    proxy._matters(
                        [QtCore.Qt.ItemDataRole.DisplayRole]))
                self.assertTrue(proxy._matters([]),
                                "empty means everything changed")


class AFilterChangeIsOnePass(unittest.TestCase):
    """`refilter()` sorts synchronously, and the rows it brings back IN emit the proxy's own `rowsInserted`, which lands in `_schedule_pass` and must not post a second pass."""

    def test_refilter_does_not_schedule_its_own_echo(self):
        from amaze.core import texture_library

        proxy = texture_library.TextureFilterProxyModel()
        proxy.setSourceModel(_TenColumns(["alpha", "beta", "gamma"]))
        proxy.sort(0)
        proxy.set_name_filter("zzz")          # empties the grid
        QtWidgets.QApplication.processEvents()
        self.assertEqual(0, proxy.rowCount(), "premise: filtered empty")
        proxy._pass_scheduled = False
        proxy.set_name_filter("")             # every row comes back IN
        self.assertFalse(
            proxy._pass_scheduled,
            "the setter's own synchronous pass scheduled a second one "
            "off its rowsInserted echo - two sorts and two "
            "layoutChanged per keystroke")


if __name__ == "__main__":
    unittest.main()
