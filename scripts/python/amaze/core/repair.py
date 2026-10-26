"""Repair: never deletes, only reports and moves. ▸p/db-restore"""

import json
import os

from amaze import branding
from amaze.core import database, debug, keyed_store, material, renderers
from amaze.core.material import BUILDER_SUFFIX, STAMP_SUFFIX
from amaze.helpers import hostos, restore as restore_lib, wording
from amaze.prefs import prefs as prefs_module


DATABASES = database.DATABASES

ASSET_SIDECARS = (".mat", ".interface", BUILDER_SUFFIX, STAMP_SUFFIX)

_MISSING = ("absent", "absent-but-known")

_IN_TROUBLE = ("unreadable", "absent-but-known", "no-library")    # an empty list only with a copy

_SETTINGS = keyed_store.SETTINGS    # machine-local, beside its own saved copies in the settings folder


def side_tables() -> tuple:
    """The keyed side tables, from the one registry that declares them."""
    from amaze.core import keyed_store
    return keyed_store.filenames()

RECOVERED_CATEGORY = "Recovered"


def configured_library(preferences=None) -> str:
    """The folder the settings name, reachable or not: unconfigured is empty."""
    if preferences is None:
        preferences = prefs_module.Prefs()
        preferences.load()
    return str(getattr(preferences, "dir", "") or "")


def survey(directory: str, asset_dir: str = "mat/",
           img_dir: str = "img/") -> dict:
    """Read-only, gathered once; while `complete` is False nothing is unclaimed."""
    lists = []
    ids = set()
    complete = True
    for filename in DATABASES + side_tables():
        entry = _survey_one(directory, filename)
        lists.append(entry)
        ids |= entry["ids"]
        if entry["state"] in ("unreadable", "absent-but-known"):
            complete = False
    unaccounted = {}
    unreadable_folders = []
    for folder, extensions, tail in (
            (asset_dir, ASSET_SIDECARS, "_cop"),
            (img_dir, (".png",), "_icon")):
        names = unlisted_in(directory, folder, extensions, tail, ids)
        if names is None:
            unreadable_folders.append(folder)
            unaccounted[folder] = []
            complete = False
        else:
            unaccounted[folder] = names
    return {
        "directory": directory,
        "asset_dir": asset_dir,
        "img_dir": img_dir,
        "lists": lists,
        "ids": ids,
        "complete": complete,
        "unreadable_folders": unreadable_folders,
        "unaccounted": unaccounted,
    }


def _survey_one(directory: str, filename: str) -> dict:
    """One list: its state, what it holds, and what copies sit beside it."""
    path = os.path.join(directory, filename)
    facts, document = restore_lib.surveyed(path)    # ONE parse for both - the state below reads `facts`, the ids read `document`
    entry = {
        "filename": filename,
        "label": database.section_label(filename),
        "path": path,
        "info": facts,
        "ids": set(),
        "trace": "",
        "snapshots": [(tier, restore_lib.info(snap))
                      for tier, snap in restore_lib.snapshots(path)],
    }
    if not facts["exists"]:
        entry["trace"] = database.absent_but_known(directory, filename)
        entry["state"] = "absent-but-known" if entry["trace"] else "absent"
        return entry
    if facts["error"]:
        entry["state"] = "unreadable"
        return entry
    from amaze.core import keyed_store
    spec = keyed_store.store_for(filename)
    if spec is not None:
        malformed = database.wrong_table_shape(document, spec.payload)
        if not malformed and spec.payload not in (document or {}):
            malformed = ("it holds no %r, so it is not the %s file"
                         % (spec.payload, spec.label))
    else:
        malformed = database.wrong_shape(document)
    if malformed or facts["count"] is None:
        entry["state"] = "unreadable"
        entry["info"] = dict(
            facts,
            error=malformed or "it is not shaped like a list Amaze wrote")
        return entry
    for row in (document.get("assets") or []):
        if isinstance(row, dict):
            entry["ids"].add(database.row_id(row))
    entry["state"] = "empty" if not facts["count"] else "ok"
    return entry


def unlisted_in(directory: str, folder: str, extensions: tuple, tail: str,
                known_ids: set):
    """Files no list accounts for, or None when the folder could not be read."""
    full = os.path.join(directory, folder)
    try:
        names = sorted(os.listdir(full))
    except OSError as exc:
        debug.event("repair", "folder could not be listed", path=full,
                    error=str(exc))
        return None
    found = []
    for name in names:
        asset_id = database.asset_id_for_file(name, extensions, tail)
        if asset_id is not None and str(asset_id) not in known_ids:
            found.append(name)
    return found


