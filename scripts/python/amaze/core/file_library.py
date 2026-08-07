"""Models for the File section - the merge of Images, Geometry and HIP.

One folder-pointer list, one files model, EVERY file in the chosen
folder. Each row carries a KIND - image, geometry, hip or other - and
keeps exactly the behaviour its own section had before the merge
(decided 2026-07-30 via the shared function sheet; recorded in
AmazeNotes/ROADMAP.md):

* **image** - thumbnails through the background convert pipeline,
  double-click / drag loads the file onto a node's file parameter.
* **geometry** - thumbnails rendered by Houdini in the blocking,
  ESC-interruptable main-thread pass, double-click imports in context.
* **hip** - thumbnails are hand-framed CAPTURES from the store under
  config_root (never rendered, never mtime-invalidated - see
  hip_library's module docstring for why both rules exist).
* **other** - any file Amaze does not recognise, shown with its OS icon
  (QFileIconProvider - verified to never come back empty) and exactly
  one action: Copy Path. Houdini often cannot open these; a path pasted
  into a parameter is the real workflow.

THE ENGINES STAY WHERE THEY WERE. This module composes
texture_library's convert pipeline, geo_library's render pass and
hip_library's capture store - it does not fork them. Every cache key
keeps its old shape (('tex', path, size), ('geo', path, cache_dir),
('hip', path, thumb_dir)) and tile-icon keys stay raw joined paths, so
nothing a user already generated is orphaned or re-rendered by the
merge.

Role numbering extends the folder-section convention (FormatRole..
FolderRole match TextureFiles/GeoFiles, OpenSceneRole matches HipFiles)
so the shared TextureFilterProxyModel, the drag code's PathRole lookup
and the AssetItemDelegate wiring carry over unchanged.

Hidden files (dotfiles) are skipped: a section that lists EVERYTHING
would otherwise fill with .DS_Store on the first macOS folder.
"""

from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import debug, folders, geo_library, hip_library
from amaze.core import grid_columns
from amaze.core import keyed_store, locations
from amaze.core import texture_library, thumbnails, tile_icons
from amaze.helpers import hostos

#: Row kinds, in the order kind_for() checks them. Values are readable
#: on purpose - they surface in menus, debug events and tests.
KIND_IMAGE = "image"
KIND_GEO = "geometry"
KIND_HIP = "hip"
KIND_OTHER = "other"


def kind_for(name: str) -> str:
    """Which per-type behaviour a filename gets. The three recognisers
    are the sections' own - one source for what counts as an image, a
    geometry file or a scene."""
    if hip_library.matched_extension(name):
        return KIND_HIP
    if texture_library.matched_extension(name):
        return KIND_IMAGE
    if geo_library.matched_extension(name):
        return KIND_GEO
    return KIND_OTHER


#: The variables a path may be written against, and the pref tokens
#: that choose one. "home" is the DEFAULT (decided 2026-07-31);
#: "absolute" writes the literal path. (An "auto" pick-the-most-
#: specific style existed for a day and was removed 2026-08-01: the
#: label explained nothing, and four plain choices beat five clever
#: ones. A stored "auto" maps to "home" in the prefs setter.)
PATH_STYLES = ("absolute", "hip", "job", "home")
_STYLE_VARS = {"hip": "$HIP", "job": "$JOB", "home": "$HOME"}


def houdini_path(path: str, style: str = "home") -> str:
    """A path written the way Houdini writes them - for Copy Path and
    the File section's location labels (the sheet: 'We should also
    start using Houdini file paths'). `style` is Preferences > Write
    Paths As: one specific variable, or "absolute". Falls back to the
    absolute path untouched when hou is not importable (plain-python
    tests) or the path does not live under the chosen variable."""
    path = hostos.canonical_path_key(path or "")
    if not path or style == "absolute":
        return path
    try:
        import hou
    except ImportError:
        return path
    var = _STYLE_VARS.get(style, "$HOME")
    try:
        expanded = hostos.canonical_path_key(hou.expandString(var))
    except Exception:                                    # noqa: BLE001
        return path
    if not expanded or expanded in ("/", "."):
        return path
    prefix = expanded.rstrip("/") + "/"
    if path.startswith(prefix):
        return var + "/" + path[len(prefix):]
    return path


