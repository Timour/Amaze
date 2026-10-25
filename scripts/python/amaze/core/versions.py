"""Every section's version store: a folder per asset and its ledger. ▸r/version-store"""

from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import time

from amaze import messages
from amaze.core import asset_files, debug, users
from amaze.core.material import BUILDER_SUFFIX
from amaze.helpers import hostos

_STEM_NUMBER = re.compile(r"(?:^|-)(\d+)$")    # a stem is `<writer>-<n>`, or bare `<n>` whenever `writer_tag` answers empty (no user picked, unreadable prefs, a name with nothing alphanumeric left) - the trailing number IS the version number either way

_KINDS = ((".mat", True), (".interface", False),    # the kinds a version archives - a missing .builder.json or .png is fine (older assets, no capture), a missing .mat is not a version
          (BUILDER_SUFFIX, False), (".png", False))

SOURCE_KINDS = {    # `asset_files()` kind -> the archive suffix it fills; a kind absent here (cop, stamp, tile icon) is not versioned, and library.py keys its pre-edit hold on this by filename suffix - `<id>_cop.mat` once collided with `<id>.mat` and archived the companion as Version 1's material
    "mat": ".mat",
    "interface": ".interface",
    "builder": BUILDER_SUFFIX,
    "thumbnail": ".png",
}

LEDGER = "versions.json"

CODE_SUFFIX = ".txt"    # a code version is its snippet's text, one file


class Section:
    """Where one section keeps its versions, and the files one version holds."""

    __slots__ = ("folder", "kinds", "source_kinds")

    def __init__(self, folder, kinds: tuple, source_kinds: dict) -> None:
        self.folder = folder                # preferences -> the store's path parts in the library
        self.kinds = kinds                  # ((suffix, required), ...)
        self.source_kinds = source_kinds    # asset_files() kind -> suffix; {}: the caller hands it in

    def payload(self) -> str:
        """The suffix without which a set of files is not a version."""
        return next(suffix for suffix, required in self.kinds if required)


MATERIAL = Section(lambda preferences: (preferences.asset_dir, "versions"), _KINDS, SOURCE_KINDS)
CODE = Section(lambda preferences: ("code", "versions"), ((CODE_SUFFIX, True),), {})    # in code.json


def versions_dir(preferences, mat_id: str, section: Section = MATERIAL) -> str:
    """mat/versions/<id>/ or code/versions/<id>/ - contained, like every id-derived path."""
    return hostos.contained_join(
        preferences.dir, *section.folder(preferences), str(mat_id))


def store_root(preferences, section: Section = MATERIAL) -> str:
    """The folder every store of `section` sits in: one listing tells which assets have one."""
    return os.path.join(preferences.dir, *section.folder(preferences))


def _ledger_path(preferences, mat_id: str, section: Section = MATERIAL) -> str:
    return os.path.join(versions_dir(preferences, mat_id, section), LEDGER)


def read_ledger(preferences, mat_id: str, section: Section = MATERIAL) -> dict:
    """The ledger, or an empty one; an unreadable one reads as empty and create and switch refuse."""
    path = _ledger_path(preferences, mat_id, section)
    if not os.path.exists(path):
        data = {"active": 0, "versions": []}
        _adopt_strays(preferences, mat_id, data, section)
        return data
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or \
                not isinstance(data.get("versions"), list):
            raise ValueError("not a ledger")
        _adopt_strays(preferences, mat_id, data, section)
        return data
    except (OSError, ValueError) as exc:
        debug.event("versions", "ledger unreadable - versions hidden "
                    "this session", mat_id=str(mat_id), error=str(exc))
        return {"active": 0, "versions": [], "unreadable": True}


def _adopt_strays(preferences, mat_id: str, ledger: dict,
                  section: Section = MATERIAL) -> None:
    """Rows for version files the ledger lacks: a sync loses rows, never files. ▸r/version-store"""
    try:
        names = os.listdir(versions_dir(preferences, mat_id, section))
    except OSError:
        return
    rows = ledger.get("versions", [])
    known = {_row_stem(row) for row in rows}
    taken = {int(row.get("n", 0)) for row in rows}
    adopted = 0
    payload = section.payload()
    for filename in sorted(names):
        if not filename.endswith(payload):
            continue
        stem = filename[:-len(payload)]
        if stem in known:
            continue
        match = _STEM_NUMBER.search(stem)
        if not match:
            continue          # not a version file - never guess
        number = int(match.group(1))
        writer = stem[:match.start()].rstrip("-")
        if number in taken:
            number = max(taken | {0}) + 1
        taken.add(number)
        known.add(stem)
        rows.append({
            "n": number,
            "name": "Version %d" % number,
            "author": writer,
            "date": "",
            "file": stem,
        })
        adopted += 1
    if not adopted:
        return
    rows.sort(key=lambda row: int(row.get("n", 0)))
    debug.event("versions", "stray archives adopted into the ledger",
                mat_id=str(mat_id), adopted=adopted)
    _write_ledger(preferences, mat_id, ledger, section)


