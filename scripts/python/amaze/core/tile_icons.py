"""Tile faces: Preview, Generic, or a custom icon written beside the render ▸r/tile-faces"""

from __future__ import annotations

import os
import re
from collections import OrderedDict

from PySide6 import QtCore, QtGui

import amaze
from amaze import amazetheme
from amaze.core import library_files, material

ICON_DIR = amaze.package_file("ui", "feather")  # the icon set, joined by amaze.package_file

CANVAS = 512
ICON_SCALE = 12.5  # 24-unit grid on CANVAS: 250px of ink; a change re-renders every tile
STROKE_UNITS = 0.8  # the thin stroke - the one value chosen by eye rather than measured
FEATHER_STROKE_UNITS = 2.0  # Feather's own default weight, the other option of the UI preference
INK_SPAN = 250.0      # no icon's ink spans more pixels than this on a 512 tile

INKS = {  # ink colours, stored by token name; light is for dark backgrounds
    "dark": "#262626",
    "light": "#d0ced0",
}
DEFAULT_INK = "dark"


def ink_colour(token: str) -> str:
    """Hex for an ink token; dark for any unknown token."""
    return INKS.get(str(token or "").strip().lower(), INKS[DEFAULT_INK])


FACES = ("image", "generic", "custom")    # the Icon menu, in its order ▸r/tile-faces
PLAIN_FACES = ("image", "generic")    # stored as {"face": ...}: no icon to compose


def is_custom(spec) -> bool:
    """Whether a stored choice is a custom icon - the one face with a composed picture."""
    return bool((spec or {}).get("name"))


def face_of(spec, default: str = "image", can_preview: bool = True) -> str:
    """The face a stored choice shows, one of FACES; the row's default when nothing is stored."""
    if is_custom(spec):
        return "custom"
    face = (spec or {}).get("face")
    face = face if face in PLAIN_FACES else default
    if face == "image" and not can_preview:
        return "generic"
    return face


def face_for(model, row: int) -> str:
    """`face_of` for one row: its stored choice, its default face, whether it can preview."""
    return face_of(model.tile_icon(row), model.default_face(row), model.can_preview(row))


def choice_for(model, row: int, spec) -> dict:
    """What to store for a row: the choice cleaned, and {} when it shows the row's own default."""
    spec = normalise(spec)
    default = model.default_face(row)
    if not is_custom(spec) and face_of(spec, default, model.can_preview(row)) == default:
        return {}
    return spec


def on_ground(image):
    """`image` over the tile ground, opaque; the generic art is drawn without a ground of its own."""
    shown = QtGui.QImage(image.size(), QtGui.QImage.Format.Format_RGB32)
    shown.fill(QtGui.QColor(amazetheme.TILE_GROUND))
    painter = QtGui.QPainter(shown)
    try:
        painter.drawImage(0, 0, image)
    finally:
        painter.end()
    return shown


_generic_images = {}    # {(art, the drawn image's cache key): the image on the tile ground}


def generic_image(art: str):
    """A generic face: the T frame's `face ▸ <art>.svg` on the tile ground, or None for no art."""
    from amaze.helpers import ui_helpers
    drawn = ui_helpers.svg_image(art + ".svg") if art else None
    if drawn is None:
        return None
    key = (art, drawn.cacheKey())    # a redrawn SVG, after `forget_svg_images`, is another key
    if key not in _generic_images:
        _generic_images[key] = on_ground(drawn)
    return _generic_images[key]


def repaint_custom(model) -> int:
    """Repaint every row of `model` showing a custom icon, for a model that composes in memory."""
    rows = [row for row in range(model.rowCount())
            if is_custom(model.tile_icon(row))]
    for row in rows:
        model.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])
    return len(rows)

PRESETS = (  # four presets beside the picker chip, the D02 swatches ▸p/one-design-document
    ("Red", "#e0523a"),
    ("Green", "#a4c18a"),
    ("Amber", "#f6ca6d"),
    ("Blue", "#b0d1df"),
)

_COMPOSED_MAX_BYTES = 64 * 1024 * 1024  # the LRU of (name, bg, size, stroke, ink) -> QImage, in bytes
_COMPOSED_MAX = 240  # and in entries
_composed: "OrderedDict" = OrderedDict()
_composed_bytes = 0


def _composed_cost(image) -> int:
    """Bytes an entry occupies. A False (no such icon) marker counts as 0."""
    try:
        return int(image.sizeInBytes()) if image else 0
    except Exception:                                   # noqa: BLE001
        return 0
_names: list = []
_fits: dict = {}


