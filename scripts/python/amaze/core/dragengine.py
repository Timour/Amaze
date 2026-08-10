"""The Drag & Drop Engine - ONE self-managed gesture for every section.

THE LAW (design spec 2026-07-26): a drop lands where it is dropped,
and nothing is created anywhere before release.

v2, after the native-drag experiments (dev log #220/#221): a Qt drag
loop starves the event loop, and no HOM call can flush a viewport
repaint inside it (GeometryViewport.draw() is documented as a merged
REQUEST; even Houdini's own LOP drags never highlight live). So the
engine rides the panel's self-managed gesture instead - normal mouse
moves, live event loop, everything paints.

What the engine owns:

- Gesture state: section key + a serial per gesture (begin/end).
- VIEWPORT HOVER: per-move (throttled) it finds the scene viewer under
  the cursor, picks the target with the documented query APIs
  (locateSceneGraphPrim in LOP, queryNodeAtPixel in OBJ - the same
  calls SideFX's own tools use) and drives the selection as the
  highlight; end() restores the pre-gesture selection however the
  gesture ends. The cursor->viewport mapping is the same y-flipped
  qtScreenGeometry idiom the network-editor resolver uses.
- viewport_release_target(): one more pick at release, classifying the
  drop world for the section's release handler.
- stock_lop(): Houdini's own lop_dragdrop.py loaded from $HH, so
  material-library resolution and assignment reuse SideFX's stock
  helpers (getMaterialLibraryLop / assignMat / getMaterialPrimPathFor-
  Node) without shadowing any Houdini file.

Sections plug in per gesture phase: the drag widgets call begin() /
hover_update() / end(), and each section's release handler asks
viewport_release_target() when its drop resolves. Materials ride the
full pipeline; the other sections keep their existing release logic
and inherit the machinery as they migrate.
"""

import importlib.util
from contextlib import contextmanager
import os
import time

import hou

from amaze.helpers import hostver

#: Gesture serial - the hover state uses it to tell gestures apart.
serial = 0

#: Hover throttle and empty-pick hysteresis (picks flicker to "" for a
#: frame or two while sweeping across geometry).
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
    # True only after an actual selection WRITE this gesture - the
    # restore is skipped otherwise, so a drag that never highlighted
    # anything ends without poking the viewer at all (a redundant
    # selection write re-armed the selector prompt and flickered it).
    "dirty": False,
}


def _dbg(msg, **data):
    try:
        from amaze.core import debug
        debug.event("drag", msg, **data)
    except Exception:
        pass


#: Diagnostic pick records allowed per GESTURE. debug.event's flood
#: guard keys on (category, message) only, so after FLOOD_VERBATIM the
#: per-move records went dark for the rest of the SESSION - and the
#: five survivors were always the first ~100ms of the first drag, the
#: cursor sweeping in from the panel over empty space. Every later
#: measurement was of that, which is worse than no measurement.
#:
#: Keying the guard on `data` instead would defeat it entirely here:
#: at PICK_INTERVAL these records are ~33/second and every one is
#: unique. A per-gesture budget keeps both properties - fresh data on
#: every drag, bounded volume.
PICK_LOG_PER_GESTURE = 8

#: Separate reserve for picks that HIT, so a fast sweep-in cannot spend
#: the whole budget on misses before the cursor reaches the geometry.
PICK_LOG_HITS_PER_GESTURE = 4


def _pick_log_budget(hit=None) -> bool:
    """True while this gesture may still record a pick diagnostic.

    HITS get their own reserve. A single chronological budget is spent
    entirely on the first ~250ms of a gesture - the cursor sweeping in
    from the panel over empty space - so every trace in a whole Windows
    session read `hit: ""` while the hovers in the same session were
    landing on the sphere. The instrument was recording the least
    informative moment of every drag and nothing else, which is the
    same failure the per-gesture budget was introduced to fix one level
    up. Misses are still worth a few records; hits are worth more,
    because a hit is the only record that proves the value passed
    landed on the object.
    """
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
    global serial
    serial += 1
    # Fresh diagnostic budget per gesture (see PICK_LOG_PER_GESTURE).
    _hover["logged"] = 0
    _hover["logged_hit"] = 0
    #: Ticks the transform probe may spend this gesture. Four picks
    #: each, Debug Mode only, and it stops early on the first hit.
    _hover["probes_left"] = 40
    #: The capability composition is logged ONCE per gesture, not per
    #: move - it is the same answer for the whole drag.
    _hover["explained"] = False


