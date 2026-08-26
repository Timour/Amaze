"""The Grid's COLUMNS - the ONE order, and the model half of it. Column 0 IS the row and answers every role the grid delegate reads; 1..N are additive, so grid mode cannot tell they exist. ▸p/list-columns"""

from __future__ import annotations

from PySide6 import QtCore, QtGui

COLUMNS = (    #: THE COLUMN ORDER, once: (key, header label). The key is what a model maps to a role and what a width is filed under; an empty label is a column with no heading ▸p/list-columns
    ("thumb", ""),
    ("name", "Name"),
    ("type", "Type"),
    ("category", "Category"),
    ("favorite", "Favorite"),
    ("version", "Version"),
    ("open", "Open"),
    ("comments", "Comments"),
    ("tags", "Tags"),
    ("license", "License"),
    ("date", "Date"),
    ("id", "ID"),
)

KEYS = tuple(key for key, _label in COLUMNS)
LABELS = tuple(label for _key, label in COLUMNS)


def selected_rows(selection) -> list:
    """The grid selection as ONE index per row - column 0, THE row. EVERY reader of the grid selection comes through here, so a table's per-cell answer and a list's per-row one collapse to the same shape once. ▸p/list-columns"""
    if selection is None:
        return []
    return [index for index in selection.selectedIndexes()
            if index.column() == 0]


class GridColumnsMixin:
    """Makes a flat model answer as a TABLE - declare `COLUMN_ROLES` and the rest follows. The base must be `QAbstractTableModel`, and this must go FIRST in the bases. ▸p/list-columns"""

    COLUMN_ROLES: dict = {}    #: {column key: role attribute name, or a literal Qt role int}; a model fills in only what it has ▸p/list-columns

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        # A valid parent means a child of a row, and a table has none.
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=None):
        if role is None:
            role = QtCore.Qt.ItemDataRole.DisplayRole
        if not (orientation == QtCore.Qt.Orientation.Horizontal
                and 0 <= section < len(LABELS)):
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return LABELS[section]
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
        """The rightmost column, for a `dataChanged` range - a repaint that stops at column 0 invalidates the thumbnail and nothing else. ▸p/list-columns"""
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

    COLOUR_COLUMNS = {"category": "CategoryColorRole"}    #: {column key: the role carrying that column's own INK}; NO FontRole anywhere ▸p/list-columns

    TICK_COLUMNS = ("favorite", "open", "comments")    #: drawn as a TICK by `TickCellDelegate`, aligned like every other column; `grid.bind_table_cell_delegates` walks this ▸p/list-columns

    def column_data(self, index, role):
        """What a LATER column shows - None for column 0, for a column this model cannot fill, and for any role but Display. NOT called `data`, and every model calls it from the top of its own. ▸p/list-columns"""
        column = index.column()
        if column <= 0 or column >= len(KEYS):
            return None
        key = KEYS[column]
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            named = self.COLOUR_COLUMNS.get(key)
            if named is None:
                return None
            value = self.data(index.siblingAtColumn(0),
                              getattr(self, named, None)) if named else None
            colour = QtGui.QColor(str(value)) if value else None
            return colour if colour is not None and colour.isValid() else None
        if role != QtCore.Qt.ItemDataRole.DisplayRole:
            return None    # a cell shows TEXT; decoration and tooltips stay column 0's ▸p/list-columns
        mapped = self._column_role(key)
        if mapped is None:
            return None    # this model has no such column - not an error ▸p/list-columns
        value = self.data(index.siblingAtColumn(0), mapped)    # the ROW's answer: the roles live on column 0
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        return value
