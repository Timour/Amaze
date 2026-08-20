"""Tile icons: a chosen Feather symbol on a chosen background colour for any tile with no picture to render - composed from ui/icon_template.svg's measured geometry (24-unit grid at scale 12.5 on a 512 canvas = 250px ink, 0.8-grid-unit stroke) and written as a normal PNG BESIDE the rendered thumbnail (`<id>_icon.png`, never over it), so the thumbnail engine, LRU cache, list mode and drag previews need no special case and clearing an icon brings the render back."""

from __future__ import annotations

import os
import re
from collections import OrderedDict

from PySide6 import QtCore, QtGui, QtSvg

from amaze.core import debug, keyed_store
from amaze.helpers import hostos

ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "ui", "feather")  # the icon set, relative to the package

CANVAS = 512
ICON_SCALE = 12.5  # straight from the template - change these and every existing tile silently re-renders differently, so they are constants, not preferences
STROKE_UNITS = 0.8  # the template's thin stroke - the one number that is a LOOK rather than a measurement
FEATHER_STROKE_UNITS = 2.0  # Feather's own default weight, the other half of the Look preference
INK_SPAN = 250.0      # the rule the numbers above satisfy: no icon's ink past this on a 512 tile, asserted by the tests against rendered pixels (Feather's 20 drawn units at ICON_SCALE)

INKS = {  # ink colours stored as TOKENS, not hex: re-tuning either one re-renders every tile that uses it instead of stranding the old literal; light exists for dark backgrounds
    "dark": "#262626",
    "light": "#d0ced0",
}
DEFAULT_INK = "dark"


def ink_colour(token: str) -> str:
    """Hex for an ink token, falling back to dark for anything odd."""
    return INKS.get(str(token or "").strip().lower(), INKS[DEFAULT_INK])

PRESETS = (  # four presets plus Custom (the colour picker); deliberately provisional - a palette is only judged against real tiles at real sizes, so these are placed to be tuned
    ("Salmon", "#ef8878"),
    ("Mint", "#4af2a1"),
    ("Sky", "#5cc9f5"),
    ("Sand", "#e2b148"),
)

