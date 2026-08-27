"""The drag & drop engine - ONE self-managed gesture per section, driven by begin() / hover_update() / end() from the drag widgets with viewport_release_target() asked at the drop; a drop lands where it is dropped and nothing is created before release. Never a native Qt drag. ▸r/native-drag-paint"""

import importlib.util
from contextlib import contextmanager
import os
import time

import hou

from amaze.helpers import hostver

serial = 0

PICK_INTERVAL = 0.03
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
    """True while this gesture may still record a pick diagnostic - hits draw on their own reserve, so a sweep-in over empty space cannot spend the whole budget on misses."""
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
    _reset_move()


def end() -> None:
    """End of gesture - however it ended. Restores the highlight."""
    _restore_highlight()
    ghost_clear()
    _reset_move()


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


PANE_REVALIDATE = 0.25


def pane_under_cursor_tracked(now=None):
    """(pane, kind, fresh) for the gesture's per-move pane question: the real z-aware lookup runs when the cursor LEAVES the cached pane's screen rect and at most every PANE_REVALIDATE otherwise - between, a pure rect check answers, because `paneTabUnderCursor` measured ~3ms per call under drag load. ▸p/drag-move-cost"""
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
    """True when the ghost's target answers are STALE - at most once per PICK_INTERVAL, immediately on a fresh gesture or another editor; the outline itself still follows every move. ▸p/drag-move-cost"""
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

NEW_NODE_HALF = (0.5, 0.15)    # the host's own placement-ghost half size (nodegraphutils.theNewNodeHalfSize); the TAB-menu ghost is the look users compare against


def _is_vop_network(editor) -> bool:
    from amaze.core import cop_library
    try:
        pwd = editor.pwd()
    except (AttributeError, hou.OperationFailed):
        return False
    return cop_library.accepts_context(pwd, "Vop")


def _snap_delta(editor, rect):
    """The host's own placement snap (nodegraphselectpos.py:302): `nodegraphsnap.snap` against `allVisibleRects` - None when it does not apply, and ALWAYS None headless, where the module's own `hou.ui` import refuses."""
    try:
        import nodegraphsnap
        result = nodegraphsnap.snap(editor, None, rect,
                                    editor.allVisibleRects([]))
        if result.isValid():
            return result.delta()
    except Exception:                                     # noqa: BLE001
        pass
    return None


def ghost_snap_position():
    """The last drawn ghost's SNAPPED centre, or None - the release places the carrier here, so what was promised is what lands."""
    return _move.get("snap_pos")


def _ghost_half_for(editor) -> tuple:
    """The placement ghost's half-extent, the host's own recipe (nodegraphselectpos.py:286-301): a 0.5 SQUARE for non-VOP contexts - the NodeShape keeps its natural proportions inside it, which is what makes it match a standard node exactly - and the flat half for VOP contexts. ▸r/overlay-shapes"""
    if _is_vop_network(editor):
        return NEW_NODE_HALF
    half = max(NEW_NODE_HALF)
    return (half, half)

GHOST_COLOUR = (0.988, 0.725, 0.0)
GHOST_ALPHA = 0.75

GHOST_FALLBACK_SHAPE = "rect"


_shape_cache: dict = {}


def _shape_for(type_name: str) -> str:
    """The node shape a created carrier would wear, or "" for a plain box, through the host's own `nodeType.defaultShape` - cached per type name, misses included, since a type's default shape cannot change within a session. ▸r/overlay-shapes"""
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
    """Draw the outline at `position` in `editor`'s network space, with the splice preview over a wire, and repaint NOW - the gesture holds the mouse grab, so the editor receives no events of its own. ▸r/native-drag-paint"""
    if editor is None or position is None:
        return
    try:
        half = _ghost_half_for(editor)
        rect = hou.BoundingRect(
            position.x() - half[0], position.y() - half[1],
            position.x() + half[0], position.y() + half[1])
        _move["snap_pos"] = None
        delta = _snap_delta(editor, rect)
        if delta is not None:    # aligned to neighbours the way the host's own placement ghost aligns - and the release lands on the same snapped point
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
    while _ghosted:
        editor = _ghosted.pop()
        try:
            editor.setOverlayShapes([])
            editor.setDropTargetItem(None, "", -1)
        except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
            pass


DROP_TARGET_RADIUS = 0.25


def wire_under_cursor(editor, position, exclude=()):
    """The connection a release at `position` would land on, as the triple `setDropTargetItem` wants - or (None, "", -1); the FIRST connection in the list wins and items in front of it are skipped, never a veto. The preference gates the QUESTION: a network where the host forbids the insert pays no hit test. ▸r/drop-targets"""
    if editor is None or position is None:
        return (None, "", -1)
    if not _drop_on_wire_allowed(editor):
        return (None, "", -1)
    try:
        spot = editor.posToScreen(position)
        radius = editor.lengthToScreen(DROP_TARGET_RADIUS)
        found = editor.networkItemsInBox(
            hou.Vector2(spot.x() - radius, spot.y() - radius),
            hou.Vector2(spot.x() + radius, spot.y() + radius),
            for_drop=True)
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
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
    """The node CONNECTOR a release at `position` would land on, as (node, name, index) - or (None, "", -1), which is also the answer when the cursor is inside a node body; asked at the host's DROP radius, never the wider connector snap radius. ▸r/drop-targets"""
    if editor is None or position is None:
        return (None, "", -1)
    try:
        spot = editor.posToScreen(position)
        radius = editor.lengthToScreen(DROP_TARGET_RADIUS)
        found = editor.networkItemsInBox(
            hou.Vector2(spot.x() - radius, spot.y() - radius),
            hou.Vector2(spot.x() + radius, spot.y() + radius),
            for_drop=True)
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
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


