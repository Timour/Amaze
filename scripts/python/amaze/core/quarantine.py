"""Where a library-internal removal puts what it takes, machine-local; never import hou here."""

from __future__ import annotations

import datetime
import os
import shutil
import time

from amaze.core import debug
from amaze.helpers import hostos


QUARANTINE_PREFIX = "quarantine"

QUARANTINE_DAYS = 30


def _quarantine_root(library_dir: str) -> str:
    """This library's quarantine, every day of it, in its history folder: by library id, else by path."""
    return os.path.join(hostos.history_root(
        os.path.join(library_dir, "library.json")), QUARANTINE_PREFIX)


def quarantine_folder(library_dir: str) -> str:
    """Today's quarantine folder, one per day, held for `QUARANTINE_DAYS`."""
    return os.path.join(_quarantine_root(library_dir),
                        time.strftime("%Y-%m-%d"))


def prune_quarantine(library_dir: str, days: int = QUARANTINE_DAYS) -> int:
    """Permanently remove quarantine days older than `days`, by the date in the folder name."""
    root = _quarantine_root(library_dir)
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


def held(library_dir: str, days: int = QUARANTINE_DAYS) -> dict:
    """{path, files, bytes, days}; each day is (day, first day it may be removed, files, bytes)."""
    root = _quarantine_root(library_dir)
    found = {"path": root, "files": 0, "bytes": 0, "days": []}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return found
    for name in names:
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        count = total = 0
        for here, _dirs, files in os.walk(folder):
            for one in files:
                try:
                    total += os.path.getsize(os.path.join(here, one))
                    count += 1
                except OSError:
                    pass
        try:
            expires = (datetime.date.fromisoformat(name)
                       + datetime.timedelta(days=days + 1)).isoformat()    # `prune_quarantine`'s cutoff
        except ValueError:
            expires = ""
        found["days"].append((name, expires, count, total))
        found["files"] += count
        found["bytes"] += total
    return found


def quarantine_size(library_dir: str) -> tuple:
    """(files, bytes) currently held for this library, across all days."""
    count = total = 0
    for folder, _dirs, files in os.walk(_quarantine_root(library_dir)):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(folder, name))
                count += 1
            except OSError:
                pass
    return count, total


def quarantine_file(library_dir: str, path: str) -> str:
    """Move one file into today's quarantine; the new path, or "" and the file is still present."""
    return quarantine_as(library_dir, path, os.path.relpath(path, library_dir))


def quarantine_as(library_dir: str, path: str, relative: str) -> str:
    """`quarantine_file` filed under `relative`, which a file from outside the library needs."""
    target = os.path.join(quarantine_folder(library_dir), relative)
    hostos.check_sandbox(target)
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
