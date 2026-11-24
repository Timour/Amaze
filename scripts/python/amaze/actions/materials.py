"""Saving, loading, converting and rendering a Material in Houdini. ▸archive/actions/materials.py"""

import contextlib
import os

import hou
from PySide6 import QtCore

from amaze import messages
from amaze.core import debug, guard, library, library_db, material, renderers, texstore, versions
from amaze.render import husk_job, nodes
from amaze.render.material_conversion import engine as conversion_engine
from amaze.render.material_conversion import report as conversion_report


def connect(model) -> None:
    """Repaint `model`'s tile when a background render is done: once per model, for every panel."""
    if not getattr(model, "_renders_connected", False):
        husk_job.jobs.thumbnailWritten.connect(model._on_thumbnail_written)    # a bound method
        model._renders_connected = True


def add_asset(model, node: hou.Node, cats: str, tags: str, fav: bool,
              name: str | None = None, picture: str = "", render: bool = True,
              about: str | None = None, license: str | None = None, sources=()) -> str:
    """Save `node` and `sources` as a new material, row and files in one change: its renderer, or ""."""
    handler = nodes.NodeHandler(model.preferences)
    handler.supplied_thumbnail = picture    # a hosted picture, which replaces the render
    handler.render_after_save = render    # False: the caller renders its rows in one batch
    renderer = handler.get_renderer_from_node(node)
    new_mat = material.Material()
    new_mat.set_data(name or node.name(), cats, tags, fav, renderer, about=about, license=license)
    new_mat.node_color = nodes.custom_node_color(node)

    def save(staging, own):
        handler.staging = staging    # the files are committed together with the row, as one change
        if not handler.save_node(node, new_mat.mat_id, False):
            return False
        for path in sources:    # a download's own files, at the folder's top level
            texstore.copy_file_into_library(path, model.preferences, own, staging, "")
        new_mat.cop_net = handler.cop_info
        keep_textures(new_mat, handler.texture_inventory)
        return True
    saved = model.save_new(new_mat, save)    # per row, so each tile appears as soon as it is saved
    debug.event("save", "save_node result", ok=saved, name=new_mat.name, renderer=handler._renderer,
                node=node.path(), node_type=node.type().name(), mat_id=new_mat.mat_id)
    if not saved:
        return ""
    nodes.stamp_asset_id(node, new_mat.mat_id)    # a later save can offer Update Existing
    return renderer


def keep_textures(mat, inventory) -> None:
    """The textures a save copied in, on the row in `_extra`, which old builds ignore."""
    mat._extra.pop("textures", None)
    if isinstance(inventory, (list, tuple)) and inventory:
        mat._extra["textures"] = list(inventory)


class UpdateRefused(Exception):
    """Raised when an update wrote nothing; its text goes in the one message after the save."""


