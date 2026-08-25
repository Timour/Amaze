"""Models for the File section - the merge of Images, Geometry and HIP: one folder-pointer list, one files model, EVERY file in the chosen folder, each row carrying a KIND that decides its behaviour (image: background convert pipeline; geometry: blocking ESC-interruptable main-thread render; hip: hand-framed captures under config_root, never rendered, never mtime-invalidated; other: OS icon, Copy Path). This module COMPOSES texture_library, geo_library and scene_captures, never forks them. Keep every cache key's existing shape (`('tex', path, size)`, `('geo', path, cache_dir)`, `('hip', path, thumb_dir)`) and keep file keys CANONICAL - one spelling per file - or a user's generated thumbnails, comments and icons orphan. Dotfiles are skipped, or the list fills with `.DS_Store`."""

from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import debug, folders, geo_library, scene_captures
from amaze.core import grid_columns
from amaze.core import keyed_store, locations
from amaze.core import texture_library, thumbnails, tile_icons
from amaze.helpers import hostos

KIND_IMAGE = "image"  # row kinds in the order kind_for() checks them; values readable on purpose - they surface in menus, debug events and tests
KIND_GEO = "geometry"
KIND_HIP = "hip"
KIND_OTHER = "other"


def kind_for(name: str) -> str:
    """Which per-type behaviour a filename gets - the three recognisers are the sections' own: one source for what counts as an image, a geometry file or a scene."""
    if scene_captures.matched_extension(name):
        return KIND_HIP
    if texture_library.matched_extension(name):
        return KIND_IMAGE
    if geo_library.matched_extension(name):
        return KIND_GEO
    return KIND_OTHER


PATH_STYLES = ("absolute", "hip", "job", "home")  # the variables a path may be written against; home is the DEFAULT, absolute writes the literal path, and a stored auto (a retired style) maps to home in the prefs setter
_STYLE_VARS = {"hip": "$HIP", "job": "$JOB", "home": "$HOME"}

GEO_PASS_LOG = "geo thumbnails"  # per-item records the geo pass may write per RUN: event()'s flood guard keys on (category, message) alone, so these shared one key and went dark after 5 of 273 - always the first five files, not a sample worth having
GEO_PASS_FAIL_LOG = "geo thumbnails failed"
GEO_PASS_LOG_BUDGET = 20


def houdini_path(path: str, style: str = "home") -> str:
    """A path written the way Houdini writes them - for Copy Path and the File section's location labels. `style` is Preferences > Write Paths As: one specific variable, or absolute. Falls back to the absolute path untouched when hou is not importable (plain-python tests) or the path does not live under the chosen variable."""
    path = hostos.canonical_path_key(path or "")
    if not path or style == "absolute":
        return path
    try:
        import hou
    except ImportError:
        return path
    var = _STYLE_VARS.get(style, "$HOME")
    try:
        expanded = hostos.canonical_path_key(hou.text.expandString(var))
    except Exception:                                    # noqa: BLE001
        return path
    if not expanded or expanded in ("/", "."):
        return path
    prefix = expanded.rstrip("/") + "/"
    if path.startswith(prefix):
        return var + "/" + path[len(prefix):]
    return path


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
    """Whether one registered location shows its unknown files: the per-location Show All Files override when set, the global Show Unknown Files preference otherwise."""
    override = locations.record(preferences, location).get("show_all")
    if override is not None:
        return bool(override)
    return bool(getattr(preferences, "file_show_unknown", True))


