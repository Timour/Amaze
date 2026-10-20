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

from amaze.core import grid_engine, multifilterproxy_model  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401


class _Rows(grid_engine.GridEngine, QtCore.QAbstractTableModel):
    """A grid model that appends as a save does: one row at a time, at the END."""

    NameRole = QtCore.Qt.ItemDataRole.UserRole
    COLUMN_ROLES = {"name": QtCore.Qt.ItemDataRole.DisplayRole}
    GRID_ROWS = ("_names",)

    def __init__(self, names=()):
        super().__init__()
        self._names = list(names)
        self.order_rows()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._names)

    def row_data(self, row, role):
        if role in (QtCore.Qt.ItemDataRole.DisplayRole, self.NameRole):
            return self._names[row]
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

        for name in ("charlie", "able", "baker"):    # a multi-save inserts a row at a time
            source.append(name)
        self.settle()
        self.assertEqual(
            ["able", "alpha", "baker", "beta", "charlie", "delta", "gamma"],
            self.shown(proxy), "several saves in one turn landed out of order")

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
        proxy.removeFilter(QtCore.Qt.ItemDataRole.DisplayRole)
        self.assertEqual(["alpha", "bravo", "zulu"], self.shown(proxy),
                         "removing the filter put the rows back unordered")


class TheResortIsCoalesced(_Case):
    """`setDynamicSortFilter(False)` is set for performance, and a sort per inserted row would put that cost straight back."""

    def test_swapping_one_filter_for_another_costs_ONE_pass(self):
        """A pass measures ~24ms. ▸p/filter-pass-cost"""
        source, proxy = self.build(["alpha", "bravo"])
        proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, "a")    # a filter must BE set, or the remove returns without a pass and the batching proves nothing
        passes = []
        real = proxy.invalidateFilter    # the REAL work; a deferred `refilter` returns at once and would count as a pass

        def counted():
            passes.append(1)
            return real()

        proxy.invalidateFilter = counted
        with proxy.one_pass():
            proxy.removeFilter(QtCore.Qt.ItemDataRole.DisplayRole)
            proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, "al")
        self.assertEqual(1, len(passes),
                         "a remove-then-set pair cost %d passes" % len(passes))
        self.assertEqual(["alpha"], self.shown(proxy),
                         "the batched pair did not actually filter")

    def test_a_burst_of_inserts_costs_ONE_sort(self):
        source, proxy = self.build(["zulu"])
        sorts = []
        source.layoutChanged.connect(lambda *a: sorts.append(1))    # the model's one sort signal
        for n in range(25):          # a multi-save arrives a row at a time
            source.append("row%02d" % n)
        self.settle()
        self.assertEqual(
            1, len(sorts),
            "25 rows arriving in one turn cost %d sorts - one per row is "
            "quadratic" % len(sorts))

    def test_a_model_is_in_name_order_before_anything_asks(self):
        """Every grid opens on Name, A to Z, so a model starts there; no proxy has to ask."""
        source = _Rows(["b", "a"])
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(source)
        self.assertEqual(["a", "b"], self.shown(proxy))
        self.assertEqual(-1, proxy.sortColumn(), "the proxy sorted itself")


