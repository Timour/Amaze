"""The drag and drop engine: Amaze's gesture until Houdini's own drop takes it ▸r/native-drag-paint"""

import functools
import importlib.util
from contextlib import contextmanager
import os
import time

import hou

PICK_INTERVAL = 0.03

_logged_once: set = set()    # the `_dbg_once` keys this gesture has recorded


def _dbg(msg, **data):
    try:
        from amaze.core import debug
        debug.event("drag", msg, **data)
    except Exception:
        pass


def _dbg_once(key: str, msg: str, **data) -> None:
    """Record `msg` once per gesture: the callers run on every move."""
    if key not in _logged_once:
        _logged_once.add(key)
        _dbg(msg, **data)


def begin(section_key: str, ids=()) -> None:
    """Start a gesture: fresh one-time diagnostics, no outline state left from the last."""
    _logged_once.clear()
    _reset_move()
    _move["snap_pos"] = None
    _move["release_snap_pos"] = None    # the previous release has already read it


def end() -> None:
    """End a gesture, however it ended: take the outline off, keep the snap point for the drop."""
    release_snap_pos = _move.get("snap_pos")    # the release reads it after this clears the outline
    ghost_clear()
    _reset_move()
    _move["release_snap_pos"] = release_snap_pos


_move = {
    "tick_at": 0.0,
    "editor": None,
    "blocked": False,
    "target": (None, "", -1),
    "type_name": "",
    "pane_at": 0.0,
    "pane": None,
    "pane_kind": None,
    "pane_rect": None,
    "snap_pos": None,    # the drawn outline's snapped centre, while one is drawn
    "release_snap_pos": None,    # the snap point at end(), returned until the next begin()
    "snap_view": None,    # (editor, network, visible bounds) that `snap_rects` were fetched for
    "snap_rects": [],
}


def _reset_move() -> None:
    _move["tick_at"] = 0.0
    _move["editor"] = None
    _move["blocked"] = False
    _move["target"] = (None, "", -1)
    _move["type_name"] = ""
    _move["pane_at"] = 0.0
    _move["pane"] = None
    _move["pane_kind"] = None
    _move["pane_rect"] = None
    _forget_snap_rects()


def _forget_snap_rects() -> None:
    _move["snap_view"] = None
    _move["snap_rects"] = []


PANE_REVALIDATE = 0.25


def pane_under_cursor_tracked(now=None):
    """(pane, kind, fresh) for the pane lookup on each move, cached by pane rect. ▸p/drag-move-cost"""
    from PySide6 import QtGui

    now = time.time() if now is None else now
    age = now - _move["pane_at"]
    rect = _move["pane_rect"]
    if rect is not None:
        if age < PANE_REVALIDATE and rect.contains(QtGui.QCursor.pos()):
            return _move["pane"], _move["pane_kind"], False
    elif _move["pane_at"] and age < PICK_INTERVAL:    # a MISS is cached for one pick interval only, so entering the editor is never missed for 250ms
        return None, None, False
    _move["pane_at"] = now
    tab = pane_tab_under_cursor()
    kind, rect = None, None
    if tab is not None:
        try:
            kind = tab.type()
            rect = tab.qtScreenGeometry()
        except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
            tab, kind, rect = None, None, None
    _move["pane"] = tab
    _move["pane_kind"] = kind
    _move["pane_rect"] = rect
    return tab, kind, True


def ghost_tick(editor, now=None) -> bool:
    """True when the ghost's cached target results are stale, once per PICK_INTERVAL. ▸p/drag-move-cost"""
    now = time.time() if now is None else now
    try:
        same = _move["editor"] is not None and editor == _move["editor"]
    except hou.ObjectWasDeleted:
        same = False
    if same and now - _move["tick_at"] < PICK_INTERVAL:
        return False
    _move["tick_at"] = now
    _move["editor"] = editor
    return True


