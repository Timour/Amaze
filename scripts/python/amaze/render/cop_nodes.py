"""Contexts and containers for the Node section: where saved nodes land. ▸archive/cop_nodes.py"""

import hou

CONTAINER_FOR = {    # child-type category -> the container type to create; the saved type wins
    "Cop": "copnet",
    "Sop": "geo",
    "Dop": "dopnet",
    "Lop": "lopnet",
    "Top": "topnet",
    "Chop": "chopnet",
    "Vop": "matnet",
    "Object": "subnet",
}

SAVE_CONTEXTS = ("Sop", "Cop", "Lop", "Dop", "Top", "Chop", "Object")    # OPmenu.xml keeps a copy

ITEM_CONTEXTS = SAVE_CONTEXTS + ("Vop",)    # a material saves here AS ITSELF, never as a network

CONTAINER_TYPES = ("geo", "copnet", "dopnet", "lopnet", "topnet",
                   "chopnet", "subnet", "sopnet", "objnet")    # OPmenu.xml's TYPES is a copy

NATIVE_HOST = {    # (destination category, asset context) -> the node Houdini itself hosts it in
    ("Lop", "Sop"): "sopcreate",
}


def accepts_context(node, context: str) -> bool:
    """Whether `node`'s interior holds `context` children: the one creation gate ▸r/node-graph."""
    try:
        return node.childTypeCategory().name() == context
    except (AttributeError, hou.OperationFailed):
        return False


def load_target_in(container: hou.Node, context: str) -> hou.Node:
    """Where in `container` saved nodes go: itself, its editable network, a child ▸r/hda-wrappers"""
    if accepts_context(container, context):
        return container

    for section in ("EditableNodes", "DiveTarget"):    # what the wrapper says about itself, in preference order
        try:
            definition = container.type().definition()
            path = definition.sections()[section].contents().strip()
        except (AttributeError, KeyError, hou.Error):
            continue
        if not path:
            continue
        target = container.node(path.split()[0])
        if target is None:
            continue
        try:
            if target.childTypeCategory().name() == context:
                return target
        except (AttributeError, hou.OperationFailed):
            continue

    for child in container.children():    # not an HDA, or it declares nothing useful: one level down
        try:
            if child.childTypeCategory().name() == context:
                return child
        except (AttributeError, hou.OperationFailed):
            continue
    return container


def container_type_in(dest: hou.Node, context: str,
                      preferred: str = "") -> str | None:
    """The node type to create in `dest` to hold `context` nodes, or None to refuse ▸r/node-graph"""
    try:
        category = dest.childTypeCategory()
    except (AttributeError, hou.OperationFailed):
        return None
    if category is None or not context:
        return None

    def _holds(candidate: str) -> bool:
        node_type = hou.nodeType(category, candidate)
        if node_type is None:
            return False
        try:
            child = node_type.childTypeCategory()
        except (AttributeError, hou.OperationFailed):
            return False
        return child is not None and child.name() == context

    for candidate in (preferred, CONTAINER_FOR.get(context, "")):    # the asset's own type first
        if candidate and _holds(candidate):
            return candidate

    native = NATIVE_HOST.get((category.name(), context))    # SOPs in Solaris go in a SOP Create
    if native and hou.nodeType(category, native) is not None:
        return native

    for candidate in ("%snet" % context.lower(), "subnet"):    # then the canonical network-of-X type
        if _holds(candidate):
            return candidate

    return None    # stop here: a registry scan answers hosts nobody knows ▸p/nodes-section


def is_container(node: hou.Node) -> bool:
    """Whether nodes can be put INTO `node`: the drop target test, so an empty geo passes."""
    return (node.type().name() in CONTAINER_TYPES
            and context_of(node) in SAVE_CONTEXTS)


def can_save(node: hou.Node) -> bool:
    """Whether the Node section can save `node`, as itself or as the network it opens."""
    return (context_of(node, [node]) in ITEM_CONTEXTS
            or saves_whole_network(node))


def saves_whole_network(node: hou.Node) -> bool:
    """Whether clicking `node` alone saves its interior: a non-empty container in a saved context."""
    return is_container(node) and bool(node.children())


def context_of(node: hou.Node, items: list | None = None) -> str:
    """The child context of `node`, or of its parent when `items` are given; "" for none."""
    net = node.parent() if items is not None else node
    try:
        return net.childTypeCategory().name()
    except (AttributeError, hou.OperationFailed):
        return ""
