"""The only module that reads and writes an asset's `<id>.json`: its metadata and its builder."""

import json
import os
import threading

from amaze.core import category_conversion, debug, library_files, material
from amaze.helpers import hostos

FORMAT = 2
METADATA = "metadata"    # the row as its database holds it: what a lost database is rebuilt from
BUILDER = "builder"    # the container's type, its interface as a dialog script, its changed values
NAMES = "category_names"    # {id: name} of the row's categories, so a rebuild keeps their names
SECTIONS = (METADATA, BUILDER, NAMES)

LOCK = threading.RLock()    # two writers share the file: the asset save and the metadata writer


def path_for(preferences, mat_id, section: str) -> str:
    """The asset's `<id>.json` in its section's folder; PathOutsideBase for an unsafe id."""
    return material.payload_path(preferences, mat_id, material.RECORD_SUFFIX, section)


def _load(path: str) -> tuple:
    """(document, error, bytes): absent is ({}, "", None); corrupt or unreadable is logged."""
    raw = None
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        document = json.loads(raw.decode("utf-8-sig"))
    except FileNotFoundError:
        return {}, "", None
    except (OSError, ValueError) as exc:
        debug.event("library", "asset record corrupt/unreadable - read as empty",
                    file=path, error=str(exc))
        return {}, str(exc), raw
    if not isinstance(document, dict):
        debug.event("library", "asset record corrupt/unreadable - read as empty",
                    file=path, error="not an object")
        return {}, "not an object", raw
    return category_conversion.record(document), "", raw


def read(path: str) -> dict:
    """{metadata, builder}, each a dict, empty where absent; never raises into an import."""
    document = _load(path)[0]
    return {name: dict(document[name]) if isinstance(document.get(name), dict) else {}
            for name in SECTIONS}


def encode(document: dict) -> bytes:
    """The file's bytes, one spelling on every OS: the versions compare them."""
    return (json.dumps(document, indent=1, sort_keys=True) + "\n").encode("utf-8")


def put_sections(change, held, path: str, sections: dict) -> bool:
    """The record at `path` with `sections` replaced, checked against its read; False if same."""
    for section in sections:
        if section not in SECTIONS:
            raise ValueError("an asset record has no %r section" % section)
    relative = held.inside(path)
    if not relative:
        raise ValueError("%s is outside the library" % path)
    found, why, raw = _load(path)
    if why:    # an unreadable record is never written over: its metadata is the database's backup
        raise ValueError("%s does not read (%s), so it is not written over" % (path, why))
    document = dict(found)
    for section, data in sections.items():
        if data:
            document[section] = data
        else:
            document.pop(section, None)
    document["format"] = FORMAT
    data = encode(document)
    if data == raw:
        return False
    change.put_file(relative, data, was=raw)
    return True


def guard_for(path: str):
    """The guard of the library holding an `<id>.json`, in `<library>/<section>/`."""
    from amaze.core import guard
    return guard.Guard(library_files.library_of_file(path))


def unreadable(path: str) -> str:
    """Why an existing record cannot be read; `""` when it reads or is absent."""
    return _load(path)[1]


def write_section(path: str, section: str, data: dict, user: str = "") -> None:
    """Replace one section and keep the other, through the guard; OSError propagates."""
    with LOCK:
        why = unreadable(path)
        if why:    # an unreadable record is never overwritten
            raise OSError("%s does not read (%s), so it was not written" % (path, why))
        held = guard_for(path)
        change = held.change(user)
        put_sections(change, held, path, {section: data})
        change.commit()


TAKE, RECORD = "take", "record"    # a staged file: (TAKE, target, written) or (RECORD, path, sections)


def staged_write(target: str, write) -> tuple:
    """`write(scratch)` fills a scratch beside `target`, staged as (TAKE, target, scratch)."""
    hostos.check_sandbox(target)
    material.make_folders(target)
    scratch = hostos.unique_scratch(target)
    try:
        write(scratch)
    except BaseException:
        hostos.discard_scratch(scratch)
        raise
    return (TAKE, target, scratch)


def add_staged(change, held, staged: list, sections=None) -> None:
    """Each staged file into `change`; `sections` fills these sections of every record."""
    for kind, target, what in staged:
        if kind != TAKE:
            put_sections(change, held, target, dict(what, **(sections or {})))
            continue
        relative = held.inside(target)
        if not relative:
            raise ValueError("%s is outside the library" % target)
        change.take(relative, what)


def discard(staged: list) -> None:
    """Remove the written files a staged save leaves when its commit fails."""
    for kind, _target, what in staged:
        if kind == TAKE:
            hostos.discard_scratch(what)


def commit_staged_files(preferences, staged: list) -> None:
    """Commit an asset's staged files as one change, its row unchanged; OSError when it fails."""
    from amaze.core import guard, library_db
    held, made = library_db.guard_of(preferences), []

    def attempt():    # a record that moved under it is read again
        made.append(held.change(library_db.user(preferences)))
        with LOCK:
            add_staged(made[-1], held, staged)
            made[-1].commit()
    try:
        guard.retried(attempt)
    except BaseException as exc:
        if not (made and made[-1].journaled):    # a written journal finishes it at the next open
            discard(staged)
        if isinstance(exc, (guard.Refused, ValueError)):
            raise OSError(str(exc)) from exc
        raise


def builder_section(found: dict) -> dict:
    """`found` in the section's shape; {} for none; a type that is not a string becomes empty."""
    if not isinstance(found, dict) or not found:
        return {}
    values = found.get("values")
    kind, script = found.get("type"), found.get("interface")
    return {"type": kind if isinstance(kind, str) else "",
            "interface": script if isinstance(script, str) else "",
            "values": dict(values) if isinstance(values, dict) else {}}


def saved_builder(preferences, mat_id, section: str) -> dict:
    """The asset's builder from its `<id>.json`; {} when it has none or the path is refused."""
    try:
        path = path_for(preferences, mat_id, section)
    except (hostos.PathOutsideBase, TypeError, KeyError) as exc:
        debug.event("import", "builder path refused", mat_id=str(mat_id)[:120], error=str(exc))
        return {}
    return builder_section(read(path)[BUILDER])
