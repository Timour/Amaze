"""Utility functions used in and around Houdini."""

import contextlib
import functools
import sys

import hou

from amaze.helpers import hostos

PATH_STYLES = ("absolute", "hip", "job", "home")  # Write Paths As: one variable or absolute; home by default
_STYLE_VARS = {"hip": "$HIP", "job": "$JOB", "home": "$HOME"}
_open_blocks = 0    # preserving blocks open right now; only the outermost arms the deferred put-back
_RETRY_MS = 100


def houdini_path(path: str, style: str = "home") -> str:
    """`path` written as Houdini writes it, under `style`'s variable; the absolute path otherwise."""
    path = hostos.canonical_path_key(path or "")
    if not path or style == "absolute":
        return path
    var = _STYLE_VARS.get(style, "$HOME")
    try:
        expanded = hostos.canonical_path_key(hou.text.expandString(var))
    except Exception:                                    # noqa: BLE001
        return path
    if not expanded or expanded in ("/", "."):
        return path
    prefix = expanded.rstrip("/") + "/"
    if path.startswith(prefix):
        return var + "/" + path[len(prefix):]
    return path


def node_pattern_match(pattern: str, name: str) -> bool:
    """Houdini node-pattern match (`*`, `mat_*`) for matnode-style parm values."""
    try:
        return bool(hou.text.patternMatch(pattern, name))
    except AttributeError:
        return bool(hou.patternMatch(pattern, name))


def node_errors(node) -> dict:
    """Houdini's own cook errors and warnings for a node, as {"errors", "warnings"}; {} for None."""
    if node is None:
        return {}
    out = {}
    for label, call in (("errors", "errors"), ("warnings", "warnings")):
        try:
            out[label] = list(getattr(node, call)())
        except Exception:
            pass
    return out


def find_file_parm(node: hou.Node) -> hou.Parm | None:
    """The node's first FileReference string parm in definition order, or None; any node type."""
    return _first_parm_where(
        node,
        lambda t: (t.type() == hou.parmTemplateType.String
                   and t.stringType() == hou.stringParmType.FileReference))


def _first_parm_where(node: hou.Node, matches) -> hou.Parm | None:
    """The node's first parm, in definition order, whose template satisfies `matches`, or None."""
    for parm in node.parms():
        if matches(parm.parmTemplate()):
            return parm
    return None


CODE_PARM_NAMES = ("snippet", "vexpression", "kernelcode", "python", "code")  # code parms are known by name only, most common first

CODE_PARM_LANGUAGE = {
    "snippet": "VEX",
    "vexpression": "VEX",
    "kernelcode": "OpenCL",
    "python": "Python",
    "code": "Code",
}


def find_code_parm(node: hou.Node) -> hou.Parm | None:
    """The node's code parm, the first of CODE_PARM_NAMES it has, or None."""
    for name in CODE_PARM_NAMES:
        parm = node.parm(name)
        if parm is not None:
            return parm
    return None


def code_parm_language(parm: hou.Parm) -> str:
    """Best-effort language label (`VEX`/`OpenCL`/`Python`/`Code`) for a code parm, from its name."""
    if parm is None:
        return "Code"
    return CODE_PARM_LANGUAGE.get(parm.name(), "Code")


def pick_cop_display_child(
    net: hou.Node, children: list | None = None
) -> hou.Node | None:
    """The child that best shows a COP network's picture, among `children` when given; None if none."""
    kids = list(children) if children is not None else list(net.children())
    if not kids:
        return None
    display = None
    try:
        display = net.displayNode()
    except AttributeError:
        display = None
    if display is not None and display not in kids:
        display = None
    if display is None:
        for child in kids:
            try:
                if child.isGenericFlagSet(hou.nodeFlag.Display):
                    display = child
                    break
            except (AttributeError, TypeError, hou.OperationFailed):
                break
    if display is not None:
        return display
    outs = [c for c in kids if c.name().lower().startswith("out")]
    for child in outs:
        lowered = child.name().lower()
        if "color" in lowered or "rgb" in lowered:
            return child
    if outs:
        return outs[0]
    for child in kids:
        if "output" in child.type().name().lower():
            return child
    terminals = [c for c in kids if not c.outputConnections()]
    if terminals:
        return terminals[-1]
    return kids[-1]


