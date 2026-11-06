"""Audit what a library folder holds; `--strict` exits 1 on anything out of place. Stdlib only."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys

_CONVENTION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "scripts", "python", "amaze", "core", "library_files.py")


def _load_convention():
    spec = importlib.util.spec_from_file_location("amaze_library_files", _CONVENTION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


naming = _load_convention()

PROBLEMS = (    # (kind, headline); each entry's line names its kind
    (naming.SCRATCH, "LEFTOVER SCRATCH - a save died partway"),
    (naming.PRE_ADOPT_COPY, "PRE-ADOPT BACKUPS - left by an earlier texture update"),
    (naming.DUPLICATE, "DUPLICATES - a sync service's second copy of a known file"),
    (naming.UNKNOWN, "UNKNOWN - not part of a library"),
    (naming.UNREADABLE, "UNREADABLE - a folder that would not list"),
)


def audit(library: str) -> dict:
    """{kind: [relative path]} for everything in `library`, `matX/` included; folders end in `/`."""
    found = {}
    for relative, kind, detail, _info in naming.walk(library, packages=True):
        if kind == naming.FOLDER:
            continue
        shown = relative + "/" if detail == "folder" else relative
        found.setdefault(kind, []).append(shown)
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Report anything in a library that does not belong.")
    parser.add_argument("library", nargs="?", default="")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when anything is out of place")
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
    belong = sum(len(found.get(kind, ())) for kind in naming.KNOWN)
    if not args.quiet:
        print("%s\n  %d files belong here" % (library, belong))

    problems = 0
    for kind, headline in PROBLEMS + ((naming.OS_NOISE_KIND,
                                       "OS noise - harmless, but not library data"),):
        entries = found.get(kind, [])
        if not entries:
            continue
        if kind != naming.OS_NOISE_KIND:
            problems += len(entries)
        print("\n  %s (%d):" % (headline, len(entries)))
        for relative in sorted(entries)[:40]:
            print("    %-10s %s" % (kind, relative))
        if len(entries) > 40:
            print("    ... and %d more" % (len(entries) - 40))

    if not problems and not args.quiet:
        print("\n  clean - nothing here that should not be")
    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    sys.exit(main())
