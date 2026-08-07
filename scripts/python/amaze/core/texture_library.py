"""What counts as an image, the shared thumbnail disk cache, and the
folder-section filter proxy.

The Images section merged into the File section on 2026-07-31
(core/file_library.py), taking its models with it - the convert
pipeline's bookkeeping lives in FileFiles now. What stays here is what
that model and its tests consume: IMAGE_EXTENSIONS, ThumbnailCache
(one class, every folder-section prefix - texture_thumbnails_* and
geo_thumbnails_* both), and TextureFilterProxyModel, the name+favorite
filter the File grid runs through.
"""

import hashlib
import json
import os
import shutil

from PySide6 import QtCore, QtGui

from amaze.core import debug, grid_proxy
from amaze.helpers import hostos

IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".exr",
    ".tif",
    ".tiff",
    ".tga",
    ".bmp",
    ".hdr",
    # Houdini's own texture format. Probed 2026-07-31: iconvert
    # round-trips it (it is Houdini's format), and sips fails CLEANLY
    # on it (exit 13, no file written), so the sips->iconvert fallback
    # fires instead of serving garbage. Rendered thumbnails and Load
    # to Node both apply - a .rat on a texture parm is its whole job.
    ".rat",
    # Camera raw in the one container macOS decodes natively. Probed
    # 2026-08-07 on a real Sigma DNG: sips converts it in ~2.3s;
    # Pillow declines fast, so the FORMAT order reaches sips cleanly.
    # A photographer's archive folder is full of these, and without
    # the extension the rows were not images at all.
    ".dng",
)


def matched_extension(name: str) -> str:
    """The IMAGE_EXTENSIONS entry the filename ends with, or ''.

    The geometry and scene kinds each had one of these and images did
    not, so file_library recognised images with `endswith(tuple)`
    instead - which answers yes/no but not WHICH, and that is why its
    FormatRole had to fall back to os.path.splitext for this one kind.
    Three kinds, one question, one shape.
    """
    return hostos.matched_extension(name, IMAGE_EXTENSIONS)

# Texture thumbnails generate at Preferences > RenderSize - the same
# resolution materials render their shaderball thumbnail at - rather than
# a separate hidden setting; the two are unified into a single setting.

# Local-machine-only cache (not the file-synced install folder, not
# the repo) - thumbnails are cheap byproducts, no reason to sync them.
# The resolution is baked into the dir name so a RenderSize change can't
# serve stale cached images generated at the old size.
def _cache_dir_for(size: int, prefix: str = "texture_thumbnails") -> str:
    # The OS-integration engine owns the root location (per-OS
    # convention) and the one-time migrations from every legacy dir.
    return os.path.join(hostos.cache_root(), f"{prefix}_{size}")


