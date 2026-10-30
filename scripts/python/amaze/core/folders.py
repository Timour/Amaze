"""Locations under All, each unfolding to its subfolders, read on a worker. ▸p/folder-sidebar
"""

import atexit
import functools
import os

from PySide6 import QtCore

from amaze.core import category, debug
from amaze.helpers import hostos


_unstoppable: list = globals().get("_unstoppable", [])    # walks that would not stop ▸r/model-contracts


def walk_following_links(root: str):
    """`os.walk` following symlinked folders, each real one once; a caller may prune or sort `dirnames` in place. Only a link is resolved: a plain folder's real path is its parent's plus its name. ▸r/platform-files"""
    try:
        stack = [(root, os.path.realpath(root))]
    except OSError:
        return
    seen = set()
    while stack:
        dirpath, real = stack.pop()
        if real in seen:
            continue                  # already covered by another path
        seen.add(real)
        try:
            with os.scandir(dirpath) as listing:
                entries = list(listing)
        except OSError:
            continue                  # unreadable, as os.walk skips it
        dirnames, filenames, reals = [], [], {}
        for entry in entries:
            try:
                is_dir = entry.is_dir()    # follows a link, as followlinks=True does
            except OSError:
                is_dir = False
            if not is_dir:
                filenames.append(entry.name)
                continue
            if hostos.is_link_like(entry):
                try:
                    child_real = os.path.realpath(entry.path)
                except OSError:
                    continue
            else:
                child_real = os.path.join(real, entry.name)
            if child_real not in seen:
                dirnames.append(entry.name)
                reals[entry.name] = child_real
        yield dirpath, dirnames, filenames
        for name in reversed(dirnames):    # depth first, in the caller's order, as os.walk goes
            if name in reals:
                stack.append((os.path.join(dirpath, name), reals[name]))


def scan_folder(path: str, recursive: bool, matches, stopped=lambda: False):
    """(files the sidebar counts, visible subfolder names), or None once `stopped()`."""
    count, subfolders = 0, []
    try:
        if recursive:
            for depth, (_dirpath, dirnames, filenames) in enumerate(walk_following_links(path)):
                if stopped():
                    return None
                dirnames[:] = sorted((d for d in dirnames if not d.startswith(".")),
                                     key=str.lower)    # hidden folders pruned, as the grid prunes them
                if depth == 0:
                    subfolders = list(dirnames)
                count += sum(1 for name in filenames if matches(name))
            return count, subfolders
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
        return 0, []
    return count, sorted(subfolders, key=str.lower)


def _gone(thread) -> bool:
    """A thread whose C++ side is deleted: it can never emit again."""
    try:
        thread.isFinished()
        return False
    except RuntimeError:
        return True


class _CountWorker(QtCore.QThread):
    """Reads ONE folder off the GUI thread, by the rule the GUI thread resolved."""

    counted = QtCore.Signal(object, object, object)    # (path, token, (count, subfolders))

    def __init__(self, path, token, recursive, matches) -> None:
        super().__init__()
        self.path, self.token = path, token
        self._recursive, self._matches = recursive, matches
        self.canceled = False    # the stop flag, the thumbnail loaders' contract; kept once it ends

    def cancel(self) -> None:
        self.canceled = True

    def _stopped(self) -> bool:
        return self.canceled or self.isInterruptionRequested()

    def run(self) -> None:
        try:
            result = scan_folder(self.path, self._recursive, self._matches,
                                 self._stopped)
        except Exception as exc:                          # noqa: BLE001 - logged; the worker still ends
            debug.event("folders", "count failed", folder=self.path,
                        error=str(exc))
            return
        if result is not None:
            self.counted.emit(self.path, self.token, result)