def end() -> None:
    """End of gesture - however it ended. Restores the highlight."""
    _restore_highlight()
    ghost_clear()


# ------------------------------------------------------------- ghost
#
# THE OUTLINE A DRAG CARRIES over a network editor, drawn the way
# Houdini draws its own move ghost: `hou.NetworkShapeNodeShape` (or a
# plain box where the type has no shape - Vop nodes are rectangles by
# the host's own rule) into `editor.setOverlayShapes`, in NETWORK
# space so it scales with zoom, alpha 0.7 (nodegraph.py:918).
#
# Measured 2026-08-07: a node is ~1.13 x 0.28 network units, and
# `nodeType.defaultShape()` answers "" for Vop types.

#: The overlay is ONE slot per editor, so whoever writes it must give
#: it back. This remembers the editors we drew into, and every exit
#: path clears them - the same teardown discipline the name tag has.
_ghosted: list = []

GHOST_SIZE = (1.1296, 0.2824)

#: The outline's colour (2026-08-07): #fcb900 at 75%.
GHOST_COLOUR = (0.988, 0.725, 0.0)
GHOST_ALPHA = 0.75

#: The shape a carrier with no shape of its own wears. `rect` is
#: Houdini's own default node shape - rounded corners, drawn by the
#: editor rather than approximated by us - and it is the first entry
#: in `editor.nodeShapes()` (read live 2026-08-07). A NetworkShapeBox
#: would draw hard corners that no Houdini node has.
GHOST_FALLBACK_SHAPE = "rect"


def _shape_for(type_name: str) -> str:
    """The node shape a created carrier would wear, or "" for a plain
    box - the host's own lookup (`nodeType.defaultShape`)."""
    if not type_name:
        return ""
    for category in (hou.sopNodeTypeCategory(), hou.vopNodeTypeCategory(),
                     hou.lopNodeTypeCategory(), hou.cop2NodeTypeCategory()):
        try:
            node_type = hou.nodeType(category, type_name)
        except (AttributeError, hou.OperationFailed):
            node_type = None
        if node_type is not None:
            try:
                return node_type.defaultShape() or ""
            except (AttributeError, hou.OperationFailed):
                return ""
    return ""


def ghost_show(editor, position, type_name: str = "",
               connection=None) -> None:
    """Draw the outline at `position` in `editor`'s network space -
    and, over a wire, the two connections the splice would make."""
    if editor is None or position is None:
        return
    try:
        rect = hou.BoundingRect(
            position.x() - GHOST_SIZE[0] / 2.0,
            position.y() - GHOST_SIZE[1] / 2.0,
            position.x() + GHOST_SIZE[0] / 2.0,
            position.y() + GHOST_SIZE[1] / 2.0)
        colour = hou.Color(GHOST_COLOUR)
        drawn = hou.NetworkShapeNodeShape(
            rect, _shape_for(type_name) or GHOST_FALLBACK_SHAPE,
            colour, GHOST_ALPHA, True, False)
        editor.setOverlayShapes(
            splice_preview(editor, connection, position, (drawn,)))
        # AND REPAINT NOW. Our gesture holds the mouse grab, so the
        # editor receives no events of its own and repaints only when
        # something else happens to trigger one - the outline then
        # lags and catches up in jumps, which is how it read live.
        # Measured: the whole per-move query costs 0.07ms, so the
        # stutter was never the picking.
        editor.redraw()
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
        return
    if editor not in _ghosted:
        _ghosted.append(editor)


def ghost_clear() -> None:
    """Give every borrowed overlay back - on EVERY exit path."""
    while _ghosted:
        editor = _ghosted.pop()
        try:
            editor.setOverlayShapes([])
            editor.setDropTargetItem(None, "", -1)
        except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
            pass


# --------------------------------------------------------- the wire
#
# DROP ONTO A WIRE TO INSERT INTO IT - the host's own gesture, and its
# own machinery: `networkItemsInBox(for_drop=True)` returns wires among
# its triples (measured live 2026-08-07: a wire came back as
# `(OpNodeConnection, "wire", 0)` carrying merge1 -> camera1), the
# radius is `lengthToScreen(0.25)` so it scales with zoom
# (nodegraphutils.getDropTargetRadius), `setDropTargetItem` is the
# documented way to highlight what a release would hit, and
# `nodegraphutils.insertItemsIntoWire` is the splice Houdini performs
# for its own inserts.

