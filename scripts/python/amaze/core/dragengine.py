"""The drag and drop engine: one self-managed gesture, never a native Qt drag. ▸r/native-drag-paint"""

import functools
import importlib.util
from contextlib import contextmanager
import os
import time

import hou

from amaze.helpers import hostver

serial = 0

PICK_INTERVAL = 0.03
_UNASKED = object()    # "no tracked answer supplied", distinct from a tracked miss (None)
CLEAR_DELAY = 0.25

_hover = {
    "serial": -1,
    "last_pick": 0.0,
    "last_hit": 0.0,
    "world": None,
    "viewer": None,
    "cur": None,
    "orig": None,
    "dirty": False,
}


def _dbg(msg, **data):
    try:
        from amaze.core import debug
        debug.event("drag", msg, **data)
    except Exception:
        pass


PICK_LOG_PER_GESTURE = 8

PICK_LOG_HITS_PER_GESTURE = 4


def _pick_log_budget(hit=None) -> bool:
    """True while this gesture may still record a pick diagnostic; hits have their own reserve."""
    key = "logged_hit" if hit else "logged"
    cap = PICK_LOG_HITS_PER_GESTURE if hit else PICK_LOG_PER_GESTURE
    if _hover.get(key, 0) >= cap:
        return False
    _hover[key] = _hover.get(key, 0) + 1
    return True


def _dbg_on() -> bool:
    """Guard for records whose DATA costs something to gather."""
    try:
        from amaze.core import debug
        return debug.is_on()
    except Exception:                                    # noqa: BLE001
        return False


def begin(section_key: str, ids=()) -> None:
    """Start a gesture: fresh serial, fresh diagnostic and probe budgets."""
    global serial
    serial += 1
    _hover["logged"] = 0
    _hover["logged_hit"] = 0
    _hover["probes_left"] = 40
    _hover["explained"] = False
    _hover["snap_failure_said"] = False
    _reset_move()
    _move["snap_pos"] = None
    _move["landing"] = None    # the previous release has had its answer


def end() -> None:
    """End of gesture, however it ended: the highlight back, the snap point kept as the landing."""
    landing = _move.get("snap_pos")    # the release asks for it after this clears the outline
    _restore_highlight()
    ghost_clear()
    _reset_move()
    _move["landing"] = landing


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
    "landing": None,    # the snap point at end(), answered until the next begin()
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
    """(pane, kind, fresh) for the per-move pane question, cached on the pane's rect. ▸p/drag-move-cost"""
    from PySide6 import QtGui

    now = time.time() if now is None else now
    age = now - _move["pane_at"]
    rect = _move["pane_rect"]
    if rect is not None:
        if age < PANE_REVALIDATE and rect.contains(QtGui.QCursor.pos()):
            return _move["pane"], _move["pane_kind"], False
    elif _move["pane_at"] and age < PICK_INTERVAL:    # a MISS holds only a pick interval, so entering the editor from dead space is never 250ms blind
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
    """True when the ghost's target answers are stale, once per PICK_INTERVAL. ▸p/drag-move-cost"""
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


def set_ghost_answers(blocked, target, type_name) -> None:
    """The tick's findings, held for the moves between ticks."""
    _move["blocked"] = bool(blocked)
    _move["target"] = target
    _move["type_name"] = type_name or ""


def ghost_answers():
    """(blocked, wire_target, type_name) as of the last tick."""
    return _move["blocked"], _move["target"], _move["type_name"]


_ghosted: list = []

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
        if not _hover.get("snap_failure_said"):    # once a gesture: this runs on every move
            _hover["snap_failure_said"] = True
            _dbg("placement snap unavailable", error=repr(exc))
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
    """The drawn ghost's snapped centre, else the landing `end()` kept, else None."""
    if _move.get("snap_pos") is not None:
        return _move["snap_pos"]
    return _move.get("landing")


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
    """The node shape a created carrier would wear, or "" for a box; cached per type. ▸r/overlay-shapes"""
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
        if delta is not None:    # aligned to neighbours like the host's ghost; the release lands on the same point
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
    if editor not in _ghosted:
        _ghosted.append(editor)