def connect_to_neighbour(target, nodes, editor=None) -> bool:
    """Wire what landed to the connector it was dropped on - an OUTPUT under the cursor feeds it, an INPUT takes its output, and an occupied input index is REPLACED, never added beside. ▸r/drop-targets"""
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
    except (AttributeError, hou.InvalidInput,    # the index was picked during the hover and spent at the release, so a connector the node has since lost arrives here - `setInput` documents this one beside the two below, and it is a SIBLING of them, never caught by naming them
            hou.OperationFailed, hou.PermissionError,
            hou.ObjectWasDeleted):
        return False
    _fit_after_wiring(nodes, editor)
    _dbg("connected to a neighbour", to=node.path(), side=name,
         index=index, nodes=[n.path() for n in nodes])
    return True


def _fit_after_wiring(nodes, editor=None) -> None:
    """Settle newly wired nodes the way the host's own drop does - PASS THE EDITOR the drop happened in, because the cursor fallback answers nothing in a driven run and settles silently into no-op. ▸r/drop-targets"""
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
    """The artist's own Drop On Wire preference decides, read through the host's own call - True when it cannot be asked. ▸r/drop-targets"""
    try:
        import nodegraphprefs
        return bool(nodegraphprefs.allowDropOnWireNetworkSpecific(
            editor, []))
    except (ImportError, AttributeError, hou.OperationFailed):
        return True


def wire_highlight(editor, target) -> None:
    """Light the wire a release would splice into, and remember the editor so a later clear reaches it. ▸r/overlay-shapes"""
    item, name, index = target
    try:
        editor.setDropTargetItem(item, name, index)
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
        return
    if editor not in _ghosted:
        _ghosted.append(editor)


def splice_preview(editor, connection, position, shapes=()) -> tuple:
    """The two wires the splice WOULD make - upstream into the ghost, ghost on to downstream - appended to `shapes` and drawn as the editor draws its own. ▸r/overlay-shapes"""
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
        half = hou.Vector2(0.0, NEW_NODE_HALF[1])    # already a HALF size, the host's own
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
    """Insert `nodes` into `connection` through the host's own `insertItemsIntoWire`, so the wiring rules stay SideFX's - a list because the host's signature takes one. ▸r/drop-targets"""
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
    """The pane tab under the mouse - the stock z-order-aware hit test, falling back to a logged geometric loop for the mouse-grab case, and None with no ui to ask, which every caller already reads as no tab under the cursor. ▸r/status-bar"""
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
    """Debug Mode only: one pick per candidate transform, once per gesture, so the log says which one HITS instead of the reader deriving it. ▸r/pick-boundary"""
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
    """(viewer, x, y, widget height, device scale) for the scene viewer under the cursor, or (None, 0, 0, 0, 1.0) - the lookup half; the geometry lives in `_scene_viewer_geometry`. ▸r/pick-boundary"""
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
    """(viewer, x, y, widget height, device scale) for a KNOWN scene viewer in viewer-space GL coordinates, origin bottom-left - mapped through qtWindow(), the GL area, never qtScreenGeometry(), which is the whole pane and carries the toolbar as a constant x error. ▸r/pick-boundary"""
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
    """Strip a raw `locateSceneGraphPrim` hit to the prim path proper - point instances come back as `path[instanceids]`. ▸r/pick-boundary"""
    i = path.find("[")
    return path[:i] if i >= 0 else path


def _viewport_at(viewer, x, y, scale=1.0, widget_h=0):
    """(viewport, local_x, local_y, viewport_height) for the viewport holding a viewer-space point, ALL IN LOGICAL PIXELS - the rects arrive in DEVICE pixels and are scaled down first, or a quad layout resolves the wrong viewport on any Retina display. ▸r/pick-boundary"""
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




def _pick_trace(world, x, y, result, extra=None):
    """One record per pick carrying what was PASSED and what came back TOGETHER - separated, they cannot be paired, and the difference between them is the whole measurement."""
    if not (_dbg_on() and _pick_log_budget(hit=bool(result))):
        return
    data = dict(extra or {})
    data.update(world=str(world), passed=(int(x), int(y)),
                hit=str(result or ""),
                houdini=hou.applicationVersionString())
    _dbg("pick", **data)


