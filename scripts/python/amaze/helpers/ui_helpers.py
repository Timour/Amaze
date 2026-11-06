"""Shared UI elements: the drag tag, the ui/ asset and SVG readers, and hand-painted widgets."""

import contextlib
import os
import re

from PySide6 import QtWidgets, QtCore, QtGui, QtSvg

import amaze
from amaze import amazetheme
from amaze.core import debug
from amaze.helpers import theme


@contextlib.contextmanager
def relayout(*models):
    """Wrap a wholesale change to models' contents; never a structural insert or removal (segfault)."""
    live = [model for model in models if model is not None]
    for model in live:
        model.layoutAboutToBeChanged.emit()
    try:
        yield              # the pair closes even when the body raises
    finally:
        for model in reversed(live):   # reverse order, so the innermost model is released first - the mirror of how they were announced
            model.layoutChanged.emit()


DRAG_TAG_STYLE = (     # the drag name tag, shared by the self-managed and the native drags
    "background-color: #2d2d2d; color: #e6e6e6;"
    " border: 1px solid #555555; padding: %dpx %dpx;"
    % (theme.ui_px(2), theme.ui_px(8))
)


def name_tag_pixmap(name: str) -> QtGui.QPixmap:
    """The drag tag as a pixmap, the drag picture for the native drags."""
    label = QtWidgets.QLabel(str(name))
    label.setStyleSheet(DRAG_TAG_STYLE)
    label.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
    label.adjustSize()
    label.ensurePolished()
    return label.grab()


_svg_image_cache: dict = {}    # rendered ui/ SVGs keyed by (name, side); a stored False means tried and failed


def svg_image(name: str, side: int = 512):
    """A ui/ SVG rendered once as a square QImage, or None when it is missing or unreadable."""
    key = (name, side)
    cached = _svg_image_cache.get(key)
    if cached is None:
        image = None
        path = amaze.package_file("ui", name)
        try:
            if os.path.exists(path):
                img = QtGui.QImage(side, side, QtGui.QImage.Format.Format_ARGB32)
                if paint_svg(img, path):
                    image = img
            else:
                debug.event("ui", "ui asset missing", name=name, path=path)
        except Exception as exc:                          # noqa: BLE001
            debug.event("ui", "ui asset not rendered",     # event, not note: the caller still draws without it
                        name=name, error=str(exc))
        cached = image if image is not None else False
        _svg_image_cache[key] = cached
    return cached or None


def forget_svg_images() -> None:
    """Drop the rendered-SVG cache; the test-isolation seam."""
    _svg_image_cache.clear()


def paint_svg(device, svg) -> bool:
    """Fill `device` transparent and draw `svg` - a path, or SVG text as bytes; False if unreadable."""
    device.fill(QtCore.Qt.GlobalColor.transparent)
    renderer = QtSvg.QSvgRenderer(
        QtCore.QByteArray(svg) if isinstance(svg, bytes) else svg)
    if not renderer.isValid():
        return False
    painter = QtGui.QPainter(device)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return True


def live_current_index(view):
    """A view's current index, re-derived from its live model, or None. ▸r/model-contracts"""
    if view is None:
        return None
    model = view.model()
    if model is None:
        return None
    index = view.currentIndex()
    if not index.isValid():
        return None
    if index.model() is not model:   # it may predate a model swap; never map it through the current proxy
        return None
    parent = index.parent()    # a tree row keeps its parent: the same row number elsewhere is another row
    try:
        rows = model.rowCount(parent)   # ROW ONLY: a list model's columnCount is private ▸r/model-contracts
    except TypeError:
        return None                  # another signature; "no selection" is the caller's safe fallback
    if index.row() >= rows:
        return None
    return model.index(index.row(), 0, parent)   # COLUMN 0, not the clicked cell ▸r/row-selection


def tooltip_text(text: str, max_px: int = 800) -> str:
    """A tooltip never drawn wider than `max_px` device pixels."""
    import html

    cap = max(1, int(max_px / theme.screen_ratio()))    # the primary screen: the target monitor is unknown at setToolTip time ▸r/screen-dpr
    metrics = QtGui.QFontMetrics(QtWidgets.QToolTip.font())
    if metrics.horizontalAdvance(text) <= cap:
        return html.escape(text) if _might_be_rich(text) else text    # Qt auto-detects rich text, so this branch escapes too ▸r/tooltip-autodetect

    body = html.escape(text).replace("\n", "<br>")   # rich text eats newlines
    return '<qt><table width="%d"><tr><td>%s</td></tr></table></qt>' % (
        cap, body)


def _might_be_rich(text: str) -> bool:
    """Whether Qt would treat `text` as rich rather than plain. ▸r/tooltip-autodetect"""
    return QtGui.Qt.mightBeRichText(str(text or ""))


_SVG_CACHE: dict = globals().get("_SVG_CACHE", {})   # rasterised SVGs keyed by (path, size, tint), kept across module reloads


_PAINT_OPACITY = re.compile(r'((?:fill|stroke)-opacity)(="|:)[0-9.]+')


def at_opacity(text: str, opacity) -> str:
    """SVG text with every fill and stroke opacity set to `opacity`; None leaves it as drawn."""
    if opacity is None:
        return text
    return _PAINT_OPACITY.sub(lambda m: "%s%s%g" % (m.group(1), m.group(2), opacity), text)


def render_svg_pixmap(path, size, color_replacements=None, opacity=None):
    """An SVG on a transparent square QPixmap, colours swapped first; always a copy, blank if missing."""
    tint = tuple(sorted((color_replacements or {}).items()))
    key = (path, int(size), tint, opacity)
    cached = _SVG_CACHE.get(key)
    if cached is not None:
        return cached.copy()
    pixmap = QtGui.QPixmap(size, size)
    if not (path and os.path.exists(path)):
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    else:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        for old, new in (color_replacements or {}).items():    # either case: Figma writes hex in capitals
            text = re.sub(re.escape(old), lambda _m, new=new: new, text, flags=re.IGNORECASE)
        paint_svg(pixmap, at_opacity(text, opacity).encode("utf-8"))    # ▸r/qicon-svg-engine
    _SVG_CACHE[key] = pixmap
    return pixmap.copy()


