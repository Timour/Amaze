"""The version store: mat/versions/<id>/ and its ledger.

THE MODEL, in one paragraph. The base files - mat/<id>.mat, .interface,
.builder.json - are always the ACTIVE version's files: every existing
code path (import, drag, thumbnail, corpus check) reads them and none
of them had to learn anything. Each version, the active one included,
also has an archived copy under mat/versions/<id>/<n>.*, and a ledger
(versions.json) records what exists, what is active, and what each
version is called. Switching versions copies an archive over the base;
creating one archives the base. Nothing is ever edited in place.

WHY the base stays authoritative: practice.md's standing rule - the
index may become a cache only "once a per-asset truth exists to rebuild
it from, and not one moment before". Same shape here: the archive is a
copy of the truth, never the truth. A library whose versions/ folder is
lost entirely still opens, imports and renders every material.

Pre-Versions builds cannot damage it: the strict classifier refuses to
sweep what it cannot positively identify, and a directory does not
match any sweepable shape. Ledger writes go through the same unique-
scratch atomic path as every database.
"""

from __future__ import annotations

import json
import os
import shutil
import time

from amaze.core import debug
from amaze.helpers import hostos

#: The file kinds a version archives - the asset's whole payload.
#: A missing .builder.json or .png is fine (older assets, no capture);
#: a missing .mat is not a version.
_KINDS = ((".mat", True), (".interface", False),
          (".builder.json", False), (".png", False))

