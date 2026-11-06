"""A .mtlx to flat `mtlx*` VOP nodes translator, on Houdini's MaterialX Python API."""

from __future__ import annotations

import os

import hou

from amaze.core import debug
from amaze.helpers import hostos


_TYPE_OVERRIDES = {  # categories whose VOP type is not mtlx<category> or its ::2.0
    "surfacematerial": None,       # the material prim - the builder IS this
}

_TYPE_TO_SIGNATURE = {  # mtlx `type` -> mtlximage `signature`; a color3 image reads sRGB, others raw
    "color3": "color3",
    "color4": "color4",
    "float": "default",
    "vector2": "vector2",
    "vector3": "vector3",
    "vector4": "vector4",
}


def _vop_type_for(category: str, parent: hou.Node) -> str | None:
    """The VOP node type for a MaterialX node category."""
    if category in _TYPE_OVERRIDES:
        return _TYPE_OVERRIDES[category]
    for candidate in ("mtlx" + category, "mtlx" + category + "::2.0"):
        try:
            if parent.type().childTypeCategory().nodeType(candidate) is not None:
                return candidate
        except Exception:
            pass
    return "mtlx" + category      # let createNode fail and be reported


def _signature(mnode) -> str | None:
    """A node's VOP signature; `convert` names its input type, then its own. ▸r/simready-graph"""
    inp = mnode.getInput("in") if mnode.getCategory() == "convert" else None
    if inp is not None:
        return inp.getType() + mnode.getType()
    return _TYPE_TO_SIGNATURE.get(mnode.getType())


def _resolve_file(value: str, mtlx_dir: str, prefix: str) -> str:
    """A .mtlx file value as a path inside `mtlx_dir`; "" when it escapes, logged, never raised."""
    if not value:
        return value
    value = value.replace("\\", "/")    # a Windows-authored `textures\map.png` must resolve on Unix
    candidates = [os.path.join(mtlx_dir, prefix, value) if prefix else None,
                  os.path.join(mtlx_dir, value)]
    contained = []
    for base in candidates:
        if not base:
            continue
        try:
            contained.append(hostos.contained_join(mtlx_dir, base))
        except hostos.PathEscape:
            continue
    for base in contained:
        if os.path.exists(base):
            return os.path.normpath(base)
    if contained:
        return os.path.normpath(contained[-1])
    debug.event("matx", "texture reference refused - outside the "
                        "downloaded package", value=str(value)[:120])
    return ""


def _set_value(node: hou.Node, parm_name: str, mtlx_type: str, value_str: str):
    """Set a constant input value, split by MaterialX type."""
    if value_str is None:
        return
    try:
        if mtlx_type in ("color3", "vector3", "color4", "vector4",
                         "vector2"):    # one body for every tuple width - the truncation to len(pt) is what sizes it
            parts = [float(v) for v in value_str.split(",")]
            pt = node.parmTuple("%s_%s" % (parm_name, mtlx_type))    # the typed slot first ▸r/mtlx-vop-tuple-parms
            if pt is None or len(pt) < len(parts):
                pt = node.parmTuple(parm_name)
            if pt is not None:
                pt.set(tuple(parts[: len(pt)]))
        elif mtlx_type == "integer":
            p = node.parm(parm_name)
            if p is not None:
                p.set(int(float(value_str)))
        elif mtlx_type in ("string", "filename"):
            p = node.parm(parm_name)
            if p is not None:
                p.set(value_str)
        elif mtlx_type == "boolean":  # "true"/"1" is on, anything else off
            p = node.parm(parm_name)
            if p is not None:
                p.set(1 if value_str.strip().lower() in ("true", "1") else 0)
        else:                       # float and everything scalar
            p = node.parm(parm_name)
            if p is not None:
                p.set(float(value_str))
    except (hou.Error, ValueError) as exc:  # collected in _DROPPED for the caller to report
        _DROPPED.append("%s.%s (%s)" % (node.name(), parm_name, exc))


_DROPPED: list = []  # inputs _set_value dropped during the current build; build_material drains and reports them


def _named_few(items, limit: int = 6) -> str:
    """The first few names, then a count of the rest."""
    names = [str(item) for item in items]
    shown = ", ".join(names[:limit])
    if len(names) <= limit:
        return shown
    return "%s, and %d more" % (shown, len(names) - limit)


