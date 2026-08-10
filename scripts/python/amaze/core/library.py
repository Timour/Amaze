"""
This Module holds the Model for the MaterialView/Thumbview for the MatlibPanel
"""

import os
import json
import shutil
import time
import importlib
from typing import Any
from PySide6 import QtCore, QtGui

import hou

from amaze.core import debug, library_policy
from amaze.core import grid_columns
from amaze.core import material, database, thumbnails, tile_icons
from amaze.core import versions
from amaze.core import quarantine
from amaze.helpers import helpers
from amaze.helpers import hostos
from amaze.prefs import prefs
from amaze.render import thumbs, nodes, material_converter

# (module reloads consolidated into panel.py's single chain)


def _count(count: int, noun: str) -> str:
    """"1 material" / "3 materials" - the count with a noun that agrees
    with it.

    "material(s)" is the plural of a program, not of English, and it
    lands in the sentences a worried user reads most carefully. Every
    noun this is used with pluralises with an s."""
    return "%d %s" % (count, noun if count == 1 else noun + "s")


#: A per-asset RECOVERY STAMP: the asset's full record, written beside
#: its files, so a library whose index is destroyed can be rebuilt.
#:
#: Write-only by design. Nothing in normal operation reads one - not the
#: model, not the grid, not import. Only a rebuild does, and only after
#: `library.json` is already gone. practice.md is explicit about why
#: this is not a demotion: the index IS the truth, and may become a
#: cache "once a per-asset truth exists to rebuild it from, and not one
#: moment before". This creates that truth; it does not spend it.
#:
#: Measured before building (research.md): `mat/<id>.mat`, `.interface`
#: and `img/<id>.png` carry no tags, no description, no favourite, no
#: date and no labelled name or category - so nothing could rebuild the
#: index, and "can this library survive losing library.json" was NO.
#: The stamp is the sixteen fields that answer it.
#:
#: WRITTEN HERE, READ ONLY BY `repair`. A stamp is a write-only shadow of
#: a row, and a second reader makes it a second source of truth -
#: `test_a_stamp_is_never_read_in_normal_operation` holds that line from
#: source. Clean Library asks whether an asset is recoverable, which is a
#: question for the recovery module, so pass 3 calls
#: `repair.stamped_assets` rather than opening a stamp itself.
STAMP_SUFFIX = ".stamp.json"


class _StampWriter:
    """Refreshes the stamps that no longer match their asset's record.

    Called after a SUCCESSFUL index write, never before: the stamps
    shadow what reached disk, and a stamp for a row the index refused
    would be a second, disagreeing account of the same library.

    Only what changed is rewritten. Reading the existing stamps costs
    ~13ms for 548 (research.md, measured), and an ordinary save - a
    favourite toggled, one asset added - then writes one file or none.
    """

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
            except (TypeError, ValueError) as exc:
                # A record that will not serialise is a finding, not a
                # reason to fail the save. The index write has already
                # succeeded by the time this runs, and taking the save
                # down here would turn a stamp problem into data loss -
                # the exact inversion a safety net must never make.
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
            except OSError as exc:
                # A stamp is a safety net, never the thing being saved.
                # Failing to write one must not cost a save that has
                # already succeeded, so this is recorded and passed over.
                debug.event("library", "recovery stamp not written",
                            mat_id=str(asset.mat_id), error=str(exc))
        return written


# The quarantine moved to core/quarantine.py, which imports no hou -
# helpers/restore.py needs these from the pure-stdlib terminal tool,
# and reaching them through THIS module meant the import raised there
# every time and the undo-copy bound retired nothing. Re-exported so
# every existing caller (repair.py, this file, the tests) is unchanged.
QUARANTINE_PREFIX = quarantine.QUARANTINE_PREFIX
QUARANTINE_DAYS = quarantine.QUARANTINE_DAYS
quarantine_folder = quarantine.quarantine_folder
prune_quarantine = quarantine.prune_quarantine
quarantine_size = quarantine.quarantine_size
quarantine_file = quarantine.quarantine_file


