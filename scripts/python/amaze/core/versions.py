"""A material's version store: `versions/` in its own folder, and its ledger. ▸r/version-store"""

from __future__ import annotations

import filecmp
import json
import os
import time

from amaze.core import asset_files, asset_record, debug, guard, library_files, material, users
from amaze.core.material import RECORD_SUFFIX
from amaze.helpers import hostos

_KINDS = tuple((suffix, suffix == ".mat")    # the kinds a version archives; only .mat is required
               for suffix in library_files.VERSION_SUFFIXES)

SOURCE_KINDS = dict(zip(("mat", "json", "thumbnail", "cop"),    # `asset_files()` kind -> suffix
                        library_files.VERSION_SUFFIXES))    # the .json: `_archive_document`
NETWORK_FIELDS = ("cop_net",)    # the row's fields that describe its network files: per version
DATE = "%Y-%m-%d %H:%M"    # a ledger row's date


def versions_dir(preferences, mat_id: str) -> str:
    """`<asset folder>/versions/`; contained like every id path."""
    return os.path.join(material.asset_dir(preferences, library_files.MATERIALS, mat_id),
                        library_files.VERSIONS)


def stored_ids(preferences) -> set:
    """The ids whose asset folder holds `versions/`."""
    return {owner for owner, folder in material.asset_ids_with_folders(
        preferences, library_files.MATERIALS).items()
        if os.path.isdir(os.path.join(folder, library_files.VERSIONS))}


def _ledger_path(preferences, mat_id: str) -> str:
    return os.path.join(versions_dir(preferences, mat_id), library_files.LEDGER)


def read_ledger(preferences, mat_id: str) -> dict:
    """The ledger, or an empty one; an unreadable one reads as empty and every change refuses."""
    return ledger_in(_ledger_path(preferences, mat_id), mat_id)


def ledger_in(path: str, mat_id: str = "") -> dict:
    """The ledger at `path`: empty when absent, empty and marked `unreadable` when it cannot be read."""
    return _ledger_read(path, mat_id)[0]


def _ledger_read(path: str, mat_id: str = "") -> tuple:
    """(the ledger at `path` as `ledger_in` reads it, the bytes it was read from or None)."""
    raw = None
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict) or \
                not isinstance(data.get("versions"), list):
            raise ValueError("not a ledger")
        return data, raw
    except FileNotFoundError:
        return {"active": 0, "versions": []}, None
    except (OSError, ValueError) as exc:
        debug.event("versions", "ledger unreadable - versions hidden "
                    "this session", mat_id=str(mat_id), error=str(exc))
        return {"active": 0, "versions": [], "unreadable": True}, raw


def _ledger_bytes(ledger: dict) -> bytes:
    return json.dumps(ledger, indent=1).encode("utf-8")


def _inside(held, path: str) -> str:
    """`path` relative to the library `held` guards; Refused for one outside it."""
    relative = held.inside(path)
    if not relative:
        raise guard.Refused("%s is outside the library" % path)
    return relative


def _put_ledger(change, held, path: str, ledger: dict, raw) -> None:
    """The ledger at `path` into `change`; the commit refuses it if the file moved since `raw`."""
    change.put_file(_inside(held, path), _ledger_bytes(ledger), was=raw)


def _commit(preferences, fill, why: str) -> bool:
    """`fill(change, guard)` reads and puts one change, committed whole; again if a file moves."""
    from amaze.core import library_db
    held = library_db.guard_of(preferences)

    def attempt():
        change = held.change(library_db.user(preferences))
        fill(change, held)
        change.commit()
    try:
        guard.retried(attempt)
    except (OSError, guard.Refused) as exc:    # Moved too, once the files kept moving
        debug.event("versions", "not written - nothing changed", why=why, error=str(exc))
        return False
    return True


def version_count(preferences, mat_id: str) -> int:
    """How many versions exist. The badge shows at > 1."""
    return len(read_ledger(preferences, mat_id).get("versions", []))


def list_versions(preferences, mat_id: str) -> list:
    """[{n, name, author, date}] oldest first, plus which is active."""
    return list(read_ledger(preferences, mat_id).get("versions", []))


def active_version(preferences, mat_id: str) -> int:
    return int(read_ledger(preferences, mat_id).get("active", 0) or 0)


def version_label(entry: dict) -> str:
    """What a version is called: its name, or `Version <n>` for one saved without a name."""
    return str(entry.get("name") or ("Version %d" % int(entry.get("n", 0))))


def active_version_name(preferences, mat_id: str) -> str:
    """The name of the version in the base, empty for an asset with none; list mode shows it."""
    ledger = read_ledger(preferences, mat_id)
    entries = ledger.get("versions", [])
    if not entries:
        return ""
    return version_label(_row_for(ledger, ledger.get("active", 0) or 0)
                         or entries[-1])    # active matches no row: the newest


