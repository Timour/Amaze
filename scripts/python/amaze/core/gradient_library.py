"""Models for the Gradients ("Colors") section - a material-style library over gradients.json, payload inline and preview painted. Curated sets seed once into ordinary user gradients; each res/def/*.json carries its own `source` attribution."""

import json
import os

import hou
from PySide6 import QtCore, QtGui

import amaze
from amaze.core import category
from amaze.core import database
from amaze.core import debug
from amaze.core import library
from amaze.core import locations
from amaze.core import material
from amaze.core import multifilterproxy_model
from amaze.core import thumbnails
from amaze.core import tile_icons
from amaze.helpers import hostos

THUMB_SIZE = 256


def _def_path(filename: str) -> str:
    """A curated set shipped inside the package - `package_file`, never a rebuilt install path, which answers "" with $AMAZE unset."""
    return amaze.package_file("res", "def", filename)


CURATED_SETS = (  # the curated sets in display order; adding one here plus its JSON in res/def/ is the whole job, and "label" feeds the seeded category names
    {"key": "wada", "label": "Wada", "file": "sanzo_wada.json"},
    {"key": "klee", "label": "Klee", "file": "paul_klee.json"},
    {"key": "albers", "label": "Albers", "file": "josef_albers.json"},
    {"key": "itten", "label": "Itten", "file": "johannes_itten.json"},
)


def _palette_ramp_data(colors: list) -> dict:
    """A STEPPED (constant-basis) ramp from a palette's hex colours, shaped like a saved user ramp so a seeded palette re-applies exactly and paints as bands."""
    n = len(colors)
    keys, values = [], []
    for i, c in enumerate(colors):
        keys.append(i / n if n else 0.0)
        h = c["hex"].lstrip("#")
        values.append([int(h[j:j + 2], 16) / 255.0 for j in (0, 2, 4)])
    return {"keys": keys, "values": values, "bases": ["Constant"] * n}


class GradientCategories(category.Categories):
    """The Colors section's category sidebar - same model, own database."""

    DB_FILENAME = "gradients.json"


