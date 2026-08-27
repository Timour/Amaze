"""Redshift -> Karma/MaterialX conversion: best-effort node-graph translation, node type by node type - anything without a mapping is reported in the ConversionReport, never silently dropped or guessed at. ▸r/rs-conversion"""

import inspect

import hou

from amaze.core import debug
from amaze.core import material

from amaze.helpers import helpers


class ConversionReport:
    """What happened during one material's conversion, so the caller can show an honest summary instead of a bare pass/fail."""

    def __init__(self, mat_name: str) -> None:
        self.mat_name = mat_name
        self.skipped: list[str] = []
        self.approximated: list[str] = []

    def skip(self, msg: str) -> None:
        self.skipped.append(msg)

    def approximate(self, msg: str) -> None:
        self.approximated.append(msg)

    def is_clean(self) -> bool:
        return not self.skipped and not self.approximated

    def summary_lines(self) -> list[str]:
        lines = [f'"{self.mat_name}":']
        for msg in self.approximated:
            lines.append("  [approximated] " + msg)
        for msg in self.skipped:
            lines.append("  [skipped] " + msg)
        if self.is_clean():
            lines.append("  fully converted, no skipped inputs")
        return lines


def _redshift_type_available() -> bool:
    """True if the Redshift plugin is loaded - `redshift_vopnet` creatable in ANY node type category, never assuming which one owns it."""
    for cat in hou.nodeTypeCategories().values():
        if hou.nodeType(cat, "redshift_vopnet") is not None:
            return True
    return False


def find_redshift_shader(vopnet: hou.Node) -> hou.Node | None:
    """The surface shader inside a reconstructed redshift_vopnet: what feeds the output node's Surface input, falling back to shaderball_scene.py's name scan when no output node or an unwired Surface."""
    for child in vopnet.children():
        if child.type().name() in material.REDSHIFT_TERMINALS:
            inputs = child.inputs()
            if inputs and inputs[0] is not None:
                tname = inputs[0].type().name()
                if "Material" in tname or "PBR" in tname:    # inputs() can return a compacted tuple (only displacement wired), where index 0 is not the Surface input at all - trust only what looks like a surface shader
                    return inputs[0]
            break
    for child in vopnet.children():
        tname = child.type().name()
        if tname in material.REDSHIFT_TERMINALS:
            continue
        if "Material" in tname or "PBR" in tname:
            return child
    return None


_UBER_CONVERTERS = {}    # Redshift material shader -> its converter; populated at the bottom once every converter it names exists, and convert_material_shader reading it is what lets a blended material recurse into its parts

STANDARD_MATERIAL_PARM_MAP = [    # redshift::StandardMaterial -> mtlxstandard_surface, verified against Houdini's own bxdf/standard_surface.mtlx nodedef; a wrong or missing name no-ops via _copy_constant_parm
    ("base_color", "base_color"),
    ("base_color_weight", "base"),
    ("diffuse_roughness", "diffuse_roughness"),
    ("metalness", "metalness"),
    ("refl_color", "specular_color"),
    ("refl_weight", "specular"),
    ("refl_roughness", "specular_roughness"),
    ("refl_ior", "specular_IOR"),
    ("refl_aniso", "specular_anisotropy"),
    ("refl_aniso_rotation", "specular_rotation"),
    ("refr_weight", "transmission"),
    ("refr_color", "transmission_color"),
    ("refr_roughness", "transmission_extra_roughness"),
    ("ms_amount", "subsurface"),
    ("ms_color", "subsurface_color"),
    ("ms_radius", "subsurface_radius"),
    ("ms_radius_scale", "subsurface_scale"),    # the radius is a DISTANCE and this its scalar multiplier - dropped, a converted subsurface material renders at scale 1 and washes out
    ("sheen_weight", "sheen"),
    ("sheen_color", "sheen_color"),
    ("sheen_roughness", "sheen_roughness"),
    ("coat_weight", "coat"),
    ("coat_color", "coat_color"),
    ("coat_roughness", "coat_roughness"),
    ("coat_ior", "coat_IOR"),
    ("coat_aniso", "coat_anisotropy"),
    ("coat_aniso_rotation", "coat_rotation"),
    ("emission_color", "emission_color"),    # thin film handled separately (gate + unit) by _convert_thin_film
    ("emission_weight", "emission"),
    ("opacity_color", "opacity"),
]


OPENPBR_MATERIAL_PARM_MAP = [    # redshift::OpenPBRMaterial (the spec's own names, read from a real saved .mat block) -> mtlxstandard_surface, kept consistent with the library's existing Karma materials; inputs handled elsewhere are in _OPENPBR_HANDLED_INPUTS
    ("base_weight", "base"),
    ("base_color", "base_color"),
    ("base_diffuse_roughness", "diffuse_roughness"),
    ("base_metalness", "metalness"),
    ("specular_weight", "specular"),
    ("specular_color", "specular_color"),
    ("specular_roughness", "specular_roughness"),
    ("specular_ior", "specular_IOR"),
    ("specular_roughness_anisotropy", "specular_anisotropy"),
    ("transmission_weight", "transmission"),
    ("transmission_color", "transmission_color"),
    ("transmission_depth", "transmission_depth"),
    ("transmission_scatter", "transmission_scatter"),
    ("transmission_scatter_anisotropy", "transmission_scatter_anisotropy"),
    ("transmission_dispersion_scale", "transmission_dispersion"),    # the vendor graph copies the WEIGHT, never the abbe number - mapping abbe (default 20) force-enabled visible dispersion on every converted transmissive material
    ("subsurface_weight", "subsurface"),
    ("subsurface_color", "subsurface_color"),
    ("subsurface_radius", "subsurface_scale"),    # crossed on purpose, matching the vendor graph: RS radius is a FLOAT distance and radius_scale a COLOR3 - straight-across collapsed the scatter colour to its red component
    ("subsurface_radius_scale", "subsurface_radius"),
    ("subsurface_scatter_anisotropy", "subsurface_anisotropy"),
    ("fuzz_weight", "sheen"),
    ("fuzz_color", "sheen_color"),
    ("fuzz_roughness", "sheen_roughness"),
    ("coat_weight", "coat"),
    ("coat_color", "coat_color"),
    ("coat_roughness", "coat_roughness"),
    ("coat_ior", "coat_IOR"),
    ("coat_roughness_anisotropy", "coat_anisotropy"),
    ("emission_color", "emission_color"),    # thin film handled separately (gate + unit) by _convert_thin_film
    ("emission_luminance", "emission"),    # OpenPBR emission is a luminance (nits), Standard Surface's a 0-1 weight - a direct copy is right for the common non-emissive case, and genuinely emissive materials are flagged in the report
    ("geometry_opacity", "opacity"),
]

CLASSIC_MATERIAL_PARM_MAP = [    # redshift::Material (the CLASSIC shader, predating StandardMaterial) -> mtlxstandard_surface, verified against the live plugin's own parameter list (Redshift 2026 / H21); the unmappable parms are reported via _CLASSIC_REPORT_ONLY, never guessed at
    ("diffuse_color", "base_color"),
    ("diffuse_weight", "base"),
    ("diffuse_roughness", "diffuse_roughness"),
    ("refl_color", "specular_color"),
    ("refl_weight", "specular"),
    ("refl_roughness", "specular_roughness"),
    ("refl_ior", "specular_IOR"),
    ("refl_metalness", "metalness"),
    ("refl_aniso", "specular_anisotropy"),
    ("refl_aniso_rotation", "specular_rotation"),
    ("sheen_color", "sheen_color"),
    ("sheen_weight", "sheen"),
    ("sheen_roughness", "sheen_roughness"),
    ("refr_color", "transmission_color"),
    ("refr_weight", "transmission"),
    ("refr_roughness", "transmission_extra_roughness"),
    ("refr_abbe", "transmission_dispersion"),
    ("refr_thin_walled", "thin_walled"),
    ("ms_amount", "subsurface"),    # the classic shader's multiple-scattering layer 1 is the closest single-layer equivalent - layers 2/3 are reported
    ("ms_color0", "subsurface_color"),
    ("ms_radius0", "subsurface_scale"),
    ("ms_radius_scale", "subsurface_radius"),
    ("coat_color", "coat_color"),
    ("coat_weight", "coat"),
    ("coat_roughness", "coat_roughness"),
    ("coat_ior", "coat_IOR"),
    ("emission_color", "emission_color"),
    ("emission_weight", "emission"),
    ("opacity_color", "opacity"),
]

