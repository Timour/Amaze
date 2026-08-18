"""Palette, fonts and UI scale, derived from Houdini 22's Pluto theme; with no theme readable every colour falls back to its original constant. ▸r/pluto-theme"""

import json

from PySide6 import QtGui

import hou


def _read_ui_scale(widget=None) -> float:
    """The factor `ui_px` applies ON TOP of Qt's own scaling, for `widget`'s screen; when Houdini merely restates a ratio Qt already applies, that is 1.0. ▸r/qt-windows-macos"""
    try:
        factor = float(hou.ui.globalScaleFactor())
    except Exception:
        return 1.0
    if factor <= 0:
        return 1.0
    dpr = screen_ratio(widget)
    if dpr > 1.0 and abs(factor - dpr) < 0.05:
        return 1.0
    return factor


def screen_ratio(widget=None) -> float:
    """The device pixel ratio of `widget`'s own screen, or the primary's when there is no widget; read it at PAINT time, an unrealised one answers primary. ▸r/screen-dpr"""
    try:
        if widget is not None:
            return float(widget.devicePixelRatioF()) or 1.0
        from PySide6 import QtGui

        screen = QtGui.QGuiApplication.primaryScreen()
        return (float(screen.devicePixelRatio()) if screen else 1.0) or 1.0
    except Exception:                                    # noqa: BLE001
        return 1.0


UI_SCALE = _read_ui_scale()      # the no-widget verdict, kept for chrome built before any window exists


def ui_px(value):
    """Scale a chrome pixel value by Houdini's UI scale; ints stay ints (floored at 1 so hairlines never vanish), floats stay floats."""
    if UI_SCALE == 1.0:
        return value
    scaled = value * UI_SCALE
    if isinstance(value, float):
        return scaled
    result = int(round(scaled))
    return max(result, 1) if value > 0 else result


MIN_UI_POINTS = 12   # the smallest readable size BEFORE the UI scale; Houdini pins no absolute point size anywhere ▸r/font-sizing

FONT_ROLES = {       # a role is a SCALE and a weight, never a literal size; tile fonts are deliberately absent, they derive from the view's option font ▸r/font-sizing
    "comments_title": {"scale": 1.4, "bold": True},    # the Comments subject name, over its section and type lines
    "empty_headline": {"scale": 1.25, "bold": True},   # the empty grid's headline, over its one explaining sentence
}


def ui_font(source=None) -> QtGui.QFont:
    """THE BASE FONT: the host's, with ONE floor applied once; `source` defaults to the application font, which is what a headless run gets. ▸r/font-sizing"""
    font = QtGui.QFont(source if source is not None
                       else QtGui.QGuiApplication.font())
    floor = float(ui_px(MIN_UI_POINTS))
    if 0 < font.pointSizeF() < floor:   # `> 0` because a font sized in PIXELS answers -1, and clamping that would convert it to points ▸r/linux-live-facts
        font.setPointSizeF(floor)
    return font


def font(role: str, source=None) -> QtGui.QFont:
    """One named font derived from :func:`ui_font`; RAISES on an unknown role rather than handing back a plausible base."""
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


_DEFAULTS = {        # the hand-tuned palette: the fallback AND the anchor the derivations reproduce under the default theme. NO print() in this module ▸r/qt-windows-macos
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

_BASE_TONES = {      # a tone on the theme base's own hue/chroma; the default base is chroma 0, so a tinted base tints every surface coherently
    "surface_low": 14.9,
    "surface": 18.2,
    "surface_high": 20.0,
    "field": 28.1,
    "text_dim": 44.1,
    "text": 67.9,
    "text_bright": 88.0,
}

_ACCENT_DERIVED = {  # (chroma factor vs the accent's own, tone), solved from the shipped chip colours against the default accent `#7082b9` ▸r/pluto-theme
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
        from amaze.core import debug   # lazy: debug imports theme for its session header, so a module-top import cycles on reload

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
        from amaze.core import debug   # lazy: debug imports theme for its session header, so a module-top import cycles on reload

        debug.event("theme", "derivation failed", name=name, error=str(exc))
    return QtGui.QColor(_DEFAULTS[name])
