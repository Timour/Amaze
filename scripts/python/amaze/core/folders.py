"""The ONE folder-pointer sidebar model behind every Folder-archetype
section (Textures, Geometry - see docs/architecture/overview.md).

A Folder section's sidebar is a flat list of registered folder paths
plus a synthetic "All" pseudo-entry pinned at row 0 (mirroring the
Materials category list's own "All"). These are pointers, not an index -
registering a folder scans or copies nothing. Subclasses only name the
preference attributes their section stores its list under and supply
the filename predicate; every behavior (counts caching, add/remove,
Locate Folder's relocate-with-favorite-rewrite) lives here once.
"""

from PySide6 import QtCore

import os

from amaze.core import category
from amaze.helpers import hostos



def walk_following_links(root: str):
    """os.walk that follows symlinked DIRECTORIES, each one once.

    Plain os.walk skips linked directories silently while still
    including linked FILES - inconsistent inside a single folder, and
    the sidebar count agrees with the omission, so nothing signals it.
    Studio texture and geometry trees are routinely assembled from
    symlinks, which made Include Subfolders quietly incomplete there.

    followlinks=True on its own can loop forever on a cycle
    (a/link -> a). The realpath set makes each PHYSICAL directory
    visited once, which is also what stops a diamond of links from
    listing the same files several times.

    Yields the same (dirpath, dirnames, filenames) triples as os.walk,
    and callers may still sort dirnames in place to steer the order.
    """
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
    """Generic registered-folders list. Subclass contract: set the
    *_attr/*_method names to the section's preference surface and
    implement matches(filename)."""

    PathRole = QtCore.Qt.ItemDataRole.UserRole
    ALL_LABEL = "All"
    # The ONE definition lives in category.py; imported so the sidebar
    # models can never drift apart.
    COUNT_ROLE = category.SIDEBAR_COUNT_ROLE

    #: Prefs attribute holding the folder list, e.g. "file_folders"
    folders_attr = ""
    #: Prefs attribute holding full-path favorites for this section
    favorites_attr = ""
    #: Prefs attribute remembering the last-selected folder
    last_folder_attr = ""
    #: Prefs attribute for the Include Subfolders toggle
    subfolders_attr = ""
    #: Prefs method names that add/remove a folder (and persist)
    add_folder_method = ""
    remove_folder_method = ""
    #: Prefs method that re-points one registered folder, IN ITS OWN
    #: ROW. Named rather than done by index assignment because a
    #: relocation must not reorder the sidebar, and because the accessor
    #: handing back the live list is an implementation detail this model
    #: must not rest on.
    relocate_folder_method = ""

    def __init__(self, preferences, parent: QtCore.QObject | None = None) -> None:
        super().__init__()
        self.preferences = preferences
        # Folder file-counts, cached so painting the sidebar never
        # touches the disk - cleared via refresh_counts() on section
        # activation, folder add/remove and subfolder-toggle changes.
        self._counts: dict = {}

    # -- subclass contract -------------------------------------------------

    def matches_in(self, path: str, filename: str) -> bool:
        """Folder-aware match - the base asks the flat rule; the File
        section overrides this to honour its per-location Show All
        Files setting (2026-08-01)."""
        return self.matches(filename)

    def matches(self, filename: str) -> bool:
        """Does this filename belong to the section (by extension)?"""
        raise NotImplementedError

    # -- prefs access through the contract ---------------------------------

    def _folders(self) -> list:
        return getattr(self.preferences, self.folders_attr)

    def _favorites(self) -> list:
        return getattr(self.preferences, self.favorites_attr)

    # -- counts ------------------------------------------------------------

    def refresh_counts(self) -> None:
        self._counts = {}

    def includes_subfolders(self, path: str) -> bool:
        """Whether THIS registered folder scans recursively. The base
        reads the section-wide flag; a subclass with per-location
        recursion overrides this (FileFolders)."""
        return bool(getattr(self.preferences, self.subfolders_attr, False))

    def display_name(self, path: str) -> str:
        """The sidebar label for a registered folder. Base: the
        basename. FileFolders overrides with custom-name-or-path."""
        return os.path.basename(path.rstrip("/\\")) or path

    def _folder_count(self, path: str) -> int:
        count = self._counts.get(path)
        if count is not None:
            return count
        count = 0
        try:
            if self.includes_subfolders(path):
                for _dirpath, dirnames, filenames in walk_following_links(path):
                    # Hidden directories are pruned like hidden files
                    # are skipped - a count that includes .git guts
                    # disagrees with the grid, which never lists them.
                    dirnames[:] = [d for d in dirnames
                                   if not d.startswith(".")]
                    dirnames.sort()
                    count += sum(1 for name in filenames
                                 if self.matches_in(path, name))
            else:
                # FILES only, matching the grid's flat scan: a
                # match-anything section (File) would otherwise count
                # subdirectories as entries and the sidebar number
                # would disagree with the tiles below it.
                count = sum(
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

    # -- Qt model ----------------------------------------------------------

    def rowCount(self, parent=None) -> int:
        return len(self._folders()) + 1

    def data(self, index, role: int = 0):
        if not index.isValid():
            return None
        row = index.row()
        if row == 0:
            # The "All" row has no real path - PathRole (and everything
            # else except the count) stays None, which callers use to
            # detect it.
            if role == QtCore.Qt.ItemDataRole.DisplayRole:
                return self.ALL_LABEL
            if role == self.COUNT_ROLE:
                # ONLY WHAT IS ALREADY COUNTED. `_counts` exists "so
                # painting the sidebar never touches the disk" (this
                # module's own docstring), but activate() and
                # prefs_changed() empty it - so this line forced a
                # recount of EVERY registered location on the very next
                # paint, and for a recursive one that is
                # walk_following_links: an os.path.realpath per
                # directory AND per child name, synchronously, inside
                # data(). Several studio texture trees with Show
                # Subfolders on meant clicking the File tab, or merely
                # closing Preferences, blocked Houdini for a full
                # recursive walk of all of them - regardless of which
                # location was actually selected, since the grid only
                # scans that one.
                #
                # The rows below fill `_counts` as they paint, so the
                # All row converges on the true total within a frame or
                # two of the sidebar being drawn, and never blocks the
                # first one.
                return sum(count for count in
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
            # The same role the asset sidebars answer, so the ONE
            # sidebar delegate paints a location's bar with no second
            # code path. "" (or no prefs) simply draws nothing.
            return self.folder_color(path)
        return None

    def row_of(self, path: str):
        """The sidebar row showing this registered folder, or None.

        Row 0 is the synthetic All entry, so a registered folder sits
        at its index in the list PLUS one - the same offset `data()`
        walks, kept in one place so a caller never re-derives it."""
        folders = self._folders()
        if path in folders:
            return folders.index(path) + 1
        return None

    def folder_color(self, path: str) -> str:
        """This location's colour, "" for none.

        Asked per ROW per repaint, so it reads the one record rather
        than the whole colour table: composing that table means walking
        every location, which inside data() is the sidebar paying
        O(locations) for every row it draws.
        """
        from amaze.core import locations
        return str(locations.record(self.preferences, path).get("color", ""))

    # -- mutation ----------------------------------------------------------

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
        # Row 0 is the synthetic "All" entry, not a real registered
        # folder - nothing to remove.
        if row <= 0 or not row - 1 < len(self._folders()):
            return
        self.beginRemoveRows(QtCore.QModelIndex(), row, row)
        path = self._folders()[row - 1]
        getattr(self.preferences, self.remove_folder_method)(path)
        self.endRemoveRows()
        self.refresh_counts()

    def relocate_folder(self, row: int, new_path: str) -> int:
        """Re-points the registered folder at ROW to NEW_PATH - for a
        folder that moved on disk, or one registered on another machine
        outside any shared tree. Everything keyed under the old path -
        favourites, comments, tile icons and the location's own record -
        follows the move, through the keyed store engine's one pass.
        Returns the number of favorites that moved, or -1 for an invalid
        row/path."""
        if row <= 0 or not row - 1 < len(self._folders()):
            return -1
        if not new_path or not os.path.isdir(new_path):
            return -1
        # CANONICAL FIRST, then the trailing separator. This appended a
        # POSIX "/" to whatever it was handed, which on Windows minted
        # the mixed spelling `C:\tex\wood/` and stored it as a folder
        # pointer and a location key. Every OS path convention belongs
        # in hostos (overview.md 4g), and its canonical form is
        # forward-slashed on all three - so this is one convention
        # rather than a second one that happens to agree on macOS.
        #
        # The trailing slash is the FOLDER-POINTER shape and stays: it
        # is what the prefix tests below and the cache manifest key on,
        # and texture_library records what it cost when the two forms
        # drifted.
        new_path = hostos.canonical_path_key(new_path)
        if not new_path.endswith("/"):
            new_path += "/"
        old_path = self._folders()[row - 1]
        if new_path == old_path:
            return 0
        # COUNTED HERE, REWRITTEN BY THE ENGINE. This used to rewrite the
        # favourites itself, into the live prefs list, and the engine's
        # own pass a few lines below then found nothing left under the
        # old prefix - a second copy of a sweep the keyed store engine
        # owns for every path-keyed store at once, kept alive only by the
        # number this function returns. Proved by sabotage: writing the
        # hand-rolled rewrite into a throwaway copy left the favourite
        # correctly moved anyway.
        old_prefix = old_path if old_path.endswith("/") else old_path + "/"
        rewritten = sum(1 for fav in self._favorites()
                        if fav.startswith(old_prefix))
        # THROUGH A NAMED CALL, never an index assignment into whatever
        # list the accessor happens to hand back. `self._folders()[row-1]
        # = new_path` is correct only while that accessor returns the one
        # live list, and it fails SILENTLY the moment it does not: a
        # Locate that reports success, logs the favourites it moved, and
        # leaves the pointer where it was.
        getattr(self.preferences, self.relocate_folder_method)(
            old_path, new_path)
        if getattr(self.preferences, self.last_folder_attr) == old_path:
            setattr(self.preferences, self.last_folder_attr, new_path)
        # Everything else keyed on the old path rides along - the
        # subclass knows what it keeps per location (names, recursion).
        self._on_folder_relocated(old_path, new_path)
        self.preferences.save()
        index = self.index(row)
        self.dataChanged.emit(index, index)
        self.refresh_counts()
        return rewritten
