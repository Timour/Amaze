"""The pane engine: every part of a pane beside the grid, built once; a pane is a description."""

from __future__ import annotations

from typing import Callable, NamedTuple, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.helpers import theme, ui_helpers

HEADER_BG = amazetheme.COMMENT_HEADER_BG
PAGE_BG = amazetheme.COMMENT_PAGE_BG
MIN_WIDTH = 220    # the narrowest a pane with a header is dragged


class Button(NamedTuple):
    """A header button: the page finds it under `name`; `size` is px as drawn, one side or (w, h)."""
    name: str
    size: object
    gap: Optional[int] = None    # px after the item before it, when not the header's own gap
    make: Optional[Callable] = None    # a button of the page's own class, in place of an art-only one


class Header(NamedTuple):
    """Icon drawn in `art_color` and shown in `color`, name and type, then the buttons."""
    icon: str
    art_color: str
    color: str
    right_pad: int
    buttons: tuple = ()


class Picture(NamedTuple):
    """A picture fitted whole into its area, never taller than it is at the pane's full width."""
    name: str
    height: int    # the area's height in px as drawn, until the drag line under it is dragged
    least: int    # the lowest the drag line takes it


class DragLine(NamedTuple):
    """The line under a picture; dragging it sets the picture area's height."""
    name: str
    height: int


class Rows(NamedTuple):
    """Striped rows in two columns, label and value; `drawn` holds the row and column figures."""
    name: str
    drawn: dict


class Widget(NamedTuple):
    """A page's own body part, filling what the parts above it leave."""
    name: str
    make: Callable


class Page(NamedTuple):
    """What a page is made of: a header or None, then its body parts from the top down."""
    drawn: Optional[dict]
    header: Optional[Header]
    body: tuple


class PictureView(QtWidgets.QWidget):
    """An image drawn whole and centred in the widget; the body gives it its size."""

    changed = QtCore.Signal()    # another image, or none: the body places its parts again

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image = None
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        ui_helpers.fill_window(self, PAGE_BG)    # beside the picture, and through its transparency
        self.hide()

    def image(self):
        return self._image

    def set_image(self, image) -> None:
        """Show `image`, a QImage, or None for no picture."""
        self._image = image
        self.changed.emit()
        self.update()

    def full_height(self, width: int) -> int:
        """The picture's height when it is `width` wide; 0 without a picture."""
        image = self._image
        return round(width * image.height() / image.width()) if image is not None else 0

    def picture_rect(self) -> QtCore.QRect:
        """Where the picture is drawn: as large as fits, centred."""
        image = self._image
        if image is None or not self.height():
            return QtCore.QRect()
        scale = min(self.width() / image.width(), self.height() / image.height())
        width, height = round(image.width() * scale), round(image.height() * scale)
        return QtCore.QRect((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def paintEvent(self, _event) -> None:
        if self._image is None:
            return
        painter = QtGui.QPainter(self)
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(self.picture_rect(), self._image)
        finally:
            painter.end()


class DragLineView(QtWidgets.QWidget):
    """The drawn line with room to grab above and below it; a drag reports where the line should be."""

    moved = QtCore.Signal(int)    # the line's wanted top, in the body's coordinates
    released = QtCore.Signal()

    def __init__(self, height: int, parent=None) -> None:
        super().__init__(parent)
        self.line = theme.ui_px(height)
        self.grab = theme.ui_px(amazetheme.DRAG_LINE_GRAB)
        self._press = None    # the pointer's y inside the line at the press
        self._moved = False
        self.setCursor(QtCore.Qt.CursorShape.SplitVCursor)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.hide()

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        try:
            painter.fillRect(0, self.grab, self.width(), self.line, QtGui.QColor(amazetheme.DRAG_LINE_COLOR))
        finally:
            painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint().y() - self.grab
            self._moved = False
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._press is not None:
            self._moved = True
            self.moved.emit(self.mapToParent(event.position().toPoint()).y() - self._press)

    def mouseReleaseEvent(self, event) -> None:
        if self._press is not None and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._press = None
            if self._moved:    # a click that moved nothing has nothing to remember
                self.released.emit()


class RowsView(ui_helpers.TwoColumnTable):
    """Label and value rows that neither take focus nor select; the page scrolls them."""

    rows_changed = QtCore.Signal()    # another number of rows: the page is another length

    def __init__(self, drawn: dict, parent=None) -> None:
        super().__init__(theme.ui_px(drawn["label_width"]), parent=parent)
        self._drawn = drawn
        self._rows = ()
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.NoContextMenu)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)    # the page scrolls

    def rows(self) -> tuple:
        return self._rows

    def set_rows(self, rows) -> None:
        """Show `rows`, (label, value) pairs; a value's tooltip is the whole value."""
        self._rows = tuple((str(label), str(value)) for label, value in rows)
        self.clear_rows()
        for label, value in self._rows:
            self.add_row(label, value)[1].setToolTip(ui_helpers.tooltip_text(value))
        self.rows_changed.emit()

    def row_height(self) -> int:
        """A row's height as the style sizes it; the drawn height before there is a row."""
        height = self.sizeHintForRow(0) if self._rows else 0
        return height if height > 0 else theme.ui_px(self._drawn["row"])

    def content_height(self) -> int:
        """What all the rows need: the page is that long and scrolls as a whole."""
        return len(self._rows) * self.row_height()


