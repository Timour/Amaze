"""Karma -> Redshift: a Karma material's MaterialX network rebuilt as a Redshift material builder, node type by node type, the mirror of `material_converter`. Every input with no Redshift shape is named in the report and left at the shader's own value, never invented. ▸r/redshift-nodes"""

from __future__ import annotations

from typing import NamedTuple

import hou

from amaze.core import debug, material
from amaze.helpers import helpers
from amaze.render import nodes
from amaze.render.material_converter import (    # the forward converter's tables and helpers are the ONE home for the pairing and the width-aware copy
    ConversionReport,
    OPENPBR_MATERIAL_PARM_MAP,
    STANDARD_MATERIAL_PARM_MAP,
    _COLOUR_INPUTS,
    _copy_constant_parm,
    _named_inputs,
)

KARMA_SHADERS = ("mtlxstandard_surface", "mtlxopen_pbr_surface")

OPENPBR_COLOUR_INPUTS = frozenset({    # the OpenPBR inputs that carry COLOUR, read sRGB; every other texture is data ▸r/redshift-nodes
    "base_color", "specular_color", "transmission_color",
    "subsurface_color", "fuzz_color", "coat_color", "emission_color",
})

GEOMETRY_TYPES = ("mtlxtexcoord", "mtlxtangent", "mtlxnormal", "mtlxposition")    # Redshift supplies these itself; nothing to build and nothing to report


class RedshiftMaterial(NamedTuple):
    """Engine output read by NAME; `wired` False means it renders black."""

    builder: object
    shader: object
    wired: bool


def make_redshift_builder(parent: hou.Node, name: str) -> hou.Node:
    """An `rs_usd_material_builder` holding ONE terminal, `redshift_usd_material`, and the suboutput it feeds - the container Redshift itself uses in Solaris, and it renders from /mat too. The stock OpenPBR shader inside goes. ▸r/redshift-nodes"""
    builder = parent.createNode("rs_usd_material_builder")    # Redshift's Solaris builder, which also renders from /mat; a `redshift_vopnet` is refused by the LOP import door ▸r/redshift-nodes
    builder.setName(helpers.sanitize_usd_path(name), unique_name=True)
    for child in list(builder.children()):
        if child.type().name() not in material.REDSHIFT_TERMINALS + ("suboutput",):    # the stock terminal and the suboutput it feeds stay; the stock shader goes
            child.destroy()
    if redshift_terminal(builder) is None:
        builder.createNode("redshift_usd_material")
    return builder


def redshift_terminal(builder: hou.Node):
    for child in builder.children():
        if child.type().name() in material.REDSHIFT_TERMINALS:
            return child
    return None


def wire_redshift_output(builder, shader, displacement=None) -> bool:
    """Surface and Displacement onto the terminal, by ROLE - the two terminal forms spell their inputs differently. Answers whether the surface landed."""
    terminal = redshift_terminal(builder)
    if terminal is None:
        return False
    names = list(terminal.inputNames())
    landed = False
    for role, node in (("surface", shader), ("displacement", displacement)):
        if node is None:
            continue
        for spelling in material.TERMINAL_INPUTS[role]:
            if spelling in names:
                try:
                    terminal.setNamedInput(spelling, node, 0)
                    landed = landed or role == "surface"
                except hou.Error as exc:    # InvalidInput is a sibling ▸r/hou-errors
                    debug.event("redshift", "could not wire the terminal",
                                role=role, error=str(exc))
                break
    return landed


def build_redshift_material(parent, name, produce) -> RedshiftMaterial:
    """THE Redshift engine, the shape of `nodes.build_karma_material`: `produce(builder)` answers (shader, displacement) and this owns the container, the terminal, the wiring and the layout."""
    builder = make_redshift_builder(parent, name)
    result = produce(builder)
    if isinstance(result, tuple):
        shader, displacement = (result + (None,))[:2]
    else:
        shader, displacement = result, None
    if shader is not None:
        wire_redshift_output(builder, shader, displacement)
    builder.layoutChildren()
    wired = shader is None or nodes.surface_terminal_wired(builder)
    if not wired:
        debug.event("redshift", "material has no wired surface terminal",
                    material=name, builder=builder.path())
    return RedshiftMaterial(builder, shader, wired)