def read_stamp(path: str) -> dict | None:
    """One recovery stamp, or None: the only opener of a stamp in the package."""
    try:
        with open(path, encoding="utf-8-sig") as handle:
            record = json.load(handle)
        if not isinstance(record, dict):
            raise ValueError("top level is not an object")
    except (OSError, ValueError) as exc:
        debug.event("repair", "recovery stamp unreadable",
                    file=path, error=str(exc))
        return None
    return record


def stamped_assets(directory: str, asset_dir: str = "mat/",
                   names: list | None = None) -> dict:
    """The assets whose stamp reads, as {id: record}; `names` reuses a listing."""
    folder = os.path.join(directory, asset_dir)
    if names is None:
        try:
            names = os.listdir(folder)
        except OSError as exc:
            debug.event("repair", "cannot list the asset folder for stamps",
                        folder=folder, error=str(exc))
            return {}
    found = {}
    for name in names:
        if not name.endswith(STAMP_SUFFIX):
            continue
        record = read_stamp(os.path.join(folder, name))
        if record is not None:
            found[name[: -len(STAMP_SUFFIX)]] = record
    return found


def rebuild_from_stamps(directory: str, asset_dir: str = "mat/",
                        index_filename: str = "library.json") -> dict:
    """One index rebuilt from the stamps `index_filename` claims; `damaged` names the stamps that would not read, `unreadable` the sibling lists that would not parse - a caller with a non-empty `unreadable` may not write the result. ▸p/clean-library-sweep"""
    folder = os.path.join(directory, asset_dir)
    assets, damaged = [], []
    categories = []
    try:
        names = sorted(os.listdir(folder))
    except OSError as exc:
        debug.event("repair", "cannot read the asset folder for a rebuild",
                    folder=folder, error=str(exc))
        return {"assets": [], "categories": [], "damaged": [],
                "unreadable": []}

    owned_elsewhere = set()
    by_file, unreadable = database.ids_claimed_by(directory)
    unreadable = [name for name in unreadable if name != index_filename]  # the index being rebuilt is unreadable BY PREMISE; a sibling is not
    for filename, ids in by_file.items():
        if filename != index_filename:
            owned_elsewhere |= ids
    if unreadable:
        debug.event("repair", "a sibling database could not be read "
                               "while rebuilding", files=unreadable)

    for name in names:
        if not name.endswith(STAMP_SUFFIX):
            continue
        asset_id = name[: -len(STAMP_SUFFIX)]
        if asset_id in owned_elsewhere:
            continue
        record = read_stamp(os.path.join(folder, name))
        if record is None:
            damaged.append(asset_id)
            continue
        record.setdefault("id", asset_id)
        assets.append(record)
        for cat in record.get("categories") or []:
            if cat and cat not in categories:
                categories.append(cat)

    debug.event("repair", "rebuilt an index from recovery stamps",
                folder=folder, assets=len(assets), damaged=len(damaged))
    return {
        "assets": assets,
        "categories": sorted(categories),
        "damaged": damaged,
        "unreadable": sorted(unreadable),
    }


