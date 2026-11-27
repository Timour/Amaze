"""The Comments page: plain, to-do and picture blocks in one document. ▸r/qt-text-checklists"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.helpers import theme, ui_helpers
from amaze.pane import comment_document, comments as pane_comments
from amaze.panel import side_pane
from amaze import tooltips

COMMENT_ICON_COLOR = amazetheme.COMMENT_ICON_COLOR    # defined once, in amazetheme ▸p/one-design-document

_DRAWN = comment_document.DRAWN    # every size and spacing below is from the N01 design frame ▸r/comments-from-frame


class _AddButton(QtWidgets.QToolButton):
    """The + button: disabled with nothing selected, painted as in N01B, not faded by Houdini."""

    def paintEvent(self, event) -> None:
        if self.isEnabled():
            super().paintEvent(event)
            return
        option = QtWidgets.QStyleOptionToolButton()
        self.initStyleOption(option)
        option.state |= QtWidgets.QStyle.StateFlag.State_Enabled    # Houdini paints a disabled menu triangle almost invisible
        option.state &= ~QtWidgets.QStyle.StateFlag.State_MouseOver
        option.palette.setCurrentColorGroup(QtGui.QPalette.ColorGroup.Active)
        painter = QtWidgets.QStylePainter(self)
        painter.drawComplexControl(QtWidgets.QStyle.ComplexControl.CC_ToolButton, option)
        painter.end()

_glyph_cache: dict = globals().get("_glyph_cache", {})   # keyed on every input and kept across module reloads


def _feather_icon(name: str, side: int, color: str, widget=None) -> QtGui.QPixmap:
    """A Feather icon recoloured at device resolution; pass the painted widget. ▸r/screen-dpr"""
    import amaze
    dpr = theme.screen_ratio(widget)
    key = (name, int(side), str(color), float(dpr))   # EVERY input in the key: colour changes per to-do state, dpr when the window moves screen
    cached = _glyph_cache.get(key)
    if cached is not None:
        return cached
    path = amaze.package_file("ui", "feather", name + ".svg")
    pixmap = ui_helpers.device_pixmap(path, side, dpr, {"currentColor": color})
    _glyph_cache[key] = pixmap
    return pixmap


class _NoteEdit(QtWidgets.QTextEdit):
    """The editor of the document engine `engine`: it paints the glyphs and hands keys to it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        palette = self.palette()   # no stylesheet: the background goes through the palette
        palette.setColor(QtGui.QPalette.ColorRole.Base,
                         QtGui.QColor(0, 0, 0, 0))
        self.setPalette(palette)
        self.setAcceptRichText(False)    # a paste or drop of text only; the engine inserts it
        self.setPlaceholderText(amazetheme.COMMENT_PLACEHOLDER)
        self.viewport().setMouseTracking(True)   # the hover cursor swap needs move events with no button held
        self.engine = comment_document.CommentDocument(
            self.document(), theme.ui_px, lambda: self.viewport().width())
        self.engine.states_changed.connect(self.viewport().update)    # the glyphs are in the margin

    def go_to(self, position: int) -> None:
        """Put the text cursor at `position`, an engine's answer; -1 leaves it."""
        if position < 0:
            return
        cursor = self.textCursor()
        cursor.setPosition(position)
        self.setTextCursor(cursor)

    def keyPressEvent(self, event) -> None:
        cursor = self.textCursor()
        at = self.engine.key(event.key(), cursor.position(), cursor.anchor())
        if at < 0:
            super().keyPressEvent(event)
            return
        self.go_to(at)

    def insertFromMimeData(self, source) -> None:
        """A paste or a drop: its text, plain, through the engine."""
        cursor = self.textCursor()
        self.go_to(self.engine.insert_text(cursor.position(), cursor.anchor(), source.text()))
        self.ensureCursorVisible()

    def _todo_at(self, pos) -> int:
        """The to-do whose glyph zone is under `pos` in the viewport, or -1; for click and hover."""
        return self.engine.todo_at(pos.x() + self.horizontalScrollBar().value(),
                                   pos.y() + self.verticalScrollBar().value())

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:    # only the left button toggles
            if self.engine.toggle(self._todo_at(event.position().toPoint())):
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not event.buttons():   # a pointing hand over the glyph zone, I-beam elsewhere; only with no button down
            over = self._todo_at(event.position().toPoint()) >= 0
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
        x_scroll = self.horizontalScrollBar().value()
        y_scroll = self.verticalScrollBar().value()
        visible = self.viewport().rect()
        for glyph in self.engine.glyphs(y_scroll + visible.bottom()):
            if glyph["zone"].bottom() - y_scroll < visible.top():
                continue
            done = glyph["done"]
            pixmap = _feather_icon(
                "check-circle" if done else "circle", glyph["side"],
                amazetheme.COMMENT_DONE_COLOR if done else amazetheme.COMMENT_OPEN_COLOR, self)
            painter.drawPixmap(int(glyph["x"] - x_scroll), int(glyph["y"] - y_scroll), pixmap)


