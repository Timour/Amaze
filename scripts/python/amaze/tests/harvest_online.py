"""Harvest the online VALUES sources into shipped tables.

The two values sources publish numbers rather than textures, and those
numbers are small enough to ship: ~86 PhysicallyBased reference
materials and 62 RGL measurements together are under 40 KB. Shipping
them buys three things at once -

  * the browser paints each tile in its real colour immediately,
  * importing a known material needs no download at all, and
  * the Generator Engine has a corpus of REAL measured materials to
    build from offline (render/generator.py).

    hython tests/harvest_online.py                 # PhysicallyBased
    hython tests/harvest_online.py --reclassify    # RGL metal flags

The RGL table's measured half (colour, roughness) comes from the
BSDF files themselves - see core/bsdf_reader.py and RGLSource; only
its inferred metal flag is recomputed here, since that inference is a
keyword rule that gets corrected from time to time and needs no
network.
"""

import argparse
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

# THREE dirnames: tests/ -> amaze/ -> python/, the directory that
# holds the `amaze` package. The original had four, which lands on
# scripts/ - where amaze is NOT importable - so every one of these
# files silently imported amaze through Houdini's own package path,
# i.e. the INSTALL. The sync-before-test discipline masked it for the
# suite's whole life; it surfaced when a deliberately-unsynced
# sabotage edit failed to change a test's behaviour.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import matx_sources  # noqa: E402

RES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "res"
)

#: Fields worth keeping from the PhysicallyBased dataset: everything
#: that maps onto a surface shader. Deliberately dropped are the
#: physical-but-not-shading fields (density, viscosity, surface
#: tension, acoustic absorption) - real data, no parameter to drive.
PB_FIELDS = (
    "color", "metalness", "roughness", "ior", "specularColor",
    "complexIor", "transmission", "transmissionDepth",
    "transmissionDispersion", "subsurfaceRadius", "thinFilmThickness",
    "thinFilmIor",
)


def harvest_physicallybased() -> dict:
    """The whole PhysicallyBased dataset, trimmed to shading fields."""
    # The LIVE API, explicitly: PhysicallyBasedSource._load() prefers
    # the shipped table now, so harvesting through it would read back
    # the file it is about to write - idempotent only by accident, and
    # lossy the moment the table's shape differs from the API's.
    items = matx_sources.get_json(
        matx_sources.PhysicallyBasedSource.API + "/materials"
    )
    table = {}
    for item in items:
        name = item.get("name")
        if not name:
            continue
        entry = {k: item[k] for k in PB_FIELDS if k in item}
        # Keyed as the API keys it: everything downstream (the
        # browser's category grouping, its search haystack) reads
        # `category`, and a table that renamed the field to `classes`
        # browsed as 86 Uncategorised materials.
        category = item.get("category")
        entry["category"] = (
            list(category) if isinstance(category, (list, tuple))
            else [str(category)] if category else []
        )
        entry["description"] = item.get("description") or ""
        entry["tags"] = [t for t in (item.get("tags") or []) if t]
        table[name] = entry
    return table


def reclassify_rgl() -> int:
    """Recompute the RGL table's INFERRED metal flag from the current
    keyword rule (the measured numbers are never touched). Returns the
    number of entries whose flag changed."""
    path = os.path.join(RES_DIR, matx_sources.RGLSource.TABLE_FILE)
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    changed = 0
    for uid, entry in doc.get("materials", {}).items():
        metal = float(matx_sources.RGLSource.infer_metal(
            uid, entry.get("description", ""), entry.get("color")
        ))
        if metal != entry.get("metalness"):
            print("  %-34s %s -> %s" % (uid, entry.get("metalness"), metal))
            entry["metalness"] = metal
            changed += 1
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=1)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reclassify", action="store_true",
                        help="recompute RGL metal flags, no network")
    args = parser.parse_args()

    if args.reclassify:
        changed = reclassify_rgl()
        print("RGL: %d metal flag(s) changed" % changed)
        return 0

    table = harvest_physicallybased()
    out = os.path.join(RES_DIR, matx_sources.PhysicallyBasedSource.TABLE_FILE)
    payload = {
        "source": "physicallybased.info",
        "licence": matx_sources.PhysicallyBasedSource.licence,
        "materials": table,
    }
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, sort_keys=True)
    metals = sum(1 for e in table.values() if e.get("metalness"))
    trans = sum(1 for e in table.values() if e.get("transmission"))
    sss = sum(1 for e in table.values() if e.get("subsurfaceRadius"))
    print("PhysicallyBased: %d materials (%d metal, %d transmissive, "
          "%d subsurface) -> %s (%d KB)"
          % (len(table), metals, trans, sss, out,
             os.path.getsize(out) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
