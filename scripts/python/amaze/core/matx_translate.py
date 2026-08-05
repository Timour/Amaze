"""Clean .mtlx -> VOP translator, built on Houdini's MaterialX Python API.

Replaces the old editmaterial approach, which was the wrong tool: it
EDITS a material, so it promotes every input to the subnet interface and
turns `file` from a node input into a promoted parameter - producing
collapsed, all-promoted nodes whose file inputs were dropped from the USD
export (the black-material bug), nothing like a hand-built material.

This parses the .mtlx directly (MaterialX 1.39 ships with Houdini) and
builds fresh `mtlx*` VOP nodes - real `file` inputs, an `out` output,
nothing promoted - FLATTENED into the builder (no nested nodegraph),
matching this studio's house style and the KARMA_REF reference. Same
shape as the Redshift converter: an adapter that produces a clean shader
network for the one Karma material engine.

Returns (shader, displacement) or (None, None) with a printed reason.
"""

from __future__ import annotations

import os

import hou

from amaze.core import debug


#: MaterialX node categories whose VOP type isn't simply "mtlx<category>".
#: Everything else maps by the mtlx<category> rule with a ::2.0 fallback.
_TYPE_OVERRIDES = {
    "surfacematerial": None,       # the material prim - the builder IS this
}

#: MaterialX node `type` -> mtlximage `signature` value. This is the
#: per-map colour-space rule at its source: a color3 image reads sRGB, a
#: float/vector3 image reads raw. The .mtlx's own type is authoritative.
_TYPE_TO_SIGNATURE = {
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


def _resolve_file(value: str, mtlx_dir: str, prefix: str) -> str:
    """A .mtlx file value is relative to the document (plus any active
    fileprefix). Resolve to an absolute path that exists where possible."""
    if not value:
        return value
    if os.path.isabs(value):
        return value
    for base in (
        os.path.join(mtlx_dir, prefix, value) if prefix else None,
        os.path.join(mtlx_dir, value),
    ):
        if base and os.path.exists(base):
            return os.path.normpath(base)
    return os.path.normpath(os.path.join(mtlx_dir, value))


def _set_value(node: hou.Node, parm_name: str, mtlx_type: str, value_str: str):
    """Set a constant input value, split by MaterialX type."""
    if value_str is None:
        return
    try:
        if mtlx_type in ("color3", "vector3"):
            parts = [float(v) for v in value_str.split(",")]
            pt = node.parmTuple(parm_name)
            if pt is not None:
                pt.set(tuple(parts[: len(pt)]))
        elif mtlx_type in ("color4", "vector4"):
            parts = [float(v) for v in value_str.split(",")]
            pt = node.parmTuple(parm_name)
            if pt is not None:
                pt.set(tuple(parts[: len(pt)]))
        elif mtlx_type == "vector2":
            parts = [float(v) for v in value_str.split(",")]
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
        elif mtlx_type == "boolean":
            # Not scalar-parseable: float("true") raises, and the except
            # below would silently drop the input at its default.
            p = node.parm(parm_name)
            if p is not None:
                p.set(1 if value_str.strip().lower() in ("true", "1") else 0)
        else:                       # float and everything scalar
            p = node.parm(parm_name)
            if p is not None:
                p.set(float(value_str))
    except (hou.Error, ValueError) as exc:
        # NOT silent. An input the .mtlx expresses in an unexpected form
        # (wrong component count, a non-numeric scalar) leaves the parm
        # at its DEFAULT, so the material builds, reports success, and
        # renders wrong - with nothing to look at. Collected here and
        # summarised by the caller, the way unresolved textures already
        # are.
        _DROPPED.append("%s.%s (%s)" % (node.name(), parm_name, exc))


#: Inputs dropped by _set_value during the current build - drained and
#: reported by build_material.
_DROPPED: list = []


def _named_few(items, limit: int = 6) -> str:
    """The first few names, then an honest count of the rest.

    A bare `items[:6]` under a total of nine reads as a list that lost
    its end, and the reader cannot tell whether the sentence was cut or
    the data was."""
    names = [str(item) for item in items]
    shown = ", ".join(names[:limit])
    if len(names) <= limit:
        return shown
    return "%s, and %d more" % (shown, len(names) - limit)


def build_material(mtlx_path: str, builder: hou.Node, name: str):
    """Translate a .mtlx into clean VOP nodes inside `builder`.

    Returns (surface_shader, displacement_shader); either may be None."""
    # Per build: an early return below (no MaterialX API, unreadable
    # document) must not carry entries into the next material's report.
    _DROPPED.clear()
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
        # The path goes in the DATA, not the sentence: it is a file
        # inside the download folder that the user has never opened.
        debug.note(
            "the downloaded MaterialX file for this material could "
            "not be read (%s), so nothing was built. Your scene is "
            "unchanged." % exc, path=mtlx_path)
        return (None, None)

    mtlx_dir = os.path.dirname(mtlx_path)

    # Every node we'll build, FLATTENED: top-level nodes (minus the
    # surfacematerial prim) plus every node inside every nodegraph. The
    # nodegraph wrapper is dropped - its outputs are resolved to the
    # internal node feeding them, so the shader wires straight to the
    # image, exactly like a hand-built flat material.
    graph_output_to_node = {}      # (graph_name, output_name) -> node_name
    all_mtlx_nodes = []            # (mtlx_node, active_file_prefix)

    for node in doc.getNodes():
        if node.getCategory() == "surfacematerial":
            continue
        all_mtlx_nodes.append((node, node.getActiveFilePrefix()))

    for graph in doc.getNodeGraphs():
        for out in graph.getOutputs():
            graph_output_to_node[(graph.getName(), out.getName())] = \
                out.getNodeName()
        for node in graph.getNodes():
            all_mtlx_nodes.append((node, node.getActiveFilePrefix()))

    # Pass 1: create a VOP node for each, set constant values + signature.
    vop_by_name = {}
    skipped = []                   # "name (category)" with no VOP type here
    for mnode, prefix in all_mtlx_nodes:
        vtype = _vop_type_for(mnode.getCategory(), builder)
        if vtype is None:
            continue
        try:
            vnode = builder.createNode(vtype)
        except hou.OperationFailed:
            skipped.append("%s (%s)"
                           % (mnode.getName(), mnode.getCategory()))
            continue
        try:
            vnode.setName(mnode.getName(), unique_name=True)
        except hou.OperationFailed:
            pass
        vop_by_name[mnode.getName()] = vnode

        # Signature from the node's declared type (images especially).
        sig = _TYPE_TO_SIGNATURE.get(mnode.getType())
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
                cs = inp.getAttribute("colorspace")
                csp = vnode.parm("filecolorspace")
                if not cs:
                    # No colorspace attribute (SideFX's own data maps
                    # ship none): leaving "automatic" hands the choice
                    # to Houdini's OCIO FILE RULES, which read every
                    # png/jpg as sRGB - degamma'ing roughness/normal
                    # DATA maps (wiki: materials research). The node's
                    # declared type decides instead: non-color
                    # signatures are data and read Raw.
                    if mnode.getType() in (
                        "float", "vector2", "vector3", "vector4"
                    ):
                        cs = "Raw"
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
    if _DROPPED:
        # Same treatment as skipped nodes: debug.event is gated on Debug
        # Mode, which is off by default, so a partially-translated
        # material would otherwise report success and render wrong with
        # nothing on screen. note() is the visible half: it prints with
        # Debug Mode off, and on Windows its log record is the whole
        # channel, because any print pops the Houdini Console.
        debug.event("import", "mtlx inputs dropped", inputs=list(_DROPPED))
        debug.note(
            "left %d MaterialX input%s at the default value: %s. The "
            "material was built, but may not look exactly like the "
            "original." % (len(_DROPPED),
                           "" if len(_DROPPED) == 1 else "s",
                           _named_few(_DROPPED)))
        _DROPPED.clear()

    # Pass 2: wire connections (now that every node exists).
    def _wire_from(mnode):
        vnode = vop_by_name.get(mnode.getName())
        if vnode is None:
            return
        for inp in mnode.getInputs():
            src_name = None
            direct = inp.getNodeName()
            graph = inp.getNodeGraphString()
            out = inp.getOutputString()
            if direct:
                src_name = direct
            elif graph and out:
                src_name = graph_output_to_node.get((graph, out))
            if not src_name:
                continue
            src = vop_by_name.get(src_name)
            if src is None:
                continue
            try:
                vnode.setNamedInput(inp.getName(), src, 0)
            except hou.OperationFailed:
                debug.event("import", "translate: could not wire input",
                            node=mnode.getName(), input=inp.getName(),
                            source=src_name)

    for mnode, _prefix in all_mtlx_nodes:
        _wire_from(mnode)

    # Find the surface shader and displacement to hand back to the engine.
    shader = displacement = None
    for mnode, _prefix in all_mtlx_nodes:
        cat = mnode.getCategory()
        vnode = vop_by_name.get(mnode.getName())
        if vnode is None:
            continue
        if cat in ("standard_surface", "open_pbr_surface") and shader is None:
            shader = vnode
        elif cat == "displacement" and displacement is None:
            displacement = vnode

    builder.layoutChildren()
    debug.event(
        "import", "translated mtlx",
        material=name, nodes=len(vop_by_name),
        shader=shader.name() if shader else None,
        displacement=displacement.name() if displacement else None,
    )
    if shader is None:
        debug.note(
            "no surface shader was found in this MaterialX material, "
            "so its nodes were built but nothing is connected to the "
            "surface output.", path=mtlx_path)
    return (shader, displacement)
