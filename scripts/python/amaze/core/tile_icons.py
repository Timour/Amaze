"""Tile faces: Preview, Generic, or a custom icon written beside the render ▸r/tile-faces"""

from __future__ import annotations

import os
import re
from collections import OrderedDict

from PySide6 import QtCore, QtGui

import amaze
from amaze import messages
from amaze.core import debug, keyed_store, material
from amaze.helpers import hostos

ICON_DIR = amaze.package_file("ui", "feather")  # the icon set, through the package's one path join

CANVAS = 512
ICON_SCALE = 12.5  # 24-unit grid on CANVAS: 250px of ink; a change re-renders every tile
STROKE_UNITS = 0.8  # the thin stroke - the one number that is a LOOK rather than a measurement
FEATHER_STROKE_UNITS = 2.0  # Feather's own default weight, the other half of the Look preference
INK_SPAN = 250.0      # no icon's ink spans more pixels than this on a 512 tile

INKS = {  # ink colours, stored by token name; light is for dark backgrounds
    "dark": "#262626",
    "light": "#d0ced0",
}
DEFAULT_INK = "dark"


def ink_colour(token: str) -> str:
    """Hex for an ink token, falling back to dark for anything odd."""
    return INKS.get(str(token or "").strip().lower(), INKS[DEFAULT_INK])


FACES = ("preview", "capture", "generic", "custom")    # the Icon menu, in its order ▸r/tile-faces
PLAIN_FACES = ("preview", "capture", "generic")    # stored as {"face": ...}: no icon to compose


def is_custom(spec) -> bool:
    """Whether a stored choice is a custom icon - the one face with a composed picture."""
    return bool((spec or {}).get("name"))


def face_of(spec, default: str = "preview", can_preview: bool = True) -> str:
    """The face a stored choice shows, one of FACES; the row's default when nothing is stored."""
    if is_custom(spec):
        return "custom"
    face = (spec or {}).get("face") or default
    if face == "preview" and not can_preview:
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


def generic_image(art: str):
    """A generic face: the T frame's `face ▸ <art>.svg`, exported whole, or None for no art."""
    from amaze.helpers import ui_helpers
    return ui_helpers.svg_image(art + ".svg") if art else None


def chosen_image(model, row: int):
    """A row's face when it shows no preview: its custom icon composed in memory, else generic."""
    spec = model.tile_icon(row)
    if is_custom(spec):
        return compose_for(model.preferences, spec)    # in memory: painting never writes
    return generic_image(model.tile_face_art(row))


def repaint_custom(model) -> int:
    """Repaint every row of `model` wearing a custom icon, for a model that composes in memory."""
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
    """Bytes an entry occupies. A False (no such icon) marker is free."""
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
    """(scale, stroke) for this icon: the template's, both shrunk together past INK_SPAN."""
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
            stroke_units: float = 0.0, ink: str = DEFAULT_INK):
    """The finished tile image, or None if the icon does not exist."""
    stroke_units = float(stroke_units or STROKE_UNITS)
    key = (str(name), str(background), int(size), stroke_units, str(ink))
    cached = _composed.get(key)
    if cached is not None:
        _composed.move_to_end(key)      # LRU: a hit is not old
        return cached or None
    svg = compose_svg(name, background, stroke_units, ink)
    image = None
    if svg:
        from amaze.helpers import ui_helpers
        drawn = QtGui.QImage(int(size), int(size), QtGui.QImage.Format.Format_ARGB32)
        if ui_helpers.paint_svg(drawn, svg.encode("utf-8")):
            image = drawn
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


