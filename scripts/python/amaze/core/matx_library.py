"""The online browser model: rows from the sources, on MaterialLibrary's role numbers."""

from __future__ import annotations

import functools
import math
import os

from amaze.helpers import hostos
import json
import hashlib

from PySide6 import QtCore, QtGui

from amaze.core import category, debug, matx_sources, renderers, sidebar_model, thumbnails, workers
from amaze.core import grid_engine

ONLINE_FACE = "face_online"    # T12: an online material with no picture
PREVIEW_DIR_NAME = "matx_previews"    # a NAME only - its folder is resolved per call in preview_cache(), like CATALOGUE_NAME below


from amaze.core.multifilterproxy_model import split_search  # noqa: E402 - re-exported; callers and tests import it from here


def preview_cache() -> str:
    """Where downloaded previews are cached right now; local, never the library folder."""
    return os.path.join(hostos.cache_root(), PREVIEW_DIR_NAME)


def _preview_crc(record):
    """A hosted picture's CRC, in its tile key and cache name, so a re-render replaces both."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    return (payload.get("preview") or {}).get("crc")


SECTION_TILE_LABELS = {"gradient": "Color", "cop": "Node",
                       "code": "Code", "file": "File"}    # a store tile's subtitle per section, equal to the sections' own labels

CATALOGUE_NAME = "matx_catalogue_v3.json"    # the on-disk catalogue; _v3 is the record shape; its path resolves per call

_LEGACY_CATALOGUE_NAMES = ["matx_catalogue.json",
                           "matx_catalogue_v2.json"]    # older-shape filenames, removed when the model is created


def catalogue_cache() -> str:
    """Where the on-disk catalogue is right now."""
    return os.path.join(hostos.cache_root(), CATALOGUE_NAME)


def _purge_legacy_caches():
    for name in _LEGACY_CATALOGUE_NAMES:
        path = os.path.join(hostos.cache_root(), name)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


CATALOGUE_CAP = 4000    # records requested from each source; none has more today ▸r/matx-source-quirks


class _CatalogueWorker(QtCore.QThread):
    """Every source's whole catalogue off the UI thread, ~3600 records (SimReady 1705), no paging."""

    done = QtCore.Signal(object, object, int)   # (records, errors, generation)
    progressed = QtCore.Signal(int, int, int)    # (sources listed, sources, generation): for the progress bar

    def __init__(self, sources, generation, previous=()):
        super().__init__()
        self._sources = list(sources)
        self._generation = generation
        self._previous = list(previous)    # the last full listing, which a source may reuse

    def run(self):
        records, errors = [], []
        self.progressed.emit(0, len(self._sources), self._generation)
        for listed, src in enumerate(self._sources, 1):
            if self.isInterruptionRequested():
                return    # on quit: no `done`, or a partial listing is cached as complete
            try:
                src.remember([r for r in self._previous if r.source == src.name])
            except Exception as exc:                    # noqa: BLE001
                debug.event("online", "last listing not reused - reading "    # costs time only
                            "it all", source=src.name, error=str(exc))
            try:
                found = src.list_materials(limit=CATALOGUE_CAP)
                if len(found) >= CATALOGUE_CAP:
                    debug.event("online", "a source filled the catalogue "
                                "cap - anything past it is not listed",
                                source=src.name, cap=CATALOGUE_CAP)
                records.extend(found)
                if getattr(src, "preview_error", ""):    # tiles listed, pictures not: never cached
                    errors.append("%s: %s" % (src.name, src.preview_error))
            except Exception as exc:                    # noqa: BLE001
                errors.append("%s: %s: %s"    # the MESSAGE, not just the type - the reason is what makes a missing source diagnosable
                              % (src.name, type(exc).__name__, exc))
            self.progressed.emit(listed, len(self._sources), self._generation)
        try:
            self.done.emit(records, errors, self._generation)
        except Exception:                               # noqa: BLE001
            pass    # nothing to report to (the model may be gone); `finished` still clears the loading flag