def ghost_clear() -> None:
    """Give every borrowed overlay back - on EVERY exit path."""
    _move["snap_pos"] = None
    _forget_snap_rects()
    while _ghosted:
        editor = _ghosted.pop()
        try:
            editor.setOverlayShapes([])
            editor.setDropTargetItem(None, "", -1)
        except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
            pass


DROP_TARGET_RADIUS = 0.25


def _drop_items_at(editor, position):
    """Every network item within the drop radius of `position`, or None when the editor cannot say."""
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
    """The connection a release at `position` would land on, or (None, "", -1). ▸r/drop-targets"""
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
    """The connector a release at `position` would land on, or (None, "", -1). ▸r/drop-targets"""
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
    """One undo entry per release: the first `drop_group` its verb opens stays open until this exits."""
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
    """A drop verb's undo group, held open under `holding_drop_group` for the splice. ▸r/undo-groups"""
    if _held["armed"] and _held["group"] is None:
        group = hou.undos.group(label)
        group.__enter__()
        _held["group"] = group
        yield
        return
    with hou.undos.group(label):    # nested in a held group it merges into it
        yield


def connect_to_neighbour(target, nodes, editor=None) -> bool:
    """Wire what landed to its connector; an occupied input is replaced. ▸r/drop-targets"""
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
    except (AttributeError, hou.InvalidInput,    # a connector the node lost since the hover lands here
            hou.OperationFailed, hou.PermissionError,
            hou.ObjectWasDeleted):
        return False
    _fit_after_wiring(nodes, editor)
    _dbg("connected to a neighbour", to=node.path(), side=name,
         index=index, nodes=[n.path() for n in nodes])
    return True


def _fit_after_wiring(nodes, editor=None) -> None:
    """Settle newly wired nodes like the host's drop; pass the drop's editor. ▸r/drop-targets"""
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
    """The artist's Drop On Wire preference; True when it cannot be asked. ▸r/drop-targets"""
    try:
        import nodegraphprefs
        return bool(nodegraphprefs.allowDropOnWireNetworkSpecific(
            editor, []))
    except (ImportError, AttributeError, hou.OperationFailed):
        return True


def wire_highlight(editor, target) -> None:
    """Light the wire a release would splice into, remembering the editor. ▸r/overlay-shapes"""
    item, name, index = target
    try:
        editor.setDropTargetItem(item, name, index)
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
        return
    if editor not in _ghosted:
        _ghosted.append(editor)


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



def _probe_transforms(tab, viewer, world):
    """Debug Mode only: one pick per candidate transform, once per gesture. ▸r/pick-boundary"""
    try:
        from PySide6 import QtGui
        window = tab.qtWindow()
        local = window.mapFromGlobal(QtGui.QCursor.pos())
        w, h = window.width(), window.height()
        lx, ly = local.x(), local.y()
        scale = 1.0
        try:
            res = viewer.curViewport().resolutionInPixels()
            if res and w:
                scale = float(res[0]) / float(w)
        except Exception:                                # noqa: BLE001
            pass
        cands = {
            "A_logical_bottomleft": (lx, h - ly),
            "B_logical_topleft": (lx, ly),
            "C_device_bottomleft": (lx * scale, (h - ly) * scale),
            "D_device_topleft": (lx * scale, ly * scale),
        }
        hits = {}
        any_hit = False
        for name, (cx, cy) in cands.items():
            try:
                if world == "lop":
                    depth, path = viewer.locateSceneGraphPrim(int(cx), int(cy))
                    got = "" if (depth is None or depth < 0) else str(path)
                else:
                    vp = viewer.curViewport()
                    node = vp.queryNodeAtPixel(int(cx), int(cy))
                    got = node.path() if node is not None else ""
            except Exception as exc:                     # noqa: BLE001
                got = "raised:%s" % type(exc).__name__
            hits[name] = got or "-"
            if got and not got.startswith("raised:"):
                any_hit = True
        if not any_hit and _hover.get("probes_left", 0) > 0:
            return False        # nothing under the cursor yet - keep going
        _dbg("transform probe", world=str(world), cursor=(lx, ly),
             widget=(w, h), scale=round(scale, 3),
             candidates={k: [int(v[0]), int(v[1])] for k, v in cands.items()},
             results=hits, any_hit=any_hit,
             houdini=hou.applicationVersionString())
        return any_hit
    except Exception as exc:                             # noqa: BLE001
        _dbg("transform probe failed", error=str(exc))
        return False


