"""Shared UI elements: the drag tag, the ui/ asset and SVG readers, the logo and the colour picker."""

import os
import re
import time

from PySide6 import QtWidgets, QtCore, QtGui, QtQml, QtQuick, QtSvg

import amaze
from amaze import amazetheme
from amaze.core import debug
from amaze.helpers import theme


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


def os_file_icon(path: str, side: int) -> QtGui.QImage:
    """The system's icon for `path`'s file type, centred on a transparent `side` square; never empty."""
    provider = QtWidgets.QFileIconProvider()
    icon = provider.icon(QtCore.QFileInfo(path))
    target = side // 2
    pixmap = icon.pixmap(target, target)
    if pixmap.isNull():
        style = QtWidgets.QApplication.style()
        if style is not None:
            pixmap = style.standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_FileIcon
            ).pixmap(target, target)
    image = QtGui.QImage(
        side, side,
        QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    if not pixmap.isNull():
        drawn = min(target, pixmap.width() * 2)    # a small native icon upscales at most 2x
        painter = QtGui.QPainter(image)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        offset = (side - drawn) // 2
        painter.drawPixmap(
            QtCore.QRect(offset, offset, drawn, drawn), pixmap)
        painter.end()
    return image


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
