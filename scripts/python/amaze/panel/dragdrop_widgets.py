"""Drag and drop between the panel's views and Houdini. ▸o/section-api"""

from PySide6 import QtWidgets, QtGui, QtCore
import hou

from amaze.core import cop_library, debug, dragengine, file_library
from amaze.helpers import helpers
from amaze.helpers import theme
from amaze.helpers import ui_helpers
from amaze.panel import sections


def _find_panel(widget: QtWidgets.QWidget):
    """The panel above `widget`, or None - found by capability, never by a fixed parentWidget() depth, which breaks silently every time the hierarchy is restructured."""
    w = widget.parentWidget()
    while w is not None:
        if hasattr(w, "import_asset"):
            return w
        w = w.parentWidget()
    return None


class GridGestureMixin:
    """The grid's SELF-MANAGED press-move-release gesture, a mixin over `QAbstractItemView` so grid and table share it. A real `QDrag` cannot serve: its nested run loop starves the per-move viewport picking. ▸r/pick-boundary ▸r/native-drag-paint"""

    ARMED_SECTIONS = ("material", "gradient", "cop", "code", "file")    #: every section that can arm a drag; what a RELEASE does is declared per section (sections.DropRule) and walked by _apply_drop_rule

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        self._drag_start = None    # None whenever no left-button press is in progress
        self._drag_section = None
        self._drag_index = None
        self._drag_panel = None    # cached at press, so the gesture never re-walks the widget tree per move
        self._dragging = False
        self._preview = None
        super().__init__(parent)

    SCROLL_SPEED = 0.75    #: fallback only, used when no panel/prefs is reachable; Qt's own wheel handling overshoots here so pixel deltas are applied by hand
    INDICATOR_MS = 167    #: how long an outcome icon stays on screen (ms) ▸r/qt-windows-macos
    WHEEL_NOTCH_PX = theme.ui_px(60)    #: classic wheel px per notch, through the UI scale so a notch moves the same VISUAL distance on scaled displays

    @debug.guarded("DragDropListView.wheelEvent")
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """One scroll engine, both axes - the axis is only a choice of scrollbar, so the pixel deltas, notch conversion and `scroll_speed` read are shared rather than reimplemented."""
        pixels = event.pixelDelta()
        angle = event.angleDelta()
        horizontal = abs(pixels.x()) > abs(pixels.y()) if (    # a trackpad reports both axes so the dominant one wins; a classic wheel reports only one
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
        """Record the geometry a scroll actually sees - list mode, Debug Mode, at most SCROLL_DIAG_LIMIT times a session. Every view-only call in it MUST be `hasattr`-guarded: the body sits inside a bare `except`, so on a table an AttributeError silently produces no diagnostic at all."""
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
            grid = (self.gridSize() if hasattr(self, "gridSize")    # QListView-only, like uniformItemSizes below: a table has neither, and both guards are load-bearing
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
                content_h=self.contentsRect().height(),    # what the view believes it scrolls through, against what the rows add up to
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
        online = bool(panel is not None and panel._is_online())    # an online row is a catalogue entry with no node and no file, and arming here drags whichever LOCAL asset sits at that row
        point = event.position().toPoint()    # WHOLE PIXELS, converted once and kept: `position()` answers a QPointF, while `indexAt`, the stored start point and the threshold in `mouseMoveEvent` are all integer geometry - a QPointF reaching them makes the drag arm at a different distance
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and not online
            and section in self.ARMED_SECTIONS
            and self.indexAt(point).isValid()    # only over a real item: empty grid space armed a ghost drag whose invalid index reached the release handlers
        ):
            self._drag_start = point
            self._drag_section = section
            self._drag_index = self.indexAt(point).siblingAtColumn(0)    # THE ROW, not the pressed cell: in list mode a cell >= 1 answers None for KindRole/PathRole ▸r/row-selection
            self._drag_panel = panel
        else:
            self._drag_start = None
            self._drag_section = None
            self._drag_index = None
            self._drag_panel = None
        super().mousePressEvent(event)

    @debug.guarded("DragDropListView.mouseMoveEvent")
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """The gesture stays in our hands so WE resolve the target at release; a File row crossing a Parameters pane hands off to a real QDrag, because only mime fills a field. Never call super() during the gesture, even before the threshold - that lets the view fall back to rubber-band selection. ▸r/pick-boundary"""
        if self._drag_start is not None:
            moved = (event.position().toPoint()
                     - self._drag_start).manhattanLength()
            if not self._dragging and moved >= (
                QtWidgets.QApplication.startDragDistance()
            ):
                self._begin_drag()
            if self._dragging:
                if self._promote_to_field_drag():
                    return
                self._move_preview()
                if self._drag_panel is not None:    # a self-managed gesture has no Qt drag events, so the drop-target feedback is driven from the cursor position
                    pane_tab, pane_kind, _fresh = (    # ONE tracked pane answer per move for every consumer below - the raw lookup measured ~3ms under drag load ▸p/drag-move-cost
                        dragengine.pane_under_cursor_tracked())
                    self._drag_panel._update_category_drag_hover_global()
                    dragengine.hover_update(
                        self._drag_panel, self._drag_section,
                        pane_tab, pane_kind
                    )
                    self._ghost_update(self._drag_panel, pane_tab,
                                       pane_kind)    # the outline, cleared by dragengine.end() on every exit path including the leave the host treats as a suspend
            return
        super().mouseMoveEvent(event)

    def _overlay_label(self, text: str = "") -> QtWidgets.QLabel:
        """Frameless, always-on-top, click-through label - the shared window setup for cursor overlays."""
        label = QtWidgets.QLabel(text)
        label.setWindowFlags(    # WindowTransparentForInput is the OS-level click-through; WA_TransparentForMouseEvents below is Qt routing only and does not cover a topmost native window under the cursor ▸r/qt-windows-macos
            QtCore.Qt.WindowType.ToolTip
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
            | QtCore.Qt.WindowType.WindowTransparentForInput
        )
        label.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        label.setAttribute(    # showing an overlay must never touch activation: on macOS an activating show()/close() over the viewport churned focus at release and flickered the selector prompt
            QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating
        )
        return label

    def _begin_drag(self) -> None:
        """Start the shared self-managed drag: a floating name tag following the cursor, one gesture for every ARMED_SECTIONS row, File included - a File row only leaves it if the cursor later crosses a Parameters pane."""
        self._dragging = True
        dragengine.begin(self._drag_section or "")
        name = ""
        if self._drag_index is not None and self._drag_index.isValid():
            name = (
                self._drag_index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
            )
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
        """Tag teardown by outcome: the tag ALWAYS goes instantly, a MISS adds a red X at the cursor, and a landed drop shows nothing because the result in the scene is its own feedback."""
        preview = self._preview
        self._preview = None
        if preview is not None:
            preview.hide()
            preview.close()
            preview.deleteLater()
        if not outcome:
            self._show_drop_indicator("icon_drop_miss.svg", "#ff3319")

    def _show_drop_indicator(self, icon_file: str, color: str) -> None:
        """A small icon at the cursor for INDICATOR_MS - the drop outcome, announced where the user is looking."""
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
        label = getattr(self, "_indicator_label", None)    # ONE persistent window per view: building and destroying a native window per drop was itself a visible hitch at release
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

        import time as _time    # no fade by design: full opacity for INDICATOR_MS then hidden, never destroyed; the serial stops a stale timer cutting short a NEWER drop's icon
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

    def _promote_to_field_drag(self) -> bool:
        """The parameter-field hand-off: a FILE row crossing into a Parameters pane becomes the one real QDrag, because only mime fills a field. After it the drag is Qt's, so a release back over a network editor gets Houdini's stock answer. It is a hand-off and not a miss, so the tag goes quietly and no indicator is shown."""
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
        preview = self._preview
        self._preview = None
        if preview is not None:
            preview.hide()
            preview.close()
            preview.deleteLater()
        self._dragging = False
        self._drag_start = None
        dragengine.end()
        if self._drag_panel is not None:
            self._drag_panel._set_drag_hover_row(-1)
        self._run_file_path_drag()
        return True

    @staticmethod
    def _file_drag_mime(panel, path: str) -> QtCore.QMimeData:
        """One mime for a file-path drag: the spelled TEXT and NOTHING else. NEVER add the URL flavour - Houdini reads a file URL as an open-this handle, so a release outside a field offered to CLEAR THE SCENE, and inside one it won over the text and filled an absolute path while Write Paths As said $HOME."""
        mime_data = QtCore.QMimeData()
        mime_data.setText(file_library.houdini_path(
            path, getattr(panel.prefs, "path_style", "home")))
        return mime_data

    def _run_file_path_drag(self) -> None:
        """The one real `QDrag`, carrying the spelled path as TEXT (`_file_drag_mime`, which is the whole mime) under the shared name-tag pixmap - "native" is the drop mechanism only, the picture stays the same everywhere."""
        index = self._drag_index    # the press-captured row: currentIndex() can point at a different one than was pressed
        if index is None or not index.isValid():
            index = self.currentIndex()
        if not index.isValid():
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
        finally:    # FINALLY, never after the try: `guarded()` re-raises, and a crashing drop that skipped this left the press state armed - the next bare hover move then launched a drag the user never began, carrying the OLD section into the wrong model
            self._drag_start = None
            self._drag_section = None
            self._drag_panel = None
            self._drag_index = None
        super().mouseReleaseEvent(event)

    def _release(self, event: QtGui.QMouseEvent) -> None:
        if self._dragging and event.button() != QtCore.Qt.MouseButton.LeftButton:    # a right/middle release mid-drag CANCELS: unfiltered, backing out performed a real import wherever the cursor was. Tear down rather than bare-return, which leaves the tag floating and the gesture live
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
                self._preview.hide()    # hidden before ANY release work, so no menu or import runs under a floating label; the widget stays alive because the outcome decides its teardown
            self._dragging = False
            dragengine.end()    # restores the hover highlight, on EVERY exit path
            panel = self._drag_panel
            idx = self._drag_index
            if panel is not None:
                panel._set_drag_hover_row(-1)   # clear the drop-target glow
            outcome = False
            keeper = helpers.preserving_selection_and_current()    # entered by hand so the refusal handler below runs BEFORE __exit__, where a `with` would restore first
            keeper.__enter__()
            try:
                if panel is not None and idx is not None:
                    section = self._drag_section
                    category = panel._category_under_cursor()    # the sidebar outranks a node target; None for folder sections and the All row
                    if category is not None:
                        panel.assign_category_active(category)
                        outcome = True
                    else:    # THE BEHAVIOUR TABLE: each section declares its doors and one walk serves them all; no rule for this row, or a release over nothing, is silent but for the miss indicator
                        rule = self._drop_rule(panel, section, idx)
                        if rule is not None:
                            helpers.forget_placed()
                            live = getattr(panel, "sections",
                                           {}).get(section)
                            outcome = self._apply_drop_rule(
                                rule, panel, live, idx, event)
                            if outcome:
                                self._splice_if_on_a_wire(panel, event)
            except hou.PermissionError as refusal:    # ONLY this class: a locked network is the app working and being told no, where any other exception is a defect that must still crash where it can be seen
                debug.exception("drop refused", refusal,
                                section=self._drag_section)
                debug.refuse(str(refusal),    # Houdini's own sentence is already a good one; `outcome` stays False so the miss indicator carries the rest ▸p/refusal-sink
                             section=self._drag_section)
            finally:
                keeper.__exit__(None, None, None)
                self._finish_preview(outcome)

    @staticmethod
    def _ghost_type(panel, rule, section, dest, index=None) -> str:
        """WHICH carrier the space door would create in `dest`, read from the declaration the creator itself builds from so the outline cannot promise a node the drop would not make; "" is no carrier and draws a plain box. `index` is HANDED IN - it lives on the gesture widget, never on the panel, and reading it off the panel raised into the except below on every drag."""
        cls = sections.SECTION_INDEX.get(section)
        name = rule.carrier_type or getattr(cls, "carrier_type", "")
        verb = getattr(cls, "carrier_type_verb", "")
        if not name and verb and index is not None:
            try:
                live = getattr(panel, "sections", {}).get(section)
                name = sections.drop_verb(live, verb)(index, dest)
            except (AttributeError, hou.OperationFailed):
                name = ""
        return name or ""

    def _ghost_update(self, panel, pane_tab, pane_type) -> None:
        """Per move: the outline where the payload would land, asking the SAME questions the release will, so what is drawn is what will happen - the pane arrives TRACKED from the caller, the outline's POSITION follows every move, and the target questions run on the engine's tick (a full per-move resolution saturated the loop at the mouse's own rate, ▸p/drag-move-cost). Over a node the editor's own drop-target highlight owns it and no ghost is drawn. ▸r/node-graph"""
        section = self._drag_section
        idx = self._drag_index
        if panel is None or idx is None:
            return
        rule = self._drop_rule(panel, section, idx)
        if rule is None:
            dragengine.ghost_clear()
            return
        preview = getattr(self, "_preview", None)
        if preview is not None:
            preview.setVisible(
                pane_type != hou.paneTabType.NetworkEditor)
        try:
            if (pane_tab is None
                    or pane_type != hou.paneTabType.NetworkEditor):
                dragengine.ghost_clear()
                return
            if getattr(rule, "context", "") and not \
                    cop_library.accepts_context(pane_tab.pwd(),
                                                rule.context):    # the network refuses this payload, so no outline promises a landing - the same declaration the release verb reads
                dragengine.ghost_clear()
                return
            spot = pane_tab.cursorPosition()
            if dragengine.ghost_tick(pane_tab):
                blocked = bool(
                    rule.on_node
                    and panel._node_under_cursor(pane_tab, pane_type)
                    is not None)
                target = (None, "", -1)    # a wire under the cursor is an INSERT, asked only where the payload could BE a link in a chain: a created carrier or an imported network
                type_name = ""
                if not blocked:
                    if rule.on_space or rule.resolve:
                        target = dragengine.wire_under_cursor(
                            pane_tab, spot)
                    type_name = self._ghost_type(
                        panel, rule, section, pane_tab.pwd(), idx)
                dragengine.set_ghost_answers(blocked, target, type_name)
                dragengine.wire_highlight(pane_tab, target)
            blocked, target, type_name = dragengine.ghost_answers()
            if blocked:
                dragengine.ghost_clear()    # the host's own highlight owns this case
                return
            dragengine.ghost_show(pane_tab, spot, type_name,
                                  connection=target[0])
        except (AttributeError, hou.OperationFailed):
            dragengine.ghost_clear()

    @staticmethod
    def _drop_rule(panel, section, idx):
        """This row's declared behaviour, by section KEY - only the key-to-class lookup lives here, the resolution being `sections.drop_rule`, which the click walker reads too."""
        return sections.drop_rule(
            sections.SECTION_INDEX.get(section), panel, idx)

    @staticmethod
    def _apply_drop_rule(rule, panel, section, idx, event) -> bool:
        """ONE precedence for every section, fixed here and nowhere else: `on_node` (whose refusal is FINAL, never a fallback) then `outside` then `resolve` then `on_space`, a door that does not apply falling through and no door left answering False. `section` is the LIVE instance, verbs resolving through `sections.drop_verb` so this door and the click door cannot drift. ▸o/section-api"""
        if rule.on_node is not None:
            node = panel._node_under_cursor()
            if node is not None:
                take = sections.drop_verb(section, rule.on_node)
                return bool(take(idx, node))
        if rule.outside is not None:
            global_pos = event.globalPosition().toPoint()
            local = panel.mapFromGlobal(global_pos)
            if not panel.rect().contains(local):
                sections.drop_verb(section, rule.outside)(idx)
                return True
        if rule.resolve is not None:
            aim = sections.drop_verb(section, rule.resolve)
            return bool(aim(idx))
        if rule.on_space is not None:
            net = panel._network_under_release()
            if net is None:
                return False
            create = sections.drop_verb(section, rule.on_space)    # the position is GATED: coordinates cross into the destination only when the release editor is showing that network itself
            return bool(create(idx, net, panel._release_position_in(net)))
        return False

    @staticmethod
    def _splice_if_on_a_wire(panel, event) -> None:
        """A release over a WIRE inserts what landed into that chain, read from the placement funnel (`helpers.place_nodes`/`auto_place`) rather than a diff of the network's children, so one question answers for every door including ones added later."""
        landed = helpers.placed_nodes()
        if not landed:
            return
        editor = dragengine.pane_tab_under_cursor()
        net = panel._network_under_release()
        spot = panel._release_position_in(net) if net is not None else None
        wire, _name, _index = dragengine.wire_under_cursor(    # WHAT LANDED IS NEVER ITS OWN TARGET: it is placed before either question is asked, so it sits under the cursor and would answer about itself
            editor, spot, exclude=landed)
        if wire is not None:
            dragengine.splice_into_wire(wire, landed, editor)
            return
        dragengine.connect_to_neighbour(    # no wire, but a lone node or the end of a chain has a connector stub within reach
            dragengine.connector_under_cursor(
                editor, spot, exclude=landed), landed, editor)


def _node_paths_from_mime(mime) -> list:
    """Node paths in a drag, tried in every format Houdini uses - node-path mime, item-path list, then text. Read text() ALONE and H21 parses to "", because only H22 populates it; multi-node drags separate with tabs/newlines."""
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
    """Receives a node dragged IN from a network editor: a drop here is a save to the library, and only that - every drag OUT is a gesture on the view."""

    @debug.guarded("DragDropCentralWidget.dragEnterEvent")
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """Accept any drag carrying a resolvable node path that did not start inside the panel. The acceptance must be EXPLICIT here: `acceptDrops` in the .ui alone gets a drop delivered on H22 and never on H21."""
        src = event.source()
        if src is not None and _find_panel(src) is not None:
            return
        if _node_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()

    @debug.guarded("DragDropCentralWidget.dropEvent")
    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        src = event.source()    # a drop that ORIGINATED in the panel is ignored: a material dragged out of our own grid also carries a valid node path, its /mat copy
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
        for i, n in enumerate(nodes):    # the dropped nodes become the selection, which only Material's save_node reads (it routes to save_asset); the other sections act on the ONE node handed to them
            n.setSelected(True, clear_all_selected=(i == 0))
        panel = _find_panel(self)
        if panel is None:
            return
        section = panel._section()    # DEFERRED out of the drop: a modal opened while the native gesture is completing takes the drag's own release on its default button ▸r/qt-windows-macos

        @debug.guarded("dropEvent.deferred_save")
        def _route(panel=panel, section=section, node=nodes[0]):
            debug.event("save", "drop save routed",
                        node=node.path(), section=getattr(section, "key", None))
            if section is None:
                panel.save_asset()
            else:
                section.save_node(node)

        QtCore.QTimer.singleShot(0, _route)


class CategoryDropFilter(QtCore.QObject):
    """Makes the category sidebar a DROP TARGET, recategorising what lands on it. It accepts only drags that started in our own grid, so a node dragged in from Houdini still reaches the save handler, and it consumes the drop so that handler never sees this one."""

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
    """The GRID: one tile per item, IconMode or ListMode. Kept as its own name because every caller, test and `.ui` refers to it."""


class DragDropTableView(GridGestureMixin, QtWidgets.QTableView):
    """LIST MODE as a real table, sharing the gesture AND the model, proxy and selection model with the grid - two views over one selection is what keeps this from doubling every area binding. It inherits the host stylesheet rather than styling itself."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)    # banded rows in the HOST's colour: Houdini's sheet carries alternate-background-color and Qt only uses it when the view asks
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(    # said rather than inherited: QTableView defaults to Extended where QListView defaults to Single, and the two views must not differ
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setAutoScroll(False)    # SELECTING A TILE MUST NEVER MOVE THE GRID: autoScroll defaults ON and re-scrolls on every currentChanged, so clicking a half-cut row jumped the view under the cursor
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
