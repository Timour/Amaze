"""Versions (D01): a material's versions, newest first; Select makes the picked one active."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from amaze import amazetheme
from amaze import tooltips
from amaze.core import versions
from amaze.dialogs.base_dialog import AssetDialog
from amaze.dialogs.library_dialog import ListRows, drawn_list
from amaze.helpers import theme, ui_helpers

NUMBER_ROLE = QtCore.Qt.ItemDataRole.UserRole + 10    # the version's number in its ledger
DATE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 11      # the day it was saved


class VersionsDialog(AssetDialog):
    """The versions as a list; `chosen` is the picked version's number once Select is pressed."""

    FORM_WIDTH = amazetheme.D01_FRAME[0]
    FRAME_KEY = "D01"

    def __init__(self, title: str, listed: list, active: int, parent=None) -> None:
        super().__init__(title, parent=parent)
        self.chosen = active
        drawn = amazetheme.drawn_list_rows(self.FRAME_KEY)

        self._list = drawn_list(
            self.FRAME_KEY, QtWidgets.QAbstractItemView.SelectionMode.SingleSelection,
            ListRows(None, self.FRAME_KEY, amazetheme.D01_SELECTED_INK,
                     lambda index: str(index.data(DATE_ROLE) or ""), whole_second=True))
        self._list.setToolTip(ui_helpers.tooltip_text(tooltips.PANEL_VERSION_ROW))
        self._select, self._cancel, buttons = self.drawn_pair(amazetheme.BTN_SELECT,
                                                              self._on_accept)
        self._select.setDefault(True)

        body = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.ui_px(drawn["button_top"]))
        column.addWidget(self._list)
        column.addLayout(buttons)
        self.set_content(body)
        self.finish(ok_cancel=False, margins=drawn["margins"])

        for entry in reversed(listed):    # the ledger lists oldest first
            item = QtWidgets.QListWidgetItem(versions.version_label(entry))
            item.setData(NUMBER_ROLE, int(entry.get("n", 0)))
            item.setData(DATE_ROLE, str(entry.get("date") or "").split(" ")[0])
            self._list.addItem(item)
            if int(entry.get("n", 0)) == active:
                self._list.setCurrentItem(item)
        self._list.itemSelectionChanged.connect(self._sync_select)
        self._sync_select()

    def _sync_select(self) -> None:
        self._select.setEnabled(bool(self._list.selectedItems()))

    def _on_accept(self) -> None:
        picked = self._list.selectedItems()
        if picked:
            self.chosen = int(picked[0].data(NUMBER_ROLE))
        super()._on_accept()
