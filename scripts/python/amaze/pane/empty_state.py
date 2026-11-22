"""Which empty state the shown grid has, and its words; the pane holds it as `empty_state`."""

from amaze import amazetheme

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


def _any_favourite(source) -> bool:
    """Whether any row of `source` is a favourite; with none, the NO_FAVOURITES page is shown."""
    role = getattr(source, "FavoriteRole", None)
    if role is None:
        return True    # a model with no FavoriteRole never shows the NO_FAVOURITES page
    return any(source.index(row, 0).data(role)
               for row in range(source.rowCount()))


class EmptyState:
    """The one rule both hosts show: which empty state applies, its words, when it may change."""

    WATCHED = ("rowsInserted", "rowsRemoved", "modelReset", "layoutChanged",
               "refiltered")    # a search that hides nothing still changes the words

    def __init__(self, pane) -> None:
        self.pane = pane
        self._watched = None    # the proxy whose signals reach `_rows_changed`

    def proxy(self):
        """The shown context's grid proxy, the one `activate` binds; None before one is shown."""
        section = self.pane.active_section()
        attr = getattr(section, "proxy_attr", "") if section is not None else ""
        return getattr(self.pane, attr, None) if attr else None

    def verdict(self) -> tuple:
        """(empty state, detail) for the shown grid, or (None, `""`)."""
        proxy = self.proxy()
        if proxy is None or proxy.rowCount() > 0:
            return (None, "")
        unreadable = self.unreadable_folder()
        if unreadable:
            return (UNREACHABLE, unreadable)
        source = proxy.sourceModel() if hasattr(proxy, "sourceModel") else None
        total = source.rowCount() if source is not None else 0
        search = (self.pane.search_text or "").strip()
        if search:
            return (NO_MATCH, search)
        if total and self.pane.favourites_only and not _any_favourite(source):
            return (NO_FAVOURITES, "")
        return (None, "")    # an empty category or location shows its grid, and its right-click menu

    def unreadable_folder(self) -> str:
        """The first still-registered folder the File model could not read, or ""."""
        pane = self.pane
        if getattr(pane, "current_section", "") != "file":
            return ""
        model = getattr(pane, "file_files_model", None)
        folders = getattr(model, "_unreadable_folders", None)
        if not folders:
            return ""
        sidebar = getattr(pane, "file_folders_model", None)
        current = ("" if getattr(model, "_all_folders_mode", True)
                   else getattr(model, "_folder", ""))
        for folder in sorted(folders):
            if current and folder != current:
                continue    # only the folder being looked at counts
            if sidebar is None or sidebar.row_of(folder) is not None:
                return folder
        return ""

    def words(self, blank: str, detail: str) -> tuple:
        """(headline, sentence, button label, handler) with %s filled in; no handler means no button."""
        words = SHARED.get(blank)
        if not words:
            return ("", "", "", "")
        headline, sentence, label, handler = words
        if "%s" in headline:
            headline = headline % _elide(detail)
        if "%s" in sentence:
            filler = detail if blank == UNREACHABLE \
                else getattr(self.pane.active_section(), "empty_noun", "items")
            sentence = sentence % filler
        return (headline, sentence, label, handler)

    def watch(self) -> None:
        """Follow the shown grid's rows, then say the verdict may have changed."""
        proxy = self.proxy()
        if proxy is not self._watched:
            self._follow(self._watched, False)
            self._follow(proxy, True)
            self._watched = proxy
        self.pane.empty_changed.emit()

    def _follow(self, proxy, on: bool) -> None:
        if proxy is None:
            return
        for name in self.WATCHED:
            signal = getattr(proxy, name, None)
            if signal is None:
                continue
            try:
                if on:
                    signal.connect(self._rows_changed)
                else:
                    signal.disconnect(self._rows_changed)
            except (RuntimeError, TypeError):    # a proxy deleted with another pane
                pass

    def _rows_changed(self, *_args) -> None:
        self.pane.empty_changed.emit()
