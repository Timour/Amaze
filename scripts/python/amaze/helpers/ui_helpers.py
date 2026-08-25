"""Shared UI elements: the drag tag, the ui/ asset and SVG readers, and the hand-painted widgets the panel is built from."""

import contextlib
import os

from PySide6 import QtWidgets, QtCore, QtGui, QtSvg, QtSvgWidgets

from amaze.core import debug
from amaze.helpers import theme


@contextlib.contextmanager
def relayout(*models):
    """Wrap a WHOLESALE change to one or more models' contents; NOT a structural insert or removal, whose own begin/end contract this would layer over and hand the proxy dangling persistent indexes at the closing signal - a native segfault (sections.py `delete_rows`)."""
    live = [model for model in models if model is not None]
    for model in live:
        model.layoutAboutToBeChanged.emit()
    try:
        yield              # the pair MUST close even when the body raises, or every attached view stays mid-layout-change for the rest of the session with its persistent indexes never restored
    finally:
        for model in reversed(live):   # reverse order, so the innermost model is released first - the mirror of how they were announced
            model.layoutChanged.emit()


DRAG_TAG_STYLE = (     # the drag name tag, shared by BOTH the self-managed drag's floating label (cop/color/code) and the native drags' pixmap (materials), so every drag looks identical though the mechanisms differ
    "background-color: #2d2d2d; color: #e6e6e6;"
    " border: 1px solid #555555; padding: %dpx %dpx;"
    % (theme.ui_px(2), theme.ui_px(8))
)


def name_tag_pixmap(name: str) -> QtGui.QPixmap:
    """The drag tag as a PIXMAP - the drag picture for the native drags, matching the self-managed system's floating label through the shared `DRAG_TAG_STYLE`."""
    label = QtWidgets.QLabel(str(name))
    label.setStyleSheet(DRAG_TAG_STYLE)
    label.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
    label.adjustSize()
    label.ensurePolished()
    return label.grab()


_svg_image_cache: dict = {}    # rendered ui/ SVGs keyed by (name, side); a stored False means tried and failed, so a missing asset is not re-rendered every batch


def svg_image(name: str, side: int = 512):
    """A ui/ SVG rendered once as a square QImage, or None; the ONE owner of that render, and it resolves its path through `ui_asset` like every other asset lookup in the package."""
    key = (name, side)
    cached = _svg_image_cache.get(key)
    if cached is None:
        image = None
        path = ui_asset(name)
        try:
            if os.path.exists(path):
                from PySide6 import QtSvg

                renderer = QtSvg.QSvgRenderer(path)
                if renderer.isValid():
                    img = QtGui.QImage(
                        side, side, QtGui.QImage.Format.Format_ARGB32)
                    img.fill(QtCore.Qt.GlobalColor.transparent)
                    painter = QtGui.QPainter(img)
                    renderer.render(painter)
                    painter.end()
                    image = img
            else:
                debug.event("ui", "ui asset missing", name=name, path=path)
        except Exception as exc:                          # noqa: BLE001
            debug.event("ui", "ui asset not rendered",     # event, not note: these are shipped SVGs, whatever wanted one still draws without it, and there is nothing a user could do about it
                        name=name, error=str(exc))
        cached = image if image is not None else False
        _svg_image_cache[key] = cached
    return cached or None


def forget_svg_images() -> None:
    """Drop the rendered-SVG cache - the NAMED test-isolation seam, so no test reaches into the module dict and pins its spelling."""
    _svg_image_cache.clear()


def ui_asset(name: str) -> str:
    """The absolute path of a ui/ asset, $AMAZE first: saved assets on disk carry literal `$AMAZE/...` parameter values, so the variable is a contract with the user's data and the plugin resolves its own resources the same way."""
    root = ""
    try:
        import hou
        root = hou.getenv("AMAZE") or hou.getenv("ASSETLIB") or ""
    except Exception:                                    # noqa: BLE001
        root = ""                  # the module-relative return below is for a genuinely undefined $AMAZE only - tests, and the offline tools that run without hou; preferring it would let a dev tree and an installed $AMAZE disagree silently
    if root:
        candidate = os.path.join(
            root, "scripts", "python", "amaze", "ui", name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "ui", name)


