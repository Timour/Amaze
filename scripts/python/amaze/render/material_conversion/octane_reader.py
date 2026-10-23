"""Octane to MaterialX: an Octane material's network rebuilt node by node in a MaterialX builder."""

from __future__ import annotations

import math

import hou

from amaze.core import debug
from amaze.helpers import wording
from amaze.render.material_converter import _copy_constant_parm, _set_poly_parm

SIGNATURE = {"float": "default", "color3": "color3", "vector3": "vector3"}

STANDARD_SURFACE = (    # NT_MAT_STANDARD_SURFACE -> mtlxstandard_surface, a rename ▸r/octane-builder
    ("base", "base"), ("baseColor", "base_color"), ("diffuseRoughness", "diffuse_roughness"),
    ("metallic", "metalness"), ("specular", "specular"), ("specularColor", "specular_color"),
    ("roughness", "specular_roughness"), ("ior", "specular_IOR"),
    ("anisotropyTexture", "specular_anisotropy"), ("rotation", "specular_rotation"),
    ("transmission", "transmission"), ("transmissionColor", "transmission_color"),
    ("transmissionDepth", "transmission_depth"), ("scattering", "transmission_scatter"),
    ("scatteringAnisotropy", "transmission_scatter_anisotropy"),
    ("roughnessExtra", "transmission_extra_roughness"), ("subsurface", "subsurface"),
    ("subsurfaceColor", "subsurface_color"), ("radius", "subsurface_radius"),
    ("scale", "subsurface_scale"), ("subsurfaceAnisotropy", "subsurface_anisotropy"),
    ("coating", "coat"), ("coatingColor", "coat_color"), ("coatingRoughness", "coat_roughness"),
    ("coatingIor", "coat_IOR"), ("coatingAnisotropy", "coat_anisotropy"),
    ("coatingRotation", "coat_rotation"), ("sheen", "sheen"), ("sheenColor", "sheen_color"),
    ("sheenRoughness", "sheen_roughness"), ("emissionWeight", "emission"),
    ("emissionColor", "emission_color"), ("filmwidth", "thin_film_thickness"),
    ("filmIor", "thin_film_IOR"), ("thinWall", "thin_walled"), ("opacity", "opacity"),
)
OPEN_PBR = (    # NT_MAT_OPEN_PBR_SURFACE -> mtlxopen_pbr_surface, one specification on both sides
    ("base", "base_weight"), ("baseColor", "base_color"),
    ("diffuseRoughness", "base_diffuse_roughness"), ("metallic", "base_metalness"),
    ("specular", "specular_weight"), ("specularColor", "specular_color"),
    ("roughness", "specular_roughness"), ("ior", "specular_ior"),
    ("anisotropyTexture", "specular_roughness_anisotropy"),
    ("transmission", "transmission_weight"), ("transmissionColor", "transmission_color"),
    ("transmissionDepth", "transmission_depth"), ("scattering", "transmission_scatter"),
    ("scatteringAnisotropy", "transmission_scatter_anisotropy"),
    ("dispersionScale", "transmission_dispersion_scale"),
    ("subsurface", "subsurface_weight"), ("subsurfaceColor", "subsurface_color"),
    ("radius", "subsurface_radius"), ("scale", "subsurface_radius_scale"),
    ("subsurfaceAnisotropy", "subsurface_scatter_anisotropy"), ("coating", "coat_weight"),
    ("coatingTransmission", "coat_color"), ("coatingRoughness", "coat_roughness"),
    ("coatingAnisotropy", "coat_roughness_anisotropy"), ("coatingIor", "coat_ior"),
    ("coatingDarkening", "coat_darkening"), ("fuzz", "fuzz_weight"), ("fuzzColor", "fuzz_color"),
    ("fuzzRoughness", "fuzz_roughness"), ("emissionLuminance", "emission_luminance"),
    ("emissionColor", "emission_color"), ("thinFilmWeight", "thin_film_weight"),
    ("filmwidth", "thin_film_thickness"), ("filmIor", "thin_film_ior"),
    ("thinWall", "geometry_thin_walled"), ("opacity", "geometry_opacity"),
)
NORMALS = {    # the shader's normal-map inputs: Octane's name -> MaterialX's, per shader
    "mtlxstandard_surface": (("normal", "normal"), ("coatingNormal", "coat_normal")),
    "mtlxopen_pbr_surface": (("normal", "geometry_normal"),
                             ("coatingNormal", "geometry_coat_normal")),
}
NO_FORM = (    # material inputs with no MaterialX form: said when wired or set
    "diffuseBrdf", "brdf", "spread", "sheenBrdf", "sheenBump", "sheenNormal", "priority",
    "fake_shadows", "refractionAlpha", "hasCaustics", "medium", "coatingBump", "smooth",
    "smoothShadowTerminator", "roundEdges", "emission", "matte", "customAov",
    "customAovChannel", "layer", "transmissionType", "specularMap",
)
REFUSED = {    # Octane materials with nothing faithful to become, each with the reason
    "octane::NT_MAT_LAYER": "a layered material - MaterialX surfaces have no layer stack here",
    "octane::NT_MAT_LAYER_GROUP": "a material layer group, which only a layered material reads",
    "octane::NT_MAT_DIFFUSE_LAYER": "a material layer, which only a layered material reads",
    "octane::NT_MAT_METALLIC_LAYER": "a material layer, which only a layered material reads",
    "octane::NT_MAT_SPECULAR_LAYER": "a material layer, which only a layered material reads",
    "octane::NT_MAT_SHEEN_LAYER": "a material layer, which only a layered material reads",
    "octane::NT_MAT_TOON": "a non-photorealistic Toon material - MaterialX has no cel model",
    "octane::NT_MAT_HAIR": "a hair material - Standard Surface has no hair BSDF",
    "octane::NT_MAT_COMPOSITE": "a composite material, which blends by Octane's own rules",
    "octane::NT_MAT_CLIPPING": "a clipping material, which cuts geometry rather than shades it",
    "octane::NT_MAT_NULL": "a null material, which renders nothing",
    "octane::NT_MAT_PORTAL": "a portal material, which guides Octane's light sampling",
    "octane::NT_MAT_SHADOW_CATCHER": "a shadow catcher, a compositing material",
    "octane::NT_TEX_TRIPLANAR": "a triplanar map of textures - MaterialX's triplanar takes files",
    "octane::NT_TEX_UVW_TRANSFORM": "a UVW transform of a whole texture, which has no MaterialX node",
}
COLOUR_SPACES = {    # Octane's colour space -> mtlximage's filecolorspace
    "NAMED_COLOR_SPACE_SRGB": "srgb_texture", "NAMED_COLOR_SPACE_OTHER": "Raw",
    "NAMED_COLOR_SPACE_LINEAR_SRGB": "lin_rec709", "NAMED_COLOR_SPACE_ACESCG": "acescg",
    "data": "Raw", "ACEScg": "ACEScg",
}
LEGACY_GAMMA = {1.0: "lin_rec709", 1.8: "g18_rec709", 2.2: "g22_rec709"}
ADDRESS = {"0": ("periodic", None), "4": ("mirror", None), "3": ("clamp", None),
           "1": ("constant", 0.0), "2": ("constant", 1.0)}    # Octane border mode -> MaterialX