def set_ghost_tick_results(blocked, target, type_name) -> None:
    """The tick's results, kept for the moves between ticks."""
    _move["blocked"] = bool(blocked)
    _move["target"] = target
    _move["type_name"] = type_name or ""


def ghost_tick_results():
    """(blocked, wire_target, type_name) as of the last tick."""
    return _move["blocked"], _move["target"], _move["type_name"]


_editors_with_overlay: list = []

def _new_node_half() -> tuple:
    """The host's placement-ghost half size, asked each time."""
    from amaze.helpers import helpers
    half = helpers.new_node_half()
    return (half.x(), half.y())


def _is_vop_network(editor) -> bool:
    from amaze.render import cop_nodes
    try:
        pwd = editor.pwd()
    except (AttributeError, hou.OperationFailed):
        return False
    return cop_nodes.accepts_context(pwd, "Vop")


def _snap_delta(editor, rect):
    """The host's placement snap delta for `rect`, or None - always None headless. ▸r/overlay-shapes"""
    try:
        import nodegraphsnap
        radius = nodegraphsnap.utils.getSnapRadius(editor)
        near = _snap_candidates(_visible_snap_rects(editor), rect, radius)
        result = nodegraphsnap.snap(editor, None, rect, near)
        if result.isValid():
            return result.delta()
    except Exception as exc:                              # noqa: BLE001
        _dbg_once("snap_failure_logged", "placement snap unavailable", error=repr(exc))
    return None


def _visible_snap_rects(editor) -> list:
    """The editor's visible rects as `_snap_entries`, fetched again for a new editor, network or view."""
    view = (editor, editor.pwd(), editor.visibleBounds())
    try:
        same = view == _move["snap_view"]
    except hou.ObjectWasDeleted:
        same = False
    if not same:
        _move["snap_rects"] = _snap_entries(editor.allVisibleRects([]))
        _move["snap_view"] = view
    return _move["snap_rects"]


def _snap_entries(pairs) -> list:
    """(left, right, bottom, top, pair) for each (item, rect) pair, in the editor's order."""
    entries = []
    for pair in pairs:
        low, high = pair[1].min(), pair[1].max()
        entries.append((low.x(), high.x(), low.y(), high.y(), pair))
    return entries


def _snap_candidates(entries, rect, radius) -> list:
    """The pairs whose x or y extent comes within `radius` of `rect`'s, in order: no other can snap."""
    low, high = rect.min(), rect.max()
    x0, y0, x1, y1 = low.x(), low.y(), high.x(), high.y()
    return [pair for left, right, bottom, top, pair in entries    # never `left < x1 + radius`: rounds
            if (left - x1 < radius and x0 - right < radius)
            or (bottom - y1 < radius and y0 - top < radius)]


def ghost_snap_position():
    """The drawn ghost's snapped centre, else the snap point `end()` kept, else None."""
    if _move.get("snap_pos") is not None:
        return _move["snap_pos"]
    return _move.get("release_snap_pos")


def _ghost_half_for(editor) -> tuple:
    """The placement ghost's half-extent: a 0.5 square, or the flat half in VOP. ▸r/overlay-shapes"""
    flat = _new_node_half()
    if _is_vop_network(editor):
        return flat
    half = max(flat)
    return (half, half)

GHOST_COLOUR = (0.988, 0.725, 0.0)
GHOST_ALPHA = 0.75

GHOST_FALLBACK_SHAPE = "rect"


_shape_cache: dict = {}


def _shape_for(type_name: str) -> str:
    """The node shape a created carrier node has, or `""` for a box; cached per type. ▸r/overlay-shapes"""
    if not type_name:
        return ""
    if type_name in _shape_cache:
        return _shape_cache[type_name]
    found = ""
    for category in (hou.sopNodeTypeCategory(), hou.vopNodeTypeCategory(),
                     hou.lopNodeTypeCategory(), hou.cop2NodeTypeCategory()):
        try:
            node_type = hou.nodeType(category, type_name)
        except (AttributeError, hou.OperationFailed):
            node_type = None
        if node_type is not None:
            try:
                found = node_type.defaultShape() or ""
            except (AttributeError, hou.OperationFailed):
                found = ""
            break
    _shape_cache[type_name] = found
    return found


