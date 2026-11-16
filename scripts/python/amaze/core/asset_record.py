"""The one reader and writer of an asset's `<id>.json`: its metadata and its builder."""

import json
import os
import threading

from amaze.core import debug, material
from amaze.helpers import hostos

FORMAT = 1
METADATA = "metadata"    # the row as its database holds it: what a lost database is rebuilt from
BUILDER = "builder"    # the container's type, its interface as a dialog script, its changed values
SECTIONS = (METADATA, BUILDER)

LOCK = threading.RLock()    # two writers share the file: the asset save and the metadata writer


def path_for(preferences, mat_id, section: str) -> str:
    """The asset's `<id>.json` in its section's folder; PathEscape for an unsafe id."""
    return material.payload_path(preferences, mat_id, material.RECORD_SUFFIX, section)


def _load(path: str) -> tuple:
    """(document, error): absent is ({}, ""), corrupt/unreadable is ({}, why) and logged."""
    try:
        with open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
    except FileNotFoundError:
        return {}, ""
    except (OSError, ValueError) as exc:
        debug.event("library", "asset record corrupt/unreadable - read as empty",
                    file=path, error=str(exc))
        return {}, str(exc)
    if not isinstance(document, dict):
        debug.event("library", "asset record corrupt/unreadable - read as empty",
                    file=path, error="not an object")
        return {}, "not an object"
    return document, ""


def read(path: str) -> dict:
    """{metadata, builder}, each a dict, empty where absent; never raises into an import."""
    document, _error = _load(path)
    return {name: dict(document[name]) if isinstance(document.get(name), dict) else {}
            for name in SECTIONS}


def encode(document: dict) -> bytes:
    """The file's bytes, one spelling on every OS: the versions compare them."""
    return (json.dumps(document, indent=1, sort_keys=True) + "\n").encode("utf-8")


def with_sections(path: str, sections: dict) -> bytes:
    """The bytes of `path`'s record with `sections` replaced and the rest kept; an empty one goes."""
    for section in sections:
        if section not in SECTIONS:
            raise ValueError("an asset record has no %r section" % section)
    document = dict(_load(path)[0])
    for section, data in sections.items():
        if data:
            document[section] = data
        else:
            document.pop(section, None)
    document["format"] = FORMAT
    return encode(document)


def guard_for(path: str):
    """The guard of the library an `<id>.json` sits in: two folders up, `<library>/<section>/`."""
    from amaze.core import guard
    return guard.Guard(os.path.dirname(os.path.dirname(os.path.abspath(path))))


def write_section(path: str, section: str, data: dict, user: str = "") -> None:
    """Replace one section and keep the other, through the guard; OSError propagates."""
    with LOCK:
        held = guard_for(path)
        relative = held.inside(path)
        if not relative:
            raise ValueError("%s is no asset record of a library" % path)
        change = held.change(user)
        change.put_file(relative, with_sections(path, {section: data}))
        change.commit()


TAKE, RECORD = "take", "record"    # a staged file: (TAKE, target, written) or (RECORD, path, sections)


def add_staged(change, held, staged: list, metadata=None) -> None:
    """Each staged file into `change`; `metadata` fills every record's metadata section."""
    for kind, target, what in staged:
        relative = held.inside(target)
        if not relative:
            raise ValueError("%s is outside the library" % target)
        if kind == TAKE:
            change.take(relative, what)
        else:
            sections = dict(what)
            if metadata is not None:
                sections[METADATA] = metadata
            change.put_file(relative, with_sections(target, sections))


def discard(staged: list) -> None:
    """Remove the written files a staged save leaves when it does not land."""
    for kind, _target, what in staged:
        if kind == TAKE:
            hostos.discard_scratch(what)


def land(preferences, staged: list) -> None:
    """An asset's staged files as one unit, its row unchanged; OSError when it did not land."""
    from amaze.core import guard, library_db
    held = library_db.guard_of(preferences)
    change = held.change(str(getattr(preferences, "library_user", "") or ""))
    try:
        with LOCK:
            add_staged(change, held, staged)
            change.commit()
    except (guard.Refused, ValueError) as exc:
        discard(staged)
        raise OSError(str(exc)) from exc


def builder_section(found: dict) -> dict:
    """`found` in the section's shape; {} for none, and a type that is not text names none."""
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
    except (hostos.PathEscape, TypeError, KeyError) as exc:
        debug.event("import", "builder path refused", mat_id=str(mat_id)[:120], error=str(exc))
        return {}
    return builder_section(read(path)[BUILDER])
