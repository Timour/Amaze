"""The Notes panel: ONE FLOWING DOCUMENT where a to-do is a block whose userState says so, its checkbox painted in the left margin; persists debounced. ▸r/qt-text-checklists"""

from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.core import debug, notes
from amaze.helpers import theme, ui_helpers
from amaze import messages

COMMENT_INK = amazetheme.COMMENT_INK    # the design's, declared once ▸p/one-design-document

SAVE_DELAY_MS = 600       # a crash loses a sentence at most, and typing is not a write per key

HEADER_BG = amazetheme.COMMENT_HEADER_BG
PAGE_BG = amazetheme.COMMENT_PAGE_BG


def _fill(widget, hex_color: str) -> None:
    """Background via the PALETTE, never a stylesheet: one on ANY ancestor hands the subtree to Qt's stylesheet engine and its primitive scrollbars."""
    palette = widget.palette()
    palette.setColor(QtGui.QPalette.ColorRole.Window,
                     QtGui.QColor(hex_color))
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)


def _dim(label) -> None:
    """Dim label text via the palette, same reasoning as _fill."""
    palette = label.palette()
    palette.setColor(QtGui.QPalette.ColorRole.WindowText,
                     QtGui.QColor(theme.color_hex("text_dim")))
    label.setPalette(palette)

_glyph_cache: dict = globals().get("_glyph_cache", {})   # keyed on every input and survives the reload chain; without it a ten-to-do page did ten SVG parses per paintEvent


def _feather_icon(name: str, side: int, ink: str, widget=None) -> QtGui.QPixmap:
    """One Feather glyph re-inked at device resolution; pass the WIDGET being painted so the ratio is its screen's, not the primary's. ▸r/screen-dpr"""
    import os

    import amaze
    dpr = theme.screen_ratio(widget)
    key = (name, int(side), str(ink), float(dpr))   # EVERY input in the key: ink changes per to-do state, dpr when the window moves screen
    cached = _glyph_cache.get(key)
    if cached is not None:
        return cached
    path = os.path.join(
        os.path.dirname(amaze.__file__), "ui", "feather", name + ".svg")
    pixmap = ui_helpers.device_pixmap(path, side, dpr, {"currentColor": ink})
    _glyph_cache[key] = pixmap
    return pixmap


STATE_TODO = 1   # to-do state is each block's userState; it is NOT inherited across Enter, a fresh block reads -1 ▸r/qt-text-checklists
STATE_DONE = 2
STATE_IMAGE = 3   # a picture block: ONE image fragment, no text of its own ▸p/comment-images

IMAGE_DIR = "img/comments"    # inside the library, beside the thumbnails `img/` already holds ▸p/comment-images

ADD_ITEMS = (    # what the + offers, in order - a new item type joins by adding ONE line here ▸p/comment-images
    ("Bullet point", "_add_todo"),
    ("Image", "_add_image"),
)


