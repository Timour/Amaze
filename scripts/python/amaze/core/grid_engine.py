"""The grid engine: what every grid model's cells show, and their order. ▸p/grid-engine"""

from __future__ import annotations

import collections
import contextlib
import functools
import os

from PySide6 import QtCore, QtGui

from amaze.core import debug, grid_columns, thumbnails, tile_icons

DISPLAY = QtCore.Qt.ItemDataRole.DisplayRole
DECORATION = QtCore.Qt.ItemDataRole.DecorationRole
PAINTED = "amazetile"    #: image://amazetile/<model>/<row>/<stamp>: a picture painted when a view shows it
NAME = grid_columns.KEYS.index("name")
ASCENDING = QtCore.Qt.SortOrder.AscendingOrder
DESCENDING = QtCore.Qt.SortOrder.DescendingOrder


@contextlib.contextmanager
def relayout(*models):
    """Wrap a wholesale change to models' contents; never a structural insert or removal (segfault)."""
    live = [model for model in models if model is not None]
    for model in live:
        model.layoutAboutToBeChanged.emit()
    try:
        yield              # layoutChanged is emitted even when the body raises
    finally:
        for model in reversed(live):   # reverse order: the last model given layoutAboutToBeChanged gets layoutChanged first
            model.layoutChanged.emit()


def role_name(attr: str) -> str:
    """The name a view reads a role by: `TileSubtitleRole` is `tileSubtitle`."""
    return attr[0].lower() + attr[1:-len("Role")]


class Picture(collections.namedtuple("Picture", "files paint stamp art blank_while_loading",
                                     defaults=((), None, None, "", True))):
    """What a tile shows: the first of `files` (path, key, crop) that reads, `paint()`, or `art`."""

    __slots__ = ()


def custom_picture(preferences, spec) -> Picture:
    """A tile's custom icon: composed when shown, for every section."""
    return Picture(paint=functools.partial(tile_icons.compose_for, preferences, spec, False),
                   stamp=tile_icons.custom_stamp(preferences, spec))


def picture_file(path: str, key) -> str:
    """A picture file's url; its query counts the engine's replacements of `key`, so a rewrite reloads."""
    url = QtCore.QUrl.fromLocalFile(path)
    url.setQuery(str(thumbnails.engine.generation(key)))
    return url.toString()


