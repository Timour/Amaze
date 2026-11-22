"""What the grid does to library assets: favourite, delete, render, convert, edit, export."""

import os

from PySide6 import QtCore
import hou

from amaze import messages
from amaze.actions import materials as material_actions
from amaze.core import grid_columns, library, renderers, tile_icons
from amaze.pane import asks


class Assets:
    """The grid selection's library work; the pane holds it as `assets`."""

    def __init__(self, pane) -> None:
        self.pane = pane

    def toggle_favourite(self, indexes) -> None:
        """Toggle the favourite on the grid's selection, via the section's `toggle_favourite`."""
        context = self.pane.active_section()
        if context is None:
            return
        context.toggle_favourite(list(indexes))

    def click_badge(self, handler: str, index) -> None:
        """A tile badge's click: the section's `handler` on the grid selection if the tile is in it."""
        context = self.pane.active_section()
        if context is None or not hasattr(context, handler):
            return
        rows = context.grid_selection()
        getattr(context, handler)(rows if index in rows else [index], index)

    def update_preview(self, indexes) -> None:
        """Re-render the grid selection's thumbnails, through the active context."""
        context = self.pane.active_section()
        if context is None:
            return
        context.update_preview(list(indexes))

    def delete(self, indexes) -> None:
        """Delete the grid selection after the context's prompt; not where `deletes_rows` is off."""
        context = self.pane.active_section()
        if context is None or not context.deletes_rows:
            return
        proxy = getattr(self.pane, context.proxy_attr, None) if context.proxy_attr else None
        sources = []
        seen = set()
        for index in indexes:
            source = proxy.mapToSource(index) if proxy is not None else index
            if source.isValid() and source.row() not in seen:
                seen.add(source.row())
                sources.append(source)
        if not sources:
            return
        name = sources[0].data(QtCore.Qt.ItemDataRole.DisplayRole) or ""    # for a prompt that quotes it
        ui = getattr(hou, "ui", None)
        if ui is None or ui.displayMessage(
            context.delete_prompt(len(sources), name),
            buttons=messages.BUTTONS_DELETE,
            default_choice=1, close_choice=1,
            title=messages.TITLE_AMAZE, severity=hou.severityType.Warning,
        ) != 0:
            return
        context.delete_rows(sources)

    def convert_selected(self, target: str) -> None:
        """`Convert to`: a converted copy of each selected material with a route to `target`."""
        from amaze.render.material_conversion import engine as conversion_engine
        pane = self.pane
        if not pane.material_model or target not in conversion_engine.targets():
            return
        indexes = grid_columns.selected_rows(pane.material_selection_model)
        if not indexes:
            return
        model = pane.material_model
        ids = [model.tile_key(pane.material_sorted_model.mapToSource(index).row())
               for index in indexes]    # by ID, with no layout pair: each converted copy inserts and saves
        lines, converted, eligible, sources, unlisted = [], 0, 0, set(), []
        before = {str(mat.mat_id) for mat in model.assets}    # the converted copies are the rows added after this
        for row in (model.find_asset_row_by_id(mat_id) for mat_id in ids):
            if row < 0:
                continue
            mat = model.assets[row]
            if not conversion_engine.has_route(mat.renderer, target):
                continue
            eligible += 1
            sources.add(renderers.normalized(mat.renderer))
            try:
                ok, report = material_actions.convert(model, model.index(row, 0), target,
                                                      render=False)
            except Exception as exc:                          # noqa: BLE001
                lines.append(messages.CONVERSION_CRASHED_LINE % (mat.name, exc))
                continue
            converted += 1 if ok else 0
            if isinstance(ok, library.ListNotSaved):
                unlisted.append(mat.name)    # the copy keeps its source's name
            lines.extend(report.summary_lines())
        self.render_new_thumbnails(before)
        shown = " and ".join(renderers.label(source)
                             for source in conversion_engine.targets() if source in sources)
        ui = getattr(hou, "ui", None)
        if ui is not None and eligible:
            ui.displayMessage(
                messages.CONVERSION_SUMMARY % (converted, eligible, shown, renderers.label(target)),
                details="\n".join(lines), title=messages.TITLE_AMAZE,
                severity=(hou.severityType.Message if converted == eligible
                          else hou.severityType.Warning))
        library.report_unlisted(unlisted)    # the status line, last, so nothing after it overwrites the line

    def render_new_thumbnails(self, before: set) -> None:
        """ONE render batch for the materials saved since `before` that have no thumbnail yet."""
        model = self.pane.material_model
        if not model.preferences.render_on_import:    # the setting each save checked when it rendered alone
            return
        rows = []
        for row, mat in enumerate(model.assets):
            if str(mat.mat_id) in before:
                continue
            path = tile_icons.tile_read_path(model.preferences, str(mat.mat_id), model.DB_FILENAME)
            if path and not os.path.exists(path):    # a hosted image is already the thumbnail
                rows.append(row)
        material_actions.render_thumbnails(model, rows)    # one husk per renderer ▸r/husk-startup

    def open_versions(self, index, proxy, model) -> None:
        """The Versions dialog over `model`'s row at `index`: Select makes the picked one active."""
        row = proxy.mapToSource(index).row()    # `index` is the proxy's
        if not 0 <= row < len(model.assets):    # -1 would index the LAST asset ▸r/model-contracts
            return
        mat = model.assets[row]
        listed, active = model.version_list(row)
        if len(listed) < 2:
            return

        def chosen(picked):
            row = model.find_asset_row_by_id(mat.mat_id)    # the rows may have changed while the dialog was open
            if picked is not None and picked != active and row >= 0:
                model.switch_version(row, picked)

        self.pane.ui.open_versions(mat.name, listed, active, chosen)

    def edit_tile_icon(self, model, proxy, proxy_indexes, categories=()) -> None:
        """Customize on any tile: one handler for every section, applied to the WHOLE selection."""
        if model is None or not proxy_indexes:
            return
        tile_keys = []    # tile keys, never rows: rows can change while the dialog is open
        rows = []
        for proxy_index in proxy_indexes:
            source = proxy.mapToSource(proxy_index) if proxy is not None \
                else proxy_index
            if not source.isValid() or source.row() in rows:
                continue
            key = model.tile_key(source.row())
            if key:
                rows.append(source.row())
                tile_keys.append(key)
        if not tile_keys:
            return
        single = len(rows) == 1    # Name only where the model renames, disabled on a multi-selection
        tile_name = None
        if "name" in model.TILE_FIELDS:
            tile_name = model.tile_name(rows[0]) if single else ""
        tile_tags = None    # no field without tags; a multi-selection opens empty
        if "tags" in model.TILE_FIELDS:
            tile_tags = model.tile_tags(rows[0]) if single else ""
        offered = None    # no field at all where the model cannot hold a category
        tile_category = ""
        if "category" in model.TILE_FIELDS:
            offered = list(categories)    # the OWNING section's list, passed in by its menu
            shared = {model.tile_category(row) for row in rows}
            tile_category = shared.pop() if len(shared) == 1 else ""    # mixed: the field starts empty
        capture = getattr(model, "capture_image", None)    # a File row's capture is its image
        faces = {"image": (capture and capture(rows[0])) or model.preview_image(rows[0]),
                 "generic": tile_icons.generic_image(model.tile_face_art(rows[0]))}
        question = asks.CustomizeQuestion(
            icon=model.tile_icon(rows[0]),
            stroke=tile_icons.stroke_for(self.pane.prefs),
            tile_name=tile_name,
            tile_name_enabled=single,
            tile_tags=tile_tags,
            categories=offered,
            tile_category=tile_category,
            face=tile_icons.face_for(model, rows[0]),
            faces=faces,
            can_preview=any(model.can_preview(row) for row in rows),
        )

        def apply(answer, tile_keys=frozenset(tile_keys)):
            rows = [row for row in range(model.rowCount())    # resolved on commit; a tile deleted meanwhile is skipped
                    if model.tile_key(row) in tile_keys]
            if not rows:
                return
            self.apply_icon_spec(model, rows, answer.spec)
            edited = set()    # keys of the records changed below - nothing saves until the one commit
            if answer.name and len(rows) == 1 and "name" in model.TILE_FIELDS:
                if model.set_tile_name(rows[0], answer.name, save=False):
                    edited.add(model.tile_key(rows[0]))
            if answer.tags is not None and "tags" in model.TILE_FIELDS:
                if len(rows) == 1:
                    if model.set_tile_tags(rows[0], answer.tags, save=False):    # "" CLEARS the tags
                        edited.add(model.tile_key(rows[0]))
                else:
                    for row in rows:    # ADDS across a selection: each tile keeps its own tags
                        if model.add_tile_tags(row, answer.tags, save=False):
                            edited.add(model.tile_key(row))
            if answer.category and "category" in model.TILE_FIELDS:
                for row in rows:    # EVERY selected tile, unlike the name and the tags
                    if model.set_tile_category(row, answer.category, save=False):
                        edited.add(model.tile_key(row))
            if edited:
                model.commit_tile_edits(edited)

        self.pane.ui.open_customize(question, apply)

    def apply_icon_spec(self, model, rows, spec) -> None:
        """One icon-store write for the selection's new icons; a failed write is shown once."""
        failed = model.set_tile_icons(rows, spec)    # one icon-store write for the whole selection
        model.commit_tile_icons(rows)    # once per selection, never per row
        ui = getattr(hou, "ui", None)
        if failed and ui is not None:
            ui.displayMessage(
                messages.TILE_ICON_SAVE_FAILED
                % (failed, "" if failed == 1 else "s"),
                title=messages.TITLE_AMAZE, severity=hou.severityType.Warning    # a real plural
            )

    def exportable_selection(self) -> tuple:
        """(the shown context, its grid selection) when that selection can be exported."""
        section = self.pane.active_section()
        if section is None or not section.exports_selection:
            return section, []
        return section, section.grid_selection()

    def exportable_category(self):
        """The shown context when its sidebar holds categories and at most one row is selected, else None."""
        section = self.pane.active_section()
        if section is None or not section.exports_categories or len(section.sidebar_selection()) > 1:
            return None
        return section

    def export_package(self) -> None:
        """View ▸ Export Asset: the shown grid's selected tiles are exported as one `.amazepkg`."""
        section, indexes = self.exportable_selection()
        if indexes:
            section.export_selection(indexes)

    def export_category(self) -> None:
        """View ▸ Export Category: the sidebar's selected category, or the whole section on All."""
        section = self.exportable_category()
        if section is not None:
            section.export_category(section.selected_category())
