"""Repair: never deletes, only reports and moves. ▸p/db-restore"""

import datetime
import json
import os

import hou

from amaze import branding
from amaze.core import database, debug, material
from amaze.core.library import STAMP_SUFFIX
from amaze.helpers import helpers, hostos, restore as restore_lib
from amaze import messages
from amaze.prefs import prefs as prefs_module


DATABASES = database.DATABASES

ASSET_SIDECARS = (".mat", ".interface", ".builder.json", ".stamp.json")


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
        names = _unlisted_in(directory, folder, extensions, tail, ids)
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
    facts = restore_lib.info(path)
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
    document, _ = restore_lib.read_document(path)
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


def _unlisted_in(directory: str, folder: str, extensions: tuple, tail: str,
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
    """One index rebuilt from the stamps `index_filename` claims, damaged named."""
    folder = os.path.join(directory, asset_dir)
    assets, damaged = [], []
    categories, tags = [], []
    try:
        names = sorted(os.listdir(folder))
    except OSError as exc:
        debug.event("repair", "cannot read the asset folder for a rebuild",
                    folder=folder, error=str(exc))
        return {"assets": [], "categories": [], "tags": [], "damaged": []}

    owned_elsewhere = set()
    by_file, unreadable = database.ids_claimed_by(directory)
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
        for tag in record.get("tags") or []:
            if tag and tag not in tags:
                tags.append(tag)

    debug.event("repair", "rebuilt an index from recovery stamps",
                folder=folder, assets=len(assets), damaged=len(damaged))
    return {
        "assets": assets,
        "categories": sorted(categories),
        "tags": sorted(tags),
        "damaged": damaged,
    }


def repair_index(directory: str, asset_dir: str = "mat/") -> tuple:
    """Newest snapshot that parses, else a rebuild from stamps; (ok, how)."""
    target = os.path.join(directory, "library.json")
    for tier in ("bak-1", "bak-2", "bak-3", "bak-first"):
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
        return True, "the newest saved copy was put back"
    document = rebuild_from_stamps(directory, asset_dir)
    if not document["assets"]:
        return False, ("no saved copy parses and no recovery stamps "
                       "were found")
    try:
        hostos.snapshot_before_write(target)
        hostos.write_json_atomic(target, {
            "version": database.SCHEMA_VERSION,
            "format": branding.LIBRARY_FORMAT,
            "assets": document["assets"],
            "categories": document["categories"],
            "tags": document["tags"],
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


def unaccounted_total(findings: dict) -> int:
    return sum(len(names) for names in findings["unaccounted"].values())


def restorable(findings: dict) -> list:
    """Every copy that could be put back, newest first, in panel order."""
    offers = []
    for entry in findings["lists"]:
        for tier, snap in entry["snapshots"]:
            offers.append((entry["filename"], tier, snap, entry["info"]))
    return offers


def _holdings(entry: dict) -> str:
    """The count with the word for what was counted, per section."""
    count = entry["info"]["count"] or 0
    return "%d saved %s" % (
        count, database.section_noun(entry["filename"], count))


def _copy_named_by_what_it_holds(filename: str, snap: dict) -> str:
    """A saved copy named by its date and count, never by its storage tier."""
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
    parts = [_copy_named_by_what_it_holds(entry["filename"], snap)
             for _tier, snap in entry["snapshots"]]
    return "%s: saved copies - %s." % (entry["label"], "; ".join(parts))


def report_lines(findings: dict) -> list:
    """The whole report, in the user's words, never the program's."""
    from amaze.core import keyed_store
    extra = [spec.label.lower() for spec in keyed_store.stores()
             if spec.in_library]
    also = ""
    if extra:
        also = (", and one%s for the %s you add to them"
                % (" each" if len(extra) > 1 else "", helpers.and_list(extra)))
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
                     % _files_by_folder(findings))
        lines.extend(_what_can_be_added_back(findings))
    elif total:
        lines.append(
            "No section lists %s. Amaze could not check the %s list either, "
            "so some of those files may be its. Nothing will be moved "
            "while that is true."
            % (_files_by_folder(findings), helpers.and_list(unchecked)))
    else:
        lines.append("Every file in the library's own folders is accounted "
                     "for by a section.")

    if troubled:
        lines.append("")
        for entry in troubled:
            lines.append(_snapshot_line(entry))

    return lines


def _files(count: int) -> str:
    """The count and its English plural, never the parenthesised one."""
    return "1 file" if count == 1 else "%d files" % count


def _files_on_a_button(count: int) -> str:
    """The same count, capitalised: every button in this tool is Title Case."""
    return _files(count).replace("file", "File")


def _and_folders(folders: list) -> str:
    return helpers.and_list(["%s folder" % _folder_name(folder)
                      for folder in folders])


def _files_by_folder(findings: dict) -> str:
    """Folder by folder, never one total: Clean Library weighs one folder."""
    parts = []
    for folder, names in findings["unaccounted"].items():
        if not names:
            continue
        part = "%s in the %s folder" % (_files(len(names)),
                                        _folder_name(folder))
        if unaccounted_total(findings) <= 6:
            part += " (%s)" % ", ".join(names)
        parts.append(part)
    return helpers.and_list(parts)


def _what_can_be_added_back(findings: dict) -> list:
    """The line that keeps the two buttons apart: pairs against everything."""
    addable = _reattachable_files(findings)
    total = unaccounted_total(findings)
    if not addable or len(addable) == total:
        return []
    return ["Of those, %s can be added back to a section. The rest are "
            "halves of an asset whose other file is not in the folder, so "
            "they can only be moved aside." % _files(len(addable))]


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


def quarantine(findings: dict) -> dict:
    """Move unclaimed files into the one quarantine; refuses on any bad list."""
    _refuse_a_houdini_that_holds_the_library()
    if not findings["complete"]:
        raise ValueError("one of the library's lists cannot be read, so "
                         "these files may belong to it")
    from amaze.core import library as library_mod
    root = library_mod.quarantine_folder(findings["directory"])
    moved, failed = [], []
    for folder, names in findings["unaccounted"].items():
        if not names:
            continue
        for name in names:
            source = os.path.join(findings["directory"], folder, name)
            if library_mod.quarantine_file(findings["directory"], source):
                moved.append(name)
            else:
                failed.append(name)
    debug.event("repair", "unclaimed files moved aside", folder=root,
                moved=len(moved), failed=len(failed),
                moved_files=moved, failed_files=failed)
    return {"folder": root, "moved": moved, "failed": failed}



def reattach(findings: dict, filename: str) -> dict:
    """A row for every complete unclaimed pair, under a plain name and no renderer."""
    _refuse_a_houdini_that_holds_the_library()
    if not findings["complete"]:
        raise ValueError("one of the library's lists cannot be read, so "
                         "these files may belong to it")
    path = os.path.join(findings["directory"], filename)
    document, error = restore_lib.read_document(path)
    malformed = error or database.wrong_shape(document)
    if malformed:
        debug.event("repair", "cannot add to a list it cannot read",
                    file=filename, reason=malformed)
        raise ValueError("that list cannot be read, so nothing was added "
                         "to it")

    added = []
    for asset_id in _complete_pairs(findings):
        asset = material.Material(
            name="Recovered %s" % asset_id[:8],
            cats=RECOVERED_CATEGORY,
            tags=[""],
            fav=False,
            renderer="",
            date=str(datetime.datetime.now())[:-7],
            mat_id=asset_id,
        )
        document.setdefault("assets", []).append(asset.get_as_dict())
        added.append(asset_id)
    if added:
        categories = document.setdefault("categories", ["_All"])
        if RECOVERED_CATEGORY not in categories:
            categories.append(RECOVERED_CATEGORY)
        _write_json(path, document)
    debug.event("repair", "unlisted files added back to a list",
                file=filename, added=len(added))
    return {"added": added, "path": path}


def _complete_pairs(findings: dict) -> list:
    """The unclaimed ids with both halves present, in a stable order."""
    halves = {}
    for name in findings["unaccounted"].get(findings["asset_dir"], []):
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


def _reattachable_files(findings: dict) -> list:
    """Every file adding a pair back accounts for, counted like the other button."""
    pairs = set(_complete_pairs(findings))
    if not pairs:
        return []
    covered = []
    for folder, names in findings["unaccounted"].items():
        extensions, tail = ((".mat", ".interface"), "_cop") \
            if folder == findings["asset_dir"] else ((".png",), "_icon")
        for name in names:
            if database.asset_id_for_file(name, extensions, tail) in pairs:
                covered.append(name)
    return covered


def _write_json(path: str, document) -> None:
    """Scratch-and-promote without the snapshot: a recovery tool keeps the copies."""
    scratch = hostos.unique_scratch(path, suffix=".repairing")
    try:
        with open(scratch, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)
    except OSError:
        hostos.discard_scratch(scratch)
        raise
    hostos.promote_scratch(scratch, path)


def put_back(findings: dict, filename: str, tier: str) -> dict:
    """One saved copy back, through the shared restore; raises `RestoreRefused`."""
    _refuse_a_houdini_that_holds_the_library(
        lambda phrase: restore_lib.RestoreRefused(
            "Nothing was put back: %s." % phrase))
    target = os.path.join(findings["directory"], filename)
    done = restore_lib.put_back(target, tier, allow_loss=True)
    debug.event("repair", "saved copy put back", file=filename, tier=tier,
                undo=done["undo"])
    return done


def open_panel_tab():
    """An Amaze panel tab, or None; reads Houdini's pane list, imports nothing."""
    try:
        desktop = hou.ui.curDesktop()                    # type: ignore
        tabs = desktop.paneTabs()
    except (AttributeError, hou.Error):
        return None
    for tab in tabs:
        try:
            if tab.type() != hou.paneTabType.PythonPanel:
                continue
            active = tab.activeInterface()
            if active is not None and active.name() == "Amaze":
                return tab
        except Exception:                                # noqa: BLE001
            continue
    return None


def session_has_a_library_open() -> bool:
    """Whether anything in this session holds a list, a closed panel included."""
    return bool(database.DatabaseConnector._instances)


def run(preferences=None) -> None:
    """The shelf tool: reports always, changes only with no library open."""
    configured = configured_library(preferences)
    if not configured:
        hou.ui.displayMessage(                           # type: ignore
            messages.NO_LIBRARY_FOLDER_CONFIGURED,
            title=messages.TITLE_AMAZE_REPAIR)
        return
    if not os.path.isdir(configured):
        hou.ui.displayMessage(                           # type: ignore
            messages.LIBRARY_FOLDER_UNREACHABLE
            % configured,
            title=messages.TITLE_AMAZE_REPAIR)
        debug.event("repair", "refused - the library folder is not there",
                    path=configured)
        return
    directory = configured

    panel = open_panel_tab()
    if panel is not None:
        hou.ui.displayMessage(                           # type: ignore
            messages.AMAZE_OPEN_STOPS_REPAIR,
            title=messages.TITLE_AMAZE_REPAIR)
        debug.event("repair", "refused - a panel is open")
        return

    findings = survey(directory)
    debug.event("repair", "surveyed", complete=findings["complete"],
                unaccounted=unaccounted_total(findings),
                states={entry["filename"]: entry["state"]
                        for entry in findings["lists"]})

    lines = report_lines(findings)
    may_change = not session_has_a_library_open()
    if not may_change:
        lines += [
            "",
            "Repair can only tell you this much right now: Amaze has "
            "already read this library since Houdini started, and it would "
            "write what it remembers back over anything put right here. "
            "Quit Houdini, start it again, and run Repair before you open "
            "Amaze - then Repair can also put a saved copy back, or move "
            "unlisted files aside for you.",
        ]

    choices, actions = _choices(findings, may_change)
    picked = hou.ui.displayMessage(                       # type: ignore
        "\n".join(lines),
        buttons=tuple(choices),
        default_choice=len(choices) - 1,
        close_choice=len(choices) - 1,
        title=messages.TITLE_AMAZE_REPAIR,
    )
    action = actions[picked] if 0 <= picked < len(actions) else None
    if action == "restore":
        _do_restore(findings)
    elif action == "quarantine":
        _do_quarantine(findings)
    elif action == "reattach":
        _do_reattach(findings)


def _choices(findings: dict, may_change: bool):
    """Only the buttons that would change something, each with its own count."""
    choices, actions = [], []
    if may_change and restorable(findings):
        choices.append("Put a Saved Copy Back")
        actions.append("restore")
    if may_change and findings["complete"] and _complete_pairs(findings):
        choices.append("Add %s to a Section"
                       % _files_on_a_button(len(_reattachable_files(
                           findings))))
        actions.append("reattach")
    if may_change and findings["complete"] and unaccounted_total(findings):
        choices.append("Move %s Aside"
                       % _files_on_a_button(unaccounted_total(findings)))
        actions.append("quarantine")
    choices.append("Close")
    actions.append(None)
    return choices, actions


def _do_restore(findings: dict) -> None:
    offers = restorable(findings)
    labels = ["%s - %s" % (database.section_label(filename),
                           _copy_named_by_what_it_holds(filename, snap))
              for filename, _tier, snap, _current in offers]
    chosen = hou.ui.selectFromList(                       # type: ignore
        labels, exclusive=True, title=messages.TITLE_AMAZE_REPAIR,
        message="Which saved copy should Amaze put back?",
        column_header="Saved copies")
    if not chosen:
        return
    filename, tier, snap, current = offers[chosen[0]]
    label = database.section_label(filename)
    if snap["error"]:
        hou.ui.displayMessage(                            # type: ignore
            messages.CHOSEN_SAVED_COPY_CANNOT_BE_READ % label,
            title=messages.TITLE_AMAZE_REPAIR)
        return
    # Name the gain and the loss, and do the subtraction for the reader.
    held = snap["count"] or 0
    if current["error"]:
        change = ("The list you have now cannot be read at the moment, so "
                  "Amaze cannot say what is in it to compare.")
    else:
        now_holds = current["count"] or 0
        change = ("The list you have now holds %d. Putting this copy back "
                  "takes you from %d to %d: anything saved to %s since %s "
                  "is not in this copy and will not be there afterwards."
                  % (now_holds, now_holds, held, label, snap["when"]))
    if hou.ui.displayMessage(                             # type: ignore
        messages.CONFIRM_PUT_SAVED_COPY_BACK % (label, snap["when"]),
        help="That copy is from %s and holds %d %s. %s\n\nYour %s' own "
             "files and thumbnails are not touched either way, and the "
             "list you have now is saved in the library folder first - "
             "run Repair again and it offers that copy back."
             % (snap["when"], held, database.section_noun(filename, held),
                change, database.section_noun(filename, 2)),
        buttons=messages.BUTTONS_PUT_COPY_BACK,
        default_choice=1, close_choice=1,
        severity=hou.severityType.Warning,                # type: ignore
        title=messages.TITLE_AMAZE_REPAIR,
    ) != 0:
        return
    try:
        done = put_back(findings, filename, tier)
    except restore_lib.RestoreRefused as exc:
        hou.ui.displayMessage(str(exc), title=messages.TITLE_AMAZE_REPAIR)  # type: ignore
        return
    undo = (restore_lib.info(os.path.join(findings["directory"],
                                          done["undo"]))
            if done["undo"] else None)
    if undo is not None and undo["exists"]:
        went_back = ("The list you had a moment ago is still in the library "
                     "folder: run Repair again and put back the copy from "
                     "%s to return to it." % undo["when"])
    else:
        went_back = ("There was no list here before, so there is nothing to "
                     "go back to.")
    hou.ui.displayMessage(                                # type: ignore
        messages.SAVED_COPY_PUT_BACK_DONE % (label, snap["when"], went_back),
        title=messages.TITLE_AMAZE_REPAIR)


def _do_quarantine(findings: dict) -> None:
    total = unaccounted_total(findings)
    if hou.ui.displayMessage(                             # type: ignore
        messages.CONFIRM_MOVE_FILES_ASIDE % _files(total),
        help="The files no section lists: %s. They move into Amaze's "
             "own holding folder on this computer - outside your "
             "library, so they do not sync and do not travel. Nothing "
             "is deleted today: they are kept for 30 days and named in "
             "the report, and moving one back is copying it back.\n\n"
             "Everything showing in Amaze stays. Do this only if you have "
             "already tried putting a saved copy of a list back: if one of "
             "these files belongs to a material whose list was lost, "
             "restoring the list is what brings it back."
             % _files_by_folder(findings),
        buttons=messages.BUTTONS_MOVE_ASIDE,
        default_choice=1, close_choice=1,
        title=messages.TITLE_AMAZE_REPAIR,
    ) != 0:
        return
    try:
        result = quarantine(findings)
    except ValueError as exc:
        # Unreachable through the buttons, and handled anyway.
        hou.ui.displayMessage(                            # type: ignore
            messages.NOTHING_MOVED_ASIDE_REASON % exc,             # a sentence
            title=messages.TITLE_AMAZE_REPAIR)
        return
    if result["failed"]:
        hou.ui.displayMessage(                            # type: ignore
            messages.FILES_MOVED_ASIDE_SOME_FAILED
            % (_files(len(result["moved"])),
               _files(len(result["failed"]))),
            title=messages.TITLE_AMAZE_REPAIR)
    else:
        hou.ui.displayMessage(                            # type: ignore
            messages.FILES_MOVED_ASIDE_DONE
            % _files(len(result["moved"])),
            title=messages.TITLE_AMAZE_REPAIR)


def _do_reattach(findings: dict) -> None:
    pairs = _complete_pairs(findings)
    owners = database.ASSET_FILE_OWNERS
    labels = [database.section_label(name) for name in owners]
    chosen = hou.ui.selectFromList(                       # type: ignore
        labels, exclusive=True, title=messages.TITLE_AMAZE_REPAIR,
        message="Which section do these %s belong in? Amaze cannot tell "
                "from the files themselves - a saved material and a saved "
                "node look the same in the folder."
                % _files(len(_reattachable_files(findings))),
        column_header="Section")
    if not chosen:
        return
    filename = owners[chosen[0]]
    label = database.section_label(filename)
    noun = database.section_noun(filename, len(pairs))
    if hou.ui.displayMessage(                             # type: ignore
        # How a material is stored is not what it is.
        messages.CONFIRM_ADD_UNLISTED_TO_SECTION % (len(pairs), noun, label),
        help="Each one comes back in a new category called %s, named %s "
             "plus the start of its file name - rename them afterwards. "
             "They come back without a renderer badge until you save them "
             "again. Their old names, categories and tags cannot come back "
             "this way: those were only ever in the list, not in the "
             "files.\n\n"
             "If there is a saved copy of the %s list from before they "
             "went missing, putting that back instead brings the names "
             "and categories with it. Nothing here is deleted or "
             "overwritten either way."
             % (RECOVERED_CATEGORY, RECOVERED_CATEGORY, label),
        buttons=messages.BUTTONS_ADD_BACK,
        default_choice=1, close_choice=1,
        title=messages.TITLE_AMAZE_REPAIR,
    ) != 0:
        return
    try:
        result = reattach(findings, filename)
    except ValueError as exc:
        hou.ui.displayMessage(                            # type: ignore
            messages.SECTION_LIST_UNCHANGED_REASON % (label, exc),
            title=messages.TITLE_AMAZE_REPAIR)
        return
    hou.ui.displayMessage(                                # type: ignore
        messages.UNLISTED_FILES_ADDED_BACK_DONE
        % (len(result["added"]),
           database.section_noun(filename, len(result["added"])),
           label, RECOVERED_CATEGORY),
        title=messages.TITLE_AMAZE_REPAIR)