def repair_index(directory: str, asset_dir: str = "mat/") -> tuple:
    """Newest snapshot that parses, else a rebuild from stamps; (ok, how)."""
    target = os.path.join(directory, "library.json")
    for tier in restore_lib.TIERS:
        source = "%s.%s" % (target, tier)
        try:
            with open(source, "rb") as handle:
                snapshot_bytes = handle.read()
        except OSError:
            continue
        if not hostos.parses_as_json(snapshot_bytes):
            continue
        try:
            outcome = restore_lib.put_back(target, tier)
        except restore_lib.RestoreRefused as refusal:
            debug.event("repair", "snapshot refused for the rebuild",
                        tier=tier, error=str(refusal))
            continue
        debug.event("repair", "index restored from a snapshot",
                    tier=tier, undo=outcome.get("undo", ""))
        newer = _materials_newer_than_the_copy(directory, asset_dir)
        if newer:
            return True, ("the newest saved copy was put back, and the %d %s "
                          "saved after it %s added back"
                          % (newer, database.section_noun("library.json", newer),
                             "was" if newer == 1 else "were"))
        return True, "the newest saved copy was put back"
    document = rebuild_from_stamps(directory, asset_dir)
    if document["unreadable"]:  # a list that will not parse claims NOTHING, so every asset it owns reads as unclaimed and lands here as ours ▸p/clean-library-sweep
        debug.event("repair", "rebuild refused - a sibling list is "
                    "unreadable", files=document["unreadable"])
        return False, ("%s cannot be read, so a rebuild cannot tell its "
                       "assets from this list's"
                       % wording.and_list(document["unreadable"]))
    if not document["assets"]:
        return False, ("no saved copy parses and no recovery stamps "
                       "were found")
    try:
        hostos.preserve_unreadable(target, why="library index")  # the snapshot tier declines a file that will not parse, so this copy is the only one kept ▸p/db-restore
        hostos.snapshot_before_write(target)
        hostos.write_json_atomic(target, {
            "version": database.SCHEMA_VERSION,
            "format": branding.LIBRARY_FORMAT,
            "assets": document["assets"],
            "categories": document["categories"],
        }, indent=4)
    except OSError as exc:
        debug.event("repair", "stamp rebuild could not be written",
                    error=str(exc))
        return False, "the rebuilt list could not be written"
    how = "the list was rebuilt from what each asset remembers"
    if document["damaged"]:
        how += " (%d could not be read)" % len(document["damaged"])
    debug.event("repair", "index rebuilt from stamps",
                assets=len(document["assets"]),
                damaged=len(document["damaged"]))
    return True, how


def _materials_newer_than_the_copy(directory: str, asset_dir: str) -> int:
    """The materials a put-back copy predates, added from their stamps; how many came back."""
    findings = survey(directory, asset_dir)
    ids = [asset_id for asset_id, _record in materials_on_record(findings)]
    if not ids or why_nothing_can_be_added(findings, "library.json"):
        return 0
    try:
        return len(_add_rows(findings, "library.json", ids)["added"])
    except (OSError, ValueError) as exc:    # the copy is back either way; these stay for Repair
        debug.event("repair", "materials newer than the copy not added",
                    error=str(exc))
        return 0


def unaccounted_total(findings: dict) -> int:
    return sum(len(names) for names in findings["unaccounted"].values())


def restorable(findings: dict) -> list:
    """Every copy that could be put back, newest first, in panel order."""
    offers = []
    for entry in findings["lists"] + [findings.get("settings") or {}]:
        for tier, snap in entry.get("snapshots", ()):
            offers.append((entry["filename"], tier, snap, entry["info"]))
    return offers


def offered_copies(findings: dict) -> list:
    """`restorable` less any copy that changes nothing; while a list is in trouble, its copies."""
    entries = {entry["filename"]: entry
               for entry in findings["lists"] + [findings.get("settings") or {}]
               if entry}
    offers, held = [], {}
    for offer in restorable(findings):
        filename, tier, snap, _now = offer
        undo = tier.startswith(restore_lib.UNDO_TIER)    # the done-dialog promises it back
        if snap["error"] or not (undo or snap["count"]):
            continue
        document, error = restore_lib.read_document(snap["path"])
        seen = held.setdefault(filename, [_as_it_is(entries[filename])])
        if error or document in seen:    # a repeat of one above it, or of the list as it is
            continue
        seen.append(document)
        offers.append(offer)
    troubled = {filename for filename, entry in entries.items()
                if entry["state"] in _IN_TROUBLE} | {
                    offer[0] for offer in offers if entries[offer[0]]["state"] != "ok"}
    if complete_pairs(findings):    # unlisted pairs are a Material or Node list's loss
        troubled |= set(database.ASSET_FILE_OWNERS)
    if troubled:
        offers = [offer for offer in offers if offer[0] in troubled
                  or offer[1].startswith(restore_lib.UNDO_TIER)]    # undo copies stay
    by_list = {}
    for offer in offers:
        by_list.setdefault(offer[0], []).append(offer)
    return [offer for group in by_list.values()    # each list's newest saved state first
            for offer in sorted(group, key=lambda one: one[2]["when"], reverse=True)]


def _as_it_is(entry: dict):
    """The list as it reads now; None where there is none to read."""
    if entry["state"] in _MISSING or entry["state"] == "unreadable":
        return None
    document, error = restore_lib.read_document(entry["path"])
    return None if error else document


