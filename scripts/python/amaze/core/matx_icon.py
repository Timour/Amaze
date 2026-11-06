"""The PhysicallyBased material icon, drawn from measured values into the template SVG."""

from __future__ import annotations

import re

from PySide6 import QtGui

import amaze
from amaze.helpers import ui_helpers

TRANSMISSIVE_ALPHA = 0.25

SHARED_TEMPLATE = "no_thumb_material.svg"
TEMPLATES = {
    "PhysicallyBased": SHARED_TEMPLATE,
    "RGL": SHARED_TEMPLATE,
}
DEFAULT_TEMPLATE = SHARED_TEMPLATE

_BASE_PLACEHOLDER = "#f9e231"
_SWATCH2_PLACEHOLDER = "#74fbea"

_SVG_CACHE = {}


def _template(source: str = "") -> str:
    """The SVG source for one value-only source, read once each."""
    name = TEMPLATES.get(source, DEFAULT_TEMPLATE)
    if name not in _SVG_CACHE:
        path = amaze.package_file("ui", name)
        with open(path, "r", encoding="utf-8") as handle:
            _SVG_CACHE[name] = handle.read()
    return _SVG_CACHE[name]


def _srgb_hex(color) -> str:
    """Linear colour, possibly above 1, to a clamped sRGB hex string."""
    if not color:
        return "#808080"
    out = []
    for component in list(color)[:3]:
        c = max(0.0, min(1.0, float(component)))
        if c <= 0.0031308:
            c = c * 12.92
        else:
            c = 1.055 * (c ** (1.0 / 2.4)) - 0.055
        out.append(int(round(c * 255)))
    while len(out) < 3:
        out.append(out[-1] if out else 128)
    return "#%02x%02x%02x" % tuple(out)


def _fill(svg: str, placeholder: str, paint: str) -> str:
    """Every `fill` naming `placeholder`, in either case - Figma writes hex in capitals."""
    return re.sub('fill="%s"' % re.escape(placeholder), lambda _m: paint, svg,
                  flags=re.IGNORECASE)


def icon_svg(values: dict, source: str = "") -> str:
    """The template with both swatches filled in, keyed on the placeholder fills."""
    svg = _template(source)
    svg = _fill(svg, _BASE_PLACEHOLDER, 'fill="%s"' % _srgb_hex(values.get("color")))
    alpha = TRANSMISSIVE_ALPHA if values.get("transmission") else 1.0
    svg = _fill(svg, _SWATCH2_PLACEHOLDER, 'fill="#000000" fill-opacity="%s"' % alpha)
    svg = svg.replace(' visibility="hidden"', "")
    return svg


def render(values: dict, size: int, source: str = "") -> QtGui.QImage:
    """A square icon for one material's values, rendered from the SVG onto a transparent image."""
    image = QtGui.QImage(
        size, size, QtGui.QImage.Format.Format_ARGB32_Premultiplied
    )
    ui_helpers.paint_svg(image, icon_svg(values, source).encode("utf-8"))
    return image
