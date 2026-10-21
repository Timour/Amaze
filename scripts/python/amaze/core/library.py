"""The shared asset model every library-backed section runs on, plus `MaterialLibrary` - the renderer-shaped half only Materials needs."""

import os
import json
import shutil
import time
from typing import Any
from PySide6 import QtCore, QtGui

import hou

from amaze.core import captures
from amaze.core import debug
from amaze.core import grid_engine
from amaze.core import locations
from amaze.core import material, database, renderers, thumbnails, tile_icons
from amaze.core import versions
from amaze.core import quarantine
from amaze.helpers import hostos
from amaze import messages
from amaze.prefs import prefs
from amaze.render import husk_job, nodes


def _count(count: int, noun: str) -> str:
    """"1 material" / "3 materials" - a count with a noun that agrees with it, because "material(s)" is the plural of a program, not of English."""
    return "%d %s" % (count, noun if count == 1 else noun + "s")


STAMP_SUFFIX = ".stamp.json"  # a per-asset recovery stamp, WRITE-ONLY: only repair.py may open one, and test_a_stamp_is_never_read_in_normal_operation holds that from source. ▸p/recovery-stamp


_STAMPED: dict = {}    # (library dir, asset id) -> repr of the record its stamp was last seen holding


class _StampWriter:
    """Rewrites the stamps that no longer match their record - call only after a SUCCESSFUL index write, since a stamp shadows what reached disk. ▸p/recovery-stamp"""

    def __init__(self, library):
        self._library = library

    @staticmethod
    def forget(preferences, mat_id) -> None:
        """Drop what this session knows of one asset's stamp, so the next save checks it again."""
        _STAMPED.pop((str(preferences.dir), str(mat_id)), None)

    @staticmethod
    def forget_library(preferences) -> None:
        """Drop what this session knows of every stamp in one library, once its rows are read afresh."""
        where = str(preferences.dir)
        for known in [key for key in _STAMPED if key[0] == where]:
            del _STAMPED[known]

    def refresh(self) -> int:
        """Write each stamp whose record changed since this session last saw it; returns how many."""
        written = 0
        preferences = self._library.preferences
        for asset in list(self._library._assets):
            known = (str(preferences.dir), str(asset.mat_id))
            try:
                record = asset.get_as_dict()
                seen = repr(record)
                if _STAMPED.get(known) == seen:
                    continue
                if not material.is_safe_asset_id(known[1]):
                    continue
                path = material.payload_path(preferences, known[1],
                                             STAMP_SUFFIX)
                payload = json.dumps(record, indent=1, sort_keys=True)
            except hostos.PathEscape:
                continue
            except (TypeError, ValueError) as exc:  # logged, never raised: the index write already landed
                debug.event("library", "recovery stamp could not be built",
                            mat_id=str(asset.mat_id), error=str(exc))
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    if handle.read() == payload:
                        _STAMPED[known] = seen
                        continue
            except (OSError, ValueError):
                pass                       # absent or unreadable: rewrite
            try:
                with hostos.scratch_beside(path) as scratch:
                    with open(scratch, "w", encoding="utf-8") as handle:
                        handle.write(payload)
                written += 1
                _STAMPED[known] = seen
            except OSError as exc:  # same: a safety net is never the thing being saved
                debug.event("library", "recovery stamp not written",
                            mat_id=str(asset.mat_id), error=str(exc))
        return written


QUARANTINE_PREFIX = quarantine.QUARANTINE_PREFIX  # re-exported: the quarantine itself lives in core/quarantine.py, which imports no hou, so helpers/restore.py can reach it from the pure-stdlib terminal tool
QUARANTINE_DAYS = quarantine.QUARANTINE_DAYS
quarantine_folder = quarantine.quarantine_folder
prune_quarantine = quarantine.prune_quarantine
quarantine_size = quarantine.quarantine_size
quarantine_file = quarantine.quarantine_file
quarantine_as = quarantine.quarantine_as


def asset_files_for(preferences, mat_id: str) -> dict:
    """{kind: path} of every FILE `mat_id` owns; {} for an unsafe id, and PathEscape propagates."""
    mat_id = str(mat_id)
    if not material.is_safe_asset_id(mat_id):    # read verbatim from library.json: `../x` escapes
        debug.event("library", "asset id cannot name a file - it owns "
                    "no paths", mat_id=mat_id)
        return {}

    def owned(suffix):
        return material.payload_path(preferences, mat_id, suffix)

    return {
        "mat": owned(preferences.ext),
        "interface": owned(".interface"),
        "builder": owned(nodes.BUILDER_SUFFIX),
        "stamp": owned(STAMP_SUFFIX),
        "cop": owned("_cop" + preferences.ext),
        "thumbnail": tile_icons.thumbnail_path(preferences, mat_id),
        "tile_icon": tile_icons.icon_image_path(preferences, mat_id),
        "capture": captures.asset_path(preferences, mat_id),
    }


