"""Redshift -> Karma/MaterialX material conversion (test/v0).

Best-effort node-graph translation, not a faithful 1:1 transpiler - no
converter can reproduce every Redshift shading feature in MaterialX, and
this doesn't try to. It walks a reconstructed Redshift material's shading
network and rebuilds the closest MaterialX equivalent it can find,
node type by node type. Anything without a mapping (custom OSL, Toon
shading, most of Redshift's procedural utility nodes - RSRamp,
RSColorLayer, RSMathRange, etc.) is left unconverted and reported, never
silently dropped or guessed at - the caller decides what to do with a
partial result.

Maxon Noise (redshift::MaxonNoise) specifically has no MaterialX
equivalent at all - it's a large proprietary noise library (Alligator,
Displaced Turbulence, Wavy Turbulence, ...) with dozens of algorithms;
MaterialX's own noise nodes are a much smaller standard set (Perlin-family
noise3d, cellnoise3d, worleynoise3d, fractal3d). convert_maxon_noise()
substitutes a generic MaterialX fractal noise as a stand-in - it will not
look identical, and every use is flagged in the ConversionReport so that's
never mistaken for a faithful reproduction.
"""

import inspect

import hou

from amaze.core import debug
from amaze.core import material

from amaze.helpers import helpers


class ConversionReport:
    """Collects what happened during a single material's conversion, so
    the caller can show the user an honest summary instead of a bare
    pass/fail."""

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
    """True if the Redshift plugin is loaded (redshift_vopnet is a
    creatable node type). Category-agnostic - scans all node type
    categories rather than assuming which one owns it."""
    for cat in hou.nodeTypeCategories().values():
        if hou.nodeType(cat, "redshift_vopnet") is not None:
            return True
    return False


def find_redshift_shader(vopnet: hou.Node) -> hou.Node | None:
    """Find the actual surface shader node inside a reconstructed
    redshift_vopnet.

    Preferred: whatever is wired into the redshift_material output
    node's Surface input (input 0) - that's the shader actually driving
    the material, by definition, regardless of how many other
    "Material"-named utility nodes (MaterialBlender, MaterialLayer, ...)
    happen to exist in the network or in what order children() returns
    them. Falls back to the name-based scan shaderball_scene.py already
    uses (find "whatever material node exists") for networks with no
    output node or an unwired Surface input."""
    for child in vopnet.children():
        if child.type().name() == "redshift_material":
            inputs = child.inputs()
            if inputs and inputs[0] is not None:
                tname = inputs[0].type().name()
                # Only trust it if it actually looks like a surface
                # shader - guards against inputs() returning a compacted
                # tuple in some cases (e.g. only displacement wired),
                # where index 0 wouldn't be the Surface input at all.
                if "Material" in tname or "PBR" in tname:
                    return inputs[0]
            break
    for child in vopnet.children():
        tname = child.type().name()
        if tname == "redshift_material":
            continue
        if "Material" in tname or "PBR" in tname:
            return child
    return None


# redshift::StandardMaterial parm name -> mtlxstandard_surface parm name.
# Verified against Houdini's own bxdf/standard_surface.mtlx nodedef.
# Uncertain entries (emission/opacity - not directly confirmed against a
# real saved material in this pass) are included as best-effort; a wrong
# or missing name just no-ops via the try/except in _copy_constant_parm
# rather than raising.
#: Redshift material shaders -> the converter that rebuilds each as an
#: mtlxstandard_surface. Populated at the bottom of the module, once
#: every converter it names exists; convert_material_shader reads it,
#: which is what lets a blended material recurse into its parts.
_UBER_CONVERTERS = {}

STANDARD_MATERIAL_PARM_MAP = [
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
    # subsurface_radius is a DISTANCE (mean free path); ms_radius_scale is
    # its scalar multiplier. Without carrying it across, a converted
    # subsurface material renders at scale 1 and washes out - the same
    # scale issue the PhysicallyBased import hit. OpenPBR already maps its
    # equivalent (subsurface_radius_scale) below.
    ("ms_radius_scale", "subsurface_scale"),
    ("sheen_weight", "sheen"),
    ("sheen_color", "sheen_color"),
    ("sheen_roughness", "sheen_roughness"),
    ("coat_weight", "coat"),
    ("coat_color", "coat_color"),
    ("coat_roughness", "coat_roughness"),
    ("coat_ior", "coat_IOR"),
    ("coat_aniso", "coat_anisotropy"),
    ("coat_aniso_rotation", "coat_rotation"),
    # thin film handled separately (gate + unit) by _convert_thin_film.
    ("emission_color", "emission_color"),
    ("emission_weight", "emission"),
    ("opacity_color", "opacity"),
]