def sort_key(value) -> tuple:
    """A cell as the sort compares it: text case-folded, numbers as numbers, empty last."""
    if value is None:
        return (2, 0, "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, value, "")
    return (1, 0, str(value).casefold())


class GridEngine:
    """Mixed in FIRST over `QAbstractTableModel` by every grid model. ▸p/grid-engine"""

    COLUMN_ROLES: dict = {}    #: {column key: role attribute name or Qt role int} ▸p/list-columns

    COLOUR_COLUMNS = {"category": "CategoryColorRole"}    #: {column key: its text colour role}

    TICK_COLUMNS = ("favorite", "open", "comments")    #: painted as a tick by `TickCellDelegate`

    GRID_ROWS: tuple = ()    #: names of the lists kept one entry per row; a sort moves them all

    TILE_FIELDS: tuple = ()    #: the record fields the tile dialog edits here, from name, tags and category

    TileSubtitleRole = QtCore.Qt.ItemDataRole.UserRole + 14    #: the tile's second line; 269 is Category
    PictureRole = QtCore.Qt.ItemDataRole.UserRole + 15    #: `picture_for_view`

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sort_column = NAME
        self._sort_order = ASCENDING
        self._resort_due = False
        for signal in (self.rowsInserted, self.rowsMoved, self.modelReset):
            signal.connect(self._schedule_resort)
        self.dataChanged.connect(self._rows_changed)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        return 0 if parent.isValid() else len(grid_columns.COLUMNS)    # a table row has no children

    def headerData(self, section, orientation, role=None):
        if role is None:
            role = DISPLAY
        if not (orientation == QtCore.Qt.Orientation.Horizontal
                and 0 <= section < len(grid_columns.LABELS)):
            return None
        if role == DISPLAY:
            return grid_columns.LABELS[section]
        return None

    def roleNames(self) -> dict:
        """Qt's role names, a column's text colour, one per `<Name>Role`; the decoded picture has none."""
        names = {role: name for role, name in super().roleNames().items() if role != DECORATION}
        names[int(QtCore.Qt.ItemDataRole.ForegroundRole)] = QtCore.QByteArray(b"foreground")
        for attr in dir(type(self)):
            if attr.endswith("Role") and len(attr) > len("Role"):
                names[int(getattr(type(self), attr))] = QtCore.QByteArray(role_name(attr).encode())
        return names

    def tile_picture(self, row: int, face: str = "") -> Picture:
        """The one decision of what `row`'s tile shows on `face`, by default its own; views only read it."""
        return Picture()

    def paint_tile(self, row: int):
        """The picture `tile_picture` paints for `row`, made now and kept nowhere; None for none."""
        picture = self.tile_picture(row)
        return picture.paint() if picture.paint is not None else None

    def shown_picture(self, row: int, face: str = "") -> tuple:
        """(image, crop) of `tile_picture`, read through the thumbnail engine."""
        picture = self.tile_picture(row, face)
        for path, key, crop in picture.files:
            image = thumbnails.engine.request_file(key, path)
            if image is not None:
                return image, crop
            if picture.blank_while_loading and not thumbnails.engine.is_missing(key):
                return None, crop    # still being read: the tile repaints when it is loaded
        if picture.paint is not None:
            image = thumbnails.engine.peek(picture.stamp)
            if image is None:
                image = picture.paint()
                if image is not None:
                    thumbnails.engine.deposit(picture.stamp, image)
            return image, False
        return (tile_icons.generic_image(picture.art) if picture.art else None), False

    def picture_for_view(self, row: int) -> dict:
        """`tile_picture` as a url a view loads itself, a file read in the background or a painted one."""
        picture = self.tile_picture(row)
        for path, key, crop in picture.files:
            if path and os.path.isfile(path):
                return {"url": picture_file(path, key), "art": "", "crop": bool(crop)}
        if picture.paint is not None:
            url = "image://%s/%x/%d/%x" % (PAINTED, id(self), row, hash(picture.stamp) & 0xffffffff)
            return {"url": url, "art": "", "crop": False}
        return {"url": "", "art": picture.art, "crop": False}

    def _column_role(self, key):
        """The role this model reads for a column, or None."""
        named = self.COLUMN_ROLES.get(key)
        if named is None:
            return None
        if isinstance(named, int):
            return named
        return getattr(self, named, None)

    def last_column(self) -> int:
        """The rightmost column, for a `dataChanged` range. ▸p/list-columns"""
        return max(self.columnCount() - 1, 0)

    def row_changed(self, row: int, roles=None) -> None:
        """Repaint one row, ACROSS EVERY COLUMN."""
        if 0 <= row < self.rowCount():
            self._repaint_rows(row, row, roles)

    def user_changed(self) -> None:
        """Another user is current: every row's star read again, across every column."""
        role = getattr(self, "FavoriteRole", None)
        if role is not None and self.rowCount():
            self._repaint_rows(0, self.rowCount() - 1, [role])

    def _repaint_rows(self, first: int, last: int, roles) -> None:
        top = self.index(first, 0)
        bottom = self.index(last, self.last_column())
        if roles is not None and DECORATION in roles:
            roles = list(roles) + [self.PictureRole]    # the same picture, for a view that loads it itself
        if roles is not None and DISPLAY not in roles and any(
                self._column_role(key) in roles for key in grid_columns.KEYS[NAME + 1:]):
            roles = list(roles) + [DISPLAY]    # a later column's text is that role, for a view of cells
        if roles is None:
            self.dataChanged.emit(top, bottom)
        else:
            self.dataChanged.emit(top, bottom, roles)

    def data(self, index, role=DISPLAY):
        """The only data(): column 0 returns `row_data`, a later column `cell_data`."""
        row = index.row()
        if not 0 <= row < self.rowCount():    # row -1: invalid; an old index can be past the end
            return None
        column = index.column()
        if column <= 0:
            if role == DECORATION:
                return self.shown_picture(row)[0]
            return self.picture_for_view(row) if role == self.PictureRole else self.row_data(row, role)
        return self.cell_data(row, column, role)

    def row_data(self, row: int, role):
        """What `row` holds for `role`; the only method a grid model writes. `row` is in range."""
        return None

    def cell_data(self, row: int, column: int, role):
        """A later column: text, text colour and the row's tooltip, all read from `row_data`."""
        if not 0 < column < len(grid_columns.KEYS):
            return None
        key = grid_columns.KEYS[column]
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            named = self.COLOUR_COLUMNS.get(key)
            ink = getattr(self, named, None) if named else None
            value = self.row_data(row, ink) if ink is not None else None
            colour = QtGui.QColor(str(value)) if value else None
            return colour if colour is not None and colour.isValid() else None
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return self.row_data(row, role)    # list mode hides column 0, so every cell returns the row's tooltip
        if role != DISPLAY:
            return None    # decoration and the rest come from column 0 only ▸p/list-columns
        mapped = self._column_role(key)
        if mapped is None:
            return None    # this model has no such column - not an error
        value = self.row_data(row, mapped)
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        return value

    def sort_column(self) -> int:
        """The column the rows are sorted by - Name, never the hidden column 0."""
        return self._sort_column

    def sort_order(self):
        return self._sort_order

    def sort(self, column: int, order=ASCENDING) -> None:
        """Sort the rows themselves; the header reaches here through the grid proxy."""
        self._sort_column = NAME if column <= 0 else column    # column 0 shows the name
        self._sort_order = order
        self.resort()

    def _sort_role(self):
        return self._column_role(grid_columns.KEYS[self._sort_column])

    def _sorted_rows(self) -> list:
        """The current rows as old row numbers, in sort order: one key each, stable both ways."""
        keys = [sort_key(self.cell_data(row, self._sort_column, DISPLAY))
                for row in range(self.rowCount())]
        return sorted(range(len(keys)), key=keys.__getitem__,
                      reverse=self._sort_order == DESCENDING)

    def _in_step(self) -> bool:
        """Every row list holds one entry per row; a list of another length would mix up rows."""
        count = self.rowCount()
        for name in self.GRID_ROWS:
            held = len(getattr(self, name))
            if held != count:
                debug.event("grid", "rows not sorted - a row list is out "
                            "of step", model=type(self).__name__,
                            rows=count, list=name, held=held)
                return False
        return True

    def _take_order(self, order: list) -> None:
        for name in self.GRID_ROWS:
            rows = getattr(self, name)
            rows[:] = [rows[old] for old in order]    # in place, so other holders see it

    def order_rows(self) -> dict | None:
        """Sort with NO signal, for a model building its rows; {old row: new row} or None."""
        moved = None
        if self._in_step():
            order = self._sorted_rows()
            if order != list(range(len(order))):
                self._take_order(order)
                moved = {old: new for new, old in enumerate(order)}
        self.rows_reordered()
        return moved

    def resort(self) -> dict | None:
        """Sort NOW in one layout change, persistent indexes moved; {old: new row} or None."""
        self._resort_due = False
        if not self._in_step():
            return None
        order = self._sorted_rows()
        if order == list(range(len(order))):
            return None
        moved = {old: new for new, old in enumerate(order)}
        self.layoutAboutToBeChanged.emit()    # PySide takes no hint here; never around an insert ▸r/node-graph
        held = self.persistentIndexList()
        self._take_order(order)
        self.rows_reordered()
        self.changePersistentIndexList(
            held, [self.index(moved.get(index.row(), index.row()),
                              index.column()) for index in held])
        self.layoutChanged.emit()
        return moved

    def rows_reordered(self) -> None:
        """Rebuild what this model indexes BY ROW after the `GRID_ROWS` lists are reordered."""

    def _schedule_resort(self, *_args) -> None:
        """Sort on the next turn, ONCE however many rows came. No timer of its own. ▸r/grid-sort-cost"""
        if self._resort_due:
            return
        self._resort_due = True
        QtCore.QTimer.singleShot(0, self._resort_if_due)    # keeps the model alive until it runs

    def _resort_if_due(self) -> None:
        if self._resort_due:
            self.resort()

    def _rows_changed(self, _top, _bottom, roles=()) -> None:
        if not roles or self._sort_role() in roles:    # a thumbnail update changes no sort column
            self._schedule_resort()