class _PreviewWorker(QtCore.QThread):
    """Writes each preview's file by URL or callable reader, checks it reads, and reports its key."""

    ready = QtCore.Signal(object)           # (key): its file is written and reads
    failed = QtCore.Signal(object)          # (key): the job produced no picture
    attempted = QtCore.Signal()             # per job, success OR failure

    def __init__(self, jobs):
        super().__init__()
        self._jobs = list(jobs)             # [(key, url_or_reader, cache_path)]

    def run(self):
        for key, fetch, path in self._jobs:
            if self.isInterruptionRequested():
                return    # on quit: the remaining pictures are not fetched
            try:
                if not os.path.exists(path):
                    if callable(fetch):    # an Amaze tile's thumbnail is one ranged read of a package member, not a URL
                        fetch(path)
                    else:
                        matx_sources.download(fetch, path)
                image = QtGui.QImage(path)
                if image.isNull():
                    try:    # a file that does not decode is removed, or it is never re-fetched
                        os.remove(path)
                    except OSError:
                        pass
                    debug.event("online", "preview did not decode",
                                url=getattr(fetch, "label", None)    # a reader has a `label` - str() of a lambda says nothing useful
                                or str(fetch), path=path)
                    self.failed.emit(key)
                else:
                    self.ready.emit(key)
            except Exception as exc:
                debug.exception("preview download", exc,
                                url=getattr(fetch, "label", None)
                                or str(fetch), path=path)
                self.failed.emit(key)
            finally:
                self.attempted.emit()    # updates the progress bar - emitted even on failure, or a timed-out preview stops it below 100%