def live_current_index(view):
    """A view's current index, RE-DERIVED from its live model, or None - never hand a STORED index back through a proxy, because `isValid()` says nothing about whether the proxy's row mapping still contains it. ▸r/model-contracts"""
    if view is None:
        return None
    model = view.model()
    if model is None:
        return None
    index = view.currentIndex()
    if not index.isValid():
        return None
    if index.model() is not model:   # it may predate a model swap entirely (a section switch rebuilds these views); mapping it through the CURRENT proxy is the bug the drag path hit, where an online index read through the material proxy dragged whichever local material sat at that row
        return None
    try:
        rows = model.rowCount(QtCore.QModelIndex())   # ROW ONLY, never columnCount - on a QAbstractListModel subclass that is a PRIVATE, uncallable method, and the column of a view's own currentIndex is in bounds by construction anyway ▸r/model-contracts
    except TypeError:
        return None                  # a model with some other signature; refusing is safe, because the caller's fallback is "no selection" and never a wrong one
    if index.row() >= rows:
        return None
    return model.index(index.row(), 0)   # COLUMN 0, not the clicked cell: over the list-mode table the current index keeps whichever column was clicked, and the grid models answer roles only on the owning one ▸r/row-selection


def _screen_dpr() -> float:
    """The PRIMARY screen's device-pixel ratio, 1.0 when headless - deliberately app-wide, because a tooltip is built at setToolTip time, before anyone knows which monitor it will pop on. ▸r/screen-dpr"""
    from PySide6 import QtGui as _QtGui

    screen = _QtGui.QGuiApplication.primaryScreen()
    if screen is None:
        return 1.0
    return float(screen.devicePixelRatio()) or 1.0


def tooltip_text(text: str, max_px: int = 800) -> str:
    """A tooltip that never draws wider than `max_px` REAL screen pixels - Qt renders a PLAIN-text tooltip as one line however long, and a width-capped table is the one rich-text width control QTextDocument honours; the cap is in DEVICE pixels, a ruler on a screenshot."""
    from PySide6 import QtWidgets as _QtWidgets

    cap = max(1, int(max_px / _screen_dpr()))
    metrics = QtGui.QFontMetrics(_QtWidgets.QToolTip.font())
    if metrics.horizontalAdvance(text) <= cap:
        return text
    import html

    body = html.escape(text).replace("\n", "<br>")   # rich text eats newlines, and the multi-paragraph tooltips keep their breaks or become one undifferentiated wall
    return '<qt><table width="%d"><tr><td>%s</td></tr></table></qt>' % (
        cap, body)


_SVG_CACHE: dict = globals().get("_SVG_CACHE", {})   # rasterised SVGs keyed by (path, size, tint), read back out of `globals()` because panel.py reloads this module on every panel open and a plain literal would throw the cache away exactly when a reopen is paying for it


def render_svg_pixmap(path, size, color_replacements=None):
    """An SVG rendered onto a transparent square QPixmap, with literal colour strings swapped first; a missing file gives a blank pixmap, and what comes back is always a COPY, because QPixmap is mutable and a caller that paints into it would poison every later ask for the same icon."""
    tint = tuple(sorted((color_replacements or {}).items()))
    key = (path, int(size), tint)
    cached = _SVG_CACHE.get(key)
    if cached is not None:
        return cached.copy()
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        for old, new in (color_replacements or {}).items():
            text = text.replace(old, new)
        painter = QtGui.QPainter(pixmap)
        QtSvg.QSvgRenderer(QtCore.QByteArray(text.encode("utf-8"))).render(painter)   # QSvgRenderer onto our OWN transparent pixmap: ONE size, dpr and cache rule for every icon in the package - not because QIcon's engine is broken, which was measured and is not ▸r/qicon-svg-engine
        painter.end()
    _SVG_CACHE[key] = pixmap
    return pixmap.copy()


def device_pixmap(path, side, dpr, color_replacements=None):
    """One SVG rasterised at DEVICE resolution with the ratio stamped, so it draws `side` logical pixels wide and stays sharp on a Retina screen. Pass the ratio of the widget being painted, never the primary's. ROUND, do not truncate: `QPixmap` truncates a float size, which loses a device pixel at every fractional ratio. ▸r/screen-dpr"""
    pixmap = render_svg_pixmap(
        path, max(1, int(round(side * dpr))), color_replacements)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