def _scene_viewer_under_cursor():
    """(viewer, x, y, height, scale) under the cursor, or (None, 0, 0, 0, 1.0). ▸r/pick-boundary"""
    tab = pane_tab_under_cursor()
    if tab is None:
        return None, 0, 0, 0, 1.0
    try:
        if tab.type() != hou.paneTabType.SceneViewer:
            return None, 0, 0, 0, 1.0
    except AttributeError:
        return None, 0, 0, 0, 1.0
    return _scene_viewer_geometry(tab)


def _scene_viewer_geometry(tab):
    """(viewer, x, y, height, scale) for a known viewer, GL coordinates. ▸r/pick-boundary"""
    from PySide6 import QtGui

    try:
        geo = tab.qtScreenGeometry()
    except AttributeError:
        return None, 0, 0, 0, 1.0
    if geo is None:
        return None, 0, 0, 0, 1.0
    cursor = QtGui.QCursor.pos()
    x, y, wh, scale = None, None, 0, 1.0
    try:
        window = tab.qtWindow()
        local = window.mapFromGlobal(cursor)
        wh = window.height()
        if wh:
            x = local.x()
            y = wh - local.y()
        try:
            res = tab.curViewport().resolutionInPixels()
            if res and window.width():
                scale = float(res[0]) / float(window.width())
        except Exception:                                # noqa: BLE001
            scale = 1.0
    except Exception:                                    # noqa: BLE001
        x, y = None, None
    if x is None or y is None:
        x = cursor.x() - geo.left()
        y = geo.height() - (cursor.y() - geo.top())
        wh, scale = geo.height(), 1.0
    if _dbg_on() and _pick_log_budget():
        try:
            vp = tab.curViewport()
            vp_size = tuple(vp.size())
        except Exception:                                # noqa: BLE001
            vp, vp_size = None, None
        try:
            res = tuple(vp.resolutionInPixels())
        except Exception:                                # noqa: BLE001
            res = None
        win = None
        try:
            win = tab.qtWindow()
            dpr = win.devicePixelRatioF()
            win_size = (win.width(), win.height())
            local = win.mapFromGlobal(cursor)
            win_local = (local.x(), local.y())
        except Exception:                                # noqa: BLE001
            dpr, win_size, win_local = None, None, None
        _dbg("viewport pick coords",
             houdini=hou.applicationVersionString(),
             geo=(geo.left(), geo.top(), geo.width(), geo.height()),
             cursor=(cursor.x(), cursor.y()),
             derived=(int(x), int(y)),
             viewport_size=vp_size, resolution=res,
             qtwindow_size=win_size, qtwindow_local=win_local, dpr=dpr)
    return tab, int(x), int(y), int(wh), scale


def _viewer_world(viewer):
    """"lop" / "obj" / None for a scene viewer, by what it displays."""
    try:
        pwd = viewer.pwd()
        cat = pwd.childTypeCategory().name().lower()
    except Exception:
        return None
    if "lop" in cat:
        return "lop"
    if "obj" in cat or "object" in cat:
        return "obj"
    return None


def _clean_prim_path(path: str) -> str:
    """Strip a raw `locateSceneGraphPrim` hit to the prim path. ▸r/pick-boundary"""
    i = path.find("[")
    return path[:i] if i >= 0 else path


