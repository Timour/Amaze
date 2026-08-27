"""THE EMPTY STATE ENGINE - which blank the grid is showing: a SIBLING of the two grid views whose visibilities `grid.apply_grid_face` owns (nothing here positions anything), words in the UI text register, and every `SHARED` row is (headline, sentence, button label, verb) with a blank verb meaning no button (devlog 480)."""
from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.helpers import theme
from amaze.panel import grid

NOTHING_YET = "nothing-yet"
NO_MATCH = "nothing-matches"
NOTHING_HERE = "nothing-here"
NO_FAVOURITES = "no-favourites"
UNREACHABLE = "unreachable"

MAX_QUOTED = 24                 # the quoted search is unbounded input

SHARED = amazetheme.EMPTY_SHARED    # the WORDS are the design's, declared once ▸p/one-design-document


def _elide(text: str) -> str:
    """The user's own string, capped so a pasted paragraph cannot run."""
    text = (text or "").strip()
    if len(text) <= MAX_QUOTED:
        return text
    return text[:MAX_QUOTED - 1] + "…"


def verdict(panel) -> tuple:
    """(blank, detail) for the current section, or (None, "") - read off the VIEW, whose proxy answers both counts."""
    view = grid.visible_view(panel)
    if view is None:
        return (None, "")
    proxy = view.model()
    if proxy is None:
        return (None, "")
    if proxy.rowCount() > 0:
        return (None, "")

    unreadable = unreadable_folder(panel)
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
    if _favourites_only(panel) and not _any_favourite(source):
        return (NO_FAVOURITES, "")
    return (NOTHING_HERE, _current_category(panel))


def _favourites_only(panel) -> bool:
    """Is the toolbar's favourites star down? Read defensively, like the search box above - a deleted chip answers RuntimeError."""
    chip = getattr(panel, "cb_favsonly", None)
    if chip is None:
        return False
    try:
        return bool(chip.isChecked())
    except RuntimeError:
        return False


def _any_favourite(source) -> bool:
    """Does ANY row of `source` carry a star? Separates a library with no favourites at all (its own blank) from a category that merely holds none of them (the category blank still explains that one, and its Show All lands on the favourites)."""
    role = getattr(source, "FavoriteRole", None)
    if role is None:
        return True    # a model with no star column cannot claim "no favorites yet"
    return any(source.index(row, 0).data(role)
               for row in range(source.rowCount()))


def unreadable_folder(panel) -> str:
    """The first STILL-REGISTERED folder the File model could not read, or "" - without it a dead drive looks like an empty one, and without the registration test a folder that was located or removed goes on being complained about, since only a scan of it can clear the flag."""
    if getattr(panel, "current_section", "") != "file":
        return ""
    model = getattr(panel, "file_files_model", None)
    folders = getattr(model, "_unreadable_folders", None)
    if not folders:
        return ""
    sidebar = getattr(panel, "file_folders_model", None)
    current = ("" if getattr(model, "_all_folders_mode", True)
               else getattr(model, "_folder", ""))
    for folder in sorted(folders):
        if current and folder != current:
            continue    # the blank describes the folder being LOOKED AT - a dead folder elsewhere must not hijack a healthy folder's no-match
        if sidebar is None or sidebar.row_of(folder) is not None:
            return folder
    return ""


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


def quote_for(panel, blank: str) -> tuple:
    """(line, attribution) drawn under a section's FIRST-RUN sentence, or ("", "") - a section declares its own in `QUOTE`, and no other blank carries one."""
    if blank != NOTHING_YET:
        return ("", "")
    section = panel._section() if hasattr(panel, "_section") else None
    quote = getattr(section, "QUOTE", None) or ()
    if len(quote) != 2:
        return ("", "")
    return (str(quote[0]), str(quote[1]))


def words_for(panel, blank: str, detail: str) -> tuple:
    """(headline, sentence, button label, verb) with %s filled in - UNREACHABLE quotes a path whole, the rest take the section's noun."""
    section = panel._section() if hasattr(panel, "_section") else None
    table = dict(SHARED)
    declared = getattr(section, "EMPTY", None) or {}
    table.update(declared)
    words = table.get(blank)
    if not words:
        return ("", "", "", "")

    headline, sentence, label, verb = words
    if "%s" in headline:
        headline = headline % _elide(detail)
    if "%s" in sentence:
        filler = detail if blank == UNREACHABLE \
            else getattr(section, "empty_noun", "items")
        sentence = sentence % filler
    return (headline, sentence, label, verb)


