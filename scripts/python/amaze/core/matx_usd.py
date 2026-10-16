"""A USD OpenPBR material as a flat .mtlx for `matx_translate`. ▸r/simready-graph"""

from __future__ import annotations

SURFACE = "ND_open_pbr_surface_surfaceshader"
IMAGE = "ND_tiledimage_"
NORMAL_MAP = "ND_normalmap"
COMBINE = "ND_combine3_vector3"
SEPARATE = "ND_separate3_vector3"
INVERT = "ND_invert_vector3"
IF_EQUAL = "ND_ifequal_"
LABELS = "semantics:labels:material"
AXES = (("in1", "outx"), ("in2", "outy"), ("in3", "outz"))

_MX_TYPES = {    # a USD value type's MaterialX name
    "float": "float", "bool": "boolean", "int": "integer", "color3f": "color3",
    "color4f": "color4", "float2": "vector2", "float3": "vector3",
    "vector3f": "vector3", "normal3f": "vector3", "float4": "vector4",
}
_DATA_TYPES = {"color3": "vector3", "color4": "vector4"}    # a raw colour map reads as data
_DATA_SPACES = ("raw", "linear", "lin_rec709", "scene_linear")    # spaces Karma must not transform


class Unread(ValueError):
    """A shader input driven by something this walk does not translate."""


def _driver(inp):
    """(prim, output name) wired into `inp`, or None when it holds a plain value."""
    found = inp.GetConnectedSources()
    sources = found[0] if isinstance(found, tuple) else found
    if not sources:
        return None
    return sources[0].source.GetPrim(), str(sources[0].sourceName)


def _driving_prim(inp, owner):
    """The prim wired into `inp`; an unwired one is a graph this walk does not know."""
    driven = _driver(inp)
    if driven is None:
        raise Unread("%s.%s is not wired" % (owner.GetName(), inp.GetBaseName()))
    return driven[0]


def _shader_id(prim) -> str:
    from pxr import UsdShade
    return str(UsdShade.Shader(prim).GetIdAttr().Get() or "")


def _value(inp, material):
    """`inp`'s value, read through to the material input it is wired to."""
    driven = _driver(inp)
    if driven is None:
        return inp.Get(), inp.GetAttr()
    prim, name = driven
    if prim != material.GetPrim():
        raise Unread("%s is driven by %s" % (inp.GetBaseName(), prim.GetName()))
    source = material.GetInput(name)
    return source.Get(), source.GetAttr()


def _input_value(shader, name, material, fallback=None):
    inp = shader.GetInput(name)
    if not inp:
        return fallback
    value = _value(inp, material)[0]
    return fallback if value is None else value


def _image(prim, material):
    """A tiledimage as (texture spec, None), or (None, its constant) with no file."""
    from pxr import UsdShade
    shader = UsdShade.Shader(prim)
    asset, attr = _value(shader.GetInput("file"), material)
    path = str(getattr(asset, "path", "") or "")
    if not path:
        return None, _input_value(shader, "default", material)
    texcoord = shader.GetInput("texcoord")
    driven = _driver(texcoord) if texcoord else None
    if driven is not None and _input_value(
            UsdShade.Shader(driven[0]), "index", material, 0) != 0:
        raise Unread("%s reads a second UV set" % prim.GetName())
    return {
        "file": path,
        "colorspace": str(attr.GetColorSpace() or ""),
        "type": _shader_id(prim)[len(IMAGE):],
        "tiling": tuple(_input_value(shader, "uvtiling", material, (1.0, 1.0))),
        "offset": tuple(_input_value(shader, "uvoffset", material, (0.0, 0.0))),
    }, None


def _flipped_image(prim, material):
    """The image under a per-channel flip chain, and which channels it flips."""
    from pxr import UsdShade
    if _shader_id(prim).startswith(IMAGE):
        return prim, (False, False, False)
    if _shader_id(prim) != COMBINE:
        raise Unread("a normal map is fed by %s" % prim.GetName())
    combine = UsdShade.Shader(prim)
    images, flips = set(), []
    for name, axis in AXES:
        choice = _driver(combine.GetInput(name))
        if choice is None or not _shader_id(choice[0]).startswith(IF_EQUAL):
            raise Unread("%s.%s is not a flip selector" % (prim.GetName(), name))
        pick = UsdShade.Shader(choice[0])
        same = (bool(_input_value(pick, "value1", material))
                == bool(_input_value(pick, "value2", material)))
        picked = _driver(pick.GetInput("in1" if same else "in2"))    # ifequal answers in1 when equal
        if picked is None or _shader_id(picked[0]) != SEPARATE or picked[1] != axis:
            raise Unread("%s does not pick channel %s" % (choice[0].GetName(), axis))
        source = _driving_prim(UsdShade.Shader(picked[0]).GetInput("in"), picked[0])
        inverted = _shader_id(source) == INVERT
        if inverted:
            amount = _input_value(UsdShade.Shader(source), "amount", material)
            if amount is not None and tuple(amount) != (1.0, 1.0, 1.0):
                raise Unread("%s inverts by %s" % (source.GetName(), tuple(amount)))
            source = _driving_prim(UsdShade.Shader(source).GetInput("in"), source)
        images.add(source.GetPath())
        flips.append(inverted)
    if len(images) != 1:
        raise Unread("%s mixes channels of %d images" % (prim.GetName(), len(images)))
    return prim.GetStage().GetPrimAtPath(images.pop()), tuple(flips)


