"""The Notes feature (2026-08-01 design): the store, the page, the
wiring.

Three layers, tested at their own altitude:

* **core/notes.py** - the guard set it copied from icons.json must
  actually guard: an unreadable file latches writes off, another
  session's keys are adopted rather than clobbered, every write leaves
  a restore tier behind, and an empty page deletes its key.
* **NotesPanel** - the widget drives the store: debounced saves flush
  on demand, the + button adds a focused row, a toggled item flips and
  persists, a blank label is not content.
* **The panel** - the toolbar button toggles a pane that follows the
  selection, and the tile models answer NotesRole so the badge can
  paint.
"""

import glob
import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.panel import sections  # noqa: E402
from amaze.core import notes  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class _Prefs:
    def __init__(self, testcase):
        self.dir = tempfile.mkdtemp(prefix="amaze_notes_lib_")
        testcase.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)


class StoreTest(unittest.TestCase):

    def setUp(self):
        notes.forget_notes()
        self.addCleanup(notes.forget_notes)
        self.prefs = _Prefs(self)

    def _path(self):
        return os.path.join(self.prefs.dir, notes.NOTES_FILE)

    def test_a_page_roundtrips_in_order(self):
        """The page is a FLOW: text above, between and below to-dos,
        in the order written (the live-pass correction)."""
        key = notes.note_key("material", "42")
        flow = [
            {"t": "text", "text": "check the roughness"},
            {"t": "todo", "label": "re-render", "done": False},
            {"t": "todo", "label": "ask about the displacement",
             "done": True},
            {"t": "text", "text": "…then compare with the scan"},
        ]
        self.assertTrue(notes.set_note(self.prefs, key, flow))
        notes.forget_notes()                 # a fresh session reads disk
        page = notes.note_for(self.prefs, key)
        self.assertEqual(flow, page["items"],
                         "the flow lost its order or content")
        self.assertTrue(notes.has_note(self.prefs, key))

    def test_the_first_builds_shape_converts_on_read(self):
        """notes.json written by the first build ({text, todos}) reads
        as text-then-todos in the flow - nothing anyone wrote is
        lost."""
        with open(self._path(), "w", encoding="utf-8") as handle:
            json.dump({"notes": {"material:1": {
                "text": "old words",
                "todos": [{"label": "old item", "done": True}]}}},
                handle)
        page = notes.note_for(self.prefs, "material:1")
        self.assertEqual(
            [{"t": "text", "text": "old words"},
             {"t": "todo", "label": "old item", "done": True}],
            page["items"])

    def test_an_empty_page_removes_the_key(self):
        key = notes.note_key("cop", "7")
        notes.set_note(self.prefs, key,
                       [{"t": "text", "text": "something"}])
        notes.set_note(self.prefs, key,
                       [{"t": "text", "text": "   "}])
        self.assertFalse(notes.has_note(self.prefs, key),
                         "an empty page still counts as a note - the "
                         "badge will never clear")
        with open(self._path(), encoding="utf-8") as handle:
            self.assertEqual({}, json.load(handle)["notes"])

    def test_junk_normalises_instead_of_raising(self):
        self.assertEqual({}, notes.normalise("a string"))
        self.assertEqual({}, notes.normalise({"items": "not-a-list",
                                              "todos": "junk"}))
        page = notes.normalise({"items": [
            3, {"t": "todo", "label": "  real  "},
            {"t": "todo", "label": ""}, {"t": "text", "text": "  "},
            {"t": "weird"}]})
        self.assertEqual([{"t": "todo", "label": "real",
                           "done": False}], page["items"])

    def test_an_unreadable_file_latches_writes_off(self):
        """The icons.json lesson: an empty table is indistinguishable
        from 'no notes yet', so the next save would erase every note
        in the library. Refuse for the session instead."""
        with open(self._path(), "w", encoding="utf-8") as handle:
            handle.write("{corrupt")
        self.assertEqual({}, notes.note_for(self.prefs, "material:1"))
        self.assertFalse(
            notes.set_note(self.prefs, "material:1",
                           [{"t": "text", "text": "text"}]),
            "a write went through over an unreadable notes file")
        with open(self._path(), encoding="utf-8") as handle:
            self.assertEqual("{corrupt", handle.read(),
                             "the unreadable file was overwritten")

    def test_another_sessions_keys_are_adopted_not_clobbered(self):
        """Two machines, one library: the other session's note must
        survive this session's next save."""
        mine = notes.note_key("material", "1")
        notes.set_note(self.prefs, mine,
                       [{"t": "text", "text": "mine"}])
        # The other session writes a DIFFERENT key underneath us.
        with open(self._path(), encoding="utf-8") as handle:
            on_disk = json.load(handle)
        on_disk["notes"]["material:2"] = {
            "items": [{"t": "text", "text": "theirs"}]}
        with open(self._path(), "w", encoding="utf-8") as handle:
            json.dump(on_disk, handle)
        notes.set_note(self.prefs, mine,
                       [{"t": "text", "text": "mine, edited"}])
        with open(self._path(), encoding="utf-8") as handle:
            final = json.load(handle)["notes"]
        self.assertIn("material:2", final,
                      "the other session's note was clobbered")
        self.assertEqual("mine, edited",
                         final[mine]["items"][0]["text"])

    def test_every_write_leaves_a_restore_tier(self):
        key = notes.note_key("code", "9")
        notes.set_note(self.prefs, key, [{"t": "text", "text": "first"}])
        notes.set_note(self.prefs, key, [{"t": "text", "text": "second"}])
        backups = glob.glob(self._path() + ".bak*")
        self.assertTrue(backups,
                        "no .bak tier beside notes.json - the first "
                        "bad write is the last word on every note")


