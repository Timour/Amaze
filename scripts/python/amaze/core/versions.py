"""Every section's version store: a folder per asset and its ledger. ▸r/version-store"""

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

CODE_SUFFIX = ".txt"    # a code version is its snippet's text, one file


class Section:
    """Where one section keeps its versions, and the files one version holds."""

    __slots__ = ("folder", "kinds", "source_kinds", "database")

    def __init__(self, folder, kinds: tuple, source_kinds: dict, database: str) -> None:
        self.folder = folder                # preferences -> the store's path parts in the library
        self.kinds = kinds                  # ((suffix, required), ...)
        self.source_kinds = source_kinds    # asset_files() kind -> suffix; {}: the caller passes the files in
        self.database = database            # the section's database, which names its folder

    def payload(self) -> str:
        """The suffix without which a set of files is not a version."""
        return next(suffix for suffix, required in self.kinds if required)


def _asset_section(database: str) -> Section:
    return Section(lambda preferences: (library_files.SECTION_FOLDERS[database],
                                        library_files.VERSIONS),
                   _KINDS, SOURCE_KINDS, database)


MATERIAL = _asset_section(library_files.MATERIALS)
NODE = _asset_section(library_files.NODES)
CODE = Section(lambda preferences: (library_files.CODE_FOLDER, library_files.VERSIONS),
               ((CODE_SUFFIX, True),), {}, "code.json")    # its text is in code.json


def versions_dir(preferences, mat_id: str, section: Section = MATERIAL) -> str:
    """`<section folder>/versions/<id>/`, contained like every id-derived path."""
    if section.database in library_files.ASSET_SECTIONS:
        return material.owned_path(preferences, section.database, library_files.VERSIONS,
                                   str(mat_id))
    return hostos.contained_join(
        os.path.join(preferences.dir, *section.folder(preferences)), str(mat_id))


def store_root(preferences, section: Section = MATERIAL) -> str:
    """The folder holding every store of `section`: one listing shows which assets have one."""
    return os.path.join(preferences.dir, *section.folder(preferences))


def stored_ids(preferences, section: Section = MATERIAL) -> set:
    """The ids with a store, by one listing of `store_root`."""
    found = set()
    try:
        found = set(os.listdir(store_root(preferences, section)))
    except OSError:
        pass
    return found


def _ledger_path(preferences, mat_id: str, section: Section = MATERIAL) -> str:
    return os.path.join(versions_dir(preferences, mat_id, section), LEDGER)


def read_ledger(preferences, mat_id: str, section: Section = MATERIAL) -> dict:
    """The ledger, or an empty one; an unreadable one reads as empty and create and switch fail."""
    path = _ledger_path(preferences, mat_id, section)
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


def _land(preferences, writes: dict, removals=(), why: str = "") -> bool:
    """{path: bytes} written and `removals` removed as ONE commit via guard.py; whether it succeeded."""
    from amaze.core import library_db
    held = library_db.guard_of(preferences)
    change = held.change(str(getattr(preferences, "library_user", "") or ""))
    outside = {}    # a caller's own staged copy, as a snippet's text is: written after the commit
    try:
        for path, data in writes.items():
            relative = held.inside(path)
            if not relative:
                outside[path] = data
                continue
            change.put_file(relative, data)
        for path in removals:
            change.remove(held.inside(path))
        change.commit()
        for path, data in outside.items():
            with open(path, "wb") as handle:
                handle.write(data)
    except OSError as exc:
        debug.event("versions", "not written - nothing changed", why=why, error=str(exc))
        return False
    return True


def _write_ledger(preferences, mat_id: str, ledger: dict,
                  section: Section = MATERIAL) -> bool:
    return _land(preferences, {_ledger_path(preferences, mat_id, section): _ledger_bytes(ledger)},
                 why="ledger")


def version_count(preferences, mat_id: str, section: Section = MATERIAL) -> int:
    """How many versions exist. The badge shows at > 1."""
    return len(read_ledger(preferences, mat_id, section).get("versions", []))


def list_versions(preferences, mat_id: str, section: Section = MATERIAL) -> list:
    """[{n, name, author, date}] oldest first, plus which is active."""
    ledger = read_ledger(preferences, mat_id, section)
    return list(ledger.get("versions", []))


def active_version(preferences, mat_id: str, section: Section = MATERIAL) -> int:
    return int(read_ledger(preferences, mat_id, section).get("active", 0) or 0)


def version_label(entry: dict) -> str:
    """What a version is called: its name, or `Version <n>` for one saved without a name."""
    return str(entry.get("name") or ("Version %d" % int(entry.get("n", 0))))