#: The stock drop-target radius in NETWORK units - the host's constant.
DROP_TARGET_RADIUS = 0.25


def wire_under_cursor(editor, position, exclude=()):
    """The connection a release at `position` would land on, with the
    triple `setDropTargetItem` wants - or (None, "", -1).

    Nodes and connectors WIN over the wire behind them: the triples
    come back sorted by distance from the box centre, so the first
    droppable item decides, which is the host's own precedence.
    """
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
    # THE HOST'S OWN PRECEDENCE (nodegraph.py, getPreferredDropTarget):
    # scan for the FIRST connection anywhere in the list - nodes and
    # connectors in front of it are skipped, not treated as a veto.
    # Measured live: with the cursor exactly on a wire midpoint the
    # triples came back `input, node, wire`, so a first-item-wins rule
    # never sees the wire at all.
    if not _drop_on_wire_allowed(editor):
        return (None, "", -1)
    for item, name, index in found:
        if isinstance(item, hou.NodeConnection):
            # Never insert into a wire the landed nodes are already
            # part of - the host guards the same case by checking the
            # connection's ends against the items being dragged.
            try:
                if (item.inputItem() in exclude
                        or item.outputItem() in exclude):
                    continue
            except (AttributeError, hou.ObjectWasDeleted):
                pass
            return (item, name, index)
    return (None, "", -1)


def connector_under_cursor(editor, position, exclude=()):
    """The node CONNECTOR a release at `position` would land on, as
    (node, name, index) - or (None, "", -1).

    A lone node, or the last of a chain, has no wire to hit, so the
    wire question alone answers nothing there and a drop lands beside
    it. Houdini reports the node's own stubs as droppable targets, and
    a point query resolves them cleanly on its own - measured live
    against a lone node, sampling straight up through it: `output`
    alone just under the bottom edge, `node` alone through the body,
    `input` alone at and above the top edge.

    ASKED AT THE HOST'S OWN DROP RADIUS, not the connector snap
    radius. The snap radius is over twice as wide (0.53 network units
    against 0.25 at the same zoom) and reaches far enough to return a
    NEIGHBOUR's stubs, which is what made this pick the wrong node in
    a populated network. The host's node drop asks at the drop radius
    (nodegraph.py, getPossibleDropTargets) and so does this.

    The node BODY winning means an ordinary node drop, not a
    connection, so this answers nothing in that case.
    """
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
    # CONTAINMENT DECIDES, NOT ORDER. Even at the drop radius the box
    # returns the body and both stubs together for most points near a
    # node - measured live, sampling up through one: `output, node`
    # below it, `node, output, input` across the body, `input, node`
    # above. Order alone cannot separate those, and a leading `node`
    # is often a NEIGHBOUR rather than the node being aimed at. Only
    # the node the cursor is actually INSIDE means an ordinary drop.
    #
    # This is by hand what the host reads off `uievent.selected`,
    # whose hit test already reports `node`/`input`/`output`. That is
    # event-loop state with no public equivalent - the editor exposes
    # `networkItemsInBox` and nothing else that answers what is at a
    # point - so the resolution has to be redone here.
    #
    # THE NODES THAT JUST LANDED ARE NOT TARGETS in either pass.
    # Placement happens before this question is asked, so the fresh
    # node sits under the cursor and answers about itself - measured
    # live, that refused every connection. The host excludes the
    # dragged items the same way (getPossibleDropTargets).
    candidates = [(item, name, index) for item, name, index in found
                  if isinstance(item, hou.Node) and item not in exclude]

    # PASS ONE: is the cursor inside a node at all? A release there is
    # an ordinary drop and wires nothing, so it has to outrank every
    # connector in the list rather than merely appear before them.
    # Measured live: released dead centre on a node body, a NEIGHBOUR's
    # input sorted first and got wired.
    for item, _name, _index in candidates:
        try:
            if editor.itemRect(item, False).contains(position):
                return (None, "", -1)
        except (AttributeError, hou.OperationFailed,
                hou.ObjectWasDeleted):
            continue

    # PASS TWO: inside nothing, so the nearest stub is the target.
    for item, name, index in candidates:
        if name in ("input", "output"):
            return (item, name, index)
    return (None, "", -1)