# redshift::OpenPBRMaterial parm name -> mtlxstandard_surface parm name.
# OpenPBR uses the spec's own names (base_weight/base_metalness/...),
# which differ from Standard Surface's Arnold-style names - names read
# from a real saved OpenPBR material's .mat block (Blue_Acrylic), mapped
# to the Standard Surface nodedef. Targets mtlxstandard_surface (not
# mtlxopen_pbr_surface) to stay consistent with the library's existing
# Karma materials. Inputs handled elsewhere (geometry_normal ->
# bump/normal, tangents, thin_walled) are excluded here and listed in
# _OPENPBR_HANDLED_INPUTS so they don't report as "unmapped".
OPENPBR_MATERIAL_PARM_MAP = [
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
    # Dispersion: the vendor graph (open_pbr_to_standard_surface.mtlx,
    # "transmissionDispersion" dot) copies the WEIGHT, never the abbe
    # number - mapping abbe (default 20) force-enabled visible
    # dispersion on every converted transmissive material.
    ("transmission_dispersion_scale", "transmission_dispersion"),
    ("subsurface_weight", "subsurface"),
    ("subsurface_color", "subsurface_color"),
    # Crossed on purpose, matching the vendor graph ("subsurfaceScale"
    # dot <- subsurface_radius, "subsurfaceRadius" color3 dot <-
    # subsurface_radius_scale): RS radius is a FLOAT distance and
    # radius_scale a COLOR3 - the straight-across mapping collapsed
    # the per-channel scatter color to its red component.
    ("subsurface_radius", "subsurface_scale"),
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
    # thin film handled separately (gate + unit) by _convert_thin_film.
    ("emission_color", "emission_color"),
    # OpenPBR emission is a luminance (nits), Standard Surface's is a
    # 0-1 weight - a direct copy is right for the common non-emissive
    # case (0 stays 0); genuinely emissive materials may need the weight
    # adjusted by hand (flagged in the report).
    ("emission_luminance", "emission"),
    ("geometry_opacity", "opacity"),
]

