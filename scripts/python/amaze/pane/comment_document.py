"""A comment's document, for either host: plain, to-do and picture blocks, their keys, their items."""

from __future__ import annotations

import os
import uuid

from PySide6 import QtCore, QtGui

from amaze import amazetheme
from amaze.core import notes

DRAWN = amazetheme.drawn_comments()    # every size and spacing below is from the N01 design frame

STATE_PLAIN = 0    # a block's kind, kept in its format so that undo takes it back ▸r/qt-text-checklists
STATE_TODO = 1
STATE_DONE = 2
STATE_UNLOADED = 4    # a picture whose file did not load: text replaces it, `src` is stored on the block
_STATE = QtGui.QTextFormat.Property.UserProperty.value + 3
_UNLOADED_SRC = QtGui.QTextFormat.Property.UserProperty.value + 1
_UNLOADED_TEXT = QtGui.QTextFormat.Property.UserProperty.value + 2
_ITEM_ID = QtGui.QTextFormat.Property.UserProperty.value + 4    # the id of a block's item
PICTURE_INSET = 24    # px of the editor's width a picture leaves free
PICTURE_LEAST = 80    # px: a picture is never narrower, however narrow the editor

ENTER_KEYS = (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter)


def block_state(block) -> int:
    """The block's kind; a new block takes the one above it, a merged block the upper one's."""
    return block.blockFormat().intProperty(_STATE)


def is_todo_block(block) -> bool:
    return block_state(block) in (STATE_TODO, STATE_DONE)


def is_image_block(block) -> bool:
    """A block that holds a picture. ▸p/comment-images"""
    return bool(image_src(block))


def block_done(block) -> bool:
    return block_state(block) == STATE_DONE


def block_id(block) -> str:
    """The id of the item the block is part of; a new block takes the one above, as its state."""
    return str(block.blockFormat().property(_ITEM_ID) or "")


def block_label(block) -> str:
    return block.text().strip()


def unloaded_picture(block):
    """The picture item an unloaded block replaces; None once its text has been edited out."""
    if block_state(block) != STATE_UNLOADED:
        return None
    block_format = block.blockFormat()
    shown = str(block_format.property(_UNLOADED_TEXT) or "")
    if not shown or shown not in block.text():
        return None
    return {"t": "image", "src": str(block_format.property(_UNLOADED_SRC) or ""), "text": shown}


def image_src(block) -> str:
    """The library-relative path an image block draws, or "", read off the fragment. ▸p/comment-images"""
    iterator = block.begin()
    while not iterator.atEnd():
        char_format = iterator.fragment().charFormat()
        if char_format.isImageFormat():
            return char_format.toImageFormat().name()
        iterator += 1
    return ""


def label_format(done: bool) -> QtGui.QTextCharFormat:
    fmt = QtGui.QTextCharFormat()   # strike-through only; the colour is the editor's
    fmt.setFontStrikeOut(bool(done))
    return fmt