class EmptyPage(QtWidgets.QWidget):
    """The words. NO geometry code, deliberately - no `setGeometry`, no event filter, no `paintEvent`, and never `WA_TransparentForMouseEvents`. ▸r/transparent-for-mouse (devlog 480)"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        base = self.font()
        outer = QtWidgets.QVBoxLayout(self)
        pad = theme.ui_px(24)
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.addStretch(1)

        self._head = QtWidgets.QLabel("", self)
        self._head.setFont(theme.font("empty_headline", base))
        self._text = QtWidgets.QLabel("", self)
        for label in (self._head, self._text):
            label.setWordWrap(True)
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter
                               | QtCore.Qt.AlignmentFlag.AlignTop)    # the label fills the pane and CENTRES ITS OWN TEXT - neither layout route works ▸r/label-centres-itself
            outer.addWidget(label)
            outer.addSpacing(theme.ui_px(8))

        self._quote = QtWidgets.QLabel("", self)    # the quotation and its attribution: italic, and the sentence's own ink at half strength, as drawn
        self._quote.setFont(theme.font("empty_quote", base))
        self._quote.setWordWrap(True)
        self._quote.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter
                                 | QtCore.Qt.AlignmentFlag.AlignTop)
        dim = QtGui.QColor(theme.color_hex("text"))
        dim.setAlphaF(0.5)
        quote_palette = self._quote.palette()    # a PALETTE, never a stylesheet: the alpha survives and the glyphs paint through it ▸r/palette-alpha
        quote_palette.setColor(QtGui.QPalette.ColorRole.WindowText, dim)
        self._quote.setPalette(quote_palette)
        outer.addWidget(self._quote)
        outer.addSpacing(theme.ui_px(8))

        self._btn = QtWidgets.QPushButton("", self)
        outer.addWidget(self._btn, 0,
                        QtCore.Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self._verb = ""

    def button(self):
        return self._btn

    def say(self, panel, blank: str, detail: str) -> None:
        """Put this blank's words up and wire its button."""
        headline, sentence, label, verb = words_for(panel, blank, detail)
        self._head.setText(headline)
        self._head.setVisible(bool(headline))
        self._text.setText(sentence)
        self._text.setVisible(bool(sentence))

        line, attribution = quote_for(panel, blank)
        self._quote.setText("%s\n%s" % (line, attribution) if line else "")
        self._quote.setVisible(bool(line))

        handler = getattr(panel, verb, None) if verb else None
        wanted = bool(label) and callable(handler)
        self._btn.setText(label if wanted else "")
        self._btn.setVisible(wanted)
        if self._verb != verb:
            if self._verb:                  # only ever one connection
                self._btn.clicked.disconnect()
            if wanted:
                self._btn.clicked.connect(handler)
            self._verb = verb


def page(panel):
    """The panel's one page, built and mounted on first ask."""
    found = getattr(panel, "empty_page", None)
    if found is not None:
        return found
    host = grid.grid_pane_layout(panel)
    if host is None:
        return None
    found = EmptyPage(host.parentWidget())
    found.setVisible(False)
    host.addWidget(found)
    panel.empty_page = found
    return found


def refresh(panel) -> None:
    """The ONE door: re-derive the blank and hand it to `grid`."""
    blank, detail = verdict(panel)
    surface = page(panel)
    if surface is None:
        return
    if blank:
        surface.say(panel, blank, detail)
    grid.apply_grid_face(panel, bool(blank))


def track(panel) -> None:
    """Watch the model, so all six paths that change the row count reach `refresh` without naming themselves (devlog 480)."""
    view = grid.visible_view(panel)
    model = view.model() if view is not None else None
    if model is None:
        return
    previous = getattr(panel, "_empty_watch", None)
    if previous is not None:
        for signal in previous:
            try:
                signal.disconnect(panel._empty_refresh)
            except (RuntimeError, TypeError):
                pass
    panel._empty_refresh = lambda *_: refresh(panel)
    watched = (model.rowsInserted, model.rowsRemoved,
               model.modelReset, model.layoutChanged)
    for signal in watched:
        signal.connect(panel._empty_refresh)
    panel._empty_watch = watched
    refresh(panel)
