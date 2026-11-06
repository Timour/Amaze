"""The Notes panel: one flowing document of plain and to-do blocks. ▸r/qt-text-checklists"""

from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.core import debug, notes
from amaze.helpers import theme, ui_helpers
from amaze import messages
from amaze import tooltips

COMMENT_INK = amazetheme.COMMENT_INK    # the design's, declared once ▸p/one-design-document

SAVE_DELAY_MS = 600       # a crash loses a sentence at most, and typing is not a write per key

HEADER_BG = amazetheme.COMMENT_HEADER_BG
PAGE_BG = amazetheme.COMMENT_PAGE_BG

_DRAWN = amazetheme.drawn_comments()    # every size and spacing below is N01's ▸r/comments-from-frame


def _fill(widget, hex_color: str) -> None:
    """Background via the palette; a stylesheet on any ancestor restyles the subtree's scrollbars."""
    palette = widget.palette()
    palette.setColor(QtGui.QPalette.ColorRole.Window,
                     QtGui.QColor(hex_color))
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)


def _ink(label, role: str, opacity: float = 1.0) -> None:
    """Label text in one of the theme's text colours, via the palette, same reasoning as _fill."""
    color = QtGui.QColor(theme.color_hex(role))
    color.setAlphaF(opacity)
    palette = label.palette()
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, color)
    label.setPalette(palette)


def _faded(pixmap: QtGui.QPixmap, opacity: float, dpr: float) -> QtGui.QPixmap:
    """`pixmap`, made at ratio `dpr`, at `opacity` on a transparent copy; 1 hands it back."""
    if opacity >= 1.0:
        return pixmap
    faded = QtGui.QPixmap(pixmap.size())
    faded.fill(QtCore.Qt.GlobalColor.transparent)
    faded.setDevicePixelRatio(dpr)
    painter = QtGui.QPainter(faded)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return faded


class _AddButton(QtWidgets.QToolButton):
    """The +: disabled with nothing selected, yet drawn as N01B draws it rather than Houdini's fade."""

    def paintEvent(self, event) -> None:
        if self.isEnabled():
            super().paintEvent(event)
            return
        option = QtWidgets.QStyleOptionToolButton()
        self.initStyleOption(option)
        option.state |= QtWidgets.QStyle.StateFlag.State_Enabled    # Houdini fades a disabled triangle away
        option.state &= ~QtWidgets.QStyle.StateFlag.State_MouseOver
        option.palette.setCurrentColorGroup(QtGui.QPalette.ColorGroup.Active)
        painter = QtWidgets.QStylePainter(self)
        painter.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_ToolButton, option)
        painter.end()

_glyph_cache: dict = globals().get("_glyph_cache", {})   # keyed on every input and survives the reload chain


def _feather_icon(name: str, side: int, ink: str, widget=None) -> QtGui.QPixmap:
    """One Feather glyph re-inked at device resolution; pass the widget being painted. ▸r/screen-dpr"""
    import amaze
    dpr = theme.screen_ratio(widget)
    key = (name, int(side), str(ink), float(dpr))   # EVERY input in the key: ink changes per to-do state, dpr when the window moves screen
    cached = _glyph_cache.get(key)
    if cached is not None:
        return cached
    path = amaze.package_file("ui", "feather", name + ".svg")
    pixmap = ui_helpers.device_pixmap(path, side, dpr, {"currentColor": ink})
    _glyph_cache[key] = pixmap
    return pixmap


STATE_TODO = 1   # each block's userState; not inherited across Enter ▸r/qt-text-checklists
STATE_DONE = 2
STATE_IMAGE = 3   # a picture block: ONE image fragment, no text of its own ▸p/comment-images
STATE_UNLOADED = 4    # a picture whose file would not load: words stand in, `src` rides on the block
_UNLOADED_SRC = QtGui.QTextFormat.Property.UserProperty.value + 1
_UNLOADED_TEXT = QtGui.QTextFormat.Property.UserProperty.value + 2