def icon_names() -> list:
    """Every icon available, sorted - cached after the first successful read."""
    global _names
    if not _names:
        try:
            _names = sorted(
                entry[:-4] for entry in os.listdir(ICON_DIR)
                if entry.endswith(".svg")
            )
        except OSError:
            _names = []
    return _names


def icon_path(name: str) -> str:
    return os.path.join(ICON_DIR, str(name) + ".svg")


def _icon_body(name: str) -> str:
    """The drawing commands inside a Feather SVG, without its own <svg> wrapper."""
    try:
        with open(icon_path(name), encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ""
    match = re.search(r"<svg[^>]*>(.*)</svg>", text, re.S)
    return match.group(1).strip() if match else ""


def _ink_span_px(body: str, scale: float, stroke: float) -> float:
    """How wide this icon's path draws in pixels at `scale`, stroke excluded, measured by rendering."""
    svg = (
        '<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">'
        '<g transform="translate(%s %s) scale(%s)" fill="none" '
        'stroke="#000000" stroke-width="%s" stroke-linecap="round" '
        'stroke-linejoin="round">%s</g></svg>'
        % (CANVAS, CANVAS, CANVAS / 2.0 - 12.0 * scale,
           CANVAS / 2.0 - 12.0 * scale, scale, stroke, body)
    )
    from amaze.helpers import ui_helpers
    image = QtGui.QImage(CANVAS, CANVAS, QtGui.QImage.Format.Format_ARGB32)
    if not ui_helpers.paint_svg(image, svg.encode("utf-8")):
        return 0.0
    box = QtGui.QRegion(  # createAlphaMask, never createMaskFromColor, whose polarity is inverted
        QtGui.QBitmap.fromImage(image.createAlphaMask())
    ).boundingRect()
    if box.isEmpty():
        return 0.0
    return max(box.width(), box.height()) - stroke * scale


def _fit(name: str, stroke_units: float):
    """(scale, stroke) for this icon: the template's, both scaled together to fit INK_SPAN."""
    key = (name, float(stroke_units))
    cached = _fits.get(key)
    if cached is not None:
        return cached
    body = _icon_body(name)
    fit = (ICON_SCALE, float(stroke_units))
    if body:
        span = _ink_span_px(body, ICON_SCALE, stroke_units)
        if span > INK_SPAN:
            factor = INK_SPAN / span
            fit = (ICON_SCALE * factor, float(stroke_units) / factor)
    _fits[key] = fit
    return fit


def compose_svg(name: str, background: str, stroke_units: float = 0.0,
                ink: str = DEFAULT_INK) -> str:
    """The template SVG text, rebuilt around one icon."""
    body = _icon_body(name)
    if not body:
        return ""
    scale, stroke = _fit(name, stroke_units or STROKE_UNITS)
    offset = CANVAS / 2.0 - 12.0 * scale  # centres the 24-unit grid on the canvas
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">\n'
        '  <path fill="%s" fill-rule="evenodd" stroke="none" '
        'd="M 0 %d L %d %d L %d 0 L 0 0 Z"/>\n'
        '  <g transform="translate(%s %s) scale(%s)" fill="none" '
        'stroke="%s" stroke-width="%s" stroke-linecap="round" '
        'stroke-linejoin="round">\n%s\n  </g>\n</svg>\n'
        % (CANVAS, CANVAS, background,
           CANVAS, CANVAS, CANVAS, CANVAS,
           offset, offset, scale,
           ink_colour(ink), stroke, body)
    )


def compose(name: str, background: str, size: int = CANVAS,
            stroke_units: float = 0.0, ink: str = DEFAULT_INK, keep: bool = True):
    """The finished tile image, or None if the icon does not exist; `keep` False leaves it uncached."""
    stroke_units = float(stroke_units or STROKE_UNITS)
    key = (str(name), str(background), int(size), stroke_units, str(ink))
    cached = _composed.get(key) if keep else None
    if cached is not None:
        _composed.move_to_end(key)      # LRU: a cache hit becomes the most recent
        return cached or None
    svg = compose_svg(name, background, stroke_units, ink)
    image = None
    if svg:
        from amaze.helpers import ui_helpers
        drawn = QtGui.QImage(int(size), int(size), QtGui.QImage.Format.Format_ARGB32)
        if ui_helpers.paint_svg(drawn, svg.encode("utf-8")):
            image = drawn
    if not keep:
        return image
    global _composed_bytes
    entry = image if image is not None else False
    _composed[key] = entry
    _composed_bytes += _composed_cost(entry)
    while _composed and (
        _composed_bytes > _COMPOSED_MAX_BYTES
        or len(_composed) > _COMPOSED_MAX
    ):
        _old_key, old_entry = _composed.popitem(last=False)   # least recent
        _composed_bytes -= _composed_cost(old_entry)
    return image