def connect_to_neighbour(target, nodes, editor=None) -> bool:
    """Wire what landed to the connector it was dropped on.

    An OUTPUT under the cursor feeds the dropped node; an INPUT takes
    the dropped node's output. Houdini replaces whatever occupied an
    input index rather than adding beside it, so a chain stays a
    chain - the same reason a wire drop inserts instead of branching.
    """
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
    except (AttributeError, hou.OperationFailed, hou.PermissionError,
            hou.ObjectWasDeleted):
        return False
    _fit_after_wiring(nodes, editor)
    _dbg("connected to a neighbour", to=node.path(), side=name,
         index=index, nodes=[n.path() for n in nodes])
    return True


def _fit_after_wiring(nodes, editor=None) -> None:
    """Let the newly wired nodes settle, the way the host's own drop
    does: `moveNodesToAvoidOverlap` nudges the block clear of what it
    is now connected to, and animates the move
    (nodegraph.NodeMoveHandler.handleDrop calls it after every
    insert). `update_graph=True` is required for nodes this new -
    the editor has no graph item for them until the next paint.

    TAKE THE EDITOR FROM THE CALLER, do not ask the cursor. Asking
    `pane_tab_under_cursor` made this a SILENT NO-OP whenever the
    pointer was not over a pane tab - which is every driven run, so
    it reported "nothing moved" for a settle that had never been
    called. The host never guesses this either: it settles into
    `uievent.editor`, the editor the drop happened in. The cursor
    lookup stays only as a fallback for callers that have none."""
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
    """The artist's own preference decides, not us.

    Houdini carries a Drop On Wire preference with a live hotkey
    toggle, and forbids it outright in COP, VOP and APEX networks
    (nodegraphprefs.allowDropOnWireNetworkSpecific). Reading the same
    preference means our insert appears exactly where the host's own
    would, and vanishes when they switch it off.
    """
    try:
        import nodegraphprefs
        return bool(nodegraphprefs.allowDropOnWireNetworkSpecific(
            editor, []))
    except (ImportError, AttributeError, hou.OperationFailed):
        return True


def wire_highlight(editor, target) -> None:
    """Light the wire a release would splice into, the way Houdini
    lights its own drop targets."""
    item, name, index = target
    try:
        editor.setDropTargetItem(item, name, index)
    except (AttributeError, hou.OperationFailed, hou.ObjectWasDeleted):
        return
    if editor not in _ghosted:
        _ghosted.append(editor)


def splice_preview(editor, connection, position, shapes=()) -> tuple:
    """The two wires the splice WOULD make, drawn as the editor draws
    its own: from the upstream node into the ghost, and from the ghost
    on to the downstream node.

    `NetworkShapeConnection` takes a position and a DIRECTION per end,
    and the editor answers both for a real item
    (`itemOutputPos`/`itemOutputDir`, `itemInputPos`/`itemInputDir`) -
    so the stubs leave and enter exactly where a real wire would.
    """
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
        half = hou.Vector2(0.0, GHOST_SIZE[1] / 2.0)
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
    """Insert `nodes` into `connection`, through the host's own
    function so the wiring rules stay SideFX's.

    `insertItemsIntoWire` reads the four facts off the connection -
    input item, its output index, output item, its input index - and
    rewires around the chain. Ours is a one-node chain today; the
    signature takes a list because the host's does.
    """
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


# ------------------------------------------------------------ picking

