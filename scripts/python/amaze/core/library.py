"""The base asset model of every library section, plus `MaterialLibrary`."""

import json
import os
import shutil
import stat
from typing import Any
from PySide6 import QtCore, QtGui

from amaze.core import asset_files
from amaze.core import asset_record
from amaze.core import captures
from amaze.core import debug
from amaze.core import documents
from amaze.core import file_info
from amaze.core import grid_engine
from amaze.core import library_db
from amaze.core import library_files
from amaze.core import locations
from amaze.core import material, renderers, thumbnails, tile_icons
from amaze.core import material_files
from amaze.core import texstore
from amaze.core import versions
from amaze.helpers import hostos
from amaze import messages
from amaze.prefs import prefs

ROWS, CATEGORIES = "assets", "categories"    # a section database's rows, and its categories


def stored(row: dict) -> dict:
    """A database entry without who changed it and when: the row as the model reads it."""
    return {field: value for field, value in row.items() if field not in documents.STAMPS}


def as_stored(record: dict) -> dict:
    """`record` as it reads back from json, so a comparison with the database is exact."""
    return json.loads(json.dumps(record, sort_keys=True))


class ListNotSaved(str):
    """The return value of a save whose files were written but whose list entry was not saved."""

    __slots__ = ()


def filled(rows) -> tuple:
    """The (label, value) rows whose value is not empty, as a tuple: the info pane shows no empty row."""
    return tuple((label, value) for label, value in rows if value)


def file_count(count: int) -> str:
    """`1 file` or `5 files`."""
    return "1 file" if count == 1 else "%d files" % count


def existing_files(paths) -> list:
    """(path, size) of each path that is a file now, from one `os.stat` each."""
    found = []
    for path in paths:
        try:
            info = os.stat(path)
        except (OSError, ValueError):    # ValueError: a path with a NUL in it
            continue
        if stat.S_ISREG(info.st_mode):
            found.append((path, info.st_size))
    return found


def size_of(found) -> str:
    """The total of `existing_files` rows as the info pane writes it; "" when no file exists."""
    return file_info.size_text(sum(size for _path, size in found)) if found else ""


def report_unlisted(names, updated: bool = False) -> None:
    """One status line for the rows a batch left unlisted: the next successful save lists them."""
    if not names:
        return
    if updated and len(names) == 1:
        debug.refuse(messages.MATERIAL_UPDATED_LIBRARY_NOT_SAVED % names[0])
    elif updated:
        debug.refuse(messages.MATERIALS_UPDATED_LIBRARY_NOT_SAVED % len(names))
    elif len(names) == 1:
        debug.refuse(messages.ASSET_ADDED_LIBRARY_NOT_SAVED % names[0])
    else:
        debug.refuse(messages.MATERIALS_ADDED_LIBRARY_NOT_SAVED % len(names))