def find_karma_shader(container: hou.Node):
    """The MaterialX surface shader inside a Karma material's container, or None."""
    for node in container.allSubChildren():
        if node.type().name() in KARMA_SHADERS:
            return node
    return None


def find_karma_conductor(container: hou.Node):
    """The MaterialX conductor BSDF a measured metal is built as, or None."""
    for node in container.allSubChildren():
        if node.type().name() == "mtlxconductor_bsdf":
            return node
    return None


def normal_incidence_reflectance(n: float, k: float) -> float:
    """Fresnel reflectance at normal incidence for a conductor with complex index n + ik: ((n-1)^2 + k^2) / ((n+1)^2 + k^2). ▸r/redshift-nodes"""
    return ((n - 1.0) ** 2 + k ** 2) / ((n + 1.0) ** 2 + k ** 2)


def convert_conductor(node: hou.Node, builder: hou.Node, report: ConversionReport):
    """mtlxconductor_bsdf -> RS Standard Material at metalness 1, its base colour the per-channel normal-incidence reflectance of the measured complex index; roughness copied from the conductor's first axis. Reported as approximated: Redshift has no complex IOR input. ▸r/redshift-nodes"""
    rs = builder.createNode("redshift::StandardMaterial")
    rs.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    rs.parm("metalness").set(1.0)
    ior = list(node.parmTuple("ior").eval()) if node.parmTuple("ior") else [1.0, 1.0, 1.0]
    extinction = list(node.parmTuple("extinction").eval()) if node.parmTuple("extinction") else [0.0, 0.0, 0.0]
    rs.parmTuple("base_color").set(tuple(
        normal_incidence_reflectance(float(n), float(k))
        for n, k in zip(ior[:3], extinction[:3])))
    roughness = node.parmTuple("roughness")
    if roughness is not None:
        rs.parm("refl_roughness").set(float(roughness.eval()[0]))
    report.approximate(
        '"%s": the measured complex index of refraction became a metalness-1 '
        "material with its normal-incidence reflectance as base colour - "
        "Redshift's Standard Material has no complex IOR input" % node.name())
    return rs


def find_karma_displacement(container: hou.Node):
    for node in container.allSubChildren():
        if node.type().name() == "mtlxdisplacement":
            return node
    return None


def convert_karma_builder(source: hou.Node, parent: hou.Node, name: str):
    """A Karma container (the saved subnet, or a builder) into a new Redshift builder under `parent`: (builder, shader, wired, report)."""
    report = ConversionReport(name)

    def produce(builder):
        return convert_karma_network(source, builder, report)

    made = build_redshift_material(parent, name, produce)
    if made.shader is not None and not made.wired:
        report.skip("the surface output is not wired, so this material "
                    "renders black until it is connected by hand")
    return made.builder, made.shader, made.wired, report


