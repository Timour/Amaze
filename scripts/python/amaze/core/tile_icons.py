"""Tile icons: a chosen symbol on a chosen colour, for anything that
has no picture to show.

A LOP setup, a DOP network, a snippet - plenty of assets simply cannot
be rendered, and a grid of identical fallback tiles tells the user
nothing. This lets any tile carry a Feather icon on a background colour
instead, chosen per asset.

**The geometry comes from the design template**, not from taste:
ui/icon_template.svg draws a 512x512 background with the icon's 24-unit
grid placed at `translate(106, 106) scale(12.5)` and a stroke of 0.8
grid units. That renders the icon's ink at **250px** across (Feather
draws on a 24 grid with 2 units of padding, so 20 units x 12.5 = 250)
with a **10px** stroke, centred. The numbers were read off the template
by measuring its clipboard against Feather's own clipboard.svg, and are
reproduced here so every one of the 287 icons lands identically.

STROKE_UNITS is the one number that is a look rather than a
measurement: 0.8 is the template's thin stroke, and Feather's own
default is 2.0 (a much bolder 25px). One constant, either way.

The composed image is written as a normal PNG into the library's image
directory, so the thumbnail engine, the LRU cache, list mode and drag
previews all keep working with no special case. It is written BESIDE
the rendered thumbnail (`<id>_icon.png`), never over it: clearing the
icon must bring a real render back, and an overwrite cannot be undone.
"""

from __future__ import annotations

import os
import re
from collections import OrderedDict

from PySide6 import QtCore, QtGui, QtSvg

from amaze.core import debug, keyed_store
from amaze.helpers import hostos

#: Where the icon set lives, relative to the package.
ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "ui", "feather")

#: Straight from the template: the 24-unit icon grid is drawn at this
#: scale on a 512 canvas with a stroke this many grid units wide. The
#: template's translate(106,106) is NOT a constant here - it is
#: "centre the grid", derived per icon so a fitted one stays centred.
#: Change these and every existing tile silently re-renders
#: differently, so they are constants, not preferences.
CANVAS = 512
ICON_SCALE = 12.5
STROKE_UNITS = 0.8
#: Feather's own default weight, the other half of the Look preference.
FEATHER_STROKE_UNITS = 2.0
#: The rule the numbers above exist to satisfy: no icon's ink may span
#: more than this on a 512 tile. Asserted by the tests against rendered
#: pixels, so an edit that breaks the design intent fails loudly.
INK_SPAN = 250.0      # Feather's 20 drawn units at ICON_SCALE

#: The two ink colours, chosen per tile (the dialog's "Icon color").
#: Stored as a TOKEN rather than a hex value so re-tuning either one
#: re-renders every tile that uses it, instead of leaving a library
#: full of the old literal. The template drew near-black; light exists
#: for dark backgrounds, where dark ink is invisible.
INKS = {
    "dark": "#262626",
    "light": "#d0ced0",
}
DEFAULT_INK = "dark"


def ink_colour(token: str) -> str:
    """Hex for an ink token, falling back to dark for anything odd."""
    return INKS.get(str(token or "").strip().lower(), INKS[DEFAULT_INK])

#: Four presets plus Custom, which opens the colour picker. These
#: values are deliberately provisional - a palette can only be judged
#: against real tiles at real sizes, so they are placed to be tuned.
PRESETS = (
    ("Salmon", "#ef8878"),
    ("Mint", "#4af2a1"),
    ("Sky", "#5cc9f5"),
    ("Sand", "#e2b148"),
)