def pane_tab_under_cursor():
    """The pane tab under the mouse: the stock z-order-aware hit test
    (hou.ui.paneTabUnderCursor, wiki: Qt/cursor facts), with the old
    geometric containment loop as fallback - kept ONLY for the
    undocumented mouse-grab case; a fallback hit is logged so the log
    answers whether the stock call ever misses during a gesture."""
    try:
        tab = hou.ui.paneTabUnderCursor()  # type: ignore
    except AttributeError:
        tab = None
    if tab is not None:
        return tab
    from PySide6 import QtGui

    cursor = QtGui.QCursor.pos()
    for pane_tab in hou.ui.paneTabs():  # type: ignore
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
    """Ask HOUDINI which coordinate transform is right, instead of
    modelling it.

    Four candidates, one pick each, once per gesture. Whichever returns
    a node under a cursor that is ON the object is the answer - and the
    answer is read off, not derived. Three separate attempts to reason
    it out from measurements were wrong, twice in opposite directions,
    so the cheap experiment wins.

      A  logical, bottom-left   (what ships today)
      B  logical, top-left      (no y flip)
      C  device,  bottom-left   (scaled by resolution/widget)
      D  device,  top-left
    """
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
    """(viewer, x, y) for the scene viewer under the global cursor,
    with viewer-space GL coordinates (origin bottom-left; the y-flip is
    the documented convention - wiki) - or (None, 0, 0)."""
    from PySide6 import QtGui

    tab = pane_tab_under_cursor()
    if tab is None:
        return None, 0, 0, 0, 1.0
    try:
        if tab.type() != hou.paneTabType.SceneViewer:
            return None, 0, 0, 0, 1.0
        geo = tab.qtScreenGeometry()
    except AttributeError:
        return None, 0, 0, 0, 1.0
    if geo is None:
        return None, 0, 0, 0, 1.0
    cursor = QtGui.QCursor.pos()
    # Map through the viewer's own GL widget, NOT the pane tab.
    #
    # qtScreenGeometry() is the whole pane - tab bar, toolbars and all -
    # while qtWindow() is the GL area itself (481x279 inside a 541x345
    # pane on H21). Measuring the cursor against the pane therefore
    # carried the viewport toolbar's width as a constant horizontal
    # error. Measured over one slow sweep on 21.0.780, passed against
    # the cursor's true position in the widget:
    #
    #     dx = +34, +34, +35          dy = 0, 0, -2
    #
    # A pure horizontal shift, and vertical already exact. That is what
    # rules out the units theory tried in 4e54dbb: a device-pixel scale
    # would have been just as wrong in y, and y was never wrong. Origin
    # only, NO scaling - queryNodeAtPixel maps window coordinates into
    # the viewport feel itself (UI_Feel::mapFromWindowToFeel, from
    # disassembly), so the value it wants is the one the widget reports.
    #
    # y keeps its flip to the GL bottom-left origin, which the same
    # measurement confirms was already right.
    #
    # It returns the LOGICAL widget height and the device scale too.
    # Everything the viewport reports about itself - vp.size(),
    # resolutionInPixels() - is in DEVICE pixels (962x558 inside a
    # 481x279 widget at dpr 2.0), while this point is logical. Mixing
    # the two is not a rounding error: flipping a logical y against the
    # device height put the pick 279px from the cursor.
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
        # Pre-2026-07-28 fallback for a Houdini without qtWindow(),
        # carrying the toolbar offset rather than picking nothing.
        x = cursor.x() - geo.left()
        y = geo.height() - (cursor.y() - geo.top())
        wh, scale = geo.height(), 1.0
    # Everything the pick depends on, in one record. A viewport drop
    # that resolves the VIEWER but picks nothing (log: target "obj" with
    # data None, target "lop" with data "") is a coordinate problem, and
    # these are the only numbers that can explain it - the Qt rect, the
    # cursor, the derived GL point, the viewport's own idea of its size,
    # and the device pixel ratio, which this math does not apply
    # anywhere.
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
    """locateSceneGraphPrim returns the RAW leaf hit - point instances
    come back as "path[instanceids]" (wiki: Viewport & picking); strip
    to the prim path proper, as SideFX's own consumers do."""
    i = path.find("[")
    return path[:i] if i >= 0 else path


def _viewport_at(viewer, x, y, scale=1.0, widget_h=0):
    """(viewport, local_x, local_y, viewport_height) for the viewport
    containing a viewer-space point, ALL IN LOGICAL PIXELS.

    queryNodeAtPixel is documented VIEWPORT-local - quad/split layouts
    mis-pick without this resolution (wiki). Falls back to curViewport
    with viewer coords (single layouts, where viewport = viewer area).

    The rects come back in DEVICE pixels - a viewport reporting
    (0, 0, 962, 558) inside a 481x279 widget is the whole widget at dpr
    2.0, not a viewport twice its size - so they are scaled down before
    being compared against a logical point. Untouched, the containment
    test compares two different units and resolves the wrong viewport in
    a quad layout on any Retina display.
    """
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
    # Single layout: the viewport IS the widget, so the widget's own
    # logical height is the authority - no device value to convert and
    # no chance of converting it with the wrong ratio.
    return vp, x, y, int(widget_h)




