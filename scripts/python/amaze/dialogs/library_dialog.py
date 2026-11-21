"""Manage Libraries (D15): take libraries off the Library list; their folders stay as they are."""

from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.dialogs.base_dialog import AssetDialog
from amaze.helpers import hostos, theme, ui_helpers

FOLDER_ROLE = QtCore.Qt.ItemDataRole.UserRole           # the library's folder, as the list holds it


def library_name(folder: str) -> str:
    """What the Library list calls a library: its folder's name."""
    return (os.path.basename(os.path.normpath(folder)) or folder) if folder else ""


def shown_path(folder: str) -> str:
    """A library's folder as the list shows it, `~` for the home folder."""
    return hostos.storage_path_key(folder).rstrip("/") or folder


class DialogTable(ui_helpers.TwoColumnTable):
    """A dialog's rows: a name and a second text, laid out as its frame draws the list."""

    def __init__(self, frame_key: str, selection_mode, whole_second: bool = False) -> None:
        super().__init__(theme.ui_px(amazetheme.drawn_list_rows(frame_key)["second_x"]), whole_second)
        self.setSelectionMode(selection_mode)
        ui_helpers.fit_drawn(self, frame_key, "QListWidget", None)

    def add_row(self, name: str, second: str, selectable: bool = True, dim: bool = False):
        """Add a row and return its name cell, which carries the row's data."""
        flags = QtCore.Qt.ItemFlag.ItemIsEnabled
        if selectable:
            flags |= QtCore.Qt.ItemFlag.ItemIsSelectable
        cells = super().add_row(name, second, flags)
        for cell in cells if dim else ():
            cell.setForeground(theme.color("text_dim"))
        return cells[0]

    def selected(self) -> list:
        """The name cells of the selected rows."""
        return [self._items.itemFromIndex(index) for index in self.selected_rows()]

    def select(self, cell) -> None:
        self.highlight(cell.index())

    def remove(self, cell) -> None:
        self._items.removeRow(cell.row())


class ManageLibrariesDialog(AssetDialog):
    """The Library list, most recent first; the open library is shown and cannot be selected."""

    FORM_WIDTH = amazetheme.D15_WIDTH
    FRAME_KEY = "D15"

    def __init__(self, preferences, open_library: str = "", parent=None) -> None:
        super().__init__(amazetheme.TITLE_MANAGE_LIBRARIES, parent=parent)
        self._prefs = preferences
        self._open_library = open_library
        self.removed: list = []    # the folders taken off the list
        drawn = amazetheme.drawn_list_rows()

        self._list = DialogTable(
            self.FRAME_KEY, QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)    # one or more
        self._remove, self._cancel, buttons = self.drawn_pair(    # Cancel closes; removals already made are kept
            amazetheme.BTN_REMOVE_FROM_LIST, self._remove_selected)
        self._cancel.setDefault(True)

        body = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.ui_px(drawn["button_top"]))
        column.addWidget(self._list)
        column.addLayout(buttons)
        self.set_content(body)
        self.finish(ok_cancel=False, margins=drawn["margins"])

        self._fill(open_library)
        self._list.selectionModel().selectionChanged.connect(self._sync_remove)
        self._sync_remove()

    def _fill(self, open_library: str) -> None:
        current = hostos.comparable_path(open_library) if open_library else ""
        for folder in self._prefs.libraries:
            reached = os.path.isdir(folder)
            path = shown_path(folder)
            cell = self._list.add_row(
                library_name(folder), path if reached else "%s, %s" % (path, amazetheme.LABEL_NOT_CONNECTED),
                selectable=hostos.comparable_path(folder) != current, dim=not reached)
            cell.setData(folder, FOLDER_ROLE)

    def _sync_remove(self, *_selection) -> None:
        self._remove.setEnabled(bool(self._list.selected()))

    def _remove_selected(self) -> None:
        """Take the selected libraries off the list and save it."""
        chosen = self._list.selected()
        folders = [str(cell.data(FOLDER_ROLE)) for cell in chosen]
        if not folders or not self._prefs.remove_libraries(folders):
            return
        self._prefs.save()
        self.removed.extend(folders)
        for cell in chosen:
            self._list.remove(cell)
