"""Models for the File section - the merge of Images, Geometry and HIP: one folder-pointer list, one files model, EVERY file in the chosen folder, each row carrying a KIND that decides its behaviour (image: background convert pipeline; geometry: blocking ESC-interruptable main-thread render; hip: hand-framed captures under config_root, never rendered, never mtime-invalidated; other: OS icon, Copy Path). This module COMPOSES texture_library, geo_library and scene_captures, never forks them. Keep every cache key's existing shape (`('tex', path, size)`, `('geo', path, cache_dir)`, `('hip', path, thumb_dir)`) and keep file keys CANONICAL - one spelling per file - or a user's generated thumbnails, comments and icons orphan. Dotfiles are skipped, or the list fills with `.DS_Store`."""

from __future__ import annotations

import os
import stat

from PySide6 import QtCore, QtGui

from amaze.core import captures, debug, folders, geo_library, scene_files
from amaze.core import grid_engine
from amaze.core import keyed_store, locations
from amaze.core import texture_library, thumbnails, tile_icons
from amaze.helpers import hostos


def kind_for(name: str) -> str:
    """Which per-type behaviour a filename gets - the three recognisers are the sections' own: one source for what counts as an image, a geometry file or a scene."""
    if scene_files.matched_extension(name):
        return locations.KIND_HIP
    if texture_library.matched_extension(name):
        return locations.KIND_IMAGE
    if geo_library.matched_extension(name):
        return locations.KIND_GEO
    return locations.KIND_OTHER


def _stat_once(known: dict):
    """An `os.stat` that asks the disk once per path, `known` holding the answers; a gone file raises."""
    def stat_of(path):
        if path not in known:
            try:
                known[path] = os.stat(path)
            except OSError:
                known[path] = None
        if known[path] is None:
            raise FileNotFoundError(path)
        return known[path]
    return stat_of


GEO_FAILURE_TAG = "png-scratch"  # untagged failures came from a scratch Qt could not read; retried once


def sweep_folder_cache(preferences, folder: str, remaining) -> int:
    """Delete the cached image+geometry thumbnails belonging to a REMOVED location - the caches are derived data keyed by full path, so this is the one moment they can be dropped without a whole-cache clear, and without it a removed folder's thumbnails linger forever. Skips: paths still covered by any REMAINING registered folder (conservative prefix check - re-rendering costs more than a few stale files), cache dirs whose manifest is unreadable (never write blind over a manifest), and hip captures entirely (hand-framed, not regenerable, durable by design under config_root). Returns how many cached thumbnails were deleted."""
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
    import json as json_mod
    for name in cache_dirs:
        if not name.startswith(("texture_thumbnails_", "geo_thumbnails_")):
            continue
        cache_dir = os.path.join(root, name)
        manifest_path = os.path.join(cache_dir, "manifest.json")
        on_disk = os.path.isfile(manifest_path)
        manifest = {}
        try:
            if on_disk:
                with open(manifest_path, encoding="utf-8") as handle:
                    manifest = json_mod.load(handle)
            if not isinstance(manifest, dict):
                raise ValueError("not a manifest")
        except (OSError, ValueError) as exc:
            debug.event("file", "sweep skipped an unreadable manifest",
                        dir=name, error=str(exc))
            continue
        live = texture_library.live_caches(cache_dir)    # a grid's own cache would save them back
        held = set(manifest)
        for cache in live:
            held.update(cache.paths())
        doomed = sorted(
            path for path in held
            if path.startswith(prefix)
            and not any(path.startswith(k) for k in keep_prefixes)
        )
        if not doomed:
            continue
        for path in doomed:
            png = os.path.join(
                cache_dir,
                texture_library.ThumbnailCache._cache_filename(path))    # the cache's OWN naming - a hand-rolled hash here would stop matching silently if the scheme moved, and the sweep would delete nothing while claiming success
            try:
                if os.path.exists(png):
                    os.remove(png)
                removed += 1
            except OSError as exc:
                debug.event("file", "sweep could not remove", path=png,
                            error=str(exc))
            manifest.pop(path, None)
        try:
            if on_disk:
                hostos.write_json_atomic(manifest_path, manifest)
        except OSError as exc:
            debug.event("file", "sweep could not rewrite the manifest",
                        dir=name, error=str(exc))
        for cache in live:
            cache.forget(doomed)
    if removed:
        debug.event("file", "removed folder's cache swept",
                    folder=folder, thumbnails=removed)
    return removed


