"""The shared asset model every library section runs on, plus `MaterialLibrary`."""

import functools
import os
import json
import shutil
import threading
import types
from typing import Any
from PySide6 import QtCore, QtGui

from amaze.core import asset_files
from amaze.core import captures
from amaze.core import debug
from amaze.core import grid_engine
from amaze.core import locations
from amaze.core import material, database, renderers, thumbnails, tile_icons, workers
from amaze.core import material_files
from amaze.core import versions
from amaze.helpers import hostos
from amaze import messages
from amaze.prefs import prefs


_STAMPED: dict = {}    # (library dir, asset id) -> repr of the record its stamp was last seen holding
_STAMP_LOCK = threading.Lock()    # held by a worker across one stamp's check-and-write


def _holds(path: str, payload: str) -> bool:
    """Whether the stamp at `path` reads exactly `payload`; an absent or unreadable one does not."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read() == payload
    except (OSError, ValueError):
        return False


def _write(path: str, payload: str, mat_id) -> bool:
    """Write one stamp atomically; a failure is logged and answered False, never raised."""
    try:
        with hostos.scratch_beside(path) as scratch:
            with open(scratch, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
        return True
    except OSError as exc:  # a safety net is never the thing being saved
        debug.event("library", "recovery stamp not written",
                    mat_id=str(mat_id), error=str(exc))
        return False


class _StampWorker(QtCore.QThread):
    """Checks the stamps a save did not change against disk, writing any that differ."""

    checked = QtCore.Signal(object, object)    # (this worker, [(key, repr)] of stamps now current)

    def __init__(self, where, preferences, items) -> None:
        super().__init__()
        self.where = where
        self._preferences = preferences    # dir and asset_dir only, read on the GUI thread
        self._items = items    # [(key, repr, payload)], every one a string
        self._canceled = False    # set under _STAMP_LOCK: no write after it, its findings dropped

    def cancel(self) -> None:
        self._canceled = True

    def run(self) -> None:
        current = []
        for known, seen, payload in self._items:
            if self._canceled or self.isInterruptionRequested():
                return
            try:
                path = material.payload_path(self._preferences, known[1],
                                             material.STAMP_SUFFIX)
            except hostos.PathEscape:
                continue
            if not _holds(path, payload):
                with _STAMP_LOCK:
                    written = not self._canceled and _write(path, payload, known[1])
                if not written:
                    continue
            current.append((known, seen))
        self.checked.emit(self, current)


class _StampEngine(QtCore.QObject):
    """Every stamp check in the process, stopped on quit and whenever its library moves on."""

    def __init__(self) -> None:
        super().__init__()
        self._threads = []    # a running QThread must keep a reference until it ends ▸r/model-contracts

    def start(self, where, preferences, items) -> None:
        """Check `items` of the library at `where` on a worker, its older checks stopped first."""
        self.cancel(where)
        worker = _StampWorker(where, preferences, items)
        worker.checked.connect(self._checked)
        worker.finished.connect(functools.partial(self._finished, worker))    # never sender()
        self._threads.append(worker)
        worker.start()

    def cancel(self, where=None) -> None:
        """Stop the checks of the library at `where`, or all; none writes after this returns."""
        with _STAMP_LOCK:
            for worker in self._threads:
                if where is None or worker.where == where:
                    worker.cancel()

    def _checked(self, worker, current) -> None:
        if not worker._canceled:    # a stopped check may hold records older than the model's
            for known, seen in current:
                _STAMPED[known] = seen

    def _finished(self, worker) -> None:
        self._threads = [t for t in self._threads if t is not worker]

    def shutdown(self) -> None:
        """Stop every check under the lock, THEN wait them out together; safe twice and when idle."""
        self.cancel()    # under _STAMP_LOCK first: no write begins after this
        workers.stop(self._threads, "library")
        self._threads = []


stamps = workers.install(__name__ + ".stamps", _StampEngine, QtCore.QCoreApplication.instance())


class _StampWriter:
    """Rewrites stale stamps; call only after a successful index write. ▸p/recovery-stamp"""

    def __init__(self, library):
        self._library = library

    @staticmethod
    def forget(preferences, mat_id) -> None:
        """Drop what this session knows of one asset's stamp, so the next save checks it again."""
        stamps.cancel(str(preferences.dir))    # a running check may hold the record before this one
        _STAMPED.pop((str(preferences.dir), str(mat_id)), None)

    @staticmethod
    def forget_library(preferences) -> None:
        """Drop what this session knows of every stamp in one library, once its rows are read afresh."""
        where = str(preferences.dir)
        stamps.cancel(where)
        for known in [key for key in _STAMPED if key[0] == where]:
            del _STAMPED[known]

    def refresh(self, indexed=None) -> int:
        """Stamp now the records unlike `indexed`, the index before this save; a worker checks the rest."""
        written, later = 0, []
        preferences = self._library.preferences
        where = str(preferences.dir)
        stamps.cancel(where)    # no older check may write after the stamps written here
        for asset in list(self._library._assets):
            known = (where, str(asset.mat_id))
            try:
                record = asset.get_as_dict()
                seen = repr(record)
                if _STAMPED.get(known) == seen:
                    continue
                if not material.is_safe_asset_id(known[1]):
                    continue
                payload = json.dumps(record, indent=1, sort_keys=True)
                if indexed is not None and self._indexed(indexed.get(known[1]), record):
                    later.append((known, seen, payload))
                    continue
                path = material.payload_path(preferences, known[1],
                                             material.STAMP_SUFFIX)
            except hostos.PathEscape:
                continue
            except (TypeError, ValueError) as exc:  # logged, never raised: the index write already landed
                debug.event("library", "recovery stamp could not be built",
                            mat_id=str(asset.mat_id), error=str(exc))
                continue
            if _holds(path, payload):
                _STAMPED[known] = seen
            elif _write(path, payload, asset.mat_id):
                written += 1
                _STAMPED[known] = seen
        if later:
            stamps.start(where, types.SimpleNamespace(dir=preferences.dir,
                                                      asset_dir=preferences.asset_dir), later)
        return written

    def _indexed(self, row, record) -> bool:
        """Whether the index's `row` already held `record`: as stored, or as today's reader reads it."""
        if row is None:
            return False
        if row == record:
            return True
        try:
            return self._library._asset_from_row(row).get_as_dict() == record
        except Exception:                                # noqa: BLE001 - an unreadable row is an edit
            return False


