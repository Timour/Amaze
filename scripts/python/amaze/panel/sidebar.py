"""The Sidebar: what a row MEANS, and what may be dropped on it. ▸o/section-api"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import debug


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
        target = view.indexAt(clamped)
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
        """Esc, or the world moved under the gesture: put the order back."""
        section = self._section()
        snapshot = self._snapshot
        self._reset()
        if section is not None and snapshot is not None:
            section.restore_sidebar_order(snapshot)


def droppable_index(panel, pos):
    """THE ONE PLACE the drop-target rules live; None if no tile may land here."""
    context = panel._section()
    if context is None or not context.takes_category_drops:
        return None
    if panel.cat_list is None:
        return None
    index = panel.cat_list.indexAt(pos)
    if not index.isValid():
        return None
    name = panel._raw_category_name(index)
    if not name or name in ("All", "_All"):
        return None
    if not context.accepts_category_drop(index, name):
        return None
    return index


def category_at_point(panel, pos):
    """The droppable category at a point, by its STORED name - the form the write needs."""
    index = droppable_index(panel, pos)
    return None if index is None else panel._raw_category_name(index)


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


def set_hover_row(panel, row: int) -> None:
    """Highlight a row (-1 clears); `repaint()`, never `update()`. ▸r/native-drag-paint"""
    delegate = getattr(panel, "sidebar_delegate", None)
    if delegate is None or delegate.drag_row == row:
        return
    delegate.drag_row = row
    if panel.cat_list is not None:
        panel.cat_list.viewport().repaint()


def update_hover(panel, pos) -> None:
    """Set the highlight from a sidebar-local point."""
    index = droppable_index(panel, pos)
    set_hover_row(panel, index.row() if index is not None else -1)


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
                and context.takes_category_drops
                and event.source() is panel.thumblist)


def handle_drop(panel, event) -> bool:
    """Recategorise if it landed on a real category; CONSUME the drop either way."""
    if not can_drop(panel, event):
        return False
    category = category_at_point(panel, event.position().toPoint())
    if category is not None:
        panel.assign_category_active(category)
    return True