_COMPOSED_MAX_BYTES = 64 * 1024 * 1024  # (name, bg, size, stroke) -> QImage, capped in BYTES not entries: 240 entries measured 63MB at rendersize 256, 252MB at 512, 1007MB at 1024 - "a gigabyte" was literal
_COMPOSED_MAX = 240  # a COUNT ceiling too - tiny icons must not grow an unbounded dict inside the byte budget; LRU not FIFO, because insertion-order eviction threw the hottest icons first and every repaint re-composed them (0.38ms at 256, 1.37ms at 1024, per tile)
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
    """Every icon available, sorted. Read from disk once."""
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
    """The drawing commands inside a Feather SVG, without its own wrapper - the wrapper's 24px size and 2-unit stroke are what this module replaces with the template's."""
    try:
        with open(icon_path(name), encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ""
    match = re.search(r"<svg[^>]*>(.*)</svg>", text, re.S)
    return match.group(1).strip() if match else ""


def _ink_span_px(body: str, scale: float, stroke: float) -> float:
    """How wide this icon actually draws in pixels at a given scale - its PATH extent with the stroke taken back off, measured by rendering because a path's bounding box is not in the file; Feather spans 20 units except the "-off" variants' corner-to-corner 22 (research.md ▸ Qt image measurement)."""
    svg = (
        '<svg viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg">'
        '<g transform="translate(%s %s) scale(%s)" fill="none" '
        'stroke="#000000" stroke-width="%s" stroke-linecap="round" '
        'stroke-linejoin="round">%s</g></svg>'
        % (CANVAS, CANVAS, CANVAS / 2.0 - 12.0 * scale,
           CANVAS / 2.0 - 12.0 * scale, scale, stroke, body)
    )
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return 0.0
    image = QtGui.QImage(CANVAS, CANVAS, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    box = QtGui.QRegion(  # createAlphaMask, NOT createMaskFromColor - the other polarity returns the whole canvas as "ink" and silently halves every icon; verified against an exhaustive alpha scan (research.md ▸ Qt image measurement)
        QtGui.QBitmap.fromImage(image.createAlphaMask())
    ).boundingRect()
    if box.isEmpty():
        return 0.0
    return max(box.width(), box.height()) - stroke * scale


def _fit(name: str, stroke_units: float):
    """(scale, stroke) for this icon: the template's, reduced only if its ink would exceed INK_SPAN - the stroke divided by the same factor so shrunk icons keep their chosen pixel weight rather than thinning out."""
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
    """The template, rebuilt around one icon - kept as SVG text rather than painted by hand because that is what the template IS: the same document with the symbol swapped."""
    body = _icon_body(name)
    if not body:
        return ""
    scale, stroke = _fit(name, stroke_units or STROKE_UNITS)
    offset = CANVAS / 2.0 - 12.0 * scale  # the template's 106 IS "centre the 24-unit grid": half the canvas back off half the grid, derived so a fitted icon stays centred without a second constant
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
        renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
        if renderer.isValid():
            image = QtGui.QImage(
                int(size), int(size), QtGui.QImage.Format.Format_ARGB32
            )
            image.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(image)
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            renderer.render(painter)
            painter.end()
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
    """Compose and save; False (recorded in the debug log) on any failure - a tile icon is a nicety, never a reason a save fails."""
    image = compose(name, background, size, stroke_units, ink)
    if image is None:
        debug.event("icons", "no such tile icon", icon=name)  # internal failures (unknown icon, failed delete) log as events because the tile keeps the icon it had; the user-visible refusal of a store write is the keyed-store engine's report (Spec.denied_alert)
        return False
    why = ""  # one report for two failures, each saying only what it knows: the OSError path carries an errno (research.md ▸ {#r/failed-write} - a read-only FILE does not stop a write, rename asks the DIRECTORY); Qt's save answers a bare False, so that one claims no cause
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
            "Your tile icon could not be saved.\n\n"
            "Nothing else has been lost - only this icon choice. The "
            "tile keeps the icon it had.\n\n"
            "This happened because %s" % why,
            key="icons-not-saved")
        return False
    return True


def is_valid_colour(value: str) -> bool:
    """A colour the composer can actually use - checked before storing, because a bad value would otherwise reach every future compose()."""
    return bool(value) and QtGui.QColor.isValidColorName(str(value))


def normalise(spec) -> dict:
    """A stored icon choice cleaned to {"name", "bg", "ink"} or {} - anything unusable costs a fallback tile rather than the grid (this reads data a user or a future version may have written); a choice saved before ink existed gets the default it rendered with, and unknown fields ride along so a newer build's addition survives this build rewriting the entry."""
    if not isinstance(spec, dict):
        return {}
    name = str(spec.get("name", "") or "").strip()
    background = str(spec.get("bg", "") or "").strip()
    if not name or name not in icon_names():
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
    """The line weight to draw with, from Preferences - Look: two looks rather than a free number (the template's thin stroke and Feather's own default), because which reads better is only obvious at tile size, so both ship and the choice is the user's."""
    try:
        weight = str(getattr(preferences, "icon_line_weight", "") or "")
    except Exception:                                       # noqa: BLE001
        weight = ""
    return FEATHER_STROKE_UNITS if weight == "feather" else STROKE_UNITS


def thumbnail_path(preferences, asset_id: str) -> str:
    """`<library>/img/<id>.png` - the ONE composition of a library thumbnail's path (nine hand-concatenations in render/thumbs.py once disagreed with `asset_files()` whenever `prefs.dir` was assigned without its trailing separator: the render reported success while every reader looked at `<lib>/img/` and the tile read Missing Thumbnail forever); contained, like every id-derived path, because the id comes verbatim out of library.json and nothing validates it on load."""
    return hostos.contained_join(
        os.path.join(preferences.dir, preferences.img_dir),
        str(asset_id) + preferences.img_ext)


def icon_image_path(preferences, asset_id: str) -> str:
    """Where a tile's composed icon lives: beside its thumbnail with a suffix so the render underneath survives - composed exactly like `thumbnail_path` and for both of its reasons, and CONTAINED because this is the path `render_for` writes and `clear_for` runs os.remove on."""
    return hostos.contained_join(
        os.path.join(preferences.dir, preferences.img_dir),
        str(asset_id) + "_icon" + preferences.img_ext)


def render_for(preferences, asset_id: str, spec) -> str:
    """Compose an asset's icon onto disk and return the path, or "" if there is no icon to make - deleting the file when the icon is cleared is the caller's job (it knows whether a render exists)."""
    spec = normalise(spec)
    if not spec:
        return ""
    path = icon_image_path(preferences, asset_id)
    size = CANVAS
    try:
        size = int(getattr(preferences, "rendersize", CANVAS)) or CANVAS
    except (TypeError, ValueError):
        pass
    if not write(path, spec["name"], spec["bg"], size,
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
    """Drop the composed-image caches - the LOOK changed (line weight), so every remembered picture is now the wrong one."""
    global _composed_bytes
    _composed.clear()
    _composed_bytes = 0
    _fits.clear()


OVERRIDES_FILE = "icons.json"  # declared into the keyed-store engine, which IS the absent-but-known guard the file never had of its own (measured 2026-08-03: absent with no .bak tier, so the first icon ever picked was the one write with no evidence behind it)

SPEC = keyed_store.bind(OVERRIDES_FILE, normalise)  # the ONE home for EVERY tile's icon choice since schema 5 stripped the record's icon field: library assets key by asset id, File rows (no record of their own) by absolute path - so it travels with the library, and a clear here is the whole delete (library.py's set_override site says the same)


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def overrides(preferences) -> dict:
    """Every icon choice in this library - a COPY."""
    return _store(preferences).all()


def override_for(preferences, key: str) -> dict:
    return _store(preferences).get(key)


def set_override(preferences, key: str, spec) -> bool:
    """Store (or with an empty spec, forget) one key's icon - the failure reporting lives on the ENGINE (`Spec.denied_alert` + `_commit`'s errno mapping), which ended this module and notes.py carrying the same ten lines twice and the panel naming a wrong cause for a file that simply would not parse."""
    return bool(_store(preferences).set(key, spec))


def forget_overrides() -> None:
    """Drop the cached tables - a test seam like its keyed-store siblings; the product's library switch drops them through the one `keyed_store.release()` at the switch door."""
    keyed_store.release()
