"""The Notes panel - a notebook page for the selected asset.

The 2026-08-01 design (Notes.svg), corrected by the same day's live
pass: the page is ONE FLOWING DOCUMENT, not a text box above a to-do
stack. You write anywhere; the + button inserts a to-do as a framed
line at the cursor - a block you type into, like an HTML frame - and
text keeps flowing above and below it. Consecutive to-dos stack as
adjacent frames. Clicking a to-do's circle checks it (struck through);
Enter inside a to-do continues with another one, Enter on an empty
to-do drops back to plain text. The first build's two competing stacks
(to-dos piling up until the text field vanished) is exactly what this
replaces.

A to-do is a block whose userState says so - page-coloured, set off
by 10px of padding, its checkbox PAINTED by the editor in the block's
left margin -
the third machinery, and the one that holds. Qt's task-list markers
inherit list state across Enter (checkboxes vanished live), and the
text-object registration path is dead in Houdini's PySide6 build
(research.md ▸ *Qt text checklists*); block state plus hand-painted
glyphs is also simply the house pattern - the delegates and the
slider already paint themselves. The serializer walks the document,
in order, into core/notes.py's item flow.

Everything persists debounced: a keystroke arms a short timer,
switching subject or hiding the panel flushes immediately.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import debug, notes
from amaze.helpers import theme, ui_helpers

#: Debounce for keystroke saves. Short enough that a crash loses a
#: sentence at most; long enough that typing is not a write per key.
#: COMMENTS ARE BLUE. The section was the star yellow, following
#: the accent preference; from 2026-08-01 it has its own colour,
#: which is what makes the toolbar button, the section header
#: icon and the to-do glyphs read as one thing. The tile badge is
#: NOT tinted - that art keeps its own palette, as all badges do.
COMMENT_INK = "#5cc9f5"

SAVE_DELAY_MS = 600

#: The pane's designed colours (2026-08-01): the header strip and the
#: writing surface. Design constants, not theme tokens - the exact
#: values were specified.
HEADER_BG = "#22232b"
PAGE_BG = "#2b2c34"


def _fill(widget, hex_color: str) -> None:
    """Background via the PALETTE, never a stylesheet: a stylesheet on
    ANY ancestor hands the whole subtree to Qt's stylesheet engine,
    whose primitive scrollbar chrome replaces Houdini's (probed;
    research.md ▸ *Qt styling & splitters*)."""
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

#: Rasterised glyphs, keyed on every input. The sibling that draws
#: the tile badges caches exactly this way and says why: "every tile
#: badge comes through here, one SVG rasterization each for the whole
#: app" (delegates.py _badge_cache).
#:
#: Without it, _paint_todo_glyphs called this inside its block walk -
#: so a page with ten to-dos did ten file opens, ten SVG parses and
#: ten rasterisations per paintEvent, and the text cursor repaints the
#: viewport about twice a second while the pane has focus. Typing a
#: sentence cost hundreds of synchronous disk reads on a pane that is
#: open by default whenever show_notes is set. The glyph set is two
#: entries.
#:
#: Survives the reload chain, like every other module-level cache here.
_glyph_cache: dict = globals().get("_glyph_cache", {})


def _feather_icon(name: str, side: int, ink: str) -> QtGui.QPixmap:
    """One Feather glyph re-inked at device resolution (the icon files
    carry stroke="currentColor", which QSvgRenderer never resolves -
    recorded)."""
    import os

    import amaze
    app = QtWidgets.QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    # EVERY input in the key (practice.md ▸ Caches & measurement): the
    # ink changes per to-do state and the dpr changes when the window
    # moves to another screen.
    key = (name, int(side), str(ink), float(dpr))
    cached = _glyph_cache.get(key)
    if cached is not None:
        return cached
    path = os.path.join(
        os.path.dirname(amaze.__file__), "ui", "feather", name + ".svg")
    pixmap = ui_helpers.render_svg_pixmap(
        path, max(1, int(round(side * dpr))), {"currentColor": ink})
    pixmap.setDevicePixelRatio(dpr)
    _glyph_cache[key] = pixmap
    return pixmap


#: To-do state lives in each block's userState - probed 2026-08-01:
#: it is NOT inherited across Enter (a fresh block reads -1), which is
#: exactly the determinism the two failed approaches lacked (see the
#: module docstring and research.md ▸ *Qt text checklists*).
STATE_TODO = 1
STATE_DONE = 2


class _NoteEdit(QtWidgets.QTextEdit):
    """The flowing document. Plain paragraphs and framed to-do blocks
    interleave freely; a to-do is any block whose userState says so,
    and its checkbox is painted in the block's left margin."""

    #: Left margin reserved on to-do blocks - where the glyph paints.
    GLYPH_SPACE = 24
    GLYPH_SIDE = 14

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        # NO stylesheet, deliberately: any stylesheet on the widget
        # hands its scrollbars to Qt's stylesheet engine, which draws
        # its own primitive chrome instead of Houdini's (the "old SGI
        # IRIX scrollbar" of the live pass). The background goes
        # through the PALETTE like the panel's other widgets.
        palette = self.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Base,
                         QtGui.QColor(0, 0, 0, 0))
        self.setPalette(palette)
        self.setAcceptRichText(False)
        self.setPlaceholderText("Write a comment...")
        # The hover cursor swap below needs move events without a
        # button held.
        self.viewport().setMouseTracking(True)

    # -- what a block is ----------------------------------------------

    @staticmethod
    def is_todo_block(block) -> bool:
        return block.userState() in (STATE_TODO, STATE_DONE)

    @staticmethod
    def block_done(block) -> bool:
        return block.userState() == STATE_DONE

    @staticmethod
    def block_label(block) -> str:
        return block.text().strip()

    # -- building blocks ----------------------------------------------

    def _todo_format(self) -> QtGui.QTextBlockFormat:
        # NO background - a to-do is the same colour as the page (the
        # 2026-08-01 call); separation is PADDING, 10px above and
        # below, plus the glyph's margin.
        fmt = QtGui.QTextBlockFormat()
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
        # Strike-through only: colour comes from the widget palette,
        # which adopt_look() clones from the category list.
        fmt = QtGui.QTextCharFormat()
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
        """Turn the cursor's block back into flowing text (the label
        survives as words)."""
        block = cursor.block()
        block.setUserState(-1)
        self._restyle_block(block, False, False)
        cursor.setCharFormat(self._label_format(False))
        self.setTextCursor(cursor)
        self.viewport().update()

    def insert_todo(self) -> None:
        """The + button: a to-do frame at the cursor. An empty plain
        block converts in place; anything else gets a new block below
        - 'as soon as you add a todo you add a frame underneath'."""
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

    # -- interaction ---------------------------------------------------

    def _merge_keeping(self, keeper, event) -> None:
        """Let Qt merge across a block separator, then hand the
        surviving block the KEEPER's to-do state back: the merge
        stamps it with the FOLLOWING block's userState instead
        (probed 2026-08-01 - research.md ▸ Qt text checklists), which
        silently unmade a frame while its struck text stayed."""
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
                # Backspace at the frame's start (or on an empty
                # frame) UNWRAPS it back to text - the deletion path,
                # the mirror of Enter-on-empty. Another Backspace then
                # removes the line like any text.
                self.make_plain_here(cursor)
                return
            if (not cursor.hasSelection() and cursor.atBlockStart()
                    and self.is_todo_block(block.previous())):
                # Backspacing a plain line UP into the to-do above:
                # Qt's separator removal stamps the merged block with
                # the FOLLOWING block's userState (probed 2026-08-01)
                # - the frame above silently lost its checkbox while
                # its struck text stayed, the screenshot bug. Merge,
                # then give the survivor its own state back.
                self._merge_keeping(block.previous(), event)
                return
        if (event.key() == QtCore.Qt.Key.Key_Delete
                and not self.textCursor().hasSelection()):
            cursor = self.textCursor()
            block = cursor.block()
            if (self.is_todo_block(block) and cursor.atBlockEnd()
                    and block.next().isValid()):
                # The unreported mirror, caught by the same probe:
                # forward-Delete at a frame's end pulls the next line
                # in and strips the checkbox the same way.
                self._merge_keeping(block, event)
                return
        if event.key() in (QtCore.Qt.Key.Key_Return,
                           QtCore.Qt.Key.Key_Enter):
            cursor = self.textCursor()
            block = cursor.block()
            if self.is_todo_block(block):
                if not self.block_label(block):
                    # Enter on an EMPTY to-do drops back to text.
                    self.make_plain_here(cursor)
                    return
                super().keyPressEvent(event)
                # The continuation is a fresh frame; userState does
                # not inherit (probed), so the block above KEEPS its
                # checkbox and this one gets its own.
                self.make_todo_here(self.textCursor(), False)
                return
        super().keyPressEvent(event)

    def _glyph_zone_block(self, pos):
        """The to-do block whose checkbox zone contains pos, or None -
        the ONE hit-test the click and the hover cursor share."""
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
        # The checkbox is a BUTTON, and the cursor should say so: a
        # pointing hand over the glyph zone, the I-beam everywhere
        # else. Only while no button is down - changing cursors mid
        # text-selection flickers.
        if not event.buttons():
            over = self._glyph_zone_block(
                event.position().toPoint()) is not None
            wanted = (QtCore.Qt.CursorShape.PointingHandCursor if over
                      else QtCore.Qt.CursorShape.IBeamCursor)
            if self.viewport().cursor().shape() != wanted:
                self.viewport().setCursor(wanted)
        super().mouseMoveEvent(event)

    # -- the checkboxes, painted by hand ------------------------------

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self.viewport())
        try:
            self._paint_todo_glyphs(painter)
        finally:
            painter.end()

    def _paint_todo_glyphs(self, painter) -> None:
        """One glyph per to-do block, in the margin its block format
        reserves - Feather circle / check-circle, the design's own."""
        layout = self.document().documentLayout()
        x_scroll = self.horizontalScrollBar().value()
        y_scroll = self.verticalScrollBar().value()
        side = theme.ui_px(self.GLYPH_SIDE)

        # 2026-08-01 named "the todo + circle" explicitly.
        ink = COMMENT_INK
        visible = self.viewport().rect()
        block = self.document().begin()
        while block.isValid():
            if self.is_todo_block(block):
                rect = layout.blockBoundingRect(block)
                top = rect.top() - y_scroll
                if top > visible.bottom():
                    break
                if rect.bottom() - y_scroll >= visible.top():
                    # The TRUE first-line geometry, not an
                    # approximation: blockBoundingRect already includes
                    # the block's padding, so adding it again landed
                    # every glyph one padding below its line (measured;
                    # research.md). lineCount is guarded because
                    # lineAt() on an un-laid-out block crashes hython
                    # natively - same entry.
                    tlayout = block.layout()
                    if tlayout is not None and tlayout.lineCount() > 0:
                        line = tlayout.lineAt(0)
                        glyph = ("check-circle" if self.block_done(block)
                                 else "circle")
                        pixmap = _feather_icon(glyph, side, ink)
                        y = (tlayout.position().y() + line.y()
                             + (line.height() - side) / 2.0 - y_scroll)
                        painter.drawPixmap(
                            int(rect.left() - x_scroll + theme.ui_px(4)),
                            int(y),
                            pixmap)
            block = block.next()

    # -- the store's shape --------------------------------------------

    def load_items(self, items: list) -> None:
        self.clear()
        cursor = self.textCursor()
        first = True
        for item in items or []:
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

    def serialize(self) -> list:
        """The document, in order, as the store's item flow. Adjacent
        plain lines join into one text item; blank plain lines between
        content survive inside it."""
        items = []
        text_lines = []

        def flush_text():
            if text_lines and any(l.strip() for l in text_lines):
                items.append({"t": "text",
                              "text": "\n".join(text_lines).strip("\n")})
            text_lines.clear()

        block = self.document().begin()
        while block.isValid():
            if self.is_todo_block(block):
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
    """The dockable page. `set_subject` points it at one asset;
    `clear_subject` shows the quiet empty state. Saves emit `changed`
    with the note key, so the grid can repaint that tile's badge.

    A HeldPane, like the sidebar: a side pane asks for its width and
    the grid gives it up. That is the whole of the width story now -
    the panel's fifty lines of splitter arithmetic measured identical
    to doing nothing, because the splitter had already honoured this
    hint before they ran."""

    changed = QtCore.Signal(str)

    def __init__(self, preferences, parent=None) -> None:
        super().__init__(preferences, "notes_panel_width",
                         theme.ui_px(450), parent)
        self.preferences = preferences
        # No accent here any more - Comments has its own colour, see
        # COMMENT_INK. This pane used to wear the star yellow.
        self._key = None
        self._loading = False
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_now)
        # Houdini quitting is the one teardown that reaches no widget
        # event of ours - the wiki's rule for the thumbnail engine
        # (research.md, wire teardown to aboutToQuit) is the same rule
        # for 600ms of typing that only exists in the widget. Qt drops
        # the connection when this pane is destroyed, so a reopened
        # panel does not leave a dead one behind.
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.flush)

        self.setMinimumWidth(theme.ui_px(220))
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ONE page. With nothing selected it shows a GHOST of itself -
        # placeholder labels, dead + button - not a different layout
        # (the 2026-08-01 call): the window always looks like itself.
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
        # THE ONE FONT TABLE owns the 1.4, not this line and not the
        # near-identical one in _match_source_style below - they were
        # two copies of the same rule, and a copy is how the panel came
        # to have four independent font rules in three files.
        self.name_label.setFont(
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
        self.add_button.clicked.connect(self._add_todo_clicked)
        self._paint_accents()
        head.addWidget(self.add_button, 0,
                       QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.header_widget = header
        page_box.addWidget(header)

        body = QtWidgets.QWidget()
        _fill(body, PAGE_BG)
        body_box = QtWidgets.QVBoxLayout(body)
        # ZERO chrome margins: the inset lives in the DOCUMENT margin
        # instead, so unscrolled text starts 12px down but scrolled
        # text slides through that zone right up to the header border.
        body_box.setContentsMargins(0, 0, 0, 0)
        self.text_edit = _NoteEdit()
        self.text_edit.document().setDocumentMargin(theme.ui_px(12))
        self.text_edit.textChanged.connect(self._something_changed)
        body_box.addWidget(self.text_edit, 1)
        self.body_widget = body
        page_box.addWidget(body, 1)
        self._ghost = True
        self._show_ghost()

    def set_note_accent(self, hex_color: str) -> None:
        """KEPT AS A NO-OP, deliberately.

        This pane used to wear the star yellow, re-tinted whenever the
        star preference changed. Comments have their own colour now
        (COMMENT_INK), so there is nothing for an accent to change -
        but the panel calls this on every accent change and on rebuild,
        and a missing method there is an AttributeError in a signal
        handler rather than a visible mistake. It stays, and it says
        why.
        """

    def _paint_accents(self) -> None:
        import os

        import amaze
        app = QtWidgets.QApplication.instance()
        dpr = app.devicePixelRatio() if app else 1.0
        side = theme.ui_px(39)
        # AS DRAWN, no tint map. The map here was a no-op wearing a
        # fix's clothes: one key (#fffc66) is not in the art at all,
        # and the other mapped the art's own blue to COMMENT_INK,
        # which IS that blue - so it recoloured nothing and would
        # have died silently the day the art changed. The art
        # carries its own colour; the toolbar chip is the one site
        # that genuinely recolours this glyph.
        pixmap = ui_helpers.render_svg_pixmap(
            os.path.join(os.path.dirname(amaze.__file__),
                         "ui", "icon_comments.svg"),
            max(1, int(round(side * dpr))))
        pixmap.setDevicePixelRatio(dpr)
        self._icon_label.setPixmap(pixmap)
        plus_side = theme.ui_px(18)
        plus_ink = PAGE_BG if getattr(self, "_ghost", False) \
            else COMMENT_INK
        self.add_button.setIcon(QtGui.QIcon(
            _feather_icon("plus-circle", plus_side, plus_ink)))
        self.add_button.setIconSize(QtCore.QSize(plus_side, plus_side))

    def adopt_look(self, source: QtWidgets.QWidget) -> None:
        """Clone font and text colour from a .ui-loaded sibling (the
        category list) - identical by construction, per the standing
        reuse directive; hand-set values drifted from the app's own
        scale within a day."""
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

    # -- subject ------------------------------------------------------

    def set_subject(self, subject) -> None:
        """Point the page at one asset, flushing any pending edit for
        the previous one first.

        `subject` is a `sections.CommentSubject`. It was six POSITIONAL
        arguments until 2026-08-03, built by three different sections
        and unpacked with `*subject` - so three authors had to agree on
        an order nothing enforced. Read by name now.
        """
        key = subject.key
        section = subject.section
        name = subject.name
        type_label = subject.type
        category = subject.category
        category_color = subject.colour
        if key == self._key:
            # THE HEADER STILL FOLLOWS. A comment is keyed by identity -
            # an id, a path, a uid - and renaming or recategorising an
            # asset changes none of those, so a rename arrives here as a
            # same-key call and the header kept the old name for as long
            # as the pane stayed open.
            #
            # Header only: this method is called on every click, and
            # reloading the stored page here would throw away whatever
            # is being typed.
            self.set_header(section, category, name, type_label,
                            category_color)
            return
        self.flush()
        self._key = key
        self._loading = True
        try:
            self.set_header(section, category, name, type_label,
                            category_color)
            note = notes.note_for(self.preferences, key)
            self.text_edit.load_items(note.get("items", []))
        finally:
            self._loading = False
        self._ghost = False
        self.text_edit.setEnabled(True)
        self.add_button.setEnabled(True)
        self._paint_accents()

    def set_header(self, section: str, category: str, name: str,
                   type_label: str, category_color: str = "") -> None:
        """The first line reads section/category; a category that
        carries a colour renders IN that colour and bold."""
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
        """The no-selection look: the SAME window, placeholder labels,
        a dead page-coloured + - never a different layout."""
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

    # -- editing ------------------------------------------------------

    def _add_todo_clicked(self) -> None:
        if self._key is None:
            return
        self.text_edit.insert_todo()

    # -- persistence --------------------------------------------------

    def _something_changed(self) -> None:
        if self._loading or self._key is None:
            return
        self._save_timer.start()

    def flush(self) -> None:
        """Write any pending edit NOW - subject switches, panel hides
        and session ends all come through here."""
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
        """A close on a pane that was never shown delivers no hide
        event, so this is not the same net as hideEvent above."""
        self.flush()
        super().closeEvent(event)
