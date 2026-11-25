"""The Versions window: a material's versions, newest first; Select makes the picked one active."""

from PySide6 import QtCore

import amaze
from amaze import amazetheme, tooltips
from amaze.core import versions
from amaze.qml import dialog_window, rows_model

VERSIONS_QML = amaze.package_file("ui", "dialogs", "VersionsWindow.qml")
LIST = amazetheme.drawn_list_rows("D01")    # the list's size as D01 draws it


class VersionRows(rows_model.RowsModel):
    """The versions as rows: each one's name, then the day it was saved."""

    COLUMNS = ("name", "date")


class VersionsState(dialog_window.DialogState):
    """The versions asked about, newest first, one of them picked: Select hands on its number."""

    rows: QtCore.QObject = None    # a `VersionRows`
    selection: QtCore.QObject = None    # its one picked row, at first the active version's
    picked: int = -1    # the picked row's version number, -1 for none
    table: dict = {}    # L01's figures, as every table has them
    listHeight: int = LIST["view"][1]
    tip: str = tooltips.PANEL_VERSION_ROW
    selectText: str = amazetheme.BTN_SELECT

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        newest = list(reversed(self.question.get("listed", [])))    # the ledger lists oldest first
        self._numbers = [int(entry.get("n", 0)) for entry in newest]
        self.rows = VersionRows(self)
        self.rows.fill([{"name": versions.version_label(entry),
                         "date": str(entry.get("date") or "").split(" ")[0]} for entry in newest])
        self.selection = QtCore.QItemSelectionModel(self.rows, self)
        self.selection.selectionChanged.connect(self._follow_pick)
        self.table = amazetheme.drawn_list()
        active = self.question.get("active")
        self.pick(self._numbers.index(active) if active in self._numbers else -1)

    @QtCore.Slot(int)
    def pick(self, row: int) -> None:
        """Row `row` alone picked, by a click or a key; -1, the space below the rows, picks none."""
        flag = QtCore.QItemSelectionModel.SelectionFlag
        if 0 <= row < len(self._numbers):
            self.selection.setCurrentIndex(self.rows.index(row, 0), flag.ClearAndSelect | flag.Rows)
        else:
            self.selection.clear()

    def _follow_pick(self, *_changed) -> None:
        picked = self.selection.selectedRows()
        self.picked = self._numbers[picked[0].row()] if picked else -1


class VersionsWindow(dialog_window.DialogWindow):
    """The Versions window: the versions as a list, then Select and Cancel."""

    STATE = VersionsState
    SOURCE_URL = QtCore.QUrl.fromLocalFile(VERSIONS_QML).toString()
    DEFAULT_SIZE = QtCore.QSize(amazetheme.D01_FRAME[0], 0)    # D01's width; as tall as its content
    MINIMUM_SIZE = QtCore.QSize(amazetheme.D01_FRAME[0], 0)


def ask(owner, name: str, listed: list, active: int, then) -> VersionsWindow:
    """The versions of material `name`: `then(number)` once, the version picked; None for Cancel."""
    return VersionsWindow.ask(owner, name, {"listed": listed, "active": active}, then)
