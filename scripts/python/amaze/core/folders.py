"""The ONE folder-pointer sidebar model behind every Folder-archetype section - a flat list of registered paths plus a synthetic All at row 0. POINTERS, not an index: registering a folder scans or copies nothing. ▸p/folder-sidebar
"""

import atexit
import functools
import os

from PySide6 import QtCore

from amaze.core import category, debug
from amaze.helpers import hostos


_unstoppable: list = globals().get("_unstoppable", [])    # walks that would not stop, parked for good ▸r/model-contracts


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


def count_files(path: str, recursive: bool, matches, stopped=lambda: False):
    """Files the sidebar counts in one location, None once `stopped()` is true. ▸p/folder-sidebar"""
    count = 0
    try:
        if recursive:
            for _dirpath, dirnames, filenames in walk_following_links(path):
                if stopped():
                    return None
                dirnames[:] = [d for d in dirnames    # hidden folders pruned, as the grid prunes them
                               if not d.startswith(".")]
                dirnames.sort()
                count += sum(1 for name in filenames if matches(name))
            return count
        for name in os.listdir(path):    # FILES only, matching the grid's flat scan
            if stopped():
                return None
            if matches(name) and os.path.isfile(os.path.join(path, name)):
                count += 1
    except OSError:
        return 0
    return count


def _gone(thread) -> bool:
    """A thread whose C++ side is deleted: it can never emit again."""
    try:
        thread.isFinished()
        return False
    except RuntimeError:
        return True


class _CountWorker(QtCore.QThread):
    """Counts a batch of locations off the GUI thread, each by the rule the GUI thread resolved."""

    counted = QtCore.Signal(object, object, object)    # (path, token, count)

    def __init__(self, jobs) -> None:
        super().__init__()
        self._jobs = jobs    # [(path, token, recursive, matches)]
        self._canceled = False    # the stop flag, the thumbnail loaders' contract

    def jobs(self) -> list:
        return [(path, token) for path, token, _recursive, _matches in self._jobs]

    def cancel(self) -> None:
        self._canceled = True

    def _stopped(self) -> bool:
        return self._canceled or self.isInterruptionRequested()

    def run(self) -> None:
        for path, token, recursive, matches in self._jobs:
            try:
                count = count_files(path, recursive, matches, self._stopped)
            except Exception as exc:                          # noqa: BLE001 - one bad rule must not end the batch
                debug.event("folders", "count failed", folder=path,
                            error=str(exc))
                continue
            if count is None:
                return
            self.counted.emit(path, token, count)