class PanelWidgetTest(unittest.TestCase):
    """The flowing document: text and framed to-dos interleave in one
    editor, in the order written - the live-pass correction of the
    first build's two competing stacks."""

    def setUp(self):
        notes.forget_notes()
        self.addCleanup(notes.forget_notes)
        self.prefs = _Prefs(self)
        from amaze.panel import notes_panel
        self.widget = notes_panel.NotesPanel(self.prefs)
        self.addCleanup(self.widget.deleteLater)

    def _subject(self, ident="5"):
        key = notes.note_key("material", ident)
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        return key

    def _press_return(self):
        event = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Return,
            QtCore.Qt.KeyboardModifier.NoModifier)
        self.widget.text_edit.keyPressEvent(event)

    def test_a_flow_loads_and_roundtrips_in_order(self):
        key = self._subject()
        flow = [
            {"t": "text", "text": "above the frames"},
            {"t": "todo", "label": "first", "done": False},
            {"t": "todo", "label": "second", "done": True},
            {"t": "text", "text": "and below them"},
        ]
        notes.set_note(self.prefs, key, flow)
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        self.assertEqual(flow, self.widget.text_edit.serialize(),
                         "the document does not carry the flow's order")

    def test_plus_inserts_a_frame_after_the_text_being_written(self):
        self._subject("6")
        edit = self.widget.text_edit
        edit.setFocus()
        cursor = edit.textCursor()
        cursor.insertText("intro line")
        edit.setTextCursor(cursor)
        self.widget.add_button.click()
        cursor = edit.textCursor()
        cursor.insertText("the to-do")
        edit.setTextCursor(cursor)
        self.assertEqual(
            [{"t": "text", "text": "intro line"},
             {"t": "todo", "label": "the to-do", "done": False}],
            edit.serialize(),
            "+ did not add the frame underneath the text")

    def test_text_keeps_flowing_below_a_frame(self):
        key = self._subject("7")
        notes.set_note(self.prefs, key,
                       [{"t": "todo", "label": "item", "done": False}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        cursor = edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        edit.setTextCursor(cursor)
        self._press_return()          # leave the frame...
        self._press_return()          # (continuation frame, emptied out)
        cursor = edit.textCursor()
        cursor.insertText("written after the frame")
        self.assertEqual(
            [{"t": "todo", "label": "item", "done": False},
             {"t": "text", "text": "written after the frame"}],
            edit.serialize(),
            "text cannot flow below a to-do frame")

    def test_enter_in_a_frame_stacks_another_frame(self):
        self._subject("8")
        edit = self.widget.text_edit
        edit.insert_todo()
        cursor = edit.textCursor()
        cursor.insertText("first")
        edit.setTextCursor(cursor)
        self._press_return()
        cursor = edit.textCursor()
        cursor.insertText("second")
        edit.setTextCursor(cursor)
        self.assertEqual(
            [{"t": "todo", "label": "first", "done": False},
             {"t": "todo", "label": "second", "done": False}],
            edit.serialize(),
            "Enter inside a frame does not stack another frame")

    def test_backspace_unwraps_a_frame(self):
        """The deletion path: Backspace at a frame's start turns it
        back into text (the mirror of Enter-on-empty); the label
        survives as plain words the next Backspace can eat."""
        key = self._subject("15")
        notes.set_note(self.prefs, key,
                       [{"t": "todo", "label": "doomed", "done": False}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        cursor = edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.Start)
        edit.setTextCursor(cursor)
        event = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Backspace,
            QtCore.Qt.KeyboardModifier.NoModifier)
        edit.keyPressEvent(event)
        self.assertEqual([{"t": "text", "text": "doomed"}],
                         edit.serialize(),
                         "Backspace did not unwrap the frame")

    def test_backspacing_a_line_into_a_frame_keeps_its_checkbox(self):
        """THE screenshot bug: backspacing an emptied line UP into the
        to-do above it. Qt's separator removal stamps the merged block
        with the FOLLOWING block's userState (probed - research.md ▸
        Qt text checklists), so the frame above silently lost its
        checkbox while its struck text stayed. The merge now hands the
        survivor its own state back."""
        key = self._subject("40")
        # The line below the frame carries one character - the store
        # prunes EMPTY text items at load, so the walk must do what
        # the user did: backspace the line empty, then once more.
        notes.set_note(self.prefs, key,
                       [{"t": "todo", "label": "keepme", "done": True},
                        {"t": "text", "text": "x"}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        cursor = edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        edit.setTextCursor(cursor)
        for _ in range(2):                    # eat "x", then merge
            event = QtGui.QKeyEvent(
                QtCore.QEvent.Type.KeyPress,
                QtCore.Qt.Key.Key_Backspace,
                QtCore.Qt.KeyboardModifier.NoModifier)
            edit.keyPressEvent(event)
        self.assertEqual(
            [{"t": "todo", "label": "keepme", "done": True}],
            edit.serialize(),
            "the merge stripped the frame above of its checkbox")

    def test_forward_delete_at_a_frames_end_keeps_its_checkbox(self):
        """The unreported mirror the probe caught: Delete at a frame's
        end pulls the next line in and unmade the frame the same way.
        The joined words become part of the frame's label."""
        key = self._subject("41")
        notes.set_note(self.prefs, key,
                       [{"t": "todo", "label": "top", "done": False},
                        {"t": "text", "text": "tail"}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        cursor = edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.Start)
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock)
        edit.setTextCursor(cursor)
        event = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Delete,
            QtCore.Qt.KeyboardModifier.NoModifier)
        edit.keyPressEvent(event)
        self.assertEqual(
            [{"t": "todo", "label": "toptail", "done": False}],
            edit.serialize(),
            "the forward merge stripped the frame of its checkbox")

    def test_an_enter_chain_keeps_every_checkbox(self):
        """THE live-pass bug: Return created the next to-do but the
        previous one's checkbox vanished. Three in a chain - every
        block must still BE a to-do when the typing stops."""
        self._subject("16")
        edit = self.widget.text_edit
        edit.insert_todo()
        for i, label in enumerate(("one", "two", "three")):
            cursor = edit.textCursor()
            cursor.insertText(label)
            edit.setTextCursor(cursor)
            if i < 2:
                self._press_return()
        self.assertEqual(
            [{"t": "todo", "label": "one", "done": False},
             {"t": "todo", "label": "two", "done": False},
             {"t": "todo", "label": "three", "done": False}],
            edit.serialize(),
            "a checkbox was lost somewhere in the chain")

    def test_text_flows_below_the_second_todo_too(self):
        """The other live-pass bug: writing underneath only worked for
        the FIRST to-do."""
        key = self._subject("17")
        notes.set_note(self.prefs, key, [
            {"t": "todo", "label": "first", "done": False},
            {"t": "todo", "label": "second", "done": False}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        cursor = edit.textCursor()
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        edit.setTextCursor(cursor)
        self._press_return()
        self._press_return()
        cursor = edit.textCursor()
        cursor.insertText("under the second")
        self.assertEqual(
            [{"t": "todo", "label": "first", "done": False},
             {"t": "todo", "label": "second", "done": False},
             {"t": "text", "text": "under the second"}],
            edit.serialize(),
            "text cannot flow below the second frame")

    def test_the_broken_qt_apis_stay_out(self):
        """Source pin on two probed facts: Qt's task-list markers
        inherit unpredictably, and QTextObjectInterface.registerHandler
        never registers in Houdini's PySide6 6.8.3. Neither API may
        return to this file."""
        import inspect
        from amaze.panel import notes_panel as module
        source = inspect.getsource(module)
        for banned in ("registerHandler", "QTextObjectInterface",
                       "MarkerType", "createList"):
            self.assertNotIn(banned, source,
                             "%s is back - it is the machinery that "
                             "failed live, twice" % banned)

    def test_todo_separation_is_padding_not_background(self):
        """The 2026-08-01 call: a to-do is page-coloured - no
        background of its own - and stands apart by 10px of padding
        above and below."""
        from amaze.helpers import theme
        self._subject("21")
        edit = self.widget.text_edit
        edit.insert_todo()
        cursor = edit.textCursor()
        cursor.insertText("padded")
        block = edit.document().begin()
        fmt = block.blockFormat()
        self.assertEqual(theme.ui_px(10), fmt.topMargin(),
                         "a to-do lost its breathing room above")
        self.assertEqual(theme.ui_px(10), fmt.bottomMargin(),
                         "a to-do lost its breathing room below")
        self.assertEqual(
            QtCore.Qt.BrushStyle.NoBrush,
            fmt.background().style(),
            "a to-do wears a background again - the call was "
            "page-coloured with padding only")

    def test_no_stylesheet_anywhere_in_the_pane(self):
        """A stylesheet on ANY ancestor hands the whole subtree to
        Qt's stylesheet engine, whose primitive scrollbars replace
        Houdini's - and headless the suite CANNOT see the difference
        (probed: offscreen style() reports QCommonStyle either way),
        so the guard is a SOURCE ban. Backgrounds go through palettes
        (_fill/_dim), the panel's own pattern."""
        import inspect
        from amaze.panel import notes_panel as module
        source = inspect.getsource(module)
        self.assertNotIn("setStyleSheet", source,
                         "a stylesheet is back somewhere in the pane "
                         "- the IRIX scrollbar returns with it, and "
                         "only the live pass would ever see it")

    def test_the_designed_colours_ride_the_palettes(self):
        """The colours survive the stylesheet purge: header and page
        backgrounds live in widget palettes with autofill on."""
        from amaze.panel import notes_panel as module
        header = self.widget.header_widget
        self.assertTrue(header.autoFillBackground())
        self.assertEqual(
            module.HEADER_BG,
            header.palette().color(
                QtGui.QPalette.ColorRole.Window).name())
        body = self.widget.body_widget
        self.assertTrue(body.autoFillBackground())
        self.assertEqual(
            module.PAGE_BG,
            body.palette().color(
                QtGui.QPalette.ColorRole.Window).name())

    def test_the_glyph_sits_on_its_text_line(self):
        """The live report: checkmarks below the text. The glyph must
        paint inside its to-do's own first-line band - the truth comes
        from the block's laid-out line, which absorbs the padding
        blockBoundingRect already contains (double-counting it was
        the bug, measured at one padding of error)."""
        from PySide6 import QtGui as G
        key = self._subject("22")
        notes.set_note(self.prefs, key,
                       [{"t": "text", "text": "a line above"},
                        {"t": "todo", "label": "on the line",
                         "done": False}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        edit.resize(300, 160)
        edit.document().setTextWidth(280)
        block = edit.document().begin().next()      # the to-do
        self.assertTrue(edit.is_todo_block(block))
        tlayout = block.layout()
        self.assertGreater(tlayout.lineCount(), 0)
        line = tlayout.lineAt(0)
        band_top = tlayout.position().y() + line.y()
        band_bottom = band_top + line.height()
        image = G.QImage(300, 160, G.QImage.Format.Format_ARGB32)
        image.fill(G.QColor("#2b2c34"))
        painter = G.QPainter(image)
        try:
            edit._paint_todo_glyphs(painter)
        finally:
            painter.end()
        rows = [y for y in range(160) for x in range(0, 40)
                if image.pixelColor(x, y).lightness() > 120]
        self.assertTrue(rows, "no glyph painted at all")
        self.assertGreaterEqual(min(rows), int(band_top) - 1,
                                "the glyph starts above its line")
        self.assertLessEqual(max(rows), int(band_bottom) + 1,
                             "the glyph reaches below its line - the "
                             "padding is double-counted again")

    def test_the_cursor_says_button_over_the_checkbox(self):
        """The checkbox is clickable and the pointer should say so: a
        pointing hand over the glyph zone, the I-beam over text."""
        from PySide6 import QtGui as G
        key = self._subject("23")
        notes.set_note(self.prefs, key,
                       [{"t": "todo", "label": "hover me",
                         "done": False}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        edit.resize(300, 120)
        edit.document().setTextWidth(280)

        def move_to(x, y):
            event = G.QMouseEvent(
                QtCore.QEvent.Type.MouseMove, QtCore.QPointF(x, y),
                QtCore.Qt.MouseButton.NoButton,
                QtCore.Qt.MouseButton.NoButton,
                QtCore.Qt.KeyboardModifier.NoModifier)
            edit.mouseMoveEvent(event)

        block = edit.document().begin()
        start = G.QTextCursor(block)
        start.setPosition(block.position())
        rect = edit.cursorRect(start)
        move_to(4, rect.center().y())          # over the glyph zone
        self.assertEqual(QtCore.Qt.CursorShape.PointingHandCursor,
                         edit.viewport().cursor().shape(),
                         "the pointer does not say the checkbox is "
                         "clickable")
        move_to(rect.left() + 40, rect.center().y())   # over the text
        self.assertEqual(QtCore.Qt.CursorShape.IBeamCursor,
                         edit.viewport().cursor().shape(),
                         "the pointer stays a hand over plain text")

    def test_the_glyphs_actually_paint(self):
        """THE invisible-checkbox lesson: serialization can be perfect
        while nothing draws. Paint the glyph pass onto an image and
        demand bright pixels where the checkbox belongs."""
        from PySide6 import QtGui as G
        key = self._subject("20")
        notes.set_note(self.prefs, key,
                       [{"t": "todo", "label": "visible", "done": False}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        edit.resize(300, 100)
        # Force the layout pass: the painter GUARDS un-laid-out blocks
        # (lineAt on one crashes hython natively - research.md), so an
        # unlaid document legitimately paints nothing.
        edit.document().setTextWidth(280)
        image = G.QImage(300, 100, G.QImage.Format.Format_ARGB32)
        image.fill(G.QColor("#2b2c34"))
        painter = G.QPainter(image)
        try:
            edit._paint_todo_glyphs(painter)
        finally:
            painter.end()
        bright = sum(
            1 for x in range(0, 60) for y in range(0, 60)
            if image.pixelColor(x, y).lightness() > 120)
        self.assertGreater(bright, 10,
                           "no checkbox pixels - the glyph pass "
                           "painted nothing (the live + bug's shape)")

    def test_no_block_rides_a_qt_list(self):
        """The indent pile-up came from QTextList inheritance; the
        editor now owns its checkboxes, so NO block may be a list
        item - if one is, the machinery regressed."""
        key = self._subject("18")
        notes.set_note(self.prefs, key, [
            {"t": "text", "text": "words"},
            {"t": "todo", "label": "item", "done": True}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        block = edit.document().begin()
        while block.isValid():
            self.assertIsNone(block.textList(),
                              "a block is a Qt list item again")
            block = block.next()

    def test_a_toggled_todo_keeps_its_checkbox(self):
        """Crossed-out text with no tickmark was the symptom: the flip
        must change the STATE of the box, never remove it."""
        key = self._subject("19")
        notes.set_note(self.prefs, key,
                       [{"t": "todo", "label": "flip me",
                         "done": False}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        block = edit.document().begin()
        self.assertTrue(edit.toggle_block(block))
        block = edit.document().begin()
        self.assertTrue(edit.is_todo_block(block),
                        "toggling removed the checkbox")
        self.assertTrue(edit.block_done(block))

    def test_toggling_flips_done_and_persists(self):
        key = self._subject("9")
        notes.set_note(self.prefs, key,
                       [{"t": "todo", "label": "fix the tiling",
                         "done": False}])
        self.widget.clear_subject()
        self.widget.set_subject(sections.CommentSubject(key, "material", "X", ""))
        edit = self.widget.text_edit
        block = edit.document().begin()
        self.assertTrue(edit.toggle_block(block),
                        "the block was not recognised as a to-do")
        self.widget._something_changed()
        self.widget.flush()
        page = notes.note_for(self.prefs, key)
        self.assertTrue(page["items"][0]["done"],
                        "the toggle did not persist")

    def test_a_blank_frame_is_not_content(self):
        key = self._subject("10")
        edit = self.widget.text_edit
        cursor = edit.textCursor()
        cursor.insertText("keep me")
        edit.setTextCursor(cursor)
        self.widget.add_button.click()          # frame left empty
        self.widget.flush()
        page = notes.note_for(self.prefs, key)
        self.assertEqual([{"t": "text", "text": "keep me"}],
                         page["items"],
                         "an empty frame counted as content")

    def test_switching_subject_flushes_the_pending_edit(self):
        first = self._subject("11")
        cursor = self.widget.text_edit.textCursor()
        cursor.insertText("typed then switched")
        self.widget.set_subject(sections.CommentSubject(
                notes.note_key("material", "12"), "material", "B", ""))
        self.assertEqual(
            "typed then switched",
            notes.note_for(self.prefs, first)["items"][0]["text"],
            "switching subjects lost the pending edit")

    def test_clear_subject_shows_the_ghost_page(self):
        """No selection = the SAME window as a ghost: placeholder
        labels, dead page-coloured +, disabled editor - never a
        different layout."""
        self._subject("13")
        self.assertTrue(self.widget.add_button.isEnabled())
        self.widget.clear_subject()
        self.assertEqual("section/category",
                         self.widget.section_label.text())
        self.assertEqual("Object name", self.widget.name_label.text())
        self.assertEqual("type", self.widget.type_label.text())
        self.assertFalse(self.widget.add_button.isEnabled(),
                         "the + still works with nothing selected")
        self.assertFalse(self.widget.text_edit.isEnabled())
        self._subject("13b")
        self.assertTrue(self.widget.add_button.isEnabled(),
                        "selecting again did not wake the page")

    def test_the_header_reads_section_slash_category(self):
        """A category joins the section line; a COLOURED category
        renders in its colour and bold."""
        self.widget.set_subject(sections.CommentSubject(
            notes.note_key("material", "c1"), "material", "X", "Karma",
            category="Metal", colour=""))
        self.assertEqual("material/Metal",
                         self.widget.section_label.text())
        self.widget.set_subject(
            sections.CommentSubject(notes.note_key("material", "c2"), "material", "X", "Karma",
                category="Metal", colour="#ff8800"))
        text = self.widget.section_label.text()
        self.assertIn("#ff8800", text)
        self.assertIn("<b>", text)
        self.assertIn("Metal", text)

    def test_the_inset_scrolls_with_the_text(self):
        """The 12px under the header is DOCUMENT margin, not chrome:
        unscrolled text starts 12px down, scrolled text passes through
        that zone to the border."""
        from amaze.helpers import theme
        edit = self.widget.text_edit
        self.assertEqual(theme.ui_px(12),
                         edit.document().documentMargin(),
                         "the inset left the document")
        body_margins = self.widget.body_widget.layout().contentsMargins()
        self.assertEqual(0, body_margins.top(),
                         "chrome margin is back - scrolled text will "
                         "vanish at the gap instead of passing under "
                         "the header")

    def test_a_save_announces_its_key(self):
        key = self._subject("14")
        heard = []
        self.widget.changed.connect(heard.append)
        cursor = self.widget.text_edit.textCursor()
        cursor.insertText("hello")
        self.widget.flush()
        self.assertEqual([key], heard,
                         "the grid never hears about the new badge")


class ModelRoleTest(unittest.TestCase):
    """NotesRole is the badge's question, answered by the real models."""

    def setUp(self):
        notes.forget_notes()
        self.addCleanup(notes.forget_notes)

    def test_file_rows_answer_by_path(self):
        from amaze.core import file_library
        prefs = _Prefs(self)
        prefs.file_folders = []
        prefs.file_favorites = []
        prefs.file_recursive_folders = []
        prefs.file_folder_names = {}
        prefs.file_show_unknown = True
        prefs.last_file_folder = ""
        prefs.rendersize = 256
        prefs.icon_line_weight = "template"
        prefs.texture_parallel_conversions = 1
        prefs.geometry_shading_mode = "hiddenlineghost"
        prefs.geometry_bg = "black"
        folder = tempfile.mkdtemp(prefix="amaze_notes_files_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with open(os.path.join(folder, "walk.bvh"), "w") as handle:
            handle.write("x")
        model = file_library.FileFiles(prefs)
        model.set_folder(folder)
        index = model.index(0, 0)
        self.assertFalse(model.data(index, model.NotesRole))
        notes.set_note(
            prefs, notes.note_key("file", model.file_key(0)),
            [{"t": "text", "text": "mocap for the intro"}])
        self.assertTrue(model.data(index, model.NotesRole),
                        "the badge cannot see the note")

    def test_asset_rows_answer_by_section_and_id(self):
        from amaze.core import cop_library
        test_support.reset_database_singletons()
        prefs = test_support.fixture_prefs(self)
        prefs.render_on_import = 0
        model = cop_library.CopLibrary(preferences=prefs)
        lop = hou.node("/obj").createNode("lopnet", "notes_src")
        self.addCleanup(lop.destroy)
        lop.createNode("sphere")
        model.add_asset(lop, "", "", False, name="NoteMe")
        row = len(model.assets) - 1
        index = model.index(row, 0)
        self.assertFalse(model.data(index, model.NotesRole))
        asset_id = model.data(index, model.IdRole)
        notes.set_note(prefs,
                       notes.note_key(model.NOTES_SECTION, asset_id),
                       [{"t": "todo", "label": "needs a category",
                         "done": False}])
        self.assertTrue(model.data(index, model.NotesRole))

    def test_the_badge_renders_the_family_art_as_drawn(self):
        """AS DRAWN: what reaches the tile is the ARTWORK, with no
        colour substitution in code (the star-colour re-tint that used
        to sit here is gone, and must not come back).

        Proven against the file rather than against named colours: the
        rendered badge must paint in colours the SVG itself declares.
        That holds through every redraw - and a re-tint, which paints
        colours the file never mentions, still fails.
        """
        from amaze.panel import delegates
        declared = test_support.art_colours("badge_comment")
        pixmap = delegates.AssetItemDelegate._badge_pixmap(
            "badge_comment", 24)
        image = pixmap.toImage()
        painted = set()
        for x in range(image.width()):
            for y in range(image.height()):
                colour = image.pixelColor(x, y)
                # Edge pixels are blends of the art and the
                # transparent ground; only fully-covered pixels say
                # what the art's own colours are.
                if colour.alpha() > 250:
                    painted.add(colour.name())
        found = bool(painted & declared)
        self.assertTrue(found,
                        "the family disc (black at 75%) is not in the "
                        "note badge as drawn")

    def test_the_star_preference_has_no_path_into_the_badge(self):
        """As drawn was the design call - declining the per-badge
        colour option. The old colour push (set_star_color) must stay
        deleted so the preference cannot quietly re-tint a corner; it
        colours only the notes button and pane now."""
        from amaze.panel import delegates
        self.assertFalse(
            hasattr(delegates.AssetItemDelegate, "set_star_color"),
            "the colour push is back - the star preference can reach "
            "the tile badges again")

    def test_every_tile_delegate_carries_the_role(self):
        """Source pin: the badge paints only where notes_role is wired
        - EVERY delegate, because EVERY section takes notes now (Color
        is not special).

        Re-keyed 2026-08-02 from 3 to 4: Node and Code stopped
        borrowing the Materials delegate and got their own, without the
        version roles (they were painting a Version column reading
        "none" on every row, and a badge click there mapped through the
        MATERIAL model). The new one still wires notes_role, which is
        the whole point of this pin - so the number moves and the
        assertion stays.
        """
        import inspect
        from amaze.panel import panel as panel_mod
        source = inspect.getsource(panel_mod)
        self.assertEqual(
            4, source.count("notes_role="),
            "the notes role is wired somewhere new, or a delegate "
            "lost it - the badge follows the wiring")


class GradientNotesTest(unittest.TestCase):
    """Color is NOT special: notes reach gradients like every section.
    Identity is solved, not dodged - a uid stamped on the entry the
    first time a note is opened, synced in gradients.json beside the
    icon that already lives there."""

    def setUp(self):
        notes.forget_notes()
        self.addCleanup(notes.forget_notes)
        test_support.reset_database_singletons()
        self.prefs = test_support.fixture_prefs(self)
        from amaze.core import gradient_library
        self.model = gradient_library.GradientLibrary(
            preferences=self.prefs)
        if not self.model.rowCount():
            self.skipTest("no gradients seeded in the fixture")

    def test_every_gradient_is_born_with_identity(self):
        """Identity from load, not from a feature: after construction
        EVERY entry carries a uid (the backfill pass), and a reload
        reads the same ones back - no stamping on demand anywhere."""
        uids = [self.model.note_uid(row)
                for row in range(self.model.rowCount())]
        self.assertTrue(all(uids),
                        "an entry exists without identity - the "
                        "backfill did not run")
        self.assertEqual(len(uids), len(set(uids)),
                         "identities collide")
        from amaze.core import gradient_library
        test_support.reset_database_singletons()
        reloaded = gradient_library.GradientLibrary(
            preferences=self.prefs)
        self.assertEqual(uids[0], reloaded.note_uid(0),
                         "the identity did not survive a reload - "
                         "notes will orphan")

    def test_a_saved_gradient_carries_identity_at_birth(self):
        self.model.add_user_gradient(
            "BirthTest", "", {"values": [[0.1, 0.2, 0.3]],
                              "keys": [0.0], "bases": ["Constant"]})
        row = next(r for r in range(self.model.rowCount())
                   if self.model.entry(r).get("name") == "BirthTest")
        self.addCleanup(self.model.remove_user_gradient, row)
        self.assertTrue(self.model.note_uid(row),
                        "a freshly saved gradient has no identity - "
                        "birth is where every section stamps it")
        # ONE mint across the app: the full uuid4 hex the asset family
        # stamps (core/material.py). Early libraries carry 12-char
        # uids - those stay valid keys, but every NEW birth is 32.
        self.assertEqual(32, len(self.model.note_uid(row)),
                         "the gradient mint is not the asset family's "
                         "full uuid4 hex")

    def test_a_gradient_note_roundtrips_and_badges(self):
        uid = self.model.note_uid(0)
        key = notes.note_key("gradient", uid)
        index = self.model.index(0, 0)
        self.assertFalse(self.model.data(index, self.model.NotesRole))
        notes.set_note(self.prefs, key,
                       [{"t": "todo", "label": "swap the third band",
                         "done": False}])
        self.assertTrue(self.model.data(index, self.model.NotesRole),
                        "the badge cannot see a gradient's note")

    def test_an_unstamped_gradient_reads_no_note_without_saving(self):
        """data() is a paint path - it must never stamp uids (a save
        per repaint) and an identity-less entry simply has no note."""
        row = self.model.rowCount() - 1
        entry = self.model.entry(row)
        entry.pop("uid", None)
        index = self.model.index(row, 0)
        self.assertFalse(self.model.data(index, self.model.NotesRole))
        self.assertNotIn("uid", entry,
                         "a paint-path read stamped an identity - "
                         "identity work belongs to load and birth")


class PanelWiringTest(unittest.TestCase):
    """The real panel: button toggles, pane follows the selection."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(
            test_support.class_scope(cls))

    def test_the_toggle_shows_persists_and_hides(self):
        panel = self.panel
        # isHidden, not isVisible - the never-shown-parent trap.
        self.assertTrue(panel.notes_panel.isHidden(),
                        "the pane is open before its button was ever "
                        "pressed")
        panel.toggle_notes_panel()
        self.assertFalse(panel.notes_panel.isHidden())
        self.assertTrue(panel.prefs.show_notes,
                        "visibility does not persist")
        panel.toggle_notes_panel()
        self.assertTrue(panel.notes_panel.isHidden())
        self.assertFalse(panel.prefs.show_notes)

    def test_the_chip_and_pane_agree_and_the_lit_colour_is_COMMENT_INK(self):
        """The button IS the pane's state, and its lit tint is the
        theme's own star token - FIXED since the star-colour rows left
        Preferences (2026-08-01): the tile star renders as drawn, so a
        colour preference had nothing left to colour, and the old
        _effective_star_color plumbing went with it."""
        panel = self.panel
        self.assertFalse(
            hasattr(type(panel), "_effective_star_color"),
            "the preference plumbing is back - the star rows were "
            "removed from Preferences, nothing may read them")
        self.assertEqual(panel.prefs.show_notes,
                         panel.btn_notes.isChecked())
        panel.toggle_notes_panel()
        self.addCleanup(panel.toggle_notes_panel)
        self.assertTrue(panel.btn_notes.isChecked())
        self.assertFalse(panel.notes_panel.isHidden())
        from amaze.helpers import ui_helpers as uih
        from amaze.panel import notes_panel as notes_pane
        panel._sync_notes_button_pixmaps()
        blue_name = QtGui.QColor(uih.IconMenuButton.IDLE_BODY).name()
        art_name = QtGui.QColor(notes_pane.COMMENT_INK).name()
        image = panel.btn_notes._pms[(True, False)].toImage()
        seen = {image.pixelColor(x, y).name()
                for x in range(0, image.width(), 4)
                for y in range(0, image.height(), 4)
                if image.pixelColor(x, y).alpha() > 40}
        self.assertIn(
            blue_name, seen,
            "the checked chip is not the toolbar's blue - it must not "
            "go white when on")
        self.assertNotIn(
            QtGui.QColor(uih.IconMenuButton.LIT_BODY).name(), seen,
            "the checked chip went white; blue in all four states")
        # AND NOT its own blue. The tint map replaces a literal, so a
        # map keyed on a colour the art no longer contains matches
        # nothing and the chip renders raw - which is exactly how it
        # shipped blue in all four states.
        self.assertNotIn(
            art_name, seen,
            "the chip is painting the Comments blue - the tint map is "
            "keyed on a colour this art does not contain, so it is "
            "doing nothing")

    def test_the_pane_wears_the_category_lists_look(self):
        """The reuse directive, pinned: font and text colour are CLONED
        from the category list - identical by construction, and the
        measured sizes prove it."""
        panel = self.panel
        # DRIVE the clone, don't observe a coincidence: headless, the
        # default fonts already agree, so a skipped clone would pass a
        # bare equality check (the vacuous-test lesson). A distinctive
        # size proves the pane actually FOLLOWS the category list.
        original = QtGui.QFont(panel.cat_list.font())
        self.addCleanup(panel.cat_list.setFont, original)
        distinctive = QtGui.QFont(original)
        distinctive.setPointSizeF(17.5)
        panel.cat_list.setFont(distinctive)
        panel.notes_panel.adopt_look(panel.cat_list)
        self.addCleanup(panel.notes_panel.adopt_look, panel.cat_list)
        note_font = panel.notes_panel.text_edit.font()
        self.assertEqual(17.5, note_font.pointSizeF(),
                         "pane %.1fpt after the category list moved to "
                         "17.5pt - the pane does not follow its sibling"
                         % note_font.pointSizeF())
        self.assertEqual(distinctive.family(), note_font.family())
        from PySide6 import QtGui as G
        self.assertEqual(
            panel.cat_list.palette().color(G.QPalette.ColorRole.Text),
            panel.notes_panel.text_edit.palette().color(
                G.QPalette.ColorRole.Text),
            "the pane's text colour is not the category list's")

    def test_the_pane_launches_at_450(self):
        """A launch width, deliberately NOT a maximum: sizeHint drives
        the splitter's first layout, dragging stays free."""
        from amaze.helpers import theme
        # The hint prefers a REMEMBERED width; 450 is the never-dragged
        # default, so pin it against a clean pref.
        self.addCleanup(
            setattr, self.panel.prefs, "notes_panel_width",
            self.panel.prefs.notes_panel_width)
        self.panel.prefs.notes_panel_width = 0
        hint = self.panel.notes_panel.sizeHint().width()
        self.assertEqual(theme.ui_px(450), hint)
        self.assertGreater(
            self.panel.notes_panel.maximumWidth(), theme.ui_px(1000),
            "a maximum width crept in - 450 is the LAUNCH width only")

    def test_the_accent_push_is_harmless_now_that_it_does_nothing(self):
        """Comments has its OWN colour from 2026-08-01, so there is no
        accent for the sync to push. The method stays as a no-op
        because the panel still calls it on every accent change and on
        rebuild, and a missing method there is an AttributeError
        inside a signal handler - a crash where there should be
        nothing at all. This pins that it survives the call."""
        panel = self.panel
        panel.notes_panel.set_note_accent("#123456")
        panel._sync_notes_button_pixmaps()
        self.assertFalse(
            hasattr(panel.notes_panel, "_accent"),
            "the pane is carrying an accent again - Comments has one "
            "fixed colour, and two sources for it will drift")

    def test_a_drag_remembers_and_the_pane_asks_for_it_back(self):
        """The width preference: a splitter drag records the pane's
        width, and the pane ASKS for that width from then on.

        The asking is a sizeHint now, the same one the sidebar has
        always used (ui_helpers.HeldPane) - it used to be a `shown`
        signal into fifty lines of splitter arithmetic on the panel,
        which measured identical to doing nothing. That the width
        actually lands when the pane opens is pinned end-to-end in
        test_comments_area."""
        panel = self.panel
        panel.toggle_notes_panel()
        self.addCleanup(panel.toggle_notes_panel)
        # The pref is shared fixture state - leave it as found, or the
        # launch-width test reads this test's leftovers.
        self.addCleanup(
            setattr, panel.prefs, "notes_panel_width",
            panel.prefs.notes_panel_width)
        pane = panel.notes_panel
        splitter = pane.parentWidget()
        index = splitter.indexOf(pane)
        # Headless the splitter never laid out - give it real
        # geometry, or this pin silently skips (a skipped pin is how
        # the accent wiring died unnoticed).
        splitter.resize(1200, 500)
        seed = [200] * splitter.count()
        seed[index] = 400
        splitter.setSizes(seed)
        sizes = splitter.sizes()
        self.assertTrue(any(sizes),
                        "the splitter still has no geometry - this "
                        "pin is not pinning")
        panel._on_splitter_moved(0, 0)
        self.assertEqual(sizes[index], panel.prefs.notes_panel_width,
                         "the drag was not recorded")
        # And the pane asks for it back - what a stretch-0 splitter
        # pane is given is exactly what its sizeHint requests.
        panel.prefs.notes_panel_width = 333
        self.assertEqual(333, pane.sizeHint().width(),
                         "the pane does not ask for the width it was "
                         "dragged to, so opening it lands somewhere "
                         "else")

    def test_the_sidebar_launches_at_its_design_width(self):
        """The other half of the one-flexible-pane construction: a
        stretch-0 pane gets exactly its sizeHint at launch, so each
        side pane must ASK for its width. The notes pane always did;
        the sidebar asked for nothing and launched at whatever
        cat_list's bare hint happened to be - the live report."""
        from amaze.helpers import theme
        panel = self.panel
        self.addCleanup(
            setattr, panel.prefs, "sidebar_width",
            panel.prefs.sidebar_width)
        panel.prefs.sidebar_width = 0
        self.assertEqual(theme.ui_px(220),
                         panel.cat_wrapper.sizeHint().width(),
                         "the never-dragged sidebar does not ask for "
                         "its design width")
        panel.prefs.sidebar_width = 187
        self.assertEqual(187, panel.cat_wrapper.sizeHint().width(),
                         "a remembered drag does not drive the "
                         "sidebar's launch width")

    def test_a_drag_remembers_the_sidebar_too(self):
        """_on_splitter_moved records BOTH side panes now - the
        sidebar's width was unrecorded, so there was nothing to
        remember across sessions."""
        panel = self.panel
        splitter = panel.notes_panel.parentWidget()
        splitter.resize(1200, 500)
        side_i = splitter.indexOf(panel.cat_wrapper)
        self.assertGreaterEqual(side_i, 0,
                                "the sidebar left the splitter")
        seed = [200] * splitter.count()
        seed[side_i] = 190
        splitter.setSizes(seed)
        real = splitter.sizes()[side_i]
        self.assertGreater(real, 0,
                           "the splitter has no geometry - this pin "
                           "is not pinning")
        self.addCleanup(
            setattr, panel.prefs, "sidebar_width",
            panel.prefs.sidebar_width)
        panel.prefs.sidebar_width = 0
        panel._on_splitter_moved(0, 0)
        self.assertEqual(real, panel.prefs.sidebar_width,
                         "the sidebar drag was not recorded")

    def test_one_flexible_pane_is_the_construction(self):
        """The unified rule for the three sections (2026-08-01): the
        sidebar and the notes pane HOLD their width, the grid is the
        splitter's ONLY flexible pane - so every redistribution Qt
        performs (the notes toggle, window resizes) lands on the grid
        alone. This replaced a hand-rolled sidebar capture-and-restore
        that fought the redistribution instead of turning it off, and
        lost live (the width walked on every toggle)."""
        panel = self.panel
        splitter = panel.notes_panel.parentWidget()
        stretches = [
            splitter.widget(i).sizePolicy().horizontalStretch()
            for i in range(splitter.count())]
        flexible = [i for i, s in enumerate(stretches) if s > 0]
        self.assertEqual(1, len(flexible),
                         "the splitter must have exactly ONE flexible "
                         "pane (the grid) - stretches are %s"
                         % stretches)
        held = (splitter.indexOf(panel.cat_wrapper),
                splitter.indexOf(panel.notes_panel))
        self.assertNotIn(flexible[0], held,
                         "a side pane is the flexible one - the grid "
                         "must absorb every width change")

    def test_the_construction_holds_the_sidebar_through_toggles(self):
        """The mechanism, proven end to end on a top-level replica
        built to the SAME rule (stretch 0/1/0, capped side pane):
        Qt's own redistribution leaves the held pane untouched
        through hide, reshow and a window resize. Together with the
        construction pin above this closes the chain the old
        machinery never could."""
        split = QtWidgets.QSplitter()
        side, grid, notes = (QtWidgets.QWidget() for _ in range(3))
        for w in (side, grid, notes):
            split.addWidget(w)
        self.addCleanup(split.deleteLater)
        from amaze.helpers import theme
        side.setMaximumWidth(theme.ui_px(220))
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        notes.hide()
        split.resize(1200, 500)
        split.show()
        app = QtWidgets.QApplication.instance()
        app.processEvents()
        split.setSizes([220, 980, 0])
        app.processEvents()
        before = split.sizes()[0]
        self.assertGreater(before, 0, "the replica never laid out")
        notes.show()
        app.processEvents()
        self.assertEqual(before, split.sizes()[0],
                         "showing the third pane taxed the held one")
        split.setSizes([before, 530, 450])
        app.processEvents()
        notes.hide()
        app.processEvents()
        self.assertEqual(before, split.sizes()[0],
                         "hiding the third pane refunded into the "
                         "held one")
        self.assertEqual(0, split.sizes()[2],
                         "the hidden pane kept width the grid should "
                         "have absorbed")
        split.resize(1500, 500)
        app.processEvents()
        self.assertEqual(before, split.sizes()[0],
                         "a window resize grew the held pane")

    def test_the_hand_rolled_restore_stays_deleted(self):
        """Source ban: the capture-and-restore machinery must not
        return - it patched the symptom of the wrong construction and
        lost to Qt's own deferred relayout live."""
        import inspect
        from amaze.panel import panel as panel_mod
        source = inspect.getsource(panel_mod)
        for banned in ("_sidebar_keep", "_restore_sidebar_width",
                       "_sidebar_width_now"):
            self.assertNotIn(banned, source,
                             "'%s' is back in panel.py - hold the "
                             "panes by construction, not bookkeeping"
                             % banned)

    def test_the_gradient_section_reaches_the_pane(self):
        """The carve-out must never return: a selected gradient yields
        a real subject - gradient:<uid> key, section line, name."""
        panel = self.panel
        model = panel.gradient_sorted_model
        if not model.rowCount():
            self.skipTest("no gradients in the fixture library")
        panel._on_tab_toggled("gradient", True)
        self.addCleanup(panel._on_tab_toggled, "material", True)
        index = model.index(0, 0)
        panel.thumblist.setCurrentIndex(index)
        subject = panel._notes_subject()
        self.assertIsNotNone(subject,
                             "Color is being treated as special again")
        self.assertTrue(subject[0].startswith("gradient:"))
        self.assertEqual("color", subject[1])

    def test_the_pane_follows_a_material_selection(self):
        panel = self.panel
        model = panel.material_sorted_model
        if not model.rowCount():
            self.skipTest("no materials in the fixture library")
        panel._on_tab_toggled("material", True)
        panel.toggle_notes_panel()
        self.addCleanup(panel.toggle_notes_panel)
        index = model.index(0, 0)
        panel.thumblist.setCurrentIndex(index)
        panel.material_selection_model.select(
            index, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        panel._refresh_notes_subject()
        shown = panel.notes_panel.name_label.text()
        expected = index.data(QtCore.Qt.ItemDataRole.DisplayRole)
        self.assertEqual(expected, shown,
                         "the pane does not follow the selection")
        self.assertEqual("material",
                         panel.notes_panel.section_label.text())


class VersionsBadgeHoverTest(unittest.TestCase):
    """The versions badge is the one BUTTON on a tile, so it alone
    answers the pointer: a lighter disc under the cursor and a
    tooltip naming what a click does (2026-08-01).

    These DRIVE the delegate rather than reading panel.py. A previous
    badge test asserted that a method body mentioned `icon_side` and
    stayed green through a sabotage that deleted the clamp using it
    (practice.md, 2026-07-29); the property here is a DECISION - is
    this point on the badge, which art comes back - so the test makes
    the decision happen and records what it decided."""

    ROLE = QtCore.Qt.ItemDataRole.UserRole + 77

    def _delegate(self):
        from amaze.panel import delegates
        return delegates.AssetItemDelegate(
            QtCore.Qt.ItemDataRole.UserRole + 78,   # subtitle_role
            versions_role=self.ROLE)

    def _index(self, versions):
        model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem("mat")
        item.setData(versions, self.ROLE)
        model.appendRow(item)
        self._model = model                 # keep it alive
        return model.index(0, 0)

    def test_the_badge_answers_only_inside_itself(self):
        delegate = self._delegate()
        index = self._index(3)
        rect = QtCore.QRect(0, 0, 120, 140)
        badge = delegate._versions_badge_rect(rect, True)
        self.assertTrue(
            delegate.versions_badge_at(index, rect, badge.center(), True),
            "the badge does not answer at its own centre")
        outside = QtCore.QPoint(rect.right() - 2, rect.top() + 2)
        self.assertFalse(
            delegate.versions_badge_at(index, rect, outside, True),
            "the badge answers for a point in the opposite corner")

    def test_a_single_version_asset_has_no_badge_to_hover(self):
        """No badge is painted under two versions, so nothing there
        may claim the pointer - a tooltip over empty pixels is a lie."""
        delegate = self._delegate()
        index = self._index(1)
        rect = QtCore.QRect(0, 0, 120, 140)
        badge = delegate._versions_badge_rect(rect, True)
        self.assertFalse(
            delegate.versions_badge_at(index, rect, badge.center(), True),
            "an asset with one version offers a badge to hover")

    def _painted(self, delegate, index, side=96):
        """What the badge painter actually put on a tile."""
        canvas = QtGui.QPixmap(side, side)
        canvas.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(canvas)
        try:
            delegate._paint_badges(painter, index, 0, 0, side)
        finally:
            painter.end()
        return canvas.toImage()

    def test_hover_swaps_the_art_the_PAINTER_lays_down(self):
        """Drive the paint, not the flag.

        The first version of this test compared the two SVG pixmaps
        and toggled the hover state, and a sabotage that made the
        painter always pick the base art left it green - it never
        asked what got painted. Same shape as the icon_side lesson in
        practice.md, caught the same way: by sabotage."""
        delegate = self._delegate()
        index = self._index(3)

        cold = self._painted(delegate, index)
        delegate.set_versions_hover(index)
        hot = self._painted(delegate, index)

        self.assertFalse(cold.isNull() or hot.isNull())
        self.assertNotEqual(
            cold, hot,
            "the painted badge is identical hovered and not - the "
            "hover art is never chosen, whatever the state says")

    def test_the_hover_state_reports_changes_once(self):
        delegate = self._delegate()
        index = self._index(3)
        self.assertFalse(delegate._is_versions_hovered(index))
        self.assertTrue(delegate.set_versions_hover(index),
                        "setting a new hover reported no change")
        self.assertTrue(delegate._is_versions_hovered(index))
        self.assertFalse(delegate.set_versions_hover(index),
                         "re-setting the SAME hover reported a change - "
                         "every mouse move would repaint the grid")
        self.assertTrue(delegate.set_versions_hover(QtCore.QModelIndex()))
        self.assertFalse(delegate._is_versions_hovered(index))

    def test_the_tooltip_says_what_a_click_does(self):
        from amaze.helpers import ui_helpers
        from amaze.panel import delegates
        import inspect
        body = inspect.getsource(delegates.AssetItemDelegate.helpEvent)
        self.assertIn("Click to select version", body)
        # It must go through the shared cap, not raw setToolTip: a
        # plain-text tooltip renders as one endless line (research.md).
        self.assertIn("ui_helpers.tooltip_text", body)
        self.assertTrue(
            ui_helpers.tooltip_text("Click to select version"),
            "the shared tooltip helper returned nothing")


if __name__ == "__main__":
    unittest.main()
