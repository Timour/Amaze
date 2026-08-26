"""Utility functions used in and around Houdini."""

import contextlib
import re

import hou


def and_list(words) -> str:
    """`a`, `a and b`, `a, b and c` - the user's punctuation, ONE owner for the hou-side of the codebase (`core/database.py` keeps its own and says why: it is deliberately Houdini-free)."""
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return "%s and %s" % (", ".join(words[:-1]), words[-1])


def node_pattern_match(pattern: str, name: str) -> bool:
    """Houdini node-pattern match (`*`, `mat_*`) for matnode-style parm values - hou.text.patternMatch, with the pre-hou.text fallback."""
    try:
        return bool(hou.text.patternMatch(pattern, name))
    except AttributeError:
        return bool(hou.patternMatch(pattern, name))


def node_errors(node) -> dict:
    """Houdini's own cook errors/warnings for a node - the message that actually explains a failed render; here because the thumbnail runner and the preview engine both need it and the preview engine may not import the runner."""
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
    """The node's first file-reference parm, or None - detected via Houdini's own parm-type system (any string parm whose stringType() is FileReference), so Karma, Redshift, Octane, COP file nodes and custom HDAs all qualify with no per-node-type table; first in parm-definition order wins."""
    return _first_parm_where(
        node,
        lambda t: (t.type() == hou.parmTemplateType.String
                   and t.stringType() == hou.stringParmType.FileReference))


def _first_parm_where(node: hou.Node, matches) -> hou.Parm | None:
    """The node's first parm whose TEMPLATE satisfies `matches`, or None - the one walk both generic parm finders share, parm-definition order deciding ties."""
    for parm in node.parms():
        if matches(parm.parmTemplate()):
            return parm
    return None


CODE_PARM_NAMES = ("snippet", "vexpression", "kernelcode", "python", "code")  # code-parm names, most common first - detection is by KNOWN name because a code parm is just a multiline String with no distinguishing template flag

CODE_PARM_LANGUAGE = {
    "snippet": "VEX",
    "vexpression": "VEX",
    "kernelcode": "OpenCL",
    "python": "Python",
    "code": "Code",
}


def find_code_parm(node: hou.Node) -> hou.Parm | None:
    """The node's code/snippet parm (a wrangle's `snippet`, an OpenCL `kernelcode`, a Python SOP's `python`, ...), or None - checked in CODE_PARM_NAMES order so a node exposing several picks the most snippet-like first."""
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
    """The child that best represents a COP network's picture - shared by the live pick at save time (render/nodes.py) and the loaded-copy fallback at render time (render/thumbs.py) so the two cannot drift; `children` restricts the pick to a subset (a selection save). Order, shaped by three live misses: the display-flagged child (displayNode() plus the per-child generic flag, which Copernicus networks need), then among OUT_* children the COLOR-named one (first-out-wins once rendered the normal map), then any OUT_* child, an output-TYPE child, a terminal child, the last child."""
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
    """The node's first COLOR ramp parm, or None - same generic-detection philosophy as find_file_parm, so MaterialX/Karma, Redshift, COP and custom-HDA ramps all qualify; first in parm-definition order wins."""
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
    """Serializes a hou.Ramp to plain JSON-able data (basis names, key positions, values) so a saved gradient re-applies exactly as it was on the source node."""
    reverse = {v: k for k, v in _RAMP_BASIS.items()}
    return {
        "bases": [reverse.get(b, "Linear") for b in ramp.basis()],
        "keys": list(ramp.keys()),
        "values": [list(v) for v in ramp.values()],
    }


def data_to_ramp(data: dict) -> hou.Ramp:
    """Inverse of ramp_to_data, and total: an unknown basis degrades to Linear, and missing or mismatched keys/values give a black COLOUR ramp rather than an InvalidSize or a float one. ▸r/ramp-and-walk-edges"""
    bases = [
        _RAMP_BASIS.get(name, hou.rampBasis.Linear)
        for name in data.get("bases", [])
    ]
    keys = list(data.get("keys", []))
    values = [tuple(v) for v in data.get("values", [])]
    width = min(len(keys), len(values))    # hou.Ramp raises InvalidSize when the three disagree, and a hand-edited or truncated gradient file is exactly where they do
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
    """A constant-basis (stepped) color ramp from a list of hex strings - discrete bands, so the palette's colors stay readable."""
    if not hex_colors:    # `max(len, 1)` made the bases and keys length 1 against no values at all, which is an InvalidSize - the same empty palette build_basis_ramp already survives ▸r/ramp-and-walk-edges
        return hou.Ramp([hou.rampBasis.Constant], [0.0], [(0.0, 0.0, 0.0)])
    n = len(hex_colors)
    bases = [hou.rampBasis.Constant] * n
    keys = [i / n for i in range(n)]
    values = [_hex_to_rgb(c) for c in hex_colors]
    return hou.Ramp(bases, keys, values)


