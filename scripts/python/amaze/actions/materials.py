"""Saving, loading, converting and rendering a Material in Houdini. ▸archive/actions/materials.py"""

import os
import shutil

import hou
from PySide6 import QtCore

from amaze import messages
from amaze.core import asset_record, debug, library, material, versions
from amaze.render import husk_job, nodes


def connect(model) -> None:
    """Repaint `model`'s tile when a background render is done: once per model, for every panel."""
    if not getattr(model, "_renders_connected", False):
        husk_job.jobs.thumbnailWritten.connect(model._on_thumbnail_written)    # a bound method
        model._renders_connected = True


def add_asset(model, node: hou.Node, cats: str, tags: str, fav: bool,
              name: str | None = None, picture: str = "", render: bool = True) -> str:
    """Save `node` into `model` as a new material: its renderer (`ListNotSaved` if unlisted), or ""."""
    handler = nodes.NodeHandler(model.preferences)
    handler.supplied_thumbnail = picture    # a hosted picture, which replaces the render
    handler.render_after_save = render    # False: the caller renders its rows in one batch
    renderer = handler.get_renderer_from_node(node)
    new_mat = material.Material()
    tags = model.sanitize_tags(tags)
    new_mat.set_data(name or node.name(), cats, tags, fav, renderer)
    new_mat.node_color = nodes.custom_node_color(node)

    handler.staging = []    # the files are committed together with the row, as one change
    saved = handler.save_node(node, new_mat.mat_id, False)
    debug.event(
        "save", "save_node result",
        ok=bool(saved), name=new_mat.name,
        renderer=handler._renderer,
        node=node.path(), node_type=node.type().name(),
        mat_id=new_mat.mat_id,
    )
    if saved:
        new_mat.cop_net = handler.cop_info
        inventory = handler.texture_inventory
        if isinstance(inventory, (list, tuple)) and inventory:    # kept in _extra like the curated tag - old builds ignore it, get_as_dict writes it
            new_mat._extra["textures"] = list(inventory)
        if not model.add_saved(new_mat, handler.staging):    # per row, so each tile appears as soon as it is saved
            debug.event("save", "material not saved - its database took neither row nor files",
                        name=new_mat.name, mat_id=new_mat.mat_id)
            debug.refuse(messages.ASSET_NOT_SAVED_DATABASE_REFUSED % new_mat.name)
            return ""
        try:  # the node stores its id, so a later save can offer Update Existing
            node.setUserData("assetlib_id", str(new_mat.mat_id))
        except (hou.OperationFailed, hou.ObjectWasDeleted):    # the save succeeded ▸r/node-vanished
            pass
        return renderer
    asset_record.discard(handler.staging)
    debug.event("save", "add_asset refused - the node was not saved",
                name=new_mat.name, node=node.path(),
                mat_id=new_mat.mat_id)
    return ""


def adding_into(model, unlisted: list):
    """`add_asset` into `model`; each save whose list was not saved adds its name to `unlisted`."""
    def save(node, *args, **kwargs):
        answer = add_asset(model, node, *args, **kwargs)
        if isinstance(answer, library.ListNotSaved):
            unlisted.append(kwargs.get("name") or node.name())    # the name `add_asset` saved it under
        return answer
    return save


class UpdateRefused(Exception):
    """Raised when an update wrote nothing; its text goes in the one message after the save."""


