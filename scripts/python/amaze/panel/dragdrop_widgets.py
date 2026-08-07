"""
Module For Drag and Drop Widgets handling the Drag and Drop from and to Houdini
"""

from PySide6 import QtWidgets, QtGui, QtCore
import hou

from amaze.core import debug, dragengine, file_library
from amaze.helpers import helpers
from amaze.helpers import theme
from amaze.helpers import ui_helpers
from amaze.panel import sections


def _find_panel(widget: QtWidgets.QWidget):
    """Walk up widget's parent chain to the MatLibPanel instance.

    More robust than a fixed parentWidget() depth: the panel's widget
    hierarchy has been restructured several times (menubar renderer
    filter, details-form rebuild, grid/list toggle), and a fixed-depth
    chain silently breaks - and calls a method that doesn't exist on
    whatever widget it lands on - every time that nesting changes.
    """
    w = widget.parentWidget()
    while w is not None:
        if hasattr(w, "import_asset"):
            return w
        w = w.parentWidget()
    return None


class GridGestureMixin:
    """The Grid's SELF-MANAGED press-move-release gesture.

    A mixin over `QAbstractItemView`, not a view, since 2026-08-04:
    list mode is becoming a real `QTableView` and the gesture has to
    run on both. It was written on `QListView` and touches exactly ONE
    method that base has and the table does not - `gridSize()`, in a
    debug helper, guarded below. Everything else it needs (`model`,
    `viewport`, `indexAt`) is `QAbstractItemView` API.

    Probed before the move, both views side by side: `indexAt` answers
    identically, press/move/release all reach an override rather than
    being swallowed by the view's own selection machinery, and both
    start at `dragDropMode=NoDragDrop, dragEnabled=False` - so the
    arming rules carry over unchanged (research.md).

    A real `QDrag` is NOT an option here and that is settled, not
    assumed: it traps the gesture in a nested run loop where the
    per-move viewport picking cannot run. Tried, shipped, reverted, and
    re-verified adversarially by a 59-agent research round (devlog #80).
    """

    #: Every section that can arm a drag - ALL of them, riding the one
    #: self-managed gesture (one look, one mechanism, live event loop -
    #: the Drag & Drop Engine's transport). What a RELEASE does is not
    #: written here: each section declares its doors (sections.DropRule)
    #: and _apply_drop_rule walks them in one fixed order. The one
    #: real-QDrag hand-off is a File gesture crossing a Parameters
    #: pane (_promote_to_field_drag) - a field is a Qt widget and only
    #: mime fills it.
    ARMED_SECTIONS = ("material", "gradient", "cop", "code", "file")

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        # Per-section press/drag tracking - see mousePressEvent/
        # mouseMoveEvent below. _drag_start is None whenever no such
        # left-button press is in progress. _drag_panel is cached at
        # press so the gesture never re-walks the widget tree per move.
        self._drag_start = None
        self._drag_section = None
        self._drag_index = None
        self._drag_panel = None
        # Self-managed label-drag state, shared by EVERY non-real-path
        # section (materials, cop, gradient/color, code, geometry) - one
        # gesture, one look; the release dispatches to the section's own
        # action (see mouseReleaseEvent).
        self._dragging = False
        self._preview = None
        super().__init__(parent)

    # Wheel scrolling handled manually: even with per-pixel scroll mode,
    # Qt's own wheel handling overshoots in this environment (roughly
    # 2x too fast), so trackpad pixel deltas are applied directly,
    # scaled by the scroll_speed preference (read fresh per event, so a
    # Preferences change applies immediately). SCROLL_SPEED is only the
    # fallback when no panel/prefs is reachable.
    SCROLL_SPEED = 0.75
    #: How long an outcome icon stays on screen (ms).
    INDICATOR_MS = 500
    # Classic mouse wheel: px per notch, pre-scaling. Runs through the
    # UI scale so a notch moves the same VISUAL distance on scaled
    # (Linux HiDPI) displays.
    WHEEL_NOTCH_PX = theme.ui_px(60)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """One scroll engine, both axes.

        This handled the Y axis only and let X fall through to Qt's
        default, which was invisible until list rows grew wider than
        the panel - and then sideways scrolling felt accelerated next
        to up/down, because it was Qt's untuned per-item stepping while
        this path applies the user's scroll_speed to a pixel delta. The
        axis is now just a choice of scrollbar; everything that makes
        vertical scrolling feel right - the trackpad pixel deltas, the
        notch conversion, the preference read fresh per event - is
        shared rather than reimplemented.
        """
        pixels = event.pixelDelta()
        angle = event.angleDelta()
        # Which way is this gesture going? A trackpad reports both, so
        # the dominant axis wins; a classic wheel reports only one.
        horizontal = abs(pixels.x()) > abs(pixels.y()) if (
            pixels.x() or pixels.y()) else abs(angle.x()) > abs(angle.y())
        delta = pixels.x() if horizontal else pixels.y()
        if delta == 0:
            # Classic mouse wheel - no pixel data, only 120-unit notches.
            raw = angle.x() if horizontal else angle.y()
            delta = raw / 120.0 * self.WHEEL_NOTCH_PX
        if delta == 0:
            super().wheelEvent(event)
            return
        # Cached: a trackpad delivers 60-120 of these a second, and the
        # press path already caches for the same reason (the panel does
        # not move between events; a new panel is a new view).
        panel = getattr(self, "_wheel_panel", None)
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

    #: How many scroll diagnostics one session may write (never a flood).
    SCROLL_DIAG_LIMIT = 12

    def _log_scroll_geometry(self, panel, bar, before, delta) -> None:
        """Record the geometry a scroll actually sees, at most
        SCROLL_DIAG_LIMIT times per session and only in list mode with
        Debug Mode on. Separates the two candidate causes of "the list
        scrolls forever and never ends": a scroll RANGE that does not
        match the content, versus geometry that changes per event."""
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
            # The ONE QListView-only call in the gesture, and it is a
            # debug helper: a table has no grid size.
            grid = (self.gridSize() if hasattr(self, "gridSize")
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
                # What the view believes it has to scroll through vs
                # what the rows actually add up to.
                content_h=self.contentsRect().height(),
                expected_h=rows * grid.height() if grid.height() else 0,
                uniform=self.uniformItemSizes(),
            )
        except Exception:
            pass

    @debug.guarded("DragDropListView.mousePressEvent")
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._dragging:
            # A stray right/middle press mid-gesture must not clear the
            # live drag state (lost drop, stuck sidebar glow, rubber
            # band, context menu under the floating tag).
            event.accept()
            return
        panel = _find_panel(self)
        section = (
            getattr(panel, "current_section", None) if panel is not None else None
        )
        # Online rows are catalogue entries, not assets: there is no
        # node to drag and no file on disk yet. Arming the material drag
        # here mapped an ONLINE proxy index through the MATERIAL proxy,
        # which drags whichever local material happens to sit at that row.
        online = bool(panel is not None and panel._is_online())
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and not online
            and section in self.ARMED_SECTIONS
            # Only arm over an actual item: a press on empty grid space
            # used to arm anyway, producing a ghost drag with an empty
            # name tag whose invalid index reached the release handlers.
            and self.indexAt(event.pos()).isValid()
        ):
            self._drag_start = event.pos()
            self._drag_section = section
            # THE ROW, not the pressed cell: in list mode the press
            # lands on a visible column >= 1, where KindRole and
            # PathRole answer None and the name tag reads that CELL's
            # text (research.md > Row selection over a table view).
            self._drag_index = self.indexAt(event.pos()).siblingAtColumn(0)
            self._drag_panel = panel
        else:
            self._drag_start = None
            self._drag_section = None
            self._drag_index = None
            self._drag_panel = None
        super().mousePressEvent(event)

    @debug.guarded("DragDropListView.mouseMoveEvent")
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """ONE self-managed gesture for every section, File rows
        included: the drop target (a node, a category, a viewport
        prim) is resolved by US at release, which means the gesture
        must stay in our hands - a real QDrag traps it in macOS's
        native drag run loop where our code cannot run at all (proven
        during the texture saga: a polling QTimer fired zero times
        inside QDrag.exec()).

        The one place a real QDrag is REQUIRED is a Parameters pane -
        a field is a Qt widget and only mime fills it - so a File
        row's gesture crossing into one HANDS OFF to the real drag
        (_promote_to_field_drag). Never call super() during the
        gesture (even before the threshold) - that used to let
        QAbstractItemView fall back to rubber-band selection.

        Speed: the release target is resolved ONCE, not polled every
        frame - the per-move networkItemsInBox poll was the lag. The
        floating tag just follows the cursor.
        """
        if self._drag_start is not None:
            moved = (event.pos() - self._drag_start).manhattanLength()
            if not self._dragging and moved >= (
                QtWidgets.QApplication.startDragDistance()
            ):
                self._begin_drag()
            if self._dragging:
                if self._promote_to_field_drag():
                    return
                self._move_preview()
                # Same accent-purple drop-target feedback as the material
                # drag gets via the sidebar filter - these gestures have no
                # Qt drag events, so drive it from the cursor position.
                if self._drag_panel is not None:
                    self._drag_panel._update_category_drag_hover_global()
                    dragengine.hover_update(
                        self._drag_panel, self._drag_section
                    )
            return
        super().mouseMoveEvent(event)

    def _overlay_label(self, text: str = "") -> QtWidgets.QLabel:
        """Frameless, always-on-top, click-through label - the shared
        window setup for cursor overlays (drag name tag, outcome icon)."""
        label = QtWidgets.QLabel(text)
        # WindowTransparentForInput makes the top-level window
        # click-through at the OS level (WS_EX_TRANSPARENT on Windows);
        # the WA_TransparentForMouseEvents attribute below only covers
        # Qt's internal routing, which is not enough for a topmost
        # native window parked under the cursor.
        label.setWindowFlags(
            QtCore.Qt.WindowType.ToolTip
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
            | QtCore.Qt.WindowType.WindowTransparentForInput
        )
        label.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        # Showing an overlay must never touch window activation: on
        # macOS an activating show()/close() over the viewport churned
        # focus at release and flickered the selector prompt.
        label.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating
        )
        return label

    def _begin_drag(self) -> None:
        """Start the shared self-managed drag: a floating name tag that
        follows the cursor. Look is temporary (a restyle is planned) -
        the point right now is one gesture for every non-real-path
        section instead of four hand-rolled ones."""
        self._dragging = True
        dragengine.begin(self._drag_section or "")
        name = ""
        if self._drag_index is not None and self._drag_index.isValid():
            name = (
                self._drag_index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
            )
        label = self._overlay_label(str(name))
        # Shared style with the native drags' pixmap (see ui_helpers)
        # so every drag tag looks identical.
        label.setStyleSheet(ui_helpers.DRAG_TAG_STYLE)
        label.adjustSize()
        self._preview = label
        self._move_preview()
        label.show()

    def _move_preview(self) -> None:
        if self._preview is not None:
            pos = QtGui.QCursor.pos()
            # Offset below-right of the cursor, like the native
            # file-drag tag sits.
            self._preview.move(
                pos.x() + theme.ui_px(12), pos.y() + theme.ui_px(14)
            )

    def _finish_preview(self, outcome) -> None:
        """Outcome-explicit tag teardown: the tag itself always goes
        instantly, and a red X (Feather icons, MIT) at the cursor
        announces a MISS. A successful drop shows NOTHING - the result
        appearing in the scene is its own feedback (a success icon was
        tried and dropped: shown before the import, the post-drop cook
        held the event loop past its own hide timer). "menu" also
        shows nothing - the menu itself was the feedback."""
        preview = self._preview
        self._preview = None
        if preview is not None:
            preview.hide()
            preview.close()
            preview.deleteLater()
        if not outcome:
            self._show_drop_indicator("icon_drop_miss.svg", "#ff3319")

    def _show_drop_indicator(self, icon_file: str, color: str) -> None:
        """A small icon at the cursor for INDICATOR_MS - the drop
        outcome, announced where the user is looking."""
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
        # ONE persistent indicator window per view, reused across
        # drops: creating and destroying a native window per outcome
        # was itself a visible hitch at release (and the deleteLater
        # race it forced once flooded the log).
        label = getattr(self, "_indicator_label", None)
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

        # No fade (design call): full opacity for INDICATOR_MS, then
        # hidden - never destroyed (see above). The serial keeps a
        # stale timer from cutting short the icon of a NEWER drop.
        import time as _time
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

    def _file_drag_kind(self) -> str:
        """The pressed File-row's kind, or '' outside the File section."""
        if self._drag_section != "file" or self._drag_index is None:
            return ""
        panel = self._drag_panel
        if panel is None:
            return ""
        try:
            return self._drag_index.data(
                panel.file_files_model.KindRole) or ""
        except RuntimeError:
            return ""

    def _promote_to_field_drag(self) -> bool:
        """The parameter-field hand-off: a FILE row's gesture crossing
        into a Parameters pane becomes the one real QDrag, because a
        field is a Qt widget and only mime fills it. Self-managed
        cannot serve fields, and a real drag cannot serve nodes (the
        run-loop trap in the class docstring), so the gesture chooses
        at the pane boundary. After the hand-off the drag is Qt's:
        releasing back over a network editor gets Houdini's stock
        answer.

        A hand-off, not a miss - the tag goes quietly and Qt's own
        drag picture takes over; no fly-back, no indicator."""
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
        """One mime for a file-path drag. The TEXT flavour is spelled
        per Write Paths As - it is what lands wherever text wins. The
        URL flavour stays the raw local file: a QUrl is an OS handle,
        not a spelling, and an encoded string inside it points at
        nothing."""
        mime_data = QtCore.QMimeData()
        mime_data.setUrls([QtCore.QUrl.fromLocalFile(path)])
        mime_data.setText(file_library.houdini_path(
            path, getattr(panel.prefs, "path_style", "home")))
        return mime_data

    def _run_file_path_drag(self) -> None:
        """Drags the pressed row's file path as real file mime data
        (QUrl + plain text, matching what dragging a file from Finder
        provides), so Houdini's parm fields accept it natively.

        The DRAG PICTURE is the shared black name tag (setPixmap), same as
        every other section - "native" is only the drop mechanism; the
        picture is an independent choice, and the design calls for ONE
        look everywhere. macOS caveat: a file/URL drag sometimes insists on its
        own file badge over a custom pixmap, so confirm the tag actually
        shows on the live test."""
        # The press-captured index, same source as every other drag
        # path - currentIndex() can point at a different row than
        # the one actually pressed.
        index = self._drag_index
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
        finally:
            # Clearing the press state also covers the plain-click case:
            # if left uncleared, a later hover move (mouseMoveEvent can
            # fire without a button held under mouse tracking) would
            # measure a large "moved" distance against a stale start
            # point and spuriously launch a drag with no button pressed.
            #
            # In a FINALLY because the release action can raise and
            # guarded() re-raises by design. It used to sit after the
            # try, so a crashing drop skipped it and left the gesture
            # half-armed: _dragging was already False (cleared before
            # the try), but _drag_start/_drag_section/_drag_panel/
            # _drag_index survived - and the next bare hover move
            # launched a full drag the user never began, carrying the
            # OLD section, so a release after switching tabs dispatched
            # the previous section's handler with an index into the
            # wrong model.
            self._drag_start = None
            self._drag_section = None
            self._drag_panel = None
            self._drag_index = None
        super().mouseReleaseEvent(event)

    def _release(self, event: QtGui.QMouseEvent) -> None:
        if self._dragging and event.button() != QtCore.Qt.MouseButton.LeftButton:
            # mousePressEvent already swallows a stray right/middle press
            # mid-gesture; the release handler did not filter, so
            # right-clicking to back out of a drag PERFORMED the drop
            # wherever the cursor happened to be - a real import or
            # assignment. Verified for both RightButton and MiddleButton.
            #
            # Torn down exactly like a release over nothing: the tag
            # flies back to its tile, which is the right feedback for a
            # cancel. Not a bare return - that would leave the tag
            # floating and the gesture live.
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
            # Hide the tag IMMEDIATELY (before any release work - a menu
            # or import must never run under a floating label), but keep
            # the widget alive: the outcome decides its teardown below.
            if self._preview is not None:
                self._preview.hide()
            self._dragging = False
            # Restores the hover highlight - on EVERY exit path.
            dragengine.end()
            panel = self._drag_panel
            idx = self._drag_index
            if panel is not None:
                panel._set_drag_hover_row(-1)   # clear the drop-target glow
            outcome = False
            # A drop leaves the artist where they were: selection,
            # current node and therefore the view survive the dispatch
            # (helpers.preserving_selection_and_current says why).
            # Entered by hand because the PermissionError handler below
            # must stay OUTSIDE the restoration.
            keeper = helpers.preserving_selection_and_current()
            keeper.__enter__()
            try:
                if panel is not None and idx is not None:
                    section = self._drag_section
                    # Released over a sidebar category? Recategorise the
                    # selection (Materials/Cop/Code/Colors) - checked
                    # first, since it's inside the panel and takes
                    # precedence over a node target. Returns None for
                    # folder sections and for the "All" row.
                    category = panel._category_under_cursor()
                    if category is not None:
                        panel.assign_category_active(category)
                        outcome = True
                    # THE BEHAVIOUR TABLE: the section declares its
                    # doors (sections.DropRule) and one walk serves
                    # every section. A section with no rule for this
                    # row - and a release over nothing - stays silent;
                    # the tag flies back to its tile to SAY so.
                    else:
                        rule = self._drop_rule(panel, section, idx)
                        if rule is not None:
                            outcome = self._apply_drop_rule(
                                rule, panel, idx, event)
            except hou.PermissionError as refusal:
                # HOUDINI REFUSING IS NOT A BUG. Dropping onto a locked
                # asset raises `Cannot create a node inside a locked
                # asset`, and nothing caught it: the exception left
                # mouseReleaseEvent, Qt logged a slot crash, and the
                # user saw a drop that silently did nothing. Recorded
                # five times in one session (2026-08-03) before the
                # debug log was read.
                #
                # It gets the gesture's OWN vocabulary for a failed
                # drop - `outcome` stays False, so the name tag flies
                # back to its tile exactly as it does for a release
                # over empty space - plus Houdini's own sentence for
                # WHY, which is already a good one. No dialog: the
                # user made one gesture and it did not land
                # (practice.md - dialogs are a bill you send the user).
                #
                # Only hou.PermissionError, deliberately. A genuine
                # programming error must still crash where it can be
                # seen; this catches the one case that is the app
                # working correctly and being told no.
                debug.exception("drop refused", refusal,
                                section=self._drag_section)
                # `hou.ui` is absent in a headless session, and an
                # AttributeError raised HERE would turn the refusal
                # this handler exists to absorb straight back into the
                # slot crash it exists to prevent.
                ui = getattr(hou, "ui", None)
                if ui is not None:
                    ui.setStatusMessage(
                        "Amaze: %s" % refusal,
                        severity=hou.severityType.Warning,
                    )
            finally:
                keeper.__exit__(None, None, None)
                self._finish_preview(outcome)

    @staticmethod
    def _drop_rule(panel, section, idx):
        """This row's declared behaviour: the section's one DropRule,
        or - for the File section, whose rows are different THINGS -
        the rule its kind table declares for the row's KindRole."""
        cls = sections.SECTION_INDEX.get(section)
        if cls is None:
            return None
        if cls.DROP_BY_KIND:
            kind = idx.data(panel.file_files_model.KindRole) or ""
            return cls.DROP_BY_KIND.get(kind)
        return cls.DROP

    @staticmethod
    def _apply_drop_rule(rule, panel, idx, event) -> bool:
        """ONE precedence for every section, fixed here and nowhere
        else. A declared door that does not apply falls through to the
        next; no door left is the uniform miss (False - the tag flies
        home). Doors, in order:

        on_node   a node under the release takes the payload - and its
                  refusal is FINAL, never a fallback into another door
        outside   released outside the panel (hip scenes; the scene
                  loader owns any save prompt, so landing IS the hit)
        resolve   the verb aims itself (material, cop, geometry)
        on_space  the creation rule on empty network space - off any
                  editor there is no network and nothing is consulted
        """
        if rule.on_node is not None:
            node = panel._node_under_cursor()
            if node is not None:
                return bool(getattr(panel, rule.on_node)(idx, node))
        if rule.outside is not None:
            global_pos = event.globalPosition().toPoint()
            local = panel.mapFromGlobal(global_pos)
            if not panel.rect().contains(local):
                getattr(panel, rule.outside)(idx)
                return True
        if rule.resolve is not None:
            return bool(getattr(panel, rule.resolve)(idx))
        if rule.on_space is not None:
            net = panel._network_under_release()
            # The GATED position: coordinates cross into the
            # destination only when the release editor is showing
            # that network itself (the seam's rule; panel.
            # _release_position_in says why).
            return bool(
                net is not None
                and getattr(panel, rule.on_space)(
                    idx, net, panel._release_position_in(net)))
        return False


