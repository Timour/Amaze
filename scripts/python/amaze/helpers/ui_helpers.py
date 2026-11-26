"""Shared UI elements: the drag tag, the ui/ asset and SVG readers, and hand-painted widgets."""

import math
import os
import re
import time

from PySide6 import QtWidgets, QtCore, QtGui, QtQml, QtQuick, QtSvg

import amaze
from amaze import amazetheme
from amaze.core import debug, grid_columns
from amaze.helpers import theme
from hutil.qt.common import qmlviews    # Houdini's own QML panels' base ▸r/houdini-qml-tabs


def open_url(url: str) -> None:
    """Open `url` in the system's browser; a refusal is logged, as a silent failure gives no clue."""
    if not QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):
        debug.event("prefs", "the OS refused to open the link", url=url)


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


def cursor_overlay(text: str = "") -> QtWidgets.QLabel:
    """Frameless, always-on-top, click-through label: the window every cursor overlay is."""
    label = QtWidgets.QLabel(text)
    label.setWindowFlags(    # WindowTransparentForInput is the OS-level click-through ▸r/qt-windows-macos
        QtCore.Qt.WindowType.ToolTip
        | QtCore.Qt.WindowType.FramelessWindowHint
        | QtCore.Qt.WindowType.WindowStaysOnTopHint
        | QtCore.Qt.WindowType.WindowDoesNotAcceptFocus
        | QtCore.Qt.WindowType.WindowTransparentForInput
    )
    label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    label.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)    # showing it never activates
    return label