_CLASSIC_HANDLED_INPUTS = {"bump_input"}    # classic-shader inputs handled outside the parm map

_CLASSIC_REPORT_ONLY = (    # classic parms whose non-default value changes the look but has no faithful Standard Surface target - reported so a conversion is never silently wrong
    ("transl_weight", 0.0, "back-lighting/translucency"),
    ("overall_color", (1.0, 1.0, 1.0), "the overall tint multiplier"),
    ("ms_weight1", 0.0, "subsurface layer 2"),
    ("ms_weight2", 0.0, "subsurface layer 3"),
    ("refr_transmittance", (1.0, 1.0, 1.0), "refraction transmittance"),
    ("refr_absorption_scale", 1.0, "absorption scale"),
    ("ss_amount", 0.0, "single-scatter subsurface"),
)

_OPENPBR_HANDLED_INPUTS = {
    "geometry_normal",
    "geometry_coat_normal",
    "geometry_tangent",
    "geometry_coat_tangent",
    "geometry_thin_walled",
    "bump_input",
}

def _convert_thin_film(rs_node: hou.Node, mtlx: hou.Node, report) -> None:
    """Redshift thin film, respecting the GATE and the UNIT a naive copy ignored - which baked a warm iridescent tint onto every converted metal (#179)."""
    def _v(name):
        p = rs_node.parm(name)
        try:
            return p.eval() if p is not None else None
        except hou.Error:
            return None

    def _put(name, value):
        p = mtlx.parm(name)
        if p is not None:
            try:
                p.set(value)
            except hou.Error:
                pass

    weight = _v("thin_film_weight")          # OpenPBR only: it gates thin film by weight (default 0), where mtlxstandard_surface has no gate - thickness > 0 switches it on
    if weight is not None:                    # -> this is an OpenPBR shader
        if weight > 1e-6:
            _put("thin_film_thickness", (_v("thin_film_thickness") or 0.0) * 1000.0)    # OpenPBR thickness is MICROMETRES, mtlx wants NANOMETRES
            ior = _v("thin_film_ior")
            if ior is not None:
                _put("thin_film_IOR", ior)
        return
    thickness_nm = _v("thinfilm_thickness")   # StandardMaterial: no weight parm (thickness > 0 IS the gate) and already in nanometres - straight across
    if thickness_nm is not None and thickness_nm > 1e-6:
        _put("thin_film_thickness", thickness_nm)
        ior = _v("thinfilm_ior")
        if ior is not None:
            _put("thin_film_IOR", ior)


def _copy_constant_parm(
    src_node: hou.Node, src_name: str, dst_node: hou.Node, dst_name: str
) -> None:
    """Copy a plain value across WIDTH-AWARE - the two shaders disagree on tuple widths, and a mismatched set() raises hou.InvalidSize (a hou.Error, which a ValueError clause misses): a scalar broadcasts, a vector collapses to its first component, anything still off no-ops."""
    src_parm = src_node.parmTuple(src_name)
    dst_parm = dst_node.parmTuple(dst_name)
    if src_parm is None or dst_parm is None:
        return
    try:
        src_vals = list(src_parm.eval())
        dst_len = len(dst_parm)
        if len(src_vals) != dst_len:
            if len(src_vals) == 1:
                src_vals = src_vals * dst_len          # scalar -> vector
            elif dst_len == 1:
                src_vals = src_vals[:1]                # vector -> scalar
            else:
                src_vals = (src_vals + [src_vals[-1]] * dst_len)[:dst_len]
        dst_parm.set(tuple(src_vals))
    except (hou.Error, TypeError, ValueError):
        pass


_UV_SCALE_TAG = "amaze_uv_scale"
_UV_SCALE_TAG_LEGACY = "matlib_uv_scale"    # the pre-rename tag, carried by saved archives converted before 2026-07-27 - the dedup check honours BOTH, new conversions write only the new one


def _named_inputs(node: hou.Node) -> dict:
    """{input_name: connected_node} for a VOP node, via the None-padded inputs()/inputNames() positional zip - padding confirmed against H21's own HOM docs; inputConnections() gave back nonsense for these node types and is avoided on purpose."""
    input_nodes = node.inputs()
    input_names = node.inputNames()
    result = {}
    for i, name in enumerate(input_names):
        if i < len(input_nodes) and input_nodes[i] is not None:
            result[name] = input_nodes[i]
    return result


def _effective_signature(node: hou.Node) -> str:
    """The signature the node is on NOW - wiring an input flips it, so it must be read after the connections are made, never assumed."""
    parm = node.parm("signature")
    if parm is None:
        return "default"
    try:
        return parm.evalAsString() or "default"
    except hou.Error:
        return "default"


def _set_poly_parm(node: hou.Node, base_name: str, values, signature: str) -> bool:
    """Set a parm on a signature-polymorphic MaterialX node (mtlxmultiply, mtlxremap, ...): one parm variant per signature with the tuple width to match, and after a signature switch the SUFFIXED variant is the one that renders - setting only the plain name succeeds silently while changing nothing visible. Nudges the signature parm first, then tries suffixed before plain."""
    if not isinstance(values, (tuple, list)):
        values = (values,)
    try:
        sig = node.parm("signature")
        if sig is not None:
            sig.set(signature)
    except hou.Error:
        pass
    for parm_name in (base_name + "_" + signature, base_name):
        parm = node.parmTuple(parm_name)
        if parm is None:
            continue
        vals = (tuple(float(v) for v in values) + (float(values[-1]),) * len(parm))[
            : len(parm)
        ]
        try:
            parm.set(vals)
            return True
        except (hou.Error, TypeError, ValueError):
            continue
    return False


def _set_multiply_in2(multiply: hou.Node, scale: tuple) -> bool:
    return _set_poly_parm(multiply, "in2", scale, "vector2")


def _get_or_create_uv_chain(
    dest_parent: hou.Node, scale: tuple, report: ConversionReport
) -> hou.Node:
    """UV chain for converted textures: one shared mtlxtexcoord per material feeding one mtlxmultiply per DISTINCT scale value - the common case is one multiply serving every image, which doubles as the dial that scales all the material's textures together."""
    tag = f"{scale[0]:.6g},{scale[1]:.6g}"    # the multiply records its scale in user data, and matching on THAT (not parm values, whose width varies by signature) is what makes reuse detection reliable
    for child in dest_parent.children():
        if (
            child.type().name() == "mtlxmultiply"
            and (child.userData(_UV_SCALE_TAG) == tag
                 or child.userData(_UV_SCALE_TAG_LEGACY) == tag)
        ):
            return child
    texcoord = None
    for child in dest_parent.children():
        if child.type().name() == "mtlxtexcoord":
            texcoord = child
            break
    if texcoord is None:
        texcoord = dest_parent.createNode("mtlxtexcoord")
    multiply = dest_parent.createNode("mtlxmultiply")
    multiply.setNamedInput("in1", texcoord, 0)
    multiply.setUserData(_UV_SCALE_TAG, tag)
    if not _set_multiply_in2(multiply, scale) and tuple(scale) != (1.0, 1.0):    # a failed set on a non-default scale renders at the wrong tiling - surfaced; on 1,1 it is harmless, in2 defaults to 1
        report.approximate(
            f"couldn't set UV scale {tag} on the texture-scale multiply - "
            "set its second input by hand"
        )
    return multiply