class FileFolders(folders.FolderListModel):
    """The File section's registered-folder sidebar - counts and lists EVERY visible file, because this section's whole point is that a folder shows what is actually in it. Per-location state: recursion is per folder (file_recursive_folders), the display name defaults to the Houdini-collapsed PATH and can be renamed (file_folder_names), removal sweeps the folder's cached thumbnails, and Locate Folder carries name + recursion along with the favourites the base already rewrites."""

    folders_attr = "file_folders"
    favorites_attr = "file_favorites"
    last_folder_attr = "last_file_folder"
    add_folder_method = "add_file_folder"
    remove_folder_method = "remove_file_folder"
    relocate_folder_method = "relocate_file_folder"
    move_folder_method = "move_file_folder"

    def matches(self, filename: str) -> bool:
        """The flat contract, answered by the per-LOCATION rule. It used to be a second three-line body applying the global `file_show_unknown` preference the per-location override replaced - unreachable (this class overrides matches_in, which _folder_count calls) and WRONG, the shape that bites the next consumer of the documented subclass contract: the sidebar number disagreeing with the tiles is the exact defect the per-location rule exists to prevent. One rule, one body: with no location to ask about, the global preference is the only answer available, which is what an empty-path matches_in gives."""
        return self.matches_in("", filename)


    def matches_in(self, path: str, filename: str) -> bool:  # the count asks the LOCATION's rule, so the sidebar number and the grid agree per location, not just globally
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
        keyed_store.retire_prefix(self.preferences, path)  # PER-LOCATION STATE DIES WITH THE POINTER, all of it in one call: naming surfaces by hand left the colour and Show All Files behind, so re-registering brought back an amber row and a hidden-files setting the user never re-chose
        sweep_folder_cache(  # ...and so do its cached thumbnails, comments and tile icons - removing a location clears everything, so re-adding is a clean slate (the UI text register - File (folders) - Remove); hip captures are the one exception, hand-framed and not regenerable, and which stores go is `survives_forget` on each spec, said once, never inferred from this method's lines
            self.preferences, path, list(self._folders()))

    def _on_folder_relocated(self, old_path: str, new_path: str) -> None:
        """One announcement, no enumeration - the old hand-written tuple named neither notes.json nor icons.json, so a Locate Folder orphaned every comment and tile icon still keyed by the old path; the caller names the prefix that moved, the engine walks its registry, and a store cannot fail to join a list it does not have to be added to."""
        keyed_store.relocate(self.preferences, old_path, new_path)