class MatxOnlineLibrary(grid_engine.GridEngine,
                       QtCore.QAbstractTableModel):
    """Rows = materials available online, from one source at a time."""

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "RendererLabelRole",
    }
    GRID_ROWS = ("_records",)

    IdRole = QtCore.Qt.ItemDataRole.UserRole            # 256 - the same role numbers as MaterialLibrary
    CategoryRole = QtCore.Qt.ItemDataRole.UserRole + 1  # 257
    FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 2  # 258
    RendererRole = QtCore.Qt.ItemDataRole.UserRole + 3  # 259
    TagRole = QtCore.Qt.ItemDataRole.UserRole + 4       # 260
    DateRole = QtCore.Qt.ItemDataRole.UserRole + 5      # 261
    RendererLabelRole = QtCore.Qt.ItemDataRole.UserRole + 6  # 262

    progress_changed = QtCore.Signal(int, int)    # (done, total) preview downloads for the thin bar - previews load as tiles scroll into view

    def __init__(self, parent=None, preferences=None):
        super().__init__(parent)
        _purge_legacy_caches()
        self.preferences = preferences
        self._sources = matx_sources.all_sources()
        self._source = self._sources[0]
        self._all = []           # every record, every source (cached)
        self._records = []       # the filtered view actually shown
        self._key_rows = {}      # preview key -> row (looked up when a preview loads)
        self._search = ""
        self._source_filter = None   # show only this source (View submenu)
        self._kind_filter = None     # the online eye's kind (None = All); session-held
        self._generation = 0
        self._loaded = False
        self._loading = False
        self._workers = []
        # a QThread destroyed while running crashes Houdini; shutdown() runs at aboutToQuit
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)
        self._error = ""
        self._requested = set()      # keys already requested
        self._hosted = {}            # key -> whether its hosted picture may still be requested this session
        self._preview_total = 0      # preview downloads queued in this batch
        self._preview_done = 0       # ...and attempted (ok or failed)
        self._pending = []           # records awaiting the next dispatch
        self._pending_scheduled = False
        self._preview_workers = []   # bounded download pool
        thumbnails.signals.ready.connect(self._on_preview_ready)    # the module's `signals` object, not the engine a reload replaces

    @property
    def sources(self):
        return self._sources

    def source_for(self, record):
        """The online source `record` came from, by name, or None."""
        return next((source for source in self._sources
                     if source.name == record.source), None)

    @property
    def source(self):
        return self._source

    @property
    def error(self):
        """Last network error, empty when none."""
        return self._error

    def set_search(self, text):
        """Filter the current source's materials locally by title, category and tags."""
        text = (text or "").strip()
        if text == self._search:
            return
        self._search = text
        self._apply_filter()

    def set_source(self, source_name):
        """Show only this source from the next `reload`, which opening the online view always calls."""
        self._source_filter = source_name

    def set_kind_filter(self, section) -> None:
        """Narrow the grid to one tile kind by section key; None shows all."""
        if section == self._kind_filter:
            return
        self._kind_filter = section
        self._apply_filter()

    def kind_filter(self):
        """The section key the grid is narrowed to; None for all."""
        return self._kind_filter

    @staticmethod
    def _record_kind(r) -> str:
        if getattr(r, "kind", "") == "amazepkg":
            return str((r.payload or {}).get("section") or "material")
        return "material"

    def _in_source(self, r):
        return self._source_filter is None or r.source == self._source_filter

    def _apply_filter(self):
        rows = [r for r in self._all if self._in_source(r)]
        if self._kind_filter:
            rows = [r for r in rows
                    if self._record_kind(r) == self._kind_filter]
        needle, tags_only = split_search(self._search)
        if needle:
            def hit(r):
                if tags_only:
                    return any(needle in str(tag).lower()
                               for tag in (r.tags or []))
                hay = "%s %s %s" % (
                    r.title, r.category, " ".join(r.tags or [])
                )
                return needle in hay.lower()
            rows = [r for r in rows if hit(r)]
        debug.event("online", "filtered", needle=needle,
                    source=self._source_filter, shown=len(rows),
                    total=len(self._all))
        self.beginResetModel()
        self._records = rows
        self.order_rows()    # in the grid's order before any view sees them; maps the keys
        self.endResetModel()    # no eager queueing after this - data() requests what it paints

    def rows_reordered(self) -> None:
        self._key_rows = {
            self._preview_key(r): i for i, r in enumerate(self._records)
        }

    def reload(self, force=False):
        """Show the catalogue from memory or the disk cache, refreshing in the background."""
        if self._loaded and not force:
            self._apply_filter()
            return

        if not self._loaded:    # instant path - the last fetch from disk; the refresh below replaces it if the remote changed
            cached = self._load_cache()
            if cached:
                self._all = cached
                self._loaded = True
                self._apply_filter()

        if self._loading:
            return
        self._loading = True
        self._generation += 1
        worker = _CatalogueWorker(    # Refresh is the user asking for a new listing, so it reuses nothing
            self._sources, self._generation, () if force else self._all)
        worker.done.connect(self._on_catalogue)
        worker.progressed.connect(self._on_catalogue_progress)
        worker.finished.connect(lambda w=worker: self._retire(w))
        self._workers.append(worker)
        worker.start()

    def _load_cache(self):
        try:
            with open(catalogue_cache(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return [matx_sources.MatxRecord.from_dict(d)
                    for d in data.get("records", [])]
        except (OSError, ValueError):
            return None

    def _save_cache(self, records) -> None:
        path = catalogue_cache()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            hostos.write_json_atomic(
                path, {"records": [r.to_dict() for r in records]},
                indent=None)
        except OSError as exc:
            debug.event("online", "catalogue cache not written",    # an event: the browser works either way
                        error=str(exc))

    def _on_catalogue_progress(self, listed, sources, generation):
        """The listing's steps on the thin bar, one per source, unless preview downloads are using it."""
        if generation == self._generation and not self._preview_total:
            self.progress_changed.emit(listed, sources)

    def _on_catalogue(self, records, errors, generation):
        self._loading = False
        if generation != self._generation:
            return
        partial = bool(errors)    # a partial fetch must not overwrite a fuller disk cache - keep whichever has more
        if not records or (
            partial and self._all and len(records) < len(self._all)
        ):
            self._error = ", ".join(errors) if errors else ""
            if errors:
                debug.event("online", "sources unavailable", errors=errors)
            return
        def _sig(recs):    # content signature: uid, title and preview_url
            return [(r.source, r.uid, r.title, r.preview_url, _preview_crc(r)) for r in recs]

        changed = _sig(records) != _sig(self._all)
        self._all = records
        self._loaded = True
        if partial:
            debug.note(    # shown this session, never cached; one note explains a short list
                "could not reach %d of the online material sites, so "
                "this list is missing whatever they hold. What loaded "
                "is shown but not kept, so reopening Online Materials "
                "tries them again." % len(errors), errors=errors)
        else:
            self._save_cache(records)
            self._prune_previews(records)
        by_source = {}
        for r in records:
            by_source[r.source] = by_source.get(r.source, 0) + 1
        debug.event("online", "catalogue loaded", total=len(records),
                    by_source=by_source, errors=errors, changed=changed)
        self._error = ", ".join(errors) if errors else ""
        if changed or not self._records:    # only rebuild if the data changed - a no-change background refresh must not reset the view
            self._apply_filter()

    def shutdown(self) -> None:
        """Stop every worker and wait for it; safe to call twice or when nothing runs."""
        workers.stop(self._workers, "online", cancel=False)    # its workers check only isInterruptionRequested
        self._workers = []
        self._loading = False

    def _retire(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
        if isinstance(worker, _CatalogueWorker):
            # `finished` is emitted even when run() raises before `done`
            self._loading = False

    @staticmethod
    def _preview_key(record):
        crc = _preview_crc(record)
        return ("matx", record.source, record.uid) + (() if crc is None else (crc,))

    def _cache_path(self, record, hosted=True):
        crc = _preview_crc(record) if hosted else None
        digest = hashlib.md5(
            ("%s/%s%s" % (record.source, record.uid, "" if crc is None else "#%d" % crc))
            .encode("utf-8")
        ).hexdigest()
        # the source name is sanitised; the digest keeps the raw value
        return os.path.join(
            preview_cache(), hostos.safe_filename(str(record.source)),
            digest + ".png")

    def _prune_previews(self, records) -> None:
        """Remove each listed source's cached pictures that no record names; a re-render leaves one unused."""
        keep = {}
        for rec in records:
            for path in (self._cache_path(rec), self._cache_path(rec, hosted=False)):
                folder, name = os.path.split(path)
                keep.setdefault(folder, set()).add(name)
        removed = 0
        for folder in keep:
            try:
                with os.scandir(folder) as found:
                    stale = [entry.path for entry in found if entry.name.endswith(".png")
                             and entry.name not in keep[folder]]    # a download in progress has no .png name
            except OSError:
                continue
            for path in stale:
                try:
                    hostos.remove_file(path)
                    removed += 1
                except OSError as exc:
                    debug.event("online", "stale preview not removed", path=path, error=str(exc))
        if removed:
            debug.event("online", "stale previews removed", count=removed)

    def _icon_size(self):
        try:
            return int(self.preferences.rendersize)
        except (AttributeError, TypeError, ValueError):
            return 256

    def _parallel(self) -> int:
        try:
            return max(1, min(16, int(
                self.preferences.matx_parallel_downloads
            )))
        except (AttributeError, TypeError, ValueError):
            return 8

    def _flush_pending(self):
        """Dispatch accumulated requests across a bounded pool of workers."""
        self._pending_scheduled = False
        limit = self._parallel()
        while self._pending and len(self._preview_workers) < limit:
            slots = limit - len(self._preview_workers)
            size = max(1, math.ceil(len(self._pending) / slots))
            chunk = self._pending[:size]
            self._pending = self._pending[size:]
            self._start_fetches(chunk)

    def _preview_batch_done(self, worker):
        if worker in self._preview_workers:
            self._preview_workers.remove(worker)
        self._retire(worker)
        # A finished worker frees a slot - dispatch more pending requests.
        if self._pending and not self._pending_scheduled:
            self._pending_scheduled = True
            QtCore.QTimer.singleShot(0, self._flush_pending)

    def _start_fetches(self, jobs) -> None:
        """One worker for these (key, fetch, path) jobs: each writes its picture file."""
        self._preview_total += len(jobs)
        self.progress_changed.emit(self._preview_done, self._preview_total)
        worker = _PreviewWorker(jobs)
        worker.ready.connect(self._on_fetched)
        worker.failed.connect(self._on_preview_failed)
        worker.attempted.connect(self._on_preview_attempted)
        worker.finished.connect(lambda w=worker: self._preview_batch_done(w))
        self._workers.append(worker)
        self._preview_workers.append(worker)
        worker.start()

    def _fetched(self, key, fetch, path: str, hosted: bool = False) -> grid_engine.Picture:
        """The picture file at `path`, fetched by `fetch` the first time it is asked for; none until then."""
        if os.path.exists(path) and not thumbnails.engine.is_missing(key):    # one that does not read
            return grid_engine.Picture(((path, key, False),))    # goes to the worker, which removes it
        if key not in self._requested:    # a fetch that failed keeps its marker: it is not tried again
            self._requested.add(key)
            if hosted:    # its failure gives way to the record's next picture
                self._hosted[key] = True
            self._pending.append((key, fetch, path))
            if not self._pending_scheduled:
                self._pending_scheduled = True
                QtCore.QTimer.singleShot(0, self._flush_pending)
        return grid_engine.Picture()

    def _on_preview_attempted(self):
        """One preview download finished: advance the bar, reset it when all queued ones are done."""
        self._preview_done += 1
        self.progress_changed.emit(self._preview_done, self._preview_total)
        if self._preview_done >= self._preview_total and not self._pending:
            self._preview_done = 0
            self._preview_total = 0

    def _on_fetched(self, key) -> None:
        """A picture file was written: its tile shows it, read as every other picture file is."""
        self._requested.discard(key)
        row = self._key_rows.get(key)
        if row is not None and 0 <= row < len(self._records):
            self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def _on_preview_failed(self, key):
        """A hosted picture that did not download: the next paint uses the tile's own face."""
        if not self._hosted.get(key):
            return    # any other failure keeps its marker, or every repaint would fetch it again
        self._hosted[key] = False
        self._requested.discard(key)
        row = self._key_rows.get(key)
        if row is not None and 0 <= row < len(self._records):
            self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def _on_preview_ready(self, key):
        try:
            if not (isinstance(key, tuple) and key and key[0] == "matx"):
                return
        except Exception:
            return
        row = self._key_rows.get(key)
        if row is None or not 0 <= row < len(self._records):
            return
        self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def rowCount(self, parent=None):
        return len(self._records)

    def record(self, row):
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def tile_picture(self, row: int, face: str = "") -> grid_engine.Picture:
        """Its store or hosted picture, else what its record paints, its preview, else its generic icon."""
        from amaze.core import code_library, cop_library, gradient_library, matx_icon
        rec = self._records[row]
        key, source = self._preview_key(rec), self.source_for(rec)
        reader = functools.partial(source.read_thumb_to, rec) if source is not None else None
        if reader is not None:
            reader.label = str(rec.uid)    # what a failure log names
        if rec.kind == "amazepkg":    # a named member before any drawn placeholder
            entry = (rec.payload.get("entry") or {}).get("record") or {}
            if rec.payload.get("thumb_member") and reader is not None:
                return self._fetched(key, reader, self._cache_path(rec))
            if entry.get("colors"):    # the Color section's own painter
                return grid_engine.Picture(paint=functools.partial(
                    gradient_library.paint_swatch, entry["colors"], entry.get("ramp") or {}), stamp=key)
            if str(entry.get("code") or ""):    # the Code section's own painter
                return grid_engine.Picture(paint=functools.partial(
                    code_library.paint_code_preview, str(entry["code"])), stamp=key)
            cop = rec.payload.get("section") == "cop"
            return grid_engine.Picture(art=cop_library.CopLibrary.TILE_FACE if cop else ONLINE_FACE)
        if _preview_crc(rec) is not None and reader is not None and self._hosted.get(key, True):
            return self._fetched(key, reader, self._cache_path(rec), hosted=True)    # Amaze's render
        if rec.kind == "values":    # drawn from the numbers
            return grid_engine.Picture(paint=functools.partial(
                matx_icon.render, rec.payload.get("values", {}), self._icon_size(), rec.source), stamp=key)
        if not rec.preview_url:    # a source that ships no picture
            return grid_engine.Picture(art=ONLINE_FACE)
        url = rec.preview_url.replace("format=webp", "format=png")    # Qt reads no WebP ▸r/matx-source-quirks
        return self._fetched(key, url, self._cache_path(rec, hosted=False))    # never the hosted file's path

    def row_data(self, row, role):
        rec = self._records[row]

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return rec.title
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            bits = [rec.title]
            if rec.author:
                bits.append("by " + rec.author)
            if rec.licence:
                bits.append(rec.licence)
            if rec.kind == "values":
                bits.append("measured values - no textures")
            return "\n".join(bits)
        if role in (self.RendererLabelRole, self.TileSubtitleRole):
            # the Type column: the source, or what a store tile is
            if rec.kind == "amazepkg":
                section = str(rec.payload.get("section") or "")
                if section == "material":
                    row = ((rec.payload.get("entry") or {})
                           .get("record") or {})
                    return renderers.label(row.get("renderer")) or "Material"
                return SECTION_TILE_LABELS.get(section, "Amaze")
            return rec.source if rec.kind == "package" else rec.source + " (values)"
        if role == self.RendererRole:
            return renderers.INTERMEDIATE.key    # what an import becomes, so the Filter treats it like library rows
        if role == self.CategoryRole:
            return [rec.category]
        if role == self.TagRole:
            return rec.tags
        if role == self.FavoriteRole:
            return False
        if role == self.IdRole:
            return str(rec.uid)
        if role == self.DateRole:
            return ""
        return None

    def categories(self):
        """The selected source's distinct categories for the sidebar, from the unfiltered rows."""
        seen = set()
        for rec in self._all:
            if rec.category and self._in_source(rec):
                seen.add(rec.category)
        return sorted(seen, key=str.lower)


class MatxSidebarModel(sidebar_model.SidebarModel):
    """The online browser's sidebar: row 0 is `All`, the rest the selected source's categories."""

    def __init__(self, online_model, parent=None):
        super().__init__(parent)
        self._online = online_model
        self._rows = ["All"]
        online_model.modelReset.connect(self.refresh)
        self.refresh()

    def refresh(self):
        rows = ["All"] + self._online.categories()
        if rows != self._rows:
            self.beginResetModel()
            self._rows = rows
            self._forget_rows()
            self.endResetModel()

    def top_keys(self) -> list:
        """The selected source's categories; no row moves, they follow the source."""
        return self._rows[1:]

    def data(self, index, role=0):
        if index.column():
            return self.color_cell(index, role)
        if role not in (QtCore.Qt.ItemDataRole.DisplayRole, category.SIDEBAR_KEY_ROLE):
            return None    # the style asks for more roles per row on every repaint
        key = super().data(index, category.SIDEBAR_KEY_ROLE)
        if key is None or role == category.SIDEBAR_KEY_ROLE:
            return key
        return key or self._rows[0]    # row 0's label, All
