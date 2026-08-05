"""The quarantine: where a library-internal removal puts what it takes.

SPLIT OUT OF core/library.py 2026-08-02, and the reason is one line in
helpers/restore.py. The retirement of old undo copies calls
`quarantine_file`, and it reached it with `from amaze.core import
library`, inside a bare `except Exception: moved = ""`. library.py
imports hou at module level - so from tools/restore.py, the pure-stdlib
tool whose whole claim is that it works when Houdini does not start,
that import ALWAYS raised, was ALWAYS swallowed with nothing recorded,
and KEEP_UNDO_COPIES therefore bounded nothing on the one path a
panicked evening of repeated restores actually uses. Reproduced: eight
restores under a Houdini-free interpreter left eight undo copies, a
full 355KB each, against a stated bound of five.

Nothing here imports hou, and nothing here may: that is the property
the tool depends on. core/library.py re-exports every name below, so
its existing callers are unchanged.
"""

from __future__ import annotations

import os
import shutil
import time

from amaze.core import debug
from amaze.helpers import hostos


#: Where Clean Library puts what it takes out.
#:
#: practice.md decided the mechanism before it was built:
#: "library-internal cleanups move files to a holding folder, never
#: unlink". Both sweep sites were still plain os.remove - and a sweep
#: that is wrong is wrong about the user's only copy. The failure this
#: exists for is confirmed and reproduced: a sync client hands back a
#: stale but perfectly parseable sibling database, its newer assets'
#: files read as unowned, and 17 files belonging to 6 live COP assets
#: are gone. No absence guard fires on that - the file is present and
#: it parses.
#:
#: OUTSIDE THE LIBRARY, beside the daily history. The first version of
#: this put it in `<library>/_removed_<date>/`, and that is wrong three
#: times over: it grows inside the library forever, it breaks the rule
#: that an installed library holds nothing temporary, and it puts the
#: recovered copies inside the synced tree the sweep's own worst case
#: (a stale sibling arriving over sync) comes from. Machine-local means
#: it never travels, never syncs, and never makes a library look untidy
#: on another machine.
QUARANTINE_PREFIX = "quarantine"

#: How long a quarantined file is kept before it is really removed.
#: Long enough to notice something missing and go looking; short enough
#: that the folder cannot grow without bound. The daily history ledger
#: uses the same shape of rule for the same reason.
QUARANTINE_DAYS = 30


def quarantine_folder(library_dir: str) -> str:
    """`<config>/history/<library>/quarantine/<date>/`, one per day, so
    a second run the same day adds to the folder rather than scattering.

    Held for QUARANTINE_DAYS, then removed. "Never auto-emptied" was
    the first answer and it is not good enough: a folder that only ever
    grows is a slow leak, and moving it out of the library relocates
    that problem rather than solving it.

    The window is what the quarantine is actually FOR. It exists so a
    wrong sweep is recoverable - and a sweep nobody noticed for a month
    was not wrong about anything the user needed. Keeping it past that
    protects nothing real and costs disk forever.
    """
    return os.path.join(hostos.history_root(
        os.path.join(library_dir, "library.json")),
        QUARANTINE_PREFIX, time.strftime("%Y-%m-%d"))


def prune_quarantine(library_dir: str, days: int = QUARANTINE_DAYS) -> int:
    """Remove quarantine days older than `days`. Returns how many went.

    By the DATE IN THE FOLDER NAME, not mtime: the name says which day
    these files were taken out, while mtime records the last time
    anything touched the folder - which a backup pass or a file copy
    rewrites, and which would then keep the oldest batch alive forever.
    """
    root = os.path.join(hostos.history_root(
        os.path.join(library_dir, "library.json")), QUARANTINE_PREFIX)
    cutoff = time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - days * 86400))
    removed = 0
    try:
        days_held = sorted(os.listdir(root))
    except OSError:
        return 0
    for name in days_held:
        if name >= cutoff:
            continue                       # ISO dates sort as dates
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        # PERMANENT, and sanctioned here specifically: THIS FOLDER IS
        # THE TRASH. practice.md's "never unlink, move to the OS Trash"
        # was written about a Delete File that removed a real model the
        # instant it was clicked - no holding period, no way back. The
        # guardrail that rule exists to provide is exactly what the
        # thirty days already are, and routing expiry into a SECOND
        # trash would only mean the same files sit in two places
        # forever, which is the unbounded growth this window exists to
        # end.
        try:
            shutil.rmtree(folder)
            removed += 1
            debug.event("cleanup", "quarantine day expired",
                        folder=folder, days=days)
        except OSError as exc:
            debug.event("cleanup", "could not expire a quarantine day",
                        folder=folder, error=str(exc))
    return removed


def quarantine_size(library_dir: str) -> tuple:
    """(files, bytes) currently held for this library, across all days."""
    root = os.path.join(hostos.history_root(
        os.path.join(library_dir, "library.json")), QUARANTINE_PREFIX)
    count = total = 0
    for folder, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(folder, name))
                count += 1
            except OSError:
                pass
    return count, total


def quarantine_file(library_dir: str, path: str) -> str:
    """Move one file into today's quarantine, keeping its folder name.

    os.replace, so it is atomic and cannot half-copy - the source and
    destination are inside the same library and therefore the same
    volume. Returns the new path, or "" if it could not be moved, in
    which case the caller must treat the file as still present.
    """
    folder = quarantine_folder(library_dir)
    relative = os.path.relpath(path, library_dir)
    target = os.path.join(folder, relative)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(target):
            # A same-named file quarantined earlier today. Keep both:
            # the older one is evidence too.
            stem, ext = os.path.splitext(target)
            target = "%s.%s%s" % (stem, time.strftime("%H%M%S"), ext)
        os.replace(path, target)
        return target
    except OSError as exc:
        debug.event("cleanup", "could not quarantine", file=path,
                    error=str(exc))
        return ""
