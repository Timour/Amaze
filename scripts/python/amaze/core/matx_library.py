"""The online MaterialX browser model.

Serves rows from the online sources (core/matx_sources.py) instead of
library.json, using the SAME role numbers as MaterialLibrary so the
existing delegate, proxy, grid, list mode and search all work untouched -
the browser IS the normal grid with a different model behind it.

Network work happens on a worker thread; the UI thread never blocks.
Preview images ride the shared thumbnail engine, so lazy loading, the RAM
budget and eviction come for free - and the preview doubles as the
imported material's thumbnail, so no shaderball render is needed.
"""

from __future__ import annotations

import math
import os

from amaze.helpers import hostos
import json
import hashlib

from PySide6 import QtCore, QtGui

from amaze.core import debug, matx_icon, matx_sources, thumbnails
from amaze.core import grid_columns

#: The preview cache's folder name. Where it LIVES is resolved per
#: call by preview_cache() below, never frozen at import - the same
#: correction CATALOGUE_NAME got, for the same two reasons stated
#: there. This constant outlived that fix by being the quieter of the
#: pair: a stale catalogue is one file, stale previews are a folder
#: that keeps growing in the location the user thought they left.
PREVIEW_DIR_NAME = "matx_previews"


def split_search(text) -> tuple:
    """(needle, tags_only) from what was typed in the filter box.

    A LEADING ":" MEANS TAGS ONLY - the same prefix the Materials box
    teaches, so the tooltip's promise holds in the online world too. A
    bare ":" is not a search: it is the moment after typing the colon
    and before typing the tag, and narrowing to nothing there would
    empty the grid mid-keystroke.

    Module-level and pure, so the rule can be tested without a Qt
    model - the parsing is the part with the edge cases.
    """
    needle = (text or "").strip().lower()
    if needle.startswith(":"):
        return needle[1:].strip(), True
    return needle, False


def preview_cache() -> str:
    """Where downloaded previews are cached right now (local only -
    never the cloud-synced library folder)."""
    return os.path.join(hostos.cache_root(), PREVIEW_DIR_NAME)

#: The catalogue (all sources' records) cached to disk, so switching to
#: Online Materials shows its categories INSTANTLY instead of waiting
#: ~2-3s for the fetch (GPUOpen's API alone is ~2.2s). Refreshed in the
#: background on every open so it stays current. The _v2 suffix is the
#: cache format version - bumped when the record shape changes (v2
#: dropped the "-<Source>" category suffix and capitalised names), so a
#: stale old cache is simply ignored and re-fetched, never shown.
#:
#: RESOLVED ON EVERY CALL, not once at import. `hostos.cache_root()`
#: answers the user's Preferences cache folder, then $AMAZE_CACHE_DIR,
#: then the OS convention - all three of which can change after this
#: module is imported. As an import-time constant it had two bugs: the
#: user pointing Preferences at another cache folder left the catalogue
#: behind in the old one, and the test suite's cache redirection (set in
#: tests/test_support.py, at ITS import) only landed when this module
#: happened to be imported afterwards. It was not: a fixture panel test
#: read and was one branch away from writing the real 684KB file in
#: ~/Library/Caches/Amaze.
CATALOGUE_NAME = "matx_catalogue_v2.json"

#: Pre-v2 cache filenames, swept once on first construction so a stale
#: old-format file (different record shape, same count - the change check
#: would not refresh it) never lingers on disk.
_LEGACY_CATALOGUE_NAMES = ["matx_catalogue.json"]


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


class _CatalogueWorker(QtCore.QThread):
    """Fetches EVERY source's full catalogue off the UI thread.

    ~1385 records over FOUR sources, of which only two touch the
    network: GPUOpen 454 and PolyHaven 783 are API calls (GPUOpen's is
    the slow one, ~1.6s), while PhysicallyBased 86 and RGL 62 read
    shipped tables in ~1ms. There is no paging: one flat list means
    typing "polyhaven" in the filter box just narrows it, with no
    source-switching machinery."""

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
                # The MESSAGE, not just the type. "GPUOpen (URLError)"
                # cannot be told apart from a dozen causes; the reason
                # is what makes a missing source diagnosable.
                errors.append("%s: %s: %s"
                              % (src.name, type(exc).__name__, exc))
        try:
            self.done.emit(records, errors, self._generation)
        except Exception:                               # noqa: BLE001
            # Nothing to report to (the model may be gone). The
            # `finished` signal still clears the loading flag.
            pass