def shows_all_files(preferences, location: str) -> bool:
    """The rule before Show ▸: the location's Show All Files override, else `file_show_unknown`."""
    override = locations.record(preferences, location).get("show_all")
    if override is not None:
        return bool(override)
    return bool(getattr(preferences, "file_show_unknown", True))


def location_kinds(preferences, location: str) -> frozenset:
    """The kinds one location lists: its Show ▸ ticks, else what it listed before Show ▸ existed."""
    kinds = locations.record(preferences, location).get("kinds")
    if kinds is not None:
        return frozenset(kinds)
    shown = set(locations.SHOWN_BY_DEFAULT)
    if shows_all_files(preferences, location):
        shown.add(locations.KIND_OTHER)
    return frozenset(shown)


class FileFolders(folders.FolderTreeModel):
    """The File section's sidebar: each location, and each subfolder, counts by its location's ticks."""

    folders_attr = "file_folders"
    favorites_attr = "file_favorites"
    last_folder_attr = "last_file_folder"
    add_folder_method = "add_file_folder"
    remove_folder_method = "remove_file_folder"
    relocate_folder_method = "relocate_file_folder"
    move_folder_method = "move_file_folder"
    write_path = None    # Write Paths As, which needs Houdini: the panel hands it in, else the path

    def matches(self, filename: str) -> bool:
        """The flat contract, answered by the per-LOCATION rule. It used to be a second three-line body applying the global `file_show_unknown` preference the per-location override replaced - unreachable (this class overrides matches_in, which _folder_count calls) and WRONG, the shape that bites the next consumer of the documented subclass contract: the sidebar number disagreeing with the tiles is the exact defect the per-location rule exists to prevent. One rule, one body: with no location to ask about, the global preference is the only answer available, which is what an empty-path matches_in gives."""
        return self.matches_in("", filename)


    def matches_in(self, path: str, filename: str) -> bool:  # the count asks the LOCATION's rule, so the sidebar number and the grid agree per location, not just globally
        if filename.startswith("."):
            return False
        return kind_for(filename) in location_kinds(self.preferences, self.location_of(path))

    def _matcher_for(self, path: str):
        kinds = location_kinds(self.preferences, self.location_of(path))    # once per folder
        return lambda name: not name.startswith(".") and kind_for(name) in kinds

    def includes_subfolders(self, path: str) -> bool:
        return bool(self._record(self.location_of(path)).get("recursive"))

    def display_name(self, path: str) -> str:
        """The full path when Pathname is ticked, over any rename; then the rename; else the folder name."""
        record = self._record(path)
        if record.get("pathname"):    # written the way Write Paths As writes paths
            style = getattr(self.preferences, "path_style", "home")
            return (self.write_path(path, style) if self.write_path is not None
                    else hostos.canonical_path_key(path))
        if record.get("name"):
            return record["name"]
        return os.path.basename(path.rstrip("/\\")) or path

    def remove_folder(self, row: int) -> bool:
        if row <= 0 or not row - 1 < len(self._folders()):
            return False
        path = self._folders()[row - 1]
        if not super().remove_folder(row):
            return False    # a refused removal keeps the pointer, so every key under it stays
        if not locations.rehome_covered(self.preferences, path):
            return True    # a refused move retires nothing, so no file a remaining location lists loses a key
        keyed_store.retire_prefix(self.preferences, path)    # what is still keyed under it, every user's, then its id row
        locations.touch()    # the engine edited the identity table outside the module's own doors
        sweep_folder_cache(    # its cached thumbnails, bar what a remaining location covers; captures stay
            self.preferences, path, list(self._folders()))
        return True

    def _on_folder_relocated(self, old_path: str, new_path: str) -> None:
        """The legacy belt: id-keyed state does not move at all (the identity row's path edit already carried it), and this sweep re-homes only path-keyed stragglers an older build wrote - the engine walks its registry, so a store cannot fail to join."""
        keyed_store.relocate(self.preferences, old_path, new_path)


