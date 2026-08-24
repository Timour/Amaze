#!/usr/bin/env hython
"""Build the official default packages: seed a THROWAWAY library with the shipped def files, then export one `.amazepkg` per curated set through the product's own collectors. Usage: hython tools/build-default-packages.py <out-dir> - point <out-dir> at the store's `packages/<category>/` folder (the browser only lists that exact shape; a package written elsewhere is silently invisible)."""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "python"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import code_library, gradient_library, packages  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402


class _Cats:
    _categories = []

    def check_add_category(self, name):
        pass


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out_dir = os.path.abspath(sys.argv[1])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="amaze_defaults_build_")
    try:
        prefs_mod.seed_test_folder(scratch)
        prefs = prefs_mod.Prefs()
        prefs.dir = os.path.join(scratch, prefs_mod.TEST_LIB_SUBDIR, "")    # trailing separator: the connector composes dir + filename, and every product door normalises before it
        gradients = gradient_library.GradientLibrary(prefs)
        gradients.seed_curated_palettes(_Cats())
        code = code_library.CodeLibrary(prefs)
        code.seed_starter_snippets(_Cats())

        def tagged(model, prefix):
            for asset in model.assets:
                tag = str((getattr(asset, "_extra", None) or {})
                          .get("curated") or "")
                if tag.startswith(prefix + "/"):
                    yield asset

        wrote = []
        for curated in gradient_library.CURATED_SETS:
            items = [packages.collect_asset(gradients, a.mat_id)
                     for a in tagged(gradients, curated["key"])]
            if not items:
                print("EMPTY SET refused: %s" % curated["key"])
                return 1
            path = os.path.join(out_dir, curated["key"] + packages.SUFFIX)
            packages.write_package(path, items)
            wrote.append((path, len(items)))
        items = [packages.collect_asset(code, a.mat_id)
                 for a in tagged(code, "starter")]
        if not items:
            print("EMPTY SET refused: starter")
            return 1
        path = os.path.join(out_dir, "starter" + packages.SUFFIX)
        packages.write_package(path, items)
        wrote.append((path, len(items)))

        for path, count in wrote:
            problems = packages.verify_package(path)
            if problems:
                print("BROKEN %s: %s" % (path, "; ".join(problems)))
                return 1
            print("%4d entries  %s" % (count, path))
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


sys.exit(main())
