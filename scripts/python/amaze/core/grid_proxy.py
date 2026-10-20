"""WHAT IS SHOWN, held however the rows change; the ORDER is the grid engine's. ▸r/proxy-invariant"""

import contextlib

from PySide6 import QtCore


class GridProxyModel(QtCore.QSortFilterProxyModel):
    """Base for every Grid proxy: it FILTERS, in the order its model keeps. ▸p/grid-engine"""

    refiltered = QtCore.Signal()    # after every filter pass, even one that moved no row

    PASSIVE_ROLES = frozenset({    # roles that cannot change what is shown ▸r/proxy-invariant
        QtCore.Qt.ItemDataRole.DecorationRole,
        QtCore.Qt.ItemDataRole.ToolTipRole,
        QtCore.Qt.ItemDataRole.SizeHintRole,
        QtCore.Qt.ItemDataRole.StatusTipRole,
    })

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._pass_scheduled = False
        self._batching = False      # inside `one_pass`: a filter setter defers instead of running the pass
        self._batch_wanted = False
        self._pass_timer = QtCore.QTimer(self)    # owned, so a queued pass dies with it ▸r/model-parent
        self._pass_timer.setSingleShot(True)
        self._pass_timer.setInterval(0)
        self._pass_timer.timeout.connect(self._pass_now)

    def sort(self, column: int, order=QtCore.Qt.SortOrder.AscendingOrder) -> None:
        """A header click: the MODEL sorts its rows, and this proxy never sorts. ▸p/grid-engine"""
        model = self.sourceModel()
        if model is not None:
            model.sort(column, order)

    def setSourceModel(self, model) -> None:
        previous = self.sourceModel()
        if previous is not None:
            try:
                previous.dataChanged.disconnect(self._source_data_changed)
            except (RuntimeError, TypeError):
                pass                     # never connected, or already gone
        super().setSourceModel(model)
        if model is not None:
            model.dataChanged.connect(self._source_data_changed)    # a row coming IN is not here yet

    def _source_data_changed(self, _first, _last, roles=()) -> None:
        if self._matters(roles):
            self._schedule_pass()

    def watched_roles(self):
        """The roles this proxy's filter reads, or None: then all but PASSIVE_ROLES re-test."""
        return None

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
        """Hold the pass to the end of the block, then run it ONCE. ▸p/filter-pass-cost"""
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
        """Re-filter NOW, for a setter that reads the result back; deferred inside `one_pass`."""
        if self._batching:
            self._batch_wanted = True
            return
        self.invalidateFilter()
        self.refiltered.emit()

    def _schedule_pass(self, *_args) -> None:
        """COALESCED: one re-filter per event-loop turn however many rows changed in it."""
        if self._pass_scheduled:
            return
        self._pass_scheduled = True
        self._pass_timer.start()

    def _pass_now(self) -> None:
        self._pass_scheduled = False    # cleared first: a change during the pass earns its own
        self.invalidateFilter()
        self.refiltered.emit()