class DragMarks:
    """What a drag shows at the cursor, for both panes: its name tag, and a miss's mark."""

    MISS_MS = 167    #: how long the miss mark stays on screen (ms) ▸r/qt-windows-macos
    MISS_ICON = "icon_drop_miss.svg"    # frame X01b's mark, in the red it is drawn in

    def __init__(self) -> None:
        self._tag = None
        self._miss = None    # one window, reused for every miss
        self._miss_serial = 0    # stops a stale timer hiding a newer miss

    def show_tag(self, name: str) -> None:
        tag = self._tag = cursor_overlay(str(name or ""))
        tag.setStyleSheet(DRAG_TAG_STYLE)    # as `name_tag_pixmap` draws it: every drag tag alike
        tag.adjustSize()
        self.move_tag()
        tag.show()

    def move_tag(self) -> None:
        if self._tag is not None:
            pos = QtGui.QCursor.pos()
            self._tag.move(pos.x() + theme.ui_px(12), pos.y() + theme.ui_px(14))    # where Qt's file tag sits

    def tag_shown(self, shown: bool) -> None:
        if self._tag is not None:
            self._tag.setVisible(shown)

    @staticmethod
    def tag_picture(name: str) -> QtGui.QPixmap:
        return name_tag_pixmap(name)

    def hide_tag(self) -> None:
        tag, self._tag = self._tag, None
        if tag is not None:
            tag.hide()
            tag.close()
            tag.deleteLater()

    def show_miss(self) -> None:
        """The miss mark at the cursor for MISS_MS."""
        size = theme.ui_px(22)
        pixmap = render_svg_pixmap(amaze.package_file("ui", self.MISS_ICON), size)
        if pixmap.isNull():
            return
        label = self._miss
        if label is None:
            label = self._miss = cursor_overlay()
            label.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        label.setPixmap(pixmap)
        label.adjustSize()
        pos = QtGui.QCursor.pos()
        label.move(pos.x() - size // 2, pos.y() - size // 2)
        label.show()
        shown_at = time.time()
        self._miss_serial += 1
        serial = self._miss_serial

        def done(window=label):
            """Hide the X, unless a newer miss took the window since."""
            if self._miss_serial != serial:
                return
            debug.event("drag", "indicator hidden", shown_ms=round((time.time() - shown_at) * 1000))
            try:
                window.clear()
                window.hide()
            except RuntimeError:
                pass

        QtCore.QTimer.singleShot(self.MISS_MS, done)


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


def svg_size(name: str) -> QtCore.QSize:
    """The size a ui/ SVG is drawn at, its own width and height; empty when it is unreadable."""
    return QtSvg.QSvgRenderer(amaze.package_file("ui", name)).defaultSize()


def forget_svg_images() -> None:
    """Clear the rendered-SVG cache, for test isolation."""
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


def tooltip_text(text: str, max_px: int = 800) -> str:
    """A tooltip never drawn wider than `max_px` device pixels."""
    import html

    cap = max(1, int(max_px / theme.screen_ratio()))    # the primary screen: the target monitor is unknown at setToolTip time ▸r/screen-dpr
    metrics = QtGui.QFontMetrics(QtWidgets.QToolTip.font())
    if metrics.horizontalAdvance(text) <= cap:
        return html.escape(text) if _might_be_rich(text) else text    # Qt auto-detects rich text, so this branch escapes too ▸r/tooltip-autodetect

    body = html.escape(text).replace("\n", "<br>")   # rich text drops plain newlines
    return '<qt><table width="%d"><tr><td>%s</td></tr></table></qt>' % (
        cap, body)


def _might_be_rich(text: str) -> bool:
    """Whether Qt would treat `text` as rich rather than plain. ▸r/tooltip-autodetect"""
    return QtGui.Qt.mightBeRichText(str(text or ""))


_SVG_CACHE: dict = globals().get("_SVG_CACHE", {})   # rasterised SVGs keyed by (path, size, tint), kept across module reloads


_PAINT_OPACITY = re.compile(r'((?:fill|stroke)-opacity)(="|:)[0-9.]+')
_SVG_ELEMENT = re.compile(r"<[^>]+>")
BADGE_BACKDROP_ID = 'id="Rounded-Rectangle'    # the layer every badge's backdrop is exported under


def at_opacity(text: str, opacity) -> str:
    """SVG text with the icon's paint opacities set to `opacity`; the backdrop element keeps its own."""
    if opacity is None:
        return text

    def element(match):
        tag = match.group(0)
        if BADGE_BACKDROP_ID in tag:
            return tag
        return _PAINT_OPACITY.sub(lambda m: "%s%s%g" % (m.group(1), m.group(2), opacity), tag)

    return _SVG_ELEMENT.sub(element, text)


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


_BLED_CACHE: dict = globals().get("_BLED_CACHE", {})    # bled_pixmap's results by every argument


def bled_pixmap(path, height, dpr, bleed) -> QtGui.QPixmap:
    """An SVG `height` logical px high in its own shape, `bleed` px of room around it; null if unread."""
    key = (path, height, round(dpr, 3), bleed)
    if key not in _BLED_CACHE:
        _BLED_CACHE[key] = _render_bled(path, height, dpr, bleed)
    return QtGui.QPixmap(_BLED_CACHE[key])    # shares the pixels: a caller's change stays its own


def _render_bled(path, height, dpr, bleed) -> QtGui.QPixmap:
    """`bled_pixmap` drawn anew."""
    renderer = QtSvg.QSvgRenderer(path) if path and os.path.exists(path) else None
    if renderer is None or not renderer.isValid():
        return QtGui.QPixmap()
    drawn = renderer.defaultSize()
    width = max(1, round(height * drawn.width() / max(drawn.height(), 1)))
    pixmap = QtGui.QPixmap(max(1, round((width + 2 * bleed) * dpr)),
                           max(1, round((height + 2 * bleed) * dpr)))
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    try:    # Qt also draws what is outside the art's own box, its shadow ▸r/qt-svg-filters
        renderer.render(painter, QtCore.QRectF(bleed * dpr, bleed * dpr, width * dpr, height * dpr))
    finally:
        painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def faded_pixmap(pixmap: QtGui.QPixmap, opacity: float, dpr: float) -> QtGui.QPixmap:
    """`pixmap`, made at ratio `dpr`, at `opacity` on a transparent copy; 1 returns it as is."""
    if opacity >= 1.0:
        return pixmap
    faded = QtGui.QPixmap(pixmap.size())
    faded.fill(QtCore.Qt.GlobalColor.transparent)
    faded.setDevicePixelRatio(dpr)
    painter = QtGui.QPainter(faded)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return faded


def striped_rows(view) -> None:
    """Make a tree view the app's one kind of row list; the style paints its rows. ▸r/one-row-list"""
    view.setHeaderHidden(True)
    view.setRootIsDecorated(False)
    view.setUniformRowHeights(True)
    view.setAnimated(False)
    view.setAlternatingRowColors(True)


class Table(QtWidgets.QTreeView):
    """The app's one table: a standard tree view the host style paints. ▸r/one-table"""

    row_chosen = QtCore.Signal(QtCore.QModelIndex)    # the user made another row current, by any means

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        striped_rows(self)
        self._quiet = False    # True while the app itself moves the highlight
        self._user = 0    # above 0 while Qt handles a mouse or key event of the user's

    def selected_rows(self) -> list:
        """The selection as one index per row, at the first column."""
        return grid_columns.selected_rows(self.selectionModel())

    def highlight(self, index) -> None:
        """Make `index`'s row the current, selected one without `row_chosen`: the app's own move."""
        self._quiet = True
        try:
            flag = QtCore.QItemSelectionModel.SelectionFlag
            self.selectionModel().setCurrentIndex(index, flag.ClearAndSelect | flag.Rows)
        finally:
            self._quiet = False

    def viewportEvent(self, event) -> bool:
        if event.type() == QtCore.QEvent.Type.ContextMenu:    # a menu runs the app's work, never a row choice
            return super().viewportEvent(event)
        return self._by_user(super().viewportEvent, event)

    def keyPressEvent(self, event) -> None:
        self._by_user(super().keyPressEvent, event)

    def _by_user(self, handle, event):
        """Run Qt's own handling of an input event, marked as the user's. ▸r/one-table"""
        self._user += 1
        try:
            return handle(event)
        finally:
            self._user -= 1

    def currentChanged(self, current, previous) -> None:
        super().currentChanged(current, previous)
        if self._user and not self._quiet and current.isValid():    # not when the data moved it
            self.row_chosen.emit(current.siblingAtColumn(0))



class TwoColumnTable(Table):
    """The app's table over two columns; `whole_second` keeps the second column's text whole."""

    def __init__(self, first_width: int, whole_second: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._items = QtGui.QStandardItemModel(0, 2, self)
        self.setModel(self._items)
        self.setIndentation(0)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)    # a long path keeps both its ends
        header, resize = self.header(), QtWidgets.QHeaderView.ResizeMode
        header.setMinimumSectionSize(1)
        header.setStretchLastSection(not whole_second)
        header.resizeSection(0, first_width)
        if whole_second:    # never cut: the second column fits its text, the first takes the rest
            header.setSectionResizeMode(0, resize.Stretch)
            header.setSectionResizeMode(1, resize.ResizeToContents)

    def add_row(self, first: str, second: str, flags=QtCore.Qt.ItemFlag.ItemIsEnabled) -> list:
        """Append a row of two cells with `flags`; returns the cells."""
        cells = [QtGui.QStandardItem(first), QtGui.QStandardItem(second)]
        for cell in cells:
            cell.setFlags(flags)
        self._items.appendRow(cells)
        return cells

    def clear_rows(self) -> None:
        self._items.setRowCount(0)

    def count(self) -> int:
        return self._items.rowCount()

    def cell(self, row: int, column: int = 0):
        return self._items.item(row, column)

def fill_window(widget, hex_color: str) -> None:
    """Background via the palette; a stylesheet on any ancestor restyles the subtree's scrollbars."""
    palette = widget.palette()
    palette.setColor(QtGui.QPalette.ColorRole.Window,
                     QtGui.QColor(hex_color))
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)