IMAGE_DIR = "img/comments"    # inside the library, beside the thumbnails `img/` already holds ▸p/comment-images

ADD_ITEMS = (    # what the + offers, in order - a new item type joins by adding ONE line here ▸p/comment-images
    ("Bullet point", "_add_todo"),
    ("Image", "_add_image"),
)


class _NoteEdit(QtWidgets.QTextEdit):
    """The flowing document: plain paragraphs and to-do blocks interleave freely."""

    GLYPH_SPACE = _DRAWN["todo_indent"]   # left margin reserved on to-do blocks, where the glyph paints
    GLYPH_SIDE = _DRAWN["glyph"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        palette = self.palette()   # no stylesheet: the background goes through the palette
        palette.setColor(QtGui.QPalette.ColorRole.Base,
                         QtGui.QColor(0, 0, 0, 0))
        self.setPalette(palette)
        self.setAcceptRichText(False)    # PASTING only - a programmatic insertImage still works ▸r/qtextdocument-images
        self.library_dir = ""            # set by the panel; what an image's relative `src` resolves against
        self.setPlaceholderText("Write a comment...")
        self.viewport().setMouseTracking(True)   # the hover cursor swap needs move events with no button held

    @staticmethod
    def is_todo_block(block) -> bool:
        return block.userState() in (STATE_TODO, STATE_DONE)

    @staticmethod
    def is_image_block(block) -> bool:
        return block.userState() == STATE_IMAGE

    @staticmethod
    def unloaded_picture(block):
        """The picture item an unloaded block stands in for; None once its words are edited away."""
        if block.userState() != STATE_UNLOADED:
            return None
        held = block.blockFormat()
        shown = str(held.property(_UNLOADED_TEXT) or "")
        if not shown or shown not in block.text():
            return None
        return {"t": "image", "src": str(held.property(_UNLOADED_SRC) or ""), "text": shown}

    def _stand_in(self, cursor, src: str, shown: str) -> None:
        """`shown` in the cursor's block, holding `src` so `serialize` writes the picture back."""
        block = cursor.block()
        block.setUserState(STATE_UNLOADED)
        self._restyle_block(block, False, False)
        held = QtGui.QTextBlockFormat()
        held.setProperty(_UNLOADED_SRC, src)
        held.setProperty(_UNLOADED_TEXT, shown)
        cursor.mergeBlockFormat(held)
        cursor.insertText(shown, self._label_format(False))

    @staticmethod
    def image_src(block) -> str:
        """The library-relative path an image block draws, or "", read off the fragment. ▸p/comment-images"""
        iterator = block.begin()
        while not iterator.atEnd():
            char_format = iterator.fragment().charFormat()
            if char_format.isImageFormat():
                return char_format.toImageFormat().name()
            iterator += 1
        return ""

    def make_image_here(self, cursor, src: str) -> bool:
        """Turn the cursor's block into a picture of `src`; False when it will not load. ▸p/comment-images"""
        image = QtGui.QImage(self.resolve_image(src))
        if image.isNull():
            return False
        self.document().addResource(
            QtGui.QTextDocument.ResourceType.ImageResource,
            QtCore.QUrl(src), image)    # keyed by the RELATIVE path, so the same key works on every machine ▸r/qtextdocument-images
        block = cursor.block()
        block.setUserState(STATE_IMAGE)
        self._restyle_block(block, False, False)
        image_format = QtGui.QTextImageFormat()
        image_format.setName(src)
        width = self._image_width(image)
        image_format.setWidth(width)
        image_format.setHeight(image.height() * width / max(image.width(), 1))
        cursor.insertImage(image_format)
        self.setTextCursor(cursor)
        return True

    def insert_image(self, src: str) -> bool:
        """A picture at the cursor: an empty plain block becomes it, else a new block below."""
        cursor = self.textCursor()
        block = cursor.block()
        if self.is_todo_block(block) or self.is_image_block(block) \
                or block.text().strip():
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertBlock(self._plain_format())
        if not self.make_image_here(cursor, src):
            return False
        cursor = self.textCursor()    # leave the cursor below the picture, out of its block ▸p/comment-images
        cursor.insertBlock(self._plain_format())
        cursor.block().setUserState(-1)
        cursor.setCharFormat(self._label_format(False))
        self.setTextCursor(cursor)
        return True

    def _image_width(self, image) -> float:
        """Never wider than the pane, never upscaled."""
        room = max(self.viewport().width() - theme.ui_px(24), theme.ui_px(80))
        return float(min(image.width(), room))

    def resolve_image(self, src: str) -> str:
        """A library-relative `src` as an absolute path; the stored form stays relative. ▸p/comment-images"""
        if not src:
            return ""
        if os.path.isabs(src):
            return src
        return os.path.join(self.library_dir or "", src)

    @staticmethod
    def block_done(block) -> bool:
        return block.userState() == STATE_DONE

    @staticmethod
    def block_label(block) -> str:
        return block.text().strip()

    def _todo_format(self) -> QtGui.QTextBlockFormat:
        fmt = QtGui.QTextBlockFormat()   # no background; padding 10px each side plus the glyph margin
        fmt.setBackground(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
        fmt.setTopMargin(theme.ui_px(_DRAWN["todo_pad"]))
        fmt.setBottomMargin(theme.ui_px(_DRAWN["todo_pad"]))
        fmt.setLeftMargin(theme.ui_px(self.GLYPH_SPACE))
        return fmt

    def _plain_format(self) -> QtGui.QTextBlockFormat:
        fmt = QtGui.QTextBlockFormat()
        fmt.setBackground(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
        fmt.setTopMargin(0)
        fmt.setBottomMargin(0)
        fmt.setLeftMargin(0)
        return fmt

    @staticmethod
    def _label_format(done: bool) -> QtGui.QTextCharFormat:
        fmt = QtGui.QTextCharFormat()   # strike-through only; colour comes from the palette adopt_look() clones off the category list
        fmt.setFontStrikeOut(bool(done))
        return fmt

    def _restyle_block(self, block, todo: bool, done: bool) -> None:
        cursor = QtGui.QTextCursor(block)
        cursor.mergeBlockFormat(
            self._todo_format() if todo else self._plain_format())
        cursor.select(QtGui.QTextCursor.SelectionType.BlockUnderCursor)
        cursor.mergeCharFormat(self._label_format(todo and done))

    def _set_todo(self, block, done: bool) -> None:
        """Make `block` a to-do, done or open: its state, its look and the glyph's repaint."""
        block.setUserState(STATE_DONE if done else STATE_TODO)
        self._restyle_block(block, True, done)
        self.viewport().update()

    def make_todo_here(self, cursor, done: bool = False) -> None:
        """Turn the cursor's block into a to-do frame."""
        self._set_todo(cursor.block(), done)
        cursor.setCharFormat(self._label_format(done))
        self.setTextCursor(cursor)

    def make_plain_here(self, cursor) -> None:
        """Turn the cursor's block back into flowing text; the label survives as words."""
        block = cursor.block()
        block.setUserState(-1)
        self._restyle_block(block, False, False)
        cursor.setCharFormat(self._label_format(False))
        self.setTextCursor(cursor)
        self.viewport().update()

    def insert_todo(self) -> None:
        """A to-do at the cursor: an empty plain block converts in place, else a new one below."""
        cursor = self.textCursor()
        block = cursor.block()
        if self.is_todo_block(block) or block.text().strip():
            cursor.movePosition(
                QtGui.QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertBlock()
        self.make_todo_here(cursor, False)
        self.setFocus()

    def toggle_block(self, block) -> bool:
        """Flip one to-do's done state. Returns whether it was one."""
        if not self.is_todo_block(block):
            return False
        self._set_todo(block, not self.block_done(block))
        return True


    def _merge_keeping(self, keeper, event) -> None:
        """Merge across a block separator, keeping the keeper's to-do state. ▸r/qt-text-checklists"""
        done = self.block_done(keeper)
        super().keyPressEvent(event)
        self._set_todo(self.textCursor().block(), done)

    def keyPressEvent(self, event) -> None:
        if event.key() == QtCore.Qt.Key.Key_Backspace:
            cursor = self.textCursor()
            block = cursor.block()
            if (self.is_todo_block(block)
                    and not cursor.hasSelection()
                    and (cursor.atBlockStart()
                         or not self.block_label(block))):
                self.make_plain_here(cursor)   # Backspace at a frame's start unwraps it back to text
                return
            if (not cursor.hasSelection() and cursor.atBlockStart()
                    and self.is_todo_block(block.previous())):
                self._merge_keeping(block.previous(), event)   # backspacing up into a to-do keeps its checkbox
                return
        if (event.key() == QtCore.Qt.Key.Key_Delete
                and not self.textCursor().hasSelection()):
            cursor = self.textCursor()
            block = cursor.block()
            if (self.is_todo_block(block) and cursor.atBlockEnd()
                    and block.next().isValid()):
                self._merge_keeping(block, event)   # forward-Delete at a frame's end pulls the next line in, same rule
                return
        if event.key() in (QtCore.Qt.Key.Key_Return,
                           QtCore.Qt.Key.Key_Enter):
            cursor = self.textCursor()
            block = cursor.block()
            if self.is_todo_block(block):
                if not self.block_label(block):
                    self.make_plain_here(cursor)   # Enter on an EMPTY to-do drops back to text
                    return
                super().keyPressEvent(event)
                self.make_todo_here(self.textCursor(), False)   # a fresh frame: userState does not inherit, so the block above keeps its checkbox
                return
        super().keyPressEvent(event)

    def _glyph_zone_block(self, pos):
        """The to-do block whose checkbox zone contains pos, or None; shared by click and hover."""
        cursor = self.cursorForPosition(pos)
        block = cursor.block()
        if not self.is_todo_block(block):
            return None
        start = QtGui.QTextCursor(block)
        start.setPosition(block.position())
        if pos.x() < self.cursorRect(start).left():
            return block
        return None

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:    # only the left button toggles
            block = self._glyph_zone_block(event.position().toPoint())
            if block is not None and self.toggle_block(block):
                self.textChanged.emit()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not event.buttons():   # a pointing hand over the glyph zone, I-beam elsewhere; only with no button down
            over = self._glyph_zone_block(
                event.position().toPoint()) is not None
            wanted = (QtCore.Qt.CursorShape.PointingHandCursor if over
                      else QtCore.Qt.CursorShape.IBeamCursor)
            if self.viewport().cursor().shape() != wanted:
                self.viewport().setCursor(wanted)
        super().mouseMoveEvent(event)


    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self.viewport())
        try:
            self._paint_todo_glyphs(painter)
        finally:
            painter.end()

    def _paint_todo_glyphs(self, painter) -> None:
        """One glyph per to-do block in its reserved margin: Feather circle or check-circle."""
        layout = self.document().documentLayout()
        x_scroll = self.horizontalScrollBar().value()
        y_scroll = self.verticalScrollBar().value()
        side = theme.ui_px(self.GLYPH_SIDE)
        visible = self.viewport().rect()
        block = self.document().begin()
        while block.isValid():
            if self.is_todo_block(block):
                rect = layout.blockBoundingRect(block)
                top = rect.top() - y_scroll
                if top > visible.bottom():
                    break
                if rect.bottom() - y_scroll >= visible.top():
                    tlayout = block.layout()   # lineAt() on an un-laid-out block crashes hython natively
                    if tlayout is not None and tlayout.lineCount() > 0:
                        line = tlayout.lineAt(0)
                        done = self.block_done(block)
                        pixmap = _feather_icon(
                            "check-circle" if done else "circle", side,
                            amazetheme.COMMENT_DONE_INK if done
                            else amazetheme.COMMENT_OPEN_INK, self)
                        y = (tlayout.position().y() + line.y()
                             + (line.height() - side) / 2.0 - y_scroll)
                        painter.drawPixmap(
                            int(rect.left() - x_scroll + theme.ui_px(_DRAWN["glyph_inset"])),
                            int(y),
                            pixmap)
            block = block.next()


    def load_items(self, items: list) -> None:
        self.clear()
        cursor = self.textCursor()
        first = True
        for item in items or []:
            if item.get("t") == "image":
                src = str(item.get("src", ""))
                if not first:
                    cursor.insertBlock(self._plain_format())
                if self.make_image_here(cursor, src):
                    cursor = self.textCursor()
                else:    # not here yet, or gone: the item's own fallback words, never a blank ▸p/comment-images
                    self._stand_in(cursor, src,
                                   item.get("text") or "[image: %s]" % os.path.basename(src))
                first = False
                continue
            if item.get("t") == "todo":
                done = bool(item.get("done"))
                if not first:
                    cursor.insertBlock()
                self.make_todo_here(cursor, done)
                cursor = self.textCursor()
                cursor.insertText(item.get("label", ""),
                                  self._label_format(done))
            else:
                for line in str(item.get("text", "")).split("\n"):
                    if not first:
                        cursor.insertBlock()
                    cursor.block().setUserState(-1)
                    self._restyle_block(cursor.block(), False, False)
                    cursor.insertText(line, self._label_format(False))
                    first = False
                continue
            first = False
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.document().clearUndoRedoStacks()    # the load is not an edit ▸r/programmatic-load-is-undoable

    def serialize(self) -> list:
        """The document as the store's item flow; adjacent plain lines join into one text item."""
        items = []
        text_lines = []

        def flush_text():
            if text_lines and any(l.strip() for l in text_lines):
                items.append({"t": "text",
                              "text": "\n".join(text_lines).strip("\n")})
            text_lines.clear()

        block = self.document().begin()
        while block.isValid():
            picture = self.unloaded_picture(block)
            if picture is not None:    # its file may arrive later: the item goes back as it came
                flush_text()
                items.append(picture)
                typed = block.text().replace(picture["text"], "", 1)
                if typed.strip():
                    text_lines.append(typed)
            elif self.is_image_block(block):
                flush_text()
                src = self.image_src(block)
                if src:
                    items.append({"t": "image", "src": src,
                                  "text": "[image: %s]"    # what a build with no image support shows instead of a blank line ▸p/comment-images
                                          % os.path.basename(src)})
                typed = block.text().replace("￼", "")    # words typed in a picture's block are content; the image reads as U+FFFC
                if typed.strip():
                    text_lines.append(typed)
            elif self.is_todo_block(block):
                flush_text()
                label = self.block_label(block)
                if label:
                    items.append({"t": "todo", "label": label,
                                  "done": self.block_done(block)})
            else:
                text_lines.append(block.text())
            block = block.next()
        flush_text()
        return items


class NotesPanel(ui_helpers.HeldPane):
    """The dockable page for one asset's notes; saves emit `changed`."""

    changed = QtCore.Signal(str)

    def __init__(self, preferences, parent=None) -> None:
        super().__init__(preferences, "notes_panel_width",
                         theme.ui_px(_DRAWN["width"]), parent)
        self.preferences = preferences
        self._key = None
        self._library = ""    # the library the page was read from, and so the one its saves write to
        self._loading = False
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_now)
        # Houdini quitting reaches no widget event of ours, so the pending 600ms of typing needs aboutToQuit
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.flush)

        self.setMinimumWidth(theme.ui_px(220))
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        page = QtWidgets.QWidget()
        page_box = QtWidgets.QVBoxLayout(page)
        page_box.setContentsMargins(0, 0, 0, 0)
        page_box.setSpacing(0)
        outer.addWidget(page)

        header = QtWidgets.QWidget()
        _fill(header, HEADER_BG)
        header.setFixedHeight(theme.ui_px(_DRAWN["header"]))
        head = QtWidgets.QHBoxLayout(header)    # one row; every item is centred in the drawn height
        head.setContentsMargins(theme.ui_px(_DRAWN["pad"]), 0,
                                theme.ui_px(_DRAWN["add_pad"]), 0)
        head.setSpacing(theme.ui_px(_DRAWN["gap"]))
        self._icon_label = QtWidgets.QLabel()
        head.addWidget(self._icon_label, 0,
                       QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.name_label = QtWidgets.QLabel()
        self.name_label.setFont(   # THE ONE FONT TABLE owns the weight, not this line
            theme.font("comments_title", self.name_label.font()))
        self.name_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)    # the name is an on-disk filename - AutoText would render a tag-shaped one as HTML
        self.type_label = QtWidgets.QLabel()
        self.type_label.setFont(theme.ui_font(self.type_label.font()))    # the name's base, floor included
        self.type_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        head.addWidget(self.name_label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.type_label, 1,    # takes the slack, so the + sits at the right
                       QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.add_button = _AddButton()
        self.add_button.setAutoRaise(True)
        self.add_button.setFixedSize(*(theme.ui_px(side) for side in _DRAWN["add"]))
        self.add_button.setToolTip(tooltips.NOTES_ADD_TODO)
        self.add_button.setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor)
        self._build_add_menu()    # the + opens a menu; InstantPopup never fires `clicked` ▸p/comment-images
        self._paint_accents()
        head.addWidget(self.add_button, 0,
                       QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.header_widget = header
        page_box.addWidget(header)

        body = QtWidgets.QWidget()
        _fill(body, PAGE_BG)
        body_box = QtWidgets.QVBoxLayout(body)
        body_box.setContentsMargins(0, 0, 0, 0)   # zero chrome margins: the inset lives in the document margin
        self.text_edit = _NoteEdit()
        self.text_edit.document().setDocumentMargin(theme.ui_px(_DRAWN["doc_margin"]))
        self.text_edit.textChanged.connect(self._something_changed)
        body_box.addWidget(self.text_edit, 1)
        self.body_widget = body
        page_box.addWidget(body, 1)
        self._ghost = True
        self._show_ghost()

    def _paint_accents(self) -> None:
        import amaze
        dpr = theme.screen_ratio(self)
        side, plus_side = theme.ui_px(_DRAWN["icon"]), theme.ui_px(_DRAWN["plus"])
        dead = getattr(self, "_ghost", False)    # nothing selected: labels and arts as N01B dims them
        text = amazetheme.COMMENT_DIM_TEXT_OPACITY if dead else 1.0
        _ink(self.name_label, "text_bright", text)
        _ink(self.type_label, "text", text)
        self._icon_label.setPixmap(_faded(ui_helpers.device_pixmap(
            amaze.package_file("ui", "icon_comments.svg"), side, dpr,
            {amazetheme.COMMENT_INK: amazetheme.COMMENT_DIM_ICON_INK} if dead else None),
            amazetheme.COMMENT_DIM_ICON_OPACITY if dead else 1.0, dpr))
        self.add_button.setIcon(QtGui.QIcon(ui_helpers.device_pixmap(
            amaze.package_file("ui", "icon_comments_add.svg"), plus_side, dpr,
            {amazetheme.COMMENT_ADD_INK: amazetheme.COMMENT_DIM_ADD_INK} if dead else None)))
        self.add_button.setIconSize(QtCore.QSize(plus_side, plus_side))

    def adopt_look(self, source: QtWidgets.QWidget) -> None:
        """Clone font and text colour from a .ui-loaded sibling."""
        self.text_edit.setFont(source.font())
        palette = self.text_edit.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Text,
                         source.palette().color(
                             QtGui.QPalette.ColorRole.Text))
        self.text_edit.setPalette(palette)
        base = theme.ui_font(source.font())
        self.type_label.setFont(base)
        self.name_label.setFont(theme.font("comments_title", base))


    def set_subject(self, subject) -> None:
        """Point the page at a `sections.CommentSubject`, flushing the previous one's pending edit."""
        key = subject.key
        library = str(getattr(self.preferences, "dir", "") or "")
        if (key, library) == (self._key, self._library):    # a rename: a reload would lose the typing
            self.set_header(subject.name, subject.type)
            return
        self.flush()
        self._key = key
        self._library = library
        self._loading = True
        try:
            self.set_header(subject.name, subject.type)
            note = notes.note_for(self.preferences, key)
            self.text_edit.library_dir = library    # what an image's relative src resolves against ▸p/comment-images
            self.text_edit.load_items(note.get("items", []))
        finally:
            self._loading = False
        self._ghost = False
        self.text_edit.setEnabled(True)
        self.add_button.setEnabled(True)
        self._paint_accents()

    def set_header(self, name: str, type_label: str) -> None:
        """One line: the asset's name in bold, then its type."""
        self.name_label.setText(name)
        self.type_label.setText(type_label)

    def clear_subject(self) -> None:
        self.flush()
        self._key = None
        self._library = ""
        self._show_ghost()

    def _show_ghost(self) -> None:
        """The no-selection look (N01B): the SAME window dimmed, never a different layout."""
        self._ghost = True
        self._loading = True
        try:
            self.set_header(amazetheme.COMMENT_DIM_NAME, amazetheme.COMMENT_DIM_TYPE)
            self.text_edit.clear()
        finally:
            self._loading = False
        self.text_edit.setEnabled(False)
        self.add_button.setEnabled(False)
        self._paint_accents()


    def _build_add_menu(self) -> None:
        """The + menu, hung ONCE: it opens on press; the corner triangle marks it. ▸p/comment-images"""
        menu = QtWidgets.QMenu(self.add_button)    # a CHILD of the button: one menu for the session, not a new one per click ▸r/menu-lifetime
        for label, handler in ADD_ITEMS:
            menu.addAction(label).triggered.connect(    # addAction(str) returns the QAction despite the stub ▸r/menu-lifetime
                getattr(self, handler))
        self.add_button.setMenu(menu)
        self.add_button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)

    def _add_todo(self) -> None:
        if self._key is None:
            return
        self.text_edit.insert_todo()

    def _add_image(self) -> None:
        """Pick a picture, copy it into the library, and put it at the cursor. ▸p/comment-images"""
        import hou

        ui = getattr(hou, "ui", None)    # absent headless, so every reach for it is guarded ▸p/refusal-sink
        if ui is None:
            return
        chosen = ui.selectFile(
            title="Add a picture to this comment",
            pattern="*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff",
            chooser_mode=hou.fileChooserMode.Read)    # NOT the ReadAndWrite default, which offers to create a file that is not there ▸r/select-file-write
        chosen = hou.text.expandString(chosen or "").strip()
        if not chosen:
            return
        src = notes.adopt_image(self.preferences, chosen)
        if not src:
            ui.displayMessage(
                messages.PICTURE_NOT_COPIED_TO_LIBRARY)
            return
        if not self.text_edit.insert_image(src):
            ui.displayMessage(
                messages.PICTURE_COPIED_BUT_UNREADABLE)
            return
        self.text_edit.setFocus()    # the insert fires textChanged, which schedules the debounced save

    def _something_changed(self) -> None:
        if self._loading or self._key is None:
            return
        self._save_timer.start()

    def flush(self) -> None:
        """Write any pending edit now; subject switches, hides and session ends call it."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()

    def _save_now(self) -> None:
        if self._key is None:
            return
        written = notes.set_note(
            self.preferences, self._key, self.text_edit.serialize(),
            self._library)
        if written:
            self.changed.emit(self._key)
        else:
            debug.event("notes", "page not persisted",
                        key=str(self._key))

    def hideEvent(self, event) -> None:
        self.flush()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        """Flush on close; a pane never shown delivers no hide event."""
        self.flush()
        super().closeEvent(event)
