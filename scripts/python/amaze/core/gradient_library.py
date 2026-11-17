"""Models for the Colors section over colors.json; curated sets are added once as user gradients."""

import json
import os

from PySide6 import QtCore, QtGui

import amaze
from amaze.core import category
from amaze.core import debug
from amaze.core import library
from amaze.core import library_db
from amaze.core import library_files
from amaze.core import material
from amaze.core import multifilterproxy_model
from amaze.core import thumbnails
from amaze.core import tile_icons
from amaze.helpers import hostos
from amaze import messages

THUMB_SIZE = 256
EMPTY_SWATCH = "#444444"    # the background where a palette paints nothing


def _def_path(filename: str) -> str:
    """The path of a curated set shipped inside the package."""
    return amaze.package_file("res", "def", filename)


CURATED_SETS = (  # display order; each needs its JSON in res/def/, `label` names its categories
    {"key": "wada", "label": "Wada", "file": "sanzo_wada.json"},
    {"key": "klee", "label": "Klee", "file": "paul_klee.json"},
    {"key": "albers", "label": "Albers", "file": "josef_albers.json"},
    {"key": "itten", "label": "Itten", "file": "johannes_itten.json"},
)


def _palette_ramp_data(colors: list) -> dict:
    """A constant-basis ramp from a palette's hex colours, shaped like a saved user ramp."""
    n = len(colors)
    keys, values = [], []
    for i, c in enumerate(colors):
        keys.append(i / n if n else 0.0)
        h = c["hex"].lstrip("#")
        values.append([int(h[j:j + 2], 16) / 255.0 for j in (0, 2, 4)])
    return {"keys": keys, "values": values, "bases": ["Constant"] * n}


def _has_rgb(value) -> bool:
    """Whether a ramp value has the three channels a colour needs; a shorter one is left out."""
    return isinstance(value, (list, tuple)) and len(value) >= 3


def paint_swatch(colors: list, ramp: dict) -> QtGui.QImage:
    """The tile face, THUMB_SIZE square: horizontal bands when banded, else the saved ramp."""
    image = QtGui.QImage(
        THUMB_SIZE, THUMB_SIZE, QtGui.QImage.Format.Format_RGB32
    )
    image.fill(QtGui.QColor(EMPTY_SWATCH))
    painter = QtGui.QPainter(image)
    try:
        if GradientLibrary._is_banded(colors or [], ramp or {}):
            band_h = THUMB_SIZE / max(len(colors or []), 1)  # stacked horizontal bands - the dictionary's own presentation
            for i, color in enumerate(colors or []):
                hex_value = color.get("hex") if isinstance(color, dict) else None
                colour = QtGui.QColor(hex_value if isinstance(hex_value, str) else "")
                if colour.isValid():    # no readable hex: the band stays empty, never black
                    painter.fillRect(
                        QtCore.QRectF(0, i * band_h, THUMB_SIZE, band_h + 1), colour)
        else:
            GradientLibrary._paint_ramp(painter, ramp or {})
    finally:
        painter.end()
    return image


class GradientCategories(category.Categories):
    """The Colors section's category sidebar - same model, own database."""

    DB_FILENAME = library_files.COLORS


