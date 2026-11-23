"""Locations under All, each unfolding to its subfolders, read on a worker. ▸p/folder-sidebar"""

import functools
import os

from PySide6 import QtCore

from amaze.core import category, debug, locations, sidebar_model, workers
from amaze.helpers import hostos


def name_order(names) -> list:
    """Folder names as the sidebar lists them: by letter, a case-only tie in one fixed order."""
    return sorted(names, key=lambda name: (name.lower(), name))


def scan_folder(path: str, matches, stopped=lambda: False):
    """(files the sidebar counts, visible subfolder names, whether it opened), None once `stopped()`."""
    count, subfolders = 0, []
    try:
        with os.scandir(path) as entries:    # one read: the files to count, the folders to unfold
            for entry in entries:
                if stopped():
                    return None
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    subfolders.append(entry.name)
                elif matches(entry.name) and entry.is_file():
                    count += 1
    except OSError:
        return 0, [], False
    return count, name_order(subfolders), True


class _CountWorker(QtCore.QThread):
    """Reads ONE folder off the GUI thread."""

    counted = QtCore.Signal(object, object, object)    # (path, token, (count, subfolders, opened))

    def __init__(self, path, token, matches) -> None:
        super().__init__()
        self.path, self.token = path, token
        self._matches = matches
        self._canceled = False    # the stop flag workers.stop() sets, the name every engine's worker uses

    def cancel(self) -> None:
        self._canceled = True

    def _stopped(self) -> bool:
        return self._canceled or self.isInterruptionRequested()

    def run(self) -> None:
        try:
            result = scan_folder(self.path, self._matches, self._stopped)
        except Exception as exc:                          # noqa: BLE001 - logged; the worker still ends
            debug.event("folders", "count failed", folder=self.path,
                        error=str(exc))
            return
        if result is not None:
            self.counted.emit(self.path, self.token, result)


class _CountEngine(QtCore.QObject):
    """Runs every folder count in the process; stops them on quit. ▸r/model-contracts"""

    def __init__(self) -> None:
        super().__init__()
        self._threads = []    # a running QThread must keep a reference until it ends ▸r/model-contracts

    def start(self, job, on_counted, ended) -> None:
        """One worker over one folder: `on_counted(path, token, result)`, then `ended(worker)`."""
        worker = _CountWorker(*job)
        worker.counted.connect(on_counted)
        worker.finished.connect(    # bound here, never sender(): ordering is per sender ▸r/model-contracts
            functools.partial(self._finished, worker, ended))
        self._threads.append(worker)
        worker.start()

    def _finished(self, worker, ended) -> None:
        self._threads = [t for t in self._threads
                         if t is not worker and not workers.gone(t)]
        ended(worker)

    def shutdown(self) -> None:
        """Stop every walk, THEN wait for each; safe twice and with nothing running."""
        workers.stop(self._threads, "folders")
        self._threads = []


ALREADY_A_LOCATION = -2    # `relocate_folder`'s return value for a folder that is a location already
_ROOT = QtCore.QModelIndex()
_SCENE = -1    # the fixed scene row's parent id: its node is never a registered location's at the same path