def _base_paths(preferences, mat_id: str) -> dict:
    """The material's own files by archive suffix."""
    owned = asset_files.asset_files_for(preferences, mat_id, library_files.MATERIALS)
    return {suffix: owned[kind] for kind, suffix in SOURCE_KINDS.items() if kind in owned}


def _archive_document(paths: dict) -> dict:
    """What a version's `<stem>.json` holds of the files `paths`: the builder, NETWORK_FIELDS."""
    found = asset_record.read(paths.get(RECORD_SUFFIX) or "")
    metadata = found[asset_record.METADATA]
    sections = {asset_record.BUILDER: asset_record.builder_section(found[asset_record.BUILDER]),
                asset_record.METADATA: {field: metadata[field] for field in NETWORK_FIELDS
                                        if metadata.get(field)}}
    return dict({name: data for name, data in sections.items() if data},
                format=asset_record.FORMAT)


def file_stem(mat_id: str, number: int) -> str:
    """The name every file of version `number` has, without its suffix: `<id>_<n>`."""
    return "%s_%d" % (mat_id, int(number))


def _row_for(ledger: dict, number: int) -> dict | None:
    for row in ledger.get("versions", []):
        if int(row.get("n", 0)) == int(number):
            return row
    return None


def _highest(ledger: dict) -> int:
    """The highest number ever given out: the stored `highest`, else the largest row's."""
    return max([int(row.get("n", 0)) for row in ledger.get("versions", [])]
               + [int(ledger.get("highest", 0) or 0)])


def _archive_paths(preferences, mat_id: str, number: int) -> dict:
    """Version `number`'s file set by suffix, each named by `file_stem`."""
    folder = versions_dir(preferences, mat_id)
    stem = file_stem(mat_id, number)
    return {kind: os.path.join(folder, stem + kind) for kind, _required in _KINDS}


def _put_set(change, held, sources: dict, targets: dict, new: bool) -> None:
    """Each kind but the record put from `sources` at `targets`; one `sources` lacks is trashed."""
    for kind, required in _KINDS:
        source = sources.get(kind)
        if kind == RECORD_SUFFIX:
            continue    # each caller puts the record it needs
        if not (source and os.path.exists(source)):
            if required:
                raise guard.Refused("no %s to copy from %s" % (kind, source))
            if os.path.exists(targets[kind]):    # the targets match the sources: it goes too
                change.trash(_inside(held, targets[kind]))
            continue
        with open(source, "rb") as handle:    # a new version's file is refused once one is there
            change.put_file(_inside(held, targets[kind]), handle.read(),
                            None if new else guard.UNCHECKED)


def _author(preferences) -> str:
    """The writer's name, stored in a row at write time; empty when no user is known."""
    try:
        writer = users.current(preferences)
        return users.name_for(preferences, writer) if writer else ""
    except (AttributeError, OSError):
        return ""


def create_version(preferences, mat_id: str, name: str = "", source_paths: dict = None) -> int:
    """Archive the base, saved BEFORE the call, as a new active version; its number, 0 if not."""
    from amaze.core import library_db
    library_db.flush(preferences)    # the base's record gets its row's pending changes first
    sources, made = source_paths or _base_paths(preferences, mat_id), []

    def fill(change, held):
        ledger, raw = _ledger_read(_ledger_path(preferences, mat_id), mat_id)
        if ledger.get("unreadable"):
            raise guard.Refused("the version list does not read")
        number = _highest(ledger) + 1
        while any(os.path.exists(path)    # a leftover file is never overwritten
                  for path in _archive_paths(preferences, mat_id, number).values()):
            debug.event("versions", "a version file is already on disk - taking "
                                    "the next number", mat_id=str(mat_id), n=number)
            number += 1
        ledger["versions"].append({"n": number, "name": name or version_label({"n": number}),
                                   "author": _author(preferences), "date": time.strftime(DATE)})
        ledger["active"] = ledger["highest"] = number
        targets = _archive_paths(preferences, mat_id, number)
        _put_set(change, held, sources, targets, new=True)
        change.put_file(_inside(held, targets[RECORD_SUFFIX]),
                        asset_record.encode(_archive_document(sources)), was=None)
        _put_ledger(change, held, _ledger_path(preferences, mat_id), ledger, raw)
        made[:] = [number]
    if not _commit(preferences, fill, "version files"):
        return 0
    debug.event("versions", "version created", mat_id=str(mat_id), n=made[0])
    return made[0]