BINARY = {    # NT_TEX_MATH_BINARY operationType -> node; texture1 is the first operand (measured)
    "0": "mtlxadd", "3": "mtlxdivide", "11": "mtlxpower", "10": "mtlxmultiply",
    "9": "mtlxmodulo", "5": "mtlxmodulo", "12": "mtlxsubtract", "7": "mtlxmax", "8": "mtlxmin",
    "1": "mtlxatan2", "2": "mtlxcrossproduct", "4": "mtlxdotproduct",
}
UNARY = {    # NT_TEX_MATH_UNARY operationType -> one MaterialX node over `in`
    "0": "mtlxabsval", "8": "mtlxexp", "12": "mtlxfract", "14": "mtlxinvert", "15": "mtlxln",
    "23": "mtlxsign", "26": "mtlxsqrt", "22": "mtlxround", "11": "mtlxfloor", "4": "mtlxceil",
    "1": "mtlxacos", "2": "mtlxasin", "5": "mtlxcos", "24": "mtlxsin", "27": "mtlxtan",
    "30": "mtlxmagnitude", "31": "mtlxnormalize",
}
SCALED = {"19": -1.0, "20": math.pi / 180.0, "7": 180.0 / math.pi}    # negate, to radians, degrees
COMPARE = {    # NT_TEX_COMPARE operationType -> (node, A is value1, texture3 when true)
    "0": ("mtlxifgreater", False, True), "1": ("mtlxifgreater", True, True),
    "2": ("mtlxifequal", True, True), "3": ("mtlxifequal", True, False),
    "4": ("mtlxifgreatereq", False, True), "5": ("mtlxifgreatereq", True, True),
}
QUALITY = {    # displacement settings with no MaterialX form, at Octane's defaults
    "quality": "1", "levelOfDetail": "10", "displacementDirection": "1", "filterType": "0",
    "filtersize": "2", "textureSpace": "0", "inputAxes": "0", "subdLevel": "0", "bump": "0",
    "displaceRestPosition": "0",
}
DISPLACEMENTS = ("octane::NT_DISPLACEMENT", "octane::NT_VERTEX_DISPLACEMENT")


def _feeds(node) -> dict:
    """{input name: (upstream node, its output index)} for each wired input of `node`."""
    names = node.inputNames()
    return {names[conn.inputIndex()]: (conn.inputNode(), conn.outputIndex())
            for conn in node.inputConnections()
            if conn.inputNode() is not None and conn.inputIndex() < len(names)}


def _values(node, name) -> tuple:
    values = node.parmTuple(name)
    return tuple(values.eval()) if values is not None else ()


def _token(node, name) -> str:
    parm = node.parm(name)
    return parm.evalAsString() if parm is not None else ""


def _set(node, name, value) -> None:
    parm = node.parm(name)
    if parm is not None:
        parm.set(value)


def _at_default(node, name) -> bool:
    values = node.parmTuple(name)
    return values is None or all(parm.isAtDefault() for parm in values)


