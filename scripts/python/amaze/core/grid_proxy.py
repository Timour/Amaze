"""The Grid area's invariant, in one place.

WHAT IS SHOWN AND IN WHAT ORDER is this proxy's responsibility, and it
has to hold however the rows change - a filter change, a category
switch, a section switch, a reload, an INSERT, or a row whose own data
changed under it.

`setDynamicSortFilter(False)` is set on the asset and online proxies
for performance (panel.py; the File and Color proxies are left on Qt's
default and inherit these rules anyway), and that one switch turns off
THREE things at once: the re-sort after a filter change, the re-sort
after an insert, and the re-test of a row whose data changed. Each of those came back as a
caller remembering something:

* the renderer menu called `sort(0)` itself after `setFilter`, and the
  category, search and favourites paths did not - so coming back to All
  showed the grid in source order;
* the save path let a new asset land at `len(self._assets)`, the BOTTOM
  of 548, which reads as "the grid did not refresh";
* three of the five right-click Favorite handlers wrapped the toggle in
  `layoutAboutToBeChanged`/`layoutChanged` on the SOURCE model to force
  a re-map, and the other two did not - so on File and Color,
  un-favouriting a tile with Favourites-only on left it in the grid,
  star off, filter lying.

Three grid proxies exist because the models differ (MultiFilter for the
asset sections, Texture for File, Gradient for Color). They differ in
what they FILTER ON. They must not differ in this.
"""

from PySide6 import QtCore


class GridProxyModel(QtCore.QSortFilterProxyModel):
    """Base for every proxy the Grid shows. Subclasses implement
    `filterAcceptsRow` and call `refilter()` when their own filter
    settings change; both invariants are handled here."""

    #: Roles whose arrival cannot change what is shown or where.
    #: DecorationRole is the load-bearing one: every tile's picture
    #: lands as a dataChanged, 548 of them on a library load, and
    #: re-filtering on each would put back exactly the cost
    #: `setDynamicSortFilter(False)` was turned off to avoid.
    PASSIVE_ROLES = frozenset({
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
        # An insert that PASSES the filter reaches the proxy as its own
        # rowsInserted; one that does not reaches nothing, and there is
        # nothing to order.
        self.rowsInserted.connect(self._schedule_pass)

    # -- the source's own changes -----------------------------------------

    def setSourceModel(self, model) -> None:
        previous = self.sourceModel()
        if previous is not None:
            try:
                previous.dataChanged.disconnect(self._source_data_changed)
            except (RuntimeError, TypeError):
                pass                     # never connected, or already gone
        super().setSourceModel(model)
        if model is not None:
            # The SOURCE's signal, not the proxy's: a row that must come
            # INTO the grid is not in the proxy to emit anything.
            model.dataChanged.connect(self._source_data_changed)

    def _source_data_changed(self, _first, _last, roles=()) -> None:
        if self._matters(roles):
            self._schedule_pass(refilters=True)

    def watched_roles(self):
        """The roles this proxy's filter and sort actually read, or None
        for "cannot say" - in which case everything but PASSIVE_ROLES is
        re-tested.

        Worth answering: a sidebar colour pick emits its colour role
        over EVERY row (that is how the tiles repaint) and no grid proxy
        filters or sorts on a colour, so the blacklist alone bought a
        full re-filter and re-sort of 548 rows for a gesture somebody
        repeats while choosing a shade.
        """
        return None

    def _matters(self, roles) -> bool:
        """An empty role list means "everything changed", which is the
        one case that must always be re-tested."""
        if not roles:
            return True
        watched = self.watched_roles()
        if watched is not None:
            return any(role in watched for role in roles)
        return any(role not in self.PASSIVE_ROLES for role in roles)

    # -- the one pass ------------------------------------------------------

    def refilter(self) -> None:
        """Re-filter AND re-sort, NOW. What a filter setter calls: the
        caller changed what is shown and expects to read it back."""
        # THE PASS'S OWN ECHO, the same guard _pass_now carries: rows a
        # re-filter brings back IN emit this proxy's rowsInserted, which
        # lands in _schedule_pass - so every filter setter also posted a
        # SECOND full sort and layoutChanged for the next event-loop
        # turn, doubling exactly the work this synchronous pass just
        # did (the measured shape in _schedule_pass's comment).
        self._in_pass = True
        try:
            self.invalidateFilter()
            self._resort()
        finally:
            self._in_pass = False

    def _resort(self) -> None:
        """Nothing to re-apply before the first sort() establishes a
        column, which is what `sortColumn() == -1` means - sorting on it
        would impose an order nobody asked for."""
        column = self.sortColumn()
        if column >= 0:
            self.sort(column, self.sortOrder())

    def _schedule_pass(self, *_args, refilters: bool = False) -> None:
        """COALESCED, on purpose. A library load inserts in one batch but
        a multi-save inserts a row at a time, and a multi-select Favorite
        toggles a row at a time - one pass per event-loop turn, however
        many rows moved in it."""
        # THE PASS'S OWN ECHO, ignored outright: rows that a re-filter
        # brings back IN emit this proxy's rowsInserted, which lands
        # right here. Answering it posts a SECOND pass, doubling the
        # sort and the layoutChanged that coalescing exists to avoid
        # (measured on 548 rows: 2 passes, 2 sorts, 2 layoutChanged for
        # one burst of three toggles).
        if self._in_pass:
            return
        if refilters:
            self._pass_refilters = True
        # Already queued: merge into it - and note that the flag above
        # is set FIRST, so an insert and a data change in the same turn
        # get one pass that does both.
        if self._pass_scheduled:
            return
        self._pass_scheduled = True
        QtCore.QTimer.singleShot(0, self._pass_now)

    def _pass_now(self) -> None:
        # Cleared at the START: from here the pass is RUNNING, which is
        # `_in_pass`'s business, and a change arriving from outside
        # during it deserves its own pass.
        self._pass_scheduled = False
        refilters, self._pass_refilters = self._pass_refilters, False
        self._in_pass = True
        try:
            if refilters:
                self.invalidateFilter()
            self._resort()
        finally:
            self._in_pass = False