class DesignedDialog(QtWidgets.QDialog):
    """A dialog in the shape the HTML designs describe: a dark header band carrying icon, subtitle, title and kind line, over a body column inset equally both sides, ending in two buttons that fill it. Every constant is the design's number HALVED and goes through `theme.ui_px` like all chrome, the trailing figure being what the page says; nothing here reads a screen. ▸p/designed-dialog, ▸r/houdini-ui-scale"""

    FRAME = (256, 218)      # the design's 512 x 435
    HEADER_H = 66           # 132
    INSET = 18              # 35, both sides, leaving a 220-wide body column
    TEXT_X = 66             # 131, where the header's three lines start
    FIRST_FIELD_Y = 82      # 163, the first field's top
    HEADER_BG = theme.color_hex("surface_low")   # the two SURFACES follow Houdini's theme, because a value kept equal to another value by hand is a value that drifts
    BODY_BG = theme.color_hex("surface")
    LABEL_INK = "#93b9e7"   # the INK stays literal: this and TITLE_INK are not theme colours but the design's own answer
    TITLE_INK = "#dddcdd"
    FIELD_H = 30            # 60
    BUTTON = (101, 21)      # 202 x 42
    BUTTON_GAP = 19         # 38
    RADIUS = 5              # 10
    SUBTITLE_PX, TITLE_PX, KIND_PX, LABEL_PX, BUTTON_PX = 12, 16, 12, 10, 12

    def __init__(self, parent=None, title="", subtitle="", kind="",
                 icon="") -> None:
        super().__init__(parent)
        self.setFixedSize(theme.ui_px(self.FRAME[0]),
                          theme.ui_px(self.FRAME[1]))
        self.setStyleSheet("QDialog { background: %s; }" % self.BODY_BG)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QtWidgets.QWidget(self)
        header.setFixedHeight(theme.ui_px(self.HEADER_H))
        header.setStyleSheet("background: %s;" % self.HEADER_BG)
        outer.addWidget(header)

        if icon and os.path.exists(icon):   # ABSOLUTE placement through the header, because the design gives absolute positions and a layout would only approximate them; the body below is a layout, where the design gives a column
            glyph = QtSvgWidgets.QSvgWidget(icon, header)   # a LIVE VECTOR, never a pixmap: QSvgWidget re-renders the file at whatever size and device resolution it is handed, so there is no raster step to get wrong on a 2.0 display
            glyph.setStyleSheet("background: transparent;")
            glyph.setGeometry(theme.ui_px(16), theme.ui_px(18),
                              theme.ui_px(30), theme.ui_px(30))

        for text, top, px, ink, bold in (   # the tops are the design's 15, 47 and 88
            (subtitle, 8, self.SUBTITLE_PX, self.LABEL_INK, False),
            (title, 24, self.TITLE_PX, self.TITLE_INK, True),
            (kind, 44, self.KIND_PX, self.LABEL_INK, False),
        ):
            if not text:
                continue
            label = QtWidgets.QLabel(str(text), header)
            font = QtGui.QFont(label.font())
            font.setPixelSize(theme.ui_px(px))
            font.setBold(bold)
            label.setFont(font)
            label.setStyleSheet("color: %s; background: transparent;" % ink)
            label.setGeometry(
                theme.ui_px(self.TEXT_X), theme.ui_px(top),
                theme.ui_px(self.FRAME[0] - self.TEXT_X - self.INSET),
                theme.ui_px(px + 4))

        body = QtWidgets.QWidget(self)
        outer.addWidget(body, 1)
        self.body_layout = QtWidgets.QVBoxLayout(body)
        inset = theme.ui_px(self.INSET)
        self.body_layout.setContentsMargins(
            inset, theme.ui_px(self.FIRST_FIELD_Y - self.HEADER_H), inset, 0)
        self.body_layout.setSpacing(0)   # ZERO: `add_field` places the design's own gaps, which differ above and below a label

    def add_field(self, widget, label: str = "") -> None:
        """A standard Houdini control at the design's size and place - STANDARD is its LOOK only, since the grey boxes in the page are placeholders for real controls; the geometry is still the design's, and the uneven gaps live here."""
        if label:
            if self.body_layout.count():
                self.body_layout.addSpacing(theme.ui_px(9))
            text = QtWidgets.QLabel(label, self)
            font = QtGui.QFont(text.font())
            font.setPixelSize(theme.ui_px(self.LABEL_PX))
            text.setFont(font)
            text.setStyleSheet(
                "color: %s; background: transparent;" % self.LABEL_INK)
            self.body_layout.addWidget(text)
            self.body_layout.addSpacing(theme.ui_px(4))
        widget.setFixedHeight(theme.ui_px(self.FIELD_H))
        self.body_layout.addWidget(widget)

    def add_buttons(self, reject_text: str, accept_text: str) -> None:
        """The design's two buttons - 202 x 42 each, filling the 442 column with a 38 gap: standard Houdini buttons with no stylesheet, but the design's geometry, since at their natural size they huddle in the corner."""
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.ui_px(self.BUTTON_GAP))
        for text, slot in ((reject_text, self.reject),
                           (accept_text, self.accept)):
            button = QtWidgets.QPushButton(text, self)
            button.setFixedSize(theme.ui_px(self.BUTTON[0]),
                                theme.ui_px(self.BUTTON[1]))
            button.clicked.connect(slot)
            row.addWidget(button)
        self.body_layout.addSpacing(theme.ui_px(self.INSET))   # the design's 35 BELOW THE FIELD, the same as the side padding; NOT a stretch, which floats them to the body's bottom and puts a different gap above them at every dialog height
        self.body_layout.addLayout(row)
        self.body_layout.addStretch(1)


