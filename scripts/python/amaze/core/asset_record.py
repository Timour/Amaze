"""The one reader and writer of an asset's `<id>.json`: its metadata and its builder."""

import json
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


def write_section(path: str, section: str, data: dict) -> None:
    """Replace one section and keep the other, written whole and atomically; OSError propagates."""
    if section not in SECTIONS:
        raise ValueError("an asset record has no %r section" % section)
    with LOCK:
        document, error = _load(path)
        if error:
            hostos.preserve_unreadable(path, why="asset record")
        document = dict(document)
        if data:
            document[section] = data
        else:
            document.pop(section, None)
        document["format"] = FORMAT
        hostos.write_json_atomic(path, document, serialised=encode(document))


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
