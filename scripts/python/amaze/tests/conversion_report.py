"""Redshift->Karma conversion over the real library, read-only, under hython."""

import argparse
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402  (must precede hou for Qt-bound APIs)

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import database, material as matmod  # noqa: E402
from amaze.render import material_converter, nodes  # noqa: E402


def library_materials(library_dir: str) -> list:
    """Every Redshift material in the library; loads, never saves."""
    database.DatabaseConnector._instances.pop("library.json", None)
    data = database.DatabaseConnector("library.json").load(library_dir)
    out = []
    for record in data.get("assets", []):
        if "Redshift" not in str(record.get("renderer", "")):
            continue
        mat = matmod.Material()
        mat.set_data_from_dict(record) if hasattr(
            mat, "set_data_from_dict") else None
        out.append((record, mat))
    return out


class _Prefs:
    """The least the import and convert paths read; nowhere to write."""

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


def check_material(record, prefs, staging) -> dict:
    """Convert one material through the real path and return its verdict."""
    result = {"name": record.get("name"), "id": record.get("id"),
              "renderer": record.get("renderer"), "stage": "convert",
              "ok": False, "detail": "", "notes": 0}
    started = time.time()
    mat = matmod.Material()
    mat._name = record.get("name", "")
    mat._mat_id = str(record.get("id"))
    mat._renderer = record.get("renderer", "")
    mat._categories = list(record.get("categories", []))
    mat._tags = list(record.get("tags", []))

    handler = nodes.NodeHandler(prefs)
    report_holder = {}

    def produce(builder):
        shader, disp, report = material_converter.convert_redshift_material(
            handler, mat, builder
        )
        report_holder["report"] = report
        return (shader, disp)

    try:
        builder, shader = nodes.build_karma_material(
            staging, mat.name, produce
        )
    except Exception as exc:                      # noqa: BLE001
        result["detail"] = "%s: %s" % (type(exc).__name__, exc)
        result["ms"] = round((time.time() - started) * 1000)
        return result

    report = report_holder.get("report")
    result["skipped"] = list(getattr(report, "skipped", []) or [])
    result["approximated"] = list(getattr(report, "approximated", []) or [])
    result["notes"] = len(result["skipped"]) + len(result["approximated"])
    if shader is None or builder is None:
        result["detail"] = (result["skipped"] or ["converter produced no shader"])[0]
        result["out_of_scope"] = bool(result["skipped"])
        result["ms"] = round((time.time() - started) * 1000)
        return result

    result["stage"] = "invariants"
    if not builder.isMaterialFlagSet():
        result["detail"] = "material flag not set"
        result["ms"] = round((time.time() - started) * 1000)
        return result
    if not nodes.surface_terminal_wired(builder):
        result["detail"] = "surface terminal not wired (renders black)"
        result["ms"] = round((time.time() - started) * 1000)
        return result

    result["stage"] = "usd"
    lib = hou.node("/stage").createNode("materiallibrary")
    try:
        moved = hou.moveNodesTo((builder,), lib)
        nodes.register_in_materiallibrary(lib, moved[0])
        import loputils

        prims = [str(p) for p in loputils.globPrimPaths(
            lib, "%type(Material)")]
        if not prims:
            result["detail"] = "no USD Material prim after translation"
        else:
            result["ok"] = True
            result["prim"] = prims[0]
    finally:
        lib.destroy()
    result["ms"] = round((time.time() - started) * 1000)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", default=None,
                        help="library dir (default: the live one)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    library_dir = args.library or (
        hou.getenv("AMAZE_TEST_LIBRARY")
        or os.path.expanduser("~/Cloud/3D/H-FILES/AMAZE/")
    )
    prefs = _Prefs(library_dir)
    records = [r for r, _m in library_materials(library_dir)]
    if args.limit:
        records = records[:args.limit]
    print("Conversion Report - %d Redshift materials from %s"
          % (len(records), library_dir))
    if not records:
        print("nothing to check")
        return 0

    staging = hou.node("/obj").createNode("matnet", "conversion_report")
    results = []
    try:
        for index, record in enumerate(records, 1):
            verdict = check_material(record, prefs, staging)
            results.append(verdict)
            mark = "ok  " if verdict["ok"] else "FAIL"
            print("  [%3d/%3d] %s %-42s %s"
                  % (index, len(records), mark,
                     str(verdict["name"])[:42],
                     "" if verdict["ok"]
                     else "(%s: %s)" % (verdict["stage"],
                                        verdict["detail"][:70])))
            for child in list(staging.children()):
                child.destroy()
    finally:
        staging.destroy()

    passed = [r for r in results if r["ok"]]
    print("\n%d/%d converted and translated cleanly" % (len(passed), len(results)))
    by_stage = {}
    for r in results:
        if not r["ok"]:
            by_stage.setdefault(r["stage"], []).append(r)
    for stage, items in sorted(by_stage.items()):
        print("  failed at %-11s %d" % (stage, len(items)))
        for item in items[:5]:
            print("      %-40s %s" % (str(item["name"])[:40],
                                      item["detail"][:60]))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            for r in results:
                handle.write(json.dumps(r) + "\n")
        print("per-material records: " + args.out)
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