class AssetLibrary(grid_engine.GridEngine,
                   QtCore.QAbstractTableModel):
    """The SHARED asset model - records, categories, tags, tile icons, saves, deletes, thumbnail plumbing and the connector's guards - that every library-backed section runs on. Nothing renderer-shaped lives here; that is `MaterialLibrary`. overview.md ▸ Models & storage carries the map."""

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
        "id": "IdRole",    # the two read-only rows the Material Info dialog used to carry, now list-mode columns ▸p/d03-retired
    }
    GRID_ROWS = ("_assets", "_mat_paths", "_row_keys")
    TILE_FACE = ""      # the section's generic face, `ui/<TILE_FACE>.svg` from its T frame ▸r/tile-faces
    NOTES_SECTION = "" # this model's notes-store key prefix - notes.note_key(NOTES_SECTION, id); every subclass names its own

    IdRole = QtCore.Qt.ItemDataRole.UserRole  # 256. THE FAMILY'S Qt ROLES ARE CLASS ATTRIBUTES, never assigned in __init__: an instance attribute SHADOWS a subclass's class attribute, and the base's __init__ runs last, so it would win every shared name (practice.md ▸ AN INSTANCE ATTRIBUTE SHADOWS THE CLASS ONE). test_role_numbers holds the whole table
    CategoryRole = QtCore.Qt.ItemDataRole.UserRole + 1  # 257 - 257-260 are what MultiFilterProxyModel switches on BY NUMBER
    FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 2  # 258
    RendererRole = QtCore.Qt.ItemDataRole.UserRole + 3  # 259
    TagRole = QtCore.Qt.ItemDataRole.UserRole + 4  # 260
    DateRole = QtCore.Qt.ItemDataRole.UserRole + 5  # 261
    RendererLabelRole = QtCore.Qt.ItemDataRole.UserRole + 6  # 262
    LicenceRole = QtCore.Qt.ItemDataRole.UserRole + 7  # 263
    CategoryColorRole = QtCore.Qt.ItemDataRole.UserRole + 8  # 264, read by the one tile delegate - this asset's category colour, "" for none, out of the SAME data dict the Categories model writes, so the grid repaints from a sidebar edit with nothing wired between them
    VersionsRole = QtCore.Qt.ItemDataRole.UserRole + 9  # 265 - how many versions; the delegate draws the chevrons badge at > 1
    NotesRole = QtCore.Qt.ItemDataRole.UserRole + 10  # 266, read by the one tile delegate - whether this asset carries a note, answered live from the notes store
    ActiveVersionRole = QtCore.Qt.ItemDataRole.UserRole + 11  # 267 - the ACTIVE version's name, "" when there are none; list mode has room to say which one you are looking at

    CropRole = QtCore.Qt.ItemDataRole.UserRole + 12  # 268 - a capture is viewport-shaped, so it fills the tile

    DB_FILENAME = ""  # which json file in the library dir backs this model; every subclass names its own, and "" breaks loudly rather than binding a nameless model to somebody's database

    def __init__(self, preferences: prefs.Prefs) -> None:
        super().__init__()
        self.preferences = preferences  # REQUIRED, and SHARED with the panel: per-model instances each re-read settings.json and drift after any save ▸p/duplication-third-verb

        db = database.DatabaseConnector(self.DB_FILENAME)
        self._data = database.load_survivable(db, self.preferences.dir)
        self._colours_seen = db._colours_adopted    # colours a merge took in, as the views know them

        self._assets = [self._asset_from_row(d)  # non-dict rows are SKIPPED, never allowed to abort the model: one junk row must not cost the whole library
                        for d in self._data["assets"]
                        if isinstance(d, dict)]
        _StampWriter.forget_library(self.preferences)
        self._remember_content_state()


        self._thumb_rows = {}  # engine deliveries arrive BY KEY; this maps them back to the row to repaint, and is rebuilt with the asset list
        thumbnails.signals.ready.connect(self._on_thumb_key_ready)  # through the RELAY, not the engine: the engine singleton is replaced on every module reload and would leave this model wired to a dead one
        captures.signals.landed.connect(self._on_capture_landed)    # from any panel or the shelf
        self.rebuild_thumbs()
        self.order_rows()    # in the grid's order before any view has the rows
        self.adopt_retired_text_into_notes()

    RETIRED_TEXT_FIELDS = ("about", "description")    #: record fields whose text is a COMMENT now, because the dialog that showed each one is gone ▸p/d03-retired

    def adopt_retired_text_into_notes(self) -> int:
        """Move every retired text field into its asset's COMMENT and clear it. Returns how many fields moved: ONE pass over the assets already in memory, reaching the notes store only for a row that still carries one. ▸p/d03-retired"""
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
        """One stored row becomes one record - THE reader every load path shares (construction, a library switch, an adopted peer row), so a subclass with a rule about its rows states it once."""
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
        """Point this model at whatever library Preferences now names. No worker teardown is needed: engine deliveries are keyed by material id, so an in-flight load cannot misroute."""
        self.beginResetModel()  # NOT bookkeeping - replacing the row set without it leaves proxies on their old count and the selection on an index into rows that are gone, so the next gesture acts on the wrong row ▸r/model-contracts
        try:
            self.preferences.load()
            db = database.DatabaseConnector(self.DB_FILENAME)
            self._data = database.load_survivable(
                db, self.preferences.dir, reload=True)
            self._colours_seen = db._colours_adopted

            self._assets = [
                self._asset_from_row(d) for d in self._data["assets"]
                if isinstance(d, dict)
            ]
            _StampWriter.forget_library(self.preferences)
            self._remember_content_state()  # a reload is a fresh read of the library, content included
            self._drop_content_label_caches()
            self.rebuild_thumbs()
            self.order_rows()
        finally:  # not a trailing call: a raising load must not leave the model stuck mid-reset, which freezes every view on it
            self.endResetModel()

    def flags(
        self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex
    ) -> QtCore.Qt.ItemFlag:
        default = super().flags(index)
        return default | QtCore.Qt.ItemFlag.ItemIsDragEnabled

    def rebuild_thumbs(self):
        """Rebuild the row->path and key->row maps. No loading happens here - the engine loads on first view (data()), so opening a big library costs only the visible screen."""
        specs = [self.tile_icon(row) for row in range(self.rowCount())]    # one store read per row
        self._mat_paths = [self._tile_image_path(row, spec)
                           for row, spec in enumerate(specs)]
        self._row_keys = [self._thumb_key(row, spec)
                          for row, spec in enumerate(specs)]    # row -> its key, the map read backwards
        self.rows_reordered()

    def rows_reordered(self) -> None:
        self._thumb_rows = {key: row for row, key in enumerate(self._row_keys)}

    def _add_thumb_paths(self, row: int, base_changed: bool = True):
        """Refresh ONE row's thumbnail maps and repaint it - never a whole-model rebuild, which made a multi-select icon pass O(rows^2) in store lookups. Serves add_asset, render_thumbnail and update_asset_content alike."""
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
        """The engine delivered (or failed) a key - repaint its row if it belongs to this model. Key-based, so reloads and reorders cannot misroute an image; a key from another library simply is not in this model's map."""
        row = self._thumb_rows.get(key)
        if row is None or not 0 <= row < self.rowCount():
            return
        self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def category_color(self, row: int) -> str:
        """The colour set on this asset's category, "" for none. One category per asset, so there is no rule about which of several wins."""
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
        """Shared-RAM-cache key for one row's picture: stable across reloads and collision-free across the models sharing the budget. EVERY input to the picture belongs in it - the library, the icon choice, the line weight - because nothing clears the app-wide cache on a library switch."""
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
        """Rename one asset - the one rename path every library section shares. A narrow write: the name field alone changes, then the ordinary save chain runs. A blank or unchanged name is a no-op."""
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
        """ADD the tags in a comma-separated line to what this asset already has, keeping its own and dropping duplicates - the multi-selection write, where `set_tile_tags` would flatten every row to one line. A blank line adds nothing."""
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
        """This asset's category - what the Customize dialog's Category dropdown shows. One category per asset, so there is no rule about which of several wins."""
        if not 0 <= row < len(self._assets):
            return ""
        cats = self._assets[row].categories or []
        return str(cats[0]) if cats else ""

    def set_tile_category(self, row: int, name: str, save: bool = True) -> bool:
        """MOVE one asset to `name`, replacing whatever it had - a narrow write beside `set_tile_name`, then the ordinary save chain. Unlike name and tags this one runs over a whole selection, so a blank is a no-op rather than a clear."""
        name = (name or "").strip()
        if not 0 <= row < len(self._assets) or not name:
            return False
        asset = self._assets[row]
        if list(asset.categories or []) == [name]:
            return False
        asset.categories = name    # the RECORD's own setter splits and drops the blanks
        self._edited(asset, save)
        return True

    def tile_tags(self, row: int) -> str:
        """This asset's tags as ONE comma-separated line - what the Customize dialog's Tags field shows and edits."""
        if not 0 <= row < len(self._assets):
            return ""
        return ", ".join(self._assets[row].tags or [])

    def set_tile_tags(self, row: int, line: str, save: bool = True) -> bool:
        """REPLACE one asset's tags from a comma-separated line: what is in the field becomes the tags, so an empty line clears them. A narrow write beside `set_tile_name`, then the ordinary save chain."""
        if not 0 <= row < len(self._assets):
            return False
        asset = self._assets[row]
        before = [tag for tag in (asset.tags or []) if tag]
        asset.tags = line or ""    # the RECORD's own setter splits and drops the blanks - the one splitter, never a second copy of it here
        if [tag for tag in (asset.tags or []) if tag] == before:
            return False
        self._edited(asset, save)
        return True

    def tile_icon(self, row: int) -> dict:
        """This row's chosen icon, {} when it shows its render. `icons.json` is the ONE home, keyed by asset id; same name as the file sections' version so one panel handler serves every tile in the app."""
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
        """WHAT THIS ROW IS KEYED BY for tile icons - the asset's own id, "" for a row that does not exist. Hold this, never a row NUMBER: a reset re-numbers everything and kills every persistent index, and the non-modal Customize dialog outlives exactly that."""
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
        """Give every row in `rows` the icon `spec` in ONE store write; answers how many were not written."""
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
        """Recompose every icon in this library - for when the LOOK changed (the line-weight preference) rather than the choice."""
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
        return str(asset.renderer or "").strip()  # the tile subtitle / Type column for one asset: the KIND field as it stands (a node context, a code language). MaterialLibrary overrides with the renderer-shaped dressing; the base knows no renderer

    def _drop_content_label_caches(self, mat_id=None) -> None:
        """Evict whatever per-id labels a subclass derives from asset CONTENT - called by the shared reload and version-switch paths, which cannot know what a subclass caches. The base derives none."""

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
                cached = versions.version_count(self.preferences, mat_id)
                self._version_count_cache[mat_id] = cached
            return cached

        if role == self.ActiveVersionRole:
            mat_id = str(asset.mat_id)
            cached = self._active_version_cache.get(mat_id)
            if cached is None:
                cached = versions.active_version_name(
                    self.preferences, mat_id)
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
        """Write the index to disk as json. True ONLY when it reached the file - honour that answer, because add_asset writes the payload files before this runs and a caller that cannot tell a refused save from a completed one reports success for an asset the library does not list."""
        db = database.DatabaseConnector(self.DB_FILENAME)
        if not db.serves(self.preferences.dir):  # THE CONNECTOR MAY HAVE MOVED: it is shared by filename across every pane, so a library switch elsewhere repoints it and this model still holds the OLD library's rows
            debug.event("library", "save refused - the connector now "
                        "serves another library",
                        model=self.preferences.dir, connector=db._path)
            debug.alert(
                messages.LIBRARY_NOT_SAVED_ANOTHER_PANEL,
                key="connector-moved")
            return False
        self.apply_refresh(db)    # the sidebar shares this connector: its save may have merged a peer's edit
        data = {}
        data["assets"] = [asset.get_as_dict() for asset in self._assets]
        db.set(data)
        stored = db.save()
        from amaze.core import model_registry
        model_registry.apply_merged(db, also=self)    # every model on this file takes what the save merged
        if stored and db._save_outcome != "identical-skip":
            _StampWriter(self).refresh()  # AFTER the index write and only when it landed; skipped on an identical-skip, where no record changed and the scan would find nothing to rewrite ▸p/recovery-stamp
        return stored

    def apply_refresh(self, db) -> bool:
        """Drain what any merge on this connector left for the model. True when the model moved."""
        rows, fields, gone = (db.take_adopted(), db.take_adopted_fields(),
                              db.take_dropped())
        self._adopt_rows(rows)
        self._adopt_fields(fields)
        self._drop_rows(gone)
        recoloured = db._colours_adopted != self._colours_seen
        self._colours_seen = db._colours_adopted
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
        """Apply `(id, field, value)` a peer changed onto the records holding them, through the ONE row reader, and tell the views. The record OBJECT is kept - dialogs and delegates hold references to it, so its state is refreshed rather than the record replaced."""
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
        """Insert rows another session added, with the row signals a view needs. A row this build cannot parse is skipped rather than allowed to abort the model - it stays on disk untouched."""
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
        """Remove rows another session deleted, with the row signals a view needs. Nothing on disk is touched - the deleting session already unlinked the files."""
        if not isinstance(rows, list):  # a list, by contract
            return
        ids = {str(row.get("id", "")) for row in rows
               if isinstance(row, dict)}
        ids.discard("")
        if not ids:
            return
        removed = False
        for index in range(len(self._assets) - 1, -1, -1):  # ONE pass, highest row first so indices stay valid - a per-row find_asset_row_by_id scan was O(dropped x library)
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
        """Write one row's editable fields and save. about/license default to None = leave unchanged; save=False defers the index write to the CALLER, so a multi-select loop saves once after the last row rather than serialising the whole document per row."""

        asset = self._assets[index.row()]

        name = name if material.MULTIPLE_VALUES not in name else asset.name
        cats = (cats if material.MULTIPLE_VALUES not in cats
                else ", ".join(asset.categories))

        if material.MULTIPLE_VALUES not in tags:
            tags = self.sanitize_tags(tags)
        else:
            tags = ", ".join(asset.tags)

        if fav is not None:  # THE STAR IS THE USER'S: it goes to the library's favourites store under its owner, never onto the shared record, and None leaves it alone
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
        """Drop every asset to its FIRST category, and return how many were collapsed. Idempotent, so it is safe on every load, and it saves only when something actually changed."""
        changed = 0
        for asset in self._assets:
            if len(asset.categories) > 1:
                asset.categories = asset.categories[0]  # setter takes a str
                changed += 1
        if changed:
            self.save()
        return changed

    CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE = True  # what a refused index write leaves behind for THIS model: an asset section writes its payload files before the list, so Repair can put the row back, where Code stores its snippet inline and there is nothing to recover. Subclasses override

    def report_refused_index_write(self, asset) -> None:
        """Say that the content was written and the list was not - call it from EVERY add_asset, which is why it is hoisted here rather than left on one subclass. The files are deliberately left where they are: content without a row is the safe direction of this failure, and Repair Library recovers exactly that shape."""
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
        return asset_files_for(self.preferences, mat_id)

    def _hold_pre_edit_files(self, mat_id: str) -> dict:
        """Copy the asset's CURRENT files aside for the version store: {archive suffix: held path}, per `versions.SOURCE_KINDS`. Read the source dict by KIND, never by filename suffix - `<id>_cop.mat` shares ".mat" with the material and `<id>_icon.png` shares ".png" with the render, so a suffix key lets whichever comes later overwrite the real payload. Kinds SOURCE_KINDS does not name are not versioned."""
        import tempfile as _tempfile
        keep = _tempfile.mkdtemp(prefix="amaze_preedit_")
        held = {}
        for kind, path in self.asset_files(mat_id).items():
            suffix = versions.SOURCE_KINDS.get(kind)
            if suffix is None or not os.path.exists(path):
                continue
            target = os.path.join(keep, os.path.basename(path))
            shutil.copyfile(path, target)
            held[suffix] = target
        return held

    def asset_directories(self, mat_id: str) -> dict:
        """{kind: absolute path} for every DIRECTORY asset `mat_id` owns - the version store, today. Kept apart from asset_files() because every caller of THAT one unlinks or copyfiles what it gets and neither works on a directory; remove_asset must still take these, or a deleted asset leaves its version store behind under an id no list names any more. Same containment rule as asset_files()."""
        mat_id = str(mat_id)
        if not material.is_safe_asset_id(mat_id):
            return {}
        try:
            return {"versions": versions.versions_dir(self.preferences,
                                                      mat_id)}
        except hostos.PathEscape as exc:  # "owns no directory we can name" - it must not raise out of remove_asset, where failing to sweep is a leak but raising after the list was written is a broken library
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
        """Row of the asset whose (possibly sanitized) name matches, but only if the match is UNIQUE - with duplicates there is no safe answer, so -1, and the caller treats the save as a new asset."""
        from amaze.helpers import helpers
        matches = []
        for row, asset in enumerate(self._assets):
            if asset.name == name or helpers.sanitize_usd_path(asset.name) == name:
                matches.append(row)
        return matches[0] if len(matches) == 1 else -1

    def switch_version(self, row: int, number: int) -> bool:
        """Make version `number` the active one for the asset at `row`. Everything downstream of the base files gets told here - the content baseline (or the next Update Existing reads our own switch as another session's write and refuses), the per-id label caches, the thumbnail and the tile."""
        if not 0 <= row < len(self._assets):
            return False
        mat = self._assets[row]
        if not versions.switch_active(self.preferences, mat.mat_id, number):
            return False
        self._content_state[str(mat.mat_id)] = self._content_stat(
            mat.mat_id)
        self._drop_content_label_caches(mat.mat_id)
        self._version_count_cache.pop(str(mat.mat_id), None)
        self._active_version_cache.pop(str(mat.mat_id), None)
        self._add_thumb_paths(row)
        self.row_changed(row, [self.VersionsRole, self.ActiveVersionRole, QtCore.Qt.ItemDataRole.DecorationRole])
        return True

    def rename_version(self, row: int, number: int, name: str) -> bool:
        """Rename one version, and TELL the view - list mode paints the active version's name in its own column, so a rename that does not evict the cache and emit leaves the row showing the old name until something unrelated repaints it."""
        if not 0 <= row < len(self._assets):
            return False
        mat = self._assets[row]
        if not versions.rename_version(
                self.preferences, mat.mat_id, number, name):
            return False
        self._active_version_cache.pop(str(mat.mat_id), None)
        model_index = self.index(row, 0)
        self.row_changed(model_index.row(), [self.ActiveVersionRole])
        return True

    _SCRATCH_TAILS = (".writing", ".capturing", ".tmp", ".part", ".new")
    _SCRATCH_MIN_AGE = 60 * 60

    def _sweep_dead_scratches(self, folder: str, quarantined: list) -> int:
        """Move scratch files older than an hour into the quarantine. A scratch is always ours and always means a save died partway, but a fresh one may be another session's live write - so age gates it, by MTIME deliberately, since a scratch carries no date in its name and its mtime IS its write time."""
        moved = 0
        try:
            names = os.listdir(folder)
        except OSError:
            return 0
        now = time.time()
        for name in names:
            if not name.endswith(self._SCRATCH_TAILS):
                continue
            full = os.path.join(folder, name)
            try:
                age = now - os.path.getmtime(full)
            except OSError:
                continue
            if age < self._SCRATCH_MIN_AGE:
                continue
            if quarantine_file(self.preferences.dir, full):
                moved += 1
                quarantined.append(name)
                debug.event("cleanup", "dead scratch quarantined",
                            file=full, age_hours=round(age / 3600, 1))
        return moved

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
        """Baseline for the content stale-write guard - what every asset's .mat looked like when THIS session read the library - and the blank slate for the two per-id version caches, which are cleared TOGETHER because they come from the same ledger. A stat each, not a hash: nothing rewrites a .mat byte-identically, so the false-conflict case the fingerprint guard exists for cannot arise here."""
        self._content_state = {
            str(asset.mat_id): self._content_stat(asset.mat_id)
            for asset in self._assets
        }
        self._version_count_cache = {}  # per id, so the delegate's paint pass never opens the ledger: a repaint runs per visible tile per frame. Invalidated point-wise on the writes that change a count
        self._active_version_cache = {}
        try:  # ONE listdir seeds both caches for every asset with NO versions folder, the overwhelming case; assets WITH one stay lazy and their first ask still reads the ledger
            have = set(os.listdir(os.path.join(
                self.preferences.dir, self.preferences.asset_dir,
                "versions")))
        except OSError:
            have = set()
        for asset in self._assets:
            if str(asset.mat_id) not in have:
                self._version_count_cache[str(asset.mat_id)] = 0
                self._active_version_cache[str(asset.mat_id)] = ""

    def cleanup_db(self, show_dialog: bool = True) -> int:
        """Clean Library: scan, report rows whose files are missing, quarantine files no section lists, rescue uncategorised rows. Never renders, never unlinks anything in the library - a file it takes is MOVED to the quarantine, which prune_quarantine empties after QUARANTINE_DAYS - and it holds the ownership sweep back on incomplete knowledge. Read ▸p/clean-library-sweep before changing any of it. Returns 1 if anything was rescued. The summary lines are left on self.last_cleanup_summary EITHER WAY; show_dialog=False only skips the dialog, so the panel can combine several libraries into one report."""
        from amaze.helpers import helpers
        summary = []

        assets_dir = os.path.join(  # THE ASSET FOLDER MUST BE READABLE BEFORE ANY OF THIS - never delete on incomplete knowledge, and the FOLDER is knowledge as much as a sibling list is
            self.preferences.dir, self.preferences.asset_dir)
        if not os.path.isdir(assets_dir):
            debug.event("cleanup", "refused - the asset folder is not readable",
                        path=assets_dir)
            message = (
                "Clean Library did nothing: the asset folder\n%s\n"
                "could not be read. Nothing was changed.\n\n"
                "If this library lives in a synced folder, let the sync "
                "finish and try again." % assets_dir)
            self.last_cleanup_summary = [message]
            ui = getattr(hou, "ui", None)  # show_dialog defaults TRUE, so the headless spelling of this call is the bare one ▸r/status-bar
            if show_dialog and ui is not None:
                ui.displayMessage(message)
            return 0

        summary.extend(database.DatabaseConnector.take_integrity_notes())  # load-time findings go BEFORE the sweep's own numbers: a list that shrank past half since its newest snapshot reads exactly like a healthy one unless somebody says both numbers out loud

        rows_to_remove = []  # --- Pass 1: scan assets, with no mutation during iteration ---
        missing_thumbs = 0
        quarantined = []
        quarantined_paths = []  # [source, destination] per moved file, for the ONE closing record, which is complete on purpose ▸p/clean-library-sweep
        for row, asset in enumerate(self._assets):
            owned = self.asset_files(asset.mat_id)
            interface_path = owned["interface"]
            mat_path = owned["mat"]
            img_path = owned["thumbnail"]

            iface_ok = os.path.exists(interface_path)
            mat_ok = os.path.exists(mat_path)
            if not iface_ok or not mat_ok:
                debug.event(
                    "cleanup", "asset files missing on disk",
                    mat_id=str(asset.mat_id), name=asset.name,
                    interface=iface_ok,
                    mat=mat_ok,
                )
                rows_to_remove.append(row)
            elif not os.path.exists(img_path):
                missing_thumbs += 1
                debug.event(
                    "cleanup", "thumbnail missing on disk",
                    mat_id=str(asset.mat_id), name=asset.name,
                )

        if rows_to_remove:  # --- Pass 2: REPORTED, NEVER REMOVED - a row holds tags, a description and a date that exist nowhere else (the note and the star have their own stores), and nothing mutates the row set before the sweep runs ---
            names = sorted(str(self._assets[row].name) or "(unnamed)"
                           for row in rows_to_remove)
            summary.append(
                "%s kept in your library, but %s files are missing: %s.\n"
                "Nothing was removed - the entry's tags, notes and "
                "favourites would go with it, and a file that has not "
                "finished syncing looks the same as one that is gone. "
                "If they really are gone, select them in Amaze "
                "and use Delete."
                % (_count(len(rows_to_remove), "material"),
                   "their" if len(rows_to_remove) > 1 else "its",
                   helpers.and_list(names[:8]) + (
                       " and %d more" % (len(names) - 8)
                       if len(names) > 8 else "")))
        if missing_thumbs:
            summary.append(  # only quote a label that EXISTS - grep the package before naming a control here ▸p/quoted-strings-go-stale
                "No thumbnail image yet for %s - select %s in Amaze and use "
                "Update Render when convenient, since a render takes "
                "time." % (_count(missing_thumbs, "material"),
                           "it" if missing_thumbs == 1 else "them"))

        known_ids, unreadable, absent_traces, empty_sections = \
            (  # --- Pass 3: files in the shared folders that NO section lists - orphanhood is relative to every sibling list, so the union has to be finished before anything is called unclaimed ---
                self._all_known_asset_ids())
        lone_count = 0
        if unreadable:
            summary.append(  # "could not be CHECKED", never "could not be read": three ways land here and only one is a failed read, and the reason goes on its own line per section
                "Nothing was deleted: Amaze could not check %s, so files "
                "that belong to it look exactly like files nothing needs "
                "any more."
                % helpers.and_list([name for name, _why in unreadable])
            )
            for name, why in unreadable:
                summary.append("%s: %s." % (name, why))
            for line in self._what_an_empty_section_means(empty_sections):
                summary.append(line)
            if absent_traces:
                summary.append(  # NAME THE WAY OUT AND WHAT IT COSTS: the trace is usually a .bak, which is what Repair would put the section back FROM, so this must not send anyone to delete it unwarned
                    "If you deleted %s on purpose, remove %s from the "
                    "library folder as well - while it is there, Amaze "
                    "reads the section as one that has not finished "
                    "arriving and will not risk deleting files it may own. "
                    "One thing first: that file is also a saved copy of "
                    "the list, and it is what Repair would use to bring "
                    "the section back. If you are not sure, run Repair and "
                    "look at it before you remove anything."
                    % (helpers.and_list(sorted(
                        "your %s list" % database.section_label(name)
                        for name in absent_traces)),
                       helpers.and_list(sorted(absent_traces.values())))
                )
            summary.append(self._the_repair_route())  # LAST, and once for every cause however many held the sweep back
            unreadable_abort = True
        else:
            unreadable_abort = False
        for folder in (  # dead scratches first: a hard kill mid-write leaves a fresh `<name>.<rand>.writing` each time and the classifier rightly refuses to read them as assets, so nothing else would ever take them
                os.path.join(self.preferences.dir,
                             self.preferences.asset_dir),
                os.path.join(self.preferences.dir,
                             self.preferences.img_dir)):
            lone_count += self._sweep_dead_scratches(folder, quarantined)

        from amaze.core import repair  # imported HERE: repair imports this module, and a top-level import would also put stamps in the core's import surface ▸p/recovery-stamp
        mats_path = os.path.join(self.preferences.dir, self.preferences.asset_dir)
        mat_names = [] if unreadable_abort else os.listdir(mats_path)  # ONE listing, shared by the stamp scan and the sweep below: a second listing a moment later can disagree, and it is wrong in both directions ▸p/clean-library-sweep
        awaiting_repair = {} if unreadable_abort else repair.stamped_assets(
            self.preferences.dir, self.preferences.asset_dir,
            names=mat_names)
        spared = set()  # AWAITING REPAIR IS NOT LEFT OVER - files with a readable stamp and no row are the one shape Repair exists for, and a stamp with no .mat beside it is normal (Code keeps its text inline)

        def take_unclaimed(folder, names, extensions, tail) -> int:
            """Quarantine the files here no list claims, sparing an id awaiting Repair; answers how many."""
            taken = 0
            for f in names:
                split = database.asset_id_for_file(f, extensions, tail)
                if split is None or str(split) in known_ids:
                    continue
                if str(split) in awaiting_repair:
                    spared.add(str(split))    # in EVERY folder, or Repair puts the row back blank
                    continue
                moved = quarantine_file(self.preferences.dir,
                                        os.path.join(folder, f))
                if moved:
                    taken += 1
                    quarantined.append(f)
                    quarantined_paths.append([os.path.join(folder, f), moved])
            return taken

        lone_count += take_unclaimed(    # the classifier the guard above counts with
            mats_path, mat_names, repair.ASSET_SIDECARS, "_cop")
        images = os.path.join(self.preferences.dir, self.preferences.img_dir)
        lone_count += take_unclaimed(    # "_icon" is a tile icon as "_cop" is a companion
            images,
            [] if unreadable_abort or not os.path.isdir(images)    # img/ may not exist yet
            else os.listdir(images),
            (".png",), "_icon")
        if quarantined_paths:
            debug.event("cleanup", "files quarantined",  # ONE record carrying EVERY move: it is the only trace of where a file went, so a sample is useless the moment somebody needs one back
                        moved=len(quarantined_paths),
                        files=quarantined_paths)
        if lone_count:
            shown = sorted(quarantined)[:8]  # NAMES, not a bare count, and say where they went: nothing is deleted, so the honest sentence is the one that tells you where to look if the sweep was wrong
            held, held_bytes = quarantine_size(self.preferences.dir)
            summary.append(
                "Moved %s that no section listed out of your library: %s.\n"
                "Nothing was deleted. They are in Amaze's own folder on "
                "this computer, not in your library, so they do not sync "
                "and do not travel - %s held there in total (%s). Open "
                "Preferences to find the folder, and empty it yourself "
                "once you are sure."
                % (_count(lone_count, "leftover file"),
                   helpers.and_list(shown) + (
                       " and %d more" % (lone_count - len(shown))
                       if lone_count > len(shown) else ""),
                   _count(held, "file"),
                   "%.1f MB" % (held_bytes / 1048576.0)))
            summary.append(
                "Anything moved out this way is kept for %d days and then "
                "removed, so that folder cannot grow without end."
                % QUARANTINE_DAYS)
            prune_quarantine(self.preferences.dir)

        if spared:
            shown_kept = sorted(  # SAY WHAT WAS KEPT, by NAME rather than by a section count - the shared folder holds materials, nodes and snippets, so a count noun would be a guess in the one sentence that has to be trustworthy. This is why the stamp reader hands back the record, not just the id
                str(awaiting_repair.get(mat_id, {}).get("name") or mat_id)
                for mat_id in spared)
            summary.append(
                "%s %s not listed in your library, but %s can still be "
                "put back. Nothing was moved or deleted."
                % (helpers.and_list(shown_kept[:8]) + (
                       " and %d more" % (len(spared) - 8)
                       if len(spared) > 8 else ""),
                   "is" if len(spared) == 1 else "are",
                   "it" if len(spared) == 1 else "they"))
            if not unreadable_abort:  # ONE repair route in a summary, never two - the refusal branch above already appended it for its own causes
                summary.append(self._the_repair_route())

        mark_rescued = 0  # --- Pass 4: rescue assets with no valid category, and normalise legacy whitespace-mangled category data ---
        rescued_count = 0
        for asset in self._assets:
            cats = asset.categories
            if isinstance(cats, str):
                cats = cats.split(",") if cats else []
            cats = [c.strip() for c in cats if isinstance(c, str) and c.strip() != ""]
            if not cats:
                cats = ["Uncategorized"]
                mark_rescued = 1
                rescued_count += 1
                debug.event(
                    "cleanup", "asset rescued to Uncategorized",
                    mat_id=str(asset.mat_id), name=asset.name,
                )
            asset.categories = ", ".join(cats)
        if rescued_count:
            summary.append(
                "Moved %s with no category into 'Uncategorized'."
                % _count(rescued_count, "material")
            )

        if mark_rescued:  # mark_rescued alone: pass 2 only reports, so rows_to_remove mutates nothing and saving on it would write an index with nothing to write
            self.save()

        self.last_cleanup_summary = list(summary)

        closing = getattr(hou, "ui", None)
        if show_dialog and closing is not None:  # --- one summary dialog for the whole run ---
            if summary:
                header = ("Clean Library stopped before deleting any files:"  # THE HEADER SAYS WHICH OF THE TWO HAPPENED: one header for both had a refusal opening with "cleanup finished"
                          if unreadable_abort
                          else "Library cleanup finished:")
                closing.displayMessage(header + "\n\n- " + "\n- ".join(summary))
            else:
                closing.displayMessage(
                    messages.CLEANUP_FOUND_NOTHING_TO_CLEAN)

        return mark_rescued

    def _what_an_empty_section_means(self, empty_sections: list) -> list:
        """ONE line for ALL the sections that list nothing, saying why Amaze will not decide on its own - the refusal above states the fact, and this states what the reader cannot know from it: that the two explanations look identical from here. One line rather than one each, or two empty sections produce two near-identical thirty-word sentences in one dialog."""
        from amaze.helpers import helpers
        if not empty_sections:
            return []
        sections = helpers.and_list(sorted(database.section_label(filename)
                                    for filename in empty_sections))
        return ["%s: a list that holds nothing looks the same whether "
                "nothing was ever saved there or it failed to load this "
                "time, so Amaze will not decide on its own which it is."
                % sections]

    def _the_repair_route(self) -> str:
        """The ONE next step for every way this sweep can be held back, appended once however many causes there were. The sentence must carry three things or it is a dead end: send the reader to Repair, say how to get the shelf TAB (registered is not displayed, so a fresh machine has the tools without one), and say to RESTART - this is only reachable from the panel, so this Houdini has already read the library and its connector would write that document back over anything put right."""
        return (
            "Run the Repair tool on the Amaze shelf to see what is wrong: "
            "it names the lists that will not load, the files nothing "
            "accounts for, and what each saved copy would bring back - and "
            "it never deletes anything. To let it put things right as "
            "well, close Amaze, quit Houdini, start it again and run "
            "Repair before you open Amaze. If your shelf has no Amaze tab, "
            "right-click the shelf tabs, choose Shelves, then Amaze.")

    def _files_no_section_accounts_for(self, known_ids: set):
        """Names of the files in the asset folder that NO section lists, or None when the folder could not be read at all. PASS A FINISHED UNION as `known_ids` - orphanhood is relative to every list sharing the directory, and a half-built one reports a live COP asset's files as unclaimed. None rather than [] on a failed listing, because an empty list reads as a clean folder, and that reading is what lets the sweep run. ▸p/clean-library-sweep"""
        from amaze.core import repair    # here: repair imports this module
        return repair.unlisted_in(self.preferences.dir,
                                  self.preferences.asset_dir,
                                  repair.ASSET_SIDECARS, "_cop", known_ids)

    def _all_known_asset_ids(self) -> tuple:
        """(ids, unreadable, absent_traces, empty_sections) for EVERY database file in the library dir, read straight off disk, so one library's cleanup never deletes files belonging to another. `unreadable` is (section name, why) as two halves because the caller writes them into two different sentences; `absent_traces` maps a database that is merely NOT THERE YET to the trace that says so, and `empty_sections` the ones that parse fine and list nothing while files sit unaccounted for - separate because the way out is a different sentence for each. code.json belongs here even though snippets keep their text inline: a Code asset with a tile icon owns a PNG in the shared image folder. ▸p/clean-library-sweep"""
        ids = {str(a.mat_id) for a in self._assets}
        unreadable = []
        absent_traces = {}
        lists_nothing = []
        claimed, unreadable_files = database.ids_claimed_by(  # THE READ IS NOT THIS METHOD'S - "which ids does each database claim" has one home, and a second copy is how two readers of these shared folders come to disagree about who owns a file. What stays here is the POLICY
            self.preferences.dir, database.DATABASES)
        for file_ids in claimed.values():    # Colors too: a palette's stamp sits in mat/, as Repair counts it
            ids |= file_ids
        for filename in database.ID_CLAIMING_DATABASES:
            full = os.path.join(self.preferences.dir, filename)
            own = filename == self.DB_FILENAME  # THIS model's own database is checked like any other: its in-memory ids are only there because a load put them there, and a REFUSED load leaves _assets honestly empty
            if filename in unreadable_files:
                unreadable.append((database.section_name(filename),  # a sibling that EXISTS and will not parse is the dangerous case; no parse position on screen, since this is interpolated into the message the user acts on and the log already has the reason
                                   "Amaze cannot read it"))
                debug.event("cleanup", "sibling database unreadable",
                            file=full, own=own)
                continue
            if filename not in claimed:
                evidence = database.absent_but_known(  # ABSENT IS FINE ONLY WHEN NOTHING BESIDE IT SAYS IT WAS HERE; otherwise it has not arrived yet and the files it owns are indistinguishable from leftovers
                    self.preferences.dir, filename)
                if not evidence:
                    continue
                unreadable.append(  # "not there yet", never "not on disk": the shared sentence ends in "could not be read", which that would fight
                    (database.section_name(filename),
                     "it is not there yet - %s beside it says it was here"
                     % evidence))
                absent_traces[filename] = evidence
                debug.event("cleanup", "database absent but known",
                            file=full, evidence=evidence, own=own)
                continue
            file_ids = claimed[filename]  # UNION, never replace: the model's own disk rows are not its in-memory ones, since another session can have added rows and a row this session added may not have reached disk
            if not file_ids and filename in database.ASSET_FILE_OWNERS:  # a list that holds nothing is NOT authoritatively empty; the dangerous condition is emptiness AND unaccounted files, decided below once every sibling is read. ASSET_FILE_OWNERS narrows it to the lists that could own one
                lists_nothing.append(filename)

        empty_sections = []
        folder = str(self.preferences.asset_dir).rstrip("/\\")  # the folder as the user sees it in Finder; prefs stores it with the separator, and "the mat/ folder" in a sentence reads as a typo
        if lists_nothing and not unreadable:
            unaccounted = self._files_no_section_accounts_for(ids)
            if unaccounted is None:  # nearly unreachable, since cleanup_db checks the folder first - but a failed listing must never arrive here reading as an empty one, which is what lets the sweep run
                empty_sections = list(lists_nothing)
                for filename in lists_nothing:
                    unreadable.append(
                        (database.section_name(filename),
                         "it lists nothing at all, and the %s folder could "
                         "not be checked for what is left over" % folder))
            elif unaccounted:
                empty_sections = list(lists_nothing)
                for filename in lists_nothing:
                    unreadable.append(
                        (database.section_name(filename),
                         "it lists nothing at all, while %s in the %s folder "
                         "are listed by no section"
                         % (_count(len(unaccounted), "file"), folder)))
                debug.event("cleanup", "section lists nothing and files are "
                            "unaccounted for", sections=list(lists_nothing),
                            unaccounted=len(unaccounted),
                            examples=unaccounted[:5])
            else:
                debug.event("cleanup", "section lists nothing and nothing is "
                            "unaccounted for - sweeping",
                            sections=list(lists_nothing))
        elif lists_nothing:  # already refusing for another reason, so the union is incomplete and nothing may be called unaccounted for from it; recorded, because this is the combination that hides one problem behind another
            debug.event("cleanup", "section lists nothing, not checked "
                        "further - already held back",
                        sections=list(lists_nothing),
                        held_back_by=list(unreadable))
        return ids, unreadable, absent_traces, empty_sections

    def toggle_fav(self, row: int) -> None:
        """Flip this row's star. Goes to the library's favourites store under its owner, never onto the shared record, so one user's stars cannot collide with another's - and with no user picked it refuses silently. A row outside the model writes nothing: -1 is what an invalid index answers and it would otherwise star the LAST asset."""
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

    def render_thumbnail(self, row) -> None:
        """Re-render one row's preview. The base has nothing to render; the sections that do override this."""

    def render_thumbnails(self, rows) -> None:
        for row in rows:  # one row at a time through each section's own `render_thumbnail`; MaterialLibrary overrides with the shared-scaffold Karma batch, which must NOT be routed to other sections - it would shaderball node setups and code snippets
            if 0 <= row < self.rowCount():
                self.render_thumbnail(row)