class Reader:
    """One Octane network read into one MaterialX builder, each node once per role."""

    def __init__(self, builder: hou.Node, report) -> None:
        self.builder = builder
        self.report = report
        self.displacement = None
        self._read = {}

    def make(self, kind: str, after: hou.Node | None = None, role: str = "") -> hou.Node:
        """A MaterialX node in the builder, named after the Octane node it stands for."""
        made = self.builder.createNode(kind)
        if after is not None:
            made.setName(wording.sanitize_usd_path(after.name()), unique_name=True)
        if role and made.parm("signature") is not None:
            _set_signature(made, role)
        return made

    def read(self, node: hou.Node, role: str, output: int = 0):
        """`node` as MaterialX for an input of `role`: (node, output index), or None."""
        if node.type().name().startswith("mtlx"):
            return self._materialx(node, output)
        key = (node.path(), role)
        if key not in self._read:
            self._read[key] = self._dispatch(node, role)
        return self._read[key]

    def _dispatch(self, node, role):
        kind = node.type().name()
        if kind in REFUSED:
            self.report.skip('"%s" is %s' % (node.name(), REFUSED[kind]))
            return None
        reader = READERS.get(kind)
        if reader is None:
            self.report.skip('"%s" (%s) has no conversion mapping yet - left at the MaterialX '
                             "default" % (node.name(), kind))
            return None
        made = reader(self, node, role)
        return made if made is None or isinstance(made, tuple) else (made, 0)

    def _materialx(self, node, output):
        """A MaterialX node inside an Octane builder crosses as it is, its inputs read in turn."""
        key = (node.path(), "copy")
        if key not in self._read:
            copy = hou.copyNodesTo((node,), self.builder)[0]
            self._read[key] = copy
            for name, (upstream, index) in _feeds(node).items():
                self.wire(copy, name, self.read(upstream, _role_of(copy, name), index))
        return (self._read[key], output)

    def wire(self, target: hou.Node, name: str, made) -> bool:
        """`made` on `target`'s input `name`; a refused wire is said."""
        if made is None:
            return False
        try:
            target.setNamedInput(name, made[0], made[1])
            return True
        except hou.Error as exc:    # InvalidInput is a sibling ▸r/hou-errors
            self.report.skip('"%s" could not be wired to %s on "%s"' % (
                made[0].name(), name, target.name()))
            debug.event("octane", "reader wire refused", input=name, error=str(exc))
            return False

    def carry(self, source, octane_name, target, mtlx_name, role="", poly=False) -> None:
        """One input across: its value always, what feeds it when wired."""
        role = role or _role_of(target, mtlx_name)
        values = _values(source, octane_name)
        if values and poly:
            _set_poly_parm(target, mtlx_name, values, SIGNATURE.get(role, role))
        elif values:
            _copy_constant_parm(source, octane_name, target, mtlx_name)
        fed = _feeds(source).get(octane_name)
        if fed is not None:
            self.wire(target, mtlx_name, self.read(fed[0], role, fed[1]))

    def said_unless_default(self, node, names, why) -> None:
        """Each of `names` wired or set away from its default, said once with `why`."""
        wired = _feeds(node)
        for name in names:
            if node.parmTuple(name) is None and name not in wired:
                continue
            if name in wired or not _at_default(node, name):
                self.report.skip('"%s" uses %s, %s' % (node.name(), name, why))


def _set_signature(node, role) -> None:
    try:
        node.parm("signature").set(SIGNATURE.get(role, role))
    except hou.Error as exc:
        debug.event("octane", "signature not set", node=node.path(), error=str(exc))


def _role_of(node, name) -> str:
    """The role of a MaterialX input by its width: three wide is colour, one is a value."""
    values = node.parmTuple(name)
    if values is None:
        values = node.parmTuple("%s_color3" % name)
    return "color3" if values is not None and len(values) == 3 else "float"


HANDLED = ("normal", "coatingNormal", "tangent", "coatingTangent", "bump", "bumpHeight",
           "displacement", "dispersion_coefficient_B", "dispersionMode")


def _shader(reader, node, kind, pairs, extra=None, consumed=()):
    """An uber shader across by its table; `extra` carries the `consumed` inputs by hand."""
    shader = reader.make(kind, node)
    for octane_name, mtlx_name in pairs:
        reader.carry(node, octane_name, shader, mtlx_name)
    if extra is not None:
        extra(reader, node, shader)
    _normals(reader, node, shader, NORMALS.get(kind, ()))
    _displacement(reader, node)
    _dispersion(reader, node, shader, kind)
    handled = {name for name, _mtlx in pairs} | set(HANDLED) | set(consumed) | set(NO_FORM)
    for name, (upstream, _index) in _feeds(node).items():
        if name not in handled:
            reader.report.skip('"%s" feeds %s, which has no conversion mapping yet' % (
                upstream.name(), name))
    reader.said_unless_default(node, NO_FORM, "which MaterialX has no form for")
    return shader


def _dispersion(reader, node, shader, kind) -> None:
    """Octane's dispersion as MaterialX's Abbe number; Cauchy's coefficients are said."""
    if node.parmTuple("dispersion_coefficient_B") is None:
        return
    target = ("transmission_dispersion" if kind == "mtlxstandard_surface"
              else "transmission_dispersion_abbe_number")
    if _token(node, "dispersionMode") == "2":
        reader.said_unless_default(node, ("dispersion_coefficient_B",),
                                   "a Cauchy coefficient, which MaterialX has no form for")
        return
    reader.carry(node, "dispersion_coefficient_B", shader, target)


def _normals(reader, node, shader, pairs) -> None:
    """Normal maps through mtlxnormalmap, a bump through mtlxbump; both meet on the normal."""
    feeds = _feeds(node)
    for octane_name, mtlx_name in pairs:
        if octane_name in feeds:
            reader.wire(shader, mtlx_name, _normal_map(reader, *feeds[octane_name]))
    if "bump" not in feeds:
        return
    height = reader.read(feeds["bump"][0], "float", feeds["bump"][1])
    if height is None:
        return
    bump = reader.make("mtlxbump", feeds["bump"][0])
    reader.wire(bump, "height", height)
    _set(bump, "scale", _values(node, "bumpHeight")[0] if _values(node, "bumpHeight") else 1.0)
    normal_name = pairs[0][1] if pairs else "normal"
    if "normal" in feeds:
        reader.wire(bump, "normal", _normal_map(reader, *feeds["normal"]))
    reader.wire(shader, normal_name, (bump, 0))
    reader.report.approximate('"%s": the bump height crossed as MaterialX bump scale - the '
                              "two may not mean the same distance" % node.name())


