"""Drag and drop between the panel's views and Houdini. ▸o/section-api"""

from PySide6 import QtWidgets, QtGui, QtCore
import hou

from amaze.core import debug
from amaze.helpers import helpers, theme
from amaze.helpers import ui_helpers
from amaze.panel import sections
from amaze.render import cop_nodes


def _find_panel(widget: QtWidgets.QWidget):
    """The panel above `widget`, or None; found by capability, never by a fixed parent depth."""
    w = widget.parentWidget()
    while w is not None:
        if hasattr(w, "import_asset"):
            return w
        w = w.parentWidget()
    return None


class GridGestureMixin:
    """The self-managed drag gesture, mixed into both views. ▸r/pick-boundary ▸r/native-drag-paint"""

    DRAG_SECTIONS = ("material", "gradient", "cop", "code", "file")    #: every section whose rows can start a drag; drop behaviour is per section (sections.DropRule)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        self._drag_start = None    # None whenever no left-button press is in progress
        self._drag_section = None
        self._drag_index = None
        self._drag_panel = None    # cached at press, so the gesture never re-walks the widget tree per move
        self._dragging = False
        self._preview = None
        super().__init__(parent)

    SCROLL_SPEED = 0.75    #: fallback only, used when no panel/prefs is reachable
    INDICATOR_MS = 167    #: how long an outcome icon stays on screen (ms) ▸r/qt-windows-macos
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
        prefs = getattr(panel, "prefs", None) if panel is not None else None
        speed = getattr(prefs, "scroll_speed", None) or self.SCROLL_SPEED
        bar = (self.horizontalScrollBar() if horizontal
               else self.verticalScrollBar())
        before = bar.value()
        bar.setValue(before - round(delta * speed))
        self._log_scroll_geometry(panel, bar, before, delta)
        event.accept()

    SCROLL_DIAG_LIMIT = 12    #: how many scroll diagnostics one session may write (never a flood)

    def _log_scroll_geometry(self, panel, bar, before, delta) -> None:
        """Log the geometry a scroll sees, in Debug Mode, at most SCROLL_DIAG_LIMIT times a session."""
        if not debug.is_on():
            return
        if getattr(panel, "prefs", None) is None or \
                panel.prefs.view_mode != "list":
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
        if self._dragging:
            event.accept()    # a stray right/middle press mid-gesture must not clear live drag state
            return
        panel = _find_panel(self)
        section = (
            getattr(panel, "current_section", None) if panel is not None else None
        )
        online = bool(panel is not None and panel._is_online())    # an online row is a catalogue entry with no node and no file
        point = event.position().toPoint()    # whole pixels, converted once: everything downstream is integer geometry
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and not online
            and section in self.DRAG_SECTIONS
            and self.indexAt(point).isValid()    # only over a real item
        ):
            self._drag_start = point
            self._drag_section = section
            self._drag_index = QtCore.QPersistentModelIndex(    # THE ROW, not the cell ▸r/row-selection
                self.indexAt(point).siblingAtColumn(0))    # persistent: it stays valid across a model reset
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
        """Update the drag; a File row over a Parameters pane becomes a QDrag. ▸r/pick-boundary"""
        if self._drag_start is not None:
            moved = (event.position().toPoint()
                     - self._drag_start).manhattanLength()
            if not self._dragging and moved >= (
                QtWidgets.QApplication.startDragDistance()
            ):
                self._begin_drag()
            if self._dragging:
                from amaze.core import dragengine
                if self._switch_to_qdrag_over_parm_pane():
                    return
                self._move_preview()
                if self._drag_panel is not None:    # drop-target feedback is driven from the cursor position
                    pane_tab, pane_kind, _fresh = (    # one pane lookup per move, shared by every call below ▸p/drag-move-cost
                        dragengine.pane_under_cursor_tracked())
                    self._drag_panel._update_category_drag_hover_global()
                    dragengine.hover_update(
                        self._drag_panel, self._drag_section,
                        pane_tab, pane_kind
                    )
                    self._update_drop_outline(self._drag_panel, pane_tab,
                                              pane_kind)    # the outline, cleared by dragengine.end() on every exit path
            return
        super().mouseMoveEvent(event)

    def _overlay_label(self, text: str = "") -> QtWidgets.QLabel:
        """Frameless, always-on-top, click-through label - the shared window setup for cursor overlays."""
        label = QtWidgets.QLabel(text)
        label.setWindowFlags(    # WindowTransparentForInput is the OS-level click-through ▸r/qt-windows-macos
            QtCore.Qt.WindowType.ToolTip
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
            | QtCore.Qt.WindowType.WindowTransparentForInput
        )
        label.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        label.setAttribute(    # showing the overlay never touches activation
            QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating
        )
        return label

    def _drag_row(self):
        """The pressed row as an index, None once it was removed from the model during the drag."""
        row = self._drag_index
        if row is None or not row.isValid():
            return None
        return QtCore.QModelIndex(row)

    def _begin_drag(self) -> None:
        """Start the self-managed drag for any DRAG_SECTIONS row: a name tag following the cursor."""
        from amaze.core import dragengine
        self._dragging = True
        dragengine.begin(self._drag_section or "")
        name = ""
        index = self._drag_row()
        if index is not None:
            name = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        label = self._overlay_label(str(name))
        label.setStyleSheet(ui_helpers.DRAG_TAG_STYLE)    # shared with the native drags' pixmap, so every drag tag looks identical
        label.adjustSize()
        self._preview = label
        self._move_preview()
        label.show()

    def _move_preview(self) -> None:
        if self._preview is not None:
            pos = QtGui.QCursor.pos()
            self._preview.move(    # below-right of the cursor, where the native file-drag tag sits
                pos.x() + theme.ui_px(12), pos.y() + theme.ui_px(14)
            )

    def _finish_preview(self, outcome) -> None:
        """Remove the name tag at once; a failed drop also shows a red X at the cursor."""
        preview = self._preview
        self._preview = None
        if preview is not None:
            preview.hide()
            preview.close()
            preview.deleteLater()
        if not outcome:
            self._show_drop_indicator("icon_drop_miss.svg", "#ff3319")

    def _show_drop_indicator(self, icon_file: str, color: str) -> None:
        """Show the drop outcome as a small icon at the cursor for INDICATOR_MS."""
        panel = self._drag_panel
        if panel is None:
            return
        path = panel._ui_icon_path(icon_file)
        size = theme.ui_px(22)
        pm = ui_helpers.render_svg_pixmap(
            path, size, {"currentColor": color}
        )
        if pm.isNull():
            return
        label = getattr(self, "_indicator_label", None)    # one persistent window per view, reused for every drop
        if label is None:
            label = self._overlay_label()
            label.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_TranslucentBackground
            )
            self._indicator_label = label
        label.setPixmap(pm)
        label.adjustSize()
        pos = QtGui.QCursor.pos()
        label.move(pos.x() - size // 2, pos.y() - size // 2)
        label.show()

        import time as _time    # the serial stops a stale timer hiding a newer drop's icon
        shown_at = _time.time()
        self._indicator_serial = getattr(self, "_indicator_serial", 0) + 1
        my_serial = self._indicator_serial

        def _done(w=label):
            if self._indicator_serial != my_serial:
                return
            debug.event(
                "drag", "indicator hidden",
                shown_ms=round((_time.time() - shown_at) * 1000),
            )
            try:
                w.clear()
                w.hide()
            except RuntimeError:
                pass

        QtCore.QTimer.singleShot(self.INDICATOR_MS, _done)

    def _switch_to_qdrag_over_parm_pane(self) -> bool:
        """Switch a File row drag over a Parameters pane to a real QDrag; Qt then runs the drag."""
        from amaze.core import dragengine
        if self._drag_section != "file":
            return False
        ui = getattr(hou, "ui", None)
        if ui is None:
            return False
        try:
            pane = ui.paneTabUnderCursor()
        except AttributeError:
            return False
        if pane is None or pane.type() != hou.paneTabType.Parm:
            return False
        self._finish_preview(True)    # a switch to QDrag, not a failed drop: remove the tag, no red X
        self._dragging = False
        self._drag_start = None
        dragengine.end()
        if self._drag_panel is not None:
            self._drag_panel._set_drag_hover_row(-1)
        self._run_file_path_drag()
        return True

    @staticmethod
    def _file_drag_mime(panel, path: str) -> QtCore.QMimeData:
        """File-path drag mime: the path per Write Paths As as text, no URL. ▸r/drag-file-url"""
        mime_data = QtCore.QMimeData()
        mime_data.setText(helpers.houdini_path(
            path, getattr(panel.prefs, "path_style", "home")))
        return mime_data

    def _run_file_path_drag(self) -> None:
        """The only real `QDrag`: `_file_drag_mime` with the shared name-tag pixmap."""
        index = self._drag_row()    # the PRESSED row: currentIndex() can name another
        if index is None:
            return
        panel = _find_panel(self)
        if panel is None:
            return
        path = index.data(panel.file_files_model.PathRole)
        if not path:
            return
        drag = QtGui.QDrag(self)
        drag.setMimeData(self._file_drag_mime(panel, path))
        name = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        drag.setPixmap(ui_helpers.name_tag_pixmap(name))
        drag.exec(QtCore.Qt.DropAction.CopyAction)

    @debug.guarded("DragDropListView.mouseReleaseEvent")
    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        try:
            self._release(event)
        finally:    # `guarded()` re-raises, so the press state is cleared here
            self._drag_start = None
            self._drag_section = None
            self._drag_panel = None
            self._drag_index = None
        super().mouseReleaseEvent(event)

    def _release(self, event: QtGui.QMouseEvent) -> None:
        from amaze.core import dragengine
        from amaze.helpers import helpers
        if self._dragging and event.button() != QtCore.Qt.MouseButton.LeftButton:    # a right or middle release mid-drag cancels the drag and removes the tag
            if self._preview is not None:
                self._preview.hide()
            self._dragging = False
            dragengine.end()
            if self._drag_panel is not None:
                self._drag_panel._set_drag_hover_row(-1)
            self._finish_preview(False)
            event.accept()
            return
        if self._dragging:
            if self._preview is not None:
                self._preview.hide()    # hidden before any drop work; _finish_preview deletes it
            self._dragging = False
            dragengine.end()    # restores the hover highlight, on EVERY exit path
            panel = self._drag_panel
            idx = self._drag_row()    # None when the row was removed mid-drag: a failed drop
            if panel is not None:
                panel._set_drag_hover_row(-1)   # clear the drop-target highlight
            outcome = False
            try:
                if panel is not None and idx is not None:
                    section = self._drag_section
                    category = panel._category_under_cursor()    # the sidebar comes before a node target; None for folder sections and the All row
                    folder = None if category is not None else panel._folder_under_cursor()
                    if category is not None:
                        panel.assign_category_active(category)
                        outcome = True
                    elif folder is not None:    # File: the tiles' files move into that folder, on disk
                        outcome = panel.move_files_active(folder)
                    else:    # apply the section's DropRule; no rule or no target shows only the red X
                        rule = self._drop_rule(panel, section, idx)
                        if rule is not None:
                            helpers.forget_placed()
                            live = getattr(panel, "sections",
                                           {}).get(section)
                            with dragengine.holding_drop_group():    # one undo group: the verb, its placement and the wire insert
                                outcome = self._apply_drop_rule(
                                    rule, panel, live, idx, event)
                                if outcome:
                                    self._splice_if_on_a_wire(panel, event)
            except hou.PermissionError as refusal:    # only this class: a locked network raises it; any other error propagates
                debug.exception("drop failed - permission error", refusal,
                                section=self._drag_section)
                debug.refuse(str(refusal),    # Houdini's own message; `outcome` stays False so the red X shows ▸p/refuse-vs-alert
                             section=self._drag_section)
            finally:
                self._finish_preview(outcome)

    @staticmethod
    def _preview_node_type(panel, rule, section, dest, index=None) -> str:
        """The node type an on_space drop would create in `dest`; `""` is none: a plain box."""
        cls = sections.SECTION_INDEX.get(section)
        name = rule.holder_node_type or getattr(cls, "holder_node_type", "")
        verb = getattr(cls, "holder_node_type_method", "")
        if not name and verb and index is not None:
            try:
                live = getattr(panel, "sections", {}).get(section)
                name = sections.drop_verb(live, verb)(index, dest)
            except (AttributeError, hou.OperationFailed):
                name = ""
        return name or ""

    def _update_drop_outline(self, panel, pane_tab, pane_type) -> None:
        """Per move: outline where the node would go; pass the tracked pane. ▸p/drag-move-cost"""
        from amaze.core import dragengine
        section = self._drag_section
        idx = self._drag_row()
        if panel is None or idx is None:
            dragengine.ghost_clear()
            return
        rule = self._drop_rule(panel, section, idx)
        if rule is None:
            dragengine.ghost_clear()
            return
        preview = getattr(self, "_preview", None)
        if preview is not None:    # the cursor tag hides over a network editor, where the outline is the feedback
            preview.setVisible(
                pane_type != hou.paneTabType.NetworkEditor)
        try:
            if (pane_tab is None
                    or pane_type != hou.paneTabType.NetworkEditor):
                dragengine.ghost_clear()
                return
            if getattr(rule, "context", "") and not \
                    cop_nodes.accepts_context(pane_tab.pwd(),
                                                rule.context):    # the network does not accept this node type, so no outline is drawn
                dragengine.ghost_clear()
                return
            spot = pane_tab.cursorPosition()
            if dragengine.ghost_tick(pane_tab):
                blocked = bool(
                    rule.on_node
                    and panel._node_under_cursor(pane_tab, pane_type)
                    is not None)
                target = (None, "", -1)    # a wire under the cursor means an insert, checked only where the node can join a chain
                type_name = ""
                if not blocked:
                    if rule.on_space or rule.resolve:
                        target = dragengine.wire_under_cursor(
                            pane_tab, spot)
                    type_name = self._preview_node_type(
                        panel, rule, section, pane_tab.pwd(), idx)
                dragengine.set_ghost_tick_results(blocked, target, type_name)
                dragengine.wire_highlight(pane_tab, target)
            blocked, target, type_name = dragengine.ghost_tick_results()
            if blocked:
                dragengine.ghost_clear()    # Houdini's own node highlight shows this case
                return
            dragengine.ghost_show(pane_tab, spot, type_name,
                                  connection=target[0])
        except (AttributeError, hou.OperationFailed):
            dragengine.ghost_clear()

    @staticmethod
    def _drop_rule(panel, section, idx):
        """This row's declared drop behaviour by section key, resolved by `sections.drop_rule`."""
        return sections.drop_rule(
            sections.SECTION_INDEX.get(section), panel, idx)

    @staticmethod
    def _apply_drop_rule(rule, panel, section, idx, event) -> bool:
        """One order for every DropRule: on_node (result final), resolve, on_space ▸o/section-api"""
        if rule.on_node is not None:
            node = panel._node_under_cursor()
            if node is not None:
                apply_to_node = sections.drop_verb(section, rule.on_node)
                return bool(apply_to_node(idx, node))
        if rule.resolve is not None:
            resolve = sections.drop_verb(section, rule.resolve)
            return bool(resolve(idx))
        if rule.on_space is not None:
            net = panel.drop_placement.network_under_release()
            if net is None:
                return section.reject_drop()
            create = sections.drop_verb(section, rule.on_space)    # the position is used only when the editor under the cursor shows that network
            return bool(create(idx, net, panel.drop_placement.release_position_in(net)))
        return section.reject_drop()

    @staticmethod
    def _splice_if_on_a_wire(panel, event) -> None:
        """Insert the nodes `helpers.placed_nodes` returns into the wire under the cursor."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        placed = helpers.placed_nodes()
        if not placed:
            return
        editor = dragengine.pane_tab_under_cursor()
        net = panel.drop_placement.network_under_release()
        spot = panel.drop_placement.release_position_in(net) if net is not None else None
        wire, _name, _index = dragengine.wire_under_cursor(    # the placed nodes are excluded: they are already under the cursor
            editor, spot, exclude=placed)
        if wire is not None:
            dragengine.splice_into_wire(wire, placed, editor)
            return
        dragengine.connect_to_neighbour(    # no wire, but a lone node or the end of a chain has a connector near the cursor
            dragengine.connector_under_cursor(
                editor, spot, exclude=placed), placed, editor)


def _node_paths_from_mime(mime) -> list:
    """Node paths in a drag: node-path mime, then item-path list, then text. ▸r/drop-mime"""
    raw = ""
    for attr in ("nodePath", "itemPath"):
        try:
            fmt = getattr(hou.qt.mimeType, attr)
        except AttributeError:
            continue
        if mime.hasFormat(fmt):
            raw = bytes(mime.data(fmt)).decode("utf-8", "replace")
            if raw.strip():
                break
    if not raw.strip():
        raw = mime.text() or ""
    paths = []
    for piece in raw.replace("\r", "\t").replace("\n", "\t").split("\t"):
        piece = piece.strip()
        if piece and hou.node(piece) is not None:
            paths.append(piece)
    return paths


class DragDropCentralWidget(QtWidgets.QWidget):
    """Receives a node dragged in from a network editor and saves it to the library."""

    @debug.guarded("DragDropCentralWidget.dragEnterEvent")
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """Accept any drag carrying a resolvable node path that did not start inside the panel."""
        src = event.source()
        if src is not None and _find_panel(src) is not None:
            return
        if _node_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()

    @debug.guarded("DragDropCentralWidget.dropEvent")
    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        src = event.source()    # a drop that started in the panel is ignored, though it carries a node path
        if src is not None and _find_panel(src) is not None:
            return
        mime = event.mimeData()
        paths = _node_paths_from_mime(mime)
        debug.event(
            "save", "drop received",
            formats=[str(f) for f in mime.formats()][:8],
            text=(mime.text() or "")[:120],
            parsed=paths,
        )
        if not paths:
            return
        event.acceptProposedAction()
        nodes = [hou.node(p) for p in paths]
        with hou.undos.disabler():    # a selection is an undo entry of its own
            for i, n in enumerate(nodes):    # the dropped nodes become the selection the save reads
                n.setSelected(True, clear_all_selected=(i == 0))
        panel = _find_panel(self)
        if panel is None:
            return
        section = panel.active_section()    # deferred out of the drop, so no modal opens mid-gesture ▸r/qt-windows-macos

        @debug.guarded("dropEvent.deferred_save")
        def _route(panel=panel, section=section, node=nodes[0]):
            debug.event("save", "drop save routed",
                        node=node.path(), section=getattr(section, "key", None))
            panel.save_from_node(node, prefer=getattr(section, "key", ""))

        helpers.run_at_top_of_loop(_route, "drop save")    # a bare timer can fire during a builder's processEvents call


class CategoryDropFilter(QtCore.QObject):
    """Makes the category sidebar a drop target for drags from the grid, recategorising them."""

    def __init__(self, cat_list, panel) -> None:
        super().__init__(cat_list)
        self._list = cat_list
        self._panel = panel
        cat_list.setAcceptDrops(True)
        cat_list.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        et = event.type()
        if et in (
            QtCore.QEvent.Type.DragEnter,
            QtCore.QEvent.Type.DragMove,
        ):
            if self._panel._can_drop_category(event):
                self._panel._update_category_drag_hover(    # accent-purple highlight, so which category the drop will hit is visible
                    event.position().toPoint()
                )
                event.acceptProposedAction()
                return True
            return False
        if et == QtCore.QEvent.Type.DragLeave:
            self._panel._set_drag_hover_row(-1)
            return False
        if et == QtCore.QEvent.Type.Drop:
            handled = self._panel._handle_category_drop(event)
            self._panel._set_drag_hover_row(-1)
            if handled:
                event.acceptProposedAction()
                return True
            return False
        return False


class DragDropListView(GridGestureMixin, QtWidgets.QListView):
    """The grid: one tile per item, IconMode or ListMode."""


class DragDropTableView(GridGestureMixin, QtWidgets.QTableView):
    """List mode as a table, sharing the gesture, model, proxy and selection model with the grid."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)    # banded rows in the host stylesheet's alternate-background-color
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.verticalHeader().setVisible(False)
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