def active_version_name(preferences, mat_id: str, section: Section = MATERIAL) -> str:
    """The name of the version in the base, empty for an asset with none; list mode shows it."""
    ledger = read_ledger(preferences, mat_id, section)
    entries = ledger.get("versions", [])
    if not entries:
        return ""
    active = int(ledger.get("active", 0) or 0)
    for entry in entries:
        if int(entry.get("n", 0)) == active:
            return version_label(entry)
    return version_label(entries[-1])    # active matches no row: return the newest


def _base_paths(preferences, mat_id: str, section: Section = MATERIAL) -> dict:
    """The asset's own files by archive suffix; {} where the caller passes the base in."""
    if not section.source_kinds:
        return {}
    owned = asset_files.asset_files_for(preferences, mat_id, section.database)
    return {suffix: owned[kind] for kind, suffix in section.source_kinds.items()
            if kind in owned}


def _builder_of(paths: dict) -> dict:
    """The builder a set of files holds in its `.json`; {} for none."""
    return asset_record.builder_section(
        asset_record.read(paths.get(RECORD_SUFFIX) or "")[asset_record.BUILDER])


@contextlib.contextmanager
def _staged_record(paths: dict, document: dict, section: Section):
    """`paths` with its `.json` swapped for a scratch holding `document`; the scratch removed after."""
    if RECORD_SUFFIX not in dict(section.kinds):
        yield paths
        return
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


def _archive_paths(preferences, mat_id: str, number: int,
                   section: Section = MATERIAL) -> dict:
    """Version `number`'s file set by suffix, each named by `file_stem`."""
    folder = versions_dir(preferences, mat_id, section)
    stem = file_stem(mat_id, number)
    return {kind: os.path.join(folder, stem + kind) for kind, _required in section.kinds}


def _copy_set(preferences, sources: dict, targets: dict, kinds: tuple = _KINDS,
              ledger=None) -> bool:
    """Copy every present kind, and `ledger` as (path, document), as ONE commit via guard.py."""
    writes, vacated = {}, []
    for kind, required in kinds:
        source = sources.get(kind)
        present = source and os.path.exists(source)
        if required and not present:
            debug.event("versions", "no %s to copy - refused" % kind, source=source)
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
    return _land(preferences, writes, vacated, why="version files")


def create_version(preferences, mat_id: str, name: str = "",
                   source_paths: dict = None, section: Section = MATERIAL) -> int:
    """Archive the base, saved BEFORE the call, as a new active version; its number, 0 on failure."""
    ledger = read_ledger(preferences, mat_id, section)
    if ledger.get("unreadable"):
        debug.event("versions", "create refused - ledger unreadable",
                    mat_id=str(mat_id))
        return 0
    number = max([int(v.get("n", 0)) for v in ledger["versions"]] or [0]) + 1
    sources = source_paths or _base_paths(preferences, mat_id, section)
    while any(os.path.exists(path) for path    # a leftover file is never overwritten
              in _archive_paths(preferences, mat_id, number, section).values()):
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
    with _staged_record(sources, _archive_document(sources), section) as staged:
        copied = _copy_set(preferences, staged,
                           _archive_paths(preferences, mat_id, number, section), section.kinds,
                           ledger=(_ledger_path(preferences, mat_id, section), ledger))
    if not copied:
        return 0
    debug.event("versions", "version created", mat_id=str(mat_id),
                n=number)
    return number


def _base_is_archived(preferences, mat_id: str, ledger: dict,
                      section: Section = MATERIAL, base: dict = None) -> bool:
    """Whether the active archive holds the base, byte for byte, except the .png. ▸r/version-store"""
    row = _row_for(ledger, ledger.get("active", 0))
    if row is None:
        return False
    archive = _archive_paths(preferences, mat_id, row.get("n", 0), section)
    base = base or _base_paths(preferences, mat_id, section)
    if RECORD_SUFFIX in dict(section.kinds) and _builder_of(base) != _builder_of(archive):
        return False
    for kind, _required in section.kinds:
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


def keep_base(preferences, mat_id: str, section: Section = MATERIAL,
              base_paths: dict = None, name: str = "") -> bool:
    """Archive the base as a version unless the active one holds it; False when it could not be."""
    ledger = read_ledger(preferences, mat_id, section)
    if ledger.get("unreadable"):
        return False
    base = base_paths or _base_paths(preferences, mat_id, section)
    if _base_is_archived(preferences, mat_id, ledger, section, base):
        return True
    return bool(create_version(preferences, mat_id, name, base, section))