def device_pixmap(path, side, dpr, color_replacements=None, opacity=None):
    """One SVG at device resolution, `side` logical px; pass the painted widget's ratio. ▸r/screen-dpr"""
    pixmap = render_svg_pixmap(
        path, max(1, int(round(side * dpr))), color_replacements, opacity)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def menu_icon(name: str, widget=None):
    """A menu row's ui/<name>.svg icon; every menu's icons come from here."""
    return QtGui.QIcon(device_pixmap(
        amaze.package_file("ui", name + ".svg"),
        theme.ui_px(amazetheme.MENU_ICON), theme.screen_ratio(widget)))


class DesignedComboBox(QtWidgets.QComboBox):
    """A combo whose popup is the width of the box, not its longest item. ▸r/combo-popup-width"""

    def showPopup(self) -> None:
        super().showPopup()
        window = self.view().window()    # the WINDOW, not the view - the view alone is not the popup
        window.setFixedWidth(self.width())
        window.move(self.mapToGlobal(
            QtCore.QPoint(0, self.height())))


_DRAWN_PINS: set = set()    # every drawn node a pin has read, for the completeness walk ▸p/one-design-document


def drawn_pins() -> frozenset:
    """Every `(frame, kind, x, y)` a pin has read; the seam the completeness walk reads."""
    return frozenset(_DRAWN_PINS)


def forget_drawn_pins() -> None:
    _DRAWN_PINS.clear()


def _wear_drawn(widget, frame_key: str, kind: str, box, height: bool,
                grow: bool = False) -> None:
    """Wear one drawn box and record which node it was, keyed by its position in the frame."""
    if grow:
        widget.setMinimumWidth(theme.ui_px(box[2]))    # a floor: a wider font grows it, never clips it
    else:
        widget.setFixedWidth(theme.ui_px(box[2]))
    if height:
        widget.setFixedHeight(theme.ui_px(box[3]))
    widget.drawn_box = tuple(box)    # where it is drawn, for a caller placing several pinned widgets in one row
    _DRAWN_PINS.add((frame_key, kind, box[0], box[1]))


def pin_drawn(widget, frame_key: str, kind: str, text: str,
              height: bool = True, nth: int = 0, grow: bool = False) -> None:
    """Size `widget` to the drawn box for `<kind> ▸ <text>` in `frame_key`. ▸p/one-design-document"""
    found = amazetheme.drawn_repeats(frame_key, kind, text)
    if nth >= len(found):
        debug.event("ui", "no drawn box for this widget",
                    frame=frame_key, kind=kind, text=text, nth=nth)
        return
    _wear_drawn(widget, frame_key, kind, found[nth], height, grow)


def pin_drawn_stem(widget, frame_key: str, kind: str, stem: str,
                   height: bool = True) -> None:
    """Pin from the one drawn node whose text opens with `stem`; none or several pins nothing."""
    found = [box for (drawn_kind, text), box
             in amazetheme.drawn_boxes(frame_key).items()
             if drawn_kind == kind and text and text.startswith(stem)]
    if len(found) != 1:
        debug.event("ui", "no ONE drawn box opens with this stem",
                    frame=frame_key, kind=kind, stem=stem, found=len(found))
        return
    _wear_drawn(widget, frame_key, kind, found[0], height)


def drawn_kind(widget, frame_key: str) -> str:
    """The kind `frame_key` draws this widget as: its class name, or the nearest drawn base."""
    boxes = amazetheme.drawn_boxes(frame_key)
    for cls in type(widget).__mro__:
        if (cls.__name__, None) in boxes:
            return cls.__name__
    return type(widget).__name__


def pin_drawn_series(widgets, frame_key: str, kind: str,
                     height: bool = True) -> None:
    """Pin widgets of one kind from the frame's rects of that kind, drawn order against creation order."""
    drawn = amazetheme.drawn_repeats(frame_key, kind, None)
    widgets = tuple(widgets)
    if len(drawn) != len(widgets):
        debug.event("ui", "the drawn nodes and the built widgets differ in "
                    "number", frame=frame_key, kind=kind, drawn=len(drawn),
                    built=len(widgets))
    for widget, box in zip(widgets, drawn):
        _wear_drawn(widget, frame_key, kind, box, height)


def header_band(parent, text: str, height: int = amazetheme.HEADER_BAND_H,
                inset: int = amazetheme.HEADER_BAND_INSET):
    """The drawn header strip over the window's content; not the title bar. ▸p/one-design-document"""
    band = QtWidgets.QWidget(parent)
    band.setObjectName("amaze_header_band")
    band.setFixedHeight(theme.ui_px(height))
    band.setAutoFillBackground(True)
    palette = band.palette()
    palette.setColor(QtGui.QPalette.ColorRole.Window,
                     theme.color("surface_low"))
    band.setPalette(palette)

    row = QtWidgets.QHBoxLayout(band)
    row.setContentsMargins(theme.ui_px(inset), 0, theme.ui_px(inset), 0)
    label = QtWidgets.QLabel(text, band)
    label.setObjectName("amaze_header_band_text")
    font = QtGui.QFont(label.font())
    font.setPixelSize(theme.ui_px(amazetheme.HEADER_BAND_TEXT_PX))
    font.setBold(amazetheme.HEADER_BAND_TEXT_BOLD)
    label.setFont(font)
    ink = label.palette()
    ink.setColor(QtGui.QPalette.ColorRole.WindowText,
                 theme.color("text_bright"))
    label.setPalette(ink)
    row.addWidget(label)
    row.addStretch(1)
    return band


DISABLED_OPACITY = 0.5   # a self-painted widget's disabled opacity; every paintEvent override applies it by hand