class FolderTreeModel(sidebar_model.SidebarModel):
    """Locations under a synthetic All, each with the subfolders its last read found."""

    PathRole = QtCore.Qt.ItemDataRole.UserRole    # a REGISTERED location's path; None on All and subfolders
    BrowseRole = QtCore.Qt.ItemDataRole.UserRole + 1    # the folder a row shows; None on All
    ALL_LABEL = "All"
    SCENE_LABEL = "$HIP"    # the fixed scene row's label, and the token saved as the last folder for it
    scene_folder_changed = QtCore.Signal(str, str)    # (old, new) once the scene row shows another folder
    scene_folder_left = QtCore.Signal(str)    # (old) once the scene row is gone: the scene has no file
    COUNT_ROLE = category.SIDEBAR_COUNT_ROLE    # the ONE definition, shared by every sidebar model
    ROW_ROLES = frozenset((int(QtCore.Qt.ItemDataRole.DisplayRole), int(QtCore.Qt.ItemDataRole.ToolTipRole),
                           int(PathRole), int(BrowseRole), COUNT_ROLE, category.SIDEBAR_COLOR_ROLE,
                           category.SIDEBAR_KEY_ROLE, category.SIDEBAR_UNREACHABLE_ROLE))    # every role a row answers
    unfolds = True    # its rows reserve space for an expand arrow ▸r/tree-views

    def flags(self, index):
        """Qt's own flags, plus what a location needs to be dragged to another place."""
        return self.move_flags(index, QtCore.QAbstractItemModel.flags(self, index))

    folders_attr = ""           # prefs attribute holding the folder list, e.g. `file_folders`
    favorites_attr = ""         # prefs attribute holding full-path favourites for this section
    last_folder_attr = ""       # prefs attribute remembering the last-selected folder
    add_folder_method = ""      # prefs METHOD names that add/remove and persist ▸p/folder-sidebar
    remove_folder_method = ""
    relocate_folder_method = ""    # changes one folder's path IN ITS OWN ROW ▸p/folder-sidebar
    move_folder_method = ""        # the sidebar reorder; empty = this section's folders do not reorder
    color_folder_method = ""       # the Label colour; empty = this section's folders take none
    COUNT_WORKERS = 2    # parallel reads: a slow share blocks one; four slowed painting ▸r/count-workers
    SIGNAL_COUNTS_MS = 100    # reads finishing within this window repaint the sidebar once, not each
    _counts_asked = QtCore.Signal()    # queued: a request from ANY thread is handled on the GUI thread

    def __init__(self, preferences, parent: QtCore.QObject | None = None) -> None:
        super().__init__()
        self.preferences = preferences
        self._counts_asked.connect(self._dispatch_counts,    # a zero-timer started outside a Qt thread never fires
                                   QtCore.Qt.ConnectionType.QueuedConnection)
        self._counts: dict = {}    # path -> its last count; a paint reads only this ▸p/folder-sidebar
        self._counted: dict = {}    # path -> the token its count was walked under
        self._tokens: dict = {}    # path -> the token a current count has; a change increments it
        self._walking: dict = {}    # path -> its ONE walk's token, None while still queued
        self._queued: list = []
        self._live = 0    # this model's workers still running
        self._count_scheduled = False
        self._counts_not_signalled: set = set()    # counted, the views not notified yet
        self._signal_counts_pending = False
        self._rows: list = []
        self._rows_key = None    # the token `_rows` was read with; None forces a reread
        self._held = None    # the rows the views know, while a write runs; SET here ▸r/qobject-missing-attribute
        self._records: dict = {}    # path -> its location record, read against `_records_key`
        self._records_key = None
        self._listed: dict = {}    # folder path -> the subfolder names its last read found
        self._unreachable: set = set()    # the folders whose last read could not open them
        self._scene = ""    # the open scene's folder the fixed row shows; "" shows no such row


    def matches(self, filename: str) -> bool:
        """Whether the sidebar counts this file; it runs on the count's worker, so it reads no settings."""
        raise NotImplementedError


    def _folders(self) -> list:
        if self._held is not None:
            return self._held
        key = self._rows_token()
        if key != self._rows_key:
            self._rows = list(getattr(self.preferences, self.folders_attr))
            self._rows_key = key
        return self._rows

    def scene_folder(self) -> str:
        """The folder the fixed scene row shows, "" while there is none."""
        return self._scene

    def _fixed(self) -> list:
        return [self._scene] if self._scene else []

    def top_keys(self) -> list:
        """The top rows after All, in view order: the fixed row, then every registered location."""
        return self._fixed() + self._folders()

    def top_parent_id(self, row: int):
        return _SCENE if row < self._offset() else None    # the scene row's id is not its location's

    def child_keys(self, key) -> list:
        """A folder's subfolders as its last read found them."""
        return [self._join(key, name) for name in self._listed.get(key, ())]

    def key_above(self, key) -> str:
        return key.rsplit("/", 1)[0] if "/" in key else ""

    def _key_gone(self, parent_id, key) -> None:
        if parent_id is not None:    # a subfolder no row shows: its counts are dropped with it
            for table in (self._counts, self._counted, self._tokens, self._listed):
                table.pop(key, None)
            self._unreachable.discard(key)

    def _offset(self) -> int:
        """The view row the registered locations start at."""
        return 1 + len(self._fixed())

    def scene_row(self):
        """The fixed scene row's view row, None while no scene folder is set."""
        return 1 if self._scene else None

    def is_scene_row(self, index) -> bool:
        node = self._nodes.get(index.internalId()) if index is not None and index.isValid() else None
        return node is not None and node[0] == _SCENE

    def registered_at(self, row) -> str:
        """The registered location at a top view row; "" for All, the fixed row or no row."""
        folders = self._folders()
        at = row - self._offset()
        return folders[at] if 0 <= at < len(folders) else ""

    def set_scene_folder(self, path: str) -> bool:
        """Point the fixed row at the scene's folder; True when what it shows changed."""
        if path:
            path = hostos.canonical_path_key(path)    # CANONICAL FIRST, then the trailing slash
            if not path.endswith("/"):
                path += "/"
        old = self._scene
        if path == old:
            return False
        if not old:
            self.beginInsertRows(_ROOT, 1, 1)
            self._scene = path
            self.endInsertRows()
            return True
        if not path:
            self.beginRemoveRows(_ROOT, 1, 1)
            self._scene = ""
            self._forget_row(self._node_ids.get((_SCENE, old)))
            self.endRemoveRows()
            self._out_of_date((old,), keep=False)
            self.scene_folder_left.emit(old)
            return True
        self._replace_top_row_folder(1, _SCENE, old, path, lambda: setattr(self, "_scene", path))
        self.scene_folder_changed.emit(old, path)
        return True

    def _rows_token(self) -> tuple:
        """The inputs of the registered list: a location write, the local order, library, user."""
        preferences = self.preferences
        return (locations.generation(),
                tuple(getattr(preferences, "last_known_folders", ()) or ()),
                str(getattr(preferences, "dir", "")),
                str(getattr(preferences, "library_user", "")))

    def _write_and_signal(self, write) -> tuple:
        """Run one prefs write while views still get the old rows, then signal what it changed."""
        before = list(self._folders())
        self._held = before
        try:
            write()
            after = list(getattr(self.preferences, self.folders_attr))
            self._signal_row_changes(before, after)
        finally:
            self._held = None
        for path in set(before) - set(after):
            self._forget_row(self._node_ids.get((None, path)))    # its rows were removed with it
        self._out_of_date(set(before).symmetric_difference(after),    # the others' counts are still valid
                          keep=False)
        return before, after

    def _signal_row_changes(self, before: list, after: list) -> None:
        """One row added or removed as row signals, anything else as a reset, a refused write as none."""
        if after == before:
            return
        at = next((i for i, (old, new) in enumerate(zip(before, after))
                   if old != new), min(len(before), len(after)))
        row = at + self._offset()    # All and the fixed row sit above the locations
        if len(after) == len(before) + 1 \
                and after[:at] + after[at + 1:] == before:
            self.beginInsertRows(_ROOT, row, row)
            self._held = None
            self.endInsertRows()
        elif len(after) == len(before) - 1 \
                and before[:at] + before[at + 1:] == after:
            self.beginRemoveRows(_ROOT, row, row)
            self._held = None
            self.endRemoveRows()
        else:
            self.beginResetModel()
            self._held = None
            self._forget_rows()
            self.endResetModel()

    def _favorites(self) -> list:
        return getattr(self.preferences, self.favorites_attr)


    def switch_model_data(self):
        """Switch to the current library; the rows are read again. ▸p/folders-follow-the-library"""
        self.beginResetModel()
        try:
            self._out_of_date(self._known(), keep=False)    # another library's rules: no count is kept
            self._rows_key = None
            self._records_key = None
            self._forget_rows()
            self._listed = {}
            self._unreachable = set()
        finally:
            self.endResetModel()

    def user_changed(self) -> None:
        """Another user's registered locations: the rows are read again, as on a library switch."""
        self.switch_model_data()

    def refresh_counts(self) -> None:
        """Mark every count stale, each shown until a new one arrives; the rows are read again."""
        self._out_of_date(self._known())
        self._rows_key = None
        self._records_key = None
        self._ask_counts_again()

    def _ask_counts_again(self) -> None:
        """Every known count marked stale for the views: the top rows, then each parent as one range."""
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0), [self.COUNT_ROLE])
        for row_id, kids in list(self._kids.items()):
            parent = self._index_for(row_id) if kids else QtCore.QModelIndex()
            if parent.isValid():
                self.dataChanged.emit(self.index(0, 0, parent), self.index(len(kids) - 1, 0, parent),
                                      [self.COUNT_ROLE])

    def _known(self) -> set:
        return set(self._counts) | set(self._walking)

    def _out_of_date(self, paths, keep: bool = True) -> None:
        """Increment each folder's token, so a walk still running for it is discarded when it ends."""
        for path in paths:
            self._tokens[path] = self._tokens.get(path, 0) + 1
            if not keep:
                self._counts.pop(path, None)
                self._counted.pop(path, None)

    def _record(self, path: str) -> dict:
        """One location's record, kept until a location write or a read of another session's save."""
        key = self._rows_token()
        if key != self._records_key:
            self._records = {}
            self._records_key = key
        found = self._records.get(path)
        if found is None:
            found = self._records[path] = locations.record(self.preferences, path)
        return found

    def location_of(self, path: str) -> str:
        """The innermost registered location a folder is in, else the folder itself."""
        if not path:
            return path    # no folder, no location
        return locations.innermost(self._folders(), path) or path

    def top_of(self, path: str) -> str:
        """The innermost top row's folder a folder is in, the scene's included, else the folder itself."""
        if not path:
            return path
        return locations.innermost(self.top_keys(), path) or path

    def display_name(self, path: str) -> str:
        """A location's sidebar label: its folder name here; FileFolders adds names and paths."""
        return os.path.basename(path.rstrip("/\\")) or path

    def _shows(self, path: str) -> bool:
        """Whether some row still shows this folder: a top row, or a subfolder already read."""
        return path in set(self.top_keys()) or bool(self._by_key.get(path))

    def _folder_count(self, path: str):
        """The count known now, None before one arrives; a stale one is recounted off the GUI thread."""
        if self._counted.get(path) != self._tokens.get(path, 0):
            self._ask_count(path)
        return self._counts.get(path)

    def _ask_count(self, path: str) -> None:
        if path in self._walking:
            return    # ONE walk per folder; a stale one is requested again when it ends
        self._walking[path] = None
        self._queued.append(path)
        if not self._count_scheduled:
            self._count_scheduled = True
            self._counts_asked.emit()    # one dispatch for all requests of one paint

    def _dispatch_counts(self) -> None:
        """One queued folder per free worker."""
        self._count_scheduled = False
        if self._live >= self.COUNT_WORKERS or not self._queued:
            return    # a worker ending dispatches again
        while self._queued and self._live < self.COUNT_WORKERS:
            path = self._queued.pop(0)    # one each: a slow share then blocks only its own worker
            if not self._shows(path):
                self._walking.pop(path, None)    # gone before its walk began
                continue
            token = self._tokens.get(path, 0)
            self._walking[path] = token
            self._live += 1
            counter.start((path, token, self.matches), self._on_counted, self._walk_ended)

    def _on_counted(self, path, token, result) -> None:
        """A count arrived: kept when still current, requested again when not."""
        if self._walking.get(path) == token:
            self._walking.pop(path)
        if not self._shows(path):
            return    # gone while it walked
        if token != self._tokens.get(path, 0):
            self._ask_count(path)    # changed while it walked: its result is of the folder as it was
            return
        count, names, opened = result
        self._counts[path] = count
        self._counted[path] = token
        self._listed[path] = list(names)
        if opened:
            self._unreachable.discard(path)
        else:
            self._unreachable.add(path)
        wanted = [self._join(path, name) for name in names]
        for row_id in list(self._by_key.get(path, ())):
            self._merge(row_id, wanted)
        self._counts_not_signalled.add(path)
        if not self._walking:
            self._signal_counts()    # the last one finished: notify now
        elif not self._signal_counts_pending:
            self._signal_counts_pending = True
            QtCore.QTimer.singleShot(self.SIGNAL_COUNTS_MS, self._signal_counts)

    def _signal_counts(self) -> None:
        """Every count arrived since the last call, signalled in ONE pass, so the views repaint once."""
        self._signal_counts_pending = False
        paths, self._counts_not_signalled = self._counts_not_signalled, set()
        if not paths:
            return
        rows = [index for index in map(self.index_of, sorted(paths)) if index.isValid()]
        rows += [index for index in (self._index_for(row_id) for path in sorted(paths)    # a folder on two top rows
                                     for row_id in sorted(self._by_key.get(path, ())))
                 if index.isValid() and index not in rows]
        for index in rows + [self.index(0, 0)]:    # each row, then All, whose total changed
            self.dataChanged.emit(index, index, [self.COUNT_ROLE, category.SIDEBAR_UNREACHABLE_ROLE])

    def _walk_ended(self, worker) -> None:
        """A walk is done: the next queued folder takes its slot."""
        self._live = max(0, self._live - 1)
        if worker.path in self._walking and self._walking[worker.path] == worker.token:
            self._walking.pop(worker.path)
        if worker._canceled:    # a shutdown: start nothing; the next paint requests again
            for path in self._queued:
                self._walking.pop(path, None)
            self._queued = []
        elif self._queued:
            self._dispatch_counts()    # direct: `finished` is delivered on the GUI thread

    def _on_folder_relocated(self, old_path: str, new_path: str) -> None:
        """Hook: update per-location state after a Locate Folder. Base: none."""


    @staticmethod
    def _join(folder: str, name: str) -> str:
        return folder.rstrip("/") + "/" + name

    def index_of(self, path) -> QtCore.QModelIndex:
        """The row showing `path`, with or without its trailing slash: All for "", a top row first."""
        if not path:
            return super().index_of("")
        key = str(path).rstrip("/")
        return super().index_of(next(    # a top row keeps its slash, a subfolder's key has none
            (folder for folder in self.top_keys() if folder.rstrip("/") == key), key))

    def data(self, index, role: int = 0):
        if index.column():
            return self.color_cell(index, role)
        if role not in self.ROW_ROLES:
            return None    # the style asks for six more roles per row on every repaint
        if role == category.SIDEBAR_KEY_ROLE:
            return super().data(index, role)    # the folder the row shows, as BrowseRole; "" on All
        if not index.isValid():
            return None
        node = self._nodes.get(index.internalId())
        if node is None:
            return None
        parent_id, path = node
        if path is None:
            if role == QtCore.Qt.ItemDataRole.DisplayRole:    # All has no real path ▸p/folder-sidebar
                return self.ALL_LABEL
            if role == self.COUNT_ROLE:
                counts = [self._folder_count(p) for p in self._folders()]    # requests counts, walks nothing here
                return None if None in counts else sum(counts)    # no partial total ▸p/folder-sidebar
            return None
        if role == self.COUNT_ROLE:
            return self._folder_count(path)
        if role == category.SIDEBAR_UNREACHABLE_ROLE:
            return path in self._unreachable
        if parent_id == _SCENE:
            return self._scene_data(path, role)
        location = parent_id is None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self.display_name(path) if location else path.rsplit("/", 1)[-1]
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return path
        if role == self.PathRole:
            return path if location else None    # every location action reads this
        if role == self.BrowseRole:
            return path
        if role == category.SIDEBAR_COLOR_ROLE:    # the asset sidebars' role, so ONE delegate paints it
            return self.color_of(path) if location else ""
        return None

    def _scene_data(self, path: str, role: int):
        """The fixed row: browsed like a folder, no PathRole, so no location action applies to it."""
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self.SCENE_LABEL
        if role in (QtCore.Qt.ItemDataRole.ToolTipRole, self.BrowseRole):
            return path
        if role == category.SIDEBAR_COLOR_ROLE:
            return ""
        return None

    def row_of(self, path: str):
        """The first TOP row showing this folder, the scene's first, or None; All's +1 is added HERE."""
        tops = self.top_keys()
        if path in tops:
            return tops.index(path) + 1
        return None

    def color_of(self, path: str) -> str:
        """This location's colour, "" for none - ONE record: this runs per row."""
        return str(self._record(path).get("color", ""))

    def set_color(self, path: str, color: str) -> None:
        """Colour one location in its record through the prefs method, or clear it with ""."""
        if not self.color_folder_method:
            return
        getattr(self.preferences, self.color_folder_method)(path, color)
        row = self.row_of(path)
        if row is not None:
            index = self.index(row, 0)
            self.dataChanged.emit(index, index)


    def is_location(self, path: str, but: str = "") -> bool:
        """Is this folder a registered location already, however it is spelled? `but` is left out."""
        if not path:
            return False
        wanted = locations.path_identity(hostos.canonical_path_key(path).rstrip("/") + "/")
        return any(locations.path_identity(folder) == wanted
                   for folder in self._folders() if folder != but)

    def add_folder(self, path: str) -> bool:
        """Register a folder; True when its row was added, False if already registered."""
        if not path or path in self._folders():
            return False
        before, after = self._write_and_signal(
            lambda: getattr(self.preferences, self.add_folder_method)(path))
        return len(after) > len(before)

    def remove_folder(self, row: int) -> bool:
        # All and the scene row are not locations; True when the location was removed
        return self.unregister_folder(row)

    def unregister_folder(self, row: int) -> bool:
        """Remove the location at ROW, nothing else; its files' data is kept for when it is re-added."""
        path = self.registered_at(row)
        if not path:
            return False
        _before, after = self._write_and_signal(
            lambda: getattr(self.preferences, self.remove_folder_method)(path))
        return path not in after

    def movable(self, index) -> bool:
        """Whether a row may be dragged: a registered location, never All, the scene row or a subfolder."""
        if index is None or not index.isValid() or index.parent().isValid():
            return False    # a subfolder moves with its location, never alone
        return self._offset() <= index.row() < self.rowCount()

    def move_row(self, index, to_row: int) -> bool:
        """Move a location to top row `to_row`, clamped to the rows the locations take."""
        if index is None or not index.isValid():
            return False
        to_row = max(self._offset(), min(int(to_row), self.rowCount() - 1))
        return self.move_folder(index.row(), to_row)

    def commit_order(self) -> None:
        """Save the order a move staged, once."""
        locations.commit_registered_order(self.preferences)

    def move_folder(self, from_row: int, to_row: int) -> bool:
        """Move one location to another TOP row; `commit_order` saves it."""
        if not self.move_folder_method:
            return False
        folders = self._folders()
        first = self._offset()    # nothing moves onto or above All and the scene row
        last = first + len(folders) - 1
        if not (first <= from_row <= last and first <= to_row <= last):
            return False
        if from_row == to_row:
            return False
        path = folders[from_row - first]
        destination = to_row if to_row < from_row else to_row + 1
        if not self.beginMoveRows(_ROOT, from_row, from_row, _ROOT, destination):
            return False
        try:
            moved = bool(getattr(self.preferences,
                                 self.move_folder_method)(path,
                                                          to_row - first))
        finally:
            self.endMoveRows()
        if not moved:
            self.beginResetModel()    # the view moved but the saved order did not: reset ▸p/folder-sidebar
            self._forget_rows()
            self.endResetModel()
        return moved

    def sort_folders(self) -> bool:
        """Sort the locations by the label each shows, as one reset; True if any moved."""
        current = list(self._folders())
        ordered = sorted(current, key=lambda path: str(self.display_name(path)).lower())
        if ordered == current:
            return False
        self.restore_order(ordered)    # a reset: the caller restores the sidebar's state
        return True

    def restore_order(self, paths) -> None:
        """Put the locations in `paths`' order, as one reset: what the sort actions use. ▸p/folder-sidebar"""
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
            self._forget_rows()
        finally:
            self.endResetModel()

    def relocate_folder(self, row: int, new_path: str) -> int:
        """Relocate ROW's location; the favourites moved, -1, or ALREADY_A_LOCATION. ▸p/folder-sidebar"""
        old_path = self.registered_at(row)
        if not old_path:
            return -1
        if not new_path or not os.path.isdir(new_path):
            return -1
        new_path = hostos.canonical_path_key(new_path)    # CANONICAL FIRST, then the trailing slash
        if not new_path.endswith("/"):
            new_path += "/"
        if new_path == old_path:
            return 0
        if self.is_location(new_path, but=old_path):
            return ALREADY_A_LOCATION    # two ids would point at one folder
        old_prefix = old_path if old_path.endswith("/") else old_path + "/"    # COUNTED here ▸p/folder-sidebar
        rewritten = sum(1 for fav in self._favorites()
                        if fav.startswith(old_prefix))

        def write():
            getattr(self.preferences, self.relocate_folder_method)(    # a NAMED call ▸p/folder-sidebar
                old_path, new_path)
            if getattr(self.preferences, self.last_folder_attr) == old_path:
                setattr(self.preferences, self.last_folder_attr, new_path)
            self._on_folder_relocated(old_path, new_path)    # everything else keyed on the old path is updated too
            self.preferences.save()
            self._rows_key = None
            self._records_key = None
        self._replace_top_row_folder(row, None, old_path, new_path, write)
        index = self.index(0, 0)
        self.dataChanged.emit(index, index)    # All's total changed
        return rewritten

    def _replace_top_row_folder(self, row: int, parent_id, old_path: str, new_path: str, write) -> None:
        """One top row shows another folder IN PLACE: its subfolder rows go, `write` saves the change."""
        old_id = self._id(parent_id, old_path)
        kids = self._kids.get(old_id)
        if kids:    # the old folder's subfolders are removed first, while their parent still exists
            self.beginRemoveRows(self.createIndex(row, 0, old_id), 0, len(kids) - 1)
            for child in list(kids):
                self._forget_row(self._node_ids.get((old_id, child)))
            kids.clear()
            self.endRemoveRows()
        write()
        self._out_of_date((old_path, new_path), keep=False)    # this row only; the rest are still valid
        new_id = self._id(parent_id, new_path)
        self._kids[new_id] = []    # its subfolders are added by the next read's inserts, never without signals
        self.changePersistentIndex(self.createIndex(row, 0, old_id),
                                   self.createIndex(row, 0, new_id))
        self._forget_row(old_id)
        index = self.index(row, 0)
        self.dataChanged.emit(index, index)


counter = workers.install(__name__, _CountEngine, QtCore.QCoreApplication.instance())
