"""The sidebar view, and what may be dropped on a row. ▸o/section-api"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.core import category, sidebar_model
from amaze.helpers import theme, ui_helpers


def top_level(index):
    """The top-level row above an index; a top-level index returns itself."""
    while index.isValid() and index.parent().isValid():
        index = index.parent()
    return index


class SidebarTreeView(ui_helpers.Table):
    """The sidebar: the app's table with a colour cell, then the name and the style's own arrow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._open: dict = {}    # id(model) -> the keys of the rows open in it
        self._pending_reveal = None    # (model, path) to select once its row is inserted
        self._watched = None
        self.expanded.connect(self._opened)
        self.collapsed.connect(self._closed)
        self.row_chosen.connect(self._forget_reveal)    # a row the user chose cancels a pending folder reveal
        self.setDragEnabled(True)    # Qt's own row move; the model says which rows and does the move
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.setDropIndicatorShown(True)

    def _forget_reveal(self, _index) -> None:
        self._pending_reveal = None

    def selectionCommand(self, index, event=None):
        """Qt's own answer, but a Ctrl-click never empties the sidebar: the grid always shows one row."""
        command = super().selectionCommand(index, event)
        flag = QtCore.QItemSelectionModel.SelectionFlag
        if index.isValid() and command & (flag.Deselect | flag.Toggle):
            return flag.ClearAndSelect | flag.Rows
        return command

    def mousePressEvent(self, event) -> None:
        """A left click on the highlighted row shows it again, as a click on any other row shows that one."""
        index = self.indexAt(event.position().toPoint())
        current = self.currentIndex()
        again = (event.button() == QtCore.Qt.MouseButton.LeftButton and index.isValid() and current.isValid()
                 and index.siblingAtColumn(0) == current.siblingAtColumn(0))
        opened = again and self.isExpanded(index.siblingAtColumn(0))
        super().mousePressEvent(event)
        if again and self.isExpanded(index.siblingAtColumn(0)) != opened:
            return    # the press was on the row's arrow: it opened or closed the row, and chose nothing
        if again and not self._quiet:
            self.row_chosen.emit(index.siblingAtColumn(0))    # no current change, so `currentChanged` sent nothing

    def _lay_out_columns(self, model) -> None:
        """The colour cell first at the bar's width, then the name, which carries the arrows."""
        header = self.header()
        color = sidebar_model.COLOR_COLUMN
        if model.columnCount() <= color:
            return
        header.setMinimumSectionSize(1)
        header.setStretchLastSection(False)
        if header.visualIndex(color) != 0:
            header.moveSection(header.visualIndex(color), 0)
        header.setSectionResizeMode(color, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(color, theme.ui_px(amazetheme.drawn_sidebar()["bar"]))
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.setTreePosition(0)    # the arrows and the indent belong to the name, not to the first cell shown
        self.setRootIsDecorated(bool(getattr(model, "unfolds", False)))    # a flat list has no arrow column

    def _remembers(self, model) -> bool:
        return model is not None and getattr(model, "unfolds", False)

    def setModel(self, model):
        old = self._watched
        if old is not None:
            for signal in (old.modelReset, old.rowsInserted):
                try:
                    signal.disconnect(self._reopen)
                except (RuntimeError, TypeError):
                    pass
        super().setModel(model)
        if model is not None:
            self._lay_out_columns(model)
        self._watched = model if self._remembers(model) else None
        if self._watched is not None:
            model.modelReset.connect(self._reopen)
            model.rowsInserted.connect(self._reopen)
            self._reopen()

    def _key(self, index):
        return index.data(category.SIDEBAR_KEY_ROLE) if self._remembers(self.model()) else None

    def _opened(self, index):
        key = self._key(index)
        if key:
            self._open.setdefault(id(self.model()), set()).add(key)

    def _closed(self, index):
        key = self._key(index)
        if key:
            self._open.get(id(self.model()), set()).discard(key)

    def _reopen(self, *_args):
        """Expand again what was expanded, and select a pending folder once its row exists."""
        model = self.model()
        if not self._remembers(model):
            return
        for key in sorted(self._open.get(id(model), ()), key=len):    # a folder before its subfolders
            index = model.index_of(key)
            if index.isValid() and not self.isExpanded(index):
                self.expand(index)
        pending = self._pending_reveal
        if pending is not None and pending[0] is model:
            index = model.index_of(pending[1])
            if index.isValid():
                self._pending_reveal = None
                self.highlight(index)    # the app's move: the folder is already browsed
                self.scrollTo(index)

    def reveal(self, path: str) -> None:
        """Expand every folder above `path` and select it, as their rows are inserted; File only."""
        model = self.model()
        if not self._remembers(model) or not path or getattr(model, "top_of", None) is None:
            return
        location = model.top_of(path)    # the top row's folder, the scene's row included
        opened = self._open.setdefault(id(model), set())
        opened.add(location)
        here = path.rstrip("/")
        while "/" in here and here != location.rstrip("/"):
            here = here.rsplit("/", 1)[0]
            if here.rstrip("/") == location.rstrip("/"):
                break
            opened.add(here)
        self._pending_reveal = (model, path)
        self._reopen()


def droppable_index(panel, pos):
    """The only place the drop-target rules are defined; None if no tile may be dropped here."""
    context = panel.active_section()
    if context is None or not (context.takes_category_drops or context.takes_file_drops):
        return None
    if panel.cat_list is None:
        return None
    index = panel.cat_list.indexAt(pos)
    if not index.isValid():
        return None
    if context.takes_file_drops:    # a folder row: the tile's file moves there, on disk
        return index if context.accepts_file_drop(index) else None
    name = panel.raw_category_name(index)
    if not name or category.is_all(name):
        return None
    if not context.accepts_category_drop(index, name):
        return None
    return index


def category_at_point(panel, pos):
    """The droppable category at a point, by its STORED name - the form the write needs."""
    context = panel.active_section()
    if context is None or not context.takes_category_drops:
        return None
    index = droppable_index(panel, pos)
    return None if index is None else panel.raw_category_name(index)


def folder_at_point(panel, pos):
    """The folder a tile dropped at a point moves into, or None."""
    context = panel.active_section()
    if context is None or not context.takes_file_drops:
        return None
    index = droppable_index(panel, pos)
    return None if index is None else context.drop_folder(index)


def _cursor_in_sidebar(panel):
    """The cursor's sidebar-local position, or None when it is not over it."""
    if panel.cat_list is None or not panel.cat_list.isVisible():
        return None
    viewport = panel.cat_list.viewport()
    pos = viewport.mapFromGlobal(QtGui.QCursor.pos())
    return pos if viewport.rect().contains(pos) else None


def category_under_cursor(panel):
    """The assignable category under the GLOBAL cursor; every self-managed drop calls this first."""
    pos = _cursor_in_sidebar(panel)
    return None if pos is None else category_at_point(panel, pos)


def folder_under_cursor(panel):
    """The folder under the GLOBAL cursor that a self-managed release moves files into."""
    pos = _cursor_in_sidebar(panel)
    return None if pos is None else folder_at_point(panel, pos)


def set_hover_row(panel, row) -> None:
    """Highlight one row by its index (-1 clears); `repaint()`, never `update()`. ▸r/native-drag-paint"""
    delegate = getattr(panel, "sidebar_delegate", None)
    if delegate is None:
        return
    persistent = (QtCore.QPersistentModelIndex(row) if isinstance(row, QtCore.QModelIndex)
                  else QtCore.QPersistentModelIndex())
    if persistent == delegate.drag_index:
        return
    delegate.drag_index = persistent
    if panel.cat_list is not None:
        panel.cat_list.viewport().repaint()


def update_hover(panel, pos) -> None:
    """Set the highlight from a sidebar-local point."""
    index = droppable_index(panel, pos)
    set_hover_row(panel, index if index is not None else -1)


def update_hover_global(panel) -> None:
    """The highlight for the SELF-MANAGED drags, which have no Qt drag events."""
    pos = _cursor_in_sidebar(panel)
    if pos is None:
        set_hover_row(panel, -1)
        return
    update_hover(panel, pos)
