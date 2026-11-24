"""Saving into the library: scene nodes through the Save dialog, new versions, snippets, galleries."""

import functools
import os

from PySide6 import QtCore
import hou

from amaze import branding, messages
from amaze.actions import materials as material_actions
from amaze.core import debug, renderers
from amaze.pane import asks
from amaze import sections
from amaze.render import nodes as nodes_mod


class Saving:
    """Everything that adds to or overwrites the library; the pane holds it as `saving`."""

    def __init__(self, pane) -> None:
        self.pane = pane

    def save_from_node(self, node: hou.Node | None = None,
                       prefer: str = "") -> None:
        """THE function a scene node is saved through: right-click and drop. ▸p/save-section-row"""
        ui = getattr(hou, "ui", None)
        selected = hou.selectedNodes()
        node = node or (selected[0] if selected else None)
        if node is None:
            if ui is not None:
                ui.displayMessage(messages.NO_NODE_TO_SAVE,
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            return
        nodes = selected if node in selected else [node]
        keys = self._save_targets(nodes)
        debug.event("save", "save_from_node", node=node.path(), offered=keys,
                    prefer=prefer)
        if not keys:
            if ui is not None:
                ui.displayMessage(messages.NODE_CANNOT_BE_SAVED % node.name(),
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            return
        key = sections.save_guess(keys, nodes, prefer)
        if key == "material":
            self.save_asset(nodes)    # the already-in-the-library prompt comes first
            return
        self._save_new(nodes, key, node)

    def _save_targets(self, nodes: list) -> list:
        """The keys of the sections, in tab order, that can save these nodes."""
        pane = self.pane
        able = [key for key, _ in pane.ALL_SECTIONS
                if key in pane.sections
                and getattr(pane, getattr(pane.sections[key], "model_attr", ""),
                            None) is not None
                and pane.sections[key].can_save(nodes)]
        shown = [key for key in able if key in pane.prefs.enabled_sections]
        return shown or able    # a hidden tab is still a place to save

    def _save_new(self, nodes: list, key: str,
                  node: hou.Node | None = None) -> None:
        """D09 for these nodes, opened on section `key`, then that section's save."""
        from amaze.helpers import helpers
        pane = self.pane
        node = node or nodes[0]
        keys = self._save_targets(nodes) or [key]
        cats, current = pane.sections[key].save_categories()
        one = nodes[0] if len(nodes) == 1 else None
        code_parm = helpers.find_code_parm(one) if one is not None else None
        question = asks.SaveQuestion(
            categories=cats, current=current, name=one.name() if one is not None else "",
            name_enabled=one is not None,
            sections=[(k, pane.sections[k].label) for k in keys],
            section=key,
            categories_for=lambda k: pane.sections[k].save_categories(),
            language=(helpers.code_parm_language(code_parm)
                      if code_parm is not None else ""),
            language_sections=[k for k in keys
                               if pane.sections[k].takes_language])

        def saved(answer):
            chosen = (answer.section if answer is not None else "") or key
            debug.event(
                "save", "save dialog closed",
                accepted=answer is not None, section=chosen,
                category=answer.categories if answer is not None else "", preselected=current,
            )
            if answer is not None:
                pane.sections[chosen].commit_save(nodes, node, answer)

        pane.ui.open_save(question, saved)

    def save_asset(self, nodes=None) -> None:
        """Save `nodes`, else the selection; ones in the library get one save-over or new prompt."""
        from amaze.core import library_settings
        model = self.pane.material_model
        ui = getattr(hou, "ui", None)
        sel = list(nodes) if nodes is not None else hou.selectedNodes()
        debug.event("save", "save_asset entry", selected=len(sel))
        if not sel:
            if ui is not None:
                ui.displayMessage(messages.NO_MATERIAL_SELECTED,
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            return
        if not model:
            if ui is not None:
                ui.displayMessage(
                    messages.NO_LIBRARY_CONFIGURED_2,
                    title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                )
            return
        existing = []    # (asset id, node) per node in the library: ONE choice for all; ids, as saves move rows
        new_nodes = []
        for node in sel:
            row = self._find_existing_asset_row(node)
            if row >= 0:
                existing.append((model.tile_key(row), node))
            else:
                new_nodes.append(node)
        debug.event("save", "overwrite check",
                    existing=len(existing), new=len(new_nodes))
        if existing:
            if len(sel) == 1:
                name = model.data(
                    model.index(model.find_asset_row_by_id(existing[0][0]), 0),
                    QtCore.Qt.ItemDataRole.DisplayRole,
                )
                message = messages.MATERIAL_ALREADY_IN_LIBRARY % name
            else:
                message = messages.MATERIALS_ALREADY_IN_LIBRARY % (len(existing), len(sel))
            if not library_settings.policy_readable(model.preferences):
                message += messages.LIBRARY_UNREADABLE_SAVES_NEW
                buttons = messages.BUTTONS_SAVE_NEW    # no save-over, an option that would always fail
                cancel_at, overwrite_at = 1, -1
            elif library_settings.allow_overwrite(model.preferences):    # the UI calls it Versions
                buttons = messages.BUTTONS_SAVE_VERSION_OR_NEW
                cancel_at, overwrite_at = 2, 0
            else:
                message += messages.VERSIONS_OFF_KEEPS_NONE
                buttons = messages.BUTTONS_OVERWRITE_OR_NEW    # Versions off: saved over, no version kept
                cancel_at, overwrite_at = 2, 0
            choice = ui.displayMessage(
                message,
                buttons=buttons,
                default_choice=0,
                close_choice=cancel_at,
                title=messages.TITLE_SAVE_TO % branding.APP_NAME, severity=hou.severityType.Message,
            ) if ui is not None else cancel_at    # no UI to prompt, so the result is the close_choice - Cancel
            if choice == cancel_at:
                return
            if choice == overwrite_at:
                self._update_existing_assets(existing)
                if new_nodes:
                    self.save_new_materials(new_nodes)
                return
        self.save_new_materials(sel)    # Save as New falls through to here with the FULL selection

    def _find_existing_asset_row(self, node: hou.Node) -> int:
        """The source row of the material this node came from, by its stored id alone; or -1."""
        mat_id = node.userData("assetlib_id")
        return self.pane.material_model.find_asset_row_by_id(mat_id) if mat_id else -1

    def _update_existing_assets(self, existing: list) -> None:
        """Save over each (id, node); failures are shown once, after the batch."""
        ui = getattr(hou, "ui", None)
        if not nodes_mod.ocio_set():    # every material would fail the same way, so it is shown once
            if ui is not None:
                ui.displayMessage(messages.OCIO_NOT_SET,
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            return
        model = self.pane.material_model
        total, done, refused = len(existing), 0, []
        try:
            with hou.InterruptableOperation(    # type: ignore
                messages.UPDATING_MATERIALS, open_interrupt_dialog=True
            ) as op:
                for mat_id, node in existing:
                    op.updateLongProgress(
                        done / total, "%d/%d  %s" % (done + 1, total, node.name()))
                    row = model.find_asset_row_by_id(mat_id)
                    name = model.assets[row].name if row >= 0 else node.name()    # read first: a save can remove the row
                    try:
                        self._update_existing_asset(mat_id, node)
                    except hou.OperationInterrupted:
                        raise
                    except material_actions.UpdateRefused as refusal:
                        refused.append((name, str(refusal)))
                    except Exception as exc:                        # noqa: BLE001 - an error becomes that material's line
                        debug.exception("save version", exc, node=node.path())
                        refused.append((name, str(exc)))
                    done += 1
        except hou.OperationInterrupted:
            debug.status(messages.SAVE_STOPPED % (done, total))
        self.pane.sidebar.refresh()    # a re-detected renderer can shift counts and hiding
        if refused and ui is not None:    # once the progress window is gone
            if len(refused) == 1:
                name, reason = refused[0]
                ui.displayMessage(messages.MATERIAL_NOT_UPDATED % (name, reason),
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            else:
                ui.displayMessage(messages.MATERIALS_NOT_UPDATED, details="\n".join(
                    messages.MATERIAL_NOT_UPDATED_LINE % (name, reason) for name, reason in refused),
                    title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)

    def _update_existing_asset(self, mat_id: str, node: hou.Node) -> None:
        """Overwrite asset `mat_id`'s files from the scene node."""
        model = self.pane.material_model
        renderer = material_actions.update_asset_content(    # NO layout pair: it saves, which merges rows from disk
            model, model.find_asset_row_by_id(mat_id), node)
        if not renderer:    # the save failed and showed its own message
            return
        model.row_changed(model.find_asset_row_by_id(mat_id))    # renderer and date changed IN PLACE
        self.enable_renderer_on_add(renderer)
        self.pane.prefs.save()
        self.pane.refresh_filter()

    def save_new_materials(self, sel: list[hou.Node]) -> None:
        """The new-material save: D09 opened on Material, any section still choosable."""
        pane = self.pane
        if not pane.material_model or not pane.category_model or not sel:
            return
        self._save_new(sel, "material")

    def enable_renderer_on_add(self, renderer: str) -> None:
        """Switch a renderer on when its first material is saved, so the save shows in its own tab."""
        found = renderers.get(renderer)
        if found is not None:
            setattr(self.pane.prefs, found.switch, True)
        self.pane.prefs.save()

    def code_category_names(self) -> list[str]:
        """The Code section's stored category names, as its dialogs list them."""
        return self.pane.sidebar.category_names_from(self.pane.code_category_model)

    def _current_code_category(self) -> str:
        """The sidebar's category while Code shows, "" for All; the code dialog's default."""
        if self.pane.current_section != "code":
            return ""
        return self.pane.sidebar.selected_category_name()

    def new_code_snippet(self) -> None:
        """New File: the code editor, empty; its first Apply adds the snippet."""
        pane = self.pane
        if not pane.code_model:
            ui = getattr(hou, "ui", None)
            if ui is not None:
                ui.displayMessage(
                    messages.NO_LIBRARY_CONFIGURED_2,
                    title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                )
            return
        question = asks.CodeQuestion(
            categories=self.code_category_names(), name="", language="VEX",
            category=self._current_code_category(), code="", versions_on=False)    # no versions
        pane.sections["code"].run_code_editor(question, "")    # the first Apply adds the snippet

    def import_galleries(self) -> None:
        """Every material preset in a .gal file saved as a material; ONE render batch after it."""
        from amaze.core import gallery_import
        pane = self.pane
        ui = getattr(hou, "ui", None)
        if not pane.material_model:
            if ui is not None:
                ui.displayMessage(messages.NO_LIBRARY_CONFIGURED,
                                  title=messages.TITLE_AMAZE, severity=hou.severityType.Warning)
            return
        picked = ui.selectFile(
            start_directory=gallery_import.default_gallery_dir(),    # opens where Houdini keeps its galleries
            title="Import Gallery (.gal)",
            file_type=hou.fileType.Any,
            pattern="*.gal",
            chooser_mode=hou.fileChooserMode.Read,
        ) if ui is not None else ""
        picked = (picked or "").strip()
        if not picked:
            return
        picked = hou.text.expandString(picked)
        with gallery_import.opened(picked) as entries:
            self._import_gallery(picked, entries)

    def _import_gallery(self, picked: str, entries) -> None:
        """The materials of one opened gallery, asked first, saved, then rendered in one batch."""
        from amaze.core import gallery_import
        pane = self.pane
        ui = getattr(hou, "ui", None)
        if not entries:
            if ui is not None:
                ui.displayMessage(
                    messages.MATERIAL_PRESETS_FOUND % picked,
                    title=messages.TITLE_AMAZE, severity=hou.severityType.Warning
                )
            return
        types = {}
        for _entry, type_name, _cat in entries:
            types[type_name] = types.get(type_name, 0) + 1
        listing = "\n".join(
            "  %d x %s" % (count, name)
            for name, count in sorted(types.items(), key=lambda x: -x[1])
        )
        renders = pane.material_model.preferences.render_on_import    # what import_entries checks
        if renders:
            question = messages.IMPORT_MATERIAL_PRESETS_FROM_RENDERING % (
                len(entries), os.path.basename(picked), listing)
        else:
            question = messages.IMPORT_MATERIAL_PRESETS_FROM % (
                len(entries), os.path.basename(picked), listing)
        choice = ui.displayMessage(
            question, buttons=messages.BUTTONS_IMPORT,
            default_choice=0, close_choice=1,
            title=messages.TITLE_AMAZE, severity=hou.severityType.Message,
        ) if ui is not None else 1    # no UI to prompt, so the result is the close_choice - Cancel
        if choice != 0:
            return
        summary, interrupted = {}, False    # import_entries fills OUR dict: Esc keeps the counts so far
        try:
            with hou.InterruptableOperation(  # type: ignore
                "Importing gallery presets", open_interrupt_dialog=True
            ) as op:
                def progress(index, total, name):
                    op.updateLongProgress(
                        float(index) / max(total, 1),
                        "%d/%d  %s" % (index + 1, total, name),
                    )
                gallery_import.import_entries(
                    functools.partial(material_actions.add_asset, pane.material_model),
                    entries, progress=progress, summary=summary,
                    library=pane.material_model)    # each save skips its render; ONE batch follows
        except hou.OperationInterrupted:
            interrupted = True
            debug.event("gallery", "import interrupted", **summary)
        for name in sorted(summary.get("categories", {})):
            pane.category_model.check_add_category(name)
        pane.sidebar.refresh()
        imported, skipped, failed = (summary.get(key, 0) for key in ("imported", "skipped", "failed"))
        if interrupted:
            text = (messages.GALLERY_IMPORT_INTERRUPTED_RENDERING % (imported, skipped, failed) if renders
                    else messages.GALLERY_IMPORT_INTERRUPTED % (imported, skipped, failed))
        elif renders:
            text = messages.GALLERY_IMPORT_FINISHED_RENDERING % (imported, skipped, failed)
        else:
            text = messages.GALLERY_IMPORT_FINISHED_IMPORTED_SKIPPED % (imported, skipped, failed)
        if ui is not None:
            ui.displayMessage(text, title=messages.TITLE_AMAZE,
                              severity=hou.severityType.Warning if failed else hou.severityType.Message)