DISABLED_OPACITY = 0.5   # what a self-painted widget's disabled state looks like: Qt does not dim a pixmap a widget paints itself, so every full paintEvent override here must apply it by hand - overview.md §2 states the behaviour


def apply_disabled_opacity(painter, widget) -> None:
    """Dim what follows when `widget` is disabled - one rule, so the three self-painted widgets cannot disagree about it again."""
    if not widget.isEnabled():
        painter.setOpacity(DISABLED_OPACITY)


class ClickSlider(QtWidgets.QSlider):
    """A slider that updates continuously, jumps to the click, and locks onto a SNAP_MARK within SNAP_RADIUS of it - a magnet zone per mark, not a grid; it paints its own groove and handle, because QSlider's sub-page/add-page stylesheet selectors render unpredictably across styles and platforms."""

    LEFT_COLOR = QtGui.QColor("#5d7abd")   # also the project accent default, which `set_accent_color` overrides from prefs at runtime regardless
    LEFT_WIDTH = theme.ui_px(3)
    RIGHT_COLOR = QtGui.QColor(theme.color_hex("field"))   # was #434343, byte-identical to this role, so the groove follows the Houdini theme like the rest of the panel
    RIGHT_WIDTH = theme.ui_px(3)
    HANDLE_COLOR = QtGui.QColor("#777f95")
    HANDLE_DIAMETER = theme.ui_px(11)   # 11 not 10: Qt centres an ellipse pen on the geometric edge, so the border eats inward into the fill by half its width rather than sitting outside it
    HANDLE_BORDER_COLOR = QtGui.QColor(theme.color_hex("surface"))   # was #2d2d2d, the toolbar row's own grey, so the handle border reads as punched out of the bar
    HANDLE_BORDER_WIDTH = theme.ui_px(1)
    DEFAULT_VALUE = 128        # VALUE-domain (thumbnail sizes), deliberately unscaled; also the first SNAP_MARK, so the size the panel opens at is the size a drag falls back onto
    SNAP_MARKS = (128, 256, 384)
    SNAP_RADIUS = 5
    TICK_COLOR = QtGui.QColor(theme.color_hex("text_dim"))   # was #696969, byte-identical to this role
    TICK_PIXEL_SIZE = theme.ui_px(1)   # the snap-mark tick is pixel art, not a smooth ellipse - exactly 5 squares of this size (centre, up, down, left, right), never a thicker diamond
    TICK_PATTERN = (
        ".X.",
        "XXX",
        ".X.",
    )

    def __init__(self) -> None:
        super(ClickSlider, self).__init__()
        self.left_color = QtGui.QColor(self.LEFT_COLOR)   # instance-level so Preferences > Appearance > Accent Color overrides the class default per panel without needing a subclass
        self.snap_marks = tuple(self.SNAP_MARKS)   # instance-level too: the marks and their tick dots belong to the toolbar's size slider, and the Preferences parameter rows set this to () for a plain slider with no dots and no magnet zones

    def set_accent_color(self, color: QtGui.QColor) -> None:
        """Overrides the filled (left) segment color and repaints."""
        self.left_color = QtGui.QColor(color)
        self.update()

    def _x_for_value(self, value: float) -> float:
        """X for any value, INSET by the handle radius at both ends so a circle centred here stays fully inside the widget; shared with `_handle_x` so the tick marks line up with where the handle would sit."""
        span = self.maximum() - self.minimum()
        fraction = 0.0 if span == 0 else (value - self.minimum()) / span
        radius = self.HANDLE_DIAMETER / 2
        usable = max(self.width() - 2 * radius, 0)
        return radius + fraction * usable

    def _handle_x(self) -> float:
        """X position of the handle centre for the current value."""
        return self._x_for_value(self.value())

    def _value_at_x(self, x: float) -> float:
        """Inverse of `_x_for_value`, with the SAME radius inset - the two must agree, or a click at either edge sets the value while the handle paints a radius away from it."""
        radius = self.HANDLE_DIAMETER / 2
        usable = max(self.width() - 2 * radius, 0)
        fraction = 0.0 if usable == 0 else (x - radius) / usable
        fraction = max(0.0, min(1.0, fraction))
        return self.minimum() + fraction * (self.maximum() - self.minimum())

    def _snap(self, value: float) -> int:
        """Lock onto the nearest SNAP_MARK within SNAP_RADIUS, else leave the value freely dragged - rounded whole and clamped to the slider's own range."""
        for mark in self.snap_marks:
            if abs(value - mark) <= self.SNAP_RADIUS:
                return mark
        return int(max(self.minimum(), min(self.maximum(), round(value))))

    def _draw_pixel_dot(self, painter: QtGui.QPainter, cx: float, cy: float) -> None:
        """Draw TICK_PATTERN centred at (cx, cy) as discrete filled squares - no antialiasing, so it reads as crisp pixel art rather than a smooth circle."""
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
        apply_disabled_opacity(painter, self)   # this override means QSlider's own disabled rendering never runs, and without it a slider greyed in LIST mode paints exactly as in GRID - reading as "the tiles are at their smallest" rather than as switched off

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
        for mark in self.snap_marks:
            if self.minimum() <= mark <= self.maximum():
                tick_x = self._x_for_value(mark)
                self._draw_pixel_dot(painter, tick_x, mid_y)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        handle_pen = QtGui.QPen(self.HANDLE_BORDER_COLOR)
        handle_pen.setWidth(self.HANDLE_BORDER_WIDTH)
        painter.setPen(handle_pen)
        painter.setBrush(self.HANDLE_COLOR)
        radius = self.HANDLE_DIAMETER / 2
        painter.drawEllipse(QtCore.QPointF(handle_x, mid_y), radius, radius)

        painter.end()

    def _apply_mouse_value(self, x: float) -> None:
        """Shared body of click and drag: snap the value under the cursor and jump straight there, with the step sized to the distance so it is one jump and not an animation."""
        value = self._snap(self._value_at_x(x))
        try:
            stepsize = int(abs(self.value() - value))
            self.setPageStep(stepsize)
            self.setSingleStep(stepsize)
        except Exception:
            pass
        self.setValue(value)

    @debug.guarded("ClickSlider.mousePressEvent")
    def mousePressEvent(self, e: QtGui.QMouseEvent):
        if e.button() == QtCore.Qt.LeftButton:
            e.accept()
            self._apply_mouse_value(e.position().toPoint().x())   # ROUNDED, not the raw QPointF: `_snap` turns x into a whole slider value, and handing it the sub-pixel float moves which mark a click at a magnet-zone edge lands on
        else:
            return super().mousePressEvent(e)

    @debug.guarded("ClickSlider.mouseMoveEvent")
    def mouseMoveEvent(self, ev: QtGui.QMouseEvent) -> None:
        ev.accept()
        self._apply_mouse_value(ev.position().toPoint().x())   # the press path's rounding, so a click and a drag to the same pixel still settle on the same value


