"""The version store, mat/versions/<id>/ and its ledger: the BASE files are always the ACTIVE version's files (the archive is a copy of the truth, never the truth), switching copies an archive over the base, creating archives the base, and nothing is edited in place. ▸r/version-store"""

from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import time

from amaze import messages
from amaze.core import debug, users
from amaze.helpers import hostos

_STEM_NUMBER = re.compile(r"(?:^|-)(\d+)$")    # a stem is `<writer>-<n>`, or bare `<n>` whenever `writer_tag` answers empty (no user picked, unreadable prefs, a name with nothing alphanumeric left) - the trailing number IS the version number either way

_KINDS = ((".mat", True), (".interface", False),    # the kinds a version archives - a missing .builder.json or .png is fine (older assets, no capture), a missing .mat is not a version
          (".builder.json", False), (".png", False))

SOURCE_KINDS = {    # `asset_files()` kind -> the archive suffix it fills; a kind absent here (cop, stamp, tile icon) is not versioned, and library.py keys its pre-edit hold on this by filename suffix - `<id>_cop.mat` once collided with `<id>.mat` and archived the companion as Version 1's material
    "mat": ".mat",
    "interface": ".interface",
    "builder": ".builder.json",
    "thumbnail": ".png",
}

LEDGER = "versions.json"


def versions_dir(preferences, mat_id: str) -> str:
    """mat/versions/<id>/ - contained, like every id-derived path."""
    return hostos.contained_join(
        preferences.dir, preferences.asset_dir, "versions", str(mat_id))


def _ledger_path(preferences, mat_id: str) -> str:
    return os.path.join(versions_dir(preferences, mat_id), LEDGER)


def read_ledger(preferences, mat_id: str) -> dict:
    """The ledger, or an empty one - unreadable is treated as empty for READING (the base files still work), but create/switch refuse on it rather than write blind over it."""
    path = _ledger_path(preferences, mat_id)
    if not os.path.exists(path):
        data = {"active": 0, "versions": []}
        _adopt_strays(preferences, mat_id, data)
        return data
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or \
                not isinstance(data.get("versions"), list):
            raise ValueError("not a ledger")
        _adopt_strays(preferences, mat_id, data)
        return data
    except (OSError, ValueError) as exc:
        debug.event("versions", "ledger unreadable - versions hidden "
                    "this session", mat_id=str(mat_id), error=str(exc))
        return {"active": 0, "versions": [], "unreadable": True}


def _adopt_strays(preferences, mat_id: str, ledger: dict) -> None:
    """Adopt version files the ledger does not know: the ledger is last-write-wins across a sync, so a losing machine's row vanishes while its archive files arrive intact - reading the directory back makes the files the truth, so a version is lost to sync only if its files are. Best-effort persist; adopting again next read costs nothing. ▸r/version-store"""
    try:
        names = os.listdir(versions_dir(preferences, mat_id))
    except OSError:
        return
    rows = ledger.get("versions", [])
    known = {_row_stem(row) for row in rows}
    taken = {int(row.get("n", 0)) for row in rows}
    adopted = 0
    for filename in sorted(names):
        if not filename.endswith(".mat"):
            continue
        stem = filename[:-len(".mat")]
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
    _write_ledger(preferences, mat_id, ledger)


def _write_ledger(preferences, mat_id: str, ledger: dict) -> bool:
    path = _ledger_path(preferences, mat_id)
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


def version_count(preferences, mat_id: str) -> int:
    """How many versions exist. The badge draws at > 1."""
    return len(read_ledger(preferences, mat_id).get("versions", []))


def list_versions(preferences, mat_id: str) -> list:
    """[{n, name, author, date}] oldest first, plus which is active."""
    ledger = read_ledger(preferences, mat_id)
    return list(ledger.get("versions", []))


def active_version(preferences, mat_id: str) -> int:
    return int(read_ledger(preferences, mat_id).get("active", 0) or 0)


