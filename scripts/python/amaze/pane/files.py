"""The File section's work on disk: its locations, paths, the clipboard and the file browser."""

import os

from PySide6 import QtCore, QtGui
import hou

from amaze import messages
from amaze.actions import files as files_actions
from amaze.core import debug, folders, locations
from amaze.helpers import wording


def reveal(path: str) -> None:
    """Show `path` in the system file browser with Houdini's `fileutils.revealFile`; never raises."""
    if not os.path.exists(path):    # the system's command fails on it without raising
        debug.refuse(messages.REVEAL_MISSING % path)
        return
    try:
        import fileutils    # ships in Houdini's python libs ▸r/show-in-file-browser-macos
        fileutils.revealFile(path)
    except Exception as exc:                             # noqa: BLE001 - the command is missing or failed
        debug.refuse(messages.REVEAL_FAILED % exc)
        return
    debug.event("file", "shown in the file browser", path=path)


def copy_files(paths) -> bool:
    """Put `paths` on the system clipboard as files, and as text one per line; False without one."""
    clipboard = QtGui.QGuiApplication.clipboard()
    paths = [path for path in paths if path]
    if clipboard is None or not paths:
        return False
    data = QtCore.QMimeData()
    data.setUrls([QtCore.QUrl.fromLocalFile(path) for path in paths])
    data.setText("\n".join(paths))
    clipboard.setMimeData(data)
    return True


def clipboard_files() -> list:
    """The paths of the local files and folders on the system clipboard, in its order."""
    clipboard = QtGui.QGuiApplication.clipboard()
    data = clipboard.mimeData() if clipboard is not None else None
    if data is None or not data.hasUrls():
        return []
    return [url.toLocalFile() for url in data.urls() if url.isLocalFile()]


class Files:
    """The File section's locations and files; the pane holds it as `files`."""

    def __init__(self, pane) -> None:
        self.pane = pane
        self.scene_watch = None    # the scene row's hipFile callback, one per pane

    def hip_path_for(self, index):
        """The scene path behind a File-grid index, or '' for a row that is not a scene."""
        if index is None or not index.isValid():
            return ""
        files = self.pane.file_files_model
        if index.data(files.KindRole) != locations.KIND_HIP:
            return ""
        return index.data(files.PathRole) or ""

    def copy_paths(self, proxy_indexes) -> None:
        """Copy the selection's paths to the clipboard as Houdini paths, one per line."""
        paths = []
        for proxy_index in proxy_indexes:
            path = proxy_index.data(self.pane.file_files_model.PathRole) or ""
            if path:
                paths.append(self.pane.drop_placement.scene_path(path))    # written as the session writes parm paths
        if not paths:
            return
        QtGui.QGuiApplication.clipboard().setText("\n".join(paths))    # no dialog - the changed clipboard IS the feedback
        debug.event("file", "paths copied", count=len(paths))

    def add_location(self) -> None:
        """Register a folder for the File section; stores the path only, nothing is scanned."""
        ui = getattr(hou, "ui", None)
        path = ui.selectFile(file_type=hou.fileType.Directory) if ui else ""
        if not path:
            return
        path = hou.text.expandString(path)
        if self.pane.file_folders_model.is_location(path):
            ui.displayMessage(messages.LOCATION_ALREADY_ADDED, title=messages.TITLE_AMAZE,
                              severity=hou.severityType.Warning)
            return
        self.pane.file_folders_model.add_folder(path)

    def remove_locations(self) -> list:
        """Unregister the selected location(s) once the user says Remove; the removed paths."""
        folders_model = self.pane.file_folders_model
        rows = sorted(    # top rows only: a subfolder's row number is not a location's
            (i.row() for i in self.pane.sidebar.rows() if not i.parent().isValid()),
            reverse=True
        )
        paths = {row: folders_model.registered_at(row) for row in rows}
        rows = [row for row in rows if paths[row]]    # All and the scene row are not locations
        if not rows:
            return []
        names = wording.and_list('"%s"' % folders_model.display_name(paths[row])
                                 for row in reversed(rows))
        ui = getattr(hou, "ui", None)
        if ui is None or ui.displayMessage(
                messages.REMOVE_LOCATION_CONFIRM % names, buttons=messages.BUTTONS_REMOVE,
                default_choice=1, close_choice=1,
                title=messages.TITLE_AMAZE, severity=hou.severityType.Warning) != 0:
            return []
        return [paths[row] for row in rows if folders_model.remove_folder(row)]

    def locate_folder(self, folders_model) -> None:
        """Sidebar "Locate Folder...": re-point the selected registered folder at a new location."""
        ui = getattr(hou, "ui", None)
        indexes = self.pane.sidebar.rows()
        row = indexes[0].row() if indexes and not indexes[0].parent().isValid() else -1    # top rows
        if row <= 0 or not folders_model.registered_at(row):    # nothing selected, All or the scene row: no location
            if ui is not None:
                ui.displayMessage(
                    messages.NO_FOLDER_SELECTED_TO_RELOCATE,
                    title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                )
            return
        path = ui.selectFile(file_type=hou.fileType.Directory) if ui else ""
        if not path:
            return
        rewritten = folders_model.relocate_folder(
            row, hou.text.expandString(path))    # favorites moved; negative: not a folder
        if rewritten < 0:
            if ui is not None:
                ui.displayMessage(
                    messages.LOCATION_ALREADY_ADDED if rewritten == folders.ALREADY_A_LOCATION
                    else messages.RELOCATE_TARGET_NOT_A_FOLDER,
                    title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                )
            return
        if rewritten:
            debug.event("folders", "relocated", favorites=rewritten)
        self.pane.sidebar.show_row()    # rescan under the new path

    def locate_unreadable(self, path: str) -> None:
        """Locate in the unreachable-folder empty state: select the named folder, re-point it."""
        model = getattr(self.pane, "file_folders_model", None)
        if model is None or not path:
            return
        row = model.row_of(path)
        view_model = self.pane.sidebar.model
        if row is None or view_model is None:
            return
        self.pane.sidebar.highlight(view_model.index(row, 0))
        self.locate_folder(model)
        context = self.pane.active_section()
        if context is not None:
            context.reselect_sidebar_row()    # a cancelled or failed Locate moved only the highlight

    def move_files(self, folder: str) -> bool:
        """Move the ACTIVE section's selected files into `folder`; True when a move started."""
        context = self.pane.active_section()
        return bool(context is not None and context.takes_file_drops
                    and context.move_files_to(folder))

    def unwatch_scene(self) -> None:
        """The scene row stops tracking the open scene; a second call does nothing."""
        watch, self.scene_watch = self.scene_watch, None
        if watch is not None:
            files_actions.unwatch_scene(watch)