class ThinProgressBar(QtWidgets.QWidget):
    """A minimal hand-painted progress bar - no text, just a filled strip against a track; deliberately not QProgressBar plus a stylesheet, which this project's Qt/macOS combination has repeatedly proven unreliable at honouring on built-in widgets."""

    FILL_COLOR = ClickSlider.LEFT_COLOR
    TRACK_COLOR = QtGui.QColor("#1a1a1a")   # its OWN constant, not ClickSlider.RIGHT_COLOR: that coupling meant a slider-only colour tweak silently recoloured this track too
    BAR_HEIGHT = theme.ui_px(4)

    def __init__(self) -> None:
        super().__init__()
        self._done = 0
        self._total = 0
        self.fill_color = QtGui.QColor(self.FILL_COLOR)   # instance-level so Preferences > Appearance > Accent Color overrides the class default per panel without needing a subclass
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
    """The Grid table's header: the sort arrow costs the column that HAS one and not the other nine, because `setSortIndicatorShown(True)` otherwise reserves room in EVERY section; what is taken back is exactly what the base added, which is the IDENTITY `test_grid_columns` pins rather than an arithmetic formula of Qt's."""

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
    """A mouse event's widget-local position for a QRectF hit test - the QPointF that Qt 6's deprecated `pos()` produced, ROUNDED to whole pixels, so a chip answers a cursor exactly where it always did."""
    return QtCore.QPointF(event.position().toPoint())   # `toPoint` rounds half AWAY FROM ZERO, which is exactly what `pos()` returned; passing the raw sub-pixel `position()` through instead flips a hit at a chip edge, and `int()` truncates rather than rounds


