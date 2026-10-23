"""What a saved material's own files say, read as text: its builder type and its shader type."""

import re

from amaze.core import material

LOP_CAPABLE_NODE_TYPES = (
    "rs_usd_material_builder",  # Redshift USD material builder
    "octane_solaris_material_builder",  # Octane Solaris material builder
)

SHADER_TYPE_LABELS = {    # renderer -> (type in the saved .mat, label); the first one found wins
    "Redshift": (
        ("redshift::ToonMaterial", "Toon"),
        ("redshift::OpenPBRMaterial", "PBR"),
        ("redshift::StandardMaterial", "Standard"),
        ("redshift::MaterialBlender", "Blend"),
        ("redshift::Hair", "Hair"),
        ("redshift::Volume", "Volume"),
        ("redshift::rsOSL", "OSL"),
    ),
    "Octane": (    # what mixes or layers first: a layer type starts with a material's ▸r/octane-builder
        ("octane::NT_MAT_MIX", "Mix"),
        ("octane::NT_MAT_LAYER", "Layered"),
        ("octane::NT_MAT_COMPOSITE", "Composite"),
        ("octane::NT_MAT_STANDARD_SURFACE", "Standard Surface"),
        ("octane::NT_MAT_OPEN_PBR_SURFACE", "OpenPBR"),
        ("octane::NT_MAT_UNIVERSAL", "Universal"),
        ("octane::NT_MAT_TOON", "Toon"),
        ("octane::NT_MAT_HAIR", "Hair"),
        ("octane::NT_MAT_METAL", "Metallic"),
        ("octane::NT_MAT_GLOSSY", "Glossy"),
        ("octane::NT_MAT_SPECULAR", "Specular"),
        ("octane::NT_MAT_DIFFUSE", "Diffuse"),
        ("octane::NT_MAT_SHADOW_CATCHER", "Shadow Catcher"),
        ("octane::NT_MAT_CLIPPING", "Clipping"),
        ("octane::NT_MAT_PORTAL", "Portal"),
        ("octane::NT_MAT_NULL", "Null"),
        ("mtlxstandard_surface", "MaterialX"),
        ("mtlxopen_pbr_surface", "MaterialX"),
    ),
}


def get_saved_node_type(preferences, mat: material.Material) -> str:
    """The builder type in the .interface's first createNode, or ""."""
    iface = material.payload_path(
        preferences, mat.mat_id, ".interface"
    )
    try:
        with open(iface, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return ""
    match = re.search(r'createNode\(\s*[\'"]([^\'"]+)[\'"]', text)
    return match.group(1) if match else ""


def shader_type_table(renderer) -> tuple:
    """The label table for a stored renderer, or () when it has none."""
    name = str(renderer or "")
    return next((table for family, table in SHADER_TYPE_LABELS.items()
                 if family in name), ())


def get_shader_type_label(preferences, mat: material.Material) -> str:
    """Shader-type label by text search of the .mat. ▸r/save-shape"""
    table = shader_type_table(mat.renderer)
    if not table:
        return ""
    mat_path = material.payload_path(
        preferences, mat.mat_id, preferences.ext
    )
    try:
        with open(mat_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return ""
    text = data.decode("latin-1")
    for needle, label in table:
        if ("type = " + needle) in text:
            return label
    return ""