RAMP_BASES = (  # the interpolations the Apply as submenu offers, in Houdini's own order - the menu is generated from this table, so a basis added here appears with no menu edit
    "Constant", "Linear", "CatmullRom", "MonotoneCubic",
    "Bezier", "BSpline", "Hermite",
)


def build_basis_ramp(hex_colors: list, basis: str) -> hou.Ramp:
    """A colour ramp from hex strings, every key on ONE basis - unknown names degrade to Linear, the same rule data_to_ramp follows."""
    b = _RAMP_BASIS.get(basis, hou.rampBasis.Linear)
    n = len(hex_colors)
    if n <= 1:
        values = [_hex_to_rgb(hex_colors[0])] if hex_colors else [(0.0, 0.0, 0.0)]
        return hou.Ramp([b], [0.0], values)
    keys = [i / (n - 1) for i in range(n)]
    values = [_hex_to_rgb(c) for c in hex_colors]
    return hou.Ramp([b] * n, keys, values)


def get_connected_nodes(node: hou.Node) -> list[hou.Node]:
    """Input and output nodes for `node` in one list - both walks include the starting node, so the concatenation is deduped by path, preserving discovery order."""
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
    nodes: list[hou.Node], selected: list[hou.Node], step: str, _visited=None
) -> list[hou.Node]:
    """Every node reachable from `nodes` by following `step` ("inputs" or "outputs") into `selected`, seeds included - ONE walker for both directions, visited-set bounded (a diamond graph re-walked once per path, exponentially, before). Not `inputAncestors()`: that EXCLUDES the seed, follows REFERENCE inputs, and HOM 22 has no output-side equivalent - checked."""
    if _visited is None:
        _visited = set()
    stack = [n for n in reversed(list(nodes)) if n is not None]    # ITERATIVE: one frame per node in a chain hit Python's recursion limit on a long series, and the visited set bounds re-walking, not depth ▸r/ramp-and-walk-edges
    while stack:
        node = stack.pop()
        if node is None or node.path() in _visited:
            continue
        _visited.add(node.path())
        selected.append(node)
        stack.extend(
            n for n in reversed(list(getattr(node, step)())) if n is not None)
    return selected


def get_connected_input_nodes(
    nodes: list[hou.Node], selected: list[hou.Node], _visited=None
) -> list[hou.Node]:
    """Every node reachable through inputs(), seeds included."""
    return _walk_connected(nodes, selected, "inputs", _visited)


def get_connected_output_nodes(
    nodes: list[hou.Node], selected: list[hou.Node], _visited=None
) -> list[hou.Node]:
    """Every node reachable through outputs(), seeds included."""
    return _walk_connected(nodes, selected, "outputs", _visited)
def sanitize_usd_path(path: str) -> str:
    """The string made safe for .usd files and Solaris - non-alphanumerics to underscores, and a leading digit prefixed (node and USD prim names may not START with one, which `01_ball.obj`-style file names hit constantly)."""
    clean = re.sub("[^a-zA-Z0-9]", "_", path)
    if clean and clean[0].isdigit():
        clean = "_" + clean
    return clean


@contextlib.contextmanager
def preserving_selection_and_current():
    """Restores the selection, each network editor's current node and its PWD after the wrapped drop, so the artist stays where they were: an import arrives selected and current (research.md ▸ Node graph) and the FollowSelection link group dives to the new current node, while restoring current alone left an editor at root. Runs the restore under `hou.undos.disabler()` because selection calls push undo entries (research.md ▸ Viewport & picking); a MENU action is deliberately not wrapped, fronting the created node being the host's own behaviour there."""
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
    try:
        yield
    finally:
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
        try:
            from PySide6 import QtCore
            QtCore.QTimer.singleShot(  # AND AGAIN on the next event-loop turn: Houdini POSTS its pane sync, so the follow-the-current dive lands after this call returns and overwrites an immediate-only restore - measured; each pass names itself in the log (research.md ▸ Qt)
                0, lambda: _put_editors_back(editors, "deferred"))
        except Exception:                                    # noqa: BLE001
            pass


