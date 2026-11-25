"""Models for the Colors section over colors.json; curated sets are added once as user gradients."""

import functools
import json

from PySide6 import QtCore, QtGui

import amaze
from amaze.core import category
from amaze.core import category_list
from amaze.core import debug
from amaze.core import library
from amaze.core import library_files
from amaze.core import material
from amaze.core import multifilterproxy_model
from amaze.core import tile_icons
from amaze import messages

THUMB_SIZE = 256
EMPTY_SWATCH = "#444444"    # the background where a palette paints nothing

BASIS_LABELS = {    # a stored basis name -> its label in a ramp's interpolation menu, where they differ
    "CatmullRom": "Catmull-Rom",
    "MonotoneCubic": "Monotone Cubic",
    "BSpline": "B-Spline",
}


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

    @staticmethod
    def _asset_from_row(row: dict):
        """A palette is stored as a `Material`, with `colors` and `ramp` among its extra keys."""
        mat = material.Material.from_dict(dict(row))
        if not str(row.get("date") or ""):
            mat._date = ""  # a stored row without a date keeps an empty one, rather than Material filling in today's
        return mat

    _SEED_MARK = "gradient_seed_v1"  # in the library's marks; bump when the seed contents change

    def seed_curated_palettes(self, category_model) -> int:
        """Every curated combination added once per library as a palette; how many were added."""
        from amaze.core import notes
        records, pages = [], {}
        try:
            for curated in CURATED_SETS:
                with open(_def_path(curated["file"]), "r", encoding="utf-8-sig") as f:
                    combos = json.load(f).get("combinations", [])
                for combo in (combo for combo in combos if combo.get("colors")):
                    colors = combo["colors"]
                    name = combo.get("name") or "Combination %s" % combo.get("id")
                    mat = self._asset_from_row({
                        "name": name,
                        "categories": ["%s %s Color%s" % (curated["label"], len(colors),
                                                          "" if len(colors) == 1 else "s")],
                        "colors": colors,
                        "ramp": _palette_ramp_data(colors),
                        "curated": "%s/%s" % (curated["key"], combo.get("id") or name),
                    })    # `curated`: the stable id a restore matches on, the same in every library
                    text = str(combo.get("note", "") or "").strip()
                    if text:
                        pages[notes.note_key(self.NOTES_SECTION, mat.mat_id)] = [
                            {"t": "text", "text": text}]
                    records.append(mat)
        except (OSError, ValueError, KeyError, TypeError) as exc:    # never blocks the open
            debug.event("gradient", "curated palettes not read", error=str(exc))
            return 0
        return self.add_shipped(self._SEED_MARK, records, pages, category_model)

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

    def set_interpolation(self, row: int, basis: str) -> bool:
        """Put every key of one palette's ramp on `basis` in one save; the user is told of a refusal."""
        if not self.takes_edits():
            return False
        asset = self._changeable(row)
        if asset is None:
            return False
        ramp = self._ramp_of(asset) or _palette_ramp_data(self._colors_of(asset))    # no ramp: its bands
        bases = [basis] * len(ramp.get("keys") or ())
        if ramp.get("bases") == bases:
            return False
        asset._extra["ramp"] = dict(ramp, bases=bases)    # keys and colours stay where they are
        self._edited(asset, save=True)
        return True

    def user_categories(self) -> list:
        """(key, name as shown) of each category, in the sidebar's order: what the save lists."""
        held = self._doc()
        return [(key, category_list.display_name(held.get(category.SECTION, key).get("name") or ""))
                for key in category.stored_order(held)[1:]]

    def add_user_gradient(self, name: str, category_name: str,
                          ramp_data: dict, tags: str = "") -> None:
        """Register a saved ramp, its colours derived from the values; `tags` is comma-separated."""
        colors = []
        for value in ramp_data.get("values", []):
            hex_color = "#%02x%02x%02x" % tuple(
                max(0, min(255, round(c * 255))) for c in value[:3]
            )
            colors.append({"name": hex_color, "hex": hex_color})
        mat = material.Material()
        mat.set_data((name or "Gradient").strip() or "Gradient", category_name, tags, False, "")
        mat._extra = {"colors": colors, "ramp": ramp_data}
        if not self.add_saved(mat):    # nothing was saved: no row is shown
            debug.refuse(messages.ASSET_NOT_SAVED_DATABASE_REFUSED % mat.name)

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

    @classmethod
    def interpolation(cls, colors: list, ramp: dict) -> str:
        """Constant when it paints as bands, else the one basis by its menu label, Mixed for several."""
        if cls._is_banded(colors, ramp):
            return "Constant"
        bases = {str(basis) for basis in ramp.get("bases") or ()}
        if len(bases) != 1:
            return "Mixed" if bases else ""
        basis = bases.pop()
        return BASIS_LABELS.get(basis, basis)    # Constant, Linear, Bezier, Hermite: the same in both

    def _info_facts(self, row: int, asset) -> tuple:
        """Colors, Values as upper-case hex, and Interpolation."""
        colors = self._colors_of(asset)
        hexes = [str(colour["hex"]).upper() for colour in colors
                 if isinstance(colour, dict) and colour.get("hex")]
        return [("Colors", str(len(colors)) if colors else ""),
                ("Values", "  ".join(hexes)),
                ("Interpolation", self.interpolation(colors, self._ramp_of(asset)))], None

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

    def painted_preview(self, row: int):
        """The palette's swatch, painted when it has no capture."""
        return self._swatch_key(row), functools.partial(self.preview_image, row)

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
            return self.category_name(row) or "Uncategorized"
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
