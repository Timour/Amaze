"""The Grid's COLUMNS - the one list, and the model half of it.

List mode is a table: thumbnail, name, type, and up to seven more.
Until 2026-08-04 it was a table COSTUME - a `QListView` in ListMode
whose delegate painted ten regions inside one item's rect, with a
hand-painted header strip above it. That cost 681 lines and gave no
click-sorting and no drag-resizing, which is recorded in ROADMAP as
the reason for this migration.

**Why the list lives in `core/` and not beside the header widget.**
The models have to answer per column now, and `core/` cannot import
`helpers/ui_helpers` - `ui_helpers` imports `core.debug`, so it would
cycle. The column order is DATA; only its rendering is a widget's
business. The header reads it from here, and so does every model.

**COLUMN 0 IS THE ROW.** It answers exactly what the model answered
before any of this, for every role - the thumbnail, the display name,
every UserRole the grid delegate reads. Columns 1..N are additive, so
`QListView` (which shows `modelColumn()` 0 and nothing else) cannot
tell the difference: **grid mode is untouched by construction**, which
is the property that makes this migration safe to do in steps.
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui

#: THE COLUMN ORDER, once. (key, header label). The key is what a
#: model maps to a role and what a width is filed under; the label is
#: what the header paints. An empty label is a column with no heading -
#: the thumbnail.
COLUMNS = (
    ("thumb", ""),
    ("name", "Name"),
    ("type", "Type"),
    ("category", "Category"),
    ("favorite", "Favorite"),
    ("version", "Version"),
    ("open", "Open"),
    ("comments", "Comments"),
    ("tags", "Tags"),
    ("license", "License"),
)

KEYS = tuple(key for key, _label in COLUMNS)
LABELS = tuple(label for _key, label in COLUMNS)

class GridColumnsMixin:
    """Makes a flat model answer as a TABLE.

    A model mixes this in and declares `COLUMN_ROLES` - {column key:
    role} for the columns it can fill. A role is named by its ATTRIBUTE
    NAME, because every model sets its roles in `__init__` (they are
    per-instance numbers, not class constants), or given as a literal
    int for Qt's own.

    Everything else follows:

    * `columnCount` is the shared list's length for every model, so the
      header and the rows cannot disagree about how many there are;
    * column 0 delegates to the model's own `data()` untouched;
    * a column with no role in this model answers None - which is how
      Color has no Tags and File has no Version, without either of them
      knowing the other exists;
    * `headerData` comes from the shared list.

    **The base must be `QAbstractTableModel`, not `QAbstractListModel`.**
    Measured 2026-08-04: a list model's `index(row, col)` returns an
    INVALID index for any col > 0 even when `columnCount` says ten -
    Qt hard-codes column 0 there - and PySide6 makes `columnCount`
    itself a private, uncallable method on that base. A list model is
    not a table with the columns switched off; it is a different model.

    The mixin goes FIRST in the bases so its `data`, `columnCount` and
    `headerData` win.
    """

    #: {column key: role attribute name, or a literal Qt role int}.
    #: A model fills in only what it has.
    COLUMN_ROLES: dict = {}

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        # A valid parent means a child of a row, and a table has none.
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=None):
        if role is None:
            role = QtCore.Qt.ItemDataRole.DisplayRole
        if not (orientation == QtCore.Qt.Orientation.Horizontal
                and 0 <= section < len(LABELS)):
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return LABELS[section]
        return None

    def _column_role(self, key):
        """The role this model answers a column with, or None."""
        named = self.COLUMN_ROLES.get(key)
        if named is None:
            return None
        if isinstance(named, int):
            return named
        return getattr(self, named, None)

    def last_column(self) -> int:
        """The rightmost column, for a `dataChanged` range.

        A row-repaint used to be `index(row, 0)` to `index(row, 0)`,
        which was the whole row when the row WAS one column. With ten,
        that range invalidates the thumbnail and nothing else - so
        every later cell keeps its old text until something forces a
        repaint. Found while migrating: the emit sites read correctly
        and were quietly half-right.
        """
        return max(self.columnCount() - 1, 0)

    def row_changed(self, row: int, roles=None) -> None:
        """Repaint one row, ACROSS EVERY COLUMN."""
        if not 0 <= row < self.rowCount():
            return
        top = self.index(row, 0)
        bottom = self.index(row, self.last_column())
        if roles is None:
            self.dataChanged.emit(top, bottom)
        else:
            self.dataChanged.emit(top, bottom, roles)

    #: NO FONT ROLE (2026-08-04). A bold name column was asked for
    #: earlier the same day and is gone again: `FontRole` is used by Qt
    #: AS-IS, so returning a bare `QFont()` with bold set handed the
    #: cell Qt's DEFAULT family and size instead of the panel's - a
    #: different typeface, not the panel's font in bold. Same shape as
    #: the absolute point-size floor in research.md. The rows wear the
    #: view's font now, like every other list in the host.

    #: {column key: the role carrying that column's own INK}. Category
    #: is the one column with a colour of its own - the colour the user
    #: gave that category, and the same one the grid paints under its
    #: tiles, so the two views agree about what a category looks like.
    COLOUR_COLUMNS = {"category": "CategoryColorRole"}

    #: Columns drawn as a TICK, not typed as text
    #: (`TickCellDelegate` paints them). `panel._bind_table_cell_
    #: delegates` walks this list; which role and which colour each one
    #: draws stays with the delegate that draws it.
    #:
    #: They ALIGN LIKE EVERY OTHER COLUMN. They were centred for one
    #: build - a mark has no reading order to line up with - and the
    #: centring was reverted after seeing it live (2026-08-04). A
    #: `QHeaderView` label starts at the cell's left edge, so a centred
    #: mark reads as a different table from the eight columns beside
    #: it.
    TICK_COLUMNS = ("favorite", "open", "comments")

    def column_data(self, index, role):
        """What a LATER column shows. Returns None for column 0, for a
        column this model cannot fill, and for any role but Display.

        NOT called `data`. A mixin's `data` is a BASE method, and every
        one of these models defines its own - so an inherited `data`
        would never run at all. Measured the hard way: Color answered
        the Tags column with its display name because `GradientLibrary.
        data` won the MRO. Each model calls this from the top of its
        own `data` instead, in two explicit lines, which is also the
        version a reader can follow.
        """
        column = index.column()
        if column <= 0 or column >= len(KEYS):
            return None
        key = KEYS[column]
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            named = self.COLOUR_COLUMNS.get(key)
            if named is None:
                return None
            value = self.data(index.siblingAtColumn(0),
                              getattr(self, named, None)) if named else None
            colour = QtGui.QColor(str(value)) if value else None
            return colour if colour is not None and colour.isValid() else None
        if role != QtCore.Qt.ItemDataRole.DisplayRole:
            # A cell shows TEXT. Decoration, tooltips and the rest stay
            # column 0's business, where the delegate already reads
            # them - answering them here would put the thumbnail in
            # every column.
            return None
        mapped = self._column_role(key)
        if mapped is None:
            # This model has no such column. Not an error: Color has no
            # Tags, File has no Version.
            return None
        # Ask for the ROW's answer: the roles live on column 0, which
        # is where every existing reader put them.
        value = self.data(index.siblingAtColumn(0), mapped)
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        return value