def _viewport_at(viewer, x, y, scale=1.0, widget_h=0):
    """(viewport, x, y, height) holding a viewer-space point, in logical pixels. ▸r/pick-boundary"""
    try:
        vps = viewer.viewports()
    except AttributeError:
        vps = ()
    for vp in vps:
        try:
            rect = vp.geometry()
        except AttributeError:
            try:
                rect = vp.size()
            except AttributeError:
                continue
        try:
            gx, gy, gw, gh = (float(v) / (scale or 1.0) for v in rect)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if gx <= x < gx + gw and gy <= y < gy + gh:
            return vp, int(x - gx), int(y - gy), int(round(gh))
    try:
        vp = viewer.curViewport()
    except AttributeError:
        return None, 0, 0, 0
    return vp, x, y, int(widget_h)




def _pick_trace(world, x, y, result, viewer=None):
    """One record per pick: what was PASSED beside what came back, with the cursor read only here."""
    if not (_dbg_on() and _pick_log_budget(hit=bool(result))):
        return
    data = _cursor_truth(viewer) if viewer is not None else {}
    data.update(world=str(world), passed=(int(x), int(y)),
                hit=str(result or ""),
                houdini=hou.applicationVersionString())
    _dbg("pick", **data)


def _cursor_truth(viewer):
    """The cursor in the GL widget's logical coordinates, sampled after the pick."""
    try:
        from PySide6 import QtGui
        window = viewer.qtWindow()
        local = window.mapFromGlobal(QtGui.QCursor.pos())
        return {"true_local": (local.x(), local.y()),
                "widget": (window.width(), window.height()),
                "resolution": tuple(viewer.curViewport().resolutionInPixels())}
    except Exception:                                    # noqa: BLE001
        return {}


def _pick(viewer, world, x, y, scale=1.0, widget_h=0):
    """Target under the pixel: a prim path (LOP) or node path (OBJ), "" for a miss. ▸r/pick-boundary"""
    if world == "lop":
        try:
            depth, path = viewer.locateSceneGraphPrim(x, y)
        except Exception as exc:                         # noqa: BLE001
            _dbg("lop pick raised", error="%s: %s" % (type(exc).__name__, exc),
                 x=x, y=y, houdini=hou.applicationVersionString())
            return ""
        if depth is None or depth < 0:
            _pick_trace("lop", x, y, "", viewer)
            return ""
        found = _clean_prim_path(str(path))
        _pick_trace("lop", x, y, found, viewer)
        return found
    if world == "obj":
        try:
            vp, lx, ly, vh = _viewport_at(viewer, x, y, scale, widget_h)
            if vp is None:
                _dbg("obj pick: no viewport resolved", x=x, y=y)
                return ""
            if hostver.obj_pick_wants_device_pixels(scale):
                lx, ly = int(round(lx * scale)), int(round(ly * scale))
            node = vp.queryNodeAtPixel(lx, ly)
        except Exception as exc:                         # noqa: BLE001
            _dbg("obj pick raised", error="%s: %s" % (type(exc).__name__, exc),
                 x=x, y=y, houdini=hou.applicationVersionString())
            return ""
        found = node.path() if node is not None else ""
        _pick_trace("obj", lx, ly, found, viewer)
        return found
    return ""



def hover_update(panel, section_key, pane_tab=None,
                 pane_kind=_UNASKED) -> None:
    """Per-move hover, throttled: pick and highlight; pass the tracked pane. ▸p/drag-move-cost"""
    if section_key != "material":
        return
    _hover["outline"] = bool(getattr(getattr(panel, "prefs", None), "obj_drag_outline", 1))
    now = time.time()
    if now - _hover["last_pick"] < PICK_INTERVAL:
        return
    _hover["last_pick"] = now
    if pane_kind is _UNASKED and pane_tab is None:
        viewer, x, y, wh, scale = _scene_viewer_under_cursor()
    elif pane_kind != hou.paneTabType.SceneViewer:
        viewer, x, y, wh, scale = None, 0, 0, 0, 1.0
    else:
        viewer, x, y, wh, scale = _scene_viewer_geometry(pane_tab)
    if viewer is None:
        _set_highlight(None, None, "", now, force_clear=True)
        return
    world = _viewer_world(viewer)
    if world is None:
        _set_highlight(None, None, "", now, force_clear=True)
        return
    if world == "obj" and _dbg_on() and not _hover.get("explained"):
        _hover["explained"] = True
        try:
            _dbg("pick capability", **hostver.explain_pick(scale))
        except Exception as exc:                         # noqa: BLE001
            _dbg("pick capability unavailable", error=str(exc))
    if _dbg_on() and _hover.get("probes_left", 0) > 0:
        _hover["probes_left"] -= 1
        if _probe_transforms(viewer, viewer, world):
            _hover["probes_left"] = 0
    _set_highlight(viewer, world,
                   _pick(viewer, world, x, y, scale, wh), now)