class SectionTabBar(QtWidgets.QWidget):
    """The full-width section tab strip below the toolbar: a rounded-top tray holding one text tab per section, the selected one filled with a chip and a thin ring - hand-painted, because stylesheet-driven buttons never reliably hold their geometry on macOS native chrome, and its half-pixel constants are painted through QRectF so they land on physical pixel boundaries at 2x."""

    segmentClicked = QtCore.Signal(str)   # the key of the tab that just became checked, emitted only on an ACTUAL change, matching QAbstractButton.setChecked()'s own behaviour
    cancelClicked = QtCore.Signal()   # the Cancel chip at the strip's right end; shown exactly while the conversion bar is - panel.set_conversion_bar_visible is the one driver

    CANCEL_LABEL = "Cancel"

    HEIGHT = theme.ui_px(28)
    TRAY_HEIGHT = theme.ui_px(23)
    TRAY_RADIUS = theme.ui_px(4)
    TRAY_LEFT = theme.ui_px(3)
    CHIP_HEIGHT = theme.ui_px(17)
    CHIP_RADIUS = theme.ui_px(4)
    CHIP_PAD_X = theme.ui_px(7.5)
    CHIP_GAP = theme.ui_px(2.5)
    CHIP_INSET = theme.ui_px(3)

    STRIP_COLOR = theme.color("surface")   # theme-derived, identical to the old literal constants under Houdini's default theme and following any other one automatically; matches the toolbar row
    TRAY_COLOR = theme.color("surface_low")   # matches the category backdrop, so the tray reads as connected to the sidebar below
    CHIP_FILL = theme.color("tab_chip")    # an ACCENT shade: Houdini's own example panel drives its checked/tab states from accent variants
    CHIP_RING = theme.color("tab_ring")
    TEXT_SELECTED = theme.color("text_bright")
    TEXT_UNSELECTED = theme.color("text")
    TEXT_HOVER = QtGui.QColor("#cccdcd")   # not in the design, which draws no tab hover state - a modest text-whitening matching the toolbar icons' hover colour

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
        """Select a tab, emitting `segmentClicked` only on an actual change; `emit=False` sets the initial checked state at construction, before panel.py's `setup()` has built the models the handlers depend on."""
        if key != self._checked_key:
            self._checked_key = key
            self.update()
            if emit:
                self.segmentClicked.emit(key)

    def _chip_rects(self) -> list:
        """[((key, label), QRectF), ...] - the chip-sized rect for every tab, and the hit target for the unselected ones that paint text only; measured against the CURRENT font, so the panel's font stamp is respected whatever the construction order."""
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
        """Show or hide the Cancel chip. Call through panel.set_conversion_bar_visible, the chip's one driver - except _build_section_tabs, which re-applies the bar's CURRENT state to a freshly built strip."""
        visible = bool(visible)
        if visible != self._cancel_visible:
            self._cancel_visible = visible
            if not visible:
                self._cancel_hover = False
            self.update()

    def cancel_visible(self) -> bool:
        return self._cancel_visible

    def _cancel_rect(self):
        """The Cancel chip's rect at the strip's right end, level with the tabs - or None while hidden, or while the strip is too narrow for the chip to clear the last tab (a hit there would be ambiguous, so neither paint nor press resolves)."""
        if not self._cancel_visible:
            return None
        metrics = self.fontMetrics()
        chip_y = (self.height() - self.CHIP_HEIGHT) / 2.0   # the STRIP's full height, not the tray's: the chip floats outside the tray, so the row is its visual reference - tray-centered it reads low
        width = metrics.horizontalAdvance(self.CANCEL_LABEL) \
            + 2 * self.CHIP_PAD_X
        x = self.width() - self.TRAY_LEFT - self.CHIP_INSET - width
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
            if key is not None or over_cancel:   # a pointing hand over an actual TAB or the Cancel chip only, since this strip spans the whole panel width and most of it is empty
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

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), self.STRIP_COLOR)

        rects = self._chip_rects()
        if rects:
            tray_top = self.height() - self.TRAY_HEIGHT   # the tray has rounded TOP corners only: the rect below runs one radius past the widget bottom so the bottom rounding is clipped off and the tray sits flush against the sidebar
            tray_right = rects[-1][1].right() + self.CHIP_INSET
            tray_path = QtGui.QPainterPath()
            tray_path.addRoundedRect(
                QtCore.QRectF(
                    self.TRAY_LEFT,
                    tray_top,
                    tray_right - self.TRAY_LEFT,
                    self.TRAY_HEIGHT + self.TRAY_RADIUS,
                ),
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
                ring_w = theme.ui_px(1.0)
                half = ring_w / 2.0
                pen = QtGui.QPen(self.CHIP_RING)
                pen.setWidthF(ring_w)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(
                    rect.adjusted(half, half, -half, -half),
                    self.CHIP_RADIUS,
                    self.CHIP_RADIUS,
                )
            if checked:
                painter.setPen(self.TEXT_SELECTED)
            elif key == self._hover_key:
                painter.setPen(self.TEXT_HOVER)
            else:
                painter.setPen(self.TEXT_UNSELECTED)
            painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, label)

        cancel = self._cancel_rect()
        if cancel is not None:   # ring only, no fill: a chip that reads as a BUTTON beside tabs that read as tabs
            ring_w = theme.ui_px(1.0)
            half = ring_w / 2.0
            pen = QtGui.QPen(self.CHIP_RING)
            pen.setWidthF(ring_w)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                cancel.adjusted(half, half, -half, -half),
                self.CHIP_RADIUS,
                self.CHIP_RADIUS,
            )
            painter.setPen(self.TEXT_HOVER if self._cancel_hover
                           else self.TEXT_UNSELECTED)
            painter.drawText(cancel, QtCore.Qt.AlignmentFlag.AlignCenter,
                             self.CANCEL_LABEL)

        painter.end()