#: (name, bg, size, stroke) -> QImage, so a grid of tiles renders each
#: distinct icon once.
#:
#: Capped in BYTES, not entries. A 240-entry cap sounds bounded until
#: you multiply it by the tile size the user picked: measured ceilings
#: were 63MB at rendersize 256, 252MB at 512 and 1007MB at 1024 - the
#: comment here used to say the bound prevented "a gigabyte", and at
#: 1024 it WAS a gigabyte, entirely outside the RAM budget the
#: thumbnail engine honours.
#:
#: LRU, not FIFO: eviction popped the oldest INSERTED entry with no
#: reordering on hit, so past the cap the hottest icons were thrown out
#: first and every repaint re-composed them (0.38ms at 256, 1.37ms at
#: 1024, per tile).
_COMPOSED_MAX_BYTES = 64 * 1024 * 1024
#: Kept as a ceiling on COUNT too - a library of tiny icons should not
#: grow an unbounded dict just because it fits in the byte budget.
_COMPOSED_MAX = 240
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
    """The drawing commands inside a Feather SVG, without its own <svg>
    wrapper - the wrapper carries a 24px size and a 2-unit stroke that
    this module replaces with the template's."""
    try:
        with open(icon_path(name), encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ""
    match = re.search(r"<svg[^>]*>(.*)</svg>", text, re.S)
    return match.group(1).strip() if match else ""


def _ink_span_px(body: str, scale: float, stroke: float) -> float:
    """How wide this icon actually draws, in pixels, at a given scale -
    its PATH extent, with the stroke's own width taken back off.

    Measured by rendering, because an SVG path's bounding box is not
    something you can read off the file. Feather's grid says every icon
    spans 20 units, and most do; the "-off" variants slash corner to
    corner and span 22, which is how they broke the 250px rule while
    every other icon obeyed it."""
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
    # createAlphaMask, NOT createMaskFromColor: the latter's polarity
    # goes the other way and returns the whole canvas as "ink", which
    # silently shrank every icon to half size. Verified against an
    # exhaustive alpha scan - same rect, to the pixel.
    box = QtGui.QRegion(
        QtGui.QBitmap.fromImage(image.createAlphaMask())
    ).boundingRect()
    if box.isEmpty():
        return 0.0
    return max(box.width(), box.height()) - stroke * scale


def _fit(name: str, stroke_units: float):
    """(scale, stroke) for this icon: the template's, reduced only if
    its ink would otherwise exceed INK_SPAN. The stroke is divided by
    the same factor so it still renders at its chosen pixel width - the
    icons that shrink must not also thin out."""
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
    """The template, rebuilt around one icon. Kept as SVG text rather
    than painted by hand because that is what the template IS - the
    same document, with the symbol swapped."""
    body = _icon_body(name)
    if not body:
        return ""
    scale, stroke = _fit(name, stroke_units or STROKE_UNITS)
    # The template's 106 offset IS "centre the 24-unit grid": half the
    # canvas, back off half the grid. Written that way so a fitted icon
    # stays centred without a second constant to keep in step.
    offset = CANVAS / 2.0 - 12.0 * scale
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
    """Compose and save. False (recorded in the debug log) on any
    failure - a tile icon is a nicety, never a reason a save fails."""
    image = compose(name, background, size, stroke_units, ink)
    if image is None:
        # note vs event for this file: an unknown icon name and a failed
        # icon delete are internal - the tile keeps the icon it had - so
        # those are events. The refusal in _write_overrides is
        # work-affecting (the user's choice is not stored), so it stays
        # visible as a note.
        debug.event("icons", "no such tile icon", icon=name)
        return False
    # ONE REPORT FOR TWO FAILURES, and each says only what it knows.
    # These were two copies of the same four lines, both ending "check
    # the library folder is reachable and not read-only" - two causes
    # guessed at once, and the second names the wrong object: measured
    # 2026-08-10, a read-only FILE does not stop a write here, because
    # rename asks the DIRECTORY (research.md ▸ WHAT A FAILED WRITE
    # ACTUALLY RAISES). The OSError path has an errno and can say which
    # it was; Qt's `save` just answers False, so that one claims no
    # cause rather than inventing the same pair.
    why = ""
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
    """A colour the composer can actually use. Checked before storing,
    because a bad value would otherwise reach every future compose()."""
    return bool(value) and QtGui.QColor.isValidColorName(str(value))


def normalise(spec) -> dict:
    """A stored icon choice, cleaned up: {"name", "bg", "ink"} or {}.

    Anything unusable becomes {} rather than raising - this reads data
    that a user (or a future version) may have written, and an odd
    value should cost a fallback tile, not the whole grid. A choice
    saved before ink existed simply gets the default, which is what it
    was rendered with."""
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
    # Unknown fields ride along - a newer build's addition must survive
    # this build rewriting the entry.
    record = {k: v for k, v in spec.items()
              if k not in ("name", "bg", "ink")}
    record.update({"name": name, "bg": background, "ink": ink})
    return record


def stroke_for(preferences) -> float:
    """The line weight to draw with, from Preferences - Look.

    Two looks rather than a free number: the template's thin stroke,
    and Feather's own default, which is what the icon set was drawn
    for. Which one reads better is only obvious at tile size, so both
    ship and the choice is the user's."""
    try:
        weight = str(getattr(preferences, "icon_line_weight", "") or "")
    except Exception:                                       # noqa: BLE001
        weight = ""
    return FEATHER_STROKE_UNITS if weight == "feather" else STROKE_UNITS


def thumbnail_path(preferences, asset_id: str) -> str:
    """`<library>/img/<id>.png` - the ONE composition of a library
    thumbnail's path.

    It was hand-concatenated in nine places in render/thumbs.py while
    `MaterialLibrary.asset_files()` composed the same path with
    os.path.join, and the two agree only while `preferences.dir` and
    `img_dir` carry their trailing separator - enforced in exactly one
    place, `refresh_data()` (prefs/persistence.py). The `dir` SETTER
    does not
    normalise, so any path that assigns it and renders before a save
    produced `<parent>/libimg/<id>.png` from the concatenation while
    asset_files(), Clean Library and tools/library-audit.py all looked
    for `<lib>/img/<id>.png`: the render reported success, the tile
    read Missing Thumbnail forever, and an unaccounted PNG was left
    outside the library. Reproduced by assigning `prefs.dir` without a
    separator; os.path.join is immune to the same input, which is why
    the two disagreed rather than both being wrong.

    Contained, like every other id-derived path: the id comes verbatim
    out of library.json and nothing validates it on load.
    """
    return hostos.contained_join(
        os.path.join(preferences.dir, preferences.img_dir),
        str(asset_id) + preferences.img_ext)


def icon_image_path(preferences, asset_id: str) -> str:
    """Where a tile's composed icon lives: beside its thumbnail, with a
    suffix, so the render underneath survives.

    Composed exactly like `thumbnail_path` above, and for both of its
    reasons. CONTAINED, because the id comes verbatim out of
    library.json and nothing validates it on load - and this is the
    path `render_for` WRITES and `clear_for` runs os.remove on, so a
    concatenated one chose which file outside the library to create and
    then delete. And through os.path.join, because the two forms
    disagree whenever `preferences.dir` is assigned without a trailing
    separator: the sibling resolved into `img/`, this one into
    `<library>img/`.
    """
    return hostos.contained_join(
        os.path.join(preferences.dir, preferences.img_dir),
        str(asset_id) + "_icon" + preferences.img_ext)


def render_for(preferences, asset_id: str, spec) -> str:
    """Compose an asset's icon onto disk and return the path, or "" if
    there is no icon to make. Deleting the file when the icon is
    cleared is the caller's job (it knows whether a render exists)."""
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


# ---------------------------------------------------------------------
# Where a choice is REMEMBERED
#
# Two kinds of tile, so two stores. A library asset (Materials, Nodes,
# Code) has a record of its own, and the icon rides along in it - so it
# travels with the library, survives a move, and is one more field in a
# file that is already backed up. Images and Geometry are listings of
# files on disk with no record anywhere, so their choices go in
# icons.json beside the library index, keyed by absolute path.
# ---------------------------------------------------------------------

def forget_composed() -> None:
    """Drop the composed-image caches - the LOOK changed (line weight),
    so every remembered picture is now the wrong one."""
    global _composed_bytes
    _composed.clear()
    _composed_bytes = 0
    _fits.clear()


#: icons.json had NO absent-but-known guard of its own. It has one now
#: without a line being written for it, because the guard is not
#: something a store performs - it is what being declared IS. Measured
#: on the real library 2026-08-03: icons.json is absent with no .bak
#: tier of any kind, so the first icon ever picked was also the one
#: write with no evidence behind it.
OVERRIDES_FILE = "icons.json"

SPEC = keyed_store.bind(OVERRIDES_FILE, normalise)


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def overrides(preferences) -> dict:
    """Every path-keyed icon choice in this library - a COPY."""
    return _store(preferences).all()


def override_for(preferences, key: str) -> dict:
    return _store(preferences).get(key)


def set_override(preferences, key: str, spec) -> bool:
    """Store (or with an empty spec, forget) one path's icon.

    THE REPORTING IS THE ENGINE'S. A `written()` beside this one held
    the refusal note and the denial alert; `notes.py` held the same ten
    lines with two words changed, and the other two stores held none.
    The words are on the Spec now (`denied_alert`) and the policy is in
    `_commit`, beside the engine's other two failure reports - which
    also ended a duplicate: `_commit` had already noted the refusal
    sentence that this noted again.

    A bare False could not say WHY, and the panel used to guess: a
    refused write got "check that the library folder is writable" when
    the folder was fine and the file simply would not parse. That is
    the same defect the errno mapping fixes one level down.
    """
    return bool(_store(preferences).set(key, spec))


def forget_overrides() -> None:
    """Drop the cached tables - the library directory changed under us."""
    keyed_store.release()
