"""The grid engine: what every grid model's cells show, and their order. ▸p/grid-engine"""

from __future__ import annotations

from PySide6 import QtCore, QtGui

from amaze.core import debug, grid_columns

DISPLAY = QtCore.Qt.ItemDataRole.DisplayRole
NAME = grid_columns.KEYS.index("name")
ASCENDING = QtCore.Qt.SortOrder.AscendingOrder
DESCENDING = QtCore.Qt.SortOrder.DescendingOrder


def sort_key(value) -> tuple:
    """A cell as the sort compares it: text case-folded, numbers as numbers, empty last."""
    if value is None:
        return (2, 0, "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, value, "")
    return (1, 0, str(value).casefold())


class GridEngine:
    """Mixed in FIRST over `QAbstractTableModel` by every grid model. ▸p/grid-engine"""

    COLUMN_ROLES: dict = {}    #: {column key: role attribute name or Qt role int} ▸p/list-columns

    COLOUR_COLUMNS = {"category": "CategoryColorRole"}    #: {column key: its ink role}

    TICK_COLUMNS = ("favorite", "open", "comments")    #: painted as a tick by `TickCellDelegate`

    GRID_ROWS: tuple = ()    #: names of the lists kept one entry per row; a sort moves them all

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sort_column = NAME
        self._sort_order = ASCENDING
        self._resort_due = False
        for signal in (self.rowsInserted, self.rowsMoved, self.modelReset):
            signal.connect(self._schedule_resort)
        self.dataChanged.connect(self._rows_changed)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(grid_columns.COLUMNS)    # a table row has no children

    def headerData(self, section, orientation, role=None):
        if role is None:
            role = DISPLAY
        if not (orientation == QtCore.Qt.Orientation.Horizontal
                and 0 <= section < len(grid_columns.LABELS)):
            return None
        if role == DISPLAY:
            return grid_columns.LABELS[section]
        return None

    def _column_role(self, key):
        """The role this model answers a column with, or None."""
        named = self.COLUMN_ROLES.get(key)
        if named is None:
            return None
        if isinstance(named, int):
            return named
        return getattr(self, named, None)

    def last_column(self) -> int:
        """The rightmost column, for a `dataChanged` range. ▸p/list-columns"""
        return max(self.columnCount() - 1, 0)

    def row_changed(self, row: int, roles=None) -> None:
        """Repaint one row, ACROSS EVERY COLUMN."""
        if not 0 <= row < self.rowCount():
            return
        top = self.index(row, 0)
        bottom = self.index(row, self.last_column())
        if roles is None:
            self.dataChanged.emit(top, bottom)
        else:
            self.dataChanged.emit(top, bottom, roles)

    def data(self, index, role=DISPLAY):
        """The one data(): column 0 is the row's answer, a later column its cell's."""
        row = index.row()
        if not 0 <= row < self.rowCount():    # an invalid index is row -1; an index outlives a shrink
            return None
        column = index.column()
        if column <= 0:
            return self.row_data(row, role)
        return self.cell_data(row, column, role)

    def row_data(self, row: int, role):
        """What `row` answers for `role`; the one method a grid model writes. `row` is in range."""
        return None

    def cell_data(self, row: int, column: int, role):
        """A later column: its text, its ink and the row's tooltip, all asked of `row_data`."""
        if not 0 < column < len(grid_columns.KEYS):
            return None
        key = grid_columns.KEYS[column]
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            named = self.COLOUR_COLUMNS.get(key)
            ink = getattr(self, named, None) if named else None
            value = self.row_data(row, ink) if ink is not None else None
            colour = QtGui.QColor(str(value)) if value else None
            return colour if colour is not None and colour.isValid() else None
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return self.row_data(row, role)    # list mode hides column 0; the pointer rests on a cell
        if role != DISPLAY:
            return None    # decoration and the rest stay column 0's ▸p/list-columns
        mapped = self._column_role(key)
        if mapped is None:
            return None    # this model has no such column - not an error
        value = self.row_data(row, mapped)
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        return value

    def sort_column(self) -> int:
        """The column the rows are sorted by - Name, never the hidden column 0."""
        return self._sort_column

    def sort_order(self):
        return self._sort_order

    def sort(self, column: int, order=ASCENDING) -> None:
        """Sort the rows themselves; the header reaches here through the grid proxy."""
        self._sort_column = NAME if column <= 0 else column    # column 0 answers the name
        self._sort_order = order
        self.resort()

    def _sort_role(self):
        return self._column_role(grid_columns.KEYS[self._sort_column])

    def _sorted_rows(self) -> list:
        """Today's rows as old row numbers, in sort order: one key each, stable both ways."""
        keys = [sort_key(self.cell_data(row, self._sort_column, DISPLAY))
                for row in range(self.rowCount())]
        return sorted(range(len(keys)), key=keys.__getitem__,
                      reverse=self._sort_order == DESCENDING)

    def _in_step(self) -> bool:
        """Every row list holds one entry per row; a list out of step would move to wrong rows."""
        count = self.rowCount()
        for name in self.GRID_ROWS:
            held = len(getattr(self, name))
            if held != count:
                debug.event("grid", "rows not sorted - a row list is out "
                            "of step", model=type(self).__name__,
                            rows=count, list=name, held=held)
                return False
        return True

    def _take_order(self, order: list) -> None:
        for name in self.GRID_ROWS:
            rows = getattr(self, name)
            rows[:] = [rows[old] for old in order]    # in place: a holder of the list sees it move

    def order_rows(self) -> dict | None:
        """Sort with NO signal, for a model building its rows; {old row: new row} or None."""
        moved = None
        if self._in_step():
            order = self._sorted_rows()
            if order != list(range(len(order))):
                self._take_order(order)
                moved = {old: new for new, old in enumerate(order)}
        self.rows_reordered()
        return moved

    def resort(self) -> dict | None:
        """Sort NOW, as one layout change carrying every bookmark; {old: new row} or None."""
        self._resort_due = False
        if not self._in_step():
            return None
        order = self._sorted_rows()
        if order == list(range(len(order))):
            return None
        moved = {old: new for new, old in enumerate(order)}
        self.layoutAboutToBeChanged.emit()    # PySide takes no hint here; never around an insert ▸r/node-graph
        held = self.persistentIndexList()
        self._take_order(order)
        self.rows_reordered()
        self.changePersistentIndexList(
            held, [self.index(moved.get(index.row(), index.row()),
                              index.column()) for index in held])
        self.layoutChanged.emit()
        return moved

    def rows_reordered(self) -> None:
        """Rebuild what this model keys BY ROW once `GRID_ROWS` moved."""

    def _schedule_resort(self, *_args) -> None:
        """Sort on the next turn, ONCE however many rows came. No timer of its own. ▸r/grid-sort-cost"""
        if self._resort_due:
            return
        self._resort_due = True
        QtCore.QTimer.singleShot(0, self._resort_if_due)    # holds the model until it runs

    def _resort_if_due(self) -> None:
        if self._resort_due:
            self.resort()

    def _rows_changed(self, _top, _bottom, roles=()) -> None:
        if not roles or self._sort_role() in roles:    # a thumbnail landing reads nothing it sorts by
            self._schedule_resort()