def active_version_name(preferences, mat_id: str) -> str:
    """The NAME of the version currently in the base files ("" when the asset has none) - list mode's column shows WHICH version where the grid's badge can only say versions exist, falling back to the `Version N` save_version writes."""
    ledger = read_ledger(preferences, mat_id)
    entries = ledger.get("versions", [])
    if not entries:
        return ""
    active = int(ledger.get("active", 0) or 0)
    for entry in entries:
        if int(entry.get("n", 0)) == active:
            return str(entry.get("name") or ("Version %d" % active))
    newest = entries[-1]    # active points at nothing (a hand-edited or half-written ledger): the versions are real, so answer with the newest rather than claiming the asset has none
    return str(newest.get("name") or ("Version %d" % int(newest.get("n", 0))))


def _base_paths(preferences, mat_id: str) -> dict:
    assets = os.path.join(preferences.dir, preferences.asset_dir)
    images = os.path.join(preferences.dir, preferences.img_dir)
    mat_id = str(mat_id)
    return {
        ".mat": os.path.join(assets, mat_id + ".mat"),
        ".interface": os.path.join(assets, mat_id + ".interface"),
        ".builder.json": os.path.join(assets, mat_id + ".builder.json"),
        ".png": os.path.join(images, mat_id + ".png"),
    }


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


def _archive_paths(preferences, mat_id: str, stem) -> dict:
    """The archive file set for one stem (`<writer>-<n>` or a bare `<n>`, which an unsigned write still produces)."""
    folder = versions_dir(preferences, mat_id)
    return {kind: os.path.join(folder, "%s%s" % (stem, kind))
            for kind, _required in _KINDS}


def _copy_set(sources: dict, targets: dict) -> bool:
    """Copy every present kind as ONE unit - all bytes first, then the renames, each destination moved aside first so a failure part way puts back the ones already moved; the residual is only a crash between two renames. practice.md ▸ THE LIST IS WRITTEN FIRST holds the held-file reproduction."""
    staged = []
    displaced = []
    created = []
    promoted = 0
    try:
        for kind, required in _KINDS:
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
                   source_paths: dict = None) -> int:
    """Archive the CURRENT base files as a new version and mark it active - the caller saves the base BEFORE calling, so create always means the base now holds the new state. Returns the new number, 0 on refusal."""
    ledger = read_ledger(preferences, mat_id)
    if ledger.get("unreadable"):
        debug.event("versions", "create refused - ledger unreadable",
                    mat_id=str(mat_id))
        return 0
    number = max([int(v.get("n", 0)) for v in ledger["versions"]] or [0]) + 1
    sources = source_paths or _base_paths(preferences, mat_id)
    tag = writer_tag(preferences)    # the stem carries the WRITER and the row records the stem it wrote, so readers never re-derive it
    stem = _stem(tag, number)
    while any(os.path.exists(path) for path    # THE NUMBER IS ALLOCATED AGAINST THE FOLDER, NOT ONLY THE LEDGER: two machines of one artist share the tag, the ledger is last-write-wins across a sync, and stepping past a stem already on disk is what stops one version's payload silently replacing another's ▸r/version-store
              in _archive_paths(preferences, mat_id, stem).values()):
        debug.event("versions", "version stem already on disk - taking "
                                "the next number", mat_id=str(mat_id),
                    stem=stem)
        number += 1
        stem = _stem(tag, number)
    if not _copy_set(sources,
                     _archive_paths(preferences, mat_id, stem)):
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
    if not _write_ledger(preferences, mat_id, ledger):
        return 0
    debug.event("versions", "version created", mat_id=str(mat_id),
                n=number)
    return number


def _base_is_archived(preferences, mat_id: str, ledger: dict) -> bool:
    """Whether the ACTIVE version's archive holds the base's content - byte-compared, .png excluded (record_render refreshes archive thumbnails on its own clock). A structural update rewrites the base without minting, and this is how a switch tells."""
    row = _row_for(ledger, ledger.get("active", 0))
    if row is None:
        return False
    archive = _archive_paths(preferences, mat_id, _row_stem(row))
    base = _base_paths(preferences, mat_id)
    for kind in (".mat", ".interface", ".builder.json"):
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


