"""Amaze's compiled files, always hash-checked: the kind a synced or updated .py cannot fool."""

import importlib.util
import os
import threading

SKIPPED_FOLDERS = ("__pycache__", "tests")    #: never imported by a running Houdini
HASH_CHECKED = 0b11    #: the PEP 552 flags of a pyc that Python re-checks against its source


def _current(path: str) -> bool:
    """Whether `path` has a hash-checked compiled file made from the source it holds now."""
    try:
        with open(path, "rb") as handle:
            source = handle.read()
        with open(importlib.util.cache_from_source(path), "rb") as handle:
            header = handle.read(16)
    except OSError:
        return False
    return (header[:4] == importlib.util.MAGIC_NUMBER
            and (int.from_bytes(header[4:8], "little") & HASH_CHECKED) == HASH_CHECKED
            and header[8:16] == importlib.util.source_hash(source))


def stale(root: str) -> list:
    """Every .py under `root` whose compiled file is missing, timestamp-checked or out of date."""
    found = []
    for folder, folders, files in os.walk(root):
        folders[:] = sorted(name for name in folders if name not in SKIPPED_FOLDERS)
        for name in sorted(files):
            path = os.path.join(folder, name)
            if name.endswith(".py") and not _current(path):
                found.append(path)
    return found


def compile_missing(root: str) -> int:
    """Compiles what `stale` names, hash-checked, and answers how many it wrote."""
    import py_compile
    written = 0
    for path in stale(root):
        if not os.access(os.path.dirname(path), os.W_OK):    # a read-only share: compiling first would waste the work
            continue
        try:
            py_compile.compile(path, doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
        except (OSError, py_compile.PyCompileError):
            continue
        written += 1
    return written


def compile_missing_in_background(root: str, done=None) -> threading.Thread:
    """`compile_missing` on its own thread, for a caller that must not wait; `done` gets the count."""
    def run():
        written = compile_missing(root)
        if done is not None:
            done(written)

    worker = threading.Thread(target=run, name="amaze-bytecode", daemon=True)
    worker.start()
    return worker