def _pick_trace(world, x, y, result, extra=None):
    """One record per pick: what we PASSED, and what came back.

    Coordinates and outcome were separate records before, so once the
    flood guard thinned them they could no longer be paired - and
    pairing is the whole measurement. A hit tells you the value you
    passed landed on the object; the cursor's true position tells you
    where the object actually was. The difference between those two IS
    the offset."""
    if not (_dbg_on() and _pick_log_budget(hit=bool(result))):
        return
    data = dict(extra or {})
    data.update(world=str(world), passed=(int(x), int(y)),
                hit=str(result or ""),
                houdini=hou.applicationVersionString())
    _dbg("pick", **data)


def _cursor_truth(viewer):
    """Where the cursor REALLY is, in the GL widget's own logical
    coordinates - the reference the passed value is judged against.

    NOTE the sample happens after the pick, so on a fast move it can
    drift a few pixels from the value that was actually passed (one
    reading showed dx 43 where the settled value was 34). Read the
    STEADY rows, not the fastest ones."""
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
    """Target under the pixel: a prim path (LOP) or node path (OBJ),
    "" for a miss. LOP coords are whole-view (quad-safe as is); OBJ
    resolves the containing viewport first."""
    if world == "lop":
        try:
            depth, path = viewer.locateSceneGraphPrim(x, y)
        except Exception as exc:                         # noqa: BLE001
            # SAY WHY. A bare `return ""` here is indistinguishable
            # from "the user dropped on empty space", which is how a
            # pick that fails on one Houdini version but not another
            # looks like nothing at all.
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
            # The viewport is resolved in bottom-left space, because
            # that is what vp.geometry() reports and quad layouts depend
            # on it. Only the final point is flipped back - on the
            # versions that want it, which the host-version engine
            # knows and this module does not.
            if hostver.obj_pick_wants_device_pixels(scale):
                # ONE call, whole question. The affected builds do not
                # apply the device pixel ratio themselves (SideFX fixed
                # that in 22.0.391), so they want the point already
                # scaled. Origin and convention are unchanged - the same
                # bottom-left GL point H22 takes, one factor apart.
                #
                # The version, the OS and the scaling are all weighed
                # inside the engine. This module used to test the scale
                # itself, which meant half the decision lived at the
                # call site and the macOS half lived nowhere at all.
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


# ---------------------------------------------------------- highlight

def hover_update(panel, section_key) -> None:
    """Per-move hover: pick under the cursor and drive the selection as
    the highlight. Called from the drag widgets during the self-managed
    gesture; throttled here."""
    if section_key != "material":
        return
    now = time.time()
    if now - _hover["last_pick"] < PICK_INTERVAL:
        return
    _hover["last_pick"] = now
    viewer, x, y, wh, scale = _scene_viewer_under_cursor()
    if viewer is None:
        _set_highlight(None, None, "", now, force_clear=True)
        return
    world = _viewer_world(viewer)
    if world is None:
        _set_highlight(None, None, "", now, force_clear=True)
        return
    if world == "obj" and _dbg_on() and not _hover.get("explained"):
        # WHY this machine picks the way it does, composed and itemised.
        # A report from a machine nobody here can reproduce then arrives
        # with the answer already in it - not "the workaround did not
        # apply" but "it did not apply because this is not macOS". This
        # bug cost a day for want of exactly that line.
        _hover["explained"] = True
        try:
            _dbg("pick capability", **hostver.explain_pick(scale))
        except Exception as exc:                         # noqa: BLE001
            _dbg("pick capability unavailable", error=str(exc))
    if _dbg_on() and _hover.get("probes_left", 0) > 0:
        # Keep probing until a candidate HITS. Probing once fired on the
        # first tick, which is always the moment the cursor crosses the
        # viewport EDGE over empty space - measured: cursor y 273 of a
        # 279-tall widget, 6px from the bottom. Useless. Stops the
        # instant any transform returns a node.
        _hover["probes_left"] -= 1
        if _probe_transforms(viewer, viewer, world):
            _hover["probes_left"] = 0
    _set_highlight(viewer, world,
                   _pick(viewer, world, x, y, scale, wh), now)


