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
    return (os.path.basename(os.path.normpath(folder)) or folder) if folder else ""


def shown_path(folder: str) -> str:
    """A library's folder as the list shows it, `~` for the home folder."""
    return hostos.storage_path_key(folder).rstrip("/") or folder


class ListRows(QtWidgets.QStyledItemDelegate):
    """A row as a drawn list paints it: name, second column, `not connected` when unreachable."""

    def __init__(self, parent=None, frame_key: str = "D15",
                 selected_ink: str = amazetheme.D15_SELECTED_INK, second=None,
                 whole_second: bool = False) -> None:
        super().__init__(parent)
        self._drawn = amazetheme.drawn_list_rows(frame_key)
        self._selected_ink = selected_ink
        self._second = second or (lambda index: shown_path(str(index.data(FOLDER_ROLE) or "")))
        self._whole_second = whole_second    # a short text such as a date: drawn whole, never cut

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
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            painter.setPen(QtCore.Qt.PenStyle.NoPen)
            painter.setBrush(QtGui.QColor(self._selected_ink))
            painter.drawRoundedRect(box, px(amazetheme.LIST_RADIUS), px(amazetheme.LIST_RADIUS))
        painter.setFont(option.font)
        if not reached:
            flag = amazetheme.LABEL_NOT_CONNECTED
            wide = metrics.horizontalAdvance(flag)
            _draw(painter, metrics, flag, QtCore.QRect(right - wide, top, wide, high),
                  QtGui.QColor(amazetheme.D15_DIM_INK), QtCore.Qt.TextElideMode.ElideNone)
            right -= wide + px(drawn["flag_right"])
        second = self._second(index)
        name_end, elide = path_x, QtCore.Qt.TextElideMode.ElideMiddle
        if self._whole_second:
            path_x = min(path_x, right - metrics.horizontalAdvance(second) - 1)    # 1: subpixel
            name_end, elide = path_x - px(drawn["name_x"]), QtCore.Qt.TextElideMode.ElideNone
        _draw(painter, metrics, str(index.data() or ""),
              QtCore.QRect(name_x, top, max(0, name_end - name_x), high),
              theme.color("text_bright") if reached else QtGui.QColor(amazetheme.D15_DIM_INK),
              QtCore.Qt.TextElideMode.ElideRight)
        _draw(painter, metrics, second,
              QtCore.QRect(path_x, top, max(0, right - path_x), high),
              theme.color("text") if reached else QtGui.QColor(amazetheme.D15_DIM_PATH_INK),
              elide)
        painter.restore()


def _draw(painter, metrics, text, rect, ink, elide) -> None:
    painter.setPen(ink)
    painter.drawText(rect, _ALIGN, metrics.elidedText(text, elide, rect.width()))


def ground_list(view) -> None:
    """A drawn list's ground: Houdini's list colour, with the drawn corners."""
    view.setStyleSheet(
        "QListWidget { background-color: %s; border: none; border-radius: %dpx; }"
        % (theme.list_ground().name(), theme.ui_px(amazetheme.LIST_RADIUS)))


def drawn_list(frame_key: str, selection_mode, delegate) -> QtWidgets.QListWidget:
    """A drawn list: no frame, no sideways scroll, `delegate` painting rows on the list ground."""
    view = QtWidgets.QListWidget()
    view.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    view.setSelectionMode(selection_mode)
    view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setUniformItemSizes(True)
    delegate.setParent(view)    # the view does not own its delegate ▸r/delegate-orphans
    view.setItemDelegate(delegate)
    ground_list(view)
    ui_helpers.pin_drawn(view, frame_key, "QListWidget", None)
    return view


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

        self._list = drawn_list(
            self.FRAME_KEY,
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection,    # one or more
            ListRows())
        self._remove, self._cancel, buttons = self.drawn_pair(    # Cancel closes; a removal made stays
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