def _text_field():
    edit = _NoteEdit()
    edit.document().setDocumentMargin(theme.ui_px(_DRAWN["doc_margin"]))    # the inset is the document's
    return edit


DESCRIPTION = side_pane.Page(    # what the page is made of; the engine builds it
    drawn=_DRAWN,
    header=side_pane.Header(
        "icon_comments.svg", amazetheme.COMMENT_ICON_ART_COLOR, amazetheme.COMMENT_ICON_COLOR, _DRAWN["add_pad"],
        (side_pane.Button("add_button", tuple(_DRAWN["add"]), make=lambda: _AddButton()),)),
    body=(side_pane.Widget("text_edit", _text_field),))


class NotesPanel(side_pane.SidePage):
    """The side pane's page showing the pane engine's `comments`; it is open only while shown."""

    def __init__(self, comments, parent=None) -> None:
        super().__init__(DESCRIPTION, parent)
        self._comments = comments
        self.add_button.setAutoRaise(True)
        self.add_button.setToolTip(tooltips.NOTES_ADD_TODO)
        self.add_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._build_add_menu()    # the + opens a menu; InstantPopup never fires `clicked` ▸p/comment-images
        comments.changed.connect(self._show)
        comments.use_document(self.text_edit.engine)
        self._show()

    def _show(self) -> None:
        """The engine's header; nothing selected (N01B) is the same page dimmed."""
        import amaze
        self._dimmed = dimmed = self._comments.dimmed()
        self.set_header(self._comments.name(), self._comments.type())
        self.text_edit.setEnabled(not dimmed)
        self.add_button.setEnabled(not dimmed)
        self.paint_header()
        plus_side = theme.ui_px(_DRAWN["plus"])
        self.add_button.setIcon(QtGui.QIcon(ui_helpers.device_pixmap(
            amaze.package_file("ui", "icon_comments_add.svg"), plus_side, theme.screen_ratio(self),
            {amazetheme.COMMENT_ADD_COLOR: amazetheme.COMMENT_DIM_ADD_COLOR} if dimmed else None)))
        self.add_button.setIconSize(QtCore.QSize(plus_side, plus_side))

    def copy_font_and_text_color(self, source: QtWidgets.QWidget) -> None:
        """Clone font and text colour from a .ui-loaded sibling."""
        self.text_edit.setFont(source.font())
        palette = self.text_edit.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Text,
                         source.palette().color(
                             QtGui.QPalette.ColorRole.Text))
        self.text_edit.setPalette(palette)
        self.copy_header_font(source)

    def _build_add_menu(self) -> None:
        """The + menu, set up ONCE: opens on press; a corner triangle marks it. ▸p/comment-images"""
        menu = QtWidgets.QMenu(self.add_button)    # a CHILD of the button: one menu for the session ▸r/menu-lifetime
        for key, text in pane_comments.ADD_ITEMS:
            menu.addAction(text).triggered.connect(    # addAction(str) returns the QAction ▸r/menu-lifetime
                lambda _checked=False, key=key: self._add(key))
        self.add_button.setMenu(menu)
        self.add_button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)

    def _add(self, key: str) -> None:
        """The add menu's row `key` at the text cursor; the editor takes the keys after it."""
        at = self._comments.add(key, self.text_edit.textCursor().position())
        if at >= 0:
            self.text_edit.go_to(at)
            self.text_edit.setFocus()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._comments.set_open(True)

    def hideEvent(self, event) -> None:
        self._comments.set_open(False)
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        """Save on close; a pane never shown delivers no hide event."""
        self._comments.flush()
        super().closeEvent(event)