class _PreviewWorker(QtCore.QThread):
    """Downloads preview images and reports them by thumbnail-engine key."""

    ready = QtCore.Signal(object, object)   # (key, QImage)
    attempted = QtCore.Signal()             # per job, success OR failure

    def __init__(self, jobs):
        super().__init__()
        self._jobs = list(jobs)             # [(key, url, cache_path)]

    def run(self):
        for key, url, path in self._jobs:
            try:
                if not os.path.exists(path):
                    matx_sources.download(url, path)
                image = QtGui.QImage(path)
                if image.isNull():
                    # A file that does not decode must NOT stay on disk.
                    # The existence check above is the only gate on
                    # re-downloading, so a 200 carrying a captive-portal
                    # page (or, before the truncation guard, a short
                    # body) blanked that tile permanently: every later
                    # session found the file, skipped the download, and
                    # decoded null again. Deleting it costs one retry.
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    debug.event("online", "preview did not decode",
                                url=url, path=path)
                else:
                    self.ready.emit(key, image)
            except Exception as exc:
                debug.exception("preview download", exc, url=url, path=path)
            finally:
                # Drives the progress bar - must fire even on failure, or a
                # timed-out preview would stall the bar short of 100%.
                self.attempted.emit()


class MatxOnlineLibrary(grid_columns.GridColumnsMixin,
                       QtCore.QAbstractTableModel):
    """Rows = materials available online, from one source at a time."""

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "RendererLabelRole",
    }

    #: Same role numbers as MaterialLibrary - the delegate and the
    #: filter proxy are shared, so they must line up exactly. CLASS
    #: attributes like the rest of the family (this model cannot
    #: inherit them - it is a catalogue, not a MaterialLibrary), held
    #: equal by test_role_numbers.
    IdRole = QtCore.Qt.ItemDataRole.UserRole            # 256
    CategoryRole = QtCore.Qt.ItemDataRole.UserRole + 1  # 257
    FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 2  # 258
    RendererRole = QtCore.Qt.ItemDataRole.UserRole + 3  # 259
    TagRole = QtCore.Qt.ItemDataRole.UserRole + 4       # 260
    DateRole = QtCore.Qt.ItemDataRole.UserRole + 5      # 261
    RendererLabelRole = QtCore.Qt.ItemDataRole.UserRole + 6  # 262

    #: (done, total) preview downloads, for the shared thin progress bar.
    #: Rolling, because previews load lazily as tiles scroll into view.
    progress_changed = QtCore.Signal(int, int)

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
        # A QThread destroyed while still running takes Houdini with
        # it. Nothing waited for these workers on the way out, so a
        # quit during a catalogue fetch or a preview download was a
        # crash waiting to happen; shutdown() is idempotent and cheap.
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

        # (The Qt roles are CLASS attributes above - assigning them
        # here would shadow a declaration, which is the trap the
        # family just removed.)
                # Through the RELAY, not the engine: the engine singleton is
        # replaced on every module reload, which would leave this
        # model wired to a dead one (see thumbnails._EngineSignals).
        thumbnails.signals.ready.connect(self._on_preview_ready)

    # -- sources -------------------------------------------------------

    @property
    def sources(self):
        return self._sources

    @property
    def source(self):
        return self._source

    @property
    def error(self):
        """Last network error ('' when fine). The panel shows an empty
        grid when offline - no dialog; dialogs confirm actions, they
        don't announce outcomes."""
        return self._error

    def set_search(self, text):
        """Filter the current source's materials locally - no API
        round-trip. Matches title, category and tags. The source itself
        is chosen from View > Online Materials (set_source), not typed
        here - the search narrows within that source."""
        text = (text or "").strip()
        if text == self._search:
            return
        self._search = text
        self._apply_filter()

    def set_source(self, source_name):
        """Show only one source's materials (View > Online Materials >
        <source>). None shows nothing until a source is picked. Refreshes
        the sidebar to that source's categories via the model reset."""
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
        self.endResetModel()
        # No eager queueing: data() asks for what it paints.

    def reload(self, force=False):
        """Show the catalogue, fast. If it's already in memory just
        re-filter; otherwise load the DISK CACHE instantly (categories
        appear in <100ms) and refresh from the network in the background.
        Only a cache miss waits on the ~2-3s fetch."""
        if self._loaded and not force:
            self._apply_filter()
            return

        # Instant path: the last fetch, off disk. Shows immediately; the
        # background refresh below replaces it if the remote changed.
        if not self._loaded:
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
            # note vs event for this file: writing the catalogue cache and
            # drawing a tile icon are internal - the browser still works
            # either way - so those are events. The unreachable-source
            # line below is about what the user is looking at right now,
            # so it stays a note.
            debug.event("online", "catalogue cache not written",
                        error=str(exc))

    def _on_catalogue(self, records, errors, generation):
        self._loading = False
        if generation != self._generation:
            return
        # A partial fetch (some source down) must not overwrite a full
        # disk cache - keep whichever has more, and only re-filter/re-save
        # when the fresh fetch actually adds something.
        partial = bool(errors)
        if not records or (
            partial and self._all and len(records) < len(self._all)
        ):
            self._error = ", ".join(errors) if errors else ""
            if errors:
                debug.event("online", "sources unavailable", errors=errors)
            return
        # Content identity, not just count - a same-count catalogue
        # update (renamed material, changed preview URL) counts as
        # changed too. uid+title+preview_url covers everything a tile
        # shows without hashing full payloads.
        def _sig(recs):
            return [(r.source, r.uid, r.title, r.preview_url) for r in recs]

        changed = _sig(records) != _sig(self._all)
        self._all = records
        self._loaded = True
        if partial:
            # Show it this session, but do NOT let it become the
            # accepted baseline. The guard above only protects an
            # EXISTING cache: on a COLD one, self._all is empty, so a
            # fetch missing a whole source (GPUOpen down: 934 records
            # instead of 1388) sailed past it and was written to disk.
            # Every later run then fetched 934, matched the cache, and
            # accepted it - GPUOpen permanently absent while
            # View > Online Materials still lists it, because that menu
            # is built from the static SOURCES tuple. A day of that is
            # indistinguishable from "AMD has nothing".
            # ONE note, not a note AND a print. The two had already
            # drifted - the note said only "not cached", the print named
            # the sources and what the user is seeing - and on Windows
            # note() returns before the print, so the record is the whole
            # channel there.
            # The most consequential sentence in this file: it is the one
            # that explains a SHORT list. So it says what is missing, and
            # that the short list is not kept - the remedy is real,
            # because this branch skips _save_cache and reload() only
            # short-circuits on a cache hit. The HTTP strings stay in the
            # data, where the log reader can still read them and the user
            # does not have to.
            debug.note(
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
        # Only rebuild the view if the data actually changed - a
        # no-change background refresh must not disturb what's on screen.
        if changed or not self._records:
            self._apply_filter()

    def shutdown(self) -> None:
        """Stop every worker and WAIT for it. Called on application
        quit; safe to call twice, and safe when nothing is running."""
        for worker in list(self._workers):
            try:
                if not worker.isRunning():
                    continue
                worker.requestInterruption()
                # Bounded: a stuck socket must not hold up the quit.
                if not worker.wait(3000):
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
            # `finished` fires even when run() dies before emitting
            # `done`; _loading was cleared ONLY in the done handler, so
            # one unlucky worker left the flag stuck True and reload()
            # returned early for the rest of the session - a browser
            # that silently never refreshes again.
            self._loading = False

    # -- previews ------------------------------------------------------

    @staticmethod
    def _preview_key(record):
        return ("matx", record.source, record.uid)

    def _cache_path(self, record):
        digest = hashlib.md5(
            ("%s/%s" % (record.source, record.uid)).encode("utf-8")
        ).hexdigest()
        # THE SOURCE NAME IS SANITISED, like every other record field
        # that becomes a path (matx_import.package_dirname). Records are
        # rebuilt from the on-disk catalogue, so `source` is whatever
        # that file says - and it was the one field reaching a directory
        # component raw. The DIGEST still carries the unsanitised value,
        # so two sources that sanitise alike keep separate files.
        return os.path.join(
            preview_cache(), hostos.safe_filename(str(record.source)),
            digest + ".png")

    def _icon_size(self):
        try:
            return int(self.preferences.rendersize)
        except (AttributeError, TypeError, ValueError):
            return 256

    def _preview(self, rec):
        """Cached preview, requesting it on a miss.

        Every other model in this codebase requests lazily from data(),
        driven by what the view actually paints. This one only peeked at
        an eagerly queued slice of the first 120 rows, so rows past that
        never got an image at all, and any preview the RAM budget evicted
        never came back. One row is queued here and the batch coalesces
        on a zero-timer, mirroring the engine's own dispatch."""
        key = self._preview_key(rec)
        image = thumbnails.engine.peek(key)
        if image is not None:
            return image
        if key in self._requested:
            return None

        # Disk-cache hit: decode it here and now. A previously-seen
        # preview must not need a network worker (or even a thread) to
        # come back - browsing the same catalogue again was downloading
        # everything a second time. Same shape as the texture cache's
        # main-thread hit path: a local stat + small PNG decode.
        if rec.preview_url:
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
        """Dispatch accumulated requests across a BOUNDED POOL.

        Previews are latency-bound, not bandwidth-bound (a 40KB GPUOpen
        thumbnail takes ~470ms), so concurrency scales close to linearly
        - measured over 32 PolyHaven previews: 1 worker 220ms each, 8
        workers 42ms, 16 workers 18ms. A single serial worker made the
        full catalogue a 5-10 minute crawl.

        Bounded because the alternative (a fresh thread per paint pass)
        is a thread explosion while scrolling, and because these are
        free public APIs worth being a polite client of."""
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
            if rec.kind == "values":
                # No render exists to download - the tile is DRAWN from
                # the material's own measured numbers. Cheap enough to do
                # on the spot (an SVG rasterise), so no worker.
                try:
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
                    # A FAILED draw keeps its marker: releasing it made
                    # every repaint re-queue the same failing draw (a
                    # broken/missing SVG template = an infinite
                    # draw-and-retry loop). The tile stays blank for
                    # the session; a panel reopen retries once.
                    continue
                # Drawing is cheap, so an evicted icon can simply be
                # redrawn on the next paint - don't hold the marker.
                self._requested.discard(key)
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
        """One preview download finished (ok or failed) - advance the bar.
        When the burst is fully drained, reset so the next scroll starts a
        fresh 0..N rather than resuming a stale total."""
        self._preview_done += 1
        self.progress_changed.emit(self._preview_done, self._preview_total)
        if self._preview_done >= self._preview_total and not self._pending:
            self._preview_done = 0
            self._preview_total = 0

    def _deposit_preview(self, key, image):
        thumbnails.engine.deposit(key, image)
        # Deposited images can still be evicted by the RAM budget; drop
        # the request marker so the next paint can ask again (from the
        # disk cache, which download() already populated).
        self._requested.discard(key)

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

    # -- model ---------------------------------------------------------

    def rowCount(self, parent=None):
        return len(self._records)

    def record(self, row):
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def data(self, index, role=0):
        # LATER COLUMNS are the table's, not the row's (step 1 of the
        # QTableView migration). Column 0 falls through unchanged, so
        # grid mode cannot tell any of this happened.
        if index.column() > 0:
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
            # What the Type column shows: the source, plus the fact that
            # value-sources produce a preset rather than a textured
            # material.
            return rec.source if rec.kind == "package" else rec.source + " (values)"
        if role == self.RendererRole:
            # What an online record becomes when imported: a normal
            # Karma material - so the Karma renderer filter behaves the
            # same over the online grid as over the library.
            return "Karma"
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
        """The distinct categories of the SELECTED source, for the sidebar
        - from _all (not the search-filtered view), so the list doesn't
        shrink as you type in the filter box. Capitalised, no source
        suffix (the source is the submenu you came in through)."""
        seen = set()
        for rec in self._all:
            if rec.category and self._in_source(rec):
                seen.add(rec.category)
        return sorted(seen, key=str.lower)


class MatxSidebarModel(QtCore.QAbstractListModel):
    """The online browser's sidebar: the categories of the SELECTED
    source (picked from View > Online Materials > <source>). Row 0 is
    "All" (all of that source); the rest are its capitalised categories,
    no source suffix - the source is already in the menu you came in
    through."""

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