def is_valid_colour(value: str) -> bool:
    """True for a colour the composer can use; check before storing one."""
    return bool(value) and QtGui.QColor.isValidColorName(str(value))


def normalise(spec) -> dict:
    """A stored icon choice as {"name", "bg", "ink"} or {}; unknown fields are kept."""
    if not isinstance(spec, dict):
        return {}
    name = str(spec.get("name", "") or "").strip()
    background = str(spec.get("bg", "") or "").strip()
    if not name or name not in icon_names():
        if spec.get("face") in PLAIN_FACES:    # a face choice: no icon to clean
            return {k: v for k, v in spec.items() if k not in ("name", "bg", "ink")}
        return {}
    if not is_valid_colour(background):
        background = PRESETS[0][1]
    ink = str(spec.get("ink", "") or "").strip().lower()
    if ink not in INKS:
        ink = DEFAULT_INK
    record = {k: v for k, v in spec.items()
              if k not in ("name", "bg", "ink")}
    record.update({"name": name, "bg": background, "ink": ink})
    return record


def stroke_for(preferences) -> float:
    """The line weight from Preferences - UI: the thin stroke or Feather's own."""
    try:
        weight = str(getattr(preferences, "icon_line_weight", "") or "")
    except Exception:                                       # noqa: BLE001
        weight = ""
    return FEATHER_STROKE_UNITS if weight == "feather" else STROKE_UNITS


def thumbnail_path(preferences, asset_id: str, section: str, name: str = "") -> str:
    """The asset's one picture, `<id>.png` in its folder, render or capture; `name` names a new one."""
    return material.payload_path(preferences, asset_id, library_files.PICTURE_SUFFIX, section, name)


def tile_read_path(preferences, asset_id: str, section: str) -> str:
    """A tile's picture path by a plain join; empty for an unsafe id, which a join cannot contain."""
    if not material.is_safe_asset_id(asset_id):
        return ""
    return os.path.join(material.listed_dir(preferences.dir, section, asset_id),
                        str(asset_id) + library_files.PICTURE_SUFFIX)


def render_size(preferences) -> int:
    """The pixel size every icon composes at: the preference when it parses, else CANVAS."""
    try:
        return int(getattr(preferences, "rendersize", CANVAS)) or CANVAS
    except (TypeError, ValueError):
        return CANVAS


def compose_for(preferences, spec, keep: bool = True):
    """One normalised spec composed in memory at the preferences' size, for every section."""
    spec = normalise(spec)
    if not is_custom(spec):
        return None
    return compose(spec["name"], spec["bg"], render_size(preferences),
                   stroke_for(preferences), spec["ink"], keep)


def custom_stamp(preferences, spec) -> tuple:
    """What a custom icon is composed from, so a changed choice, weight or size is a new picture."""
    spec = normalise(spec)
    return ("custom", spec.get("name"), spec.get("bg"), spec.get("ink"), stroke_for(preferences),
            render_size(preferences))


def forget_composed() -> None:
    """Drop the composed-image caches; call when the line weight changes."""
    global _composed_bytes
    _composed.clear()
    _composed_bytes = 0
    _fits.clear()


SECTION = "icons"    # in each database: a tile's chosen face, by asset id or file key


def _document(preferences, database: str):
    from amaze.core import library_db
    return library_db.document(preferences, database)


def override_for(preferences, key: str, database: str) -> dict:
    """The face chosen for one tile of `database`, {} for none."""
    return stored_choice(_document(preferences, database).get(SECTION, str(key)))


def stored_choice(found) -> dict:
    """The choice one entry of a database's `icons` holds, {} for none."""
    from amaze.core import documents
    if not isinstance(found, dict):
        return {}
    return normalise({field: value for field, value in found.items()
                      if field not in (documents.BY, documents.AT)})    # the stamps are set by documents.py


def set_override(preferences, key: str, spec, database: str) -> bool:
    """Store one tile's face, or forget it with an empty spec."""
    return set_overrides(preferences, {key: spec}, database)[str(key)]


def set_overrides(preferences, specs: dict, database: str) -> dict:
    """`set_override` for many tiles as one change; {key: whether the database now holds that choice}."""
    from amaze.core import library_db
    if not library_db.accepts(preferences, database):
        return {str(key): False for key in specs}
    held = _document(preferences, database)
    with library_db.library_for(preferences).holding():
        for key, spec in specs.items():
            chosen = normalise(spec)
            if chosen:
                held.put(SECTION, str(key), chosen)
            else:
                held.drop(SECTION, str(key))
    library_db.changed(preferences, database)    # the panel timer saves it with the rest of the user's action
    return {str(key): override_for(preferences, key, database) == normalise(spec)
            for key, spec in specs.items()}