def _set_highlight(viewer, world, target, now, force_clear=False):
    """Drive the highlight for one pick, LOP or OBJ. ▸r/pick-boundary"""
    if _hover["serial"] != serial or (
        viewer is not None
        and _hover["viewer"] is not None
        and viewer != _hover["viewer"]
    ):
        _restore_highlight()
        _hover["serial"] = serial
    if not target:
        if not force_clear and _hover["cur"] and \
                now - _hover["last_hit"] < CLEAR_DELAY:
            return
    else:
        _hover["last_hit"] = now
    if viewer is not None and _hover["viewer"] is None:
        _hover["viewer"] = viewer
        _hover["world"] = world
        if world == "lop":
            _hover["orig"] = None
        else:
            try:
                _hover["orig"] = [n.path() for n in hou.selectedNodes()]
            except Exception:
                _hover["orig"] = None
    if target == (_hover["cur"] or ""):
        if _hover["world"] == "lop" and _hover["viewer"] is not None \
                and _hover["cur"]:
            try:
                _hover["viewer"].setSceneGraphHighlight([_hover["cur"]])
            except Exception:
                pass
        return
    _hover["cur"] = target or None
    _dbg("hover", world=str(world), target=str(target))
    w = _hover["world"]
    v = _hover["viewer"]
    _hover["dirty"] = True
    try:
        if w == "lop" and v is not None:
            v.setSceneGraphHighlight([target] if target else [])
        elif w == "obj" and _hover.get("outline", True):    # the OBJ Drag Outline preference
            with hou.undos.disabler():
                if target:
                    node = hou.node(target)
                    if node is not None:
                        node.setSelected(True, clear_all_selected=True)
                else:
                    hou.clearAllSelected()
    except Exception:
        pass


def _restore_highlight() -> None:
    v, w, orig = _hover["viewer"], _hover["world"], _hover["orig"]
    dirty = _hover["dirty"]
    _hover["viewer"] = None
    _hover["world"] = None
    _hover["cur"] = None
    _hover["orig"] = None
    _hover["dirty"] = False
    if v is None or not dirty:
        return
    try:
        if w == "lop":
            v.setSceneGraphHighlight([])
        elif orig is not None:
            with hou.undos.disabler():
                hou.clearAllSelected()
                for p in orig:
                    try:
                        n = hou.node(p)
                        if n is not None:
                            n.setSelected(True)
                    except Exception:                    # noqa: BLE001
                        continue    # one node that raises must not keep the rest unselected
    except Exception:
        pass


def viewport_release_target(panel):
    """One more pick at release: ("lop"|"obj", viewer, target), or None off a scene viewer."""
    viewer, x, y, wh, scale = _scene_viewer_under_cursor()
    if viewer is None:
        return None
    world = _viewer_world(viewer)
    if world == "lop":
        return ("lop", viewer, _pick(viewer, world, x, y, scale, wh))
    if world == "obj":
        path = _pick(viewer, world, x, y, scale, wh)
        return ("obj", viewer, hou.node(path) if path else None)
    return None


@functools.cache
def _load_stock_lop():
    """`lop_dragdrop.py` loaded from $HH, or None when the load fails; either answer is kept."""
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
