"""What counts as an image, the shared thumbnail disk cache, and the File grid's filter proxy."""

import hashlib
import json
import os
import shutil
import weakref

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
    ".rat",  # Houdini's own texture format; iconvert reads it
    ".dng",  # camera raw; sips reads it on macOS
)


def matched_extension(name: str) -> str:
    """The IMAGE_EXTENSIONS entry the filename ends with, or ''."""
    return hostos.matched_extension(name, IMAGE_EXTENSIONS)


_LIVE = globals().get("_LIVE", weakref.WeakSet())    # every ThumbnailCache alive in this process


def live_caches(cache_dir: str) -> list:
    """Every ThumbnailCache this process holds over `cache_dir`."""
    wanted = hostos.comparable_path(cache_dir)
    return [cache for cache in list(_LIVE)
            if hostos.comparable_path(cache.cache_dir) == wanted]


def _cache_dir_for(size: int, prefix: str = "texture_thumbnails") -> str:
    # a machine-local cache, one directory per prefix and render size
    return os.path.join(hostos.cache_root(), f"{prefix}_{size}")


class ThumbnailCache:
    """Thumbnails by canonical source path, kept 1:1 with the folder; the manifest is main-thread only."""

    def __init__(self, size: int, prefix: str = "texture_thumbnails",
                 failure_tag: str = "") -> None:
        self.size = size
        self._failure_tag = failure_tag    # a failure kept only if this tag wrote it; a new tag retries once
        self.cache_dir = _cache_dir_for(size, prefix)
        self.manifest_path = os.path.join(self.cache_dir, "manifest.json")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._manifest: dict = self._load_manifest()
        self._dirty = False
        _LIVE.add(self)

    def paths(self) -> list:
        """Every source path this object holds an entry for, saved or not."""
        return list(self._manifest)

    def forget(self, paths) -> None:
        """Drop entries a sweep took off disk, adopting the disk first so no save writes them back."""
        self._adopt_from_disk()
        for path in paths:
            self._manifest.pop(self._key(path), None)

    def moved(self, moves: dict) -> None:
        """Entries a move re-filed on disk: both ends dropped, then the disk read in, the move's own."""
        for old, new in moves.items():
            self._manifest.pop(self._key(old), None)
            self._manifest.pop(self._key(new), None)    # a stale entry here would outlive the carry
        self._adopt_from_disk()

    def _load_manifest(self) -> dict:
        """The manifest, or {}; one that exists but will not parse sets `_unreadable`, blocking saves."""
        self._unreadable = False
        self._disk_state = None
        if not os.path.exists(self.manifest_path):
            return {}
        try:
            with open(self.manifest_path, "rb") as f:
                raw = f.read()
            self._disk_state = hostos.file_fingerprint(raw)    # of the bytes parsed, never a second read
            loaded = json.loads(raw.decode("utf-8"))
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

    def _adopt_from_disk(self) -> None:
        """Fold in entries another writer added since this read; only adds, and a shared key keeps ours."""
        answer = hostos.peer_read(self.manifest_path,    # ▸r/peer-read
                                  getattr(self, "_disk_state", None))
        self._disk_state = answer.fingerprint    # the read just made, never a second one
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
            return  # never overwrite a manifest that could not be read
        if not self.ensure_dir():
            return
        try:
            self._adopt_from_disk()  # sessions share this path; the atomic writer keeps it whole
            self._disk_state = hostos.write_json_atomic(    # what we wrote, never a re-read
                self.manifest_path, self._manifest, indent=None)
            self._dirty = False
        except Exception as exc:                         # noqa: BLE001
            debug.note("failed to save the texture thumbnail manifest: %s"
                       % exc, path=self.manifest_path)

    @staticmethod
    def _cache_filename(full_path: str) -> str:
        return hashlib.sha1(full_path.encode("utf-8")).hexdigest() + ".png"

    @staticmethod
    def _key(full_path: str) -> str:
        """How the manifest spells a source file; every way in goes through this."""
        return hostos.canonical_path_key(full_path)

    def _cache_path(self, full_path: str) -> str:
        return os.path.join(self.cache_dir, self._cache_filename(full_path))

    def png_path(self, full_path: str) -> str:
        """Where `full_path`'s thumbnail PNG lives in this cache - what a convert worker writes."""
        return self._cache_path(self._key(full_path))

    def adopt(self, full_path: str, png: str) -> bool:
        """Record the worker's PNG for `full_path`; False when `png` is not its file here, or it is gone."""
        full_path = self._key(full_path)
        if hostos.comparable_path(png) != hostos.comparable_path(self._cache_path(full_path)):
            return False
        try:
            st = os.stat(full_path)
        except OSError:
            return False
        self._manifest[full_path] = {"mtime": st.st_mtime, "size": st.st_size}
        self._dirty = True
        return True

    def valid_path(self, full_path: str, stat=None) -> str | None:
        """The cached PNG's path while its entry matches the source's mtime and size, else None."""
        full_path = self._key(full_path)
        entry = self._manifest.get(full_path)
        if not entry:
            return None
        try:
            st = (stat or os.stat)(full_path)    # a caller's own stat answers for one it already made
        except OSError:
            return None
        if entry.get("mtime") != st.st_mtime or entry.get("size") != st.st_size:
            return None
        cache_path = self._cache_path(full_path)
        if not os.path.exists(cache_path):
            return None
        return cache_path

    def ensure_dir(self) -> bool:
        """Recreate the cache directory if it has gone; False when it cannot be made."""
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
        """Write a new thumbnail and record it in the manifest; call save() to flush."""
        full_path = self._key(full_path)
        try:
            st = os.stat(full_path)
        except OSError:
            return
        if not self.ensure_dir():
            return
        try:
            written = image.save(self._cache_path(full_path), "PNG")  # False on failure, rather than raising
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
        """Record that nothing could read this file as it is now; `invalidate` retries it."""
        full_path = self._key(full_path)
        try:
            st = os.stat(full_path)
        except OSError:
            return
        self._manifest[full_path] = {"mtime": st.st_mtime,
                                     "size": st.st_size,
                                     "failed": True}
        if self._failure_tag:
            self._manifest[full_path]["tag"] = self._failure_tag
        self._dirty = True

    def known_failure(self, full_path: str, stat=None) -> bool:
        """True when this exact file has already defeated every converter."""
        entry = self._manifest.get(self._key(full_path))
        if not entry or not entry.get("failed"):
            return False
        if entry.get("tag", "") != self._failure_tag:
            return False
        try:
            st = (stat or os.stat)(full_path)
        except OSError:
            return False
        return (entry.get("mtime") == st.st_mtime
                and entry.get("size") == st.st_size)

    def reconcile(self, folder: str, current_names: list) -> None:
        """Drop this folder's cache entries whose source file is gone or changed."""
        self.reconcile_many({folder: current_names})

    def reconcile_many(self, by_folder: dict, stat=None) -> None:
        """Reconcile several directories in one pass over the manifest, with one flush."""
        wanted = {}  # both sides through canonical_path_key
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
                st = (stat or os.stat)(full_path)
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
        """Evict one cache entry, valid or not; in a loop pass `flush=False` and save() once after."""
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
        """Delete every texture and geometry thumbnail directory and reset the manifest."""
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
    """File's filters: name text, favourites, kind - its own role numbers, not the assets'."""

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._name_filter = ""
        self._favorites_only = False
        self._kind_filter = ""

    def set_name_filter(self, text: str) -> None:
        if (text or "") == self._name_filter:
            return
        self._name_filter = text or ""
        self.refilter()

    def set_favorites_only(self, enabled: bool) -> None:
        if enabled == self._favorites_only:
            return
        self._favorites_only = enabled
        self.refilter()

    def watched_roles(self):
        """Exactly what filterAcceptsRow reads: the display name, favourite and kind."""
        watched = {QtCore.Qt.ItemDataRole.DisplayRole}
        model = self.sourceModel()
        for name in ("FavoriteRole", "KindRole"):
            role = getattr(model, name, None)
            if role is not None:
                watched.add(role)
        return watched

    def set_kind_filter(self, kind) -> None:
        """Show only rows of one locations.KIND_* value, or of every kind for None."""
        if (kind or "") == self._kind_filter:
            return
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
            kind_role = getattr(model, "KindRole", None)  # no role, no match
            if kind_role is None:
                return False
            if index.data(kind_role) != self._kind_filter:
                return False
        if self._name_filter:
            name = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
            if self._name_filter.lower() not in name.lower():
                return False
        return True