class GradientLibrary(library.AssetLibrary):
    """The Colors section's asset model - the shared engine over gradients.json, with the palette payload inline and a painted preview."""

    NOTES_SECTION = "gradient"

    DB_FILENAME = "gradients.json"

    CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE = False  # a palette lives INLINE, so a refused list write leaves nothing on disk to recover

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "RendererLabelRole",
        "category": "CategoryLabelRole",
        "favorite": "FavoriteRole",
        "comments": "NotesRole",
    }

    CategoryLabelRole = QtCore.Qt.ItemDataRole.UserRole + 13  # list mode's Category column, the display string; CategoryRole answers a LIST for the proxy. test_role_numbers holds the gap

    def __init__(self, preferences) -> None:
        super().__init__(preferences)
        self._persist_minted_ids_once()
        self._sweep_notes_to_store_once()

    @staticmethod
    def _asset_from_row(row: dict):
        """A palette rides as a `Material`, `colors` and `ramp` among its carried-through keys."""
        row = dict(row)
        legacy = str(row.get("uid") or "")  # `uid` was the pre-connector spelling; mapping it onto `id` keeps notes and tile icons on one key
        if legacy and not str(row.get("id") or ""):
            row["id"] = legacy
        mat = material.Material.from_dict(row)
        if not str(row.get("date") or ""):
            mat._date = ""  # a stored row without a date keeps an empty one, rather than Material fabricating today's
        return mat

    @property
    def _load_failed(self) -> bool:
        """Whether the connector is refusing to write this file - read through to the connector's own latch."""
        if self.preferences is None:
            return False
        return bool(getattr(
            database.DatabaseConnector(self.DB_FILENAME),
            "_write_blocked", False))

    def switch_model_data(self) -> None:
        super().switch_model_data()
        self._persist_minted_ids_once()
        self._sweep_notes_to_store_once()

    def _persist_minted_ids_once(self) -> None:
        """Write a minted id back so it IS the row's identity rather than a value that changes every launch - notes and tile icons are keyed by it."""
        raw = [row for row in (self._data.get("assets") or [])
               if isinstance(row, dict)]
        minted = 0
        for row, asset in zip(raw, self._assets):
            if not str(row.get("id") or row.get("uid") or ""):
                row["id"] = asset.mat_id  # stamped INTO the connector's row, in place: the connector unions by id, so a bare save lands a duplicate beside the original
                minted += 1
        if minted and self.save():
            debug.event("gradients", "ids minted and persisted",
                        count=minted)

    def _sweep_notes_to_store_once(self) -> None:
        """Move any entry-level `note` text onto the asset's Comments page; a note the store cannot take stays on the row and is retried next load - moved, never dropped."""
        from amaze.core import notes
        moved = cleared = 0
        pages = {}
        carriers = {}
        for asset in self._assets:
            extra = getattr(asset, "_extra", None)
            if not isinstance(extra, dict) or "note" not in extra:
                continue
            text = str(extra.get("note", "") or "").strip()
            if not text:
                del extra["note"]
                cleared += 1
                continue
            key = notes.note_key(self.NOTES_SECTION, asset.mat_id)
            page = notes.note_for(self.preferences, key)
            items = list(pages.get(key, page.get("items", [])))
            items.append({"t": "text", "text": text})
            pages[key] = items
            carriers.setdefault(key, []).append(extra)
        if pages and notes.set_notes(self.preferences, pages):  # collected and written ONCE: per-entry writes rotated a snapshot each
            for extras in carriers.values():
                for extra in extras:
                    extra.pop("note", None)
                    moved += 1
        if moved or cleared:
            self.save()
            debug.event("gradients", "notes swept to the notes store",
                        moved=moved, cleared=cleared)

    _SEED_MARKER = ".amaze_gradient_seed_v1"  # bump when the seed contents change, so a new set re-seeds
    _SEED_MARKER_LEGACY = ".assetlib_gradient_seed_v1"  # renamed on sight so an old library does not re-seed and duplicate

    def seed_curated_palettes(self, category_model) -> None:
        """First run per library: every curated combination becomes a normal user gradient. Guarded by a marker file, best-effort - never blocks panel startup."""
        try:
            lib_dir = self.preferences.dir
            if not lib_dir:
                return
            if self._load_failed:
                return  # a refused file must not earn a PERMANENT marker for a save that never happened
            marker = os.path.join(lib_dir, self._SEED_MARKER)
            hostos.migrate_legacy_file(
                lib_dir, self._SEED_MARKER_LEGACY, self._SEED_MARKER)
            if os.path.exists(marker):
                return
            seeded = 0
            categories = []
            for curated in CURATED_SETS:
                path = _def_path(curated["file"])
                if not path or not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8-sig") as f:
                    combos = json.load(f).get("combinations", [])
                for combo in combos:
                    colors = combo.get("colors") or []
                    if not colors:
                        continue
                    n = len(colors)
                    cat_name = "%s %s Color%s" % (
                        curated["label"], n, "" if n == 1 else "s")
                    if cat_name not in categories:
                        categories.append(cat_name)
                    name = (combo.get("name")
                            or "Combination %s" % combo.get("id"))
                    mat = self._asset_from_row({
                        "name": name,
                        "categories": [cat_name],
                        "colors": colors,
                        "ramp": _palette_ramp_data(colors),
                        "note": combo.get("note", ""),
                    })
                    row = len(self._assets)
                    self.beginInsertRows(QtCore.QModelIndex(), row, row)
                    try:
                        self._assets.append(mat)
                    finally:
                        self.endInsertRows()
                    seeded += 1
            if not seeded:
                return  # def files unreachable this run: leave the marker off and retry next launch
            self.rebuild_thumbs()
            if not self.save():  # the marker is PERMANENT, so it must not be minted for a save that never landed
                debug.event("gradient", "curated seed not marked - the "
                            "save did not reach disk")
                return
            for cat_name in categories:
                category_model.check_add_category(cat_name)
        except Exception as exc:                        # noqa: BLE001
            debug.event("gradient", "curated palette seed failed",
                        error=str(exc))
            return
        if not os.path.exists(os.path.join(lib_dir, self.DB_FILENAME)):  # database.save() reports an OSError instead of raising, so a save held off by a full disk lands here looking successful - and a marker with no database behind it refuses gradients.json on every future launch
            debug.event("gradient", "seed marker withheld - the "
                        "database is not on disk", file=lib_dir)
            return
        try:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("seeded %d curated palettes\n" % seeded)
        except OSError as exc:
            debug.exception("gradient seed marker", exc, marker=marker)
            debug.note(
                "the curated palettes are in your Colors library, but "
                "adding them could not be recorded (%s) - so they "
                "will be added a second time when Houdini next "
                "starts. Your own palettes are not affected." % exc)
            self._seed_marker_failed = True  # a RECORD, not a guard: hand-deleting 348 duplicated palettes is not a next step that works
            return
        self._sweep_notes_to_store_once()  # the seeded notes move to their Comments pages in THIS session, not on the next launch's sweep

    @staticmethod
    def _colors_of(asset) -> list:
        """The palette's colour dicts - carried through on the record beside the fields the family knows."""
        extra = getattr(asset, "_extra", None) or {}
        colors = extra.get("colors")
        return colors if isinstance(colors, list) else []

    @staticmethod
    def _ramp_of(asset) -> dict:
        extra = getattr(asset, "_extra", None) or {}
        ramp = extra.get("ramp")
        return ramp if isinstance(ramp, dict) else {}

    def entry(self, row: int) -> dict | None:
        """READ-ONLY view of one palette - a copy on purpose, because edits go through the record API, not through this dict."""
        if not 0 <= row < len(self._assets):
            return None
        asset = self._assets[row]
        return {
            "name": asset.name,
            "categories": list(asset.categories),
            "colors": self._colors_of(asset),
            "ramp": self._ramp_of(asset),
        }

    def is_favorite(self, row: int) -> bool:
        """The star, from the library store under its owner - the int-row spelling the Colors proxy reads."""
        if not 0 <= row < len(self._assets):
            return False
        return locations.is_favourite(
            self.preferences, self._assets[row].mat_id)

    def note_uid(self, row: int) -> str:
        """A palette's identity - its record id, the same key its Comments page and tile icon use."""
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].mat_id)

    def user_categories(self) -> list:
        """The categories the save dialog lists, without the `_All` marker."""
        return [name for name in self._data.get("categories", [])
                if isinstance(name, str) and name != "_All"]

    def set_user_category(self, rows: list, category_name: str) -> int:
        """Move the given rows' palettes to a category; returns how many moved."""
        category_name = (category_name or "").strip()
        if not category_name:
            return 0
        cats = self._data.setdefault("categories", [])
        if category_name not in cats:
            cats.append(category_name)
        moved = 0
        for row in rows:
            if not 0 <= row < len(self._assets):
                continue
            asset = self._assets[row]
            if asset.categories != [category_name]:
                asset.categories = category_name
                moved += 1
        if moved:
            self.save()
            for row in rows:
                self.row_changed(row)
        return moved

    def add_user_gradient(self, name: str, category_name: str,
                          ramp_data: dict) -> None:
        """Register a saved ramp; the colour list is derived from the ramp values so search, swatches and subtitles work as they do for seeded entries."""
        colors = []
        for value in ramp_data.get("values", []):
            hex_color = "#%02x%02x%02x" % tuple(
                max(0, min(255, round(c * 255))) for c in value[:3]
            )
            colors.append({"name": hex_color, "hex": hex_color})
        category_name = (category_name or "").strip()
        cats = self._data.setdefault("categories", [])
        if category_name and category_name not in cats:
            cats.append(category_name)
        mat = material.Material()
        mat.set_data((name or "Gradient").strip() or "Gradient",
                     category_name, "", False, "")
        mat._extra = {"colors": colors, "ramp": ramp_data}
        self.beginInsertRows(QtCore.QModelIndex(), 0, 0)  # at the TOP: the Colors grid shows source order and the newest palette belongs where the eye is
        try:
            self._assets.insert(0, mat)
        finally:
            self.endInsertRows()
        self.rebuild_thumbs()
        if not self.save():  # nothing reached disk, so nothing stays on screen
            self.beginRemoveRows(QtCore.QModelIndex(), 0, 0)
            try:
                del self._assets[0]
            finally:
                self.endRemoveRows()
            self.rebuild_thumbs()
            debug.alert(
                'Amaze could not save "%s".\n\n'
                "Nothing else has been lost - your other colors are "
                "exactly as they were.\n\n"
                "Close any other Amaze panel, or restart Houdini, then "
                "try again." % (name or "this palette"),
                key="colors-not-saved")
            return
        self.row_changed(0)

    def remove_asset(self, index) -> None:
        """The family's delete verb in Colors' terms - a palette owns nothing on disk beyond its row, so there is no file pass."""
        if index.isValid():
            self.remove_user_gradient(index.row())

    def remove_user_gradient(self, row: int) -> None:
        """Delete a palette, honouring the connector's answer."""
        if not 0 <= row < len(self._assets):
            return
        asset = self._assets[row]
        if not self.removeRow(row):  # says the delete out loud - the connector unions rows, so an unspoken delete comes straight back
            return
        if not self.save():
            self.beginInsertRows(QtCore.QModelIndex(), row, row)
            try:
                self._assets.insert(row, asset)
            finally:
                self.endInsertRows()
            self.rebuild_thumbs()
            try:
                connector = database.DatabaseConnector(self.DB_FILENAME)
                connector.unforget(asset.mat_id)  # in the document too: set() has already consumed the mark by now
                connector.set({"assets": [asset.get_as_dict()]})
            except (AttributeError, TypeError) as exc:
                debug.event("gradient", "could not take back a row "
                            "removal", error=str(exc))
            debug.alert(
                '"%s" was not deleted, because Amaze could not update '
                "your colors.\n\n"
                "Nothing was removed - the palette is exactly as it "
                "was.\n\n"
                "Close any other Amaze panel, or restart Houdini, then "
                "try again." % (asset.name or "That palette"),
                key="colors-delete-refused")

    def cleanup_db(self, show_dialog: bool = True) -> int:
        """Reduced to a state flush: palettes are stored inline, so the inherited missing-file and lonely-file passes would call every one an orphan."""
        self.save()
        self.last_cleanup_summary = [
            "Colors: nothing to clean (palettes are stored inline)."
        ]
        return 0

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        """Give one palette a tile icon, or clear it with an empty spec. NO PNG is written - the icon is composed in memory by the paint path."""
        row = index.row() if hasattr(index, "row") else int(index)
        if not 0 <= row < len(self._assets):
            return False
        spec = tile_icons.normalise(spec)
        stored = tile_icons.set_override(
            self.preferences, str(self._assets[row].mat_id), spec)
        if save:
            self.save()
        self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])
        return bool(stored)

    @staticmethod
    def _is_banded(colors: list, ramp: dict) -> bool:
        """True when the palette paints as bands rather than a gradient - every basis Constant, or no ramp yet."""
        bases = ramp.get("bases") or []
        return bool(colors) and (
            not bases or all(b == "Constant" for b in bases)
        )

    def _swatch_key(self, row: int):
        """Content-addressed, so renames cannot stale it and edits mint a new key while the old image ages out of the shared LRU."""
        asset = self._assets[row]
        colors = self._colors_of(asset)
        ramp = self._ramp_of(asset)
        hexes = tuple(c.get("hex") for c in colors if isinstance(c, dict))
        bases = tuple(ramp.get("bases") or ())
        stops = tuple(round(float(k), 6) for k in (ramp.get("keys") or ())  # positions too: same colours in different places paint differently
                      if isinstance(k, (int, float)))
        icon = self.tile_icon(row)
        icon_key = (icon.get("name"), icon.get("bg"), icon.get("ink")) \
            if icon else None
        return ("grad", self._is_banded(colors, ramp), hexes, bases,
                stops, icon_key, THUMB_SIZE)

    def _decoration_image(self, index: QtCore.QModelIndex):
        """The painted swatch (or chosen icon) over the engine's PAINT path - this section has no thumbnail files, so the base's file loader never applies."""
        row = index.row()
        asset = self._assets[row]
        key = self._swatch_key(row)
        image = thumbnails.engine.peek(key)
        if image is not None:
            return image
        if self.tile_icon(row):
            composed = self._missing_thumb_image(row)
            if composed is not None:
                thumbnails.engine.deposit(key, composed)
                return composed
        colors = self._colors_of(asset)
        ramp = self._ramp_of(asset)
        image = QtGui.QImage(
            THUMB_SIZE, THUMB_SIZE, QtGui.QImage.Format.Format_RGB32
        )
        painter = QtGui.QPainter(image)
        if self._is_banded(colors, ramp):
            band_h = THUMB_SIZE / max(len(colors), 1)  # stacked horizontal bands - the dictionary's own presentation
            for i, color in enumerate(colors):
                painter.fillRect(
                    QtCore.QRectF(0, i * band_h, THUMB_SIZE, band_h + 1),
                    QtGui.QColor(color["hex"]),
                )
        else:
            self._paint_ramp(painter, ramp)
        painter.end()
        thumbnails.engine.deposit(key, image)
        return image

    @staticmethod
    def _paint_ramp(painter: QtGui.QPainter, ramp_data: dict) -> None:
        """Left-to-right preview of a saved ramp: hard bands when it is fully constant-basis, otherwise a linear-interpolated gradient."""
        keys = ramp_data.get("keys", [])
        values = ramp_data.get("values", [])
        bases = ramp_data.get("bases", [])
        if not keys or not values:
            painter.fillRect(0, 0, THUMB_SIZE, THUMB_SIZE,
                             QtGui.QColor("#444444"))
            return
        if all(b == "Constant" for b in bases):
            edges = list(keys) + [1.0]
            for i, value in enumerate(values):
                x0 = max(0.0, min(1.0, edges[i])) * THUMB_SIZE
                x1 = max(0.0, min(1.0, edges[i + 1])) * THUMB_SIZE
                color = QtGui.QColor.fromRgbF(*value[:3])
                painter.fillRect(
                    QtCore.QRectF(x0, 0, x1 - x0 + 1, THUMB_SIZE), color)
            return
        gradient = QtGui.QLinearGradient(0, 0, THUMB_SIZE, 0)
        for key, value in zip(keys, values):
            gradient.setColorAt(
                max(0.0, min(1.0, key)), QtGui.QColor.fromRgbF(*value[:3])
            )
        painter.fillRect(0, 0, THUMB_SIZE, THUMB_SIZE,
                         QtGui.QBrush(gradient))

    def render_thumbnail(self, row) -> None:
        """No render - the preview is drawn from the palette's own ramp; repaint it from current content."""
        if 0 <= row < len(self._assets):
            thumbnails.engine.discard(self._swatch_key(row))
            self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])

    def data(self, index, role: int = 0):
        if index.column() > 0:  # later columns are the table's, not the row's; column 0 falls through so grid mode cannot tell
            return self.column_data(index, role)
        row = index.row()
        if not 0 <= row < len(self._assets):
            return None
        asset = self._assets[row]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return asset.name or "Gradient"
        if role in (self.RendererLabelRole, self.RendererRole):
            return "Gradient"  # uniformly the KIND of thing; which set or size an entry belongs to is Category-column information
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            from amaze.helpers import ui_helpers
            names = ", ".join(
                str(c.get("name", "")) for c in self._colors_of(asset))
            return ui_helpers.tooltip_text(names)
        if role == self.CategoryLabelRole:
            cats = asset.categories
            return cats[0] if cats else "Uncategorized"
        return super().data(index, role)


class GradientFilterProxyModel(multifilterproxy_model.MultiFilterProxyModel):
    """The family proxy with Colors' two own dimensions on top: the palette-size filter, and a name search that also matches the colour names inside a palette."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._size_filter = None

    def set_size_filter(self, bounds) -> None:
        """Show only palettes holding this many colors. `bounds` is (fewest, most), `most` None meaning no upper end; None switches the filter off. panel/sections.py ▸ GradientSection.FILTER_CHOICES is where the pairs live."""
        self._size_filter = bounds
        self.refilter()

    def _name_matches(self, needle: str, index) -> bool:
        if super()._name_matches(needle, index):
            return True
        entry = self.sourceModel().entry(index.row()) or {}
        needle = needle.lower()
        return any(needle in str(color.get("name", "")).lower()
                   for color in entry.get("colors") or ())

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        if not super().filterAcceptsRow(source_row, source_parent):
            return False
        if self._size_filter is None:
            return True
        entry = self.sourceModel().entry(source_row) or {}
        fewest, most = self._size_filter
        held = len(entry.get("colors") or ())
        return held >= fewest and (most is None or held <= most)