class FileFiles(grid_engine.GridEngine,
               QtCore.QAbstractTableModel):
    """All files inside the selected folder (or every registered folder in All mode), each behaving as its kind."""

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "FormatRole",
        "favorite": "FavoriteRole",
        "open": "OpenSceneRole",
        "comments": "NotesRole",
    }
    GRID_ROWS = ("_files", "_kinds", "_row_specs")

    FormatRole = QtCore.Qt.ItemDataRole.UserRole + 1
    PathRole = QtCore.Qt.ItemDataRole.UserRole + 2
    FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 3
    FolderRole = QtCore.Qt.ItemDataRole.UserRole + 4
    OpenSceneRole = QtCore.Qt.ItemDataRole.UserRole + 5  # True for the scene Houdini currently has open (hip rows only)
    KindRole = QtCore.Qt.ItemDataRole.UserRole + 6  # KIND_* string for the row - the per-type dispatch key for menus, double-click and drag
    CropRole = QtCore.Qt.ItemDataRole.UserRole + 7  # crop this row's image to fill the tile - hip captures are viewport-shaped, letterboxing wastes the tile
    NotesRole = QtCore.Qt.ItemDataRole.UserRole + 10  # matches the library family's numbering (+8 is the category colour on both families, +10 notes on both)
    CategoryColorRole = QtCore.Qt.ItemDataRole.UserRole + 8  # the owning LOCATION's colour, painted as the same tile band - deliberately +8, matching MaterialLibrary's CategoryColorRole, so the one delegate reads one number

    progress_changed = QtCore.Signal(int, int)  # (done, total) for the current folder's background image batch or geometry render pass - drives the thin bar above the grid

    def __init__(self, preferences, parent=None) -> None:
        super().__init__()
        self.preferences = preferences
        self._folder = ""
        self._all_folders_mode = False
        self._files: list = []          # (folder, filename) pairs
        self._kinds: list = []          # KIND_* per row, same order
        self._file_key_cache: dict = {}  # full path -> its store key, filled per row per load - the ident lookup walks the identity table, and the paint path must not
        self._file_key_generation = -1   # the locations generation the cache was built against - a register or Locate moves it, and stale idents must not outlive the boundary that minted them
        self._row_specs: list = []      # per-row engine spec (key, source, payload); source is one of file (valid cached PNG, lazy), convert (image pipeline), render (geo pass), capture (hip store), os-icon
        self._key_rows: dict = {}
        self._image_cache = None
        self._image_cache_key = None
        self._geo_cache = None
        self._geo_cache_key = None
        self._pending_writes: dict = {}
        self._unreadable_folders: set = set()  # registered folders that could not be READ this scan, so the empty state has a fact to speak from rather than teaching an offline archive as an empty one
        self._progress_keys: set = set()
        self._progress_done = 0
        self._progress_total = 0
        self._os_icons: dict = {}
        self.hfs = os.environ.get("HFS", "")    # Houdini's install, for the converter; the panel hands in $HFS
        self.open_scene = lambda: ""    # the scene Houdini has open; the panel hands in the live answer
        self.render_geo = None    # the geometry render pass; the panel hands it in, a bare model renders none
        self.os_icon = None    # the system's file icons; the panel hands them in, a bare model draws none
        self._colour_cache: dict = {}  # folder -> the owning location's colour band; THE PAINT PATH - the uncached shape deep-copied a location record per tile per frame and keyed on the row's own directory, painting recursive subfolder rows bandless; cleared on rescan and by colours_changed()
        thumbnails.signals.ready.connect(self._on_thumb_key_ready)  # through the RELAY, not the engine: the singleton is replaced on every module reload, which would leave this model wired to a dead one (thumbnails._EngineSignals)
        thumbnails.signals.convert_attempted.connect(
            self._on_convert_attempted)
        captures.signals.landed.connect(self._on_capture_landed)    # from any panel or the shelf

    def _get_image_cache(self):
        """The texture pipeline's cache, exact same prefix and keys - every thumbnail generated before the merge is still a hit. Keyed on the cache GENERATION as well as the size: `ThumbnailCache.__init__` resolves the root once and then holds its disk state, so changing the cache location left every cache built beforehand writing to the old root; `set_cache_override` bumps the counter, and scene_captures has always keyed on it."""
        key = (self.preferences.rendersize, hostos.cache_generation())
        if self._image_cache is None or self._image_cache_key != key:
            self._image_cache = texture_library.ThumbnailCache(key[0])
            self._image_cache_key = key
        return self._image_cache

    def _get_geo_cache(self):
        """Geo's size+shading+background-keyed cache, same prefix."""
        size = self.preferences.rendersize
        mode = getattr(
            self.preferences, "geometry_shading_mode", "hiddenlineghost")
        bg = getattr(self.preferences, "geometry_bg", "black")
        key = (size, mode, bg, hostos.cache_generation())
        if self._geo_cache is None or self._geo_cache_key != key:
            self._geo_cache = texture_library.ThumbnailCache(
                size, prefix="geo_thumbnails_%s_%s" % (mode, bg),
                failure_tag=GEO_FAILURE_TAG)
            self._geo_cache_key = key
        return self._geo_cache

    def rowCount(self, parent=None) -> int:
        return len(self._files)

    def rows_reordered(self) -> None:
        self._key_rows = {}    # engine key -> its rows, read off each row's spec
        for row, spec in enumerate(self._row_specs):
            if spec[0] is not None:
                self._key_rows.setdefault(spec[0], []).append(row)

    def set_folder(self, path: str) -> None:
        self._all_folders_mode = False
        self._folder = path
        self._load([path] if path else [])

    def set_all_folders(self) -> None:
        self._all_folders_mode = True
        self._folder = ""
        self._load(list(self.preferences.file_folders))

    def browsing(self) -> str:
        """The location this model lists, "" for every location (All)."""
        return "" if self._all_folders_mode else self._folder

    def refresh_current_folder(self) -> None:
        """Re-runs the current selection - cheap when nothing changed, every item is still a cache hit."""
        if self._all_folders_mode:
            self.set_all_folders()
        elif self._folder:
            self.set_folder(self._folder)

    def _scan(self, folder: str) -> list:
        """(containing dir, name, stat or None) per visible file; a flat scan keeps the stat it made."""
        results = []
        if not folder or not os.path.isdir(folder):
            if folder:  # an UNREACHABLE folder is not an empty one: an unmounted share looks exactly like isdir() saying no, and the nothing-here-yet state then teaches the wrong thing about an archive that is merely offline - recorded so the state has a fact behind it
                self._unreadable_folders.add(folder)
                debug.event("file", "a registered folder could not be "
                            "read", folder=folder, reason="not there")
            return results
        self._unreadable_folders.discard(folder)
        owner = locations.owner_of(self.preferences, folder) or folder    # a subfolder: its location's tick
        if locations.record(self.preferences, owner).get("recursive"):
            for dirpath, dirnames, filenames in \
                    folders.walk_following_links(folder):
                dirnames[:] = [d for d in dirnames  # the skip-hidden rule applies to DIRECTORIES too: without the prune, recursion floods the grid with thousands of .git internals
                               if not d.startswith(".")]
                dirnames.sort(key=str.lower)
                for name in sorted(filenames, key=str.lower):
                    if not name.startswith("."):
                        results.append((dirpath, name, None))
        else:
            try:
                names = sorted(os.listdir(folder), key=str.lower)
            except OSError as exc:  # present but unreadable - a permissions change, a share dropped mid-session; same rule as above, say so rather than showing an empty folder
                self._unreadable_folders.add(folder)
                debug.event("file", "a registered folder could not be "
                            "read", folder=folder, error=str(exc))
                return []
            for name in names:
                if name.startswith("."):
                    continue
                try:
                    st = os.stat(os.path.join(folder, name))
                except (OSError, ValueError):
                    continue
                if stat.S_ISREG(st.st_mode):    # `os.path.isfile`, keeping the stat it made
                    results.append((folder, name, st))
        return results

    def _load(self, folder_list: list) -> None:
        """One scan, four behaviours: image conversions queue in the background exactly as the Images section did, geometry misses render in the blocking interruptable pass exactly as Geometry did, hip and other rows cost nothing at load."""
        self.cancel_conversions("folder switch")
        image_cache = self._get_image_cache()
        geo_cache = self._get_geo_cache()

        self.beginResetModel()
        self._files = []
        self._file_key_cache = {}
        self._kinds = []
        self._row_specs = []
        self._key_rows = {}
        self._pending_writes = {}
        self._progress_keys = set()
        self._colour_cache = {}
        geo_misses = []

        entries = []
        known: dict = {}    # canonical path -> the one stat this load makes of it
        for folder in folder_list:
            owner = locations.owner_of(self.preferences, folder) or folder
            kinds = location_kinds(self.preferences, owner)    # per the location a file came from
            for dirpath, name, st in self._scan(folder):
                kind = kind_for(name)
                if kind not in kinds:
                    continue
                full = hostos.canonical_path_key(os.path.join(dirpath, name))
                if st is not None:
                    known[full] = st
                entries.append((dirpath, name, kind, full))
        stat_of = _stat_once(known)

        image_dirs: dict = {}  # ONE reconcile pass per manifest for every directory at once
        geo_dirs: dict = {}
        for dirpath, name, kind, _full in entries:
            if kind == locations.KIND_IMAGE:
                image_dirs.setdefault(dirpath, []).append(name)
            elif kind == locations.KIND_GEO:
                geo_dirs.setdefault(dirpath, []).append(name)
        if image_dirs:
            image_cache.reconcile_many(image_dirs, stat=stat_of)
        if geo_dirs:
            geo_cache.reconcile_many(geo_dirs, stat=stat_of)

        convert_queued = False
        for dirpath, name, kind, full in entries:
            row = len(self._files)
            self._files.append((dirpath, name))
            self._kinds.append(kind)
            if kind == locations.KIND_IMAGE:
                key = ("tex", full, image_cache.size)  # NO staleness in the key: every requester discards first (here and rerender_thumbnails), and a third caller must do the same or put the mtime into the key
                self._key_rows.setdefault(key, []).append(row)
                cached_png = image_cache.valid_path(full, stat=stat_of)
                if cached_png is not None:
                    self._row_specs.append((key, "file", cached_png))
                elif image_cache.known_failure(full, stat=stat_of):
                    self._row_specs.append((key, "missing", full))  # already defeated every converter as it stands - re-queueing pays each adapter's timeout again on every visit; Rerender Thumbnail is the deliberate retry
                else:
                    self._row_specs.append((key, "convert", full))
                    if not convert_queued:
                        self._configure_engine_convert()  # options pushed once per batch, lazily
                        convert_queued = True
                    thumbnails.engine.discard(key)
                    thumbnails.engine.request_convert(
                        key, full, image_cache.size)
                    self._pending_writes[key] = full
                    self._progress_keys.add(key)
            elif kind == locations.KIND_GEO:
                key = ("geo", full, geo_cache.cache_dir)  # same discard-first contract as the tex key above
                self._key_rows.setdefault(key, []).append(row)
                cached_png = geo_cache.valid_path(full, stat=stat_of)
                if cached_png is not None:
                    self._row_specs.append((key, "file", cached_png))
                elif geo_cache.known_failure(full, stat=stat_of):
                    self._row_specs.append((key, "missing", full))    # rendered nothing as it stands
                else:
                    self._row_specs.append((key, "render", full))
                    geo_misses.append((row, full))
            elif kind == locations.KIND_HIP:
                self._row_specs.append((None, "none", full))    # no render: its picture is a capture
            else:
                self._row_specs.append(
                    (None, "os-icon", os.path.join(dirpath, name)))
        moved = self.order_rows()    # in the grid's order before any view sees them
        if moved:
            geo_misses = [(moved[row], full) for row, full in geo_misses]
        self.endResetModel()

        self._progress_done = 0
        self._progress_total = len(self._progress_keys)  # distinct KEYS, not rows - duplicates share one conversion (the progress-bar-stalls-forever lesson, texture_library)
        self.progress_changed.emit(
            self._progress_done, self._progress_total)

        if geo_misses and self.render_geo is not None:
            self.render_geo(geo_misses)

    def _configure_engine_convert(self) -> None:
        thumbnails.engine.configure_convert(
            self.hfs,
            self.preferences.texture_parallel_conversions,
        )

    def _on_thumb_key_ready(self, key) -> None:
        """Engine delivery: repaint every row holding the key, and give a freshly GENERATED image its main-thread disk-cache write (the manifest is main-thread-only by design)."""
        rows = self._key_rows.get(key) or ()
        if not rows:
            return
        full_path = self._pending_writes.pop(key, None)
        if full_path is not None and self._image_cache is not None:
            image = thumbnails.engine.peek(key)
            queued_size = key[2] if len(key) > 2 else None  # filed at the size it was made at, or not at all: Preferences is non-modal, so RenderSize can change mid-batch and late deliveries were written into the NEW size's manifest - small images served as large ones across restarts; the row still repaints below, only the durable copy would be mislabelled
            if image is not None and queued_size == self.preferences.rendersize:
                self._image_cache.put(full_path, image)
            elif image is not None:
                debug.event("file", "converted image not cached - the "
                                    "size changed while it was in flight",
                            queued=queued_size,
                            now=self.preferences.rendersize)
        for row in rows:
            index = self.index(row, 0)
            self.row_changed(index.row(), [QtCore.Qt.ItemDataRole.DecorationRole])

    def _on_convert_attempted(self, key) -> None:
        """Advance the bar for every attempted item, success or failure; flush the manifest once the batch completes."""
        if key not in self._progress_keys:
            return
        self._progress_keys.discard(key)
        failed_path = self._pending_writes.pop(key, None)  # an attempt that delivered no image is a FAILURE, and this is the one place both outcomes are known - remembered so the next visit skips it (texture_library.remember_failure says why)
        if (failed_path is not None and self._image_cache is not None
                and thumbnails.engine.peek(key) is None):
            self._image_cache.remember_failure(failed_path)
        self._progress_done += 1
        self.progress_changed.emit(
            self._progress_done, self._progress_total)
        if self._progress_done >= self._progress_total:
            self._flush_image_cache("batch complete")

    def cancel_conversions(self, why: str = "cancelled") -> None:
        """Abandon the running image batch: the panel Cancel chip's verb, and the first thing a folder switch does. FLUSH FIRST, then cancel - thumbnails already generated must reach the manifest or the folder re-converts from scratch next visit. Then the batch is SETTLED: cancelled attempts never report, so the bar is driven to complete rather than left waiting for them. `_pending_writes` stays - a conversion finishing during the cancel still gets its durable write."""
        self._flush_image_cache(why)
        thumbnails.engine.cancel_pending_converts()
        self._progress_keys = set()
        self._progress_done = self._progress_total
        self.progress_changed.emit(
            self._progress_done, self._progress_total)

    def _flush_image_cache(self, why: str) -> None:
        if self._image_cache is None:
            return
        try:
            self._image_cache.save()
        except Exception as exc:                         # noqa: BLE001
            debug.note("could not flush the image thumbnail cache "
                       "(%s)" % exc, why=why)

    def _folder_colour(self, folder: str) -> str:
        """The OWNING location's colour band for a row in `folder`, resolved by PREFIX - a subfolder row belongs to the registered location above it, longest match wins; keying on the row's own directory painted every subfolder row of a recursive location bandless. Cached per FOLDER because this is the paint path, and every input is in the key."""
        generation = locations.generation()
        cached = self._colour_cache.get(folder)
        if cached is not None and cached[0] == generation:
            return cached[1]
        colour = str(locations.record(    # the row's own directory first: a location itself
            self.preferences, folder).get("color", ""))
        if not colour:
            owner = locations.innermost(locations.paths(self.preferences), folder)
            if owner:
                colour = str(locations.record(self.preferences, owner).get("color", ""))
        self._colour_cache[folder] = (generation, colour)
        return colour

    def colours_changed(self) -> None:
        """A location's colour moved - drop the paint-path cache; the caller (the section's colour setter) emits the repaint."""
        self._colour_cache = {}

    def clear_cache(self) -> None:
        """Wipe the on-disk thumbnail caches (images AND geometry - one clear() sweeps both prefixes) and the in-memory copies; hip captures are NOT touched - hand-framed, not regenerable, which is why they live under config_root."""
        self._get_image_cache().clear()
        self._geo_cache = None  # the object too: clear() rmtrees the geo prefix on disk, and a kept in-memory manifest went on describing deleted PNGs, growing entries that could never hit again
        self._geo_cache_key = None
        thumbnails.engine.clear()

    def capture_path(self, row: int) -> str:
        """Where this row's capture lives in the library; "" for a row that does not exist."""
        key = self.file_key(row) if 0 <= row < len(self._files) else ""
        return captures.file_path(self.preferences, key) if key else ""

    def has_capture(self, row: int) -> bool:
        return captures.exists(self.capture_path(row))

    def capture_image(self, row: int):
        """The row's capture, read now for the Customize preview; None where there is none."""
        path = self.capture_path(row)
        image = QtGui.QImage(path) if captures.exists(path) else QtGui.QImage()
        return None if image.isNull() else image

    def _capture_tile_image(self, row: int):
        """The tile's capture through the engine, its row registered for the delivery."""
        path = self.capture_path(row)
        key = ("capture", path)
        rows = self._key_rows.setdefault(key, [])
        if row not in rows:
            rows.append(row)
        image = thumbnails.engine.request_file(key, path) if path else None
        if image is not None:
            return image
        if not path or thumbnails.engine.is_missing(key):
            return tile_icons.generic_image(self.tile_face_art(row))    # not captured yet
        return None

    def _on_capture_landed(self, key) -> None:
        """A capture landed for `key`: drop the old picture and repaint the rows showing that file."""
        thumbnails.engine.discard(("capture", captures.file_path(self.preferences, str(key))))
        for row in range(len(self._files)):
            if self.file_key(row) == str(key):
                self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def refresh_row(self, row: int) -> None:
        """Repaint one row after its capture was replaced - drops the engine's copy first or the old image keeps being served."""
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

    def _os_icon_image(self, path: str):
        """The system's icon for this file type, drawn by the panel's `os_icon`, cached per extension."""
        ext = os.path.splitext(path)[1].lower()
        canvas_side = int(getattr(
            self.preferences, "rendersize", 512) or 512)
        cache_key = (ext, canvas_side)
        cached = self._os_icons.get(cache_key)
        if cached is None and self.os_icon is not None:
            cached = self._os_icons[cache_key] = self.os_icon(path, canvas_side)
        return cached

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
        self.toggle_favorites([row])

    def toggle_favorites(self, rows) -> None:
        """Flip the star on every row in `rows` in ONE store write, each keyed by its one file identity."""
        wanted = {}
        flipped = []
        for row in rows:
            key = self.file_key(row)
            if not key:
                continue
            current = wanted[key] if key in wanted else \
                locations.is_favourite(self.preferences, key)
            wanted[key] = not current
            flipped.append(row)
        if not wanted:
            return
        locations.set_favourites(self.preferences, wanted)
        for row in flipped:
            self.row_changed(row, [self.FavoriteRole])

    def rerender_thumbnails(self, rows: list) -> None:
        """Force-regenerate rendered thumbnails: image rows re-convert, geometry rows re-render; hip rows are SKIPPED (a capture is hand-framed, only a new capture replaces it) and other rows have nothing to render."""
        image_cache = self._get_image_cache()
        geo_cache = self._get_geo_cache()
        geo_misses = []
        queued = set()
        for row in rows:
            full = self._full_path(row)
            if not full or not 0 <= row < len(self._kinds):
                continue
            kind = self._kinds[row]
            if kind == locations.KIND_IMAGE:
                if not queued:
                    self._configure_engine_convert()
                image_cache.invalidate(full, flush=False)  # one write after the loop, not one per row: 500 selected images meant 500 full manifest serialisations with an fsync each, on the main thread, before the bar even exists
                key = ("tex", full, image_cache.size)
                thumbnails.engine.discard(key)
                self._row_specs[row] = (key, "convert", full)
                thumbnails.engine.request_convert(
                    key, full, image_cache.size)
                self._pending_writes[key] = full
                self._progress_keys.add(key)
                queued.add(key)
            elif kind == locations.KIND_GEO:
                geo_cache.invalidate(full, flush=False)
                key = ("geo", full, geo_cache.cache_dir)
                thumbnails.engine.discard(key)
                self._row_specs[row] = (key, "render", full)
                geo_misses.append((row, full))
            else:
                continue
            key_rows = self._key_rows.setdefault(key, [])  # the caches re-key on LIVE preferences (the dialog is non-modal), so a key built here can differ from the one _load registered - without this the delivery finds no row, never writes the disk cache, and the tile keeps the old picture
            if row not in key_rows:
                key_rows.append(row)
            index = self.index(row, 0)
            self.row_changed(index.row(), [QtCore.Qt.ItemDataRole.DecorationRole])
        image_cache.save()  # ONE flush for the whole selection, both caches; save() is a no-op when nothing was dirtied
        geo_cache.save()
        if queued:  # distinct KEYS, not rows, the lesson _load carries: a row-count total leaves the bar short forever and the flush gated behind it never runs; every key still pending keeps an in-flight batch's bar consistent
            self._progress_done = 0
            self._progress_total = len(self._progress_keys)
            self.progress_changed.emit(
                self._progress_done, self._progress_total)
        if geo_misses and self.render_geo is not None:
            self.render_geo(geo_misses)

    def file_key(self, row: int) -> str:  # rows are FILES, not library assets: per-tile state keys by `loc:<id>/<relative>` for a file a registered location owns - so a moved folder orphans nothing - and by the canonical absolute path for one no location owns
        if not 0 <= row < len(self._files):
            return ""
        folder, name = self._files[row]
        full = hostos.canonical_path_key(os.path.join(folder, name))
        if locations.generation() != self._file_key_generation:
            self._file_key_generation = locations.generation()
            self._file_key_cache = {}
        cached = self._file_key_cache.get(full)
        if cached is None:
            cached = locations.file_ident(self.preferences, full) or full
            self._file_key_cache[full] = cached
        return cached

    def tile_icon(self, row: int) -> dict:
        key = self.file_key(row)
        return tile_icons.override_for(self.preferences, key) if key else {}

    def tile_key(self, row: int) -> str:
        """A file row is keyed by its PATH - the same key its icon is stored under, and the one thing that survives a re-scan."""
        return self.file_key(row)

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        row = index.row() if hasattr(index, "row") else int(index)
        return self.set_tile_icons([row], spec) == 0

    def set_tile_icons(self, rows, spec) -> int:
        """Give every row in `rows` the icon `spec` in ONE store write; answers how many were not written."""
        keyed = {}
        for row in rows:
            key = self.file_key(row)
            if key:
                keyed[row] = (key, tile_icons.choice_for(self, row, spec))
        if not keyed:
            return len(rows)
        held = tile_icons.set_overrides(  # what really landed - a read-only library must not take icons
            self.preferences, dict(keyed.values()))
        for row in keyed:
            self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])
        return len(rows) - sum(1 for key, _spec in keyed.values() if held[key])

    def commit_tile_icons(self, rows=None) -> None:
        """Signature parity with the asset models; already persisted."""

    def rerender_tile_icons(self) -> int:
        """Repaint every file wearing an icon; they compose in memory, so nothing is written."""
        return tile_icons.repaint_custom(self)

    def _kind(self, row: int) -> str:
        return self._kinds[row] if 0 <= row < len(self._kinds) else ""

    def tile_face_art(self, row: int) -> str:
        """A scene's generic face is T08's Houdini icon, every other file's T11's."""
        return "icon_hip" if self._kind(row) == locations.KIND_HIP else "face_file"

    def can_preview(self, row: int) -> bool:
        """Every file but a scene has one: a render, the image, or the system's icon for its type."""
        return self._kind(row) != locations.KIND_HIP

    def default_face(self, row: int) -> str:
        """Capture for a scene, Render for every other file: its picture, or the system's icon."""
        return "capture" if self._kind(row) == locations.KIND_HIP else "preview"

    def preview_image(self, row: int):
        """The row's own picture as far as it has landed: the tile's Preview, and Customize's."""
        if not 0 <= row < len(self._row_specs):
            return None
        key, source, payload = self._row_specs[row]
        if source == "os-icon":
            return self._os_icon_image(payload)
        if source in ("missing", "none"):
            return tile_icons.generic_image(self.tile_face_art(row))    # unreadable, or a scene
        if source == "file":
            return thumbnails.engine.request_file(key, payload)
        image = thumbnails.engine.peek(key)    # convert/render rows: what has landed so far
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

    def row_data(self, row, role):
        folder, name = self._files[row]
        kind = self._kinds[row]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return name
        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            face = tile_icons.face_for(self, row)
            if face == "capture":
                return self._capture_tile_image(row)
            if face != "preview":
                return tile_icons.chosen_image(self, row)
            return self.preview_image(row)
        if role == self.FormatRole:
            if kind == locations.KIND_GEO:
                return geo_library.matched_extension(
                    name).lstrip(".").upper()
            if kind == locations.KIND_HIP:
                return scene_files.matched_extension(  # capitalized, not upper-cased - a scene extension is a word
                    name).lstrip(".").capitalize()
            if kind == locations.KIND_IMAGE:
                return texture_library.matched_extension(  # its own recogniser, like the other two kinds; the splitext fallback below is for KIND_OTHER, which by definition has no list to match against
                    name).lstrip(".").upper()
            return os.path.splitext(name)[1].lstrip(".").upper()
        if role in (self.PathRole, QtCore.Qt.ItemDataRole.ToolTipRole):
            return hostos.canonical_path_key(os.path.join(folder, name))
        if role == self.FavoriteRole:
            return locations.is_favourite(  # a MEMBERSHIP TEST per tile per repaint, asked by the file's ONE identity - file_favorites composes the whole list out of the store, so asking it here would rebuild every star to answer about one
                self.preferences, self.file_key(row))
        if role == self.FolderRole:
            return os.path.basename(folder.rstrip("/\\")) or folder
        if role == self.CategoryColorRole:
            return self._folder_colour(folder)
        if role == self.KindRole:
            return kind
        if role == self.CropRole:
            return tile_icons.face_for(self, row) == "capture"    # viewport-shaped: it fills the tile
        if role == self.NotesRole:
            from amaze.core import notes
            return notes.has_note(
                self.preferences,
                notes.note_key("file", self.file_key(row)))
        if role == self.OpenSceneRole:
            if kind != locations.KIND_HIP:
                return False
            return self._full_path(row) == self.open_scene()
        return None
