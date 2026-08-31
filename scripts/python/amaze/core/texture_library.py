"""What counts as an image, the shared thumbnail disk cache, and the folder-section filter proxy. The Images section merged into the File section 2026-07-31 (core/file_library.py), taking its models with it; what stays here is what that model and its tests consume: IMAGE_EXTENSIONS, ThumbnailCache (one class, every folder-section prefix - texture_thumbnails_* and geo_thumbnails_* both), and TextureFilterProxyModel, the name+favorite filter the File grid runs through."""

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
    ".rat",  # Houdini's own texture format - probed 2026-07-31: iconvert round-trips it and sips fails CLEANLY on it (exit 13, no file), so the sips->iconvert fallback fires instead of serving garbage
    ".dng",  # camera raw in the one container macOS decodes natively - probed 2026-08-07 on a real Sigma DNG: sips converts in ~2.3s, Pillow declines fast, so the FORMAT order reaches sips cleanly
)


def matched_extension(name: str) -> str:
    """The IMAGE_EXTENSIONS entry the filename ends with, or '' - three kinds, one question, one shape (an `endswith(tuple)` answers yes/no but never WHICH, which forced a splitext fallback on this one kind)."""
    return hostos.matched_extension(name, IMAGE_EXTENSIONS)


def _cache_dir_for(size: int, prefix: str = "texture_thumbnails") -> str:
    # local-machine-only cache with the resolution baked into the dir name, so a RenderSize change cannot serve stale images; hostos owns the root and the legacy-dir migrations
    return os.path.join(hostos.cache_root(), f"{prefix}_{size}")


