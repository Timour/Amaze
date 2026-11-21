"""The info page: an image file's picture, then a read-only table of facts about the selection."""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.core import file_info, image_preview
from amaze.helpers import theme, ui_helpers
from amaze.panel import side_pane

_DRAWN = amazetheme.drawn_info()    # every size and spacing below is from the N02 design frame
WIDER_READ_MS = 150    # a pane dragged wider reads its picture again this long after the last resize

DESCRIPTION = side_pane.Page(    # what the page is made of; the engine builds it
    drawn=_DRAWN,
    header=side_pane.Header(
        "icon_info.svg", amazetheme.INFO_ICON_COLOR, _DRAWN["preview_button_pad"],
        (side_pane.Button("preview_button", _DRAWN["preview_button"]),)),
    body=(side_pane.Picture("preview", _DRAWN["preview_height"], amazetheme.INFO_PREVIEW_LEAST),
          side_pane.DragLine("drag_line", _DRAWN["drag_line"]),
          side_pane.Rows("table", _DRAWN)))


class InfoPanel(side_pane.SidePage):
    """The side pane's page showing a selection's facts; it reads a file only while it is shown."""

    shown = QtCore.Signal()    # each show: the panel points it at the selection again

    def __init__(self, preferences, reader=None, parent=None, pictures=None) -> None:
        super().__init__(DESCRIPTION, parent)
        self._preferences = preferences
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
        self.table.setFont(self.type_label.font())
        self.preview_button.setIconSize(self.preview_button.size())
        self.preview_button.clicked.connect(self.toggle_preview)
        self.preview_button.hide()    # only an image file has a picture to hide
        saved = int(getattr(preferences, "info_preview_height", 0) or 0)
        if saved:
            self.body_widget.set_wanted_height(saved)
        self.body_widget.height_set.connect(self._on_height_set)
        self._show_no_selection()

    def copy_font(self, source: QtWidgets.QWidget) -> None:
        """Take the base font from a .ui-loaded sibling."""
        self.table.setFont(self.copy_header_font(source))

    def _paint_accents(self) -> None:
        import amaze
        self.paint_header()
        shown = self.preview_shown()
        self.preview_button.setIcon(QtGui.QIcon(ui_helpers.device_pixmap(
            amaze.package_file("ui", "icon_preview_hide.svg" if shown else "icon_preview_show.svg"),
            theme.ui_px(_DRAWN["preview_button"]), theme.screen_ratio(self))))
        self.preview_button.setToolTip(ui_helpers.tooltip_text(
            amazetheme.INFO_HIDE_PREVIEW if shown else amazetheme.INFO_SHOW_PREVIEW))

    def rows(self) -> tuple:
        """The rows shown, for tests."""
        return self.table.rows()

    def _save(self) -> None:
        save = getattr(self._preferences, "save", None)
        if save is not None:
            save()

    def _on_height_set(self, height: int) -> None:
        """A drag of the line ended: the picture area's height is remembered."""
        self._preferences.info_preview_height = int(height)
        self._save()

    def set_subject(self, subject) -> None:
        """Show a `file_info.Subject`; its read is asked for only while the pane is shown."""
        if self.isHidden():
            return
        current = self._subject
        if (current is not None and current.key == subject.key
                and current.before == subject.before and current.after == subject.after):
            return
        if current is None or current.key != subject.key:
            self.body_widget.scroll_to_top()    # another selection starts at the top of the page
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

    def preview_shown(self) -> bool:
        """Whether an image file's picture is shown: the saved setting, on until switched off."""
        return bool(getattr(self._preferences, "info_preview", True))

    def toggle_preview(self) -> None:
        """Hide or show the picture, remember it, and read the picture again when it is shown."""
        self._preferences.info_preview = not self.preview_shown()
        self._save()
        self._paint_accents()
        self.preview.set_image(None)
        self._ask_picture()

    def _show_picture_of(self, subject) -> None:
        path = self.picture_path(subject)
        self.preview_button.setVisible(bool(path))    # only an image file has a picture to hide
        if path == self._picture_path and path:
            return
        self._picture_path = path
        self.preview.set_image(None)    # never another file's picture over these rows
        self._ask_picture()

    def _picture_width(self) -> int:
        """The pane's width in screen pixels: the picture is read no wider."""
        return max(1, round(self.body_widget.width() * theme.screen_ratio(self)))

    def _ask_picture(self) -> None:
        self._wider.stop()
        if not self._picture_path or not self.preview_shown():    # hidden: the file is not read
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
        self.preview_button.hide()

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
