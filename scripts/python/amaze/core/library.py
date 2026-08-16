"""The shared asset model every library-backed section runs on, plus `MaterialLibrary` - the renderer-shaped half only Materials needs."""

import os
import json
import shutil
import time
from typing import Any
from PySide6 import QtCore

import hou

from amaze.core import debug, library_policy
from amaze.core import grid_columns
from amaze.core import locations
from amaze.core import material, database, thumbnails, tile_icons
from amaze.core import versions
from amaze.core import quarantine
from amaze.helpers import helpers
from amaze.helpers import hostos
from amaze.prefs import prefs
from amaze.render import thumbs, nodes, material_converter


def _count(count: int, noun: str) -> str:
    """"1 material" / "3 materials" - a count with a noun that agrees with it, because "material(s)" is the plural of a program, not of English."""
    return "%d %s" % (count, noun if count == 1 else noun + "s")


STAMP_SUFFIX = ".stamp.json"  # a per-asset recovery stamp, WRITE-ONLY: only repair.py may open one, and test_a_stamp_is_never_read_in_normal_operation holds that from source. ▸p/recovery-stamp


class _StampWriter:
    """Rewrites the stamps that no longer match their record - call only after a SUCCESSFUL index write, since a stamp shadows what reached disk. ▸p/recovery-stamp"""

    def __init__(self, library):
        self._library = library

    def refresh(self) -> int:
        written = 0
        for asset in list(self._library._assets):
            try:
                path = self._library.asset_files(asset.mat_id)["stamp"]
            except (hostos.PathEscape, TypeError, KeyError):
                continue
            try:
                payload = json.dumps(asset.get_as_dict(), indent=1,
                                     sort_keys=True)
            except (TypeError, ValueError) as exc:  # logged, never raised: the save has already succeeded, so failing here would turn a stamp problem into data loss
                debug.event("library", "recovery stamp could not be built",
                            mat_id=str(asset.mat_id), error=str(exc))
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    if handle.read() == payload:
                        continue
            except (OSError, ValueError):
                pass                       # absent or unreadable: rewrite
            try:
                with hostos.scratch_beside(path) as scratch:
                    with open(scratch, "w", encoding="utf-8") as handle:
                        handle.write(payload)
                written += 1
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