def set_text_color(label, role: str, opacity: float = 1.0) -> None:
    """Label text in one of the theme's text colours, via the palette, same reasoning as fill_window."""
    color = theme.color(role)
    color.setAlphaF(opacity)
    palette = label.palette()
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, color)
    label.setPalette(palette)


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


_DRAWN_NODES_FITTED: set = set()    # every drawn node a pin has read, for the drawn-binding completeness test ▸p/one-design-document


def drawn_nodes_fitted() -> frozenset:
    """Every `(frame, kind, x, y)` a pin has read; read by the drawn-binding completeness test."""
    return frozenset(_DRAWN_NODES_FITTED)


def forget_drawn_nodes_fitted() -> None:
    _DRAWN_NODES_FITTED.clear()


def _fit_to_box(widget, frame_key: str, kind: str, box, height: bool,
                grow: bool = False) -> None:
    """Size `widget` to one drawn box and record its node, keyed by its position in the frame."""
    if grow:
        widget.setMinimumWidth(theme.ui_px(box[2]))    # a floor: a wider font grows it, never clips it
    else:
        widget.setFixedWidth(theme.ui_px(box[2]))
    if height:
        widget.setFixedHeight(theme.ui_px(box[3]))
    widget.drawn_box = tuple(box)    # where it is drawn, for a caller placing several pinned widgets in one row
    _DRAWN_NODES_FITTED.add((frame_key, kind, box[0], box[1]))