def build_material(mtlx_path: str, builder: hou.Node, name: str):
    """Translate a .mtlx into VOP nodes inside `builder`; (shader, displacement), either may be None."""
    _DROPPED.clear()  # an early return below must not carry entries into the next material's report
    try:
        import MaterialX as mx
    except ImportError as exc:
        debug.note(
            "Houdini's MaterialX support could not be loaded (%s), so "
            "this material could not be built. Your scene is "
            "unchanged." % exc)
        return (None, None)

    doc = mx.createDocument()
    try:
        mx.readFromXmlFile(doc, mtlx_path)
    except Exception as exc:
        debug.note(  # the path goes in the data, not the sentence
            "the downloaded MaterialX file for this material could "
            "not be read (%s), so nothing was built. Your scene is "
            "unchanged." % exc, path=mtlx_path)
        return (None, None)

    mtlx_dir = os.path.dirname(mtlx_path)

    all_mtlx_nodes = []  # (mtlx_node, active_file_prefix), every graph flattened; key by getNamePath()

    for node in doc.getNodes():
        if node.getCategory() == "surfacematerial":
            continue
        all_mtlx_nodes.append((node, node.getActiveFilePrefix()))

    for graph in doc.getNodeGraphs():
        for node in graph.getNodes():
            all_mtlx_nodes.append((node, node.getActiveFilePrefix()))

    vop_by_path = {}               # mtlx name path -> VOP node
    skipped = []                   # name (category) pairs with no VOP type here
    for mnode, prefix in all_mtlx_nodes:  # pass 1: create a VOP node for each, set constant values + signature
        vtype = _vop_type_for(mnode.getCategory(), builder)
        if vtype is None:
            continue
        try:
            vnode = builder.createNode(vtype)
        except hou.Error:
            skipped.append("%s (%s)"
                           % (mnode.getName(), mnode.getCategory()))
            continue
        try:
            vnode.setName(mnode.getName(), unique_name=True)
        except hou.OperationFailed:
            pass
        vop_by_path[mnode.getNamePath()] = vnode

        sig = _signature(mnode)
        sig_parm = vnode.parm("signature")
        if sig is not None and sig_parm is not None:
            try:
                sig_parm.set(sig)
            except hou.Error:
                pass

        for inp in mnode.getInputs():
            if inp.getValue() is None:
                continue            # a connection, handled in pass 2
            if inp.getType() == "filename":
                resolved = _resolve_file(
                    inp.getValueString(), mtlx_dir, prefix
                )
                fp = vnode.parm(inp.getName())
                if fp is not None:
                    fp.set(resolved)
                cs = inp.getAttribute("colorspace")    # the file's own; with none, the signature decides
                csp = vnode.parm("filecolorspace")
                if cs and csp is not None:
                    try:
                        csp.set(cs)
                    except hou.Error:
                        pass
            else:
                _set_value(vnode, inp.getName(), inp.getType(),
                           inp.getValueString())

    if skipped:
        debug.event("import", "vop nodes skipped", nodes=skipped)
        debug.note(
            "left out %d node%s with no Houdini equivalent: %s. "
            "Everything else in the material was built."
            % (len(skipped), "" if len(skipped) == 1 else "s",
               _named_few(skipped)))
    if _DROPPED:  # note() is the half the user sees with Debug Mode off
        debug.event("import", "mtlx inputs dropped", inputs=list(_DROPPED))
        debug.note(
            "left %d MaterialX input%s at the default value: %s. The "
            "material was built, but may not look exactly like the "
            "original." % (len(_DROPPED),
                           "" if len(_DROPPED) == 1 else "s",
                           _named_few(_DROPPED)))
        _DROPPED.clear()

    def _source_node(mnode, inp):
        """The mtlx node feeding this input, looked up in its own scope by MaterialX, or None."""
        direct = inp.getNodeName()
        if direct:
            parent = mnode.getParent()
            return parent.getNode(direct) if parent is not None else None
        graph = inp.getNodeGraphString()
        out = inp.getOutputString()
        if not (graph and out):
            return None
        gobj = doc.getNodeGraph(graph)
        if gobj is None:
            return None
        oobj = gobj.getOutput(out)
        if oobj is None:
            return None
        return gobj.getNode(oobj.getNodeName())

    def _wire_from(mnode):
        vnode = vop_by_path.get(mnode.getNamePath())
        if vnode is None:
            return
        for inp in mnode.getInputs():
            src_node = _source_node(mnode, inp)
            if src_node is None:
                continue
            src = vop_by_path.get(src_node.getNamePath())
            if src is None:
                continue
            try:
                vnode.setNamedInput(inp.getName(), src, 0)
            except hou.OperationFailed:
                debug.event("import", "translate: could not wire input",
                            node=mnode.getNamePath(), input=inp.getName(),
                            source=src_node.getNamePath())

    for mnode, _prefix in all_mtlx_nodes:  # pass 2: wire connections, now that every node exists
        _wire_from(mnode)

    shader = displacement = None  # find the surface shader and displacement to hand back to the engine
    for mnode, _prefix in all_mtlx_nodes:
        cat = mnode.getCategory()
        vnode = vop_by_path.get(mnode.getNamePath())
        if vnode is None:
            continue
        if cat in ("standard_surface", "open_pbr_surface") and shader is None:
            shader = vnode
        elif cat == "displacement" and displacement is None:
            displacement = vnode

    builder.layoutChildren()
    debug.event(
        "import", "translated mtlx",
        material=name, nodes=len(vop_by_path),
        shader=shader.name() if shader else None,
        displacement=displacement.name() if displacement else None,
    )
    if shader is None:
        debug.note(
            "no surface shader was found in this MaterialX material, "
            "so its nodes were built but nothing is connected to the "
            "surface output.", path=mtlx_path)
    return (shader, displacement)