def _write_ledger(preferences, mat_id: str, ledger: dict,
                  section: Section = MATERIAL) -> bool:
    path = _ledger_path(preferences, mat_id, section)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):    # the snapshot tier every other store has, guarded so the session's once-per-file slot is not spent on the ledger's own birth

            hostos.snapshot_before_write(path)
        hostos.write_json_atomic(path, ledger, indent=1)
        return True
    except OSError as exc:
        debug.event("versions", "ledger not written",
                    mat_id=str(mat_id), error=str(exc))
        return False


def version_count(preferences, mat_id: str, section: Section = MATERIAL) -> int:
    """How many versions exist. The badge draws at > 1."""
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
    """The name of the version in the base, "" for an asset with none; list mode shows it."""
    ledger = read_ledger(preferences, mat_id, section)
    entries = ledger.get("versions", [])
    if not entries:
        return ""
    active = int(ledger.get("active", 0) or 0)
    for entry in entries:
        if int(entry.get("n", 0)) == active:
            return version_label(entry)
    return version_label(entries[-1])    # active points at nothing: answer with the newest


def _base_paths(preferences, mat_id: str, section: Section = MATERIAL) -> dict:
    """The asset's own files by archive suffix; {} where the caller hands the base in."""
    if not section.source_kinds:
        return {}
    owned = asset_files.asset_files_for(preferences, mat_id)
    return {suffix: owned[kind] for kind, suffix in section.source_kinds.items()
            if kind in owned}


def writer_tag(preferences) -> str:
    """The signature version FILES carry - the UID identifies, the NAME signs: the library user's name with only alphanumerics kept, and empty when no library user exists yet (never the OS account, never the machine name), so `_stem` emits the bare `<n>` form rather than inventing a signature."""
    try:
        uid = users.current(preferences)
    except (AttributeError, OSError):
        return ""
    if not uid:
        return ""
    author = users.name_for(preferences, uid)
    return "".join(ch for ch in str(author or "") if ch.isalnum())[:24]


def _stem(tag: str, number: int) -> str:
    return "%s-%d" % (tag, int(number)) if tag else "%d" % int(number)


def _row_stem(row: dict) -> str:
    """The stem a ledger row's files use - recorded at write time, or the bare number for rows whose writer signed nothing."""
    return str(row.get("file") or int(row.get("n", 0)))


def _row_for(ledger: dict, number: int) -> dict | None:
    for row in ledger.get("versions", []):
        if int(row.get("n", 0)) == int(number):
            return row
    return None


def _archive_paths(preferences, mat_id: str, stem,
                   section: Section = MATERIAL) -> dict:
    """The archive file set for one stem, `<writer>-<n>` or a bare `<n>` when unsigned."""
    folder = versions_dir(preferences, mat_id, section)
    return {kind: os.path.join(folder, "%s%s" % (stem, kind))
            for kind, _required in section.kinds}


def _copy_set(sources: dict, targets: dict, kinds: tuple = _KINDS) -> bool:
    """Copy every present kind as ONE unit - all bytes first, then the renames, each destination moved aside first so a failure part way puts back the ones already moved; the residual is only a crash between two renames. practice.md ▸ THE LIST IS WRITTEN FIRST holds the held-file reproduction."""
    staged = []
    displaced = []
    created = []
    promoted = 0
    try:
        for kind, required in kinds:
            source = sources.get(kind)
            present = source and os.path.exists(source)
            if required and not present:
                debug.event("versions", "no %s to copy - refused" % kind,
                            source=source)
                return False
            if not present:
                continue
            target = targets[kind]
            try:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                scratch = hostos.unique_scratch(target)
                shutil.copyfile(source, scratch)
            except OSError as exc:    # nothing has been promoted yet, whichever kind this is
                debug.event("versions", "copy failed - nothing promoted",
                            source=source, target=target, error=str(exc))
                return False
            staged.append((scratch, target))

        for scratch, target in staged:
            if os.path.exists(target):    # the destination moves aside FIRST, so this kind can be put back if a later one cannot be written
                aside = hostos.unique_scratch(target, ".rollback",
                                              create=False)
                hostos.replace_file(target, aside)
                displaced.append((aside, target))
            else:
                created.append(target)    # nothing to put back for this kind - the rollback must REMOVE it instead
            hostos.promote_scratch(scratch, target)
            promoted += 1
        staged = []
    except OSError as exc:
        debug.event("versions", "promote failed - putting the base back",
                    promoted=promoted, of=len(staged), error=str(exc))
        staged = staged[promoted:]
        for target in created:
            try:
                if os.path.exists(target):
                    os.remove(target)
            except OSError as undo_exc:
                debug.event("versions", "ROLLBACK FAILED - a created "
                            "kind stays", target=target,
                            error=str(undo_exc))
        for aside, target in reversed(displaced):
            try:
                hostos.replace_file(aside, target)
            except OSError as undo_exc:    # nothing more can be done, and it must not be silent - the only shape that still leaves the base mixed
                debug.event("versions", "ROLLBACK FAILED - the base is "
                            "mixed", target=target, error=str(undo_exc))
        displaced = []
        return False
    finally:
        for scratch, _target in staged:    # whatever never made it into place, on any exit
            hostos.discard_scratch(scratch)
        for aside, _target in displaced:    # on the success path these are the old files, already replaced
            hostos.discard_scratch(aside)
    return True