def fit_drawn(widget, frame_key: str, kind: str, text: str,
              height: bool = True, nth: int = 0, grow: bool = False) -> None:
    """Size `widget` to the drawn box for `<kind> ▸ <text>` in `frame_key`. ▸p/one-design-document"""
    found = amazetheme.drawn_repeats(frame_key, kind, text)
    if nth >= len(found):
        debug.event("ui", "no drawn box for this widget",
                    frame=frame_key, kind=kind, text=text, nth=nth)
        return
    _fit_to_box(widget, frame_key, kind, found[nth], height, grow)


def drawn_kind(widget, frame_key: str) -> str:
    """The kind `frame_key` draws this widget as: its class name, or the nearest drawn base."""
    boxes = amazetheme.drawn_boxes(frame_key)
    for cls in type(widget).__mro__:
        if (cls.__name__, None) in boxes:
            return cls.__name__
    return type(widget).__name__


def fit_drawn_series(widgets, frame_key: str, kind: str,
                     height: bool = True) -> None:
    """Pin widgets of one kind from the frame's rects of that kind, drawn order against creation order."""
    drawn = amazetheme.drawn_repeats(frame_key, kind, None)
    widgets = tuple(widgets)
    if len(drawn) != len(widgets):
        debug.event("ui", "the drawn nodes and the built widgets differ in "
                    "number", frame=frame_key, kind=kind, drawn=len(drawn),
                    built=len(widgets))
    for widget, box in zip(widgets, drawn):
        _fit_to_box(widget, frame_key, kind, box, height)


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
    text_palette = label.palette()
    text_palette.setColor(QtGui.QPalette.ColorRole.WindowText,
                          theme.color("text_bright"))
    label.setPalette(text_palette)
    row.addWidget(label)
    row.addStretch(1)
    return band


DISABLED_OPACITY = 0.5   # a self-painted widget's disabled opacity; every paintEvent override applies it by hand


def apply_disabled_opacity(painter, widget) -> None:
    """Dim what follows when `widget` is disabled - used by every self-painted widget."""
    if not widget.isEnabled():
        painter.setOpacity(DISABLED_OPACITY)


