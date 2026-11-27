"""What the info pane shows of the selection, for either host; it reads only while open."""

from PySide6 import QtCore

from amaze import amazetheme
from amaze.core import file_info, grid_columns, image_preview

WIDER_READ_MS = 150    # a pane dragged wider reads its picture again this long after the last resize


def subject_of(pane):
    """What the info pane shows, or None: one selected row's, or several rows' together."""
    context = pane.active_section()
    if context is None or not context.takes_info:    # the context decides
        return None
    indexes = grid_columns.selected_rows(context.grid_selection_model())    # grid and list share it
    if not indexes:
        return None
    if len(indexes) == 1:
        return context.info_subject(indexes[0])
    return context.info_subject_for(indexes)


def picture_path(subject) -> str:
    """The file whose picture the pane shows for `subject`: an image file it can read, else ""."""
    request = subject.request
    if request is None or request.kind != file_info.KIND_IMAGE or len(request.paths) != 1:
        return ""
    return request.paths[0] if image_preview.can_read(request.paths[0]) else ""


class Info(QtCore.QObject):
    """The info pane's subject, rows and picture, and their reads; the pane holds it as `info`."""

    changed = QtCore.Signal()    # the header, the rows or the preview button changed
    another = QtCore.Signal()    # another selection is shown: its page starts at the top
    picture_changed = QtCore.Signal()    # `picture()` is another image, or None

    def __init__(self, pane, reader=None, pictures=None) -> None:
        super().__init__(pane)
        self.pane = pane
        self._reader = reader if reader is not None else file_info.Reader(self)
        self._reader.ready.connect(self._on_ready)
        self._pictures = pictures if pictures is not None else image_preview.Reader(self)
        self._pictures.ready.connect(self._on_picture)
        self._wider = QtCore.QTimer(self)
        self._wider.setSingleShot(True)
        self._wider.setInterval(WIDER_READ_MS)
        self._wider.timeout.connect(self._ask_picture)
        self._open = False    # the pane is shown: only then is a file read
        self._subject = None
        self._header = (amazetheme.COMMENT_DIM_NAME, "", True)    # name, type, dimmed
        self._rows = ()
        self._picture_path = ""    # the image file the preview is for, "" for none
        self._picture = None
        self._width = 0    # the picture's room in screen pixels, 0 until the view gives it
        self._followed = []    # the selections whose changes point the pane at the selection
        pane.models_built.connect(self._follow_selections)
        pane.context_shown.connect(self.refresh)
        pane.library_switching.connect(self.clear)    # the switch selects nothing

    def name(self) -> str:
        return self._header[0]

    def type(self) -> str:
        return self._header[1]

    def dimmed(self) -> bool:
        """Nothing selected: the header's texts and icon are dimmed."""
        return self._header[2]

    def rows(self) -> tuple:
        """The rows shown: the subject's before rows, a read's rows, then its after rows."""
        return self._rows

    def picture(self):
        """The picture shown, a QImage, or None."""
        return self._picture

    def preview_offered(self) -> bool:
        """Only an image file has a picture to hide."""
        return bool(self._picture_path)

    def preview_shown(self) -> bool:
        """Whether an image file's picture is shown: the saved setting, on until switched off."""
        return bool(self.pane.prefs.info_preview)

    def preview_height(self) -> int:
        """The picture area's height as last dragged, in scaled px; 0 for none."""
        return int(self.pane.prefs.info_preview_height or 0)

    def keep_preview_height(self, height: int) -> None:
        """A drag of the line ended: the picture area's height is remembered."""
        self.pane.prefs.info_preview_height = int(height)
        self.pane.prefs.save()

    def is_open(self) -> bool:
        return self._open

    def set_open(self, on: bool) -> None:
        """Opened, the pane is pointed at the selection; closed, every read stops."""
        self._open = bool(on)
        if self._open:
            self.refresh()
        else:
            self.stop_reading()

    def _follow_selections(self) -> None:
        for section in self.pane.sections.values():
            selection = section.grid_selection_model()
            if selection is not None and selection not in self._followed:
                self._followed.append(selection)
                selection.selectionChanged.connect(self.refresh)

    def refresh(self, *_args) -> None:
        """Point the pane at the current selection; returns at once while it is closed."""
        if not self._open:
            return
        subject = subject_of(self.pane)
        if subject is None:
            self.clear()
        else:
            self.set_subject(subject)

    def set_subject(self, subject) -> None:
        """Show a `file_info.Subject`; its read is asked for only while the pane is open."""
        if not self._open:
            return
        current = self._subject
        if (current is not None and current.key == subject.key
                and current.before == subject.before and current.after == subject.after):
            return
        if current is None or current.key != subject.key:
            self.another.emit()
        self._subject = subject
        self._header = (subject.name, subject.type, False)
        self._rows = tuple(subject.before) + tuple(subject.after)
        self._show_picture_of(subject)
        self.changed.emit()
        if subject.request is not None:
            self._reader.ask(subject.key, subject.request)
        elif current is not None:
            self._reader.stop()    # the previous subject's read is no longer wanted

    def _on_ready(self, key: str, rows: list) -> None:
        """A read's rows go between the before and after rows; another key's are dropped."""
        subject = self._subject
        if subject is None or key != subject.key:
            return
        self._rows = tuple(subject.before) + tuple(rows) + tuple(subject.after)
        self.changed.emit()

    def toggle_preview(self) -> None:
        """Hide or show the picture, remember it, and read the picture again when it is shown."""
        self.pane.prefs.info_preview = not self.preview_shown()
        self.pane.prefs.save()
        self._set_picture(None)
        self.changed.emit()
        self._ask_picture()

    def set_width(self, width: float) -> None:
        """The picture's room in screen pixels; wider than the picture read, it is read again."""
        known, self._width = self._width, max(1, round(width))
        if not known:    # the picture waited for its room
            self._ask_picture()
            return
        image = self._picture
        if image is not None and image.width() < self._width and not image.text(image_preview.WHOLE):
            self._wider.start()    # read it wider once the drag rests

    def _show_picture_of(self, subject) -> None:
        path = picture_path(subject)
        if path == self._picture_path and path:
            return
        self._picture_path = path
        self._set_picture(None)    # never another file's picture over these rows
        self._ask_picture()

    def _ask_picture(self) -> None:
        self._wider.stop()
        if not self._picture_path or not self.preview_shown() or not self._width:    # not read
            self._pictures.stop()
            return
        self._pictures.ask(self._picture_path, self._width)

    def _on_picture(self, path: str, image) -> None:
        """A read's picture is shown; another file's is dropped."""
        if path == self._picture_path:
            self._set_picture(image)

    def _set_picture(self, image) -> None:
        self._picture = image
        self.picture_changed.emit()

    def clear(self) -> None:
        """Nothing selected: the dimmed header, no rows, and no read on its way."""
        self.stop_reading()
        self._header = (amazetheme.COMMENT_DIM_NAME, "", True)
        self._rows = ()
        self.changed.emit()

    def stop_reading(self) -> None:
        """Drop the reads on their way and forget the subject, so the next one is read again."""
        if self._subject is not None:    # a read is only ever asked for a current subject
            self._reader.stop()
        self._subject = None
        self._wider.stop()
        self._pictures.stop()
        self._picture_path = ""
        self._set_picture(None)
        self.changed.emit()
