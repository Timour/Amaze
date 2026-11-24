"""A drag of tiles out of a pane into Houdini, the one gesture both panes run. ▸o/section-api"""

from PySide6 import QtCore, QtGui
import hou

from amaze import sections
from amaze.core import debug, dragengine
from amaze.helpers import helpers
from amaze.render import cop_nodes
from amaze.sections import base as section_base

DRAG_SECTIONS = ("material", "gradient", "cop", "code", "file")    #: rows that drag; each section drops its own way


def drags(pane, section_key: str) -> bool:
    """Whether a press on a row of `section_key` may start a drag; an online row has no node or file."""
    return section_key in DRAG_SECTIONS and not pane.is_online()


def file_drag_mime(pane, path: str) -> QtCore.QMimeData:
    """File-path drag mime: the path per Write Paths As as text, no URL. ▸r/drag-file-url"""
    mime_data = QtCore.QMimeData()
    mime_data.setText(helpers.houdini_path(path, getattr(pane.prefs, "path_style", "home")))
    return mime_data


class DragSession:
    """One view's drag: `begin`, a `move` per move, one end, `release` or `cancel`. ▸r/pick-boundary"""

    def __init__(self, source, marks) -> None:
        self.source = source    # the view: it holds the keyboard for Esc, and a real QDrag starts from it
        self.marks = marks    # `ui_helpers.DragMarks`: the tag and the red X, the widgets the engine has none of
        self.running = False
        self.pane = None
        self.section = ""
        self._row = QtCore.QPersistentModelIndex()    # the pressed row; persistent, so a removed row is a miss
        self._sidebar = None    # the host's sidebar rows under the cursor, or None: no sidebar drop there

    def begin(self, pane, section_key: str, row, name: str, sidebar=None) -> None:
        """Start dragging `row`, the pressed row at column 0: its name follows the cursor."""
        self.pane, self.section, self._sidebar = pane, section_key or "", sidebar
        self._row = QtCore.QPersistentModelIndex(row)
        self.running = True
        dragengine.begin(self.section)
        self.source.grabKeyboard()    # Esc reaches the view whatever has the focus; released at the end
        QtGui.QGuiApplication.instance().applicationStateChanged.connect(self._on_application_state)
        self.marks.show_tag(name)

    def move(self) -> None:
        """One move of the pointer: the tag, the sidebar row, the hover and the outline follow it."""
        if not self.running:
            return
        try:
            self._follow()
        except Exception:    # the host's guard logs it: the drag does not stay half on
            self.cancel(miss=True)
            raise

    def release(self) -> None:
        """The left button let go: the drop, one undo step; a miss or a refusal shows the red X."""
        if not self.running:
            return
        self._end()    # before any drop work: the tag and every highlight are gone
        row = self._pressed_row()    # None when the row was removed during the drag: a miss
        outcome = False
        try:
            if row is not None:
                outcome = self._drop(row)
        except hou.PermissionError as refusal:    # only this class: a locked network raises it
            debug.exception("drop failed - permission error", refusal, section=self.section)
            debug.refuse(str(refusal), section=self.section)    # Houdini's own message ▸p/refuse-vs-alert
        finally:
            if not outcome:
                self.marks.show_miss()

    def cancel(self, miss: bool = False) -> None:
        """End with no drop: Esc and a hidden view quietly, another button or an error with the red X."""
        if self.running:
            self._end(miss)

    def _follow(self) -> None:
        """The tag, the drop targets and the highlight, from one pane lookup. ▸p/drag-move-cost"""
        if self._switch_to_qdrag_over_parm_pane():
            return
        self.marks.move_tag()
        pane_tab, pane_kind, _fresh = dragengine.pane_under_cursor_tracked()
        if self._sidebar is not None:
            self._sidebar.hover()
        dragengine.hover_update(self.pane, self.section, pane_tab, pane_kind)
        self._update_drop_outline(pane_tab, pane_kind)    # the outline; the end clears it

    def _drop(self, row):
        """Onto a sidebar category or folder, else into Houdini by the row's own drop rule."""
        category, folder = self._sidebar.target() if self._sidebar is not None else (None, None)
        if category is not None:
            self.pane.sidebar.assign_category(category)
            return True
        if folder is not None:    # File: the selected files move into that folder, on disk
            return self.pane.files.move_files(folder)
        model, proxy = self.pane.sections.get(self.section).tile_models()
        return self.pane.drop_placement.release(self.section, model.tile_key(proxy.mapToSource(row).row()))

    def _end(self, miss: bool = False) -> None:
        """The one end of a drag, for every way out: what the drag set is taken back."""
        self.running = False
        self.source.releaseKeyboard()
        try:
            QtGui.QGuiApplication.instance().applicationStateChanged.disconnect(self._on_application_state)
        except (RuntimeError, TypeError):
            pass    # not connected
        dragengine.end()
        if self._sidebar is not None:
            self._sidebar.clear()
        self.marks.hide_tag()
        if miss:
            self.marks.show_miss()

    def _pressed_row(self):
        """The pressed row as an index, None once it was removed from the model during the drag."""
        return QtCore.QModelIndex(self._row) if self._row.isValid() else None

    def _on_application_state(self, state) -> None:
        """The tag is hidden while another application is in front."""
        self.marks.tag_shown(state == QtCore.Qt.ApplicationState.ApplicationActive)

    def _switch_to_qdrag_over_parm_pane(self) -> bool:
        """A File row over a Parameters pane becomes a real QDrag; Qt then runs the drag."""
        if self.section != "file":
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
        self._end()    # a switch to QDrag, not a failed drop: no red X
        self._run_file_path_drag()
        return True

    def _run_file_path_drag(self) -> None:
        """The only real `QDrag`: `file_drag_mime`, the name tag as its picture."""
        row = self._pressed_row()    # the PRESSED row: the current one can name another
        if row is None:
            return
        path = row.data(self.pane.file_files_model.PathRole)
        if not path:
            return
        drag = QtGui.QDrag(self.source)
        drag.setMimeData(file_drag_mime(self.pane, path))
        drag.setPixmap(self.marks.tag_picture(row.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""))
        drag.exec(QtCore.Qt.DropAction.CopyAction)

    def _preview_node_type(self, rule, dest, row) -> str:
        """The node type an on_space drop would create in `dest`; `""` is none: a plain box."""
        cls = sections.SECTION_INDEX.get(self.section)
        name = rule.holder_node_type or getattr(cls, "holder_node_type", "")
        handler = getattr(cls, "holder_node_type_method", "")
        if not name and handler and row is not None:
            try:
                live = self.pane.sections.get(self.section)
                name = section_base.drop_handler(live, handler)(row, dest)
            except (AttributeError, hou.OperationFailed):
                name = ""
        return name or ""

    def _update_drop_outline(self, pane_tab, pane_type) -> None:
        """Per move: outline where the node would go; pass the tracked pane. ▸p/drag-move-cost"""
        row = self._pressed_row()
        rule = self._drop_rule(row) if row is not None else None
        if rule is None:
            dragengine.ghost_clear()
            return
        self.marks.tag_shown(pane_type != hou.paneTabType.NetworkEditor)    # there the outline shows it
        try:
            if pane_tab is None or pane_type != hou.paneTabType.NetworkEditor:
                dragengine.ghost_clear()
                return
            if getattr(rule, "context", "") and not cop_nodes.accepts_context(
                    pane_tab.pwd(), rule.context):    # the network does not take this node type: no outline
                dragengine.ghost_clear()
                return
            spot = pane_tab.cursorPosition()
            if dragengine.ghost_tick(pane_tab):
                blocked = bool(rule.on_node and self.pane.drop_placement.node_under_cursor(pane_tab, pane_type)
                               is not None)
                target = (None, "", -1)    # a wire under the cursor is an insert, asked only where a chain can take it
                type_name = ""
                if not blocked:
                    if rule.on_space or rule.resolve:
                        target = dragengine.wire_under_cursor(pane_tab, spot)
                    type_name = self._preview_node_type(rule, pane_tab.pwd(), row)
                dragengine.set_ghost_tick_results(blocked, target, type_name)
                dragengine.wire_highlight(pane_tab, target)
            blocked, target, type_name = dragengine.ghost_tick_results()
            if blocked:
                dragengine.ghost_clear()    # Houdini's own node highlight shows this case
                return
            dragengine.ghost_show(pane_tab, spot, type_name, connection=target[0])
        except (AttributeError, hou.OperationFailed):
            dragengine.ghost_clear()

    def _drop_rule(self, row):
        """This row's declared drop behaviour by section key, resolved by `section_base.drop_rule`."""
        return section_base.drop_rule(sections.SECTION_INDEX.get(self.section), self.pane, row)
