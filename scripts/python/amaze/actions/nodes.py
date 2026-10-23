"""Saving, loading and rendering a Node asset in Houdini. ▸archive/actions/nodes.py"""

import hou

from amaze.core import debug, material
from amaze.render import cop_nodes, nodes


def add_asset(model, node: hou.Node, cats: str, tags: str, fav: bool,
              items: list | None = None, name: str = "") -> str:
    """Save `node`, or `items` inside it, into `model`: the context label recorded, "" on failure."""
    handler = nodes.NodeHandler(model.preferences)
    new_mat = material.Material()
    tags = model.sanitize_tags(tags)
    context = cop_nodes.context_of(node, items)
    label = (context or "NODE").upper()
    new_mat.set_data(name.strip() or node.name(), cats, tags, fav, label)
    new_mat.node_color = nodes.custom_node_color(node)

    if not handler.save_node_cop(node, new_mat.mat_id, items=items):
        return ""
    new_mat.cop_net = handler.cop_info    # carries `thumb_node`, read off the live display flag
    model._append_record(new_mat)
    if not model.save():
        model.report_refused_index_write(new_mat)
    try:
        node.setUserData("assetlib_id", str(new_mat.mat_id))
    except hou.OperationFailed:
        pass
    return label


def import_asset_to_scene(model, index, context_node=None):
    """Rebuild the saved network in the scene, in `context_node` when given: (ok, reason, created)."""
    handler = nodes.NodeHandler(model.preferences)
    return handler.import_cop_asset(
        model.assets[index.row()], context_node=context_node
    )


def render_thumbnail(model, row: int) -> None:
    """Re-render one asset's tile from its saved files; a context with no picture says so instead."""
    try:
        asset = model.assets[row]
        info = asset.cop_net or {}
        from amaze.render import thumbs
        thumber = thumbs.ThumbNailRenderer(model.preferences)
        context = str(asset.renderer or "").upper()
        outcome = thumber.render_network_thumbnail(    # None for a context with no picture
            context, str(asset.mat_id),
            str(info.get("thumb_node", "")))
        if outcome is None:
            debug.note(
                "%s networks have no picture to render, so "
                "this tile keeps its node icon. Only "
                "Copernicus and SOP networks can be "
                "rerendered." % context)
    except Exception as exc:
        debug.note(
            "the thumbnail could not be rerendered (%s). The tile "
            "keeps the picture it had, and the saved network is "
            "unchanged." % exc)
    finally:
        model._add_thumb_paths(row)


def render_thumbnails(model, rows) -> None:
    """Update Render on Node tiles: each row re-rendered in turn, as the model's base loop did."""
    for row in rows:
        if 0 <= row < model.rowCount():
            render_thumbnail(model, row)