_COLOUR_INPUTS = frozenset({    # the standard-surface inputs that carry COLOUR (sRGB read, color3 signature); everything else a texture can feed is scalar DATA read Raw - the per-map colour-space rule, verified against SideFX's own StandardSurface .mtlx
    "base_color",
    "specular_color",
    "coat_color",
    "emission_color",
    "subsurface_color",
    "sheen_color",
    "transmission_color",
})


def _apply_image_colorspace(
    image_node: hou.Node, role: str, report: ConversionReport, label: str
) -> None:
    """Set an mtlximage's signature + colour space by semantic role - "color" (sRGB, color3), "data" (Raw, float) or "normal" (Raw, vector3); a texture read in the wrong space looks SUBTLY wrong, which is why it is forced rather than left to the node default."""
    if "image" not in image_node.type().name():
        return
    signature, colorspace = {
        "color": ("color3", "srgb_texture"),
        "data": ("default", "Raw"),
        "normal": ("vector3", "Raw"),
    }.get(role, ("color3", "srgb_texture"))
    for parm_name, value in (
        ("signature", signature),
        ("filecolorspace", colorspace),
    ):
        parm = image_node.parm(parm_name)
        if parm is None:
            continue
        try:
            parm.set(value)
        except hou.Error:
            report.approximate(
                f'{label}: could not set the texture {parm_name}={value} '
                "- it may be read in the wrong colour space"
            )


def convert_texture_sampler(
    rs_node: hou.Node,
    dest_parent: hou.Node,
    report: ConversionReport,
    target_input: str = "",
) -> hou.Node:
    """redshift::TextureSampler -> mtlximage plus the shared UV chain carrying the sampler's own `scale`; `target_input` picks the colour space per _COLOUR_INPUTS, and normal maps go through convert_bump_map, which sets Vector3/Raw itself."""
    mtlx = dest_parent.createNode("mtlximage")
    path_parm = rs_node.parm("tex0")
    if path_parm is not None:
        mtlx.parm("file").set(path_parm.unexpandedString())
    role = "color" if target_input in _COLOUR_INPUTS else "data"
    _apply_image_colorspace(mtlx, role, report, f'"{rs_node.name()}"')
    scale = (1.0, 1.0)
    scale_parm = rs_node.parmTuple("scale")
    if scale_parm is not None:
        try:
            vals = scale_parm.eval()
            if len(vals) >= 2:
                scale = (float(vals[0]), float(vals[1]))
            elif len(vals) == 1:
                scale = (float(vals[0]), float(vals[0]))
        except hou.Error:
            pass
    try:
        mtlx.setNamedInput(
            "texcoord", _get_or_create_uv_chain(dest_parent, scale, report), 0
        )
    except hou.OperationFailed:
        report.skip(
            f'"{rs_node.name()}": couldn\'t wire a texcoord node into its '
            "mtlximage - UVs may need connecting by hand"
        )
    return mtlx


def convert_maxon_noise(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
) -> hou.Node:
    """redshift::MaxonNoise -> a generic MaterialX fractal-noise stand-in: the Maxon library has no MaterialX equivalent, so every use is flagged as approximated, never claimed faithful."""
    position = dest_parent.createNode("mtlxposition")
    fractal = dest_parent.createNode("mtlxfractal3d")
    fractal.setNamedInput("position", position, 0)
    report.approximate(
        f'"{rs_node.name()}" (redshift::MaxonNoise) has no MaterialX equivalent - '
        "substituted a generic fractal noise; review visually, it will not match exactly"
    )
    return fractal


def convert_bump_map(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
) -> hou.Node | None:
    """The RS output node's "Bump Map" input -> mtlxnormalmap feeding the shader's normal input: the texture goes STRAIGHT into "in" with no conversion node between - library content wires real normal maps through BumpMap nodes whatever inputType says, so trusting it minted a nonsensical normal->normal conversion."""
    nm = dest_parent.createNode("mtlxnormalmap")
    if rs_node.type().name() == "redshift::BumpMap":
        tex_src = _named_inputs(rs_node).get("input")
        input_type = rs_node.parm("inputType")
        if input_type is not None and input_type.eval() == 1:    # scale copies ONLY when inputType says tangent-space normal - a height-style scale like 0.001 on a normal-map strength flattens it to nothing
            _copy_constant_parm(rs_node, "scale", nm, "scale")
    else:
        tex_src = rs_node    # something else wired straight into the output's Bump Map input
    if tex_src is None:
        report.skip(
            f'"{rs_node.name()}": bump map has no texture input to convert'
        )
        return nm
    converted = convert_node(tex_src, dest_parent, report)
    if converted is not None:    # a normal map is DATA: Vector3 + Raw, no sRGB transform - SideFX's own guidance and their chess_set .mtlx both say so
        _apply_image_colorspace(
            converted, "normal", report, f'"{rs_node.name()}"'
        )
        try:
            nm.setNamedInput("in", converted, 0)
        except hou.OperationFailed:
            report.skip(
                f'"{rs_node.name()}": converted bump texture couldn\'t be '
                "wired into mtlxnormalmap"
            )
    return nm


def convert_displacement(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
) -> hou.Node | None:
    """The RS output node's "Displacement" input -> mtlxdisplacement; redshift::Displacement takes its texture on `texMap` (confirmed from saved library data) and its Change Range remap is rebuilt as mtlxremap when in use."""
    disp = dest_parent.createNode("mtlxdisplacement")
    remap_values = None
    if rs_node.type().name() == "redshift::Displacement":
        _copy_constant_parm(rs_node, "scale", disp, "scale")
        ranges = {}
        for pname, default in (
            ("oldrange_min", 0.0),
            ("oldrange_max", 1.0),
            ("newrange_min", 0.0),
            ("newrange_max", 1.0),
        ):
            parm = rs_node.parm(pname)
            ranges[pname] = parm.eval() if parm is not None else default
        if any(
            abs(ranges[p] - d) > 1e-6
            for p, d in (
                ("oldrange_min", 0.0),
                ("oldrange_max", 1.0),
                ("newrange_min", 0.0),
                ("newrange_max", 1.0),
            )
        ):
            remap_values = ranges
        tex_src = _named_inputs(rs_node).get("texMap")
    else:
        tex_src = rs_node    # something else wired straight into the output's Displacement input - converted directly as the displacement source
    if tex_src is None:
        return disp
    converted = convert_node(tex_src, dest_parent, report)
    if converted is None:
        return disp
    if remap_values is not None:    # a non-default Change Range maps exactly onto mtlxremap (oldrange -> inlow/inhigh, newrange -> outlow/outhigh), inserted only when in use; a failed set falls back to the honest adjust-by-hand note
        remap = dest_parent.createNode("mtlxremap")
        ok = True
        for base, key in (
            ("inlow", "oldrange_min"),
            ("inhigh", "oldrange_max"),
            ("outlow", "newrange_min"),
            ("outhigh", "newrange_max"),
        ):
            ok = _set_poly_parm(remap, base, remap_values[key], "color3") and ok
        try:
            remap.setNamedInput("in", converted, 0)
            converted = remap
        except hou.OperationFailed:
            ok = False
        if not ok:
            report.approximate(
                f'"{rs_node.name()}" uses a Change Range remap that '
                "couldn't be fully rebuilt as mtlxremap - check the remap "
                "node's values (or displacement levels) by hand"
            )
    try:
        disp.setNamedInput("displacement", converted, 0)
    except hou.OperationFailed:
        report.skip(
            f'"{rs_node.name()}": converted displacement texture '
            "couldn't be wired into mtlxdisplacement"
        )
    return disp


_RAMP_MAPPING_OUTPUT = {"0": 1, "1": 0}  # RSRamp inputMapping -> the mtlxseparate2 output index that drives it (Vertical -> V = outy = 1, Horizontal -> U = outx = 0); menu values confirmed on the real parm
_RAMP_MAPPING_LABELS = {
    "0": "Vertical",
    "1": "Horizontal",
    "2": "Diagonal",
    "3": "Radial",
    "4": "Circular",
}


