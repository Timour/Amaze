"""
Module with helpful utility functions used in and around houdini
"""

import re
import html

import hou


def node_pattern_match(pattern: str, name: str) -> bool:
    """Houdini node-pattern match ("*", "mat_*") for matnode-style
    parm values - hou.text.patternMatch, with the pre-hou.text
    fallback."""
    try:
        return bool(hou.text.patternMatch(pattern, name))
    except AttributeError:
        return bool(hou.patternMatch(pattern, name))


def tooltip_html(text: str, width: int = 250) -> str:
    """RETIRED - use ui_helpers.tooltip_text.

    There were two tooltip-width engines solving the same problem (Qt
    renders a plain tooltip as one unwrapped line, so cap it with a
    width-constrained rich-text table) by two different rules, and the
    measured fix landed in only one of them. This one decided by
    `longest * 7 <= width` - characters times seven, in design px, with
    no device-pixel term at all - so any tooltip wide in PIXELS but
    short in characters (a proportional-font description, a colour-name
    list) passed the heuristic and was returned unconstrained, which is
    the screen-crossing tooltip ui_helpers.tooltip_text was written for
    after a live report. It MEASURES the real string against the
    tooltip font and divides the cap by the screen's device ratio.

    Kept as a one-line delegate rather than deleted: it is a public
    helper and the widget tooltips already read the other one, so this
    guarantees the two cannot answer differently again.
    """
    from amaze.helpers import ui_helpers
    return ui_helpers.tooltip_text(text)


def find_file_parm(node: hou.Node) -> hou.Parm | None:
    """Returns the first file-reference parm on the node, or None if it
    has none.

    Detects it generically via Houdini's own parm-type system (any
    string parm whose stringType() is hou.stringParmType.FileReference -
    the same "does this parm hold a file path" mechanism Houdini's own
    tooling uses, e.g. for dependency collection) instead of a hardcoded
    per-node-type lookup table. Covers any node with a file-browse parm
    - Karma (mtlximage), Redshift, Octane, Copernicus/COP file nodes,
    future renderers, custom HDAs - without needing to know about that
    node type in advance. If a node exposes more than one file parm, the
    first one in parm-definition order wins; there's no attempt to guess
    which is "the" primary one beyond that.
    """
    return _first_parm_where(
        node,
        lambda t: (t.type() == hou.parmTemplateType.String
                   and t.stringType() == hou.stringParmType.FileReference))


def _first_parm_where(node: hou.Node, matches) -> hou.Parm | None:
    """The node's first parm whose TEMPLATE satisfies `matches`, or None.

    Both generic parm finders here are this walk with one predicate
    swapped; the second's docstring already said "same generic-detection
    philosophy as find_file_parm above", which is the shape asking to be
    one function. Parm-definition order decides ties, as it always did.
    """
    for parm in node.parms():
        if matches(parm.parmTemplate()):
            return parm
    return None


# Code-parm names, most common first: a wrangle's VEX snippet, an
# OpenCL kernel, a Python SOP's script, a Gas/DOP snippet. Detection is
# by KNOWN name rather than parm-type (a code parm is just a multiline
# String with no distinguishing template flag) - covers the nodes a
# "save a wrangle snippet" library actually cares about.
CODE_PARM_NAMES = ("snippet", "vexpression", "kernelcode", "python", "code")

CODE_PARM_LANGUAGE = {
    "snippet": "VEX",
    "vexpression": "VEX",
    "kernelcode": "OpenCL",
    "python": "Python",
    "code": "Code",
}


def find_code_parm(node: hou.Node) -> hou.Parm | None:
    """The node's code/snippet parm (a wrangle's `snippet`, an OpenCL
    `kernelcode`, a Python SOP's `python`, ...), or None. Checked in
    CODE_PARM_NAMES order so a node exposing several picks the most
    snippet-like first."""
    for name in CODE_PARM_NAMES:
        parm = node.parm(name)
        if parm is not None:
            return parm
    return None


def code_parm_language(parm: hou.Parm) -> str:
    """Best-effort language label ('VEX'/'OpenCL'/'Python'/'Code') for a
    code parm, from its name."""
    if parm is None:
        return "Code"
    return CODE_PARM_LANGUAGE.get(parm.name(), "Code")


def pick_cop_display_child(
    net: hou.Node, children: list | None = None
) -> hou.Node | None:
    """The child that best represents a COP network's picture - shared
    by the live pick at save time (render/nodes.py) and the loaded-copy
    fallback at render time (render/thumbs.py) so the two can't drift.
    `children` restricts the pick to a subset (a selection save): the
    network's display node only wins if it is IN that subset.

    Order, shaped by three misses hit in live testing:
    1. The display-flagged child. displayNode() first, but that call
       has not proven reliable on Copernicus networks - so each child
       is also asked directly via the generic flag API
       (isGenericFlagSet(hou.nodeFlag.Display)).
    2. Among OUT_*-named children, the one named like COLOR - a fabric
       setup carries OUT_color/OUT_normal/OUT_height siblings, and
       first-out*-wins rendered the normal map.
    3. Any OUT_*-named child, then an output-TYPE child.
    4. A terminal child (nothing downstream), then the last child.
    """
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
    """Returns the first COLOR ramp parm on the node, or None.

    Same generic-detection philosophy as find_file_parm above: any parm
    whose template is a color RampParmTemplate qualifies, so this covers
    MaterialX/Karma ramps, Redshift ramps, COP ramps and custom HDAs
    without a per-node-type table. First in parm-definition order wins.
    """
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
    """Serializes a hou.Ramp to plain JSON-able data (basis names, key
    positions, values) so a saved gradient re-applies exactly as it was
    on the source node."""
    reverse = {v: k for k, v in _RAMP_BASIS.items()}
    return {
        "bases": [reverse.get(b, "Linear") for b in ramp.basis()],
        "keys": list(ramp.keys()),
        "values": [list(v) for v in ramp.values()],
    }