class _Flagged(grid_engine.GridEngine, QtCore.QAbstractTableModel):
    """A grid model with a favourite FLAG per row, toggled after the fact."""

    FlagRole = QtCore.Qt.ItemDataRole.UserRole + 2     # 258, FavoriteRole
    ColourRole = QtCore.Qt.ItemDataRole.UserRole + 8   # 264, a colour
    COLUMN_ROLES = {"name": QtCore.Qt.ItemDataRole.DisplayRole}
    GRID_ROWS = ("_names",)

    def __init__(self, names, flagged=()):
        super().__init__()
        self._names = list(names)
        self._flags = {name: name in flagged for name in names}
        self.order_rows()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._names)

    def row_data(self, row, role):
        name = self._names[row]
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

    def test_the_row_that_arrives_lands_IN_ORDER(self):
        """Same rule as an insert: a row coming back into view lands in order, not at the end."""
        source, proxy = self.build_flagged(
            ["gamma", "alpha", "beta"], ["gamma"])
        source.toggle(source._names.index("alpha"))    # by name: the model keeps its own order
        source.toggle(source._names.index("beta"))
        self.settle()
        self.assertEqual(["alpha", "beta", "gamma"], self.shown(proxy))


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

    def _counting(self, source, proxy):
        counts = {"sort": 0, "filter": 0}    # the proxy's passes, and the model's sorts
        real_filter = proxy.invalidateFilter
        proxy.invalidateFilter = lambda: (
            counts.__setitem__("filter", counts["filter"] + 1),
            real_filter())[1]
        source.layoutChanged.connect(
            lambda *a: counts.__setitem__("sort", counts["sort"] + 1))
        return counts

    def test_rows_coming_IN_or_going_OUT_cost_one_pass(self):
        names = ["alpha", "bravo", "charlie"]
        for flagged, shown in (([], names), (names, [])):
            with self.subTest(arriving=not flagged):
                source, proxy = self.build_flagged(names, flagged)
                counts = self._counting(source, proxy)

                for row in range(3):
                    source.toggle(row)          # three rows move at once
                self.settle()
                self.settle()                   # a second turn, for any echo

                self.assertEqual(shown, self.shown(proxy),
                                 "the rows did not move, so this measures "
                                 "nothing")
                self.assertEqual(
                    1, counts["filter"],
                    "%d re-filters for one burst" % counts["filter"])
                self.assertEqual(
                    0, counts["sort"],
                    "%d sorts for a star the order does not read" % counts["sort"])

    def test_an_insert_and_a_data_change_MERGE_into_one_pass(self):
        """An insert costs the model one sort and a star in the same turn one re-filter."""
        source, proxy = self.build_flagged(["bravo"], ["bravo"])
        counts = self._counting(source, proxy)

        source.append_flagged("alpha", True)   # insert: sort only
        source.toggle(0)                       # bravo un-starred: filter
        self.settle()

        self.assertEqual(["alpha"], self.shown(proxy),
                         "the two changes did not both land")
        self.assertEqual(1, counts["sort"], "%d sorts" % counts["sort"])
        self.assertEqual(1, counts["filter"],
                         "%d re-filters" % counts["filter"])


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
        for emitted, emit in (
                ("colour pick", lambda s: s.colour_changed()),    # one role over every row
                ("thumbnail", lambda s: [s.thumbnail_arrived(r)    # 548 per library load
                                         for r in range(2)])):
            with self.subTest(emitted=emitted):
                source, proxy = self.build_flagged(["alpha", "bravo"],
                                                   ["alpha"])
                calls = []
                proxy.invalidateFilter = lambda: calls.append(1)

                emit(source)
                self.settle()

                self.assertEqual(
                    [], calls,
                    "a %s re-filtered the whole grid %d time(s)"
                    % (emitted, len(calls)))

    def test_the_SORT_role_still_counts(self):
        """A rename changes where a row sorts, so it must re-pass even though no filter reads it."""
        source, proxy = self.build_flagged(
            ["zulu", "bravo"], ["zulu", "bravo"])
        self.assertEqual(["bravo", "zulu"], self.shown(proxy))
        source.rename(source._names.index("zulu"), "alpha")
        self.settle()
        self.assertEqual(
            ["alpha", "bravo"], self.shown(proxy),
            "a renamed row did not move - the sort role was treated as "
            "passive")