class AssetLibrary(grid_columns.GridColumnsMixin,
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
    }
    NOTES_SECTION = ""  # this model's notes-store key prefix - notes.note_key(NOTES_SECTION, id); every subclass names its own

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

    DB_FILENAME = ""  # which json file in the library dir backs this model; every subclass names its own, and "" breaks loudly rather than binding a nameless model to somebody's database

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        preferences: prefs.Prefs | None = None,
    ) -> None:
        super().__init__()

        # A Prefs passed POSITIONALLY lands in `parent` and leaves `preferences` None, so the model would silently bind to the LIVE library instead of the caller's. Duck-typed, not isinstance: the category tests patch prefs.Prefs with a mock
        if parent is not None and hasattr(parent, "asset_dir") \
                and hasattr(parent, "dir"):
            raise TypeError(
                "%s: pass preferences by KEYWORD (preferences=...) - a "
                "positional Prefs binds the model to the live library."
                % type(self).__name__
            )

        if preferences is None:  # share the panel's Prefs when given: per-model instances each re-read settings.json and drift from each other after any save
            preferences = prefs.Prefs()
            preferences.load()
        self.preferences = preferences
        self._thumbsize = self.preferences.thumbsize

        db = database.DatabaseConnector(self.DB_FILENAME)
        self._data = database.load_survivable(db, self.preferences.dir)

        self._assets = [self._asset_from_row(d)  # non-dict rows are SKIPPED, never allowed to abort the model: one junk row must not cost the whole library
                        for d in self._data["assets"]
                        if isinstance(d, dict)]
        self._remember_content_state()

        self._tags = self._data.setdefault("tags", [])  # setdefault, not an index: gradients.json has never carried `tags`, and a live alias into the document is the contract every list here keeps

        self._thumb_rows = {}  # engine deliveries arrive BY KEY; this maps them back to the row to repaint, and is rebuilt with the asset list
        thumbnails.signals.ready.connect(self._on_thumb_key_ready)  # through the RELAY, not the engine: the engine singleton is replaced on every module reload and would leave this model wired to a dead one
        self.rebuild_thumbs()

    @staticmethod
    def _asset_from_row(row: dict):
        """One stored row becomes one record - THE reader every load path shares (construction, a library switch, an adopted peer row), so a subclass with a rule about its rows states it once."""
        return material.Material.from_dict(row)

    def _get__mat_paths(self):
        self._mat_paths = []
        for elem in range(self.rowCount()):
            mat_id = self._assets[elem].mat_id
            is_fav = self._assets[elem].fav
            path = (
                self.preferences.dir
                + self.preferences.img_dir
                + mat_id
                + self.preferences.img_ext
            )
            if self.tile_icon(elem):  # a chosen icon is loaded like any other thumbnail - swapping the PATH, not the pipeline, so engine, LRU cache, list mode and drag previews are untouched and clearing it restores the render
                path = tile_icons.icon_image_path(self.preferences, mat_id)
            self._mat_paths.append((path, is_fav, elem))

    def switch_model_data(self):
        """Point this model at whatever library Preferences now names. No worker teardown is needed: engine deliveries are keyed by material id, so an in-flight load cannot misroute."""
        self.beginResetModel()  # NOT bookkeeping - replacing the row set without it leaves proxies on their old count and the selection on an index into rows that are gone, which segfaults on the next repaint ▸r/model-contracts
        try:
            self.preferences.load()
            db = database.DatabaseConnector(self.DB_FILENAME)
            self._data = database.load_survivable(
                db, self.preferences.dir, reload=True)
            self._thumbsize = self.preferences.thumbsize

            self._assets = [
                self._asset_from_row(d) for d in self._data["assets"]
                if isinstance(d, dict)
            ]
            self._remember_content_state()  # a reload is a fresh read of the library, content included
            self._tags = self._data.setdefault("tags", [])
            self._drop_content_label_caches()
            self.rebuild_thumbs()
        finally:  # not a trailing call: a raising load must not leave the model stuck mid-reset, which freezes every view on it
            self.endResetModel()

    def flags(
        self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex
    ) -> QtCore.Qt.ItemFlag:
        default = super().flags(index)
        return default | QtCore.Qt.ItemFlag.ItemIsDragEnabled

    def rebuild_thumbs(self):
        """Rebuild the row->path and key->row maps. No loading happens here - the engine loads on first view (data()), so opening a big library costs only the visible screen."""
        self._mat_paths = []
        self._get__mat_paths()
        self._thumb_rows = {
            self._thumb_key(row): row for row in range(self.rowCount())
        }

    def _add_thumb_paths(self, index: QtCore.QModelIndex):
        """Refresh one row's thumbnail: forget the key so the repaint re-requests the (re)written PNG, and clear a sticky "missing" so a fresh render gets its retry. Serves add_asset, render_thumbnail and update_asset_content alike."""
        self.rebuild_thumbs()
        row = index.row()
        if 0 <= row < self.rowCount():
            versions.record_render(self.preferences,  # every path that declares this row's PNG fresh comes through here, so the ACTIVE version's archive slot follows the base picture; identical bytes are skipped inside
                                   self._assets[row].mat_id)
            thumbnails.engine.discard(self._thumb_key(row))
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

    def _thumb_key(self, row: int):
        """Shared-RAM-cache key for one row's picture: stable across reloads and collision-free across the models sharing the budget. EVERY input to the picture belongs in it - the library, the icon choice, the line weight - because nothing clears the app-wide cache on a library switch."""
        home = hostos.canonical_path_key(str(self.preferences.dir or ""))
        spec = self.tile_icon(row)
        if not spec:
            return (home, self.DB_FILENAME, self._assets[row].mat_id,
                    "", "", "", 0)
        return (home, self.DB_FILENAME, self._assets[row].mat_id,
                spec["name"], spec["bg"], spec["ink"],
                tile_icons.stroke_for(self.preferences))

    @classmethod
    def _placeholder_image(cls, svg_name: str):
        """One of ui/'s SVGs rendered once as a tile-sized image. The name stays because the subclasses call it; the render and its cache live in `ui_helpers.svg_image`."""
        from amaze.helpers import ui_helpers
        return ui_helpers.svg_image(svg_name)

    def _missing_thumb_image(self, row: int = -1):
        """What a row with no thumbnail file shows. The row is passed because sections differ on what "no thumbnail" MEANS - for a material it is a failure, for a LOP node asset it is normal."""
        if 0 <= row < len(self._assets):
            spec = self.tile_icon(row)
            if spec:
                return tile_icons.compose(  # composed in memory, never written: painting must not touch the disk, and this is what makes a library copied without its _icon.png files still show them
                    spec["name"], spec["bg"],
                    int(getattr(self.preferences, "rendersize", 512) or 512),
                    tile_icons.stroke_for(self.preferences),
                    spec["ink"],
                )
        return self._placeholder_image("missing_thumbnail.svg")

    def tile_name(self, row: int) -> str:
        """The asset's display name - what the Customize dialog's Name field shows."""
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].name or "")

    def set_tile_name(self, row: int, name: str) -> bool:
        """Rename one asset - the one rename path every library section shares. A narrow write: the name field alone changes, then the ordinary save chain runs. A blank or unchanged name is a no-op."""
        name = (name or "").strip()
        if not 0 <= row < len(self._assets) or not name:
            return False
        asset = self._assets[row]
        if name == asset.name:
            return False
        asset.name = name
        self.save()
        model_index = self.index(row, 0)
        self.row_changed(model_index.row())
        return True

    def tile_icon(self, row: int) -> dict:
        """This row's chosen icon, {} when it shows its render. `icons.json` is the ONE home, keyed by asset id; same name as the file sections' version so one panel handler serves every tile in the app."""
        if 0 <= row < len(self._assets):
            return tile_icons.override_for(
                self.preferences, str(self._assets[row].mat_id))
        return {}

    def tile_key(self, row: int) -> str:
        """WHAT THIS ROW IS KEYED BY for tile icons - the asset's own id, "" for a row that does not exist. Hold this, never a row NUMBER: a reset re-numbers everything and kills every persistent index, and the non-modal Customize dialog outlives exactly that."""
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].mat_id)

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        """Give one asset a tile icon, or clear it with an empty spec: writes the composed PNG and repaints the row. save=False leaves the index write to commit_tile_icons(), so a selection costs one database write instead of one per row. False means the icon could not be written - a read-only library must not report success."""
        row = index.row() if hasattr(index, "row") else int(index)
        if not 0 <= row < len(self._assets):
            return False
        asset = self._assets[row]
        spec = tile_icons.normalise(spec)
        stored = tile_icons.set_override(  # the store is the ONE home since schema 5 stripped the record field, so a clear here is the whole delete
            self.preferences, str(asset.mat_id), spec)
        written = bool(stored)
        if spec:
            written = written and bool(
                tile_icons.render_for(self.preferences, asset.mat_id, spec)
            )
        else:
            tile_icons.clear_for(self.preferences, asset.mat_id)
        self._add_thumb_paths(self.index(row, 0))
        if save:
            self.save()
        return written

    def commit_tile_icons(self, rows=None) -> None:
        """Persist icon changes made with save=False, once."""
        self.save()

    def rerender_tile_icons(self) -> int:
        """Recompose every icon in this library - for when the LOOK changed (the line-weight preference) rather than the choice."""
        made = 0
        for row, asset in enumerate(self._assets):
            spec = self.tile_icon(row)
            if not spec:
                continue
            if tile_icons.render_for(self.preferences, asset.mat_id, spec):
                made += 1
            self._add_thumb_paths(self.index(row, 0))
        return made

    def _decoration_image(self, index: QtCore.QModelIndex):
        """The tile thumbnail for a row - the engine's FILE loader over the library's own PNG. Overridden by the Code section, which has no PNGs and paints a preview via the engine's PAINT path."""
        row = index.row()
        key = self._thumb_key(row)
        image = thumbnails.engine.request_file(key, self._mat_paths[row][0])
        if image is not None:
            return image
        if thumbnails.engine.is_missing(key):
            return self._missing_thumb_image(row)
        return None

    def set_custom_iconsize(self, size: QtCore.QSize) -> None:
        """Sets a custom IconSize - usually called via the View - Thumbnail Size Slider"""
        self._thumbsize = size.width()

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
        if not 0 <= row < len(self._assets):
            return False
        going = self._assets[row]
        try:  # SAY THE DELETE OUT LOUD: the connector unions rows, so a row merely missing from the next set() reads as "this pane has not heard of it" and is adopted straight back
            database.DatabaseConnector(self.DB_FILENAME).forget(going.mat_id)
        except (AttributeError, TypeError) as exc:
            debug.event("library", "could not mark a row for removal",
                        error=str(exc))

        self.beginRemoveRows(QtCore.QModelIndex(), row, row)  # bracketed so attached views and proxies adjust by protocol; del by INDEX, since remove-by-value drops the first EQUAL element, which needn't be this row's
        del self._assets[row]
        self.endRemoveRows()
        self.rebuild_thumbs()  # rows shifted, so remap keys to rows; the removed asset's cached image ages out of the shared LRU on its own
        return True

    def renderer_label(self, asset) -> str:
        return str(asset.renderer or "").strip()  # the tile subtitle / Type column for one asset: the KIND field as it stands (a node context, a code language). MaterialLibrary overrides with the renderer-shaped dressing; the base knows no renderer

    def _drop_content_label_caches(self, mat_id=None) -> None:
        """Evict whatever per-id labels a subclass derives from asset CONTENT - called by the shared reload and version-switch paths, which cannot know what a subclass caches. The base derives none."""

    def data(
        self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex, role: int = 0
    ) -> Any:
        if index.column() > 0:  # later columns are the TABLE's, not the row's; column 0 falls through unchanged, so grid mode cannot tell
            return self.column_data(index, role)
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self._assets[index.row()].name

        if role == self.RendererLabelRole:
            return self.renderer_label(self._assets[index.row()])

        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            return self._decoration_image(index)  # the RAW stored image, never rescaled per paint - the delegate scales and caches to the actual tile size; a cache miss queues a background load and the dark tile paints until delivery

        if role == self.CategoryRole:
            return self._assets[index.row()].categories
        if role == self.CategoryColorRole:
            return self.category_color(index.row())

        if role == self.TagRole:
            return self._assets[index.row()].tags

        if role == self.LicenceRole:
            return str(self._assets[index.row()].license or "")

        if role == self.FavoriteRole:
            return locations.is_favourite(  # THE USER'S, in the library store, keyed by asset id and tagged with the owner - never the record, whose field schema 5 stripped
                self.preferences, self._assets[index.row()].mat_id)

        if role == self.VersionsRole:
            mat_id = str(self._assets[index.row()].mat_id)
            cached = self._version_count_cache.get(mat_id)
            if cached is None:
                cached = versions.version_count(self.preferences, mat_id)
                self._version_count_cache[mat_id] = cached
            return cached

        if role == self.ActiveVersionRole:
            mat_id = str(self._assets[index.row()].mat_id)
            cached = self._active_version_cache.get(mat_id)
            if cached is None:
                cached = versions.active_version_name(
                    self.preferences, mat_id)
                self._active_version_cache[mat_id] = cached
            return cached

        if role == self.RendererRole:
            return str(self._assets[index.row()].renderer)

        if role == self.DateRole:
            return str(self._assets[index.row()].date)

        if role == self.IdRole:
            return str(self._assets[index.row()].mat_id)

        if role == self.NotesRole:
            from amaze.core import notes
            return notes.has_note(
                self.preferences,
                notes.note_key(self.NOTES_SECTION,
                               self._assets[index.row()].mat_id))

    def save(self) -> bool:
        """Write the index to disk as json. True ONLY when it reached the file - honour that answer, because add_asset writes the payload files before this runs and a caller that cannot tell a refused save from a completed one reports success for an asset the library does not list."""
        db = database.DatabaseConnector(self.DB_FILENAME)
        if not db.serves(self.preferences.dir):  # THE CONNECTOR MAY HAVE MOVED: it is shared by filename across every pane, so a library switch elsewhere repoints it and this model still holds the OLD library's rows
            debug.event("library", "save refused - the connector now "
                        "serves another library",
                        model=self.preferences.dir, connector=db._path)
            debug.alert(
                "Amaze did not save this library, because another Amaze "
                "panel has been pointed at a different one.\n\n"
                "Nothing is lost. Close the other panel, or reopen this "
                "one, and your changes will save again.",
                key="connector-moved")
            return False
        data = {}
        data["tags"] = self._tags
        data["assets"] = [asset.get_as_dict() for asset in self._assets]
        db.set(data)
        stored = db.save()
        self._adopt_rows(db.take_adopted())  # a save can ADOPT rows another session wrote while we had the library open; they reached disk but not this model, and assets[] above is rebuilt from the model, so the next save would write them out of existence
        if stored and getattr(db, "_save_outcome", "") != "identical-skip":
            _StampWriter(self).refresh()  # AFTER the index write and only when it landed; skipped on an identical-skip, where no record changed and the scan would find nothing to rewrite ▸p/recovery-stamp
        return stored

    def _adopt_rows(self, rows: list) -> None:
        """Insert rows another session added, with the row signals a view needs. A row this build cannot parse is skipped rather than allowed to abort the model - it stays on disk untouched."""
        if not isinstance(rows, list):  # a list, by contract
            return
        parsed = []
        for row in rows:
            try:
                parsed.append(self._asset_from_row(row))
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

    @property
    def assets(self) -> list:
        """This model's records, in row order - the live list, not a copy."""
        return self._assets

    @property
    def tags(self) -> list:
        """Every tag in this library - a live alias into the stored document."""
        return self._tags

    @property
    def thumbsize(self) -> int:
        """The tile size the size slider last set, in pixels."""
        return self._thumbsize

    @thumbsize.setter
    def thumbsize(self, val: int) -> None:
        self._thumbsize = val

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
            self.check_add_tags(tags)
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
            self.save()
        model_index = self.index(index.row(), 0)
        self.row_changed(model_index.row())  # full-row repaint, all roles: name, categories, tags and favourite may all have changed

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
        name = getattr(asset, "name", "") or "The asset"
        debug.event("save", "asset content written but the index write "
                    "was refused", name=name,
                    mat_id=getattr(asset, "mat_id", ""),
                    model=self.DB_FILENAME)
        if self.CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE:
            debug.alert(
                '"%s" was written to disk, but Amaze could not update '
                "the library list.\n\n"
                "Nothing is lost - the files are there. It will not "
                "appear in the grid until the list is written.\n\n"
                "Restart Houdini, then run Repair Library from the "
                "Amaze shelf to put it back in the list." % name,
                key="index-refused-after-content-write")
        else:
            debug.alert(
                '"%s" was not saved, because Amaze could not update the '
                "library list.\n\n"
                "Nothing else was changed - everything already in the "
                "library is untouched.\n\n"
                "Restart Houdini and save it again." % name,
                key="index-refused-inline-content")

    def asset_files(self, mat_id: str) -> dict:
        """{kind: absolute path} for every FILE asset `mat_id` owns - THE one place that answers which files an asset owns, so every new per-asset file is added HERE and nowhere else. Paths come back whether or not the file exists, and each caller decides what an absent one means. Directories are `asset_directories()`, never here: these values get unlinked and copyfile'd. An empty dict means the id cannot name a file, so the asset owns nothing on disk."""
        mat_id = str(mat_id)
        if not material.is_safe_asset_id(mat_id):  # the id is read verbatim out of library.json and nothing validates it on load, so `../../../Documents/x` would compose outside the library and remove_asset's unlink loop would take the user's own files
            debug.event("library", "asset id cannot name a file - it owns "
                        "no paths", mat_id=mat_id)
            return {}

        def owned(suffix):  # through material.payload_path, the ONE composition, which contains against the directory the leaf goes into; PathEscape propagates and the callers that must survive it already catch it
            return material.payload_path(self.preferences, mat_id, suffix)

        return {
            "mat": owned(self.preferences.ext),
            "interface": owned(".interface"),
            "builder": owned(nodes.BUILDER_SUFFIX),
            "stamp": owned(STAMP_SUFFIX),
            "cop": owned("_cop" + self.preferences.ext),
            "thumbnail": tile_icons.thumbnail_path(self.preferences, mat_id),  # through tile_icons, so the renderers and this function compose one path from one place
            "tile_icon": tile_icons.icon_image_path(self.preferences, mat_id),
        }

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
        """Remove one asset from this library AND from disk. THE LIST IS WRITTEN FIRST AND ITS ANSWER IS HONOURED - library.json IS the truth here, so nothing on disk is touched until the list that stops naming the asset has actually been written, and a refused write puts the row back with every file still there. save() returns False WITHOUT RAISING on several paths, so never discard its answer."""
        if not self.hasIndex(index.row(), 0):
            return
        if len(self._assets) < index.row() + 1:
            return
        row = index.row()
        asset = self._assets[row]

        owned = self.asset_files(asset.mat_id)  # asset_files(), never a list spelled out here: the hand-written one fell behind every time a new per-asset file appeared
        owned_dirs = self.asset_directories(asset.mat_id)

        if not self.removeRow(row):
            return
        if not self.save():
            self.beginInsertRows(QtCore.QModelIndex(), row, row)  # PUT IT BACK: nothing has been unlinked yet, so restoring the row returns the library to exactly the state it was in
            self._assets.insert(row, asset)
            self.endInsertRows()
            self.rebuild_thumbs()
            try:  # removeRow marked the row for deletion on the next write, so without this the delete just declined happens anyway the next time anything saves
                connector = database.DatabaseConnector(self.DB_FILENAME)
                connector.unforget(asset.mat_id)
                connector.set({"assets": [asset.get_as_dict()]})  # unforget clears a PENDING delete, but the failed save() above already ran set(), which consumed the mark and dropped the row from the live document - so the row has to go back in too
            except (AttributeError, TypeError) as exc:
                debug.event("library", "could not take back a row removal",
                            error=str(exc))
            debug.event("library", "delete refused - the library list "
                        "could not be written", name=asset.name,
                        mat_id=str(asset.mat_id))
            debug.alert(
                '"%s" was not deleted, because Amaze could not update the '
                "library list.\n\n"
                "Nothing was removed - the material and its files are "
                "exactly as they were.\n\n"
                "Close any other Amaze panel, or restart Houdini, then "
                "try again." % asset.name,
                key="delete-refused-index-write")
            return

        for path in owned.values():  # the list no longer names this asset, so its files are unclaimed; guarded per file, because a transient hold (sync client, AV scanner, the thumbnail loader's read) must not abort the sequence and cleanup_db sweeps whatever is left
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as exc:
                    debug.event(
                        "library",
                        "asset file remove skipped",
                        file=path,
                        error=str(exc),
                    )
        for path in owned_dirs.values():  # the version store: its id leaves every list the moment the save above lands, so no later run could decide the folder was safe to take
            if os.path.isdir(path):
                try:
                    shutil.rmtree(path)
                except OSError as exc:
                    debug.event(
                        "library",
                        "asset version store remove skipped",
                        folder=path,
                        error=str(exc),
                    )

    def check_add_tags(self, tag: str) -> None:
        """Add this tag to the library's list if it is not there. Saves ONLY when one was actually added - this runs once per row in the recategorise loop, where an unconditional save is a full index write per selected tile."""
        changed = False
        for t in tag.split(","):
            t = t.strip()
            if t != "" and t not in self.tags:
                self.tags.append(t)
                changed = True
        if changed:
            self.save()

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
        model_index = self.index(row, 0)
        self._add_thumb_paths(model_index)
        self.row_changed(model_index.row(), [self.VersionsRole, self.ActiveVersionRole, QtCore.Qt.ItemDataRole.DecorationRole])
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
        """(mtime_ns, size) of an asset's .mat, or None when absent."""
        try:
            st = os.stat(self.asset_files(mat_id)["mat"])
            return (st.st_mtime_ns, st.st_size)
        except (OSError, hostos.PathEscape, TypeError, KeyError):
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
            if show_dialog:
                hou.ui.displayMessage(message)  # type: ignore
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

            if not os.path.exists(interface_path) or not os.path.exists(mat_path):
                debug.event(
                    "cleanup", "asset files missing on disk",
                    mat_id=str(asset.mat_id), name=asset.name,
                    interface=os.path.exists(interface_path),
                    mat=os.path.exists(mat_path),
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
                "Update Preview when convenient, since a render takes "
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

        for f in mat_names:
            split = database.asset_id_for_file(  # the same classifier the guard above counted with
                f, (".mat", ".interface", nodes.BUILDER_SUFFIX,
                    STAMP_SUFFIX), "_cop")
            if split is not None:
                found = str(split) in known_ids
                if not found and str(split) in awaiting_repair:
                    spared.add(str(split))
                    continue
                if not found:
                    moved = quarantine_file(self.preferences.dir,
                                            os.path.join(mats_path, f))
                    if moved:
                        lone_count += 1
                        quarantined.append(f)
                        quarantined_paths.append(
                            [os.path.join(mats_path, f), moved])

        mats_path = os.path.join(self.preferences.dir, self.preferences.img_dir)
        if unreadable_abort or not os.path.isdir(mats_path):  # isdir, because a library whose img/ has not been created yet raised straight out of cleanup
            listing = []
        else:
            listing = os.listdir(mats_path)
        for f in listing:
            split = database.asset_id_for_file(f, (".png",), "_icon")  # "_icon" is a tile icon, not a leftover - the same shape the .mat pass handles for "_cop"
            if split is not None:
                found = str(split) in known_ids
                if not found and str(split) in awaiting_repair:  # THE SAME ID IS SPARED IN BOTH FOLDERS, or Repair puts the row back blank
                    spared.add(str(split))
                    continue
                if not found:
                    moved = quarantine_file(self.preferences.dir,
                                            os.path.join(mats_path, f))
                    if moved:
                        lone_count += 1
                        quarantined.append(f)
                        quarantined_paths.append(
                            [os.path.join(mats_path, f), moved])
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

        if show_dialog:  # --- one summary dialog for the whole run ---
            if summary:
                header = ("Clean Library stopped before deleting any files:"  # THE HEADER SAYS WHICH OF THE TWO HAPPENED: one header for both had a refusal opening with "cleanup finished"
                          if unreadable_abort
                          else "Library cleanup finished:")
                hou.ui.displayMessage(
                    header + "\n\n- " + "\n- ".join(summary)  # type: ignore
                )
            else:
                hou.ui.displayMessage("Library cleanup finished: nothing to clean.")  # type: ignore

        return mark_rescued

    def _what_an_empty_section_means(self, empty_sections: list) -> list:
        """ONE line for ALL the sections that list nothing, saying why Amaze will not decide on its own - the refusal above states the fact, and this states what the reader cannot know from it: that the two explanations look identical from here. One line rather than one each, or two empty sections produce two near-identical thirty-word sentences in one dialog."""
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
        assets_dir = os.path.join(
            self.preferences.dir, self.preferences.asset_dir)
        try:
            names = sorted(os.listdir(assets_dir))
        except OSError as exc:
            debug.event("cleanup", "asset folder could not be listed",
                        path=assets_dir, error=str(exc))
            return None
        found = []
        for name in names:
            asset_id = database.asset_id_for_file(
                name, (".mat", ".interface"), "_cop")
            if asset_id is not None and str(asset_id) not in known_ids:
                found.append(name)
        return found

    def _all_known_asset_ids(self) -> tuple:
        """(ids, unreadable, absent_traces, empty_sections) for EVERY database file in the library dir, read straight off disk, so one library's cleanup never deletes files belonging to another. `unreadable` is (section name, why) as two halves because the caller writes them into two different sentences; `absent_traces` maps a database that is merely NOT THERE YET to the trace that says so, and `empty_sections` the ones that parse fine and list nothing while files sit unaccounted for - separate because the way out is a different sentence for each. code.json belongs here even though snippets keep their text inline: a Code asset with a tile icon owns a PNG in the shared image folder. ▸p/clean-library-sweep"""
        ids = {str(a.mat_id) for a in self._assets}
        unreadable = []
        absent_traces = {}
        lists_nothing = []
        claimed, unreadable_files = database.ids_claimed_by(  # THE READ IS NOT THIS METHOD'S - "which ids does each database claim" has one home, and a second copy is how two readers of these shared folders come to disagree about who owns a file. What stays here is the POLICY
            self.preferences.dir)
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
            ids |= file_ids

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

    def toggle_fav(self, index: QtCore.QModelIndex) -> None:
        """Flip this row's star. Goes to the library's favourites store under its owner, never onto the shared record, so one user's stars cannot collide with another's - and with no user picked it refuses silently."""
        mat_id = self._assets[index.row()].mat_id
        locations.set_favourite(
            self.preferences, mat_id,
            not locations.is_favourite(self.preferences, mat_id))
        model_index = self.index(index.row(), 0)
        self.row_changed(model_index.row(), [self.FavoriteRole])

    def render_thumbnail(self, index) -> None:
        """Re-render one row's preview. The base has nothing to render; the sections that do override this."""

    def render_thumbnails(self, indexes) -> None:
        for index in indexes:  # one row at a time through each section's own `render_thumbnail`; MaterialLibrary overrides with the shared-scaffold Karma batch, which must NOT be routed to other sections - it would shaderball node setups and code snippets
            if index.isValid():
                self.render_thumbnail(index)


class MaterialLibrary(AssetLibrary):
    """The Material tab's model - the shared engine plus what a MATERIAL is: renderer detection on save, USD-ness and shader-type labels read from the saved files, the Karma-scaffold render batch, MAT/LOP import routing and the Redshift conversion."""

    NOTES_SECTION = "material"

    DB_FILENAME = "library.json"

    def __init__(self, parent=None, preferences=None) -> None:
        super().__init__(parent, preferences=preferences)
        self._usd_cache = {}  # both are derived by READING the saved files, so they are cached per material id rather than paid on every repaint
        self._shader_type_cache = {}

    def switch_model_data(self):
        super().switch_model_data()
        self._drop_content_label_caches()

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
        """Best-effort shader-type suffix (Standard/PBR/Toon/...), cached per material id. Only meaningful for Redshift - every other renderer answers ''."""
        if "Redshift" not in str(asset.renderer or ""):
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
        """Human label for the material's renderer: 'USD ' prefix for the USD-builder types and a ':<ShaderType>' suffix for Redshift when it can be determined, so 'USD Redshift:PBR'. "" when the renderer is unknown."""
        renderer = str(asset.renderer or "").strip()
        if not renderer:
            return ""
        label = ("USD " + renderer) if self.is_usd_material(asset) else renderer
        shader_type = self.shader_type_label(asset)
        if shader_type:
            label += ":" + shader_type
        return label

    def add_asset(self, node: hou.Node, cats: str, tags: str, fav: bool) -> str:
        """Add a material to this library. THE RENDERER STRING IS THE CONTRACT: a renderer name means the asset is IN the library, "" means it is not, and the sibling add_assets answer the same way - so never return it unconditionally."""
        handler = nodes.NodeHandler(self.preferences)
        renderer = handler.get_renderer_from_node(node)
        new_mat = material.Material()
        tags = self.sanitize_tags(tags)
        new_mat.set_data(node.name(), cats, tags, fav, renderer)
        new_mat.node_color = nodes.custom_node_color(node)

        saved = handler.save_node(node, new_mat.mat_id, False)
        debug.event(
            "save", "save_node result",
            ok=bool(saved), name=new_mat.name,
            renderer=getattr(handler, "_renderer", None),
            node=node.path(), node_type=node.type().name(),
            mat_id=new_mat.mat_id,
        )
        if saved:
            new_mat.builder = handler.builder  # still recorded, though NOTHING has read it since 2026-08-14 - material.Material.builder's setter carries why it stays
            new_mat.cop_net = handler.cop_info
            row = len(self._assets)  # per-row insert signals, not a batch-wide layout pair in the caller, so each tile appears AS ITS SAVE FINISHES during a multi-save
            self.beginInsertRows(QtCore.QModelIndex(), row, row)
            self._assets.append(new_mat)
            self.endInsertRows()
            self._add_thumb_paths(self.index(row, 0))
            if not hasattr(self, "_content_state"):
                self._content_state = {}
            self._content_state[str(new_mat.mat_id)] = self._content_stat(
                new_mat.mat_id)
            if not self.save():  # THE INDEX WRITE CAN BE REFUSED, and the files are already on disk by now, so say so rather than reporting a save that leaves an asset absent the next time Houdini opens
                self.report_refused_index_write(new_mat)
            try:  # stamp the scene node with its library id, so a later Save to Amaze on the same node can offer update-instead-of-duplicate
                node.setUserData("assetlib_id", str(new_mat.mat_id))
            except hou.OperationFailed:
                pass
            return renderer
        debug.event("save", "add_asset refused - the node was not saved",
                    name=new_mat.name, node=node.path(),
                    mat_id=new_mat.mat_id)
        return ""

    def update_asset_content(self, row: int, node: hou.Node) -> str:
        """Overwrite an EXISTING entry's node content from the given scene node - same id, name, categories, tags and favourite; new files, thumbnail, renderer info and date. The Update Existing half of the save flow. Returns the detected renderer, "" on failure."""
        if row < 0 or row >= len(self._assets):
            return ""
        mat = self._assets[row]
        if not library_policy.allow_overwrite(self.preferences.dir):  # THE GATE lives here, not only in the dialog: a UI-level check is a suggestion, and this is the layer every caller goes through
            debug.event("library", "overwrite refused - the library "
                        "does not allow it", mat_id=str(mat.mat_id),
                        name=mat.name)
            return ""
        known = getattr(self, "_content_state", {}).get(str(mat.mat_id))  # THE CONTENT STALE-WRITE GUARD: this write stays exclusive even with Versions, because content is outside the index merge entirely and two structural updates to one id silently last-write-wins. The refusal itself preserves the edit - the network is still in the scene
        current = self._content_stat(mat.mat_id)
        if known is not None and current is not None and current != known:
            debug.event("library", "content update refused - the files "
                        "changed since this session read them",
                        mat_id=str(mat.mat_id), name=mat.name)
            debug.alert(
                'Someone else has updated "%s" since this Houdini read '
                "it, so Amaze did not save over their version.\n\n"
                "Nothing is lost - your network is still in the scene. "
                "Save it as a new material, or reopen the Amaze panel "
                "to load their version first." % mat.name,
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
        if renderer:
            mat.renderer = renderer
        mat.node_color = nodes.custom_node_color(node)
        mat.set_current_date()
        self._drop_content_label_caches(mat.mat_id)  # a content update is the one flow that changes what is INSIDE the saved files, so the per-id labels read from them genuinely go stale here
        if not mat.cop_net:  # the updated network no longer references a COP net, so the old <id>_cop.mat is stale
            cop_path = os.path.join(
                self.preferences.dir,
                self.preferences.asset_dir,
                str(mat.mat_id) + "_cop.mat",
            )
            if os.path.exists(cop_path):
                try:
                    os.remove(cop_path)
                except OSError as exc:
                    debug.event(
                        "library",
                        "stale cop file remove skipped",
                        file=cop_path,
                        error=str(exc),
                    )
        self._add_thumb_paths(self.index(row, 0))  # the engine discard inside is what makes the repaint fetch the freshly rendered PNG
        self.save()
        try:
            node.setUserData("assetlib_id", str(mat.mat_id))
        except hou.OperationFailed:
            pass
        return renderer

    def render_thumbnail(self, index: QtCore.QModelIndex) -> None:
        self.render_thumbnails([index])  # a batch of one, down the same path

    def render_thumbnails(self, indexes) -> None:
        """Re-render every index, building ONE Karma scaffold for the whole batch. The scaffold is a full USD stage composition and is identical for every material, so building it per row pays the stage load per row."""
        rows = [i for i in indexes if i.isValid()]
        if not rows:
            return
        with thumbs.ThumbNailRenderer.karma_batch(self.preferences) as scaffold:
            for index in rows:
                renderer = thumbs.ThumbNailRenderer(
                    self.preferences, self._assets[index.row()])
                renderer.create_thumbnail(scaffold)
                self._add_thumb_paths(index)

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

    def convert_redshift_to_karma(self, index: QtCore.QModelIndex):
        """Best-effort conversion of a Redshift material to a Karma/MaterialX equivalent, registered as a NEW entry beside the source and never replacing it. Returns (ok, report), and READ the report even when ok - a successful conversion can still have skipped or approximated inputs. render/material_converter.py says what is handled."""
        mat = self._assets[index.row()]
        if "Redshift" not in mat.renderer:
            report = material_converter.ConversionReport(mat.name)
            report.skip("not a Redshift material")
            return False, report

        handler = nodes.NodeHandler(self.preferences)
        with hou.undos.disabler():  # off the undo stack at BOTH ends, or a create/destroy pair on the live stack resurrects the scratch with the converted network on one Ctrl+Z ▸r/undo-groups
            scratch = hou.node("/obj").createNode("matnet")
        try:
            report_holder = {}  # the converter is one ADAPTER producing the shader network; build_karma_material owns the container, wiring, layout and the surface-terminal check, and the material has to be built inside a real Karma builder because kma_* nodes are not valid outside one


            def produce(builder):
                shader, disp, report = material_converter.convert_redshift_material(
                    handler, mat, builder
                )
                report_holder["report"] = report
                return (shader, disp)

            builder, mtlx_node, wired = nodes.build_karma_material(
                scratch, mat.name, produce
            )
            report = report_holder.get("report")
            if mtlx_node is None:
                return False, report
            if not wired and report is not None:
                report.skip(  # THE ENGINE'S VERDICT REACHES THE REPORT: it is the only thing read after a convert-all sweep, and is_clean() asks about skips, so an unwired terminal has to arrive as one
                    "the surface output is not wired, so this "
                    "material renders black until it is "
                    "connected by hand")
            saved = self.add_asset(
                builder, ",".join(mat.categories), ",".join(mat.tags), False)
            return bool(saved), report  # the scratch dies in the finally, so a refused save leaves NOTHING behind and True here would tell a convert-all sweep that an unreachable material is in the library
        finally:
            with hou.undos.disabler():  # the live Karma network exists only to be copied by add_asset's save path - never left in the scene

                scratch.destroy()