def _base_is_archived(preferences, mat_id: str, ledger: dict, base: dict = None) -> bool:
    """Whether the active archive holds the base, byte for byte, except the .png. ▸r/version-store"""
    row = _row_for(ledger, ledger.get("active", 0))
    if row is None:
        return False
    archive = _archive_paths(preferences, mat_id, row.get("n", 0))
    base = base or _base_paths(preferences, mat_id)
    if _archive_document(base) != _archive_document(archive):
        return False
    for kind, _required in _KINDS:
        if kind in (".png", RECORD_SUFFIX):    # the render is kept separately; the record is above
            continue
        base_path, archive_path = base.get(kind), archive.get(kind)
        in_base = bool(base_path) and os.path.exists(base_path)
        in_archive = bool(archive_path) and os.path.exists(archive_path)
        if in_base != in_archive:
            return False
        try:
            if in_base and not filecmp.cmp(base_path, archive_path,
                                           shallow=False):
                return False
        except OSError:
            return False
    return True


def keep_base(preferences, mat_id: str, base_paths: dict = None, name: str = "") -> bool:
    """Archive the base as a version unless the active one holds it; False when it could not be."""
    ledger = read_ledger(preferences, mat_id)
    if ledger.get("unreadable"):
        return False
    base = base_paths or _base_paths(preferences, mat_id)
    if not os.path.isfile(base.get(".mat") or "") or _base_is_archived(preferences, mat_id, ledger, base):
        return True    # no network on disk is nothing to lose; an archived one is kept already
    return bool(create_version(preferences, mat_id, name, base))


def switch_active(preferences, mat_id: str, number: int, base_paths: dict = None,
                  base_name: str = "") -> bool:
    """Copy version `number` over the base and mark it active; an unarchived base is archived first."""
    from amaze.core import library_db
    library_db.flush(preferences)    # every pending change is saved to the base's record before it is read
    ledger = read_ledger(preferences, mat_id)
    if ledger.get("unreadable"):
        return False
    row = _row_for(ledger, number)
    if row is None:
        debug.event("versions", "switch not made - no such version",
                    mat_id=str(mat_id), n=number)
        return False
    base = base_paths or _base_paths(preferences, mat_id)
    if not keep_base(preferences, mat_id, base, base_name):
        debug.event("versions", "switch not made - the base holds "
                                "unarchived content and could not "
                                "be archived",
                    mat_id=str(mat_id), n=number)
        return False
    held, mat_id = library_db.document(preferences, library_files.MATERIALS), str(mat_id)
    was = held.get("assets", mat_id)
    if not isinstance(was, dict):
        return False
    kept = _archive_document(_archive_paths(preferences, mat_id, number)).get(
        asset_record.METADATA, {})
    with library_db.library_for(preferences).holding():    # saved below with the files, at once
        edited = held.edit("assets", mat_id, **{
            field: kept.get(field) or {} for field in NETWORK_FIELDS
            if (was.get(field) or {}) != (kept.get(field) or {})})
    saved = held.save(also=lambda change: _restore(change, held, preferences, mat_id, int(number),
                                                   base))
    if not saved:
        if edited:
            with library_db.library_for(preferences).holding():
                held.put("assets", mat_id, was)    # the row as it was, the files not switched
        debug.event("versions", "switch not made - nothing changed", mat_id=mat_id,
                    n=int(number), reason=saved.reason, detail=saved.detail)
        return False
    debug.event("versions", "active version switched",
                mat_id=mat_id, n=number)
    return True


def _restore(change, held, preferences, mat_id: str, number: int, base: dict) -> None:
    """`also` of a switch: the archive over the base, the row's record, the list naming it."""
    from amaze.core import library_db
    ledger, raw = _ledger_read(_ledger_path(preferences, mat_id), mat_id)    # again on each try
    row = held.get("assets", mat_id)
    if ledger.get("unreadable") or _row_for(ledger, number) is None or not isinstance(row, dict):
        raise guard.Refused("version %d of %s is gone" % (number, mat_id))
    ledger["active"] = number
    archive = _archive_paths(preferences, mat_id, number)
    _put_set(change, held.guard, archive, base, new=False)
    target = base.get(RECORD_SUFFIX) or asset_record.path_for(
        preferences, mat_id, library_files.MATERIALS)
    asset_record.put_sections(change, held.guard, target, dict(
        library_db.record_sections(held, row),
        **{asset_record.BUILDER: _archive_document(archive).get(asset_record.BUILDER, {})}))
    _put_ledger(change, held.guard, _ledger_path(preferences, mat_id), ledger, raw)


def record_render(preferences, mat_id: str) -> bool:
    """Copy the base thumbnail into the active archive: a version is made before its render exists."""
    return record_base(preferences, mat_id, ".png")