def ghost_show(editor, position, type_name: str = "",
               connection=None) -> None:
    """Draw the outline at `position` in `editor`, with any splice, and repaint. ▸r/native-drag-paint"""
    if editor is None or position is None:
        return
    try:
        half = _ghost_half_for(editor)
        rect = hou.BoundingRect(
            position.x() - half[0], position.y() - half[1],
            position.x() + half[0], position.y() + half[1])
        _move["snap_pos"] = None
        delta = _snap_delta(editor, rect)
        if delta is not None:    # aligned to neighbours like the host's ghost; the release uses the same point
            rect.translate(delta)
            _move["snap_pos"] = hou.Vector2(position.x() + delta.x(),
                                            position.y() + delta.y())
        colour = hou.Color(GHOST_COLOUR)
        drawn = hou.NetworkShapeNodeShape(
            rect, _shape_for(type_name) or GHOST_FALLBACK_SHAPE,
            colour, GHOST_ALPHA, True, False)
        editor.setOverlayShapes(
            splice_preview(editor, connection, position, (drawn,)))
        editor.redraw()
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
        return
    if editor not in _editors_with_overlay:
        _editors_with_overlay.append(editor)


def ghost_clear() -> None:
    """Clear every overlay and drop highlight this module set - on EVERY exit path."""
    _move["snap_pos"] = None
    _forget_snap_rects()
    while _editors_with_overlay:
        editor = _editors_with_overlay.pop()
        try:
            editor.setOverlayShapes([])
            editor.setDropTargetItem(None, "", -1)
        except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
            pass


DROP_TARGET_RADIUS = 0.25


def _drop_items_at(editor, position):
    """Every network item within the drop radius of `position`, or None when the editor call fails."""
    try:
        spot = editor.posToScreen(position)
        radius = editor.lengthToScreen(DROP_TARGET_RADIUS)
        return editor.networkItemsInBox(
            hou.Vector2(spot.x() - radius, spot.y() - radius),
            hou.Vector2(spot.x() + radius, spot.y() + radius),
            for_drop=True)
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
        return None


def wire_under_cursor(editor, position, exclude=()):
    """The connection a release at `position` would drop onto, or `(None, "", -1)`. ▸r/drop-targets"""
    if editor is None or position is None:
        return (None, "", -1)
    if not _drop_on_wire_allowed(editor):
        return (None, "", -1)
    found = _drop_items_at(editor, position)
    if found is None:
        return (None, "", -1)
    for item, name, index in found:
        if isinstance(item, hou.NodeConnection):
            try:
                if (item.inputItem() in exclude
                        or item.outputItem() in exclude):
                    continue
            except (AttributeError, hou.ObjectWasDeleted):
                pass
            return (item, name, index)
    return (None, "", -1)


def connector_under_cursor(editor, position, exclude=()):
    """The connector a release at `position` would drop onto, or `(None, "", -1)`. ▸r/drop-targets"""
    if editor is None or position is None:
        return (None, "", -1)
    found = _drop_items_at(editor, position)
    if found is None:
        return (None, "", -1)
    candidates = [(item, name, index) for item, name, index in found
                  if isinstance(item, hou.Node) and item not in exclude]

    for item, _name, _index in candidates:
        try:
            if editor.itemRect(item, False).contains(position):
                return (None, "", -1)
        except (AttributeError, hou.OperationFailed,
                hou.ObjectWasDeleted):
            continue

    for item, name, index in candidates:
        if name in ("input", "output"):
            return (item, name, index)
    return (None, "", -1)


_held = {"armed": False, "group": None}    # the release's one undo group, while its splice is pending