def switch_active(preferences, mat_id: str, number: int) -> bool:
    """Copy version `number`'s archive over the base files and mark it active - the base is archived first if it is not itself a version yet, because a truth must not be overwritten on an assumption."""
    ledger = read_ledger(preferences, mat_id)
    if ledger.get("unreadable"):
        return False
    row = _row_for(ledger, number)
    if row is None:
        debug.event("versions", "switch refused - no such version",
                    mat_id=str(mat_id), n=number)
        return False
    if not _base_is_archived(preferences, mat_id, ledger):
        if not create_version(preferences, mat_id):
            debug.event("versions", "switch refused - the base holds "
                                    "unarchived content and could not "
                                    "be archived",
                        mat_id=str(mat_id), n=number)
            return False
        ledger = read_ledger(preferences, mat_id)    # minting appended a row and moved `active`
        row = _row_for(ledger, number)
        if row is None:
            return False
    previous = ledger.get("active")
    if not _copy_set(
            _archive_paths(preferences, mat_id, _row_stem(row)),
            _base_paths(preferences, mat_id)):
        return False
    ledger["active"] = int(number)
    if not _write_ledger(preferences, mat_id, ledger):    # the base already holds `number` while the disk ledger names the previous - the previous archive is still complete, so the rollback is one more promote
        previous_row = (_row_for(ledger, previous)
                        if previous is not None else None)
        rolled_back = (
            previous_row is not None
            and _copy_set(
                _archive_paths(preferences, mat_id,
                               _row_stem(previous_row)),
                _base_paths(preferences, mat_id)))
        debug.event("versions",
                    "switch refused - ledger write failed",
                    mat_id=str(mat_id), n=int(number),
                    rolled_back=bool(rolled_back))
        if not rolled_back:  # disk and list now DISAGREE and the next save builds on the wrong base - the you-think-you-saved case, which interrupts ▸p/dialogs-are-a-bill
            debug.alert(messages.VERSION_SWITCH_DIVERGED % int(number),
                        key="versions-diverged-%s" % mat_id)
        return False
    debug.event("versions", "active version switched",
                mat_id=str(mat_id), n=number)
    return True


def record_render(preferences, mat_id: str) -> bool:
    """Copy the base thumbnail into the ACTIVE version's archive slot - a version is minted BEFORE its save's render lands, so the fresh slot starts holding the previous picture; run wherever a row's PNG is declared fresh, and identical bytes cost no write."""
    active = 0
    try:
        ledger = read_ledger(preferences, mat_id)
        if ledger.get("unreadable") or not ledger.get("versions"):
            return False
        active = int(ledger.get("active", 0) or 0)
        active_row = _row_for(ledger, active)
        if active_row is None:
            return False
        source = _base_paths(preferences, mat_id)[".png"]
        if not os.path.exists(source):
            return False
        target = _archive_paths(preferences, mat_id,
                                _row_stem(active_row))[".png"]
        if os.path.exists(target) and filecmp.cmp(source, target,
                                                  shallow=False):
            return True
        os.makedirs(os.path.dirname(target), exist_ok=True)
        scratch = hostos.unique_scratch(target)
        shutil.copyfile(source, scratch)
        hostos.promote_scratch(scratch, target)
    except (OSError, hostos.PathEscape) as exc:    # best-effort by design: this FOLLOWS a thumbnail refresh, and gets an event and a False, never an exception up through it
        debug.event("versions", "render not recorded to the active slot",
                    mat_id=str(mat_id), n=active, error=str(exc))
        return False
    debug.event("versions", "render recorded to the active slot",
                mat_id=str(mat_id), n=active)
    return True


def rename_version(preferences, mat_id: str, number: int,
                   name: str) -> bool:
    """Rename one version in the ledger - names are labels, nothing on disk moves, so a rename can never be a file operation that fails halfway."""
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