def _cursor_truth(viewer):
    """Where the cursor REALLY is in the GL widget's logical coordinates - sampled AFTER the pick, so read the steady rows: a fast move drifts this a few pixels from the value actually passed."""
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
    """Target under the pixel - a prim path (LOP) or node path (OBJ), "" for a miss; LOP coords are whole-view and quad-safe as they are, OBJ resolves its containing viewport first and asks `hostver` whether that build wants device pixels. ▸r/pick-boundary"""
    if world == "lop":
        try:
            depth, path = viewer.locateSceneGraphPrim(x, y)
        except Exception as exc:                         # noqa: BLE001
            _dbg("lop pick raised", error="%s: %s" % (type(exc).__name__, exc),
                 x=x, y=y, houdini=hou.applicationVersionString())
            return ""
        if depth is None or depth < 0:
            _pick_trace("lop", x, y, "", _cursor_truth(viewer))
            return ""
        found = _clean_prim_path(str(path))
        _pick_trace("lop", x, y, found, _cursor_truth(viewer))
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
        _pick_trace("obj", lx, ly, found, _cursor_truth(viewer))
        return found
    return ""



def hover_update(panel, section_key, pane_tab=None,
                 pane_kind=None) -> None:
    """Per-move hover, throttled here: pick under the cursor and drive the highlight - called from the drag widgets during the gesture, Materials only, with the TRACKED pane handed in so a tick over any other pane costs no lookup ▸p/drag-move-cost."""
    if section_key != "material":
        return
    now = time.time()
    if now - _hover["last_pick"] < PICK_INTERVAL:
        return
    _hover["last_pick"] = now
    if pane_tab is None and pane_kind is None:
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
    """Drive the highlight for one pick - LOP through the transient scene-graph API, which must be RE-ASSERTED every tick, and OBJ through an undo-silent selection write, which must be captured and restored. ▸r/pick-boundary"""
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
        elif w == "obj":
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
                    n = hou.node(p)
                    if n is not None:
                        n.setSelected(True)
    except Exception:
        pass



@contextmanager
def keep_editor_focus():
    """Wrap a VIEWPORT release so path-linked network editors do not follow the imported node into the library - captures editor paths and the selection, unflags what the wrapped work selected, and restores any editor that moved; network-editor releases deliberately do NOT use it."""
    ui = getattr(hou, "ui", None)
    try:
        editors = [
            (pt, pt.pwd())
            for pt in (ui.paneTabs() if ui is not None else ())
            if pt.type() == hou.paneTabType.NetworkEditor
        ]
    except Exception:
        editors = []
    try:
        prev = set(hou.selectedNodes())
    except Exception:
        prev = None
    try:
        yield
    finally:
        if prev is not None:
            try:
                with hou.undos.disabler():
                    for n in hou.selectedNodes():
                        if n not in prev:
                            n.setCurrent(False)
                            n.setSelected(False)
            except Exception:
                pass
        for pt, pwd in editors:
            try:
                if pt.pwd() != pwd:
                    pt.setPwd(pwd)
            except Exception:
                pass


def viewport_release_target(panel):
    """One more pick at release: ("lop", viewer, primpath_or_"") / ("obj", viewer, node_or_None) / None when the release was not over a material-capable scene viewer."""
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


_stock_lop_cache = None


def stock_lop():
    """Houdini's own `scripts/scene/lop_dragdrop.py` for its material-library and assignment helpers, loaded once from $HH by explicit path - NO $HH, no lookup, because a relative join here would be loaded and EXECUTED from the working directory."""
    global _stock_lop_cache
    if _stock_lop_cache is None:
        hh = hou.getenv("HH")
        if not hh:
            from amaze.core import debug
            debug.event("drag", "no $HH - the host's own LOP helpers "
                                "were not loaded")
            return None
        path = os.path.join(hh, "scripts", "scene", "lop_dragdrop.py")
        try:
            spec = importlib.util.spec_from_file_location(
                "houdini_stock_lop_dragdrop", path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _stock_lop_cache = mod
        except Exception as exc:
            _dbg("stock lop_dragdrop load failed", error=str(exc))
            _stock_lop_cache = False
    return _stock_lop_cache or None



def _first_child_where(network, matches, connected_to=None):
    """The first child of `network` that `matches`, in creation order, or None - pass `connected_to` to consider only children wired into that node's input chain, because an assignment into a disconnected node is accepted and changes nothing on screen."""
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


def first_materiallibrary(network, connected_to=None):
    """The FIRST editable, non-bypassed materiallibrary in the network, or None - the drop policy's container, so drops add to one instead of scattering a fresh library each time; `connected_to` restricts it to that node's input chain."""
    def _is_library(child):
        return ("materiallibrary" in child.type().name()
                and child.isEditable()
                and not child.isBypassed())

    return _first_child_where(network, _is_library, connected_to)


def find_assignmaterial(network, connected_to=None):
    """The FIRST assignmaterial node in the network, or None - reused so repeated drops converge on one node rather than chaining; PASS `connected_to` for a viewport drop, or a leftover disconnected node wins on creation order and the binding lands where nothing displays it."""
    return _first_child_where(
        network,
        lambda child: child.type().name() == "assignmaterial",
        connected_to)