def _build_ramp_uv_driver(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
):
    """The value driving an RSRamp with nothing wired into `input`, rebuilt as mtlxtexcoord -> mtlxseparate2 -> the inputMapping channel, honouring inputInvert - without it the ramp reads flat. Returns (node, output_index), or None if the chain couldn't be built."""
    mapping = ""
    parm = rs_node.parm("inputMapping")
    if parm is not None:
        try:
            mapping = str(parm.eval())
        except hou.Error:
            mapping = ""
    out_index = _RAMP_MAPPING_OUTPUT.get(mapping)
    if out_index is None:
        report.approximate(
            f'"{rs_node.name()}" (RSRamp) uses a '
            f"{_RAMP_MAPPING_LABELS.get(mapping, mapping)} input mapping - "
            "MaterialX has no direct equivalent, so the ramp is driven by "
            "V instead; adjust by hand if it matters"
        )
        out_index = 1
    try:
        texcoord = dest_parent.createNode("mtlxtexcoord")
        separate = dest_parent.createNode("mtlxseparate2")
        separate.setNamedInput("in", texcoord, 0)
    except hou.Error:
        report.skip(
            f'"{rs_node.name()}" (RSRamp): could not build the UV driver - '
            "wire the ramp's input by hand"
        )
        return None
    driver, driver_out = separate, out_index
    invert = rs_node.parm("inputInvert")
    try:
        if invert is not None and invert.eval():
            inv = dest_parent.createNode("mtlxinvert")
            inv.setNamedInput("in", separate, out_index)
            driver, driver_out = inv, 0
    except hou.Error:
        report.approximate(
            f'"{rs_node.name()}" (RSRamp) has Invert Input enabled - it '
            "couldn't be reproduced; flip the ramp by hand"
        )
    return (driver, driver_out)


def convert_ramp(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
) -> hou.Node | None:
    """redshift::RSRamp -> kma_rampconst, the real Karma ramp node - t input drives the lookup, the gradient copies as a hou.Ramp onto vramp/framp with its colours intact. NOT hmtlxrampc: voptoolutils' KARMAMTLX_TAB_MASK excludes `^hmtlxramp*`, so Karma degrades it to a float evaluation - colour knots in, greyscale out; and kma_rampconst only exists inside a real Karma Material Builder, which is why the converter builds there (nodes.make_karma_builder)."""
    ramp = None
    src_parm = rs_node.parm("ramp")
    if src_parm is not None:
        try:
            ramp = src_parm.evalAsRamp()
        except hou.Error:
            ramp = None

    try:
        node = dest_parent.createNode("kma_rampconst")
    except hou.Error as exc:
        report.skip(
            f'"{rs_node.name()}" (RSRamp): the Karma ramp node could not '
            f"be created here ({exc}) - rebuild the ramp by hand"
        )
        return None

    is_color = True    # colour ramps live on "vramp", float ramps on "framp"
    if ramp is not None:
        try:
            values = ramp.values()
            if values:
                is_color = isinstance(values[0], (tuple, list))
        except hou.Error:
            pass
    if ramp is not None:
        target = "vramp" if is_color else "framp"
        parm = node.parm(target)
        if parm is not None:
            try:
                parm.set(ramp)
            except hou.Error:
                report.approximate(
                    f'"{rs_node.name()}" (RSRamp): the gradient could not '
                    "be copied - rebuild the ramp by hand"
                )
        try:
            if any(b != hou.rampBasis.Linear for b in ramp.basis()):    # both Houdini MaterialX ramp nodes are LINEAR-ONLY (SideFX docs for kma_rampconst and hmtlxrampc both say so)
                report.approximate(
                    f'"{rs_node.name()}" (RSRamp) uses non-linear knot '
                    "interpolation - the Karma ramp only supports Linear, "
                    "so the gradient is rebuilt as linear"
                )
        except (hou.Error, AttributeError):
            pass

    src_in = _named_inputs(rs_node).get("input")    # whatever drives the lookup: a wired input converts directly, otherwise the UV-derived driver chain - without one the ramp reads flat
    driver = None
    if src_in is not None:
        converted = convert_node(src_in, dest_parent, report)
        if converted is not None:
            driver = (converted, 0)
    else:
        driver = _build_ramp_uv_driver(rs_node, dest_parent, report)
    if driver is not None:
        try:
            node.setNamedInput("t", driver[0], driver[1])
        except hou.OperationFailed:
            report.skip(
                f'"{rs_node.name()}" (RSRamp): the driving value could not '
                "be wired into the ramp's t input"
            )
    else:
        report.approximate(
            f'"{rs_node.name()}" (RSRamp): nothing drives the gradient - '
            "wire the ramp's t input by hand or it reads flat"
        )

    source = rs_node.parm("inputSource")    # the "Alt" input source has no MaterialX equivalent; UV Map and Auto both mean the UV-driven chain above
    try:
        if source is not None and str(source.eval()) == "1":
            report.approximate(
                f'"{rs_node.name()}" (RSRamp) uses the "Alt" input source '
                "- no Karma equivalent, so it is driven by UV instead"
            )
    except hou.Error:
        pass
    return node


_LAYER_BLEND_NODES = {    # RSColorLayer blend mode -> the MaterialX node that performs it, every one shipping in H21 AND H22 (verified in both); modes with no equivalent are absent on purpose and reported
    "0": None,               # Normal - the layer colour itself
    "2": "mtlxplus",         # Add
    "3": "mtlxminus",        # Subtract
    "4": "mtlxmultiply",     # Multiply
    "5": "mtlxdifference",   # Difference
    "6": "mtlxmax",          # Lighten
    "7": "mtlxmin",          # Darken
    "8": "mtlxscreen",       # Screen
    "11": "mtlxburn",        # Burn
    "12": "mtlxdodge",       # Dodge
    "13": "mtlxoverlay",     # Overlay
    "15": "mtlxdivide",      # Divide
}

_LAYER_BLEND_UNSUPPORTED = {    # modes standard MaterialX has no node for - named in the report so the difference is visible instead of silent
    "1": "Average", "9": "Hardlight", "10": "Softlight",
    "14": "Exclusion",
}

_LAYER_COUNT = 7    # how many layers an RSColorLayer exposes


def _layer_input(node, name):
    """The node feeding a named input, or None."""
    return _named_inputs(node).get(name)


def _constant_color(parent, values, name="layer_color"):
    """A colour constant as a node, for feeding blend inputs."""
    const = parent.createNode("mtlxconstant", name)
    _set_poly_parm(const, "value", tuple(values)[:3], "color3")
    return const