class ClickSlider(QtWidgets.QSlider):
    """A self-painted slider that jumps to the click and locks onto a SNAP_MARK within SNAP_RADIUS."""

    LEFT_COLOR = QtGui.QColor(amazetheme.SLIDER_LEFT)   # the accent default; `set_accent_color` overrides it from prefs
    LEFT_WIDTH = theme.ui_px(3)
    RIGHT_COLOR = theme.live("field")   # the groove follows the Houdini theme
    RIGHT_WIDTH = theme.ui_px(3)
    HANDLE_COLOR = QtGui.QColor(amazetheme.SLIDER_HANDLE)
    HANDLE_DIAMETER = theme.ui_px(11)   # 11: Qt centres an ellipse pen on the edge, so half the border's width falls inside
    HANDLE_BORDER_COLOR = theme.live("surface")   # was #2d2d2d, the toolbar row's own grey, so the handle border looks cut out of the bar
    HANDLE_BORDER_WIDTH = theme.ui_px(1)
    DEFAULT_VALUE = 128        # a size, unscaled, and one of the SNAP_MARKS so a drag can stop on it
    SNAP_MARKS = amazetheme.TILE_SIZES
    SNAP_RADIUS = 5
    TICK_COLOR = theme.live("text_dim")   # was #696969, byte-identical to this role
    TICK_PIXEL_SIZE = theme.ui_px(1)   # the snap-mark tick is pixel art: 5 squares of this size, centre and four neighbours
    TICK_PATTERN = (
        ".X.",
        "XXX",
        ".X.",
    )

    def __init__(self) -> None:
        super(ClickSlider, self).__init__()
        self.left_color = QtGui.QColor(self.LEFT_COLOR)   # instance-level, so the Accent Color pref overrides it per panel
        self.snap_marks = tuple(self.SNAP_MARKS)   # instance-level too; () gives a plain slider with no dots and no snapping
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
        """Step Size: a key step moves to the next mark in its direction ▸r/slider-steps."""
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
        delta = angle.y() if angle.y() else -angle.x()    # Qt's convention: up and right both increase
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
        self._apply_mouse_value(ev.position().toPoint().x())   # the press path's rounding, so a click and a drag to the same pixel give the same value


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
        self.fill_color = QtGui.QColor(color)   # overrides the fill colour and repaints, as ClickSlider.set_accent_color does
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


class _StripLine(QtWidgets.QWidget):
    """The strip's bottom row in the tab bar's colour, over the tab bar; it takes no mouse events."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)    # Houdini's style ends the first and last tab a row short of the others
        painter.fillRect(self.rect(), theme.color("tab_bar"))
        painter.end()


LOGO_HEIGHT = 34    # the About wordmark's drawn height, its empty margin trimmed off
_SVG_SIZE = re.compile(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"')    # an SVG file's drawn width and height
_logo_cache = None   # the wordmark rendered for one pixel ratio, reused while the ratio stays


def logo_image(ratio: float):
    """The Amaze wordmark cropped to its pixels, LOGO_HEIGHT tall at pixel ratio `ratio`. ▸r/screen-dpr"""
    global _logo_cache
    if isinstance(_logo_cache, dict) and _logo_cache.get("dpr") == ratio:
        return _logo_cache["image"] or None

    path = amaze.package_file("ui", "logo.svg")
    image = None
    try:
        with open(path, encoding="utf-8") as handle:
            drawn = _SVG_SIZE.search(handle.read())
        tall = round(1024 * float(drawn.group(2)) / float(drawn.group(1)))    # paint_svg fills the image
        full = QtGui.QImage(1024, tall, QtGui.QImage.Format.Format_ARGB32)
        if paint_svg(full, path):
            box = QtGui.QRegion(
                QtGui.QBitmap.fromImage(full.createAlphaMask())
            ).boundingRect()
            if not box.isEmpty():
                image = full.copy(box).scaledToHeight(   # DEVICE pixels tall, drawn back at logical size
                    max(1, round(theme.ui_px(LOGO_HEIGHT) * ratio)),
                    QtCore.Qt.TransformationMode.SmoothTransformation,
                )
                image.setDevicePixelRatio(ratio)
    except Exception as exc:                                # noqa: BLE001
        debug.event("prefs", "About logo not loaded", error=str(exc))   # event, not note: it is cosmetic
    _logo_cache = {"dpr": ratio, "image": image if image is not None
                   else False}
    return image


class LogoImages(QtQuick.QQuickImageProvider):
    """`image://amazelogo/logo`: the trimmed wordmark at the pixel ratio the QML asks for."""

    def __init__(self) -> None:
        super().__init__(QtQml.QQmlImageProviderBase.ImageType.Image)

    def requestImage(self, _key: str, size: QtCore.QSize, requested: QtCore.QSize) -> QtGui.QImage:
        ratio = requested.height() / LOGO_HEIGHT if requested.height() > 0 else theme.screen_ratio()
        image = logo_image(ratio) or QtGui.QImage()
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image


TAB_ART = amazetheme.drawn_tabs()["icons"]    # a section's art and its drawn box; a tab with no entry has no icon


def section_tab_rows(segments) -> list:
    """The tab strip's rows: each name, its art's file, the drawn box and the file's own box."""
    rows = []
    for key, label in segments:
        row = {"label": label, "icon": "", "width": 0, "height": 0,
               "artX": 0, "artY": 0, "artWidth": 0, "artHeight": 0}
        if key in TAB_ART:
            art, width, height = TAB_ART[key]
            box = QtSvg.QSvgRenderer(amaze.package_file("ui", art)).viewBoxF()    # past the layer's box by its outline
            row.update(icon=art, width=width, height=height, artX=box.x(), artY=box.y(),
                       artWidth=box.width(), artHeight=box.height())
        rows.append(row)
    return rows