def _normal(prim, material):
    """A normalmap as a texture spec with its flips and scale, or None with no texture."""
    from pxr import UsdShade
    shader = UsdShade.Shader(prim)
    driven = _driver(shader.GetInput("in"))
    if driven is None:
        return None
    image_prim, flips = _flipped_image(driven[0], material)
    image, _constant = _image(image_prim, material)
    if image is None:
        return None
    image.update(type="vector3", flip=flips,
                 scale=float(_input_value(shader, "scale", material, 1.0)))
    return image


def material_spec(usda_path: str) -> dict:
    """The material's constants, images and normal maps, off its composed OpenPBR graph."""
    from pxr import Usd, UsdShade
    stage = Usd.Stage.Open(usda_path)
    prim = stage.GetDefaultPrim()
    material = UsdShade.Material(prim)
    shader = material.ComputeSurfaceSource("mtlx")[0]    # one context token, not a list
    if not shader or str(shader.GetIdAttr().Get()) != SURFACE:
        raise ValueError("%s is not an OpenPBR material" % prim.GetName())
    labels = prim.GetAttribute(LABELS)
    spec = {"name": prim.GetName(), "labels": [str(t) for t in (labels.Get() or [])],
            "constants": {}, "images": {}, "normals": {}, "unread": []}
    for inp in shader.GetInputs():
        name = inp.GetBaseName()
        try:
            driven = _driver(inp)
            kind = _shader_id(driven[0]) if driven and driven[0] != prim else ""
            if not kind:
                value = _value(inp, material)[0]
                if value is not None:
                    spec["constants"][name] = (_MX_TYPES.get(str(inp.GetTypeName()), ""), value)
            elif kind.startswith(IMAGE):
                image, constant = _image(driven[0], material)
                if image is not None:
                    spec["images"][name] = image
                elif constant is not None:
                    spec["constants"][name] = (kind[len(IMAGE):], constant)
            elif kind == NORMAL_MAP:
                normal = _normal(driven[0], material)
                if normal is not None:
                    spec["normals"][name] = normal
            else:
                raise Unread("%s is driven by %s" % (name, kind))
        except Unread as why:
            spec["unread"].append(str(why))
    return spec


def texture_files(spec: dict) -> list:
    """Every texture path the material names, as written - relative to its .usda."""
    found = [image["file"] for image in spec["images"].values()]
    found += [normal["file"] for normal in spec["normals"].values()]
    return sorted(set(found))


def _mx_value(mx, kind: str, value):
    if kind in ("color3", "color4", "vector2", "vector3", "vector4"):
        return getattr(mx, kind.capitalize())(*[float(v) for v in value])
    if kind == "boolean":
        return bool(value)
    if kind == "integer":
        return int(value)
    return float(value)


def _add_image(doc, mx, name: str, image: dict):
    """A tiledimage for one map; a raw colour map reads as data, then converts."""
    space = image["colorspace"].lower()
    data = _DATA_TYPES.get(image["type"]) if space in _DATA_SPACES else None
    node = doc.addNode("tiledimage", "tiledimage_" + name, data or image["type"])
    node.setInputValue("file", image["file"], "filename")
    if space == "srgb":
        node.getInput("file").setAttribute("colorspace", "srgb_texture")
    if tuple(image["tiling"]) != (1.0, 1.0):
        node.setInputValue("uvtiling", mx.Vector2(*[float(v) for v in image["tiling"]]))
    if tuple(image["offset"]) != (0.0, 0.0):
        node.setInputValue("uvoffset", mx.Vector2(*[float(v) for v in image["offset"]]))
    if not data:
        return node
    convert = doc.addNode("convert", "convert_" + name, image["type"])
    convert.setConnectedNode("in", node)
    return convert


def _add_normal(doc, mx, name: str, normal: dict):
    """A normal map: its image, the channel flips as multiply-and-add, then a normalmap."""
    node = _add_image(doc, mx, name, normal)
    if any(normal["flip"]):
        sign = doc.addNode("multiply", "flip_" + name, "vector3")
        sign.setConnectedNode("in1", node)
        sign.setInputValue("in2", mx.Vector3(*[-1.0 if f else 1.0 for f in normal["flip"]]))
        node = doc.addNode("add", "unflip_" + name, "vector3")
        node.setConnectedNode("in1", sign)
        node.setInputValue("in2", mx.Vector3(*[1.0 if f else 0.0 for f in normal["flip"]]))
    mapped = doc.addNode("normalmap", "normalmap_" + name, "vector3")
    mapped.setConnectedNode("in", node)
    if normal["scale"] != 1.0:
        mapped.setInputValue("scale", float(normal["scale"]))
    return mapped


def write_mtlx(spec: dict, path: str) -> str:
    """`spec` as a validated .mtlx at `path`; texture paths stay relative to it."""
    import MaterialX as mx
    doc = mx.createDocument()
    surface = doc.addNode("open_pbr_surface", "open_pbr_surface", "surfaceshader")
    for name, (kind, value) in sorted(spec["constants"].items()):
        if kind:
            surface.setInputValue(name, _mx_value(mx, kind, value), kind)
    for name, image in sorted(spec["images"].items()):
        surface.setConnectedNode(name, _add_image(doc, mx, name, image))
    for name, normal in sorted(spec["normals"].items()):
        surface.setConnectedNode(name, _add_normal(doc, mx, name, normal))
    doc.addMaterialNode(mx.createValidName(spec["name"]), surface)
    valid, why = doc.validate()
    if not valid:
        raise ValueError("the translated material is not valid MaterialX: %s" % why)
    mx.writeToXmlFile(doc, path)
    return path