class _CountEngine(QtCore.QObject):
    """Every count walk in the process, held until it finishes and stopped on quit. ▸r/model-contracts"""

    def __init__(self) -> None:
        super().__init__()
        self._threads = []    # a running QThread must keep a reference until it ends ▸r/model-contracts

    def start(self, jobs, landed, ended) -> None:
        """One worker over `jobs`: `landed(path, token, count)` per location, then `ended(worker)`."""
        worker = _CountWorker(jobs)
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
    COUNT_WORKERS = 4    # walks at once: a slow share holds one, the other counts keep landing
    ANNOUNCE_MS = 100    # counts landing inside this window repaint the sidebar once, not each
    _counts_asked = QtCore.Signal()    # queued: an ask from ANY thread dispatches on this model's

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


    def matches_in(self, path: str, filename: str) -> bool:
        """Folder-aware match - the base asks the flat rule; File overrides it for the per-location Show All Files setting."""
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
        self._out_of_date(set(before).symmetric_difference(after),    # the others' counts still hold
                          keep=False)
        return before, after

    def _announce(self, before: list, after: list) -> None:
        """One row in or out as its own signals, anything else as a reset, a refusal as nothing."""
        if after == before:
            return
        at = next((i for i, (old, new) in enumerate(zip(before, after))
                   if old != new), min(len(before), len(after)))
        root = QtCore.QModelIndex()
        if len(after) == len(before) + 1 \
                and after[:at] + after[at + 1:] == before:
            self.beginInsertRows(root, at + 1, at + 1)    # +1 for the All row
            self._held = None
            self.endInsertRows()
        elif len(after) == len(before) - 1 \
                and before[:at] + before[at + 1:] == after:
            self.beginRemoveRows(root, at + 1, at + 1)
            self._held = None
            self.endRemoveRows()
        else:
            self.beginResetModel()
            self._held = None
            self.endResetModel()

    def _favorites(self) -> list:
        return getattr(self.preferences, self.favorites_attr)


    def switch_model_data(self):
        """Re-point at whichever library is now live - the folders are read THROUGH to `prefs`, so the rows are already right and what was missing is the reset that repaints them. ▸p/folders-follow-the-library"""
        self.beginResetModel()
        try:
            self._out_of_date(self._known(), keep=False)    # another library's rules: no number carries over
            self._rows_key = None
            self._records_key = None
        finally:
            self.endResetModel()

    def refresh_counts(self) -> None:
        """Every count out of date, each shown until a fresh walk lands; the rows read again."""
        self._out_of_date(self._known())
        self._rows_key = None
        self._records_key = None

    def _known(self) -> set:
        return set(self._counts) | set(self._walking)

    def _out_of_date(self, paths, keep: bool = True) -> None:
        """Bump each location's token, so a walk still running for it lands and is dropped."""
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
        """Whether THIS registered folder scans recursively - the base answers no, and recursion is the location record's. ▸p/folder-sidebar"""
        return False

    def display_name(self, path: str) -> str:
        """The sidebar label for a registered folder - the basename here, custom-name-or-path in FileFolders."""
        return os.path.basename(path.rstrip("/\\")) or path

    def _matcher_for(self, path: str):
        """One folder's name test, its rule resolved ONCE here; it runs on the count's worker."""
        return lambda name: self.matches_in(path, name)

    def _folder_count(self, path: str):
        """The count known now, None before one lands; a stale one is walked off the GUI thread."""
        if self._counted.get(path) != self._tokens.get(path, 0):
            self._ask_count(path)
        return self._counts.get(path)

    def _ask_count(self, path: str) -> None:
        if path in self._walking:
            return    # ONE walk per location; a stale one asks again when it lands
        self._walking[path] = None
        self._queued.append(path)
        if not self._count_scheduled:
            self._count_scheduled = True
            self._counts_asked.emit()    # one paint's asks, one batch

    def _dispatch_counts(self) -> None:
        """Hand the queued locations to the free workers, every rule resolved HERE, on the GUI thread."""
        self._count_scheduled = False
        free = self.COUNT_WORKERS - self._live
        if free <= 0 or not self._queued:
            return    # a worker ending dispatches again
        queued, self._queued = self._queued, []
        registered = set(self._folders())
        jobs = []
        for path in queued:
            if path not in registered:
                self._walking.pop(path, None)    # removed before its walk began
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
            jobs.append((path, token) + rule)
        for chunk in (jobs[i::free] for i in range(free)):
            if chunk:
                self._live += 1
                counter.start(chunk, self._on_counted, self._walk_ended)

    def _on_counted(self, path, token, count) -> None:
        """A walk landed: kept and announced when still current, dropped and asked again when not."""
        if self._walking.get(path) == token:
            self._walking.pop(path)
        row = self.row_of(path)
        if row is None:
            return    # removed while it walked
        if token != self._tokens.get(path, 0):
            self._ask_count(path)    # changed while it walked: its answer is the old rule's
            return
        self._counts[path] = count
        self._counted[path] = token
        self._unannounced.add(path)
        if not self._walking:
            self._announce_counts()    # the last one in: say it now
        elif not self._announce_armed:
            self._announce_armed = True
            QtCore.QTimer.singleShot(self.ANNOUNCE_MS, self._announce_counts)

    def _announce_counts(self) -> None:
        """Every count landed since the last call, told in ONE pass, so the views repaint once."""
        self._announce_armed = False
        paths, self._unannounced = self._unannounced, set()
        rows = sorted(r for r in map(self.row_of, paths) if r is not None)
        for at in rows + [0] if rows else []:    # each row, then All, whose total moved
            index = self.index(at)
            self.dataChanged.emit(index, index, [self.COUNT_ROLE])

    def _walk_ended(self, worker) -> None:
        """A worker is done: what it left unanswered may be asked again, and a queue waiting moves."""
        self._live = max(0, self._live - 1)
        for path, token in worker.jobs():
            if path in self._walking and self._walking[path] == token:
                self._walking.pop(path)
        if self._queued and not self._count_scheduled:
            self._count_scheduled = True
            self._counts_asked.emit()

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
                counts = [self._folder_count(p) for p in self._folders()]    # asks, walks nothing here
                return None if None in counts else sum(counts)    # no partial total ▸p/folder-sidebar
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
        if row <= 0 or not row - 1 < len(self._folders()):
            return False
        path = self._folders()[row - 1]
        _before, after = self._answered(
            lambda: getattr(self.preferences, self.remove_folder_method)(path))
        return path not in after

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
        self._rows_key = None
        self._records_key = None
        self._out_of_date((old_path, new_path), keep=False)    # this location only; the rest still hold
        for at in (row, 0):
            index = self.index(at)
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