class FileFiles(grid_columns.GridColumnsMixin,
               QtCore.QAbstractTableModel):
    """All files inside the selected folder (or every registered folder in All mode), each behaving as its kind."""

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
        self._colour_cache: dict = {}  # folder -> the owning location's colour band; THE PAINT PATH - the uncached shape deep-copied a location record per tile per frame and keyed on the row's own directory, painting recursive subfolder rows bandless; cleared on rescan and by colours_changed()
        self._capture_seen: dict = {}  # does this scene have a capture, filled lazily on first paint and kept: the alternative is a stat per visible scene row per FRAME - cheap on a warm local disk, not on a sleeping external volume, which a registered File location is exactly where one turns up (research.md - Volume mounts on macOS); same shape as folders.py `_counts`
        thumbnails.signals.ready.connect(self._on_thumb_key_ready)  # through the RELAY, not the engine: the singleton is replaced on every module reload, which would leave this model wired to a dead one (thumbnails._EngineSignals)
        thumbnails.signals.convert_attempted.connect(
            self._on_convert_attempted)
        scene_captures.signals.captured.connect(self._on_capture_landed)  # a capture from anywhere - the tile menu, the shelf tool - repaints this model's row for that scene

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
                size, prefix="geo_thumbnails_%s_%s" % (mode, bg))
            self._geo_cache_key = key
        return self._geo_cache

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
        """Re-runs the current selection - cheap when nothing changed, every item is still a cache hit."""
        if self._all_folders_mode:
            self.set_all_folders()
        elif self._folder:
            self.set_folder(self._folder)

    def _scan(self, folder: str) -> list:
        """[(containing_dir, name)] pairs - every visible file, flat by default, recursive when Include Subfolders is on; files keep their CONTAINING dir so paths, cache keys and the Category column stay correct per subfolder."""
        results = []
        if not folder or not os.path.isdir(folder):
            if folder:  # an UNREACHABLE folder is not an empty one: an unmounted share looks exactly like isdir() saying no, and the nothing-here-yet state then teaches the wrong thing about an archive that is merely offline - recorded so the state has a fact behind it
                self._unreadable_folders.add(folder)
                debug.event("file", "a registered folder could not be "
                            "read", folder=folder, reason="not there")
            return results
        self._unreadable_folders.discard(folder)
        if locations.record(self.preferences, folder).get("recursive"):
            for dirpath, dirnames, filenames in \
                    folders.walk_following_links(folder):
                dirnames[:] = [d for d in dirnames  # the skip-hidden rule applies to DIRECTORIES too: without the prune, recursion floods the grid with thousands of .git internals
                               if not d.startswith(".")]
                dirnames.sort(key=str.lower)
                for name in sorted(filenames, key=str.lower):
                    if not name.startswith("."):
                        results.append((dirpath, name))
        else:
            try:
                names = sorted(os.listdir(folder), key=str.lower)
            except OSError as exc:  # present but unreadable - a permissions change, a share dropped mid-session; same rule as above, say so rather than showing an empty folder
                self._unreadable_folders.add(folder)
                debug.event("file", "a registered folder could not be "
                            "read", folder=folder, error=str(exc))
                return []
            for name in names:
                full = os.path.join(folder, name)
                if not name.startswith(".") and os.path.isfile(full):
                    results.append((folder, name))
        return results

    def _load(self, folder_list: list) -> None:
        """One scan, four behaviours: image conversions queue in the background exactly as the Images section did, geometry misses render in the blocking interruptable pass exactly as Geometry did, hip and other rows cost nothing at load."""
        self.cancel_conversions("folder switch")
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
        self._capture_seen = {}  # a rescan is the moment the disk is authoritative again, so the remembered stats go with the rows they described
        geo_misses = []

        entries = []
        for folder in folder_list:
            keep_other = shows_all_files(self.preferences, folder)  # unknowns are dropped at gather time, per the LOCATION they came from - the All view can show one location's unknowns and hide another's
            for dirpath, name in self._scan(folder):
                if not keep_other and kind_for(name) == KIND_OTHER:
                    continue
                entries.append((dirpath, name))

        image_dirs: dict = {}  # ONE reconcile pass per manifest for every directory at once
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
                    self._row_specs.append((key, "missing", full))  # already defeated every converter as it stands - re-queueing pays each adapter's timeout again on every visit; Rerender Thumbnail is the deliberate retry
                else:
                    self._row_specs.append((key, "convert", full))
                    if not convert_queued:
                        self._configure_engine_convert()  # options pushed once per batch, lazily - the hou import stays out of plain-python paths
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
                key = ("hip", full, scene_captures.thumb_dir())
                self._key_rows.setdefault(key, []).append(row)
                self._row_specs.append((key, "capture", full))
            else:
                self._row_specs.append(
                    (None, "os-icon", os.path.join(dirpath, name)))
        self.endResetModel()

        self._progress_done = 0
        self._progress_total = len(self._progress_keys)  # distinct KEYS, not rows - duplicates share one conversion (the progress-bar-stalls-forever lesson, texture_library)
        self.progress_changed.emit(
            self._progress_done, self._progress_total)

        if geo_misses:
            self._render_geo_misses(geo_misses)

    def _configure_engine_convert(self) -> None:
        import hou

        thumbnails.engine.configure_convert(
            hou.text.expandString("$HFS"),
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
        colour = str(locations.record(  # the row's own directory first - the registered-location case, which must keep working on every prefs surface
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
        """A location's colour moved - drop the paint-path cache; the caller (the section's colour setter) emits the repaint."""
        self._colour_cache = {}

    def clear_cache(self) -> None:
        """Wipe the on-disk thumbnail caches (images AND geometry - one clear() sweeps both prefixes) and the in-memory copies; hip captures are NOT touched - hand-framed, not regenerable, which is why they live under config_root."""
        self._get_image_cache().clear()
        self._geo_cache = None  # the object too: clear() rmtrees the geo prefix on disk, and a kept in-memory manifest went on describing deleted PNGs, growing entries that could never hit again
        self._geo_cache_key = None
        thumbnails.engine.clear()

    def _render_geo_misses(self, misses: list) -> None:
        """Render missing geometry thumbnails NOW, on the main thread - blocking but ESC-interruptable; every finished file lands in the disk cache immediately so an interrupted pass resumes."""
        import hou
        from amaze.render import thumbs

        misses = [pair for pair in misses  # a CACHE gets no thumbnail unasked, filtered HERE so there is one answer and the dialog cannot open for a list that is entirely caches: two filecache files once re-cooked on EVERY switch to Files (~75 attempts, all no-cookable-geometry), reported as the bar flashing on entering the section
                  if not geo_library.is_cache(pair[1])]
        if not misses:
            return
        cache = self._get_geo_cache()
        size = self.preferences.rendersize
        thumber = thumbs.ThumbNailRenderer(self.preferences)
        cache.ensure_dir()
        scratch_seed = os.path.join(cache.cache_dir, "geo_render.png")  # ONE SCRATCH PER ITEM, unique, create=False: a fixed name was one buffer for the whole pass, and create_thumb_geo_file decides success by os.path.exists - an ESC'd flipbook returns without raising, found the PREVIOUS file's picture and cached the wrong image against this file's own mtime; the fixed name was also shared by every Houdini process, and a pre-created empty file passes the exists test just as well
        total = len(misses)
        done = 0
        failed = []
        debug.begin_pass(GEO_PASS_LOG)  # fresh allowance for this pass's per-item records; the closing record below carries what the budget could not
        debug.begin_pass(GEO_PASS_FAIL_LOG)
        self.progress_changed.emit(0, total)
        try:
            with hou.InterruptableOperation(
                "Rendering geometry thumbnails",
                "Rendering geometry thumbnails",
                open_interrupt_dialog=True,
            ) as operation:
                for row, full in misses:
                    operation.updateProgress(done / total)
                    if debug.pass_budget(GEO_PASS_LOG, GEO_PASS_LOG_BUDGET):
                        debug.event("file", "geo thumbnail",
                                    i=done + 1, total=total, file=full)
                    ok = False
                    tmp_path = hostos.unique_scratch(
                        scratch_seed, suffix=".render", create=False)
                    try:
                        ok = thumber.create_thumb_geo_file(
                            full, tmp_path, size)
                    except hou.OperationInterrupted:
                        raise
                    except Exception as exc:             # noqa: BLE001
                        failed.append(full)
                        if debug.pass_budget(GEO_PASS_FAIL_LOG,
                                             GEO_PASS_LOG_BUDGET):
                            debug.event("file", "geo thumbnail failed",
                                        file=full, error=str(exc))
                    try:
                        if ok:
                            image = QtGui.QImage(tmp_path)
                            if not image.isNull():
                                cache.put(full, image)
                                thumbnails.engine.deposit(
                                    ("geo", full, cache.cache_dir), image)
                    finally:  # gone before the next item, whatever happened - nothing may be left for a later render to inherit and report as its own
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                    done += 1
                    self.progress_changed.emit(done, total)
                    QtWidgets.QApplication.processEvents(  # the pass blocks the event loop; pump paints only, so finished tiles appear mid-pass without letting input re-enter the panel
                        QtCore.QEventLoop.ProcessEventsFlag
                        .ExcludeUserInputEvents
                    )
        except hou.OperationInterrupted:
            debug.event("file", "geo pass interrupted",
                        done=done, total=total)
        finally:
            debug.event("file", "geo pass done", done=done, total=total,  # ONE record for the whole pass, ALWAYS, naming every failure - the per-item records are a bounded sample, and a pass that logged 5 of 273 was unreadable exactly when it mattered
                        failed=len(failed), files=failed)
            if not self._progress_keys:  # ONE OWNER PER FOLDER OPEN: this pass emits into the image batch's signal, so an unconditional terminal (0, 0) hid the bar while conversions still ran - a flickering bar with the wrong denominator, the only signal a long conversion is still going
                self.progress_changed.emit(0, 0)
            cache.save()
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def _capture_png(self, hip_path: str) -> str:
        """This scene's capture PNG, or an empty path if it has none. The stat is remembered per scene (`_capture_seen`): a repaint must not ask the filesystem a question this process already answered - `_on_capture_landed` forgets the one path a capture just changed, a rescan forgets the lot, so the only way to a stale answer is deleting a PNG from under a running panel, re-read on the next folder visit."""
        seen = self._capture_seen.get(hip_path)
        if seen is None:
            png = scene_captures.thumb_path(hip_path)
            seen = png if (png and os.path.isfile(png)) else ""
            self._capture_seen[hip_path] = seen
        return seen

    def _on_capture_landed(self, hip_path) -> None:
        path = str(hip_path or "")
        self._capture_seen.pop(path, None)  # forget BEFORE the repaint: refresh_row paints, and painting is what re-asks
        row = self.row_for_path(path)
        if row >= 0:
            self.refresh_row(row)

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
        """The system's icon for this file type, drawn centred on a transparent square, cached per extension (the provider is not free and a folder of logs is one icon repeated). The provider can hand back SMALL icons, so the native pixmap draws at its own size, upscaled at most 2x, never stretched across the tile - and NEVER empty: if nothing paintable comes back, Qt's generic file icon stands in, because a tile with no picture at all reads as a loading failure."""
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
            if kind == KIND_IMAGE:
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
            elif kind == KIND_GEO:
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
        if geo_misses:
            self._render_geo_misses(geo_misses)

    def file_key(self, row: int) -> str:  # rows are FILES, not library assets: per-tile choices live in icons.json keyed by absolute path, CANONICAL - the raw join carried the location's $AMAZE-relative spelling (research.md - Windows), so re-registering the same folder absolute sent every comment and icon under it dark; nothing was orphaned by canonicalising, measured: icons.json did not exist and notes.json held no file keys
        if not 0 <= row < len(self._files):
            return ""
        folder, name = self._files[row]
        return hostos.canonical_path_key(os.path.join(folder, name))

    def tile_icon(self, row: int) -> dict:
        key = self.file_key(row)
        return tile_icons.override_for(self.preferences, key) if key else {}

    def tile_key(self, row: int) -> str:
        """A file row is keyed by its PATH - the same key its icon is stored under, and the one thing that survives a re-scan."""
        return self.file_key(row)

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        row = index.row() if hasattr(index, "row") else int(index)
        key = self.file_key(row)
        if not key:
            return False
        written = tile_icons.set_override(self.preferences, key, spec)  # report what actually happened - a read-only library must not take icons it will lose at restart
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

    def data(self, index, role: int = 0):
        if index.column() > 0:  # LATER COLUMNS are the table's, not the row's (QTableView migration step 1); column 0 falls through unchanged, so grid mode cannot tell any of this happened
            return self.column_data(index, role)
        if not index.isValid():
            return None
        row = index.row()
        if not 0 <= row < len(self._files):  # isValid() does not mean in-range: an index outlives a shrink
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
                return None  # remembered: nothing could read this file as it stands, so the tile rests on its placeholder rather than paying every converter's timeout again
            if source == "file":
                return thumbnails.engine.request_file(key, payload)
            if source == "capture":
                png = self._capture_png(payload)
                if png:
                    image = thumbnails.engine.request_file(key, png)
                    if image is not None:
                        return image
                return scene_captures.placeholder_image()  # no capture yet - the resting state, not a wait
            image = thumbnails.engine.peek(key)  # convert/render rows: serve what has landed; after eviction the disk cache takes over as a file load
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
                return scene_captures.matched_extension(  # capitalized, not upper-cased - a scene extension is a word
                    name).lstrip(".").capitalize()
            if kind == KIND_IMAGE:
                return texture_library.matched_extension(  # its own recogniser, like the other two kinds; the splitext fallback below is for KIND_OTHER, which by definition has no list to match against
                    name).lstrip(".").upper()
            return os.path.splitext(name)[1].lstrip(".").upper()
        if role in (self.PathRole, QtCore.Qt.ItemDataRole.ToolTipRole):
            return hostos.canonical_path_key(os.path.join(folder, name))
        if role == self.FavoriteRole:
            return locations.is_favourite(  # a MEMBERSHIP TEST per tile per repaint - file_favorites composes the whole list out of the store, so asking it here would rebuild every star to answer about one
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
            return self._full_path(row) == scene_captures.current_scene_path()
        return None