class MaterialLibrary(grid_columns.GridColumnsMixin,
                     QtCore.QAbstractTableModel):

    
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
#: The notes-store key prefix for this model's assets
    #: (notes.note_key(NOTES_SECTION, id)). Subclasses override.
    NOTES_SECTION = "material"
    """The Model for the ThumbList View in the MatLibPanel
    Subclasses QtCore.QAbstractListModel
    """

    #: which json file in the library dir backs this model - the COP
    #: section subclasses this model over its own cops.json (see
    #: core/cop_library.py), everything else shares library.json.
    DB_FILENAME = "library.json"

    def __init__(
        self,
        parent: QtCore.QObject | None = None,
        preferences: prefs.Prefs | None = None,
    ) -> None:
        super().__init__()

        # A Prefs passed POSITIONALLY lands in `parent` and leaves
        # `preferences` None - so the model silently loads the LIVE
        # library instead of the caller's. That is how a test run wrote
        # a stray material into the real library; refuse it loudly
        # rather than quietly binding to the user's data.
        # Duck-typed on purpose: the category tests patch prefs.Prefs
        # with a mock, and isinstance() against a non-class raises. A
        # QObject parent has neither of these attributes; a Prefs has
        # both.
        if parent is not None and hasattr(parent, "asset_dir") \
                and hasattr(parent, "dir"):
            raise TypeError(
                "%s: pass preferences by KEYWORD (preferences=...) - a "
                "positional Prefs binds the model to the live library."
                % type(self).__name__
            )

        # Share the panel's Prefs when given - the old per-model
        # instances each re-read settings.json at startup and drifted
        # from each other after any save (Elmar-era wart).
        if preferences is None:
            preferences = prefs.Prefs()
            preferences.load()
        self.preferences = preferences
        self._thumbsize = self.preferences.thumbsize

        db = database.DatabaseConnector(self.DB_FILENAME)
        self._data = db.load(self.preferences.dir)

        self._assets = [material.Material.from_dict(d) for d in self._data["assets"]]
        self._remember_content_state()
        self._adopt_record_favorites()
        self._adopt_record_icons()

        self._tags = self._data["tags"]

        # Engine deliveries arrive BY KEY - this maps them back to the
        # row to repaint. Rebuilt with the asset list.
        self._thumb_rows = {}
                # Through the RELAY, not the engine: the engine singleton is
        # replaced on every module reload, which would leave this
        # model wired to a dead one (see thumbnails._EngineSignals).
        thumbnails.signals.ready.connect(self._on_thumb_key_ready)

        self.IdRole = QtCore.Qt.ItemDataRole.UserRole  # 256
        self.CategoryRole = QtCore.Qt.ItemDataRole.UserRole + 1  # 257
        self.FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 2  # 258
        self.RendererRole = QtCore.Qt.ItemDataRole.UserRole + 3  # 259
        self.TagRole = QtCore.Qt.ItemDataRole.UserRole + 4  # 260
        self.DateRole = QtCore.Qt.ItemDataRole.UserRole + 5  # 261
        self.RendererLabelRole = QtCore.Qt.ItemDataRole.UserRole + 6  # 262
        self.LicenceRole = QtCore.Qt.ItemDataRole.UserRole + 7  # 263
        #: The colour of this asset's category, "" when it has none.
        #: Read from the SAME data dict the Categories model writes -
        #: one DatabaseConnector per file, shared - so the grid repaints
        #: from the sidebar's edit with nothing wired between them.
        self.CategoryColorRole = QtCore.Qt.ItemDataRole.UserRole + 8  # 264
        #: How many versions this asset has. The delegate draws the
        #: chevrons badge at > 1; the dialog opens from a click on it.
        self.VersionsRole = QtCore.Qt.ItemDataRole.UserRole + 9  # 265
        #: Whether this asset carries a note (text or open to-dos) -
        #: the Notes badge's question, answered live from the notes
        #: store (a dict lookup, cheap per repaint).
        self.NotesRole = QtCore.Qt.ItemDataRole.UserRole + 10  # 266
        #: The ACTIVE version's name ("" when there are no versions).
        #: List mode has room to say which version you are looking at,
        #: where the grid's badge could only say that versions exist.
        self.ActiveVersionRole = QtCore.Qt.ItemDataRole.UserRole + 11  # 267
        # is_usd is derived from each material's .interface file; cache the
        # result per material id so it is read once, not on every repaint.
        self._usd_cache = {}
        # Shader type (Standard/PBR/Toon/...) is derived from each
        # material's .mat file - same reasoning, cache per material id.
        self._shader_type_cache = {}

        self.rebuild_thumbs()

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
            # A chosen tile icon is loaded like any other thumbnail -
            # swapping the PATH rather than the pipeline means the
            # engine, the LRU cache, list mode and drag previews all
            # keep working untouched, and clearing the icon restores
            # the render that was never overwritten.
            if self.tile_icon(elem):
                path = tile_icons.icon_image_path(self.preferences, mat_id)
            self._mat_paths.append((path, is_fav, elem))

    def switch_model_data(self):
        # No worker teardown needed: engine deliveries are keyed by
        # material id, so a reload can't misroute in-flight loads -
        # same material keeps its cached image straight through.
        #
        # begin/endResetModel is NOT bookkeeping. This replaces the whole
        # row set behind Qt's back, and without the reset every attached
        # proxy keeps its old row count and the selection model keeps a
        # current index into rows that no longer exist. Measured on a
        # 7-asset -> 1-asset switch: the proxy still reported 7 rows and
        # current row 6 against a 1-row source. The next repaint asks
        # data() for row 6 - an out-of-range read on the native side,
        # the classic Qt segfault shape, reachable from Preferences by
        # simply pointing the library at a smaller one. (log #288)
        self.beginResetModel()
        try:
            self.preferences.load()
            db = database.DatabaseConnector(self.DB_FILENAME)
            self._data = db.reload_with_path(self.preferences.dir)
            self._thumbsize = self.preferences.thumbsize

            self._assets = [
                material.Material.from_dict(d) for d in self._data["assets"]
            ]
            # A reload is a fresh read of the library, content included.
            self._remember_content_state()
            self._adopt_record_favorites()
            # BOTH adoptions, like __init__. Only the favourites one ran
            # here, so pointing Preferences at a library an older build
            # wrote left every record-level icon unmigrated for the
            # session - living on `tile_icon`'s fallback alone, which is
            # the state in which clearing one does not stick.
            self._adopt_record_icons()
            self._tags = self._data["tags"]
            self._usd_cache = {}
            self._shader_type_cache = {}
            self.rebuild_thumbs()
        finally:
            # finally, not a trailing call: a raising load must not leave
            # the model stuck mid-reset, which freezes every view on it.
            self.endResetModel()

    def flags(
        self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex
    ) -> QtCore.Qt.ItemFlag:
        default = super().flags(index)
        return default | QtCore.Qt.ItemFlag.ItemIsDragEnabled

    def rebuild_thumbs(self):
        """Rebuild the row->path and key->row maps. No loading happens
        here: the engine loads on first view (data()), so opening a
        big library costs only the visible screen."""
        self._mat_paths = []
        self._get__mat_paths()
        self._thumb_rows = {
            self._thumb_key(row): row for row in range(self.rowCount())
        }

    def _add_thumb_paths(self, index: QtCore.QModelIndex):
        """Refresh one row's thumbnail: forget the key so the repaint
        re-requests the (re)written PNG. Serves add_asset (new row),
        render_thumbnail and update_asset_content uniformly - and
        clears a sticky "missing" so a fresh render gets its retry."""
        self.rebuild_thumbs()
        row = index.row()
        if 0 <= row < self.rowCount():
            # Every path that declares this row's PNG fresh runs
            # through here, so the ACTIVE version's archive slot
            # follows the base picture. Identical bytes are skipped
            # inside, which makes the call after a switch a free no-op.
            versions.record_render(self.preferences,
                                   self._assets[row].mat_id)
            thumbnails.engine.discard(self._thumb_key(row))
            self.row_changed(
                row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def _on_thumb_key_ready(self, key) -> None:
        """The engine delivered (or failed) a key - repaint its row if
        it belongs to this model. Key-based, so reloads and reorders
        can never misroute an image; a key from another library simply
        isn't in this model's map."""
        row = self._thumb_rows.get(key)
        if row is None or not 0 <= row < self.rowCount():
            return
        self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def category_color(self, row: int) -> str:
        """The colour set on this asset's category, "" for none. One
        category per asset, so there is no rule to invent about which
        of several wins - which is exactly why multi-category went."""
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
        """Shared-RAM-cache key: stable across reloads (same
        material keeps its cached image through a library refresh) and
        collision-free across the models sharing the budget."""
        # THE LIBRARY IS PART OF THE KEY. It carried the database
        # filename and the asset id, and nothing clears the app-wide RAM
        # cache on a library SWITCH - `switch_model_data` only rebuilds
        # the row map. So two libraries holding the same id served one
        # image: point Preferences at a copy of a library whose picture
        # has since been re-rendered and the tile paints the first
        # one's, with the second's file never read. The docstring's
        # promise is true of a reload and was false of a switch, and
        # Test Mode seeds a second library from the real one.
        home = hostos.canonical_path_key(str(self.preferences.dir or ""))
        spec = self.tile_icon(row)
        if not spec:
            return (home, self.DB_FILENAME, self._assets[row].mat_id,
                    "", "", "", 0)
        # EVERY input to the picture belongs in the key, not just the
        # choice: the line weight and the render size change what the
        # image looks like too. Leaving them out made correctness
        # depend on remembering to discard the cache by hand.
        return (home, self.DB_FILENAME, self._assets[row].mat_id,
                spec["name"], spec["bg"], spec["ink"],
                tile_icons.stroke_for(self.preferences))

    # The placeholder cache moved with the render, into
    # `ui_helpers.svg_image` - one QImage per design, reused by every
    # row in every library that wants it, and now by the scene section
    # too instead of its own second dict.

    @classmethod
    def _placeholder_image(cls, svg_name: str):
        """One of ui/'s SVGs rendered once as a tile-sized image.

        The rendering and the cache moved to `ui_helpers.svg_image`,
        which `scene_captures` had written a second copy of. The path
        went with them, and that is the part that mattered: this built
        `$AMAZE + "/scripts/python/amaze/ui/"` by hand rather than
        through `ui_asset`, so with $AMAZE unset it looked for the file
        at an absolute path formed from nothing and drew no
        placeholder. The name stays because the subclasses call it.
        """
        from amaze.helpers import ui_helpers
        return ui_helpers.svg_image(svg_name)

    def _missing_thumb_image(self, row: int = -1):
        """What a row with no thumbnail file shows. The row is passed
        because sections differ on what "no thumbnail" MEANS - for a
        material it is a failure, for a LOP node asset it is normal."""
        if 0 <= row < len(self._assets):
            spec = self.tile_icon(row)
            if spec:
                # Self-healing: the choice is stored on the asset, so a
                # library copied without its _icon.png files still shows
                # them. Composed in memory rather than written here -
                # painting must not touch the disk.
                return tile_icons.compose(
                    spec["name"], spec["bg"],
                    int(getattr(self.preferences, "rendersize", 512) or 512),
                    tile_icons.stroke_for(self.preferences),
                    spec["ink"],
                )
        return self._placeholder_image("missing_thumbnail.svg")

    def tile_name(self, row: int) -> str:
        """The asset's display name - what the Customize dialog's Name
        field shows."""
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].name or "")

    def set_tile_name(self, row: int, name: str) -> bool:
        """Rename one asset from the Customize dialog - the one rename
        path every library section shares (Material, Node and Code all
        inherit it). A narrow write: the name field alone changes, then
        the ordinary save chain runs, so nothing else is touched. A
        blank or unchanged name is a no-op."""
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
        """This row's chosen icon, {} when it shows its render. Same
        name as the file sections' version so one panel handler serves
        every tile in the app.

        The shared store answers first (one icons.json for every
        section, keyed by asset id); the record field is the fallback
        for icons an older build wrote - or ones whose icon name this
        build does not ship, which the migration deliberately held."""
        if 0 <= row < len(self._assets):
            stored = tile_icons.override_for(
                self.preferences, str(self._assets[row].mat_id))
            return stored or tile_icons.normalise(self._assets[row].icon)
        return {}

    def tile_key(self, row: int) -> str:
        """WHAT THIS ROW IS KEYED BY for tile icons - the asset's own
        id. "" for a row that does not exist.

        The stable identity behind a row NUMBER, which nothing outside
        a single event should hold: a reset re-numbers everything and
        kills every persistent index, even when no row moved. The
        Customize dialog is non-modal and outlives exactly that.
        """
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].mat_id)

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        """Give one asset a tile icon (or clear it with an empty spec).
        Writes the composed PNG and repaints the row.

        save=False leaves the index write to commit_tile_icons(), so a
        selection costs one database write instead of one per row.
        Returns False if the icon could not be written - a read-only
        library must not report success."""
        row = index.row() if hasattr(index, "row") else int(index)
        if not 0 <= row < len(self._assets):
            return False
        asset = self._assets[row]
        spec = tile_icons.normalise(spec)
        # THE STORE IS THE ONE HOME. The record field used to be
        # written too, so a build that predates the store still read
        # the pick - retired 2026-08-09 with LIBRARY_FORMAT 2, which
        # answers that case generally: such a build opens the library
        # read-only and is told to update, instead of quietly showing
        # a second copy of one value that is free to drift. Reading
        # the field still happens (see tile_icon's fallback and
        # _adopt_record_icons) - a library written by any older build
        # still carries picks there.
        stored = tile_icons.set_override(
            self.preferences, str(asset.mat_id), spec)
        written = bool(stored)
        if spec:
            written = written and bool(
                tile_icons.render_for(self.preferences, asset.mat_id, spec)
            )
        else:
            tile_icons.clear_for(self.preferences, asset.mat_id)
            # AND THE FALLBACK, or the clear cannot stick. Removing the
            # store key is the whole delete, and `tile_icon` then falls
            # straight back to the record - which nothing else clears,
            # `get_as_dict` re-serialises on every save, and
            # `_adopt_record_icons` copies back into the store at the
            # next panel open. So on any library an older build wrote,
            # the icon was unclearable.
            #
            # Clearing is the one direction that may still write this
            # field. Setting stopped on 2026-08-09 because a second
            # copy of a value is free to drift; an empty one carries no
            # value to drift, and saying the user's choice in both
            # homes is what makes it the same choice in both.
            asset.icon = {}
        self._add_thumb_paths(self.index(row, 0))
        if save:
            self.save()
        return written

    def commit_tile_icons(self, rows=None) -> None:
        """Persist icon changes made with save=False, once."""
        self.save()

    def rerender_tile_icons(self) -> int:
        """Recompose every icon in this library - for when the LOOK
        changed (the line-weight preference) rather than the choice."""
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
        """The tile thumbnail for a row - the engine's FILE loader over
        the library's own PNG. Overridden by the Code section, which has
        no PNGs and paints a code preview via the engine's PAINT path."""
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
        # Qt model contract: bracket the mutation so attached views and
        # proxies adjust by protocol (callers used to compensate with
        # external invalidates). del by INDEX - remove-by-value drops
        # the first EQUAL element, which needn't be this row's.
        # SAY THE DELETE OUT LOUD. The connector unions rows now - it
        # can only keep one - so a row simply missing from the next
        # set() reads as "this pane has not heard of it" and is adopted
        # straight back. Without this, deleting an asset would appear to
        # work until the next save put it back.
        going = self._assets[row]
        try:
            database.DatabaseConnector(self.DB_FILENAME).forget(going.mat_id)
        except (AttributeError, TypeError) as exc:
            debug.event("library", "could not mark a row for removal",
                        error=str(exc))

        self.beginRemoveRows(QtCore.QModelIndex(), row, row)
        del self._assets[row]
        self.endRemoveRows()
        # Rows shifted - remap keys to rows (the removed asset's cached
        # image just ages out of the shared LRU naturally).
        self.rebuild_thumbs()
        return True

    def is_usd_material(self, asset) -> bool:
        """True if the material is a USD-builder type (rs_usd_material_builder
        or octane_solaris_material_builder), detected from its .interface file
        and cached per material id."""
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
        """Best-effort specific shader-type suffix (Standard/PBR/Toon/...),
        cached per material id. Only meaningful for Redshift right now -
        every other renderer returns ''."""
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
        """Human label for the material's renderer, prefixed 'USD ' for the
        USD-builder types (e.g. 'USD Redshift', 'Octane', 'Karma'), plus a
        ':<ShaderType>' suffix for Redshift when the underlying shader
        type can be determined (e.g. 'Redshift:Standard',
        'USD Redshift:PBR') - so "just Redshift" tiles are told apart
        by actual shading model, not only by the USD/classic builder
        split the plain 'USD ' prefix already covers.
        Empty string if the renderer is unknown."""
        renderer = str(asset.renderer or "").strip()
        if not renderer:
            return ""
        label = ("USD " + renderer) if self.is_usd_material(asset) else renderer
        shader_type = self.shader_type_label(asset)
        if shader_type:
            label += ":" + shader_type
        return label

    def data(
        self, index: QtCore.QModelIndex | QtCore.QPersistentModelIndex, role: int = 0
    ) -> Any:
        # LATER COLUMNS are the table's, not the row's (step 1 of the
        # QTableView migration). Column 0 falls through unchanged, so
        # grid mode cannot tell any of this happened.
        if index.column() > 0:
            return self.column_data(index, role)
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self._assets[index.row()].name

        if role == self.RendererLabelRole:
            return self.renderer_label(self._assets[index.row()])

        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            # Raw stored image, no per-paint rescale - the delegate
            # scales (and caches) to the actual tile size, same as the
            # Textures/Geometry models have always behaved. The old
            # smooth-scale here ran for every visible tile on every
            # repaint, which is why material grids scrolled noticeably
            # heavier than the other sections.
            # One engine for every section (core/thumbnails.py):
            # cached image back instantly, else a background load is
            # queued and the dark tile paints until delivery. Evicted
            # keys (RAM budget) transparently reload from the library's
            # own PNG - disk is the swap, and it's already written.
            # Subclasses that don't store PNGs (the Code section paints
            # a preview) override _decoration_image; the default is the
            # engine's file loader over the library's own thumbnail PNG.
            return self._decoration_image(index)

        if role == self.CategoryRole:
            return self._assets[index.row()].categories
        if role == self.CategoryColorRole:
            return self.category_color(index.row())

        if role == self.TagRole:
            return self._assets[index.row()].tags

        if role == self.LicenceRole:
            return str(self._assets[index.row()].license or "")

        if role == self.FavoriteRole:
            # PER-USER, from prefs - the shared field on the record is
            # frozen history, kept only so older builds keep working.
            try:
                return self.preferences.is_material_favorite(
                    self._assets[index.row()].mat_id)
            except AttributeError:
                return self._assets[index.row()].fav

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
        """Save data to disk as json. True only when it reached the file.

        Propagated from the connector rather than swallowed: add_asset
        writes the material's .mat/.interface BEFORE this runs, so a
        caller that cannot tell a completed save from a refused one
        reports success for an asset the library does not list.
        """
        db = database.DatabaseConnector(self.DB_FILENAME)
        # THE CONNECTOR MAY HAVE MOVED. It is shared by filename across
        # every pane in the process, so a library switch in another pane
        # repoints it - and this model still holds the OLD library's
        # rows. Writing them now puts library A's assets into library
        # B's file, silently, with the stale-write guard blind to it
        # because the connector's own write refreshed its own baseline.
        if not db.serves(self.preferences.dir):
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
        # A save can ADOPT rows another session wrote while we had the
        # library open. Those rows reached disk but not this model, and
        # assets[] above is rebuilt from the model - so the next save
        # wrote them out of existence. Take them now.
        self._adopt_rows(db.take_adopted())
        if stored and getattr(db, "_save_outcome", "") != "identical-skip":
            # AFTER the index write, and only when it landed - and not
            # on an identical-skip: bytes that did not change describe
            # records that did not change, so the 548-file stamp scan
            # would find nothing to rewrite (it cost ~13ms per no-op
            # save, per the class docstring's measurement).
            _StampWriter(self).refresh()
        return stored

    def _adopt_rows(self, rows: list) -> None:
        """Insert rows another session added, with the row signals a
        view needs. A row this build cannot parse is skipped rather than
        allowed to abort the model - it stays on disk untouched."""
        # A list, by contract. Anything else (a mock, a future
        # connector that forgets) is not worth guessing about.
        if not isinstance(rows, list):
            return
        parsed = []
        for row in rows:
            try:
                parsed.append(material.Material.from_dict(row))
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
        """
        Docstring for assets

        :param self: Description
        :return: Description
        :rtype: list[Any]
        """
        return self._assets

    @property
    def tags(self) -> list:
        """
        Docstring for tags

        :param self: Description
        :return: Description
        :rtype: list[Any]
        """
        return self._tags

    @property
    def thumbsize(self) -> int:
        """
        Docstring for thumbsize

        :param self: Description
        :return: Description
        :rtype: int
        """
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

        # dict.fromkeys dedupes while preserving insertion order; a plain
        # set() here made tag order reshuffle unpredictably on every edit.
        ts = dict.fromkeys(ts)
        new_tags = ",".join(ts)
        return new_tags

    def set_assetdata(self, index: QtCore.QModelIndex, name, cats, tags, fav,
                      about=None, license=None, save=True) -> None:
        """Set Assetdata for the given index and parameters
        the library is saved immidiately after. about/license default to
        None = leave unchanged (only the Material Info dialog edits them).
        save=False defers the index write to the CALLER: the multi-select
        loops save once after the last row instead of once per row -
        each save serialises and hashes the whole 548-row document."""

        asset = self._assets[index.row()]

        name = name if material.MULTIPLE_VALUES not in name else asset.name
        cats = (cats if material.MULTIPLE_VALUES not in cats
                else ", ".join(asset.categories))

        if material.MULTIPLE_VALUES not in tags:
            tags = self.sanitize_tags(tags)
            self.check_add_tags(tags)
        else:
            tags = ", ".join(asset.tags)

        # THE STAR IS PER-USER, like toggle_fav: it goes to settings,
        # never onto the shared record (whose `favorite` is frozen
        # history). None leaves the star alone - the recategorise path
        # passes that, because it edits the record, not the star.
        if fav is not None:
            try:
                if bool(fav) != bool(
                        self.preferences.is_material_favorite(
                            asset.mat_id)):
                    self.preferences.set_material_favorite(
                        asset.mat_id, bool(fav))
            except AttributeError:
                pass
        asset.set_data(name, cats, tags, asset.fav, None, about=about,
                       license=license)
        if save:
            self.save()
        # Full-row repaint (all roles) - name/categories/tags/favorite
        # may all have changed.
        model_index = self.index(index.row(), 0)
        self.row_changed(model_index.row())

    def collapse_multicategory(self) -> int:
        """Multi-category was removed (a hazard that made sorting harder):
        every asset keeps only its FIRST category. Idempotent - once every
        asset has <=1 category a re-run is a no-op - so it's safe to call
        on every load; it saves only if it actually changed something.
        Returns the number of assets collapsed."""
        changed = 0
        for asset in self._assets:
            if len(asset.categories) > 1:
                asset.categories = asset.categories[0]  # setter takes a str
                changed += 1
        if changed:
            self.save()
        return changed

    #: Every file an asset owns, by kind. ONE answer to the question
    #: "which files does asset X own?", because the call sites that
    #: asked it separately kept disagreeing:
    #:
    #:   * remove_asset listed five and missed the builder sidecar the
    #:     moment one was added - deleting a material left it behind
    #:     forever, and Clean Library's classifier is an allow-list, so
    #:     nothing swept it either;
    #:   * cleanup_db's first pass listed three, missing the `_cop`
    #:     companion and the tile icon remove_asset does delete;
    #:   * update_asset_content knew about one.
    #:
    #: Every new per-asset file (the builder sidecar, and the recovery
    #: stamp next) has to be added HERE and nowhere else. The gap
    #: compounds the day an asset owns N version files instead of one
    #: set - which is the shape Versions brings.
    #: What a refused index write leaves behind for THIS model. The
    #: asset sections write payload files before the list, so their
    #: content survives and Repair can put the row back; Code stores a
    #: snippet inline, so there is nothing on disk and nothing to
    #: recover. Subclasses override.
    CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE = True

    def report_refused_index_write(self, asset) -> None:
        """Say that the content was written and the list was not.

        HOISTED so a subclass cannot forget it. This tail existed only
        on MaterialLibrary; CopLibrary.add_asset and
        CodeLibrary.add_asset ran the identical sequence - write the
        payload, insert the row, call save() - and discarded save()'s
        answer, so a refused write reported a saved asset that is not
        in the library and whose files are then unaccounted for by any
        list. cops.json reaches that refusal easily: load()'s
        absent-but-known guard latches it whenever the file is mid-sync
        at panel construction.

        The files are deliberately LEFT where they are. Content without
        a row is the safe direction of this failure - a row without
        content is the phantom that looks fine until the day it is
        needed - and Repair Library recovers exactly this shape, so the
        recovery already exists and the honest thing is to name it.
        """
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
        """{kind: absolute path} for every FILE asset `mat_id` owns.

        Paths are returned whether or not the file exists: the callers
        want "what would this asset own", and each decides for itself
        what an absent one means.

        Directories an asset owns are `asset_directories()`, not here -
        these values are unlinked and copyfile'd by callers, and a
        directory among them would break both.

        AN ID THAT CANNOT NAME A FILE OWNS NOTHING. The id is read
        verbatim out of library.json (material.py:163 takes it as-is,
        nothing validates it on load), so with `../../../Documents/x`
        the ordinary composition resolves outside the library and
        remove_asset's os.remove loop then unlinks the user's own
        files - measured, 7 of 7 paths outside the library and the file
        there destroyed. Refused at BOTH doors material.py names: the
        id predicate here, and contained_join where the path is
        actually built. An empty dict means "owns nothing on disk",
        which is the right answer for an id that cannot name a file -
        remove_asset then drops the row and touches nothing.
        """
        mat_id = str(mat_id)
        if not material.is_safe_asset_id(mat_id):
            debug.event("library", "asset id cannot name a file - it owns "
                        "no paths", mat_id=mat_id)
            return {}
        # Contained against the directory the leaf goes INTO, because
        # the id is the untrusted part; how dir and asset_dir compose
        # is ours. PathEscape propagates - the callers that must
        # survive it already catch it (refresh, _content_stat).
        #
        # Through material.payload_path, which IS that composition -
        # the renderers wrote it out by hand at twenty sites and this
        # one joined, and the note below about thumbnails was true of
        # the payloads too.
        def owned(suffix):
            return material.payload_path(self.preferences, mat_id, suffix)

        return {
            "mat": owned(self.preferences.ext),
            "interface": owned(".interface"),
            "builder": owned(nodes.BUILDER_SUFFIX),
            "stamp": owned(STAMP_SUFFIX),
            "cop": owned("_cop" + self.preferences.ext),
            # Through tile_icons.thumbnail_path, so the renderers and
            # this function compose the same path from one place - they
            # had nine hand-concatenations and this join, which agree
            # only while preferences.dir carries its separator.
            "thumbnail": tile_icons.thumbnail_path(self.preferences, mat_id),
            "tile_icon": tile_icons.icon_image_path(self.preferences, mat_id),
        }

    def _hold_pre_edit_files(self, mat_id: str) -> dict:
        """Copy the asset's CURRENT files aside for the version store:
        {archive suffix: held path}, per `versions.SOURCE_KINDS`.

        Keyed by KIND, never by filename suffix: `<id>_cop.mat` shares
        ".mat" with the material and `<id>_icon.png` shares ".png" with
        the render, so a suffix-keyed dict let whichever came later
        overwrite the real payload - Version 1 then archived the COP
        companion as the material, and switching back promoted it over
        `mat/<id>.mat`. Kinds SOURCE_KINDS does not name (cop, stamp,
        tile icon) are not versioned.
        """
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
        """{kind: absolute path} for every DIRECTORY asset `mat_id` owns.

        The version store, today. Separate from asset_files() because
        every caller of that one either unlinks or copyfiles what it
        gets, and neither works on a directory - but remove_asset must
        still take these, or deleting an asset leaves its whole version
        store behind under an id no list mentions any more, so no later
        run can ever decide it is safe to remove. That is what shipped:
        Clean Library, Repair and library-audit all classify through
        asset_id_for_file, which returns None for the directory entry
        `versions`, so nothing saw it.

        Same containment rule as asset_files(); versions_dir already
        composes through contained_join itself.
        """
        mat_id = str(mat_id)
        if not material.is_safe_asset_id(mat_id):
            return {}
        try:
            return {"versions": versions.versions_dir(self.preferences,
                                                      mat_id)}
        except hostos.PathEscape as exc:
            # "This asset owns no directory we can name", the same
            # answer asset_files() gives for an id it cannot compose,
            # and the same response refresh() and _content_stat()
            # already make to a PathEscape from that function. It must
            # not raise out of remove_asset: failing to sweep a version
            # store is a leak, while a delete that raises out of the
            # model after the list was written is a broken library.
            debug.event("library", "version store path refused",
                        mat_id=mat_id, error=str(exc))
            return {}

    def remove_asset(self, index: QtCore.QModelIndex) -> None:
        """Removes a material from this Library and Disk
        the library is saved immediately after.

        THE LIST IS WRITTEN FIRST AND ITS ANSWER IS HONOURED. This used
        to unlink all seven payload files and THEN save() with the
        result discarded - and save() returns False without raising on
        five paths (a connector pointed elsewhere, an empty document, a
        write block latched at load, a merge that will not parse, a
        held file). Reproduced: with the write refused, the .mat,
        .interface and thumbnail were destroyed, library.json still
        listed the asset, and there was no quarantine copy of any of
        them - so the next launch showed a tile with nothing behind it
        and the material was unrecoverable.

        The order is the other way round now because library.json IS
        the truth here, not an index over it (practice.md ▸ Standing
        design assumptions): nothing on disk is touched until the list
        that stops naming it has actually been written. On a refusal
        the row goes back and the files are all still there, which is
        the direction of failure this can afford.
        """
        if not self.hasIndex(index.row(), 0):
            return
        if len(self._assets) < index.row() + 1:
            return
        row = index.row()
        asset = self._assets[row]

        # asset_files(), not a list written out here. The list written
        # out here is what fell behind: a tile icon had to be added to
        # it once, and the builder sidecar was missed entirely when that
        # file appeared.
        owned = self.asset_files(asset.mat_id)
        owned_dirs = self.asset_directories(asset.mat_id)

        if not self.removeRow(row):
            return
        if not self.save():
            # PUT IT BACK. The material's files are all still on disk -
            # nothing has been unlinked yet - so restoring the row
            # returns the library to exactly the state it was in, and
            # the user can try again once whatever refused the write
            # has let go.
            self.beginInsertRows(QtCore.QModelIndex(), row, row)
            self._assets.insert(row, asset)
            self.endInsertRows()
            self.rebuild_thumbs()
            # removeRow marked the row for deletion on the next write;
            # without this, the delete we just declined would happen
            # anyway the next time anything saves.
            try:
                connector = database.DatabaseConnector(self.DB_FILENAME)
                connector.unforget(asset.mat_id)
                # unforget clears a PENDING delete, but save() already
                # ran set(), which consumed the mark and dropped the
                # row from the connector's live document - so ANY other
                # model's save (Categories writes only its own keys and
                # never re-adds assets) would commit the delete we just
                # declined. Put the row back in the document too.
                connector.set({"assets": [asset.get_as_dict()]})
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

        # The list no longer names this asset, so its files are now
        # unclaimed and safe to remove.
        #
        # Deletes are guarded per file: a transient hold on any of them
        # (sync client, AV scanner, the thumbnail loader's read) must
        # not abort the sequence - the library entry is already gone and
        # saved, and cleanup_db sweeps any file left behind once the
        # hold is released.
        for path in owned.values():
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
        # The version store, which nothing removed before this: its id
        # is gone from every list the moment the save above lands, so
        # no later run could ever decide the folder was safe to take.
        for path in owned_dirs.values():
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
        """Checks if this tag exists and adds it if needed. Saves only
        when one was actually added - this runs once per row in the
        recategorise loop, and the unconditional save cost a full index
        write per selected tile (check_add_category already guards)."""
        changed = False
        for t in tag.split(","):
            t = t.strip()
            if t != "" and t not in self.tags:
                self.tags.append(t)
                changed = True
        if changed:
            self.save()

    # `get_current_network_node` lived here and was called by nothing
    # but its own two tests. `NodeHandler.get_current_network_node`
    # (render/nodes.py) is the one every import goes through, and it is
    # the LATER answer to the same question: it reads the editor's
    # pwd() rather than currentNode(), which is what stopped it
    # crashing when no node was current in the picked pane, and it
    # honours an explicit context override. This copy still asked the
    # crashing way.

    def remove_category(self, cat: str) -> None:
        """Removes the given category from the library (and also in all assets)"""
        # check assets against category and remove there also:
        for asset in self._assets:
            asset.remove_category(cat)

    def rename_category(self, old: str, new: str) -> None:
        """Renames the given category in the library (and also in all assets)"""
        # Update all Categories with that name in all assets
        for asset in self._assets:
            asset.rename_category(old, new)

    def add_asset(self, node: hou.Node, cats: str, tags: str, fav: bool) -> str:
        """Add a Material to this Library.

        Returns the renderer string on success, "" when the save was
        refused - the same contract the cop and code add_assets keep.
        """
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
            # Whether the saved node WAS a builder. Never recorded, so
            # every newly saved Mantra asset had builder == 0 and
            # load_interface_mantra took its else branch - the saved
            # .interface (promoted and spare parameters) was never
            # executed at all, and the import dumped loose VOPs into
            # /mat instead of rebuilding a material.
            new_mat.builder = handler.builder
            new_mat.cop_net = handler.cop_info
            # Proper per-row insert signals (not a batch-wide layout
            # change pair in the caller): each saved material's tile
            # appears AS ITS SAVE FINISHES during a multi-save.
            row = len(self._assets)
            self.beginInsertRows(QtCore.QModelIndex(), row, row)
            self._assets.append(new_mat)
            self.endInsertRows()
            self._add_thumb_paths(self.index(row, 0))
            if not hasattr(self, "_content_state"):
                self._content_state = {}
            self._content_state[str(new_mat.mat_id)] = self._content_stat(
                new_mat.mat_id)
            # THE INDEX WRITE CAN BE REFUSED, and the material's files
            # are already on disk by this point - save_node ran above.
            # Reporting success then leaves the user with an asset they
            # watched appear in the grid, absent from the library the
            # next time Houdini opens.
            #
            # The files are deliberately LEFT where they are. Content
            # without a row is the safe direction of this failure (a row
            # without content is the phantom that looks fine until the
            # day it is needed), and Repair Library recovers exactly
            # this shape - so the recovery already exists and the honest
            # thing is to name it.
            if not self.save():
                self.report_refused_index_write(new_mat)
            # Stamp the scene node with its library id so a later
            # "Save to Amaze" on the same node can offer
            # update-instead-of-duplicate (standard file-save semantics).
            try:
                node.setUserData("assetlib_id", str(new_mat.mat_id))
            except hou.OperationFailed:
                pass
            return renderer
        # THE RENDERER-STRING CONTRACT: a renderer name means the asset
        # is IN the library, "" means it is not. Both sibling
        # add_assets (cop_library, code_library) have always answered
        # this way, and code_library's docstring even names it as the
        # contract - this one returned the renderer whether or not
        # save_node worked, so all six call sites read a refused save
        # as a good one and the only trace was a debug record.
        debug.event("save", "add_asset refused - the node was not saved",
                    name=new_mat.name, node=node.path(),
                    mat_id=new_mat.mat_id)
        return ""

    def find_asset_row_by_id(self, mat_id: str) -> int:
        """Row of the asset with the given id, or -1."""
        for row, asset in enumerate(self._assets):
            if str(asset.mat_id) == str(mat_id):
                return row
        return -1

    def find_asset_row_by_name(self, name: str) -> int:
        """Row of the asset whose (possibly sanitized) name matches, but
        only if the match is UNIQUE - with duplicates there is no safe
        answer, so -1 and the caller treats the save as a new material."""
        matches = []
        for row, asset in enumerate(self._assets):
            if asset.name == name or helpers.sanitize_usd_path(asset.name) == name:
                matches.append(row)
        return matches[0] if len(matches) == 1 else -1

    def switch_version(self, row: int, number: int) -> bool:
        """Make version `number` the active one for the asset at `row`.

        Everything downstream of the base files has to be told: the
        content baseline (or the next Update Existing would read our own
        switch as another session's write and refuse), the per-id label
        caches, the thumbnail, and the tile.
        """
        if not 0 <= row < len(self._assets):
            return False
        mat = self._assets[row]
        if not versions.switch_active(self.preferences, mat.mat_id, number):
            return False
        self._content_state[str(mat.mat_id)] = self._content_stat(
            mat.mat_id)
        self._usd_cache.pop(mat.mat_id, None)
        self._shader_type_cache.pop(mat.mat_id, None)
        self._version_count_cache.pop(str(mat.mat_id), None)
        self._active_version_cache.pop(str(mat.mat_id), None)
        model_index = self.index(row, 0)
        self._add_thumb_paths(model_index)
        self.row_changed(model_index.row(), [self.VersionsRole, self.ActiveVersionRole, QtCore.Qt.ItemDataRole.DecorationRole])
        return True

    def rename_version(self, row: int, number: int, name: str) -> bool:
        """Rename one version, and TELL the view.

        This used to return the versions module's answer and stop
        there, which was invisible while the name lived only inside the
        dialog that set it. List mode now paints the active version's
        name in its own column, so a rename that does not evict the
        cache and emit leaves the row showing the old name until
        something unrelated repaints it."""
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

    def _adopt_record_favorites(self) -> None:
        """One-time move of the record-level favourites into THIS user's
        prefs. The material library was the one section whose favourite
        lived on the SHARED record - in a multi-user library my star
        toggled yours; the three folder sections were per-user all
        along. The shared field stays on the rows exactly as loaded
        (older builds keep reading it); it simply stops being what this
        build reads or writes."""
        try:
            self.preferences.adopt_material_favorites(
                [str(asset.mat_id) for asset in self._assets
                 if asset.fav])
        except AttributeError:
            # A fixture prefs without the accessor - nothing to adopt.
            pass

    def _adopt_record_icons(self) -> None:
        """One-time move of record-level tile icons into the shared
        store (icons.json, keyed by the asset id beside the File
        section's path keys) - ROADMAP, one icons.json for every
        section. The record field stays EXACTLY as loaded: this build
        no longer writes it (retired with LIBRARY_FORMAT 2), and
        reading it is how a library from an older build keeps its
        picks. Not deleted either - removing the only copy such a
        build can read would make the move one-way for no gain. A spec
        whose icon name this build does not ship is HELD on the record
        rather than normalised away, for the same reason."""
        moved = held = 0
        for asset in self._assets:
            raw = asset.icon
            if not raw:
                continue
            spec = tile_icons.normalise(raw)
            if not spec:
                held += 1
                continue
            key = str(asset.mat_id)
            if tile_icons.override_for(self.preferences, key):
                continue
            if tile_icons.set_override(self.preferences, key, spec):
                moved += 1
        if moved or held:
            debug.event("icons", "record icons adopted into the store",
                        db=self.DB_FILENAME, moved=moved, held=held)

    _SCRATCH_TAILS = (".writing", ".capturing", ".tmp", ".part", ".new")
    _SCRATCH_MIN_AGE = 60 * 60

    def _sweep_dead_scratches(self, folder: str, quarantined: list) -> int:
        """Move scratch files older than an hour into the quarantine.

        A scratch is ALWAYS ours and always means a save died partway -
        but a fresh one may be a live write from another session, so
        age gates the sweep, by mtime deliberately: a scratch carries
        no date in its name, and its mtime IS its write time - the
        sort-by-name retention rule is about files whose name says
        which day they are OF, which a scratch's does not.
        """
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
        """Baseline for the content stale-write guard: what every
        asset's .mat looked like when THIS session read the library.

        A stat each, not a hash - 556 stats cost milliseconds at open,
        and unlike the index (which this session rewrites no-op-
        identically), nothing rewrites a .mat byte-identically, so the
        false-conflict case the fingerprint guard exists for does not
        arise here. An atomic content write always moves mtime_ns.
        """
        self._content_state = {
            str(asset.mat_id): self._content_stat(asset.mat_id)
            for asset in self._assets
        }
        # Version counts, per id, so the delegate's paint pass never
        # touches disk: a repaint runs per visible tile per frame, and
        # the ledger read is a file open. Cleared here because this
        # runs on every fresh read of the library, and invalidated
        # point-wise on the writes that change a count.
        self._version_count_cache = {}
        # Count and NAME come from the same ledger - one goes stale
        # exactly when the other does, so they are cleared together
        # everywhere. A name that outlived its switch would sit in the
        # row claiming the wrong version is loaded.
        self._active_version_cache = {}
        # ONE listdir seeds both caches for every asset with NO
        # versions folder - the overwhelming case. First paint used to
        # stat mat/versions/<id>/versions.json once per visible tile;
        # negligible on a local SSD, real on a synced or network
        # library. Assets WITH a folder stay lazy: their first ask
        # still reads the ledger, which is the honest source.
        try:
            have = set(os.listdir(os.path.join(
                self.preferences.dir, self.preferences.asset_dir,
                "versions")))
        except OSError:
            have = set()
        for asset in self._assets:
            if str(asset.mat_id) not in have:
                self._version_count_cache[str(asset.mat_id)] = 0
                self._active_version_cache[str(asset.mat_id)] = ""

    def update_asset_content(self, row: int, node: hou.Node) -> str:
        """Overwrite an EXISTING library entry's node content from the
        given scene node - same id, name, categories, tags and favorite;
        new node files, thumbnail, renderer/type info and date. This is
        the 'Update Existing' half of the file-save-style flow (the
        other half being a normal add_asset). Returns the detected
        renderer on success, '' on failure."""
        if row < 0 or row >= len(self._assets):
            return ""
        mat = self._assets[row]
        # THE GATE, here rather than only in the dialog. The panel also
        # stops offering Overwrite, but a UI-level check is a
        # suggestion: this is the layer every caller goes through, and
        # today's capture work is the standing example of what happens
        # when a policy lives beside one of its callers.
        if not library_policy.allow_overwrite(self.preferences.dir):
            debug.event("library", "overwrite refused - the library "
                        "does not allow it", mat_id=str(mat.mat_id),
                        name=mat.name)
            return ""
        # THE CONTENT STALE-WRITE GUARD. This is the one write that
        # stays genuinely exclusive even after Versions ships: two
        # sessions both doing a structural Update Existing to the same
        # id silently last-write-wins the .mat/.interface pair, and
        # content is outside the index merge entirely. If the file
        # moved since this session read it, refuse - loudly, naming the
        # way out. The user's edit is PRESERVED by the refusal itself:
        # their network is still in the scene, and Save As New keeps it
        # without touching the other session's work.
        known = getattr(self, "_content_state", {}).get(str(mat.mat_id))
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

        # THE VERSIONS DECISION RULE. Same nodes, same wiring, only
        # values differ -> this save becomes a new version; anything
        # else -> the structural path below, exactly as before. Decided
        # by instantiating the saved base in staging and comparing
        # structure signatures - a textual diff cannot answer it
        # (research.md: the .interface carries no child values).
        #
        # Any failure to ANSWER the question degrades to the structural
        # path: a wrong "structural" merely skips a version; a wrong
        # "version" would archive a lie.
        # SYMMETRY IS THE CORRECTNESS. The first cut compared the live
        # node's signature against a staged load of the base and read
        # EVERY save as structural: the importer wires and wraps what
        # the raw stage-load does not, so the two sides never matched.
        # Both sides now pass through the same transform - stage-load
        # the base BEFORE the save and stage-load it AFTER - so the
        # only thing that can differ is what the save changed.
        old_signature = None
        pre_edit = {}
        try:
            old_signature = nodes.staged_asset(
                self.preferences, mat, nodes.structure_signature)
            if versions.version_count(self.preferences, mat.mat_id) == 0:
                # The pre-edit files, held aside: if this turns out
                # parameter-only they become Version 1 - the state the
                # user is versioning away from must not be lost, and by
                # then the save has overwritten the base.
                pre_edit = self._hold_pre_edit_files(mat.mat_id)
        except Exception as exc:                          # noqa: BLE001
            debug.event("versions", "pre-save staging failed - the save "
                        "will be treated as structural",
                        mat_id=str(mat.mat_id), error=str(exc))

        handler = nodes.NodeHandler(self.preferences)
        renderer = handler.get_renderer_from_node(node)
        # THE PRE-EDIT COPIES GO AWAY ON EVERY EXIT. The rmtree used to
        # sit on the success path only, so the early return below - a
        # node Houdini refuses to save, a locked file, a full disk -
        # left a directory holding full copies of the asset's .mat,
        # .interface, .builder.json and .png in the system temp dir,
        # once per attempt. Outside the library, so no audit or cleanup
        # sees it, and on macOS the system temp dir is only swept at
        # reboot.
        try:
            # update=True: overwrites <id>.mat/.interface (+ COP
            # companion) and always re-renders the thumbnail,
            # regardless of the render_on_import preference.
            if not handler.save_node(node, mat.mat_id, True):
                return ""
            # Our own write is the new baseline for this id.
            self._content_state[str(mat.mat_id)] = self._content_stat(
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
                # The base now holds the new state; archive it as the
                # new active version. Auto-named - never interrupt a
                # save to ask for a name (practice.md) - renameable in
                # the dialog.
                versions.create_version(self.preferences, mat.mat_id)
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
        # A content update is the one flow that can change what's inside
        # the saved files, so the per-id label caches (USD-ness, shader
        # type) genuinely go stale here - evict both.
        self._usd_cache.pop(mat.mat_id, None)
        self._shader_type_cache.pop(mat.mat_id, None)
        # Stale companion file: if the updated network no longer
        # references any COP net, remove the old <id>_cop.mat.
        if not mat.cop_net:
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
        # Reload the freshly rendered thumbnail into the model - the
        # engine discard inside makes the repaint fetch the new PNG.
        self._add_thumb_paths(self.index(row, 0))
        self.save()
        try:
            node.setUserData("assetlib_id", str(mat.mat_id))
        except hou.OperationFailed:
            pass
        return renderer

    def cleanup_db(self, show_dialog: bool = True) -> int:
        """Removes orphan data from disk, rescues uncategorized materials
        and reports everything in a single summary dialog.
        Never renders anything. Returns 1 if materials were rescued.

        show_dialog=False skips the dialog so the panel can combine
        several libraries' cleanups (materials + COP networks + browser
        prefs) into ONE report - the lines are always left on
        self.last_cleanup_summary either way."""
        summary = []

        # THE ASSET FOLDER MUST BE READABLE BEFORE ANY OF THIS.
        # Measured: with mat/ not yet synced down (the small json arrives
        # before the big folder, routinely, on a second machine), pass 1
        # called every asset missing and emptied the entire index to
        # disk - and then os.listdir raised out of the function before
        # the summary was built, so there was no dialog and no summary
        # line either. "Never DELETE on incomplete knowledge" applies to
        # the FOLDER as much as to a sibling database.
        assets_dir = os.path.join(
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

        # Load-time findings the person running a cleanup must see
        # BEFORE the sweep's own numbers: a list that shrank past half
        # since its newest snapshot reads exactly like a list that is
        # fine, unless somebody says the two numbers out loud.
        summary.extend(database.DatabaseConnector.take_integrity_notes())

        # --- Pass 1: scan assets (no mutation during iteration) ---
        rows_to_remove = []
        missing_thumbs = 0
        quarantined = []
        #: [source, destination] per moved file, for the ONE closing
        #: record. A per-file event shared one flood key and named 6 of
        #: 23 before going dark - a removal record has to be complete
        #: or it cannot be followed back.
        quarantined_paths = []
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

        # --- Pass 2: remove collected rows, highest row first so the
        # remaining indices stay valid ---
        #
        # removeRow, NOT remove_asset. These rows were collected BECAUSE
        # a file is missing, and remove_asset also unlinks the files -
        # so it deleted the SURVIVING sibling of a pair. Measured: a
        # .mat that had not finished syncing down cost its .interface
        # and .png permanently, and the .mat then arrived as an orphan
        # that the NEXT Clean Library deleted too. Cascading loss across
        # two passes, from a folder that was merely mid-sync.
        #
        # The index entry is what is stale here; whatever is still on
        # disk is evidence, and evidence is not ours to destroy.
        # REPORTED, NOT REMOVED. A row carries tags, a description, a
        # favourite and a date that exist NOWHERE else - library.json is
        # the truth, not a rebuildable index - so one os.path.exists()
        # miss must not destroy them. A file that has not finished
        # syncing down looks exactly like a file that is gone.
        #
        # This also retires the old two-pass cascade: pass 2 removed the
        # row, pass 3 then read the surviving sibling as an orphan and
        # deleted it too. Nothing mutates the row set before the sweep
        # runs any more.
        if rows_to_remove:
            names = sorted(str(self._assets[row].name) or "(unnamed)"
                           for row in rows_to_remove)
            summary.append(
                "%s kept in your library, but %s files are missing: %s.\n"
                "Nothing was removed - the entry holds tags, notes and "
                "favourites that are not stored anywhere else, and a file "
                "that has not finished syncing looks the same as one that "
                "is gone. If they really are gone, select them in Amaze "
                "and use Delete Entry."
                % (_count(len(rows_to_remove), "material"),
                   "their" if len(rows_to_remove) > 1 else "its",
                   helpers.and_list(names[:8]) + (
                       " and %d more" % (len(names) - 8)
                       if len(names) > 8 else "")))
        if missing_thumbs:
            # ONLY QUOTE A LABEL THAT EXISTS. This sentence named "Update
            # all Thumbnails" for a menu item grep cannot find anywhere in
            # the package; the control that does this is Rerender
            # Thumbnail, on a tile's right-click menu.
            summary.append(
                "No thumbnail image yet for %s - select %s in Amaze and use "
                "Render Thumbnail when convenient, since a render takes "
                "time." % (_count(missing_thumbs, "material"),
                           "it" if missing_thumbs == 1 else "them"))

        # --- Pass 3: lonely files on disk ---
        # The material and COP libraries share the same asset/img
        # directories, so "no entry in THIS database" is not enough to
        # call a file orphaned - union the ids from every sibling
        # database file before deleting anything.
        known_ids, unreadable, absent_traces, empty_sections = \
            self._all_known_asset_ids()
        lone_count = 0
        if unreadable:
            # Deleting on incomplete knowledge is never the safe
            # default: abort pass 3 entirely and SAY so, rather than
            # removing files whose owner we simply could not read.
            #
            # "could not be CHECKED", not "could not be read": there are
            # now three ways to land here and only one of them is a failed
            # read. A file that is not there yet, and one that is right
            # there and lists nothing while files it may own are sitting
            # in the asset folder, both fit "checked" and neither fits
            # "read" - and a sentence that fights the entry it introduces
            # leaves the reader unable to tell what is actually wrong. One
            # sentence shape for the whole family.
            #
            # AND IN THE USER'S WORDS. "Skipped the orphaned-file pass"
            # was the first wording: a pass is an internal loop and an
            # orphan is one of the banned words, in the first line of the
            # message that decides whether anything after it is
            # understood.
            #
            # THE REASON GOES ON ITS OWN LINE, one per section. Carrying
            # it inline nested a parenthetical inside a parenthetical
            # before the sentence reached its verb - "could not check
            # Nodes (cops.json) (it lists nothing at all, while 2 files
            # ...), so files that belong to it ..." - and a reader who
            # loses the thread of the first line has no reason to trust
            # the rest.
            summary.append(
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
                # NAME THE WAY OUT - AND WHAT IT COSTS. Both load-time
                # refusals name a way out; this one did not, so a user who
                # deleted a list on purpose had the sweep disabled for
                # good with nothing on screen saying why.
                #
                # The catch this sentence has to carry: on the real
                # library the trace it names is usually a .bak copy
                # (measured: cops.json has four), which is exactly what
                # Repair would put the section back FROM. Sending someone
                # to delete it, in the message whose partner tool exists
                # to restore it, spends the evidence to silence the
                # warning about the evidence.
                summary.append(
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
            # LAST, and for every cause. Whichever way the sweep was held
            # back - a list that has not arrived, one that will not parse,
            # one that lists nothing while files sit unaccounted for -
            # this is the step that answers it, and it is the same step.
            summary.append(self._the_repair_route())
            unreadable_abort = True
        else:
            unreadable_abort = False
        # STEP 14 NEEDS NOTHING HERE, and that is the finding rather
        # than an omission. It was specified as "give save() a bool and
        # skip pass 3 when pass 2's save returned False" - but step 11
        # took the write out of pass 2 entirely: rows are reported now,
        # never removed, so there is no index write for the sweep to be
        # racing. Its own spec anticipated this ("re-check against the
        # landed diff before building; do not duplicate").
        #
        # A guard WAS built here first, constructing a connector to read
        # its write-blocked latch, and it misfired immediately - it
        # refused a sweep in a fixture where nothing was wrong. The
        # cases it was reaching for are already covered upstream by
        # unreadable_abort, which stops the sweep for every kind of
        # incomplete knowledge about a sibling list.
        # DEAD SCRATCHES, before the ownership sweep. Uniquifying the
        # scratch names traded a reused leftover for an unbounded one: a
        # hard kill mid-write now leaves a fresh `<name>.<rand>.writing`
        # each time, the classifier rightly refuses to treat them as
        # assets, and nothing else ever touched them. The plan assigned
        # clearing them HERE. Age-gated to an hour, because a scratch a
        # moment old may be a live write in another session - and
        # quarantined like everything else this sweep moves, never
        # unlinked.
        for folder in (
                os.path.join(self.preferences.dir,
                             self.preferences.asset_dir),
                os.path.join(self.preferences.dir,
                             self.preferences.img_dir)):
            lone_count += self._sweep_dead_scratches(folder, quarantined)

        # AWAITING REPAIR IS NOT THE SAME AS LEFT OVER. An asset whose
        # index write was refused has files on disk and a row nowhere -
        # byte for byte the shape this sweep calls unaccounted for - and
        # it is the ONE case Repair exists for, because
        # repair.rebuild_from_stamps reconstructs the row from the
        # `<id>.stamp.json` sitting beside the asset. Sweeping it was
        # therefore the tidying pass carrying off the evidence the
        # recovery pass reads: safe only while the panel that still
        # remembered the asset stayed open, and lost on the first Clean
        # Library after a restart.
        #
        # The read is repair.stamped_assets, the SAME reader
        # rebuild_from_stamps parses with, so whether a given stamp reads
        # cannot mean one thing to the sweep and another to the rebuild.
        # Readable is the whole test: a stamp that will not parse
        # rebuilds nothing, so it protects nothing.
        #
        # IMPORTED HERE, not at module scope: repair imports this module,
        # so a top-level import is a cycle. It also keeps stamps out of
        # the core's import surface, which is what
        # test_a_stamp_is_never_read_in_normal_operation guards.
        from amaze.core import repair
        mats_path = os.path.join(self.preferences.dir, self.preferences.asset_dir)
        # ONE LISTING OF THE ASSET FOLDER, shared by the stamp scan and
        # the sweep below. Not a saved syscall: the sweep decides what to
        # move from one listing, and a second listing taken a moment
        # later can disagree - a stamp written in between would spare a
        # file the sweep never saw, one deleted in between would drop
        # protection from a file it is about to move.
        mat_names = [] if unreadable_abort else os.listdir(mats_path)
        awaiting_repair = {} if unreadable_abort else repair.stamped_assets(
            self.preferences.dir, self.preferences.asset_dir,
            names=mat_names)
        # A STAMP WITH NO .mat BESIDE IT IS NORMAL, and requiring one was
        # a wrong guard that got as far as a green suite. Measured on the
        # test library: 24 stamps, 7 .mat files, and all 17 of the
        # remainder are Code snippets - code.json claims every one. Code
        # keeps its text inline and owns no .mat, so demanding a payload
        # would deny protection to the whole section precisely when its
        # list is the thing that was lost.
        #
        # It also fixes the wrong case. A refused index write leaves NO
        # stamp - _StampWriter runs only on a save that landed - so the
        # shape this pass really meets is an asset that saved fine and
        # later lost its row, which is Repair's own case.
        spared = set()

        for f in mat_names:
            # Same classifier the guard above counted with - see
            # database.asset_id_for_file for why that is one function.
            split = database.asset_id_for_file(
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
        # isdir, ASYMMETRIC with the mat/ scan until now: a library whose
        # img/ has not been created yet raised straight out of cleanup.
        if unreadable_abort or not os.path.isdir(mats_path):
            listing = []
        else:
            listing = os.listdir(mats_path)
        for f in listing:
            # "<id>_icon.png" is a tile icon, not a leftover - the same
            # shape the .mat pass handles for "_cop". Without that tail,
            # every Clean Library deleted every icon and then reported
            # them as orphans removed.
            split = database.asset_id_for_file(f, (".png",), "_icon")
            if split is not None:
                found = str(split) in known_ids
                # THE SAME ID, SPARED IN BOTH FOLDERS. Repair puts the
                # row back; an icon quarantined in the same run would
                # bring it back blank, needing a re-render of a
                # thumbnail that was sitting right there.
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
        if quarantined_paths:
            # ONE record, carrying every move. Complete on purpose: this
            # is the only trace of where a file went, so a sample is
            # useless the moment somebody needs to put one back.
            debug.event("cleanup", "files quarantined",
                        moved=len(quarantined_paths),
                        files=quarantined_paths)
        if lone_count:
            # NAMES, not a bare count, and it says WHERE they went. This
            # used to read "Removed N files that no section listed" - a
            # sentence you cannot check and cannot undo. Nothing is
            # deleted now, so the honest sentence is the one that tells
            # you where to look if the sweep was wrong.
            #
            # "orphaned" stays out of it: a banned word, and this is the
            # last place to use one that exists only because of how the
            # thing was built.
            shown = sorted(quarantined)[:8]
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
            # SAY WHAT WAS KEPT, or the sweep reports a clean library
            # while real materials sit in the folder unlisted, and the
            # one person who could act on it never learns there is
            # anything to act on.
            #
            # It says what these files ARE before what to do about them:
            # a material that never finished being added is a thing an
            # artist can picture, where naming the sidecar would be the
            # storage layer wearing a coat. No banned word does the work
            # here (practice.md > Writing for the user).
            # THE NAME THE USER HAS SEEN, which is why the stamp reader
            # hands back the record and not just the id. Falling back to
            # the id only when a stamp carries no name: an unnamed
            # material still has to be nameable in a sentence.
            # NAMED, NOT COUNTED BY SECTION. The shared asset folder
            # holds materials, nodes and snippets, and a file no list
            # claims is one whose section nobody can name - so a count
            # noun would be a guess in the one sentence that has to be
            # trustworthy. Their own names carry it instead, and those
            # come from the stamp, which is why the reader returns the
            # record.
            shown_kept = sorted(
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
            if not unreadable_abort:
                # ONE repair route in the summary, never two. The
                # refusal branch above already appends it for its own
                # causes; this is the same step for a different finding,
                # and its docstring is explicit that there is only one of
                # it however many findings there are.
                summary.append(self._the_repair_route())

        # --- Pass 4: rescue materials without a valid category and
        # normalize legacy whitespace-mangled category data ---
        mark_rescued = 0
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

        # mark_rescued alone: missing-file rows are REPORTED and kept
        # since the report-only change, so rows_to_remove mutates
        # nothing and saving on it wrote an index that by construction
        # had nothing to write.
        if mark_rescued:
            self.save()

        self.last_cleanup_summary = list(summary)

        # --- Single summary dialog ---
        if show_dialog:
            if summary:
                # THE HEADER SAYS WHICH OF THE TWO HAPPENED. One header
                # for both outcomes meant a refusal opened with "Library
                # cleanup finished", so a reader who took the first line
                # and closed the dialog believed the library had been
                # tidied when nothing had been touched.
                header = ("Clean Library stopped before deleting any files:"
                          if unreadable_abort
                          else "Library cleanup finished:")
                hou.ui.displayMessage(
                    header + "\n\n- " + "\n- ".join(summary)  # type: ignore
                )
            else:
                hou.ui.displayMessage("Library cleanup finished: nothing to clean.")  # type: ignore

        return mark_rescued

    def _what_an_empty_section_means(self, empty_sections: list) -> list:
        """ONE line for every section that lists nothing, saying why Amaze
        will not decide on its own.

        The entry in the refusal above states the FACT (it lists nothing,
        and N files are listed by no section). This states what the reader
        cannot know from that: that the two explanations look identical
        from here. Without it the refusal reads as an accusation of a
        library that may be perfectly fine.

        One line for all of them rather than one each: two empty sections
        produced two near-identical thirty-word sentences in a single
        dialog, which is the nagging the aggregate rule exists to prevent.
        """
        if not empty_sections:
            return []
        sections = helpers.and_list(sorted(database.section_label(filename)
                                    for filename in empty_sections))
        return ["%s: a list that holds nothing looks the same whether "
                "nothing was ever saved there or it failed to load this "
                "time, so Amaze will not decide on its own which it is."
                % sections]

    def _the_repair_route(self) -> str:
        """The ONE next step for every way this sweep can be held back.

        A REFUSAL NAMES THE WAY OUT, or it is a dead end - and the way out
        cannot be "delete a copy beside the file" for the case that
        matters, because what stands in the way is real files in the asset
        folder that no section lists, and deleting backups does not make
        them accounted for.

        So it is Repair, and Repair exists for this sentence to point at:
        it reads the same files, says in plain words which list will not
        load and which files nothing accounts for, can put a saved copy of
        a list back, and never deletes anything. It lives on the SHELF
        rather than in the panel because a list put back while the panel
        is open is overwritten by the panel's own next save - a recovery
        that does not stick is worse than no recovery, since it turns a
        recoverable library into a confident wrong belief.

        ONE line for all three causes, not one per finding: aggregate
        before interrupting. The specific finding is already named per
        section above; this is the step, and there is only one of it.

        The shelf tab is a per-machine step (INSTALL.md 6b-2 - registered
        is not displayed, so a fresh machine has the tools without a tab),
        which is why the sentence says how to get the tab. A next step
        that assumes setup nobody did is the same dead end one door along.

        IT ALSO NAMES THE RESTART, and that is not padding. This message
        can only be reached from the panel, so by the time it is on screen
        this Houdini has read the library - one connector per file lives
        for the whole process, holding the document it read, and its next
        save writes that document over anything put back. So Repair
        reports in this session and can only ACT in a fresh one. Sending
        someone to a tool that will tell them to quit and come back, and
        not saying so here, is the same broken remedy one step later.
        """
        return (
            "Run the Repair tool on the Amaze shelf to see what is wrong: "
            "it names the lists that will not load, the files nothing "
            "accounts for, and what each saved copy would bring back - and "
            "it never deletes anything. To let it put things right as "
            "well, close Amaze, quit Houdini, start it again and run "
            "Repair before you open Amaze. If your shelf has no Amaze tab, "
            "right-click the shelf tabs, choose Shelves, then Amaze.")

    def _files_no_section_accounts_for(self, known_ids: set):
        """Names of the files in the asset folder that NO section lists,
        or None when the folder could not be read at all.

        ORPHANHOOD IS RELATIVE TO EVERY LIST SHARING THE DIRECTORY, never
        to one. Measured 2026-07-29 on the real library: 548 records in
        library.json plus 8 in cops.json is 556 .mat files, exactly. So
        `known_ids` must already be the finished union of every sibling
        plus this session's memory - a half-built union here would report
        a live COP asset's files as unclaimed, which is byte for byte how
        21 files were deleted once and how a human nearly deleted the
        same 8 by hand. The caller builds it in full first and only then
        asks.

        None, not [], when the listing fails: an empty list here means
        "nothing is unaccounted for", which is the reading that lets the
        sweep run. A handler that returns a neutral value makes a failure
        indistinguishable from an honest empty result, and this is the one
        place where that difference is a deletion.
        """
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
        """(ids, unreadable, absent_traces, empty_sections) for EVERY
        database file in the library dir, read directly from disk - used
        by cleanup_db so one library's cleanup never deletes files that
        belong to another.

        `unreadable` is (what to call the section, why it could not be
        checked) rather than one composed string, because the caller
        writes those two halves into two different sentences: the section
        names go in the headline, the reasons on a line each. Composed
        together they nested one parenthetical inside another.

        `absent_traces` maps a database that is merely NOT THERE YET to
        the trace that says so; `empty_sections` lists the ones that are
        right there, parse perfectly and yield ZERO ids while files in the
        asset folder are unaccounted for. Both exist so the message can
        name the way out, and they are separate because the way out is a
        different sentence: one is "if you deleted it on purpose", the
        other is Repair.

        code.json belongs here even though snippets keep their text in
        the index rather than in files: a Code asset with a tile icon
        owns a PNG in the shared image directory, and without its ids
        the material cleanup reads that PNG as an orphan."""
        ids = {str(a.mat_id) for a in self._assets}
        unreadable = []
        absent_traces = {}
        lists_nothing = []
        # THE READ ITSELF IS NOT THIS METHOD'S. "Which ids does each
        # database claim" is one question with one home
        # (database.ids_claimed_by), and repair.rebuild_from_stamps
        # asks it too. A second copy here is exactly how the two
        # readers of these SHARED folders would come to disagree about
        # who owns a file - the disagreement this guard exists to
        # prevent. What stays here is the POLICY, which is this
        # method's alone: what an absent, unreadable or empty database
        # MEANS for a sweep that deletes.
        claimed, unreadable_files = database.ids_claimed_by(
            self.preferences.dir)
        for filename in database.ID_CLAIMING_DATABASES:
            full = os.path.join(self.preferences.dir, filename)
            # THIS model's own database is checked too, and that is the
            # point of not skipping straight past it. Its ids are the
            # in-memory ones above - but only because a load put them
            # there, and a load that was REFUSED leaves _assets honestly
            # empty. Measured on the first version of this fix: with
            # cops.json mid-sync, the material cleanup correctly skipped
            # the pass and then the COP model's own cleanup ran on the
            # same click (panel.cleanup_db calls both) with zero ids of
            # its own and deleted all 23 files anyway - byte for byte
            # the loss the guard was written to stop. The database a
            # model is built on is the LAST one whose absence may be
            # waved through.
            own = filename == self.DB_FILENAME
            if filename in unreadable_files:
                # A sibling that EXISTS and will not parse is the
                # dangerous case: skipping it makes every file it owns
                # look orphaned, and pass 3 DELETES orphans. Measured
                # with cops.json truncated mid-write, which is a
                # cloud-sync client's normal state - two live COP
                # assets swept, then their own rows removed by the next
                # cleanup for missing files, a cascade across two
                # passes.
                #
                # NO PARSE POSITION ON SCREEN: this entry is
                # interpolated into the message the user acts on, and
                # the parser's line-and-column reason belongs in the
                # log, where the shared read already puts it.
                # section_name here too, so one dialog does not carry
                # two names for one thing.
                unreadable.append((database.section_name(filename),
                                   "Amaze cannot read it"))
                debug.event("cleanup", "sibling database unreadable",
                            file=full, own=own)
                continue
            if filename not in claimed:
                # Absent is fine - it owns nothing - ONLY when nothing
                # beside it says it was ever here. Otherwise this is a
                # database that has not arrived yet, and the files it
                # owns are indistinguishable from orphans, exactly as if
                # it were there and unparseable. Reproduced 2026-07-29
                # with cops.json momentarily gone: 21 files belonging to
                # its 8 live assets were removed and reported as
                # orphans. The read that could have told us who owned
                # them is the one that failed, so the answer is the same
                # as below - refuse the pass, delete nothing.
                evidence = database.absent_but_known(
                    self.preferences.dir, filename)
                if not evidence:
                    continue
                # "not there yet", not "not on disk": the shared
                # sentence below ends in "could not be read", and "not
                # on disk ... could not be read" fights itself.
                unreadable.append(
                    (database.section_name(filename),
                     "it is not there yet - %s beside it says it was here"
                     % evidence))
                absent_traces[filename] = evidence
                debug.event("cleanup", "database absent but known",
                            file=full, evidence=evidence, own=own)
                continue
            # THE MODEL'S OWN DATABASE COUNTS TOO, and its disk rows
            # are not the in-memory ones: another session can have
            # added rows since this one loaded. Union, never replace -
            # a row this session added has not necessarily reached disk
            # yet (practice.md ▸ DB-HARDENING step 10).
            file_ids = claimed[filename]
            # A DATABASE THAT LISTS NOTHING IS NOT AUTHORITATIVELY
            # EMPTY - it is the shape a wrongly-seeded one has, and it
            # is indistinguishable from a section nobody has used. The
            # dangerous condition is emptiness AND files still sitting
            # in the asset folder, so the decision is made below, once
            # every sibling has been read; this loop only notes it.
            # ASSET_FILE_OWNERS narrows it to the lists that could own
            # one of those files - Code and Colors keep their content
            # inline and cannot (database.py says so once, for both
            # readers of that fact).
            if not file_ids and filename in database.ASSET_FILE_OWNERS:
                lists_nothing.append(filename)
            ids |= file_ids

        # THE STRICT TEST, and it is narrow on purpose (DB-HARDENING step
        # 10, decided 2026-07-30). A section that lists nothing holds the
        # sweep back ONLY while files in the asset folder are unaccounted
        # for:
        #   * lists nothing + nothing unaccounted for = a section nobody
        #     has used. Sweep, because there is nothing here that could
        #     have belonged to it.
        #   * lists nothing + files sitting right there = a load that
        #     failed. Refuse, because those files may be its assets.
        #
        # This REPLACES the version that shipped first, which asked
        # instead whether a copy beside the file still listed materials.
        # Measured on the real library: gradients.json has no .bak at all
        # and code.json has none either, so the least-protected files got
        # the weakest guard - the evidence the guard needed was exactly
        # the evidence those files do not have. The files in the asset
        # folder are evidence every library has.
        #
        # It also replaces the live-model acceptance that went with it. A
        # model whose own load quietly produced nothing agrees "empty"
        # perfectly happily, and Clean Library is reached from the panel's
        # own View menu - so the panel is open, its sections are loaded,
        # and the one configuration that defeated the guard was the
        # ordinary one. Files nothing accounts for cannot be talked out of
        # existence by a model; they are either somebody's assets or
        # leftovers, and only the user can say which. That is Repair's
        # question, and Lightroom's answer to the same problem: refuse to
        # decide, and ask.
        empty_sections = []
        # The folder as the user sees it in Finder - prefs stores it with
        # the separator ("mat/") because everything else joins paths with
        # it, and "the mat/ folder" in a sentence reads as a typo.
        folder = str(self.preferences.asset_dir).rstrip("/\\")
        if lists_nothing and not unreadable:
            unaccounted = self._files_no_section_accounts_for(ids)
            if unaccounted is None:
                # The folder was readable moments ago (cleanup_db checks
                # it before anything else) so this is nearly unreachable -
                # but "could not list it" must never arrive here as
                # "nothing is unaccounted for".
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
        elif lists_nothing:
            # Already refusing for another reason, so the union is
            # incomplete and NOTHING may be called unaccounted for from
            # it. Recorded rather than dropped: this is the combination
            # that hides one problem behind another in a log.
            debug.event("cleanup", "section lists nothing, not checked "
                        "further - already held back",
                        sections=list(lists_nothing),
                        held_back_by=list(unreadable))
        return ids, unreadable, absent_traces, empty_sections

    def toggle_fav(self, index: QtCore.QModelIndex) -> None:
        """
        Toggle the Favorite Parameter for the given QModelIndex

        :param self: Description
        :param index: Description
        :type index: QtCore.QModelIndex
        """
        mat_id = self._assets[index.row()].mat_id
        try:
            now = not self.preferences.is_material_favorite(mat_id)
            # prefs.set saves prefs itself; the LIBRARY is untouched -
            # a favourite toggle no longer writes the shared index at
            # all, which is the whole point: my star cannot collide
            # with yours when it never leaves my settings.
            self.preferences.set_material_favorite(mat_id, now)
        except AttributeError:
            self._assets[index.row()].fav = not self._assets[index.row()].fav
            self.save()
        model_index = self.index(index.row(), 0)
        self.row_changed(model_index.row(), [self.FavoriteRole])

    def render_thumbnail(self, index: QtCore.QModelIndex) -> None:
        """
        Render the Thumbnail for the given QModelIndex

        :param self: Description
        :param index: Description
        :type index: QtCore.QModelIndex
        """
        self.render_thumbnails([index])

    def render_thumbnails(self, indexes) -> None:
        """Re-render every index, building ONE Karma scaffold for the
        batch.

        The scaffold is a full USD stage composition and is identical
        for every material, so a per-material build paid the stage
        load once per row - `build_karma_scaffold` and
        `render_karma_into` were written to be shared across a batch
        and had no caller doing it. A single render is just a batch of
        one and takes the same path.
        """
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
        """
        Import the given QModelIndex into the Houdini scene.

        target: "auto" (context-aware), "mat", or "lop"; context_node
        optionally pins the destination context (drag release point).
        Returns (ok, reason) from the importer so the panel can report any
        materials that could not live in the requested context.

        :param self: Description
        :param index: Description
        :type index: QtCore.QModelIndex
        """
        importer = nodes.NodeHandler(self.preferences)
        return importer.import_asset_to_scene(
            self._assets[index.row()], target, context_node=context_node
        )

    def convert_redshift_to_karma(self, index: QtCore.QModelIndex):
        """Best-effort conversion of a Redshift material to a Karma/
        MaterialX equivalent (test/v0 - see render/material_converter.py
        for exactly what is and isn't handled). Registers the result as a
        new library entry in the same category(ies) as the source,
        alongside it - never replaces or touches the original.

        Returns (ok, report). report.summary_lines() explains what
        happened even when ok is True - a "successful" conversion can
        still have skipped/approximated inputs, nothing here is silently
        perfect."""
        mat = self._assets[index.row()]
        if "Redshift" not in mat.renderer:
            report = material_converter.ConversionReport(mat.name)
            report.skip("not a Redshift material")
            return False, report

        handler = nodes.NodeHandler(self.preferences)
        # Off the undo stack at BOTH ends: a create/destroy pair on the
        # live stack resurrects the scratch with the converted network
        # on one Ctrl+Z (#278).
        with hou.undos.disabler():
            scratch = hou.node("/obj").createNode("matnet")
        try:
            # Build the converted material INSIDE a real Karma Material
            # Builder, not a bare matnet. Karma-context nodes (kma_*,
            # e.g. the proper kma_rampconst ramp) simply aren't valid
            # outside one, and a builder saves/reimports as a single
            # subnet exactly like a hand-built Karma material does
            # (load_items_file_mtlx's unwrap path) instead of as loose
            # items needing scaffolding on the way back in.
            # The Redshift converter is one ADAPTER feeding the shared
            # Karma material engine: it only produces the shader network;
            # the engine owns the container, wiring, layout and the
            # surface-terminal invariant check.
            report_holder = {}

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
                # THE ENGINE'S VERDICT REACHES THE REPORT, through the
                # channel the report already has. It is the only thing
                # the user reads after a convert-all sweep, and it said
                # fully converted, no skipped inputs over a material
                # with no wired surface terminal - a black render
                # reported as a clean conversion, because `is_clean()`
                # asks about skips and nothing had skipped.
                report.skip("the surface output is not wired, so this "
                            "material renders black until it is "
                            "connected by hand")
            saved = self.add_asset(
                builder, ",".join(mat.categories), ",".join(mat.tags), False)
            # The scratch network is destroyed in the finally below, so
            # a refused save leaves NOTHING behind - answering True
            # here would tell the convert-all sweep that a material it
            # can no longer reach is in the library.
            return bool(saved), report
        finally:
            # The live Karma network only exists to be copied by
            # add_asset()'s own save path - never left in the scene,
            # same discipline as the Redshift scratch reconstruction in
            # convert_redshift_material() itself.
            with hou.undos.disabler():
                scratch.destroy()