@contextmanager
def holding_drop_group():
    """One undo entry per release: the first `drop_group` a handler opens stays open until this exits."""
    _held.update(armed=True, group=None)
    error = (None, None, None)
    try:
        yield
    except BaseException as exc:
        error = (type(exc), exc, exc.__traceback__)
        raise
    finally:
        group = _held["group"]
        _held.update(armed=False, group=None)
        if group is not None:
            group.__exit__(*error)


@contextmanager
def drop_group(label: str):
    """A handler's undo group, held open under `holding_drop_group` for the splice. ▸r/undo-groups"""
    if _held["armed"] and _held["group"] is None:
        group = hou.undos.group(label)
        group.__enter__()
        _held["group"] = group
        yield
        return
    with hou.undos.group(label):    # nested in a held group it merges into it
        yield


def connect_to_neighbour(target, nodes, editor=None) -> bool:
    """Wire the dropped nodes to the target connector; an occupied input is replaced. ▸r/drop-targets"""
    node, name, index = target
    nodes = [n for n in nodes if n is not None]
    if node is None or not nodes:
        return False
    first, last = nodes[0], nodes[-1]
    try:
        with hou.undos.group("Amaze Connect"):
            if name == "output":
                if first.inputConnectors():
                    first.setInput(0, node, index)
                else:
                    return False
            else:
                if last.outputConnectors():
                    node.setInput(index, last)
                else:
                    return False
    except (AttributeError, hou.InvalidInput,    # a connector the node lost since the hover is caught here
            hou.OperationFailed, hou.PermissionError,
            hou.ObjectWasDeleted):
        return False
    _fit_after_wiring(nodes, editor)
    _dbg("connected to a neighbour", to=node.path(), side=name,
         index=index, nodes=[n.path() for n in nodes])
    return True


def _fit_after_wiring(nodes, editor=None) -> None:
    """Move newly wired nodes apart as the host's drop does; pass the drop's editor. ▸r/drop-targets"""
    if not nodes:
        return
    try:
        import nodegraphutils
        if editor is None:
            editor = pane_tab_under_cursor()
        if editor is None:
            return
        nodegraphutils.moveNodesToAvoidOverlap(editor, nodes,
                                               update_graph=True)
    except (ImportError, AttributeError, hou.OperationFailed,
            hou.ObjectWasDeleted):
        return


def _drop_on_wire_allowed(editor) -> bool:
    """The artist's Drop On Wire preference; True when it cannot be read. ▸r/drop-targets"""
    try:
        import nodegraphprefs
        return bool(nodegraphprefs.allowDropOnWireNetworkSpecific(
            editor, []))
    except (ImportError, AttributeError, hou.OperationFailed):
        return True


def wire_highlight(editor, target) -> None:
    """Highlight the wire a release would splice into, remembering the editor. ▸r/overlay-shapes"""
    item, name, index = target
    try:
        editor.setDropTargetItem(item, name, index)
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
        return
    if editor not in _editors_with_overlay:
        _editors_with_overlay.append(editor)


def splice_preview(editor, connection, position, shapes=()) -> tuple:
    """The two wires the splice would make, appended to `shapes`. ▸r/overlay-shapes"""
    if editor is None or connection is None or position is None:
        return tuple(shapes)
    try:
        colour = hou.Color(GHOST_COLOUR)
        upstream = connection.inputItem()
        downstream = connection.outputItem()
        out_pos = editor.itemOutputPos(
            upstream, connection.inputItemOutputIndex())
        out_dir = editor.itemOutputDir(
            upstream, connection.inputItemOutputIndex())
        in_pos = editor.itemInputPos(downstream, connection.inputIndex())
        in_dir = editor.itemInputDir(downstream, connection.inputIndex())
        half = hou.Vector2(0.0, _new_node_half()[1])    # already a HALF size, the host's own
        top = position + half
        bottom = position - half
        return tuple(shapes) + (
            hou.NetworkShapeConnection(top, hou.Vector2(0, 1),
                                       out_pos, out_dir, colour, 0.8),
            hou.NetworkShapeConnection(in_pos, in_dir,
                                       bottom, hou.Vector2(0, -1),
                                       colour, 0.8),
        )
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
        return tuple(shapes)


