"""Houdini's UI scale and screen pixel ratio, and a colour made readable on another."""


from PySide6 import QtGui

from amaze import amazetheme

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


def _relative_luminance(color):
    """WCAG relative luminance of a QColor, sRGB-linearised."""
    channels = []
    for value in (color.red(), color.green(), color.blue()):
        channel = value / 255.0
        channels.append(
            channel / 12.92 if channel <= 0.03928
            else ((channel + 0.055) / 1.055) ** 2.4
        )
    return (0.2126 * channels[0] + 0.7152 * channels[1]
            + 0.0722 * channels[2])


def contrast_ratio(one, two):
    """WCAG contrast ratio between two colours (1.0 - 21.0)."""
    first = _relative_luminance(one)
    second = _relative_luminance(two)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def readable_on(color, background, floor=4.5):
    """`color` lightened or darkened until it reaches `floor` contrast on `background`, hue kept."""
    if contrast_ratio(color, background) >= floor:
        return color
    toward_light = _relative_luminance(background) < 0.5   # move away from the background's luminance
    best = color
    for _step in range(20):
        best = best.lighter(115) if toward_light else best.darker(115)
        if contrast_ratio(best, background) >= floor:
            return best
    return QtGui.QColor(amazetheme.LIST_TEXT_COLOR)    # a colour that never reaches `floor` takes the list's text colour
