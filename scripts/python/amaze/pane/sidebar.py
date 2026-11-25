"""The sidebar's rows: the model shown, the pane's selection of its rows, and the work on them."""

from amaze import amazetheme
from amaze.core import category, grid_columns

KEY_PAUSE_MS = 180    #: the arrow keys' pause before the row they stop on is shown: a File step lists a folder


class Sidebar:
    """Which sidebar rows are shown and selected; the pane holds it as `sidebar`."""

    SIDEBAR_PROXY_ATTRS = {    # section key -> its sidebar proxy attribute
        "material": "category_sorted_model",
        "cop": "cop_category_sorted_model",
        "code": "code_category_sorted_model",
        "gradient": "gradient_category_sorted_model",    # Colors
    }
    DEFAULT_SIDEBAR_COLOUR = amazetheme.SIDEBAR_PICKER_START

    def __init__(self, pane) -> None:
        self.pane = pane
        self.model = None    # the rows the sidebar shows
        self.selection = None    # the host's sidebar view's selection of them

    def show_model(self, model) -> None:
        """The sidebar shows `model`'s rows; the host's view then gives its selection of them."""
        self.model = model
        self.selection = None

    def use_selection(self, selection) -> None:
        """The selection the host's sidebar view keeps; the view moves its current row when rows go."""
        self.selection = selection

    def rows(self) -> list:
        """The selected rows, one index each at the first column."""
        return grid_columns.selected_rows(self.selection)

    def current(self):
        """The current row as a fresh index, or None. ▸r/model-contracts"""
        return grid_columns.live_current_index(self.selection)

    def highlight(self, index) -> None:
        """Make `index`'s row current and selected: the app's own move, which chooses nothing."""
        self.pane.sidebar_highlight.emit(index)

    def reveal(self, path: str) -> None:
        """Unfold every folder above `path` and select it as its rows are read; File only."""
        self.pane.sidebar_reveal.emit(path)

    def show_row(self, index=None) -> None:
        """The active section shows the category or folder of `index`, else of the selected row."""
        if index is None:
            rows = self.rows()
            index = rows[0] if rows else None
        section = self.pane.active_section()
        if index is not None and section is not None:
            section.select_category(index)

    def select_key(self, key: str) -> bool:
        """Point the sidebar at the row keyed `key`, "" for All, and refilter; whether it is shown."""
        model = self.model
        if model is None:
            return False
        index = model.index_of(key)
        if index.isValid() and self.selection is not None:
            self.highlight(index)
        self.show_row()
        return index.isValid()

    def select_default_row(self, sidebar_proxy):
        """Select the sidebar's All row and return its key, ""; the caller applies the filter."""
        if sidebar_proxy is None:
            return None
        target = sidebar_proxy.index_of("")
        if not target.isValid():
            return None
        if self.selection is None:
            return None
        self.highlight(target)    # a new model leaves nothing selected
        return self.raw_category_name(target)

    def reselect(self) -> None:
        """Re-highlight the shown grid's sidebar row, after the rows were re-read."""
        context = self.pane.active_section()
        if context is not None:
            context.reselect_sidebar_row()

    @staticmethod
    def raw_category_name(index) -> str:
        """The key behind a sidebar row, never its shown name, "" on All; key every action on it."""
        if index is None or not index.isValid():
            return ""
        return str(index.data(category.SIDEBAR_KEY_ROLE) or "")    # DisplayRole drops a leading "_"

    def drop_target(self, index) -> tuple:
        """(category, folder) a tile dropped on sidebar row `index` goes to; (None, None) where none may."""
        context = self.pane.active_section()
        if context is None or index is None or not index.isValid():
            return None, None
        if context.takes_file_drops:    # a folder row: the tiles' files move there, on disk
            return None, (context.drop_folder(index) if context.accepts_file_drop(index) else None)
        name = self.raw_category_name(index)
        if (not context.takes_category_drops or not name or category.is_all(name)
                or not context.accepts_category_drop(index, name)):
            return None, None
        return name, None

    def selected_category_name(self) -> str:
        """The sidebar's category, "" for All: selection, then current index; no section check."""
        indexes = self.rows()
        index = indexes[0] if indexes else self.current()    # current but not selected after a restore
        name = self.raw_category_name(index)
        return "" if category.is_all(name) else name

    def proxies(self) -> tuple:
        """Every asset section's sidebar proxy that exists right now."""
        found = []
        for attr in self.SIDEBAR_PROXY_ATTRS.values():
            proxy = getattr(self.pane, attr, None)
            if proxy is not None:
                found.append(proxy)
        return tuple(found)

    def refresh(self) -> None:
        """Re-evaluate empty-category hiding and counts, for changes that emit no layoutChanged."""
        for proxy in self.proxies():
            proxy.refresh()
        self.pane.sidebar_changed.emit()
        self._ensure_selection(self.pane.current_section)    # the refilter may hide the grid's row

    def _ensure_selection(self, section_key: str) -> None:
        """Select All when the filter hid the grid's category in section `section_key`."""
        if self.pane.current_section != section_key:
            return
        proxy = getattr(self.pane, self.SIDEBAR_PROXY_ATTRS.get(section_key, ""), None)
        if proxy is None or self.model is not proxy:
            return
        section = self.pane.active_section()
        stack = section.stack() if section is not None else None
        if stack is None:
            return
        shown = stack.proxy.filter_value(stack.model.CategoryRole)    # the grid's filter, never the selection
        if not shown:
            return    # All: every category is a row, and All is always one
        row = proxy.index_of(shown)
        if not row.isValid():
            self.select_key("")    # the grid's category is hidden: All
            return
        current = self.current()
        if current is None or current.row() != row.row():
            self.select_key(shown)    # the row is still there and the selection moved off it

    def set_colour(self, pick: bool, preset: str = "") -> None:
        """Label ▸ on the sidebar selection: `preset`, or "" for none; `pick` asks for a colour."""
        context = self.pane.active_section()
        if context is None:
            return
        names = [context.colour_key(index)    # stored name, or a location's path in File
                 for index in self.rows()]
        names = [name for name in names    # All is skipped
                 if name and not category.is_all(name)]
        if not names:
            return

        def apply(colour):
            if colour is None:
                return
            for name in names:
                context.set_sidebar_colour(name, colour)    # the context decides the store and the repaint

        if not pick:
            apply(preset)
            return
        self.pane.ui.ask_colour(context.sidebar_colour(names[0]) or self.DEFAULT_SIDEBAR_COLOUR,
                                context.colour_title, apply)

    def assign_category(self, category_name: str) -> None:
        """Move the active section's selected assets into the category keyed `category_name`."""
        section = self.pane.active_section()
        stack = section.stack() if section is not None else None
        if stack is None:
            return
        model, proxy, selmodel, catmodel = stack
        keys = {model.tile_key(proxy.mapToSource(index).row())
                for index in grid_columns.selected_rows(selmodel)}
        if category.assign(model, catmodel, keys, (category_name or "").strip()):
            self.refresh()