class GradientLibrary(library.AssetLibrary):
    """The Colors section's asset model over colors.json, palettes inline, previews painted."""

    NOTES_SECTION = "gradient"    # the key prefix of its comments; never rename it
    TILE_FACE = "face_color"    # T10

    DB_FILENAME = library_files.COLORS

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "RendererLabelRole",
        "category": "CategoryLabelRole",
        "favorite": "FavoriteRole",
        "comments": "NotesRole",
    }

    CategoryLabelRole = QtCore.Qt.ItemDataRole.UserRole + 13  # the Category column's display string

    @staticmethod
    def _asset_from_row(row: dict):
        """A palette is stored as a `Material`, with `colors` and `ramp` among its extra keys."""
        mat = material.Material.from_dict(dict(row))
        if not str(row.get("date") or ""):
            mat._date = ""  # a stored row without a date keeps an empty one, rather than Material filling in today's
        return mat

    @property
    def _load_failed(self) -> bool:
        """Whether the database accepts no change now."""
        if self.preferences is None:
            return False
        return not library_db.accepts(self.preferences, self.DB_FILENAME)

    _SEED_MARK = "gradient_seed_v1"  # in the library's marks; bump when the seed contents change

    def seed_curated_palettes(self, category_model) -> None:
        """Once per library, recorded as a mark: every curated combination becomes a user gradient."""
        from amaze.core import library_settings, notes
        try:
            lib_dir = self.preferences.dir
            if not lib_dir:
                return
            if self._load_failed:
                return  # a database that accepts no change must not get a PERMANENT mark for a save that never happened
            if library_settings.marked(self.preferences, self._SEED_MARK):
                return
            seeded = 0
            categories = []
            pages = {}
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
                        "curated": "%s/%s" % (curated["key"],    # the stable id a restore matches on - ids are made per library, this tag is not
                                              combo.get("id") or name),
                    })
                    text = str(combo.get("note", "") or "").strip()
                    if text:
                        pages[notes.note_key(self.NOTES_SECTION,
                                             mat.mat_id)] = [
                            {"t": "text", "text": text}]
                    self._append_record(mat)
                    seeded += 1
            if not seeded:
                return  # def files unreachable this run: leave the marker off and retry next launch
            if not self.save():  # the mark is PERMANENT, so it is never made for a failed save
                debug.event("gradient", "curated seed not marked - save() returned False")
                return
            if not all(saved for saved in library_db.flush(self.preferences).values()):
                debug.event("gradient", "curated seed not marked - the save failed")
                return
            if pages:
                notes.set_notes(self.preferences, pages)  # after the rows: a comment for a palette that was not saved belongs to no row
            for cat_name in categories:
                category_model.check_add_category(cat_name)
        except Exception as exc:                        # noqa: BLE001
            debug.event("gradient", "curated palette seed failed",
                        error=str(exc))
            return
        if not library_settings.mark(self.preferences, self._SEED_MARK, seeded=seeded):
            self._seed_marker_failed = True  # a RECORD: the next open seeds again
            debug.event("gradient", "seed mark not kept", file=lib_dir)

    @staticmethod
    def _colors_of(asset) -> list:
        """The palette's colour dicts - kept in the record beside the fields Material knows."""
        colors = asset._extra.get("colors")
        return colors if isinstance(colors, list) else []

    @staticmethod
    def _ramp_of(asset) -> dict:
        ramp = asset._extra.get("ramp")
        return ramp if isinstance(ramp, dict) else {}

    def entry(self, row: int) -> dict | None:
        """A read-only copy of one palette; edits go through the record API."""
        if not 0 <= row < len(self._assets):
            return None
        asset = self._assets[row]
        return {
            "name": asset.name,
            "categories": list(asset.categories),
            "colors": self._colors_of(asset),
            "ramp": self._ramp_of(asset),
        }

    def user_categories(self) -> list:
        """The categories the save dialog lists, with neither spelling of All (`_All`, `All`)."""
        return [name for name in category.stored_order(self._doc())
                if isinstance(name, str) and not category.is_all(name)]

    def set_user_category(self, rows: list, category_name: str) -> int:
        """Move the given rows' palettes to a category; returns how many moved."""
        category_name = (category_name or "").strip()
        if not category_name:
            return 0
        moved = []
        for row in rows:
            if not 0 <= row < len(self._assets):
                continue
            asset = self._assets[row]
            if asset.categories != [category_name]:
                asset.categories = [category_name]    # one name, its commas included
                moved.append(asset)
        if moved:
            self._saved_rows_changed(moved)
        return len(moved)

    def add_user_gradient(self, name: str, category_name: str,
                          ramp_data: dict, tags: str = "") -> None:
        """Register a saved ramp, its colours derived from the values; `tags` is comma-separated."""
        colors = []
        for value in ramp_data.get("values", []):
            hex_color = "#%02x%02x%02x" % tuple(
                max(0, min(255, round(c * 255))) for c in value[:3]
            )
            colors.append({"name": hex_color, "hex": hex_color})
        category_name = (category_name or "").strip()
        mat = material.Material()
        mat.set_data((name or "Gradient").strip() or "Gradient",
                     category_name, self.sanitize_tags(tags or ""),
                     False, "")
        mat._extra = {"colors": colors, "ramp": ramp_data}
        self._append_record(mat)
        if not self.save():  # nothing was saved, so the row is removed from the view too
            self._take_back_refused_append(mat)
            debug.alert(
                messages.PALETTE_NOT_SAVED % (name or "this palette"),
                key="colors-not-saved")
            return
        self.row_changed(0)

    def _owned_paths(self, mat_id) -> list:
        """A palette has at most one file, its captured picture: the rest is stored inline."""
        try:
            return list(self.asset_files(mat_id).values())
        except hostos.PathEscape:
            return []

    def _report_refused_delete(self, asset) -> None:
        """A palette's failed delete, reported with the Colors section's message."""
        debug.alert(
            messages.PALETTE_NOT_DELETED % (asset.name or "That palette"),
            key="colors-delete-refused")

    def _tile_icon_saved(self, row: int, spec, stored: bool) -> bool:
        """No PNG is written for a palette; the row's paths are refreshed, as a Capture face reads a file."""
        self._add_thumb_paths(row, base_changed=False)    # also repaints the tile
        return stored

    def rerender_tile_icons(self) -> int:
        """Repaint every palette showing an icon; AssetLibrary's would write PNGs a palette never has."""
        return tile_icons.repaint_custom(self)

    @staticmethod
    def _is_banded(colors: list, ramp: dict) -> bool:
        """True when the palette paints as bands: every basis Constant, or no ramp yet."""
        bases = ramp.get("bases") or []
        return bool(colors) and (
            not bases or all(b == "Constant" for b in bases)
        )

    def _swatch_key(self, row: int):
        """The swatch's cache key, built from its content, so any edit makes a new key."""
        asset = self._assets[row]
        colors = self._colors_of(asset)
        ramp = self._ramp_of(asset)
        hexes = tuple(c.get("hex") for c in colors if isinstance(c, dict))
        bases = tuple(ramp.get("bases") or ())
        stops = tuple(round(float(k), 6) for k in (ramp.get("keys") or ())  # positions too: same colours in different places paint differently
                      if isinstance(k, (int, float)))
        icon = self.tile_icon(row)
        weight = (tile_icons.stroke_for(self.preferences)
                  if tile_icons.is_custom(icon) else 0)
        icon_key = (tile_icons.face_for(self, row), icon.get("name"), icon.get("bg"),
                    icon.get("ink"), weight)
        return ("grad", self._is_banded(colors, ramp), hexes, bases,
                stops, icon_key, THUMB_SIZE)

    def _decoration_image(self, row: int):
        """The painted swatch, its capture, or its chosen icon."""
        face = tile_icons.face_for(self, row)
        if face == "image":    # a capture replaces the swatch; thumbnails.engine loads its file
            held = self._thumb_key(row)
            captured = thumbnails.engine.request_file(held, self._mat_paths[row])
            if captured is not None:
                return captured
            if not thumbnails.engine.is_missing(held):
                return None    # still being read: the tile repaints when it is loaded
        key = self._swatch_key(row)
        image = thumbnails.engine.peek(key)
        if image is not None:
            return image
        if face != "image":
            face = self._missing_thumb_image(row)
            if face is not None:
                thumbnails.engine.deposit(key, face)
                return face
        image = self.preview_image(row)
        thumbnails.engine.deposit(key, image)
        return image

    def preview_image(self, row: int):
        """The painted swatch, for the tile and the Customize preview."""
        if not 0 <= row < len(self._assets):
            return None
        asset = self._assets[row]
        return paint_swatch(self._colors_of(asset), self._ramp_of(asset))

    @staticmethod
    def _paint_ramp(painter: QtGui.QPainter, ramp_data: dict) -> None:
        """A saved ramp left to right: hard bands when all constant-basis, else a linear gradient."""
        keys = list(ramp_data.get("keys") or [])
        values = list(ramp_data.get("values") or [])
        bases = ramp_data.get("bases", [])
        width = min(len(keys), len(values))    # the length both lists share, as data_to_ramp ▸r/ramp-and-walk-edges
        keys, values = keys[:width], values[:width]
        if not width:
            painter.fillRect(0, 0, THUMB_SIZE, THUMB_SIZE,
                             QtGui.QColor(EMPTY_SWATCH))
            return
        if all(b == "Constant" for b in bases):
            edges = list(keys) + [1.0]
            for i, value in enumerate(values):
                if not _has_rgb(value):
                    continue
                x0 = max(0.0, min(1.0, edges[i])) * THUMB_SIZE
                x1 = max(0.0, min(1.0, edges[i + 1])) * THUMB_SIZE
                color = QtGui.QColor.fromRgbF(*value[:3])
                painter.fillRect(
                    QtCore.QRectF(x0, 0, x1 - x0 + 1, THUMB_SIZE), color)
            return
        stops = [(key, value) for key, value in zip(keys, values) if _has_rgb(value)]
        if not stops:
            return
        gradient = QtGui.QLinearGradient(0, 0, THUMB_SIZE, 0)
        for key, value in stops:
            gradient.setColorAt(
                max(0.0, min(1.0, key)), QtGui.QColor.fromRgbF(*value[:3])
            )
        painter.fillRect(0, 0, THUMB_SIZE, THUMB_SIZE,
                         QtGui.QBrush(gradient))

    def row_data(self, row, role):
        asset = self._assets[row]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return asset.name or "Gradient"
        if role in (self.RendererLabelRole, self.RendererRole):
            return "Gradient"  # the KIND of thing; its set or size is shown in the Category column
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            return ", ".join(
                str(c.get("name", "")) for c in self._colors_of(asset))
        if role == self.CategoryLabelRole:
            cats = asset.categories
            return cats[0] if cats else "Uncategorized"
        return super().row_data(row, role)


class GradientFilterProxyModel(multifilterproxy_model.MultiFilterProxyModel):
    """MultiFilterProxyModel plus a palette-size filter and a search that matches colour names."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._size_filter = None

    def set_size_filter(self, bounds) -> None:
        """Show palettes with (fewest, most) colours, `most` None for no limit; None turns it off."""
        if bounds == self._size_filter:
            return
        self._size_filter = bounds
        self.refilter()

    def _name_matches(self, needle: str, index) -> bool:
        if super()._name_matches(needle, index):
            return True
        entry = self.sourceModel().entry(index.row()) or {}
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
