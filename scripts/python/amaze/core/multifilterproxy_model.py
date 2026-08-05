"""
Provides a Model for filtering multiple Parameters at the same time
"""

from PySide6 import QtCore

from amaze.core import grid_proxy


class MultiFilterProxyModel(grid_proxy.GridProxyModel):
    """
    Provides a Model for filtering multiple Parameters at the same time

    The asset sections' proxy. WHAT IS SHOWN AND IN WHAT ORDER is the
    base class's (core/grid_proxy.py), shared with the File and Color
    proxies; what is left here is the FILTERS - which roles this one
    matches on, and how.
    """

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._filters = {}

    def watched_roles(self):
        """Exactly what this proxy reads: the roles it is filtering on
        right now, plus the one it sorts by. Anything else - a
        thumbnail landing, a colour picked on the sidebar, a note badge
        appearing - changes nothing about what is shown or where."""
        return set(self._filters) | {self.sortRole()}

    def setFilter(self, filter_role, filter_value):
        """
        Sets the Filter for the given role

        :param self: Description
        :param filter_role: Description
        :param filter_value: Description
        """
        if filter_value == "":
            # An empty-string filter accepts everything - store nothing
            # (dead entries otherwise accumulate and cost a data() call
            # per row per filter forever). Exact match: False is a real
            # FavoriteRole filter value.
            self.removeFilter(filter_role)
            return
        self._filters[filter_role] = filter_value
        self.refilter()

    def removeFilter(self, filter_role):
        if not self._filters:
            return
        if filter_role in self._filters.keys():
            del self._filters[filter_role]
            # Refilter immediately - without this, rows stayed hidden
            # by the REMOVED filter until some other change happened to
            # invalidate the proxy (Elmar-era gap; callers papered over
            # it with their own invalidate() calls).
            self.refilter()

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

            if role == 0:  # Check Names
                if curr_filter == "":
                    name_filter = True
                if curr_filter.lower() not in data.lower():
                    name_filter = False
            elif role == 257:  # Check Category:
                # A material matches if ANY of its categories equals the
                # filter (materials can belong to multiple categories).
                if curr_filter == "":
                    cat_filter = True
                elif len(data) < 1:
                    cat_filter = False
                else:
                    cat_filter = any(
                        curr_filter.lower() == str(elem).strip().lower()
                        for elem in data
                    )

            elif role == 258:  # Check Favorite:
                if curr_filter != data and curr_filter != "":
                    return False
            elif role == 259:  # Check Renderer:
                # "all_renderers" is tested FIRST, and an empty renderer
                # is no longer a special case. It used to be rejected
                # before the All escape was ever reached, which made a
                # row with renderer="" invisible under EVERY setting of
                # the menu - there was no way to see it at all.
                #
                # Repair mints exactly that: reattach() recovers orphaned
                # files with renderer="", then the completion dialog
                # tells the user to "Open Amaze to see them - they are in
                # the Recovered category". They were not there, and the
                # route out was closed too, because Edit Info needs a
                # tile the user can select. All must mean all.
                if curr_filter.lower() not in data.lower():
                    if "all_renderers" not in curr_filter.lower():
                        render_filter = False

            elif role == 260:  # is TagRole
                # Empty filter must accept every row, including one with no
                # tags at all - checking this only inside the loop meant an
                # empty `data` list (a material with zero tags) skipped the
                # loop body entirely and fell through to the pre-loop
                # tag_filter = False, wrongly excluding untagged materials
                # even when no tag filter was active.
                if curr_filter == "":
                    tag_filter = True
                else:
                    tag_filter = any(
                        curr_filter.lower() in str(elem).lower() for elem in data
                    )

        # (no fav_filter: the favourites role returns early above, so
        # the variable was initialised True and never assigned.)
        if tag_filter and cat_filter and name_filter and render_filter:
            return True
        return False