class _NoteEdit(QtWidgets.QTextEdit):
    """The flowing document: plain paragraphs and framed to-do blocks interleave freely, a to-do being any block whose userState says so."""

    GLYPH_SPACE = 24   # left margin reserved on to-do blocks, where the glyph paints
    GLYPH_SIDE = 14

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        palette = self.palette()   # NO stylesheet: it would hand the scrollbars to Qt's engine and its primitive chrome; the background goes through the palette
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
    def image_src(block) -> str:
        """The library-relative path an image block draws, or "" - read off the FRAGMENT, since the block's own text is only the object-replacement character. ▸p/comment-images"""
        iterator = block.begin()
        while not iterator.atEnd():
            char_format = iterator.fragment().charFormat()
            if char_format.isImageFormat():
                return char_format.toImageFormat().name()
            iterator += 1
        return ""

    def make_image_here(self, cursor, src: str) -> bool:
        """Turn the cursor's block into a picture of `src` (library-relative); False when the file will not load, so the caller can say so instead of leaving a blank. ▸p/comment-images"""
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
        """The picture button: a picture at the cursor; an empty plain block becomes it in place, anything else gets a new block below - the same rule `insert_todo` follows."""
        cursor = self.textCursor()
        block = cursor.block()
        if self.is_todo_block(block) or self.is_image_block(block) \
                or block.text().strip():
            cursor.movePosition(QtGui.QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertBlock(self._plain_format())
        if not self.make_image_here(cursor, src):
            return False
        cursor = self.textCursor()    # LEAVE THE CURSOR BELOW THE PICTURE: it still carries the image char format, so typing here would land inside the picture's own block and `serialize` would drop every word ▸p/comment-images
        cursor.insertBlock(self._plain_format())
        cursor.block().setUserState(-1)
        cursor.setCharFormat(self._label_format(False))
        self.setTextCursor(cursor)
        return True

    def _image_width(self, image) -> float:
        """Never wider than the pane, never upscaled - a screenshot dropped in at full size would otherwise force a horizontal scrollbar on every comment."""
        room = max(self.viewport().width() - theme.ui_px(24), theme.ui_px(80))
        return float(min(image.width(), room))

    def resolve_image(self, src: str) -> str:
        """A library-relative `src` as an absolute path; the stored form stays relative so a library opened on another machine still finds it. ▸p/comment-images"""
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
        fmt = QtGui.QTextBlockFormat()   # NO background: a to-do is the page's colour and separation is PADDING, 10px each side plus the glyph margin
        fmt.setBackground(QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush))
        fmt.setTopMargin(theme.ui_px(10))
        fmt.setBottomMargin(theme.ui_px(10))
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

    def make_todo_here(self, cursor, done: bool = False) -> None:
        """Turn the cursor's block into a to-do frame."""
        block = cursor.block()
        block.setUserState(STATE_DONE if done else STATE_TODO)
        self._restyle_block(block, True, done)
        cursor.setCharFormat(self._label_format(done))
        self.setTextCursor(cursor)
        self.viewport().update()

    def make_plain_here(self, cursor) -> None:
        """Turn the cursor's block back into flowing text; the label survives as words."""
        block = cursor.block()
        block.setUserState(-1)
        self._restyle_block(block, False, False)
        cursor.setCharFormat(self._label_format(False))
        self.setTextCursor(cursor)
        self.viewport().update()

    def insert_todo(self) -> None:
        """The + button: a to-do frame at the cursor; an empty plain block converts in place, anything else gets a new frame below it."""
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
        done = not self.block_done(block)
        block.setUserState(STATE_DONE if done else STATE_TODO)
        self._restyle_block(block, True, done)
        self.viewport().update()
        return True


    def _merge_keeping(self, keeper, event) -> None:
        """Merge across a block separator, then give the survivor the KEEPER's to-do state back; Qt stamps it with the FOLLOWING block's userState. ▸r/qt-text-checklists"""
        done = self.block_done(keeper)
        super().keyPressEvent(event)
        block = self.textCursor().block()
        block.setUserState(STATE_DONE if done else STATE_TODO)
        self._restyle_block(block, True, done)
        self.viewport().update()

    def keyPressEvent(self, event) -> None:
        if event.key() == QtCore.Qt.Key.Key_Backspace:
            cursor = self.textCursor()
            block = cursor.block()
            if (self.is_todo_block(block)
                    and not cursor.hasSelection()
                    and (cursor.atBlockStart()
                         or not self.block_label(block))):
                self.make_plain_here(cursor)   # Backspace at a frame's start UNWRAPS it back to text, the mirror of Enter-on-empty; another then deletes normally
                return
            if (not cursor.hasSelection() and cursor.atBlockStart()
                    and self.is_todo_block(block.previous())):
                self._merge_keeping(block.previous(), event)   # backspacing UP into a to-do; without this the frame above loses its checkbox and keeps its struck text
                return
        if (event.key() == QtCore.Qt.Key.Key_Delete
                and not self.textCursor().hasSelection()):
            cursor = self.textCursor()
            block = cursor.block()
            if (self.is_todo_block(block) and cursor.atBlockEnd()
                    and block.next().isValid()):
                self._merge_keeping(block, event)   # the mirror: forward-Delete at a frame's end pulls the next line in and strips the checkbox the same way
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
        """The to-do block whose checkbox zone contains pos, or None: the ONE hit-test the click and the hover cursor share."""
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
        block = self._glyph_zone_block(event.position().toPoint())
        if block is not None and self.toggle_block(block):
            self.textChanged.emit()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not event.buttons():   # a pointing hand over the glyph zone, I-beam elsewhere; only with no button down, since swapping mid-selection flickers
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
        """One glyph per to-do block, in the margin its block format reserves: Feather circle / check-circle."""
        layout = self.document().documentLayout()
        x_scroll = self.horizontalScrollBar().value()
        y_scroll = self.verticalScrollBar().value()
        side = theme.ui_px(self.GLYPH_SIDE)
        ink = COMMENT_INK   # the to-do glyphs wear the Comments colour too, not the accent
        visible = self.viewport().rect()
        block = self.document().begin()
        while block.isValid():
            if self.is_todo_block(block):
                rect = layout.blockBoundingRect(block)
                top = rect.top() - y_scroll
                if top > visible.bottom():
                    break
                if rect.bottom() - y_scroll >= visible.top():
                    tlayout = block.layout()   # blockBoundingRect ALREADY includes the padding; lineAt() on an un-laid-out block crashes hython natively
                    if tlayout is not None and tlayout.lineCount() > 0:
                        line = tlayout.lineAt(0)
                        glyph = ("check-circle" if self.block_done(block)
                                 else "circle")
                        pixmap = _feather_icon(glyph, side, ink, self)
                        y = (tlayout.position().y() + line.y()
                             + (line.height() - side) / 2.0 - y_scroll)
                        painter.drawPixmap(
                            int(rect.left() - x_scroll + theme.ui_px(4)),
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
                    first = True    # the block exists now, so the fallback below REUSES it rather than adding a second
                if self.make_image_here(cursor, src):
                    cursor = self.textCursor()
                    first = False
                    continue
                cursor.block().setUserState(-1)    # the picture would not load, so this block carries the fallback text below instead
                item = {"t": "text",    # the file is gone or unreadable: show the fallback the item already carries rather than a blank ▸p/comment-images
                        "text": item.get("text")
                        or "[image: %s]" % os.path.basename(src)}
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
        self.document().clearUndoRedoStacks()    # the LOAD is not an edit: left undoable, one Ctrl+Z peels the page apart block by block, each step fires textChanged, and the debounced save then writes the emptied note over the real one ▸r/programmatic-load-is-undoable

    def serialize(self) -> list:
        """The document, in order, as the store's item flow: adjacent plain lines join into one text item, and blank lines between content survive inside it."""
        items = []
        text_lines = []

        def flush_text():
            if text_lines and any(l.strip() for l in text_lines):
                items.append({"t": "text",
                              "text": "\n".join(text_lines).strip("\n")})
            text_lines.clear()

        block = self.document().begin()
        while block.isValid():
            if self.is_image_block(block):
                flush_text()
                src = self.image_src(block)
                if src:
                    items.append({"t": "image", "src": src,
                                  "text": "[image: %s]"    # what a build with no image support shows instead of a blank line ▸p/comment-images
                                          % os.path.basename(src)})
                typed = block.text().replace("￼", "")    # the caret can legally land in the picture's block (a click right of it), and words typed there are real content - the image fragment itself reads as U+FFFC (measured, hython 22.0.418)
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
    """The dockable page: `set_subject` points it at one asset, `clear_subject` shows the empty state, and saves emit `changed` so the grid repaints that tile's badge."""

    changed = QtCore.Signal(str)

    def __init__(self, preferences, parent=None) -> None:
        super().__init__(preferences, "notes_panel_width",
                         theme.ui_px(450), parent)
        self.preferences = preferences
        self._key = None
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
        head = QtWidgets.QHBoxLayout(header)
        gap = theme.ui_px(10)
        head.setContentsMargins(gap, gap, gap, gap)
        head.setSpacing(gap)
        self._icon_label = QtWidgets.QLabel()
        head.addWidget(self._icon_label, 0,
                       QtCore.Qt.AlignmentFlag.AlignVCenter)

        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(0)
        self.section_label = QtWidgets.QLabel()
        _dim(self.section_label)
        self.name_label = QtWidgets.QLabel()
        self.name_label.setFont(   # THE ONE FONT TABLE owns the 1.4, not this line
            theme.font("comments_title", self.name_label.font()))
        self.type_label = QtWidgets.QLabel()
        _dim(self.type_label)
        for label in (self.section_label, self.name_label,
                      self.type_label):
            titles.addWidget(label)
        head.addLayout(titles, 1)

        self.add_button = QtWidgets.QToolButton()
        self.add_button.setAutoRaise(True)
        self.add_button.setToolTip("Add a to-do at the cursor")
        self.add_button.setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor)
        self._build_add_menu()    # the + opens a menu now, so nothing connects to `clicked` - InstantPopup does not fire it ▸p/comment-images
        self._paint_accents()
        head.addWidget(self.add_button, 0,
                       QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.header_widget = header
        page_box.addWidget(header)

        body = QtWidgets.QWidget()
        _fill(body, PAGE_BG)
        body_box = QtWidgets.QVBoxLayout(body)
        body_box.setContentsMargins(0, 0, 0, 0)   # ZERO chrome margins: the inset lives in the DOCUMENT margin, so scrolled text slides up to the header border
        self.text_edit = _NoteEdit()
        self.text_edit.document().setDocumentMargin(theme.ui_px(12))
        self.text_edit.textChanged.connect(self._something_changed)
        body_box.addWidget(self.text_edit, 1)
        self.body_widget = body
        page_box.addWidget(body, 1)
        self._ghost = True
        self._show_ghost()

    def set_note_accent(self, hex_color: str) -> None:
        """KEPT AS A NO-OP: Comments has its own colour so no accent reaches here, but the panel calls this on every accent change and a missing method is an AttributeError in a signal handler."""

    def _paint_accents(self) -> None:
        import os

        import amaze
        dpr = theme.screen_ratio(self)
        side = theme.ui_px(39)
        # AS DRAWN, no tint map: the art carries its own colour and the toolbar chip is the one site that genuinely recolours this glyph
        pixmap = ui_helpers.device_pixmap(
            os.path.join(os.path.dirname(amaze.__file__),
                         "ui", "icon_comments.svg"),
            side, dpr)
        self._icon_label.setPixmap(pixmap)
        plus_side = theme.ui_px(18)
        plus_ink = PAGE_BG if getattr(self, "_ghost", False) \
            else COMMENT_INK
        self.add_button.setIcon(QtGui.QIcon(
            _feather_icon("plus-circle", plus_side, plus_ink, self)))
        self.add_button.setIconSize(QtCore.QSize(plus_side, plus_side))

    def adopt_look(self, source: QtWidgets.QWidget) -> None:
        """Clone font and text colour from a .ui-loaded sibling, identical by construction; hand-set values drifted from the app's own scale within a day."""
        self.text_edit.setFont(source.font())
        palette = self.text_edit.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Text,
                         source.palette().color(
                             QtGui.QPalette.ColorRole.Text))
        self.text_edit.setPalette(palette)
        base = QtGui.QFont(source.font())
        self.section_label.setFont(base)
        self.type_label.setFont(base)
        self.name_label.setFont(theme.font("comments_title", base))


    def set_subject(self, subject) -> None:
        """Point the page at one asset, flushing any pending edit for the previous one first; `subject` is a `sections.CommentSubject`, read BY NAME."""
        key = subject.key
        section = subject.section
        name = subject.name
        type_label = subject.type
        category = subject.category
        category_color = subject.colour
        if key == self._key:
            self.set_header(section, category, name, type_label,   # HEADER ONLY: a rename arrives as a same-key call so the header must follow, but reloading the page would discard what is being typed
                            category_color)
            return
        self.flush()
        self._key = key
        self._loading = True
        try:
            self.set_header(section, category, name, type_label,
                            category_color)
            note = notes.note_for(self.preferences, key)
            self.text_edit.library_dir = str(    # re-read per page: a library switch moves where an image's relative src points ▸p/comment-images
                getattr(self.preferences, "dir", "") or "")
            self.text_edit.load_items(note.get("items", []))
        finally:
            self._loading = False
        self._ghost = False
        self.text_edit.setEnabled(True)
        self.add_button.setEnabled(True)
        self._paint_accents()

    def set_header(self, section: str, category: str, name: str,
                   type_label: str, category_color: str = "") -> None:
        """The first line reads section/category; a category carrying a colour renders IN that colour and bold."""
        import html
        section_text = html.escape(section)
        if category:
            shown = html.escape(category)
            if category_color:
                section_text = (
                    '%s/<b><span style="color:%s">%s</span></b>'
                    % (section_text, html.escape(category_color), shown))
            else:
                section_text = "%s/%s" % (section_text, shown)
        self.section_label.setTextFormat(
            QtCore.Qt.TextFormat.RichText)
        self.section_label.setText(section_text)
        self.name_label.setText(name)
        self.type_label.setText(type_label)

    def clear_subject(self) -> None:
        self.flush()
        self._key = None
        self._show_ghost()

    def _show_ghost(self) -> None:
        """The no-selection look: the SAME window with placeholder labels and a dead page-coloured +, never a different layout."""
        self._ghost = True
        self._loading = True
        try:
            self.set_header("section/category", "", "Object name",
                            "type")
            self.text_edit.clear()
        finally:
            self._loading = False
        self.text_edit.setEnabled(False)
        self.add_button.setEnabled(False)
        self._paint_accents()


    def _build_add_menu(self) -> None:
        """Hang the + button's menu on it ONCE, Qt's own way - `InstantPopup` opens it on press and adds no arrow, so the button looks exactly as it did. ▸p/comment-images"""
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
        """Pick a picture, COPY it into the library, and put it at the cursor - the note stores the library-relative path. ▸p/comment-images"""
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
        self.text_edit.setFocus()    # the insert fires textChanged, which schedules the debounced save - the same route the + button relies on

    def _something_changed(self) -> None:
        if self._loading or self._key is None:
            return
        self._save_timer.start()

    def flush(self) -> None:
        """Write any pending edit NOW: subject switches, panel hides and session ends all come through here."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()

    def _save_now(self) -> None:
        if self._key is None:
            return
        written = notes.set_note(
            self.preferences, self._key, self.text_edit.serialize())
        if written:
            self.changed.emit(self._key)
        else:
            debug.event("notes", "page not persisted",
                        key=str(self._key))

    def hideEvent(self, event) -> None:
        self.flush()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        """A close on a pane that was never shown delivers no hide event, so this is not the same net as hideEvent above."""
        self.flush()
        super().closeEvent(event)