def apply_disabled_opacity(painter, widget) -> None:
    """Dim what follows when `widget` is disabled - the one rule for every self-painted widget."""
    if not widget.isEnabled():
        painter.setOpacity(DISABLED_OPACITY)


class ClickSlider(QtWidgets.QSlider):
    """A self-painted slider that jumps to the click and locks onto a SNAP_MARK within SNAP_RADIUS."""

    LEFT_COLOR = QtGui.QColor(amazetheme.SLIDER_LEFT)   # the accent default; `set_accent_color` overrides it from prefs
    LEFT_WIDTH = theme.ui_px(3)
    RIGHT_COLOR = QtGui.QColor(theme.color_hex("field"))   # the groove follows the Houdini theme
    RIGHT_WIDTH = theme.ui_px(3)
    HANDLE_COLOR = QtGui.QColor(amazetheme.SLIDER_HANDLE)
    HANDLE_DIAMETER = theme.ui_px(11)   # 11: Qt centres an ellipse pen on the edge, so the border eats half its width inward
    HANDLE_BORDER_COLOR = QtGui.QColor(theme.color_hex("surface"))   # was #2d2d2d, the toolbar row's own grey, so the handle border reads as punched out of the bar
    HANDLE_BORDER_WIDTH = theme.ui_px(1)
    DEFAULT_VALUE = 128        # a size, unscaled, and one of the SNAP_MARKS so a drag can land on it
    SNAP_MARKS = (64, 128, 192, 256, 320, 384, 448, 512)
    SNAP_RADIUS = 5
    TICK_COLOR = QtGui.QColor(theme.color_hex("text_dim"))   # was #696969, byte-identical to this role
    TICK_PIXEL_SIZE = theme.ui_px(1)   # the snap-mark tick is pixel art: 5 squares of this size, centre and four neighbours
    TICK_PATTERN = (
        ".X.",
        "XXX",
        ".X.",
    )

    def __init__(self) -> None:
        super(ClickSlider, self).__init__()
        self.left_color = QtGui.QColor(self.LEFT_COLOR)   # instance-level, so the Accent Color pref overrides it per panel
        self.snap_marks = tuple(self.SNAP_MARKS)   # instance-level too; () gives a plain slider with no dots and no magnet zones
        self.stepped = False
        self._wheel_rest = 0
        self.actionTriggered.connect(self._step_action)

    @classmethod
    def nearest_mark(cls, value: float, marks=None) -> int:
        """The snap mark closest to `value`, the lower one on a tie."""
        return min(sorted(marks or cls.SNAP_MARKS), key=lambda mark: abs(mark - value))

    def drawn_marks(self) -> tuple:
        """The marks that get a dot: every snap mark strictly inside the range, never the two ends."""
        return tuple(mark for mark in self.snap_marks if self.minimum() < mark < self.maximum())

    def _mark_beyond(self, value: float, direction: int) -> int:
        """The next mark past `value` in `direction`, or the last mark that way."""
        marks = sorted(self.snap_marks)
        if direction > 0:
            return next((mark for mark in marks if mark > value), marks[-1])
        return next((mark for mark in reversed(marks) if mark < value), marks[0])

    def _step_action(self, action: int) -> None:
        """Step Size: a key's step lands on the next mark that way ▸r/slider-steps."""
        if not self.stepped or not self.snap_marks:
            return
        kind = QtWidgets.QAbstractSlider.SliderAction(action)
        if kind == QtWidgets.QAbstractSlider.SliderAction.SliderToMinimum:
            self.setSliderPosition(min(self.snap_marks))
        elif kind == QtWidgets.QAbstractSlider.SliderAction.SliderToMaximum:
            self.setSliderPosition(max(self.snap_marks))
        elif self.sliderPosition() != self.value():
            self.setSliderPosition(self._mark_beyond(
                self.value(), 1 if self.sliderPosition() > self.value() else -1))

    @debug.guarded("ClickSlider.wheelEvent")
    def wheelEvent(self, e: QtGui.QWheelEvent) -> None:
        if not self.stepped or not self.snap_marks:
            return super().wheelEvent(e)
        angle = e.angleDelta()
        delta = angle.y() if angle.y() else -angle.x()    # Qt's reading: up and right both grow
        if e.inverted():
            delta = -delta
        if delta * self._wheel_rest < 0:
            self._wheel_rest = 0
        self._wheel_rest += delta
        steps = int(self._wheel_rest / 120)
        self._wheel_rest -= steps * 120
        value = self.value()
        for _ in range(abs(steps)):
            value = self._mark_beyond(value, 1 if steps > 0 else -1)
        self.setValue(value)
        e.accept()

    def set_accent_color(self, color: QtGui.QColor) -> None:
        """Overrides the filled (left) segment color and repaints."""
        self.left_color = QtGui.QColor(color)
        self.update()

    def _x_for_value(self, value: float) -> float:
        """X for any value, inset by the handle radius at both ends; shared with `_handle_x`."""
        span = self.maximum() - self.minimum()
        fraction = 0.0 if span == 0 else (value - self.minimum()) / span
        radius = self.HANDLE_DIAMETER / 2
        usable = max(self.width() - 2 * radius, 0)
        return radius + fraction * usable

    def _handle_x(self) -> float:
        """X position of the handle centre for the current value."""
        return self._x_for_value(self.value())

    def _value_at_x(self, x: float) -> float:
        """Inverse of `_x_for_value`, with the same radius inset."""
        radius = self.HANDLE_DIAMETER / 2
        usable = max(self.width() - 2 * radius, 0)
        fraction = 0.0 if usable == 0 else (x - radius) / usable
        fraction = max(0.0, min(1.0, fraction))
        return self.minimum() + fraction * (self.maximum() - self.minimum())

    def _snap(self, value: float) -> int:
        """Lock onto the nearest SNAP_MARK within SNAP_RADIUS, else round and clamp the dragged value."""
        if self.stepped and self.snap_marks:
            return self.nearest_mark(value, self.snap_marks)
        for mark in self.snap_marks:
            if abs(value - mark) <= self.SNAP_RADIUS:
                return mark
        return int(max(self.minimum(), min(self.maximum(), round(value))))

    def _draw_pixel_dot(self, painter: QtGui.QPainter, cx: float, cy: float) -> None:
        """Draw TICK_PATTERN centred at (cx, cy) as filled squares, without antialiasing."""
        rows = self.TICK_PATTERN
        size = self.TICK_PIXEL_SIZE
        h = len(rows)
        w = len(rows[0])
        left = cx - (w * size) / 2.0
        top = cy - (h * size) / 2.0
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(self.TICK_COLOR)
        for row, line in enumerate(rows):
            for col, char in enumerate(line):
                if char == "X":
                    painter.drawRect(
                        QtCore.QRectF(left + col * size, top + row * size, size, size)
                    )

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        apply_disabled_opacity(painter, self)   # QSlider's own disabled rendering never runs here

        mid_y = self.height() / 2
        handle_x = self._handle_x()

        left_pen = QtGui.QPen(self.left_color)
        left_pen.setWidth(self.LEFT_WIDTH)
        left_pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
        painter.setPen(left_pen)
        painter.drawLine(QtCore.QPointF(0, mid_y), QtCore.QPointF(handle_x, mid_y))

        right_pen = QtGui.QPen(self.RIGHT_COLOR)
        right_pen.setWidth(self.RIGHT_WIDTH)
        right_pen.setCapStyle(QtCore.Qt.PenCapStyle.FlatCap)
        painter.setPen(right_pen)
        painter.drawLine(
            QtCore.QPointF(handle_x, mid_y), QtCore.QPointF(self.width(), mid_y)
        )

        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)   # OFF for the tick marks: crisp pixel-art squares, not smoothed geometry
        for mark in self.drawn_marks():
            self._draw_pixel_dot(painter, self._x_for_value(mark), mid_y)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        handle_pen = QtGui.QPen(self.HANDLE_BORDER_COLOR)
        handle_pen.setWidth(self.HANDLE_BORDER_WIDTH)
        painter.setPen(handle_pen)
        painter.setBrush(self.HANDLE_COLOR)
        radius = self.HANDLE_DIAMETER / 2
        painter.drawEllipse(QtCore.QPointF(handle_x, mid_y), radius, radius)

        painter.end()

    def _apply_mouse_value(self, x: float) -> None:
        """Click and drag: snap the value under the cursor and jump there, steps restored. ▸r/slider-steps"""
        value = self._snap(self._value_at_x(x))
        single, page = self.singleStep(), self.pageStep()
        try:
            stepsize = int(abs(self.value() - value))
            self.setPageStep(stepsize)
            self.setSingleStep(stepsize)
            self.setValue(value)
        finally:
            self.setSingleStep(single)
            self.setPageStep(page)

    @debug.guarded("ClickSlider.mousePressEvent")
    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.LeftButton:
            e.accept()
            self._apply_mouse_value(e.position().toPoint().x())   # rounded, never the raw sub-pixel QPointF
        else:
            return super().mousePressEvent(e)

    @debug.guarded("ClickSlider.mouseMoveEvent")
    def mouseMoveEvent(self, ev: QtGui.QMouseEvent) -> None:
        ev.accept()
        self._apply_mouse_value(ev.position().toPoint().x())   # the press path's rounding, so a click and a drag to the same pixel still settle on the same value