class AssetLibrary(grid_engine.GridEngine,
                   QtCore.QAbstractTableModel):
    """The base asset model of every library section; no renderer-specific code is here."""

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
    TILE_FIELDS = ("name", "tags", "category")
    KEEPS_VERSIONS = False    # only Materials keep versions ▸r/version-store
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
        self.preferences = preferences  # required, and shared with the panel ▸p/delete-both-duplicates
        self._removed_ids = set()    # ids this model removed, dropped from the database at its save
        self._assets = self._read_rows()
        self._colours_seen = self._colours()
        self._remember_content_state()

        self._thumb_rows = {}  # maps each loaded thumbnail's key back to the row to repaint
        thumbnails.signals.ready.connect(self._on_thumb_key_ready)  # through the relay, never the engine singleton, which a module reload replaces
        captures.signals.capture_saved.connect(self._on_capture_saved)    # from any panel or the shelf
        self.rebuild_thumbs()
        self.order_rows()    # in the grid's order before any view has the rows

    def _doc(self) -> documents.Document:
        """This model's database, from `library_db`."""
        return library_db.document(self.preferences, self.DB_FILENAME)

    def _read_rows(self) -> list:
        """One record per row in the database; an unreadable row is skipped."""
        found = []
        self._rows_library_key = library_db.key_of(self.preferences)    # the library these rows came from
        for key, row in self._doc().table(ROWS).items():
            if not isinstance(row, dict):
                continue
            try:
                found.append(self._asset_from_row(dict(stored(row), id=row.get("id", key))))
            except Exception as exc:                        # noqa: BLE001
                debug.event("database", "row not readable", file=self.DB_FILENAME,
                            asset_id=str(key), error=str(exc))
        return found

    def _colours(self) -> dict:
        """{category: colour} as the database holds them now."""
        return {name: str(entry.get("color") or "")
                for name, entry in self._doc().table(CATEGORIES).items()
                if isinstance(entry, dict) and entry.get("color")}

    @staticmethod
    def _asset_from_row(row: dict):
        """One stored row as one record; every load path uses this."""
        return material.Material.from_dict(row)

    def _tile_image_path(self, row: int, spec=None) -> str:
        """The file a row's tile loads: its one picture, render or capture; "" if unsafe."""
        return tile_icons.tile_read_path(
            self.preferences, str(self._assets[row].mat_id), self.DB_FILENAME)

    def capture_path(self, row: int) -> str:
        """Where a capture of this row is written: its one picture; "" for no row or an unsafe id."""
        if not 0 <= row < len(self._assets):
            return ""
        asset = self._assets[row]
        mat_id = str(asset.mat_id)
        if not material.is_safe_asset_id(mat_id):
            return ""
        return tile_icons.thumbnail_path(self.preferences, mat_id, self.DB_FILENAME, asset.name)

    def _on_capture_saved(self, key) -> None:
        """A capture was saved for `key`: refresh that tile's paths, drop its cached picture, repaint."""
        for row in range(self.rowCount()):
            if self.tile_key(row) == str(key):
                self._add_thumb_paths(row, base_changed=False)
                return

    def switch_model_data(self):
        """Point this model at the library Preferences names, its rows read afresh."""
        self.beginResetModel()  # required: without it proxies and selection keep stale rows ▸r/model-contracts
        try:
            self._removed_ids = set()
            self._assets = self._read_rows()
            self._colours_seen = self._colours()
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
        self._folders_stamp = self._current_folders_stamp()
        self._mat_paths = [self._tile_image_path(row, spec)
                           for row, spec in enumerate(specs)]
        self._row_keys = [self._thumb_key(row, spec)
                          for row, spec in enumerate(specs)]    # row -> its key, the reverse of `_thumb_rows`
        self.rows_reordered()

    def _current_folders_stamp(self) -> int:
        return material.folders_stamp(self.preferences, self.DB_FILENAME)

    def _picture_paths_current(self) -> None:
        """Every row's picture path again once the asset folders changed: a rename moves a folder."""
        stamp = self._current_folders_stamp()
        if stamp != getattr(self, "_folders_stamp", None):
            self._folders_stamp = stamp
            self._mat_paths = [self._tile_image_path(row) for row in range(len(self._assets))]

    def rows_reordered(self) -> None:
        self._thumb_rows = {key: row for row, key in enumerate(self._row_keys)}

    def _add_thumb_paths(self, row: int, base_changed: bool = True):
        """Refresh one row's thumbnail maps and repaint it, never a whole-model rebuild."""
        if not 0 <= row < self.rowCount():
            return
        mat_id = self._assets[row].mat_id
        spec = self.tile_icon(row)    # one store read for both the path and the key
        entry = self._tile_image_path(row, spec)
        if row < len(self._mat_paths):
            self._mat_paths[row] = entry
        elif row == len(self._mat_paths):
            self._mat_paths.append(entry)    # add_asset appends the row first, so the maps grow by one here
        else:
            self.rebuild_thumbs()    # the maps no longer match the rows - rebuild them all
        key = self._thumb_key(row, spec)
        if row < len(self._row_keys):
            stale = self._row_keys[row]
            if self._thumb_rows.get(stale) == row:
                del self._thumb_rows[stale]
            self._row_keys[row] = key
        else:
            self._row_keys.append(key)
        self._thumb_rows[key] = row
        if base_changed and self.KEEPS_VERSIONS:    # a new base picture also goes to the ACTIVE version
            versions.record_render(self.preferences, mat_id)
        thumbnails.engine.discard(key)
        self.row_changed(
            row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def _on_thumb_key_ready(self, key) -> None:
        """The engine loaded (or failed to load) a key: repaint its row if it is in this model."""
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
        entry = self._doc().get(CATEGORIES, cats[0])
        return str((entry or {}).get("color") or "") if isinstance(entry, dict) else ""

    def _thumb_key(self, row: int, spec=None):
        """Shared-RAM-cache key for one row's picture; every input to the picture belongs in it."""
        library_key = hostos.canonical_path_key(str(self.preferences.dir or ""))
        if spec is None:
            spec = self.tile_icon(row)
        if not tile_icons.is_custom(spec):
            return (library_key, self.DB_FILENAME, self._assets[row].mat_id,
                    "", "", "", 0)
        return (library_key, self.DB_FILENAME, self._assets[row].mat_id,
                spec["name"], spec["bg"], spec["ink"],
                tile_icons.stroke_for(self.preferences))

    def tile_face_art(self, row: int) -> str:
        """This row's generic face art, "" where it has none."""
        return self.TILE_FACE

    def can_preview(self, row: int) -> bool:
        """Whether this row can have a picture of its own."""
        return True

    def default_face(self, row: int) -> str:
        """Image where the row can have a picture, Generic where it cannot."""
        return "image" if self.can_preview(row) else "generic"

    def preview_image(self, row: int):
        """The row's own picture, read now for the Customize preview; None where there is none yet."""
        if not 0 <= row < len(self._assets):
            return None
        image = QtGui.QImage(self._tile_image_path(row))
        return None if image.isNull() else image

    def tile_name(self, row: int) -> str:
        """The asset's display name - what the Customize dialog's Name field shows."""
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].name or "")

    def set_tile_name(self, row: int, name: str, save: bool = True) -> bool:
        """Rename one asset, then save; a blank or unchanged name is a no-op."""
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
        """Move one asset to category `name`, then save; a blank is a no-op."""
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
        """This row's chosen icon, {} when it shows its picture; the database keys it by asset id."""
        if 0 <= row < len(self._assets):
            return tile_icons.override_for(
                self.preferences, str(self._assets[row].mat_id), self.DB_FILENAME)
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
        """Save, then repaint each record at its row AFTER the save: a save can add and remove rows."""
        stored = self.save()
        rows = {str(asset.mat_id): row for row, asset in enumerate(self._assets)}
        for asset in assets:
            self.row_changed(rows.get(str(asset.mat_id), -1), roles)
        return stored

    def tile_key(self, row: int) -> str:
        """The key for this row's tile icons: the asset id, "" for no row. Store this, never a row number."""
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].mat_id)

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        """One asset's icon ({} clears); False when not written. `save` is unused: no record changes."""
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
        held = tile_icons.set_overrides(  # icons are stored only in the database, so a clear here deletes the icon
            self.preferences,
            {str(self._assets[row].mat_id): choice
             for row, choice in chosen.items()}, self.DB_FILENAME)
        failed = len(rows) - len(valid)
        for row in valid:
            stored = held[str(self._assets[row].mat_id)]
            if not self._tile_icon_saved(row, chosen[row], stored):
                failed += 1
        return failed

    def _tile_icon_saved(self, row: int, spec, stored: bool) -> bool:
        """After the store write: refresh the tile; a custom icon is composed for display, no file."""
        self._add_thumb_paths(row, base_changed=False)
        return stored

    def commit_tile_icons(self, rows=None) -> None:
        """Nothing to commit: `set_tile_icons` wrote the icon store, and no record field changed."""

    def rerender_tile_icons(self) -> int:
        """Recompose every icon in this library, for when the look changed rather than the choice."""
        return tile_icons.repaint_custom(self)    # composed in memory: a repaint is the whole update

    def tile_picture(self, row: int, face: str = "") -> grid_engine.Picture:
        """Its custom or generic file icon; else its render or capture, then what it paints of itself."""
        spec = self.tile_icon(row)
        face = face or tile_icons.face_of(spec, self.default_face(row), self.can_preview(row))
        if face == "custom":
            return grid_engine.custom_picture(self.preferences, spec)
        if face == "generic":
            return grid_engine.Picture(art=self.tile_face_art(row))
        self._picture_paths_current()
        files = ((self._mat_paths[row], self._thumb_key(row, spec), True),)    # a capture fills the tile
        painted = self.painted_preview(row)
        if painted is not None:
            return grid_engine.Picture(files, paint=painted[1], stamp=painted[0])
        return grid_engine.Picture(files, art=self.tile_face_art(row))

    def painted_preview(self, row: int):
        """(stamp, paint) of the preview a row with no picture file paints of itself; None for none."""
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
        self._removed_ids.add(str(self._assets[row].mat_id))    # RECORD THE DELETE: a row only removed from the model stays saved
        self.beginRemoveRows(QtCore.QModelIndex(), row, row)  # del by INDEX: by value drops the first EQUAL one
        del self._assets[row]
        self.endRemoveRows()
        return True

    def renderer_label(self, asset) -> str:
        return str(asset.renderer or "").strip()  # the list's Type column: the kind field as it stands; MaterialLibrary overrides it

    def tile_subtitle(self, asset) -> str:
        return self.renderer_label(asset)    # the tile's second line; MaterialLibrary shortens it

    def _drop_content_label_caches(self, mat_id=None) -> None:
        """Evict per-id labels a subclass derives from asset content. The base derives none."""

    def row_data(self, row: int, role: int) -> Any:
        asset = self._assets[row]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return asset.name

        if role == self.RendererLabelRole:
            return self.renderer_label(asset)

        if role == self.TileSubtitleRole:
            return self.tile_subtitle(asset)

        if role == self.CategoryRole:
            return asset.categories
        if role == self.CategoryColorRole:
            return self.category_color(row)

        if role == self.TagRole:
            return asset.tags

        if role == self.LicenceRole:
            return str(asset.license or "")

        if role == self.CropRole:
            return self.shown_picture(row)[1]

        if role == self.FavoriteRole:
            return locations.is_favourite(  # the USER'S star, in the database, never the record
                self.preferences, asset.mat_id, self.DB_FILENAME)

        if role == self.VersionsRole:
            mat_id = str(asset.mat_id)
            cached = self._version_count_cache.get(mat_id) if self.KEEPS_VERSIONS else 0
            if cached is None:
                cached = versions.version_count(self.preferences, mat_id)
                self._version_count_cache[mat_id] = cached
            return cached

        if role == self.ActiveVersionRole:
            mat_id = str(asset.mat_id)
            cached = self._active_version_cache.get(mat_id) if self.KEEPS_VERSIONS else ""
            if cached is None:
                cached = versions.active_version_name(self.preferences, mat_id)
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

    def _stage_rows(self, held) -> None:
        """Put every record in the database as this user's change, drop the removed rows; not saved."""
        for asset in self._assets:
            held.put(ROWS, str(asset.mat_id), as_stored(asset.get_as_dict()))
        for key in self._removed_ids:
            held.drop(ROWS, key)
        self._removed_ids = set()

    def save(self) -> bool:
        """Stage the records in the database for the timer to save; False when it accepts no change."""
        if not library_db.accepts(self.preferences, self.DB_FILENAME):
            return False
        if getattr(self, "_rows_library_key", None) not in (None, library_db.key_of(self.preferences)):
            debug.event("library", "save skipped - the rows are from another library",
                        store=self.DB_FILENAME, dir=str(self.preferences.dir))
            return False    # the folder changed without a switch: these rows are from another library
        held = self._doc()
        with library_db.library_for(self.preferences).holding():
            self._stage_rows(held)
        library_db.changed(self.preferences, self.DB_FILENAME)
        return True

    def apply_refresh(self) -> bool:
        """Load the database's changes that this model lacks; True when the model changed."""
        rows = {key: dict(stored(row), id=row.get("id", key))
                for key, row in self._doc().table(ROWS).items() if isinstance(row, dict)}
        have = {str(asset.mat_id): asset for asset in self._assets}
        added = [row for key, row in rows.items()
                   if key not in have and key not in self._removed_ids]
        gone = [{"id": key} for key in have if key not in rows]
        fields = []
        for key, asset in have.items():
            if key not in rows:
                continue
            mine = as_stored(asset.get_as_dict())
            fields.extend((key, field, value) for field, value in as_stored(rows[key]).items()
                          if mine.get(field) != value)
        self._insert_added_rows(added)
        self._apply_field_changes(fields)
        self._drop_rows(gone)
        colours = self._colours()
        recoloured = colours != self._colours_seen
        self._colours_seen = colours
        if recoloured:
            self.repaint_category_colours()
        return bool(added or fields or gone or recoloured)

    def repaint_category_colours(self) -> None:
        """Repaint every tile's category band, for that role only: a colour never resizes a column."""
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0),
                [self.CategoryColorRole])

    def _apply_field_changes(self, fields: list) -> None:
        """Apply other sessions' `(id, field, value)` changes to the records in place; notify views."""
        if not isinstance(fields, list) or not fields:  # a list, by contract, like `_insert_added_rows`
            return
        wanted: dict = {}
        for asset_id, field, value in fields:
            wanted.setdefault(str(asset_id), {})[field] = value
        for row, asset in enumerate(self._assets):
            changes = wanted.get(str(asset.mat_id))
            if not changes:
                continue
            try:
                fresh = self._asset_from_row(
                    dict(asset.get_as_dict(), **changes))
            except Exception as exc:                        # noqa: BLE001
                debug.event("database", "changed field not readable",
                            file=self.DB_FILENAME, error=str(exc),
                            asset_id=str(asset.mat_id))
                continue
            asset.__dict__.update(fresh.__dict__)
            self.row_changed(row)    # the whole row: a loaded field can affect any column

    def _append_record(self, record) -> int:
        """Add a new record, sorted into place at once; returns its row AFTER the sort."""
        row = len(self._assets)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        try:
            self._assets.append(record)
        finally:
            self.endInsertRows()
        self._add_thumb_paths(row)
        moved = self.resort()    # now, so no caller keeps a row number that is about to change
        self._content_state[str(record.mat_id)] = self._content_stat(
            record.mat_id)
        return moved.get(row, row) if moved else row

    def _remove_unsaved_record(self, record) -> None:
        """Remove a new record whose save failed from the model and the database, by identity."""
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
        with library_db.library_for(self.preferences).holding():
            self._doc().drop(ROWS, str(record.mat_id))

    def add_saved(self, record, staged: list) -> bool:
        """Save a new record and the files its save staged as ONE change; False: neither was saved."""
        if not library_db.accepts(self.preferences, self.DB_FILENAME):
            asset_record.discard(staged)
            return False
        self._append_record(record)
        held = self._doc()
        row = as_stored(record.get_as_dict())
        guard = library_db.guard_of(self.preferences)
        with library_db.library_for(self.preferences).holding():
            self._stage_rows(held)
        saved = library_db.save(self.preferences, self.DB_FILENAME, also=lambda change: (
            asset_record.add_staged(change, guard, staged, metadata=row)))
        if not saved:
            asset_record.discard(staged)
            self._remove_unsaved_record(record)
            return False
        return True

    def _insert_added_rows(self, rows: list) -> None:
        """Insert rows another session added, with the row signals; an unparseable row is skipped."""
        if not isinstance(rows, list):  # a list, by contract
            return
        parsed = []
        for row in rows:
            try:
                parsed.append(self._asset_from_row(row))
            except Exception as exc:                        # noqa: BLE001
                debug.event("database", "added row not readable",
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
        self.resort()    # now: the save that added them may still hold its own rows

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

        if fav is not None:  # the star goes to this user's stars in the database, never onto the record
            if bool(fav) != locations.is_favourite(
                    self.preferences, asset.mat_id, self.DB_FILENAME):
                locations.set_favourite(
                    self.preferences, asset.mat_id, bool(fav), self.DB_FILENAME)
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

    def report_failed_index_write(self, asset, updated: bool = False) -> None:
        """Show on the status line that an inline asset's list write failed; it is kept in memory."""
        name = asset.name or "The asset"
        debug.event("save", "inline asset not saved - the index write "
                    "was refused", name=name, mat_id=asset.mat_id,
                    model=self.DB_FILENAME)
        report_unlisted([name], updated=updated)    # the library's own alert said why; a restart loses it

    def asset_files(self, mat_id: str) -> dict:
        """`asset_files_for` this library; a new per-asset file is added THERE and nowhere else."""
        return asset_files.asset_files_for(self.preferences, mat_id, self.DB_FILENAME)

    def info_header(self, row: int) -> tuple:
        """(name, type) heading a row in the info pane: what the comments pane shows for it."""
        return (str(self.row_data(row, QtCore.Qt.ItemDataRole.DisplayRole) or ""),
                str(self.row_data(row, self.RendererLabelRole) or ""))

    def info_rows(self, row: int) -> tuple:
        """(before, after, request) the info pane shows for one row; a row with no value is left out."""
        asset = self._assets[row]
        facts, request = self._info_facts(row, asset)
        before = [("Name", str(self.row_data(row, QtCore.Qt.ItemDataRole.DisplayRole) or "")),
                  ("Date", str(asset.date or "").split(" ")[0])] + facts    # stored with its time
        after = (("Version", self._info_version(row)),
                 ("License", str(asset.license or "").strip()),
                 ("ID", str(asset.mat_id)))
        return filled(before), filled(after), request

    def _info_facts(self, row: int, asset) -> tuple:
        """([rows after Date], the read that adds rows or None); each section names its own."""
        return [], None

    def _info_version(self, row: int) -> str:
        """The Version column's text without its leading word; "" when it only repeats the name."""
        role = self._column_role("version")
        text = str(self.row_data(row, role) or "").strip() if role else ""
        if text.startswith("Version "):    # `versions` names an unnamed version "Version 2"
            text = text[len("Version "):]
        name = str(self.row_data(row, QtCore.Qt.ItemDataRole.DisplayRole) or "")
        return "" if text == name else text    # a Code version is named after its snippet

    def texture_paths(self, asset) -> list:
        """The texture files the record lists, as absolute paths; nothing is opened."""
        tokens = asset._extra.get("textures")
        own = self.asset_directories(asset.mat_id).get("folder", "")
        return [texstore.resolve(str(token), self.preferences, own)
                for token in (tokens if isinstance(tokens, list) else ()) if token]

    def folder_files(self, asset) -> list:
        """Every file in the asset's folder: versions, textures and comment pictures included."""
        folder = self.asset_directories(asset.mat_id).get("folder", "")
        return [os.path.join(here, name)
                for here, _folders, names in os.walk(folder) for name in names] if folder else []

    def info_paths(self, row: int) -> list:
        """Every file one row owns, for the read that adds up their sizes."""
        return self.folder_files(self._assets[row])

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
        """{kind: absolute path} of every directory of asset `mat_id`: its own folder."""
        mat_id = str(mat_id)
        if not material.is_safe_asset_id(mat_id):
            return {}
        try:
            return {"folder": material.asset_dir(self.preferences, self.DB_FILENAME, mat_id)}
        except hostos.PathOutsideBase as exc:  # no valid directory path; must not raise out of remove_asset
            debug.event("library", "version store path refused",
                        mat_id=mat_id, error=str(exc))
            return {}

    def remove_asset(self, index: QtCore.QModelIndex) -> None:
        """Remove one asset from the list, then from disk - `remove_rows` over one row."""
        if self.hasIndex(index.row(), 0):
            self.remove_rows([index.row()])

    def remove_rows(self, rows) -> int:
        """Delete these rows and move their files to the library's trash as ONE change; how many."""
        going = [(row, self._assets[row])
                 for row in sorted({int(r) for r in rows})
                 if 0 <= row < len(self._assets)]
        if not going:
            return 0
        if not library_db.accepts(self.preferences, self.DB_FILENAME):
            self._report_refused_delete(going[-1][1])
            return 0
        guard = library_db.guard_of(self.preferences)
        owned = [guard.inside(path) for _row, asset in going
                 for path in self._owned_paths(asset.mat_id) if os.path.lexists(path)]
        for row, _asset in reversed(going):    # highest first, so every row number stays valid
            self._unlist_row(row)
        self.rebuild_thumbs()
        with library_db.library_for(self.preferences).holding():
            self._stage_rows(self._doc())
            taken = self._unlist_what_belongs(going)    # its comments' pictures are in its folder

        def trash(change):
            for relative in owned:
                if relative:
                    change.trash(relative)
        if not library_db.save(self.preferences, self.DB_FILENAME, also=trash):
            self._restore_unsaved_removals(going, taken)    # nothing on disk changed: the change is all or nothing
            self._report_refused_delete(going[-1][1])
            return 0
        return len(going)

    def _owned_paths(self, mat_id) -> list:
        """What a delete trashes: the asset's whole folder."""
        return list(self.asset_directories(mat_id).values())

    def _report_refused_delete(self, asset) -> None:
        """Tell the user a delete did not happen because the list could not be written."""
        debug.event("library", "delete refused - the library list "
                    "could not be written", name=asset.name,
                    mat_id=str(asset.mat_id))
        debug.alert(
            messages.ASSET_NOT_DELETED_LIST_NOT_UPDATED % asset.name,
            key="delete-refused-index-write")

    def _unlist_what_belongs(self, going) -> dict:
        """Drop each deleted asset's comments, icon and every user's favorite; {id: what they were}."""
        held, taken = self._doc(), {}
        for _row, asset in going:
            key = str(asset.mat_id)
            taken[key] = (held.get("comments", key), held.get("icons", key),
                          held.take_everyones("favorites", key))
            held.drop("comments", key)
            held.drop("icons", key)
        return taken

    def _restore_unsaved_removals(self, going, taken=None) -> None:
        """Put back `(row, record)` pairs whose delete failed to save, in the model and the database."""
        held = self._doc()
        with library_db.library_for(self.preferences).holding():
            for key, (page, icon, stars) in (taken or {}).items():
                if page is not None:
                    held.put("comments", key, page)
                if icon is not None:
                    held.put("icons", key, icon)
                held.put_everyones("favorites", key, stars)
        for row, asset in going:    # ascending, so each returns to its old row
            row = min(max(row, 0), len(self._assets))
            self.beginInsertRows(QtCore.QModelIndex(), row, row)
            try:
                self._assets.insert(row, asset)
            finally:
                self.endInsertRows()
        self.rebuild_thumbs()
        self.resort()
        with library_db.library_for(self.preferences).holding():
            self._stage_rows(self._doc())    # else the next save performs the failed delete

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

    def version_list(self, row: int) -> tuple:
        """([{n, name, author, date}] oldest first, the active number) for the asset at `row`."""
        if not (self.KEEPS_VERSIONS and 0 <= row < len(self._assets)):
            return [], 0
        mat_id = str(self._assets[row].mat_id)
        return (versions.list_versions(self.preferences, mat_id),
                versions.active_version(self.preferences, mat_id))

    def switch_version(self, row: int, number: int) -> bool:
        """Make version `number` active for the asset at `row`, and refresh its caches and tile."""
        if not (self.KEEPS_VERSIONS and 0 <= row < len(self._assets)):
            return False
        mat = self._assets[row]
        if not versions.switch_active(self.preferences, mat.mat_id, number):
            return False
        self._content_state[str(mat.mat_id)] = self._content_stat(
            mat.mat_id)
        self._drop_content_label_caches(mat.mat_id)
        self._add_thumb_paths(row, base_changed=False)    # the archive's own picture, no fresh render
        self._versions_changed(mat)
        return True

    def rename_version(self, row: int, number: int, name: str) -> bool:
        """Rename one version, clear the cache and repaint the view."""
        if not (self.KEEPS_VERSIONS and 0 <= row < len(self._assets)):
            return False
        mat = self._assets[row]
        if not versions.rename_version(self.preferences, mat.mat_id, number, name):
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
        """(mtime_ns, size) of an asset's .mat, or None when absent; builds that one path only."""
        if not material.is_safe_asset_id(str(mat_id)):
            return None
        try:
            return hostos.disk_state(material.payload_path(
                self.preferences, mat_id, self.preferences.ext, self.DB_FILENAME))
        except (hostos.PathOutsideBase, TypeError, KeyError):    # Code and Colors own no `.mat`
            return None

    def _remember_content_state(self) -> None:
        """Record each .mat's state for the stale-write check; clear the two per-id version caches."""
        self._content_state = {
            str(asset.mat_id): self._content_stat(asset.mat_id)
            for asset in self._assets
        }
        self._version_count_cache = {}  # per id, so a paint pass never opens the ledger; invalidated per write
        self._active_version_cache = {}
        have = versions.stored_ids(self.preferences) if self.KEEPS_VERSIONS else set()    # seeds both
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
                locations.is_favourite(self.preferences, mat_id, self.DB_FILENAME)
            wanted[mat_id] = not current
            flipped.append(row)
        if not wanted:
            return
        locations.set_favourites(self.preferences, wanted, self.DB_FILENAME)
        for row in flipped:
            self.row_changed(row, [self.FavoriteRole])


class MaterialLibrary(AssetLibrary):
    """The Material tab's model: records, their renderer labels, and the repaint after a render."""

    NOTES_SECTION = "material"
    TILE_FACE = "face_material"    # T06
    KEEPS_VERSIONS = True

    DB_FILENAME = library_files.MATERIALS

    def __init__(self, preferences) -> None:
        super().__init__(preferences)
        self._usd_cache = {}  # both derived by reading the saved files, so cached per material id
        self._shader_type_cache = {}

    def _on_thumbnail_written(self, asset_id: str) -> None:
        """A background render's PNG was written: repaint that one tile, wherever its row is now."""
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
        """True if the material is a USD-builder type, from its saved builder type, cached per id."""
        mid = asset.mat_id
        if mid in self._usd_cache:
            return self._usd_cache[mid]
        try:
            node_type = material_files.get_saved_node_type(self.preferences, asset, self.DB_FILENAME)
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

    def tile_subtitle(self, asset) -> str:
        """The renderer's name alone, `Redshift`: the tile's second line shares its line with the icon."""
        return renderers.label(str(asset.renderer or "").strip())

    RendererIconRole = QtCore.Qt.ItemDataRole.UserRole + 16    # the renderer's art on that line, "" for none

    def row_data(self, row: int, role: int):
        if role == self.RendererIconRole:
            return renderers.tile_icon(self._assets[row].renderer)
        return super().row_data(row, role)

    def _info_facts(self, row: int, asset) -> tuple:
        """Size, Renderer and Textures, and the read that finds the largest texture."""
        textures = existing_files(self.texture_paths(asset))
        facts = [("Size", size_of(existing_files(self.folder_files(asset)))),
                 ("Renderer", self.tile_subtitle(asset)),
                 ("Textures", file_count(len(textures)) if textures else "")]
        return facts, file_info.request_for_textures([path for path, _size in textures])

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