def switch_active(preferences, mat_id: str, number: int, section: Section = MATERIAL,
                  base_paths: dict = None, base_name: str = "") -> bool:
    """Copy version `number` over the base and mark it active; an unarchived base is archived first."""
    from amaze.core import library_db
    library_db.flush(preferences)    # every pending change is saved to the base's record before it is read
    ledger = read_ledger(preferences, mat_id, section)
    if ledger.get("unreadable"):
        return False
    row = _row_for(ledger, number)
    if row is None:
        debug.event("versions", "switch refused - no such version",
                    mat_id=str(mat_id), n=number)
        return False
    base = base_paths or _base_paths(preferences, mat_id, section)
    if not keep_base(preferences, mat_id, section, base, base_name):
        debug.event("versions", "switch refused - the base holds "
                                "unarchived content and could not "
                                "be archived",
                    mat_id=str(mat_id), n=number)
        return False
    ledger = read_ledger(preferences, mat_id, section)    # keep_base may add a row and change `active`
    row = _row_for(ledger, number)
    if row is None:
        return False
    ledger["active"] = int(number)
    if not _restore(preferences, mat_id, int(number), base, section, ledger):
        debug.event("versions", "switch refused - nothing changed", mat_id=str(mat_id),
                    n=int(number))
        return False
    debug.event("versions", "active version switched",
                mat_id=str(mat_id), n=number)
    return True


def _restore(preferences, mat_id: str, number: int, base: dict, section: Section,
             ledger: dict) -> bool:
    """Copy one archive over the base and write the ledger, as one commit; the metadata is kept."""
    archive = _archive_paths(preferences, mat_id, number, section)
    named = (_ledger_path(preferences, mat_id, section), ledger)
    if RECORD_SUFFIX not in dict(section.kinds):
        return _copy_set(preferences, archive, base, section.kinds, ledger=named)
    target = base.get(RECORD_SUFFIX) or asset_record.path_for(
        preferences, mat_id, section.database)
    with asset_record.LOCK:    # no metadata write happens between the read and the copy
        document = {"format": asset_record.FORMAT}
        metadata = asset_record.read(target)[asset_record.METADATA]
        builder = _builder_of(archive)
        if metadata:
            document[asset_record.METADATA] = metadata
        if builder:
            document[asset_record.BUILDER] = builder
        with _staged_record(archive, document, section) as staged:
            return _copy_set(preferences, staged, dict(base, **{RECORD_SUFFIX: target}),
                             section.kinds, ledger=named)


def record_render(preferences, mat_id: str, section: Section = MATERIAL) -> bool:
    """Copy the base thumbnail into the active archive: a version is made before its render exists."""
    return record_base(preferences, mat_id, ".png", section)


def record_base(preferences, mat_id: str, kind: str, section: Section = MATERIAL,
                source: str = "") -> bool:
    """Copy one kind of the base over the ACTIVE version's archive; identical bytes are not rewritten."""
    active = 0
    try:
        ledger = read_ledger(preferences, mat_id, section)
        if ledger.get("unreadable") or not ledger.get("versions"):
            return False
        active = int(ledger.get("active", 0) or 0)
        active_row = _row_for(ledger, active)
        if active_row is None:
            return False
        source = source or _base_paths(preferences, mat_id, section).get(kind)
        if not source or not os.path.exists(source):
            return False
        target = _archive_paths(preferences, mat_id, active, section)[kind]
        if os.path.exists(target) and filecmp.cmp(source, target,
                                                  shallow=False):
            return True
        with open(source, "rb") as handle:
            data = handle.read()
        if not _land(preferences, {target: data}, why="active slot"):
            return False
    except (OSError, hostos.PathEscape) as exc:    # best-effort: it follows a save, never raises
        debug.event("versions", "base not recorded to the active slot",
                    mat_id=str(mat_id), n=active, kind=kind, error=str(exc))
        return False
    debug.event("versions", "base recorded to the active slot",
                mat_id=str(mat_id), n=active, kind=kind)
    return True


def rename_version(preferences, mat_id: str, number: int,
                   name: str, section: Section = MATERIAL) -> bool:
    """Rename one version in the ledger; a name is a label, so no file moves."""
    name = str(name or "").strip()
    if not name:
        return False
    ledger = read_ledger(preferences, mat_id, section)
    if ledger.get("unreadable"):
        return False
    for version in ledger["versions"]:
        if int(version.get("n", 0)) == int(number):
            version["name"] = name
            return _write_ledger(preferences, mat_id, ledger, section)
    return False


def version_file(preferences, mat_id: str, number: int,
                 section: Section = MATERIAL) -> str:
    """Version `number`'s payload file; empty when it has no row or the file is missing."""
    if _row_for(read_ledger(preferences, mat_id, section), number) is None:
        return ""
    path = _archive_paths(preferences, mat_id, number, section)[section.payload()]
    return path if os.path.exists(path) else ""