def _normal_map(reader, source, output=0):
    """A tangent-space normal image as mtlximage (vector3, Raw) into mtlxnormalmap."""
    image = reader.read(source, "vector3", output)
    if image is None:
        return None
    key = (source.path(), "normalmap")
    if key not in reader._read:
        normalmap = reader.make("mtlxnormalmap", source)
        normalmap.setName(wording.sanitize_usd_path(source.name()) + "_normalmap",
                          unique_name=True)
        reader.wire(normalmap, "in", image)
        reader._read[key] = (normalmap, 0)
    return reader._read[key]


def _displacement(reader, node) -> None:
    """The material's displacement pin; a bare texture on it displaces at height 1."""
    fed = _feeds(node).get("displacement")
    if fed is None or reader.displacement is not None:
        return
    if fed[0].type().name() in DISPLACEMENTS:
        made = reader.read(fed[0], "displacement", fed[1])
        reader.displacement = made[0] if made else None
        return
    height = reader.read(fed[0], "float", fed[1])
    if height is not None:
        displacement = reader.make("mtlxdisplacement", fed[0], "float")
        reader.wire(displacement, "displacement", height)
        reader.displacement = displacement
        reader.report.approximate('"%s" displaces "%s" directly - it crossed at height 1' % (
            fed[0].name(), node.name()))


def read_standard(reader, node, role):
    return _shader(reader, node, "mtlxstandard_surface", STANDARD_SURFACE)


def read_open_pbr(reader, node, role):
    def tangents(reader, node, shader):
        for octane_name, mtlx_name in (("tangent", "geometry_tangent"),
                                       ("coatingTangent", "geometry_coat_tangent")):
            fed = _feeds(node).get(octane_name)
            if fed is not None:
                reader.wire(shader, mtlx_name, reader.read(fed[0], "vector3", fed[1]))
    return _shader(reader, node, "mtlxopen_pbr_surface", OPEN_PBR, tangents)


def _lobe(reader, node, octane_name, shader, weight, colour) -> None:
    """An Octane colour lobe as MaterialX's weight 1 and colour, or 0 when black and unwired."""
    values = _values(node, octane_name)
    on = octane_name in _feeds(node) or any(v > 0 for v in values)
    _set(shader, weight, 1.0 if on else 0.0)
    if on:
        reader.carry(node, octane_name, shader, colour)


def _metal_ior(reader, node, shader) -> bool:
    """RGB IOR mode: each channel's (n, k) as its head-on reflectance, metalness 1."""
    if _token(node, "metallicMode") != "2":
        return False
    from amaze.render.material_conversion import materialx    # one home for the physics
    channels = [_values(node, name) for name in ("index", "index2", "index3")]
    shader.setInput(shader.inputIndex("base_color"), None)    # the measured colour replaces it
    shader.parmTuple("base_color").set(tuple(
        materialx.normal_incidence_reflectance(float(n), float(k)) for n, k in channels))
    _set(shader, "metalness", 1.0)
    reader.report.approximate('"%s": the RGB complex index of refraction became a metalness-1 '
                              "surface with its head-on reflectance as base colour" % node.name())
    return True


def _approximated(reader, node, what) -> None:
    reader.report.approximate('"%s": %s became a Standard Surface, lobe by lobe' % (
        node.name(), what))


def _film(reader, node, shader) -> None:
    """Octane's film width in micrometres as MaterialX's thickness in nanometres."""
    fed = _feeds(node).get("filmwidth")
    if fed is not None:
        width = reader.read(fed[0], "float", fed[1])
        scaled = reader.make("mtlxmultiply", fed[0], "float")
        reader.wire(scaled, "in1", width)
        _set(scaled, "in2", 1000.0)
        reader.wire(shader, "thin_film_thickness", (scaled, 0))
    elif _values(node, "filmwidth"):
        _set(shader, "thin_film_thickness", _values(node, "filmwidth")[0] * 1000.0)


SHARED = (("roughness", "specular_roughness"), ("anisotropyTexture", "specular_anisotropy"),
          ("rotation", "specular_rotation"), ("filmIor", "thin_film_IOR"), ("opacity", "opacity"))


def read_universal(reader, node, role):
    def lobes(reader, node, shader):
        _set(shader, "base", 1.0)
        reader.carry(node, "albedo", shader, "base_color")
        reader.carry(node, "metallic", shader, "metalness")
        reader.carry(node, "edgeTint", shader, "specular_color")
        _metal_ior(reader, node, shader)
        _lobe(reader, node, "transmission", shader, "transmission", "transmission_color")
        _lobe(reader, node, "coating", shader, "coat", "coat_color")
        _lobe(reader, node, "sheen", shader, "sheen", "sheen_color")
        _film(reader, node, shader)
        _approximated(reader, node, "Octane's Universal material")
    pairs = SHARED + (("specular", "specular"), ("ior", "specular_IOR"),
                      ("coatingRoughness", "coat_roughness"), ("coatingIor", "coat_IOR"),
                      ("sheenRoughness", "sheen_roughness"))
    return _shader(reader, node, "mtlxstandard_surface", pairs, lobes, (
        "albedo", "metallic", "edgeTint", "index", "index2", "index3", "metallicMode",
        "transmission", "coating", "sheen", "filmwidth"))


def read_diffuse(reader, node, role):
    def lobes(reader, node, shader):
        _set(shader, "base", 1.0)
        _set(shader, "specular", 0.0)
        reader.carry(node, "diffuse", shader, "base_color")
        reader.carry(node, "roughness", shader, "diffuse_roughness")
        reader.said_unless_default(node, ("transmission",), "which MaterialX has no form for")
        _approximated(reader, node, "Octane's Diffuse material")
    return _shader(reader, node, "mtlxstandard_surface", (("opacity", "opacity"),), lobes,
                   ("diffuse", "roughness", "transmission"))