def find_color_ramp_parm(node: hou.Node) -> hou.Parm | None:
    """The node's first colour ramp parm in definition order, or None; any node type."""
    return _first_parm_where(
        node,
        lambda t: (t.type() == hou.parmTemplateType.Ramp
                   and t.parmType() == hou.rampParmType.Color))


_RAMP_BASIS = {
    "Constant": hou.rampBasis.Constant,
    "Linear": hou.rampBasis.Linear,
    "CatmullRom": hou.rampBasis.CatmullRom,
    "MonotoneCubic": hou.rampBasis.MonotoneCubic,
    "Bezier": hou.rampBasis.Bezier,
    "BSpline": hou.rampBasis.BSpline,
    "Hermite": hou.rampBasis.Hermite,
}


def ramp_to_data(ramp: hou.Ramp) -> dict:
    """A hou.Ramp as JSON-able data: basis names, key positions and values."""
    reverse = {v: k for k, v in _RAMP_BASIS.items()}
    return {
        "bases": [reverse.get(b, "Linear") for b in ramp.basis()],
        "keys": list(ramp.keys()),
        "values": [list(v) for v in ramp.values()],
    }


def data_to_ramp(data: dict) -> hou.Ramp:
    """Inverse of ramp_to_data, never raising: bad data gives a colour ramp ▸r/ramp-and-walk-edges"""
    bases = [
        _RAMP_BASIS.get(name, hou.rampBasis.Linear)
        for name in data.get("bases", [])
    ]
    keys = list(data.get("keys", []))
    values = [tuple(v) for v in data.get("values", [])]
    width = min(len(keys), len(values))    # hou.Ramp raises InvalidSize when the lengths disagree
    if not width:
        return hou.Ramp([hou.rampBasis.Linear], [0.0], [(0.0, 0.0, 0.0)])
    keys, values = keys[:width], values[:width]
    bases = (bases + [hou.rampBasis.Linear] * width)[:width]
    return hou.Ramp(bases, keys, values)


def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


def build_stepped_ramp(hex_colors: list) -> hou.Ramp:
    """A stepped, constant-basis colour ramp from a list of hex strings."""
    if not hex_colors:    # an empty palette gives one black key ▸r/ramp-and-walk-edges
        return hou.Ramp([hou.rampBasis.Constant], [0.0], [(0.0, 0.0, 0.0)])
    n = len(hex_colors)
    bases = [hou.rampBasis.Constant] * n
    keys = [i / n for i in range(n)]
    values = [_hex_to_rgb(c) for c in hex_colors]
    return hou.Ramp(bases, keys, values)


RAMP_BASES = tuple(_RAMP_BASIS)  # the Apply as submenu's entries, in Houdini's own order


def build_basis_ramp(hex_colors: list, basis: str) -> hou.Ramp:
    """A colour ramp from hex strings, every key on one basis; an unknown name means Linear."""
    b = _RAMP_BASIS.get(basis, hou.rampBasis.Linear)
    n = len(hex_colors)
    if n <= 1:
        values = [_hex_to_rgb(hex_colors[0])] if hex_colors else [(0.0, 0.0, 0.0)]
        return hou.Ramp([b], [0.0], values)
    keys = [i / (n - 1) for i in range(n)]
    values = [_hex_to_rgb(c) for c in hex_colors]
    return hou.Ramp([b] * n, keys, values)


def get_connected_nodes(node: hou.Node) -> list[hou.Node]:
    """Input and output nodes of `node`, itself included, deduped by path in discovery order."""
    in_nodes = get_connected_input_nodes([node], selected=[])
    out_nodes = get_connected_output_nodes([node], selected=[])
    seen = set()
    unique = []
    for n in in_nodes + out_nodes:
        path = n.path()
        if path not in seen:
            seen.add(path)
            unique.append(n)
    return unique


