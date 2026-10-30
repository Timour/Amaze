"""The Sidebar: what a row MEANS, and what may be dropped on it. ▸o/section-api"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.core import category, debug
from amaze.helpers import theme


def top_level(index):
    """The top row an index sits under; a top row answers itself."""
    while index.isValid() and index.parent().isValid():
        index = index.parent()
    return index


class SidebarTreeView(QtWidgets.QTreeView):
    """The one sidebar: a flat list in the asset tabs, a folder tree in File. ▸r/tree-views"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)    # each row draws its own arrow, after its colour bar
        self.setUniformRowHeights(True)
        self.setIndentation(theme.ui_px(amazetheme.SIDEBAR_INDENT))
        self._open: dict = {}    # id(model) -> the folder paths open in it
        self._standing = None    # (model, path) to stand on once its row arrives
        self._watched = None
        self._arrow_press = False
        self._pressed = None    # the row a left press landed on, held across the gesture
        self.expanded.connect(self._opened)
        self.collapsed.connect(self._closed)

    def drawBranches(self, painter, rect, index):
        """Qt's indent-column arrows stay undrawn: the row's own arrow is the only one."""

    def paintEvent(self, event):
        if not self.alternatingRowColors():
            super().paintEvent(event)
            return
        rows = QtCore.QRect(0, 0, self.viewport().width(), self._rows_bottom())
        super().paintEvent(QtGui.QPaintEvent(event.region().intersected(rows)))    # below: the plain ground

    def _rows_bottom(self) -> int:
        """Where the last row on screen ends, 0 with none."""
        index, bottom = self.indexAt(QtCore.QPoint(0, 0)), 0
        while index.isValid():
            rect = self.visualRect(index)
            bottom = rect.bottom() + 1
            if bottom > self.viewport().height():
                break
            index = self.indexBelow(index)
        return bottom

    def arrow_rect(self, index) -> QtCore.QRect:
        """Where a row's arrow sits in the viewport; empty when the row has none."""
        model = self.model()
        delegate = self.itemDelegateForIndex(index) if index.isValid() else None
        if (model is None or delegate is None or not hasattr(delegate, "arrow_box")
                or not getattr(model, "unfolds", False) or not model.hasChildren(index)):
            return QtCore.QRect()
        option = QtWidgets.QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = self.visualRect(index)
        delegate.initStyleOption(option, index)
        decoration = self.style().subElementRect(
            QtWidgets.QStyle.SubElement.SE_ItemViewItemDecoration, option, self)
        return delegate.arrow_box(decoration)

    def _on_arrow(self, event) -> QtCore.QModelIndex:
        point = event.position().toPoint()
        index = self.indexAt(point)
        if event.button() == QtCore.Qt.MouseButton.LeftButton \
                and self.arrow_rect(index).contains(point):
            return index
        return QtCore.QModelIndex()

    def mousePressEvent(self, event):
        index = self._on_arrow(event)
        if index.isValid():    # the arrow opens or closes; it neither selects nor clicks
            self.setExpanded(index, not self.isExpanded(index))
            self._arrow_press = True
            event.accept()
            return
        self._arrow_press = False
        pressed = self.indexAt(event.position().toPoint())
        if pressed.isValid():
            self._standing = None    # a row the user chose outranks a folder still unfolding
        left = event.button() == QtCore.Qt.MouseButton.LeftButton
        self._pressed = QtCore.QPersistentModelIndex(pressed) if left else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._arrow_press:
            self._arrow_press = False
            event.accept()
            return
        pressed, self._pressed = self._pressed, None
        under = self.indexAt(event.position().toPoint())
        super().mouseReleaseEvent(event)    # Qt clicks only a release on the row pressed
        if pressed is None or not pressed.isValid() or QtCore.QModelIndex(pressed) == under:
            return
        current = self.currentIndex()
        if current.isValid() and self.selectionModel().isSelected(current):
            self.clicked.emit(current)    # dragged onto another row, or released off it: still a choice

    def keyPressEvent(self, event):
        before = QtCore.QPersistentModelIndex(self.currentIndex())
        super().keyPressEvent(event)
        if QtCore.QModelIndex(before) != self.currentIndex():
            self._standing = None    # the user moved off the row waiting for its folder

    def mouseDoubleClickEvent(self, event):
        index = self._on_arrow(event)
        if index.isValid():    # each click on the arrow is one toggle
            self.setExpanded(index, not self.isExpanded(index))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _remembers(self, model) -> bool:
        return model is not None and getattr(model, "unfolds", False) \
            and hasattr(model, "BrowseRole")

    def setModel(self, model):
        old = self._watched
        if old is not None:
            for signal in (old.modelReset, old.rowsInserted):
                try:
                    signal.disconnect(self._reopen)
                except (RuntimeError, TypeError):
                    pass
        super().setModel(model)
        self._watched = model if self._remembers(model) else None
        if self._watched is not None:
            model.modelReset.connect(self._reopen)
            model.rowsInserted.connect(self._reopen)
            self._reopen()

    def _path(self, index):
        model = self.model()
        return index.data(model.BrowseRole) if self._remembers(model) else None

    def _opened(self, index):
        path = self._path(index)
        if path:
            self._open.setdefault(id(self.model()), set()).add(path)

    def _closed(self, index):
        path = self._path(index)
        if path:
            self._open.get(id(self.model()), set()).discard(path)

    def _reopen(self, *_args):
        """Open again what was open, and stand on a pending folder once its row is there."""
        model = self.model()
        if not self._remembers(model):
            return
        for path in sorted(self._open.get(id(model), ()), key=len):    # parents first
            index = model.index_of(path)
            if index.isValid() and not self.isExpanded(index):
                self.expand(index)
        standing = self._standing
        if standing is not None and standing[0] is model:
            index = model.index_of(standing[1])
            if index.isValid():
                self._standing = None
                self.selectionModel().setCurrentIndex(
                    index, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.scrollTo(index)

    def reveal(self, path: str) -> None:
        """Open every folder above `path` and stand on it, as their rows arrive."""
        model = self.model()
        if not self._remembers(model) or not path:
            return
        location = model.location_of(path)
        opened = self._open.setdefault(id(model), set())
        opened.add(location)
        here = path.rstrip("/")
        while "/" in here and here != location.rstrip("/"):
            here = here.rsplit("/", 1)[0]
            if here.rstrip("/") == location.rstrip("/"):
                break
            opened.add(here)
        self._standing = (model, path)
        self._reopen()


class SidebarReorder(QtCore.QObject):
    """Press-hold row reorder; asks the Section, owns only the state machine. ▸r/press-gestures"""

    EDGE_SCROLL_MARGIN = 16

    def __init__(self, panel):
        view = panel.cat_list
        super().__init__(view)
        self._panel = panel
        self._clear()
        self._hold_timer = QtCore.QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(self._hold_fired)
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

    def reordering(self) -> bool:
        return self._reordering

    def _clear(self) -> None:
        """The blank slate: no press, no grab, no snapshot, nothing moved."""
        self._pressed_pos = None
        self._grabbed = None
        self._snapshot = None
        self._changed = False
        self._reordering = False

    def _reset(self) -> None:
        """The blank slate again, and the cursor goes back with it."""
        self._hold_timer.stop()
        was_reordering = self._reordering
        self._clear()
        if was_reordering:
            view = self._panel.cat_list
            if view is not None:
                view.viewport().unsetCursor()

    def _section(self):
        section = self._panel._section()
        if section is None or not getattr(section, "reorders_sidebar",
                                          False):
            return None
        return section

    @debug.guarded("SidebarReorder.eventFilter")
    def eventFilter(self, watched, event):
        etype = event.type()
        if etype == QtCore.QEvent.Type.MouseButtonPress:
            return self._on_press(event)
        if etype == QtCore.QEvent.Type.MouseMove:
            return self._on_move(event)
        if etype == QtCore.QEvent.Type.MouseButtonRelease:
            return self._on_release(event)
        if (etype == QtCore.QEvent.Type.KeyPress
                and self._reordering
                and event.key() == QtCore.Qt.Key.Key_Escape):
            self._abort()
            return True
        return False

    def _on_press(self, event) -> bool:
        self._reset()
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        section = self._section()
        view = self._panel.cat_list
        if section is None or view is None:
            return False
        pos = event.position().toPoint()
        index = view.indexAt(pos)
        if not section.sidebar_movable(index):
            return False
        self._pressed_pos = pos
        self._grabbed = QtCore.QPersistentModelIndex(
            view.model().index(index.row(), 0))
        # Re-read per press: the platform owns this number, not us.
        self._hold_timer.setInterval(
            QtWidgets.QApplication.startDragTime())
        self._hold_timer.start()
        return False

    @debug.guarded("SidebarReorder._hold_fired")
    def _hold_fired(self) -> None:
        if self._reordering or self._pressed_pos is None:
            return
        section = self._section()
        view = self._panel.cat_list
        if (section is None or view is None
                or self._grabbed is None or not self._grabbed.isValid()):
            self._reset()
            return
        self._snapshot = section.sidebar_order_snapshot()
        self._reordering = True
        view.viewport().setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)

    def _on_move(self, event) -> bool:
        if self._reordering:
            self._follow(event.position().toPoint())
            return True
        if self._hold_timer.isActive() and self._pressed_pos is not None:
            moved = (event.position().toPoint()
                     - self._pressed_pos).manhattanLength()
            if moved >= QtWidgets.QApplication.startDragDistance():
                # It was a click (or an idle wiggle), not a hold.
                self._reset()
        return False

    def _follow(self, pos) -> None:
        """The grabbed row goes to the row under the clamped cursor. ▸r/press-gestures"""
        section = self._section()
        view = self._panel.cat_list
        if (section is None or view is None
                or self._grabbed is None or not self._grabbed.isValid()):
            self._abort()
            return
        area = view.viewport().rect()
        clamped = QtCore.QPoint(
            min(max(pos.x(), area.left()), area.right()),
            min(max(pos.y(), area.top()), area.bottom()))
        if pos.y() < area.top() + self.EDGE_SCROLL_MARGIN:
            bar = view.verticalScrollBar()
            bar.setValue(bar.value() - bar.singleStep())
        elif pos.y() > area.bottom() - self.EDGE_SCROLL_MARGIN:
            bar = view.verticalScrollBar()
            bar.setValue(bar.value() + bar.singleStep())
        target = top_level(view.indexAt(clamped))    # over a subfolder, its location's row
        if not target.isValid():
            return
        to_row = max(1, target.row())
        if to_row == self._grabbed.row():
            return
        if section.move_sidebar_row(
                QtCore.QModelIndex(self._grabbed), to_row):
            self._changed = True

    def _on_release(self, event) -> bool:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        if self._reordering:
            section = self._section()
            changed = self._changed
            self._reset()
            if changed and section is not None:
                section.commit_sidebar_order()
        else:
            self._reset()
        # Passed through: the row under the hand IS the grabbed row.
        return False

    def _abort(self) -> None:
        """Esc, or the world moved under the gesture: put the order back, and the grid's row."""
        section = self._section()
        snapshot = self._snapshot
        self._reset()
        if section is None:
            return
        if snapshot is not None:
            section.restore_sidebar_order(snapshot)    # a reset, which clears the highlight
        section.stand_again()


