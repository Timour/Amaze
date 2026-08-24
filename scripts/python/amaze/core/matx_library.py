"""The online browser model: rows from the sources instead of library.json, MaterialLibrary's role numbers so the shared delegate/proxy/grid work untouched, network on a worker thread, and previews riding the shared thumbnail engine (the preview doubles as the imported material's thumbnail)."""

from __future__ import annotations

import math
import os

from amaze.helpers import hostos
import json
import hashlib

from PySide6 import QtCore, QtGui

from amaze.core import debug, matx_icon, matx_sources, thumbnails
from amaze.core import grid_columns

PREVIEW_DIR_NAME = "matx_previews"    # a NAME only - where it lives resolves per call in preview_cache(), like CATALOGUE_NAME below


def split_search(text) -> tuple:
    """(needle, tags_only) from the filter box: a LEADING ":" means tags only (the prefix the Materials box teaches), and a bare ":" is the moment before the tag, not a search - pure and module-level so the edge cases test without a Qt model."""
    needle = (text or "").strip().lower()
    if needle.startswith(":"):
        return needle[1:].strip(), True
    return needle, False


def preview_cache() -> str:
    """Where downloaded previews are cached right now - local only, never the cloud-synced library folder."""
    return os.path.join(hostos.cache_root(), PREVIEW_DIR_NAME)


CATALOGUE_NAME = "matx_catalogue_v3.json"    # the on-disk catalogue that makes Online open instantly; _v3 is the record-shape version (v3: per-tile Amaze records, uid folder/file#id). Its PATH resolves per call - frozen at import it missed both the Preferences cache move and the suite's redirection, one branch from writing the real cache from a test

_LEGACY_CATALOGUE_NAMES = ["matx_catalogue.json",
                           "matx_catalogue_v2.json"]    # older-shape filenames, swept once on first construction so a stale old-shape file never lingers - a v2 file held one tile per PACKAGE, whose payload the v3 import door cannot read


def catalogue_cache() -> str:
    """Where the on-disk catalogue lives right now."""
    return os.path.join(hostos.cache_root(), CATALOGUE_NAME)


def _purge_legacy_caches():
    for name in _LEGACY_CATALOGUE_NAMES:
        path = os.path.join(hostos.cache_root(), name)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def swatch_image(colors, size: int) -> QtGui.QImage:
    """A palette's tile, drawn: equal vertical bands of its own hex colours - the whole preview an online palette needs, no download."""
    image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor("#2d2d2d"))
    good = [c for c in colors if QtGui.QColor(str(c)).isValid()]
    if good:
        band = size / float(len(good))
        painter = QtGui.QPainter(image)
        try:
            for n, colour in enumerate(good):
                painter.fillRect(
                    int(n * band), 0,
                    int((n + 1) * band) - int(n * band), size,
                    QtGui.QColor(str(colour)))
        finally:
            painter.end()
    return image


class _CatalogueWorker(QtCore.QThread):
    """Fetches EVERY source's full catalogue off the UI thread - ~1800 records over FIVE sources (GPUOpen 454 and PolyHaven 783 by API, Amaze by ranged manifest reads, PhysicallyBased 86 and RGL 62 from shipped tables in ~1ms); no paging, one flat list the filter box narrows."""

    done = QtCore.Signal(object, object, int)   # (records, errors, generation)

    def __init__(self, sources, generation):
        super().__init__()
        self._sources = list(sources)
        self._generation = generation

    def run(self):
        records, errors = [], []
        for src in self._sources:
            try:
                records.extend(src.list_materials(limit=1000))
            except Exception as exc:                    # noqa: BLE001
                errors.append("%s: %s: %s"    # the MESSAGE, not just the type - the reason is what makes a missing source diagnosable
                              % (src.name, type(exc).__name__, exc))
        try:
            self.done.emit(records, errors, self._generation)
        except Exception:                               # noqa: BLE001
            pass    # nothing to report to (the model may be gone); `finished` still clears the loading flag


class _PreviewWorker(QtCore.QThread):
    """Fetches preview images - a URL download or a callable reader - and reports them by thumbnail-engine key."""

    ready = QtCore.Signal(object, object)   # (key, QImage)
    attempted = QtCore.Signal()             # per job, success OR failure

    def __init__(self, jobs):
        super().__init__()
        self._jobs = list(jobs)             # [(key, url_or_reader, cache_path)]

    def run(self):
        for key, fetch, path in self._jobs:
            try:
                if not os.path.exists(path):
                    if callable(fetch):    # an Amaze tile's thumbnail is one ranged member read, not a URL
                        fetch(path)
                    else:
                        matx_sources.download(fetch, path)
                image = QtGui.QImage(path)
                if image.isNull():
                    try:    # a file that does not decode must NOT stay on disk - the existence check is the only gate on re-fetching, so keeping it blanks the tile permanently
                        os.remove(path)
                    except OSError:
                        pass
                    debug.event("online", "preview did not decode",
                                url=getattr(fetch, "label", None)    # a reader carries its label - str() of a lambda names nothing
                                or str(fetch), path=path)
                else:
                    self.ready.emit(key, image)
            except Exception as exc:
                debug.exception("preview download", exc,
                                url=getattr(fetch, "label", None)
                                or str(fetch), path=path)
            finally:
                self.attempted.emit()    # drives the bar - must fire even on failure, or a timed-out preview stalls it short of 100%