class _CountEngine(QtCore.QObject):
    """Every folder read in the process, stopped on quit. ▸r/model-contracts"""

    def __init__(self) -> None:
        super().__init__()
        self._threads = []    # a running QThread must keep a reference until it ends ▸r/model-contracts

    def start(self, job, landed, ended) -> None:
        """One worker over one folder: `landed(path, token, result)`, then `ended(worker)`."""
        worker = _CountWorker(*job)
        worker.counted.connect(landed)
        worker.finished.connect(    # bound here, never sender(): ordering is per sender ▸r/model-contracts
            functools.partial(self._finished, worker, ended))
        self._threads.append(worker)
        worker.start()

    def _finished(self, worker, ended) -> None:
        self._threads = [t for t in self._threads
                         if t is not worker and not _gone(t)]
        ended(worker)

    def shutdown(self) -> None:
        """Stop every walk, THEN wait for each; safe twice and with nothing running."""
        for thread in list(self._threads):
            try:
                thread.cancel()
                thread.requestInterruption()
            except RuntimeError:
                pass
        unstopped = []
        for thread in list(self._threads):
            try:
                if thread.isRunning() and not thread.wait(3000):    # bounded, as thumbnails' is
                    thread.terminate()
                    if not thread.wait(500):
                        unstopped.append(thread)
            except RuntimeError:
                pass
        if unstopped:    # parked, not dropped: freed mid-run it takes the process down
            _unstoppable.extend(unstopped)
            debug.event("folders", "count walks would not stop - parked",
                        count=len(unstopped))
        self._threads = []


_ROOT = QtCore.QModelIndex()