def splice_into_wire(connection, nodes, editor=None) -> bool:
    """Insert the list `nodes` into `connection` via the host's `insertItemsIntoWire`. ▸r/drop-targets"""
    nodes = [n for n in nodes if n is not None]
    if connection is None or not nodes:
        return False
    try:
        import nodegraphutils
    except ImportError:
        return False
    try:
        with hou.undos.group("Amaze Insert Into Wire"):
            nodegraphutils.insertItemsIntoWire(
                connection, nodes, nodes,
                remove_existing_connections=True)
    except (AttributeError, hou.OperationFailed, hou.PermissionError,
            hou.ObjectWasDeleted):
        return False
    _fit_after_wiring(nodes, editor)
    _dbg("spliced into a wire", nodes=[n.path() for n in nodes])
    return True



def pane_tab_under_cursor():
    """The pane tab under the mouse, or None, including when there is no ui. ▸r/status-bar"""
    ui = getattr(hou, "ui", None)
    if ui is None:
        return None
    try:
        tab = ui.paneTabUnderCursor()
    except AttributeError:
        tab = None
    if tab is not None:
        return tab
    from PySide6 import QtGui

    cursor = QtGui.QCursor.pos()
    for pane_tab in ui.paneTabs():
        try:
            if not pane_tab.isCurrentTab():
                continue
            geo = pane_tab.qtScreenGeometry()
        except AttributeError:
            continue
        if geo is not None and geo.contains(cursor):
            _dbg("paneTabUnderCursor missed - geometric fallback hit",
                 pane=pane_tab.name())
            return pane_tab
    return None


def viewer_world(viewer):
    """"lop" / "obj" / None for a scene viewer, by the network it shows."""
    try:
        pwd = viewer.pwd()
        cat = pwd.childTypeCategory().name().lower()
    except (hou.Error, AttributeError) as exc:
        _dbg_once("world_failure_logged", "viewer network not read", error=repr(exc))
        return None
    if "lop" in cat:
        return "lop"
    if "obj" in cat or "object" in cat:
        return "obj"
    return None


@functools.cache
def _load_stock_lop():
    """`lop_dragdrop.py` loaded from $HH, or None when the load fails; either result is cached."""
    path = os.path.join(hou.getenv("HH"), "scripts", "scene", "lop_dragdrop.py")
    try:
        spec = importlib.util.spec_from_file_location(
            "houdini_stock_lop_dragdrop", path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        _dbg("stock lop_dragdrop load failed", error=str(exc))
        return None
    return mod


def stock_lop():
    """Houdini's own `scripts/scene/lop_dragdrop.py`, loaded once from $HH; no $HH, no lookup."""
    if not hou.getenv("HH"):
        from amaze.core import debug
        debug.event("drag", "no $HH - the host's own LOP helpers "
                            "were not loaded")
        return None
    return _load_stock_lop()



def _first_child_where(network, matches, connected_to=None):
    """The first child of `network` that `matches`, or None; `connected_to` limits to its chain."""
    try:
        children = network.children()
    except AttributeError:
        return None
    allowed = None
    if connected_to is not None:
        try:
            allowed = set(connected_to.inputAncestors(
                follow_subnets=True,
                include_ref_inputs=True,
                only_used_inputs=True,
            )) | {connected_to}
        except (AttributeError, hou.Error):
            allowed = None
    for child in children:
        if allowed is not None and child not in allowed:
            continue
        try:
            if matches(child):
                return child
        except AttributeError:
            continue
    return None


def find_assignmaterial(network, connected_to=None):
    """The first assignmaterial node in the network, or None; pass `connected_to` for a viewport drop."""
    return _first_child_where(
        network,
        lambda child: child.type().name() == "assignmaterial",
        connected_to)