class ThinProgressBar(QtWidgets.QWidget):
    """A minimal hand-painted progress bar - no text, just a filled strip against a track."""

    FILL_COLOR = ClickSlider.LEFT_COLOR
    TRACK_COLOR = QtGui.QColor(amazetheme.SLIDER_TRACK)   # its own constant, not ClickSlider.RIGHT_COLOR
    BAR_HEIGHT = theme.ui_px(4)

    def __init__(self) -> None:
        super().__init__()
        self._done = 0
        self._total = 0
        self.fill_color = QtGui.QColor(self.FILL_COLOR)   # instance-level, so the Accent Color pref overrides it per panel
        self.setFixedHeight(self.BAR_HEIGHT)

    def set_accent_color(self, color: QtGui.QColor) -> None:
        self.fill_color = QtGui.QColor(color)   # overrides the fill colour and repaints, the same verb ClickSlider.set_accent_color carries
        self.update()

    def set_progress(self, done: int, total: int) -> None:
        self._done = done
        self._total = total
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.TRACK_COLOR)
        if self._total > 0:
            fraction = min(max(self._done / self._total, 0.0), 1.0)
            fill_w = int(self.width() * fraction)
            if fill_w > 0:
                painter.fillRect(0, 0, fill_w, self.height(), self.fill_color)
        painter.end()


class GridHeaderView(QtWidgets.QHeaderView):
    """The Grid table's header: the sort arrow takes room only in the column that has one."""

    def sectionSizeFromContents(self, logicalIndex):
        size = super().sectionSizeFromContents(logicalIndex)
        if (not self.isSortIndicatorShown()
                or logicalIndex == self.sortIndicatorSection()):
            return size
        option = QtWidgets.QStyleOptionHeader()
        self.initStyleOption(option)
        margin = self.style().pixelMetric(
            QtWidgets.QStyle.PixelMetric.PM_HeaderMargin, option, self)
        return QtCore.QSize(
            max(size.width() - size.height() - margin, 1), size.height())


def _event_point(event) -> QtCore.QPointF:
    """A mouse event's widget-local position for a QRectF hit test, rounded to whole pixels."""
    return QtCore.QPointF(event.position().toPoint())   # `toPoint` rounds half away from zero, as `pos()` did