class _SectionTabsView(qmlviews.BaseQmlWidget):
    """The section tabs' QML, made as Houdini makes its own QML panels. ▸r/houdini-qml-tabs"""

    SOURCE_URL = QtCore.QUrl.fromLocalFile(amaze.package_file("ui", "pane", "SectionTabs.qml")).toString()


class SectionTabBar(QtWidgets.QWidget):
    """The section tab strip below the toolbar: Houdini's own QML tab bar, section icons first."""

    segmentClicked = QtCore.Signal(str)   # the key of the tab that just became checked, emitted only on an actual change
    cancelClicked = QtCore.Signal()   # the Cancel button; only panel.set_conversion_bar_visible shows or hides it

    CANCEL_LABEL = "Cancel"

    _DRAWN = amazetheme.drawn_tabs()    # S01's height and left edge ▸r/tabs-from-frame
    HEIGHT = theme.ui_px(_DRAWN["height"])
    LEFT = theme.ui_px(_DRAWN["left"])    # where the tab bar starts, as the frame's tray does
    LINE_W = theme.ui_px(1)    # the frame's line node carries no weight ▸r/toolbar-tabs-840

    STRIP_COLOR = theme.color("surface")   # theme-derived; matches the toolbar row

    def __init__(self, segments: list) -> None:
        """segments: list of (key, label) pairs, left to right."""
        super().__init__()
        self._segments = list(segments)
        self._checked_key = None
        self._cancel_visible = False
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._tabs = self._make_tabs()
        self._cancel_button = QtWidgets.QPushButton(self.CANCEL_LABEL, self)
        self._cancel_button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._cancel_button.clicked.connect(self.cancelClicked)
        self._cancel_button.hide()
        self._line = _StripLine(self)    # made last, so it is above the tab bar
        self._place()

    def _make_tabs(self):
        """The QML tab bar, with the section rows and the choice wired to the strip."""
        tabs = _SectionTabsView(parent=self)
        tabs.setClearColor(self.STRIP_COLOR)
        tabs.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        root = tabs.rootObject()
        if root is None:
            raise RuntimeError("the section tabs did not load: %s"
                               % "; ".join(e.toString() for e in tabs.errors()))
        root.setProperty("tabs", section_tab_rows(self._segments))
        root.tabChosen.connect(self._on_tab)
        return tabs

    def tab_rect(self, index: int) -> QtCore.QRect:
        """Where tab `index` is drawn, in the strip's coordinates."""
        rect = self._tabs.rootObject().tabRect(index)
        return QtCore.QRectF(rect).translated(QtCore.QPointF(self._tabs.pos())).toAlignedRect()

    def _on_tab(self, index: int) -> None:
        if 0 <= index < len(self._segments):
            self.setChecked(self._segments[index][0])

    def setChecked(self, key: str, emit: bool = True) -> None:
        """Select a tab, emitting `segmentClicked` only on a change; `emit=False` sets the initial state."""
        if key != self._checked_key:
            self._checked_key = key
            keys = [k for k, _label in self._segments]
            if key in keys:
                self._tabs.rootObject().setProperty("currentIndex", keys.index(key))
            if emit:
                self.segmentClicked.emit(key)

    def set_cancel_visible(self, visible: bool) -> None:
        """Show or hide the Cancel button; call through panel.set_conversion_bar_visible."""
        self._cancel_visible = bool(visible)
        self._place()

    def cancel_visible(self) -> bool:
        return self._cancel_visible

    def _cancel_rect(self):
        """The Cancel button's rect, or None while hidden or when the strip is too narrow for it."""
        self._place()
        if self._cancel_button.isHidden():
            return None
        return QtCore.QRectF(self._cancel_button.geometry())

    def _tabs_size(self) -> QtCore.QSize:
        root = self._tabs.rootObject()
        return QtCore.QSize(math.ceil(root.property("implicitWidth")),
                            min(math.ceil(root.property("implicitHeight")), self.HEIGHT))

    def _place(self) -> None:
        """Lay out the tab bar at the left on the line row, the Cancel button at the right, the line."""
        size = self._tabs_size()
        width = min(size.width(), max(self.width() - self.LEFT, 0))
        self._tabs.setGeometry(self.LEFT, self.HEIGHT - size.height(), width, size.height())
        style = self.style()
        margin = style.pixelMetric(QtWidgets.QStyle.PixelMetric.PM_LayoutRightMargin)
        gap = style.pixelMetric(QtWidgets.QStyle.PixelMetric.PM_LayoutHorizontalSpacing)
        button = self._cancel_button.sizeHint()
        above = self.HEIGHT - self.LINE_W    # the button is centred on the strip above its line
        button_h = min(button.height(), above)
        x = self.width() - margin - button.width()
        self._cancel_button.setGeometry(x, (above - button_h) // 2, button.width(), button_h)
        self._cancel_button.setVisible(self._cancel_visible and x >= self.LEFT + size.width() + gap)
        self._line.setGeometry(0, self.HEIGHT - self.LINE_W, self.width(), self.LINE_W)
        self._line.raise_()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place()

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(self.LEFT + self._tabs_size().width(), self.HEIGHT)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.STRIP_COLOR)
        painter.end()


