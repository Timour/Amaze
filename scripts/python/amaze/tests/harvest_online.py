"""Harvests the online VALUES sources into shipped tables, so a tile paints in its real colour with no download and the generator has a corpus offline. Only the RGL table's INFERRED metal flag is recomputed here - its measured half comes from the BSDF files.  `hython tests/harvest_online.py [--reclassify]`  ▸archive/harvest_online.py"""

import argparse
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import matx_sources  # noqa: E402

RES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "res"
)

PB_FIELDS = (
    "color", "metalness", "roughness", "ior", "specularColor",
    "complexIor", "transmission", "transmissionDepth",
    "transmissionDispersion", "subsurfaceRadius", "thinFilmThickness",
    "thinFilmIor",
)


def harvest_physicallybased() -> dict:
    """The whole PhysicallyBased dataset, trimmed to shading fields. Reads the LIVE API, never the source's loader, which prefers the shipped table and would read back the file this is about to write - and keys each entry as the API keys it."""
    items = matx_sources.get_json(
        matx_sources.PhysicallyBasedSource.API + "/materials"
    )
    table = {}
    for item in items:
        name = item.get("name")
        if not name:
            continue
        entry = {k: item[k] for k in PB_FIELDS if k in item}
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
    """Recomputes the RGL table's INFERRED metal flag from the current keyword rule, never touching the measured numbers. Answers how many changed."""
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


def reread_rgl() -> int:
    """Re-reads every RGL measurement's roughness and colours from its file, metalness kept."""
    path = os.path.join(RES_DIR, matx_sources.RGLSource.TABLE_FILE)
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    folder = tempfile.mkdtemp(prefix="amaze_rgl_harvest_")
    changed = 0
    try:
        for uid, entry in sorted(doc.get("materials", {}).items()):
            target = os.path.join(folder, uid + "_rgb.bsdf")
            matx_sources.download("%s/%s/%s_rgb.bsdf"
                                  % (matx_sources.RGLSource.CDN, uid, uid), target)
            values, _note = matx_sources.RGLSource.values_from_bsdf(target, uid)
            for key in ("roughness", "color", "specularColor"):
                if key in values and values[key] != entry.get(key):
                    print("  %-34s %-13s %s -> %s" % (uid, key, entry.get(key), values[key]))
                    entry[key] = values[key]
                    changed += 1
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=1)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reclassify", action="store_true",
                        help="recompute RGL metal flags, no network")
    parser.add_argument("--rgl", action="store_true",
                        help="re-read every RGL roughness and colour from its measurement")
    args = parser.parse_args()

    if args.reclassify:
        changed = reclassify_rgl()
        print("RGL: %d metal flag(s) changed" % changed)
        return 0
    if args.rgl:
        changed = reread_rgl()
        print("RGL: %d value(s) changed" % changed)
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