class SectionTabBar(QtWidgets.QWidget):
    """The full-width section tab strip below the toolbar, hand-painted, one text tab per section."""

    segmentClicked = QtCore.Signal(str)   # the key of the tab that just became checked, emitted only on an actual change
    cancelClicked = QtCore.Signal()   # the Cancel chip; panel.set_conversion_bar_visible is the one driver

    CANCEL_LABEL = "Cancel"

    _DRAWN = amazetheme.drawn_tabs()    # every size but the two radii is S01's ▸r/tabs-from-frame
    HEIGHT = theme.ui_px(_DRAWN["height"])
    TRAY_HEIGHT = theme.ui_px(_DRAWN["tray_height"])
    TRAY_RADIUS = theme.ui_px(4)
    TRAY_LEFT = theme.ui_px(_DRAWN["tray_left"])
    CHIP_HEIGHT = theme.ui_px(_DRAWN["chip_height"])
    CHIP_RADIUS = theme.ui_px(4)
    CHIP_RING_W = theme.ui_px(1)
    CHIP_PAD_X = theme.ui_px(_DRAWN["chip_pad"])
    CHIP_GAP = theme.ui_px(_DRAWN["chip_gap"])
    CHIP_INSET = theme.ui_px(_DRAWN["chip_inset"])

    STRIP_COLOR = theme.color("surface")   # theme-derived; matches the toolbar row
    TRAY_COLOR = theme.color("surface_low")   # matches the category backdrop, so the tray reads as connected to the sidebar below
    CHIP_FILL = theme.color("tab_chip")    # an ACCENT shade: Houdini's own example panel drives its checked/tab states from accent variants
    CHIP_RING = theme.color("tab_ring")
    TEXT_SELECTED = theme.color("text_bright")
    TEXT_UNSELECTED = theme.color("text")
    TEXT_HOVER = QtGui.QColor(amazetheme.TAB_TEXT_HOVER)   # tab hover text, matching the toolbar icons' hover colour

    def __init__(self, segments: list) -> None:
        """segments: list of (key, label) pairs, left to right."""
        super().__init__()
        self._segments = list(segments)
        self._checked_key = None
        self._hover_key = None
        self._cancel_visible = False
        self._cancel_hover = False
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )

    def setChecked(self, key: str, emit: bool = True) -> None:
        """Select a tab, emitting `segmentClicked` only on a change; `emit=False` sets the initial state."""
        if key != self._checked_key:
            self._checked_key = key
            self.update()
            if emit:
                self.segmentClicked.emit(key)

    def _chip_rects(self) -> list:
        """[((key, label), QRectF), ...]: each tab's chip rect and hit target, in the current font."""
        metrics = self.fontMetrics()
        tray_top = self.height() - self.TRAY_HEIGHT
        chip_y = tray_top + (self.TRAY_HEIGHT - self.CHIP_HEIGHT) / 2.0
        x = self.TRAY_LEFT + self.CHIP_INSET
        rects = []
        for key, label in self._segments:
            w = metrics.horizontalAdvance(label) + 2 * self.CHIP_PAD_X
            rects.append(
                ((key, label), QtCore.QRectF(x, chip_y, w, self.CHIP_HEIGHT))
            )
            x += w + self.CHIP_GAP
        return rects

    def _key_at(self, pos) -> str | None:
        for (key, _), rect in self._chip_rects():
            if rect.contains(QtCore.QPointF(pos)):
                return key
        return None

    def set_cancel_visible(self, visible: bool) -> None:
        """Show or hide the Cancel chip; call through panel.set_conversion_bar_visible."""
        visible = bool(visible)
        if visible != self._cancel_visible:
            self._cancel_visible = visible
            if not visible:
                self._cancel_hover = False
            self.update()

    def cancel_visible(self) -> bool:
        return self._cancel_visible

    def _cancel_rect(self, rects=None):
        """The Cancel chip's rect, or None while hidden or when the strip is too narrow for it."""
        if not self._cancel_visible:
            return None
        metrics = self.fontMetrics()
        chip_y = (self.height() - self.CHIP_HEIGHT) / 2.0   # centred on the strip's full height, not the tray's
        width = metrics.horizontalAdvance(self.CANCEL_LABEL) \
            + 2 * self.CHIP_PAD_X
        x = self.width() - self.TRAY_LEFT - self.CHIP_INSET - width
        if rects is None:
            rects = self._chip_rects()
        tabs_right = rects[-1][1].right() if rects else 0
        if x < tabs_right + self.CHIP_GAP:
            return None
        return QtCore.QRectF(x, chip_y, width, self.CHIP_HEIGHT)

    def sizeHint(self) -> QtCore.QSize:
        rects = self._chip_rects()
        right = rects[-1][1].right() + self.CHIP_INSET if rects else 0
        return QtCore.QSize(int(right) + self.TRAY_LEFT, self.HEIGHT)

    @debug.guarded("SectionTabBar.mousePressEvent")
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        point = _event_point(event)
        cancel = self._cancel_rect()
        if cancel is not None and cancel.contains(point):
            self.cancelClicked.emit()
            return
        key = self._key_at(point)
        if key is not None:
            self.setChecked(key)

    @debug.guarded("SectionTabBar.mouseMoveEvent")
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        point = _event_point(event)
        key = self._key_at(point)
        cancel = self._cancel_rect()
        over_cancel = cancel is not None and cancel.contains(point)
        if key != self._hover_key or over_cancel != self._cancel_hover:
            self._hover_key = key
            self._cancel_hover = over_cancel
            if key is not None or over_cancel:   # a pointing hand over a tab or the Cancel chip only
                self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            else:
                self.unsetCursor()
            self.update()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        if self._hover_key is not None or self._cancel_hover:
            self._hover_key = None
            self._cancel_hover = False
            self.unsetCursor()
            self.update()

    def _tray_rect(self, rects=None):
        """The tray behind the tabs, flush with the strip's bottom, or None with no tabs."""
        if rects is None:
            rects = self._chip_rects()
        if not rects:
            return None
        top = self.height() - self.TRAY_HEIGHT
        right = rects[-1][1].right() + self.CHIP_INSET
        return QtCore.QRectF(self.TRAY_LEFT, top, right - self.TRAY_LEFT, self.TRAY_HEIGHT)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), self.STRIP_COLOR)

        rects = self._chip_rects()
        tray = self._tray_rect(rects)
        if tray is not None:
            tray_path = QtGui.QPainterPath()
            tray_path.addRoundedRect(    # one radius past the bottom, so only the top corners round
                tray.adjusted(0, 0, 0, self.TRAY_RADIUS),
                self.TRAY_RADIUS,
                self.TRAY_RADIUS,
            )
            painter.fillPath(tray_path, self.TRAY_COLOR)

        for (key, label), rect in rects:
            checked = key == self._checked_key
            if checked:
                chip_path = QtGui.QPainterPath()
                chip_path.addRoundedRect(rect, self.CHIP_RADIUS, self.CHIP_RADIUS)
                painter.fillPath(chip_path, self.CHIP_FILL)
                draw_ring(painter, rect, self.CHIP_RING, self.CHIP_RING_W,
                          self.CHIP_RADIUS)
            if checked:
                painter.setPen(self.TEXT_SELECTED)
            elif key == self._hover_key:
                painter.setPen(self.TEXT_HOVER)
            else:
                painter.setPen(self.TEXT_UNSELECTED)
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, label)

        cancel = self._cancel_rect(rects)
        if cancel is not None:   # ring only, no fill: a chip that reads as a BUTTON beside tabs that read as tabs
            draw_ring(painter, cancel, self.CHIP_RING, self.CHIP_RING_W,
                      self.CHIP_RADIUS)
            painter.setPen(self.TEXT_HOVER if self._cancel_hover
                           else self.TEXT_UNSELECTED)
            painter.drawText(cancel, QtCore.Qt.AlignmentFlag.AlignCenter,
                             self.CANCEL_LABEL)

        painter.end()