#: `asset_files()` kind -> the archive suffix it fills. The store
#: archives exactly the four _KINDS; a kind absent here (cop, stamp,
#: tile icon) is not versioned. library.py keys its pre-edit hold with
#: this: keyed by filename suffix, `<id>_cop.mat` collided with
#: `<id>.mat` and the companion was archived as Version 1's material
#: (found 2026-08-06).
SOURCE_KINDS = {
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
    """The ledger, or an empty one. Unreadable is reported and treated
    as empty for READING - the base files still work, which is the
    whole point of the base staying authoritative - but create/switch
    refuse on an unreadable ledger rather than write blind over it."""
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


def _write_ledger(preferences, mat_id: str, ledger: dict) -> bool:
    path = _ledger_path(preferences, mat_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
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
    """The NAME of the version currently in the base files, or "" when
    the asset has no versions at all.

    List mode shows this in a column where the grid shows a badge: the
    badge could only ever say "there are versions", while a row has
    room to say WHICH one you are looking at. Named versions are the
    point of the feature, so the name is what the column shows -
    falling back to the "Version N" that save_version writes when a
    version was never given one.
    """
    ledger = read_ledger(preferences, mat_id)
    entries = ledger.get("versions", [])
    if not entries:
        return ""
    active = int(ledger.get("active", 0) or 0)
    for entry in entries:
        if int(entry.get("n", 0)) == active:
            return str(entry.get("name") or ("Version %d" % active))
    # Active points at nothing (a hand-edited or half-written ledger):
    # the versions are real, so say so with the newest rather than
    # claiming the asset has none.
    newest = entries[-1]
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


def _archive_paths(preferences, mat_id: str, number: int) -> dict:
    folder = versions_dir(preferences, mat_id)
    return {kind: os.path.join(folder, "%d%s" % (number, kind))
            for kind, _required in _KINDS}


def _copy_set(sources: dict, targets: dict) -> bool:
    """Copy every present kind as ONE unit: all bytes first, then the
    renames.

    WHY BOTH PHASES. This used to copy-and-promote one kind at a time,
    and its docstring only claimed the .mat go/no-go - "a half-copied
    set fails loudly on the .mat before anything else was touched" -
    which says nothing about a failure on the SECOND file, after the
    .mat has already gone over the base. Reproduced on switch_active
    with the .interface held: the base was left holding version 1's
    .mat and version 2's .interface, and the caller's `return False`
    meant the ledger was never updated either, so nothing on disk or in
    the ledger recorded that the material was now a mixture of two
    versions. Importing it then builds one version's network behind
    another's parameter interface.

    There is still no portable multi-file atomic rename, so the promote
    phase ALSO rolls back. Two phases alone were not enough and the
    reproduction says so: the realistic failure is a sync client
    holding one file, `replace_file` retries three times and re-raises
    PermissionError, and by then the earlier kinds have already gone
    over the base. So each destination is moved aside before its
    replacement lands, and a failure part way puts back the ones that
    already moved. That undo is renames of files this function itself
    just created, in the same directory - the one operation most likely
    to succeed at the moment another one did not.

    What remains uncovered is a crash between two renames. The base is
    then mixed with nothing to run the undo; that is the residual, and
    it is orders of magnitude narrower than a held file, which happens.
    """
    staged = []
    displaced = []
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
            except OSError as exc:
                # Nothing has been promoted yet, whichever kind this
                # is. The old line here read
                # `return kind != ".mat" and False if required else
                # False`, which evaluates to False in every branch -
                # whatever it meant to express, it was a tautology.
                debug.event("versions", "copy failed - nothing promoted",
                            source=source, target=target, error=str(exc))
                return False
            staged.append((scratch, target))

        for scratch, target in staged:
            # Move the destination aside FIRST, so this kind can be put
            # back if a later one cannot be written.
            if os.path.exists(target):
                aside = hostos.unique_scratch(target, ".rollback",
                                              create=False)
                hostos.replace_file(target, aside)
                displaced.append((aside, target))
            hostos.promote_scratch(scratch, target)
            promoted += 1
        staged = []
    except OSError as exc:
        debug.event("versions", "promote failed - putting the base back",
                    promoted=promoted, of=len(staged), error=str(exc))
        staged = staged[promoted:]
        for aside, target in reversed(displaced):
            try:
                hostos.replace_file(aside, target)
            except OSError as undo_exc:
                # Nothing more can be done here, and it must not be
                # silent: this is the only shape that still leaves the
                # base mixed.
                debug.event("versions", "ROLLBACK FAILED - the base is "
                            "mixed", target=target, error=str(undo_exc))
        displaced = []
        return False
    finally:
        # Whatever never made it into place, on any exit.
        for scratch, _target in staged:
            hostos.discard_scratch(scratch)
        # On the success path these are the old versions of the files,
        # already replaced - drop them.
        for aside, _target in displaced:
            hostos.discard_scratch(aside)
    return True


def create_version(preferences, mat_id: str, name: str = "",
                   source_paths: dict = None) -> int:
    """Archive the CURRENT base files as a new version and mark it
    active. Returns the new version number, 0 on refusal.

    First call on an asset archives the base TWICE conceptually: the
    pre-existing state becomes Version 1, so the state the user is
    versioning away from is kept - opinion-based versioning starts by
    not losing the opinion you had.

    The caller saves the base files BEFORE calling this (automatic-on-
    save integration): so "create" here always means "the base now
    holds the new state; archive it".
    """
    ledger = read_ledger(preferences, mat_id)
    if ledger.get("unreadable"):
        debug.event("versions", "create refused - ledger unreadable",
                    mat_id=str(mat_id))
        return 0
    number = max([int(v.get("n", 0)) for v in ledger["versions"]] or [0]) + 1
    sources = source_paths or _base_paths(preferences, mat_id)
    if not _copy_set(sources, _archive_paths(preferences, mat_id, number)):
        return 0
    author = ""
    try:
        author = preferences.version_author
    except AttributeError:
        pass
    ledger["versions"].append({
        "n": number,
        "name": name or ("Version %d" % number),
        "author": author,
        "date": time.strftime("%Y-%m-%d %H:%M"),
    })
    ledger["active"] = number
    if not _write_ledger(preferences, mat_id, ledger):
        return 0
    debug.event("versions", "version created", mat_id=str(mat_id),
                n=number)
    return number


def switch_active(preferences, mat_id: str, number: int) -> bool:
    """Copy version `number`'s archive over the base files and mark it
    active. The base is archived first if it is not itself a version
    yet (it always should be, but a truth must not be overwritten on an
    assumption)."""
    ledger = read_ledger(preferences, mat_id)
    if ledger.get("unreadable"):
        return False
    known = {int(v.get("n", 0)) for v in ledger["versions"]}
    if int(number) not in known:
        debug.event("versions", "switch refused - no such version",
                    mat_id=str(mat_id), n=number)
        return False
    if not _copy_set(_archive_paths(preferences, mat_id, int(number)),
                     _base_paths(preferences, mat_id)):
        return False
    ledger["active"] = int(number)
    if not _write_ledger(preferences, mat_id, ledger):
        return False
    debug.event("versions", "active version switched",
                mat_id=str(mat_id), n=number)
    return True


def rename_version(preferences, mat_id: str, number: int,
                   name: str) -> bool:
    """Rename one version in the ledger. Names are labels, nothing on
    disk moves - the files are numbered, deliberately, so a rename can
    never be a file operation that fails halfway."""
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
