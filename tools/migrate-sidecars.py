"""Writes builder sidecars for a library saved before them, running each .interface once."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "python",
    ),
)

from amaze.core import library as library_mod  # noqa: E402
from amaze.core import renderers  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.render import nodes as nodes_mod  # noqa: E402

BACKUP_ROOT = os.path.expanduser("~/Developer/backup/amaze")    #: outside the library, which keeps its shape


def configured_library() -> str:
    """The configured library, read WITHOUT Prefs.load(), which migrates a real settings file."""
    settings = os.path.join(hostos.config_root(), "settings.json")
    try:
        with open(settings, encoding="utf-8") as handle:
            stored = json.load(handle).get("directory", "")
    except (OSError, ValueError):
        return ""
    return os.path.normpath(hou.text.expandString(stored)) + os.sep if stored else ""


def back_up(library: str, ids: list, asset_dir: str) -> str:
    """Copies each .interface this run reads outside the library, named by content, held once."""
    digest = hashlib.sha256()
    sources = []
    for asset_id in sorted(ids):
        src = os.path.join(library, asset_dir, asset_id + ".interface")
        if not os.path.exists(src):
            continue
        sources.append((asset_id, src))
        digest.update(asset_id.encode("utf-8"))
        with open(src, "rb") as handle:
            digest.update(handle.read())

    dest = os.path.join(BACKUP_ROOT,
                        "interface-" + digest.hexdigest()[:12])
    if os.path.isdir(dest):
        return dest + "  (already held - identical content)"
    staging = dest + ".writing"
    os.makedirs(staging, exist_ok=True)
    for asset_id, src in sources:
        shutil.copy2(src, os.path.join(staging, asset_id + ".interface"))
    os.replace(staging, dest)
    return dest


def loaded_now(model, row: int) -> str:
    """The builder the CURRENT loader produces, no exec: a sidecar is written only if it differs."""
    hou.hipFile.clear(suppress_save_prompt=True)
    before = set(hou.node("/mat").children())
    ok, _reason = model.import_asset_to_scene(model.index(row), target="mat")
    if not ok:
        return ""
    fresh = [n for n in hou.node("/mat").children() if n not in before]
    if len(fresh) != 1:
        return ""
    return nodes_mod.capture_builder(fresh[0])


def capture_one(library: str, asset_dir: str, asset_id: str) -> str:
    """Runs one legacy `.interface` with undo off and captures what it built, as data."""
    path = os.path.join(library, asset_dir, asset_id + ".interface")
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        code = handle.read()

    with hou.undos.disabler():
        hou_parent = hou.node("/obj").createNode("matnet")
        try:
            scope = {"hou": hou, "hou_parent": hou_parent}
            exec(code, scope)  # noqa: S102 - the one deliberate run, code-prose.md
            built = hou_parent.children()
            if not built:
                return ""
            return nodes_mod.capture_builder(built[0])
        finally:
            hou_parent.destroy()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Write builder sidecars for assets that predate them.")
    parser.add_argument("library", nargs="?", default="")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be written, write nothing")
    parser.add_argument("--force", action="store_true",
                        help="rewrite sidecars that already exist")
    args = parser.parse_args(argv)

    library = args.library or configured_library()
    if not library or not os.path.isfile(os.path.join(library,
                                                      "library.json")):
        sys.stderr.write("no library.json under %r\n" % library)
        return 2

    asset_dir = "mat"
    with open(os.path.join(library, "library.json"), encoding="utf-8") as fh:
        assets = json.load(fh)["assets"]

    preferences = prefs_mod.Prefs()
    preferences.dir = library if library.endswith(os.sep) else library + os.sep
    preferences.path = tempfile.mkdtemp(prefix="amaze_migrate_prefs_")
    preferences.legacy_path = ""
    model = library_mod.MaterialLibrary(preferences=preferences)

    todo = []
    for asset in assets:
        asset_id = str(asset.get("id"))
        sidecar = os.path.join(library, asset_dir,
                               asset_id + nodes_mod.BUILDER_SUFFIX)
        if os.path.exists(sidecar) and not args.force:
            continue
        if not os.path.exists(os.path.join(library, asset_dir,
                                           asset_id + ".interface")):
            continue
        todo.append(asset)

    print("library: %s\n%d assets, %d need a sidecar"
          % (library, len(assets), len(todo)))
    if args.dry_run:
        for asset in todo[:20]:
            print("  would write: %s (%s)"
                  % (asset.get("name"), asset.get("renderer")))
        if len(todo) > 20:
            print("  ... and %d more" % (len(todo) - 20))
        return 0
    if not todo:
        print("nothing to do")
        return 0

    backup = back_up(library, [str(a.get("id")) for a in todo], asset_dir)
    print("backup of every .interface this run reads: %s" % backup)

    written = failed = skipped = 0
    for number, asset in enumerate(todo, 1):
        asset_id = str(asset.get("id"))
        sys.stderr.write("[%d/%d] %s\n"
                         % (number, len(todo), asset.get("name")))
        try:
            legacy = capture_one(library, asset_dir, asset_id)
        except Exception as exc:  # noqa: BLE001 - one bad file keeps no sidecar; the run goes on
            print("  FAILED %s: %s: %s"
                  % (asset.get("name"), type(exc).__name__, exc))
            failed += 1
            continue
        if not legacy:
            failed += 1
            continue

        if renderers.is_karma(asset.get("renderer")):    # Karma's loader builds its own builder
            skipped += 1
            continue

        row = model.find_asset_row_by_id(asset_id)    # compare values too, not the interface alone
        current = loaded_now(model, row) if row != -1 else ""
        if current:
            now, was = json.loads(current), json.loads(legacy)
            if (now.get("dialog_script") == was.get("dialog_script")
                    and now.get("values") == was.get("values")):
                skipped += 1
                continue
        text = legacy
        target = os.path.join(library, asset_dir,
                              asset_id + nodes_mod.BUILDER_SUFFIX)
        scratch = hostos.unique_scratch(target)
        try:
            with open(scratch, "w", encoding="utf-8") as handle:
                handle.write(text)
            hostos.promote_scratch(scratch, target)
            written += 1
        finally:
            hostos.discard_scratch(scratch)

    print("\n%d sidecars written, %d already reproduced by the loader "
          "(no sidecar needed), %d could not be captured"
          % (written, skipped, failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