class FolderTreeModel(QtCore.QAbstractItemModel):
    """Locations under a synthetic All, each with the subfolders its last read found."""

    PathRole = QtCore.Qt.ItemDataRole.UserRole    # a REGISTERED location's path; None on All and subfolders
    BrowseRole = QtCore.Qt.ItemDataRole.UserRole + 1    # the folder a row shows; None on All
    ALL_LABEL = "All"
    COUNT_ROLE = category.SIDEBAR_COUNT_ROLE    # the ONE definition, shared by every sidebar model
    unfolds = True    # its rows keep an arrow's room ▸r/tree-views

    folders_attr = ""           # prefs attribute holding the folder list, e.g. `file_folders`
    favorites_attr = ""         # prefs attribute holding full-path favourites for this section
    last_folder_attr = ""       # prefs attribute remembering the last-selected folder
    add_folder_method = ""      # prefs METHOD names that add/remove and persist ▸p/folder-sidebar
    remove_folder_method = ""
    relocate_folder_method = ""    # re-points one folder IN ITS OWN ROW ▸p/folder-sidebar
    move_folder_method = ""        # the sidebar reorder; empty = this section's folders do not reorder
    COUNT_WORKERS = 4    # reads at once: a slow share holds one, the other reads keep landing
    ANNOUNCE_MS = 100    # reads landing inside this window repaint the sidebar once, not each
    _counts_asked = QtCore.Signal()    # queued: an ask from ANY thread dispatches on the GUI thread

    def __init__(self, preferences, parent: QtCore.QObject | None = None) -> None:
        super().__init__()
        self.preferences = preferences
        self._counts_asked.connect(self._dispatch_counts,    # a zero-timer armed off a Qt thread never fires
                                   QtCore.Qt.ConnectionType.QueuedConnection)
        self._counts: dict = {}    # path -> its last count; a paint reads only this ▸p/folder-sidebar
        self._counted: dict = {}    # path -> the token its count was walked under
        self._tokens: dict = {}    # path -> the token a current count carries; a change bumps it
        self._walking: dict = {}    # path -> its ONE walk's token, None while still queued
        self._queued: list = []
        self._live = 0    # this model's workers still running
        self._count_scheduled = False
        self._unannounced: set = set()    # landed, the views not told yet
        self._announce_armed = False
        self._rows: list = []
        self._rows_key = None    # what `_rows` was read against; None reads again
        self._records: dict = {}    # path -> its location record, read against `_records_key`
        self._records_key = None
        self._listed: dict = {}    # folder path -> the subfolder names its last read found
        self._nodes: dict = {0: (None, None)}    # row id -> (parent row id, path); 0 is All
        self._node_ids: dict = {}    # (parent row id, path) -> row id
        self._by_path: dict = {}    # path -> the ids of every row showing it
        self._kids: dict = {}    # row id -> its child paths in order, once asked
        self._next_id = 0


    def matches_in(self, path: str, filename: str) -> bool:
        """Folder-aware match: the base asks the flat rule; File asks Show ▸'s ticks."""
        return self.matches(filename)

    def matches(self, filename: str) -> bool:
        """Does this filename belong to the section (by extension)?"""
        raise NotImplementedError


    def _folders(self) -> list:
        held = getattr(self, "_held", None)    # the rows the views know, while a write is answered
        if held is not None:
            return held
        key = self._rows_token()
        if key != self._rows_key:
            self._rows = list(getattr(self.preferences, self.folders_attr))
            self._rows_key = key
        return self._rows

    def _rows_token(self) -> tuple:
        """What the registered list derives from: a location write, the copy's order, library, user."""
        from amaze.core import locations
        preferences = self.preferences
        return (locations.generation(),
                tuple(getattr(preferences, "last_known_folders", ()) or ()),
                str(getattr(preferences, "dir", "")),
                str(getattr(preferences, "library_user", "")))

    def _answered(self, write) -> tuple:
        """Run one prefs write with the old rows still served, then announce what it changed."""
        before = list(self._folders())
        self._held = before
        try:
            write()
            after = list(getattr(self.preferences, self.folders_attr))
            self._announce(before, after)
        finally:
            self._held = None
        for path in set(before) - set(after):
            self._forget_row(self._node_ids.get((None, path)))    # its rows went with it
        self._out_of_date(set(before).symmetric_difference(after),    # the others' counts still hold
                          keep=False)
        return before, after

    def _announce(self, before: list, after: list) -> None:
        """One row in or out as its own signals, anything else as a reset, a refusal as nothing."""
        if after == before:
            return
        at = next((i for i, (old, new) in enumerate(zip(before, after))
                   if old != new), min(len(before), len(after)))
        if len(after) == len(before) + 1 \
                and after[:at] + after[at + 1:] == before:
            self.beginInsertRows(_ROOT, at + 1, at + 1)    # +1 for the All row
            self._held = None
            self.endInsertRows()
        elif len(after) == len(before) - 1 \
                and before[:at] + before[at + 1:] == after:
            self.beginRemoveRows(_ROOT, at + 1, at + 1)
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
        """Re-point at the live library; the rows read through. ▸p/folders-follow-the-library"""
        self.beginResetModel()
        try:
            self._out_of_date(self._known(), keep=False)    # another library's rules: no number carries over
            self._rows_key = None
            self._records_key = None
            self._forget_rows()
            self._listed = {}
        finally:
            self.endResetModel()

    def refresh_counts(self) -> None:
        """Every read out of date, each shown until a fresh one lands; the rows read again."""
        self._out_of_date(self._known())
        self._rows_key = None
        self._records_key = None

    def _known(self) -> set:
        return set(self._counts) | set(self._walking)

    def _out_of_date(self, paths, keep: bool = True) -> None:
        """Bump each folder's token, so a walk still running for it lands and is dropped."""
        for path in paths:
            self._tokens[path] = self._tokens.get(path, 0) + 1
            if not keep:
                self._counts.pop(path, None)
                self._counted.pop(path, None)

    def _record(self, path: str) -> dict:
        """One location's record, kept until a location write or a store rereads its file."""
        from amaze.core import keyed_store, locations
        key = (self._rows_token(), keyed_store.loads())
        if key != self._records_key:
            self._records = {}
            self._records_key = key
        found = self._records.get(path)
        if found is None:
            found = self._records[path] = locations.record(self.preferences, path)
        return found

    def includes_subfolders(self, path: str) -> bool:
        """Whether this folder's count walks below it; the base answers no. ▸p/folder-sidebar"""
        return False

    def location_of(self, path: str) -> str:
        """The innermost registered location a folder sits in, else the folder itself."""
        if not path:
            return path    # no folder, no location: the global rule answers
        from amaze.core import locations
        return locations.innermost(self._folders(), path) or path

    def display_name(self, path: str) -> str:
        """A location's sidebar label: its folder name here; FileFolders adds names and paths."""
        return os.path.basename(path.rstrip("/\\")) or path

    def _matcher_for(self, path: str):
        """One folder's name test, its rule resolved ONCE here; it runs on the count's worker."""
        return lambda name: self.matches_in(path, name)

    def _shows(self, path: str) -> bool:
        """Whether some row still shows this folder: a location, or a subfolder already read."""
        return path in set(self._folders()) or bool(self._by_path.get(path))

    def _folder_count(self, path: str):
        """The count known now, None before one lands; a stale one is read off the GUI thread."""
        if self._counted.get(path) != self._tokens.get(path, 0):
            self._ask_count(path)
        return self._counts.get(path)

    def _ask_count(self, path: str) -> None:
        if path in self._walking:
            return    # ONE walk per folder; a stale one asks again when it lands
        self._walking[path] = None
        self._queued.append(path)
        if not self._count_scheduled:
            self._count_scheduled = True
            self._counts_asked.emit()    # one paint's asks, one dispatch

    def _dispatch_counts(self) -> None:
        """One queued folder per free worker, its rule resolved HERE, on the GUI thread."""
        self._count_scheduled = False
        if self._live >= self.COUNT_WORKERS or not self._queued:
            return    # a worker ending dispatches again
        while self._queued and self._live < self.COUNT_WORKERS:
            path = self._queued.pop(0)    # one each: a slow share then holds only its own worker
            if not self._shows(path):
                self._walking.pop(path, None)    # gone before its walk began
                continue
            try:
                rule = (bool(self.includes_subfolders(path)),
                        self._matcher_for(path))
            except Exception as exc:                          # noqa: BLE001 - a bad record skips one count, not all
                self._walking.pop(path, None)
                debug.event("folders", "count rule unreadable", folder=path,
                            error=str(exc))
                continue
            token = self._tokens.get(path, 0)
            self._walking[path] = token
            self._live += 1
            counter.start((path, token) + rule, self._on_counted, self._walk_ended)

    def _on_counted(self, path, token, result) -> None:
        """A read landed: kept when still current, asked again when not."""
        if self._walking.get(path) == token:
            self._walking.pop(path)
        if not self._shows(path):
            return    # gone while it walked
        if token != self._tokens.get(path, 0):
            self._ask_count(path)    # changed while it walked: its answer is the old rule's
            return
        count, names = result
        self._counts[path] = count
        self._counted[path] = token
        self._listed[path] = list(names)
        wanted = [self._join(path, name) for name in names]
        for row_id in list(self._by_path.get(path, ())):
            self._merge(row_id, wanted)
        self._unannounced.add(path)
        if not self._walking:
            self._announce_counts()    # the last one in: say it now
        elif not self._announce_armed:
            self._announce_armed = True
            QtCore.QTimer.singleShot(self.ANNOUNCE_MS, self._announce_counts)

    def _announce_counts(self) -> None:
        """Every read landed since the last call, told in ONE pass, so the views repaint once."""
        self._announce_armed = False
        paths, self._unannounced = self._unannounced, set()
        if not paths:
            return
        rows = [index for index in map(self.index_of, sorted(paths)) if index.isValid()]
        for index in rows + [self.index(0, 0)]:    # each row, then All, whose total moved
            self.dataChanged.emit(index, index, [self.COUNT_ROLE])

    def _walk_ended(self, worker) -> None:
        """A walk is done: the next queued folder takes its slot."""
        self._live = max(0, self._live - 1)
        if worker.path in self._walking and self._walking[worker.path] == worker.token:
            self._walking.pop(worker.path)
        if worker.canceled:    # a shutdown: start nothing; the next paint asks again
            for path in self._queued:
                self._walking.pop(path, None)
            self._queued = []
        elif self._queued:
            self._dispatch_counts()    # direct: `finished` lands on the GUI thread

    def _on_folder_relocated(self, old_path: str, new_path: str) -> None:
        """Hook: per-location state follows a Locate Folder. Base: none."""


    @staticmethod
    def _join(folder: str, name: str) -> str:
        return folder.rstrip("/") + "/" + name

    def _id(self, parent_id, path) -> int:
        """The row id of `path` shown under the row `parent_id` (None at the top)."""
        key = (parent_id, path)
        row_id = self._node_ids.get(key)
        if row_id is None:
            self._next_id += 1
            row_id = self._node_ids[key] = self._next_id
            self._nodes[row_id] = key
            self._by_path.setdefault(path, set()).add(row_id)
        return row_id

    def _children(self, row_id) -> list:
        """A row's child paths; the first ask takes them from the folder's last read."""
        kids = self._kids.get(row_id)
        if kids is None:
            path = self._nodes[row_id][1]
            kids = self._kids[row_id] = [self._join(path, name)
                                         for name in self._listed.get(path, ())]
        return kids

    def _index_for(self, row_id) -> QtCore.QModelIndex:
        """The index of a row id where it stands now, invalid once it stands nowhere."""
        node = self._nodes.get(row_id)
        if node is None:
            return QtCore.QModelIndex()
        parent_id, path = node
        if path is None:
            return self.createIndex(0, 0, 0)
        if parent_id is None:
            row = self.row_of(path)
        else:
            siblings = self._kids.get(parent_id) or []
            row = siblings.index(path) if path in siblings else None
        return QtCore.QModelIndex() if row is None else self.createIndex(row, 0, row_id)

    def _merge(self, row_id, wanted: list) -> None:
        """One row's children brought in line with a read: what left goes, what came arrives."""
        kids = self._kids.get(row_id)
        if kids is None or kids == wanted:
            return    # never asked: its first ask reads the new list
        parent = self._index_for(row_id)
        if not parent.isValid():
            return
        keep = set(wanted)
        for row in range(len(kids) - 1, -1, -1):
            if kids[row] not in keep:
                self.beginRemoveRows(parent, row, row)
                gone = kids.pop(row)
                self._forget_row(self._node_ids.get((row_id, gone)))
                self.endRemoveRows()
        for row, path in enumerate(wanted):
            if row >= len(kids) or kids[row] != path:
                self.beginInsertRows(parent, row, row)
                kids.insert(row, path)
                self.endInsertRows()

    def _forget_row(self, row_id) -> None:
        """Drop a row id and everything below it; no signals - its rows are already gone."""
        if row_id is None or row_id not in self._nodes:
            return
        for child in self._kids.pop(row_id, None) or ():
            self._forget_row(self._node_ids.get((row_id, child)))
        key = self._nodes.pop(row_id)
        self._node_ids.pop(key, None)
        showing = self._by_path.get(key[1])
        if showing is not None:
            showing.discard(row_id)
            if not showing:
                del self._by_path[key[1]]
                if key[0] is not None:    # a subfolder no row shows: its numbers go with it
                    for table in (self._counts, self._counted, self._tokens, self._listed):
                        table.pop(key[1], None)

    def _forget_rows(self) -> None:
        """Every row id but All's, inside a reset; what the reads found stays."""
        self._nodes = {0: (None, None)}
        self._node_ids = {}
        self._by_path = {}
        self._kids = {}

    def index_of(self, path) -> QtCore.QModelIndex:
        """The row showing `path`: a location, or a subfolder already read; else invalid."""
        if not path:
            return QtCore.QModelIndex()
        key = str(path).rstrip("/")
        for row, folder in enumerate(self._folders(), 1):
            if folder.rstrip("/") == key:
                return self.createIndex(row, 0, self._id(None, folder))
        up = key.rsplit("/", 1)[0] if "/" in key else ""
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
            folders = self._folders()
            if row == 0:
                return self.createIndex(0, 0, 0)
            if row - 1 < len(folders):
                return self.createIndex(row, 0, self._id(None, folders[row - 1]))
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
        if node is None or node[0] is None:
            return QtCore.QModelIndex()
        return self._index_for(node[0])

    def rowCount(self, parent=None) -> int:
        if parent is None or not parent.isValid():
            return len(self._folders()) + 1
        node = self._nodes.get(parent.internalId())
        if node is None or node[1] is None:
            return 0
        return len(self._children(parent.internalId()))

    def columnCount(self, parent=None) -> int:
        return 1

    def hasChildren(self, parent=None) -> bool:
        return self.rowCount(parent) > 0

    def data(self, index, role: int = 0):
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
                counts = [self._folder_count(p) for p in self._folders()]    # asks, walks nothing here
                return None if None in counts else sum(counts)    # no partial total ▸p/folder-sidebar
            return None
        location = parent_id is None
        if role == self.COUNT_ROLE:
            return self._folder_count(path)
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self.display_name(path) if location else path.rsplit("/", 1)[-1]
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return path
        if role == self.PathRole:
            return path if location else None    # every location verb keys off this
        if role == self.BrowseRole:
            return path
        if role == category.SIDEBAR_COLOR_ROLE:    # the asset sidebars' role, so ONE delegate paints it
            return self.folder_color(path) if location else ""
        return None

    def row_of(self, path: str):
        """The TOP row showing this registered folder, or None; the +1 for All lives HERE."""
        folders = self._folders()
        if path in folders:
            return folders.index(path) + 1
        return None

    def folder_color(self, path: str) -> str:
        """This location's colour, "" for none - ONE record: this runs per row."""
        return str(self._record(path).get("color", ""))


    def add_folder(self, path: str) -> bool:
        """Register a folder pointer; True when its row landed, nothing if already registered."""
        if not path or path in self._folders():
            return False
        before, after = self._answered(
            lambda: getattr(self.preferences, self.add_folder_method)(path))
        return len(after) > len(before)

    def remove_folder(self, row: int) -> bool:
        # row 0 is the synthetic All entry; True when the pointer is gone
        return self.set_aside_folder(row)

    def set_aside_folder(self, row: int) -> bool:
        """Drop the pointer at ROW and nothing else; what its files carry waits for it to return."""
        if row <= 0 or not row - 1 < len(self._folders()):
            return False
        path = self._folders()[row - 1]
        _before, after = self._answered(
            lambda: getattr(self.preferences, self.remove_folder_method)(path))
        return path not in after

    def move_folder(self, from_row: int, to_row: int) -> bool:
        """Move one location to another TOP row - the press-hold reorder, persisted on release."""
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
        if not self.beginMoveRows(_ROOT, from_row, from_row, _ROOT, destination):
            return False
        try:
            moved = bool(getattr(self.preferences,
                                 self.move_folder_method)(path,
                                                          to_row - 1))
        finally:
            self.endMoveRows()
        if not moved:
            self.beginResetModel()    # the view moved and the truth did not: resync ▸p/folder-sidebar
            self._forget_rows()
            self.endResetModel()
        return moved

    def restore_folder_order(self, paths) -> None:
        """Put a snapshot's order back: the reorder's Esc, a reset. ▸p/folder-sidebar"""
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
        """Re-point the location at ROW; the favourites moved, or -1. ▸p/folder-sidebar"""
        if row <= 0 or not row - 1 < len(self._folders()):
            return -1
        if not new_path or not os.path.isdir(new_path):
            return -1
        new_path = hostos.canonical_path_key(new_path)    # CANONICAL FIRST, then the pointer's slash
        if not new_path.endswith("/"):
            new_path += "/"
        old_path = self._folders()[row - 1]
        if new_path == old_path:
            return 0
        old_id = self._id(None, old_path)
        kids = self._kids.get(old_id)
        if kids:    # the old folder's subfolders leave first, while their parent still stands
            self.beginRemoveRows(self.createIndex(row, 0, old_id), 0, len(kids) - 1)
            for child in list(kids):
                self._forget_row(self._node_ids.get((old_id, child)))
            kids.clear()
            self.endRemoveRows()
        old_prefix = old_path if old_path.endswith("/") else old_path + "/"    # COUNTED here ▸p/folder-sidebar
        rewritten = sum(1 for fav in self._favorites()
                        if fav.startswith(old_prefix))
        getattr(self.preferences, self.relocate_folder_method)(    # a NAMED call ▸p/folder-sidebar
            old_path, new_path)
        if getattr(self.preferences, self.last_folder_attr) == old_path:
            setattr(self.preferences, self.last_folder_attr, new_path)
        self._on_folder_relocated(old_path, new_path)    # everything else keyed on the old path rides along
        self.preferences.save()
        self._rows_key = None
        self._records_key = None
        self._out_of_date((old_path, new_path), keep=False)    # this location only; the rest still hold
        self.changePersistentIndex(self.createIndex(row, 0, old_id),
                                   self.createIndex(row, 0, self._id(None, new_path)))
        self._forget_row(old_id)
        for at in (row, 0):
            index = self.index(at, 0)
            self.dataChanged.emit(index, index)
        return rewritten


_previous_counter = globals().get("counter")    # a reload re-runs this body: stop the old walks first ▸r/module-reload
if _previous_counter is not None:
    try:
        _previous_counter.shutdown()
    except Exception:                                    # noqa: BLE001
        pass
    try:
        atexit.unregister(_previous_counter.shutdown)
    except Exception:                                    # noqa: BLE001
        pass
    try:
        _prev_app = QtCore.QCoreApplication.instance()
        if _prev_app is not None:
            _prev_app.aboutToQuit.disconnect(_previous_counter.shutdown)
    except (RuntimeError, TypeError):
        pass                     # never connected, or already gone

counter = _CountEngine()

_app_instance = QtCore.QCoreApplication.instance()
if _app_instance is not None:
    _app_instance.aboutToQuit.connect(counter.shutdown)    # quitting Houdini mid-walk

atexit.register(counter.shutdown)    # headless, aboutToQuit never fires ▸r/model-contracts