class TheRuleHasOneHome(unittest.TestCase):

    def test_no_caller_sorts_after_saving(self):
        """No caller may `sort()` a proxy beside a mutation - the proxy guarantees its own order."""
        import ast

        BUILDERS = ("setup", "_grid_proxy", "__init__", "_build_models", "_build_ui")   # construction is not a re-sort: `sort(0)` in `_grid_proxy` sets the column, or nothing sorts
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
                if hasattr(proxy, "setFilter"):
                    proxy.setFilter(model.FavoriteRole, True)   # arm it as the section does: it watches ACTIVE filters
                for roles, matters, why in (
                        ([model.CategoryColorRole], False,
                         "a colour pick re-filters the whole section"),
                        ([model.NotesRole], False,
                         "a comment badge re-filters the whole section"),
                        ([model.FavoriteRole], True,
                         "un-favouriting with Favourites-only on would "
                         "leave the row in the grid, star off"),
                        ([QtCore.Qt.ItemDataRole.DisplayRole], True,
                         "a role the filter reads went quiet"),
                        ([], True, "empty means everything changed")):
                    self.assertEqual(matters, proxy._matters(roles), why)


class _Counted(QtCore.QAbstractListModel):
    """Five roles on the MaterialLibrary numbers, every row passing every filter, fetches counted."""

    ROLES = {256 + 1: ["Wood"], 256 + 2: True, 256 + 3: "Karma",
             256 + 4: ["oak"]}

    def __init__(self, names):
        super().__init__()
        self._names = list(names)
        self.fetched = {}

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._names)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        self.fetched[int(role)] = self.fetched.get(int(role), 0) + 1
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self._names[index.row()]
        return self.ROLES.get(int(role))


class AFilterPassFetchesEachRoleOnce(unittest.TestCase):
    """A pass reads each filtered role at most once per row and stops at the first test a row fails."""

    FILTERS = {257: "wood", 258: True, 259: "karma", 260: "oak"}

    def _pass(self, name_filter):
        source = _Counted(["alpha", "beta", "gamma"])
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(source)
        with proxy.one_pass():
            proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, name_filter)
            for role, value in self.FILTERS.items():
                proxy.setFilter(role, value)
        source.fetched.clear()
        proxy.invalidateFilter()
        return source.fetched, proxy.rowCount()

    def test_a_pass_reads_each_role_once_and_stops_at_a_failure(self):
        for name_filter, rows, reads in (
                ("a", 3, {0: 3, 257: 3, 258: 3, 259: 3, 260: 3}),
                ("zz", 0, {0: 3})):    # failing the cheapest test reads nothing behind it
            with self.subTest(name_filter=name_filter):
                fetched, shown = self._pass(name_filter)
                self.assertEqual(rows, shown,
                                 "premise: the name filter did not narrow "
                                 "as set up")
                self.assertEqual(reads, fetched,
                                 "a pass read a role twice per row, or "
                                 "past the first test the row failed")


class AnUnchangedFilterCostsNoPass(unittest.TestCase):
    """Setting a filter to the value it already holds re-tests nothing, on all three grid proxies."""

    def _passes(self, proxy, first, again):
        proxy.setSourceModel(_Rows([]))
        first(proxy)
        passes = []
        proxy.invalidateFilter = lambda: passes.append(1)
        again(proxy)
        return len(passes)

    def test_no_grid_proxy_refilters_for_an_unchanged_value(self):
        from amaze.core import gradient_library, texture_library
        role = QtCore.Qt.ItemDataRole.DisplayRole
        cases = [("asset %r" % (value,),
                  multifilterproxy_model.MultiFilterProxyModel,
                  lambda p, value=value: p.setFilter(role, value))
                 for value in ("al", True)]
        cases += [("file %s" % name, texture_library.TextureFilterProxyModel,
                   lambda p, name=name, value=value: getattr(p, name)(value))
                  for name, value in (("set_name_filter", "al"),
                                      ("set_favorites_only", True),
                                      ("set_kind_filter", "image"))]
        cases.append(("colour set_size_filter",
                      gradient_library.GradientFilterProxyModel,
                      lambda p: p.set_size_filter((2, 2))))
        for label, proxy_class, setter in cases:
            with self.subTest(label):
                self.assertEqual(0, self._passes(proxy_class(), setter, setter))


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
