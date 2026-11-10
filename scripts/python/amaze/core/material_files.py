"""What a saved material's own files say, read as text: its builder type and its shader type."""

import json
import os
import re

from amaze.core import material, renderers

LOP_CAPABLE_NODE_TYPES = tuple(each.usd_builder for each in renderers.ALL if each.usd_builder)

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


_CREATE_NODE = re.compile(rb'createNode\(\s*[\'"]([^\'"]+)[\'"]')
_SIDECAR_TYPE = re.compile(rb'\n  "type": "([^"\\]*)"')    # a top-level key, as `capture_builder` indents it
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)


STALE_SIDECAR_S = 60    # one save writes both files moments apart


def get_saved_node_type(preferences, mat: material.Material) -> str:
    """The builder type the builder sidecar records, else the .interface's first createNode, or ""."""
    iface = material.payload_path(preferences, mat.mat_id, ".interface")
    recorded = _sidecar_type(preferences, mat, iface)
    if recorded:
        return recorded
    try:    # an asset saved before the sidecar
        with open(iface, "rb") as fh:
            text = fh.read(4096)    # the builder's createNode opens the script
            match = _CREATE_NODE.search(text)
            if match is None:
                text += fh.read()
                match = _CREATE_NODE.search(text)
    except OSError:
        return ""
    return match.group(1).decode("utf-8", "replace") if match else ""


def _sidecar_type(preferences, mat: material.Material, iface: str) -> str:
    """The sidecar's `type`, or "" when absent or unusable; per row, so no log and one open."""
    try:
        if _NO_FOLLOW:    # the contained .interface's sibling, never through a link
            stem = iface[:-len(".interface")]
            fh = os.fdopen(os.open(stem + material.BUILDER_SUFFIX, os.O_RDONLY | _NO_FOLLOW), "rb")
        else:
            fh = open(material.payload_path(
                preferences, mat.mat_id, material.BUILDER_SUFFIX), "rb")
        with fh:
            if os.fstat(fh.fileno()).st_mtime < os.stat(iface).st_mtime - STALE_SIDECAR_S:
                return ""    # re-saved by an Amaze that writes no sidecar: the .interface is newer
            data = fh.read()
    except OSError:
        return ""
    match = _SIDECAR_TYPE.search(data)
    if match:
        return match.group(1).decode("utf-8", "replace")
    try:    # written some other way: parse it
        parsed = json.loads(data)
    except ValueError:
        return ""
    kind = parsed.get("type") if isinstance(parsed, dict) else None
    return kind if isinstance(kind, str) else ""


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
