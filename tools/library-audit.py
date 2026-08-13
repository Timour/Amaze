"""What is allowed to exist inside a library directory - and what isn't.

    tools/library-audit.py [LIBRARY]        report
    tools/library-audit.py --strict [LIB]   exit 1 if anything is unknown

WHY. A library is the user's data, and Amaze is not its only writer -
the OS, a sync client, an interrupted save and our own development all
leave things behind. Until 2026-07-30 there was no written statement of
what a library may contain, so the question "is this library clean?"
could only be answered by reading the code and reasoning it out fresh
each time. That is the kind of question that gets answered differently
by the same person twice.

This file IS the statement. Everything a library may hold is listed
below; anything else is reported. Pure stdlib on purpose - no Houdini,
no imports from the package - so it runs on any machine, in a hook, or
against a library copied off a stick.

A SCRATCH file is called out separately from a merely unknown one. An
unknown file might be the user's own; a leftover `.writing` is always
ours, and always means a save died partway.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

#: The four databases plus the policy file and the two keyed side
#: tables. notes.json (core/notes.py) and icons.json (core/tile_icons.py)
#: are written into the library beside the databases and carry a .bak
#: tier of their own; policy.json is snapshotted too (library_policy.py
#: :139, "the only library JSON with zero backup coverage until now").
#: None of the three was listed, so --strict exited 1 on a library where
#: nothing was wrong - measured on the real one: 7 files reported as
#: not-library-data, among them the notes store and the policy file's
#: only restore points, under a heading that says anything unknown "is
#: either a failed write or not library data".
#:
#: THIS LIST DUPLICATES `keyed_store`'s REGISTRY, DELIBERATELY AND
#: PERMANENTLY. That module declares every store as data and `stores()`
#: is the one enumeration Repair and the restore picker read - but this
#: file may not import it, because it must run where Houdini will not
#: start. So a new store is added in BOTH places, and this is the end
#: that fails loudly: an undeclared file is UNKNOWN and `--strict`
#: exits 1. Stated at both ends now; the other end used to read as
#: though it had absorbed this one.
DATABASES = ("library.json", "cops.json", "code.json", "gradients.json")
SIDE_TABLES = ("notes.json", "icons.json", "locations.json",
               "favourites.json", "users.json", "prefs.json")
LOOSE_FILES = DATABASES + SIDE_TABLES + ("policy.json",)

#: The product's own restore tier. NOT clutter: snapshot_before_write
#: writes these, Repair Library reads them, restore.put_back recovers
#: from them. Every shipping library carries them, and a library without
#: them has no way back from a bad write.
#:
#: Built from LOOSE_FILES, not DATABASES: every file that gets
#: snapshotted gets a tier, and keying this on the narrower tuple is
#: what made the wider one wrong.
BACKUP = re.compile(r"^(%s)\.bak-(1|2|3|first)$"
                    % "|".join(re.escape(d) for d in LOOSE_FILES))

#: helpers/restore.py's undo copies: one per restore, timestamped, with
#: a counter when two land in the same second. Repair's own undo
#: sentence points the user at these, so reporting them as
#: not-library-data contradicts the tool beside it.
UNDO_COPIES = re.compile(r"^(%s)\.bak-before-restore-\d{8}-\d{6}(-\d+)?$"
                         % "|".join(re.escape(d) for d in LOOSE_FILES))

#: hostos.preserve_unreadable keeps a file it could not parse rather
#: than letting the next write destroy the evidence.
PRESERVED = re.compile(r"^(%s)\.unreadable(\.\d+)?$"
                       % "|".join(re.escape(d) for d in LOOSE_FILES))

#: Seed markers - "the curated content was already offered here once",
#: so a user who deleted it does not get it back on every launch.
MARKERS = (".amaze_gradient_seed_v1", ".amaze_code_starter_v1",
           ".assetlib_gradient_seed_v1", ".assetlib_code_starter_v1")

#: Asset payloads, by directory.
ASSET_DIRS = {
    # .builder.json is the builder sidecar: the container's own
    # parameter interface and values, recorded as data so importing a
    # material never has to execute a file. .stamp.json is the recovery
    # stamp: the asset's whole record, so the index can be rebuilt if it
    # is lost. Both are per-asset sidecars; see overview.md.
    "mat": (".mat", ".interface", ".builder.json", ".stamp.json"),
    "img": (".png", ".jpg", ".jpeg"),
}

#: MaterialX packages: a directory per package, holding the .mtlx and
#: whatever textures it references. Texture extensions are open-ended
#: by nature, so this directory is checked for SCRATCH only.
PACKAGE_DIRS = ("matX",)

#: Always ours, always a failed write. A fixed-name scratch that
#: survives is the bug class this project has hit repeatedly.
SCRATCH = re.compile(
    r"(\.writing|\.capturing|\.tmp|\.temp|\.new|\.partial|\.lock"
    r"|\.swp|~)$|^\.amaze_scratch", re.IGNORECASE)

#: The OS's own droppings. Not ours, still not the user's data.
OS_NOISE = (".DS_Store", "Thumbs.db", "desktop.ini", ".Spotlight-V100",
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
    # mat/versions/<id>/<n>.<kind> + versions.json: the version store.
    # The archive holds the same kinds the base does, numbered.
    if top == "mat" and len(parts) == 4 and parts[1] == "versions":
        # The archive holds the same kinds the base does - INCLUDING
        # the thumbnail, which lives in img/ for the base and so was
        # not in ASSET_DIRS["mat"]. Measured on the real library: four
        # `mat/versions/<id>/<n>.png` reported as not-library-data.
        if (name == "versions.json"
                or name.endswith(ASSET_DIRS["mat"])
                or name.endswith(ASSET_DIRS["img"])):
            return "ok"
        return "unknown"
    if top in ASSET_DIRS and len(parts) == 2:
        return "ok" if name.endswith(ASSET_DIRS[top]) else "unknown"
    if top in PACKAGE_DIRS:
        # Texture formats are open-ended; scratch was already caught.
        return "ok"
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
