"""The Comments pane's subject, its saves and its add menu, for either host."""

import types

from PySide6 import QtCore

from amaze import amazetheme, messages
from amaze.core import debug, grid_columns, notes

SAVE_DELAY_MS = 600       # a crash loses a sentence at most, and typing is not a write per key

ADD_ITEMS = (    # the add menu's rows, in order: (key, text); a new item type is ONE line here
    ("todo", "Bullet point"),
    ("image", "Image"),
)
PICTURE_PATTERN = "*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff"


def subject_of(pane):
    """What the Comments pane shows, or None: the selected current row's, else the first selected."""
    context = pane.active_section()
    if context is None or not context.takes_comments:    # the context decides
        return None
    selection = context.grid_selection_model()    # grid and list share it, and its current row
    index = grid_columns.selected_current_in(selection, selection)
    return context.comment_subject(index) if index is not None else None


def items_of(preferences, key: str) -> list:
    """The items of the comment `key` as the store holds them, each of a kind the editor shows."""
    return notes.normalise_items(notes.note_for(preferences, key).get("items"))


class Comments(QtCore.QObject):
    """The Comments pane's subject and its saves; the pane holds it as `comments`."""

    changed = QtCore.Signal()    # the header changed: another subject, or nothing selected

    def __init__(self, pane) -> None:
        super().__init__(pane)
        self.pane = pane
        self.document = None    # the shown view's `CommentDocument`
        self._open = False    # the pane is shown: only then does it follow the selection
        self._key = None
        self._row = None    # the subject's row in its model, whose comment mark a save changes
        self._library = ""    # the library the page was read from, and so the one its saves write to
        self._typed_in = None    # the library and user of the typing waiting to be saved
        self._loading = False
        self._header = (amazetheme.COMMENT_DIM_NAME, amazetheme.COMMENT_DIM_TYPE, True)    # name, type, dimmed
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._save_now)
        self._followed = []    # the selections whose changes point the pane at the selection
        app = QtCore.QCoreApplication.instance()
        if app is not None:    # Houdini quitting reaches no widget event of ours
            app.aboutToQuit.connect(self.flush)
        pane.models_built.connect(self._follow_selections)
        pane.context_shown.connect(self.refresh)
        pane.library_switching.connect(self.clear)    # the typing is saved to its own library first

    def name(self) -> str:
        return self._header[0]

    def type(self) -> str:
        return self._header[1]

    def dimmed(self) -> bool:
        """Nothing selected: the header is dimmed and the page takes no typing."""
        return self._header[2]

    def use_document(self, document) -> None:
        """The view's `CommentDocument`: the subject is loaded into it, and its edits are saved."""
        self.document = document
        document.document.contentsChanged.connect(self._edited)
        self._show()

    def is_open(self) -> bool:
        return self._open

    def set_open(self, on: bool) -> None:
        """Opened, the pane is pointed at the selection; closed, what was typed is saved at once."""
        self._open = bool(on)
        if self._open:
            self.refresh()
        else:
            self.flush()

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
        """Show a `sections.CommentSubject`, saving the previous one's typing first."""
        library = str(getattr(self.pane.prefs, "dir", "") or "")
        self._header = (subject.name, subject.type, False)
        if (subject.key, library) == (self._key, self._library):    # a rename: a reload would lose the typing
            self._row = subject.row
            self.changed.emit()
            return
        self.flush()
        self._key, self._library, self._row = subject.key, library, subject.row
        self._show()
        self.changed.emit()

    def clear(self) -> None:
        """Nothing selected (N01B): the same page dimmed and empty, the typing saved first."""
        self.flush()
        self._key, self._library, self._row = None, "", None
        self._header = (amazetheme.COMMENT_DIM_NAME, amazetheme.COMMENT_DIM_TYPE, True)
        self._show()
        self.changed.emit()

    def _show(self) -> None:
        """The subject's comment in the document, or none; the load is not typing."""
        if self.document is None:
            return
        self._loading = True
        try:
            if self._key is None:
                self.document.clear()
            else:
                self.document.load(self._library, self._key, items_of(self.pane.prefs, self._key))
        finally:
            self._loading = False

    def _edited(self) -> None:
        if self._loading or self._key is None:
            return
        if not self._save_timer.isActive():    # a switch then names another library and its user
            self._typed_in = types.SimpleNamespace(
                dir=self._library, library_user=self.pane.prefs.library_user)
        self._save_timer.start()

    def flush(self) -> None:
        """Write any pending edit now; switches, hides, closes and the session's end call it."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()

    def _save_now(self) -> None:
        if self._key is None or self.document is None:
            return
        if notes.set_notes(self._typed_in, {self._key: self.document.serialize()}):    # at quit no timer fires
            self._mark_row()
        else:
            debug.event("notes", "comment not saved", key=str(self._key))

    def _mark_row(self) -> None:
        """The subject's row reads its comment mark again, in every view of its model."""
        row = self._row
        if row is not None and row.isValid():
            row.model().row_changed(row.row(), [row.model().NotesRole])

    def add_rows(self) -> list:
        """The add menu's rows, as `pane.menus.Menu` gives a menu's rows."""
        return [{"key": key, "text": text, "enabled": not self.dimmed()} for key, text in ADD_ITEMS]

    def add(self, key: str, position: int) -> int:
        """Run the add menu's row `key` at cursor `position`; the new cursor position, -1 for none."""
        if self._key is None or self.document is None:
            return -1
        if key == "todo":
            return self.document.insert_todo(position)
        if key == "image":
            return self._add_image(position)
        return -1

    def _add_image(self, position: int) -> int:
        """Pick a picture, copy it into the library, and put it at `position`. ▸p/comment-images"""
        import hou

        ui = getattr(hou, "ui", None)    # absent headless, so every use of it is guarded ▸p/refuse-vs-alert
        if ui is None:
            return -1
        chosen = ui.selectFile(
            title="Add a picture to this comment", pattern=PICTURE_PATTERN,
            chooser_mode=hou.fileChooserMode.Read)    # NOT the ReadAndWrite default ▸r/select-file-write
        chosen = hou.text.expandString(chosen or "").strip()
        if not chosen:
            return -1
        src = notes.copy_image_into_library(self.pane.prefs, chosen, self._key)
        if not src:
            ui.displayMessage(messages.PICTURE_NOT_COPIED_TO_LIBRARY, title=messages.TITLE_AMAZE,
                              severity=hou.severityType.Warning)
            return -1
        at = self.document.insert_image(position, src)
        if at < 0:
            ui.displayMessage(messages.PICTURE_COPIED_BUT_UNREADABLE, title=messages.TITLE_AMAZE,
                              severity=hou.severityType.Warning)
        return at