def _walk_connected(
    nodes: list[hou.Node], selected: list[hou.Node], step: str
) -> list[hou.Node]:
    """Every node reached from `nodes` by `step` ("inputs"/"outputs"), seeds included, into `selected`."""
    visited = set()
    stack = [n for n in reversed(list(nodes)) if n is not None]    # iterative ▸r/ramp-and-walk-edges
    while stack:
        node = stack.pop()
        if node is None or node.path() in visited:
            continue
        visited.add(node.path())
        selected.append(node)
        stack.extend(
            n for n in reversed(list(getattr(node, step)())) if n is not None)
    return selected


def get_connected_input_nodes(
    nodes: list[hou.Node], selected: list[hou.Node]
) -> list[hou.Node]:
    """Every node reachable through inputs(), seeds included."""
    return _walk_connected(nodes, selected, "inputs")


def get_connected_output_nodes(
    nodes: list[hou.Node], selected: list[hou.Node]
) -> list[hou.Node]:
    """Every node reachable through outputs(), seeds included."""
    return _walk_connected(nodes, selected, "outputs")


@contextlib.contextmanager
def preserving_selection_and_current():
    """Puts back the selection and the Network Editors after Amaze's own scratch copies took them."""
    try:
        before = list(hou.selectedNodes())
    except hou.Error:
        before = []
    editors = []
    ui = getattr(hou, "ui", None)
    if ui is not None:
        try:
            for pane_tab in ui.paneTabs():
                if pane_tab.type() == hou.paneTabType.NetworkEditor:
                    editors.append((pane_tab, pane_tab.currentNode(),
                                    pane_tab.pwd()))
        except (AttributeError, hou.Error):
            editors = []
    global _open_blocks
    _open_blocks += 1
    try:
        yield
    finally:
        _open_blocks -= 1
        with hou.undos.disabler():
            try:
                after = hou.selectedNodes()
            except hou.Error:
                after = ()
            for node in after:
                if node not in before:
                    try:
                        node.setSelected(False)
                    except (hou.OperationFailed, hou.ObjectWasDeleted):
                        pass
            for node in before:
                try:
                    node.setSelected(True)
                except (hou.OperationFailed, hou.ObjectWasDeleted):
                    pass
            _put_editors_back(editors, "immediate")
        if not _open_blocks:    # an inner block's pass would run last and win with a mid-operation state
            run_at_top_of_loop(functools.partial(_put_editors_back, editors, "deferred"),
                               "editor put-back")    # Houdini's own dive follows the first pass ▸r/editor-put-back


def run_at_top_of_loop(fn, what: str) -> None:
    """Run `fn` at the top of the event loop, outside Amaze's work. ▸p/deferred-ui-at-top-level"""
    try:
        from PySide6 import QtCore
    except Exception:                                    # noqa: BLE001
        return
    QtCore.QTimer.singleShot(0, functools.partial(_run_when_idle, fn, what, 0))


def _run_when_idle(fn, what: str, waited: int) -> None:
    """Run `fn` with no Amaze block open and no Amaze frame below; otherwise re-arm at 100 ms."""
    if _open_blocks or inside_amaze_work(sys._getframe(0).f_back):
        if not waited:
            from amaze.core import debug
            debug.event("interact", "%s waits" % what, open_blocks=_open_blocks)
        from PySide6 import QtCore
        QtCore.QTimer.singleShot(
            _RETRY_MS, functools.partial(_run_when_idle, fn, what, waited + _RETRY_MS))
        return
    fn()


def inside_amaze_work(frame) -> bool:
    """True while an Amaze frame but a test's is below `frame`: an event pump inside our own work."""
    while frame is not None:
        name = frame.f_globals.get("__name__", "")
        if name.startswith("amaze.") and not name.startswith("amaze.tests"):
            return True
        frame = frame.f_back
    return False