def _set_highlight(viewer, world, target, now, force_clear=False):
    if _hover["serial"] != serial or (
        viewer is not None
        and _hover["viewer"] is not None
        and viewer != _hover["viewer"]
    ):
        # New gesture, or the cursor moved to a DIFFERENT viewer
        # mid-gesture: restore the old viewer's selection and re-latch.
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
            # setSceneGraphHighlight never touches the selection, so
            # there is nothing to capture or restore for LOP (wiki).
            _hover["orig"] = None
        else:
            try:
                _hover["orig"] = [n.path() for n in hou.selectedNodes()]
            except Exception:
                _hover["orig"] = None
    if target == (_hover["cur"] or ""):
        # Unchanged target: selection (OBJ) is persistent state and
        # needs nothing - but the LOP highlight is TRANSIENT (the
        # viewport clears it during its own event processing; a
        # one-shot write visibly flickered out while the cursor sat
        # still). Re-assert it every pick tick, the way the Scene
        # Graph Tree drives it on every hover event.
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
            # The dedicated highlight API (selection-independent, the
            # Scene Graph Tree's own hover mechanism) - no selector
            # prompt churn, no undo entries, no restore bookkeeping.
            v.setSceneGraphHighlight([target] if target else [])
        elif w == "obj":
            # Selection IS the highlight at OBJ level (no equivalent
            # API exists there) - but selection calls push undo
            # entries, so the whole hover must be undo-silent (wiki:
            # Undo).
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


# ------------------------------------------------------------ release

@contextmanager
def keep_editor_focus():
    """A viewport release must not move the user's network editors:
    the import machinery leaves the imported node current+selected
    (hou.moveNodesTo tags moved nodes like a paste - verified in
    hython), and path-linked editors follow the current node INTO the
    material library - the live "jumps into the amaze every drop"
    report. Captures editor paths and the selection; on exit unflags
    whatever the wrapped work selected, then restores any editor whose
    path changed. Network-editor releases deliberately do NOT use
    this - a drop on the network diving into the library is wanted
    feedback there."""
    try:
        editors = [
            (pt, pt.pwd())
            for pt in hou.ui.paneTabs()  # type: ignore
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
    """One more pick at release: ("lop", viewer, primpath_or_"") /
    ("obj", viewer, node_or_None) / None when the release was not over
    a material-capable scene viewer."""
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
    """Houdini's own scripts/scene/lop_dragdrop.py, for its material-
    library and assignment helpers - loaded from $HH by explicit path
    (Amaze does not shadow it; there is nothing to shadow anymore)."""
    global _stock_lop_cache
    if _stock_lop_cache is None:
        # NO $HH, NO LOOKUP. `or ""` made the join RELATIVE, and the
        # result is then loaded and executed - so in an environment
        # without $HH (a stripped hython, a broken package env) this
        # would run `scripts/scene/lop_dragdrop.py` from whatever the
        # working directory happened to be. Always set inside Houdini,
        # which is what makes the fallback pure downside.
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


# ---------------------------------------------- LOP container policy

def first_materiallibrary(network, connected_to=None):
    """The FIRST existing, editable, non-bypassed materiallibrary in
    the network (creation order) - the drop policy's container: drops
    add to it instead of scattering fresh libraries per drop. None if
    the network has none.

    connected_to (a node): only consider libraries wired into that
    node's input chain - viewport drops prefer a library the display
    chain actually shows, since an assignment into a disconnected one
    silently does not display."""
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
        except (AttributeError, hou.OperationFailed):
            allowed = None
    for child in children:
        if allowed is not None and child not in allowed:
            continue
        try:
            if (
                "materiallibrary" in child.type().name()
                and child.isEditable()
                and not child.isBypassed()
            ):
                return child
        except AttributeError:
            continue
    return None


def find_assignmaterial(network, connected_to=None):
    """The FIRST existing assignmaterial node in the network - reused
    for assignments (its multiparm dedupes), so repeated drops converge
    on one assign node instead of chaining new ones. None if absent.

    connected_to (a node): only consider assign nodes wired into that
    node's input chain - the same filter first_materiallibrary already
    applies, and for the same reason. Without it this returned the first
    assignmaterial in CREATION order, so a leftover disconnected one
    (nothing wired to it, not in the display chain) won over the live
    one: the material imported, the binding was written into a node
    nothing displays, the menu was accepted, and the viewport did not
    change. No error, no icon, nothing to see."""
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
        except (AttributeError, hou.OperationFailed):
            allowed = None
    for child in children:
        if allowed is not None and child not in allowed:
            continue
        try:
            if child.type().name() == "assignmaterial":
                return child
        except AttributeError:
            continue
    return None
