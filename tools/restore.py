#!/usr/bin/env python3
"""Inspect and restore Amaze's database snapshots.

Every write to a critical database first copies the on-disk file to a
rolling ``.bak-1/2/3`` beside it, plus an immutable ``.bak-first``.

    tools/restore.py list <file>            what snapshots exist
    tools/restore.py restore <file> bak-2   put one back

CLOSE HOUDINI FIRST, or the running panel overwrites what you put back.

A restore SNAPSHOTS THE CURRENT STATE first, to a timestamped
``.bak-before-restore-<when>`` that no later restore overwrites, and
``list`` prints its exact name - so a restore chosen in a panic is
itself reversible. Never give that copy a fixed name: two restores in a
row then overwrite the only copy of the starting state.

The LOGIC is in ``amaze/helpers/restore.py``, which the Repair shelf
tool shares; this is only the terminal front end. Keep both pure
stdlib - the tool has to work when Houdini will not start.
"""

import argparse
import os
import sys

# The package, from beside this file - tools/ is not installed into
# $AMAZE (sync-install.sh copies scripts/, python_panels/ and toolbar/),
# so this tool always runs out of a clone and scripts/python is always
# its sibling. Nothing imported below touches hou.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "python"))

from amaze.helpers import restore as restore_lib          # noqa: E402


def cmd_list(target: str) -> int:
    print("current   %s" % restore_lib.describe(target))
    found = restore_lib.snapshots(target)
    if not found:
        print("no snapshots beside this file")
        return 1
    for tier, path in found:
        print("%-9s %s" % (tier, restore_lib.describe(path)))
    return 0


def cmd_restore(target: str, tier: str, allow_loss: bool = False) -> int:
    try:
        done = restore_lib.put_back(target, tier, allow_loss=allow_loss)
    except restore_lib.RestoreRefused as exc:
        # The sentence is written for a DIALOG, so it carries no parse
        # position; a terminal wants that detail, and .detail is where it
        # rides. Same refusal, same wording, one extra clause here.
        detail = " (%s)" % exc.detail if exc.detail else ""
        print("refusing to restore: %s%s" % (exc, detail), file=sys.stderr)
        return 1
    if done["undo"]:
        print("current state saved to %s" % done["undo"])
    print("restored %s -> %s" % (done["tier"], os.path.basename(target)))
    print("now      %s" % restore_lib.describe(target))
    for asset_id in done.get("stranded", []):
        # Named, not counted: these files are still on disk and the
        # restored list does not know them - Repair reattaches them.
        print("note: %s is on disk but not in the restored list - "
              "Repair Library can reattach it" % asset_id)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect and restore Amaze database snapshots.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list", help="show available snapshots")
    p_list.add_argument("file")
    p_restore = sub.add_parser("restore", help="put a snapshot back")
    p_restore.add_argument("file")
    p_restore.add_argument(
        "tier",
        help="bak-1 | bak-2 | bak-3 | bak-first, or an undo copy's full "
             "name as `list` prints it (bak-before-restore-<when>)")
    p_restore.add_argument(
        "--allow-loss", action="store_true",
        help="restore even when the copy holds fewer records than the "
             "current list - refused otherwise, with both counts named")
    args = parser.parse_args()

    target = os.path.abspath(os.path.expanduser(args.file))
    if args.command == "list":
        return cmd_list(target)
    return cmd_restore(target, args.tier,
                       allow_loss=args.allow_loss)


if __name__ == "__main__":
    sys.exit(main())