def read_glossy(reader, node, role):
    def lobes(reader, node, shader):
        _set(shader, "base", 1.0)
        reader.carry(node, "diffuse", shader, "base_color")
        _lobe(reader, node, "sheen", shader, "sheen", "sheen_color")
        _film(reader, node, shader)
        _approximated(reader, node, "Octane's Glossy material")
    pairs = SHARED + (("specular", "specular"), ("ior", "specular_IOR"),
                      ("sheenRoughness", "sheen_roughness"))
    return _shader(reader, node, "mtlxstandard_surface", pairs, lobes,
                   ("diffuse", "sheen", "filmwidth"))


def read_specular(reader, node, role):
    def lobes(reader, node, shader):
        _set(shader, "base", 0.0)
        _set(shader, "transmission", 1.0)
        reader.carry(node, "transmission", shader, "transmission_color")
        reader.carry(node, "reflection", shader, "specular_color")
        _film(reader, node, shader)
        _approximated(reader, node, "Octane's Specular material")
    pairs = SHARED + (("ior", "specular_IOR"), ("thinWall", "thin_walled"))
    return _shader(reader, node, "mtlxstandard_surface", pairs, lobes,
                   ("transmission", "reflection", "filmwidth"))


def read_metal(reader, node, role):
    def lobes(reader, node, shader):
        _set(shader, "base", 1.0)
        _set(shader, "metalness", 1.0)
        if not _metal_ior(reader, node, shader):
            reader.carry(node, "specular", shader, "base_color")
        reader.carry(node, "edgeTint", shader, "specular_color")
        _lobe(reader, node, "sheen", shader, "sheen", "sheen_color")
        _film(reader, node, shader)
        _approximated(reader, node, "Octane's Metallic material")
    pairs = SHARED + (("sheenRoughness", "sheen_roughness"),)
    return _shader(reader, node, "mtlxstandard_surface", pairs, lobes, (
        "specular", "edgeTint", "index", "index2", "index3", "metallicMode", "sheen",
        "filmwidth", "diffuse"))


def read_mix_material(reader, node, role):
    """A Mix material: amount 1 shows material1, so material1 is the foreground (measured)."""
    _displacement(reader, node)    # the mix's own wins over its materials'
    feeds = _feeds(node)
    first, second = (reader.read(feeds[name][0], "surface", feeds[name][1])
                     if name in feeds else None for name in ("material1", "material2"))
    if first is None or second is None:
        reader.report.skip('"%s" mixes a material that did not convert - the other one '
                           "stands alone" % node.name())
        return first or second
    mix = reader.make("mtlxmix", node)
    reader.wire(mix, "fg", first)
    reader.wire(mix, "bg", second)
    reader.carry(node, "amount", mix, "mix", "float")
    return mix


def _colour_space(reader, node, image, role) -> None:
    """mtlximage's colour space from Octane's own; a normal map always reads Raw."""
    if role == "vector3":
        _set(image, "filecolorspace", "Raw")
        return
    space = _token(node, "colorSpace")
    if space == "NAMED_COLOR_SPACE_LINEAR_SRGB_WITH_LEGACY_GAMMA":
        gamma = round(_values(node, "gamma")[0], 2) if _values(node, "gamma") else 1.0
        target = LEGACY_GAMMA.get(gamma)
        if target is None:
            reader.report.approximate('"%s": legacy gamma %g has no colour space of its own - '
                                      "read as linear" % (node.name(), gamma))
            target = "lin_rec709"
    else:
        target = COLOUR_SPACES.get(space)
    if target is None:
        reader.report.skip('"%s" reads its file as %s, which mtlximage has no colour space '
                           "for - left at the image's default" % (node.name(), space))
        return
    _set(image, "filecolorspace", target)


def _texcoord(reader, node, image) -> None:
    """Octane's projection and 2D transform as mtlxtexcoord and mtlxplace2d on the image."""
    feeds = _feeds(node)
    projection, transform = feeds.get("projection"), feeds.get("transform")
    if projection is None and transform is None:
        return
    texcoord = reader.make("mtlxtexcoord", role="")
    _set(texcoord, "signature", "vector2")
    if projection is not None:
        if projection[0].type().name() == "octane::NT_PROJ_UVW":
            uv_set = _values(projection[0], "uvSet")
            _set(texcoord, "index", max(0, int(uv_set[0]) - 1) if uv_set else 0)
        else:
            reader.report.skip('"%s" is a %s projection, which has no MaterialX form - the '
                               "image reads the mesh UVs" % (projection[0].name(),
                                                             projection[0].type().name()))
    if transform is None:
        reader.wire(image, "texcoord", (texcoord, 0))
        return
    if transform[0].type().name() != "octane::NT_TRANSFORM_2D":
        reader.report.skip('"%s" is a %s, which has no MaterialX form - the image is placed '
                           "as it was" % (transform[0].name(), transform[0].type().name()))
        reader.wire(image, "texcoord", (texcoord, 0))
        return
    place = reader.make("mtlxplace2d", transform[0])
    place.parmTuple("pivot").set((0.5, 0.5))    # Octane scales and turns about the UV centre
    _set(place, "operationorder", "1")    # translate, rotate, scale: Octane's order (measured)
    reader.carry(transform[0], "scale", place, "scale", "vector2")
    reader.carry(transform[0], "rotation", place, "rotate", "float")
    reader.carry(transform[0], "translation", place, "offset", "vector2")
    reader.wire(place, "texcoord", (texcoord, 0))
    reader.wire(image, "texcoord", (place, 0))