def convert_color_layer(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport,
    target_input: str = "",
) -> hou.Node | None:
    """redshift::RSColorLayer -> a MaterialX blend chain, rebuilt literally: per layer the mode's blend node combines the running result with the layer colour and an mtlxmix folds it back by the mask; an inexpressible mode is reported and treated as Normal, the mode it degrades to most predictably."""
    current = _layer_input(rs_node, "base_color")
    if current is None:
        base = rs_node.parmTuple("base_color")
        current = _constant_color(
            dest_parent, base.eval() if base else (0.0, 0.0, 0.0),
            "base_color",
        )
    else:
        current = convert_node(current, dest_parent, report, target_input)
        if current is None:
            return None

    used = 0
    for index in range(1, _LAYER_COUNT + 1):
        enable = rs_node.parm("layer%d_enable" % index)
        if enable is None or not enable.eval():
            continue
        colour_src = _layer_input(rs_node, "layer%d_color" % index)
        if colour_src is not None:
            layer_node = convert_node(
                colour_src, dest_parent, report, target_input
            )
            if layer_node is None:
                report.skip(
                    "colour layer %d's input could not be converted - "
                    "the layer was dropped" % index
                )
                continue
        else:
            parm = rs_node.parmTuple("layer%d_color" % index)
            layer_node = _constant_color(
                dest_parent, parm.eval() if parm else (0.0, 0.0, 0.0),
                "layer%d_color" % index,
            )

        mode_parm = rs_node.parm("layer%d_blend_mode" % index)
        mode = str(mode_parm.eval()) if mode_parm is not None else "0"
        blended = layer_node
        if mode in _LAYER_BLEND_NODES and _LAYER_BLEND_NODES[mode]:
            blend = dest_parent.createNode(_LAYER_BLEND_NODES[mode])
            names = [n for n in blend.inputNames() if n]    # compositing nodes take (fg, bg), the math ones (in1, in2) - both mean layer over result here
            if "fg" in names and "bg" in names:
                blend.setNamedInput("fg", layer_node, 0)
                blend.setNamedInput("bg", current, 0)
            else:
                blend.setNamedInput(names[0], current, 0)
                blend.setNamedInput(names[1], layer_node, 0)
            blended = blend
        elif mode in _LAYER_BLEND_UNSUPPORTED:
            report.skip(
                'colour layer %d uses blend mode "%s", which MaterialX '
                "has no node for - converted as Normal"
                % (index, _LAYER_BLEND_UNSUPPORTED[mode])
            )

        mask_src = _layer_input(rs_node, "layer%d_mask" % index)
        mask_parm = rs_node.parm("layer%d_mask" % index)
        mask_value = float(mask_parm.eval()) if mask_parm is not None else 1.0
        if mask_src is None and mask_value >= 0.999:
            current = blended          # fully opaque layer - no mix
        else:
            mix = dest_parent.createNode("mtlxmix")
            mix.setNamedInput("fg", blended, 0)
            mix.setNamedInput("bg", current, 0)
            if mask_src is not None:
                converted_mask = convert_node(
                    mask_src, dest_parent, report, ""
                )
                if converted_mask is not None:
                    mix.setNamedInput("mix", converted_mask, 0)
            else:
                mix_parm = mix.parm("mix")
                if mix_parm is not None:
                    mix_parm.set(mask_value)
            current = mix
        used += 1

    debug.event("convert", "colour layer", node=rs_node.path(),
                layers=used)
    return current


def convert_fresnel(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport,
    target_input: str = "",
) -> hou.Node | None:
    """redshift::Fresnel -> a MaterialX facing-ratio blend, the term rebuilt rather than approximated by a constant: with an IOR the Schlick form F = F0 + (1-F0)(1-cos)^5, F0 = ((ior-1)/(ior+1))^2, and in curve-falloff mode the exponent is the node's own curve value."""
    facing = rs_node.parmTuple("facing_color")
    perp = rs_node.parmTuple("perp_color")
    facing_node = _layer_input(rs_node, "facing_color")
    perp_node = _layer_input(rs_node, "perp_color")
    facing_node = (
        convert_node(facing_node, dest_parent, report, target_input)
        if facing_node is not None else
        _constant_color(dest_parent,
                        facing.eval() if facing else (0.0, 0.0, 0.0),
                        "fresnel_facing")
    )
    perp_node = (
        convert_node(perp_node, dest_parent, report, target_input)
        if perp_node is not None else
        _constant_color(dest_parent,
                        perp.eval() if perp else (1.0, 1.0, 1.0),
                        "fresnel_perp")
    )
    if facing_node is None or perp_node is None:
        return None

    ratio = dest_parent.createNode("mtlxfacingratio")
    inverted = dest_parent.createNode("mtlxsubtract")    # 1 - facingratio: the Fresnel term rises toward grazing angles
    in1 = inverted.parm("in1")
    if in1 is not None:
        in1.set(1.0)
    inverted.setNamedInput("in2", ratio, 0)

    use_ior = rs_node.parm("fresnel_useior")
    curve = rs_node.parm("user_curve")
    exponent = 5.0
    if use_ior is not None and not use_ior.eval() and curve is not None:
        exponent = max(float(curve.eval()), 0.001)
    power = dest_parent.createNode("mtlxpower")
    power.setNamedInput("in1", inverted, 0)
    in2 = power.parm("in2")
    if in2 is not None:
        in2.set(exponent)

    term = power
    if use_ior is None or use_ior.eval():
        ior_parm = rs_node.parm("ior")
        ior = float(ior_parm.eval()) if ior_parm is not None else 1.4
        f0 = ((ior - 1.0) / (ior + 1.0)) ** 2 if ior + 1.0 else 0.04
        scaled = dest_parent.createNode("mtlxmultiply")    # F = F0 + (1 - F0) * (1 - cos)^exponent
        scaled.setNamedInput("in1", power, 0)
        scaled_in2 = scaled.parm("in2")
        if scaled_in2 is not None:
            scaled_in2.set(1.0 - f0)
        biased = dest_parent.createNode("mtlxadd")
        biased.setNamedInput("in1", scaled, 0)
        biased_in2 = biased.parm("in2")
        if biased_in2 is not None:
            biased_in2.set(f0)
        term = biased
        if rs_node.parm("extinction_coeff") is not None and \
                float(rs_node.parm("extinction_coeff").eval()) > 0:
            report.skip(
                "the Fresnel node's extinction coefficient (metallic "
                "medium) has no MaterialX facing-ratio equivalent"
            )

    mix = dest_parent.createNode("mtlxmix")
    mix.setNamedInput("fg", perp_node, 0)    # at grazing (term -> 1) the perpendicular colour wins
    mix.setNamedInput("bg", facing_node, 0)
    mix.setNamedInput("mix", term, 0)
    debug.event("convert", "fresnel", node=rs_node.path(),
                mode="ior" if (use_ior is None or use_ior.eval()) else "curve")
    return mix


def convert_math_range(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport,
    target_input: str = "",
) -> hou.Node | None:
    """redshift::RSMathRange -> mtlxremap one-to-one (input/old/new ranges onto in/inlow/inhigh/outlow/outhigh); Redshift clamps by default and MaterialX's remap does not, so a clamp is appended when it is on."""
    remap = dest_parent.createNode("mtlxremap")
    pairs = (
        ("input", "in"), ("old_min", "inlow"), ("old_max", "inhigh"),
        ("new_min", "outlow"), ("new_max", "outhigh"),
    )
    inputs = _named_inputs(rs_node)
    for rs_name, mtlx_name in pairs:    # wiring FIRST, values after: a wired colour source flips the remap's signature, and the values must land on the variant that renders
        src = inputs.get(rs_name)
        if src is None:
            continue
        converted = convert_node(src, dest_parent, report, target_input)
        if converted is not None:
            try:
                remap.setNamedInput(mtlx_name, converted, 0)
            except hou.OperationFailed:
                pass
    signature = _effective_signature(remap)
    for rs_name, mtlx_name in pairs:
        if rs_name in inputs:
            continue
        parm = rs_node.parm(rs_name)
        if parm is not None:
            try:
                _set_poly_parm(remap, mtlx_name, float(parm.eval()),
                               signature)
            except hou.Error:
                pass
    result = remap
    clamp_parm = rs_node.parm("clamp")
    if clamp_parm is not None and clamp_parm.eval():
        clamp = dest_parent.createNode("mtlxclamp")
        clamp.setNamedInput("in", remap, 0)
        signature = _effective_signature(clamp)
        new_min, new_max = rs_node.parm("new_min"), rs_node.parm("new_max")
        if new_min is not None:
            _set_poly_parm(clamp, "low", float(new_min.eval()), signature)
        if new_max is not None:
            _set_poly_parm(clamp, "high", float(new_max.eval()), signature)
        result = clamp
    return result


NODE_CONVERTERS = {
    "redshift::RSMathRange": convert_math_range,
    "redshift::RSColorLayer": convert_color_layer,
    "redshift::Fresnel": convert_fresnel,
    "redshift::TextureSampler": convert_texture_sampler,
    "redshift::MaxonNoise": convert_maxon_noise,
    "redshift::RSRamp": convert_ramp,
}