def _put_editors_back(editors, pass_name: str) -> None:
    """Return each editor to the network and current node it had."""
    from amaze.core import debug
    moved = []
    with hou.undos.disabler():
        for pane_tab, current, pwd in editors:
            try:
                if (current is not None and pwd is not None
                        and current != pwd
                        and current.parent() == pwd):  # current first, and only from inside pwd, or the editor dives
                    pane_tab.setCurrentNode(current)
            except (AttributeError, hou.OperationFailed,
                    hou.ObjectWasDeleted):
                pass
            try:
                showing = pane_tab.pwd()
                if pwd is not None and showing != pwd:
                    moved.append((showing.path(), pwd.path()))
                    pane_tab.setPwd(pwd)
            except (AttributeError, hou.OperationFailed,
                    hou.ObjectWasDeleted):
                pass
    if moved:
        debug.event("interact", "editor put back after a dive",
                    pass_name=pass_name, moves=moved)


_last_placed: list = []  # what the last place_nodes or auto_place put down


def placed_nodes() -> list:
    """The nodes the most recent placement landed."""
    return [n for n in _last_placed if n is not None]


def forget_placed() -> None:
    """Start a gesture with nothing remembered."""
    del _last_placed[:]


def _remember_placed(nodes) -> None:
    del _last_placed[:]
    _last_placed.extend(n for n in nodes if n is not None)


def auto_place(node) -> None:
    """Place a new node with no drop point, leaving every other node where it is."""
    if node is None:
        return
    _remember_placed([node])
    try:
        node.moveToGoodPosition(move_inputs=False, move_outputs=False,
                                move_unconnected=False)
    except (hou.OperationFailed, hou.ObjectWasDeleted):
        pass


def centred_on(position):
    """The setPosition value that centres a node's body on `position`; None for None."""
    if position is None:
        return None
    try:
        import nodegraphutils
        half = nodegraphutils.getNewNodeHalfSize()
    except (ImportError, AttributeError):
        half = hou.Vector2(0.5, 0.15)
    return hou.Vector2(position.x() - half.x(), position.y() - half.y())


def _box_depth(item) -> int:
    """How many network boxes hold `item`: an outer box moves before the boxes inside it."""
    depth = 0
    try:
        box = item.parentNetworkBox()
        while box is not None:
            depth += 1
            box = box.parentNetworkBox()
    except (AttributeError, hou.ObjectWasDeleted):
        pass
    return depth


def place_nodes(nodes, position) -> None:
    """Move created items as a group so the NODES' centroid lands at `position`; notes, boxes, dots ride along."""
    from amaze.core import debug
    items = [item for item in nodes if item is not None]
    nodes = [item for item in items if isinstance(item, hou.Node)]
    if not nodes:
        return
    _remember_placed(nodes)
    position = centred_on(position)
    if position is None:
        debug.event("interact", "placed by the import, no drop point",
                    nodes=len(nodes), first=nodes[0].path())
        return
    centroid_x = sum(n.position().x() for n in nodes) / len(nodes)
    centroid_y = sum(n.position().y() for n in nodes) / len(nodes)
    shift = hou.Vector2(position.x() - centroid_x, position.y() - centroid_y)
    targets = [(item, item.position() + shift) for item in items]
    boxes = sorted((pair for pair in targets if isinstance(pair[0], hou.NetworkBox)),
                   key=lambda pair: _box_depth(pair[0]))
    rest = [pair for pair in targets if not isinstance(pair[0], hou.NetworkBox)]
    for item, target in boxes + rest:    # a box carries what it holds, so all land absolute
        try:
            item.setPosition(target)
        except (hou.OperationFailed, hou.ObjectWasDeleted):
            pass
    try:
        after_x = sum(n.position().x() for n in nodes) / len(nodes)  # the achieved centroid, logged beside the asked one
        after_y = sum(n.position().y() for n in nodes) / len(nodes)
    except hou.ObjectWasDeleted:
        return
    debug.event("interact", "placed at the drop point",
                asked=[round(position.x(), 3), round(position.y(), 3)],
                landed=[round(after_x, 3), round(after_y, 3)],
                drift=[round(after_x - position.x(), 3),
                       round(after_y - position.y(), 3)],
                nodes=len(nodes), riders=len(items) - len(nodes),
                first=nodes[0].path())
