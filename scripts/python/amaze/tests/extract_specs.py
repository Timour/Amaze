"""Standard-surface numbers measured off real materials, for the generator."""

import argparse
import json
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import database, material as matmod  # noqa: E402
from amaze.render import material_converter, nodes  # noqa: E402

SPEC_PARMS = (
    "base", "base_color", "metalness", "specular", "specular_roughness",
    "specular_IOR", "coat", "coat_roughness", "transmission",
    "emission", "emission_color", "sheen", "sheen_roughness",
    "subsurface", "subsurface_color",
)


class _Prefs:
    def __init__(self, library_dir):
        self.dir = library_dir
        self.asset_dir = "mat/"
        self.img_dir = "img/"
        self.ext = ".mat"
        self.img_ext = ".png"
        self.render_on_import = 0
        self.rendersize = 256
        self.thumbsize = 128
        self.rendersamples = 8
        self.karma_rendersamples = 9


def _read_shader(shader) -> dict:
    """The spec values authored on one mtlxstandard_surface."""
    spec = {}
    for name in SPEC_PARMS:
        tuple_parm = shader.parmTuple(name)
        if tuple_parm is None:
            continue
        try:
            values = [float(v) for v in tuple_parm.eval()]
        except (hou.Error, TypeError, ValueError):
            continue
        spec[name] = values[0] if len(values) == 1 else values
    return spec


def from_library(library_dir: str, limit: int = 0) -> list:
    """Convert the library's Redshift materials and read each shader."""
    database.DatabaseConnector._instances.pop("library.json", None)
    data = database.DatabaseConnector("library.json").load(library_dir)
    records = [
        r for r in data.get("assets", [])
        if "Redshift" in str(r.get("renderer", ""))
    ]
    if limit:
        records = records[:limit]
    prefs = _Prefs(library_dir)
    staging = hou.node("/obj").createNode("matnet", "spec_extract")
    out = []
    try:
        for index, record in enumerate(records, 1):
            mat = matmod.Material()
            mat._name = record.get("name", "")
            mat._mat_id = str(record.get("id"))
            mat._renderer = record.get("renderer", "")
            handler = nodes.NodeHandler(prefs)

            def produce(builder, _handler=handler, _mat=mat):
                shader, disp, _report = (
                    material_converter.convert_redshift_material(
                        _handler, _mat, builder
                    )
                )
                return (shader, disp)

            try:
                builder, shader = nodes.build_karma_material(
                    staging, mat.name, produce
                )
            except Exception:                      # noqa: BLE001
                continue
            if shader is not None and \
                    shader.type().name() == "mtlxstandard_surface":
                spec = _read_shader(shader)
                if spec:
                    out.append({
                        "name": record.get("name"),
                        "source": "library",
                        "categories": record.get("categories", []),
                        "spec": spec,
                    })
            for child in list(staging.children()):
                child.destroy()
            if index % 50 == 0:
                print("  ...%d/%d" % (index, len(records)))
    finally:
        staging.destroy()
    return out


_USD_INPUT = re.compile(
    r'(?:float|color3f)\s+inputs:(\w+)\s*=\s*(\(?[-\d.eE, ]+\)?)'
)


def from_houdini_corpus() -> list:
    """The values SideFX ships in `basic_materials.usd`, read as text."""
    hh = hou.getenv("HH") or ""
    path = os.path.join(
        hh, "usd", "materials", "basic_materials", "basic_materials.usd"
    )
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8", errors="replace").read()
    out = []
    blocks = re.split(r'def Material "', text)
    for block in blocks[1:]:
        name = block.split('"', 1)[0]
        body = block
        if "ND_standard_surface_surfaceshader" not in body:
            continue
        spec = {}
        for parm, raw in _USD_INPUT.findall(body):
            if parm not in SPEC_PARMS:
                continue
            values = [
                float(v) for v in raw.strip("() ").split(",") if v.strip()
            ]
            if not values:
                continue
            spec[parm] = values[0] if len(values) == 1 else values
        if spec:
            out.append({"name": name, "source": "houdini",
                        "categories": [], "spec": spec})
    return out


def summarise(entries: list) -> dict:
    """Per parameter: the observed values and their quantiles."""
    scalars = {}
    colors = {}
    for entry in entries:
        for parm, value in entry["spec"].items():
            if isinstance(value, list):
                colors.setdefault(parm, []).append(value)
            else:
                scalars.setdefault(parm, []).append(value)
    stats = {}
    for parm, values in sorted(scalars.items()):
        values.sort()
        n = len(values)
        stats[parm] = {
            "n": n,
            "min": round(values[0], 4),
            "p10": round(values[int(n * 0.10)], 4),
            "median": round(values[n // 2], 4),
            "p90": round(values[min(int(n * 0.90), n - 1)], 4),
            "max": round(values[-1], 4),
            "mean": round(sum(values) / n, 4),
        }
    color_stats = {}
    for parm, vectors in sorted(colors.items()):
        n = len(vectors)
        channels = list(zip(*vectors))
        color_stats[parm] = {
            "n": n,
            "mean": [round(sum(c) / n, 4) for c in channels],
        }
    return {"scalars": stats, "colors": color_stats}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    parser.add_argument("--skip-library", action="store_true")
    args = parser.parse_args()

    library_dir = args.library or os.path.expanduser(
        "~/Cloud/3D/H-FILES/AMAZE/"
    )
    entries = from_houdini_corpus()
    print("Houdini's shipped corpus: %d materials" % len(entries))
    if not args.skip_library:
        print("Converting library materials for their numbers...")
        found = from_library(library_dir, args.limit)
        print("library: %d materials contributed numbers" % len(found))
        entries.extend(found)

    summary = summarise(entries)
    print("\nparameter distributions from %d real materials:" % len(entries))
    for parm, stat in summary["scalars"].items():
        print("  %-20s n=%-4d min %-7s p10 %-7s median %-7s p90 %-7s max %s"
              % (parm, stat["n"], stat["min"], stat["p10"],
                 stat["median"], stat["p90"], stat["max"]))
    for parm, stat in summary["colors"].items():
        print("  %-20s n=%-4d mean rgb %s" % (parm, stat["n"], stat["mean"]))

    out = args.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "res", "material_specs.json",
    )
    # The public repo carries the numbers, never the library's own names.
    shipped = []
    for entry in entries:
        if entry.get("source") == "houdini":
            shipped.append(entry)
        else:
            shipped.append({"source": entry["source"], "spec": entry["spec"]})
    payload = {
        "source": "amaze extract_specs",
        "materials": len(entries),
        "summary": summary,
        "entries": shipped,
    }
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1)
    print("\nwritten: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
