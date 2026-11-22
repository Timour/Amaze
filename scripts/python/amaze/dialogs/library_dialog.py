"""A library's name and folder as its lists show them, and the two-column table dialogs use."""

from __future__ import annotations

import os

from PySide6 import QtCore

from amaze import amazetheme
from amaze.helpers import hostos, theme, ui_helpers


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