def _put_editors_back(editors, pass_name: str) -> None:
    """Return each editor to the network and current node it had."""
    from amaze.core import debug
    moved = []
    with hou.undos.disabler():
        for pane_tab, current, pwd in editors:
            try:
                if (current is not None and pwd is not None
                        and current != pwd
                        and current.parent() == pwd):  # current FIRST, and only when it lives INSIDE the restored network: an idle editor answers currentNode() with the network ITSELF, and making a network current sends the editor to its PARENT - the very dive this undoes (measured live)
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


_last_placed: list = []  # what the last placement put down - every door lands nodes through place_nodes or auto_place, so this is the one funnel that knows; the wire splice reads it instead of diffing a network's children (practice.md ▸ DONT PATCH, DONT HAND-ROLL)


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
    """Place a freshly created node WITHOUT rearranging the network - the no-drop-point half of the placement rule. `moveToGoodPosition()` defaults to moving inputs, outputs AND unconnected neighbours (measured: an untouched box slid from y=0.0 to 0.894); the three flags off leave them put, matching Houdini's own tab-menu flow, and a source scan in test_nodes_section keeps this the only caller."""
    if node is None:
        return
    _remember_placed([node])
    try:
        node.moveToGoodPosition(move_inputs=False, move_outputs=False,
                                move_unconnected=False)
    except (hou.OperationFailed, hou.ObjectWasDeleted):
        pass


def centred_on(position):
    """The POSITION to set so a node's body sits centred on `position` - `setPosition` anchors a corner, so a raw drop point puts the node beside the cursor; Houdini's own placement subtracts `getNewNodeHalfSize()` (a constant Vector2(0.5, 0.15)) and the ghost draws centred, so both agree with the host."""
    if position is None:
        return None
    try:
        import nodegraphutils
        half = nodegraphutils.getNewNodeHalfSize()
    except (ImportError, AttributeError):
        half = hou.Vector2(0.5, 0.15)
    return hou.Vector2(position.x() - half.x(), position.y() - half.y())


def place_nodes(nodes, position) -> None:
    """Move created nodes as a GROUP so their centroid lands at `position`, preserving their relative layout - the ONE placement rule of the interaction system, fed by the import seam's created list; None position or nothing created leaves the import's own placement standing."""
    from amaze.core import debug
    nodes = [node for node in nodes if node is not None]
    if not nodes:
        return
    _remember_placed(nodes)
    position = centred_on(position)
    if position is None:
        debug.event("interact", "placed by the import, no drop point",  # logged because a node that missed the drop point and a node never given one are different faults wearing the same symptom
                    nodes=len(nodes), first=nodes[0].path())
        return
    centroid_x = sum(n.position().x() for n in nodes) / len(nodes)
    centroid_y = sum(n.position().y() for n in nodes) / len(nodes)
    shift_x = position.x() - centroid_x
    shift_y = position.y() - centroid_y
    for node in nodes:
        try:
            node.setPosition(hou.Vector2(
                node.position().x() + shift_x,
                node.position().y() + shift_y))
        except (hou.OperationFailed, hou.ObjectWasDeleted):
            pass
    try:
        after_x = sum(n.position().x() for n in nodes) / len(nodes)  # what was asked and what landed, one record: only the achieved centroid tells a wrong-space position, a later mover and a refused setPosition apart (practice.md: coordinates and outcome in the SAME record)
        after_y = sum(n.position().y() for n in nodes) / len(nodes)
    except hou.ObjectWasDeleted:
        return
    debug.event("interact", "placed at the drop point",
                asked=[round(position.x(), 3), round(position.y(), 3)],
                landed=[round(after_x, 3), round(after_y, 3)],
                drift=[round(after_x - position.x(), 3),
                       round(after_y - position.y(), 3)],
                nodes=len(nodes), first=nodes[0].path())
