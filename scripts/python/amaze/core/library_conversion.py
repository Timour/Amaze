"""The only module that knows format 3: its file shapes, and the builder its files hold."""

import json
import re

from amaze.core import asset_record, debug, library_files

OLD_FOLDER = "mat"    # format 3: every section's asset files and version folders, together
OLD_PICTURES = "img"    # format 3: `img/<id>.png`, `img/<id>_icon.png`, `img/comments/<hex>.<ext>`
OLD_CAPTURES = "captures"    # format 3: `captures/<id>.png` and `captures/file_<sha1>.png`
INTERFACE = ".interface"    # the builder as `asCode()` Python: read for its type, never executed
BUILDER = ".builder.json"    # the builder as data, its interface under `dialog_script`
STAMP = ".stamp.json"    # the row, written beside the asset files
OLD_SUFFIXES = (BUILDER, STAMP, INTERFACE)
ICON_TAIL = "_icon"    # `img/<id>_icon.png`: a custom icon composed to disk
TEXTURE_UPDATE_BACKUP = ".pre-adopt"    # `mat/<id>.mat.pre-adopt`: backups an earlier texture update left
OLD_MEMBER_KINDS = ("builder", "interface", "stamp", "tile_icon", "capture")    # an old package's
OLD_POLICY = "policy.json"    # format 3's policy file, which the tests' older library writes

_CREATE_NODE = re.compile(rb'createNode\(\s*[\'"]([^\'"]+)[\'"]')


def interface_type(raw: bytes) -> str:
    """The builder type a format 3 `.interface` creates first, or ""."""
    match = _CREATE_NODE.search(raw or b"")
    return match.group(1).decode("utf-8", "replace") if match else ""


def builder_from_bytes(raw: bytes, interface, stale: bool = False, where: str = "") -> dict:
    """The builder section from `.builder.json`'s bytes; `interface()` returns `.interface`'s."""
    data = {}
    if raw:
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except ValueError as exc:
            debug.event("convert", "builder sidecar unreadable", path=where, error=str(exc))
            data = {}
        if not isinstance(data, dict) or "dialog_script" not in data:
            debug.event("convert", "builder sidecar has the wrong shape", path=where)
            data = {}
    found = asset_record.builder_section(dict(data, interface=data.get("dialog_script"))) \
        if data else {}
    if not found.get("type") or stale:    # re-saved by an Amaze that wrote no sidecar
        typed = interface_type(interface())
        if typed:
            found = dict(found or {"interface": "", "values": {}}, type=typed)
    return found


def builder_from_members(held: dict) -> dict:
    """The builder in a package's members: a new `json`, else format 3's `builder`/`interface`."""
    if held.get("json"):
        try:
            document = json.loads(held["json"].decode("utf-8-sig"))
        except (ValueError, AttributeError) as exc:
            debug.event("packages", "builder member unreadable", error=str(exc))
            document = {}
        found = asset_record.builder_section((document or {}).get(asset_record.BUILDER)) \
            if isinstance(document, dict) else {}
        if found:
            return found
    return builder_from_bytes(held.get("builder", b""), lambda: held.get("interface", b""))


def _id_of(name: str, suffixes: tuple) -> str:
    """The id of a format 3 file name, by the old rule: letters and digits only."""
    for suffix in suffixes:
        if name.endswith(suffix) and name[: -len(suffix)].isalnum():
            return name[: -len(suffix)]
    return ""


def old_shape(relative: str) -> bool:
    """Whether a library path is one only format 3 wrote: a leftover the conversion did not use."""
    parts = library_files.split(relative)
    if not parts:
        return False
    top, name = parts[0], parts[-1]
    if top == OLD_FOLDER:    # files left in `mat/` are unknown to the conversion: reported, never removed
        return False
    if len(parts) == 2 and library_files.owns_assets(top) and name.endswith(TEXTURE_UPDATE_BACKUP):
        return bool(_id_of(name[: -len(TEXTURE_UPDATE_BACKUP)], (".mat",)))
    if len(parts) == 2 and library_files.owns_assets(top):
        return bool(_id_of(name, OLD_SUFFIXES))
    if len(parts) == 2 and top == OLD_PICTURES:
        return bool(_id_of(name, (ICON_TAIL + ".png", ".png")))
    if len(parts) == 2 and top == OLD_CAPTURES:
        return not name.startswith("file_") and bool(_id_of(name, (".png",)))
    if len(parts) == 4 and parts[1] == library_files.VERSIONS and library_files.owns_assets(top):
        return name.endswith((BUILDER, INTERFACE))
    return False

