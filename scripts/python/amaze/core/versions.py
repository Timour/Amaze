"""A material's version store: `versions/` in its own folder, and its ledger. ▸r/version-store"""

from __future__ import annotations

import contextlib
import filecmp
import json
import os
import tempfile
import time

from amaze.core import asset_files, asset_record, debug, library_files, material, users
from amaze.core.material import RECORD_SUFFIX
from amaze.helpers import hostos

_KINDS = ((".mat", True), (RECORD_SUFFIX, False),    # the kinds a version archives; only .mat is required
          (".png", False))

SOURCE_KINDS = {    # `asset_files()` kind -> archive suffix; a kind absent here is not versioned
    "mat": ".mat",
    "json": RECORD_SUFFIX,    # archived as its builder alone ▸r/version-store
    "thumbnail": ".png",
}

LEDGER = "versions.json"


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
    return os.path.join(versions_dir(preferences, mat_id), LEDGER)


def read_ledger(preferences, mat_id: str) -> dict:
    """The ledger, or an empty one; an unreadable one reads as empty and create and switch fail."""
    path = _ledger_path(preferences, mat_id)
    if not os.path.exists(path):
        return {"active": 0, "versions": []}
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or \
                not isinstance(data.get("versions"), list):
            raise ValueError("not a ledger")
        return data
    except (OSError, ValueError) as exc:
        debug.event("versions", "ledger unreadable - versions hidden "
                    "this session", mat_id=str(mat_id), error=str(exc))
        return {"active": 0, "versions": [], "unreadable": True}


def _ledger_bytes(ledger: dict) -> bytes:
    return json.dumps(ledger, indent=1).encode("utf-8")


def _commit_files(preferences, writes: dict, removals=(), why: str = "") -> bool:
    """{path: bytes} written and `removals` removed as ONE commit via guard.py; whether it succeeded."""
    from amaze.core import library_db
    held = library_db.guard_of(preferences)
    change = held.change(str(getattr(preferences, "library_user", "") or ""))
    try:
        for path, data in writes.items():
            relative = held.inside(path)
            if not relative:
                debug.event("versions", "not written - outside the library", why=why, path=path)
                return False
            change.put_file(relative, data)
        for path in removals:
            change.remove(held.inside(path))
        change.commit()
    except OSError as exc:
        debug.event("versions", "not written - nothing changed", why=why, error=str(exc))
        return False
    return True


def _write_ledger(preferences, mat_id: str, ledger: dict) -> bool:
    return _commit_files(preferences,
                         {_ledger_path(preferences, mat_id): _ledger_bytes(ledger)},
                         why="ledger")


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
    active = int(ledger.get("active", 0) or 0)
    for entry in entries:
        if int(entry.get("n", 0)) == active:
            return version_label(entry)
    return version_label(entries[-1])    # active matches no row: return the newest


def _base_paths(preferences, mat_id: str) -> dict:
    """The material's own files by archive suffix."""
    owned = asset_files.asset_files_for(preferences, mat_id, library_files.MATERIALS)
    return {suffix: owned[kind] for kind, suffix in SOURCE_KINDS.items() if kind in owned}


def _builder_of(paths: dict) -> dict:
    """The builder a set of files holds in its `.json`; {} for none."""
    return asset_record.builder_section(
        asset_record.read(paths.get(RECORD_SUFFIX) or "")[asset_record.BUILDER])


@contextlib.contextmanager
def _staged_record(paths: dict, document: dict):
    """`paths` with its `.json` swapped for a scratch holding `document`; the scratch removed after."""
    handle, scratch = tempfile.mkstemp(prefix="amaze_version_", suffix=RECORD_SUFFIX)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(asset_record.encode(document))
        yield dict(paths, **{RECORD_SUFFIX: scratch})
    finally:
        hostos.discard_scratch(scratch)


def _archive_document(sources: dict) -> dict:
    """What a version's `<stem>.json` holds: the builder alone, never the metadata."""
    builder = _builder_of(sources)
    return {"format": asset_record.FORMAT, asset_record.BUILDER: builder} if builder \
        else {"format": asset_record.FORMAT}


def file_stem(mat_id: str, number: int) -> str:
    """The name every file of version `number` has, without its suffix: `<id>_<n>`."""
    return "%s_%d" % (mat_id, int(number))


def _row_for(ledger: dict, number: int) -> dict | None:
    for row in ledger.get("versions", []):
        if int(row.get("n", 0)) == int(number):
            return row
    return None


def _archive_paths(preferences, mat_id: str, number: int) -> dict:
    """Version `number`'s file set by suffix, each named by `file_stem`."""
    folder = versions_dir(preferences, mat_id)
    stem = file_stem(mat_id, number)
    return {kind: os.path.join(folder, stem + kind) for kind, _required in _KINDS}