class MatxOnlineLibrary(grid_columns.GridColumnsMixin,
                       QtCore.QAbstractTableModel):
    """Rows = materials available online, from one source at a time."""

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "RendererLabelRole",
    }

    IdRole = QtCore.Qt.ItemDataRole.UserRole            # 256 - same role NUMBERS as MaterialLibrary, the shared delegate and proxy must line up; held equal by test_role_numbers
    CategoryRole = QtCore.Qt.ItemDataRole.UserRole + 1  # 257
    FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 2  # 258
    RendererRole = QtCore.Qt.ItemDataRole.UserRole + 3  # 259
    TagRole = QtCore.Qt.ItemDataRole.UserRole + 4       # 260
    DateRole = QtCore.Qt.ItemDataRole.UserRole + 5      # 261
    RendererLabelRole = QtCore.Qt.ItemDataRole.UserRole + 6  # 262

    progress_changed = QtCore.Signal(int, int)    # (done, total) preview downloads for the thin bar - rolling, previews load as tiles scroll in

    def __init__(self, parent=None, preferences=None):
        super().__init__(parent)
        _purge_legacy_caches()
        self.preferences = preferences
        self._sources = matx_sources.all_sources()
        self._source = self._sources[0]
        self._all = []           # every record, every source (cached)
        self._records = []       # the filtered view actually shown
        self._key_rows = {}      # preview key -> row (delivery lookup)
        self._search = ""
        self._source_filter = None   # show only this source (View submenu)
        self._generation = 0
        self._loaded = False
        self._loading = False
        self._workers = []
        # a QThread destroyed while still running takes Houdini with it - shutdown() is idempotent and wired to aboutToQuit
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)
        self._error = ""
        self._requested = set()      # keys already asked for
        self._preview_total = 0      # preview downloads queued this burst
        self._preview_done = 0       # ...and attempted (ok or failed)
        self._pending = []           # records awaiting the next dispatch
        self._pending_scheduled = False
        self._preview_workers = []   # bounded download pool
        thumbnails.signals.ready.connect(self._on_preview_ready)    # through the RELAY, not the engine: the singleton is replaced on module reload (thumbnails._EngineSignals)

    @property
    def sources(self):
        return self._sources

    @property
    def source(self):
        return self._source

    @property
    def error(self):
        """Last network error ('' when fine) - the panel shows an empty grid when offline, no dialog: dialogs confirm actions, they don't announce outcomes."""
        return self._error

    def set_search(self, text):
        """Filter the current source's materials locally (title, category, tags) - no API round-trip; the SOURCE is picked elsewhere, the search narrows within it."""
        text = (text or "").strip()
        if text == self._search:
            return
        self._search = text
        self._apply_filter()

    def set_source(self, source_name):
        """Show only one source's materials; None shows nothing until one is picked - the sidebar follows via the model reset."""
        self._source_filter = source_name
        self._apply_filter()

    def _in_source(self, r):
        return self._source_filter is None or r.source == self._source_filter

    def _apply_filter(self):
        rows = [r for r in self._all if self._in_source(r)]
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
        self._key_rows = {
            self._preview_key(r): i for i, r in enumerate(rows)
        }
        self.endResetModel()    # no eager queueing after this - data() asks for what it paints

    def reload(self, force=False):
        """Show the catalogue fast: in memory → re-filter; else the DISK cache instantly with a background network refresh - only a cache miss waits on the fetch."""
        if self._loaded and not force:
            self._apply_filter()
            return

        if not self._loaded:    # instant path - the last fetch off disk; the refresh below replaces it if the remote changed
            cached = self._load_cache()
            if cached:
                self._all = cached
                self._loaded = True
                self._apply_filter()

        if self._loading:
            return
        self._loading = True
        self._generation += 1
        worker = _CatalogueWorker(self._sources, self._generation)
        worker.done.connect(self._on_catalogue)
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
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"records": [r.to_dict() for r in records]}, handle)
        except OSError as exc:
            debug.event("online", "catalogue cache not written",    # an EVENT: internal, the browser works either way - the unreachable-source line below stays a note because it is about what the user sees
                        error=str(exc))

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
        def _sig(recs):    # content identity, not just count: uid+title+preview_url covers everything a tile shows without hashing payloads
            return [(r.source, r.uid, r.title, r.preview_url) for r in recs]

        changed = _sig(records) != _sig(self._all)
        self._all = records
        self._loaded = True
        if partial:
            debug.note(    # shown this session, never the accepted BASELINE (a cold-cache partial once became permanent - PartialCatalogueTest); ONE note, the sentence that explains a SHORT list
                "could not reach %d of the online material sites, so "
                "this list is missing whatever they hold. What loaded "
                "is shown but not kept, so reopening Online Materials "
                "tries them again." % len(errors), errors=errors)
        else:
            self._save_cache(records)
        by_source = {}
        for r in records:
            by_source[r.source] = by_source.get(r.source, 0) + 1
        debug.event("online", "catalogue loaded", total=len(records),
                    by_source=by_source, errors=errors, changed=changed)
        self._error = ", ".join(errors) if errors else ""
        if changed or not self._records:    # only rebuild if the data changed - a no-change background refresh must not disturb the screen
            self._apply_filter()

    def shutdown(self) -> None:
        """Stop every worker and WAIT for it - called on application quit, safe to call twice or when nothing runs."""
        for worker in list(self._workers):
            try:
                if not worker.isRunning():
                    continue
                worker.requestInterruption()
                if not worker.wait(3000):    # bounded: a stuck socket must not hold up the quit
                    worker.terminate()
                    worker.wait(500)
            except RuntimeError:
                pass            # already destroyed by Qt - nothing to do
        self._workers = []
        self._loading = False

    def _retire(self, worker):
        if worker in self._workers:
            self._workers.remove(worker)
        if isinstance(worker, _CatalogueWorker):
            # `finished` fires even when run() dies before `done` - clearing _loading only in the done handler once left it stuck True, a browser that silently never refreshed again
            self._loading = False

    @staticmethod
    def _preview_key(record):
        return ("matx", record.source, record.uid)

    def _cache_path(self, record):
        digest = hashlib.md5(
            ("%s/%s" % (record.source, record.uid)).encode("utf-8")
        ).hexdigest()
        # the source name is SANITISED like every path-bound record field (it comes off the on-disk catalogue); the digest keeps the raw value, so two sources that sanitise alike stay apart
        return os.path.join(
            preview_cache(), hostos.safe_filename(str(record.source)),
            digest + ".png")

    def _icon_size(self):
        try:
            return int(self.preferences.rendersize)
        except (AttributeError, TypeError, ValueError):
            return 256

    def _preview(self, rec):
        """Cached preview, requested lazily from data() on a miss - the old eager first-120-rows queue left later rows imageless and evictions permanent; one row queues here, the batch coalesces on a zero-timer."""
        key = self._preview_key(rec)
        image = thumbnails.engine.peek(key)
        if image is not None:
            return image
        if key in self._requested:
            return None

        if rec.preview_url:    # disk-cache hit decodes here and now - a seen preview must not need a worker (rebrowsing once re-downloaded everything); the texture cache's main-thread hit shape
            path = self._cache_path(rec)
            if os.path.exists(path):
                cached = QtGui.QImage(path)
                if not cached.isNull():
                    thumbnails.engine.deposit(key, cached)
                    return cached

        self._requested.add(key)
        self._pending.append(rec)
        if not self._pending_scheduled:
            self._pending_scheduled = True
            QtCore.QTimer.singleShot(0, self._flush_pending)
        return None

    def _parallel(self) -> int:
        try:
            return max(1, min(16, int(
                self.preferences.matx_parallel_downloads
            )))
        except (AttributeError, TypeError, ValueError):
            return 8

    def _flush_pending(self):
        """Dispatch accumulated requests across a BOUNDED POOL - previews are latency-bound so concurrency scales near-linearly (32 PolyHaven: 1 worker 220ms each, 8 workers 42ms; serial was a 5-10min crawl), and bounded against a per-paint thread explosion and for being a polite client of free APIs."""
        self._pending_scheduled = False
        limit = self._parallel()
        while self._pending and len(self._preview_workers) < limit:
            slots = limit - len(self._preview_workers)
            size = max(1, math.ceil(len(self._pending) / slots))
            chunk = self._pending[:size]
            self._pending = self._pending[size:]
            self._queue_previews(chunk)

    def _preview_batch_done(self, worker):
        if worker in self._preview_workers:
            self._preview_workers.remove(worker)
        self._retire(worker)
        # A finished worker frees a slot - keep the pool fed.
        if self._pending and not self._pending_scheduled:
            self._pending_scheduled = True
            QtCore.QTimer.singleShot(0, self._flush_pending)

    def _queue_previews(self, records):
        jobs = []
        for rec in records:
            key = self._preview_key(rec)
            if thumbnails.engine.peek(key) is not None:
                continue
            if rec.kind == "amazepkg":
                colors = rec.payload.get("colors")
                if colors:
                    try:    # drawn like the values branch below, same marker semantics
                        thumbnails.engine.deposit(
                            key, swatch_image(colors, self._icon_size()))
                    except Exception as exc:              # noqa: BLE001
                        debug.event("online", "swatch not drawn",
                                    title=rec.title, error=str(exc))
                        continue
                    self._requested.discard(key)
                    continue
                member = rec.payload.get("thumb_member")
                source = next((s for s in self.sources
                               if s.name == rec.source), None)
                if member and source is not None:
                    reader = (lambda path, s=source, r=rec:
                              s.read_thumb_to(r, path))
                    reader.label = str(rec.uid)    # folder/file#id - what a failure log names instead of a lambda repr
                    jobs.append((key, reader, self._cache_path(rec)))
                continue    # no colours, no thumbnail member (a snippet): the engine's no-preview tile stands
            if rec.kind == "values":
                try:    # no render to download - the tile is DRAWN from the measured numbers, cheap enough on the spot, no worker
                    thumbnails.engine.deposit(
                        key,
                        matx_icon.render(
                            rec.payload.get("values", {}),
                            self._icon_size(),
                            rec.source,
                        ),
                    )
                except Exception as exc:
                    debug.event("online", "tile icon not drawn",
                                title=rec.title, error=str(exc))
                    continue    # a FAILED draw keeps its marker - releasing it re-queued the failing draw every repaint; blank for the session, a panel reopen retries once
                self._requested.discard(key)    # drawing is cheap: an evicted icon redraws on the next paint - don't hold the marker
                continue
            if not rec.preview_url:
                continue
            jobs.append((key, rec.preview_url, self._cache_path(rec)))
        if not jobs:
            return
        self._preview_total += len(jobs)
        self.progress_changed.emit(self._preview_done, self._preview_total)
        worker = _PreviewWorker(jobs)
        worker.ready.connect(self._deposit_preview)
        worker.attempted.connect(self._on_preview_attempted)
        worker.finished.connect(lambda w=worker: self._preview_batch_done(w))
        self._workers.append(worker)
        self._preview_workers.append(worker)
        worker.start()

    def _on_preview_attempted(self):
        """One preview download finished (ok or failed) - advance the bar, and on a drained burst reset so the next scroll starts a fresh 0..N."""
        self._preview_done += 1
        self.progress_changed.emit(self._preview_done, self._preview_total)
        if self._preview_done >= self._preview_total and not self._pending:
            self._preview_done = 0
            self._preview_total = 0

    def _deposit_preview(self, key, image):
        thumbnails.engine.deposit(key, image)
        self._requested.discard(key)    # the RAM budget can still evict - drop the marker so the next paint re-asks (the disk cache answers)

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

    def data(self, index, role=0):
        if index.column() > 0:    # LATER COLUMNS are the table's (QTableView migration step 1); column 0 falls through unchanged, so grid mode cannot tell
            return self.column_data(index, role)
        if not index.isValid() or index.row() >= len(self._records):
            return None
        rec = self._records[index.row()]

        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return rec.title
        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            return self._preview(rec)
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            from amaze.helpers import ui_helpers

            bits = [rec.title]
            if rec.author:
                bits.append("by " + rec.author)
            if rec.licence:
                bits.append(rec.licence)
            if rec.kind == "values":
                bits.append("measured values - no textures")
            return ui_helpers.tooltip_text("\n".join(bits))
        if role == self.RendererLabelRole:
            # the Type column: the source, plus that value-sources produce a preset rather than a textured material
            return rec.source if rec.kind == "package" else rec.source + " (values)"
        if role == self.RendererRole:
            return "Karma"    # what an import becomes - so the Karma renderer filter behaves the same over the online grid as over the library
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
        """The SELECTED source's distinct categories for the sidebar - from _all, not the filtered view, so the list doesn't shrink as you type."""
        seen = set()
        for rec in self._all:
            if rec.category and self._in_source(rec):
                seen.add(rec.category)
        return sorted(seen, key=str.lower)


class MatxSidebarModel(QtCore.QAbstractListModel):
    """The online browser's sidebar: row 0 is "All", the rest the SELECTED source's categories - no source suffix, the source is the submenu you came in through."""

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
            self.endResetModel()

    def rowCount(self, parent=None):
        return len(self._rows)

    def category_at(self, row):
        """The category for a row, or None for the "All" row."""
        if 0 <= row < len(self._rows):
            return None if row == 0 else self._rows[row]
        return None

    def data(self, index, role=0):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self._rows[index.row()]
        return None