def create_version(preferences, mat_id: str, name: str = "",
                   source_paths: dict = None, section: Section = MATERIAL) -> int:
    """Archive the base, saved BEFORE the call, as a new active version; its number, 0 refused."""
    ledger = read_ledger(preferences, mat_id, section)
    if ledger.get("unreadable"):
        debug.event("versions", "create refused - ledger unreadable",
                    mat_id=str(mat_id))
        return 0
    number = max([int(v.get("n", 0)) for v in ledger["versions"]] or [0]) + 1
    sources = source_paths or _base_paths(preferences, mat_id, section)
    tag = writer_tag(preferences)    # the stem carries the WRITER and the row records the stem it wrote, so readers never re-derive it
    stem = _stem(tag, number)
    while any(os.path.exists(path) for path    # THE NUMBER IS ALLOCATED AGAINST THE FOLDER, NOT ONLY THE LEDGER: two machines of one artist share the tag, the ledger is last-write-wins across a sync, and stepping past a stem already on disk is what stops one version's payload silently replacing another's ▸r/version-store
              in _archive_paths(preferences, mat_id, stem, section).values()):
        debug.event("versions", "version stem already on disk - taking "
                                "the next number", mat_id=str(mat_id),
                    stem=stem)
        number += 1
        stem = _stem(tag, number)
    if not _copy_set(sources,
                     _archive_paths(preferences, mat_id, stem, section),
                     section.kinds):
        return 0
    author = ""    # THE NAME, NOT THE UID, FROZEN here rather than resolved at read time: the stem beside it froze the same name, and a row that outlives its user record still says who wrote it
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
        "file": stem,
    })
    ledger["active"] = number
    if not _write_ledger(preferences, mat_id, ledger, section):
        return 0
    debug.event("versions", "version created", mat_id=str(mat_id),
                n=number)
    return number


def _base_is_archived(preferences, mat_id: str, ledger: dict,
                      section: Section = MATERIAL, base: dict = None) -> bool:
    """Whether the active archive holds the base, byte for byte, the .png aside. ▸r/version-store"""
    row = _row_for(ledger, ledger.get("active", 0))
    if row is None:
        return False
    archive = _archive_paths(preferences, mat_id, _row_stem(row), section)
    base = base or _base_paths(preferences, mat_id, section)
    for kind, _required in section.kinds:
        if kind == ".png":    # record_render refreshes it on its own clock
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
    ledger = read_ledger(preferences, mat_id, section)    # keeping may add a row and move `active`
    row = _row_for(ledger, number)
    if row is None:
        return False
    previous = ledger.get("active")
    if not _copy_set(
            _archive_paths(preferences, mat_id, _row_stem(row), section),
            base, section.kinds):
        return False
    ledger["active"] = int(number)
    if not _write_ledger(preferences, mat_id, ledger, section):    # the previous archive is whole
        previous_row = (_row_for(ledger, previous)
                        if previous is not None else None)
        rolled_back = (
            previous_row is not None
            and _copy_set(
                _archive_paths(preferences, mat_id,
                               _row_stem(previous_row), section),
                base, section.kinds))
        debug.event("versions",
                    "switch refused - ledger write failed",
                    mat_id=str(mat_id), n=int(number),
                    rolled_back=bool(rolled_back))
        if not rolled_back:  # the base and the ledger disagree, so it interrupts ▸p/dialogs-are-a-bill
            debug.alert(messages.VERSION_SWITCH_DIVERGED % int(number),
                        key="versions-diverged-%s" % mat_id)
        return False
    debug.event("versions", "active version switched",
                mat_id=str(mat_id), n=number)
    return True


def record_render(preferences, mat_id: str) -> bool:
    """Copy the base thumbnail into the active archive: a version is minted before its render lands."""
    return record_base(preferences, mat_id, ".png")


def record_base(preferences, mat_id: str, kind: str, section: Section = MATERIAL,
                source: str = "") -> bool:
    """Copy one kind of the base over the ACTIVE version's archive; identical bytes cost no write."""
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
        target = _archive_paths(preferences, mat_id,
                                _row_stem(active_row), section)[kind]
        if os.path.exists(target) and filecmp.cmp(source, target,
                                                  shallow=False):
            return True
        os.makedirs(os.path.dirname(target), exist_ok=True)
        scratch = hostos.unique_scratch(target)
        shutil.copyfile(source, scratch)
        hostos.promote_scratch(scratch, target)
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
    """Version `number`'s payload file; "" when it has no row or the file is gone."""
    row = _row_for(read_ledger(preferences, mat_id, section), number)
    if row is None:
        return ""
    path = _archive_paths(preferences, mat_id, _row_stem(row),
                          section)[section.payload()]
    return path if os.path.exists(path) else ""