def droppable_index(panel, pos):
    """THE ONE PLACE the drop-target rules live; None if no tile may land here."""
    context = panel._section()
    if context is None or not (context.takes_category_drops or context.takes_file_drops):
        return None
    if panel.cat_list is None:
        return None
    index = panel.cat_list.indexAt(pos)
    if not index.isValid():
        return None
    if context.takes_file_drops:    # a folder row: the tile's file moves there, on disk
        return index if context.accepts_file_drop(index) else None
    name = panel._raw_category_name(index)
    if not name or category.is_all(name):
        return None
    if not context.accepts_category_drop(index, name):
        return None
    return index


def category_at_point(panel, pos):
    """The droppable category at a point, by its STORED name - the form the write needs."""
    context = panel._section()
    if context is None or not context.takes_category_drops:
        return None
    index = droppable_index(panel, pos)
    return None if index is None else panel._raw_category_name(index)


def folder_at_point(panel, pos):
    """The folder a tile dropped at a point moves into, or None."""
    context = panel._section()
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
    """The assignable category under the GLOBAL cursor - every self-managed release asks first."""
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
    held = (QtCore.QPersistentModelIndex(row) if isinstance(row, QtCore.QModelIndex)
            else QtCore.QPersistentModelIndex())
    if held == delegate.drag_index:
        return
    delegate.drag_index = held
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


def can_drop(panel, event) -> bool:
    """Only OUR OWN grid, only into a context that takes drops - the rest falls through."""
    context = panel._section()
    return bool(context is not None
                and (context.takes_category_drops or context.takes_file_drops)
                and event.source() is panel.thumblist)


def handle_drop(panel, event) -> bool:
    """Recategorise on a category, move the files on a folder; CONSUME the drop either way."""
    if not can_drop(panel, event):
        return False
    pos = event.position().toPoint()
    folder = folder_at_point(panel, pos)
    if folder is not None:
        panel.move_files_active(folder)
        return True
    category = category_at_point(panel, pos)
    if category is not None:
        panel.assign_category_active(category)
    return True