def read_image(reader, node, role):
    """Octane's three image textures as mtlximage, with its space, borders, power and invert."""
    alpha = node.type().name() == "octane::NT_TEX_ALPHAIMAGE"
    signature = "color4" if alpha else SIGNATURE.get(role, "color3")
    image = reader.make("mtlximage", node)
    _set(image, "signature", signature)
    _set(image, "file", node.parm("A_FILENAME").unexpandedString())
    _colour_space(reader, node, image, role)
    for axis in ("U", "V"):
        mode, fill = ADDRESS.get(_token(node, "borderMode" + axis), ("periodic", None))
        _set(image, axis.lower() + "addressmode", mode)
        if fill is not None:
            _set_poly_parm(image, "default", (fill,) * 4, signature)
    _texcoord(reader, node, image)
    made = (image, 0)
    if alpha:
        extract = reader.make("mtlxextract", node)
        _set(extract, "signature", "color4")
        reader.wire(extract, "in", made)
        _set(extract, "index", 3)
        made = _widen(reader, (extract, 0), role)
    if _values(node, "invert") and _values(node, "invert")[0]:    # Octane inverts, then powers
        invert = reader.make("mtlxinvert", node, role)
        reader.wire(invert, "in", made)
        made = (invert, 0)
        if not (_values(node, "linearSpaceInvert") and _values(node, "linearSpaceInvert")[0]):
            reader.report.approximate('"%s" inverts before linearising - MaterialX inverts '
                                      "the linear value" % node.name())
    power = _feeds(node).get("power")
    if power is not None or (_values(node, "power") and _values(node, "power")[0] != 1.0):
        multiply = reader.make("mtlxmultiply", node, role)
        reader.wire(multiply, "in1", made)
        reader.carry(node, "power", multiply, "in2", role, poly=True)
        made = (multiply, 0)
    return made


def _widen(reader, made, role):
    """A single value as three channels when the input wants colour or a vector."""
    if role == "float":
        return made
    combine = reader.make("mtlxcombine3", made[0], role)
    for name in ("in1", "in2", "in3"):
        reader.wire(combine, name, made)
    return (combine, 0)


def read_rgb(reader, node, role):
    values = _values(node, "A_VALUE")
    constant = reader.make("mtlxconstant", node, role)
    _set_poly_parm(constant, "value", values[:1] if role == "float" else values,
                   SIGNATURE.get(role, "color3"))
    return constant


def read_float(reader, node, role):
    value = _values(node, "A_VALUE")[:1] or (0.0,)
    constant = reader.make("mtlxconstant", node, role)
    _set_poly_parm(constant, "value", value * (1 if role == "float" else 3),
                   SIGNATURE.get(role, "color3"))
    return constant


def _two(kind, first, second):
    """A two-input node: Octane's `first` and `second` onto MaterialX's in1 and in2."""
    def read(reader, node, role):
        made = reader.make(kind, node, role)
        reader.carry(node, first, made, "in1", role, poly=True)
        reader.carry(node, second, made, "in2", role, poly=True)
        return made
    return read


def read_mix_texture(reader, node, role):
    """A Mix texture: amount 0 shows texture1, MaterialX's background (measured)."""
    mix = reader.make("mtlxmix", node, role)
    reader.carry(node, "texture1", mix, "bg", role, poly=True)
    reader.carry(node, "texture2", mix, "fg", role, poly=True)
    reader.carry(node, "amount", mix, "mix", "float")
    return mix


def read_invert(reader, node, role):
    invert = reader.make("mtlxinvert", node, role)
    reader.carry(node, "texture", invert, "in", role, poly=True)
    return invert


def read_clamp(reader, node, role):
    clamp = reader.make("mtlxclamp", node, role)
    reader.carry(node, "input", clamp, "in", role, poly=True)
    reader.carry(node, "min", clamp, "low", role, poly=True)
    reader.carry(node, "max", clamp, "high", role, poly=True)
    return clamp


def read_range(reader, node, role):
    ranged = reader.make("mtlxrange", node, role)
    reader.carry(node, "input", ranged, "in", role, poly=True)
    for octane_name, mtlx_name in (("inputMin", "inlow"), ("inputMax", "inhigh"),
                                   ("outputMin", "outlow"), ("outputMax", "outhigh")):
        reader.carry(node, octane_name, ranged, mtlx_name, role, poly=True)
    _set(ranged, "doclamp", 1 if _values(node, "clamp") and _values(node, "clamp")[0] else 0)
    curve = _token(node, "interpolationType")
    if curve and curve != "0":
        reader.report.approximate('"%s" interpolates by %s - MaterialX\'s range is linear' % (
            node.name(), dict((("1", "steps"), ("2", "smoothstep"), ("3", "smootherstep"),
                               ("4", "posterize"))).get(curve, curve)))
    return ranged


def _convert_space(reader, node, made, role):
    """A channel picker's or merger's colour space conversion, where MaterialX has one."""
    conversion = _token(node, "colorSpaceConversion")
    kind = {"1": "mtlxrgbtohsv", "2": "mtlxhsvtorgb"}.get(conversion)
    if kind is not None:
        converted = reader.make(kind, node, "color3")
        reader.wire(converted, "in", made)
        return (converted, 0)
    if conversion and conversion != "0":
        reader.report.skip('"%s" converts colour spaces (%s), which has no MaterialX node - '
                           "the channels cross unconverted" % (node.name(), conversion))
    return made


def read_channel_pick(reader, node, role):
    fed = _feeds(node).get("texture")
    if fed is None:
        return None
    source = reader.read(fed[0], "color3", fed[1])
    if source is None:
        return None
    source = _convert_space(reader, node, source, role)
    extract = reader.make("mtlxextract", node)
    _set(extract, "signature", "color3")
    reader.wire(extract, "in", source)
    _set(extract, "index", int(_token(node, "colorChannel") or 0))
    return _widen(reader, (extract, 0), role)


