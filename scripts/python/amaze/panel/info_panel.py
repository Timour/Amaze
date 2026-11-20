"""The info pane: an image file's picture, then a read-only table of facts about the selection."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.core import file_info, image_preview
from amaze.helpers import theme, ui_helpers

HEADER_BG = amazetheme.COMMENT_HEADER_BG    # the comments pane's header and page colours
PAGE_BG = amazetheme.COMMENT_PAGE_BG

_DRAWN = amazetheme.drawn_info()    # every size and spacing below is from the N02 design frame
WIDER_READ_MS = 150    # a pane dragged wider reads its picture again this long after the last resize


class _Preview(QtWidgets.QWidget):
    """An image file's picture across the pane's width, its height from its shape; hidden without one."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image = None
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        ui_helpers.fill_window(self, PAGE_BG)    # shows through a picture with transparency
        self.hide()

    def image(self):
        return self._image

    def set_image(self, image) -> None:
        """Show `image`, a QImage, or None for no picture."""
        self._image = image
        self._fit()
        self.setVisible(image is not None)
        self.update()

    def _fit(self) -> None:
        image = self._image
        height = round(self.width() * image.height() / image.width()) if image is not None else 0
        if height != self.height() or self.minimumHeight() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()    # the height follows the width; the width is the pane's

    def paintEvent(self, _event) -> None:
        if self._image is None:
            return
        painter = QtGui.QPainter(self)
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(self.rect(), self._image)
        finally:
            painter.end()


