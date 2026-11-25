"""Drag and drop between the panel's views and Houdini. ▸o/section-api"""

from PySide6 import QtWidgets, QtGui, QtCore

from amaze.core import debug
from amaze.helpers import theme
from amaze.helpers import ui_helpers
from amaze.pane import drag_session, node_drop


def _find_panel(widget: QtWidgets.QWidget):
    """The panel above `widget`, or None; found by capability, never by a fixed parent depth."""
    w = widget.parentWidget()
    while w is not None:
        if hasattr(w, "import_asset_auto"):    # the tile double-click every panel handles
            return w
        w = w.parentWidget()
    return None


class GridGestureMixin:
    """The press that starts a drag, mixed into both views; the drag is the view's `drag_session`."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        self._drag_start = None    # None whenever no left press may still start a drag
        self._drag_section = None
        self._drag_index = None
        self._drag_panel = None    # cached at press, so the gesture never re-walks the widget tree per move
        self._ended_early = False    # the left press whose drag Esc, another button or an error ended: its moves go nowhere
        self.drag = drag_session.DragSession(self, ui_helpers.DragMarks())
        super().__init__(parent)

    WHEEL_NOTCH_PX = theme.ui_px(60)    #: classic wheel px per notch, through the UI scale

    @debug.guarded("DragDropListView.wheelEvent")
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """One scroll code path for both axes; the axis only selects the scrollbar."""
        pixels = event.pixelDelta()
        angle = event.angleDelta()
        horizontal = abs(pixels.x()) > abs(pixels.y()) if (    # a trackpad reports both axes so the larger one is used; a classic wheel reports only one
            pixels.x() or pixels.y()) else abs(angle.x()) > abs(angle.y())
        delta = pixels.x() if horizontal else pixels.y()
        if delta == 0:
            raw = angle.x() if horizontal else angle.y()    # classic wheel: no pixel data, only 120-unit notches
            delta = raw / 120.0 * self.WHEEL_NOTCH_PX
        if delta == 0:
            super().wheelEvent(event)
            return
        panel = getattr(self, "_wheel_panel", None)    # cached: a trackpad delivers 60-120 events a second and the panel does not move between them
        if panel is None:
            panel = _find_panel(self)
            self._wheel_panel = panel
        bar = (self.horizontalScrollBar() if horizontal
               else self.verticalScrollBar())
        before = bar.value()
        bar.setValue(before - round(delta))    # the system's own distance, as Qt's views take it
        self._log_scroll_geometry(panel, bar, before, delta)
        event.accept()

    SCROLL_DIAG_LIMIT = 12    #: how many scroll diagnostics one session may write (never a flood)

    def _log_scroll_geometry(self, panel, bar, before, delta) -> None:
        """Log the geometry a scroll sees, in Debug Mode, at most SCROLL_DIAG_LIMIT times a session."""
        if not debug.is_on():
            return
        if panel is None or panel.pane.prefs.view_mode != "list":
            return
        seen = getattr(self, "_scroll_diag_count", 0)
        if seen >= self.SCROLL_DIAG_LIMIT:
            return
        self._scroll_diag_count = seen + 1
        try:
            model = self.model()
            grid = (self.gridSize() if hasattr(self, "gridSize")    # QListView-only, like uniformItemSizes below: a table has neither, so both checks are needed
                    else QtCore.QSize())
            rows = model.rowCount() if model is not None else 0
            debug.event(
                "list", "scroll geometry",
                n=self._scroll_diag_count,
                delta=round(float(delta), 1),
                value_before=before, value_after=bar.value(),
                range_max=bar.maximum(), page_step=bar.pageStep(),
                rows=rows,
                grid=[grid.width(), grid.height()],
                viewport=[self.viewport().width(), self.viewport().height()],
                content_h=self.contentsRect().height(),    # the view's content height, to compare with the rows' total height below
                expected_h=rows * grid.height() if grid.height() else 0,
                uniform=(self.uniformItemSizes()
                         if hasattr(self, "uniformItemSizes") else None),
            )
        except Exception:
            pass

    @debug.guarded("DragDropListView.mousePressEvent")
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if self.drag.running:
            event.accept()    # a stray right/middle press mid-gesture must not clear live drag state
            return
        self._ended_early = False
        panel = _find_panel(self)
        section = panel.pane.current_section if panel is not None else None
        point = event.position().toPoint()    # whole pixels, converted once: everything downstream is integer geometry
        index = self.indexAt(point)
        if (event.button() == QtCore.Qt.MouseButton.LeftButton and panel is not None
                and drag_session.drags(panel.pane, section) and index.isValid()):    # only over a real item
            self._drag_start = point
            self._drag_section = section
            self._drag_index = QtCore.QPersistentModelIndex(index.siblingAtColumn(0))    # THE ROW ▸r/row-selection
            self._drag_panel = panel
        else:
            self._drag_start = None
            self._drag_section = None
            self._drag_index = None
            self._drag_panel = None
        super().mousePressEvent(event)

    @debug.guarded("DragDropListView.mouseDoubleClickEvent")
    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        """On a button badge a double-click is a second press, as a Qt button takes it ▸r/item-double-click"""
        point = event.position().toPoint()
        index = self.indexAt(point)
        delegate = self.itemDelegate()
        if (index.isValid() and hasattr(delegate, "button_badge_at")
                and delegate.button_badge_at(index, self.visualRect(index), point) is not None):
            self.mousePressEvent(event)
            return
        super().mouseDoubleClickEvent(event)

    @debug.guarded("DragDropListView.mouseMoveEvent")
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """Past the drag distance the press begins a drag, which then takes every move. ▸r/pick-boundary"""
        if self._ended_early:
            if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
                event.accept()    # Qt still holds the press: a move it saw would start its own drag of the tile
                return
            self._ended_early = False
        if self.drag.running:
            self._follow_drag()
            return
        if self._drag_start is not None:
            moved = (event.position().toPoint() - self._drag_start).manhattanLength()
            if moved >= QtWidgets.QApplication.startDragDistance():
                self._begin_drag()
                self._follow_drag()
            return
        super().mouseMoveEvent(event)

    def _begin_drag(self) -> None:
        """The pressed row's drag begins; this press starts no other."""
        panel, row = self._drag_panel, self._drag_index
        self._drag_start = None
        name = row.data(QtCore.Qt.ItemDataRole.DisplayRole) if row.isValid() else ""
        self.drag.begin(panel.pane, self._drag_section, row, name, sidebar=PanelSidebar(panel))

    def _follow_drag(self) -> None:
        try:
            self.drag.move()
        except Exception:    # the drag ended itself; the guard logs it
            self._end_press_early()
            raise

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if self.drag.running and event.key() == QtCore.Qt.Key.Key_Escape:
            self.drag.cancel()
            self._end_press_early()
            event.accept()
            return
        super().keyPressEvent(event)

    def _end_press_early(self) -> None:
        """The drag ended before its release: moves while the button stays down go nowhere."""
        self._drag_start = None
        self._ended_early = True

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        self.drag.cancel()    # a view hidden or closed mid-drag gets no release
        self._end_press_early()    # nor a hover after it may start one
        super().hideEvent(event)

    @debug.guarded("DragDropListView.mouseReleaseEvent")
    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        try:
            if self.drag.running and event.button() != QtCore.Qt.MouseButton.LeftButton:    # another button ends it
                self.drag.cancel(miss=True)
                self._ended_early = True    # the left button is still down
                event.accept()
            elif self.drag.running:
                self.drag.release()
        finally:    # `guarded()` re-raises, so the press state is cleared here
            self._drag_start = None
            self._drag_section = None
            self._drag_panel = None
            self._drag_index = None
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._ended_early = False    # that press is over
        super().mouseReleaseEvent(event)


