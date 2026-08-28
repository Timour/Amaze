"""What counts as a geometry file and how one loads - the extension knowledge the File models and the import path both consume. LONGEST MATCH WINS, so `x.bgeo.sc` reports `.bgeo.sc` rather than `.bgeo`. What counts as a CACHE, and so gets no thumbnail unasked, is a decision about how these files arise rather than a fact about the format. ▸archive/geo_library.py
"""

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
    """Is this a cache file, and so not something to render unasked? Longest-wins matching is what makes it answerable - a plain `endswith` on the shorter extension confuses the two."""
    return bool(hostos.matched_extension(name, CACHE_EXTENSIONS))


def loader_sop_for(path: str) -> str:
    """The SOP that reads a geometry file - Alembic and USD have dedicated loaders, everything else goes through the File SOP. FBX has NO SOP-level loader, and surfaces as a missing thumbnail rather than an error."""
    lowered = path.lower()
    if lowered.endswith(".abc"):
        return "alembic"
    if lowered.endswith((".usd", ".usda", ".usdc")):
        return "usdimport"
    return "file"