def update_asset_content(model, row: int, node: hou.Node) -> str:
    """Rewrite `row`'s files from `node`: its renderer, `ListNotSaved` if unlisted; refusals raise."""
    from amaze.core import library_settings
    if row < 0 or row >= len(model._assets):
        raise UpdateRefused(messages.UPDATE_REFUSED_GONE)
    mat = model._assets[row]
    if not library_settings.policy_readable(model.preferences):  # every caller is checked here
        debug.event("library", "overwrite refused - the library's "
                    "policy cannot be read", mat_id=str(mat.mat_id),
                    name=mat.name)
        raise UpdateRefused(messages.UPDATE_REFUSED_LIBRARY_UNREADABLE)
    known = model._content_state.get(str(mat.mat_id))    # content files are not merged like the index: the last write would overwrite
    current = model._content_stat(mat.mat_id)
    if known is not None and current is not None and current != known:
        debug.event("library", "content update refused - the files "
                    "changed since this session read them",
                    mat_id=str(mat.mat_id), name=mat.name)
        raise UpdateRefused(messages.UPDATE_REFUSED_CHANGED_ON_DISK)
    handler = nodes.NodeHandler(model.preferences)
    renderer = handler.get_renderer_from_node(node)
    if not nodes.ocio_set():    # the two checks `save_node` makes, run before a version is kept
        raise UpdateRefused(messages.OCIO_NOT_SET)
    if not renderer:
        raise UpdateRefused(messages.UPDATE_REFUSED_NOT_A_BUILDER)

    keeps_versions = library_settings.allow_overwrite(model.preferences)  # Preferences > Versions
    if keeps_versions:
        kept = versions.keep_base(model.preferences, mat.mat_id)  # the material as it was, unless a version holds it
        model._versions_changed(mat)
        if not kept:
            debug.event("versions", "overwrite refused - the material as it was "
                        "could not be kept as a version", mat_id=str(mat.mat_id), name=mat.name)
            raise UpdateRefused(messages.UPDATE_REFUSED_NOT_KEPT)
    if not handler.save_node(node, mat.mat_id, True):  # its two checks already ran above
        return ""
    model._content_state[str(mat.mat_id)] = model._content_stat(  # our own write is the new baseline for this id
        mat.mat_id)
    if keeps_versions:
        versions.create_version(model.preferences, mat.mat_id)  # the new state as the active version
        model._versions_changed(mat)
    mat.cop_net = handler.cop_info
    keep_textures(mat, handler.texture_inventory)    # the new content's references replace the old
    if renderer:
        mat.renderer = renderer
    mat.node_color = nodes.custom_node_color(node)
    mat.set_current_date()
    model._drop_content_label_caches(mat.mat_id)  # the labels read from the saved files are stale now
    if not mat.cop_net:  # the updated network no longer references a COP net, so the old <id>_cop.mat is stale
        cop_path = model.asset_files(mat.mat_id).get("cop", "")
        if cop_path and os.path.exists(cop_path):
            try:
                held = library_db.guard_of(model.preferences)
                change = held.change(library_db.user(model.preferences))
                change.trash(held.inside(cop_path))
                change.commit()
            except (OSError, guard.Refused) as exc:
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
    nodes.stamp_asset_id(node, mat.mat_id)
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


@contextlib.contextmanager
def rebuilt_as(preferences, mat, target: str, report):
    """`mat` rebuilt from its files and converted to `target`; all of it is removed afterwards."""
    with hou.undos.disabler():    # the WHOLE block, the id stamp on the new builder included ▸r/undo-groups
        scratch = hou.node("/obj").createNode("matnet")
        try:
            source = nodes.NodeHandler(preferences).rebuild_saved(mat, scratch)
            yield conversion_engine.convert(source, mat.renderer, target, scratch, mat.name, report)
        finally:
            scratch.destroy()


def convert(model, index: QtCore.QModelIndex, target: str, render: bool = True):
    """Convert this row to a `target` material, saved as a new row, same name: (ok, report)."""
    mat = model._assets[index.row()]
    report = conversion_report.ConversionReport(mat.name)
    reason = conversion_engine.why_not(mat.renderer, target)
    if reason:    # before the rebuild: a missing plugin makes it raise
        report.skip(reason)
        return False, report
    with rebuilt_as(model.preferences, mat, target, report) as made:
        if made.shader is None:
            return False, report
        saved = add_asset(
            model, made.builder, ",".join(mat.categories), ",".join(mat.tags), False,
            name=mat.name, render=render, about=mat.about, license=mat.license)
        return bool(saved), report    # a refused save leaves nothing


def convert_rows(model, ids, target: str):
    """Convert to for the rows `ids` that have a route: (message, details, all converted)."""
    lines, converted, eligible, sources = [], 0, 0, set()
    for row in (model.find_asset_row_by_id(mat_id) for mat_id in ids):
        if row < 0:
            continue
        mat = model.assets[row]
        if not conversion_engine.has_route(mat.renderer, target):
            continue
        eligible += 1
        sources.add(renderers.normalized(mat.renderer))
        try:
            ok, report = convert(model, model.index(row, 0), target, render=False)
        except Exception as exc:                              # noqa: BLE001 - one crash costs its row
            lines.append(messages.CONVERSION_CRASHED_LINE % (mat.name, exc))
            continue
        converted += 1 if ok else 0
        lines.extend(report.summary_lines())
    if not eligible:
        return None
    message = conversion_report.summary(converted, eligible, sources, renderers.label(target))
    return message, "\n".join(lines), converted == eligible