class PanelSidebar:
    """The widget panel's sidebar under the cursor, as the drag session asks for it."""

    def __init__(self, panel) -> None:
        self.panel = panel

    def hover(self) -> None:
        self.panel._update_category_drag_hover_global()

    def clear(self) -> None:
        self.panel._set_drag_hover_row(-1)

    def target(self) -> tuple:
        """(category, folder) under the cursor: a category first, None for folder sections and All."""
        category = self.panel._category_under_cursor()
        return category, (None if category is not None else self.panel._folder_under_cursor())


class DragDropCentralWidget(QtWidgets.QWidget):
    """Receives a node dragged in from a network editor and saves it to the library."""

    @debug.guarded("DragDropCentralWidget.dragEnterEvent")
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """Accept any drag carrying a resolvable node path that did not start inside the panel."""
        src = event.source()
        if src is not None and _find_panel(src) is not None:
            return
        if node_drop.node_paths(event.mimeData()):
            event.acceptProposedAction()

    @debug.guarded("DragDropCentralWidget.dropEvent")
    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        src = event.source()    # a drop that started in the panel is ignored, though it carries a node path
        if src is not None and _find_panel(src) is not None:
            return
        panel = _find_panel(self)
        if panel is not None and node_drop.save(panel.pane, event.mimeData()):
            event.acceptProposedAction()


class DragDropListView(GridGestureMixin, QtWidgets.QListView):
    """The grid: one tile per item, IconMode or ListMode."""


class DragDropRowsView(GridGestureMixin, ui_helpers.Table):
    """List mode: the app's one kind of row list with its headline shown. ▸r/one-row-list"""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)    # the table: Houdini's style paints the rows, the space under them and the headline
        self.setHeaderHidden(False)
        self.setIndentation(0)
        self.setItemsExpandable(False)
        self.setExpandsOnDoubleClick(False)
        self.setAllColumnsShowFocus(True)
        self.setWordWrap(False)
        self._row_height = 0    # 0: the cell delegates' own; else what `GridCellDelegate.sizeHint` returns
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(    # set explicitly so both views match
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setAutoScroll(False)    # selecting a row never scrolls the view
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

    def row_height(self) -> int:
        return self._row_height

    def set_row_height(self, height: int) -> None:
        """Every row is `height` px high; the view lays its rows out again."""
        if height != self._row_height:
            self._row_height = int(height)
            self.scheduleDelayedItemsLayout()