def _holdings(entry: dict) -> str:
    """The count with the word for what was counted, per section."""
    count = entry["info"]["count"] or 0
    return "%d saved %s" % (
        count, database.section_noun(entry["filename"], count))


def copy_named_by_what_it_holds(filename: str, snap: dict) -> str:
    """A saved copy named by its date and count, never by its storage tier."""
    if filename == _SETTINGS:    # a count of settings tells the reader nothing
        return ("from %s, cannot be read" if snap["error"]
                else "from %s") % snap["when"]
    if snap["error"]:
        return "from %s, cannot be read" % snap["when"]
    count = snap["count"] or 0
    return "from %s, %d saved %s" % (
        snap["when"], count, database.section_noun(filename, count))


def _snapshot_line(entry: dict) -> str:
    if not entry["snapshots"]:
        line = ("%s: there are no saved copies of this list beside it, so "
                "there is nothing to put back." % entry["label"])
        if entry["filename"] in database.ASSET_FILE_OWNERS:
            # Only where it is true: Code and Colors keep their assets inline.
            line += (" Your %s' own files and thumbnails are still in the "
                     "library folder either way."
                     % database.section_noun(entry["filename"], 2))
        return line
    parts = []
    for _tier, snap in entry["snapshots"]:
        part = copy_named_by_what_it_holds(entry["filename"], snap)
        if part not in parts:    # two copies alike read as one
            parts.append(part)
    return "%s: saved copies - %s." % (entry["label"], "; ".join(parts))


def report_lines(findings: dict) -> list:
    """The whole report, in the user's words, never the program's."""
    from amaze.core import keyed_store
    extra = [spec.label.lower() for spec in keyed_store.stores()
             if spec.in_library]
    also = ""
    if extra:
        also = (", and one%s for the %s you add to them"
                % (" each" if len(extra) > 1 else "", wording.and_list(extra)))
    lines = ["Amaze looked at the library in %s. It keeps a separate list "
             "for each of its sections - Materials, Nodes, Code and "
             "Colors%s."
             % (str(findings["directory"]).rstrip("/\\"), also), ""]

    troubled = []
    empty = []
    unchecked = []
    for entry in findings["lists"]:
        label, state = entry["label"], entry["state"]
        if state == "ok":
            lines.append("%s: %s, and the list reads fine."
                         % (label, _holdings(entry)))
        elif state == "empty":
            troubled.append(entry)
            empty.append(label)
            lines.append("%s: the list is there and holds nothing." % label)
        elif state == "unreadable":
            troubled.append(entry)
            unchecked.append(label)
            lines.append(
                "%s: the list is there and Amaze cannot read it. It has "
                "not been changed." % label)
        elif state == "absent-but-known":
            troubled.append(entry)
            unchecked.append(label)
            lines.append(
                "%s: there is no list for it in the library folder, though "
                "Amaze can see there was one here before. If this folder "
                "syncs, it may still be on its way - give it a minute and "
                "run Repair again." % label)
        else:
            lines.append("%s: nothing saved here yet." % label)

    if empty:
        lines.append("")
        lines.append(
            "A list that holds nothing looks the same whether nothing was "
            "ever saved there or it failed to load this time, so Amaze "
            "will not decide on its own which it is.")

    total = unaccounted_total(findings)
    lines.append("")
    if findings["unreadable_folders"]:
        lines.append(
            "Amaze could not look inside the %s, so it cannot say whether "
            "anything in there is listed by no section. Nothing will be "
            "moved while that is true."
            % _and_folders(findings["unreadable_folders"]))
    elif total and findings["complete"]:
        lines.append("No section lists %s. Either they belong to something "
                     "whose list was lost, or nothing needs them any more."
                     % files_by_folder(findings))
        lines.extend(_what_can_be_added_back(findings))
    elif total:
        lines.append(
            "No section lists %s. Amaze could not check the %s list either, "
            "so some of those files may be its. Nothing will be moved "
            "while that is true."
            % (files_by_folder(findings), wording.and_list(unchecked)))
        lines.extend(_what_can_be_added_back(findings))
    else:
        lines.append("Every file in the library's own folders is accounted "
                     "for by a section.")

    if troubled:
        lines.append("")
        for entry in troubled:
            lines.append(_snapshot_line(entry))

    return lines


def files(count: int) -> str:
    """The count and its English plural, never the parenthesised one."""
    return "1 file" if count == 1 else "%d files" % count