# OpenPBR shader inputs converted OUTSIDE the parm map (bump/normal via
# the geometry_normal input, tangents, thin-walled) - excluded from the
# "connected but unmapped" report.
# redshift::Material (the CLASSIC Redshift shader) parm name ->
# mtlxstandard_surface parm name. Verified against the live plugin's
# own parameter list (Redshift 2026 / H21). The classic shader predates
# StandardMaterial: reflection carries its own IOR and Fresnel mode,
# subsurface is the multi-layer ms_* set, and translucency has no
# Standard Surface equivalent at all - the unmappable ones are
# reported, never guessed at.
CLASSIC_MATERIAL_PARM_MAP = [
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
    # Subsurface: the classic shader's multiple-scattering layer 1 is
    # the closest single-layer equivalent (layers 2/3 are reported).
    ("ms_amount", "subsurface"),
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

#: Classic-shader inputs handled outside the parm map (bump/normal), or
#: with no Standard Surface counterpart - each reported once by name.
_CLASSIC_HANDLED_INPUTS = {"bump_input"}

#: Classic parms whose non-default value changes the look but has no
#: faithful Standard Surface target: reported so a conversion is never
#: silently wrong.
_CLASSIC_REPORT_ONLY = (
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
    """Convert Redshift thin film, respecting the GATE and the UNIT that a
    naive copy ignored (which baked a warm iridescent tint onto every
    converted metal - #179; the root cause was indeed a scaling
    problem):

    * OpenPBR gates thin film with `thin_film_weight` (default 0), and its
      `thin_film_thickness` is in MICROMETRES (parm range 0-1, default
      0.5um = 500nm). mtlxstandard_surface has NO weight gate (thickness
      >0 switches it on) and wants NANOMETRES - so apply only when the
      weight is on, and convert um -> nm (x1000).
    * StandardMaterial has no weight (thickness>0 IS the gate) and its
      `thinfilm_thickness` is already in NANOMETRES (parm range 0-1000) ->
      copy straight across.

    So a metal that genuinely has thin film converts correctly; one that
    doesn't (weight 0, or thickness 0) leaves mtlx's thin film off."""
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

    weight = _v("thin_film_weight")          # OpenPBR only
    if weight is not None:                    # -> this is an OpenPBR shader
        if weight > 1e-6:
            _put("thin_film_thickness", (_v("thin_film_thickness") or 0.0) * 1000.0)
            ior = _v("thin_film_ior")
            if ior is not None:
                _put("thin_film_IOR", ior)
        return
    thickness_nm = _v("thinfilm_thickness")   # StandardMaterial, in nm
    if thickness_nm is not None and thickness_nm > 1e-6:
        _put("thin_film_thickness", thickness_nm)
        ior = _v("thinfilm_ior")
        if ior is not None:
            _put("thin_film_IOR", ior)


def _copy_constant_parm(
    src_node: hou.Node, src_name: str, dst_node: hou.Node, dst_name: str
) -> None:
    """Copy a plain value across, WIDTH-AWARE: OpenPBR and Standard
    Surface don't always agree on a parm's tuple width (e.g. a color on
    one side, a scalar on the other), and a raw set() of a mismatched
    width raises hou.InvalidSize - which is a sibling of hou.Error, NOT
    caught by the old (OperationFailed, TypeError, ValueError) clause,
    so it aborted the whole OpenPBR conversion ("aluminum: crashed -
    Invalid size" in the error dialog). A scalar broadcasts to a vector, a
    vector collapses to its first component; anything still off no-ops
    rather than raising."""
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
#: The pre-rename tag. Materials converted before 2026-07-27 carry it
#: in their saved archives, so the dedup check honours BOTH - new
#: conversions write only the new tag.
_UV_SCALE_TAG_LEGACY = "matlib_uv_scale"


def _named_inputs(node: hou.Node) -> dict:
    """{input_name: connected_node} for a VOP node, via the None-padded
    inputs()/inputNames() positional zip (padding confirmed against H21's
    own HOM docs - see convert_standard_material's history note for why
    inputConnections() isn't used instead)."""
    input_nodes = node.inputs()
    input_names = node.inputNames()
    result = {}
    for i, name in enumerate(input_names):
        if i < len(input_nodes) and input_nodes[i] is not None:
            result[name] = input_nodes[i]
    return result


def _set_poly_parm(node: hou.Node, base_name: str, values, signature: str) -> bool:
    """Set a parm on a signature-polymorphic MaterialX node
    (mtlxmultiply, mtlxremap, ...), safely. These nodes carry one parm
    variant per signature (in2, in2_color3, in2_vector2, ... - confirmed
    from a saved multiply's spare-parm block in the real library), the
    parm's tuple width varies accordingly, and a blind set of the wrong
    width raises hou.InvalidSize - which is a hou.Error, NOT a
    ValueError, so a careless except clause misses it (that combination
    crashed every conversion once). Nudges the signature parm first,
    then tries the suffixed variant BEFORE the plain base name: after a
    signature switch the suffixed parm is the one that actually renders,
    and setting only the plain variant succeeds silently while changing
    nothing visible (that exact miss shipped once too - textures came
    out unscaled with the scale correctly read)."""
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
    """UV chain for converted textures: one shared mtlxtexcoord per
    material, feeding one mtlxmultiply per *distinct* UV scale value -
    every mtlximage wires its texcoord input from the multiply matching
    its source sampler's Redshift `scale` parm. Samplers in production
    materials usually channel-reference one shared scale value, so the
    common case is a single multiply serving every image - which then
    doubles as the one dial that scales all the material's textures
    together (the original ask). A material mixing different scales gets
    one multiply per value, still correct per image.

    The multiply doubles as the record of which scale it carries via
    node user data - matching on that (not on parm values, whose width
    varies by signature) is what makes reuse detection reliable."""
    tag = f"{scale[0]:.6g},{scale[1]:.6g}"
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
    if not _set_multiply_in2(multiply, scale) and tuple(scale) != (1.0, 1.0):
        # A failed set on a non-default scale means the converted
        # texture would render at the wrong tiling - worth surfacing.
        # (A failed set on 1,1 is harmless: multiply's in2 defaults to 1.)
        report.approximate(
            f"couldn't set UV scale {tag} on the texture-scale multiply - "
            "set its second input by hand"
        )
    return multiply


#: Standard-surface inputs that carry COLOUR (need an sRGB read and a
#: color3 signature). Everything else a texture can feed - roughness,
#: metalness, specular, opacity, coat weight, ... - is scalar DATA and
#: must be read RAW/linear. This is the wiki's per-map colour-space rule
#: (karma-material-best-practice.md §12), verified against SideFX's own
#: StandardSurface .mtlx: the colour image carries colorspace
#: "srgb_texture", the roughness image carries none.
_COLOUR_INPUTS = frozenset({
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
    """Set an mtlximage's signature + colour space by semantic role.

    role: "color" (sRGB, color3), "data" (Raw, float) or "normal" (Raw,
    vector3). A texture read in the wrong space isn't obviously broken -
    it looks *subtly* wrong - which is exactly why it's worth forcing
    rather than leaving to the node default (color3/auto)."""
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
    """redshift::TextureSampler -> mtlximage (+ the material's shared
    texcoord->multiply UV chain wired into its texcoord input, carrying
    the sampler's own Redshift `scale` value - confirmed as a 2-float
    parm from real saved library data, where production materials
    genuinely use it, e.g. scale 5,5).

    `target_input` is the standard-surface input this texture feeds, used
    to pick the colour space: a colour input reads sRGB, everything else
    reads Raw (see _COLOUR_INPUTS). Normal maps go through convert_bump_map,
    which sets the Vector3/Raw combination itself."""
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
    """redshift::MaxonNoise -> a generic MaterialX fractal noise stand-in.
    See the module docstring - this is deliberately not claimed to be a
    faithful reproduction, just the closest available substitute."""
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
    """The RS output node's "Bump Map" input -> mtlxnormalmap feeding the
    shader's normal input (project convention: everything bump goes to
    the normal map). Real parm/input names confirmed from saved library
    data: redshift::BumpMap takes its texture on "input" and has
    inputType (0 = height field, 1 = tangent-space normal) + scale.

    The bump texture goes STRAIGHT into mtlxnormalmap's "in" input, no
    conversion node in between - an earlier version inserted
    mtlxheighttonormal whenever the RS inputType parm said height-field,
    but library content wires real normal-map textures through BumpMap
    nodes regardless of that setting, so trusting it produced a
    nonsensical normal->normal "conversion". The library's hand-built
    materials settle the wiring convention: all 67 normal-map textures
    in the library feed mtlxnormalmap's "in" input directly
    (normal/tangent inputs always unconnected). The RS scale is still
    only copied when inputType explicitly says tangent-space normal
    (value 1) - a height-style scale like 0.001 copied onto a
    normal-map strength would flatten it to nothing."""
    nm = dest_parent.createNode("mtlxnormalmap")
    if rs_node.type().name() == "redshift::BumpMap":
        tex_src = _named_inputs(rs_node).get("input")
        input_type = rs_node.parm("inputType")
        if input_type is not None and input_type.eval() == 1:
            _copy_constant_parm(rs_node, "scale", nm, "scale")
    else:
        # Something else wired straight into the output's Bump Map input.
        tex_src = rs_node
    if tex_src is None:
        report.skip(
            f'"{rs_node.name()}": bump map has no texture input to convert'
        )
        return nm
    converted = convert_node(tex_src, dest_parent, report)
    if converted is not None:
        # A normal map is DATA, not colour: Vector3 signature + Raw colour
        # space, so no sRGB transform is applied. SideFX's guidance is
        # explicit about this, and it matches their own chess_set .mtlx
        # (image type vector3, no colorspace attr). Wrong here looks
        # subtly wrong, not obviously broken - worth forcing.
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
    """The RS output node's "Displacement" input -> mtlxdisplacement.
    Real parm/input names confirmed from saved library data:
    redshift::Displacement takes its texture on "texMap" and has a float
    scale (plus a Change Range remap, which mtlxdisplacement has no
    equivalent for - reported when it's actually in use)."""
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
        # Something else wired straight into the output's Displacement
        # input - convert it directly as the displacement source.
        tex_src = rs_node
    if tex_src is None:
        return disp
    converted = convert_node(tex_src, dest_parent, report)
    if converted is None:
        return disp
    # A non-default Change Range on the RS node has a faithful MaterialX
    # equivalent after all: mtlxremap (inlow/inhigh -> outlow/outhigh
    # maps exactly onto RS's oldrange -> newrange). Inserted between the
    # converted texture and the displacement node only when actually in
    # use. Parms set via the polymorphic-safe helper (same
    # signature-variant parm layout as mtlxmultiply); a failed set
    # falls back to the old honest "adjust by hand" note rather than
    # silently producing wrong displacement levels.
    if remap_values is not None:
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


#: RSRamp inputMapping -> which UV channel drives the ramp, expressed as
#: the mtlxseparate2 output index (outx = 0 = U, outy = 1 = V). Menu
#: values/labels confirmed by inspecting the real parm in Houdini:
#: 0 Vertical, 1 Horizontal, 2 Diagonal, 3 Radial, 4 Circular.
_RAMP_MAPPING_OUTPUT = {"0": 1, "1": 0}  # Vertical -> V, Horizontal -> U
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
    """The value that drives an RSRamp when nothing is wired into its
    "input": Redshift derives it from the UV map according to
    inputMapping (Vertical -> V, Horizontal -> U). Rebuilt in MaterialX
    as mtlxtexcoord -> mtlxseparate2 -> the matching channel, honouring
    inputInvert. Without this the converted ramp has no driving value at
    all and reads flat. Returns (node, output_index), or None if the
    chain couldn't be built."""
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
    """redshift::RSRamp -> kma_rampconst ("Karma Ramp Const"), Houdini's
    real Karma ramp node - a ramp stays a ramp.

    It takes the lookup position on its "t" input (float) and holds the
    gradient in an ordinary Houdini ramp parm ("vramp" for colour,
    "framp" for float), so the whole gradient copies across as a
    hou.Ramp with its colours intact.

    Two earlier attempts were wrong and are worth remembering:
    hmtlxrampc is EXCLUDED from the Karma context (voptoolutils'
    KARMAMTLX_TAB_MASK lists "^hmtlxramp*") so Karma degrades it to a
    float evaluation - colour knots in, greyscale out; and rebuilding
    the gradient out of mtlxremap/clamp/mix worked but wasn't a ramp any
    more. kma_rampconst only exists inside a real Karma Material
    Builder context, which is why the converter now builds there
    (nodes.make_karma_builder)."""
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

    # Colour ramps live on "vramp", float ramps on "framp".
    is_color = True
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
        # Both Houdini MaterialX ramp nodes are LINEAR-ONLY (SideFX docs
        # for kma_rampconst and hmtlxrampc both say so), so any other
        # knot interpolation can't be reproduced faithfully.
        try:
            if any(b != hou.rampBasis.Linear for b in ramp.basis()):
                report.approximate(
                    f'"{rs_node.name()}" (RSRamp) uses non-linear knot '
                    "interpolation - the Karma ramp only supports Linear, "
                    "so the gradient is rebuilt as linear"
                )
        except (hou.Error, AttributeError):
            pass

    # Whatever drives the lookup. A wired input converts directly;
    # otherwise Redshift derives it from the UV map per inputMapping,
    # which we rebuild as texcoord -> separate -> U/V. Without a driver
    # the ramp has nothing to look up and reads flat.
    src_in = _named_inputs(rs_node).get("input")
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

    # "Alt" input source has no MaterialX equivalent (UV Map / Auto both
    # mean the UV-driven chain above).
    source = rs_node.parm("inputSource")
    try:
        if source is not None and str(source.eval()) == "1":
            report.approximate(
                f'"{rs_node.name()}" (RSRamp) uses the "Alt" input source '
                "- no Karma equivalent, so it is driven by UV instead"
            )
    except hou.Error:
        pass
    return node


# Node type name -> converter function. Anything not listed here is
# reported as skipped rather than guessed at.
#: RSColorLayer blend mode -> the MaterialX node that performs it.
#: Every one of these ships in H21 and H22 (verified in both). Modes
#: with no MaterialX equivalent are absent on purpose and reported.
_LAYER_BLEND_NODES = {
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

#: Modes Standard MaterialX has no node for - named in the report so
#: the difference is visible instead of silent.
_LAYER_BLEND_UNSUPPORTED = {
    "1": "Average", "9": "Hardlight", "10": "Softlight",
    "14": "Exclusion",
}

#: How many layers an RSColorLayer exposes.
_LAYER_COUNT = 7


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
    """redshift::RSColorLayer -> a MaterialX blend chain.

    Photoshop-style layering: a base colour plus up to seven layers,
    each with its own colour, mask and blend mode. Rebuilt literally -
    per layer, the blend node for its mode combines the running result
    with the layer colour, and an mtlxmix folds that back in by the
    layer's mask. A layer whose mode MaterialX cannot express is
    reported and treated as Normal, which is the mode it degrades to
    most predictably."""
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
            # MaterialX compositing nodes take (fg, bg); the math ones
            # take (in1, in2) - both mean "layer over result" here.
            names = [n for n in blend.inputNames() if n]
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
    """redshift::Fresnel -> a MaterialX facing-ratio blend.

    Redshift blends a facing colour into a perpendicular (grazing)
    colour by a Fresnel term. MaterialX ships mtlxfacingratio in both
    H21 and H22, so the term is rebuilt rather than approximated by a
    constant: with an IOR the Schlick form is used -
    F = F0 + (1-F0)(1-cos)^5, F0 = ((ior-1)/(ior+1))^2 - and with the
    curve-falloff mode the exponent is the node's own curve value."""
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
    # 1 - facingratio: the Fresnel term rises toward grazing angles.
    inverted = dest_parent.createNode("mtlxsubtract")
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
        # F = F0 + (1 - F0) * (1 - cos)^exponent
        scaled = dest_parent.createNode("mtlxmultiply")
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
    # At grazing (term -> 1) the perpendicular colour wins.
    mix.setNamedInput("fg", perp_node, 0)
    mix.setNamedInput("bg", facing_node, 0)
    mix.setNamedInput("mix", term, 0)
    debug.event("convert", "fresnel", node=rs_node.path(),
                mode="ior" if (use_ior is None or use_ior.eval()) else "curve")
    return mix


def convert_math_range(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport,
    target_input: str = "",
) -> hou.Node | None:
    """redshift::RSMathRange -> mtlxremap, a one-to-one mapping
    (input/old_min/old_max/new_min/new_max ->
    in/inlow/inhigh/outlow/outhigh). Redshift clamps by default and
    MaterialX's remap does not, so a clamp is appended when it is on."""
    remap = dest_parent.createNode("mtlxremap")
    pairs = (
        ("input", "in"), ("old_min", "inlow"), ("old_max", "inhigh"),
        ("new_min", "outlow"), ("new_max", "outhigh"),
    )
    inputs = _named_inputs(rs_node)
    for rs_name, mtlx_name in pairs:
        src = inputs.get(rs_name)
        if src is not None:
            converted = convert_node(src, dest_parent, report, target_input)
            if converted is not None:
                try:
                    remap.setNamedInput(mtlx_name, converted, 0)
                except hou.OperationFailed:
                    pass
            continue
        parm = rs_node.parm(rs_name)
        target = remap.parm(mtlx_name)
        if parm is not None and target is not None:
            try:
                target.set(float(parm.eval()))
            except hou.Error:
                pass
    result = remap
    clamp_parm = rs_node.parm("clamp")
    if clamp_parm is not None and clamp_parm.eval():
        clamp = dest_parent.createNode("mtlxclamp")
        clamp.setNamedInput("in", remap, 0)
        low, high = clamp.parm("low"), clamp.parm("high")
        new_min, new_max = rs_node.parm("new_min"), rs_node.parm("new_max")
        if low is not None and new_min is not None:
            low.set(float(new_min.eval()))
        if high is not None and new_max is not None:
            high.set(float(new_max.eval()))
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
    """Dispatch a single connected (procedural) input node to its
    converter, or report it as unsupported. Returns None on no mapping -
    callers must handle that by leaving the destination input unwired
    rather than crashing.

    `target_input` is the standard-surface input the result will feed,
    so a texture sampler can pick its colour space from what it drives
    (colour vs data). Every converter whose signature takes it gets it
    - six of them re-forward it to the samplers nested behind them, and
    the identity check this used to be handed the hint only to
    convert_texture_sampler ITSELF: a base_color texture behind an
    RSColorCorrection converted as data/Raw, silently desaturated, with
    a success report. Read from the SIGNATURE so a new converter that
    declares the parameter joins without touching this dispatch."""
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


#: Upstream (input) nodes with no MaterialX equivalent, each with the
#: reason in the user's terms. Anything absent falls back to the
#: generic "no conversion mapping yet" - these are the ones where the
#: absence is a PROPERTY of the node, not a gap to close later.
_UNCONVERTIBLE_INPUTS = {
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


#: Redshift shaders that are NOT surface materials in the Standard
#: Surface sense. A conversion attempt would either fail or invent a
#: look, so each is refused with the reason - measured across a
#: 400-material library, these are the bulk of what "cannot convert".
_OUT_OF_SCOPE_SHADERS = {
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
    """When no convertible surface terminal was found: the reason, in
    the user's terms, derived from what the network actually contains.
    Empty string when the network holds nothing recognisable."""
    present = {c.type().name() for c in vopnet.allSubChildren()}
    for type_name, reason in _OUT_OF_SCOPE_SHADERS.items():
        if type_name in present:
            return reason
    return ""


def convert_classic_material(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport
) -> hou.Node:
    """redshift::Material (the classic Redshift shader) ->
    mtlxstandard_surface."""
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
    # Fresnel/BRDF modes change the specular response; only the default
    # combination maps 1:1 onto Standard Surface's GGX + IOR model.
    for parm_name, default, what in (
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
    """Redshift's *_isGlossiness toggles make a roughness parm carry
    GLOSSINESS (1-roughness). Copied raw, a glossiness-workflow
    material converts INVERTED - shiny reads matte. Verified on the
    live plugin: refl_isGlossiness / coat_isGlossiness /
    refr_isGlossiness, all default off."""
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
    """The two non-linear transforms SideFX's own translation graph
    applies that a straight copy omits (open_pbr_to_standard_surface
    .mtlx): sheen roughness is fuzz_roughness^2.5, and specular
    roughness is mixed toward coat_roughness by coat weight. Constants
    only - a textured input is reported instead of being baked."""
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
    """redshift::OpenPBRMaterial -> mtlxstandard_surface (OpenPBR's
    spec parm names translated to Standard Surface's, per
    OPENPBR_MATERIAL_PARM_MAP)."""
    return _convert_uber_shader(
        rs_node, dest_parent, report,
        OPENPBR_MATERIAL_PARM_MAP, _OPENPBR_HANDLED_INPUTS,
    )


def convert_color_correction(
    rs_node: hou.Node, dest_parent: hou.Node, report: ConversionReport,
    target_input: str = "",
) -> hou.Node | None:
    """redshift::RSColorCorrection -> the MaterialX correction chain.

    Hue, saturation and level are one mtlxhsvadjust (its amount is
    exactly [hue shift, saturation gain, value gain]); gamma is
    mtlxrange's own gamma; contrast is mtlxcontrast. Only contrast
    needs interpreting - Redshift's neutral is 0.5 where MaterialX's
    is amount 1.0 around a 0.5 pivot - so a non-default contrast is
    mapped linearly and REPORTED as approximated rather than presented
    as exact."""
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
    """redshift::ParticleAttributeLookup -> mtlxgeompropvalue.

    Both read a named geometry attribute at shading time, so the
    attribute name carries straight across ("Cd" stays "Cd")."""
    attribute = rs_node.parm("attribute")
    name = str(attribute.eval()).strip() if attribute is not None else ""
    if not name:
        report.skip(
            "a particle-attribute lookup has no attribute name set"
        )
        return None
    lookup = dest_parent.createNode("mtlxgeompropvalue")
    signature = lookup.parm("signature")
    # Colour attributes are colour; anything else reads as float, which
    # is what the remaining lookups in practice are (pscale, age, id).
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
    """Any Redshift MATERIAL node -> its MaterialX equivalent.

    The single entry point for "this node is a material": the three
    uber shaders convert directly, and the blender/layer nodes recurse
    through here for each material they combine, so a blend of blends
    converts as deeply as it nests."""
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
    """A blend mask as the FLOAT mtlxmix wants. Redshift blends
    materials by a COLOUR; MaterialX mixes surfaces by a single
    weight, so a connected colour is reduced through mtlxluminance
    and a constant colour by its own luminance - reported when the
    colour is not grey, since that is where the two models part."""
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
    """redshift::MaterialBlender / redshift::MaterialLayer -> a chain
    of mtlxmix nodes over converted materials.

    MaterialX mixes SURFACES natively (mtlxmix with two surface
    inputs outputs a surface - verified in both Houdini versions), so
    each material is converted on its own and mixed by the layer's
    blend weight. Additive layers are reported: MaterialX's surface
    mix interpolates, it does not sum."""
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
) -> hou.Node:
    """Build an mtlxstandard_surface node (under dest_parent) equivalent
    to rs_node (a Redshift Standard or OpenPBR material) using parm_map.
    For each mapped parameter: if the Redshift input has a live
    connection, recursively convert whatever feeds it; otherwise just
    copy the constant value across. handled_inputs are connected inputs
    dealt with elsewhere (bump/normal), so they aren't reported as
    unmapped."""
    mtlx = dest_parent.createNode("mtlxstandard_surface")
    # inputConnections()/NodeConnection.outputNode() was tried first and
    # gave back nonsense for this node type - outputNode() kept reporting
    # rs_node itself, with output-sounding names ("outColor", "out"), not
    # the upstream texture nodes actually feeding it. Rather than keep
    # guessing at that API's exact semantics, switched to the plain
    # inputs()/inputNames() pairing this codebase already uses
    # successfully elsewhere for the same kind of lookup
    # (helpers.get_connected_nodes, and shaderball_scene.py's own
    # setNamedInput(name, tex, 0) wiring - which is also why the output
    # index below is hardcoded to 0: every proven wiring call in this
    # codebase assumes a texture/utility node's primary output is index 0,
    # and there's no simple way to recover a specific output index from
    # inputs() alone).
    name_to_node = _named_inputs(rs_node)
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
    # A connected input the parm map doesn't cover used to vanish without
    # a trace (the skip-notes above only fire for MAPPED inputs) -
    # a real conversion showed a live "bump_input" connection converting
    # to nothing, silently. bump/normal inputs are handled separately in
    # convert_redshift_material; everything else unmapped at least gets
    # reported now.
    mapped = {rs_name for rs_name, _ in parm_map}
    for name in name_to_node:
        if name in mapped or name in handled_inputs:
            continue
        report.skip(
            f'shader input "{name}" is connected but has no conversion '
            "mapping yet - left at the MaterialX default"
        )
    _convert_thin_film(rs_node, mtlx, report)
    # Fidelity passes shared by every Redshift uber shader, both
    # verified against the shipped vendor translation graph and the
    # live plugin's own parameters (materials research 2026-07).
    _apply_glossiness_inversion(rs_node, mtlx, report)
    _apply_vendor_transforms(rs_node, mtlx, report)
    return mtlx


def convert_redshift_material(
    node_handler,
    source_mat,
    prefs_dir_parent: hou.Node,
) -> tuple[hou.Node | None, ConversionReport]:
    """Reconstructs source_mat (a Redshift material.Material) at a scratch
    location, converts its shader network, and returns the converted
    (shader, displacement, report): the mtlxstandard_surface, an
    mtlxdisplacement (or None), and a report of what couldn't be
    converted - the SAME adapter API as the online translator, so the
    engine wires each into the builder's own terminal. Both live under
    prefs_dir_parent; the caller registers via add_asset() and destroys
    the scratch node.

    redshift::StandardMaterial and redshift::OpenPBRMaterial (the two
    largest groups in a real-world library) are both handled, each via
    its own parm map to mtlxstandard_surface; any other shader type is
    reported and skipped, returning (None, report)."""
    report = ConversionReport(source_mat.name)
    debug.event("convert", "start", material=source_mat.name,
                renderer=source_mat.renderer, mat_id=source_mat.mat_id)

    # Preflight: the converter must RECONSTRUCT the Redshift material to
    # read its parameters, which needs the Redshift plugin loaded. When
    # it isn't (e.g. the Houdini/Redshift version mismatch keeps it from
    # loading), createNode("redshift_vopnet") raises "Invalid node type
    # name" mid-reconstruction - a cryptic crash. Report it clearly and
    # skip instead.
    if not _redshift_type_available():
        report.skip(
            "Redshift isn't loaded this session, so the source material "
            "can't be read (the converter reconstructs the Redshift "
            "network to read its parameters). Load Redshift and retry - "
            "check the Houdini/Redshift plugin versions match."
        )
        return None, None, report

    # Off the undo stack at BOTH ends: a create/destroy pair on the
    # live stack resurrects the scratch with the whole reconstructed
    # Redshift copy on one Ctrl+Z (#278).
    with hou.undos.disabler():
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

        # Bump and displacement live on the redshift_material OUTPUT
        # node's own named inputs in RS networks, never on the shader -
        # walk them from there. Bump becomes mtlxnormalmap -> the
        # shader's normal input; displacement becomes mtlxdisplacement,
        # tied to the surface via a collect node so the whole
        # displacement branch is reachable from the single node the
        # save path walks connections from (get_connected_nodes only
        # recurses through inputs of the node it's handed - a
        # displacement chain not wired to anything shared with the
        # shader would silently not be saved at all).
        out_node = None
        for child in vopnet.children():
            if child.type().name() == "redshift_material":
                out_node = child
                break
        out_inputs = _named_inputs(out_node) if out_node is not None else {}
        # Bump can arrive two ways in RS networks: wired into the
        # shader's own bump_input, or into the output node's "Bump Map"
        # input - real production libraries show both patterns (a real
        # material used bump_input, which the output-node-only handling
        # silently dropped). Shader-level wins when both exist (it's the
        # same BumpMap node in every observed case) - only one normal
        # input to feed either way.
        # StandardMaterial wires bump into bump_input or the output's
        # "Bump Map"; OpenPBR wires its normal/bump into the shader's
        # own geometry_normal input. Check all three.
        shader_inputs = _named_inputs(shader)
        bump_src = (
            shader_inputs.get("geometry_normal")
            or shader_inputs.get("bump_input")
            or out_inputs.get("Bump Map")
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
            disp_src = out_inputs.get("Displacement")
            if disp_src is not None:
                mtlx_disp = convert_displacement(disp_src, prefs_dir_parent, report)

        # Sanitized: node names can't contain spaces/dashes etc., and
        # library material names can - an unsanitized setName() would
        # raise hou.OperationFailed and abort the whole conversion for
        # any such material. Same helper the import path uses.
        mtlx.setName(
            helpers.sanitize_usd_path(source_mat.name), unique_name=True
        )
        # Return (shader, displacement) - the SAME adapter API the online
        # translator uses, so the engine wires each into its own builder
        # terminal (surface_output / displacement_output). This replaced a
        # collect node bundling the two, which the KARMA_REF subnetconnector
        # builder rejects (its surface terminal won't accept a collect's
        # output - hou.InvalidInput, the converter crash). Displacement is
        # saved as part of the whole builder now, so it no longer needs a
        # collect to stay reachable from one node.
        return mtlx, mtlx_disp, report
    finally:
        # The reconstructed Redshift copy is only ever scratch scaffolding
        # for reading values/connections - never left in the scene, same
        # discipline as every other temp-node use in this codebase.
        with hou.undos.disabler():
            scratch.destroy()


# Registered here, not in the literal above: these converters are
# defined further down the module (they lean on the material entry
# point), so the table is completed once everything it names exists.
NODE_CONVERTERS.update({
    "redshift::RSColorCorrection": convert_color_correction,
    "redshift::ParticleAttributeLookup": convert_particle_attribute,
})

_UBER_CONVERTERS.update({
    "redshift::StandardMaterial": convert_standard_material,
    "redshift::OpenPBRMaterial": convert_openpbr_material,
    "redshift::Material": convert_classic_material,
})
