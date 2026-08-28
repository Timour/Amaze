"""Where a library-internal removal puts what it takes. NOTHING HERE IMPORTS hou AND NOTHING MAY - the pure-stdlib restore tool reaches this, and an import that raises there is swallowed with nothing recorded. `core/library.py` re-exports every name below, and the folder is machine-local and OUTSIDE the library, because a sweep's worst case is a stale sibling arriving over sync. ▸archive/quarantine.py"""

from __future__ import annotations

import os
import shutil
import time

from amaze.core import debug
from amaze.helpers import hostos


QUARANTINE_PREFIX = "quarantine"

QUARANTINE_DAYS = 30


def quarantine_folder(library_dir: str) -> str:
    """One folder per day, so a second run the same day adds rather than scatters. Held for `QUARANTINE_DAYS` - a sweep nobody noticed inside the window was not wrong about anything needed, and keeping it longer costs disk forever."""
    return os.path.join(hostos.history_root(
        os.path.join(library_dir, "library.json")),
        QUARANTINE_PREFIX, time.strftime("%Y-%m-%d"))


def prune_quarantine(library_dir: str, days: int = QUARANTINE_DAYS) -> int:
    """Removes quarantine days older than `days`, BY THE DATE IN THE NAME - mtime records the last touch, which a backup pass rewrites. The removal here is PERMANENT and sanctioned: this folder IS the trash, and a second one would only mean the same files sit in two places forever."""
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
    """Moves one file into today's quarantine. `os.replace` first, atomic where it works - but a rename cannot cross volumes and the library may be on a drive of its own, so the fallback copies then unlinks: a torn copy lands on the QUARANTINE side and the source survives. Answers the new path, or `""`, and the caller must then treat the file as still present."""
    folder = quarantine_folder(library_dir)
    relative = os.path.relpath(path, library_dir)
    target = os.path.join(folder, relative)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(target):
            stem, ext = os.path.splitext(target)
            target = "%s.%s%s" % (stem, time.strftime("%H%M%S"), ext)
        try:
            os.replace(path, target)
        except OSError:
            shutil.move(path, target)
        return target
    except (OSError, shutil.Error) as exc:
        debug.event("cleanup", "could not quarantine", file=path,
                    error=str(exc))
        return ""