def files_on_a_button(count: int) -> str:
    """The same count, capitalised: every button in this tool is Title Case."""
    return files(count).replace("file", "File")


def count_on_a_button(count: int, filename: str) -> str:
    """`3 Materials`, `1 Material`: a section's count, Title Case for a button."""
    noun = database.section_noun(filename, count)
    return "%d %s" % (count, noun[:1].upper() + noun[1:])


def _and_folders(folders: list) -> str:
    return wording.and_list(["%s folder" % _folder_name(folder)
                      for folder in folders])


def files_by_folder(findings: dict) -> str:
    """Folder by folder, never one total: Clean Library weighs one folder."""
    parts = []
    for folder, names in findings["unaccounted"].items():
        if not names:
            continue
        part = "%s in the %s folder" % (files(len(names)),
                                        _folder_name(folder))
        if unaccounted_total(findings) <= 6:
            part += " (%s)" % ", ".join(names)
        parts.append(part)
    return wording.and_list(parts)


def _what_can_be_added_back(findings: dict) -> list:
    """The line that keeps the buttons apart: materials by name, then pairs, then the rest."""
    if why_nothing_can_be_added(findings):
        return []
    on_record = materials_on_record(findings)
    addable = reattachable_files(findings)
    rest = unaccounted_total(findings) - len(addable) - len(
        _files_of(findings, [asset_id for asset_id, _record in on_record]))
    said = [_materials_sentence(on_record)] if on_record else []
    if addable and (rest or on_record):
        said.append("%s can be added back to a section."
                    % (files(len(addable)).replace(" ", " more ", 1) if on_record
                       else "Of those, " + files(len(addable))))
    if rest and said:
        said.append("The rest are halves of an asset whose other file is not "
                    "in the folder, so they can only be moved aside.")
    return [" ".join(said)] if said else []


def _materials_sentence(on_record: list) -> str:
    """The materials Add Back puts on the list, by name while there are few enough to read."""
    count = len(on_record)
    one = count == 1
    names = ""
    if count <= 6:
        names = ": " + wording.and_list([str(record.get("name") or asset_id)
                                          for asset_id, record in on_record])
    return ("The files include %d %s with %s name, category and tags saved "
            "beside %s%s. Add %s Back puts %s on the %s list."
            % (count, database.section_noun("library.json", count),
               "its" if one else "their", "it" if one else "them", names,
               count_on_a_button(count, "library.json"), "it" if one else "them",
               database.section_label("library.json")))


def _folder_name(folder: str) -> str:
    return str(folder).rstrip("/\\") or folder


_SESSION_HOLDS_THE_LIBRARY = (
    "this Houdini has already read the library and would write what it "
    "remembers back over the change - quit Houdini, start it again, and "
    "run Repair before you open Amaze")


def _refuse_a_houdini_that_holds_the_library(refusal=ValueError) -> None:
    """Every action enforces this for itself; the button logic is a courtesy."""
    if session_has_a_library_open():
        raise refusal(_SESSION_HOLDS_THE_LIBRARY)


def movable(findings: dict) -> dict:
    """`findings` less the files of the materials Add Back can put on the list."""
    kept = set(_files_of(findings, [asset_id for asset_id, _record
                                    in materials_on_record(findings)]))
    if not kept:
        return findings
    return dict(findings, unaccounted={
        folder: [name for name in names if name not in kept]
        for folder, names in findings["unaccounted"].items()})


def quarantine(findings: dict) -> dict:
    """Move unclaimed files aside, never a material Add Back names; refuses on any bad list."""
    _refuse_a_houdini_that_holds_the_library()
    if not findings["complete"]:
        raise ValueError("one of the library's lists cannot be read, so "
                         "these files may belong to it")
    findings = movable(findings)
    from amaze.core import quarantine as holding
    root = holding.quarantine_folder(findings["directory"])
    moved, failed = [], []
    for folder, names in findings["unaccounted"].items():
        if not names:
            continue
        for name in names:
            source = os.path.join(findings["directory"], folder, name)
            if holding.quarantine_file(findings["directory"], source):
                moved.append(name)
            else:
                failed.append(name)
    debug.event("repair", "unclaimed files moved aside", folder=root,
                moved=len(moved), failed=len(failed),
                moved_files=moved, failed_files=failed)
    return {"folder": root, "moved": moved, "failed": failed}