class _InfoTable(QtWidgets.QWidget):
    """The rows, painted: labels on the left, values on the right, a line between the columns."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows = ()
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.NoContextMenu)
        ui_helpers.fill_window(self, PAGE_BG)

    def rows(self) -> tuple:
        return self._rows

    def set_rows(self, rows) -> None:
        """Show `rows`, (label, value) pairs; the table is at least as tall as its rows."""
        self._rows = tuple((str(label), str(value)) for label, value in rows)
        self.setMinimumHeight(self._row_top(len(self._rows)))    # the scroll area scrolls past it
        self.update()

    @staticmethod
    def _row_top(index: int) -> int:
        return theme.ui_px(_DRAWN["first_row"]) + index * theme.ui_px(_DRAWN["row"])

    def _columns(self) -> tuple:
        """(label x, label width, value x, value width); each column keeps the drawn gaps."""
        label_x = theme.ui_px(_DRAWN["label_x"])
        value_x = theme.ui_px(_DRAWN["value_x"])
        divider_x = theme.ui_px(_DRAWN["divider_x"])
        label_w = divider_x - (value_x - divider_x) - label_x    # the divider's gap on its left too
        value_w = self.width() - value_x - label_x    # the label's inset on the right edge
        return label_x, max(0, label_w), value_x, max(0, value_w)

    def text_rects(self, index: int) -> tuple:
        """(label box, value box) of row `index`: the drawn text height, dropped into its row."""
        label_x, label_w, value_x, value_w = self._columns()
        text_y = theme.ui_px(_DRAWN["text_y"])
        top = self._row_top(index) + text_y
        text_h = theme.ui_px(_DRAWN["row"]) - 2 * text_y    # centred: as much below as above
        return (QtCore.QRect(label_x, top, label_w, text_h),
                QtCore.QRect(value_x, top, value_w, text_h))

    def shown_text(self, index: int) -> tuple:
        """(label, value) of row `index` as painted: label elided right, value in the middle."""
        label, value = self._rows[index]
        _label_x, label_w, _value_x, value_w = self._columns()    # the same widths text_rects gives
        metrics = self.fontMetrics()
        return (metrics.elidedText(label, QtCore.Qt.TextElideMode.ElideRight, label_w),
                metrics.elidedText(value, QtCore.Qt.TextElideMode.ElideMiddle, value_w))

    def row_at(self, pos) -> int:
        """The row under `pos`, or -1."""
        top = theme.ui_px(_DRAWN["first_row"])
        if pos.y() < top:
            return -1
        index = (pos.y() - top) // theme.ui_px(_DRAWN["row"])
        return index if index < len(self._rows) else -1

    def tooltip_at(self, pos) -> str:
        """The whole value of the row under `pos` when it is shown elided, else ""."""
        index = self.row_at(pos)
        if index < 0:
            return ""
        value = self._rows[index][1]
        return value if self.shown_text(index)[1] != value else ""

    def event(self, event) -> bool:
        if event.type() == QtCore.QEvent.Type.ToolTip:
            text = self.tooltip_at(event.pos())
            if text:
                QtWidgets.QToolTip.showText(event.globalPos(), ui_helpers.tooltip_text(text), self)
            else:
                QtWidgets.QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    def paintEvent(self, _event) -> None:
        row_h = theme.ui_px(_DRAWN["row"])
        align = QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        painter = QtGui.QPainter(self)
        try:
            painter.setFont(self.font())
            index = 0
            while self._row_top(index) < self.height():    # the filled rows run on below the last
                if index % 2 == 0:    # rows 1, 3, 5... are filled; the rows between show the page
                    painter.fillRect(0, self._row_top(index), self.width(), row_h,
                                     QtGui.QColor(amazetheme.INFO_ROW_BG))
                index += 1
            for index in range(len(self._rows)):
                label, value = self.shown_text(index)
                label_box, value_box = self.text_rects(index)
                painter.setPen(QtGui.QColor(amazetheme.INFO_TEXT))
                painter.drawText(label_box, align, label)
                painter.drawText(value_box, align, value)
            line = theme.ui_px(amazetheme.INFO_DIVIDER_WIDTH)
            painter.fillRect(theme.ui_px(_DRAWN["divider_x"]) - line // 2, self._row_top(0),
                             line, self.height() - self._row_top(0),    # to the pane's bottom
                             QtGui.QColor(amazetheme.INFO_DIVIDER))
        finally:
            painter.end()


class InfoPanel(ui_helpers.SavedWidthPane):
    """The side pane showing a selection's facts; it reads a file only while it is shown."""

    shown = QtCore.Signal()    # each show: the panel points it at the selection again

    def __init__(self, preferences, reader=None, parent=None, pictures=None) -> None:
        super().__init__(preferences, "notes_panel_width",    # the comments pane's place and width
                         theme.ui_px(_DRAWN["width"]), parent)
        if reader is None:
            reader = file_info.Reader()
            reader.setParent(self)
        self._reader = reader
        self._reader.ready.connect(self._on_ready)
        if pictures is None:
            pictures = image_preview.Reader()
            pictures.setParent(self)
        self._pictures = pictures
        self._pictures.ready.connect(self._on_picture)
        self._picture_path = ""    # the image file the preview is for, "" for none
        self._wider = QtCore.QTimer(self)
        self._wider.setSingleShot(True)
        self._wider.setInterval(WIDER_READ_MS)
        self._wider.timeout.connect(self._ask_picture)
        self._subject = None

        self.setMinimumWidth(theme.ui_px(220))
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QtWidgets.QWidget()
        ui_helpers.fill_window(header, HEADER_BG)
        header.setFixedHeight(theme.ui_px(_DRAWN["header"]))
        head = QtWidgets.QHBoxLayout(header)    # one row; every item is centred in the drawn height
        head.setContentsMargins(theme.ui_px(_DRAWN["pad"]), 0, theme.ui_px(_DRAWN["pad"]), 0)
        head.setSpacing(theme.ui_px(_DRAWN["gap"]))
        self._icon_label = QtWidgets.QLabel()
        head.addWidget(self._icon_label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.name_label = QtWidgets.QLabel()
        self.name_label.setFont(theme.font("comments_title", self.name_label.font()))
        self.name_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)    # a name on disk, not HTML
        self.type_label = QtWidgets.QLabel()
        self.type_label.setFont(theme.ui_font(self.type_label.font()))
        self.type_label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        head.addWidget(self.name_label, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self.type_label, 1, QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.header_widget = header
        outer.addWidget(header)

        self.preview = _Preview()
        self.table = _InfoTable()
        self.table.setFont(self.type_label.font())
        body = QtWidgets.QWidget()    # the picture, then the table filling what is left
        ui_helpers.fill_window(body, PAGE_BG)
        column = QtWidgets.QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.preview)
        column.addWidget(self.table, 1)
        scroll = QtWidgets.QScrollArea()
        scroll.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidgetResizable(True)    # the body takes the pane's width; long values elide
        scroll.setWidget(body)
        ui_helpers.fill_window(scroll.viewport(), PAGE_BG)
        self.body_widget = scroll
        outer.addWidget(scroll, 1)
        self._dimmed = True
        self._show_no_selection()

    def copy_font(self, source: QtWidgets.QWidget) -> None:
        """Take the base font from a .ui-loaded sibling, as the comments pane does."""
        base = theme.ui_font(source.font())
        self.type_label.setFont(base)
        self.name_label.setFont(theme.font("comments_title", base))
        self.table.setFont(base)

    def _paint_accents(self) -> None:
        import amaze
        dpr = theme.screen_ratio(self)
        dimmed = self._dimmed    # nothing selected: labels and icon dimmed as the comments pane's
        text = amazetheme.COMMENT_DIM_TEXT_OPACITY if dimmed else 1.0
        ui_helpers.set_text_color(self.name_label, "text_bright", text)
        ui_helpers.set_text_color(self.type_label, "text", text)
        ink = amazetheme.COMMENT_DIM_ICON_COLOR if dimmed else amazetheme.INFO_ICON_COLOR
        self._icon_label.setPixmap(ui_helpers.faded_pixmap(ui_helpers.device_pixmap(
            amaze.package_file("ui", "icon_info.svg"), theme.ui_px(_DRAWN["icon"]), dpr,
            {amazetheme.INFO_ICON_ART_COLOR: ink}),
            amazetheme.COMMENT_DIM_ICON_OPACITY if dimmed else 1.0, dpr))

    def rows(self) -> tuple:
        """The rows shown, for tests."""
        return self.table.rows()

    def set_header(self, name: str, type_label: str) -> None:
        """One line: the selection's name in bold, then its type."""
        self.name_label.setText(name)
        self.type_label.setText(type_label)

    def set_subject(self, subject) -> None:
        """Show a `file_info.Subject`; its read is asked for only while the pane is shown."""
        if self.isHidden():
            return
        current = self._subject
        if (current is not None and current.key == subject.key
                and current.before == subject.before and current.after == subject.after):
            return
        self._subject = subject
        self._dimmed = False
        self.set_header(subject.name, subject.type)
        self.table.set_rows(tuple(subject.before) + tuple(subject.after))
        self._paint_accents()
        self._show_picture_of(subject)
        if subject.request is not None:
            self._reader.ask(subject.key, subject.request)
        elif current is not None:
            self._reader.stop()    # the previous subject's read is no longer wanted

    def _on_ready(self, key: str, rows: list) -> None:
        """A read's rows go between the before and after rows; another key's are dropped."""
        subject = self._subject
        if subject is None or key != subject.key:
            return
        self.table.set_rows(tuple(subject.before) + tuple(rows) + tuple(subject.after))

    @staticmethod
    def picture_path(subject) -> str:
        """The file whose picture the pane shows for `subject`: an image file it can read, else ""."""
        request = subject.request
        if request is None or request.kind != file_info.KIND_IMAGE or len(request.paths) != 1:
            return ""
        return request.paths[0] if image_preview.can_read(request.paths[0]) else ""

    def _show_picture_of(self, subject) -> None:
        path = self.picture_path(subject)
        if path == self._picture_path and path:
            return
        self._picture_path = path
        self.preview.set_image(None)    # never another file's picture over these rows
        self._ask_picture()

    def _picture_width(self) -> int:
        """The pane's width in screen pixels: the picture is read no wider."""
        return max(1, round(self.body_widget.viewport().width() * theme.screen_ratio(self)))

    def _ask_picture(self) -> None:
        self._wider.stop()
        if not self._picture_path:
            self._pictures.stop()
            return
        self._pictures.ask(self._picture_path, self._picture_width())

    def _on_picture(self, path: str, image) -> None:
        """A read's picture is shown; another file's is dropped."""
        if path == self._picture_path:
            self.preview.set_image(image)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        image = self.preview.image()
        if (image is not None and image.width() < self._picture_width()
                and not image.text(image_preview.WHOLE)):
            self._wider.start()    # dragged wider than the picture read: read it wider, once the drag rests

    def clear_subject(self) -> None:
        """Nothing selected: the dimmed header, no rows, and no read on its way."""
        self.stop_reading()
        self._show_no_selection()

    def stop_reading(self) -> None:
        """Drop the read on its way and forget the subject, so the next one is read again."""
        if self._subject is not None:    # a read is only ever asked for a current subject
            self._reader.stop()
        self._subject = None
        self._wider.stop()
        self._pictures.stop()
        self._picture_path = ""
        self.preview.set_image(None)

    def _show_no_selection(self) -> None:
        self._dimmed = True
        self.set_header(amazetheme.COMMENT_DIM_NAME, "")
        self.table.set_rows(())
        self._paint_accents()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.shown.emit()

    def hideEvent(self, event) -> None:
        self.stop_reading()
        super().hideEvent(event)
