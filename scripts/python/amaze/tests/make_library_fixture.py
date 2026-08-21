"""Build the tracked library fixture - six materials, their thumbnails and library.json - as `USER=amaze hython make_library_fixture.py`, the neutral account being something Houdini resolves at startup and this script cannot set for itself (▸r/author-stamp); the output is COMMITTED so the suite generates nothing at test time, and this exits 1 naming the file if anything it wrote carries an account name, a machine name or a home directory."""
import json
import os
import shutil
import sys

import hou

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import branding                                 # noqa: E402
from amaze.core import database                            # noqa: E402
from amaze.render import nodes as nodes_mod                # noqa: E402
from amaze.tests import make_file_fixtures as guard        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets", "library")

CATEGORIES = ["_All", "Karma_Mats", "usds"]

MATERIALS = (   # (id, name, base colour) - ids and names are the ones the suite already cites, so this is a drop-in replacement; the colours differ only so six tiles are tellable apart by eye, nothing asserts on them
    ("139888336268658010", "Metal", (0.56, 0.57, 0.58)),
    ("139888336377945550", "Bricks", (0.52, 0.24, 0.18)),
    ("139888336889814930", "gold", (1.00, 0.77, 0.34)),
    ("139888337058723210", "glass", (0.78, 0.87, 0.90)),
    ("139888337254621540", "bubblegum", (0.94, 0.55, 0.70)),
    ("139888337459841200", "plastic", (0.20, 0.42, 0.72)),
)

DATE = "2026-01-27 20:07:06"   # a FIXED date: a generated timestamp would rewrite every row on every run and the rows are what the suite reads


def sentinel_row() -> dict:
    """The id -1 row the real format carries at the head of the list."""
    return {"id": -1, "name": "", "categories": [""], "tags": [""],
            "favorite": 0, "date": -1, "renderer": "", "usd": 0,
            "builder": 0}


def asset_row(asset_id: str, name: str) -> dict:
    return {"id": asset_id, "name": name, "categories": ["Karma_Mats"],
            "tags": [""], "favorite": False, "date": DATE,
            "renderer": "MaterialX", "usd": 1, "builder": 0}


def build_material(parent: hou.Node, name: str, colour) -> hou.Node:
    """One Karma builder holding one mtlxstandard_surface, built and wired by the app's own two functions so the saved shape is the shape the app writes. `parent` must be /mat: under /stage the builder is a LOP subnet and no mtlx VOP type is valid inside it."""
    builder = nodes_mod.make_karma_builder(parent, name)
    shader = builder.createNode("mtlxstandard_surface", name + "_surface")
    shader.parmTuple("base_color").set(colour)
    shader.parm("specular_roughness").set(0.35)
    nodes_mod.wire_builder_output(builder, shader)
    return builder


def save_pair(builder: hou.Node, asset_id: str, folder: str) -> None:
    """The .mat + .interface unit, written the way render/nodes.py writes it. ▸p/asset-write-unit"""
    with open(os.path.join(folder, asset_id + ".interface"), "w",
              encoding="utf-8") as handle:
        handle.write(builder.asCode())
    builder.saveItemsToFile(builder.allItems(),
                            os.path.join(folder, asset_id + ".mat"))


def make_thumbnail(path: str, colour) -> None:
    """A 256x256 swatch. Deterministic and depicting nothing - the grid only has to have a real image to paint, and a Karma render here would make this script depend on a working renderer."""
    from PySide6 import QtGui
    image = QtGui.QImage(256, 256, QtGui.QImage.Format.Format_ARGB32)
    top = QtGui.QColor.fromRgbF(*colour)
    for y in range(256):
        shade = 0.55 + 0.45 * (1.0 - y / 255.0)
        row = QtGui.QColor.fromRgbF(*[min(1.0, c * shade) for c in colour])
        for x in range(256):
            image.setPixelColor(x, y, row if (x + y) % 64 else top)
    image.save(path, "PNG")


def main() -> int:
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "mat"))
    os.makedirs(os.path.join(OUT, "img"))

    hou.hipFile.clear(suppress_save_prompt=True)
    scratch = guard.neutral_scratch("library")
    guard.neutral_scene_vars(scratch)
    parent = hou.node("/mat")
    written = []
    for asset_id, name, colour in MATERIALS:
        builder = build_material(parent, name, colour)
        save_pair(builder, asset_id, os.path.join(OUT, "mat"))
        thumb = os.path.join(OUT, "img", asset_id + ".png")
        make_thumbnail(thumb, colour)
        builder.destroy()
        written += [os.path.join(OUT, "mat", asset_id + ".mat"),
                    os.path.join(OUT, "mat", asset_id + ".interface"),
                    thumb]
        print("%s  %s" % (asset_id, name))

    document = {"version": database.SCHEMA_VERSION,   # STAMPED CURRENT, which the corpus this replaces was not: with no key the loader reads 1, finds no `_MIGRATIONS` step for it (the chain starts at 4) and latches `_migration_incomplete`, so every test ran against a library in a broken-chain state no real one is in. The chain has its own tests in test_upgrade_tool - it does not want incidental cover here
                "format": branding.LIBRARY_FORMAT,
                "categories": CATEGORIES, "tags": [],
                "assets": [sentinel_row()]
                + [asset_row(i, n) for i, n, _c in MATERIALS]}
    index = os.path.join(OUT, "library.json")
    with open(index, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=1)
    written.append(index)
    shutil.rmtree(guard.SCRATCH_ROOT, ignore_errors=True)

    total = sum(os.path.getsize(p) for p in written if os.path.isfile(p))
    print("\n%d files, %.1f KB total" % (len(written), total / 1024.0))
    redacted = guard.redact_written(written)
    print("redacted %d stamped identit%s"
          % (redacted, "y" if redacted == 1 else "ies"))
    carried = guard.verify_no_identity(written)
    if carried:
        print("REFUSED: %d finding(s) - fix the writer above" % carried)
        return 1
    print("verified: nothing in the fixture carries an identity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