def draw_chip(painter, rect, fill, ring, inner_border=None):
    """Draw the design's rounded button chip - fill, a light outer ring, and optionally a darker one just inside it, which is what separates the clicked state from hover; shared by IconMenuButton and ChipToggleButton so the two hover looks cannot drift apart."""
    ring_w = theme.ui_px(1)
    half = ring_w / 2.0
    outer = QtCore.QRectF(rect).adjusted(half, half, -half, -half)
    painter.setPen(QtGui.QPen(ring, ring_w))
    painter.setBrush(fill)
    painter.drawRoundedRect(outer, theme.ui_px(5), theme.ui_px(5))
    if inner_border is not None:
        inset = ring_w + half
        inner = QtCore.QRectF(rect).adjusted(inset, inset, -inset, -inset)
        painter.setPen(QtGui.QPen(inner_border, ring_w))
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(inner, theme.ui_px(4), theme.ui_px(4))


class ToggleSwitch(QtWidgets.QCheckBox):
    """A pill toggle switch, drop-in for QCheckBox - same signals, same checked API, same row layout - hand-painted, with its colours from the theme roles the design's swatches map to and its sizes in DESIGN px, scaled here."""

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
               if self.text() else 0)
            + theme.ui_px(2)
        )
        h = max(theme.ui_px(self.TRACK_H) + theme.ui_px(4),
                fm.height() + theme.ui_px(2))
        return QtCore.QSize(w, h)

    def minimumSizeHint(self) -> QtCore.QSize:
        return self.sizeHint()

    def hitButton(self, pos: QtCore.QPoint) -> bool:
        # The whole row (track + text) toggles, like a checkbox's text.
        return self.rect().contains(pos)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        tw = theme.ui_px(self.TRACK_W)
        th = theme.ui_px(self.TRACK_H)
        y = (self.height() - th) / 2.0
        ring_w = theme.ui_px(1.0)   # the track below is inset by half this, so the scaled border pen renders crisp
        half = ring_w / 2.0
        track = QtCore.QRectF(half, y + half, tw - ring_w, th - ring_w)
        radius = track.height() / 2.0
        if self.isChecked():
            knob = theme.color("star")   # Houdini's own toggle switches use the theme HIGHLIGHT for the on state: knob at full strength, track a deep-dimmed version of the same colour
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