class ThumbnailCache:
    """Disk-backed cache of generated texture thumbnails, keyed by source
    file path and kept 1:1 with what's actually in a folder: reconcile()
    drops any cached entry whose source file is gone or has changed
    (mtime/size), so stale thumbnails never linger. All methods are only
    ever called from the main thread - manifest mutation is not
    thread-safe by design, the background worker only generates images,
    it never touches the cache itself."""

    def __init__(self, size: int, prefix: str = "texture_thumbnails") -> None:
        self.size = size
        self.cache_dir = _cache_dir_for(size, prefix)
        self.manifest_path = os.path.join(self.cache_dir, "manifest.json")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._manifest: dict = self._load_manifest()
        self._dirty = False
        self._remember_disk_state()

    def _load_manifest(self) -> dict:
        """The manifest, or {} - and a file that EXISTS but will not
        parse is not the same thing as no file.

        Reading an unreadable manifest as empty and then writing over it
        turns one truncated write into permanent loss of the whole map:
        every PNG in the directory becomes an orphan nothing will ever
        find again, and the folder re-converts from scratch on every
        visit (~6.2s per EXR). Houdini catches SIGABRT and keeps going,
        so a truncated write is not hypothetical here. tile_icons is the
        reference implementation of this policy; this was the outlier.
        """
        self._unreadable = False
        if not os.path.exists(self.manifest_path):
            return {}
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                return loaded
            raise ValueError("manifest is %s, not an object"
                             % type(loaded).__name__)
        except Exception as exc:                         # noqa: BLE001
            self._unreadable = True
            debug.note(
                "could not read the texture thumbnail manifest (%s). "
                "Caching is disabled this session so the file is not "
                "overwritten; the existing thumbnails are untouched."
                % exc, path=self.manifest_path)
            return {}

    def _remember_disk_state(self) -> None:
        """The manifest's fingerprint as this object last saw it."""
        self._disk_state = hostos.disk_state(self.manifest_path)

    def _adopt_from_disk(self) -> None:
        """Fold in entries another writer added since this object read.

        The manifest is read once, in __init__, and FileFiles keeps one
        cache object per size for the whole session - so save() wrote
        the whole in-memory dict over whatever was on disk. Reproduced:
        tab A converts 300 images and flushes, tab B (which had read
        the manifest earlier) converts 40 and flushes, and the manifest
        then holds 40. Tab A's 300 PNGs are orphans nothing will ever
        find again, and that folder re-converts from scratch on the
        next visit at ~6.2s per EXR.

        Adoption can only ADD, the same rule tile_icons._adopt_from_disk
        states: an entry is per-file and self-describing, so there is no
        field-level conflict to resolve - a key this session does not
        hold is another writer's and is kept, a key both hold takes
        ours, because ours was just measured against the file on disk.
        """
        current = hostos.disk_state(self.manifest_path)
        if current is None or getattr(self, "_disk_state", None) == current:
            return                          # nothing moved underneath us
        try:
            with open(self.manifest_path, encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, ValueError):
            return              # an unreadable peer is _load_manifest's
        if not isinstance(loaded, dict):
            return
        adopted = 0
        for key, value in loaded.items():
            if key not in self._manifest and isinstance(value, dict):
                self._manifest[key] = value
                adopted += 1
        if adopted:
            debug.event("textures", "adopted thumbnail entries another "
                        "writer added", path=self.manifest_path,
                        adopted=adopted)

    def save(self) -> None:
        if not self._dirty:
            return
        if getattr(self, "_unreadable", False):
            # REFUSE OVER OVERWRITE: preserve what is there rather than
            # replacing a map we could not read with a partial one.
            return
        if not self.ensure_dir():
            return
        # Temp-then-replace: an in-place write that is interrupted
        # leaves a truncated manifest, which the next launch reads as
        # empty - the exact loss this method exists to prevent.
        #
        # A UNIQUE scratch name, not the fixed `manifest_path + ".new"`
        # this used, and this is the LIVE case of that defect rather than
        # the exotic one: the cache directory is derived from the size and
        # a prefix, not from anything per-process, so two Houdini sessions
        # on one machine browsing images share this exact path and
        # therefore shared one scratch buffer. Measured for the JSON case,
        # two writers x 600 saves through a fixed name: 790 unparseable
        # reads and 794 that PARSED holding both writers' content. Read
        # back, that is a map pointing at the wrong PNGs - and the module's
        # own read path then declines to overwrite it, so the folder
        # re-converts from scratch on every visit (~6.2s per EXR) until
        # someone deletes the file by hand.
        #
        # indent=None keeps the bytes exactly as they were: this is a
        # cache file, and a reformat would rewrite every manifest on disk
        # for no reason.
        try:
            self._adopt_from_disk()
            hostos.write_json_atomic(self.manifest_path, self._manifest,
                                     indent=None)
            self._remember_disk_state()
            self._dirty = False
        except Exception as exc:                         # noqa: BLE001
            debug.note("failed to save the texture thumbnail manifest: %s"
                       % exc, path=self.manifest_path)

    @staticmethod
    def _cache_filename(full_path: str) -> str:
        return hashlib.sha1(full_path.encode("utf-8")).hexdigest() + ".png"

    def _cache_path(self, full_path: str) -> str:
        return os.path.join(self.cache_dir, self._cache_filename(full_path))

    def valid_path(self, full_path: str) -> str | None:
        """The cached PNG's path if the manifest entry still matches the
        source file on disk (same mtime/size) - a stat, no decode. The
        engine's background file loader does the actual reading, so
        folder opens no longer pay a synchronous decode per cached
        file on the main thread."""
        entry = self._manifest.get(full_path)
        if not entry:
            return None
        try:
            st = os.stat(full_path)
        except OSError:
            return None
        if entry.get("mtime") != st.st_mtime or entry.get("size") != st.st_size:
            return None
        cache_path = self._cache_path(full_path)
        if not os.path.exists(cache_path):
            return None
        return cache_path

    def ensure_dir(self) -> bool:
        """Recreate the cache directory if it has gone away.

        It genuinely does. clear() sweeps EVERY texture_thumbnails_* and
        geo_thumbnails_* directory but recreates only its own, and
        GeoFiles._get_cache() memoises its ThumbnailCache on
        (size, mode, bg) - none of which change when the cache is
        cleared. So one press of "Delete Local Cache" left the geometry
        section holding a cache object pointing at a directory that no
        longer existed, for the rest of the session: every render wrote
        nothing, nothing was cached, and it repeated on every visit.

        Cheap enough to call before each write (one stat on the happy
        path), and it heals an externally deleted cache too."""
        if os.path.isdir(self.cache_dir):
            return True
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            return True
        except OSError as exc:
            # "cache" and "directory" are both the program's words, and
            # the path is inside a folder the user has never opened, so
            # it goes in the data. What they actually NOTICE is the
            # slowness, which the old sentence never mentioned.
            debug.note(
                "could not create the folder Amaze keeps image "
                "thumbnails in (%s), so thumbnails are made again "
                "every time you open the folder. Your images are "
                "untouched." % exc, path=self.cache_dir)
            return False

    def put(self, full_path: str, image: QtGui.QImage) -> None:
        """Persist a freshly generated thumbnail and record it in the
        manifest. Does not flush to disk - call save() when convenient."""
        try:
            st = os.stat(full_path)
        except OSError:
            return
        if not self.ensure_dir():
            return
        try:
            # QImage.save returns False rather than raising - so a write
            # into a missing directory used to fall straight through to
            # the manifest line below and record a cache entry for a
            # file that was never written. get() then found no file and
            # re-rendered, every visit, forever.
            written = image.save(self._cache_path(full_path), "PNG")
        except Exception as exc:
            # The BASENAME stays in the sentence, unlike the cache folder
            # above: this one is the user's own image, in the folder they
            # are looking at right now.
            debug.note(
                "the thumbnail for %s could not be saved (%s), so it "
                "is made again on every visit. The image itself is "
                "untouched." % (os.path.basename(full_path), exc))
            return
        if not written:
            debug.note(
                "the thumbnail for %s could not be saved, so it is "
                "made again on every visit. The image itself is "
                "untouched." % os.path.basename(full_path),
                path=full_path)
            return
        self._manifest[full_path] = {"mtime": st.st_mtime, "size": st.st_size}
        self._dirty = True

    def remember_failure(self, full_path: str) -> None:
        """Record that NOTHING could read this file as it stands.

        Without this a file no converter can decode is re-queued on
        every visit to its folder and pays each adapter's timeout
        again - measured live as a stall that never resolves, on the
        same handful of files, forever. The record is keyed to the
        file as it is now, so replacing it with a good image converts
        normally; `invalidate` (Rerender Thumbnail) clears it, which
        is the deliberate retry.
        """
        try:
            st = os.stat(full_path)
        except OSError:
            return
        self._manifest[full_path] = {"mtime": st.st_mtime,
                                     "size": st.st_size,
                                     "failed": True}
        self._dirty = True

    def known_failure(self, full_path: str) -> bool:
        """True when this exact file has already defeated every
        converter - the skip that keeps a folder open fast."""
        entry = self._manifest.get(full_path)
        if not entry or not entry.get("failed"):
            return False
        try:
            st = os.stat(full_path)
        except OSError:
            return False
        return (entry.get("mtime") == st.st_mtime
                and entry.get("size") == st.st_size)

    def reconcile(self, folder: str, current_names: list) -> None:
        """Drop cache entries for this folder whose source file is gone or
        has changed, so the cache stays 1:1 with the folder's contents."""
        self.reconcile_many({folder: current_names})

    def reconcile_many(self, by_folder: dict) -> None:
        """Reconcile SEVERAL directories in one pass over the manifest.

        The per-directory version walks the whole manifest each time,
        and the callers call it once per containing directory - so
        opening a folder with Include Subfolders on was O(subdirs x
        manifest). The manifest is global per resolution and grows with
        every file ever thumbnailed, so this degraded monotonically:
        measured 300 subdirs against a 40,000-entry manifest at 3.13s of
        pure dict iteration, on the main thread, inside the folder open.

        Each stale find also called save(), a full JSON rewrite of the
        entire manifest, up to once per subdirectory. One pass, one
        flush."""
        # BOTH SIDES THROUGH canonical_path_key. The manifest's keys are
        # canonicalised by put(), while these came straight off a scan
        # dirpath - and relocate_folder (folders.py:232) forces a
        # TRAILING SLASH onto a path it rewrites, which os.walk then
        # preserves on the root dirpath. Reproduced: with the slash,
        # `os.path.dirname(<key>)` is "/a/b" against a wanted key of
        # "/a/b/", so every entry in that directory missed and nothing
        # was ever reconciled again for a folder the user had run
        # Locate Folder on - 2,000 deleted images leaving 2,000 orphan
        # PNGs and 2,000 dead entries, in a manifest that is global per
        # resolution and only grows. The same mismatch is unconditional
        # on Windows, where the scan path is os.sep-flavoured and the
        # keys are not: canonical_path_key's own docstring records that
        # exact defect class having cost something once already.
        wanted = {}
        for folder, names in by_folder.items():
            key = hostos.canonical_path_key(folder)
            wanted[key] = {hostos.canonical_path_key(
                os.path.join(folder, name)) for name in names}

        stale = []
        for full_path, entry in self._manifest.items():
            # Through the same funnel, so an entry written by an older
            # build that did not canonicalise still matches.
            current_full = wanted.get(hostos.canonical_path_key(
                os.path.dirname(full_path)))
            if current_full is None:
                continue          # not a directory we were asked about
            if full_path not in current_full:
                stale.append(full_path)
                continue
            try:
                st = os.stat(full_path)
            except OSError:
                stale.append(full_path)
                continue
            if entry.get("mtime") != st.st_mtime or entry.get("size") != st.st_size:
                stale.append(full_path)

        if not stale:
            return
        for full_path in stale:
            cache_path = self._cache_path(full_path)
            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                except OSError:
                    pass
            del self._manifest[full_path]
        self._dirty = True
        self.save()

    def invalidate(self, full_path: str, flush: bool = True) -> None:
        """Evict a single cache entry ("Rerender Thumbnail") - unlike
        reconcile(), which only drops entries whose source file is gone
        or changed, this drops a still-valid entry on request because the
        user wants a fresh render regardless.

        `flush=False` for a LOOP. This ended in an unconditional save(),
        a full JSON serialise of the whole manifest through
        write_json_atomic - fsync and rename - and rerender_thumbnails
        calls it once per selected row: measured, 25 rows produced 25
        full serialisations, so 500 selected images means 500 rewrites
        of a manifest that is global per resolution and measured at
        40,000 entries, on the main thread, before the progress bar is
        even set up. reconcile_many's docstring records the identical
        lesson ("One pass, one flush") for the sibling path; invalidate
        never got it.
        """
        if full_path not in self._manifest:
            return
        cache_path = self._cache_path(full_path)
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
            except OSError:
                pass
        del self._manifest[full_path]
        self._dirty = True
        if flush:
            self.save()

    def invalidate_many(self, paths) -> None:
        """Evict several entries and write the manifest ONCE."""
        for path in paths:
            self.invalidate(path, flush=False)
        self.save()

    def clear(self) -> None:
        """Delete every cached thumbnail file and reset the manifest, in
        memory and on disk. Sweeps every texture_thumbnails_* AND
        geo_thumbnails_* directory, not just the current one's - the
        geometry section keys its dirs by shading mode + background +
        resolution, so combinations tried once would otherwise sit
        orphaned in ~/Library/Caches forever."""
        parent = os.path.dirname(self.cache_dir)
        try:
            for name in os.listdir(parent):
                if name.startswith(("texture_thumbnails_", "geo_thumbnails_")):
                    shutil.rmtree(os.path.join(parent, name), ignore_errors=True)
        except OSError:
            pass
        os.makedirs(self.cache_dir, exist_ok=True)
        self._manifest = {}
        self._dirty = True
        self.save()