def _merge(names):
    def read(reader, node, role):
        if role == "float":
            fed = _feeds(node).get(names[0])
            return reader.read(fed[0], "float", fed[1]) if fed is not None else None
        combine = reader.make("mtlxcombine3", node, role)
        for octane_name, mtlx_name in zip(names, ("in1", "in2", "in3")):
            reader.carry(node, octane_name, combine, mtlx_name, "float")
        return _convert_space(reader, node, (combine, 0), role)
    return read


def read_pass_through(reader, node, role):
    fed = _feeds(node).get("input")
    return reader.read(fed[0], role, fed[1]) if fed is not None else None


def read_math_binary(reader, node, role):
    operation = _token(node, "operationType")
    if operation == "6":    # log_b(a) = ln(a) / ln(b)
        logs = []
        for operand in ("texture1", "texture2"):
            ln = reader.make("mtlxln", node, role)
            _operand(reader, node, operand, ln, "in", role)
            logs.append((ln, 0))
        divide = reader.make("mtlxdivide", node, role)
        reader.wire(divide, "in1", logs[0])
        reader.wire(divide, "in2", logs[1])
        return divide
    kind = BINARY.get(operation)
    if kind is None:
        reader.report.skip('"%s" runs operation %s, which has no conversion mapping yet' % (
            node.name(), operation))
        return None
    vector = kind in ("mtlxcrossproduct", "mtlxdotproduct")
    made = reader.make(kind, node, "vector3" if vector else role)
    first, second = (("iny", "inx") if kind == "mtlxatan2" else ("in1", "in2"))
    _operand(reader, node, "texture1", made, first, "vector3" if vector else role)
    _operand(reader, node, "texture2", made, second, "vector3" if vector else role)
    if operation == "5":
        reader.report.approximate('"%s" keeps the sign of a negative remainder - MaterialX\'s '
                                  "modulo is always positive" % node.name())
    if kind == "mtlxdotproduct":
        return _widen(reader, (made, 0), role)
    return made


def _operand(reader, node, octane_name, target, mtlx_name, role) -> None:
    """An operand: its wire, or the value its typed slot holds (texture1_float, ...)."""
    fed = _feeds(node).get(octane_name)
    if fed is not None:
        reader.wire(target, mtlx_name, reader.read(fed[0], role, fed[1]))
        return
    slot = {"float": "_float", "color3": "_color", "vector3": "_vector"}.get(role, "_float")
    values = _values(node, octane_name + slot)
    if values:
        _set_poly_parm(target, mtlx_name, values, SIGNATURE.get(role, role))


def read_math_unary(reader, node, role):
    operation = _token(node, "operationType")
    fed = _feeds(node).get("texture")
    if fed is None:
        return None
    value = reader.read(fed[0], role, fed[1])
    if value is None:
        return None
    if operation in UNARY:
        made = reader.make(UNARY[operation], node, role)
        reader.wire(made, "in", value)
        return made
    if operation in SCALED:
        made = reader.make("mtlxmultiply", node, role)
        reader.wire(made, "in1", value)
        _set_poly_parm(made, "in2", (SCALED[operation],) * 3, SIGNATURE.get(role, role))
        return made
    if operation in ("16", "17"):    # log 2 and log 10 as ln(x) / ln(base)
        ln = reader.make("mtlxln", node, role)
        reader.wire(ln, "in", value)
        divide = reader.make("mtlxdivide", node, role)
        reader.wire(divide, "in1", (ln, 0))
        base = math.log(2.0 if operation == "16" else 10.0)
        _set_poly_parm(divide, "in2", (base,) * 3, SIGNATURE.get(role, role))
        return divide
    reader.report.skip('"%s" runs operation %s, which has no conversion mapping yet' % (
        node.name(), operation))
    return None


def read_compare(reader, node, role):
    kind, a_first, true_first = COMPARE.get(_token(node, "operationType"), (None, True, True))
    if kind is None:
        return None
    made = reader.make(kind, node, role)
    values = ("value1", "value2") if a_first else ("value2", "value1")
    _operand(reader, node, "texture1", made, values[0], "float")
    _operand(reader, node, "texture2", made, values[1], "float")
    results = ("in1", "in2") if true_first else ("in2", "in1")
    reader.carry(node, "texture3", made, results[0], role, poly=True)
    reader.carry(node, "texture4", made, results[1], role, poly=True)
    return made


def read_gradient(reader, node, role):
    """A gradient map as a chain of ranged mixes, one per pair of keys, linear between them."""
    ramp = node.parm("octane_gradient").evalAsRamp() if node.parm("octane_gradient") else None
    keys = sorted(zip(ramp.keys(), (tuple(v) for v in ramp.values()))) if ramp else []
    fed = _feeds(node).get("input")
    driver = reader.read(fed[0], "float", fed[1]) if fed is not None else None
    if not keys:
        return None
    made = reader.make("mtlxconstant", node, role)
    _set_poly_parm(made, "value", keys[0][1], SIGNATURE.get(role, "color3"))
    made = (made, 0)
    for (low, _before), (high, colour) in zip(keys, keys[1:]):
        ranged = reader.make("mtlxrange", node, "float")
        if driver is not None:
            reader.wire(ranged, "in", driver)
        _set(ranged, "inlow", low)
        _set(ranged, "inhigh", high if high > low else low + 1e-6)
        _set(ranged, "doclamp", 1)
        mix = reader.make("mtlxmix", node, role)
        reader.wire(mix, "bg", made)
        _set_poly_parm(mix, "fg", colour, SIGNATURE.get(role, "color3"))
        reader.wire(mix, "mix", (ranged, 0))
        made = (mix, 0)
    if _token(node, "gradientInterpolationType") not in ("", "2"):
        reader.report.approximate('"%s" interpolates its keys other than linearly - they '
                                  "cross as linear" % node.name())
    return made