def draw_chip(painter, rect, fill, ring, inner_border=None):
    """Draw the design's rounded button chip: fill, a light outer ring, optionally a darker inner one."""
    ring_w = theme.ui_px(1)
    draw_ring(painter, rect, ring, ring_w, theme.ui_px(5), fill)
    if inner_border is not None:
        inner = QtCore.QRectF(rect).adjusted(ring_w, ring_w, -ring_w, -ring_w)
        draw_ring(painter, inner, inner_border, ring_w, theme.ui_px(4))


def draw_ring(painter, rect, ink, width, radius,
              fill=QtCore.Qt.BrushStyle.NoBrush) -> None:
    """A rounded ring `width` wide drawn wholly inside `rect`, over `fill`."""
    half = width / 2.0
    painter.setPen(QtGui.QPen(ink, width))
    painter.setBrush(fill)
    painter.drawRoundedRect(
        QtCore.QRectF(rect).adjusted(half, half, -half, -half), radius, radius)


class ToggleSwitch(QtWidgets.QCheckBox):
    """A hand-painted pill toggle switch, a drop-in for QCheckBox with the same signals and API."""

    TRACK_W = 23    # 46x30 rendered px, halved by the 2x rule - the design's fatter revision over the first 52x26 pass
    TRACK_H = 15
    KNOB_INSET = 2
    GAP = 8

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QtCore.QSize:
        fm = QtGui.QFontMetrics(self.font())
        w = (
            theme.ui_px(self.TRACK_W)
            + (theme.ui_px(self.GAP) + fm.horizontalAdvance(self.text())
               + theme.ui_px(2)     # the trailing slack is the text's; a textless switch is drawn flush
               if self.text() else 0)
        )
        h = max(theme.ui_px(self.TRACK_H) + theme.ui_px(4),
                fm.height() + theme.ui_px(2))
        return QtCore.QSize(w, h)

    def minimumSizeHint(self) -> QtCore.QSize:
        return self.sizeHint()

    def hitButton(self, pos: QtCore.QPoint) -> bool:
        # The whole row (track + text) toggles, like a checkbox's text.
        return self.rect().contains(pos)

    def changeEvent(self, event: QtCore.QEvent) -> None:
        if event.type() == QtCore.QEvent.Type.EnabledChange:    # the pointing hand promises a click; a disabled switch must not wear it
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor
                           if self.isEnabled()
                           else QtCore.Qt.CursorShape.ArrowCursor)
        super().changeEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        apply_disabled_opacity(p, self)    # a full paintEvent override dims by hand or a disabled switch reads as simply not working
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        tw = theme.ui_px(self.TRACK_W)
        th = theme.ui_px(self.TRACK_H)
        y = (self.height() - th) / 2.0
        ring_w = theme.ui_px(1.0)   # the track below is inset by half this, so the scaled border pen renders crisp
        half = ring_w / 2.0
        track = QtCore.QRectF(half, y + half, tw - ring_w, th - ring_w)
        radius = track.height() / 2.0
        if self.isChecked():
            knob = theme.color("star")   # the theme highlight: knob at full strength, track a dimmed version of it
            fill = QtGui.QColor(knob).darker(260)
        else:
            fill = theme.color("field")
            knob = theme.color("text_dim")
        p.setPen(QtGui.QPen(fill.darker(140), ring_w))
        p.setBrush(fill)
        p.drawRoundedRect(track, radius, radius)
        inset = theme.ui_px(self.KNOB_INSET)
        d = th - 2 * inset
        kx = (tw - inset - d) if self.isChecked() else inset
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(knob)
        p.drawEllipse(QtCore.QRectF(kx, y + inset, d, d))
        if self.text():
            p.setPen(self.palette().color(QtGui.QPalette.ColorRole.WindowText))
            p.drawText(
                QtCore.QRectF(
                    tw + theme.ui_px(self.GAP), 0,
                    self.width() - tw - theme.ui_px(self.GAP), self.height(),
                ),
                QtCore.Qt.AlignmentFlag.AlignVCenter
                | QtCore.Qt.AlignmentFlag.AlignLeft,
                self.text(),
            )


def icon_rect(button, side: int) -> QtCore.QRect:
    """Where a self-painted toolbar button draws its `side` icon: centred, one offset both ways."""
    offset = (button.width() - side) // 2
    return QtCore.QRect(offset, offset, side, side)