def reattach(findings: dict, filename: str, only=None) -> dict:
    """Add the unclaimed pairs, or the ids in `only`, to `filename` from their stamps ▸p/recovery-stamp"""
    _refuse_a_houdini_that_holds_the_library()
    return _add_rows(findings, filename,
                     complete_pairs(findings) if only is None else list(only))


def add_materials_back(findings: dict) -> dict:
    """Put every material `materials_on_record` finds on the Material list; raises as `reattach`."""
    _refuse_a_houdini_that_holds_the_library()
    return _add_rows(findings, "library.json",
                     [asset_id for asset_id, _record in materials_on_record(findings)])


def materials_on_record(findings: dict) -> list:
    """The unlisted pairs whose stamp names a renderer Amaze knows, as `(id, record)`, by id."""
    if "asset_dir" not in findings:
        return []
    folder = os.path.join(findings["directory"], findings["asset_dir"])
    found = []
    for asset_id in complete_pairs(findings):
        path = os.path.join(folder, asset_id + STAMP_SUFFIX)
        record = read_stamp(path) if os.path.exists(path) else None
        if record is not None and renderers.get(record.get("renderer")):    # a node's names a context
            found.append((asset_id, record))
    return found


def why_nothing_can_be_added(findings: dict, filename: str = "") -> str:
    """Empty when unlisted files may go on `filename`, or on any list; else why they may not."""
    if findings.get("unreadable_folders"):
        return ("Amaze could not look inside the %s, so it cannot tell which "
                "files are listed" % _and_folders(findings["unreadable_folders"]))
    for entry in findings.get("lists", ()):
        if entry["state"] == "unreadable":
            return ("that list cannot be read, so nothing was added to it"
                    if entry["filename"] == filename else
                    "one of the library's lists cannot be read, so these "
                    "files may belong to it")
    return ""


def _add_rows(findings: dict, filename: str, ids: list) -> dict:
    """`reattach` without the session guard, for the panel's own repair; writes a missing list new."""
    reason = why_nothing_can_be_added(findings, filename)
    if reason:
        raise ValueError(reason)
    path = os.path.join(findings["directory"], filename)
    missing = _state_of(findings, filename) in _MISSING
    if missing and os.path.exists(path):
        debug.event("repair", "a list arrived after the survey", file=filename)
        raise ValueError("the list has arrived in the library folder since "
                         "Repair looked, so nothing was added to it - run "
                         "Repair again")
    document, error = (({"categories": ["_All"], "tags": [], "assets": []}, "")
                       if missing else restore_lib.read_document(path))
    malformed = error or database.wrong_shape(document)
    if malformed:
        debug.event("repair", "cannot add to a list it cannot read",
                    file=filename, reason=malformed)
        raise ValueError("that list cannot be read, so nothing was added "
                         "to it")

    added, minted, rows = [], [], []
    folder = os.path.join(findings["directory"], findings["asset_dir"])
    for asset_id in ids:
        record = read_stamp(os.path.join(folder, asset_id + STAMP_SUFFIX))
        if record is None:
            record = material.Material(
                name="Recovered %s" % asset_id[:8],
                cats=RECOVERED_CATEGORY,
                tags=[],
                fav=False,
                renderer="",
                mat_id=asset_id,
            ).get_as_dict()
            minted.append(asset_id)
        record["id"] = asset_id
        rows.append(record)
        added.append(asset_id)
    if added:
        document.setdefault("assets", []).extend(rows)
        categories = document.setdefault("categories", ["_All"])
        for row in rows:                # a stamped row brings its own back
            for cat in row.get("categories") or []:
                if cat and cat not in categories:
                    categories.append(cat)
        if minted and RECOVERED_CATEGORY not in categories:
            categories.append(RECOVERED_CATEGORY)
        if missing:
            prefs_module.write_fresh_index(path, document)    # the one door a new list is born by
        else:
            _write_json(path, document)
    debug.event("repair", "unlisted files added back to a list",
                file=filename, added=len(added), from_stamps=len(added) - len(minted),
                written_new=missing)
    return {"added": added, "path": path, "minted": minted}


def _state_of(findings: dict, filename: str) -> str:
    return next((entry["state"] for entry in findings.get("lists", ())
                 if entry["filename"] == filename), "")