def read_color_correction(reader, node, role):
    """The texture passes through; each correction set away from neutral is said."""
    reader.said_unless_default(
        node, ("brightness", "invert", "hue", "saturation", "gamma", "contrast", "gain",
               "exposure", "mask"),
        "a colour correction with no faithful MaterialX twin, so the texture crosses "
        "uncorrected")
    fed = _feeds(node).get("texture")
    return reader.read(fed[0], role, fed[1]) if fed is not None else None


def read_normal(reader, node, role):
    normal = reader.make("mtlxnormal", node)
    space = _token(node, "coordinateSystem")
    _set(normal, "space", {"0": "world", "2": "object"}.get(space, "world"))
    if space not in ("0", "2"):
        reader.report.approximate('"%s" reads the normal in a space MaterialX has no node for '
                                  "- read in world space" % node.name())
    return normal


def read_uv(reader, node, role):
    texcoord = reader.make("mtlxtexcoord", node)
    _set(texcoord, "signature", "vector2")
    if role == "float":
        extract = reader.make("mtlxextract", node)
        _set(extract, "signature", "vector2")
        reader.wire(extract, "in", (texcoord, 0))
        return extract
    combine = reader.make("mtlxcombine3", node, role)
    for index, name in enumerate(("in1", "in2")):
        extract = reader.make("mtlxextract", node)
        _set(extract, "signature", "vector2")
        reader.wire(extract, "in", (texcoord, 0))
        _set(extract, "index", index)
        reader.wire(combine, name, (extract, 0))
    return combine


def read_displacement(reader, node, role):
    """Texture or vertex displacement: (texture - mid level) x height, as mtlxdisplacement."""
    vector = (node.type().name() == "octane::NT_VERTEX_DISPLACEMENT"
              and _token(node, "displacementMapType") == "0")
    displacement = reader.make("mtlxdisplacement", node, "vector3" if vector else "float")
    fed = _feeds(node).get("texture")
    if fed is not None:
        height = reader.read(fed[0], "vector3" if vector else "float", fed[1])
        level = _values(node, "black_level")[0] if _values(node, "black_level") else 0.0
        if height is not None and level and not vector:
            shifted = reader.make("mtlxsubtract", node, "float")
            reader.wire(shifted, "in1", height)
            _set(shifted, "in2", level)
            height = (shifted, 0)
        reader.wire(displacement, "displacement", height)
    reader.carry(node, "amount", displacement, "scale", "float")
    if vector:
        reader.report.approximate('"%s" displaces by a vector map - its axes and space are '
                                  "assumed to be MaterialX's" % node.name())
    for name, default in QUALITY.items():
        if _token(node, name) not in ("", default):
            reader.report.skip('"%s" sets %s, an Octane displacement setting with no MaterialX '
                               "form" % (node.name(), name))
    return displacement


READERS = {    # Octane node type -> its reader; anything absent is reported, never guessed
    "octane::NT_MAT_STANDARD_SURFACE": read_standard,
    "octane::NT_MAT_OPEN_PBR_SURFACE": read_open_pbr,
    "octane::NT_MAT_UNIVERSAL": read_universal,
    "octane::NT_MAT_DIFFUSE": read_diffuse,
    "octane::NT_MAT_GLOSSY": read_glossy,
    "octane::NT_MAT_SPECULAR": read_specular,
    "octane::NT_MAT_METAL": read_metal,
    "octane::NT_MAT_MIX": read_mix_material,
    "octane::NT_TEX_IMAGE": read_image,
    "octane::NT_TEX_FLOATIMAGE": read_image,
    "octane::NT_TEX_ALPHAIMAGE": read_image,
    "octane::NT_TEX_RGB": read_rgb,
    "octane::NT_TEX_FLOAT": read_float,
    "octane::NT_TEX_MIX": read_mix_texture,
    "octane::NT_TEX_MULTIPLY": _two("mtlxmultiply", "texture1", "texture2"),
    "octane::NT_TEX_ADD": _two("mtlxadd", "texture1", "texture2"),
    "octane::NT_TEX_SUBTRACT": _two("mtlxsubtract", "texture1", "texture2"),
    "octane::NT_TEX_INVERT": read_invert,
    "octane::NT_TEX_CLAMP": read_clamp,
    "octane::NT_TEX_RANGE": read_range,
    "octane::NT_TEX_CHANNEL_PICK": read_channel_pick,
    "octane::NT_TEX_CHANNEL_MERGE": _merge(("texture1", "texture2", "texture3")),
    "octane::NT_TEX_FLOATS_TO_COLOR": _merge(("input1", "input2", "input3")),
    "octane::NT_TEX_FLOAT3_TO_COLOR": read_pass_through,
    "octane::NT_TEX_MATH_BINARY": read_math_binary,
    "octane::NT_TEX_MATH_UNARY": read_math_unary,
    "octane::NT_TEX_COMPARE": read_compare,
    "octane::NT_TEX_GRADIENT": read_gradient,
    "octane::NT_TEX_COLORCORRECTION": read_color_correction,
    "octane::NT_TEX_NORMAL": read_normal,
    "octane::NT_TEX_UV": read_uv,
    "octane::NT_DISPLACEMENT": read_displacement,
    "octane::NT_VERTEX_DISPLACEMENT": read_displacement,
}


def to_materialx(shader: hou.Node | None, builder: hou.Node, report) -> tuple:
    """Inside `builder`: (surface, displacement) in MaterialX for Octane's `shader`."""
    if shader is None:
        report.skip("no Octane material found inside the saved network")
        return None, None
    reader = Reader(builder, report)
    made = reader.read(shader, "surface")
    if made is None:
        return None, None
    surface = made[0]
    surface.setName(wording.sanitize_usd_path(report.mat_name) or "surface", unique_name=True)
    return surface, reader.displacement