def update_asset_content(model, row: int, node: hou.Node) -> str:
    """Rewrite `row`'s files from `node`: its renderer, `ListNotSaved` if unlisted; refusals raise."""
    from amaze.core import library_settings
    if row < 0 or row >= len(model._assets):
        raise UpdateRefused(messages.UPDATE_REFUSED_GONE)
    mat = model._assets[row]
    if not library_settings.allow_overwrite(model.preferences):  # every caller is checked here
        debug.event("library", "overwrite refused - the library "
                    "does not allow it", mat_id=str(mat.mat_id),
                    name=mat.name)
        raise UpdateRefused(messages.UPDATE_REFUSED_VERSIONS_OFF)
    known = model._content_state.get(str(mat.mat_id))    # content files are not merged like the index: the last write would overwrite
    current = model._content_stat(mat.mat_id)
    if known is not None and current is not None and current != known:
        debug.event("library", "content update refused - the files "
                    "changed since this session read them",
                    mat_id=str(mat.mat_id), name=mat.name)
        raise UpdateRefused(messages.UPDATE_REFUSED_CHANGED_ON_DISK)
    handler = nodes.NodeHandler(model.preferences)
    renderer = handler.get_renderer_from_node(node)
    if not nodes.ocio_set():    # the two checks `save_node` makes, run before any file is copied aside
        raise UpdateRefused(messages.OCIO_NOT_SET)
    if not renderer:
        raise UpdateRefused(messages.UPDATE_REFUSED_NOT_A_BUILDER)

    old_signature = None  # values-only is a new version, else structural ▸p/structure-signature
    pre_edit = {}
    try:  # a failed comparison counts as structural: it only skips a version
        old_signature = nodes.staged_asset(
            model.preferences, mat, nodes.structure_signature)
        if versions.version_count(model.preferences, mat.mat_id) == 0:
            pre_edit = model._hold_pre_edit_files(mat.mat_id)  # a values-only save makes them Version 1
    except Exception as exc:                          # noqa: BLE001
        debug.event("versions", "pre-save staging failed - the save "
                    "will be treated as structural",
                    mat_id=str(mat.mat_id), error=str(exc))

    try:  # the pre-edit copies are deleted on every exit, early returns included
        if not handler.save_node(node, mat.mat_id, True):  # its two checks already ran above
            return ""
        model._content_state[str(mat.mat_id)] = model._content_stat(  # our own write is the new baseline for this id
            mat.mat_id)
        parameter_only = False
        if old_signature is not None:
            try:
                new_signature = nodes.staged_asset(
                    model.preferences, mat, nodes.structure_signature)
                parameter_only = (new_signature == old_signature)
            except Exception as exc:                  # noqa: BLE001
                debug.event("versions", "post-save staging failed - "
                            "no version minted",
                            mat_id=str(mat.mat_id), error=str(exc))
        if parameter_only:
            if pre_edit and versions.version_count(
                    model.preferences, mat.mat_id) == 0:
                versions.create_version(model.preferences, mat.mat_id,
                                        source_paths=pre_edit)
            versions.create_version(model.preferences, mat.mat_id)  # the new state as the active version

            model._version_count_cache.pop(str(mat.mat_id), None)
            model._active_version_cache.pop(str(mat.mat_id), None)
    finally:
        if pre_edit:
            shutil.rmtree(os.path.dirname(
                next(iter(pre_edit.values()))), ignore_errors=True)
    mat.cop_net = handler.cop_info
    mat._extra.pop("textures", None)    # replaced entirely - the new content's references are the inventory now
    inventory = handler.texture_inventory
    if isinstance(inventory, (list, tuple)) and inventory:
        mat._extra["textures"] = list(inventory)
    if renderer:
        mat.renderer = renderer
    mat.node_color = nodes.custom_node_color(node)
    mat.set_current_date()
    model._drop_content_label_caches(mat.mat_id)  # the labels read from the saved files are stale now
    if not mat.cop_net:  # the updated network no longer references a COP net, so the old <id>_cop.mat is stale
        cop_path = model.asset_files(mat.mat_id).get("cop", "")
        if cop_path and os.path.exists(cop_path):
            try:
                os.remove(cop_path)
            except OSError as exc:
                debug.event(
                    "library",
                    "stale cop file remove skipped",
                    file=cop_path,
                    error=str(exc),
                )
    model._add_thumb_paths(row)  # the engine discard inside is what makes the repaint fetch the freshly rendered PNG
    listed = model.save()
    if not listed:    # `save` showed why; the record stays in memory until a later save succeeds
        debug.event("library", "update written but the library list was not saved",
                    mat_id=str(mat.mat_id), name=mat.name)
    try:
        node.setUserData("assetlib_id", str(mat.mat_id))
    except (hou.OperationFailed, hou.ObjectWasDeleted):    # a deleted node is left without the id ▸r/node-vanished
        pass
    return renderer if listed else library.ListNotSaved(renderer)


def render_thumbnail(model, row: int) -> None:
    render_thumbnails(model, [row])  # a batch of one, through the same code


def render_thumbnails(model, rows) -> None:
    """Re-render each row in `rows`: each renderer's rows in ONE husk. ▸r/husk-startup"""
    from amaze.render import thumbs
    rows = [row for row in rows if 0 <= row < model.rowCount()]
    if not rows:
        return
    thumbs.ThumbNailRenderer.render_assets(
        model.preferences, [model._assets[row] for row in rows])
    for row in rows:
        model._add_thumb_paths(row)


def import_asset_to_scene(
    model,
    index: QtCore.QModelIndex,
    target: str = "auto",
    context_node=None,
):
    """Load `index` into the scene by `target`: (ok, reason, created). ▸p/material-import-entry"""
    importer = nodes.NodeHandler(model.preferences)
    ok, reason, created = importer.import_asset_to_scene(
        model._assets[index.row()], target, context_node=context_node
    )
    for node in created:
        node.setCurrent(True, True)    # current and selected, as a node from the Tab menu is
    return ok, reason, created


def convert(model, index: QtCore.QModelIndex, target: str, render: bool = True):
    """Convert this row to a `target` material, saved as a new row, same name: (ok, report)."""
    from amaze.render.material_conversion import engine as conversion_engine
    from amaze.render.material_conversion.report import ConversionReport
    mat = model._assets[index.row()]
    report = ConversionReport(mat.name)
    reason = conversion_engine.why_not(mat.renderer, target)
    if reason:    # before the rebuild: a missing plugin makes it raise
        report.skip(reason)
        return False, report

    handler = nodes.NodeHandler(model.preferences)
    with hou.undos.disabler():    # the WHOLE block, the id stamp on the new builder included ▸r/undo-groups
        scratch = hou.node("/obj").createNode("matnet")
        try:
            source = handler.rebuild_saved(mat, scratch)
            made = conversion_engine.convert(
                source, mat.renderer, target, scratch, mat.name, report)
            if made.shader is None:
                return False, report
            saved = add_asset(
                model, made.builder, ",".join(mat.categories), ",".join(mat.tags), False,
                name=mat.name, render=render)
            if isinstance(saved, library.ListNotSaved):    # files saved, list not saved: the caller tells the user
                return saved, report
            return bool(saved), report    # a refused save leaves nothing: the scratch matnet is destroyed below
        finally:
            scratch.destroy()
