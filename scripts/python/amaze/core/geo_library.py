"""What counts as a geometry file and how one loads; the longest extension match wins."""

from amaze.helpers import hostos

GEO_EXTENSIONS = (
    ".bgeo.sc",
    ".bgeo.gz",
    ".bgeo",
    ".geo",
    ".obj",
    ".fbx",
    ".abc",
    ".usd",
    ".usda",
    ".usdc",
    ".ply",
    ".stl",
)


CACHE_EXTENSIONS = (
    ".bgeo.sc",
    ".vdb",
)


def matched_extension(name: str) -> str:
    """The extension entry the filename ends with, longest first, or empty."""
    return hostos.matched_extension(name, GEO_EXTENSIONS)


def is_cache(name: str) -> bool:
    """Is this a cache file, and so not something to render unasked?"""
    return bool(hostos.matched_extension(name, CACHE_EXTENSIONS))


def loader_sop_for(path: str) -> str:
    """The SOP that reads a geometry file; FBX has none and shows as a missing thumbnail."""
    lowered = path.lower()
    if lowered.endswith(".abc"):
        return "alembic"
    if lowered.endswith((".usd", ".usda", ".usdc")):
        return "usdimport"
    return "file"
