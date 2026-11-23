"""The File section: registered folders and every file in them, each row by its kind."""

from __future__ import annotations

import os

import hou
from PySide6 import QtCore

from amaze import amazetheme, messages
from amaze.core import debug, file_library, file_moves, grid_columns, locations, notes, scene_captures, section_list, sidebar_model
from amaze.helpers import hostos, wording
from amaze.pane import files as pane_files
from amaze.sections import base


UNDO_MOVE = (    # first in both File menus while the last move can be undone
    base.MenuEntry("Undo Move", handler="menu_undo_move", needs="always", shown="can_undo_move"),
    base.SEPARATOR,
)


def _file_count(count: int) -> str:
    """`1 file` or `3 files`, for the move messages."""
    return messages.MOVE_ONE_FILE if count == 1 else messages.MOVE_FILES % count


class FolderSection(base.Section):
    """A folder list and a files model behind TextureFilterProxyModel; stack() is None."""

    files_attr = ""
    last_folder_pref = ""
    selection_attr = ""    # with delegate_attr, what activate() points the shared grid at
    delegate_attr = ""
    search_hint = ""    # files carry no tags or categories, so the name is all there is to match
    library_model_attrs = ("file_folders_model",)    # the folders are stored in the library's files.json ▸p/folders-follow-the-library

    def __init__(self, pane) -> None:
        super().__init__(pane)
        changed = getattr(self._p(self.sidebar_attr), "scene_folder_changed", None)
        if changed is not None:
            changed.connect(self._scene_moved)
        left = getattr(self._p(self.sidebar_attr), "scene_folder_left", None)
        if left is not None:
            left.connect(self._scene_left)

    def _scene_left(self, old: str) -> None:
        """The scene row was removed: a grid showing its folder calls `activate` again."""
        try:
            active = self.pane.active_section() is self
        except RuntimeError:    # the pane was deleted, and the shared model outlives it
            return
        shown = self.shown_sidebar_key()
        if active and shown and (shown.rstrip("/") + "/").startswith(old):
            self.activate()

    def _scene_moved(self, old: str, new: str) -> None:
        """The scene's folder moved: a grid on the scene row, or inside it, shows the new folder."""
        try:
            folders = self._shown_sidebar()
        except RuntimeError:    # the pane was deleted, and the shared model outlives it
            return
        if folders is None:
            return
        if folders.is_scene_row(sidebar_model.top_level(self.pane.sidebar.selection.currentIndex())):
            self.pane.sidebar.highlight(folders.index(folders.scene_row(), 0))
            self._browse(new, remember=folders.SCENE_LABEL)

    def filter_text(self, text: str) -> None:
        proxy = self._p(self.proxy_attr)
        if proxy is not None:
            proxy.set_name_filter(text)

    def filter_favorites(self, on: bool) -> None:
        proxy = self._p(self.proxy_attr)
        if proxy is not None:
            proxy.set_favorites_only(on)

    def apply_filter(self, value) -> None:
        proxy = self._p(self.proxy_attr)
        if proxy is not None:
            proxy.set_kind_filter(value)


    def before_sidebar_shown(self) -> None:
        self._p(self.sidebar_attr).refresh_counts()    # every count is read again on entering

    def restore_sidebar_selection(self) -> None:
        """Select the remembered folder: All, the scene row, a location, or a subfolder inside one."""
        pane = self.pane
        folders = self._p(self.sidebar_attr)
        last = getattr(pane.prefs, self.last_folder_pref, "")
        if last == folders.ALL_LABEL:
            target_row = 0
        elif last == folders.SCENE_LABEL:
            target_row = folders.scene_row()
        else:
            target_row = folders.row_of(last) if last else None
        inside = ""    # a remembered subfolder: the grid shows it, the sidebar expands to it
        if target_row is None and last and last not in (folders.ALL_LABEL, folders.SCENE_LABEL):
            owner = folders.top_of(last)
            if owner.rstrip("/") != last.rstrip("/") and os.path.isdir(last):
                inside, target_row = last, folders.row_of(owner)
        if target_row is None:
            target_row = 1 if folders.rowCount() > 1 else 0    # never All: it scans every location
        if folders.rowCount() > 0:
            target_index = folders.index(target_row, 0)
            if pane.sidebar.selection is not None:
                pane.sidebar.highlight(target_index)
            if inside:
                self._browse(inside)
                pane.sidebar.reveal(inside)    # selects it once its parent folders have been read
            else:
                pane.sidebar.show_row()

    def library_switched(self) -> None:
        self.activate()    # the files model lists a folder, not the library

    def _browse(self, path, remember=None) -> None:
        """Point the files model at a folder path (None = the 'All' row), remember it, and persist."""
        files = self._p(self.files_attr)
        folders = self._p(self.sidebar_attr)
        if path is None:
            setattr(self.pane.prefs, self.last_folder_pref, folders.ALL_LABEL)
            files.set_all_folders()
        else:
            setattr(self.pane.prefs, self.last_folder_pref, path if remember is None else remember)
            files.set_folder(path)
        self.pane.prefs.save()

    def select_category(self, index) -> None:
        folders = self._p(self.sidebar_attr)
        remember = folders.SCENE_LABEL if folders.is_scene_row(index) else None    # by SCENE_LABEL: the scene's folder can change
        self._browse(index.data(folders.BrowseRole), remember)    # a location's path, or a subfolder's

    def shown_sidebar_key(self) -> str:
        files = self._p(self.files_attr)
        return files.browsing() if files is not None else ""

    def select_sidebar_key(self, key: str) -> None:
        """A rowless subfolder selects its location: until its row is read, or always if deleted."""
        folders = self._shown_sidebar()
        if not (key and folders is not None and self._has_no_row(folders, key)):
            super().select_sidebar_key(key)
            return
        if not os.path.isdir(key):    # deleted from disk: select its location row and show its files
            super().select_sidebar_key(folders.top_of(key))
            return
        self.pane.sidebar.highlight(folders.index(folders.row_of(folders.top_of(key)), 0))
        if self.shown_sidebar_key() != key:
            self._browse(key)
        self.pane.sidebar.reveal(key)

    @staticmethod
    def _has_no_row(folders, path: str) -> bool:
        """Is `path` a folder inside a top row's folder, with no row of its own?"""
        owner = folders.top_of(path)
        return (owner.rstrip("/") != path.rstrip("/") and folders.row_of(owner) is not None
                and not folders.index_of(path).isValid())

    def tile_models(self):
        return self._p(self.files_attr), self._p(self.proxy_attr)

    def selected_kinds(self, indexes) -> set:
        """Every kind in the selection, read once for the whole Grid menu."""
        files = self._p(self.files_attr)
        if files is None:
            return set()
        return {index.data(files.KindRole) or "" for index in indexes}

    def _path_of(self, index) -> str:
        files = self._p(self.files_attr)
        if files is None or index is None or not index.isValid():
            return ""
        return str(index.data(files.PathRole) or "")

    def selection_has_importable(self, indexes, current) -> bool:
        return bool(self.selected_kinds(indexes)
                    & {locations.KIND_IMAGE, locations.KIND_GEO})

    def selection_has_scene(self, indexes, current) -> bool:
        return locations.KIND_HIP in self.selected_kinds(indexes)

    def menu_offers_preview(self, indexes, current) -> bool:
        files, rows = self._model_and_rows(indexes)    # a capture, an OS icon and a .rat not rendered cannot re-render
        return bool(self.offers_preview_update and files is not None
                    and any(files.renders_thumbnail(row) for row in rows))

    def menu_import_enabled(self, indexes, current) -> bool:
        """An image loads onto one node parameter, so images import one at a time; geometry imports all."""
        kinds = self.selected_kinds(indexes)
        return len(indexes) == 1 or kinds == {locations.KIND_GEO}

    def menu_capture_enabled(self, indexes, current) -> bool:
        """One tile; a scene only while it is the one open, however it was opened."""
        if len(indexes) != 1:
            return False
        files = self._p(self.files_attr)
        if files is None or current is None or \
                current.data(files.KindRole) != locations.KIND_HIP:
            return True
        path = self._path_of(current)    # with another scene open, the capture would be saved under this one
        return bool(path) and path == scene_captures.current_scene_path()

    def menu_import(self, indexes, current, payload=None) -> None:
        files = self._p(self.files_attr)
        if files is None:
            return
        if self.selected_kinds(indexes) == {locations.KIND_IMAGE}:
            self.pane.loading.click_on_row(self, current)    # `click_on_row`, the same call as a double-click on the row
            return
        for index in indexes:
            if index.data(files.KindRole) == locations.KIND_GEO:
                self.pane.loading.import_geo_asset(index)

    def menu_load_scene(self, indexes, current, payload=None) -> None:
        self.open_hip_scene(current)

    def menu_copy_path(self, indexes, current, payload=None) -> None:
        self.pane.files.copy_paths(indexes)

    def menu_reveal(self, indexes, current, payload=None) -> None:
        path = self._path_of(current)
        if not path:
            return
        try:
            pane_files.reveal(path)
        except Exception as exc:                         # noqa: BLE001
            debug.event("file", "reveal failed", error=str(exc))

    def menu_new_enabled(self, indexes, current) -> bool:
        """New Folder and Save Scene act on the folder shown: none while All is showing."""
        return bool(self._shown_folder())

    def _shown_folder(self) -> str:
        files = self._p(self.files_attr)
        return files.browsing() if files is not None else ""

    def _ask_new_name(self, title: str, then) -> None:
        """`then(name)` with the typed name; nothing for a cancel, a cleared field, or a slash in it."""
        def typed(name):
            name = (name or "").strip()
            if name and ("/" in name or os.sep in name):
                debug.refuse(messages.NEW_NAME_HAS_A_SLASH % name)
                return
            if name:
                then(name)
        self.pane.ui.ask_name(title, "", typed)

    def menu_new_folder(self, indexes, current, payload=None) -> None:
        folder = self._shown_folder()
        if folder:
            self._ask_new_name("New Folder", lambda name: self._make_folder(folder, name))

    def _make_folder(self, folder: str, name: str) -> None:
        """A new folder `name` inside `folder`; a name in use or a failed write is refused."""
        path = os.path.join(folder, name)
        if os.path.exists(path):
            debug.refuse(messages.NEW_FOLDER_TAKEN % (name, folder))
            return
        try:
            os.makedirs(path)
        except OSError as exc:
            debug.refuse(messages.NEW_FOLDER_FAILED % (name, exc))
            return
        debug.event("file", "folder made", path=path)
        self._refresh_shown()

    def menu_save_scene(self, indexes, current, payload=None) -> None:
        """Save As of the open scene into the folder shown; the file becomes the open scene."""
        folder = self._shown_folder()
        if folder:
            self._ask_new_name("Save Scene", lambda name: self._save_scene_as(folder, name))

    def _save_scene_as(self, folder: str, name: str) -> None:
        """The open scene saved as `name` in `folder`, then the open scene; a name in use is refused."""
        path = os.path.join(folder, name + scene_captures.scene_extension())
        if os.path.exists(path):
            debug.refuse(messages.SAVE_SCENE_TAKEN % (os.path.basename(path), folder))
            return
        try:
            hou.hipFile.save(path)
        except hou.Error as exc:
            debug.refuse(messages.SAVE_SCENE_FAILED % (path, exc))
            return
        debug.event("hip", "scene saved as new", file=path)
        self._refresh_shown()

    def _refresh_shown(self) -> None:
        """The grid lists the folder again; the sidebar re-reads it, so a new subfolder gets its row."""
        folders, files = self._p(self.sidebar_attr), self._p(self.files_attr)
        if files is not None:
            files.refresh_current_folder()
        if folders is not None:
            folders.refresh_counts()

    def toggle_favourite(self, indexes) -> None:
        files, rows = self._model_and_rows(indexes)    # the model resolves each row to its path key
        if files is not None:
            files.toggle_favorites(rows)

    takes_file_drops = True    # ▸r/cross-volume-move
    _last_move = ()    # (source, destination) per file of the last move, until it is undone

    def accepts_file_drop(self, index) -> bool:
        """A location, or a folder inside one; never All."""
        return bool(self.drop_folder(index))

    def drop_folder(self, index) -> str:
        folders = self._p(self.sidebar_attr)
        return str(index.data(folders.BrowseRole) or "") if folders is not None else ""

    def move_files_to(self, folder: str) -> bool:
        """Move the grid's selected files into `folder`, on a worker; True when a move started."""
        if file_moves.mover.busy():
            debug.refuse(messages.MOVE_BUSY)
            return False
        selection = self._p(self.selection_attr)
        paths = [self._path_of(index) for index in
                 (grid_columns.selected_rows(selection) if selection is not None else ())]
        scene = scene_captures.current_scene_path()
        open_scene = [path for path in paths if path and scene
                      and hostos.canonical_path_key(path) == hostos.canonical_path_key(scene)]
        notices = [messages.MOVE_OPEN_SCENE % os.path.basename(path) for path in open_scene]
        pairs = file_moves.targets([path for path in paths if path not in open_scene], folder)
        if not pairs:
            if notices:
                debug.refuse(" ".join(notices))
            return False
        self._start_move(pairs, folder, notices, undo=False)
        return True

    def can_undo_move(self, indexes, current) -> bool:
        return bool(self._last_move) and not file_moves.mover.busy()

    def menu_undo_move(self, indexes, current, payload=None) -> None:
        pairs = file_moves.back(self._last_move)
        if not pairs or file_moves.mover.busy():
            return
        self._last_move = ()
        self._start_move(pairs, os.path.dirname(pairs[0][1]), [], undo=True)

    def menu_copy(self, indexes, current, payload=None) -> None:
        """The selected files go on the system clipboard, as files."""
        paths = [self._path_of(index) for index in indexes]
        if pane_files.copy_files(paths):
            debug.event("file", "files copied", count=len([path for path in paths if path]))

    def menu_paste_enabled(self, indexes, current) -> bool:
        """A folder is shown, the clipboard holds files, and no move or paste is running."""
        return bool(self._shown_folder() and pane_files.clipboard_files()
                    and not file_moves.mover.busy())

    def menu_paste(self, indexes, current, payload=None) -> None:
        """Copy the clipboard's files into the folder shown; names in use are asked about once."""
        folder = self._shown_folder()
        paths = pane_files.clipboard_files()
        if not folder or not paths or file_moves.mover.busy():
            return
        notices = [messages.PASTE_FOLDER % os.path.basename(path.rstrip("/\\"))
                   for path in paths if os.path.isdir(path)]
        pairs = [(path, os.path.join(folder, os.path.basename(path)))
                 for path in paths if not os.path.isdir(path)]
        taken = [pair for pair in pairs
                 if os.path.lexists(pair[1]) and not file_moves.same_file(*pair)]
        answer = self._ask_overwrite(taken) if taken else "skip"
        if answer == "cancel":
            return
        if answer == "skip":
            pairs = [pair for pair in pairs if pair not in taken]
        if not pairs:
            if notices:
                debug.refuse(" ".join(notices))
            return
        self._move_job = {"count": len(pairs), "name": self._folder_name(folder),
                          "notices": notices, "undo": False, "percent": -1, "paste": True}
        file_moves.mover.start(pairs, self.pane.prefs, self._move_progress, self._move_finished,
                               copying=True, replace=answer == "overwrite")

    def _ask_overwrite(self, taken) -> str:
        """`overwrite`, `skip` or `cancel` for the names already in the folder; `skip` without a UI."""
        ui = getattr(hou, "ui", None)
        if ui is None:
            return "skip"
        lines = self._name_in_use_lines(taken, "asked")
        choice = ui.displayMessage(
            " ".join(lines), buttons=messages.BUTTONS_OVERWRITE_OR_SKIP,
            default_choice=1, close_choice=2,
            title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
        return ("overwrite", "skip", "cancel")[choice]

    def _start_move(self, pairs, folder: str, notices, undo: bool) -> None:
        self._move_job = {"count": len(pairs), "name": self._folder_name(folder),
                          "notices": list(notices), "undo": undo, "percent": -1, "paste": False}
        file_moves.mover.start(pairs, self.pane.prefs, self._move_progress, self._move_finished)

    def _move_progress(self, done, total) -> None:
        """A copy's progress on the status line, once per whole percent."""
        job = self._move_job
        percent = int(done * 100 / total) if total else 100
        if percent != job["percent"]:
            job["percent"] = percent
            count, name = _file_count(job["count"]), job["name"]
            debug.status(messages.PASTE_PROGRESS % (count, name, percent) if job["paste"]
                         else messages.MOVE_PROGRESS % (count, name, percent))

    def _move_finished(self, result) -> None:
        """Refresh the models, offer Undo after a move, and show the result on one line."""
        job = self._move_job
        for attr in (self.files_attr, self.sidebar_attr):
            model = self._p(attr)
            if model is not None:
                (model.refresh_counts if attr == self.sidebar_attr
                 else model.refresh_current_folder)()
        paste = job["paste"]
        if not paste:    # a paste leaves the last move undoable
            self._last_move = () if job["undo"] else tuple(result.moved)
        lines = list(job["notices"])
        if result.moved:
            count = _file_count(len(result.moved))
            if job["undo"]:
                lines.insert(0, messages.MOVE_BACK % count)
            elif paste:
                lines.insert(0, messages.PASTE_DONE % (count, job["name"]))
            else:
                lines.insert(0, messages.MOVE_DONE % (count, job["name"]))
        lines += self._name_in_use_lines(result.skipped, "pasted" if paste else "moved")
        lines += [messages.PASTE_FAILED % (os.path.basename(source), why) if paste
                  else messages.MOVE_FAILED % (os.path.basename(source), why)
                  for source, why in result.failed]
        if job["notices"] or result.skipped or result.failed:
            debug.refuse(" ".join(lines))
        elif lines:
            debug.status(" ".join(lines))

    def _name_in_use_lines(self, skipped, said="moved") -> list:
        """One sentence per folder with names in use, worded as `moved`, `pasted` or `asked`."""
        by_folder = {}
        for _source, dest in skipped:
            by_folder.setdefault(os.path.dirname(dest), []).append(os.path.basename(dest))
        lines = []
        for folder, names in by_folder.items():
            shown = names[:3] + ([messages.MOVE_MORE % (len(names) - 3)] if len(names) > 3 else [])
            listed, name = wording.and_list(shown), self._folder_name(folder)
            one, many = {
                "moved": (messages.MOVE_TAKEN % (listed, name),
                          messages.MOVE_TAKEN_MANY % (listed, name)),
                "pasted": (messages.PASTE_TAKEN % (listed, name),
                           messages.PASTE_TAKEN_MANY % (listed, name)),
                "asked": (messages.PASTE_ASK % (listed, name),
                          messages.PASTE_ASK_MANY % (listed, name)),
            }[said]
            lines.append(one if len(names) == 1 else many)
        return lines

    def _folder_name(self, folder: str) -> str:
        """A folder as the sidebar names it, else its own name."""
        folders = self._p(self.sidebar_attr)
        index = folders.index_of(folder) if folders is not None else QtCore.QModelIndex()
        shown = index.data() if index.isValid() else ""
        return str(shown or os.path.basename(folder.rstrip("/\\")) or folder)

    colour_title = "Location Color"

    def location_key(self, index) -> str:
        """The registered location on this row, by its path; "" on All, the scene row and a subfolder."""
        folders = self._p(self.sidebar_attr)
        if folders is None or index is None or not index.isValid():
            return ""
        return str(index.data(folders.PathRole) or "")

    def colour_key(self, index) -> str:
        return self.location_key(index)    # a colour belongs to a location, never to a subfolder

    def repaint_grid_colours(self) -> None:
        files = self._p(self.files_attr)
        if files is not None and files.rowCount():    # every tile from that location repaints, role-scoped
            files.colours_changed()    # drop the colour cache before the repaint
            files.dataChanged.emit(
                files.index(0, 0), files.index(files.rowCount() - 1, 0),
                [files.CategoryColorRole])

    offers_preview_update = True

    def update_preview(self, indexes) -> None:
        files, rows = self._model_and_rows(indexes)    # ONE batch: images re-convert, scenes re-read
        if rows:
            files.rerender_thumbnails(rows)

    def comment_subject(self, index):
        model, proxy = self.tile_models()    # a row here is a file, keyed by its path
        if model is None or proxy is None:
            return None
        source = proxy.mapToSource(index)
        if not source.isValid():
            return None
        path = model.file_key(source.row())
        if not path:
            return None
        return base.CommentSubject(
            key=notes.note_key(self.key, path),
            name=source.data(QtCore.Qt.ItemDataRole.DisplayRole) or "",
            type=source.data(model.FormatRole) or "",
        )


class FileSection(FolderSection):
    """One folder list, every file shown, each row handled by its kind. ▸o/section-api"""

    key = "file"
    label = section_list.label(key)
    filter_tooltip = "Show one kind of file."
    empty_noun = "file"

    FILTER_CHOICES = (  # the known kinds, in the order kind_for tests them; KIND_OTHER has no entry
        base.FilterEntry("Images", "Images", locations.KIND_IMAGE),
        base.FilterEntry("Geometry", "Geometry", locations.KIND_GEO),
        base.FilterEntry("Hip", "Hip", locations.KIND_HIP),
    )

    GRID_MENU = UNDO_MOVE + (  # the selection's KINDS decide the actions; no Delete: these are the user's own files
        base.MenuEntry("New Folder", handler="menu_new_folder", needs="menu_new_enabled"),
        base.SEPARATOR,
        base.MenuEntry("Copy", handler="menu_copy"),
        base.MenuEntry("Paste", handler="menu_paste", needs="menu_paste_enabled"),
        base.SEPARATOR,
        base.MenuEntry("Open Scene", handler="menu_load_scene", needs="one",
                  shown="selection_has_scene"),
        base.MenuEntry("Save Scene", handler="menu_save_scene", needs="menu_new_enabled"),
        base.SEPARATOR,
        base.MenuEntry("Load Asset", handler="menu_import", needs="menu_import_enabled",
                  shown="selection_has_importable"),
        base.MenuEntry("Copy Path", handler="menu_copy_path"),
        base.SEPARATOR,
        base.MenuEntry("Show Location", handler="menu_reveal", needs="one"),
        base.SEPARATOR,
    ) + base.GRID_MENU_TAIL

    _PATH_ONLY = base.DropRule(on_node="drop_file_path_on_node",    # per row kind: every kind sets its path on a node; a drop off any node differs
                          click_resolve="click_copy_path")
    DROP_BY_KIND = {
        locations.KIND_IMAGE: base.DropRule(
            on_node="drop_file_path_on_node",
            on_space="create_image_node_in",
            click_on_node="drop_file_path_on_node",
            holder_node_type="mtlximage"),  # the drag preview shows THIS node type
        locations.KIND_GEO: base.DropRule(
            on_node="drop_file_path_on_node",
            resolve="drop_geo_at_release",
            click_on_node="drop_file_path_on_node",
            click_resolve="click_import_geo"),
        locations.KIND_HIP: base.DropRule(
            on_node="drop_file_path_on_node",
            click_resolve="click_open_hip"),
        locations.KIND_OTHER: _PATH_ONLY,
        "": _PATH_ONLY,
    }

    exports_selection = True

    def export_package_to(self, indexes, path: str) -> int:    # the File version: each selected file is packaged whole under its kind
        items = []
        from amaze.core import packages
        for index in indexes:
            if index is None or not index.isValid():
                continue
            source = index.data(file_library.FileFiles.PathRole)
            if not source:
                continue
            kind = (index.data(file_library.FileFiles.KindRole)
                    or file_library.kind_for(os.path.basename(source)))
            items.append(packages.collect_file(source, kind))
        if not items:
            return 0
        return packages.write_package(path, items)

    def click_import_geo(self, index) -> bool:
        self.pane.loading.import_geo_asset(index)
        return True

    def drop_geo_at_release(self, index: QtCore.QModelIndex) -> bool:
        """Import dropped geometry into the network under the cursor; quietly False if none."""
        from amaze.core import dragengine
        from amaze.helpers import helpers
        pane = self.pane
        context = pane.drop_placement.context_under_cursor(
            pane.drop_placement.is_sop_container, include_viewports=True
        )
        if context is None:
            return False
        path = index.data(pane.file_files_model.PathRole)
        if not path:
            return False
        with dragengine.drop_group("Amaze Import Geometry"):
            created = pane.drop_placement.import_geo_in_context(path, context)
        if created is not None:
            helpers.place_nodes([created],
                                pane.drop_placement.release_position_in(context))
        return True

    def click_open_hip(self, index) -> bool:
        self.open_hip_scene(index)
        return True

    def open_hip_scene(self, index) -> None:
        """Open a scene file from the grid; Houdini's own save prompt handles unsaved changes."""
        path = self.pane.files.hip_path_for(index)
        if not path:
            return
        if not os.path.isfile(path):
            debug.refuse(debug.Damage(messages.SCENE_FILE_MISSING % path))    # ▸p/refuse-vs-alert
            debug.event("hip", "scene missing", file=path)
            return
        try:
            hou.hipFile.load(path, suppress_save_prompt=False,
                             ignore_load_warnings=False)
        except hou.LoadWarning as warn:    # a scene that loads with warnings is still open
            debug.event("hip", "opened with warnings", file=path,
                        warning=str(warn)[:400])
        except Exception as exc:                         # noqa: BLE001
            debug.refuse(debug.Damage(messages.SCENE_OPEN_FAILED % (path, exc)))
            debug.event("hip", "open failed", file=path, error=str(exc))
            return
        debug.event("hip", "scene opened", file=path)

    def drop_file_path_on_node(self, index, node) -> bool:
        """A File row dropped on a node sets its first file parameter; False if it has none."""
        pane = self.pane
        from amaze.core import dragengine
        from amaze.helpers import helpers
        path = index.data(pane.file_files_model.PathRole)
        if not path:
            return False
        parm = helpers.find_file_parm(node)
        if parm is None:
            debug.refuse(messages.NODE_HAS_NO_FILE_PARM
                         % (node.name(), os.path.basename(path)))
            return False
        with dragengine.drop_group("Amaze Set File Path"):
            parm.set(pane.drop_placement.scene_path(path))
        return True

    def create_image_node_in(self, index, dest, position=None) -> bool:
        """Create a mtlximage node set to the file's path, where the network can contain one."""
        pane = self.pane
        from amaze.core import dragengine
        from amaze.helpers import helpers
        path = index.data(pane.file_files_model.PathRole)
        if not path:
            return False
        base = wording.sanitize_usd_path(
            os.path.splitext(os.path.basename(path))[0]) or "image"
        with dragengine.drop_group("Amaze Create Image Node"):
            node = pane.drop_placement.create_holder_node(dest, "mtlximage", base, position)
            if node is None:
                return False
            parm = helpers.find_file_parm(node)
            if parm is None:
                node.destroy()
                return False
            parm.set(pane.drop_placement.scene_path(path))
        return True

    def click_copy_path(self, index) -> bool:
        """Copy the path: the only click action for a file of unknown kind."""
        self.pane.files.copy_paths([index])
        return True

    SIDEBAR_MENU = UNDO_MOVE + (  # per-location entries need a REAL row: All is no location, its key `""`
        base.MenuEntry("Add", handler="menu_add_location", needs="always"),
        base.MenuEntry("Locate", handler="menu_locate_location",
                  needs="on_a_location"),
        base.MenuEntry("Rename", handler="menu_rename_location",
                  children="rename_actions", needs="on_a_location"),
        base.MenuEntry("Remove", handler="menu_remove_location",
                  needs="on_a_location"),
        base.SEPARATOR,
        base.MenuEntry("Sort by name", handler="menu_sort_locations",
                  needs="always"),
        base.SEPARATOR,
        base.MenuEntry("Label", handler="menu_label_colour", children="label_colours",
                  needs="on_a_location"),
    )

    def menu_sort_locations(self, indexes, current, payload=None) -> None:
        """Sort by name, once: the locations below All and the scene row, from any row clicked."""
        folders = self._p(self.sidebar_attr)
        if folders is None:
            return
        shown = self.shown_sidebar_key()    # the grid's folder: a right press moved only the sidebar
        if not folders.sort_folders():    # a model reset, which clears the sidebar's selection
            return
        folders.commit_order()    # one write, as on a drag's release
        self.select_sidebar_key(shown)

    def on_a_location(self, indexes, current) -> bool:
        return bool(self.location_key(current))

    def rename_actions(self, indexes, current) -> tuple:
        """Edit names the location; Set to Default goes back to the folder's own name."""
        path = self.location_key(current)
        named = bool(path and self.pane.prefs.file_folder_names.get(path))
        return (("Edit", "edit", "", True), None,
                ("Set to Default", "default", "", named))    # disabled with no name set, never hidden

    def _repaint_location(self, path: str) -> None:
        folders = self._p(self.sidebar_attr)
        row = folders.row_of(path) if folders is not None else None
        if row is not None:
            index = folders.index(row, 0)
            folders.dataChanged.emit(index, index)

    def menu_rename_location(self, indexes, current, payload=None) -> None:
        path = self.location_key(current)
        if not path:
            return
        if payload == "default":
            self._name_location(path, "")
            return
        prefs = self.pane.prefs
        self.pane.ui.ask_name(
            "Rename Location", prefs.file_folder_names.get(path)
            or os.path.basename(path.rstrip("/\\")),    # the field starts with the name, never the path
            lambda name: name is not None and self._name_location(path, name))

    def _name_location(self, path: str, name: str) -> None:
        """Show the location at `path` as `name`; "" goes back to its folder's own name."""
        self.pane.prefs.set_file_folder_name(path, name)
        self._repaint_location(path)

    def menu_add_location(self, indexes, current, payload=None) -> None:
        self.pane.files.add_location()

    def menu_remove_location(self, indexes, current, payload=None) -> None:
        self.reselect_after_removal(self.pane.files.remove_locations())

    def menu_locate_location(self, indexes, current, payload=None) -> None:
        self.pane.files.locate_folder(self._p(self.sidebar_attr))

    proxy_attr = "file_sorted_model"
    selection_attr = "file_selection_model"
    delegate_attr = "file_delegate"
    tile_badges = ("open", "favourite", "comment")
    list_columns = ("name", "type", "favorite", "open", "comments")
    sidebar_attr = "file_folders_model"
    files_attr = "file_files_model"
    last_folder_pref = "last_file_folder"

    def prefs_changed(self) -> None:
        folders, files = self._p(self.sidebar_attr), self._p(self.files_attr)
        if folders is not None:
            folders.refresh_counts()    # Show Unknown Files changes what counts as a row
        if files is not None:
            files.refresh_current_folder()    # once, so display preferences apply without a click
