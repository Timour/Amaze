"""Houdini 22 theme (Pluto) auto-follow.

Houdini 22 stores its UI theme as three roles - base, primary (the
accent), highlight - as hue/chroma/tone triplets in the
pluto_ui.themeValues preference, readable through the documented
hou.getPreference call. Amaze derives its own palette from those
roles so the panel follows whatever theme is active automatically -
no preference toggle, and like Houdini's own UI the
accent is used as a FAMILY of shades (chroma/tone variants), not one
flat color.

Every derived color is anchored so the DEFAULT theme reproduces the
panel's hand-tuned palette exactly: the tone/chroma factors below were
computed from the real shipped hexes and round-trip verified against
Houdini's own OkLCH math (hutil.oklch - the same module the theme
editor uses; it ships wherever the theme system does, so its absence
simply means "no theme"). When no theme is readable (Houdini 21, or
any failure), every color falls back to the original constant,
byte-identical to the pre-theme build.
"""

import json

from PySide6 import QtGui

import hou


# ---------------------------------------------------------------------------
# Houdini global UI scale
#
# On macOS, HiDPI scaling happens inside Qt (devicePixelRatio 2 on a
# Retina display) and hou.ui.globalScaleFactor() stays 1.0 - so every
# hand-tuned pixel value in this project renders at its intended size
# there unchanged. On Linux (and Windows) Houdini instead scales its OWN
# widgets by the Global UI Size factor (Preferences > General User
# Interface / $HOUDINI_UISCALE) while Qt logical pixels map 1:1 to the
# screen - hand-built chrome that ignores the factor renders tiny next
# to Houdini's UI on a HiDPI screen there (reported as "half size" on
# Fedora). ui_px() multiplies chrome pixel values by that factor: a
# no-op wherever the factor is 1.0, the missing scale everywhere else.
# Equivalent to hou.ui.scaledSize() but also handles the half-pixel
# float values some hand-painted widgets use.
#
# Deliberately NOT applied to value-domain numbers (thumbnail sizes,
# slider ranges/snap marks, render resolutions, cache keys) - those are
# content sizes, not chrome.
def _read_ui_scale() -> float:
    """The factor ui_px() applies ON TOP of Qt's own scaling.

    Two scaling systems exist and versions differ in which one carries
    the display scale: Qt's devicePixelRatio (macOS Retina) and
    Houdini's globalScaleFactor (Windows/Linux Global UI Size). H22 on
    macOS reports factor 1.0 and lets Qt's dpr 2.0 do the work; H21 on
    macOS reports the SAME 2.0 in BOTH - applying the factor then
    double-scaled every widget. General rule: when Houdini reports
    (about) the same scale Qt already applies, it is describing Qt's
    scaling, not requesting more - use 1.0. A factor Qt does NOT
    already apply (Windows 1.5 with dpr 1.0) is applied as before."""
    try:
        factor = float(hou.ui.globalScaleFactor())
    except Exception:
        return 1.0
    if factor <= 0:
        return 1.0
    try:
        from PySide6 import QtGui

        screen = QtGui.QGuiApplication.primaryScreen()
        dpr = float(screen.devicePixelRatio()) if screen else 1.0
    except Exception:
        dpr = 1.0
    if dpr > 1.0 and abs(factor - dpr) < 0.05:
        return 1.0
    return factor


UI_SCALE = _read_ui_scale()


def ui_px(value):
    """Scale a chrome pixel value by Houdini's global UI scale factor.
    Ints stay ints (rounded, floored at 1 for positive inputs so
    hairlines never vanish); floats stay floats (half-pixel paint
    values)."""
    if UI_SCALE == 1.0:
        return value
    scaled = value * UI_SCALE
    if isinstance(value, float):
        return scaled
    result = int(round(scaled))
    return max(result, 1) if value > 0 else result


