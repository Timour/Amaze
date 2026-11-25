"""A node dragged from a network editor onto either pane: its paths read off the drag, then saved."""

import hou

from amaze.core import debug
from amaze.helpers import helpers


def node_paths(mime) -> list:
    """Node paths in a drag: node-path mime, then item-path list, then text. ▸r/drop-mime"""
    raw = ""
    for attr in ("nodePath", "itemPath"):
        try:
            fmt = getattr(hou.qt.mimeType, attr)
        except AttributeError:
            continue
        if mime.hasFormat(fmt):
            raw = bytes(mime.data(fmt)).decode("utf-8", "replace")
            if raw.strip():
                break
    if not raw.strip():
        raw = mime.text() or ""
    paths = []
    for piece in raw.replace("\r", "\t").replace("\n", "\t").split("\t"):
        piece = piece.strip()
        if piece and hou.node(piece) is not None:
            paths.append(piece)
    return paths


def save(pane, mime) -> bool:
    """Save the dropped nodes as Save to Amaze does, after the drop has returned; False for none."""
    paths = node_paths(mime)
    debug.event("save", "drop received", formats=[str(f) for f in mime.formats()][:8],
                text=(mime.text() or "")[:120], parsed=paths)
    if not paths:
        return False
    nodes = [hou.node(path) for path in paths]
    with hou.undos.disabler():    # a selection is an undo entry of its own
        for number, node in enumerate(nodes):    # the dropped nodes become the selection the save reads
            node.setSelected(True, clear_all_selected=(number == 0))
    section = getattr(pane.active_section(), "key", "")    # out of the drop: no modal mid-gesture ▸r/qt-windows-macos

    @debug.guarded("node_drop.save")
    def route() -> None:
        debug.event("save", "drop save routed", node=nodes[0].path(), section=section)
        pane.saving.save_from_node(nodes[0], prefer=section)

    helpers.run_at_top_of_loop(route, "drop save")    # a bare timer can fire during a builder's processEvents
    return True
