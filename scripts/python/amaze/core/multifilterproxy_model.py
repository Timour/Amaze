"""The asset sections' proxy: several role filters at once, over the shared grid invariant."""

from PySide6 import QtCore

from amaze.core import grid_proxy


def split_search(text) -> tuple:
    """(needle, tags_only) from the filter box - the ONE home of the colon rules: a LEADING ":" means tags only, a bare ":" is the moment before the tag, not a search. Both the local sections and the online model split through here."""
    needle = (text or "").strip().lower()
    if needle.startswith(":"):
        return needle[1:].strip(), True
    return needle, False


class MultiFilterProxyModel(grid_proxy.GridProxyModel):
    """The FILTERS - which roles this proxy matches on and how; what is shown and in what ORDER is the base class's. ▸r/filter-role-numbers"""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._filters = {}
        self._folded = {}  # role -> the lowered spelling of a STRING filter, folded ONCE at set time - filterAcceptsRow ran .lower() per row per keystroke; the favourites role compares raw and stays out

    def watched_roles(self):
        """Exactly what this proxy reads: the roles it filters on now, plus the ones it orders by."""
        return set(self._filters) | {self.sortRole(), self.sort_column_role()}    # the sort COLUMN's role too: sorting by Favorite orders on FavoriteRole, and watching DisplayRole alone left a starred row sitting in its old place

    def setFilter(self, filter_role, filter_value):
        """Filter on one role; an empty string clears it. ▸r/filter-role-numbers"""
        if filter_value == "":    # exact match, not falsy: False is a real FavoriteRole value, and storing dead entries costs a data() call per row per filter forever
            self.removeFilter(filter_role)
            return
        self._filters[filter_role] = filter_value
        self._folded[filter_role] = (filter_value.lower()
                                     if isinstance(filter_value, str)
                                     else filter_value)
        self.refilter()

    def filter_value(self, filter_role):
        """What this proxy filters `filter_role` on, or None when it does not - the one reader, so a caller comparing the grid's category against the sidebar need not reach into the store."""
        return self._filters.get(filter_role)

    def removeFilter(self, filter_role):
        if not self._filters:
            return
        if filter_role in self._filters.keys():
            del self._filters[filter_role]
            self._folded.pop(filter_role, None)
            self.refilter()    # immediately, or rows stay hidden by the REMOVED filter until something else invalidates the proxy

    def _name_matches(self, needle: str, index) -> bool:
        """Does this row answer the search text? The ONE test a section may widen rather than copy the whole filter walk; `needle` arrives already lower-folded."""
        name = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        return needle in name.lower()

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex,
    ) -> bool:
        if not self._filters:
            return True

        name_filter = True
        cat_filter = True
        tag_filter = True
        render_filter = True
        index = self.sourceModel().index(source_row, 0, source_parent)
        for role, curr_filter in self._filters.items():
            data = index.data(role)
            folded = self._folded.get(role, curr_filter)  # lowered at set time; only the raw-comparing favourites role reads curr_filter

            if role == 0:  # Check Names
                if curr_filter != "" \
                        and not self._name_matches(folded, index):
                    name_filter = False
            elif role == 257:  # Check Category: a row matches if ANY of its categories equals the filter
                if curr_filter == "":
                    cat_filter = True
                elif len(data) < 1:
                    cat_filter = False
                else:
                    cat_filter = any(
                        folded == str(elem).strip().lower()
                        for elem in data
                    )

            elif role == 258:  # Check Favorite:
                if curr_filter != data and curr_filter != "":
                    return False
            elif role == 259:  # Check Renderer: all_renderers is tested FIRST and an empty renderer is no special case - repair mints those rows ▸r/filter-role-numbers
                if folded not in data.lower():
                    if "all_renderers" not in folded:
                        render_filter = False

            elif role == 260:  # is TagRole: an empty filter accepts every row INCLUDING one with no tags - testing that inside the loop hid every untagged material ▸r/filter-role-numbers
                if curr_filter == "":
                    tag_filter = True
                else:
                    tag_filter = any(
                        folded in str(elem).lower() for elem in data
                    )

        if tag_filter and cat_filter and name_filter and render_filter:    # no fav_filter: the favourites role returns early above
            return True
        return False
