"""Manage Libraries (D15): take libraries off the Library list; their folders stay as they are."""

from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.dialogs.base_dialog import AssetDialog
from amaze.helpers import hostos, theme, ui_helpers

FOLDER_ROLE = QtCore.Qt.ItemDataRole.UserRole           # the library's folder, as the list holds it
REACHED_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1      # False for a folder that cannot be reached now
_ALIGN = QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter


def library_name(folder: str) -> str:
    """What the Library list calls a library: its folder's name."""
    return os.path.basename(os.path.normpath(folder)) or folder


def shown_path(folder: str) -> str:
    """A library's folder as the list shows it, `~` for the home folder."""
    return hostos.storage_path_key(folder).rstrip("/") or folder


class _LibraryRows(QtWidgets.QStyledItemDelegate):
    """A row as D15 draws it: folder name, path, and `not connected` when it cannot be reached."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drawn = amazetheme.drawn_library_rows()

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), theme.ui_px(self._drawn["pitch"]))

    def paint(self, painter, option, index):
        drawn, px = self._drawn, theme.ui_px
        row = option.rect
        box = QtCore.QRect(row.x() + px(drawn["box_x"]), row.y() + px(drawn["box_y"]),
                           row.width() - 2 * px(drawn["box_x"]), px(drawn["box_h"]))
        reached = index.data(REACHED_ROLE) is not False
        metrics = QtGui.QFontMetrics(option.font)
        top, high = box.y() + px(drawn["text_y"]), px(drawn["text_h"])
        right = box.x() + box.width() - px(drawn["flag_right"])
        name_x = box.x() + px(drawn["name_x"])
        path_x = box.x() + px(drawn["path_x"])
        painter.save()
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.fillRect(box, QtGui.QColor(amazetheme.D15_SELECTED_INK))
        painter.setFont(option.font)
        if not reached:
            flag = amazetheme.LABEL_NOT_CONNECTED
            wide = metrics.horizontalAdvance(flag)
            _draw(painter, metrics, flag, QtCore.QRect(right - wide, top, wide, high),
                  QtGui.QColor(amazetheme.D15_DIM_INK), QtCore.Qt.TextElideMode.ElideNone)
            right -= wide + px(drawn["flag_right"])
        _draw(painter, metrics, str(index.data() or ""),
              QtCore.QRect(name_x, top, path_x - name_x, high),
              theme.color("text_bright") if reached else QtGui.QColor(amazetheme.D15_DIM_INK),
              QtCore.Qt.TextElideMode.ElideRight)
        _draw(painter, metrics, shown_path(str(index.data(FOLDER_ROLE) or "")),
              QtCore.QRect(path_x, top, max(0, right - path_x), high),
              theme.color("text") if reached else QtGui.QColor(amazetheme.D15_DIM_PATH_INK),
              QtCore.Qt.TextElideMode.ElideMiddle)
        painter.restore()


def _draw(painter, metrics, text, rect, ink, elide) -> None:
    painter.setPen(ink)
    painter.drawText(rect, _ALIGN, metrics.elidedText(text, elide, rect.width()))


class ManageLibrariesDialog(AssetDialog):
    """The Library list, most recent first; the open library is shown and cannot be selected."""

    FORM_WIDTH = amazetheme.D15_WIDTH
    FRAME_KEY = "D15"

    def __init__(self, preferences, open_library: str = "", parent=None) -> None:
        super().__init__(amazetheme.TITLE_MANAGE_LIBRARIES, parent=parent)
        self._prefs = preferences
        self.removed: list = []    # the folders taken off the list
        drawn = amazetheme.drawn_library_rows()

        self._list = QtWidgets.QListWidget()
        self._list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)    # one or more
        self._list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setUniformItemSizes(True)
        self._list.setItemDelegate(_LibraryRows(self._list))
        palette = self._list.palette()    # PALETTE, as the sidebar does: a view paints its viewport from Base
        palette.setColor(QtGui.QPalette.ColorRole.Base, theme.color("field"))
        self._list.setPalette(palette)
        ui_helpers.pin_drawn(self._list, self.FRAME_KEY, "QListWidget", None)

        self._remove = QtWidgets.QPushButton(amazetheme.BTN_REMOVE_FROM_LIST)
        self._close = QtWidgets.QPushButton(amazetheme.BTN_CLOSE)
        for button in (self._remove, self._close):
            ui_helpers.pin_drawn(button, self.FRAME_KEY, "QPushButton", button.text())
            button.setAutoDefault(False)
        self._close.setDefault(True)
        self._remove.clicked.connect(self._remove_selected)
        self._close.clicked.connect(self._on_accept)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(theme.ui_px(drawn["button_gap"]))
        buttons.addStretch(1)
        buttons.addWidget(self._remove)
        buttons.addWidget(self._close)
        body = QtWidgets.QWidget()
        column = QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.ui_px(drawn["button_top"]))
        column.addWidget(self._list)
        column.addLayout(buttons)
        self.set_content(body)
        self.finish(ok_cancel=False, margins=drawn["margin"])    # the frame's margin, all four sides

        self._fill(open_library)
        self._list.itemSelectionChanged.connect(self._sync_remove)
        self._sync_remove()

    def _fill(self, open_library: str) -> None:
        current = hostos.comparable_path(open_library) if open_library else ""
        for folder in self._prefs.libraries:
            item = QtWidgets.QListWidgetItem(library_name(folder))
            item.setData(FOLDER_ROLE, folder)
            item.setData(REACHED_ROLE, os.path.isdir(folder))
            if hostos.comparable_path(folder) == current:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsSelectable)
            self._list.addItem(item)

    def _sync_remove(self) -> None:
        self._remove.setEnabled(bool(self._list.selectedItems()))

    def _remove_selected(self) -> None:
        """Take the selected libraries off the list and save it."""
        chosen = self._list.selectedItems()
        folders = [str(item.data(FOLDER_ROLE)) for item in chosen]
        if not folders or not self._prefs.remove_libraries(folders):
            return
        self._prefs.save()
        self.removed.extend(folders)
        for item in chosen:
            self._list.takeItem(self._list.row(item))
