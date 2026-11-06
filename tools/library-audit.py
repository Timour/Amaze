"""Audit what a library folder holds; `--strict` exits 1 on anything unknown ▸p/store-declarations"""

from __future__ import annotations

import argparse
import os
import re
import sys

DATABASES = ("library.json", "cops.json", "code.json", "gradients.json")    # mirrors keyed_store's registry: add a new store in both ▸p/store-declarations
SIDE_TABLES = ("notes.json", "icons.json", "locations.json",
               "location_paths.json", "favourites.json", "users.json",
               "prefs.json")
LOOSE_FILES = DATABASES + SIDE_TABLES + ("policy.json",)

BACKUP = re.compile(r"^(%s)\.bak-(1|2|3|first)$"    # the restore tier snapshot_before_write writes, for every loose file
                    % "|".join(re.escape(d) for d in LOOSE_FILES))

UNDO_COPIES = re.compile(r"^(%s)\.bak-before-restore-\d{8}-\d{6}(-\d+)?$"    # helpers/restore.py's undo copies, one per restore
                         % "|".join(re.escape(d) for d in LOOSE_FILES))

PRESERVED = re.compile(r"^(%s)\.unreadable(\.\d+)?$"    # files hostos.preserve_unreadable kept because they did not parse
                       % "|".join(re.escape(d) for d in LOOSE_FILES))

MARKERS = (".amaze_gradient_seed_v1", ".amaze_code_starter_v1",    # seed markers: the curated content was already offered here once
           ".assetlib_gradient_seed_v1", ".assetlib_code_starter_v1")

ASSET_DIRS = {    # asset payloads by directory, with the builder sidecar and the recovery stamp
    "mat": (".mat", ".interface", ".builder.json", ".stamp.json"),
    "img": (".png", ".jpg", ".jpeg"),
}

PACKAGE_DIRS = ("matX",)    # a directory per MaterialX package, checked for scratch only

SCRATCH = re.compile(    # always ours, always a write that died partway
    r"(\.writing|\.capturing|\.tmp|\.temp|\.new|\.partial|\.lock"
    r"|\.swp|~)$|^\.amaze_scratch", re.IGNORECASE)

OS_NOISE = (".DS_Store", "Thumbs.db", "desktop.ini", ".Spotlight-V100",    # the OS's own droppings - not ours, still not the user's data
            ".fseventsd", ".TemporaryItems", "._.DS_Store")


def classify(relative: str) -> str:
    """One of: ok, scratch, os-noise, unknown."""
    parts = relative.split(os.sep)
    name = parts[-1]

    if name in OS_NOISE or name.startswith("._"):
        return "os-noise"
    if SCRATCH.search(name):
        return "scratch"

    if len(parts) == 1:
        if name in LOOSE_FILES or name in MARKERS:
            return "ok"
        if (BACKUP.match(name) or PRESERVED.match(name)
                or UNDO_COPIES.match(name)):
            return "ok"
        return "unknown"

    top = parts[0]
    if top == "mat" and len(parts) == 4 and parts[1] == "versions":    # mat/versions/<id>/<n>.<kind> + versions.json: the version store
        if (name == "versions.json"
                or name.endswith(ASSET_DIRS["mat"])
                or name.endswith(ASSET_DIRS["img"])):    # a version also archives the thumbnail
            return "ok"
        return "unknown"
    if top in ASSET_DIRS and len(parts) == 2:
        return "ok" if name.endswith(ASSET_DIRS[top]) else "unknown"
    if top in PACKAGE_DIRS:
        return "ok"    # texture formats are open-ended; scratch was already caught above
    return "unknown"


def audit(library: str) -> dict:
    found = {"ok": [], "scratch": [], "os-noise": [], "unknown": []}
    for root, dirs, files in os.walk(library):
        dirs[:] = [d for d in dirs if d not in (".git",)]
        for name in files:
            full = os.path.join(root, name)
            found[classify(os.path.relpath(full, library))].append(full)
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Report anything in a library that does not belong.")
    parser.add_argument("library", nargs="?", default="")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when anything is scratch or unknown")
    parser.add_argument("--quiet", action="store_true",
                        help="only print problems")
    args = parser.parse_args(argv)

    library = args.library or os.environ.get("AMAZE_LIBRARY", "")
    if not library:
        sys.stderr.write("give a library directory (or set AMAZE_LIBRARY)\n")
        return 2
    if not os.path.isfile(os.path.join(library, "library.json")):
        sys.stderr.write("no library.json under %s\n" % library)
        return 2

    found = audit(library)
    if not args.quiet:
        print("%s\n  %d files belong here" % (library, len(found["ok"])))

    problems = 0
    for kind, headline in (
            ("scratch", "LEFTOVER SCRATCH - a save died partway"),
            ("unknown", "UNKNOWN - not part of a library"),
            ("os-noise", "OS noise - harmless, but not library data")):
        entries = found[kind]
        if not entries:
            continue
        if kind != "os-noise":
            problems += len(entries)
        print("\n  %s (%d):" % (headline, len(entries)))
        for path in sorted(entries)[:40]:
            print("    " + os.path.relpath(path, library))
        if len(entries) > 40:
            print("    ... and %d more" % (len(entries) - 40))

    if not problems and not args.quiet:
        print("\n  clean - nothing here that should not be")
    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    sys.exit(main())