def sweep_folder_cache(preferences, folder: str, remaining) -> int:
    """Delete the cached image+geometry thumbnails belonging to a
    REMOVED location (the confirmed 2026-07-31 decision) - the caches
    are derived data keyed by full path, so this is the one moment
    they can be dropped without a whole-cache clear, and without it a
    removed folder's thumbnails linger forever.

    Skips: paths still covered by any REMAINING registered folder
    (conservative prefix check - re-rendering costs more than a few
    stale files), cache dirs whose manifest is unreadable (never write
    blind over a manifest - the recorded refuse-over-overwrite gate),
    and hip captures entirely: hand-framed, not regenerable, durable
    by design under config_root.

    Returns how many cached thumbnails were deleted.
    """
    prefix = hostos.canonical_path_key(folder).rstrip("/") + "/"
    keep_prefixes = [
        hostos.canonical_path_key(r).rstrip("/") + "/"
        for r in remaining if r
    ]
    removed = 0
    root = hostos.cache_root()
    try:
        cache_dirs = sorted(os.listdir(root), key=str.lower)
    except OSError:
        return 0
    import hashlib
    import json as json_mod
    for name in cache_dirs:
        if not name.startswith(("texture_thumbnails_", "geo_thumbnails_")):
            continue
        cache_dir = os.path.join(root, name)
        manifest_path = os.path.join(cache_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json_mod.load(handle)
            if not isinstance(manifest, dict):
                raise ValueError("not a manifest")
        except (OSError, ValueError) as exc:
            debug.event("file", "sweep skipped an unreadable manifest",
                        dir=name, error=str(exc))
            continue
        doomed = [
            path for path in manifest
            if path.startswith(prefix)
            and not any(path.startswith(k) for k in keep_prefixes)
        ]
        if not doomed:
            continue
        for path in doomed:
            png = os.path.join(
                cache_dir,
                hashlib.sha1(path.encode("utf-8")).hexdigest() + ".png")
            try:
                if os.path.exists(png):
                    os.remove(png)
                removed += 1
            except OSError as exc:
                debug.event("file", "sweep could not remove", path=png,
                            error=str(exc))
            manifest.pop(path, None)
        try:
            hostos.write_json_atomic(manifest_path, manifest)
        except OSError as exc:
            debug.event("file", "sweep could not rewrite the manifest",
                        dir=name, error=str(exc))
    if removed:
        debug.event("file", "removed folder's cache swept",
                    folder=folder, thumbnails=removed)
    return removed


def shows_all_files(preferences, location: str) -> bool:
    """Whether one registered location shows its unknown files: the
    per-location Show All Files override when set, the global Show
    Unknown Files preference otherwise (2026-08-01)."""
    override = locations.record(preferences, location).get("show_all")
    if override is not None:
        return bool(override)
    return bool(getattr(preferences, "file_show_unknown", True))


class FileFolders(folders.FolderListModel):
    """The File section's registered-folder sidebar. Counts and lists
    EVERY visible file - this section's whole point is that a folder
    shows what is actually in it.

    Per-location state (all confirmed 2026-07-31): recursion is per
    folder (file_recursive_folders), the display name defaults to the
    PATH itself (Houdini-collapsed) and can be renamed
    (file_folder_names), removal sweeps the folder's cached
    thumbnails, and Locate Folder carries name + recursion along with
    the favourites the base already rewrites."""

    folders_attr = "file_folders"
    favorites_attr = "file_favorites"
    last_folder_attr = "last_file_folder"
    subfolders_attr = "file_include_subfolders"
    add_folder_method = "add_file_folder"
    remove_folder_method = "remove_file_folder"
    relocate_folder_method = "relocate_file_folder"

    def matches(self, filename: str) -> bool:
        """The flat contract, answered by the per-LOCATION rule.

        This used to be a second three-line body applying the GLOBAL
        `file_show_unknown` preference that the per-location Show All
        Files override replaced on 2026-08-01 - and it was unreachable,
        because _folder_count calls matches_in() and this class
        overrides that too. Unreachable and WRONG is the shape that
        bites the next consumer of the documented subclass contract: it
        would have got the pre-2026-08-01 answer, and a location with
        Show All Files off inside a session with the global preference
        on would count files the grid does not list - the sidebar
        number disagreeing with the tiles, which is the exact defect
        the per-location rule exists to prevent.

        One rule, one body: with no location to ask about, the global
        preference is the only answer available, which is what
        matches_in("") gives.
        """
        return self.matches_in("", filename)


    def matches_in(self, path: str, filename: str) -> bool:
        # Per-location Show All Files (2026-08-01): the count asks the
        # LOCATION's rule, so the sidebar number and the grid agree
        # per location, not just globally.
        if filename.startswith("."):
            return False
        if shows_all_files(self.preferences, path):
            return True
        return kind_for(filename) != KIND_OTHER

    def includes_subfolders(self, path: str) -> bool:
        return bool(locations.record(
            self.preferences, path).get("recursive"))

    def display_name(self, path: str) -> str:
        custom = locations.record(self.preferences, path).get("name")
        if custom:
            return custom
        style = getattr(self.preferences, "path_style", "home")
        return houdini_path(path, style).rstrip("/") or path

    def remove_folder(self, row: int) -> None:
        if row <= 0 or not row - 1 < len(self._folders()):
            return
        path = self._folders()[row - 1]
        super().remove_folder(row)
        # PER-LOCATION STATE DIES WITH THE POINTER - all of it, in one
        # call. This used to name two of the four surfaces by hand and
        # clear those; the colour and the Show All Files override were
        # left behind, so re-registering the same folder brought back an
        # amber sidebar row and a hidden-files setting the user had
        # never re-chosen, with nothing on screen having said either was
        # kept.
        keyed_store.retire_prefix(self.preferences, path)
        # ...and so do its cached thumbnails. COMMENTS AND TILE ICONS
        # GO TOO, since his 2026-08-03 "clear everything - favourites,
        # comments and icons": re-adding the folder is a clean slate
        # (ui-text.md ▸ File (folders) ▸ Remove). Hip captures are the
        # one exception, and sweep_folder_cache says why - hand-framed,
        # not regenerable. Which stores go is `survives_forget` on each
        # spec, said once and readable, rather than inferred from which
        # lines this method happens to contain.
        sweep_folder_cache(
            self.preferences, path, list(self._folders()))

    def _on_folder_relocated(self, old_path: str, new_path: str) -> None:
        """One announcement, no enumeration.

        This used to walk a hand-written tuple of three dicts plus one
        list - and it named neither notes.json nor icons.json, so a
        Locate Folder orphaned every comment and every tile icon still
        keyed by the old path. The caller names the prefix that moved;
        the engine walks its registry, and a store cannot fail to join
        a list it does not have to be added to.
        """
        keyed_store.relocate(self.preferences, old_path, new_path)


class FileFiles(grid_columns.GridColumnsMixin,
               QtCore.QAbstractTableModel):
    """All files inside the selected folder (or every registered folder
    in "All" mode), each behaving as its kind."""

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "FormatRole",
        "favorite": "FavoriteRole",
        "open": "OpenSceneRole",
        "comments": "NotesRole",
    }

    FormatRole = QtCore.Qt.ItemDataRole.UserRole + 1
    PathRole = QtCore.Qt.ItemDataRole.UserRole + 2
    FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 3
    FolderRole = QtCore.Qt.ItemDataRole.UserRole + 4
    #: True for the scene Houdini currently has open (hip rows only).
    OpenSceneRole = QtCore.Qt.ItemDataRole.UserRole + 5
    #: KIND_* string for the row - the per-type dispatch key for menus,
    #: double-click and drag.
    KindRole = QtCore.Qt.ItemDataRole.UserRole + 6
    #: Truthy when the delegate should crop this row's image to fill
    #: the tile (hip captures are viewport-shaped; letterboxing them
    #: wastes the tile).
    CropRole = QtCore.Qt.ItemDataRole.UserRole + 7
    #: Matches the library family's numbering (UserRole + 8 is the
    #: category colour on both families, + 10 is notes on both).
    NotesRole = QtCore.Qt.ItemDataRole.UserRole + 10
    #: The colour set on the LOCATION this row came from - the File
    #: section's answer to a category colour, painted as the same tile
    #: band. Deliberately UserRole + 8, matching MaterialLibrary's
    #: CategoryColorRole, so the one delegate reads one number.
    CategoryColorRole = QtCore.Qt.ItemDataRole.UserRole + 8

    #: (done, total) for the current folder's background image batch or
    #: geometry render pass - drives the thin bar above the grid.
    progress_changed = QtCore.Signal(int, int)

    def __init__(self, preferences, parent=None) -> None:
        super().__init__()
        self.preferences = preferences
        self._folder = ""
        self._all_folders_mode = False
        self._files: list = []          # (folder, filename) pairs
        self._kinds: list = []          # KIND_* per row, same order
        # Per-row engine spec: (key, source, payload). source is one of
        # "file" (valid cached PNG, lazy), "convert" (image pipeline),
        # "render" (geo pass), "capture" (hip store), "os-icon".
        self._row_specs: list = []
        self._key_rows: dict = {}
        self._image_cache = None
        self._geo_cache = None
        self._geo_cache_key = None
        self._pending_writes: dict = {}
        self._progress_keys: set = set()
        self._progress_done = 0
        self._progress_total = 0
        self._os_icons: dict = {}
        # Folder -> the owning location's colour band. THE PAINT PATH:
        # data(CategoryColorRole) runs per tile per repaint, and the
        # uncached shape deep-copied a location record per tile per
        # frame - and keyed it on the row's own directory, so every
        # subfolder row of a recursive location painted bandless.
        # Cleared on rescan and by colours_changed().
        self._colour_cache: dict = {}
        # Does this scene have a capture? Filled lazily on the first
        # paint of a row and kept, because the alternative is a stat
        # per visible scene row per FRAME - data(DecorationRole) is
        # what a repaint calls, and scroll, hover and resize are all
        # repaints. hip_library's own thumb_dir() memo closed the
        # DIRECTORY half of this same path for the same reason (its
        # note measures 10 thumb_path() calls at 20 makedirs + 40
        # isdir); this is the file half. Cheap on a warm local disk,
        # which is why it never showed - not cheap on a sleeping
        # external volume, and a registered File location is exactly
        # where one turns up (research.md > Volume mounts on macOS).
        # Same shape as folders.py's `_counts` and delegates.py's font
        # cache, so this stops being the odd one out.
        self._capture_seen: dict = {}
        # Through the RELAY, not the engine: the engine singleton is
        # replaced on every module reload, which would leave this model
        # wired to a dead one (see thumbnails._EngineSignals).
        thumbnails.signals.ready.connect(self._on_thumb_key_ready)
        thumbnails.signals.convert_attempted.connect(
            self._on_convert_attempted)
        # A capture from anywhere - the tile menu, the shelf tool -
        # repaints this model's row for that scene.
        hip_library.signals.captured.connect(self._on_capture_landed)

    # -- caches, one per engine ---------------------------------------

    def _get_image_cache(self):
        """The texture pipeline's cache, exact same prefix and keys -
        every thumbnail generated before the merge is still a hit."""
        size = self.preferences.rendersize
        if self._image_cache is None or self._image_cache.size != size:
            self._image_cache = texture_library.ThumbnailCache(size)
        return self._image_cache

    def _get_geo_cache(self):
        """Geo's size+shading+background-keyed cache, same prefix."""
        size = self.preferences.rendersize
        mode = getattr(
            self.preferences, "geometry_shading_mode", "hiddenlineghost")
        bg = getattr(self.preferences, "geometry_bg", "black")
        key = (size, mode, bg)
        if self._geo_cache is None or self._geo_cache_key != key:
            self._geo_cache = texture_library.ThumbnailCache(
                size, prefix="geo_thumbnails_%s_%s" % (mode, bg))
            self._geo_cache_key = key
        return self._geo_cache

    # -- listing ------------------------------------------------------

    def rowCount(self, parent=None) -> int:
        return len(self._files)

    def set_folder(self, path: str) -> None:
        self._all_folders_mode = False
        self._folder = path
        self._load([path] if path else [])

    def set_all_folders(self) -> None:
        self._all_folders_mode = True
        self._folder = ""
        self._load(list(self.preferences.file_folders))

    def refresh_current_folder(self) -> None:
        """Re-runs the current selection. Cheap when nothing changed -
        every item is still a cache hit."""
        if self._all_folders_mode:
            self.set_all_folders()
        elif self._folder:
            self.set_folder(self._folder)

    def _scan(self, folder: str) -> list:
        """[(containing_dir, name)] pairs - every visible file, flat by
        default, recursive when Include Subfolders is on. Files keep
        their CONTAINING dir so paths, cache keys and the Category
        column stay correct per subfolder."""
        results = []
        if not folder or not os.path.isdir(folder):
            return results
        if locations.record(self.preferences, folder).get("recursive"):
            for dirpath, dirnames, filenames in \
                    folders.walk_following_links(folder):
                # The skip-hidden rule applies to DIRECTORIES too:
                # without the prune, a project folder with recursion
                # on floods the grid with thousands of .git internals.
                dirnames[:] = [d for d in dirnames
                               if not d.startswith(".")]
                dirnames.sort(key=str.lower)
                for name in sorted(filenames, key=str.lower):
                    if not name.startswith("."):
                        results.append((dirpath, name))
        else:
            try:
                names = sorted(os.listdir(folder), key=str.lower)
            except OSError:
                return []
            for name in names:
                full = os.path.join(folder, name)
                if not name.startswith(".") and os.path.isfile(full):
                    results.append((folder, name))
        return results

    def _load(self, folder_list: list) -> None:
        """One scan, four behaviours. Image conversions queue in the
        background exactly as the Images section did; geometry misses
        render in the blocking interruptable pass exactly as Geometry
        did; hip and other rows cost nothing at load."""
        # FLUSH FIRST, then cancel: thumbnails generated before a
        # folder switch must reach the manifest or the folder
        # re-converts from scratch next visit (the Images lesson).
        self._flush_image_cache("folder switch")
        thumbnails.engine.cancel_pending_converts()
        image_cache = self._get_image_cache()
        geo_cache = self._get_geo_cache()

        self.beginResetModel()
        self._files = []
        self._kinds = []
        self._row_specs = []
        self._key_rows = {}
        self._pending_writes = {}
        self._progress_keys = set()
        self._colour_cache = {}
        # A rescan is the moment the disk is authoritative again, so
        # the remembered stats go with the rows they described.
        self._capture_seen = {}
        geo_misses = []

        entries = []
        for folder in folder_list:
            # Per-location Show All Files (2026-08-01): unknown files
            # are dropped at gather time, per the LOCATION they came
            # from - the "All" view can show one location's unknowns
            # and hide another's.
            keep_other = shows_all_files(self.preferences, folder)
            for dirpath, name in self._scan(folder):
                if not keep_other and kind_for(name) == KIND_OTHER:
                    continue
                entries.append((dirpath, name))

        # ONE reconcile pass per manifest for every directory at once.
        image_dirs: dict = {}
        geo_dirs: dict = {}
        for dirpath, name in entries:
            kind = kind_for(name)
            if kind == KIND_IMAGE:
                image_dirs.setdefault(dirpath, []).append(name)
            elif kind == KIND_GEO:
                geo_dirs.setdefault(dirpath, []).append(name)
        if image_dirs:
            image_cache.reconcile_many(image_dirs)
        if geo_dirs:
            geo_cache.reconcile_many(geo_dirs)

        convert_queued = False
        for dirpath, name in entries:
            kind = kind_for(name)
            row = len(self._files)
            self._files.append((dirpath, name))
            self._kinds.append(kind)
            full = hostos.canonical_path_key(os.path.join(dirpath, name))
            if kind == KIND_IMAGE:
                key = ("tex", full, image_cache.size)
                self._key_rows.setdefault(key, []).append(row)
                cached_png = image_cache.valid_path(full)
                if cached_png is not None:
                    self._row_specs.append((key, "file", cached_png))
                elif image_cache.known_failure(full):
                    # Already defeated every converter as it stands -
                    # re-queueing pays each adapter's timeout again on
                    # every visit. The row shows its placeholder;
                    # Rerender Thumbnail is the deliberate retry.
                    self._row_specs.append((key, "missing", full))
                else:
                    self._row_specs.append((key, "convert", full))
                    if not convert_queued:
                        # Options pushed once per batch, lazily - the
                        # hou import stays out of plain-python paths.
                        self._configure_engine_convert()
                        convert_queued = True
                    thumbnails.engine.discard(key)
                    thumbnails.engine.request_convert(
                        key, full, image_cache.size)
                    self._pending_writes[key] = full
                    self._progress_keys.add(key)
            elif kind == KIND_GEO:
                key = ("geo", full, geo_cache.cache_dir)
                self._key_rows.setdefault(key, []).append(row)
                cached_png = geo_cache.valid_path(full)
                if cached_png is not None:
                    self._row_specs.append((key, "file", cached_png))
                else:
                    self._row_specs.append((key, "render", full))
                    geo_misses.append((row, full))
            elif kind == KIND_HIP:
                key = ("hip", full, hip_library.thumb_dir())
                self._key_rows.setdefault(key, []).append(row)
                self._row_specs.append((key, "capture", full))
            else:
                self._row_specs.append(
                    (None, "os-icon", os.path.join(dirpath, name)))
        self.endResetModel()

        self._progress_done = 0
        # Distinct KEYS, not rows - duplicates share one conversion
        # (the progress-bar-stalls-forever lesson, texture_library).
        self._progress_total = len(self._progress_keys)
        self.progress_changed.emit(
            self._progress_done, self._progress_total)

        if geo_misses:
            self._render_geo_misses(geo_misses)

    # -- image pipeline (the Images section's, verbatim) --------------

    def _configure_engine_convert(self) -> None:
        import hou

        thumbnails.engine.configure_convert(
            hou.expandString("$HFS"),
            self.preferences.texture_parallel_conversions,
        )

    def _on_thumb_key_ready(self, key) -> None:
        """Engine delivery: repaint every row holding the key, and give
        a freshly GENERATED image its main-thread disk-cache write
        (the manifest is main-thread-only by design)."""
        rows = self._key_rows.get(key) or ()
        if not rows:
            return
        full_path = self._pending_writes.pop(key, None)
        if full_path is not None and self._image_cache is not None:
            image = thumbnails.engine.peek(key)
            if image is not None:
                self._image_cache.put(full_path, image)
        for row in rows:
            index = self.index(row, 0)
            self.row_changed(index.row(), [QtCore.Qt.ItemDataRole.DecorationRole])

    def _on_convert_attempted(self, key) -> None:
        """Advance the bar for every attempted item, success or failure;
        flush the manifest once the batch completes."""
        if key not in self._progress_keys:
            return
        self._progress_keys.discard(key)
        # An attempt that delivered no image is a FAILURE, and the one
        # place both outcomes are known - remembered so the next visit
        # skips it (texture_library.remember_failure says why).
        failed_path = self._pending_writes.pop(key, None)
        if (failed_path is not None and self._image_cache is not None
                and thumbnails.engine.peek(key) is None):
            self._image_cache.remember_failure(failed_path)
        self._progress_done += 1
        self.progress_changed.emit(
            self._progress_done, self._progress_total)
        if self._progress_done >= self._progress_total:
            self._flush_image_cache("batch complete")

    def _flush_image_cache(self, why: str) -> None:
        if self._image_cache is None:
            return
        try:
            self._image_cache.save()
        except Exception as exc:                         # noqa: BLE001
            debug.note("could not flush the image thumbnail cache "
                       "(%s)" % exc, why=why)

    def _folder_colour(self, folder: str) -> str:
        """The OWNING location's colour band for a row in `folder`.

        Resolved by PREFIX - a subfolder row belongs to the registered
        location above it, longest match wins; keying the lookup on the
        row's own directory painted every subfolder row of a recursive
        location bandless. Cached per FOLDER because this is the paint
        path: the uncached shape deep-copied a location record per tile
        per frame. Every input is in the key (the folder; the colour's
        own changes clear the cache via colours_changed and the
        rescan)."""
        generation = locations.generation()
        cached = self._colour_cache.get(folder)
        if cached is not None and cached[0] == generation:
            return cached[1]
        # The row's own directory first - the registered-location case,
        # and the one that must keep working on every prefs surface
        # (the unreachable-library fallback answers this read too).
        colour = str(locations.record(
            self.preferences, folder).get("color", ""))
        if not colour:
            key = hostos.canonical_path_key(folder)
            best = -1
            for registered in locations.paths(self.preferences):
                root = hostos.canonical_path_key(registered).rstrip("/")
                if (key == root or key.startswith(root + "/")) \
                        and len(root) > best:
                    best = len(root)
                    colour = str(locations.record(
                        self.preferences, registered).get("color", ""))
        self._colour_cache[folder] = (generation, colour)
        return colour

    def colours_changed(self) -> None:
        """A location's colour moved - drop the paint-path cache. The
        caller (the section's colour setter) emits the repaint."""
        self._colour_cache = {}

    def clear_cache(self) -> None:
        """Wipe the on-disk thumbnail caches (images AND geometry - one
        clear() sweeps both prefixes) and the in-memory copies. Hip
        captures are NOT touched: they are hand-framed and cannot be
        regenerated, which is why they live under config_root."""
        self._get_image_cache().clear()
        # The geo cache object too: clear() rmtrees the geo prefix on
        # disk, and the kept in-memory manifest went on describing
        # deleted PNGs, growing entries that could never hit again.
        self._geo_cache = None
        self._geo_cache_key = None
        thumbnails.engine.clear()

    # -- geo pipeline (the Geometry section's, verbatim) --------------

    def _render_geo_misses(self, misses: list) -> None:
        """Render missing geometry thumbnails NOW, on the main thread -
        blocking but ESC-interruptable; every finished file lands in
        the disk cache immediately so an interrupted pass resumes."""
        import hou
        from amaze.render import thumbs

        # A CACHE GETS NO THUMBNAIL UNASKED. Filtered HERE rather than
        # at the two places misses are collected, so there is one
        # answer and the progress dialog below cannot open for a list
        # that turns out to be entirely caches.
        #
        # Measured from the debug log, 2026-08-04: two filecache files
        # were re-cooked on EVERY switch to Files - 45 failure records
        # across 10 sessions, roughly 75 attempts, all
        # `no cookable geometry` - and each pass put a progress bar on
        # screen for work that could not succeed. Reported as the bar
        # flashing on entering the section.
        misses = [pair for pair in misses
                  if not geo_library.is_cache(pair[1])]
        if not misses:
            return
        cache = self._get_geo_cache()
        size = self.preferences.rendersize
        thumber = thumbs.ThumbNailRenderer(self.preferences)
        cache.ensure_dir()
        tmp_path = os.path.join(cache.cache_dir, "_render_tmp.png")
        total = len(misses)
        done = 0
        self.progress_changed.emit(0, total)
        try:
            with hou.InterruptableOperation(
                "Rendering geometry thumbnails",
                "Rendering geometry thumbnails",
                open_interrupt_dialog=True,
            ) as operation:
                for row, full in misses:
                    operation.updateProgress(done / total)
                    debug.event("file", "geo thumbnail",
                                i=done + 1, total=total, file=full)
                    ok = False
                    try:
                        ok = thumber.create_thumb_geo_file(
                            full, tmp_path, size)
                    except hou.OperationInterrupted:
                        raise
                    except Exception as exc:             # noqa: BLE001
                        debug.event("file", "geo thumbnail failed",
                                    file=full, error=str(exc))
                    if ok:
                        image = QtGui.QImage(tmp_path)
                        if not image.isNull():
                            cache.put(full, image)
                            thumbnails.engine.deposit(
                                ("geo", full, cache.cache_dir), image)
                    done += 1
                    self.progress_changed.emit(done, total)
                    # The pass blocks the event loop; pump paints only
                    # so finished tiles appear mid-pass without letting
                    # input re-enter the panel.
                    QtWidgets.QApplication.processEvents(
                        QtCore.QEventLoop.ProcessEventsFlag
                        .ExcludeUserInputEvents
                    )
        except hou.OperationInterrupted:
            debug.event("file", "geo pass interrupted",
                        done=done, total=total)
        finally:
            # ONE OWNER PER FOLDER OPEN. This pass emits into the same
            # signal the image-conversion batch uses, and its
            # processEvents above pumps that batch's own progress - so
            # a folder of 400 EXRs and 20 un-rendered geometry files
            # made the bar alternate between n/20 and n/400, and then
            # this terminal (0, 0) HID it while 380 conversions were
            # still running. It reappeared on the next attempted, so
            # the net effect was a flickering bar with the wrong
            # denominator - the only signal the user has that a long
            # conversion is still going.
            if not self._progress_keys:
                self.progress_changed.emit(0, 0)
            cache.save()
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    # -- hip capture relay (the HIP section's) ------------------------

    def _capture_png(self, hip_path: str) -> str:
        """This scene's capture PNG, or "" if it has none.

        The stat is remembered per scene (see `_capture_seen`): a
        repaint must not ask the filesystem a question this process
        already answered. `_on_capture_landed` forgets the one path a
        capture just changed, and a rescan forgets the lot, so the
        only way to a stale answer is deleting a PNG from under a
        running panel - which re-reads on the next folder visit.
        """
        seen = self._capture_seen.get(hip_path)
        if seen is None:
            png = hip_library.thumb_path(hip_path)
            seen = png if (png and os.path.isfile(png)) else ""
            self._capture_seen[hip_path] = seen
        return seen

    def _on_capture_landed(self, hip_path) -> None:
        path = str(hip_path or "")
        # Forget BEFORE the repaint: refresh_row paints, and painting
        # is what re-asks.
        self._capture_seen.pop(path, None)
        row = self.row_for_path(path)
        if row >= 0:
            self.refresh_row(row)

    def refresh_row(self, row: int) -> None:
        """Repaint one row after its capture was replaced - drops the
        engine's copy first or the old image keeps being served."""
        full = self._full_path(row)
        if full and 0 <= row < len(self._row_specs):
            key = self._row_specs[row][0]
            if key is not None:
                try:
                    thumbnails.engine.discard(key)
                except Exception as exc:                 # noqa: BLE001
                    debug.event("file", "could not drop cached image",
                                error=str(exc))
        if 0 <= row < len(self._files):
            index = self.index(row, 0)
            self.row_changed(index.row(), [QtCore.Qt.ItemDataRole.DecorationRole])

    def row_for_path(self, path: str) -> int:
        wanted = hostos.canonical_path_key(path or "")
        for row in range(len(self._files)):
            if self._full_path(row) == wanted:
                return row
        return -1

    # -- OS icons for unrecognised files ------------------------------

    def _os_icon_image(self, path: str):
        """The system's icon for this file type, drawn centred on a
        transparent square. Cached per extension - the provider is not
        free and a folder of logs is one icon repeated.

        Per the recorded probe: the provider can hand back SMALL icons,
        so the native pixmap is drawn at its own size (upscaled at most
        2x, never more) rather than stretched across the tile. NEVER
        empty: if the provider returns nothing paintable (measured
        headless), Qt's own generic file icon stands in - a tile with
        no picture at all reads as a loading failure."""
        ext = os.path.splitext(path)[1].lower()
        canvas_side = int(getattr(
            self.preferences, "rendersize", 512) or 512)
        cache_key = (ext, canvas_side)
        cached = self._os_icons.get(cache_key)
        if cached is not None:
            return cached
        provider = QtWidgets.QFileIconProvider()
        icon = provider.icon(QtCore.QFileInfo(path))
        target = canvas_side // 2
        pixmap = icon.pixmap(target, target)
        if pixmap.isNull():
            style = QtWidgets.QApplication.style()
            if style is not None:
                pixmap = style.standardIcon(
                    QtWidgets.QStyle.StandardPixmap.SP_FileIcon
                ).pixmap(target, target)
        image = QtGui.QImage(
            canvas_side, canvas_side,
            QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        if not pixmap.isNull():
            side = min(target, pixmap.width() * 2)
            painter = QtGui.QPainter(image)
            painter.setRenderHint(
                QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            offset = (canvas_side - side) // 2
            painter.drawPixmap(
                QtCore.QRect(offset, offset, side, side), pixmap)
            painter.end()
        self._os_icons[cache_key] = image
        return image

    # -- shared row plumbing ------------------------------------------

    def _full_path(self, row: int):
        if 0 <= row < len(self._files):
            folder, name = self._files[row]
            return hostos.canonical_path_key(os.path.join(folder, name))
        return None

    def kind(self, row: int) -> str:
        if 0 <= row < len(self._kinds):
            return self._kinds[row]
        return ""

    def toggle_favorite(self, row: int) -> None:
        full = self._full_path(row)
        if not full:
            return
        locations.set_favourite(
            self.preferences, full,
            not locations.is_favourite(self.preferences, full))
        index = self.index(row, 0)
        self.row_changed(index.row(), [self.FavoriteRole])

    def rerender_thumbnails(self, rows: list) -> None:
        """Force-regenerate rendered thumbnails: image rows re-convert,
        geometry rows re-render. Hip rows are SKIPPED - a capture is
        hand-framed, only a new capture replaces it - and other rows
        have nothing to render."""
        image_cache = self._get_image_cache()
        geo_cache = self._get_geo_cache()
        geo_misses = []
        queued = set()
        for row in rows:
            full = self._full_path(row)
            if not full or not 0 <= row < len(self._kinds):
                continue
            kind = self._kinds[row]
            if kind == KIND_IMAGE:
                if not queued:
                    self._configure_engine_convert()
                # flush=False: one write after the loop, not one per
                # row. 500 selected images meant 500 full manifest
                # serialisations with an fsync each, on the main
                # thread, before the progress bar even exists.
                image_cache.invalidate(full, flush=False)
                key = ("tex", full, image_cache.size)
                thumbnails.engine.discard(key)
                self._row_specs[row] = (key, "convert", full)
                thumbnails.engine.request_convert(
                    key, full, image_cache.size)
                self._pending_writes[key] = full
                self._progress_keys.add(key)
                queued.add(key)
            elif kind == KIND_GEO:
                geo_cache.invalidate(full, flush=False)
                key = ("geo", full, geo_cache.cache_dir)
                thumbnails.engine.discard(key)
                self._row_specs[row] = (key, "render", full)
                geo_misses.append((row, full))
            else:
                continue
            # The caches re-key on LIVE preferences (the prefs dialog
            # is non-modal), so a key built here can differ from the
            # one _load registered - without this, the delivery finds
            # no row, never writes the disk cache, and the tile keeps
            # the old picture.
            key_rows = self._key_rows.setdefault(key, [])
            if row not in key_rows:
                key_rows.append(row)
            index = self.index(row, 0)
            self.row_changed(index.row(), [QtCore.Qt.ItemDataRole.DecorationRole])
        # ONE flush for the whole selection, both caches. Their save()
        # is a no-op when nothing was dirtied.
        image_cache.save()
        geo_cache.save()
        if queued:
            # DISTINCT KEYS, not rows - the same lesson _load already
            # carries: duplicate rows share one conversion, and a
            # row-count total leaves the bar short forever and the
            # manifest flush gated behind it never runs. The total is
            # every key still pending, so an in-flight batch keeps a
            # consistent bar instead of a clobbered one.
            self._progress_done = 0
            self._progress_total = len(self._progress_keys)
            self.progress_changed.emit(
                self._progress_done, self._progress_total)
        if geo_misses:
            self._render_geo_misses(geo_misses)

    # -- tile icons (the folder-section contract, verbatim) -----------
    #
    # These rows are FILES, not library assets, so per-tile choices
    # live in the library's icons.json keyed by absolute path.
    #
    # The key is CANONICAL now (2026-08-06). It stayed the raw
    # os.path.join for a year of one reason - canonicalising would
    # orphan every icons.json entry written before the File merge - and
    # that reason was measured empty before this changed: icons.json
    # does not exist and notes.json holds no file keys, so there is
    # nothing to orphan and never was. The raw join was itself the
    # orphaner: locations are stored $AMAZE-relative and expandString
    # substitutes verbatim (research.md > Windows), so every key
    # carried the location's `..` spelling - re-register the same
    # folder absolute and every comment and icon under it went dark.
    # One spelling per file, whatever road named it.

    def file_key(self, row: int) -> str:
        if not 0 <= row < len(self._files):
            return ""
        folder, name = self._files[row]
        return hostos.canonical_path_key(os.path.join(folder, name))

    def tile_icon(self, row: int) -> dict:
        key = self.file_key(row)
        return tile_icons.override_for(self.preferences, key) if key else {}

    def tile_key(self, row: int) -> str:
        """A file row is keyed by its PATH - the same key its icon is
        stored under, and the one thing that survives a re-scan."""
        return self.file_key(row)

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        row = index.row() if hasattr(index, "row") else int(index)
        key = self.file_key(row)
        if not key:
            return False
        # Report what actually happened - a read-only library must not
        # take icons it will lose at restart.
        written = tile_icons.set_override(self.preferences, key, spec)
        model_index = self.index(row, 0)
        self.row_changed(model_index.row(), [QtCore.Qt.ItemDataRole.DecorationRole])
        return written

    def commit_tile_icons(self, rows=None) -> None:
        """Signature parity with the asset models; already persisted."""

    def _tile_icon_image(self, row: int):
        spec = tile_icons.normalise(self.tile_icon(row))
        if not spec:
            return None
        return tile_icons.compose(
            spec["name"], spec["bg"],
            int(getattr(self.preferences, "rendersize", 512) or 512),
            tile_icons.stroke_for(self.preferences),
            spec["ink"],
        )

    # -- data ---------------------------------------------------------

    def data(self, index, role: int = 0):
        # LATER COLUMNS are the table's, not the row's (step 1 of the
        # QTableView migration). Column 0 falls through unchanged, so
        # grid mode cannot tell any of this happened.
        if index.column() > 0:
            return self.column_data(index, role)
        if not index.isValid():
            return None
        row = index.row()
        # isValid() does not mean in-range: an index outlives a shrink.
        if not 0 <= row < len(self._files):
            return None
        folder, name = self._files[row]
        kind = self._kinds[row]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return name
        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            chosen = self._tile_icon_image(row)
            if chosen is not None:
                return chosen
            if not 0 <= row < len(self._row_specs):
                return None
            key, source, payload = self._row_specs[row]
            if source == "os-icon":
                return self._os_icon_image(payload)
            if source == "missing":
                # Remembered: nothing could read this file as it
                # stands, so the tile rests on its placeholder rather
                # than paying every converter's timeout again.
                return None
            if source == "file":
                return thumbnails.engine.request_file(key, payload)
            if source == "capture":
                png = self._capture_png(payload)
                if png:
                    image = thumbnails.engine.request_file(key, png)
                    if image is not None:
                        return image
                # No capture yet - the resting state, not a wait.
                return hip_library.placeholder_image()
            # convert / render rows: serve what has landed; after
            # eviction the disk cache takes over as a file load.
            image = thumbnails.engine.peek(key)
            if image is not None:
                return image
            if source == "convert":
                if not thumbnails.engine.is_pending(key) and not (
                    thumbnails.engine.is_missing(key)
                ):
                    cache = self._image_cache
                    cached_png = (
                        cache.valid_path(payload) if cache else None)
                    if cached_png is not None:
                        return thumbnails.engine.request_file(
                            key, cached_png)
                return None
            cached_png = self._get_geo_cache().valid_path(payload)
            if cached_png is not None:
                return thumbnails.engine.request_file(key, cached_png)
            return None
        if role == self.FormatRole:
            if kind == KIND_GEO:
                return geo_library.matched_extension(
                    name).lstrip(".").upper()
            if kind == KIND_HIP:
                # "Hiplc", not "HIPLC" - a scene extension is a word.
                return hip_library.matched_extension(
                    name).lstrip(".").capitalize()
            if kind == KIND_IMAGE:
                # Its own recogniser now, like the other two kinds. The
                # splitext fallback below is for KIND_OTHER, which by
                # definition has no list to match against.
                return texture_library.matched_extension(
                    name).lstrip(".").upper()
            return os.path.splitext(name)[1].lstrip(".").upper()
        if role in (self.PathRole, QtCore.Qt.ItemDataRole.ToolTipRole):
            return hostos.canonical_path_key(os.path.join(folder, name))
        if role == self.FavoriteRole:
            # A MEMBERSHIP TEST, per tile per repaint. `file_favorites`
            # composes the whole list out of the store now, so asking it
            # here would rebuild every star to answer about one.
            return locations.is_favourite(
                self.preferences,
                hostos.canonical_path_key(os.path.join(folder, name)))
        if role == self.FolderRole:
            return os.path.basename(folder.rstrip("/\\")) or folder
        if role == self.CategoryColorRole:
            return self._folder_colour(folder)
        if role == self.KindRole:
            return kind
        if role == self.CropRole:
            return kind == KIND_HIP
        if role == self.NotesRole:
            from amaze.core import notes
            return notes.has_note(
                self.preferences,
                notes.note_key("file", self.file_key(row)))
        if role == self.OpenSceneRole:
            if kind != KIND_HIP:
                return False
            return self._full_path(row) == hip_library.current_scene_path()
        return None