class IconMenuButton(QtWidgets.QWidget):
    """The toolbar's hand-painted icon button that pops a QMenu, its hover cleared on `aboutToHide`."""

    IDLE_BODY = amazetheme.MENU_IDLE_BODY
    LIT_BODY = amazetheme.MENU_LIT_BODY
    IDLE_TRIANGLE = amazetheme.MENU_IDLE_TRIANGLE
    LIT_TRIANGLE = amazetheme.MENU_LIT_TRIANGLE
    PUNCH_OUT = amazetheme.MENU_PUNCH_OUT
    OPEN_PUNCH_OUT = amazetheme.MENU_OPEN_PUNCH_OUT
    HOVER_PUNCH_OUT = amazetheme.MENU_HOVER_PUNCH_OUT
    CHIP_FILL = QtGui.QColor(amazetheme.MENU_CHIP_FILL)
    CHIP_BORDER = QtGui.QColor(amazetheme.MENU_CHIP_BORDER)
    CHIP_RING = QtGui.QColor(amazetheme.MENU_CHIP_RING)
    HOVER_CHIP_FILL = QtGui.QColor(amazetheme.MENU_HOVER_CHIP_FILL)
    HOVER_CHIP_RING = QtGui.QColor(amazetheme.MENU_HOVER_CHIP_RING)
    TEXT_COLOR = QtGui.QColor(amazetheme.MENU_TEXT)
    RENDER_SCALE = 4    # icons render at 4x the icon size and paint scaled down

    def __init__(
        self,
        menu: QtWidgets.QMenu | None,
        svg_path: str,
        icon_size: int | None = None,     # DESIGN px, scaled here; None is B01's ▸r/toolbar-from-frame
        button_size: int | None = None,
        on_click=None,           # with menu=None a click calls this instead of popping a menu; no menu triangle
        fallback_label: str = "",
        name: str = "",          # its object name, which B01 draws it under
    ) -> None:
        super().__init__()
        self.setObjectName(name)
        self._menu = menu
        self._on_click = on_click
        self._hovered = False
        self._open = False
        drawn = amazetheme.drawn_toolbar()
        if icon_size is None:
            icon_size = drawn["icons"].get(name, drawn["menu_icon"])
        self._icon_size = theme.ui_px(icon_size)
        button_size = theme.ui_px(drawn["button"] if button_size is None else button_size)
        self.setFixedSize(button_size, button_size)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        render_size = self._icon_size * self.RENDER_SCALE
        self._idle_pm = render_svg_pixmap(svg_path, render_size)
        self._hover_pm = render_svg_pixmap(
            svg_path,
            render_size,
            {
                self.IDLE_BODY: self.LIT_BODY,
                self.IDLE_TRIANGLE: self.LIT_TRIANGLE,
                self.PUNCH_OUT: self.HOVER_PUNCH_OUT,
            },
        )
        self._open_pm = render_svg_pixmap(
            svg_path,
            render_size,
            {
                self.IDLE_BODY: self.LIT_BODY,
                self.IDLE_TRIANGLE: self.LIT_TRIANGLE,
                self.PUNCH_OUT: self.OPEN_PUNCH_OUT,
            },
        )
        self._fallback_text = (   # a missing asset degrades to the menu title or the given label, drawn as text
            "" if (svg_path and os.path.exists(svg_path))
            else (menu.title() if menu is not None else fallback_label)
        )
        if menu is not None:
            menu.aboutToHide.connect(self._on_menu_closed)

    def set_menu(self, menu) -> None:
        """Swap the popped menu - the stuck-highlight guard's `aboutToHide` hook follows it."""
        if menu is self._menu:
            return
        if self._menu is not None:
            try:
                self._menu.aboutToHide.disconnect(self._on_menu_closed)
            except (RuntimeError, TypeError):
                pass
        self._menu = menu
        if menu is not None:
            menu.aboutToHide.connect(self._on_menu_closed)

    def menu(self):
        return self._menu

    def _on_menu_closed(self) -> None:
        self._open = False
        self._hovered = self.rect().contains(   # the cursor is read directly: Qt drops hover/leave events across a popup closing
            self.mapFromGlobal(QtGui.QCursor.pos())
        )
        self.update()

    @debug.guarded("IconMenuButton.mousePressEvent")
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        if self._menu is None:
            if self._on_click is not None:
                self._on_click()
            return
        self._open = True
        self.update()
        self._menu.popup(self.mapToGlobal(QtCore.QPoint(0, self.height())))

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform, True
        )
        apply_disabled_opacity(painter, self)   # a bare QWidget gets no disabled treatment from Qt either
        if self._open:
            draw_chip(   # the design's CLICKED chip: blue fill, light outer ring, darker border ring just inside it
                painter, self.rect(), self.CHIP_FILL, self.CHIP_RING,
                self.CHIP_BORDER,
            )
        elif self._hovered:
            draw_chip(   # the design's HOVER chip, the grey sibling: fill and light outer ring only, no inner border ring
                painter, self.rect(), self.HOVER_CHIP_FILL,
                self.HOVER_CHIP_RING,
            )
        if self._fallback_text:
            painter.setPen(self.TEXT_COLOR)
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignmentFlag.AlignCenter,
                self._fallback_text,
            )
        else:
            if self._open:
                pm = self._open_pm
            elif self._hovered:
                pm = self._hover_pm
            else:
                pm = self._idle_pm
            painter.drawPixmap(icon_rect(self, self._icon_size), pm)
        painter.end()