def draw_chip(painter, rect, fill, ring, inner_border=None):
    """Draw the design's rounded button chip: fill, a light outer ring, optionally a darker inner one."""
    ring_w = theme.ui_px(1)
    draw_ring(painter, rect, ring, ring_w, theme.ui_px(5), fill)
    if inner_border is not None:
        inner = QtCore.QRectF(rect).adjusted(ring_w, ring_w, -ring_w, -ring_w)
        draw_ring(painter, inner, inner_border, ring_w, theme.ui_px(4))


def draw_ring(painter, rect, color, width, radius,
              fill=QtCore.Qt.BrushStyle.NoBrush) -> None:
    """A rounded ring `width` wide drawn wholly inside `rect`, over `fill`."""
    half = width / 2.0
    painter.setPen(QtGui.QPen(color, width))
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
               + theme.ui_px(2)     # the trailing 2 px are for the text; a switch without text has none
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
        if event.type() == QtCore.QEvent.Type.EnabledChange:    # the pointing hand means clickable; a disabled switch gets the arrow
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor
                           if self.isEnabled()
                           else QtCore.Qt.CursorShape.ArrowCursor)
        super().changeEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        apply_disabled_opacity(p, self)    # a full paintEvent override must dim itself, or a disabled switch looks broken
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


def icon_rect(button, side: int) -> QtCore.QRectF:
    """Where a self-painted toolbar button draws its `side` icon: where B01 draws it, else centred."""
    at = amazetheme.drawn_toolbar()["icon_at"].get(button.objectName())
    if at is None:
        return QtCore.QRectF((button.width() - side) // 2, (button.height() - side) // 2, side, side)
    return QtCore.QRectF(theme.ui_px(float(at["x"])), theme.ui_px(float(at["y"])), side, side)


class IconMenuButton(QtWidgets.QWidget):
    """The toolbar's hand-painted icon button that pops a QMenu, its hover cleared on `aboutToHide`."""

    IDLE_BODY = amazetheme.MENU_IDLE_BODY
    HOVER_BODY = amazetheme.MENU_HOVER_BODY
    IDLE_TRIANGLE = amazetheme.MENU_IDLE_TRIANGLE
    HOVER_TRIANGLE = amazetheme.MENU_HOVER_TRIANGLE
    CUTOUT = amazetheme.MENU_CUTOUT
    OPEN_CUTOUT = amazetheme.MENU_OPEN_CUTOUT
    HOVER_CUTOUT = amazetheme.MENU_HOVER_CUTOUT
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
        icon_size: int | None = None,     # DESIGN px, scaled here; None takes frame B01's ▸r/toolbar-from-frame
        button_size: int | None = None,
        on_click=None,           # with menu=None a click calls this instead of popping a menu; no menu triangle
        fallback_label: str = "",
        name: str = "",          # its object name, also its node name in frame B01
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
                self.IDLE_BODY: self.HOVER_BODY,
                self.IDLE_TRIANGLE: self.HOVER_TRIANGLE,
                self.CUTOUT: self.HOVER_CUTOUT,
            },
        )
        self._open_pm = render_svg_pixmap(
            svg_path,
            render_size,
            {
                self.IDLE_BODY: self.HOVER_BODY,
                self.IDLE_TRIANGLE: self.HOVER_TRIANGLE,
                self.CUTOUT: self.OPEN_CUTOUT,
            },
        )
        self._fallback_text = (   # a missing asset degrades to the menu title or the given label, drawn as text
            "" if (svg_path and os.path.exists(svg_path))
            else (menu.title() if menu is not None else fallback_label)
        )
        if menu is not None:
            menu.aboutToHide.connect(self._on_menu_closed)

    def set_menu(self, menu) -> None:
        """Replace the menu; the `aboutToHide` connection that clears the hover moves to it."""
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
            draw_chip(   # the design's HOVER chip, the grey variant: fill and light outer ring only, no inner border ring
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
            painter.drawPixmap(icon_rect(self, self._icon_size), pm, QtCore.QRectF(pm.rect()))
        painter.end()


class ChipToggleButton(QtWidgets.QToolButton):
    """A self-painted checkable QToolButton drawing IconMenuButton's hover chip."""

    RENDER_SCALE = 4

    def __init__(self, button_size: int | None = None, icon_size: int | None = None,
                 name: str = "") -> None:
        super().__init__()
        self.setObjectName(name)    # also its node name in frame B01
        self.setCheckable(True)
        drawn = amazetheme.drawn_toolbar()    # DESIGN px, scaled here; None takes frame B01's ▸r/toolbar-from-frame
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
        """Set the chip's four state pixmaps: the SVG as drawn when idle, lightened on hover."""
        size = self._icon_size * self.RENDER_SCALE
        base = dict(recolour or {})
        on_map = dict(recolour_on) if recolour_on else base   # the on state may recolour differently from the off state
        lit = dict(base)
        lit[IconMenuButton.IDLE_BODY] = IconMenuButton.HOVER_BODY

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
            painter.drawPixmap(icon_rect(self, self._icon_size), pm, QtCore.QRectF(pm.rect()))
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