class IconMenuButton(QtWidgets.QWidget):
    """The toolbar's icon button that pops a QMenu, fully hand-painted because Houdini's own button chrome shows NO visible open state in this panel; hover and open are tracked explicitly and cleared on the menu's `aboutToHide`, which is what avoids Qt's stuck-highlight-after-popup quirk."""

    IDLE_BODY = "#5d7abd"
    LIT_BODY = "#cccdcd"
    IDLE_TRIANGLE = "#7f807f"
    LIT_TRIANGLE = "#a5b3d4"
    PUNCH_OUT = "#2d2d2d"
    OPEN_PUNCH_OUT = "#2d4075"
    HOVER_PUNCH_OUT = "#424142"
    CHIP_FILL = QtGui.QColor("#2d4075")
    CHIP_BORDER = QtGui.QColor("#1e2c50")
    CHIP_RING = QtGui.QColor("#707ca3")
    HOVER_CHIP_FILL = QtGui.QColor("#424142")
    HOVER_CHIP_RING = QtGui.QColor("#555455")
    TEXT_COLOR = QtGui.QColor("#e6e6e6")
    RENDER_SCALE = 4    # icons render at 4x the icon size, so painting scales a sharp pixmap DOWN on a retina display rather than a soft one up

    def __init__(
        self,
        menu: QtWidgets.QMenu | None,
        svg_path: str,
        icon_size: int = 18,     # 18 against the 36-unit body-centred viewBoxes holds the icon body at the design's ~29px; DESIGN px, with the UI scale applied here so every call site stays scale-agnostic
        button_size: int = 24,
        on_click=None,           # with menu=None this is a plain ACTION button and a click calls this instead of popping a menu - the gear goes straight into Preferences, and its icon carries no menu triangle
        fallback_label: str = "",
    ) -> None:
        super().__init__()
        self._menu = menu
        self._on_click = on_click
        self._hovered = False
        self._open = False
        self._icon_size = theme.ui_px(icon_size)
        button_size = theme.ui_px(button_size)
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
        self._fallback_text = (   # a missing asset degrades to the menu title, or the given label, drawn as text so the button stays usable
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
        self._hovered = self.rect().contains(   # the cursor is read DIRECTLY, because Qt does not reliably resend hover/leave events across a popup closing
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
        apply_disabled_opacity(painter, self)   # a bare QWidget gets no disabled treatment from Qt either, and the panel dims this chip alongside the star and Comments so the three read as one row
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
            offset = (self.width() - self._icon_size) // 2
            target = QtCore.QRect(
                offset, offset, self._icon_size, self._icon_size
            )
            painter.drawPixmap(target, pm)
        painter.end()


class ChipToggleButton(QtWidgets.QToolButton):
    """A checkable icon button carrying IconMenuButton's own hover chip, so the two match across the toolbar; it subclasses QToolButton to keep the toggled/setChecked wiring but paints entirely itself, and plain enter/leave hover tracking is safe here because no popup is involved."""

    RENDER_SCALE = 4

    def __init__(self, button_size: int = 24, icon_size: int = 16) -> None:
        super().__init__()
        self.setCheckable(True)
        button_size = theme.ui_px(button_size)   # DESIGN px in, UI scale applied HERE so call sites stay scale-agnostic, matching IconMenuButton
        self.setFixedSize(button_size, button_size)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._icon_size = theme.ui_px(icon_size)
        self._hovered = False
        self._pms = {}

    DISABLED_OPACITY = DISABLED_OPACITY   # kept as a class attribute because a test pins it HERE, but the value is the module-level rule every self-painted widget shares - one value, not three

    def set_art(self, off_path, on_path=None, lighten_on_hover=True,
                recolour=None, recolour_on=None):
        """THE one way a chip gets its four states, and the house rule is that AT REST BOTH STATES ARE THE ART AS DRAWN - the picture says on or off and nothing re-tints to say it again, while hover lightens; pass `lighten_on_hover=False` where the on-state is carried by COLOUR rather than shape, `on_path=None` for one drawing serving both, and `recolour` for art that serves two places at once."""
        size = self._icon_size * self.RENDER_SCALE
        base = dict(recolour or {})
        on_map = dict(recolour_on) if recolour_on else base   # the ON state may recolour differently: that is how a chip says "you are in this state" with a colour instead of a second drawing, one file and a tint where the star uses two files
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
        apply_disabled_opacity(painter, self)   # a DISABLED chip is half there; without this the star switched off for the online browser painted exactly like a live one and read as simply not working
        pm = self._pms.get((self.isChecked(), self._hovered))
        if pm is not None:
            offset = (self.width() - self._icon_size) // 2
            painter.drawPixmap(
                QtCore.QRect(offset, offset, self._icon_size, self._icon_size),
                pm,
            )
        painter.end()




class SideIconPinner(QtCore.QObject):
    """Keep an icon QLabel pinned to one edge of a line edit, inset and vertically centred - it reacts to the line edit's own Resize events, because the edit is only max-width and a one-time `move()` would not stay correct across a panel resize."""

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

def pick_color(initial, parent=None, title="Select Color"):
    """One colour picker for the whole app - Houdini's when it can be shown, Qt's when it cannot, returning a QColor or None; a NATIVE modal raised while a Qt exec loop is active lands UNDER it, invisible, so `activeModalWidget()` decides at call time and no call site needs to know."""
    from PySide6 import QtGui, QtWidgets

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
            from amaze.core import debug
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
        else QtGui.QColor("#4af2a1"),
        parent, title)
    return picked if picked.isValid() else None


class HeldPane(QtWidgets.QWidget):
    """A splitter side pane that OWNS its width: the construction's law is ONE flexible pane, the grid, so a stretch-0 pane gets exactly what its sizeHint asks for - the remembered dragged width when there is one, the design width otherwise; it lives here rather than in panel.py so both panes share it without importing the panel that holds them."""

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
