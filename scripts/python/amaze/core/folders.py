"""The ONE folder-pointer sidebar model behind every Folder-archetype section - a flat list of registered paths plus a synthetic All at row 0. POINTERS, not an index: registering a folder scans or copies nothing. ▸p/folder-sidebar
"""

from PySide6 import QtCore

import os

from amaze.core import category
from amaze.helpers import hostos



def walk_following_links(root: str):
    """`os.walk` that follows symlinked DIRECTORIES, each physical one once - same `(dirpath, dirnames, filenames)` triples, so callers may still sort `dirnames` in place. Costs a realpath per directory and per child: never call it from a paint path. ▸r/platform-files"""
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        try:
            real = os.path.realpath(dirpath)
        except OSError:
            continue
        if real in seen:
            dirnames[:] = []          # already covered by another path
            continue
        seen.add(real)
        dirnames[:] = [
            name for name in dirnames
            if os.path.realpath(os.path.join(dirpath, name)) not in seen
        ]
        yield dirpath, dirnames, filenames


class FolderListModel(QtCore.QAbstractListModel):
    """Generic registered-folders list - a subclass sets the `*_attr`/`*_method` names to its section's preference surface and implements `matches(filename)`. ▸p/folder-sidebar"""

    PathRole = QtCore.Qt.ItemDataRole.UserRole
    ALL_LABEL = "All"
    COUNT_ROLE = category.SIDEBAR_COUNT_ROLE    # the ONE definition, imported so the sidebar models cannot drift apart

    folders_attr = ""           # prefs attribute holding the folder list, e.g. `file_folders`
    favorites_attr = ""         # prefs attribute holding full-path favourites for this section
    last_folder_attr = ""       # prefs attribute remembering the last-selected folder
    add_folder_method = ""      # prefs METHOD names that add/remove and persist ▸p/folder-sidebar
    remove_folder_method = ""
    relocate_folder_method = ""    # re-points one folder IN ITS OWN ROW; named, never an index assignment ▸p/folder-sidebar
    move_folder_method = ""        # the sidebar reorder; empty = this section's folders do not reorder

    def __init__(self, preferences, parent: QtCore.QObject | None = None) -> None:
        super().__init__()
        self.preferences = preferences
        self._counts: dict = {}    # folder file-counts, cached so painting never touches the disk ▸p/folder-sidebar


    def matches_in(self, path: str, filename: str) -> bool:
        """Folder-aware match - the base asks the flat rule; File overrides it for the per-location Show All Files setting."""
        return self.matches(filename)

    def matches(self, filename: str) -> bool:
        """Does this filename belong to the section (by extension)?"""
        raise NotImplementedError


    def _folders(self) -> list:
        return getattr(self.preferences, self.folders_attr)

    def _favorites(self) -> list:
        return getattr(self.preferences, self.favorites_attr)


    def switch_model_data(self):
        """Re-point at whichever library is now live - the folders are read THROUGH to `prefs`, so the rows are already right and what was missing is the reset that repaints them. ▸p/folders-follow-the-library"""
        self.beginResetModel()
        try:
            self._counts = {}    # counts are per-folder and the folders have just changed
        finally:
            self.endResetModel()

    def refresh_counts(self) -> None:
        self._counts = {}

    def includes_subfolders(self, path: str) -> bool:
        """Whether THIS registered folder scans recursively - the base answers no, and recursion is the location record's. ▸p/folder-sidebar"""
        return False

    def display_name(self, path: str) -> str:
        """The sidebar label for a registered folder - the basename here, custom-name-or-path in FileFolders."""
        return os.path.basename(path.rstrip("/\\")) or path

    def _folder_count(self, path: str) -> int:
        count = self._counts.get(path)
        if count is not None:
            return count
        count = 0
        try:
            if self.includes_subfolders(path):
                for _dirpath, dirnames, filenames in walk_following_links(path):
                    # hidden directories pruned as hidden files are skipped, or the count disagrees with the grid ▸p/folder-sidebar
                    dirnames[:] = [d for d in dirnames
                                   if not d.startswith(".")]
                    dirnames.sort()
                    count += sum(1 for name in filenames
                                 if self.matches_in(path, name))
            else:
                count = sum(    # FILES only, matching the grid's flat scan ▸p/folder-sidebar
                    1 for name in os.listdir(path)
                    if self.matches_in(path, name)
                    and os.path.isfile(os.path.join(path, name))
                )
        except OSError:
            count = 0
        self._counts[path] = count
        return count

    def _on_folder_relocated(self, old_path: str, new_path: str) -> None:
        """Hook: per-location state follows a Locate Folder. Base: none."""


    def rowCount(self, parent=None) -> int:
        return len(self._folders()) + 1

    def data(self, index, role: int = 0):
        if not index.isValid():
            return None
        row = index.row()
        if row == 0:
            if role == QtCore.Qt.ItemDataRole.DisplayRole:    # the All row has no real path: PathRole and all but the count stay None ▸p/folder-sidebar
                return self.ALL_LABEL
            if role == self.COUNT_ROLE:
                return sum(count for count in    # ONLY WHAT IS ALREADY COUNTED - summing on demand recounts every location inside the paint path ▸p/folder-sidebar
                           (self._counts.get(p) for p in self._folders())
                           if count is not None)
            return None
        path = self._folders()[row - 1]
        if role == self.COUNT_ROLE:
            return self._folder_count(path)
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self.display_name(path)
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return path
        if role == self.PathRole:
            return path
        if role == category.SIDEBAR_COLOR_ROLE:
            return self.folder_color(path)    # the same role the asset sidebars answer, so ONE delegate paints it; "" draws nothing
        return None

    def row_of(self, path: str):
        """The sidebar row showing this registered folder, or None - the +1 for the synthetic All row lives HERE so no caller re-derives it. ▸p/folder-sidebar"""
        folders = self._folders()
        if path in folders:
            return folders.index(path) + 1
        return None

    def folder_color(self, path: str) -> str:
        """This location's colour, "" for none - reads the ONE record, never the whole colour table, because this runs per row per repaint. ▸p/folder-sidebar"""
        from amaze.core import locations
        return str(locations.record(self.preferences, path).get("color", ""))


    def add_folder(self, path: str) -> None:
        """Register a folder pointer. No-op if already registered."""
        if not path or path in self._folders():
            return
        row = len(self._folders()) + 1
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        getattr(self.preferences, self.add_folder_method)(path)
        self.endInsertRows()
        self.refresh_counts()

    def remove_folder(self, row: int) -> None:
        # row 0 is the synthetic All entry, not a real folder
        if row <= 0 or not row - 1 < len(self._folders()):
            return
        self.beginRemoveRows(QtCore.QModelIndex(), row, row)
        path = self._folders()[row - 1]
        getattr(self.preferences, self.remove_folder_method)(path)
        self.endRemoveRows()
        self.refresh_counts()

    def move_folder(self, from_row: int, to_row: int) -> bool:
        """Move one registered folder to another VIEW row - the sidebar's press-hold reorder, in memory, persisted on release. ▸p/folder-sidebar"""
        if not self.move_folder_method:
            return False
        folders = self._folders()
        count = len(folders)
        if not (1 <= from_row <= count and 1 <= to_row <= count):
            return False
        if from_row == to_row:
            return False
        path = folders[from_row - 1]
        destination = to_row if to_row < from_row else to_row + 1
        if not self.beginMoveRows(QtCore.QModelIndex(), from_row,
                                  from_row, QtCore.QModelIndex(),
                                  destination):
            return False
        try:
            moved = bool(getattr(self.preferences,
                                 self.move_folder_method)(path,
                                                          to_row - 1))
        finally:
            self.endMoveRows()
        if not moved:
            self.beginResetModel()    # the view moved and the truth did not: resync rather than leave them disagreeing ▸p/folder-sidebar
            self.endResetModel()
        return moved

    def restore_folder_order(self, paths) -> None:
        """Put a snapshot's order back - the reorder gesture's Esc, a whole-row-set statement wearing the reset pair. ▸p/folder-sidebar"""
        if not self.move_folder_method:
            return
        paths = [p for p in (paths or [])]
        if paths == list(self._folders()):
            return
        self.beginResetModel()
        try:
            mover = getattr(self.preferences, self.move_folder_method)
            for row, path in enumerate(paths):
                mover(path, row)
        finally:
            self.endResetModel()

    def relocate_folder(self, row: int, new_path: str) -> int:
        """Re-point the registered folder at ROW to NEW_PATH, everything keyed under the old path following through the keyed-store engine's one pass - returns the favourites moved, or -1 for an invalid row or path. ▸p/folder-sidebar"""
        if row <= 0 or not row - 1 < len(self._folders()):
            return -1
        if not new_path or not os.path.isdir(new_path):
            return -1
        new_path = hostos.canonical_path_key(new_path)    # CANONICAL FIRST, then the trailing separator - the folder-POINTER shape ▸p/folder-sidebar
        if not new_path.endswith("/"):
            new_path += "/"
        old_path = self._folders()[row - 1]
        if new_path == old_path:
            return 0
        old_prefix = old_path if old_path.endswith("/") else old_path + "/"    # COUNTED here, REWRITTEN by the engine ▸p/folder-sidebar
        rewritten = sum(1 for fav in self._favorites()
                        if fav.startswith(old_prefix))
        getattr(self.preferences, self.relocate_folder_method)(    # THROUGH A NAMED CALL, never an index assignment - that fails SILENTLY ▸p/folder-sidebar
            old_path, new_path)
        if getattr(self.preferences, self.last_folder_attr) == old_path:
            setattr(self.preferences, self.last_folder_attr, new_path)
        self._on_folder_relocated(old_path, new_path)    # everything else keyed on the old path rides along
        self.preferences.save()
        index = self.index(row)
        self.dataChanged.emit(index, index)
        self.refresh_counts()
        return rewritten