class Body(QtWidgets.QWidget):
    """A page's parts from the top down; the body places them and scrolls the page. ▸r/one-side-pane"""

    height_set = QtCore.Signal(int)    # a drag of the line ended: the picture area's height

    def __init__(self, parts, parent=None) -> None:
        super().__init__(parent)
        ui_helpers.fill_window(self, PAGE_BG)
        self._parts = tuple(parts)    # (description, widget), top down
        self._picture = self._line = self._fills = None
        self._wanted = self._least = 0
        self._wide = 0    # the parts' width: the body's, less the page's scrollbar while it shows
        self._placing = False
        self._bar = QtWidgets.QScrollBar(QtCore.Qt.Orientation.Vertical, self)    # the page's one scrollbar
        self._bar.hide()
        self._bar.valueChanged.connect(self.place)
        for spec, widget in self._parts:
            widget.setParent(self)
            if isinstance(spec, Picture):
                self._picture = widget
                self._wanted, self._least = theme.ui_px(spec.height), theme.ui_px(spec.least)
                widget.changed.connect(self.place)
                widget.installEventFilter(self)
            elif isinstance(spec, DragLine):
                self._line = widget
                widget.installEventFilter(self)
                widget.moved.connect(self._dragged)
                widget.released.connect(lambda: self.height_set.emit(self._wanted))
            else:
                self._fills = widget
                if self._pages():
                    widget.viewport().installEventFilter(self)
                    widget.rows_changed.connect(self.place)
                widget.show()

    def _pages(self) -> bool:
        """Whether the last part shows all of itself, so the page scrolls; else that part scrolls itself."""
        return hasattr(self._fills, "content_height")

    def scrollbar(self) -> QtWidgets.QScrollBar:
        return self._bar

    def scroll_to_top(self) -> None:
        self._bar.setValue(0)

    def _wheel(self, event) -> None:
        turn = event.pixelDelta().y()
        if not turn:
            step = getattr(self._fills, "row_height", lambda: theme.ui_px(19))()
            turn = event.angleDelta().y() / 120.0 * QtWidgets.QApplication.wheelScrollLines() * step
        self._bar.setValue(self._bar.value() - round(turn))

    def wheelEvent(self, event) -> None:
        if self._pages():
            self._wheel(event)
        else:
            super().wheelEvent(event)

    def eventFilter(self, watched, event) -> bool:
        """A wheel turn anywhere on a page that scrolls moves the whole page."""
        if event.type() != QtCore.QEvent.Type.Wheel or not self._pages():
            return super().eventFilter(watched, event)
        self._wheel(event)
        return True

    def wanted_height(self) -> int:
        """The picture area's height as dragged or drawn; a picture may get less."""
        return self._wanted

    def set_wanted_height(self, height: int) -> None:
        self._wanted = max(self._least, int(height))
        self.place()

    def picture_height(self, width=None) -> int:
        """The picture area's height: never more than the picture is when it is as wide as the parts."""
        picture = self._picture
        if picture is None or picture.image() is None:
            return 0
        return min(self._wanted, picture.full_height(self._wide if width is None else width))

    def _dragged(self, top: int) -> None:
        picture = self._picture
        if picture is None or picture.image() is None:
            return
        most = picture.full_height(self._wide)    # past it a drag does nothing
        self._wanted = max(self._least, min(top + self._bar.value(), most))
        self.place()

    def _long(self, width: int) -> int:
        """The page's length with its parts `width` wide."""
        tall = self.picture_height(width)
        line = self._line.line if tall and self._line is not None else 0
        return tall + line + self._fills.content_height()

    def place(self, *_value) -> None:
        """Decide once whether the page needs its scrollbar, then give every part its place."""
        if self._placing:
            return
        self._placing = True
        try:
            width, height = self.width(), self.height()
            self._wide, bar = width, 0
            if self._pages():
                if self._long(width) > height:    # decided at the full width, and not gone back on
                    bar = self._bar.sizeHint().width()
                    self._wide = max(1, width - bar)
                self._bar.setRange(0, max(0, self._long(self._wide) - height) if bar else 0)
                self._bar.setPageStep(max(1, height))
                self._bar.setSingleStep(getattr(self._fills, "row_height", lambda: theme.ui_px(19))())
                self._bar.setGeometry(width - bar, 0, bar, height)
                self._bar.setVisible(bar > 0)
                self._bar.raise_()
            top = -self._bar.value() if bar else 0
            tall = self.picture_height()
            for spec, widget in self._parts:
                if isinstance(spec, Picture):
                    widget.setGeometry(0, top, self._wide, tall)
                    widget.setVisible(tall > 0)
                    top += tall
                elif isinstance(spec, DragLine):
                    widget.setVisible(tall > 0)
                    if tall > 0:
                        widget.setGeometry(0, top - widget.grab, self._wide, widget.line + 2 * widget.grab)
                        widget.raise_()    # its room to grab lies over the parts beside it
                        top += widget.line
                else:
                    room = max(0, height - top)    # at least to the pane's bottom, so the stripes reach it
                    widget.setGeometry(0, top, self._wide,
                                       max(room, widget.content_height()) if self._pages() else room)
        finally:
            self._placing = False

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.place()


