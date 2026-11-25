#!/usr/bin/env hython
"""hython tools/build-default-packages.py <out-dir>; out-dir is the store's packages/<category>/"""

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

from amaze.actions import library as library_actions  # noqa: E402
from amaze.core import code_library, gradient_library, packages, users  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out_dir = os.path.abspath(sys.argv[1])
    os.makedirs(out_dir, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix="amaze_defaults_build_")
    try:
        prefs_mod.create_library(scratch)
        prefs = prefs_mod.Prefs()
        prefs.dir = os.path.join(scratch, "")    # keep the trailing separator: the connector appends the filename
        prefs.library_user = users.create(prefs, "Amaze")    # a library takes no change without a user
        library_actions.ensure_library_dirs(prefs)
        gradients = gradient_library.GradientLibrary(prefs)
        gradients.seed_curated_palettes(gradient_library.GradientCategories(prefs))
        code = code_library.CodeLibrary(prefs)
        code.seed_starter_snippets(code_library.CodeCategories(prefs))

        wanted = [(gradients, curated["key"]) for curated in gradient_library.CURATED_SETS]
        wanted.append((code, "starter"))
        collected = {id(model): [packages.collect_asset(model, a.mat_id) for a in model.assets]
                     for model in (gradients, code)}
        unmarked = [name for items in collected.values() for name in packages.unmarked(items)]
        if unmarked:    # Restore finds a preset by its mark, so none may ship without one
            print("UNMARKED refused: %s" % ", ".join(unmarked))
            return 1
        wrote, placed = [], set()
        for model, key in wanted:
            items = [item for item in collected[id(model)]
                     if str(item["record"]["curated"]).startswith(key + "/")]
            if not items:
                print("EMPTY SET refused: %s" % key)
                return 1
            path = os.path.join(out_dir, key + packages.SUFFIX)
            packages.write_package(path, items)
            wrote.append((path, len(items)))
            placed.update(id(item) for item in items)
        strays = [str(item["record"]["curated"]) for items in collected.values()
                  for item in items if id(item) not in placed]
        if strays:
            print("NO SET for: %s" % ", ".join(strays))
            return 1

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