class ChipToggleButton(QtWidgets.QToolButton):
    """A self-painted checkable QToolButton carrying IconMenuButton's own hover chip."""

    RENDER_SCALE = 4

    def __init__(self, button_size: int | None = None, icon_size: int | None = None,
                 name: str = "") -> None:
        super().__init__()
        self.setObjectName(name)    # B01 draws it under this name
        self.setCheckable(True)
        drawn = amazetheme.drawn_toolbar()    # DESIGN px, scaled here; None is B01's ▸r/toolbar-from-frame
        button_size = theme.ui_px(drawn["button"] if button_size is None else button_size)
        self.setFixedSize(button_size, button_size)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        if icon_size is None:
            icon_size = drawn["icons"].get(name, drawn["chip_icon"])
        self._icon_size = theme.ui_px(icon_size)
        self._hovered = False
        self._pms = {}

    DISABLED_OPACITY = DISABLED_OPACITY   # the module-level value, also exposed on the class

    def set_art(self, off_path, on_path=None, lighten_on_hover=True,
                recolour=None, recolour_on=None):
        """The one way a chip gets its four states: the art as drawn at rest, lightened on hover."""
        size = self._icon_size * self.RENDER_SCALE
        base = dict(recolour or {})
        on_map = dict(recolour_on) if recolour_on else base   # the on state may recolour differently from the off state
        lit = dict(base)
        lit[IconMenuButton.IDLE_BODY] = IconMenuButton.LIT_BODY

        def art(path, tints):
            return render_svg_pixmap(path, size, tints) if tints \
                else render_svg_pixmap(path, size)

        off = art(off_path, base)
        on = art(on_path or off_path, on_map)
        self.set_state_pixmaps(
            off,
            on,
            art(off_path, lit) if lighten_on_hover else off,
            (art(on_path or off_path, lit) if lighten_on_hover else on),
        )

    def set_state_pixmaps(self, off_pm, on_pm, hover_off_pm, hover_on_pm):
        """Pixmaps keyed by (checked, hovered)."""
        self._pms = {
            (False, False): off_pm,
            (True, False): on_pm,
            (False, True): hover_off_pm,
            (True, True): hover_on_pm,
        }
        self.update()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform, True
        )
        if self._hovered and self.isEnabled():
            draw_chip(
                painter, self.rect(), IconMenuButton.HOVER_CHIP_FILL,
                IconMenuButton.HOVER_CHIP_RING,
            )
        apply_disabled_opacity(painter, self)   # a disabled chip paints dimmed
        pm = self._pms.get((self.isChecked(), self._hovered))
        if pm is not None:
            painter.drawPixmap(icon_rect(self, self._icon_size), pm)
        painter.end()




class SideIconPinner(QtCore.QObject):
    """Keep an icon QLabel pinned to one edge of a line edit, inset, centred, following its resizes."""

    def __init__(
        self,
        line_edit: QtWidgets.QLineEdit,
        icon_label: QtWidgets.QLabel,
        margin: int,
        side: str = "right",
    ) -> None:
        super().__init__(line_edit)
        self._line_edit = line_edit
        self._icon_label = icon_label
        self._margin = margin
        self._side = side
        line_edit.installEventFilter(self)
        self.reposition()

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if obj is self._line_edit and event.type() == QtCore.QEvent.Type.Resize:
            self.reposition()
        return False

    def reposition(self) -> None:
        w = self._icon_label.width()
        h = self._icon_label.height()
        if self._side == "left":
            x = self._margin
        else:
            x = self._line_edit.width() - self._margin - w
        y = (self._line_edit.height() - h) // 2
        self._icon_label.move(max(x, 0), max(y, 0))

def load_ui(path: str, *custom_widgets):
    """The `.ui` loader: raises OSError naming a file that will not open or parse. ▸r/ui-loader"""
    from PySide6 import QtUiTools

    loader = QtUiTools.QUiLoader()
    for widget in custom_widgets:
        loader.registerCustomWidget(widget)    # the .ui names these, so they must be registered BEFORE the load
    handle = QtCore.QFile(path)
    if not handle.open(QtCore.QFile.OpenModeFlag.ReadOnly):    # False for a missing file ▸r/ui-loader
        raise OSError("the interface file could not be opened: %s" % path)
    try:
        built = loader.load(handle)
    except RuntimeError as exc:    # a malformed .ui raises, with no filename in the message ▸r/ui-loader
        raise OSError("the interface file did not parse: %s (%s)"
                      % (path, exc))
    finally:
        handle.close()
    if built is None:
        raise OSError("the interface file produced no widget: %s" % path)
    return built


def pick_color(initial, parent=None, title="Select Color"):
    """One colour picker for the app, Houdini's or else Qt's under a Qt modal; a QColor or None."""
    if isinstance(initial, str):
        initial = QtGui.QColor(initial) if initial else QtGui.QColor()

    use_native = False
    try:
        import hou
        use_native = (hasattr(hou, "ui")
                      and QtWidgets.QApplication.activeModalWidget()
                      is None)
    except ImportError:
        pass

    if use_native:
        import hou
        seed = None
        if initial is not None and initial.isValid():
            seed = hou.Color((initial.redF(), initial.greenF(),
                              initial.blueF()))
        try:
            chosen = hou.ui.selectColor(initial_color=seed)
        except hou.Error as exc:
            debug.event("ui", "houdini colour picker failed - falling "
                        "back to Qt", error=str(exc))
            chosen = None
            use_native = False
        else:
            if chosen is None:
                return None                       # cancelled
            r, g, b = chosen.rgb()
            return QtGui.QColor.fromRgbF(
                max(0.0, min(1.0, r)), max(0.0, min(1.0, g)),
                max(0.0, min(1.0, b)))

    picked = QtWidgets.QColorDialog.getColor(
        initial if initial is not None and initial.isValid()
        else QtGui.QColor(amazetheme.SIDEBAR_PICKER_START),
        parent, title)
    return picked if picked.isValid() else None


class HeldPane(QtWidgets.QWidget):
    """A splitter side pane that owns its width: the remembered dragged width, else the design width."""

    def __init__(self, preferences, pref_key, default_px, parent=None):
        super().__init__(parent)
        self._preferences = preferences
        self._pref_key = pref_key
        self._default_px = default_px

    def sizeHint(self):
        hint = super().sizeHint()
        remembered = int(getattr(
            self._preferences, self._pref_key, 0) or 0)
        return QtCore.QSize(remembered or self._default_px,
                            hint.height())
