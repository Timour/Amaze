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

import filecmp
import json
import os
import random
import re
import shutil
import time

from amaze.core import debug
from amaze.helpers import hostos

#: The placeholder pool for a blank author: colour names, minted once
#: per machine and saved to prefs, so two machines with untouched
#: settings still sign different filenames. Deliberately NEVER the OS
#: user or the machine name (practice.md - legal/identity terms), and
#: colour words because this app already speaks colour.
PLACEHOLDER_NAMES = (
    "Amber", "Aqua", "Auburn", "Azure", "Beige", "Blush", "Bronze",
    "Burgundy", "Carmine", "Celadon", "Cerise", "Cerulean", "Charcoal",
    "Chartreuse", "Cinnabar", "Cobalt", "Copper", "Coral", "Cream",
    "Crimson", "Cyan", "Ebony", "Emerald", "Fawn", "Fuchsia", "Gold",
    "Heliotrope", "Indigo", "Ivory", "Jade", "Lavender", "Lilac",
    "Magenta", "Mahogany", "Maroon", "Mauve", "Mint", "Moss", "Ochre",
    "Olive", "Onyx", "Orchid", "Pearl", "Periwinkle", "Pewter", "Plum",
    "Rose", "Ruby", "Russet", "Rust", "Saffron", "Sage", "Salmon",
    "Sapphire", "Scarlet", "Sepia", "Sienna", "Silver", "Slate",
    "Tangerine", "Taupe", "Teal", "Terracotta", "Turquoise", "Ultramarine",
    "Umber", "Vermilion", "Violet", "Viridian", "Wisteria",
)

#: A stem is `<writer>-<n>`, or bare `<n>` from libraries written
#: before writers signed their files. The trailing number IS the
#: version number either way.
_STEM_NUMBER = re.compile(r"(?:^|-)(\d+)$")

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
    """Adopt version files the ledger does not know.

    The ledger is one JSON file, so a sync between two machines is
    last-write-wins: the row a losing machine wrote vanishes while its
    ARCHIVE FILES arrive intact - a stem already on disk is stepped
    past at write time, so once the other machine's files have landed
    the two cannot take the same name.

    THE NARROWER CLAIM IS THE HONEST ONE. This used to say
    writer-stemmed names cannot collide, which is false whenever both
    machines belong to ONE artist: the writer is the artist's own
    `version_author`, and the placeholder that makes two machines
    differ is minted only when that preference is blank. Two machines
    writing while both are offline still land on one name, because
    nothing shared can allocate it.
    Reading the directory back into the ledger makes the files the
    truth - the same rule the whole store is built on - so a version
    can be lost to sync only if its files are, and losing the ledger
    entirely now costs only names and dates, not the versions.
    Best-effort persist; adopting again next read costs nothing."""
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
        # The snapshot tier every other store has - guarded on
        # existence so the session's once-per-file slot is not spent
        # on the ledger's own birth, when there is nothing to copy.
        if os.path.exists(path):
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


def writer_tag(preferences) -> str:
    """The signature version FILES carry: the author preference, or a
    colour-name placeholder minted ONCE and saved back to prefs when
    the author is blank. Two machines can then never mint the same
    filename even with untouched settings. Never the OS user, never
    the machine name."""
    try:
        author = str(preferences.version_author or "").strip()
    except AttributeError:
        return ""
    if not author:
        author = random.choice(PLACEHOLDER_NAMES)
        try:
            preferences.version_author = author
            preferences.save()
        except (AttributeError, OSError):
            # A prefs that cannot hold it signs nothing this call;
            # the next call mints again.
            return ""
        debug.event("versions", "placeholder author minted",
                    author=author)
    return "".join(ch for ch in author if ch.isalnum())[:24]


def _stem(tag: str, number: int) -> str:
    return "%s-%d" % (tag, int(number)) if tag else "%d" % int(number)