def convert_node(
    rs_node: hou.Node,
    dest_parent: hou.Node,
    report: ConversionReport,
    target_input: str = "",
) -> hou.Node | None:
    """Dispatch one connected input node to its converter, or report it as unsupported - None on no mapping, and callers leave the destination unwired rather than crash. `target_input` (the standard-surface input the result will feed) goes to EVERY converter whose signature declares it, read from the signature so nested samplers keep their colour-space hint."""
    conv = NODE_CONVERTERS.get(rs_node.type().name())
    if conv is None:
        report.skip(
            _UNCONVERTIBLE_INPUTS.get(rs_node.type().name())
            or (
                f'"{rs_node.name()}" ({rs_node.type().name()}) has no '
                "conversion mapping yet - left at the MaterialX default"
            )
        )
        return None
    if "target_input" in inspect.signature(conv).parameters:
        return conv(rs_node, dest_parent, report, target_input)
    return conv(rs_node, dest_parent, report)


_UNCONVERTIBLE_INPUTS = {    # upstream nodes whose lack of a MaterialX equivalent is a PROPERTY, not a gap to close later - each with the reason in the user's terms; anything absent falls back to the generic no-mapping-yet skip
    "redshift::Flakes":
        "the metallic-flake generator (car paint) perturbs the "
        "specular normal with its own procedural flake distribution - "
        "MaterialX has no equivalent, and approximating it with noise "
        "would invent a different look rather than convert this one",
    "redshift::rsOSL":
        "an OSL node - its behaviour lives in shader source code, "
        "which has no parameter-level equivalent to convert",
    "redshift::RSShaderSwitch":
        "a shader switch selects between whole networks at render "
        "time; MaterialX has no runtime switch, so the chosen branch "
        "would have to be baked in by hand",
    "redshift::RaySwitch":
        "a ray switch feeds different shading to camera, reflection "
        "and refraction rays - MaterialX shades one way for all rays",
    "redshift::CameraMap":
        "camera-projected mapping depends on a scene camera, which a "
        "material-level MaterialX graph cannot reference",
    "redshift::WireFrame":
        "wireframe shading needs primitive-edge data MaterialX does "
        "not expose",
}


_OUT_OF_SCOPE_SHADERS = {    # Redshift shaders that are NOT surface materials - a conversion attempt would fail or invent a look, so each is refused with the reason; measured across a 400-material library these are the bulk of what cannot convert
    "redshift::ToonMaterial":
        "a non-photorealistic Toon material - MaterialX Standard "
        "Surface has no cel/outline model, so there is nothing "
        "faithful to convert it to",
    "redshift::Hair2":
        "a hair shader - Standard Surface has no hair BSDF (Karma's "
        "own kma_fur would be the target, not standard_surface)",
    "redshift::Volume":
        "a volume shader - this converter handles surfaces only",
    "redshift::rsOSL":
        "an OSL shader - its behaviour lives in shader code, which "
        "has no parameter-level equivalent",
    "redshift::AmbientOcclusion":
        "an ambient-occlusion utility shader, not a surface material",
    "redshift::Sprite":
        "a sprite/cutout shader, not a surface material",
    "redshift::Flakes":
        "a procedural metallic-flake generator (car paint) - it "
        "perturbs the specular normal with its own flake distribution, "
        "which MaterialX has no node for; approximating it with noise "
        "would invent a different look rather than convert this one",
}


def out_of_scope_reason(vopnet: hou.Node) -> str:
    """When no convertible surface terminal was found: the reason in the user's terms, derived from what the network actually contains - empty when it holds nothing recognisable."""
    present = {c.type().name() for c in vopnet.allSubChildren()}
    for type_name, reason in _OUT_OF_SCOPE_SHADERS.items():
        if type_name in present:
            return reason
    return ""


def convert_classic_material(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
) -> hou.Node:
    """redshift::Material (the classic Redshift shader) -> mtlxstandard_surface."""
    mtlx = _convert_uber_shader(
        rs_node, dest_parent, report,
        CLASSIC_MATERIAL_PARM_MAP, _CLASSIC_HANDLED_INPUTS,
    )
    if mtlx is None:
        return mtlx
    for parm_name, default, what in _CLASSIC_REPORT_ONLY:
        parm = rs_node.parmTuple(parm_name)
        if parm is None:
            continue
        try:
            value = parm.eval()
        except hou.Error:
            continue
        expected = default if isinstance(default, tuple) else (default,)
        if tuple(round(float(v), 4) for v in value) != tuple(
                round(float(v), 4) for v in expected):
            report.skip(
                '"%s" is set (%s) - %s has no Standard Surface '
                "equivalent and was not converted"
                % (parm_name, ", ".join("%.3g" % float(v) for v in value),
                   what)
            )
    for parm_name, default, what in (    # Fresnel/BRDF modes change the specular response - only the default combination maps 1:1 onto Standard Surface's GGX + IOR model
        ("refl_fresnel_mode", "3", "reflection Fresnel mode"),
        ("refl_brdf", "0", "reflection BRDF"),
        ("coat_brdf", "0", "coat BRDF"),
    ):
        parm = rs_node.parm(parm_name)
        if parm is not None and str(parm.eval()) != default:
            report.skip(
                '"%s" is not the default - %s cannot be reproduced '
                "exactly by Standard Surface's GGX model"
                % (parm_name, what)
            )
    return mtlx


def _apply_glossiness_inversion(rs_node, mtlx, report) -> None:
    """Redshift's *_isGlossiness toggles make a roughness parm carry GLOSSINESS (1-roughness) - copied raw, a glossiness-workflow material converts INVERTED, shiny reads matte. Verified on the live plugin, all three default off."""
    for toggle, mtlx_name in (
        ("refl_isGlossiness", "specular_roughness"),
        ("coat_isGlossiness", "coat_roughness"),
        ("refr_isGlossiness", "transmission_extra_roughness"),
    ):
        parm = rs_node.parm(toggle)
        if parm is None or not parm.eval():
            continue
        target = mtlx.parm(mtlx_name)
        if target is None:
            continue
        index = _input_index(mtlx, mtlx_name)
        if index >= 0 and mtlx.input(index) is not None:
            report.skip(
                '"%s" is on and "%s" is textured - the glossiness->'
                "roughness inversion was NOT applied to the texture"
                % (toggle, mtlx_name)
            )
            continue
        try:
            target.set(max(0.0, 1.0 - float(target.eval())))
            report.approximate('"%s" was on - "%s" inverted to roughness'
                        % (toggle, mtlx_name))
        except hou.Error:
            pass


def _input_index(node, name) -> int:
    try:
        return list(node.inputNames()).index(name)
    except (ValueError, hou.Error):
        return -1


def _apply_vendor_transforms(rs_node, mtlx, report) -> None:
    """The two non-linear transforms SideFX's own translation graph applies that a straight copy omits (open_pbr_to_standard_surface.mtlx): sheen roughness = fuzz_roughness^2.5, and specular roughness mixed toward coat_roughness by coat weight - constants only, a textured input is reported instead of baked."""
    sheen = mtlx.parm("sheen_roughness")
    if sheen is not None and _input_index(mtlx, "sheen_roughness") >= 0 \
            and mtlx.input(_input_index(mtlx, "sheen_roughness")) is None:
        try:
            value = float(sheen.eval())
            if value > 0:
                sheen.set(value ** 2.5)
        except hou.Error:
            pass
    coat_weight = mtlx.parm("coat")
    spec_rough = mtlx.parm("specular_roughness")
    coat_rough = mtlx.parm("coat_roughness")
    if None in (coat_weight, spec_rough, coat_rough):
        return
    try:
        weight = float(coat_weight.eval())
        if weight <= 0:
            return
        if mtlx.input(_input_index(mtlx, "specular_roughness")) is not None:
            report.skip(
                "specular roughness is textured, so the coated-material "
                "roughness mix SideFX's translation applies was skipped"
            )
            return
        mixed = (1.0 - weight) * float(spec_rough.eval()) \
            + weight * float(coat_rough.eval())
        spec_rough.set(mixed)
        report.approximate(
            "specular roughness mixed toward coat roughness by coat "
            "weight %.3g (matching SideFX's own translation graph)" % weight
        )
    except hou.Error:
        pass