def _node_paths_from_mime(mime) -> list:
    """Node paths carried by a drag, across every format Houdini uses:
    the dedicated node-path mime, the item-path list, then plain text.
    H22's node drag populates text() too; H21's populates ONLY the
    Houdini formats - reading just text() made a dropped node parse to
    "" and the save flow silently do nothing. Multi-node drags separate
    paths with tabs/newlines."""
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
    """Receives a node dragged IN from a network editor (drop = save to
    the library). The legacy leave-the-panel OUTBOUND import that used
    to live here (and on DragDropListView) is gone: every section's
    drag-out is now a self-managed or mime-based gesture in
    DragDropListView, so the native model drag that fed those handlers
    never starts - and during the material mime drag the leftover
    handler actively double-imported (DRAGTEST log, 2026-07-19)."""

    @debug.guarded("DragDropCentralWidget.dragEnterEvent")
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        """EXPLICIT acceptance: nothing in code ever accepted the drag
        (the .ui only sets acceptDrops) - H22's Qt still delivered the
        drop, H21's never did, so a node dropped on the panel produced
        no reaction at all. Accept any drag carrying a resolvable node
        path that did not start inside the panel."""
        src = event.source()
        if src is not None and _find_panel(src) is not None:
            return
        if _node_paths_from_mime(event.mimeData()):
            event.acceptProposedAction()

    @debug.guarded("DragDropCentralWidget.dropEvent")
    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        # A material dragged OUT of our own grid carries a valid node path
        # (its /mat copy) - ignore any drop that ORIGINATED inside the
        # panel; only a node dragged in from a network editor is a
        # "save this".
        src = event.source()
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
        # The dropped nodes BECOME the selection the save flow reads -
        # a multi-node drop saves them all (save_asset multi-selection
        # semantics).
        for i, n in enumerate(nodes):
            n.setSelected(True, clear_all_selected=(i == 0))
        panel = _find_panel(self)
        if panel is None:
            return
        # DEFERRED out of the drop event: opening a modal dialog here,
        # while the native drag gesture is still completing, let the
        # drag's own mouse-release land on the dialog's default button -
        # the save dialog was accepted with default values before it
        # ever painted (observed on H21/macOS). A zero timer runs the
        # save flow right after the drop fully finishes.
        section = panel._section()

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
    """Makes the category sidebar a real DROP TARGET: dragging assets from
    the grid onto a category recategorises them (same gesture as a node
    drop, but aimed at a category). Installed as an event filter on the
    sidebar so no .ui subclassing is needed; it accepts only drags that
    started in our own grid (so a node dragged in from Houdini still falls
    through to the save handler), and consumes the drop so it never
    reaches the central widget's save-node flow."""

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
                # Highlight the category under the cursor in the accent
                # purple, so it's clear which one the drop will hit.
                self._panel._update_category_drag_hover(
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
    """The GRID: one tile per item, IconMode or ListMode.

    Kept as its own name because every caller, test and `.ui` file
    refers to it. What used to BE this class is the mixin above.
    """


class DragDropTableView(GridGestureMixin, QtWidgets.QTableView):
    """LIST MODE as a real table (step 2 of the QTableView migration).

    Shares the gesture, and shares the MODEL, PROXY and SELECTION MODEL
    with the grid view - Qt supports two views over one selection, and
    that is what keeps this from doubling every area binding.

    It wears the HOST's look, not its own (2026-08-04). The panel puts
    `hou.qt.styleSheet()` on its root and every child inherits it, so
    the rows band and select like every other list in Houdini. What it
    ADDS is what a real header gives for free - click a heading to
    sort, drag an edge to resize.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setShowGrid(False)
        # BANDED ROWS, in the host's own colour. Houdini's stylesheet
        # carries `QTableView { alternate-background-color:
        # rgb(@ListEntry1@) }` - ListEntry1 is LISTB, grey 0.2286 in
        # UIDark.hcs - and Qt only uses it when the view asks for it.
        # This was False to match the hand-painted strip it replaced,
        # which had no banding to inherit.
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        # The grid is multi-select and so is this - QTableView already
        # defaults to ExtendedSelection where QListView defaults to
        # Single, so this says it rather than inheriting a difference.
        self.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
