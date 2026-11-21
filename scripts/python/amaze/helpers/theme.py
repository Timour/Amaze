"""Palette, fonts and UI scale from Houdini's Pluto theme, else built-in colours. ▸r/pluto-theme"""


from PySide6 import QtGui

try:
    import hou
except ImportError:
    hou = None


def _read_ui_scale() -> float:
    """The factor `ui_px` applies on top of Qt's scaling. ▸r/qt-windows-macos"""
    try:
        factor = float(hou.ui.globalScaleFactor())
    except Exception:
        return 1.0
    if factor <= 0:
        return 1.0
    return factor    # H22 reports Global UI Size alone; Qt's dpr handles the screen


def screen_ratio(widget=None) -> float:
    """The pixel ratio of `widget`'s screen, else the primary's; read it at paint time. ▸r/screen-dpr"""
    try:
        if widget is not None:
            return float(widget.devicePixelRatioF()) or 1.0
        screen = QtGui.QGuiApplication.primaryScreen()
        return (float(screen.devicePixelRatio()) if screen else 1.0) or 1.0
    except Exception:                                    # noqa: BLE001
        return 1.0


UI_SCALE = _read_ui_scale()      # the scale read without a widget, for chrome built before any window exists


def ui_px(value):
    """Scale a chrome pixel value by Houdini's UI scale; ints stay ints, floored at 1."""
    if UI_SCALE == 1.0:
        return value
    scaled = value * UI_SCALE
    if isinstance(value, float):
        return scaled
    result = int(round(scaled))
    return max(result, 1) if value > 0 else result


MIN_UI_POINTS = 12   # the smallest readable size before the UI scale ▸r/font-sizing

FONT_ROLES = {       # a role is a scale and a weight, never a literal size ▸r/font-sizing
    "comments_title": {"scale": 1.0, "bold": True},    # the Comments subject name, beside its type
    "empty_headline": {"scale": 1.25, "bold": True},   # the empty grid's headline, over its one explaining sentence
    "empty_quote": {"scale": 1.0, "italic": True},     # the empty first-run grid's quotation and its attribution, drawn at the sentence's size
}


def point_size(source, scale: float = 1.0):
    """`scale` times `source`'s point size, or None when it has none to scale. ▸r/font-sizing"""
    points = source.pointSizeF()
    return points * scale if points > 0 else None   # `> 0` because a font sized in PIXELS returns -1, and Qt rejects any size at or below zero


def ui_font(source=None) -> QtGui.QFont:
    """The base font: `source` or the application font, floored at MIN_UI_POINTS. ▸r/font-sizing"""
    font = QtGui.QFont(source if source is not None
                       else QtGui.QGuiApplication.font())
    floor = float(ui_px(MIN_UI_POINTS))
    points = point_size(font)   # None for a pixel-sized font, which is left alone ▸r/linux-live-facts
    if points is not None and points < floor:
        font.setPointSizeF(floor)
    return font


def font(role: str, source=None) -> QtGui.QFont:
    """One named font derived from :func:`ui_font`; raises KeyError on an unknown role."""
    try:
        spec = FONT_ROLES[role]
    except KeyError:
        raise KeyError(
            "%r is not a font role - the roles are %s"
            % (role, ", ".join(sorted(FONT_ROLES)))) from None
    derived = ui_font(source)
    points = point_size(derived, spec["scale"])
    if points is not None:
        derived.setPointSizeF(points)   # a pixel-sized base keeps its own size: the role's weight still applies, its scale cannot
    if spec.get("bold"):
        derived.setBold(True)
    if spec.get("italic"):
        derived.setItalic(True)    # a request; check `QFontInfo(...).styleName()` ▸r/font-italic
    return derived


_DEFAULTS = {        # Houdini's default dark theme, for a session that publishes no theme (hython)
    "surface_low": "#282828",  # tab tray, sidebar backdrop, thumb bg
    "surface": "#2d2d2d",  # toolbar row, tab strip, line_tags
    "field": "#434343",  # filter box fill, toolbar divider
    "row": "#2f2f2f",  # a row list's darker row: the line between the info table's columns
    "text_dim": "#656565",  # grid tile subtitle
    "text": "#a6a6a6",  # grid tile name, unselected tab text
    "text_bright": "#dddddd",  # selected tab text, "Filter" label
    "tab_chip": "#404862",  # section tab selected fill
    "tab_ring": "#464f6b",  # section tab selected ring
    "star": "#fdba00",  # favorite badge (Yellow mode)
}

_ROLES = {           # an Amaze colour -> the role Houdini's theme publishes it under ▸r/one-row-list
    "surface_low": "surfaceLow",
    "surface": "bg",
    "field": "field",
    "row": "viewSurface",
    "text_dim": "dimFg",
    "text": "secondarySurfaceFg",
    "text_bright": "fg",
    "star": "highlight",
}
TAB_RING_LIGHTER = 110    # Houdini's style draws a selected tab's outline this much lighter than its fill


def houdini_role(role: str):
    """A colour Houdini 22's theme publishes under `role`, or None where no theme is published."""
    app = QtGui.QGuiApplication.instance()
    value = app.property("pluto_" + role) if app is not None else None
    return QtGui.QColor(value) if isinstance(value, QtGui.QColor) and value.isValid() else None


def _selected_tab():
    """(fill, outline) of a selected tab, mixed as Houdini's own style mixes them; None with no theme."""
    high, checked = houdini_role("surfaceHighest"), houdini_role("checkedSurface")
    if high is None or checked is None:
        return None
    fill = QtGui.QColor.fromRgbF((high.redF() + checked.redF()) / 2, (high.greenF() + checked.greenF()) / 2,
                                 (high.blueF() + checked.blueF()) / 2)
    return fill, fill.lighter(TAB_RING_LIGHTER)


def accent(fallback_hex: str) -> QtGui.QColor:
    """The theme's accent; the manual accent preference when no theme."""
    return houdini_role("primary") or QtGui.QColor(fallback_hex)


def color(name: str) -> QtGui.QColor:
    """A named Amaze colour: Houdini's own for it, read now, so a changed theme shows at once."""
    if name in ("tab_chip", "tab_ring"):
        tab = _selected_tab()
        live = tab[name == "tab_ring"] if tab else None
    else:
        live = houdini_role(_ROLES[name])
    return live or QtGui.QColor(_DEFAULTS[name])


def color_hex(name: str) -> str:
    return color(name).name()


def houdini_color(name: str, fallback: str) -> QtGui.QColor:
    """Houdini's own colour `name` from the active scheme, else `fallback`."""
    qt = getattr(hou, "qt", None)    # absent in hython ▸r/houdini-code-look
    if qt is not None:
        try:
            return QtGui.QColor(qt.getColor(name))
        except Exception:    # noqa: BLE001 - hou.OperationFailed for a name the scheme lacks
            pass
    return QtGui.QColor(fallback)


def syntax_colors() -> dict:
    """Houdini's syntax colours by kind; its dark scheme's when the current ones are for light."""
    from amaze import amazetheme
    live = {kind: houdini_color(name, fallback)
            for kind, (name, fallback) in amazetheme.CODE_SYNTAX.items()}
    if live["plain"].lightnessF() < 0.5:    # Houdini's light scheme: unreadable on Amaze's dark background
        live = {kind: QtGui.QColor(fallback)
                for kind, (_name, fallback) in amazetheme.CODE_SYNTAX.items()}
    return live