def list_is_missing(findings: dict, filename: str) -> bool:
    """Whether adding back to `filename` writes the list new."""
    return _state_of(findings, filename) in _MISSING


def complete_pairs(findings: dict) -> list:
    """The unclaimed ids with both halves present, in a stable order."""
    halves = {}
    for name in findings["unaccounted"].get(findings.get("asset_dir"), []):    # none for settings
        asset_id = database.asset_id_for_file(
            name, (".mat", ".interface"), "_cop")
        if not asset_id:
            continue
        if os.path.splitext(name)[0] != asset_id:
            continue
        halves.setdefault(asset_id, set()).add(
            os.path.splitext(name)[1].lower())
    return sorted(asset_id for asset_id, seen in halves.items()
                  if {".mat", ".interface"} <= seen)


def unsorted_pairs(findings: dict) -> list:
    """The complete pairs `materials_on_record` leaves: only the user can name their section."""
    on_record = {asset_id for asset_id, _record in materials_on_record(findings)}
    return [asset_id for asset_id in complete_pairs(findings)
            if asset_id not in on_record]


def reattachable_files(findings: dict) -> list:
    """Every file adding the unsorted pairs back accounts for, counted like the other button."""
    return _files_of(findings, unsorted_pairs(findings))


def _files_of(findings: dict, ids) -> list:
    """Every unaccounted file the assets in `ids` own, the builder, stamp and thumbnail included."""
    ids = set(ids)
    covered = []
    for folder, names in findings["unaccounted"].items():
        extensions, tail = (ASSET_SIDECARS, "_cop") \
            if folder == findings["asset_dir"] else ((".png",), "_icon")
        for name in names:
            if ids and database.asset_id_for_file(name, extensions, tail) in ids:
                covered.append(name)
    return covered


def _write_json(path: str, document) -> None:
    """Scratch-and-promote without the snapshot: a recovery tool keeps the copies. `scratch_beside` discards on ANY raise - the hand-rolled version discarded only on a write-time OSError, so a raising promote left a `.repairing` file for the orphan scan to misread."""
    with hostos.scratch_beside(path, suffix=".repairing") as scratch:
        with open(scratch, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)


def target_of(findings: dict, filename: str) -> str:
    """The file a saved copy goes back over: settings.json in its own folder, a list in the library."""
    settings = findings.get("settings") or {}
    if filename == settings.get("filename"):
        return settings["path"]
    return os.path.join(findings["directory"], filename)


def put_back(findings: dict, filename: str, tier: str) -> dict:
    """One saved copy back, through the shared restore; raises `RestoreRefused`."""
    _refuse_a_houdini_that_holds_the_library(
        lambda phrase: restore_lib.RestoreRefused(
            "Nothing was put back: %s." % phrase))
    target = target_of(findings, filename)
    done = restore_lib.put_back(target, tier, allow_loss=True)
    debug.event("repair", "saved copy put back", file=filename, tier=tier,
                undo=done["undo"])
    return done


def session_has_a_library_open() -> bool:
    """Whether anything in this session holds a list, a closed panel included."""
    return bool(database.DatabaseConnector._instances)


def settings_survey(preferences=None):
    """settings.json as a list Repair can put back; None when no settings folder is named."""
    folder = (hostos.config_root() if preferences is None
              else str(getattr(preferences, "path", "") or ""))
    if not folder:
        return None
    path = os.path.join(folder, _SETTINGS)
    facts = restore_lib.info(path)
    if not facts["exists"]:
        state = "absent"
    elif facts["error"] or facts["count"] is None:
        state = "unreadable"
    else:
        state = "ok"
    return {"filename": _SETTINGS,
            "label": database.section_label(_SETTINGS),
            "path": path, "info": facts, "ids": set(), "trace": "",
            "state": state,
            "snapshots": [(tier, _with_library(*restore_lib.surveyed(snap)))
                          for tier, snap in restore_lib.snapshots(path)]}


def _with_library(facts: dict, document) -> dict:
    """A settings copy's facts plus `library`, the folder its `directory` key names or empty."""
    named = document.get("directory") if isinstance(document, dict) else ""
    return dict(facts, library=named if isinstance(named, str) else "")


def copies_naming_a_library(settings) -> list:
    """The saved settings copies that read and name a library folder; the rest are no way back."""
    return [(tier, snap) for tier, snap in (settings or {}).get("snapshots", ())
            if not snap["error"] and snap["library"]]