def write(path: str, name: str, background: str, size: int = CANVAS,
          stroke_units: float = 0.0, ink: str = DEFAULT_INK) -> bool:
    """Compose and save; False, logged, on any failure, and never a raise."""
    image = compose(name, background, size, stroke_units, ink)
    if image is None:
        debug.event("icons", "no such tile icon", icon=name)  # an event: the tile keeps its icon
        return False
    why = ""  # the OSError cause when there is one; Qt's False names none ▸r/failed-write
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not image.save(path, "PNG"):
            debug.event("icons", "could not write the tile icon image",
                        path=path)
            why = "the picture could not be written."
    except OSError as exc:
        _cause, why = hostos.why_failed(exc, path)
        debug.event("icons", "could not write the tile icon image",
                    path=path, error=str(exc))
    if why:
        debug.alert(
            messages.TILE_ICON_NOT_SAVED % why,
            key="icons-not-saved")
        return False
    return True


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
    """The line weight from Preferences - Look: the thin stroke or Feather's own."""
    try:
        weight = str(getattr(preferences, "icon_line_weight", "") or "")
    except Exception:                                       # noqa: BLE001
        weight = ""
    return FEATHER_STROKE_UNITS if weight == "feather" else STROKE_UNITS


def _image_parts(preferences, asset_id, icon: bool) -> tuple:
    """(image folder, file name) of a render or its icon - the one spelling every door below joins."""
    return (os.path.join(preferences.dir, preferences.img_dir),
            str(asset_id) + ("_icon" if icon else "") + preferences.img_ext)


def thumbnail_path(preferences, asset_id: str) -> str:
    """`<library>/img/<id>.png`, the one composition of a thumbnail path, contained to the library."""
    return hostos.contained_join(*_image_parts(preferences, asset_id, False))


def icon_image_path(preferences, asset_id: str) -> str:
    """A tile's composed icon path, beside its thumbnail with a suffix, contained like it."""
    return hostos.contained_join(*_image_parts(preferences, asset_id, True))


def tile_read_path(preferences, asset_id: str, icon: bool) -> str:
    """A tile's image path as the two above compose it; "" for an unsafe id. No realpath."""
    if not material.is_safe_asset_id(asset_id):
        return ""
    return os.path.join(*_image_parts(preferences, asset_id, icon))


def render_size(preferences) -> int:
    """The pixel size every icon composes at: the preference when it parses, else CANVAS."""
    try:
        return int(getattr(preferences, "rendersize", CANVAS)) or CANVAS
    except (TypeError, ValueError):
        return CANVAS


def compose_for(preferences, spec):
    """One normalised spec composed in memory at the preferences' size, for every section."""
    spec = normalise(spec)
    if not is_custom(spec):
        return None
    return compose(spec["name"], spec["bg"], render_size(preferences),
                   stroke_for(preferences), spec["ink"])


def render_for(preferences, asset_id: str, spec) -> str:
    """Compose an asset's icon to disk: its path, or "" with no icon; the caller deletes cleared ones."""
    spec = normalise(spec)
    if not is_custom(spec):
        return ""
    path = icon_image_path(preferences, asset_id)
    if not write(path, spec["name"], spec["bg"], render_size(preferences),
                 stroke_for(preferences), spec["ink"]):
        return ""
    return path


def clear_for(preferences, asset_id: str) -> None:
    """Remove a composed icon file. Missing is success."""
    path = icon_image_path(preferences, asset_id)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        debug.event("icons", "composed icon not removed", error=str(exc))


def forget_composed() -> None:
    """Drop the composed-image caches; call when the line weight changes."""
    global _composed_bytes
    _composed.clear()
    _composed_bytes = 0
    _fits.clear()


OVERRIDES_FILE = "icons.json"  # kept by the keyed-store engine

SPEC = keyed_store.bind(OVERRIDES_FILE, normalise)  # every tile's icon, by asset id or file path


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def override_for(preferences, key: str) -> dict:
    return _store(preferences).get(key)


def set_override(preferences, key: str, spec) -> bool:
    """Store one key's icon, or forget it with an empty spec; the engine reports failures."""
    return bool(_store(preferences).set(key, spec))


def set_overrides(preferences, specs: dict) -> dict:
    """`set_override` for many keys in ONE write; {key: whether the store now holds that choice}."""
    store = _store(preferences)
    written = store.update(specs)
    if written:
        return dict.fromkeys(specs, True)
    held = written.reason != keyed_store.REASON_NO_USER    # as `set` answers: an unchanged key holds
    return {key: held and store.get(key) == normalise(spec)
            for key, spec in specs.items()}