class AssetLibrary(grid_engine.GridEngine,
                   QtCore.QAbstractTableModel):
    """The shared asset model every library section runs on; nothing renderer-shaped lives here."""

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "RendererLabelRole",
        "category": "CategoryRole",
        "favorite": "FavoriteRole",
        "version": "ActiveVersionRole",
        "comments": "NotesRole",
        "tags": "TagRole",
        "license": "LicenceRole",
        "date": "DateRole",
        "id": "IdRole",    # list-mode columns ▸p/d03-retired
    }
    GRID_ROWS = ("_assets", "_mat_paths", "_row_keys")
    VERSION_SECTION = versions.MATERIAL    # where this model's versions live ▸r/version-store
    TILE_FACE = ""      # the section's generic face, `ui/<TILE_FACE>.svg` from its T frame ▸r/tile-faces
    NOTES_SECTION = "" # this model's notes-store key prefix; every subclass names its own
    ROW_NOUN = "material"    # what a message calls one row of this section; counts pluralise it

    IdRole = QtCore.Qt.ItemDataRole.UserRole  # 256. Roles are class attributes, never set in __init__, where they shadow a subclass's
    CategoryRole = QtCore.Qt.ItemDataRole.UserRole + 1  # 257 - 257-260 are what MultiFilterProxyModel switches on BY NUMBER
    FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 2  # 258
    RendererRole = QtCore.Qt.ItemDataRole.UserRole + 3  # 259
    TagRole = QtCore.Qt.ItemDataRole.UserRole + 4  # 260
    DateRole = QtCore.Qt.ItemDataRole.UserRole + 5  # 261
    RendererLabelRole = QtCore.Qt.ItemDataRole.UserRole + 6  # 262
    LicenceRole = QtCore.Qt.ItemDataRole.UserRole + 7  # 263
    CategoryColorRole = QtCore.Qt.ItemDataRole.UserRole + 8  # 264: this asset's category colour, "" for none, from the dict the Categories model writes
    VersionsRole = QtCore.Qt.ItemDataRole.UserRole + 9  # 265 - how many versions; the delegate draws the chevrons badge at > 1
    NotesRole = QtCore.Qt.ItemDataRole.UserRole + 10  # 266: whether this asset carries a note, read live from the notes store
    ActiveVersionRole = QtCore.Qt.ItemDataRole.UserRole + 11  # 267: the active version's name, "" when there are none

    CropRole = QtCore.Qt.ItemDataRole.UserRole + 12  # 268 - a capture is viewport-shaped, so it fills the tile

    DB_FILENAME = ""  # the json file in the library dir backing this model; every subclass names its own

    def __init__(self, preferences: prefs.Prefs) -> None:
        super().__init__()
        self.preferences = preferences  # required, and shared with the panel ▸p/duplication-third-verb

        self._data = database.open_document(self)

        self._assets = [self._asset_from_row(d)  # non-dict rows are skipped
                        for d in self._data["assets"]
                        if isinstance(d, dict)]
        _StampWriter.forget_library(self.preferences)
        self._remember_content_state()


        self._thumb_rows = {}  # maps engine deliveries, by key, back to the row to repaint
        thumbnails.signals.ready.connect(self._on_thumb_key_ready)  # through the relay, never the engine singleton, which a module reload replaces
        captures.signals.landed.connect(self._on_capture_landed)    # from any panel or the shelf
        self.rebuild_thumbs()
        self.order_rows()    # in the grid's order before any view has the rows
        self.adopt_retired_text_into_notes()

    RETIRED_TEXT_FIELDS = ("about", "description")    #: record fields whose text is now a comment ▸p/d03-retired

    def adopt_retired_text_into_notes(self) -> int:
        """Move each retired text field into its asset's comment; returns how many. ▸p/d03-retired"""
        if not self.NOTES_SECTION:
            return 0
        from amaze.core import notes
        pages, carried = {}, []    # key -> the page to write; (asset, field, needs that write)
        for asset in self._assets:
            key = notes.note_key(self.NOTES_SECTION, str(asset.mat_id))
            items = None
            for field in self.RETIRED_TEXT_FIELDS:
                text = getattr(asset, field)
                if not isinstance(text, str) or not text.strip():
                    continue    # a hand-edited record can carry any type; only TEXT is worth moving
                text = text.strip()
                if items is None:
                    items = list(notes.note_for(self.preferences, key).get(
                        "items", []))
                if any(item.get("t") == "text"    # carried already, here or by another machine
                       and item.get("text", "").strip() == text
                       for item in items):
                    carried.append((asset, field, False))
                    continue
                items = [{"t": "text", "text": text}] + items
                pages[key] = items
                carried.append((asset, field, True))
        written = not pages or bool(notes.set_notes(self.preferences, pages))    # ONE write
        moved = 0
        for asset, field, needed in carried:
            if needed and not written:
                continue    # a read-only library: leave the field rather than clear text nothing kept
            setattr(asset, field, "")
            moved += 1
        if moved:
            self.save()
            debug.event("library", "retired text moved into comments",
                        section=self.NOTES_SECTION, fields=moved)
        return moved

    @staticmethod
    def _asset_from_row(row: dict):
        """One stored row becomes one record - the reader every load path shares."""
        return material.Material.from_dict(row)

    def _tile_image_path(self, row: int, spec=None) -> str:
        """The file a row's tile loads: its capture or chosen icon, else its render; "" if unsafe."""
        if spec is None:
            spec = self.tile_icon(row)
        if (spec or {}).get("face") == "capture":
            return self.capture_path(row)
        return tile_icons.tile_read_path(
            self.preferences, str(self._assets[row].mat_id),
            tile_icons.is_custom(spec))

    def capture_path(self, row: int) -> str:
        """Where this row's capture lives; "" for a row that does not exist or an unsafe id."""
        if not 0 <= row < len(self._assets):
            return ""
        mat_id = str(self._assets[row].mat_id)
        if not material.is_safe_asset_id(mat_id):
            return ""
        return captures.asset_path(self.preferences, mat_id)

    def has_capture(self, row: int) -> bool:
        return captures.exists(self.capture_path(row))

    def capture_image(self, row: int):
        """The row's capture, read now for the Customize preview; None where there is none."""
        path = self.capture_path(row)
        image = QtGui.QImage(path) if captures.exists(path) else QtGui.QImage()
        return None if image.isNull() else image

    def _on_capture_landed(self, key) -> None:
        """A capture landed for `key`: re-point and repaint that tile, dropping the old picture."""
        for row in range(self.rowCount()):
            if self.tile_key(row) == str(key):
                self._add_thumb_paths(row, base_changed=False)
                return

    def switch_model_data(self):
        """Point this model at the library Preferences names; stamp checks stop."""
        stamps.cancel()    # a check still running holds the records of the library left behind
        self.beginResetModel()  # required: without it proxies and selection keep stale rows ▸r/model-contracts
        try:
            self._data = database.open_document(self, reload=True)

            self._assets = [
                self._asset_from_row(d) for d in self._data["assets"]
                if isinstance(d, dict)
            ]
            _StampWriter.forget_library(self.preferences)
            self._remember_content_state()  # a reload is a fresh read of the library, content included
            self._drop_content_label_caches()
            self.rebuild_thumbs()
            self.order_rows()
        finally:  # a raising load must not leave the model stuck mid-reset
            self.endResetModel()

    def flags(
        self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex
    ) -> QtCore.Qt.ItemFlag:
        default = super().flags(index)
        return default | QtCore.Qt.ItemFlag.ItemIsDragEnabled

    def rebuild_thumbs(self):
        """Rebuild the row->path and key->row maps; no loading happens here."""
        specs = [self.tile_icon(row) for row in range(self.rowCount())]    # one store read per row
        self._mat_paths = [self._tile_image_path(row, spec)
                           for row, spec in enumerate(specs)]
        self._row_keys = [self._thumb_key(row, spec)
                          for row, spec in enumerate(specs)]    # row -> its key, the map read backwards
        self.rows_reordered()

    def rows_reordered(self) -> None:
        self._thumb_rows = {key: row for row, key in enumerate(self._row_keys)}

    def _add_thumb_paths(self, row: int, base_changed: bool = True):
        """Refresh one row's thumbnail maps and repaint it, never a whole-model rebuild."""
        if not 0 <= row < self.rowCount():
            return
        mat_id = self._assets[row].mat_id
        spec = self.tile_icon(row)    # one store read serves the path and the key
        entry = self._tile_image_path(row, spec)
        if row < len(self._mat_paths):
            self._mat_paths[row] = entry
        elif row == len(self._mat_paths):
            self._mat_paths.append(entry)    # add_asset appends the row first, so the maps grow by one here
        else:
            self.rebuild_thumbs()    # the maps fell out of step with the rows - resync whole
        key = self._thumb_key(row, spec)
        if row < len(self._row_keys):
            stale = self._row_keys[row]
            if self._thumb_rows.get(stale) == row:
                del self._thumb_rows[stale]
            self._row_keys[row] = key
        else:
            self._row_keys.append(key)
        self._thumb_rows[key] = row
        if base_changed:    # the ACTIVE version's archive slot follows a fresh base picture
            versions.record_render(self.preferences, mat_id)
        thumbnails.engine.discard(key)
        self.row_changed(
            row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def _on_thumb_key_ready(self, key) -> None:
        """The engine delivered (or failed) a key: repaint its row if it belongs to this model."""
        row = self._thumb_rows.get(key)
        if row is None or not 0 <= row < self.rowCount():
            return
        self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def category_color(self, row: int) -> str:
        """The colour set on this asset's category, "" for none."""
        if not 0 <= row < len(self._assets):
            return ""
        cats = self._assets[row].categories
        if not cats:
            return ""
        table = self._data.get("category_colors")
        if not isinstance(table, dict):
            return ""
        return str(table.get(cats[0], "") or "")

    def _thumb_key(self, row: int, spec=None):
        """Shared-RAM-cache key for one row's picture; every input to the picture belongs in it."""
        home = hostos.canonical_path_key(str(self.preferences.dir or ""))
        if spec is None:
            spec = self.tile_icon(row)
        if (spec or {}).get("face") == "capture":
            return (home, self.DB_FILENAME, self._assets[row].mat_id,
                    "capture", "", "", 0)
        if not tile_icons.is_custom(spec):
            return (home, self.DB_FILENAME, self._assets[row].mat_id,
                    "", "", "", 0)
        return (home, self.DB_FILENAME, self._assets[row].mat_id,
                spec["name"], spec["bg"], spec["ink"],
                tile_icons.stroke_for(self.preferences))

    def tile_face_art(self, row: int) -> str:
        """This row's generic face art, "" where it has none."""
        return self.TILE_FACE

    def can_preview(self, row: int) -> bool:
        """Whether this row can have a picture of its own."""
        return True

    def default_face(self, row: int) -> str:
        """Preview where the row can have a picture, Generic where it cannot."""
        return "preview" if self.can_preview(row) else "generic"

    def preview_image(self, row: int):
        """The row's own picture, read now for the Customize preview; None where there is none yet."""
        if not 0 <= row < len(self._assets):
            return None
        image = QtGui.QImage(tile_icons.thumbnail_path(self.preferences, self._assets[row].mat_id))
        return None if image.isNull() else image

    def _missing_thumb_image(self, row: int = -1):
        """A row with no picture shows its chosen face."""
        if 0 <= row < len(self._assets):
            return tile_icons.chosen_image(self, row)
        return tile_icons.generic_image(self.TILE_FACE)

    def tile_name(self, row: int) -> str:
        """The asset's display name - what the Customize dialog's Name field shows."""
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].name or "")

    def set_tile_name(self, row: int, name: str, save: bool = True) -> bool:
        """Rename one asset, then the save chain; a blank or unchanged name is a no-op."""
        name = (name or "").strip()
        if not 0 <= row < len(self._assets) or not name:
            return False
        asset = self._assets[row]
        if name == asset.name:
            return False
        asset.name = name
        self._edited(asset, save)
        return True

    def add_tile_tags(self, row: int, line: str, save: bool = True) -> bool:
        """Add a comma-separated line of tags to this asset's own, dropping duplicates."""
        if not 0 <= row < len(self._assets):
            return False
        asset = self._assets[row]
        before = [tag for tag in (asset.tags or []) if tag]
        wanted = [tag.strip() for tag in (line or "").split(",")
                  if tag.strip()]
        merged = list(before)
        for tag in wanted:
            if tag not in merged:
                merged.append(tag)
        if merged == before:
            return False
        asset.tags = ", ".join(merged)
        self._edited(asset, save)
        return True

    def tile_category(self, row: int) -> str:
        """This asset's category, as the Customize dialog's Category dropdown shows it."""
        if not 0 <= row < len(self._assets):
            return ""
        cats = self._assets[row].categories or []
        return str(cats[0]) if cats else ""

    def set_tile_category(self, row: int, name: str, save: bool = True) -> bool:
        """Move one asset to category `name`, then the save chain; a blank is a no-op."""
        name = (name or "").strip()
        if not 0 <= row < len(self._assets) or not name:
            return False
        asset = self._assets[row]
        if list(asset.categories or []) == [name]:
            return False
        asset.categories = [name]    # one name, its commas included
        self._edited(asset, save)
        return True

    def tile_tags(self, row: int) -> str:
        """This asset's tags as one comma-separated line, as the Customize dialog's Tags field shows."""
        if not 0 <= row < len(self._assets):
            return ""
        return ", ".join(self._assets[row].tags or [])

    def set_tile_tags(self, row: int, line: str, save: bool = True) -> bool:
        """Replace one asset's tags from a comma-separated line; an empty line clears them."""
        if not 0 <= row < len(self._assets):
            return False
        asset = self._assets[row]
        before = [tag for tag in (asset.tags or []) if tag]
        asset.tags = line or ""    # the record's own setter splits and drops the blanks
        if [tag for tag in (asset.tags or []) if tag] == before:
            return False
        self._edited(asset, save)
        return True

    def tile_icon(self, row: int) -> dict:
        """This row's chosen icon, {} when it shows its render; `icons.json` is keyed by asset id."""
        if 0 <= row < len(self._assets):
            return tile_icons.override_for(
                self.preferences, str(self._assets[row].mat_id))
        return {}

    def _edited(self, asset, save: bool) -> None:
        """Save and repaint one edited record now, or with `save` False leave it to `commit_tile_edits`."""
        if save:
            self._saved_rows_changed([asset])

    def commit_tile_edits(self, keys) -> bool:
        """ONE save for the records the `save=False` setters changed, named by key, then their repaint."""
        wanted = {str(key) for key in keys}
        return self._saved_rows_changed(
            [asset for asset in self._assets if str(asset.mat_id) in wanted])

    def _saved_rows_changed(self, assets, roles=None) -> bool:
        """Save, then repaint each record on the row the save LEFT it on: a save adopts and drops rows."""
        stored = self.save()
        rows = {str(asset.mat_id): row for row, asset in enumerate(self._assets)}
        for asset in assets:
            self.row_changed(rows.get(str(asset.mat_id), -1), roles)
        return stored

    def tile_key(self, row: int) -> str:
        """The key for this row's tile icons: the asset id, "" for no row. Hold this, never a row number."""
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].mat_id)

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        """One asset's icon ({} clears); False when not written. `save` is unused: no record moves."""
        row = index.row() if hasattr(index, "row") else int(index)
        if not 0 <= row < len(self._assets):
            return False
        return self.set_tile_icons([row], spec) == 0

    def set_tile_icons(self, rows, spec) -> int:
        """Give every row in `rows` the icon `spec` in one store write; returns how many failed."""
        valid = [row for row in rows if 0 <= row < len(self._assets)]
        if not valid:
            return len(rows)
        chosen = {row: tile_icons.choice_for(self, row, spec) for row in valid}
        held = tile_icons.set_overrides(  # the store is the one home, so a clear here is the whole delete
            self.preferences,
            {str(self._assets[row].mat_id): choice
             for row, choice in chosen.items()})
        failed = len(rows) - len(valid)
        for row in valid:
            stored = held[str(self._assets[row].mat_id)]
            if not self._tile_icon_landed(row, chosen[row], stored):
                failed += 1
        return failed

    def _tile_icon_landed(self, row: int, spec, stored: bool) -> bool:
        """After the store write: compose or drop this row's icon picture and refresh its tile."""
        asset = self._assets[row]
        written = stored
        if tile_icons.is_custom(spec):
            written = written and bool(
                tile_icons.render_for(self.preferences, asset.mat_id, spec)
            )
        else:
            tile_icons.clear_for(self.preferences, asset.mat_id)
        self._add_thumb_paths(row, base_changed=False)
        return written

    def commit_tile_icons(self, rows=None) -> None:
        """Nothing to commit: `set_tile_icons` wrote the icon store, and no record field moved."""

    def rerender_tile_icons(self) -> int:
        """Recompose every icon in this library, for when the look changed rather than the choice."""
        made = 0
        for row, asset in enumerate(self._assets):
            spec = self.tile_icon(row)
            if not tile_icons.is_custom(spec):
                continue
            if tile_icons.render_for(self.preferences, asset.mat_id, spec):
                made += 1
            self._add_thumb_paths(row, base_changed=False)
        return made

    def _decoration_image(self, row: int):
        """A row's tile picture, the library's own PNG through the thumbnail engine."""
        if tile_icons.face_for(self, row) == "generic":
            return tile_icons.chosen_image(self, row)
        key = self._thumb_key(row)
        image = thumbnails.engine.request_file(key, self._mat_paths[row])
        if image is not None:
            return image
        if thumbnails.engine.is_missing(key):
            return self._missing_thumb_image(row)
        return None

    def rowCount(
        self, parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex | None = None
    ) -> int:
        return len(self._assets)

    def removeRow(
        self,
        row: int,
        /,
        parent: QtCore.QModelIndex | QtCore.QPersistentModelIndex = ...,
    ) -> bool:
        if not self._unlist_row(row):
            return False
        self.rebuild_thumbs()  # rows shifted, so remap keys to rows; the dropped image ages out of the LRU
        return True

    def _unlist_row(self, row: int) -> bool:
        """Take one row out of the model, marked for removal at the next save; maps NOT rebuilt."""
        if not 0 <= row < len(self._assets):
            return False
        going = self._assets[row]
        try:  # SAY THE DELETE: the connector unions rows, so a row only left out of set() comes back
            database.DatabaseConnector(self.DB_FILENAME).forget(going.mat_id)
        except (AttributeError, TypeError) as exc:
            debug.event("library", "could not mark a row for removal",
                        error=str(exc))
        _StampWriter.forget(self.preferences, going.mat_id)    # its stamp may be unlinked with it

        self.beginRemoveRows(QtCore.QModelIndex(), row, row)  # del by INDEX: by value drops the first EQUAL one
        del self._assets[row]
        self.endRemoveRows()
        return True

    def renderer_label(self, asset) -> str:
        return str(asset.renderer or "").strip()  # the tile subtitle: the kind field as it stands; MaterialLibrary overrides it

    def _drop_content_label_caches(self, mat_id=None) -> None:
        """Evict per-id labels a subclass derives from asset content. The base derives none."""

    def row_data(self, row: int, role: int) -> Any:
        asset = self._assets[row]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return asset.name

        if role == self.RendererLabelRole:
            return self.renderer_label(asset)

        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            return self._decoration_image(row)  # the RAW stored image; the delegate scales it

        if role == self.CategoryRole:
            return asset.categories
        if role == self.CategoryColorRole:
            return self.category_color(row)

        if role == self.TagRole:
            return asset.tags

        if role == self.LicenceRole:
            return str(asset.license or "")

        if role == self.CropRole:
            return tile_icons.face_for(self, row) == "capture"

        if role == self.FavoriteRole:
            return locations.is_favourite(  # the USER'S star, in the library store, never the record
                self.preferences, asset.mat_id)

        if role == self.VersionsRole:
            mat_id = str(asset.mat_id)
            cached = self._version_count_cache.get(mat_id)
            if cached is None:
                cached = versions.version_count(self.preferences, mat_id,
                                                self.VERSION_SECTION)
                self._version_count_cache[mat_id] = cached
            return cached

        if role == self.ActiveVersionRole:
            mat_id = str(asset.mat_id)
            cached = self._active_version_cache.get(mat_id)
            if cached is None:
                cached = versions.active_version_name(
                    self.preferences, mat_id, self.VERSION_SECTION)
                self._active_version_cache[mat_id] = cached
            return cached

        if role == self.RendererRole:
            return str(asset.renderer)

        if role == self.DateRole:
            return str(asset.date)

        if role == self.IdRole:
            return str(asset.mat_id)

        if role == self.NotesRole:
            from amaze.core import notes
            return notes.has_note(
                self.preferences,
                notes.note_key(self.NOTES_SECTION, asset.mat_id))
        return None

    def save(self) -> bool:
        """Write the index to disk as json; True only when it reached the file, so honour the answer."""
        db = database.connector_for_save(self, "save")
        if db is None:  # another pane moved the shared connector: this model holds the old library's rows
            return False
        self.apply_refresh(db)    # the sidebar shares this connector: its save may have merged a peer's edit
        data = {}
        data["assets"] = [asset.get_as_dict() for asset in self._assets]
        db.set(data)
        indexed = db._loaded_rows    # the index before this save: a record unlike it is this save's edit
        stored = db.save()
        from amaze.core import model_registry
        model_registry.apply_merged(db, also=self)    # every model on this file takes what the save merged
        if stored and db._save_outcome != "identical-skip":
            _StampWriter(self).refresh(indexed)  # after a write that landed ▸p/recovery-stamp
        return stored

    def apply_refresh(self, db) -> bool:
        """Drain what any merge on this connector left for the model. True when the model moved."""
        rows, fields, gone = (db.take_adopted(), db.take_adopted_fields(),
                              db.take_dropped())
        self._adopt_rows(rows)
        self._adopt_fields(fields)
        self._drop_rows(gone)
        recoloured = database.colours_moved(self, db)
        if recoloured:
            self.repaint_category_colours()
        return bool(rows or fields or gone or recoloured)

    def repaint_category_colours(self) -> None:
        """Repaint every tile's category band, role-scoped: a colour never moves a column width."""
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0),
                [self.CategoryColorRole])

    def _adopt_fields(self, fields: list) -> None:
        """Apply peer `(id, field, value)` changes onto the records in place, and tell the views."""
        if not isinstance(fields, list) or not fields:  # a list, by contract, like `_adopt_rows`
            return
        wanted: dict = {}
        for asset_id, field, value in fields:
            wanted.setdefault(str(asset_id), {})[field] = value
            _StampWriter.forget(self.preferences, asset_id)
        for row, asset in enumerate(self._assets):
            changes = wanted.get(str(asset.mat_id))
            if not changes:
                continue
            try:
                fresh = self._asset_from_row(
                    dict(asset.get_as_dict(), **changes))
            except Exception as exc:                        # noqa: BLE001
                debug.event("database", "adopted field not readable",
                            file=self.DB_FILENAME, error=str(exc),
                            asset_id=str(asset.mat_id))
                continue
            asset.__dict__.update(fresh.__dict__)
            self.row_changed(row)    # the whole row: an adopted field can reach any column

    def _append_record(self, record) -> int:
        """Add a new record, sorted into place at once; answers the row it holds NOW."""
        row = len(self._assets)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        try:
            self._assets.append(record)
        finally:
            self.endInsertRows()
        self._add_thumb_paths(row)
        moved = self.resort()    # now, so no caller holds a row that is about to move
        self._content_state[str(record.mat_id)] = self._content_stat(
            record.mat_id)
        return moved.get(row, row) if moved else row

    def _take_back_refused_append(self, record) -> None:
        """Take a refused new record back out of the model and the save's document, by identity."""
        row = next((i for i, held in enumerate(self._assets)
                    if held is record), -1)
        if row >= 0:
            self.beginRemoveRows(QtCore.QModelIndex(), row, row)
            try:
                del self._assets[row]
            finally:
                self.endRemoveRows()
            self.rebuild_thumbs()
        self._content_state.pop(str(record.mat_id), None)
        try:
            connector = database.DatabaseConnector(self.DB_FILENAME)
            if connector.serves(self.preferences.dir):    # a serves() refusal never ran set()
                connector.forget(record.mat_id)
                connector.set({"assets": []})    # set() is where a forget lands; else any save writes it
        except (AttributeError, TypeError) as exc:
            debug.event("library", "could not take back a refused append",
                        error=str(exc))

    def _adopt_rows(self, rows: list) -> None:
        """Insert rows another session added, with the row signals; an unparseable row is skipped."""
        if not isinstance(rows, list):  # a list, by contract
            return
        parsed = []
        for row in rows:
            try:
                parsed.append(self._asset_from_row(row))
                _StampWriter.forget(self.preferences, parsed[-1].mat_id)
            except Exception as exc:                        # noqa: BLE001
                debug.event("database", "adopted row not readable",
                            file=self.DB_FILENAME, error=str(exc),
                            asset_id=str(row.get("id", "")))
        if not parsed:
            return
        start = len(self._assets)
        self.beginInsertRows(QtCore.QModelIndex(), start,
                             start + len(parsed) - 1)
        try:
            self._assets.extend(parsed)
        finally:
            self.endInsertRows()
        self.rebuild_thumbs()
        self.resort()    # now: the save that adopted them may still hold its own rows

    def _drop_rows(self, rows: list) -> None:
        """Remove rows another session deleted, with the row signals; nothing on disk is touched."""
        if not isinstance(rows, list):  # a list, by contract
            return
        ids = {str(row.get("id", "")) for row in rows
               if isinstance(row, dict)}
        ids.discard("")
        if not ids:
            return
        removed = False
        for index in range(len(self._assets) - 1, -1, -1):  # one pass, highest row first so indices stay valid
            if str(self._assets[index].mat_id) not in ids:
                continue
            _StampWriter.forget(self.preferences, self._assets[index].mat_id)
            self.beginRemoveRows(QtCore.QModelIndex(), index, index)
            try:
                del self._assets[index]
            finally:
                self.endRemoveRows()
            removed = True
        if removed:
            self.rebuild_thumbs()

    @property
    def assets(self) -> list:
        """This model's records, in row order - the live list, not a copy."""
        return self._assets

    def sanitize_tags(self, tags):
        ts = []
        for t in tags.split(","):
            t = t.strip()
            if t != "":
                ts.append(t)

        ts = dict.fromkeys(ts)  # dedupes while PRESERVING order; a set() here reshuffles tag order on every edit
        new_tags = ",".join(ts)
        return new_tags

    def set_assetdata(self, index: QtCore.QModelIndex, name, cats, tags, fav,
                      about=None, license=None, save=True) -> None:
        """Write one row's editable fields; None leaves a field unchanged, save=False defers the write."""

        asset = self._assets[index.row()]

        name = name if material.MULTIPLE_VALUES not in name else asset.name
        cats = (cats if material.MULTIPLE_VALUES not in cats
                else ", ".join(asset.categories))

        if material.MULTIPLE_VALUES not in tags:
            tags = self.sanitize_tags(tags)
        else:
            tags = ", ".join(asset.tags)

        if fav is not None:  # the star goes to the favourites store under its owner, never onto the record
            if bool(fav) != locations.is_favourite(
                    self.preferences, asset.mat_id):
                locations.set_favourite(
                    self.preferences, asset.mat_id, bool(fav))
        asset.set_data(name, cats, tags, asset.fav, None, about=about,
                       license=license)
        if save:
            self._saved_rows_changed([asset])
        else:
            self.row_changed(index.row())  # full-row repaint: name, categories, tags and star may all change

    def collapse_multicategory(self) -> int:
        """Drop every asset to its first category; returns how many collapsed. Idempotent."""
        changed = 0
        for asset in self._assets:
            if len(asset.categories) > 1:
                asset.categories = asset.categories[0]  # setter takes a str
                changed += 1
        if changed:
            self.save()
        return changed

    CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE = True  # whether Repair can recover what a refused index write leaves; subclasses override

    def report_refused_index_write(self, asset) -> None:
        """Report content written but the list not; call it from every add_asset. Files stay put."""
        name = asset.name or "The asset"
        debug.event("save", "asset content written but the index write "
                    "was refused", name=name, mat_id=asset.mat_id,
                    model=self.DB_FILENAME)
        if self.CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE:
            debug.alert(
                messages.ASSET_FILES_WRITTEN_BUT_LIST_NOT_UPDATED % name,
                key="index-refused-after-content-write")
        else:
            debug.alert(
                messages.ASSET_NOT_SAVED_LIST_NOT_UPDATED % name,
                key="index-refused-inline-content")

    def asset_files(self, mat_id: str) -> dict:
        """`asset_files_for` this library; a new per-asset file is added THERE and nowhere else."""
        return asset_files.asset_files_for(self.preferences, mat_id)

    def _hold_pre_edit_files(self, mat_id: str) -> dict:
        """Copy the asset's current files aside for the version store: {archive suffix: held path}."""
        import tempfile as _tempfile
        keep = _tempfile.mkdtemp(prefix="amaze_preedit_")
        held, copied = {}, False
        try:
            for kind, path in self.asset_files(mat_id).items():
                suffix = versions.SOURCE_KINDS.get(kind)
                if suffix is None or not os.path.exists(path):
                    continue
                target = os.path.join(keep, os.path.basename(path))
                shutil.copyfile(path, target)
                held[suffix] = target
            copied = True
        finally:
            if not (copied and held):
                shutil.rmtree(keep, ignore_errors=True)    # nothing held, or a copy raised: no folder left
        return held

    def asset_directories(self, mat_id: str) -> dict:
        """{kind: absolute path} for every directory asset `mat_id` owns, the version store today."""
        mat_id = str(mat_id)
        if not material.is_safe_asset_id(mat_id):
            return {}
        try:
            return {"versions": versions.versions_dir(
                self.preferences, mat_id, self.VERSION_SECTION)}
        except hostos.PathEscape as exc:  # owns no directory we can name; must not raise out of remove_asset
            debug.event("library", "version store path refused",
                        mat_id=mat_id, error=str(exc))
            return {}

    def remove_asset(self, index: QtCore.QModelIndex) -> None:
        """Remove one asset from the list, then from disk - `remove_rows` over one row."""
        if self.hasIndex(index.row(), 0):
            self.remove_rows([index.row()])

    def remove_rows(self, rows) -> int:
        """Delete these rows in ONE list write, their files only once it lands; returns how many went."""
        going = [(row, self._assets[row])
                 for row in sorted({int(r) for r in rows})
                 if 0 <= row < len(self._assets)]
        if not going:
            return 0
        owned = [self._owned_paths(asset.mat_id) for _row, asset in going]
        for row, _asset in reversed(going):    # highest first, so every row number still holds
            self._unlist_row(row)
        self.rebuild_thumbs()
        if not self.save():    # the list is the truth: answered False, nothing on disk is touched
            self._take_back_refused_removals(going)
            self._report_refused_delete(going[-1][1])
            return 0
        for files, folders in owned:
            self._unlink_owned(files, folders)
        return len(going)

    def _owned_paths(self, mat_id) -> tuple:
        """(files, folders) a deleted asset takes with it - from `asset_files()`, never a hand list."""
        return self.asset_files(mat_id), self.asset_directories(mat_id)

    def _report_refused_delete(self, asset) -> None:
        """Tell the user a delete did not happen because the list could not be written."""
        debug.event("library", "delete refused - the library list "
                    "could not be written", name=asset.name,
                    mat_id=str(asset.mat_id))
        debug.alert(
            messages.ASSET_NOT_DELETED_LIST_NOT_UPDATED % asset.name,
            key="delete-refused-index-write")

    @staticmethod
    def _unlink_owned(files: dict, folders: dict) -> None:
        """Remove what a listed-no-more asset owned, each guarded: Clean Library sweeps a held one."""
        for path in files.values():
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as exc:
                    debug.event("library", "asset file remove skipped",
                                file=path, error=str(exc))
        for path in folders.values():    # the version store goes with its id
            if os.path.isdir(path):
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    debug.event("library",
                                "asset version store remove skipped",
                                folder=path, error=str(exc))

    def _take_back_refused_removals(self, going) -> None:
        """Put back `(row, record)` pairs whose delete the save refused, in the model and the document."""
        for row, asset in going:    # ascending, so each lands where it stood
            row = min(max(row, 0), len(self._assets))    # the save's drain may have dropped rows above it
            self.beginInsertRows(QtCore.QModelIndex(), row, row)
            try:
                self._assets.insert(row, asset)
            finally:
                self.endInsertRows()
        self.rebuild_thumbs()
        self.resort()
        try:
            connector = database.DatabaseConnector(self.DB_FILENAME)
            for _row, asset in going:
                connector.unforget(asset.mat_id)    # else the next save carries out the declined delete
            if connector.serves(self.preferences.dir):    # a serves() refusal never ran set()
                connector.set({"assets": [asset.get_as_dict()
                                          for _row, asset in going]})    # set() dropped them
        except (AttributeError, TypeError) as exc:
            debug.event("library", "could not take back a row removal",
                        error=str(exc))

    def remove_category(self, cat: str) -> None:
        """Take this category off every asset in the library. Does not save."""
        for asset in self._assets:
            asset.remove_category(cat)

    def rename_category(self, old: str, new: str) -> None:
        """Rename this category on every asset in the library. Does not save."""
        for asset in self._assets:
            asset.rename_category(old, new)

    def find_asset_row_by_id(self, mat_id: str) -> int:
        """Row of the asset with the given id, or -1."""
        for row, asset in enumerate(self._assets):
            if str(asset.mat_id) == str(mat_id):
                return row
        return -1

    def find_asset_row_by_name(self, name: str) -> int:
        """Row of the asset whose (possibly sanitized) name matches uniquely, else -1."""
        from amaze.helpers import wording
        matches = []
        for row, asset in enumerate(self._assets):
            if asset.name == name or wording.sanitize_usd_path(asset.name) == name:
                matches.append(row)
        return matches[0] if len(matches) == 1 else -1

    def version_list(self, row: int) -> tuple:
        """([{n, name, author, date}] oldest first, the active number) for the asset at `row`."""
        if not 0 <= row < len(self._assets):
            return [], 0
        mat_id = str(self._assets[row].mat_id)
        return (versions.list_versions(self.preferences, mat_id, self.VERSION_SECTION),
                versions.active_version(self.preferences, mat_id, self.VERSION_SECTION))

    def switch_version(self, row: int, number: int) -> bool:
        """Make version `number` active for the asset at `row`, and tell everything downstream."""
        if not 0 <= row < len(self._assets):
            return False
        mat = self._assets[row]
        if not versions.switch_active(self.preferences, mat.mat_id, number,
                                      self.VERSION_SECTION):
            return False
        self._content_state[str(mat.mat_id)] = self._content_stat(
            mat.mat_id)
        self._drop_content_label_caches(mat.mat_id)
        self._add_thumb_paths(row, base_changed=False)    # the archive's own picture, no fresh render
        self._versions_changed(mat)
        return True

    def rename_version(self, row: int, number: int, name: str) -> bool:
        """Rename one version, evict the cache and tell the view."""
        if not 0 <= row < len(self._assets):
            return False
        mat = self._assets[row]
        if not versions.rename_version(
                self.preferences, mat.mat_id, number, name, self.VERSION_SECTION):
            return False
        self._versions_changed(mat)
        return True

    def _versions_changed(self, asset) -> None:
        """Drop the row's two ledger caches and repaint both version columns, wherever the row is now."""
        mat_id = str(asset.mat_id)
        self._version_count_cache.pop(mat_id, None)
        self._active_version_cache.pop(mat_id, None)
        self.row_changed(self.find_asset_row_by_id(asset.mat_id),
                         [self.VersionsRole, self.ActiveVersionRole])

    def _content_stat(self, mat_id: str):
        """(mtime_ns, size) of an asset's .mat, or None when absent; composes that one path only."""
        if not material.is_safe_asset_id(str(mat_id)):
            return None
        try:
            return hostos.disk_state(material.payload_path(
                self.preferences, mat_id, self.preferences.ext))
        except (hostos.PathEscape, TypeError):
            return None

    def _remember_content_state(self) -> None:
        """Baseline the content stale-write guard and clear the two per-id version caches."""
        self._content_state = {
            str(asset.mat_id): self._content_stat(asset.mat_id)
            for asset in self._assets
        }
        self._version_count_cache = {}  # per id, so a paint pass never opens the ledger; invalidated per write
        self._active_version_cache = {}
        try:  # one listdir seeds both caches for assets with no versions folder
            have = set(os.listdir(versions.store_root(
                self.preferences, self.VERSION_SECTION)))
        except OSError:
            have = set()
        for asset in self._assets:
            if str(asset.mat_id) not in have:
                self._version_count_cache[str(asset.mat_id)] = 0
                self._active_version_cache[str(asset.mat_id)] = ""

    def toggle_fav(self, row: int) -> None:
        """Flip this row's star in the owner's favourites store; no user or bad row writes nothing."""
        self.toggle_favs([row])

    def toggle_favs(self, rows) -> None:
        """Flip the star on every row in `rows` in ONE store write; rows outside the model are skipped."""
        wanted = {}
        flipped = []
        for row in rows:
            if not 0 <= row < self.rowCount():
                continue
            mat_id = self._assets[row].mat_id
            current = wanted[mat_id] if mat_id in wanted else \
                locations.is_favourite(self.preferences, mat_id)
            wanted[mat_id] = not current
            flipped.append(row)
        if not wanted:
            return
        locations.set_favourites(self.preferences, wanted)
        for row in flipped:
            self.row_changed(row, [self.FavoriteRole])


