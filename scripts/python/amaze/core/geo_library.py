"""What counts as a geometry file, and how one loads.

The Geometry section merged into the File section on 2026-07-31
(core/file_library.py), taking its models with it - the render-pass
behaviour lives in FileFiles._render_geo_misses now. What stays here is
the extension knowledge both that model and the import path consume:
which files are geometry, which entry matched (longest wins, so
'x.bgeo.sc' is '.bgeo.sc'), and which SOP loads each format.
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


#: What a CACHE is written as, and so what gets no thumbnail of its
#: own. The File Cache SOP's documented output: SideFX's help says the
#: default saves as
#: `<Base Name>/v<Version>/<Base Name>_v<Version>.$F4.bgeo.sc` in a
#: `geo` folder, and that the only other File Type is `.vdb` - "if all
#: the primitives in the input are always VDB volumes". There is no
#: third option.
#:
#: `.sc` is BLOSC COMPRESSION, not a cache marker (Houdini's own
#: `HOUDINI_BLOSC_COMPRESSION_CODEC` is "the compression codec to use
#: when compressing with BLOSC for .sc"), so this is a decision about
#: how these files arise in practice rather than a fact about the
#: format: a compressed .bgeo is what the File Cache SOP writes, and a
#: hand-saved single asset is a plain .bgeo. The cost of the decision
#: is a single asset deliberately saved compressed, which gets no
#: thumbnail until one is asked for.
CACHE_EXTENSIONS = (
    ".bgeo.sc",
    ".vdb",
)


def matched_extension(name: str) -> str:
    """The GEO_EXTENSIONS entry the filename ends with (longest wins,
    so 'x.bgeo.sc' reports '.bgeo.sc', not '.bgeo'), or ''."""
    return hostos.matched_extension(name, GEO_EXTENSIONS)


def is_cache(name: str) -> bool:
    """Is this a cache file, and so not something to render unasked?

    Longest-wins matching is what makes this answerable at all: a
    '.bgeo.sc' reports '.bgeo.sc' rather than '.bgeo', so the two
    cannot be confused by a plain endswith on the shorter one.
    """
    return bool(hostos.matched_extension(name, CACHE_EXTENSIONS))


def loader_sop_for(path: str) -> str:
    """The SOP type that reads the given geometry file: Alembic and USD
    have dedicated loaders, everything else goes through the File SOP.
    (FBX has no SOP-level loader at all - the File SOP fails to cook
    it, which surfaces as a missing thumbnail / empty import rather
    than an error; a real FBX import pipeline is a future chunk.)"""
    lowered = path.lower()
    if lowered.endswith(".abc"):
        return "alembic"
    if lowered.endswith((".usd", ".usda", ".usdc")):
        return "usdimport"
    return "file"