def record_base(preferences, mat_id: str, kind: str, source: str = "") -> bool:
    """Copy one kind of the base over the ACTIVE version's archive while that version holds the base."""
    active = 0
    try:
        ledger = read_ledger(preferences, mat_id)
        if ledger.get("unreadable") or not ledger.get("versions"):
            return False
        active = int(ledger.get("active", 0) or 0)
        active_row = _row_for(ledger, active)
        if active_row is None:
            return False
        base = _base_paths(preferences, mat_id)
        if not _base_is_archived(preferences, mat_id, ledger, base):    # saved over with Versions off
            return False
        source = source or base.get(kind)
        if not source or not os.path.exists(source):
            return False
        target = _archive_paths(preferences, mat_id, active)[kind]
        if os.path.exists(target) and filecmp.cmp(source, target,
                                                  shallow=False):
            return True
        with open(source, "rb") as handle:
            data = handle.read()
        if not _commit(preferences, lambda change, held: change.put_file(
                _inside(held, target), data), "active slot"):
            return False
    except (OSError, hostos.PathOutsideBase) as exc:    # best-effort: it follows a save, never raises
        debug.event("versions", "base not recorded to the active slot",
                    mat_id=str(mat_id), n=active, kind=kind, error=str(exc))
        return False
    debug.event("versions", "base recorded to the active slot",
                mat_id=str(mat_id), n=active, kind=kind)
    return True


def rename_version(preferences, mat_id: str, number: int, name: str) -> bool:
    """Rename one version in the ledger; a name is a label, so no file moves."""
    name = str(name or "").strip()
    if not name:
        return False

    def fill(change, held):
        ledger, raw = _ledger_read(_ledger_path(preferences, mat_id), mat_id)
        row = _row_for(ledger, number)
        if row is None:    # an unreadable list has no row
            raise guard.Refused("version %s is not in the version list" % number)
        row["name"] = name
        _put_ledger(change, held, _ledger_path(preferences, mat_id), ledger, raw)
    return _commit(preferences, fill, "rename version")


def delete_version(preferences, mat_id: str, number: int) -> bool:
    """Trash version `number`'s files and take out its row as one commit; never the active one."""
    def fill(change, held):
        ledger, raw = _ledger_read(_ledger_path(preferences, mat_id), mat_id)
        row = _row_for(ledger, number)
        if row is None or int(number) == int(ledger.get("active", 0) or 0):    # unreadable: no row
            raise guard.Refused("version %s is not one to delete" % number)
        ledger["highest"] = _highest(ledger)    # a deleted number is never given out again
        ledger["versions"].remove(row)
        for path in _archive_paths(preferences, mat_id, number).values():
            if os.path.exists(path):
                change.trash(_inside(held, path))
        _put_ledger(change, held, _ledger_path(preferences, mat_id), ledger, raw)
    if not _commit(preferences, fill, "delete version"):
        return False
    debug.event("versions", "version deleted", mat_id=str(mat_id), n=number)
    return True


def put_back(change, held, networks: list) -> int:
    """Each network `<id>_<n>.mat` its list lacks added to the list, with n and its file's date."""
    added, folders = 0, {}
    for path in networks:
        folders.setdefault(os.path.dirname(path), []).append(path)
    for folder, paths in sorted(folders.items()):
        owner = library_files.folder_id(os.path.basename(os.path.dirname(folder)))
        ledger, raw = _ledger_read(os.path.join(folder, library_files.LEDGER), owner)
        if ledger.get("unreadable"):
            continue    # never written over
        rows = len(ledger["versions"])
        listed = {int(row.get("n", 0)) for row in ledger["versions"]}
        for path in sorted(paths):
            number = library_files.version_number(os.path.basename(path), owner, (".mat",))
            if number is None or number in listed or not os.path.isfile(path):
                continue    # listed meanwhile, or gone
            date = time.strftime(DATE, time.localtime(os.path.getmtime(path)))
            ledger["versions"].append({"n": number, "date": date})
            listed.add(number)
        if len(ledger["versions"]) > rows:
            added += len(ledger["versions"]) - rows
            ledger["versions"].sort(key=lambda row: int(row.get("n", 0)))    # oldest first
            ledger["highest"] = _highest(ledger)
            _put_ledger(change, held, os.path.join(folder, library_files.LEDGER), ledger, raw)
    return added


def version_file(preferences, mat_id: str, number: int) -> str:
    """Version `number`'s network file; empty when it has no row or the file is missing."""
    if _row_for(read_ledger(preferences, mat_id), number) is None:
        return ""
    path = _archive_paths(preferences, mat_id, number)[".mat"]
    return path if os.path.exists(path) else ""