class MaterialLibrary(AssetLibrary):
    """The Material tab's model: records, their renderer labels, and the repaint a render asks for."""

    NOTES_SECTION = "material"
    TILE_FACE = "face_material"    # T06

    DB_FILENAME = "library.json"

    def __init__(self, preferences) -> None:
        super().__init__(preferences)
        self._usd_cache = {}  # both derived by reading the saved files, so cached per material id
        self._shader_type_cache = {}

    def _on_thumbnail_written(self, asset_id: str) -> None:
        """A background render's PNG landed: repaint that one tile, wherever its row is now."""
        row = self.find_asset_row_by_id(asset_id)
        if row >= 0:
            self._add_thumb_paths(row)

    def _drop_content_label_caches(self, mat_id=None) -> None:
        if not hasattr(self, "_usd_cache"):  # the base constructor reloads before this subclass's __init__ makes the caches
            return
        if mat_id is None:
            self._usd_cache = {}
            self._shader_type_cache = {}
        else:
            self._usd_cache.pop(mat_id, None)
            self._shader_type_cache.pop(mat_id, None)

    def is_usd_material(self, asset) -> bool:
        """True if the material is a USD-builder type, from its .interface file, cached per id."""
        mid = asset.mat_id
        if mid in self._usd_cache:
            return self._usd_cache[mid]
        try:
            node_type = material_files.get_saved_node_type(self.preferences, asset)
            result = node_type in material_files.LOP_CAPABLE_NODE_TYPES
        except Exception:
            result = False
        self._usd_cache[mid] = result
        return result

    def shader_type_label(self, asset) -> str:
        """Shader-type suffix (PBR, Standard Surface...) cached per id; '' for a renderer with no table."""
        if not material_files.shader_type_table(asset.renderer):
            return ""
        mid = asset.mat_id
        if mid in self._shader_type_cache:
            return self._shader_type_cache[mid]
        try:
            result = material_files.get_shader_type_label(self.preferences, asset)
        except Exception:
            result = ""
        self._shader_type_cache[mid] = result
        return result

    def renderer_label(self, asset) -> str:
        """'USD ' for a USD-builder type, ':<shader>' where a table names it: `USD Redshift:PBR`."""
        renderer = renderers.label(str(asset.renderer or "").strip())
        if not renderer:
            return ""
        label = ("USD " + renderer) if self.is_usd_material(asset) else renderer
        shader_type = self.shader_type_label(asset)
        if shader_type:
            label += ":" + shader_type
        return label
