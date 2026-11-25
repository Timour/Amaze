"""RowsModel: a table's rows for QML, a dict each; a column shows one key, QML reads the rest."""

from PySide6 import QtCore


class RowsModel(QtCore.QAbstractTableModel):
    """Rows for a table: `COLUMNS` name the key each column shows, `FIELDS` the roles beside them."""

    COLUMNS: tuple = ()    # per column, the row key whose text it shows as `display`
    FIELDS: tuple = ()    # the row keys QML reads by name besides `display`, a role each

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list = []

    @classmethod
    def role(cls, field: str) -> int:
        return QtCore.Qt.ItemDataRole.UserRole + cls.FIELDS.index(field)

    def fill(self, rows: list) -> None:
        """New rows, the old removed as rows: a reset clears Qt's selection model with no signal."""
        if self.rows:
            self.beginRemoveRows(QtCore.QModelIndex(), 0, len(self.rows) - 1)
            self.rows = []
            self.endRemoveRows()
        if rows:
            self.beginInsertRows(QtCore.QModelIndex(), 0, len(rows) - 1)
            self.rows = rows
            self.endInsertRows()

    def selectable(self, row: dict) -> bool:
        """Whether `row` can be chosen; a row that cannot is only shown."""
        return True

    def roleNames(self) -> dict:
        roles = {QtCore.Qt.ItemDataRole.DisplayRole: b"display"}
        roles.update({self.role(field): field.encode() for field in self.FIELDS})
        return roles

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def flags(self, index):
        flags = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemNeverHasChildren
        if index.isValid() and self.selectable(self.rows[index.row()]):
            flags |= QtCore.Qt.ItemFlag.ItemIsSelectable
        return flags

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return row[self.COLUMNS[index.column()]]
        number = int(role) - int(QtCore.Qt.ItemDataRole.UserRole)
        return row[self.FIELDS[number]] if 0 <= number < len(self.FIELDS) else None