# -- THE ONE FONT TABLE ------------------------------------------------
#
# One document controls every font, the way one table already controls
# the colours. Raised 2026-08-04, after list mode and the tiles were
# both found rendering wrong on Windows: this module owned `ui_px` and
# the colours and owned no fonts at all, so the sizes were four
# independent rules in three files, each correct only on the machine it
# was typed on.
#
# THE HOST'S OWN CONVENTION, read out of the shipped code 2026-08-05:
# `hou.qt`'s entire Python widget library sets NO point size anywhere -
# it inherits. `houdini/config/Styles/base.qss` sizes text in scaled
# PIXELS (`@15px@`), and Pluto's style resolves sizes through
# `pixelMetric` multiplied by its own scale factor. Nothing in Houdini
# pins an absolute point size, which is what Amaze was doing.

#: The panel's smallest readable size, BEFORE the UI scale. Houdini
#: scales its own chrome by Global UI Size and this follows it -
#: decided 2026-08-05, as the closest of three options to the host.
#: At UI_SCALE 1.0 (this Mac) `ui_px(12)` is 12, so nothing moves.
MIN_UI_POINTS = 12

#: Named font roles, as DATA: how each derives from the base. A role is
#: a scale and a weight, never a literal size - "derive a related size
#: from the one it relates to, never floor it independently"
#: (research.md, the Windows font report).
#:
#: THE TILE FONTS ARE DELIBERATELY NOT HERE. `AssetItemDelegate` derives
#: its name and sub-line from the VIEW's own option font, which is
#: correct and must stay: a font that does not come from the view hands
#: the cell Qt's default family, not the panel's font in another weight
#: (research.md ▸ *FontRole REPLACES the view's font*). A role here is
#: for a widget that has no option font to derive from.
FONT_ROLES = {
    # The Comments pane's subject name, over its section and type lines.
    "comments_title": {"scale": 1.4, "bold": True},
    # The empty grid's headline, over its one explaining sentence.
    "empty_headline": {"scale": 1.25, "bold": True},
}


def ui_font(source=None) -> QtGui.QFont:
    """THE BASE FONT: the host's, with one floor, applied once.

    `source` is the font to start from - the panel passes Houdini's own
    main-window font. Defaults to the application's, which is what a
    headless run and any widget with no host to ask both get.

    The floor was written into `panel.py` as a bare `12.0` with the
    comment that it compensates a ~1pt Qt-vs-native rendering
    difference. Measured 2026-08-05: at a 9pt host font it adds THREE
    points, not one, which is the Windows report - the sub-line and the
    name ending up different sizes because only one of them was floored.
    Whatever the number is, there is now exactly one of it.
    """
    font = QtGui.QFont(source if source is not None
                       else QtGui.QGuiApplication.font())
    floor = float(ui_px(MIN_UI_POINTS))
    # `> 0` because a font sized in PIXELS answers -1 here, and clamping
    # that to the floor would silently convert it to points.
    if 0 < font.pointSizeF() < floor:
        font.setPointSizeF(floor)
    return font


def font(role: str, source=None) -> QtGui.QFont:
    """One named font, derived from :func:`ui_font`.

    Raises on an unknown role rather than quietly handing back the base:
    a typo that returns something plausible is the shape this table
    exists to end.
    """
    try:
        spec = FONT_ROLES[role]
    except KeyError:
        raise KeyError(
            "%r is not a font role - the roles are %s"
            % (role, ", ".join(sorted(FONT_ROLES)))) from None
    derived = ui_font(source)
    derived.setPointSizeF(derived.pointSizeF() * spec["scale"])
    if spec.get("bold"):
        derived.setBold(True)
    return derived


# NOTE: deliberately no print() here - on Windows, any Python print pops
# the Houdini Console WINDOW open, and this module re-imports on every
# panel open (the reload chain), so a scale announcement spawned a
# console dialog per open. The factor is recorded in the Debug Engine's
# session header instead (core/debug.py, "ui_scale").


# The hand-tuned palette: the fallback AND the anchor the derivations
# reproduce under Houdini 22's default theme.
_DEFAULTS = {
    "surface_low": "#262626",  # tab tray, sidebar backdrop, thumb bg
    "surface": "#2d2d2d",  # toolbar row, tab strip, line_tags
    "surface_high": "#313131",  # grid + details bg, star stamped hole
    "field": "#434343",  # filter box fill, toolbar divider
    "text_dim": "#696969",  # grid tile subtitle
    "text": "#a6a6a6",  # grid tile name, unselected tab text
    "text_bright": "#dddddd",  # selected tab text, "Filter" label
    "tab_chip": "#3e4765",  # section tab selected fill
    "tab_ring": "#43506d",  # section tab selected ring
    "star": "#fcb900",  # favorite badge (Yellow mode)
}

