"""The Versions window: a material's versions, newest first; Select makes the picked one active."""

from PySide6 import QtCore

import amaze
from amaze import amazetheme, messages, tooltips
from amaze.core import guard, versions
from amaze.qml import dialog_window, rows_model

VERSIONS_QML = amaze.package_file("ui", "dialogs", "VersionsWindow.qml")
FRAME = "QML D01"    # the window as UI Design QML draws it
LIST = amazetheme.drawn_list_rows(FRAME)    # the list's size as that frame draws it
WIDTH = amazetheme.DIALOG_LAYOUT[FRAME]["frame"][0]


class VersionRows(rows_model.RowsModel):
    """The versions as rows: each one's name, then the day it was saved."""

    COLUMNS = ("name", "date")


class VersionsState(dialog_window.DialogState):
    """The versions asked about, newest first, one of them picked: Select hands on its number."""

    rows: QtCore.QObject = None    # a `VersionRows`
    selection: QtCore.QObject = None    # its one picked row, at first the active version's
    picked: int = -1    # the picked row's version number, -1 for none
    deletable: bool = False    # Delete is on: more than one version is left
    table: dict = {}    # L01's figures, as every table has them
    listHeight: int = LIST["view"][1]
    buttonWidth: int = max(node[3] for node in amazetheme.DIALOG_LAYOUT[FRAME]["nodes"]
                           if node[0] == "QPushButton")
    tip: str = tooltips.PANEL_VERSION_ROW
    selectText: str = amazetheme.BTN_SELECT
    deleteText: str = messages.BUTTONS_DELETE[0]
    deleteTip: str = messages.HELP_DELETE_VERSION % guard.TRASH_DAYS

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._numbers = []
        self.rows = VersionRows(self)
        self.selection = QtCore.QItemSelectionModel(self.rows, self)
        self.selection.selectionChanged.connect(self._follow_pick)
        self.table = amazetheme.drawn_list()
        self.reasked(self.question)

    def reasked(self, question: dict) -> None:
        """The versions in `question` shown: a row gone is removed as a row, the active one picked."""
        super().reasked(question)
        newest = list(reversed(question.get("listed", [])))    # the ledger lists oldest first
        numbers = [int(entry.get("n", 0)) for entry in newest]
        for row in reversed(range(len(self._numbers))):
            if self._numbers[row] not in numbers:
                del self._numbers[row]
                self.rows.remove(row)
        if self._numbers != numbers:
            self._numbers = numbers
            self.rows.fill([{"name": versions.version_label(entry),
                             "date": str(entry.get("date") or "").split(" ")[0]}
                            for entry in newest])
        self.deletable = len(numbers) > 1
        active = question.get("active")
        self.pick(numbers.index(active) if active in numbers else -1)

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
    """The Versions window: the versions as a list, then Select, Delete and Cancel."""

    STATE = VersionsState
    SOURCE_URL = QtCore.QUrl.fromLocalFile(VERSIONS_QML).toString()
    DEFAULT_SIZE = QtCore.QSize(WIDTH, 0)    # the frame's width; as tall as its content
    MINIMUM_SIZE = QtCore.QSize(WIDTH, 0)


def ask(owner, name: str, listed: list, active: int, then) -> VersionsWindow:
    """`then(number)` at the close, None at Cancel; at Delete `then({delete: n})` returns the next."""
    return VersionsWindow.ask(owner, name, {"listed": listed, "active": active}, then)
