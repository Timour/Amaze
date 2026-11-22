"""The empty grid page: which empty state applies, and its text; `grid.apply_grid_face` shows it."""
from PySide6 import QtCore, QtWidgets

from amaze import amazetheme
from amaze.helpers import theme
from amaze.panel import grid

NO_MATCH = "nothing-matches"
NO_FAVOURITES = "no-favourites"
UNREACHABLE = "unreachable"

MAX_QUOTED = 24                 # the search text quoted in the headline can be any length

SHARED = amazetheme.EMPTY_SHARED    # the texts are defined once, in amazetheme ▸p/one-design-document


def _elide(text: str) -> str:
    """The user's search text, cut to MAX_QUOTED characters so a pasted paragraph stays short."""
    text = (text or "").strip()
    if len(text) <= MAX_QUOTED:
        return text
    return text[:MAX_QUOTED - 1] + "…"


def verdict(panel) -> tuple:
    """(empty state, detail) for the current section, or (None, `""`), from the visible view."""
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

    search = ""
    box = getattr(panel, "line_filter", None)
    if box is not None:
        try:
            search = (box.text() or "").strip()
        except RuntimeError:                        # a deleted widget
            search = ""
    if search:
        return (NO_MATCH, search)
    if total and _favourites_only(panel) and not _any_favourite(source):
        return (NO_FAVOURITES, "")
    return (None, "")    # an empty category or location shows its grid, and its right-click menu


def _favourites_only(panel) -> bool:
    """Whether the toolbar's favourites button is checked; False when the button is deleted."""
    chip = getattr(panel, "cb_favsonly", None)
    if chip is None:
        return False
    try:
        return bool(chip.isChecked())
    except RuntimeError:
        return False


def _any_favourite(source) -> bool:
    """Whether any row of `source` is a favourite; with none, the NO_FAVOURITES page is shown."""
    role = getattr(source, "FavoriteRole", None)
    if role is None:
        return True    # a model with no FavoriteRole never shows the NO_FAVOURITES page
    return any(source.index(row, 0).data(role)
               for row in range(source.rowCount()))


def unreadable_folder(panel) -> str:
    """The first still-registered folder the File model could not read, or ""."""
    if getattr(panel.pane, "current_section", "") != "file":
        return ""
    model = getattr(panel.pane, "file_files_model", None)
    folders = getattr(model, "_unreadable_folders", None)
    if not folders:
        return ""
    sidebar = getattr(panel.pane, "file_folders_model", None)
    current = ("" if getattr(model, "_all_folders_mode", True)
               else getattr(model, "_folder", ""))
    for folder in sorted(folders):
        if current and folder != current:
            continue    # only the folder being looked at counts
        if sidebar is None or sidebar.row_of(folder) is not None:
            return folder
    return ""



def words_for(panel, blank: str, detail: str) -> tuple:
    """(headline, sentence, button label, handler) with %s filled in; no handler means no button."""
    section = panel.pane.active_section()
    words = SHARED.get(blank)
    if not words:
        return ("", "", "", "")

    headline, sentence, label, handler = words
    if "%s" in headline:
        headline = headline % _elide(detail)
    if "%s" in sentence:
        filler = detail if blank == UNREACHABLE \
            else getattr(section, "empty_noun", "items")
        sentence = sentence % filler
    return (headline, sentence, label, handler)


class EmptyPage(QtWidgets.QWidget):
    """The empty-state labels and button, with no geometry code. ▸r/transparent-for-mouse"""

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
                               | QtCore.Qt.AlignmentFlag.AlignTop)    # the label centres its own text ▸r/label-centres-itself
            outer.addWidget(label)
            outer.addSpacing(theme.ui_px(8))

        self._btn = QtWidgets.QPushButton("", self)
        outer.addWidget(self._btn, 0,
                        QtCore.Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self._handler_name = ""

    def button(self):
        return self._btn

    def say(self, panel, blank: str, detail: str) -> None:
        """Show this empty state's texts and connect its button to the method its path names."""
        headline, sentence, label, handler_name = words_for(panel, blank, detail)
        self._head.setText(headline)
        self._head.setVisible(bool(headline))
        self._text.setText(sentence)
        self._text.setVisible(bool(sentence))

        handler = getattr(panel, handler_name, None) if handler_name else None
        wanted = bool(label) and callable(handler)
        self._btn.setText(label if wanted else "")
        self._btn.setVisible(wanted)
        if self._handler_name != handler_name:
            if self._handler_name:          # only ever one connection
                self._btn.clicked.disconnect()
            if wanted:
                self._btn.clicked.connect(handler)
            self._handler_name = handler_name


def page(panel):
    """The panel's EmptyPage, created and added to the grid pane on the first call."""
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
    """The only entry point: recompute the empty state and pass it to `grid.apply_grid_face`."""
    blank, detail = verdict(panel)
    surface = page(panel)
    if surface is None:
        return
    if blank:
        surface.say(panel, blank, detail)
    grid.apply_grid_face(panel, bool(blank))


def track(panel) -> None:
    """Watch the model, so every change to the row count reaches `refresh`."""
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
               model.modelReset, model.layoutChanged,
               model.refiltered)    # a search that hides nothing still changes the words
    for signal in watched:
        signal.connect(panel._empty_refresh)
    panel._empty_watch = watched
    refresh(panel)