def convert_karma_network(source: hou.Node, builder: hou.Node, report: ConversionReport):
    """Inside `builder`: the Redshift shader for `source`'s MaterialX one, every wired input converted or reported, the normal map as a Bump Map, the displacement as one. Answers (shader, displacement)."""
    src = find_karma_shader(source)
    if src is None:
        conductor = find_karma_conductor(source)
        if conductor is not None:
            return convert_conductor(conductor, builder, report), None
        report.skip("no MaterialX surface shader found inside the saved network")
        return None, None
    kind = src.type().name()
    if kind == "mtlxstandard_surface":
        rs = builder.createNode("redshift::StandardMaterial")
        pairs = [(rs_name, mtlx_name) for rs_name, mtlx_name in STANDARD_MATERIAL_PARM_MAP]
        colour_inputs = _COLOUR_INPUTS
        bump_input = "bump_input"
        normal_input = "normal"
    else:
        rs = builder.createNode("redshift::OpenPBRMaterial")
        pairs = [(rs_name, mtlx_name) for rs_name, mtlx_name in OPENPBR_MATERIAL_PARM_MAP]
        colour_inputs = OPENPBR_COLOUR_INPUTS
        bump_input = "geometry_normal" if "geometry_normal" in rs.inputNames() else ""
        normal_input = "normal"
    rs.setName(helpers.sanitize_usd_path(src.name()), unique_name=True)

    wired_inputs = _named_inputs(src)
    for rs_name, mtlx_name in pairs:
        _copy_constant_parm(src, mtlx_name, rs, rs_name)    # the value crosses whether or not a texture rides the input - what the shader shows when the wire is cut
        feeding = wired_inputs.get(mtlx_name)
        if feeding is None:
            continue
        role = "color" if mtlx_name in colour_inputs else "data"
        _connect(rs, rs_name, convert_upstream(feeding, builder, report, role), feeding, report)

    normal_src = wired_inputs.get(normal_input)
    if normal_src is not None:
        bump = convert_upstream(normal_src, builder, report, "normal")
        if bump is not None:
            if bump_input:
                _connect(rs, bump_input, bump, normal_src, report)
            else:
                terminal = redshift_terminal(builder)
                names = list(terminal.inputNames()) if terminal is not None else []
                spelling = next((s for s in material.TERMINAL_INPUTS["bump"] if s in names), "")
                if spelling:
                    terminal.setNamedInput(spelling, bump, 0)

    displacement = None
    disp_src = find_karma_displacement(source)
    if disp_src is not None:
        displacement = convert_displacement(disp_src, builder, report)
    return rs, displacement


def _constant_behind(node) -> hou.Node | None:
    """The mtlxconstant a wire carries, seen through mtlxdot pass-throughs; None for anything else."""
    for _hop in range(8):
        if node is None:
            return None
        kind = node.type().name().split("::")[0]
        if kind == "mtlxconstant":
            return node
        if kind != "mtlxdot":
            return None
        node = _named_inputs(node).get("in")
    return None


def _connect(rs: hou.Node, rs_name: str, converted, feeding: hou.Node, report: ConversionReport, output_index: int = 0) -> None:
    """Wire a converted node into the shader, or say why not - a missing converter has already been reported, so only a refused wire speaks here. A constant on the wire has no Redshift node: its value lands on the parm the wire would have fed, because the Redshift math nodes default to ZERO and a dropped factor renders black. ▸r/redshift-nodes"""
    if converted is None:
        constant = _constant_behind(feeding)
        if constant is not None:
            _copy_signature_parm(constant, "value", rs, rs_name)
        return
    node, index = converted if isinstance(converted, tuple) else (converted, output_index)
    try:
        rs.setNamedInput(rs_name, node, index)
    except hou.Error as exc:
        report.skip('"%s" could not be wired into %s (%s)' % (feeding.name(), rs_name, exc))