def convert_standard_material(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
) -> hou.Node:
    """redshift::StandardMaterial -> mtlxstandard_surface."""
    return _convert_uber_shader(
        rs_node, dest_parent, report,
        STANDARD_MATERIAL_PARM_MAP, {"bump_input"},
    )


def convert_openpbr_material(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
) -> hou.Node:
    """redshift::OpenPBRMaterial -> mtlxstandard_surface, the spec's parm names translated per OPENPBR_MATERIAL_PARM_MAP."""
    return _convert_uber_shader(
        rs_node, dest_parent, report,
        OPENPBR_MATERIAL_PARM_MAP, _OPENPBR_HANDLED_INPUTS,
        vendor_transforms=True,
    )


def convert_color_correction(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport,
    target_input: str = "",
) -> hou.Node | None:
    """redshift::RSColorCorrection -> mtlxhsvadjust (amount = [hue shift, saturation gain, value gain]) + mtlxcontrast + mtlxrange's gamma; only contrast needs interpreting - Redshift's neutral is 0.5 where MaterialX's is amount 1.0 around a 0.5 pivot - so it maps linearly and is REPORTED as approximated."""
    source = _named_inputs(rs_node).get("input")
    if source is not None:
        current = convert_node(source, dest_parent, report, target_input)
        if current is None:
            return None
    else:
        parm = rs_node.parmTuple("input")
        current = _constant_color(
            dest_parent, parm.eval() if parm else (0.0, 0.0, 0.0),
            "correction_input",
        )

    def _value(name, default):
        parm = rs_node.parm(name)
        try:
            return float(parm.eval()) if parm is not None else default
        except hou.Error:
            return default

    hue = _value("hue", 0.0)
    saturation = _value("saturation", 1.0)
    level = _value("level", 1.0)
    if (hue, saturation, level) != (0.0, 1.0, 1.0):
        hsv = dest_parent.createNode("mtlxhsvadjust")
        hsv.setNamedInput("in", current, 0)
        _set_poly_parm(hsv, "amount", (hue, saturation, level), "vector3")
        current = hsv

    contrast = _value("contrast", 0.5)
    if abs(contrast - 0.5) > 1e-4:
        node = dest_parent.createNode("mtlxcontrast")
        node.setNamedInput("in", current, 0)
        amount = node.parm("amount")
        pivot = node.parm("pivot")
        if amount is not None:
            amount.set(contrast * 2.0)
        if pivot is not None:
            pivot.set(0.5)
        report.approximate(
            "colour-correction contrast %.3g mapped onto MaterialX's "
            "contrast around a 0.5 pivot - the two curves are not "
            "identical" % contrast
        )
        current = node

    gamma = _value("gamma", 1.0)
    if abs(gamma - 1.0) > 1e-4:
        node = dest_parent.createNode("mtlxrange")
        node.setNamedInput("in", current, 0)
        gamma_parm = node.parm("gamma")
        if gamma_parm is not None:
            gamma_parm.set(gamma)
        current = node
    return current


def convert_particle_attribute(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport,
    target_input: str = "",
) -> hou.Node | None:
    """redshift::ParticleAttributeLookup -> mtlxgeompropvalue: both read a named geometry attribute at shading time, so the name carries straight across."""
    attribute = rs_node.parm("attribute")
    name = str(attribute.eval()).strip() if attribute is not None else ""
    if not name:
        report.skip(
            "a particle-attribute lookup has no attribute name set"
        )
        return None
    lookup = dest_parent.createNode("mtlxgeompropvalue")
    signature = lookup.parm("signature")    # colour attributes read as colour; anything else as float, which is what the remaining lookups in practice are (pscale, age, id)
    if signature is not None:
        try:
            signature.set("color3" if name in ("Cd", "diffuse") else "default")
        except hou.Error:
            pass
    prop = lookup.parm("geomprop")
    if prop is not None:
        prop.set(name)
    report.approximate(
        'particle attribute "%s" reads through mtlxgeompropvalue - it '
        "resolves only where the geometry actually carries that "
        "attribute" % name
    )
    return lookup


def convert_material_shader(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
) -> hou.Node | None:
    """Any Redshift MATERIAL node -> its MaterialX equivalent: the three uber shaders convert directly, and the blender/layer nodes recurse through here per combined material, so a blend of blends converts as deeply as it nests."""
    type_name = rs_node.type().name()
    converter = _UBER_CONVERTERS.get(type_name)
    if converter is not None:
        return converter(rs_node, dest_parent, report)
    if type_name in ("redshift::MaterialBlender", "redshift::MaterialLayer"):
        return convert_material_blend(rs_node, dest_parent, report)
    report.skip(
        "%s feeds a material blend but has no conversion mapping"
        % type_name
    )
    return None


def _blend_weight(rs_node, input_name, parm_name, dest_parent, report):
    """A blend mask as the FLOAT mtlxmix wants: Redshift blends by a COLOUR, so a connected one reduces through mtlxluminance and a constant by its own luminance - reported when not grey, which is where the two models part."""
    src = _named_inputs(rs_node).get(input_name)
    if src is not None:
        converted = convert_node(src, dest_parent, report, "")
        if converted is None:
            return None, 1.0
        lum = dest_parent.createNode("mtlxluminance")
        lum.setNamedInput("in", converted, 0)
        return lum, None
    parm = rs_node.parmTuple(parm_name)
    values = tuple(float(v) for v in parm.eval())[:3] if parm else (1.0,)
    if len(values) == 3:
        if max(values) - min(values) > 0.01:
            report.approximate(
                'blend colour "%s" is not grey (%s) - MaterialX mixes '
                "surfaces by a single weight, so its luminance was used"
                % (parm_name, ", ".join("%.2g" % v for v in values))
            )
        weight = 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]
    else:
        weight = values[0] if values else 1.0
    return None, weight


def convert_material_blend(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport,
    target_input: str = "",
) -> hou.Node | None:
    """redshift::MaterialBlender / redshift::MaterialLayer -> a chain of mtlxmix nodes over converted materials - mtlxmix mixes SURFACES natively (verified in both Houdini versions); additive layers are reported, since the surface mix interpolates and does not sum."""
    inputs = _named_inputs(rs_node)
    base_src = inputs.get("baseColor")
    if base_src is None:
        report.skip(
            "a material blend has no base material connected - nothing "
            "to convert"
        )
        return None
    current = convert_material_shader(base_src, dest_parent, report)
    if current is None:
        return None

    is_layer = rs_node.type().name() == "redshift::MaterialLayer"
    layers = (("layerColor", "layerMask", ""),) if is_layer else tuple(
        ("layerColor%d" % i, "blendColor%d" % i, "additiveMode%d" % i)
        for i in range(1, 7)
    )
    blended = 0
    for layer_input, blend_input, additive_parm in layers:
        layer_src = inputs.get(layer_input)
        if layer_src is None:
            continue
        layer_shader = convert_material_shader(
            layer_src, dest_parent, report
        )
        if layer_shader is None:
            continue
        weight_node, weight_value = _blend_weight(
            rs_node, blend_input, blend_input, dest_parent, report
        )
        if additive_parm:
            additive = rs_node.parm(additive_parm)
            if additive is not None and additive.eval():
                report.approximate(
                    "layer %s is ADDITIVE - MaterialX's surface mix "
                    "interpolates rather than sums, so it converted as "
                    "a blend" % layer_input
                )
        mix = dest_parent.createNode("mtlxmix")
        try:
            mix.setNamedInput("fg", layer_shader, 0)
            mix.setNamedInput("bg", current, 0)
        except hou.OperationFailed as exc:
            report.skip("could not mix material layer %s (%s)"
                        % (layer_input, exc))
            continue
        if weight_node is not None:
            mix.setNamedInput("mix", weight_node, 0)
        else:
            mix_parm = mix.parm("mix")
            if mix_parm is not None:
                mix_parm.set(max(0.0, min(1.0, float(weight_value))))
        current = mix
        blended += 1
    debug.event("convert", "material blend", node=rs_node.path(),
                layers=blended)
    if not blended:
        report.approximate(
            "a material blend had no convertible layers - only its base "
            "material was converted"
        )
    return current


