"""THE EMPTY STATE ENGINE - which blank the grid is showing.

Words in `docs/architecture/ui-text.md`; a SIBLING of the two grid
views and never an overlay, so `grid.apply_grid_face` owns all three
visibilities and nothing here positions anything (devlog 480).
"""
from PySide6 import QtCore, QtWidgets

from amaze.helpers import theme
from amaze.panel import grid

NOTHING_YET = "nothing-yet"
NO_MATCH = "nothing-matches"
NOTHING_HERE = "nothing-here"
UNREACHABLE = "unreachable"

MAX_QUOTED = 24                 # the quoted search is unbounded input
MAX_MEASURE = 420               # the readable measure, centred in the pane

#: (headline, sentence, button label, verb); a blank verb means no
#: button.
SHARED = {
    NO_MATCH: (
        'Nothing matches "%s"',
        "No saved %s has that in its name, tags or category.",
        "Clear Search", "clear_filter_box"),
    NOTHING_HERE: (
        'Nothing in "%s"',
        "Your other categories still have %s in them.",
        "Show All", "show_all_categories"),
    UNREACHABLE: (
        "Can't read that folder",
        "%s did not answer. It may be a drive that is not mounted, or "
        "a share that is offline. Nothing has been removed from your "
        "library.",
        "", ""),
}


def _elide(text: str) -> str:
    """The user's own string, capped so a pasted paragraph cannot run."""
    text = (text or "").strip()
    if len(text) <= MAX_QUOTED:
        return text
    return text[:MAX_QUOTED - 1] + "…"


def verdict(panel) -> tuple:
    """(blank, detail) for the current section, or (None, "") - read
    off the VIEW, whose proxy answers both counts."""
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
    """The first folder the File model could not read, or "" - its only
    reader, and without it a dead drive looks like an empty one."""
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


def words_for(panel, blank: str, detail: str) -> tuple:
    """(headline, sentence, button label, verb) with %s filled in."""
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
        # UNREACHABLE quotes a path whole; the rest take the noun.
        filler = detail if blank == UNREACHABLE \
            else getattr(section, "empty_noun", "items")
        sentence = sentence % filler
    return (headline, sentence, label, verb)


class EmptyPage(QtWidgets.QWidget):
    """The words. NO geometry code, deliberately - no `setGeometry`, no
    event filter, no `paintEvent`, and no
    `WA_TransparentForMouseEvents`, which suppresses mouse delivery to
    a widget AND its children (devlog 480).
    """

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
                               | QtCore.Qt.AlignmentFlag.AlignTop)
            label.setMaximumWidth(theme.ui_px(MAX_MEASURE))
            # NO ALIGNMENT ARGUMENT: an aligned item is given its size
            # HINT width, so a wrapping label added that way clips
            # instead of wrapping, and Qt centres it anyway
            # (research.md > Qt widgets, views & painting).
            outer.addWidget(label)
            outer.addSpacing(theme.ui_px(8))

        self._btn = QtWidgets.QPushButton("", self)
        # The flag IS right here - a button takes its own width.
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
    """Watch the model, so all six paths that change the row count
    reach `refresh` without naming themselves (devlog 480)."""
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
