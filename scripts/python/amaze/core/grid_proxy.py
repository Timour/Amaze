"""WHAT IS SHOWN AND IN WHAT ORDER, held however the rows change - filter, category, section, reload, insert, or a row whose own data changed. The three grid proxies differ in what they FILTER ON and must not differ in this. ▸r/proxy-invariant"""

import contextlib

from PySide6 import QtCore

from amaze.core import grid_columns


class GridProxyModel(QtCore.QSortFilterProxyModel):
    """Base for every proxy the Grid shows: subclasses implement `filterAcceptsRow` and call `refilter()` when their own filter settings change."""

    PASSIVE_ROLES = frozenset({    # roles whose arrival cannot change what is shown or where; DecorationRole is the load-bearing one, 548 pictures landing per load ▸r/proxy-invariant
        QtCore.Qt.ItemDataRole.DecorationRole,
        QtCore.Qt.ItemDataRole.ToolTipRole,
        QtCore.Qt.ItemDataRole.SizeHintRole,
        QtCore.Qt.ItemDataRole.StatusTipRole,
    })

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._pass_scheduled = False
        self._pass_refilters = False
        self._in_pass = False
        self._batching = False      # inside `one_pass`: a filter setter defers instead of running the pass
        self._batch_wanted = False
        self._pass_timer = QtCore.QTimer(self)    # OWNED, so Qt takes it when this proxy goes: a static singleShot keeps the bound method alive and fires it after the C++ object is gone ▸r/model-parent
        self._pass_timer.setSingleShot(True)
        self._pass_timer.setInterval(0)
        self._pass_timer.timeout.connect(self._pass_now)
        self.rowsInserted.connect(self._schedule_pass)    # an insert that PASSES the filter arrives as the proxy's own rowsInserted; one that does not has nothing to order

    def setSourceModel(self, model) -> None:
        previous = self.sourceModel()
        if previous is not None:
            try:
                previous.dataChanged.disconnect(self._source_data_changed)
            except (RuntimeError, TypeError):
                pass                     # never connected, or already gone
        super().setSourceModel(model)
        if model is not None:
            model.dataChanged.connect(self._source_data_changed)    # the SOURCE's signal, not the proxy's: a row that must come INTO the grid is not in the proxy to emit anything

    def _source_data_changed(self, _first, _last, roles=()) -> None:
        if self._matters(roles):
            self._schedule_pass(refilters=True)

    def watched_roles(self):
        """The roles this proxy's filter and sort actually read, or None for "cannot say" - then everything but PASSIVE_ROLES re-tests. ▸r/proxy-invariant"""
        return None

    def sort_column_role(self):
        """The role the SORT COLUMN actually reads: a later column answers DisplayRole out of a UserRole on column 0, so a whitelist watching `sortRole()` alone misses the role its own order depends on and the rows stop re-sorting."""
        column = self.sortColumn()
        mapper = getattr(self.sourceModel(), "_column_role", None)
        if column <= 0 or mapper is None or column >= len(grid_columns.KEYS):
            return self.sortRole()
        return mapper(grid_columns.KEYS[column]) or self.sortRole()

    def _matters(self, roles) -> bool:
        """An empty role list means everything changed - the one case that must always re-test."""
        if not roles:
            return True
        watched = self.watched_roles()
        if watched is not None:
            return any(role in watched for role in roles)
        return any(role not in self.PASSIVE_ROLES for role in roles)

    @contextlib.contextmanager
    def one_pass(self):
        """Hold the pass until the block ends, then run it ONCE - for a caller changing two filters for one gesture. A pass measures ~24ms. ▸p/filter-pass-cost"""
        if self._batching:
            yield                        # already inside one; the outermost runs it
            return
        self._batching = True
        self._batch_wanted = False
        try:
            yield
        finally:
            self._batching = False
            if self._batch_wanted:
                self.refilter()

    def refilter(self) -> None:
        """Re-filter AND re-sort, NOW - what a filter setter calls when it expects to read the result back; inside `one_pass` it is deferred to the end of the block."""
        if self._batching:
            self._batch_wanted = True
            return
        self._in_pass = True    # the pass's own echo: rows a re-filter brings back IN emit rowsInserted, which would post a SECOND full sort for the next turn ▸r/proxy-invariant
        try:
            self.invalidateFilter()
            self._resort()
        finally:
            self._in_pass = False

    def _resort(self) -> None:
        """Re-apply the established order; `sortColumn() == -1` means none is, and sorting then would impose one nobody asked for."""
        column = self.sortColumn()
        if column >= 0:
            self.sort(column, self.sortOrder())

    def _schedule_pass(self, *_args, refilters: bool = False) -> None:
        """COALESCED: one pass per event-loop turn however many rows moved in it - a load inserts in one batch, a multi-save a row at a time. ▸r/proxy-invariant"""
        if self._in_pass:
            return    # the pass's own echo, ignored outright: answering it posts a second pass, doubling what coalescing exists to avoid
        if refilters:
            self._pass_refilters = True
        if self._pass_scheduled:    # already queued: merge into it - the flag above is set FIRST, so an insert and a data change in one turn get one pass that does both
            return
        self._pass_scheduled = True
        self._pass_timer.start()    # the OWNED timer, never a static singleShot: Qt takes it with this proxy, so a pass queued by a panel that then closes cannot run on a destroyed object ▸r/model-parent

    def _pass_now(self) -> None:
        self._pass_scheduled = False    # cleared at the START: from here the pass is RUNNING, which is `_in_pass`'s business, and a change arriving during it deserves its own pass
        refilters, self._pass_refilters = self._pass_refilters, False
        self._in_pass = True
        try:
            if refilters:
                self.invalidateFilter()
            self._resort()
        finally:
            self._in_pass = False