def convert_upstream(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """The Redshift node for one MaterialX node feeding a shader input, or None with the reason in the report. `role` is what the value MEANS at its destination - color, data or normal - which decides a texture's colour space."""
    kind = node.type().name().split("::")[0]
    if kind in GEOMETRY_TYPES:
        return None
    converter = NODE_CONVERTERS.get(kind)
    if converter is None:
        report.skip('"%s" (%s) has no Redshift equivalent - the input keeps '
                    "the shader's own value" % (node.name(), node.type().name()))
        return None
    return converter(node, builder, report, role)


def _uv_scale(image: hou.Node) -> tuple:
    """The (u, v) scale the texcoord chain applies, (1, 1) when there is none - the forward converter's `_get_or_create_uv_chain` records it on an mtlxmultiply between the texcoord and the image."""
    feeding = _named_inputs(image).get("texcoord")
    if feeding is None or feeding.type().name() != "mtlxmultiply":
        return (1.0, 1.0)
    constant = _constant_behind(_named_inputs(feeding).get("in2"))    # a wired constant is the factor Karma applies; the multiply's own parm is then dead
    source, names = ((constant, _signature_slots(constant, "value"))
                     if constant is not None
                     else (feeding, _signature_slots(feeding, "in2")))
    for parm_name in names:
        tuple_parm = source.parmTuple(parm_name)
        if tuple_parm is not None:
            values = list(tuple_parm.eval())
            if len(values) >= 2:
                return (float(values[0]), float(values[1]))
            if len(values) == 1:
                return (float(values[0]), float(values[0]))
    return (1.0, 1.0)


def convert_image(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """mtlximage -> RS Texture Sampler on the SAME file: `tex0` takes the image's unexpanded path, so a `$AMAZELIB` token stays a token and the twins share one texture store; colour reads sRGB, data and normals Raw. ▸r/redshift-nodes"""
    sampler = builder.createNode("redshift::TextureSampler")
    sampler.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    file_parm = node.parm("file")
    if file_parm is not None:
        sampler.parm("tex0").set(file_parm.unexpandedString())
    sampler.parm("tex0_colorSpace").set("sRGB" if role == "color" else "Raw")
    sampler.parmTuple("scale").set(_uv_scale(node))
    return sampler


def convert_normalmap(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """mtlxnormalmap -> RS Bump Map in tangent-space-normal mode, the map on `input`; `scale` crosses over, which the forward converter copies only in this mode too. ▸r/redshift-nodes"""
    bump = builder.createNode("redshift::BumpMap")
    bump.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    bump.parm("inputType").set("1")
    _copy_constant_parm(node, "scale", bump, "scale")
    feeding = _named_inputs(node).get("in")
    if feeding is None:
        report.skip('"%s": normal map has no texture to convert' % node.name())
        return bump
    _connect(bump, "input", convert_upstream(feeding, builder, report, "normal"), feeding, report)
    return bump


def convert_displacement(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str = "data"):
    """mtlxdisplacement -> RS Displacement as a height field, the map on `texMap`, `scale` across. ▸r/redshift-nodes"""
    disp = builder.createNode("redshift::Displacement")
    disp.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    disp.parm("map_encoding").set("2")
    _copy_constant_parm(node, "scale", disp, "scale")
    feeding = _named_inputs(node).get("displacement")
    if feeding is None:
        report.skip('"%s": displacement has no texture to convert' % node.name())
        return disp
    _connect(disp, "texMap", convert_upstream(feeding, builder, report, "data"), feeding, report)
    return disp


def convert_mix(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """mtlxmix -> RS Color Mix: MaterialX shows `bg` at mix 0 and `fg` at 1, Redshift Input 1 at 0 and Input 2 at 1. ▸r/redshift-nodes"""
    mix = builder.createNode("redshift::RSColorMix")
    mix.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    wired = _named_inputs(node)
    for mtlx_name, rs_name in (("bg", "input1"), ("fg", "input2"), ("mix", "mixAmount")):
        feeding = wired.get(mtlx_name)
        if feeding is not None:
            _connect(mix, rs_name, convert_upstream(feeding, builder, report, role if mtlx_name != "mix" else "data"), feeding, report)
        else:
            _copy_signature_parm(node, mtlx_name, mix, rs_name)
    return mix


def convert_multiply(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """mtlxmultiply -> RS Mul (float) or RS Mul Vector (colour and vector), each input converted or copied."""
    signature = node.parm("signature").evalAsString() if node.parm("signature") else "default"
    scalar = signature in ("default", "float", "FA")
    mul = builder.createNode("redshift::RSMathMul" if scalar else "redshift::RSMathMulVector")
    mul.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    wired = _named_inputs(node)
    for mtlx_name, rs_name in (("in1", "input1"), ("in2", "input2")):
        feeding = wired.get(mtlx_name)
        if feeding is not None:
            _connect(mul, rs_name, convert_upstream(feeding, builder, report, role), feeding, report)
        else:
            _copy_signature_parm(node, mtlx_name, mul, rs_name)
    return mul


TWO_INPUT_MATH = {    # mtlx category -> (Redshift float node, Redshift vector node, (mtlx input, RS connector) pairs) ▸r/redshift-nodes
    "mtlxadd": ("redshift::RSMathAdd", "redshift::RSMathAddVector", (("in1", "input1"), ("in2", "input2"))),
    "mtlxsubtract": ("redshift::RSMathSub", "redshift::RSMathSubVector", (("in1", "input1"), ("in2", "input2"))),
    "mtlxdivide": ("redshift::RSMathDiv", "redshift::RSMathDivVector", (("in1", "input1"), ("in2", "input2"))),
    "mtlxmax": ("redshift::RSMathMax", "redshift::RSMathMaxVector", (("in1", "input1"), ("in2", "input2"))),
    "mtlxmin": ("redshift::RSMathMin", "redshift::RSMathMinVector", (("in1", "input1"), ("in2", "input2"))),
    "mtlxpower": ("redshift::RSMathPow", "redshift::RSMathPowVector", (("in1", "base"), ("in2", "exponent"))),
    "mtlxabsval": ("redshift::RSMathAbs", "redshift::RSMathAbsVector", (("in", "input"),)),
}


def _is_scalar(node: hou.Node) -> bool:
    signature = node.parm("signature").evalAsString() if node.parm("signature") else "default"
    return signature in ("default", "float", "FA")


def convert_math(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """A MaterialX math node -> the Redshift float or vector node of the same operation, each input converted or copied. ▸r/redshift-nodes"""
    scalar_type, vector_type, pairs = TWO_INPUT_MATH[node.type().name().split("::")[0]]
    made = builder.createNode(scalar_type if _is_scalar(node) else vector_type)
    made.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    wired = _named_inputs(node)
    for mtlx_name, rs_name in pairs:
        feeding = wired.get(mtlx_name)
        if feeding is not None:
            _connect(made, rs_name, convert_upstream(feeding, builder, report, role), feeding, report)
        else:
            _copy_signature_parm(node, mtlx_name, made, rs_name)
    return made


def convert_clamp(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """mtlxclamp -> RS Change Range holding its input between `low` and `high`: the same range in and out, clamp on. Float only; a colour clamp is reported."""
    if not _is_scalar(node):
        report.skip('"%s" (mtlxclamp %s) has no Redshift equivalent - the input keeps '
                    "the shader's own value" % (node.name(), node.parm("signature").evalAsString()))
        return None
    rng = builder.createNode("redshift::RSMathRange")
    rng.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    for mtlx_name, rs_names in (("low", ("old_min", "new_min")), ("high", ("old_max", "new_max"))):
        for rs_name in rs_names:
            _copy_constant_parm(node, mtlx_name, rng, rs_name)
    rng.parm("clamp").set(1)
    feeding = _named_inputs(node).get("in")
    if feeding is not None:
        _connect(rng, "input", convert_upstream(feeding, builder, report, "data"), feeding, report)
    return rng


def convert_remap(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """mtlxremap -> RS Change Range, float only; a colour remap is reported."""
    signature = node.parm("signature").evalAsString() if node.parm("signature") else "default"
    if signature not in ("default", "float"):
        report.skip('"%s" (mtlxremap %s) has no Redshift equivalent - the input keeps '
                    "the shader's own value" % (node.name(), signature))
        return None
    rng = builder.createNode("redshift::RSMathRange")
    rng.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    for mtlx_name, rs_name in (("inlow", "old_min"), ("inhigh", "old_max"),
                               ("outlow", "new_min"), ("outhigh", "new_max")):
        _copy_constant_parm(node, mtlx_name, rng, rs_name)
    feeding = _named_inputs(node).get("in")
    if feeding is not None:
        _connect(rng, "input", convert_upstream(feeding, builder, report, "data"), feeding, report)
    return rng


def convert_extract(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """mtlxextract -> RS Color Splitter, the channel picked as the OUTPUT (outR/outG/outB/outA by `index`)."""
    splitter = builder.createNode("redshift::RSColorSplitter")
    splitter.setName(helpers.sanitize_usd_path(node.name()), unique_name=True)
    index_parm = node.parm("index")
    index = int(index_parm.eval()) if index_parm is not None else 0
    feeding = _named_inputs(node).get("in")
    if feeding is not None:
        _connect(splitter, "input", convert_upstream(feeding, builder, report, "data"), feeding, report)
    return (splitter, max(0, min(index, 3)))


def convert_dot(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """mtlxdot passes its input through unchanged: the Redshift side is whatever feeds it, or nothing."""
    feeding = _named_inputs(node).get("in")
    if feeding is None:
        return None
    return convert_upstream(feeding, builder, report, role)


def convert_constant(node: hou.Node, builder: hou.Node, report: ConversionReport, role: str):
    """A constant has no node of its own on the Redshift side: the caller copies its value. Answered as None after the copy so nothing is wired."""
    return None


def _signature_slots(node: hou.Node, name: str) -> tuple:
    """The parm names to try for one MaterialX input, live slot first: `<name>_<signature>`, then the bare float name - every signature's slot exists on the node, so the dead ones read as zeros. ▸r/mtlx-vop-tuple-parms"""
    signature = node.parm("signature").evalAsString() if node.parm("signature") else "default"
    return ("%s_%s" % (name, signature), name)


def _copy_signature_parm(src: hou.Node, src_name: str, dst: hou.Node, dst_name: str) -> None:
    """Copy a MaterialX input that lives in a per-signature slot (`in2_color3`, `bg_vector3`) into a Redshift parm, width-aware; the bare name is the float signature's. ▸r/mtlx-vop-tuple-parms"""
    for candidate in _signature_slots(src, src_name):
        if src.parmTuple(candidate) is not None:
            _copy_constant_parm(src, candidate, dst, dst_name)
            return


NODE_CONVERTERS = {    # MaterialX node type (version suffix stripped) -> converter; anything absent is reported, never guessed
    "mtlximage": convert_image,
    "mtlxnormalmap": convert_normalmap,
    "mtlxdisplacement": convert_displacement,
    "mtlxmix": convert_mix,
    "mtlxmultiply": convert_multiply,
    "mtlxremap": convert_remap,
    "mtlxextract": convert_extract,
    "mtlxconstant": convert_constant,
    "mtlxdot": convert_dot,
    "mtlxclamp": convert_clamp,
}
NODE_CONVERTERS.update({category: convert_math for category in TWO_INPUT_MATH})


LEGACY_CONTAINER = "redshift_vopnet"
USD_CONTAINER = "rs_usd_material_builder"
CLASSIC_TERMINAL = material.REDSHIFT_TERMINALS[0]    # `redshift_material`, the OBJ-only output the upgrade leaves behind


def upgrade_to_usd_builder(builder: hou.Node) -> hou.Node:
    """A legacy `redshift_vopnet` rebuilt as an `rs_usd_material_builder` beside it: every child but the classic `redshift_material` output moves across with names and wiring kept, the USD terminal takes the classic one's feeds by role (`Bump Map` becomes `BumpMap`), the old container is destroyed and the new one carries its name. Anything else is answered unchanged. ▸r/redshift-nodes"""
    if builder.type().name() != LEGACY_CONTAINER:
        return builder
    name = builder.name()
    classic = [c for c in builder.children()
               if c.type().name() == CLASSIC_TERMINAL]
    feeds = []    # (classic input name, source node name, source output index)
    for terminal in classic:
        for conn in terminal.inputConnections():
            feeds.append((conn.outputName(), conn.inputNode().name(),
                          conn.outputIndex()))
    movers = [c for c in builder.children()
              if c.type().name() != CLASSIC_TERMINAL]
    fresh = make_redshift_builder(builder.parent(), name + "_usd")
    if movers:
        hou.moveNodesTo(movers, fresh)
    terminal = redshift_terminal(fresh)
    spelling = {"Bump Map": "BumpMap"}
    for input_name, source_name, index in feeds:
        source = fresh.node(source_name)
        if source is None or terminal is None:
            continue
        try:
            terminal.setNamedInput(spelling.get(input_name, input_name),
                                   source, index)
        except hou.Error as exc:    # an input the USD terminal does not have (Shadow, Photon) is dropped, not fatal
            debug.event("redshift", "legacy feed not carried",
                        input=input_name, error=str(exc))
    builder.destroy()
    fresh.setName(name, unique_name=True)
    return fresh