def _art_button(spec: Button) -> QtWidgets.QToolButton:
    """A header button showing its art only."""
    button = QtWidgets.QToolButton()
    button.setObjectName(spec.name)
    button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(    # on the button itself: art only, no frame
        "QToolButton#%s { border: none; background: transparent; padding: 0; }" % spec.name)
    return button


def _part(spec):
    if isinstance(spec, Picture):
        return PictureView()
    if isinstance(spec, DragLine):
        return DragLineView(spec.height)
    if isinstance(spec, Rows):
        return RowsView(spec.drawn)
    return spec.make()


class SidePage(QtWidgets.QWidget):
    """A page built from its `Page` description; each named part is an attribute of the page."""

    def __init__(self, description: Page, parent=None) -> None:
        super().__init__(parent)
        self.description = description
        self._dimmed = True    # nothing selected: the header's texts and icon are dimmed
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header_widget = None
        if description.header is not None:
            self.header_widget = self._build_header(description.drawn, description.header)
            outer.addWidget(self.header_widget)
        parts = []
        for spec in description.body:
            widget = _part(spec)
            setattr(self, spec.name, widget)
            parts.append((spec, widget))
        self.body_widget = Body(parts)
        outer.addWidget(self.body_widget, 1)

    def _build_header(self, drawn: dict, spec: Header) -> QtWidgets.QWidget:
        header = QtWidgets.QWidget()
        ui_helpers.fill_window(header, HEADER_BG)
        header.setFixedHeight(theme.ui_px(drawn["header"]))
        head = QtWidgets.QHBoxLayout(header)    # one row; every item is centred in the drawn height
        head.setContentsMargins(theme.ui_px(drawn["pad"]), 0, theme.ui_px(spec.right_pad), 0)
        head.setSpacing(theme.ui_px(drawn["gap"]))
        self._icon_label = QtWidgets.QLabel()
        head.addWidget(self._icon_label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.name_label = QtWidgets.QLabel()
        self.name_label.setFont(theme.font("comments_title", self.name_label.font()))
        self.name_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)    # a name on disk, not HTML
        self.type_label = QtWidgets.QLabel()
        self.type_label.setFont(theme.ui_font(self.type_label.font()))
        self.type_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        head.addWidget(self.name_label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.type_label, 1, QtCore.Qt.AlignmentFlag.AlignVCenter)    # takes the free space
        for button_spec in spec.buttons:
            button = _art_button(button_spec) if button_spec.make is None else button_spec.make()
            size = button_spec.size if isinstance(button_spec.size, tuple) else (button_spec.size,) * 2
            button.setFixedSize(*(theme.ui_px(side) for side in size))
            if button_spec.gap is not None:
                head.addSpacing(theme.ui_px(button_spec.gap) - head.spacing())
            head.addWidget(button, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
            setattr(self, button_spec.name, button)
        return header

    def set_header(self, name: str, type_label: str) -> None:
        """One line: the selection's name in bold, then its type."""
        self.name_label.setText(name)
        self.type_label.setText(type_label)

    def copy_header_font(self, source: QtWidgets.QWidget):
        """Take the header's fonts from a .ui-loaded sibling; returns the base font."""
        base = theme.ui_font(source.font())
        self.type_label.setFont(base)
        self.name_label.setFont(theme.font("comments_title", base))
        return base

    def paint_header(self) -> None:
        """The header's text colours and its icon, dimmed while nothing is selected."""
        import amaze
        spec, dpr, dimmed = self.description.header, theme.screen_ratio(self), self._dimmed
        text = amazetheme.COMMENT_DIM_TEXT_OPACITY if dimmed else 1.0
        ui_helpers.set_text_color(self.name_label, "text_bright", text)
        ui_helpers.set_text_color(self.type_label, "text", text)
        self._icon_label.setPixmap(ui_helpers.faded_pixmap(ui_helpers.device_pixmap(
            amaze.package_file("ui", spec.icon), theme.ui_px(self.description.drawn["icon"]), dpr,
            {spec.art_color: amazetheme.COMMENT_DIM_ICON_COLOR if dimmed else spec.color}),
            amazetheme.COMMENT_DIM_ICON_OPACITY if dimmed else 1.0, dpr))


class Pane(QtWidgets.QWidget):
    """A pane beside the grid: one place in the splitter and one saved width for all its pages."""

    def __init__(self, preferences, pref_key: str, default_px: int, most_px: int = 0, parent=None) -> None:
        super().__init__(parent)
        self._preferences, self._pref_key, self._default_px = preferences, pref_key, default_px
        if most_px:
            self.setMaximumWidth(most_px)
        self._stack = QtWidgets.QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._none = QtWidgets.QWidget()    # current while the pane is closed, so every page is hidden
        self._stack.addWidget(self._none)

    def sizeHint(self) -> QtCore.QSize:
        """The width last dragged to, else the drawn width: what a pane that does not stretch is given."""
        remembered = int(getattr(self._preferences, self._pref_key, 0) or 0)
        return QtCore.QSize(remembered or self._default_px, super().sizeHint().height())

    def remember_width(self, splitter) -> bool:
        """Store the width the splitter gives this pane; False while it is hidden or has none."""
        index = splitter.indexOf(self)
        sizes = splitter.sizes()
        if self.isHidden() or not 0 <= index < len(sizes) or sizes[index] <= 0:
            return False
        setattr(self._preferences, self._pref_key, sizes[index])
        return True

    def add_page(self, page: SidePage) -> None:
        self._stack.addWidget(page)

    def page(self):
        """The page shown, or None while the pane is closed."""
        current = self._stack.currentWidget()
        return None if current is self._none else current

    def show_page(self, page) -> None:
        """Show `page` in the pane's place, or with None close the pane."""
        self._stack.setCurrentWidget(self._none if page is None else page)
        self.setVisible(page is not None)
