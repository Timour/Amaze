"""The PhysicallyBased material icon, DRAWN from the material's measured numbers because a value-only source ships no textures to render. Two live swatches - base colour and transparency - are string-substituted into the template SVG, so re-exporting the template is all a design change needs. Substitution keys on the placeholder FILLS, never element ids, which vary between exports. ▸archive/matx_icon.py"""

from __future__ import annotations

import os

from PySide6 import QtCore, QtGui, QtSvg

import hou

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
        path = ui_helpers.ui_asset(name)
        with open(path, "r", encoding="utf-8") as handle:
            _SVG_CACHE[name] = handle.read()
    return _SVG_CACHE[name]


def _srgb_hex(color) -> str:
    """Linear colour to an sRGB hex string. The stored values are LINEAR and some exceed 1, so BOTH the clamp and the transfer function are required - scaling straight to 0-255 renders every swatch far too dark."""
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


def icon_svg(values: dict, source: str = "") -> str:
    """The template with both swatches filled in. Keyed on the placeholder FILLS rather than element ids, so one substitution serves any template the designer exports, and the authoring `visibility=hidden` must go or the swatch never draws."""
    svg = _template(source)
    svg = svg.replace(
        'fill="%s"' % _BASE_PLACEHOLDER,
        'fill="%s"' % _srgb_hex(values.get("color")),
    )
    alpha = TRANSMISSIVE_ALPHA if values.get("transmission") else 1.0
    svg = svg.replace(
        'fill="%s"' % _SWATCH2_PLACEHOLDER,
        'fill="#000000" fill-opacity="%s"' % alpha,
    )
    svg = svg.replace(' visibility="hidden"', "")
    return svg


def render(values: dict, size: int, source: str = "") -> QtGui.QImage:
    """A square icon for one material's measured values, rendered straight from the SVG onto a transparent image - never through `QIcon`, whose engine has lost the alpha before."""
    image = QtGui.QImage(
        size, size, QtGui.QImage.Format.Format_ARGB32_Premultiplied
    )
    image.fill(QtCore.Qt.GlobalColor.transparent)

    renderer = QtSvg.QSvgRenderer(
        QtCore.QByteArray(icon_svg(values, source).encode("utf-8"))
    )
    painter = QtGui.QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return image