class ThumbnailCache:
    """Disk-backed cache of generated thumbnails, keyed by canonical source path and kept 1:1 with the folder by reconcile(); main-thread only - the background worker generates images and never touches the cache."""

    def __init__(self, size: int, prefix: str = "texture_thumbnails") -> None:
        self.size = size
        self.cache_dir = _cache_dir_for(size, prefix)
        self.manifest_path = os.path.join(self.cache_dir, "manifest.json")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._manifest: dict = self._load_manifest()
        self._dirty = False
        self._remember_disk_state()

    def _load_manifest(self) -> dict:
        """The manifest, or {} - a file that EXISTS but will not parse latches `_unreadable`, because reading it as empty and writing over it turns one truncated write into permanent loss of the whole map (every PNG orphaned, ~6.2s per EXR to re-convert; tile_icons is the reference policy)."""
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
        self._disk_state = hostos.fingerprint_of(self.manifest_path)

    def _adopt_from_disk(self) -> None:
        """Fold in entries another writer added since this object read - adoption can only ADD (an entry is per-file and self-describing): a key this session does not hold is another writer's and is kept, a key both hold takes ours, because ours was just measured against the file on disk. Without it, two tabs flushing left the later writer's 40 entries and orphaned the earlier one's 300 PNGs."""
        answer = hostos.peer_read(self.manifest_path,    # ▸r/peer-read
                                  getattr(self, "_disk_state", None))
        if answer.verdict != hostos.PEER_CHANGED:
            return      # unchanged, absent, or an unreadable peer, which is _load_manifest's
        adopted = 0
        for key, value in answer.document.items():
            key = self._key(key)
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
            return  # REFUSE OVER OVERWRITE: preserve what is there rather than replacing a map we could not read with a partial one
        if not self.ensure_dir():
            return
        try:
            self._adopt_from_disk()  # temp-then-replace through the atomic writer, whose UNIQUE scratch name matters here: two sessions share this exact path (the dir derives from size+prefix, nothing per-process), and a fixed scratch name measured 790 unparseable reads plus 794 that parsed holding both writers' content; indent=None keeps a cache file's bytes as they were
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

    @staticmethod
    def _key(full_path: str) -> str:
        """How the manifest spells a source file - ONE answer at every door in (the load side keeps entries verbatim, so an older raw-spelled key stays until re-written); a raw Windows-flavoured key misses a wanted set spelled with forward slashes, reads stale, and the folder re-converts every visit."""
        return hostos.canonical_path_key(full_path)

    def _cache_path(self, full_path: str) -> str:
        return os.path.join(self.cache_dir, self._cache_filename(full_path))

    def valid_path(self, full_path: str) -> str | None:
        """The cached PNG's path if the manifest entry still matches the source file (same mtime/size) - a stat, no decode; the engine's background loader does the reading."""
        full_path = self._key(full_path)
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
        """Recreate the cache directory if it has gone away - it genuinely does: clear() sweeps every prefix directory but recreates only its own, while a memoised cache object keeps pointing at the swept path for the rest of the session; one stat on the happy path, and it heals an externally deleted cache too."""
        if os.path.isdir(self.cache_dir):
            return True
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            return True
        except OSError as exc:
            debug.note(  # what the user NOTICES is the slowness, so the sentence says that; the path goes in the data
                "could not create the folder Amaze keeps image "
                "thumbnails in (%s), so thumbnails are made again "
                "every time you open the folder. Your images are "
                "untouched." % exc, path=self.cache_dir)
            return False

    def put(self, full_path: str, image: QtGui.QImage) -> None:
        """Persist a freshly generated thumbnail and record it in the manifest - does not flush to disk, call save() when convenient."""
        full_path = self._key(full_path)  # canonicalised HERE, at the write door itself - it used to hold only because every caller happened to do it first
        try:
            st = os.stat(full_path)
        except OSError:
            return
        if not self.ensure_dir():
            return
        try:
            written = image.save(self._cache_path(full_path), "PNG")  # QImage.save answers False rather than raising - falling through here once recorded manifest entries for files never written, re-rendering every visit forever
        except Exception as exc:
            debug.note(  # the BASENAME stays in this sentence: it is the user's own image, in the folder they are looking at
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
        """Record that NOTHING could read this file as it stands - keyed to the file as it is now, so replacing it converts normally and `invalidate` (Rerender Thumbnail) is the deliberate retry; without it an undecodable file re-queues and pays every adapter's timeout on each visit, forever."""
        full_path = self._key(full_path)
        try:
            st = os.stat(full_path)
        except OSError:
            return
        self._manifest[full_path] = {"mtime": st.st_mtime,
                                     "size": st.st_size,
                                     "failed": True}
        self._dirty = True

    def known_failure(self, full_path: str) -> bool:
        """True when this exact file has already defeated every converter - the skip that keeps a folder open fast."""
        entry = self._manifest.get(self._key(full_path))
        if not entry or not entry.get("failed"):
            return False
        try:
            st = os.stat(full_path)
        except OSError:
            return False
        return (entry.get("mtime") == st.st_mtime
                and entry.get("size") == st.st_size)

    def reconcile(self, folder: str, current_names: list) -> None:
        """Drop cache entries for this folder whose source file is gone or changed, so the cache stays 1:1 with the folder's contents."""
        self.reconcile_many({folder: current_names})

    def reconcile_many(self, by_folder: dict) -> None:
        """Reconcile SEVERAL directories in one pass over the manifest, one flush - the per-directory walk was O(subdirs x manifest) with a full JSON rewrite per stale find (measured: 300 subdirs against 40,000 entries, 3.13s of dict iteration inside the folder open)."""
        wanted = {}  # BOTH sides through canonical_path_key: scan dirpaths arrive os.sep-flavoured (and Locate Folder forces a trailing slash the walk preserves), so an uncanonicalised dirname never matches a wanted key and nothing reconciles again for that folder
        for folder, names in by_folder.items():
            key = hostos.canonical_path_key(folder)
            wanted[key] = {hostos.canonical_path_key(
                os.path.join(folder, name)) for name in names}

        stale = []
        for full_path, entry in self._manifest.items():
            current_full = wanted.get(hostos.canonical_path_key(  # through the same funnel, so an entry written by an older build still matches
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
        """Evict a single cache entry ("Rerender Thumbnail") - drops a still-valid entry on request, unlike reconcile(). `flush=False` for a LOOP, one save() after: an unconditional flush measured 25 rows as 25 full manifest serialisations (fsync each) on the main thread."""
        full_path = self._key(full_path)
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

    def clear(self) -> None:
        """Delete every cached thumbnail file and reset the manifest, in memory and on disk - sweeps every texture_thumbnails_* AND geo_thumbnails_* directory, because the geometry section keys its dirs by shading mode + background + resolution and combinations tried once would sit orphaned forever."""
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
    """Filename text filter + favorites-only toggle + kind filter for the File section - deliberately not MultiFilterProxyModel, whose hardcoded Material role numbers would collide with this model's unrelated numbering; what the two DO share (the Grid area's shown-and-ordered invariant) is the base class."""

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
        """Exactly what filterAcceptsRow reads - favourite, kind, the display name - plus the sort role, so a role emitted over every row (a sidebar colour, a comment badge) does not buy a whole re-filter through the blacklist fallback."""
        watched = {QtCore.Qt.ItemDataRole.DisplayRole, self.sortRole(),
                   self.sort_column_role()}    # the sort COLUMN's role too: a later column orders on a UserRole this set would otherwise drop
        model = self.sourceModel()
        for name in ("FavoriteRole", "KindRole"):
            role = getattr(model, name, None)
            if role is not None:
                watched.add(role)
        return watched

    def set_kind_filter(self, kind) -> None:
        """Show only rows of one KIND - a file_library.KIND_* value, or None for every kind (KIND_OTHER included); the kind is what the File section IS since the 2026-07-31 merge, and this is how the toolbar gets back to one of them."""
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
            kind_role = getattr(model, "KindRole", None)  # a model without the role answers None rather than raising, which would silently accept every row - no role, no kind, no match
            if kind_role is None:
                return False
            if index.data(kind_role) != self._kind_filter:
                return False
        if self._name_filter:
            name = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
            if self._name_filter.lower() not in name.lower():
                return False
        return True