def data_to_ramp(data: dict) -> hou.Ramp:
    """Inverse of ramp_to_data - unknown basis names degrade to
    Linear rather than failing."""
    bases = [
        _RAMP_BASIS.get(name, hou.rampBasis.Linear)
        for name in data.get("bases", [])
    ]
    values = [tuple(v) for v in data.get("values", [])]
    return hou.Ramp(bases, list(data.get("keys", [])), values)


def _hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


def build_stepped_ramp(hex_colors: list) -> hou.Ramp:
    """A constant-basis (stepped) color ramp from a list of hex strings
    - discrete bands, so the palette's colors stay readable (the
    presentation used for the Sanzo Wada combinations)."""
    n = max(len(hex_colors), 1)
    bases = [hou.rampBasis.Constant] * n
    keys = [i / n for i in range(n)]
    values = [_hex_to_rgb(c) for c in hex_colors]
    return hou.Ramp(bases, keys, values)


#: The interpolations the "Apply as" submenu offers, in Houdini's own
#: order. Every one is a real hou.rampBasis - the menu is generated
#: from this table, so a basis added here appears with no menu edit.
RAMP_BASES = (
    "Constant", "Linear", "CatmullRom", "MonotoneCubic",
    "Bezier", "BSpline", "Hermite",
)


def build_basis_ramp(hex_colors: list, basis: str) -> hou.Ramp:
    """A colour ramp from hex strings, every key on ONE basis - what
    "Apply as <basis>" builds. Unknown names degrade to Linear, the
    same rule data_to_ramp already follows."""
    b = _RAMP_BASIS.get(basis, hou.rampBasis.Linear)
    n = len(hex_colors)
    if n <= 1:
        values = [_hex_to_rgb(hex_colors[0])] if hex_colors else [(0.0, 0.0, 0.0)]
        return hou.Ramp([b], [0.0], values)
    keys = [i / (n - 1) for i in range(n)]
    values = [_hex_to_rgb(c) for c in hex_colors]
    return hou.Ramp([b] * n, keys, values)


def get_connected_nodes(node: hou.Node) -> list[hou.Node]:
    """
    Get all connected nodes for the given node
    Returns Input and Output Nodes in a single list

    Both get_connected_input_nodes and get_connected_output_nodes include
    the starting node itself in their result, so the raw concatenation
    would contain it twice - dedupe by path, preserving discovery order.

    :param node: Description
    :type node: hou.Node
    :return: Description
    :rtype: list[Node]
    """
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
    """Collect every node reachable from `nodes` by following `step`
    ("inputs" or "outputs") into `selected`, seeds included.

    ONE walker for both directions. They were two functions differing
    in the word "inputs"/"outputs".

    A visited set bounds it - without one, a node reachable through
    several paths (diamond-shaped shader graphs) was re-walked once per
    path, exponentially in the worst case, and the result was only
    deduped afterwards.

    Not `hou.Node.inputAncestors()`, which exists and is Houdini's own
    C++ walk of this: it EXCLUDES the seed node (ours includes it, and
    every caller here wants it) and it follows REFERENCE inputs by
    default, which `.inputs()` does not. There is also no output-side
    equivalent in HOM 22 - checked, no `outputDescendants` - so half a
    pair would have moved to the framework and half stayed hand-rolled.
    """
    if _visited is None:
        _visited = set()
    for node in nodes:
        if node is not None and node.path() not in _visited:
            _visited.add(node.path())
            selected.append(node)
            _walk_connected(getattr(node, step)(), selected, step, _visited)
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
    """
    Sanitze String for usage in .usd files and Solaris

    :param path: Description
    :type path: str
    :return: Description
    :rtype: str
    """
    clean = re.sub("[^a-zA-Z0-9]", "_", path)
    # Node names and USD prim names may not START with a digit -
    # "01_ball.obj"-style file names hit this constantly in the
    # Geometry section.
    if clean and clean[0].isdigit():
        clean = "_" + clean
    return clean


def place_nodes(nodes, position) -> None:
    """Move created nodes as a GROUP so their centroid lands at
    `position`, preserving their relative layout - the ONE placement
    rule of the interaction system, fed by the import seam's created
    list. None position, or nothing created: the import's own
    placement stands."""
    nodes = [node for node in nodes if node is not None]
    if position is None or not nodes:
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