class TextureFilterProxyModel(grid_proxy.GridProxyModel):
    """Combines a filename text filter with a favorites-only toggle for
    the File section - deliberately not MultiFilterProxyModel
    (core/multifilterproxy_model.py), which hardcodes Material-specific
    role numbers (e.g. 258 as its own FavoriteRole) that would collide
    with TextureFiles' unrelated role numbering rather than actually
    generalizing across both models.

    What the two DO share is the Grid area's invariant - what is shown
    and in what order - and that is the base class they now have in
    common (core/grid_proxy.py). This one only says what it filters
    on."""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._name_filter = ""
        self._favorites_only = False
        self._kind_filter = ""

    def set_name_filter(self, text: str) -> None:
        self._name_filter = text or ""
        self.refilter()

    def set_favorites_only(self, enabled: bool) -> None:
        self._favorites_only = enabled
        self.refilter()

    def watched_roles(self):
        """Exactly what filterAcceptsRow reads - favourite, kind, the
        display name - plus the sort role. A location colour picked on
        the sidebar or a comment badge appearing emits its role over
        every row, and the whole-blacklist fallback bought a full
        re-filter and re-sort of the section for each (the base's own
        watched_roles docstring names the gesture; MultiFilterProxyModel
        answered, this proxy fell through)."""
        watched = {QtCore.Qt.ItemDataRole.DisplayRole, self.sortRole()}
        model = self.sourceModel()
        for name in ("FavoriteRole", "KindRole"):
            role = getattr(model, name, None)
            if role is not None:
                watched.add(role)
        return watched

    def set_kind_filter(self, kind) -> None:
        """Show only rows of one KIND - a file_library.KIND_* value, or
        None for every kind (which includes KIND_OTHER, the files the
        section has no behaviour for).

        The kind is what the File section IS since the 2026-07-31
        merge: images, geometry and scenes stopped being three tabs and
        became three kinds in one list, and this is how the toolbar
        gets back to one of them."""
        self._kind_filter = kind or ""
        self.refilter()

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex,
    ) -> bool:
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        if self._favorites_only and not index.data(model.FavoriteRole):
            return False
        if self._kind_filter:
            # KindRole belongs to FileFiles, and this proxy serves that
            # model alone - but a model without the role answers None
            # rather than raising, which would silently accept every
            # row. getattr keeps that honest: no role, no kind, no
            # match.
            kind_role = getattr(model, "KindRole", None)
            if kind_role is None:
                return False
            if index.data(kind_role) != self._kind_filter:
                return False
        if self._name_filter:
            name = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
            if self._name_filter.lower() not in name.lower():
                return False
        return True