class CommentDocument(QtCore.QObject):
    """The blocks of one QTextDocument, worked on by cursor positions; the editor draws the glyphs."""

    states_changed = QtCore.Signal()    # a block became a to-do, done, open or plain: its glyph changed

    def __init__(self, document, px=lambda value: value, room=lambda: 0) -> None:
        super().__init__(document)    # deleted with the document
        self.document = document
        self._px = px    # a design px in the editor's px
        self._room = room    # the editor's width in its px, which a picture fits
        self.library_dir = ""    # what an image's relative `src` resolves against
        self.note_key = ""    # whose folder a `$AMAZEASSET/` picture is in

    def _cursor(self, position: int, anchor: int = -1) -> QtGui.QTextCursor:
        cursor = QtGui.QTextCursor(self.document)
        cursor.setPosition(anchor if anchor >= 0 else position)
        cursor.setPosition(position, QtGui.QTextCursor.MoveMode.KeepAnchor)
        return cursor

    def _block_format(self, state: int) -> QtGui.QTextBlockFormat:
        """A block's format for `state`: a to-do has padding above and below and the glyph's margin."""
        todo = state in (STATE_TODO, STATE_DONE)
        fmt = QtGui.QTextBlockFormat()   # no background
        fmt.setBackground(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
        fmt.setTopMargin(self._px(DRAWN["todo_pad"]) if todo else 0)
        fmt.setBottomMargin(self._px(DRAWN["todo_pad"]) if todo else 0)
        fmt.setLeftMargin(self._px(DRAWN["todo_indent"]) if todo else 0)
        fmt.setProperty(_STATE, state)
        return fmt

    def _set_state(self, block, state: int) -> None:
        """Make `block` plain, an open or a done to-do: its state, its look and its glyph."""
        cursor = QtGui.QTextCursor(block)
        cursor.beginEditBlock()    # one undo takes back the state and the look together
        cursor.mergeBlockFormat(self._block_format(state))
        cursor.select(QtGui.QTextCursor.SelectionType.BlockUnderCursor)
        cursor.mergeCharFormat(label_format(state == STATE_DONE))
        cursor.endEditBlock()
        self.states_changed.emit()

    def _set_todo(self, block, done: bool) -> None:
        self._set_state(block, STATE_DONE if done else STATE_TODO)

    def toggle(self, number: int) -> bool:
        """Flip the done state of the to-do in block `number`. Returns whether it was one."""
        block = self.document.findBlockByNumber(number)
        if not block.isValid() or not is_todo_block(block):
            return False
        self._set_todo(block, not block_done(block))
        return True

    def insert_todo(self, position: int) -> int:
        """A to-do at `position`: an empty plain block converts in place, else a new one below."""
        cursor = self._cursor(position)
        block = cursor.block()
        cursor.beginEditBlock()
        if is_todo_block(block) or block.text().strip():
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertBlock()
        self._set_todo(cursor.block(), False)
        cursor.endEditBlock()
        return cursor.position()

    def _make_image(self, cursor, src: str) -> bool:
        """Turn the cursor's block into a picture of `src`; False when it will not load. ▸p/comment-images"""
        image = QtGui.QImage(notes.image_path(self.library_dir, self.note_key, src))
        if image.isNull():
            return False
        self.document.addResource(    # the key Qt looks the name up by: its base url resolves it
            QtGui.QTextDocument.ResourceType.ImageResource,
            self.document.baseUrl().resolved(QtCore.QUrl(src)), image)    # the name stays RELATIVE ▸r/qtextdocument-images
        self._set_state(cursor.block(), STATE_PLAIN)
        image_format = QtGui.QTextImageFormat()
        image_format.setName(src)
        width = float(min(image.width(), max(self._room() - self._px(PICTURE_INSET), self._px(PICTURE_LEAST))))
        image_format.setWidth(width)    # never wider than the editor, never upscaled
        image_format.setHeight(image.height() * width / max(image.width(), 1))
        cursor.insertImage(image_format)
        return True

    def insert_image(self, position: int, src: str) -> int:
        """A picture at `position`, the cursor left below it; -1 when its file will not load."""
        cursor = self._cursor(position)
        block = cursor.block()
        cursor.beginEditBlock()
        if is_todo_block(block) or is_image_block(block) or block.text().strip():
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertBlock(self._block_format(STATE_PLAIN))
        if not self._make_image(cursor, src):
            cursor.endEditBlock()
            return -1
        cursor.insertBlock(self._block_format(STATE_PLAIN), label_format(False))    # below the picture ▸p/comment-images
        cursor.endEditBlock()
        return cursor.position()

    def insert_text(self, position: int, anchor: int, text: str) -> int:
        """Pasted or dropped text, as plain text over the selection; the new cursor position."""
        cursor = self._cursor(position, anchor)
        cursor.insertText(text)
        return cursor.position()

    def key(self, key: int, position: int, anchor: int) -> int:
        """What Enter, Backspace or Delete does in or next to a to-do; -1 for the editor's own."""
        cursor = self._cursor(position, anchor)
        if cursor.hasSelection():
            return -1
        block = cursor.block()
        merge = None    # the native edit that joins a line to the to-do above it
        if key == QtCore.Qt.Key.Key_Backspace:
            if is_todo_block(block) and (cursor.atBlockStart() or not block_label(block)):
                self._set_state(block, STATE_PLAIN)   # Backspace at a to-do's start turns it back into plain text
                return cursor.position()
            if cursor.atBlockStart() and is_todo_block(block.previous()):
                merge = cursor.deletePreviousChar
        elif key == QtCore.Qt.Key.Key_Delete:
            if is_todo_block(block) and cursor.atBlockEnd() and block.next().isValid():
                merge = cursor.deleteChar
        elif key in ENTER_KEYS and is_todo_block(block):
            if not block_label(block):
                self._set_state(block, STATE_PLAIN)   # Enter on an EMPTY to-do turns it back into plain text
                return cursor.position()
            cursor.beginEditBlock()
            cursor.insertBlock()
            self._set_todo(cursor.block(), False)   # a new to-do is open, whatever the one above
            cursor.endEditBlock()
            return cursor.position()
        if merge is None:
            return -1
        cursor.beginEditBlock()
        merge()    # the joined block keeps the upper one's state ▸r/qt-text-checklists
        self._set_state(cursor.block(), block_state(cursor.block()))    # its whole label struck as it is
        cursor.endEditBlock()
        return cursor.position()

    def glyphs(self) -> list:
        """Each to-do's glyph and its click zone, in document px."""
        layout = self.document.documentLayout()
        side = self._px(DRAWN["glyph"])
        found = []
        block = self.document.begin()
        while block.isValid():
            if is_todo_block(block):
                rect = layout.blockBoundingRect(block)
                lines = block.layout()   # lineAt() on an un-laid-out block crashes hython natively
                if lines is not None and lines.lineCount() > 0:
                    line = lines.lineAt(0)
                    found.append({
                        "block": block.blockNumber(), "done": block_done(block),
                        "x": rect.left() + self._px(DRAWN["glyph_inset"]),
                        "y": lines.position().y() + line.y() + (line.height() - side) / 2.0,
                        "side": side,
                        "zone": QtCore.QRectF(0, rect.top(), rect.left() + block.blockFormat().leftMargin(),
                                              rect.height())})    # left of the text, the whole block high
            block = block.next()
        return found

    def _insert_unloaded_text(self, cursor, src: str, shown: str) -> None:
        """Insert `shown` in the cursor's block, storing `src` so `serialize` saves the picture."""
        self._set_state(cursor.block(), STATE_UNLOADED)
        block_format = QtGui.QTextBlockFormat()
        block_format.setProperty(_UNLOADED_SRC, src)
        block_format.setProperty(_UNLOADED_TEXT, shown)
        cursor.mergeBlockFormat(block_format)
        cursor.insertText(shown, label_format(False))

    def load(self, library_dir: str, note_key: str, items: list) -> int:
        """Show the items of the comment `note_key`; the end position. The load is not an edit."""
        self.library_dir, self.note_key = library_dir, note_key
        self.document.clear()
        cursor = QtGui.QTextCursor(self.document)
        first = True
        for item in items or []:
            if item.get("t") == "image":
                src = str(item.get("src", ""))
                if not first:
                    cursor.insertBlock(self._block_format(STATE_PLAIN))
                if not self._make_image(cursor, src):    # not synced yet, or deleted: its text ▸p/comment-images
                    self._insert_unloaded_text(cursor, src,
                                               item.get("text") or "[image: %s]" % os.path.basename(src))
                self._mark(cursor.block(), item.get("id"))
            elif item.get("t") == "todo":
                done = bool(item.get("done"))
                if not first:
                    cursor.insertBlock()
                self._set_todo(cursor.block(), done)
                cursor.insertText(item.get("label", ""), label_format(done))
                self._mark(cursor.block(), item.get("id"))
            else:
                for line in str(item.get("text", "")).split("\n"):
                    if not first:
                        cursor.insertBlock()
                    self._set_state(cursor.block(), STATE_PLAIN)
                    cursor.insertText(line, label_format(False))
                    self._mark(cursor.block(), item.get("id"))
                    first = False
            first = False
        self.document.clearUndoRedoStacks()    # the load is not an edit ▸r/programmatic-load-is-undoable
        self.states_changed.emit()
        return cursor.position()

    def _stamp(self, stamps: list) -> None:
        """Each (block, id) `serialize` gave out put on its block, in the last edit for undo."""
        if not stamps:
            return
        cursor = QtGui.QTextCursor(self.document)
        cursor.joinPreviousEditBlock()
        for block, ident in stamps:
            self._mark(block, ident)
        cursor.endEditBlock()

    def _mark(self, block, ident) -> None:
        """`block` made a part of the item `ident`, in its format so that undo takes it back."""
        block_format = QtGui.QTextBlockFormat()
        block_format.setProperty(_ITEM_ID, str(ident or ""))
        QtGui.QTextCursor(block).mergeBlockFormat(block_format)

    def clear(self) -> None:
        self.library_dir, self.note_key = "", ""
        self.document.clear()
        self.document.clearUndoRedoStacks()
        self.states_changed.emit()

    def serialize(self) -> list:
        """The document as the store's item list, each with its id; a new item gets one here."""
        items, text_lines, taken, stamps = [], [], set(), []    # text_lines: (block or None, line)

        def add(item, blocks) -> None:
            """`item` with the id its blocks carry; a new id for a new item or a taken one."""
            blocks = [one for one in blocks if one is not None]
            ident = next((block_id(one) for one in blocks if block_id(one)), "")
            if not ident or ident in taken:    # a block below takes the id of the one above it
                ident = uuid.uuid4().hex
            taken.add(ident)
            stamps.extend((one, ident) for one in blocks if block_id(one) != ident)
            items.append(dict(item, id=ident))

        def flush_text():
            lines = [line for _block, line in text_lines]
            if any(line.strip() for line in lines):    # adjacent plain lines are one item
                add({"t": "text", "text": "\n".join(lines).strip("\n")},
                    [one for one, _line in text_lines])
            text_lines.clear()

        block = self.document.begin()
        while block.isValid():
            picture = unloaded_picture(block)
            if picture is not None:    # its file may appear later: the item is saved unchanged
                flush_text()
                add(picture, [block])
                typed = block.text().replace(picture["text"], "", 1)
                if typed.strip():
                    text_lines.append((None, typed))
            elif is_image_block(block):
                flush_text()
                src = image_src(block)
                if src:    # its text is what a build with no image support shows ▸p/comment-images
                    add({"t": "image", "src": src,
                         "text": "[image: %s]" % os.path.basename(src)}, [block])
                typed = block.text().replace("￼", "")    # text typed in a picture's block; the image is U+FFFC
                if typed.strip():
                    text_lines.append((None, typed))
            elif is_todo_block(block):
                flush_text()
                label = block_label(block)
                if label:
                    add({"t": "todo", "label": label, "done": block_done(block)}, [block])
            else:
                ident = block_id(block)
                if ident and ident != next((block_id(one) for one, _line in text_lines
                                            if one is not None and block_id(one)), ident):
                    flush_text()    # the line of another item
                text_lines.append((block, block.text()))
            block = block.next()
        flush_text()
        self._stamp(stamps)
        return items
