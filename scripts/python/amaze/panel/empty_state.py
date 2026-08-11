"""THE EMPTY STATE ENGINE - what the grid says when it has nothing.

THE ENGINE DECIDES WHICH BLANK; A SECTION DECLARES ONLY ITS WORDS -
the same split the Keyed Store Engine uses. Five sections times four
blanks is twenty states, so the arithmetic of "is this empty, and why"
lives once or it lives five times and disagrees.

FOUR BLANKS, each derived from what the panel already holds:
`nothing-yet` (no rows at all), `nothing-matches` (rows exist, a
search is set), `nothing-here` (rows exist, another filter is on) and
`unreachable` (File only, a registered folder could not be read).

The design is practice.md ▸ *Empty states are the best teaching moment
in the app*; the width bands are measured in research.md ▸ *WHAT A
SQUEEZED PANEL ACTUALLY LEAVES THE GRID*, and overview.md ▸ 4i is the
map entry.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.helpers import theme
from amaze.panel import grid


#: Which blank. Named rather than returned as prose so a caller can
#: branch, and so a test can name the case it means.
NOTHING_YET = "nothing-yet"
NO_MATCH = "nothing-matches"
NOTHING_HERE = "nothing-here"
UNREACHABLE = "unreachable"

#: Below this the button goes and the sentence stays. Design pixels.
FULL_WIDTH = 420

#: Below either of these nothing is drawn at all.
MIN_WIDTH = 250
MIN_HEIGHT = 60

#: The sentence never runs wider than this, however wide the grid is -
#: a 1200px line of 12px text is a paragraph, not a caption.
MAX_TEXT_WIDTH = 420

#: A search string is the user's own text and has no length limit: one
#: pasted path makes the headline wider than any panel. Elided here
#: rather than hoped about.
MAX_QUOTED = 24


#: The three blanks every section says the same way - only the NOUN
#: differs, and `Section.empty_noun` carries it. A section may override
#: any of them in its own `EMPTY`.
SHARED = {
    NO_MATCH: (
        "Nothing matches “%s”",
        "No saved %s has that in its name, tags or category.",
        "Clear search", "clear_filter_box"),
    NOTHING_HERE: (
        "Nothing in “%s”",
        "Your other categories still have %s in them.",
        "Show all", "show_all_categories"),
    UNREACHABLE: (
        "This folder cannot be reached",
        "%s\n\nIt may be a disconnected drive, or a sync that has not "
        "finished. Nothing has been removed — the files come back when "
        "the folder does.",
        "", ""),
}


def _elide(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_QUOTED:
        return text
    return text[:MAX_QUOTED - 1] + "…"


def verdict(panel) -> tuple:
    """(blank, detail) for the panel's current section, or (None, "").

    Read off the VIEW the user is looking at, not off a section's
    internals: `visible_view` already owns which of the two grid views
    is up, and the proxy behind it answers both counts. `detail` is
    whatever the sentence needs to quote back - the search string, the
    category, the folder that could not be read.
    """
    view = grid.visible_view(panel)
    if view is None:
        return (None, "")
    proxy = view.model()
    if proxy is None:
        return (None, "")
    if proxy.rowCount() > 0:
        return (None, "")

    unreadable = _unreadable_folder(panel)
    if unreadable:
        return (UNREACHABLE, unreadable)

    source = proxy.sourceModel() if hasattr(proxy, "sourceModel") else None
    total = source.rowCount() if source is not None else 0
    if not total:
        return (NOTHING_YET, "")

    search = ""
    box = getattr(panel, "line_filter", None)
    if box is not None:
        try:
            search = (box.text() or "").strip()
        except RuntimeError:                        # a deleted widget
            search = ""
    if search:
        return (NO_MATCH, search)
    return (NOTHING_HERE, _current_category(panel))


def _unreadable_folder(panel) -> str:
    """The first registered folder the File model could not read, or "".

    THE FACT WAS ALREADY COMPUTED AND THROWN AWAY. `FileFilesModel`
    fills `_unreadable_folders` on every scan and nothing has ever read
    it, so a disconnected drive and an empty folder have looked
    identical - the exact thing that model's own comment says must not
    happen.
    """
    if getattr(panel, "current_section", "") != "file":
        return ""
    model = getattr(panel, "file_files_model", None)
    folders = getattr(model, "_unreadable_folders", None)
    if not folders:
        return ""
    return sorted(folders)[0]


def _current_category(panel) -> str:
    """The category the sidebar is on, or "" for All."""
    view = getattr(panel, "cat_list", None)
    if view is None:
        return ""
    try:
        index = view.currentIndex()
        if not index.isValid():
            return ""
        name = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
    except RuntimeError:
        return ""
    name = str(name)
    return "" if name in ("All", "_All") else name


class EmptyState(QtWidgets.QWidget):
    """The one surface, over the grid pane.

    Parented to the PANE rather than to either view: the two views swap
    (show_table), and a surface owned by one of them would vanish with
    it. Transparent for mouse events it does not use, so a right-click
    on empty grid still opens the section's menu - the menu law covers
    the no-selection case deliberately and an overlay must not take
    that away.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents,
                          True)
        self._headline = ""
        self._body = ""
        self._button = ""
        #: Whether this blank has a button at all, kept apart from the
        #: width band so a narrow grid hides it without forgetting.
        self._wanted_button = False
        self._tracked = None
        self._connection = None

        self._btn = QtWidgets.QPushButton(self)
        self._btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        # The button is the one thing here that IS clickable, so it
        # takes mouse events back from the transparent parent.
        self._btn.setAttribute(
            QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._btn.hide()

    def track(self, view) -> None:
        """Follow the view's geometry, without the panel bookkeeping it.

        The surface owns this because the panel already owns "what is
        shown changed" and one of those is enough for it to know. A
        resize is not a content change and must not travel through the
        content path - that is how the deleted list-row sizing ended up
        recomputing on every viewport resize.
        """
        if self._tracked is view:
            return
        if self._tracked is not None:
            try:
                self._tracked.removeEventFilter(self)
            except RuntimeError:
                pass
        self._tracked = view
        if view is not None:
            view.installEventFilter(self)

    def eventFilter(self, watched, event):
        if (event.type() == QtCore.QEvent.Type.Resize
                and watched is self._tracked):
            self.setGeometry(watched.geometry())
            self._apply_band()
        return False

    def _apply_band(self) -> None:
        """Hide, or drop the button, by the measured widths."""
        if (self.width() < theme.ui_px(MIN_WIDTH)
                or self.height() < theme.ui_px(MIN_HEIGHT)):
            self.hide()
            return
        self._btn.setVisible(bool(self._button) and self._wanted_button
                             and self.width() >= theme.ui_px(FULL_WIDTH))
        self.show()
        self.update()

    def set_state(self, headline: str, body: str, button: str) -> None:
        self._headline = headline or ""
        self._body = body or ""
        self._button = button or ""
        self._btn.setText(self._button)
        self.update()

    def set_verb(self, handler) -> None:
        """What the button does, rebound each time.

        Disconnected first: this surface outlives every state it shows,
        so connecting without clearing would fire one click into every
        handler it had ever been given.
        """
        self._wanted_button = bool(self._button) and handler is not None
        # The connection is HELD: a bare `disconnect()` on a signal
        # with nothing attached warns rather than raising, so no except
        # clause catches it.
        if self._connection is not None:
            try:
                self._btn.clicked.disconnect(self._connection)
            except (RuntimeError, TypeError):
                pass
            self._connection = None
        if handler is not None:
            self._connection = self._btn.clicked.connect(
                lambda _=False, h=handler: h())

    def button(self) -> QtWidgets.QPushButton:
        return self._btn

    def paintEvent(self, event) -> None:
        """Hand-painted, and it stops there.

        The BUTTON is a real QPushButton so it inherits Houdini's
        stylesheet and looks like every other button in the host -
        research.md is explicit that the app-wide sheet is ours and
        every child inherits it, and that the fix for a widget that
        looks wrong is to stop fighting the sheet rather than out-paint
        it. The text is painted because two labels in a layout cost a
        layout pass on a surface that is usually not shown at all.
        """
        if not self._headline:
            return
        width = self.width()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, True)

        column = min(theme.ui_px(MAX_TEXT_WIDTH), width - theme.ui_px(32))
        left = (width - column) // 2

        head_font = QtGui.QFont(self.font())
        head_font.setBold(True)
        head_font.setPixelSize(max(1, theme.ui_px(15)))
        body_font = QtGui.QFont(self.font())

        head_metrics = QtGui.QFontMetrics(head_font)
        body_metrics = QtGui.QFontMetrics(body_font)
        flags = int(QtCore.Qt.TextFlag.TextWordWrap
                    | QtCore.Qt.AlignmentFlag.AlignHCenter)

        head_rect = head_metrics.boundingRect(
            0, 0, column, 0, flags, self._headline)
        show_body = bool(self._body) and self._can_show_body()
        body_rect = QtCore.QRect()
        if show_body:
            body_rect = body_metrics.boundingRect(
                0, 0, column, 0, flags, self._body)

        gap = theme.ui_px(10)
        total = head_rect.height()
        if show_body:
            total += gap + body_rect.height()
        if self._btn.isVisible():
            total += gap + self._btn.sizeHint().height()

        y = max(theme.ui_px(8), (self.height() - total) // 2)

        painter.setFont(head_font)
        painter.setPen(theme.color("text_bright"))
        painter.drawText(QtCore.QRect(left, y, column, head_rect.height()),
                         flags, self._headline)
        y += head_rect.height()

        if show_body:
            y += gap
            painter.setFont(body_font)
            painter.setPen(theme.color("text"))
            painter.drawText(QtCore.QRect(left, y, column, body_rect.height()),
                             flags, self._body)
            y += body_rect.height()

        if self._btn.isVisible():
            y += gap
            hint = self._btn.sizeHint()
            self._btn.setGeometry((width - hint.width()) // 2, y,
                                  hint.width(), hint.height())
        painter.end()

    def _can_show_body(self) -> bool:
        return self.width() >= theme.ui_px(FULL_WIDTH)


def refresh(panel) -> None:
    """THE ONE DOOR. Ask the engine what the grid should say, and say it.

    Cheap enough to call from anything that changes what is shown - it
    reads two row counts and returns immediately when the grid has
    rows, which is the case every time but one.
    """
    blank, detail = verdict(panel)
    surface = _surface(panel)
    if surface is None:
        return
    if blank is None:
        surface.hide()
        return

    from amaze.panel import sections as sections_module

    section = sections_module.SECTION_INDEX.get(
        getattr(panel, "current_section", ""))
    # The section first, then the shared shape.
    words = (getattr(section, "EMPTY", None) or {}).get(blank)
    if not words:
        words = SHARED.get(blank)
    if not words:
        surface.hide()
        return

    headline, body, button, verb = words
    if "%s" in headline:
        headline = headline % _elide(detail)
    if "%s" in body:
        # The BODY takes the noun for the shared sentences and the raw
        # detail for the unreachable one, which quotes a path.
        filler = detail if blank == UNREACHABLE else getattr(
            section, "empty_noun", "items")
        body = body % filler

    view = grid.visible_view(panel)
    if view is None:
        surface.hide()
        return

    handler = getattr(panel, verb, None) if verb else None
    surface.set_state(headline, body, button)
    surface.set_verb(handler if callable(handler) else None)
    surface.track(view)
    surface.setGeometry(view.geometry())
    # THE BAND DECIDES WHETHER ANY OF THAT IS SHOWN, and it is the
    # surface's own question - the same one it re-asks on every resize
    # without the panel being told.
    surface._apply_band()
    surface.raise_()


def _surface(panel):
    """The panel's one EmptyState, built on first use.

    On the GRID PANE, which does not swap, rather than on a view that
    does. Built lazily because a panel that never empties never needs
    it, and because this must not add a widget to the construction path
    that every panel open pays for.
    """
    surface = getattr(panel, "_empty_state", None)
    if surface is not None:
        return surface
    view = grid.visible_view(panel)
    if view is None:
        return None
    parent = view.parentWidget()
    if parent is None:
        return None
    surface = EmptyState(parent)
    panel._empty_state = surface
    return surface