# Base-family surfaces: a tone on the theme base's own hue/chroma
# (the default base is chroma 0, which lands exactly on the greys
# above; a tinted base tints every surface coherently).
_BASE_TONES = {
    "surface_low": 14.9,
    "surface": 18.2,
    "surface_high": 20.0,
    "field": 28.1,
    "text_dim": 44.1,
    "text": 67.9,
    "text_bright": 88.0,
}

# Accent-family shades: (chroma factor vs the accent's own, tone) -
# the "different opacities of the accent" Houdini's own example panel
# shows. Factors/tones solved from the shipped chip colors against the
# default accent #7082b9.
_ACCENT_DERIVED = {
    "tab_chip": (0.60, 30.4),
    "tab_ring": (0.59, 33.8),
}

_theme = "unread"
_derived = {}


def _read():
    global _theme
    if _theme != "unread":
        return _theme
    _theme = None
    try:
        raw = hou.getPreference("pluto_ui.themeValues")
        if raw:
            values = json.loads(raw)
            from hutil import oklch

            _theme = {
                "oklch": oklch,
                "base": _to_qcolor(oklch, values["base"]),
                "accent": _to_qcolor(oklch, values["primary"]),
                "highlight": _to_qcolor(oklch, values["highlight"]),
            }
    except Exception as exc:
        # Imported lazily: core/debug.py itself imports theme for its
        # session header, so a module-top import would cycle on reload.
        from amaze.core import debug

        debug.event("theme", "not readable, using built-in colors", error=str(exc))
    return _theme


def _to_qcolor(oklch, triplet):
    hue, chroma, tone = (float(v) for v in triplet[:3])
    ok = oklch.OkLCH(
        oklch.tone_to_lightness(tone),
        chroma / 100.0 * oklch.max_chroma,
        hue,
    )
    return _rgb_qcolor(oklch, ok)


def _rgb_qcolor(oklch, ok):
    rgb = oklch.chromaClamp(ok)
    return QtGui.QColor(int(rgb.red), int(rgb.green), int(rgb.blue))


def _lch(oklch, qcolor):
    return oklch.RGB(qcolor.red(), qcolor.green(), qcolor.blue()).to_OKLCH()


def accent(fallback_hex: str) -> QtGui.QColor:
    """The theme's accent; the manual accent preference when no theme."""
    theme = _read()
    if theme is not None:
        return QtGui.QColor(theme["accent"])
    return QtGui.QColor(fallback_hex)


def color(name: str) -> QtGui.QColor:
    """A named Amaze color, theme-derived when a theme is active."""
    theme = _read()
    if theme is None:
        return QtGui.QColor(_DEFAULTS[name])
    if name not in _derived:
        _derived[name] = _derive(theme, name)
    return QtGui.QColor(_derived[name])


def color_hex(name: str) -> str:
    return color(name).name()


def _derive(theme, name):
    oklch = theme["oklch"]
    try:
        if name == "star":
            return QtGui.QColor(theme["highlight"])
        if name in _BASE_TONES:
            base = _lch(oklch, theme["base"])
            return _rgb_qcolor(
                oklch,
                oklch.OkLCH(
                    oklch.tone_to_lightness(_BASE_TONES[name]),
                    base.chroma,
                    base.hue,
                ),
            )
        if name in _ACCENT_DERIVED:
            factor, tone = _ACCENT_DERIVED[name]
            acc = _lch(oklch, theme["accent"])
            return _rgb_qcolor(
                oklch,
                oklch.OkLCH(
                    oklch.tone_to_lightness(tone),
                    acc.chroma * factor,
                    acc.hue,
                ),
            )
    except Exception as exc:
        # Imported lazily: core/debug.py itself imports theme for its
        # session header, so a module-top import would cycle on reload.
        from amaze.core import debug

        debug.event("theme", "derivation failed", name=name, error=str(exc))
    return QtGui.QColor(_DEFAULTS[name])