def _copy_set(preferences, sources: dict, targets: dict, ledger=None) -> bool:
    """Copy every present kind, and `ledger` as (path, document), as ONE commit via guard.py."""
    writes, vacated = {}, []
    for kind, required in _KINDS:
        source = sources.get(kind)
        present = source and os.path.exists(source)
        if required and not present:
            debug.event("versions", "no %s to copy - copy stopped" % kind, source=source)
            return False
        if not present:
            if targets.get(kind) and os.path.exists(targets[kind]):
                vacated.append(targets[kind])    # the targets match the sources: it is removed too
            continue
        try:
            with open(source, "rb") as handle:
                writes[targets[kind]] = handle.read()
        except OSError as exc:
            debug.event("versions", "copy failed - nothing changed", source=source,
                        error=str(exc))
            return False
    if ledger is not None:
        writes[ledger[0]] = _ledger_bytes(ledger[1])
    return _commit_files(preferences, writes, vacated, why="version files")


def create_version(preferences, mat_id: str, name: str = "", source_paths: dict = None) -> int:
    """Archive the base, saved BEFORE the call, as a new active version; its number, 0 on failure."""
    ledger = read_ledger(preferences, mat_id)
    if ledger.get("unreadable"):
        debug.event("versions", "version not created - ledger unreadable",
                    mat_id=str(mat_id))
        return 0
    number = max([int(v.get("n", 0)) for v in ledger["versions"]] or [0]) + 1
    sources = source_paths or _base_paths(preferences, mat_id)
    while any(os.path.exists(path)    # a leftover file is never overwritten
              for path in _archive_paths(preferences, mat_id, number).values()):
        debug.event("versions", "a version file is already on disk - taking "
                                "the next number", mat_id=str(mat_id), n=number)
        number += 1
    author = ""    # the writer's name, stored in the row at write time
    try:
        writer = users.current(preferences)
        if writer:
            author = users.name_for(preferences, writer)
    except (AttributeError, OSError):
        pass
    ledger["versions"].append({
        "n": number,
        "name": name or ("Version %d" % number),
        "author": author,
        "date": time.strftime("%Y-%m-%d %H:%M"),
    })
    ledger["active"] = number
    with _staged_record(sources, _archive_document(sources)) as staged:
        copied = _copy_set(preferences, staged, _archive_paths(preferences, mat_id, number),
                           ledger=(_ledger_path(preferences, mat_id), ledger))
    if not copied:
        return 0
    debug.event("versions", "version created", mat_id=str(mat_id),
                n=number)
    return number


def _base_is_archived(preferences, mat_id: str, ledger: dict, base: dict = None) -> bool:
    """Whether the active archive holds the base, byte for byte, except the .png. ▸r/version-store"""
    row = _row_for(ledger, ledger.get("active", 0))
    if row is None:
        return False
    archive = _archive_paths(preferences, mat_id, row.get("n", 0))
    base = base or _base_paths(preferences, mat_id)
    if _builder_of(base) != _builder_of(archive):
        return False
    for kind, _required in _KINDS:
        if kind in (".png", RECORD_SUFFIX):    # the render is updated separately; the builder is compared above
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
    if _base_is_archived(preferences, mat_id, ledger, base):
        return True
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
    ledger = read_ledger(preferences, mat_id)    # keep_base may add a row and change `active`
    row = _row_for(ledger, number)
    if row is None:
        return False
    ledger["active"] = int(number)
    if not _restore(preferences, mat_id, int(number), base, ledger):
        debug.event("versions", "switch not made - nothing changed", mat_id=str(mat_id),
                    n=int(number))
        return False
    debug.event("versions", "active version switched",
                mat_id=str(mat_id), n=number)
    return True


def _restore(preferences, mat_id: str, number: int, base: dict, ledger: dict) -> bool:
    """Copy one archive over the base and write the ledger, as one commit; the metadata is kept."""
    archive = _archive_paths(preferences, mat_id, number)
    named = (_ledger_path(preferences, mat_id), ledger)
    target = base.get(RECORD_SUFFIX) or asset_record.path_for(
        preferences, mat_id, library_files.MATERIALS)
    with asset_record.LOCK:    # no metadata write happens between the read and the copy
        document = {"format": asset_record.FORMAT}
        metadata = asset_record.read(target)[asset_record.METADATA]
        builder = _builder_of(archive)
        if metadata:
            document[asset_record.METADATA] = metadata
        if builder:
            document[asset_record.BUILDER] = builder
        with _staged_record(archive, document) as staged:
            return _copy_set(preferences, staged, dict(base, **{RECORD_SUFFIX: target}),
                             ledger=named)


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
        if not _commit_files(preferences, {target: data}, why="active slot"):
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
    ledger = read_ledger(preferences, mat_id)
    if ledger.get("unreadable"):
        return False
    for version in ledger["versions"]:
        if int(version.get("n", 0)) == int(number):
            version["name"] = name
            return _write_ledger(preferences, mat_id, ledger)
    return False


def version_file(preferences, mat_id: str, number: int) -> str:
    """Version `number`'s network file; empty when it has no row or the file is missing."""
    if _row_for(read_ledger(preferences, mat_id), number) is None:
        return ""
    path = _archive_paths(preferences, mat_id, number)[".mat"]
    return path if os.path.exists(path) else ""