def _convert_uber_shader(
    rs_node: hou.Node,
    dest_parent: hou.Node,
    report: ConversionReport,
    parm_map: list,
    handled_inputs: set,
    vendor_transforms: bool = False,
) -> hou.Node:
    """Build the mtlxstandard_surface equivalent of rs_node using parm_map: a mapped input with a live connection converts recursively, otherwise the constant copies across; handled_inputs are connected inputs dealt with elsewhere, so they are not reported as unmapped. vendor_transforms is OpenPBR's alone - its fuzz curve applied to Standard/classic sheen silently rewrites a value the 1:1 map copied correctly."""
    mtlx = dest_parent.createNode("mtlxstandard_surface")
    name_to_node = _named_inputs(rs_node)    # NOT inputConnections(): its outputNode() reported rs_node itself with output-sounding names for this node type; and the output index everywhere below is hardcoded 0, the primary output every proven wiring call in this codebase assumes
    debug.event("convert", "shader connected inputs",
                node=rs_node.path(), inputs=list(name_to_node.keys()))
    for rs_name, mtlx_name in parm_map:
        src_node = name_to_node.get(rs_name)
        if src_node is None:
            _copy_constant_parm(rs_node, rs_name, mtlx, mtlx_name)
            continue
        converted = convert_node(src_node, dest_parent, report, mtlx_name)
        if converted is not None:
            try:
                mtlx.setNamedInput(mtlx_name, converted, 0)
            except hou.OperationFailed:
                report.skip(
                    f'"{rs_name}" -> "{mtlx_name}": conversion built '
                    "successfully but couldn't be wired to the shader input"
                )
    mapped = {rs_name for rs_name, _ in parm_map}    # a connected input the map does not cover is REPORTED - the skip notes above fire only for mapped inputs, and a live connection once converted to nothing silently
    for name in name_to_node:
        if name in mapped or name in handled_inputs:
            continue
        report.skip(
            f'shader input "{name}" is connected but has no conversion '
            "mapping yet - left at the MaterialX default"
        )
    _convert_thin_film(rs_node, mtlx, report)    # fidelity passes shared by every Redshift uber shader, verified against the vendor translation graph and the live plugin's own parameters
    _apply_glossiness_inversion(rs_node, mtlx, report)
    if vendor_transforms:
        _apply_vendor_transforms(rs_node, mtlx, report)
    return mtlx


def convert_redshift_material(
    node_handler,
    source_mat,
    prefs_dir_parent: hou.Node,
) -> tuple[hou.Node | None, ConversionReport]:
    """Reconstruct source_mat at a scratch location, convert its shader network, and return (shader, displacement, report) - the SAME adapter API as the online translator, so the engine wires each into the builder's own terminal; an unhandled shader type is reported and skipped, returning (None, None, report)."""
    report = ConversionReport(source_mat.name)
    debug.event("convert", "start", material=source_mat.name,
                renderer=source_mat.renderer, mat_id=source_mat.mat_id)

    if not _redshift_type_available():    # preflight: reconstruction needs the Redshift plugin loaded, or createNode("redshift_vopnet") raises `Invalid node type name` mid-way - a cryptic crash reported clearly here instead
        report.skip(
            "Redshift isn't loaded this session, so the source material "
            "can't be read (the converter reconstructs the Redshift "
            "network to read its parameters). Load Redshift and retry - "
            "check the Houdini/Redshift plugin versions match."
        )
        return None, None, report

    with hou.undos.disabler():    # off the undo stack at BOTH ends: a create/destroy pair on the live stack resurrects the scratch with the whole reconstructed copy on one Ctrl+Z (#278)
        scratch = hou.node("/obj").createNode("matnet")
    try:
        node_handler._hou_parent = scratch
        node_handler._import_path = scratch
        node_handler._use_existing_node = True

        iface_path = material.payload_path(
            node_handler._preferences, source_mat.mat_id, ".interface"
        )
        node_handler.load_interface_other(iface_path, source_mat, "redshift_vopnet")
        node_handler.load_items_file(source_mat, move_builder=True)
        vopnet = node_handler.builder_node

        shader = find_redshift_shader(vopnet)
        if shader is None:
            reason = out_of_scope_reason(vopnet)
            report.skip(
                reason or "no surface shader node found inside the "
                "saved network"
            )
            return None, None, report
        shader_type = shader.type().name()
        if shader_type == "redshift::StandardMaterial":
            mtlx = convert_standard_material(shader, prefs_dir_parent, report)
        elif shader_type == "redshift::OpenPBRMaterial":
            mtlx = convert_openpbr_material(shader, prefs_dir_parent, report)
        elif shader_type == "redshift::Material":
            mtlx = convert_classic_material(shader, prefs_dir_parent, report)
        elif shader_type in ("redshift::MaterialBlender",
                             "redshift::MaterialLayer"):
            mtlx = convert_material_blend(shader, prefs_dir_parent, report)
        elif shader_type in _OUT_OF_SCOPE_SHADERS:
            report.skip(_OUT_OF_SCOPE_SHADERS[shader_type])
            return None, None, report
        else:
            report.skip(
                f"shader is {shader_type}, which has no conversion "
                "mapping yet"
            )
            return None, None, report

        out_node = None    # bump and displacement live on the redshift_material OUTPUT node's own named inputs, never on the shader - walked from there
        for child in vopnet.children():
            if child.type().name() in material.REDSHIFT_TERMINALS:
                out_node = child
                break
        out_inputs = _named_inputs(out_node) if out_node is not None else {}
        shader_inputs = _named_inputs(shader)    # bump arrives THREE ways - the shader's bump_input (StandardMaterial), its geometry_normal (OpenPBR), or the output node's bump input, asked by ROLE because the classic and USD forms spell it differently (material.TERMINAL_INPUTS); shader-level wins when both exist
        bump_src = (
            shader_inputs.get("geometry_normal")
            or shader_inputs.get("bump_input")
            or material.terminal_input(out_inputs, "bump")
        )
        if bump_src is not None:
            nm = convert_bump_map(bump_src, prefs_dir_parent, report)
            if nm is not None:
                try:
                    mtlx.setNamedInput("normal", nm, 0)
                except hou.OperationFailed:
                    report.skip(
                        "converted bump couldn't be wired to the "
                        "shader's normal input"
                    )
        mtlx_disp = None
        if out_node is not None:
            disp_src = material.terminal_input(out_inputs, "displacement")
            if disp_src is not None:
                mtlx_disp = convert_displacement(disp_src, prefs_dir_parent, report)

        mtlx.setName(
            helpers.sanitize_usd_path(source_mat.name), unique_name=True    # sanitized with the import path's own helper - library names carry spaces/dashes a node name cannot, and an unsanitized setName() aborts the whole conversion
        )
        return mtlx, mtlx_disp, report    # NOT bundled through a collect node: the KARMA_REF subnetconnector builder's surface terminal refuses a collect's output (hou.InvalidInput), and displacement saves as part of the whole builder now
    finally:
        with hou.undos.disabler():
            scratch.destroy()    # the reconstructed copy is scratch scaffolding for reading values, never left in the scene


NODE_CONVERTERS.update({    # registered here, not in the literal above: these converters lean on the material entry point, so the table completes once everything it names exists
    "redshift::RSColorCorrection": convert_color_correction,
    "redshift::ParticleAttributeLookup": convert_particle_attribute,
})

_UBER_CONVERTERS.update({
    "redshift::StandardMaterial": convert_standard_material,
    "redshift::OpenPBRMaterial": convert_openpbr_material,
    "redshift::Material": convert_classic_material,
})