def _row_stem(row: dict) -> str:
    """The stem a ledger row's files use - recorded at write time, or
    the bare number for rows from before writers signed files."""
    return str(row.get("file") or int(row.get("n", 0)))


def _row_for(ledger: dict, number: int) -> dict | None:
    for row in ledger.get("versions", []):
        if int(row.get("n", 0)) == int(number):
            return row
    return None


def _archive_paths(preferences, mat_id: str, stem) -> dict:
    """The archive file set for one stem (`<writer>-<n>` or a bare
    legacy `<n>` - accepted forever)."""
    folder = versions_dir(preferences, mat_id)
    return {kind: os.path.join(folder, "%s%s" % (stem, kind))
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
    # The stem carries the WRITER, and the row records the stem it
    # wrote so readers never re-derive it.
    #
    # THE NUMBER IS ALLOCATED AGAINST THE FOLDER, NOT ONLY THE LEDGER.
    # The writer is the artist's own `version_author`, so two machines
    # belonging to ONE artist carry the SAME tag - the placeholder that
    # makes two machines differ is minted only when the author is blank.
    # The ledger is last-write-wins across a sync, so a machine whose
    # row lost still computes the same next number, and with the same
    # tag that is the same filename: one version's payload silently
    # replaced by another's, which `_adopt_strays` cannot recover
    # because the stem reads as already known.
    #
    # Stepping past a stem that is ALREADY ON DISK closes every case
    # where the other machine's files have arrived, which is all of
    # them once a sync completes. Two machines writing while both
    # offline still land on one name; that is a property of having no
    # shared allocator, and it is why the invariant in `_adopt_strays`
    # is stated as the narrower thing it can honestly claim.
    tag = writer_tag(preferences)
    stem = _stem(tag, number)
    while any(os.path.exists(path) for path
              in _archive_paths(preferences, mat_id, stem).values()):
        debug.event("versions", "version stem already on disk - taking "
                                "the next number", mat_id=str(mat_id),
                    stem=stem)
        number += 1
        stem = _stem(tag, number)
    if not _copy_set(sources,
                     _archive_paths(preferences, mat_id, stem)):
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
        "file": stem,
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
    row = _row_for(ledger, number)
    if row is None:
        debug.event("versions", "switch refused - no such version",
                    mat_id=str(mat_id), n=number)
        return False
    previous = ledger.get("active")
    if not _copy_set(
            _archive_paths(preferences, mat_id, _row_stem(row)),
            _base_paths(preferences, mat_id)):
        return False
    ledger["active"] = int(number)
    if not _write_ledger(preferences, mat_id, ledger):
        # The base already holds version `number` while the ledger on
        # disk still names the previous one - the exact base/ledger
        # disagreement _copy_set's two-phase design prevents one layer
        # down. The previous active's archive is still complete, so the
        # rollback is one more promote.
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
        return False
    debug.event("versions", "active version switched",
                mat_id=str(mat_id), n=number)
    return True


def record_render(preferences, mat_id: str) -> bool:
    """Copy the base thumbnail into the ACTIVE version's archive slot.

    The archive is each version's DURABLE thumbnail - it lives until
    the version goes - but a version is minted at save time, BEFORE
    that save's render lands, so a fresh slot starts holding the
    previous version's picture. Running this wherever a row's PNG is
    declared fresh keeps the active slot true to what was last
    rendered while its version was active. Identical bytes are left
    untouched, so the call after a switch costs no write and no sync
    churn.
    """
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
    except (OSError, hostos.PathEscape) as exc:
        # Best-effort by design: this FOLLOWS a thumbnail refresh, so
        # a library whose paths refuse to compose gets an event and a
        # False, never an exception up through the refresh.
        debug.event("versions", "render not recorded to the active slot",
                    mat_id=str(mat_id), n=active, error=str(exc))
        return False
    debug.event("versions", "render recorded to the active slot",
                mat_id=str(mat_id), n=active)
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