class MaterialLibrary(AssetLibrary):
    """The Material tab's model: renderer, labels, thumbnail batches, import routing, conversion."""

    NOTES_SECTION = "material"
    TILE_FACE = "face_material"    # T06

    DB_FILENAME = "library.json"

    def __init__(self, preferences) -> None:
        super().__init__(preferences)
        self._usd_cache = {}  # both are derived by READING the saved files, so they are cached per material id rather than paid on every repaint
        self._shader_type_cache = {}
        husk_job.jobs.thumbnailWritten.connect(self._on_thumbnail_written)    # a bound method

    def _on_thumbnail_written(self, asset_id: str) -> None:
        """A background render's PNG landed: repaint that one tile, wherever its row is now."""
        row = self.find_asset_row_by_id(asset_id)
        if row >= 0:
            self._add_thumb_paths(row)

    def _drop_content_label_caches(self, mat_id=None) -> None:
        if not hasattr(self, "_usd_cache"):  # USD-ness and shader type, this model's two content-derived labels: evicted whole on a reload, per id on a version switch or content update. The guard is because the base constructor reloads before this subclass's __init__ has made the caches
            return
        if mat_id is None:
            self._usd_cache = {}
            self._shader_type_cache = {}
        else:
            self._usd_cache.pop(mat_id, None)
            self._shader_type_cache.pop(mat_id, None)

    def is_usd_material(self, asset) -> bool:
        """True if the material is a USD-builder type, detected from its .interface file and cached per material id."""
        mid = asset.mat_id
        if mid in self._usd_cache:
            return self._usd_cache[mid]
        try:
            handler = nodes.NodeHandler(self.preferences)
            node_type = handler.get_saved_node_type(asset)
            result = node_type in nodes.NodeHandler.LOP_CAPABLE_NODE_TYPES
        except Exception:
            result = False
        self._usd_cache[mid] = result
        return result

    def shader_type_label(self, asset) -> str:
        """Shader-type suffix (PBR, Standard Surface...) cached per id; '' for a renderer with no table."""
        if not nodes.NodeHandler.shader_type_table(asset.renderer):
            return ""
        mid = asset.mat_id
        if mid in self._shader_type_cache:
            return self._shader_type_cache[mid]
        try:
            handler = nodes.NodeHandler(self.preferences)
            result = handler.get_shader_type_label(asset)
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

    def add_asset(self, node: hou.Node, cats: str, tags: str, fav: bool,
                  name: str | None = None) -> str:
        """Add a material to this library. `name` is the one the save dialog collected; without it the asset is named after the node, which is what a multi-selection save passes. THE RENDERER STRING IS THE CONTRACT: a renderer name means the asset is IN the library, "" means it is not, and the sibling add_assets answer the same way - so never return it unconditionally."""
        handler = nodes.NodeHandler(self.preferences)
        renderer = handler.get_renderer_from_node(node)
        new_mat = material.Material()
        tags = self.sanitize_tags(tags)
        new_mat.set_data(name or node.name(), cats, tags, fav, renderer)
        new_mat.node_color = nodes.custom_node_color(node)

        saved = handler.save_node(node, new_mat.mat_id, False)
        debug.event(
            "save", "save_node result",
            ok=bool(saved), name=new_mat.name,
            renderer=handler._renderer,
            node=node.path(), node_type=node.type().name(),
            mat_id=new_mat.mat_id,
        )
        if saved:
            new_mat.cop_net = handler.cop_info
            inventory = handler.texture_inventory
            if isinstance(inventory, (list, tuple)) and inventory:    # rides _extra like the curated tag - old builds ignore it, get_as_dict carries it
                new_mat._extra["textures"] = list(inventory)
            self._append_record(new_mat)    # per row, so in a multi-save each tile shows as its save lands
            if not self.save():  # THE INDEX WRITE CAN BE REFUSED, and the files are already on disk by now, so say so rather than reporting a save that leaves an asset absent the next time Houdini opens
                self.report_refused_index_write(new_mat)
            try:  # stamp the scene node with its library id, so a later Save to Amaze on the same node can offer update-instead-of-duplicate
                node.setUserData("assetlib_id", str(new_mat.mat_id))
            except (hou.OperationFailed, hou.ObjectWasDeleted):    # the files are already on disk: a node deleted mid-save must not turn a SAVE THAT SUCCEEDED into a reported failure ▸r/node-vanished
                pass
            return renderer
        debug.event("save", "add_asset refused - the node was not saved",
                    name=new_mat.name, node=node.path(),
                    mat_id=new_mat.mat_id)
        return ""

    def update_asset_content(self, row: int, node: hou.Node) -> str:
        """Overwrite an EXISTING entry's node content from the given scene node - same id, name, categories, tags and favourite; new files, thumbnail, renderer info and date. The Update Existing half of the save flow. Returns the detected renderer, "" on failure."""
        from amaze.core import library_policy
        if row < 0 or row >= len(self._assets):
            return ""
        mat = self._assets[row]
        if not library_policy.allow_overwrite(self.preferences.dir):  # THE GATE lives here, not only in the dialog: a UI-level check is a suggestion, and this is the layer every caller goes through
            debug.event("library", "overwrite refused - the library "
                        "does not allow it", mat_id=str(mat.mat_id),
                        name=mat.name)
            return ""
        known = self._content_state.get(str(mat.mat_id))    # content is outside the index merge: last write would win
        current = self._content_stat(mat.mat_id)
        if known is not None and current is not None and current != known:
            debug.event("library", "content update refused - the files "
                        "changed since this session read them",
                        mat_id=str(mat.mat_id), name=mat.name)
            debug.alert(
                messages.ASSET_CHANGED_ON_DISK_SINCE_LOAD % mat.name,
                key="content-changed-on-disk")
            return ""

        old_signature = None  # THE VERSIONS DECISION RULE: same nodes and wiring with only values differing becomes a new VERSION, anything else takes the structural path. SYMMETRY IS THE CORRECTNESS - both sides stage-load the base, before the save and after, so the only thing that can differ is what the save changed ▸p/structure-signature
        pre_edit = {}
        try:  # any failure to ANSWER the question degrades to structural: a wrong structural merely skips a version, where a wrong version archives a lie
            old_signature = nodes.staged_asset(
                self.preferences, mat, nodes.structure_signature)
            if versions.version_count(self.preferences, mat.mat_id) == 0:
                pre_edit = self._hold_pre_edit_files(mat.mat_id)  # held aside because if this turns out parameter-only they become Version 1, and by then the save has overwritten the base
        except Exception as exc:                          # noqa: BLE001
            debug.event("versions", "pre-save staging failed - the save "
                        "will be treated as structural",
                        mat_id=str(mat.mat_id), error=str(exc))

        handler = nodes.NodeHandler(self.preferences)
        renderer = handler.get_renderer_from_node(node)
        try:  # THE PRE-EDIT COPIES GO AWAY ON EVERY EXIT, which is why this try wraps the early returns too: they live in the system temp dir, outside the library, where no audit or cleanup sees them and macOS sweeps only at reboot
            if not handler.save_node(node, mat.mat_id, True):  # update=True overwrites the pair (+ COP companion) and always re-renders the thumbnail, whatever render_on_import says
                return ""
            self._content_state[str(mat.mat_id)] = self._content_stat(  # our own write is the new baseline for this id
                mat.mat_id)
            parameter_only = False
            if old_signature is not None:
                try:
                    new_signature = nodes.staged_asset(
                        self.preferences, mat, nodes.structure_signature)
                    parameter_only = (new_signature == old_signature)
                except Exception as exc:                  # noqa: BLE001
                    debug.event("versions", "post-save staging failed - "
                                "no version minted",
                                mat_id=str(mat.mat_id), error=str(exc))
            if parameter_only:
                if pre_edit and versions.version_count(
                        self.preferences, mat.mat_id) == 0:
                    versions.create_version(self.preferences, mat.mat_id,
                                            source_paths=pre_edit)
                versions.create_version(self.preferences, mat.mat_id)  # the base now holds the new state, so archive it as the new active version; auto-named, because a save is never interrupted to ask for one, and renameable in the dialog

                self._version_count_cache.pop(str(mat.mat_id), None)
                self._active_version_cache.pop(str(mat.mat_id), None)
        finally:
            if pre_edit:
                shutil.rmtree(os.path.dirname(
                    next(iter(pre_edit.values()))), ignore_errors=True)
        mat.cop_net = handler.cop_info
        mat._extra.pop("textures", None)    # replaced whole - the new content's references are the inventory now
        inventory = handler.texture_inventory
        if isinstance(inventory, (list, tuple)) and inventory:
            mat._extra["textures"] = list(inventory)
        if renderer:
            mat.renderer = renderer
        mat.node_color = nodes.custom_node_color(node)
        mat.set_current_date()
        self._drop_content_label_caches(mat.mat_id)  # a content update is the one flow that changes what is INSIDE the saved files, so the per-id labels read from them genuinely go stale here
        if not mat.cop_net:  # the updated network no longer references a COP net, so the old <id>_cop.mat is stale
            cop_path = self.asset_files(mat.mat_id).get("cop", "")
            if cop_path and os.path.exists(cop_path):
                try:
                    os.remove(cop_path)
                except OSError as exc:
                    debug.event(
                        "library",
                        "stale cop file remove skipped",
                        file=cop_path,
                        error=str(exc),
                    )
        self._add_thumb_paths(row)  # the engine discard inside is what makes the repaint fetch the freshly rendered PNG
        self.save()
        try:
            node.setUserData("assetlib_id", str(mat.mat_id))
        except (hou.OperationFailed, hou.ObjectWasDeleted):    # same: the update has already been written, so a vanished node costs the stamp, never the save ▸r/node-vanished
            pass
        return renderer

    def render_thumbnail(self, row: int) -> None:
        self.render_thumbnails([row])  # a batch of one, down the same path

    def render_thumbnails(self, rows) -> None:
        """Re-render every row in the model: Karma's and Octane's in ONE husk each. ▸r/husk-startup"""
        from amaze.render import thumbs
        rows = [row for row in rows if 0 <= row < self.rowCount()]
        if not rows:
            return
        thumbs.ThumbNailRenderer.render_assets(
            self.preferences, [self._assets[row] for row in rows])
        for row in rows:
            self._add_thumb_paths(row)

    def import_asset_to_scene(
        self,
        index: QtCore.QModelIndex,
        target: str = "auto",
        context_node=None,
    ):
        """Import this row into the Houdini scene. target is "auto" (context-aware), "mat" or "lop"; context_node pins the destination (a drag's release point). Returns the importer's (ok, reason, created), so the panel can report the materials that could not live in the requested context. ▸p/material-import-door"""
        importer = nodes.NodeHandler(self.preferences)
        return importer.import_asset_to_scene(
            self._assets[index.row()], target, context_node=context_node
        )

    def convert(self, index: QtCore.QModelIndex, target: str):
        """This row as a `target` material, saved beside it under its name: (ok, report)."""
        from amaze.render.material_conversion import engine as conversion_engine
        from amaze.render.material_conversion.report import ConversionReport
        mat = self._assets[index.row()]
        report = ConversionReport(mat.name)
        reason = conversion_engine.why_not(mat.renderer, target)
        if reason:    # before the rebuild: a missing plugin makes it raise
            report.skip(reason)
            return False, report

        handler = nodes.NodeHandler(self.preferences)
        with hou.undos.disabler():    # off the undo stack at BOTH ends ▸r/undo-groups
            scratch = hou.node("/obj").createNode("matnet")
        try:
            source = handler.rebuild_saved(mat, scratch)
            made = conversion_engine.convert(
                source, mat.renderer, target, scratch, mat.name, report)
            if made.shader is None:
                return False, report
            saved = self.add_asset(
                made.builder, ",".join(mat.categories), ",".join(mat.tags), False,
                name=mat.name)
            return bool(saved), report    # a refused save leaves nothing: the scratch goes below
        finally:
            with hou.undos.disabler():
                scratch.destroy()
