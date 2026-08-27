"""What is allowed to exist inside a library directory: `tools/library-audit.py [LIBRARY]` reports, `--strict` exits 1 on anything unknown - pure stdlib on purpose, so it runs where Houdini will not start; SCRATCH is called out separately because a leftover `.writing` is always ours and always means a save died partway. ▸p/store-declarations"""

from __future__ import annotations

import argparse
import os
import re
import sys

DATABASES = ("library.json", "cops.json", "code.json", "gradients.json")    # with SIDE_TABLES and policy.json, everything loose a library may hold; DUPLICATES keyed_store's registry DELIBERATELY - this file may not import it, so a new store is added in BOTH places and this is the end that fails loudly ▸p/store-declarations
SIDE_TABLES = ("notes.json", "icons.json", "locations.json",
               "location_paths.json", "favourites.json", "users.json",
               "prefs.json")
LOOSE_FILES = DATABASES + SIDE_TABLES + ("policy.json",)

BACKUP = re.compile(r"^(%s)\.bak-(1|2|3|first)$"    # the PRODUCT's restore tier, not clutter: snapshot_before_write writes these, Repair and restore.put_back read them - built from LOOSE_FILES because every snapshotted file gets a tier, and keying on the narrower tuple is what made the wider one wrong
                    % "|".join(re.escape(d) for d in LOOSE_FILES))

UNDO_COPIES = re.compile(r"^(%s)\.bak-before-restore-\d{8}-\d{6}(-\d+)?$"    # helpers/restore.py's undo copies, one per restore; Repair's own undo sentence points the user at these
                         % "|".join(re.escape(d) for d in LOOSE_FILES))

PRESERVED = re.compile(r"^(%s)\.unreadable(\.\d+)?$"    # hostos.preserve_unreadable keeps what it could not parse rather than letting the next write destroy the evidence
                       % "|".join(re.escape(d) for d in LOOSE_FILES))

MARKERS = (".amaze_gradient_seed_v1", ".amaze_code_starter_v1",    # seed markers - the curated content was already offered here once, so a user who deleted it does not get it back on every launch
           ".assetlib_gradient_seed_v1", ".assetlib_code_starter_v1")

ASSET_DIRS = {    # asset payloads by directory; .builder.json is the builder sidecar (the parameter interface as data, so importing never executes a file) and .stamp.json the recovery stamp (the whole record, so the index can be rebuilt) - see overview.md
    "mat": (".mat", ".interface", ".builder.json", ".stamp.json"),
    "img": (".png", ".jpg", ".jpeg"),
}

PACKAGE_DIRS = ("matX",)    # a directory per MaterialX package, .mtlx + textures; texture extensions are open-ended by nature, so checked for SCRATCH only

SCRATCH = re.compile(    # always ours, always a failed write - a fixed-name scratch that survives is the bug class this project has hit repeatedly
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
                or name.endswith(ASSET_DIRS["img"])):    # the archive numbers the same kinds the base holds INCLUDING the thumbnail, which lives in img/ for the base - measured: four mat/versions PNGs reported as not-library-data
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
