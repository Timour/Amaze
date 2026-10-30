"""Saving, loading, converting and rendering a Material in Houdini. ▸archive/actions/materials.py"""

import os
import shutil

import hou
from PySide6 import QtCore

from amaze import messages
from amaze.core import debug, material, versions
from amaze.render import husk_job, nodes


def connect(model) -> None:
    """Repaint `model`'s tile when a background render lands: once per model, for every panel."""
    if not getattr(model, "_renders_connected", False):
        husk_job.jobs.thumbnailWritten.connect(model._on_thumbnail_written)    # a bound method
        model._renders_connected = True


def add_asset(model, node: hou.Node, cats: str, tags: str, fav: bool,
              name: str | None = None, picture: str = "", render: bool = True) -> str:
    """Save `node` into `model` as a new material: its renderer when it is in, "" when it is not."""
    handler = nodes.NodeHandler(model.preferences)
    handler.supplied_thumbnail = picture    # a hosted picture, which replaces the render
    handler.render_after_save = render    # False: the caller renders its rows in one batch
    renderer = handler.get_renderer_from_node(node)
    new_mat = material.Material()
    tags = model.sanitize_tags(tags)
    new_mat.set_data(name or node.name(), cats, tags, fav, renderer)
    new_mat.node_color = nodes.custom_node_color(node)

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
        if isinstance(inventory, (list, tuple)) and inventory:    # rides _extra like the curated tag - old builds ignore it, get_as_dict carries it
            new_mat._extra["textures"] = list(inventory)
        model._append_record(new_mat)    # per row, so in a multi-save each tile shows as its save lands
        if not model.save():  # the index write can be refused with the files already on disk
            model.report_refused_index_write(new_mat)
        try:  # the node carries its id, so a later save can offer Update Existing
            node.setUserData("assetlib_id", str(new_mat.mat_id))
        except (hou.OperationFailed, hou.ObjectWasDeleted):    # the save succeeded ▸r/node-vanished
            pass
        return renderer
    debug.event("save", "add_asset refused - the node was not saved",
                name=new_mat.name, node=node.path(),
                mat_id=new_mat.mat_id)
    return ""


def update_asset_content(model, row: int, node: hou.Node) -> str:
    """Row `row`'s saved files rewritten from `node`, its record kept: the renderer, "" on failure."""
    from amaze.core import library_policy
    if row < 0 or row >= len(model._assets):
        return ""
    mat = model._assets[row]
    if not library_policy.allow_overwrite(model.preferences.dir):  # the gate every caller goes through
        debug.event("library", "overwrite refused - the library "
                    "does not allow it", mat_id=str(mat.mat_id),
                    name=mat.name)
        return ""
    known = model._content_state.get(str(mat.mat_id))    # content is outside the index merge: last write would win
    current = model._content_stat(mat.mat_id)
    if known is not None and current is not None and current != known:
        debug.event("library", "content update refused - the files "
                    "changed since this session read them",
                    mat_id=str(mat.mat_id), name=mat.name)
        debug.alert(
            messages.ASSET_CHANGED_ON_DISK_SINCE_LOAD % mat.name,
            key="content-changed-on-disk")
        return ""

    old_signature = None  # values-only is a new version, else structural ▸p/structure-signature
    pre_edit = {}
    try:  # a failed answer counts as structural: it only skips a version
        old_signature = nodes.staged_asset(
            model.preferences, mat, nodes.structure_signature)
        if versions.version_count(model.preferences, mat.mat_id) == 0:
            pre_edit = model._hold_pre_edit_files(mat.mat_id)  # a values-only save makes them Version 1
    except Exception as exc:                          # noqa: BLE001
        debug.event("versions", "pre-save staging failed - the save "
                    "will be treated as structural",
                    mat_id=str(mat.mat_id), error=str(exc))

    handler = nodes.NodeHandler(model.preferences)
    renderer = handler.get_renderer_from_node(node)
    try:  # the pre-edit copies go on every exit, the early returns included
        if not handler.save_node(node, mat.mat_id, True):  # overwrites the pair, always re-renders
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
    mat._extra.pop("textures", None)    # replaced whole - the new content's references are the inventory now
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
    model.save()
    try:
        node.setUserData("assetlib_id", str(mat.mat_id))
    except (hou.OperationFailed, hou.ObjectWasDeleted):    # a vanished node costs the stamp ▸r/node-vanished
        pass
    return renderer


def render_thumbnail(model, row: int) -> None:
    render_thumbnails(model, [row])  # a batch of one, down the same path


def render_thumbnails(model, rows) -> None:
    """Re-render every row in the model: Karma's and Octane's in ONE husk each. ▸r/husk-startup"""
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
    """Load `index` into the scene by `target`: (ok, reason, created). ▸p/material-import-door"""
    importer = nodes.NodeHandler(model.preferences)
    return importer.import_asset_to_scene(
        model._assets[index.row()], target, context_node=context_node
    )


def convert(model, index: QtCore.QModelIndex, target: str, render: bool = True):
    """This row as a `target` material, saved beside it under its name: (ok, report)."""
    from amaze.render.material_conversion import engine as conversion_engine
    from amaze.render.material_conversion.report import ConversionReport
    mat = model._assets[index.row()]
    report = ConversionReport(mat.name)
    reason = conversion_engine.why_not(mat.renderer, target)
    if reason:    # before the rebuild: a missing plugin makes it raise
        report.skip(reason)
        return False, report

    handler = nodes.NodeHandler(model.preferences)
    with hou.undos.disabler():    # the WHOLE staged body, the twin's stamp included ▸r/undo-groups
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
            return bool(saved), report    # a refused save leaves nothing: the scratch goes below
        finally:
            scratch.destroy()
