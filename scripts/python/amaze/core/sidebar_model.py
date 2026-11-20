"""The model every sidebar list is: All, the top rows, the rows under a row. ▸r/sidebar-engine"""

from PySide6 import QtCore

_ROOT = QtCore.QModelIndex()


class SidebarModel(QtCore.QAbstractItemModel):
    """All on row 0, then the top rows, each with the rows under it; a row's id is kept by its key."""

    unfolds = False    # True where rows may hold rows under them; the view then draws arrows ▸r/tree-views

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._nodes: dict = {0: (None, None)}    # row id -> (parent row id, key); 0 is All
        self._node_ids: dict = {}    # (parent row id, key) -> row id
        self._by_key: dict = {}    # key -> the ids of every row showing it
        self._kids: dict = {}    # row id -> its child keys in order, once requested
        self._next_id = 0

    def top_keys(self) -> list:
        """The keys of the rows under All, in view order."""
        return []

    def top_parent_id(self, row: int):
        """The parent id a top row's id is kept under: None, or a negative number of the subclass's."""
        return None

    def child_keys(self, key) -> list:
        """The keys of the rows under the row keyed `key`, asked once per row id."""
        return []

    def key_above(self, key) -> str:
        """The key of the row that a row keyed `key` is under; "" for a top row."""
        return ""

    def _key_gone(self, parent_id, key) -> None:
        """Called once no row shows `key`; `parent_id` was the last such row's parent id."""

    def movable(self, index) -> bool:
        """Whether a row may be dragged to reorder; no row may here."""
        return False

    def move_row(self, index, to_row: int) -> bool:
        return False

    def order_snapshot(self):
        return None

    def restore_order(self, snapshot) -> None:
        pass

    def commit_order(self) -> None:
        pass

    @staticmethod
    def _is_top(parent_id) -> bool:
        return parent_id is None or parent_id < 0

    def _id(self, parent_id, key) -> int:
        """The row id of `key` shown under the row `parent_id`, or a top row's under its parent id."""
        pair = (parent_id, key)
        row_id = self._node_ids.get(pair)
        if row_id is None:
            self._next_id += 1
            row_id = self._node_ids[pair] = self._next_id
            self._nodes[row_id] = pair
            self._by_key.setdefault(key, set()).add(row_id)
        return row_id

    def _rekey_top_row(self, parent_id, old, new) -> None:
        """Give the top row keyed `old` the key `new` and keep its row id, so its index stays valid."""
        row_id = self._node_ids.pop((parent_id, old), None) if old != new else None
        if row_id is None:
            return
        self._node_ids[(parent_id, new)] = row_id
        self._nodes[row_id] = (parent_id, new)
        showing = self._by_key.get(old)
        if showing is not None:
            showing.discard(row_id)
            if not showing:
                del self._by_key[old]
        self._by_key.setdefault(new, set()).add(row_id)

    def _children(self, row_id) -> list:
        """A row's child keys; the first call takes them from `child_keys`."""
        kids = self._kids.get(row_id)
        if kids is None:
            kids = self._kids[row_id] = list(self.child_keys(self._nodes[row_id][1]))
        return kids

    def _index_for(self, row_id) -> QtCore.QModelIndex:
        """The index of a row id at its current row, invalid once no row shows it."""
        node = self._nodes.get(row_id)
        if node is None:
            return QtCore.QModelIndex()
        parent_id, key = node
        if key is None:
            return self.createIndex(0, 0, 0)
        if self._is_top(parent_id):
            for row, top in enumerate(self.top_keys(), 1):
                if top == key and self.top_parent_id(row) == parent_id:
                    return self.createIndex(row, 0, row_id)
            return QtCore.QModelIndex()
        siblings = self._kids.get(parent_id) or []
        if key not in siblings:
            return QtCore.QModelIndex()
        return self.createIndex(siblings.index(key), 0, row_id)

    def _merge(self, row_id, wanted: list) -> None:
        """Update one row's children to match `wanted`: removed rows go, new rows are inserted."""
        kids = self._kids.get(row_id)
        if kids is None or kids == wanted:
            return    # never requested: its first request reads the new list
        parent = self._index_for(row_id)
        if not parent.isValid():
            return
        keep = set(wanted)
        last = len(kids)    # adjacent rows go, and come, as ONE signal: each costs every view a pass
        while last > 0:
            first = last
            while first > 0 and kids[first - 1] not in keep:
                first -= 1
            if first == last:
                last -= 1
                continue
            self.beginRemoveRows(parent, first, last - 1)
            for gone in kids[first:last]:
                self._forget_row(self._node_ids.get((row_id, gone)))
            del kids[first:last]
            self.endRemoveRows()
            last = first
        row = 0
        while row < len(wanted):
            if row < len(kids) and kids[row] == wanted[row]:
                row += 1
                continue
            following = kids[row] if row < len(kids) else None    # the next row already present
            end = row + 1
            while end < len(wanted) and wanted[end] != following:
                end += 1
            self.beginInsertRows(parent, row, end - 1)
            kids[row:row] = wanted[row:end]
            self.endInsertRows()
            row = end

    def _forget_row(self, row_id) -> None:
        """Drop a row id and everything below it; no signals - its rows are already gone."""
        if row_id is None or row_id not in self._nodes:
            return
        for child in self._kids.pop(row_id, None) or ():
            self._forget_row(self._node_ids.get((row_id, child)))
        node = self._nodes.pop(row_id)
        self._node_ids.pop(node, None)
        showing = self._by_key.get(node[1])
        if showing is not None:
            showing.discard(row_id)
            if not showing:
                del self._by_key[node[1]]
                self._key_gone(*node)

    def _forget_rows(self) -> None:
        """Drop every row id but All's, inside a reset."""
        self._nodes = {0: (None, None)}
        self._node_ids = {}
        self._by_key = {}
        self._kids = {}

    def index_of(self, key) -> QtCore.QModelIndex:
        """The row keyed `key`: All for "", the first top row, a row under the row `key_above` gives."""
        if not key:
            return self.createIndex(0, 0, 0)
        tops = self.top_keys()
        if key in tops:
            row = tops.index(key) + 1
            return self.createIndex(row, 0, self._id(self.top_parent_id(row), key))
        up = self.key_above(key)
        parent = self.index_of(up) if up else QtCore.QModelIndex()
        if not parent.isValid():
            return QtCore.QModelIndex()
        kids = self._children(parent.internalId())
        if key not in kids:
            return QtCore.QModelIndex()
        return self.createIndex(kids.index(key), 0, self._id(parent.internalId(), key))

    def index(self, row: int, column: int = 0, parent=_ROOT) -> QtCore.QModelIndex:
        if column != 0 or row < 0:
            return QtCore.QModelIndex()
        if parent is None or not parent.isValid():
            if row == 0:
                return self.createIndex(0, 0, 0)
            tops = self.top_keys()
            if row - 1 < len(tops):
                return self.createIndex(row, 0, self._id(self.top_parent_id(row), tops[row - 1]))
            return QtCore.QModelIndex()
        if parent.internalId() not in self._nodes:
            return QtCore.QModelIndex()
        kids = self._children(parent.internalId())
        if row < len(kids):
            return self.createIndex(row, 0, self._id(parent.internalId(), kids[row]))
        return QtCore.QModelIndex()

    def parent(self, index=None):
        if index is None:
            return super().parent()    # the QObject parent this overload would hide
        if not index.isValid():
            return QtCore.QModelIndex()
        node = self._nodes.get(index.internalId())
        if node is None or self._is_top(node[0]):
            return QtCore.QModelIndex()
        return self._index_for(node[0])

    def rowCount(self, parent=None) -> int:
        if parent is None or not parent.isValid():
            return len(self.top_keys()) + 1
        node = self._nodes.get(parent.internalId())
        if node is None or node[1] is None:
            return 0
        return len(self._children(parent.internalId()))

    def columnCount(self, parent=None) -> int:
        return 1

    def hasChildren(self, parent=None) -> bool:
        return self.rowCount(parent) > 0

    def flags(self, index) -> QtCore.Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid() and not self.unfolds:
            flags |= QtCore.Qt.ItemFlag.ItemNeverHasChildren    # as Qt's list model marks its rows
        return flags

    def data(self, index, role: int = 0):
        """SIDEBAR_KEY_ROLE from the row's key, "" on All; a subclass answers every other role."""
        if role != category.SIDEBAR_KEY_ROLE or not index.isValid():
            return None
        node = self._nodes.get(index.internalId())
        return None if node is None else node[1] or ""


from amaze.core import category  # noqa: E402 - below the class: category.py subclasses it as this loads

