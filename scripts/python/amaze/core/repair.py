"""Check Library: the guard's judgement of the databases and the folder, and fixes through it."""

import filecmp
import json
import os
import time

from amaze.core import debug, documents, guard, library_db, material, renderers
from amaze.core import library_files as naming
from amaze.core import asset_record
from amaze.core.material import RECORD_SUFFIX
from amaze.helpers import hostos, wording
from amaze.prefs import prefs as prefs_module


DATABASES = naming.DATABASES
ROWS = "assets"

ASSET_SIDECARS = naming.ASSET_SUFFIXES

_MISSING = ("absent", "absent-but-known")

_IN_TROUBLE = ("unreadable", "absent-but-known", "newer", "no-library")    # empty: only with a copy

_SETTINGS = "settings.json"    # machine-local; Check Library says when it will not read

RECOVERED_CATEGORY = "Recovered"

_STATE = {guard.CORRUPT: "unreadable", guard.MISSING: "absent-but-known", guard.NEWER: "newer",
          guard.FRESH: "absent"}


class RestoreRefused(Exception):
    """A restore not done; `str()` is a sentence for a dialog."""


def configured_library(preferences=None) -> str:
    """The folder the settings name, reachable or not: unconfigured is empty."""
    if preferences is None:
        preferences = prefs_module.Prefs()
        preferences.load()
    return str(getattr(preferences, "dir", "") or "")


CAPTURES_DIR = naming.CAPTURE_FOLDER + "/"

SCRATCH_MIN_AGE = 60 * 60    # a younger scratch may be another session's live write

UNCATEGORISED = "Uncategorized"

_ASSET_KINDS = (naming.ASSET, naming.RECORD, naming.COMPANION, naming.RENDER)    # owned by id
_PICTURE_SECTIONS = tuple(section for section in naming.SECTION_FOLDERS    # a capture is all they own
                          if section not in naming.ASSET_SECTIONS)


def asset_folders(directory: str = "") -> list:
    """Each asset section's folder: `["materials", "nodes"]`."""
    return [naming.SECTION_FOLDERS[section] for section in naming.ASSET_SECTIONS]


def _unlistable(directory: str) -> tuple:
    """(folder, the kinds in it an asset owns by id, whether it must be there to be listed)."""
    return tuple((folder, _ASSET_KINDS, folder == naming.SECTION_FOLDERS[naming.MATERIALS])
                 for folder in asset_folders(directory)) + tuple(
        (naming.SECTION_FOLDERS[section], (naming.RENDER,), False)
        for section in _PICTURE_SECTIONS)


def _guard(directory: str) -> guard.Guard:
    return guard.Guard(str(directory))


def survey(preferences_or_directory, img_dir: str = "img/") -> dict:
    """Everything Check Library reports, from one walk; with preferences the Files section too."""
    preferences = None
    directory = preferences_or_directory
    if not isinstance(preferences_or_directory, (str, os.PathLike)):
        preferences = preferences_or_directory
        directory = str(preferences.dir or "")
        img_dir = preferences.img_dir
    directory = str(directory)
    held = _guard(directory)
    held.expire_trash()
    listing = _walk(directory)

    lists = []
    ids = set()
    complete = True
    shrunk = []
    for reading in held.health():
        entry = _survey_one(held, reading)
        lists.append(entry)
        ids |= entry["ids"]
        if entry["state"] in ("unreadable", "absent-but-known", "newer") and \
                entry["filename"] in naming.LISTS:
            complete = False
        if reading.shrunk:
            shrunk.append((reading.name,) + tuple(reading.shrunk))

    folders = asset_folders(directory)
    keys = {folder: folder + "/" for folder, _kinds, _needed in _unlistable(directory)}
    keys.update({naming.RENDER_FOLDER: img_dir, naming.CAPTURE_FOLDER: CAPTURES_DIR})
    unaccounted = {}
    unreadable_folders = []
    for folder, kinds, needed in _unlistable(directory):
        names = listing["names"].get(folder)
        if names is None and (needed or folder in listing["unreadable"]):
            debug.event("repair", "folder could not be listed",
                        path=os.path.join(directory, folder))
            unreadable_folders.append(keys[folder])
            unaccounted[keys[folder]] = []
            complete = False
            continue
        unaccounted[keys[folder]] = sorted(
            name for name, (kind, owner) in (names or {}).items()
            if kind in kinds and owner not in ids)

    findings = {
        "directory": directory,
        "asset_dirs": [keys[folder] for folder in folders],
        "img_dir": img_dir,
        "lists": lists,
        "ids": ids,
        "complete": complete,
        "unreadable_folders": unreadable_folders,
        "unaccounted": unaccounted,
        "preferences": preferences,
    }
    findings["stamps"] = _stamps_of_unlisted_pairs(findings, listing)
    findings.update(_listed_rows_checked(lists, listing))
    findings.update(_out_of_place(directory, listing))
    findings.update(_files_section(preferences))
    findings["shrunk"] = shrunk
    findings["holding"] = held.trash_held()
    return findings


def _walk(directory: str) -> dict:
    """The library in one walk: {names: {folder: {name: (kind, detail)}}, out_of_place, ...}."""
    names = {}
    out_of_place = []
    unreadable = []
    for relative, kind, detail, info in naming.walk(directory):
        if kind == naming.UNREADABLE:
            unreadable.append(relative)
            debug.event("repair", "folder could not be listed",
                        path=os.path.join(directory, relative), error=detail)
            continue
        parts = naming.split(relative)
        names.setdefault(naming.join(parts[:-1]), {})[parts[-1]] = (kind, detail)
        if kind == naming.FOLDER:
            names.setdefault(relative, {})    # entered: an empty one is listed, and empty
        elif kind in naming.OUT_OF_PLACE:
            out_of_place.append((relative, kind, detail, info))
    if "" not in unreadable:
        names.setdefault("", {})
    for relative in unreadable:
        names.pop(relative, None)
    _records_by_content(directory, names, out_of_place)
    _superseded(out_of_place)
    return {"names": names, "out_of_place": out_of_place, "unreadable": unreadable}


def metadata_stem(name: str) -> str:
    """The id of an `<id>.json` for any safe id, however it is spelled; else ""."""
    if not name.endswith(RECORD_SUFFIX):
        return ""
    stem = name[: -len(RECORD_SUFFIX)]
    return stem if material.is_safe_asset_id(stem) else ""


def _records_by_content(directory: str, names: dict, out_of_place: list) -> None:
    """An `<id>.json` holding metadata is an asset's, whatever its id spells."""
    found = set()
    for folder in asset_folders(directory):
        here = names.get(folder) or {}
        for name, (kind, _detail) in list(here.items()):
            stem = metadata_stem(name) if kind == naming.UNKNOWN else ""
            if stem and asset_record.read(
                    os.path.join(directory, folder, name))[asset_record.METADATA]:
                here[name] = (naming.RECORD, stem)
                found.add(folder + "/" + name)
    out_of_place[:] = [entry for entry in out_of_place if entry[0] not in found]


def _superseded(out_of_place: list) -> None:
    """What the format 4 conversion left: leftovers Amaze made, never read for content."""
    from amaze.core import library_conversion
    out_of_place[:] = [(relative, naming.SUPERSEDED, detail, info)
                       if kind == naming.UNKNOWN and library_conversion.old_shape(relative)
                       else (relative, kind, detail, info)
                       for relative, kind, detail, info in out_of_place]


def _folders_of(findings: dict) -> list:
    """(folder key, absolute path) of each asset folder the survey listed."""
    return [(key, os.path.join(findings["directory"], key))
            for key in findings.get("asset_dirs", ())]


def metadata_of(folders, asset_id: str):
    """The metadata an asset's `<id>.json` holds; None when none in `folders` holds any."""
    for folder in folders:
        found = asset_record.read(os.path.join(folder, asset_id + RECORD_SUFFIX))[
            asset_record.METADATA]
        if found:
            return found
    return None


def _stamps_of_unlisted_pairs(findings: dict, listing: dict) -> dict:
    """{id: record or None} for each unlisted pair or lone metadata: all a survey opens."""
    folders = [path for _key, path in _folders_of(findings)]
    return {asset_id: metadata_of(folders, asset_id)
            for asset_id in _ids_with_a_stamp(findings)}


def _on_disk(listing: dict, folders: list, names: tuple) -> bool:
    """Whether any of `names` is in any of the asset `folders` the walk listed."""
    return any(name in (listing["names"].get(folder) or {}) for folder in folders
               for name in names)


def _listed_rows_checked(lists: list, listing: dict) -> dict:
    """Per Material and Node database: rows whose files are gone, renders missing, no category."""
    missing_files, missing_renders, uncategorised = {}, {}, {}
    for entry in lists:
        filename = entry["filename"]
        if filename not in naming.ASSET_SECTIONS:
            continue
        home = naming.SECTION_FOLDERS[filename]
        folders = [home]
        listed = home in listing["names"]
        gone, unrendered, loose = [], [], []
        for row in entry.get("rows", ()):
            asset_id = str(row.get("id", ""))
            named = (asset_id, str(row.get("name") or asset_id))
            if not _categories_of(row):
                loose.append(named)
            if not listed or not material.is_safe_asset_id(asset_id):
                continue
            if not _on_disk(listing, folders, (asset_id + ".mat", )) or not _on_disk(
                    listing, folders, (asset_id + RECORD_SUFFIX,)):
                gone.append(named)
            elif (not _on_disk(listing, folders, (asset_id + naming.PICTURE_SUFFIX,))
                  and (filename == naming.MATERIALS
                       or renderers.can_hold_a_render(row.get("renderer")))):
                unrendered.append(named)
        missing_files[filename] = gone
        missing_renders[filename] = unrendered
        uncategorised[filename] = loose
    return {"missing_files": missing_files, "missing_renders": missing_renders,
            "uncategorised": uncategorised}


def _categories_of(row: dict) -> list:
    """A row's categories as a list, blanks dropped."""
    found = row.get("categories")
    if isinstance(found, str):
        found = [found]
    return [one.strip() for one in (found or []) if isinstance(one, str) and one.strip()]


def _out_of_place(directory: str, listing: dict) -> dict:
    """Leftovers to sweep, duplicates held back, and the files and folders no name fits."""
    leftovers, held_back, unknown, unknown_folders = [], [], [], []
    now = time.time()
    for relative, kind, detail, info in listing["out_of_place"]:
        size, when = (info.st_size, info.st_mtime) if info is not None else (0, 0.0)
        if kind == naming.SCRATCH:
            if info is not None and now - when >= SCRATCH_MIN_AGE:
                leftovers.append((relative, kind, size, when))
        elif kind in (naming.PRE_ADOPT_COPY, naming.SUPERSEDED):
            leftovers.append((relative, kind, size, when))
        elif kind == naming.DUPLICATE:
            why = _why_a_duplicate_stays(directory, relative, detail, listing)
            if why:
                held_back.append((relative, detail, size, when, why))
            else:
                leftovers.append((relative, kind, size, when))
        elif detail == "folder":
            files_in, total = _folder_size(os.path.join(directory, relative))
            unknown_folders.append((relative, files_in, total, when))
        else:
            unknown.append((relative, size, when))
    return {"leftovers": leftovers, "held_back": held_back, "unknown": unknown,
            "unknown_folders": unknown_folders}


def _why_a_duplicate_stays(directory: str, relative: str, original: str, listing=None) -> str:
    """Empty when the duplicate may go, else `alone` or `differs`."""
    parts = naming.split(original)
    if listing is not None:
        present = parts[-1] in listing["names"].get(naming.join(parts[:-1]), {})
    else:
        present = os.path.isfile(os.path.join(directory, *parts))
    if not present:
        return "alone"
    if naming.classify(original)[0] in naming.COPIES:
        return ""
    try:
        same = filecmp.cmp(os.path.join(directory, *naming.split(relative)),
                           os.path.join(directory, *parts), shallow=False)
    except OSError:
        same = False
    return "" if same else "differs"


def _folder_size(path: str) -> tuple:
    count = total = 0
    for here, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(here, name))
                count += 1
            except OSError:
                pass
    return count, total


def _files_section(preferences) -> dict:
    """The Files section's folders not on this computer or on a drive away, and stars gone."""
    found = {"dead_folders": [], "unmounted_folders": [], "dead_stars": []}
    if preferences is None:
        return found
    from amaze.core import locations
    for path in locations.registered_paths(preferences):
        if os.path.isdir(path):
            continue
        if hostos.volume_unreachable(path):    # unreachable is not gone: a blinking network share
            found["unmounted_folders"].append(path)
        else:
            found["dead_folders"].append(path)
    for path in locations.favourite_paths(preferences):
        if os.path.exists(path) or hostos.volume_unreachable(path):
            continue
        if not os.path.isdir(os.path.dirname(path)):    # its folder is not here, or not synced yet
            continue
        found["dead_stars"].append(path)
    return found


def _count(name: str, document) -> int:
    """How many entries a database holds by the section it is counted by, per-user ones summed."""
    kind = guard.DATABASES[name]
    section = kind.counted or ("users" if name == naming.MASTER else "")
    table = (document or {}).get(section) or {}
    if kind.sections.get(section) == guard.PER_USER:
        return sum(len(own or {}) for own in table.values() if isinstance(own, dict))
    return len(table)


def _backup_facts(held: guard.Guard, name: str, entry: str, when) -> dict:
    """What one backup is: its date, what it holds, or why it cannot be read."""
    path = held.path(guard.BACKUP_DIR, entry)
    facts = {"path": path, "name": entry, "exists": True, "size": 0,
             "when": when.strftime("%Y-%m-%d %H:%M"), "count": None,
             "noun": naming.section_noun(name), "error": ""}
    try:
        raw = held.read_file(guard.BACKUP_DIR + "/" + entry)
        facts["size"] = len(raw)
        document = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("it is not a database")
        facts["count"] = _count(name, document)
    except (OSError, ValueError) as exc:
        facts["error"] = str(exc)
    return facts


def stored(row: dict) -> dict:
    """A row without who changed it and when."""
    return {field: value for field, value in row.items() if field not in documents.STAMPS}


def _survey_one(held: guard.Guard, reading) -> dict:
    """One database as the guard judges it: its state, what it holds, and its backups."""
    name = reading.name
    path = held.path(name)
    exists = os.path.lexists(path)
    facts = {"path": path, "name": name, "exists": exists, "size": 0, "when": "",
             "count": None, "noun": naming.section_noun(name), "error": reading.why}
    if exists:
        try:
            info = os.stat(path)
            facts["size"] = info.st_size
            facts["when"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(info.st_mtime))
        except OSError:
            pass
    entry = {
        "filename": name,
        "label": naming.section_label(name),
        "path": path,
        "info": facts,
        "ids": set(),
        "rows": [],
        "trace": "",
        "verdict": reading.verdict,
        "snapshots": [(backup, _backup_facts(held, name, backup, when))
                      for backup, when in held.backups(name)],
    }
    if reading.verdict != guard.FINE:
        entry["state"] = _STATE.get(reading.verdict, "unreadable")
        if reading.verdict == guard.MISSING:
            entry["trace"] = reading.why
        return entry
    facts["count"] = _count(name, reading.document)
    for key, row in ((reading.document or {}).get(ROWS) or {}).items():
        if isinstance(row, dict):
            entry["ids"].add(str(key))
            entry["rows"].append(dict(stored(row), id=row.get("id", key)))
    entry["state"] = "empty" if not facts["count"] and name in naming.LISTS else "ok"
    return entry


def _metadata_names(directory: str) -> dict:
    """{id: [folder, ...]} of every `<id>.json` in the asset folders."""
    found = {}
    for folder in asset_folders(directory):
        path = os.path.join(directory, folder)
        try:
            names = sorted(os.listdir(path))
        except OSError as exc:
            debug.event("repair", "cannot read an asset folder for a rebuild",
                        folder=path, error=str(exc))
            continue
        for name in names:
            asset_id = metadata_stem(name)
            if asset_id and path not in found.get(asset_id, ()):
                found.setdefault(asset_id, []).append(path)
    return found


def ids_claimed_by(directory: str) -> tuple:
    """`(by_file, unreadable)`: ids per section database that reads, and those that do not."""
    held = _guard(directory)
    by_file, unreadable = {}, []
    for name in naming.LISTS:
        reading = held.read(name)
        if reading.verdict == guard.FRESH:
            continue
        if reading.verdict != guard.FINE:
            unreadable.append(name)
            continue
        by_file[name] = set(((reading.document or {}).get(ROWS) or {}))
    return by_file, unreadable


def rebuild_from_stamps(directory: str, index_filename: str = naming.MATERIALS) -> dict:
    """A section database rebuilt from each asset's metadata; refused while one is unreadable."""
    assets, damaged = {}, []
    categories = []
    by_id = _metadata_names(directory)
    owned_elsewhere = set()
    by_file, unreadable = ids_claimed_by(directory)
    unreadable = [name for name in unreadable if name != index_filename]
    for filename, ids in by_file.items():
        if filename != index_filename:
            owned_elsewhere |= ids
    if unreadable:
        debug.event("repair", "a sibling database could not be read while rebuilding",
                    files=unreadable)
    for asset_id, folders in sorted(by_id.items()):
        if asset_id in owned_elsewhere:
            continue
        record = metadata_of(folders, asset_id)
        if record is None:
            damaged.append(asset_id)
            continue
        if _list_of(record) not in ("", index_filename):
            continue    # metadata that names another database goes in that one
        record.setdefault("id", asset_id)
        assets[asset_id] = record
        for cat in record.get("categories") or []:
            if cat and cat not in categories:
                categories.append(cat)
    debug.event("repair", "rebuilt a database from asset metadata",
                folder=directory, assets=len(assets), damaged=len(damaged))
    return {"assets": assets,
            "categories": {name: {"order": order} for order, name in enumerate(sorted(categories))},
            "damaged": damaged,
            "unreadable": sorted(unreadable)}


def _readable_backups(held: guard.Guard, name: str) -> list:
    """The backups of a database that read, newest first; those holding nothing last."""
    found = []
    for order, (entry, when) in enumerate(held.backups(name)):
        if entry.endswith(guard.UNDO_TAIL):
            continue
        facts = _backup_facts(held, name, entry, when)
        if facts["error"]:
            continue
        found.append((not facts["count"], order, entry))
    return [entry for *_key, entry in sorted(found)]


def repair_index(directory: str, guard_session: bool = True, name: str = naming.MATERIALS,
                 **legacy) -> tuple:
    """The newest backup holding assets, else one that reads, else a rebuild; (ok, how)."""
    if legacy.get("guard", guard_session):
        _refuse_a_houdini_that_holds_the_library()
    held = _guard(directory)
    for entry in _readable_backups(held, name):
        try:
            held.restore(name, entry)
        except (guard.Refused, OSError) as exc:
            debug.event("repair", "backup refused for the rebuild", backup=entry, error=str(exc))
            continue
        debug.event("repair", "database restored from a backup", backup=entry)
        return True, _after_a_put_back(directory, name, "the newest backup was restored")["said"]
    document = rebuild_from_stamps(directory, name)
    if document["unreadable"]:
        debug.event("repair", "rebuild refused - a sibling database is unreadable",
                    files=document["unreadable"])
        return False, ("%s cannot be read, so a rebuild cannot tell its "
                       "assets from this database's"
                       % wording.and_list(document["unreadable"]))
    if not document["assets"]:
        return False, "no backup can be read and no asset metadata was found"
    try:
        change = held.change("")
        change.replace(name, {ROWS: document["assets"], "categories": document["categories"]})
        change.commit()
    except OSError as exc:
        debug.event("repair", "rebuilt database could not be written", error=str(exc))
        return False, "the rebuilt database could not be written"
    how = "the database was rebuilt from each asset's metadata"
    if document["damaged"]:
        how += " (%d could not be read)" % len(document["damaged"])
    debug.event("repair", "database rebuilt from asset metadata",
                assets=len(document["assets"]), damaged=len(document["damaged"]))
    return True, how


def _edit(directory: str, name: str, edit) -> bool:
    """One database read with its ticket, changed by `edit(document)`, saved; whether it was."""
    held = _guard(directory)
    reading = held.read(name)
    if not reading.writable:
        raise ValueError("that database cannot be read, so nothing was changed in it")
    document = json.loads(json.dumps(reading.document or {}))
    if not edit(document):
        return False
    change = held.change("")
    change.put(reading.ticket, document)
    change.commit()
    return True


def _rows_against_their_stamps(directory: str, name: str, folders: list) -> tuple:
    """(rows that took their newer metadata, names of rows with no .mat and no metadata)."""
    taken, gone = [0], []

    def edit(document):
        rows = document.setdefault(ROWS, {})
        categories = document.setdefault("categories", {})
        for asset_id, row in list(rows.items()):
            if not material.is_safe_asset_id(asset_id) or not isinstance(row, dict):
                continue
            record = metadata_of(folders, asset_id)
            if record is None:
                if not any(os.path.exists(os.path.join(one, asset_id + ".mat"))
                           for one in folders):
                    gone.append(str(row.get("name") or asset_id))    # listed, never dropped
                continue
            if str(record.get("id", asset_id)) != asset_id:
                continue
            record["id"] = row.get("id", asset_id)
            if record != stored(row):
                rows[asset_id] = record
                taken[0] += 1
                for cat in record.get("categories") or []:
                    if cat and cat not in categories:
                        categories[cat] = {"order": len(categories)}
        return bool(taken[0])
    try:
        _edit(directory, name, edit)
    except (OSError, ValueError) as exc:    # the backup is back either way
        debug.event("repair", "newer records not taken", error=str(exc))
        taken[0] = 0
    debug.event("repair", "rows checked against their metadata", taken=taken[0], gone=len(gone))
    return taken[0], sorted(gone)


def _after_a_put_back(directory: str, filename: str, how=None) -> dict:
    """A Material or Node database put back: newer metadata taken, later rows added back."""
    if filename not in naming.ASSET_SECTIONS:
        return {"refreshed": 0, "newer": 0, "gone": [],
                "said": how if how is not None else ""}
    folders = [os.path.join(directory, naming.SECTION_FOLDERS[filename])]
    refreshed, gone = _rows_against_their_stamps(directory, filename, folders)
    newer = _rows_newer_than_the_copy(directory, filename)
    return {"refreshed": refreshed, "newer": newer, "gone": gone,
            "said": _put_back_sentence(refreshed, newer, gone, filename, how)}


def _put_back_sentence(refreshed: int, newer: int, gone: list,
                       filename: str = naming.MATERIALS, how=None) -> str:
    """`how`, then what came after the backup and the rows whose files are gone."""
    def counted(count, after):
        return "the %d %s %s after it %s" % (
            count, naming.section_noun(filename, count), after,
            "was" if count == 1 else "were")

    done = []
    if refreshed:
        done.append(counted(refreshed, "changed") + " brought up to date")
    if newer:
        done.append(counted(newer, "saved") + " added back")
    said = wording.and_list(done)
    if how is not None:
        said = how + (", and " + said if said else "")
    if gone:
        said += "%s%s %s in it, but %s files are gone" % (
            " - " if said else "",
            wording.and_list(gone[:8]) + (" and %d more" % (len(gone) - 8) if len(gone) > 8 else ""),
            "is" if len(gone) == 1 else "are", "its" if len(gone) == 1 else "their")
    if how is None and said:
        said = "Also, " + said + "."
    return said


def _rows_newer_than_the_copy(directory: str, filename: str) -> int:
    """The rows a restored backup predates, added from their metadata; how many came back."""
    findings = survey(directory)
    ids = [asset_id for asset_id, _record in on_record(findings, filename)]
    if not ids or why_nothing_can_be_added(findings, filename):
        return 0
    try:
        return len(_add_rows(findings, filename, ids)["added"])
    except (OSError, ValueError) as exc:    # the backup is back either way; these stay for Repair
        debug.event("repair", "rows newer than the backup not added",
                    file=filename, error=str(exc))
        return 0


def unaccounted_total(findings: dict) -> int:
    return sum(len(names) for names in findings["unaccounted"].values())


def restorable(findings: dict) -> list:
    """Every backup that could be restored, newest first, in panel order."""
    offers = []
    for entry in findings["lists"]:
        for tier, snap in entry.get("snapshots", ()):
            offers.append((entry["filename"], tier, snap, entry["info"]))
    return offers


def _document_of(path: str):
    """A database file's sections, without its format stamp; None when it does not read."""
    try:
        with open(path, "rb") as handle:
            document = json.loads(handle.read().decode("utf-8-sig"))
    except (OSError, ValueError):
        return None
    if isinstance(document, dict):
        document.pop("format", None)
    return document


def offered_copies(findings: dict) -> list:
    """`restorable` less a backup that changes nothing; while a database is in trouble, its own."""
    entries = {entry["filename"]: entry for entry in findings["lists"]}
    offers, held = [], {}
    for offer in restorable(findings):
        filename, tier, snap, _now = offer
        undo = tier.endswith(guard.UNDO_TAIL)    # the done-dialog promises it back
        if snap["error"] or not (undo or snap["count"]):
            continue
        document = _document_of(snap["path"])
        now = None
        if entries[filename]["state"] in ("ok", "empty"):
            now = _document_of(entries[filename]["path"])
        seen = held.setdefault(filename, [now])
        if document in seen:    # a repeat of one above it, or of the database as it is
            continue
        seen.append(document)
        offers.append(offer)
    troubled = {filename for filename, entry in entries.items()
                if entry["state"] in _IN_TROUBLE} | {
                    offer[0] for offer in offers if entries[offer[0]]["state"] != "ok"}
    if complete_pairs(findings):    # unlisted pairs are a Material or Node database's loss
        troubled |= set(naming.ASSET_SECTIONS)
    if troubled:
        offers = [offer for offer in offers if offer[0] in troubled
                  or offer[1].endswith(guard.UNDO_TAIL)]    # undo copies stay
    by_list = {}
    for offer in offers:
        by_list.setdefault(offer[0], []).append(offer)
    return [offer for group in by_list.values()    # each database's newest backup first
            for offer in sorted(group, key=lambda one: one[2]["when"], reverse=True)]


def copy_named_by_what_it_holds(filename: str, snap: dict) -> str:
    """A backup named by its date and count."""
    if snap["error"]:
        return "from %s, cannot be read" % snap["when"]
    count = snap["count"] or 0
    return "from %s, %d saved %s" % (
        snap["when"], count, naming.section_noun(filename, count))


def _snapshot_line(entry: dict) -> str:
    if not entry["snapshots"]:
        line = ("%s: there are no backups of this database, so "
                "there is nothing to restore." % entry["label"])
        if entry["filename"] in naming.ASSET_SECTIONS:
            line += (" Your %s' own files and thumbnails are still in the "
                     "library folder either way."
                     % naming.section_noun(entry["filename"], 2))
        return line
    parts = []
    for _tier, snap in entry["snapshots"]:
        part = copy_named_by_what_it_holds(entry["filename"], snap)
        if part not in parts:    # two backups alike read as one
            parts.append(part)
    return "%s: backups - %s." % (entry["label"], "; ".join(parts))


def report_lines(findings: dict) -> list:
    """The whole report, in the user's words, never the program's."""
    lines = ["Amaze looked at the library in %s. It keeps a database for each of its "
             "sections - Materials, Nodes, Code, Colors and Files - and one for the "
             "library itself." % os.path.normpath(str(findings["directory"])), ""]

    troubled = [entry for entry in findings["lists"] if entry["state"] in _TROUBLE_LINES]
    problems = []
    if troubled:
        problems.append("\n".join(_TROUBLE_LINES[entry["state"]] % entry["label"]
                                  for entry in troubled))
    if any(entry["state"] == "empty" for entry in troubled):
        problems.append(
            "A database that holds nothing looks the same whether nothing was "
            "ever saved there or it failed to load this time, so Amaze "
            "will not decide on its own which it is.")
    well = [_lists_line(findings["lists"], bool(troubled))]

    total = unaccounted_total(findings)
    unchecked = [entry["label"] for entry in troubled
                 if entry["state"] in ("unreadable", "absent-but-known", "newer")]
    if findings["unreadable_folders"]:
        problems.append(
            "Amaze could not look inside the %s, so it cannot say whether "
            "there are orphaned files in there. Nothing will be "
            "moved while that is true."
            % _and_folders(findings["unreadable_folders"]))
    elif total and findings["complete"]:
        held = ["None of them will be moved to the trash while a database that may own "
                "them holds nothing: restore a backup of it, or add them to a section."
                ] if why_unlisted_stay(findings) else []
        problems.append(" ".join(["%s %s. Either they belong to something "
                                  "whose database was lost, or nothing needs them any more."
                                  % (files_by_folder(findings), _orphaned(total))]
                                 + _what_can_be_added_back(findings) + held))
    elif total:
        problems.append(" ".join([
            "%s %s. Amaze could not check the %s database either, "
            "so some of those files may be its. Nothing will be moved "
            "while that is true."
            % (files_by_folder(findings), _orphaned(total), wording.and_list(unchecked))]
            + _what_can_be_added_back(findings)))
    elif findings["unaccounted"]:
        well.append("There are no orphaned files in %s."
                    % wording.and_list(["`%s`" % folder for folder in findings["unaccounted"]]))

    said, fine = _check_lines(findings)
    problems.extend(said)
    well.extend(fine)
    problems.extend(_snapshot_line(entry) for entry in troubled)

    for line in problems + [line for line in well if line]:
        lines.extend([line, ""])
    if "holding" in findings:
        lines.append(_holding_line(findings["holding"]))
    return lines


def _orphaned(count: int) -> str:
    """What follows the files no database names: `is orphaned: no database names it`."""
    return ("is orphaned: no database names it" if count == 1
            else "are orphaned: no database names them")


_TROUBLE_LINES = {    # a database's state, and the line it gets when it is in trouble
    "empty": "%s: the database is there and holds nothing.",
    "unreadable": "%s: the database is corrupt/unreadable. It has not been changed.",
    "absent-but-known": (
        "%s: there is no database for it in the library folder, though Amaze can see there "
        "was one here before. If this folder syncs, it may not have synced yet - give it "
        "a minute and run Check Library again."),
    "newer": "%s: the database was saved by a newer Amaze, so it is read-only here. "
             "Update Amaze to change it.",
}


def _lists_line(lists: list, others: bool) -> str:
    """One line for every database that reads fine, each count in its own noun."""
    held = [_counted(entry["info"]["count"] or 0, entry["filename"])
            for entry in lists if entry["state"] == "ok"]
    unsaved = [entry["label"] for entry in lists if entry["state"] == "absent"]
    said = []
    if held:
        said.append("%s: %s." % ("The other databases read fine" if others
                                 else "Every database reads fine", wording.and_list(held)))
    if unsaved:
        said.append("Nothing is saved yet in %s." % wording.and_list(unsaved))
    return " ".join(said)


_SHOWN = 8    # names in a sentence before "and N more"
_SHOWN_LINES = 20    # lines of their own before "and N more"


def _named(names: list) -> str:
    names = list(names)
    more = len(names) - _SHOWN
    return wording.and_list(names[:_SHOWN] + (["%d more" % more] if more > 0 else []))


def _counted(count: int, filename: str) -> str:
    return "%d %s" % (count, naming.section_noun(filename, count))


def _per_section(found: dict) -> str:
    """`3 materials and 1 node`, a count per database in its own noun, empty ones left out."""
    return wording.and_list([_counted(len(rows), filename)
                             for filename, rows in found.items() if rows])


def _every_section() -> str:
    """`material and node`: the nouns of the databases that own asset files."""
    return wording.and_list([naming.section_noun(filename, 1)
                             for filename in naming.ASSET_SECTIONS])


def _size(count: int) -> str:
    if count < 1024 * 1024:
        return "%d KB" % max(1, round(count / 1024.0)) if count else "0 KB"
    return "%.1f MB" % (count / 1048576.0)


def _day(when: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(when)) if when else "an unknown date"


def _limited(lines: list) -> list:
    more = len(lines) - _SHOWN_LINES
    return lines[:_SHOWN_LINES] + (["  and %d more" % more] if more > 0 else [])


def _check_lines(findings: dict) -> tuple:
    """(problems, all-well lines) of what only a full survey asks; a check with none says so."""
    if "leftovers" not in findings:
        return [], []
    said, well = [], []
    missing = findings.get("missing_files") or {}
    for filename, rows in missing.items():
        if rows:
            said.append("%s %s in the %s database, but %s files are missing: %s. A file "
                        "that has not finished syncing looks the same as one that is gone."
                        % (_counted(len(rows), filename), "is" if len(rows) == 1 else "are",
                           naming.section_label(filename),
                           "its" if len(rows) == 1 else "their",
                           _named(name for _id, name in rows)))
    renders = findings.get("missing_renders") or {}
    if any(renders.values()):
        total = sum(len(rows) for rows in renders.values())
        said.append("No thumbnail image yet for %s - select %s in Amaze and use Thumbnail ▸ "
                    "Render Image when convenient, since a render takes time."
                    % (_per_section(renders), "it" if total == 1 else "them"))
    if not any(missing.values()) and not any(renders.values()):
        well.append("Every %s in the databases has its files, and every one that can have a "
                    "render has one." % _every_section())
    elif not any(missing.values()):
        well.append("Every %s in the databases has its files." % _every_section())
    gone = _leftover_lines(findings) + _unknown_lines(findings)
    said.extend(gone)
    if not gone:
        well.append("There are no temporary files from a save that did not finish, and every file "
                    "in the library folder has a name Amaze knows.")
    loose = findings.get("uncategorised") or {}
    if any(loose.values()):
        total = sum(len(rows) for rows in loose.values())
        said.append("%s %s no category, so %s can be put in %s."
                    % (_per_section(loose), "has" if total == 1 else "have",
                       "it" if total == 1 else "they", UNCATEGORISED))
    else:
        well.append("Every %s has a category." % _every_section())
    files_section = _files_section_lines(findings)
    said.extend(files_section)
    if not files_section and findings.get("preferences") is not None:
        well.append("Every folder in the Files section is on this computer, and "
                    "every starred file is still there.")
    for filename, holds, newest in findings.get("shrunk", ()):
        said.append("Your %s database holds %s, but its newest backup holds %s. If you "
                    "did not remove them yourself, that backup can be restored."
                    % (naming.section_label(filename), _counted(holds, filename),
                       _counted(newest, filename)))
    return said, well


_LEFTOVER_KINDS = (    # (kind, one, more)
    (naming.SCRATCH, "temporary file from a save that did not finish",
     "temporary files from saves that did not finish"),
    (naming.PRE_ADOPT_COPY, "backup kept from before an earlier texture update",
     "backups kept from before an earlier texture update"),
    (naming.SUPERSEDED, "file of the older format whose content is now in the asset's .json",
     "files of the older format whose content is now in their asset's .json"),
    (naming.DUPLICATE, "conflict copy a sync service made of a file still here",
     "conflict copies a sync service made of files still here"),
)


def _leftover_lines(findings: dict) -> list:
    said = []
    leftovers = findings.get("leftovers") or []
    if leftovers:
        parts = []
        for kind, one, more in _LEFTOVER_KINDS:
            count = sum(1 for entry in leftovers if entry[1] == kind)
            if count:
                parts.append("%d %s" % (count, one if count == 1 else more))
        said.append("Amaze made %s here that nothing needs any more: %s. Moving them "
                    "to the trash takes them out of the library: %s."
                    % (files(len(leftovers)), wording.and_list(parts),
                       _named("`%s`" % entry[0] for entry in leftovers)))
    for relative, original, size, when, why in findings.get("held_back") or []:
        if why == "alone":
            said.append("`%s` looks like a conflict copy of `%s`, which is not here, so "
                        "it is left where it is." % (relative, original))
        else:
            said.append("`%s` is a conflict copy of `%s`, from %s (%s), and the two "
                        "differ, so it is left where it is." % (
                            relative, original, _day(when), _size(size)))
    return said


def _unknown_lines(findings: dict) -> list:
    entries = []
    for relative, files_in, size, when in findings.get("unknown_folders") or []:
        entries.append((relative, "  `%s/` - a folder of %s, %s, from %s" % (
            relative, files(files_in), _size(size), _day(when))))
    for relative, size, when in findings.get("unknown") or []:
        entries.append((relative, "  `%s` - %s, from %s" % (relative, _size(size), _day(when))))
    if not entries:
        return []
    head = ("This is not a file Amaze knows, so it is left where it is:" if len(entries) == 1
            else "These %d are not files Amaze knows, so they are left where they are:"
            % len(entries))
    return [head + "\n" + "\n".join(_limited([line for _relative, line in sorted(entries)]))]


def _files_section_lines(findings: dict) -> list:
    said = []
    dead = findings.get("dead_folders") or []
    if dead:
        said.append("%s in the Files section %s not on this computer. Setting %s aside "
                    "keeps %s comments, icons and favorites, and they come back when "
                    "the folder is added again:\n  %s"
                    % ("This folder" if len(dead) == 1 else "These %d folders" % len(dead),
                       "is" if len(dead) == 1 else "are", "it" if len(dead) == 1 else "them",
                       "its" if len(dead) == 1 else "their",
                       "\n  ".join(sorted(os.path.normpath(p) for p in dead))))
    unmounted = findings.get("unmounted_folders") or []
    if unmounted:
        said.append("%s on a drive that is not connected, so %s left as %s - %s back "
                    "when the drive is." % (
                        "1 folder is" if len(unmounted) == 1
                        else "%d folders are" % len(unmounted),
                        "it is" if len(unmounted) == 1 else "they are",
                        "it is" if len(unmounted) == 1 else "they are",
                        "it will be" if len(unmounted) == 1 else "they will be"))
    stars = findings.get("dead_stars") or []
    if stars:
        said.append("%s gone from %s folder:\n  %s" % (
            "This starred file is" if len(stars) == 1
            else "These %d starred files are" % len(stars),
            "its" if len(stars) == 1 else "their",
            "\n  ".join(sorted(os.path.normpath(p) for p in stars))))
    return said


def _holding_line(held: dict) -> str:
    """The trash's line: what it holds, when the oldest day goes, and where it is."""
    if not held["files"]:
        return ("The library's trash is empty. Files moved to it are deleted "
                "after %d days: %s" % (guard.TRASH_DAYS, held["path"]))
    first = next((expires for _day_name, expires, _n, _b in held["days"] if expires), "")
    return ("The library's trash holds %s (%s), moved there on "
            "%s. Each day's files are deleted after %d days%s: %s"
            % (files(held["files"]), _size(held["bytes"]),
               "1 day" if len(held["days"]) == 1 else "%d days" % len(held["days"]),
               guard.TRASH_DAYS,
               ", and the oldest go on %s" % first if first else "", held["path"]))


def files(count: int) -> str:
    """The count and its English plural, never the parenthesised one."""
    return "1 file" if count == 1 else "%d files" % count


def files_on_a_button(count: int) -> str:
    """The same count, capitalised: every button in this tool is Title Case."""
    return files(count).replace("file", "File")


def count_on_a_button(count: int, filename: str) -> str:
    """`3 Materials`, `1 Material`: a section's count, Title Case for a button."""
    noun = naming.section_noun(filename, count)
    return "%d %s" % (count, noun[:1].upper() + noun[1:])


def folders(count: int) -> str:
    """`1 folder`, `3 folders`."""
    return "1 folder" if count == 1 else "%d folders" % count


def favorites(count: int) -> str:
    """`1 favorite`, `3 favorites`."""
    return "1 favorite" if count == 1 else "%d favorites" % count


def on_a_button(counted: str) -> str:
    """A count sentence part in Title Case for a button: `3 folders` reads `3 Folders`."""
    return " ".join(word if word == "and" else word[:1].upper() + word[1:]
                    for word in counted.split(" "))


def uncategorised_count(findings: dict) -> str:
    """`3 materials and 1 node`: the rows with no category, each database in its own noun."""
    return _per_section(findings.get("uncategorised") or {})


def _and_folders(names: list) -> str:
    return wording.and_list(["%s folder" % _folder_name(folder) for folder in names])


def files_by_folder(findings: dict) -> str:
    """Folder by folder, never one total, each folder's names while there are few."""
    parts = []
    for folder, names in findings["unaccounted"].items():
        if not names:
            continue
        part = "%s in the %s folder" % (files(len(names)), _folder_name(folder))
        if unaccounted_total(findings) <= 6:
            part += " (%s)" % ", ".join(names)
        parts.append(part)
    return wording.and_list(parts)


def _what_can_be_added_back(findings: dict) -> list:
    """The line that keeps the buttons apart: materials by name, then pairs, then the rest."""
    if why_nothing_can_be_added(findings):
        return []
    on_record_now = materials_on_record(findings)
    addable = reattachable_files(findings)
    rest = unaccounted_total(findings) - len(addable) - len(
        _files_of(findings, [asset_id for asset_id, _record in on_record_now]))
    said = [_materials_sentence(on_record_now)] if on_record_now else []
    if addable and (rest or on_record_now):
        said.append("%s can be added back to a section."
                    % (files(len(addable)).replace(" ", " more ", 1) if on_record_now
                       else "Of those, " + files(len(addable))))
    if rest and said:
        said.append("The rest are halves of an asset whose other file is not "
                    "in the folder, so they can only be moved to the trash.")
    spared = len(_files_of(findings, stamped_unlisted(findings)))
    if spared:
        one = spared == 1
        said.append("Moving files to the trash leaves %s where %s: the metadata of what "
                    "%s to is saved beside %s, so %s can still be added back."
                    % (files(spared), "it is" if one else "they are",
                       "it belongs" if one else "they belong", "it" if one else "them",
                       "it" if one else "they"))
    return [" ".join(said)] if said else []


def _materials_sentence(on_record_now: list) -> str:
    """The materials Add Back puts in the database, by name while there are few to read."""
    count = len(on_record_now)
    one = count == 1
    names = ""
    if count <= 6:
        names = ": " + wording.and_list([str(record.get("name") or asset_id)
                                          for asset_id, record in on_record_now])
    return ("The files include %d %s with %s metadata saved "
            "beside %s%s. Add %s Back puts %s in the %s database."
            % (count, naming.section_noun(naming.MATERIALS, count),
               "its" if one else "their", "it" if one else "them", names,
               count_on_a_button(count, naming.MATERIALS), "it" if one else "them",
               naming.section_label(naming.MATERIALS)))


def _folder_name(folder: str) -> str:
    return str(folder).rstrip("/\\") or folder


_SESSION_HOLDS_THE_LIBRARY = (
    "this Houdini session has already read the library, so open Amaze and use "
    "Library ▸ Check Library…")


def _refuse_a_houdini_that_holds_the_library(refusal=ValueError) -> None:
    """Every action enforces this for itself; the button logic is a courtesy."""
    if session_has_a_library_open():
        raise refusal(_SESSION_HOLDS_THE_LIBRARY)


def movable(findings: dict) -> dict:
    """`findings` less the files of each unlisted pair whose metadata reads: those go back."""
    kept = set(_files_of(findings, stamped_unlisted(findings)))
    if not kept:
        return findings
    return dict(findings, unaccounted={
        folder: [name for name in names if name not in kept]
        for folder, names in findings["unaccounted"].items()})


def files_to_move_aside(findings: dict) -> int:
    """Move to Trash's count: the unlisted files `movable` leaves, and the leftovers."""
    unlisted = 0 if why_unlisted_stay(findings) else unaccounted_total(movable(findings))
    return unlisted + len(findings.get("leftovers") or ())


def why_unlisted_stay(findings: dict) -> str:
    """Empty when unlisted files may go to the trash; else why a database may still own them."""
    if not findings.get("complete"):
        return "one of the library's databases cannot be read, so these files may belong to it"
    empty = [entry["label"] for entry in findings.get("lists", ())    # only its own folder is held
             if entry["state"] == "empty" and entry["filename"] in naming.ASSET_SECTIONS
             and findings["unaccounted"].get(naming.SECTION_FOLDERS[entry["filename"]] + "/")]
    if empty:
        return ("the %s database holds nothing, so these files may belong to it"
                % wording.and_list(empty))
    return ""


def unknown_to_move_aside(findings: dict) -> int:
    """Move Unknown's count: each unknown file, and each unknown folder as one."""
    return len(findings.get("unknown") or ()) + len(findings.get("unknown_folders") or ())


MOVABLE = ("unlisted", "leftovers", "unknown")


def move_aside(findings: dict, what, guard_session: bool = True, **legacy) -> dict:
    """What `what` names, one of MOVABLE or several, into the library's trash as ONE change."""
    if legacy.get("guard", guard_session):
        _refuse_a_houdini_that_holds_the_library()
    asked = (what,) if isinstance(what, str) else tuple(what)
    for one in asked:
        if one not in MOVABLE:
            raise ValueError("there is nothing called %r to move to the trash" % one)
    directory = findings["directory"]
    reason = why_unlisted_stay(findings) if "unlisted" in asked else ""
    if reason:
        raise ValueError(reason)
    held = _guard(directory)
    change = held.change("")
    moved, failed, taken = [], [], []

    def take(relative, shown):
        if os.path.lexists(os.path.join(directory, *naming.split(relative))):
            change.trash(relative)
            moved.append(shown)
        else:
            failed.append(shown)

    if "unlisted" in asked:
        by_file, unreadable = ids_claimed_by(directory)
        if unreadable:
            raise ValueError("one of the library's databases cannot be read, so these "
                             "files may belong to it")
        claimed = set().union(*by_file.values()) if by_file else set()
        for folder, names in movable(findings)["unaccounted"].items():
            for name in names:
                relative = folder.rstrip("/\\") + "/" + name
                if naming.classify(relative)[1] in claimed:
                    taken.append(name)    # a database claims it since the check
                    continue
                take(relative, name)
    if "leftovers" in asked:
        for relative, kind, _size, _when in findings.get("leftovers", ()):
            if kind == naming.DUPLICATE and _why_a_duplicate_stays(
                    directory, relative, naming.classify(relative)[1]):
                failed.append(relative)    # it changed since the check: a second version now
                continue
            take(relative, relative)
    if "unknown" in asked:
        for relative, _size, _when in findings.get("unknown", ()):
            take(relative, relative)
        for relative, _files, _size, _when in findings.get("unknown_folders", ()):
            take(relative, relative)
    try:
        change.commit()
    except OSError as exc:
        debug.event("repair", "nothing moved to the trash", error=str(exc))
        failed.extend(moved)
        moved = []
    root = held.path(guard.TRASH_DIR)
    debug.event("repair", "files moved to the trash", what=list(asked), folder=root,
                moved=len(moved), failed=len(failed), failed_files=failed)
    return {"folder": root, "moved": moved, "failed": failed, "claimed": taken}


def set_aside_folders(findings: dict, guard_session: bool = True, **legacy) -> list:
    """Drop the Files section's pointer to each folder not on this computer; files untouched."""
    if legacy.get("guard", guard_session):
        _refuse_a_houdini_that_holds_the_library()
    preferences = findings["preferences"]
    done = []
    for path in findings.get("dead_folders", ()):
        if os.path.isdir(path) or hostos.volume_unreachable(path):
            continue    # it came back since the check
        preferences.remove_file_folder(path)
        done.append(path)
    debug.event("repair", "folders set aside", folders=done)
    return done


def drop_dead_stars(findings: dict, guard_session: bool = True, **legacy) -> list:
    """Unstar each starred file gone from a folder that is still here, as one change."""
    if legacy.get("guard", guard_session):
        _refuse_a_houdini_that_holds_the_library()
    from amaze.core import locations
    gone = [path for path in findings.get("dead_stars", ())
            if not os.path.exists(path) and os.path.isdir(os.path.dirname(path))]
    if gone:
        locations.set_favourites(findings["preferences"], {path: False for path in gone})
    debug.event("repair", "stars on files that are gone dropped", files=gone)
    return gone


def rescue_uncategorised(findings: dict, guard_session: bool = True, **legacy) -> dict:
    """Each row with no category put in Uncategorized, database by database; {database: n}."""
    if legacy.get("guard", guard_session):
        _refuse_a_houdini_that_holds_the_library()
    done = {}
    for filename, rows in findings.get("uncategorised", {}).items():
        wanted = {asset_id for asset_id, _name in rows}
        if not wanted:
            continue
        count = [0]

        def edit(document, wanted=wanted, count=count):
            for asset_id, row in (document.get(ROWS) or {}).items():
                if asset_id in wanted and isinstance(row, dict) and not _categories_of(row):
                    row["categories"] = [UNCATEGORISED]
                    count[0] += 1
            if count[0]:
                categories = document.setdefault("categories", {})
                categories.setdefault(UNCATEGORISED, {"order": len(categories)})
            return bool(count[0])
        if _edit(findings["directory"], filename, edit):
            done[filename] = count[0]
    debug.event("repair", "rows with no category put in one", lists=done)
    return done


def reattach(findings: dict, filename: str, only=None, guard_session: bool = True,
             **legacy) -> dict:
    """Add the unclaimed pairs, or the ids in `only`, to `filename` from their metadata."""
    if legacy.get("guard", guard_session):
        _refuse_a_houdini_that_holds_the_library()
    return _add_rows(findings, filename,
                     complete_pairs(findings) if only is None else list(only))


def add_materials_back(findings: dict, guard_session: bool = True, **legacy) -> dict:
    """Put every material `materials_on_record` finds in the Materials database."""
    if legacy.get("guard", guard_session):
        _refuse_a_houdini_that_holds_the_library()
    return _add_rows(findings, naming.MATERIALS,
                     [asset_id for asset_id, _record in materials_on_record(findings)])


def materials_on_record(findings: dict) -> list:
    """`on_record` for the Materials database: what Add Back puts there."""
    return on_record(findings, naming.MATERIALS)


def on_record(findings: dict, filename: str) -> list:
    """The unlisted pairs whose readable metadata belongs in `filename`, as `(id, record)`."""
    if "asset_dirs" not in findings:
        return []
    stamps = _stamps(findings)
    return [(asset_id, stamps[asset_id]) for asset_id in complete_pairs(findings)
            if stamps.get(asset_id) is not None and _list_of(stamps[asset_id]) == filename]


def _list_of(record: dict) -> str:
    """The database a record goes in: a renderer Amaze knows is a material's, else a node's."""
    renderer = record.get("renderer")
    if renderers.get(renderer):
        return naming.MATERIALS
    return naming.NODES if renderer else ""


def stamped_unlisted(findings: dict) -> list:
    """The unlisted ids whose metadata reads, a pair or alone: what can still be put back."""
    if "asset_dirs" not in findings:
        return []
    stamps = _stamps(findings)
    return sorted(asset_id for asset_id, record in stamps.items() if record is not None)


def _unaccounted_assets(findings: dict) -> list:
    """Every unlisted name in the asset folders."""
    return [name for key in findings.get("asset_dirs", ())
            for name in findings["unaccounted"].get(key, [])]


def _ids_with_a_stamp(findings: dict) -> list:
    """The unlisted complete pairs, and the ids whose unlisted metadata sits alone, by id."""
    alone = [metadata_stem(name) for name in _unaccounted_assets(findings)]
    return sorted(set(complete_pairs(findings)) | {one for one in alone if one})


def _stamps(findings: dict) -> dict:
    """The metadata of the unlisted pairs, read once per survey."""
    if "stamps" not in findings:
        found = [path for _key, path in _folders_of(findings)]
        findings["stamps"] = {asset_id: metadata_of(found, asset_id)
                              for asset_id in _ids_with_a_stamp(findings)}
    return findings["stamps"]


def why_nothing_can_be_added(findings: dict, filename: str = "") -> str:
    """Empty when unlisted files may go in `filename`, or in any database; else why not."""
    if findings.get("unreadable_folders"):
        return ("Amaze could not look inside the %s, so it cannot tell which "
                "files are orphaned" % _and_folders(findings["unreadable_folders"]))
    for entry in findings.get("lists", ()):
        if entry["filename"] not in naming.LISTS:
            continue
        if entry["state"] in ("unreadable", "newer"):
            return ("that database cannot be read, so nothing was added to it"
                    if entry["filename"] == filename else
                    "one of the library's databases cannot be read, so these "
                    "files may belong to it")
        if entry["state"] == "absent-but-known" and entry["filename"] != filename:
            return ("the %s database has not synced to the library folder yet, so these "
                    "files may belong to it" % entry["label"])
    return ""


def _add_rows(findings: dict, filename: str, ids: list) -> dict:
    """`reattach` without the session check: rows added, their files moved home, ONE change."""
    reason = why_nothing_can_be_added(findings, filename)
    if reason:
        raise ValueError(reason)
    directory = findings["directory"]
    held = _guard(directory)
    reading = held.read(filename)
    if reading.verdict == guard.MISSING:
        raise ValueError("the database has not synced to the library folder yet, so nothing "
                         "was added to it - run Check Library again")
    if not reading.writable:
        debug.event("repair", "cannot add to a database it cannot read", file=filename)
        raise ValueError("that database cannot be read, so nothing was added to it")
    document = json.loads(json.dumps(reading.document or {}))
    by_file, unreadable = ids_claimed_by(directory)
    if [name for name in unreadable if name != filename]:
        raise ValueError("one of the library's databases cannot be read, so these "
                         "files may belong to it")
    rows = document.setdefault(ROWS, {})
    taken = set(rows)
    for other, claimed in by_file.items():
        if other != filename:
            taken |= claimed
    added, minted = [], []
    places = [path for _key, path in _folders_of(findings)]
    claimed = [one for one in ids if one in taken]    # a database took them since the check
    categories = document.setdefault("categories", {})
    for asset_id in [one for one in ids if one not in taken]:
        record = metadata_of(places, asset_id)
        if record is None:
            record = material.Material(
                name="Recovered %s" % asset_id[:8], cats=RECOVERED_CATEGORY, tags=[],
                fav=False, renderer="", mat_id=asset_id).get_as_dict()
            minted.append(asset_id)
        record["id"] = asset_id
        rows[asset_id] = record
        added.append(asset_id)
        for cat in record.get("categories") or []:    # a row with metadata brings its own back
            if cat and cat not in categories:
                categories[cat] = {"order": len(categories)}
    if minted and RECOVERED_CATEGORY not in categories:
        categories[RECOVERED_CATEGORY] = {"order": len(categories)}
    if added:
        change = held.change("")
        change.put(reading.ticket, document)
        _move_home(findings, held, change, filename, added)
        change.commit()
    debug.event("repair", "unlisted files added back to a database",
                file=filename, added=len(added), from_metadata=len(added) - len(minted),
                written_new=reading.verdict == guard.FRESH)
    return {"added": added, "path": held.path(filename), "minted": minted, "claimed": claimed}


def _move_home(findings: dict, held: guard.Guard, change, filename: str, ids: list) -> None:
    """The files of rows just added to `filename` into its section's folder, same change."""
    if filename not in naming.ASSET_SECTIONS:
        return
    home = os.path.join(findings["directory"], naming.SECTION_FOLDERS[filename])
    wanted = set(ids)
    for _key, folder in _folders_of(findings):
        if os.path.normpath(folder) == os.path.normpath(home):
            continue
        for name in _listdir(folder):
            if naming.asset_id(name, ASSET_SIDECARS + (".png",), "_cop") not in wanted:
                continue
            target = os.path.join(home, name)
            if os.path.lexists(target):
                continue
            change.take(held.inside(target), os.path.join(folder, name))


def _listdir(folder: str) -> list:
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def _state_of(findings: dict, filename: str) -> str:
    return next((entry["state"] for entry in findings.get("lists", ())
                 if entry["filename"] == filename), "")


def list_is_missing(findings: dict, filename: str) -> bool:
    """Whether adding back to `filename` writes the database new."""
    return _state_of(findings, filename) in _MISSING


def complete_pairs(findings: dict) -> list:
    """The unclaimed ids with a `.mat` and an `<id>.json` in ONE folder, in a stable order."""
    halves = {}
    for key in findings.get("asset_dirs", ()):
        for name in findings["unaccounted"].get(key, []):
            kind, asset_id = naming.classify(key + name)
            if kind == naming.RECORD or (kind == naming.UNKNOWN and metadata_stem(name)):
                kind, asset_id = naming.RECORD, asset_id or metadata_stem(name)
            if kind in (naming.ASSET, naming.RECORD) and asset_id:
                halves.setdefault((key, asset_id), set()).add(kind)
    return sorted({asset_id for (_key, asset_id), seen in halves.items()
                   if {naming.ASSET, naming.RECORD} <= seen})


def unsorted_pairs(findings: dict) -> list:
    """The complete pairs `materials_on_record` leaves: only the user can name their section."""
    named_already = {asset_id for asset_id, _record in materials_on_record(findings)}
    return [asset_id for asset_id in complete_pairs(findings) if asset_id not in named_already]


def reattachable_files(findings: dict) -> list:
    """Every file adding the unsorted pairs back accounts for, counted like the other button."""
    return _files_of(findings, unsorted_pairs(findings))


def _files_of(findings: dict, ids) -> list:
    """Every unaccounted file the assets in `ids` own: the builder, metadata and picture too."""
    ids = set(ids)
    covered = []
    for folder, names in findings["unaccounted"].items():
        extensions, tail = (ASSET_SIDECARS + (".png",), "_cop") \
            if folder in findings.get("asset_dirs", ()) else ((".png",), "_icon")
        for name in names:
            if ids and naming.asset_id(name, extensions, tail) in ids:
                covered.append(name)
    return covered


def target_of(findings: dict, filename: str) -> str:
    """The file a backup goes back over: a database in the library."""
    return os.path.join(findings["directory"], filename)


def put_back(findings: dict, filename: str, tier: str, guard_session: bool = True,
             **legacy) -> dict:
    """One backup restored through the guard, then for a Material or Node one the rows after."""
    if legacy.get("guard", guard_session):
        _refuse_a_houdini_that_holds_the_library(
            lambda phrase: RestoreRefused("Nothing was restored: %s." % phrase))
    held = _guard(findings["directory"])
    try:
        held.restore(filename, tier)
    except guard.Refused as exc:
        raise RestoreRefused("That backup cannot be read, so nothing was restored and the "
                             "database you have now is untouched.") from exc
    except OSError as exc:
        raise RestoreRefused("Nothing was restored: %s." % exc) from exc
    undo = next((entry for entry, _when in held.backups(filename)
                 if entry.endswith(guard.UNDO_TAIL)), "")
    debug.event("repair", "backup restored", file=filename, backup=tier, undo=undo)
    done = {"tier": tier, "undo": undo, "said": ""}
    if filename in naming.ASSET_SECTIONS:
        done.update(_after_a_put_back(findings["directory"], filename))
    return done


def undo_facts(findings: dict, filename: str, undo: str) -> dict:
    """What the undo copy a restore kept is, for the done message; {} for none."""
    if not undo:
        return {}
    held = _guard(findings["directory"])
    for entry, when in held.backups(filename):
        if entry == undo:
            return _backup_facts(held, filename, entry, when)
    return {}


def session_has_a_library_open() -> bool:
    """Whether anything in this session holds a library's databases, a closed panel too."""
    return bool(library_db.held_libraries())


def session_holds(directory: str) -> bool:
    """Whether this session holds the databases of the library in `directory`."""
    wanted = hostos.canonical_path_key(str(directory or ""))
    return any(key == wanted for key in library_db.held_libraries())


def settings_survey(preferences=None):
    """settings.json's state for the shelf tool; None when no settings folder is named."""
    folder = (hostos.config_root() if preferences is None
              else str(getattr(preferences, "path", "") or ""))
    if not folder:
        return None
    path = os.path.join(folder, _SETTINGS)
    state = "absent"
    if os.path.exists(path):
        state = "ok"
        try:
            with open(path, encoding="utf-8-sig") as handle:
                if not isinstance(json.load(handle), dict):
                    state = "unreadable"
        except (OSError, ValueError):
            state = "unreadable"
    return {"filename": _SETTINGS, "label": "Settings", "path": path, "ids": set(),
            "trace": "", "state": state, "snapshots": [],
            "info": {"path": path, "exists": state != "absent", "count": None,
                     "error": "" if state != "unreadable" else "unreadable"}}


def copies_naming_a_library(settings) -> list:
    """The saved settings copies that name a library folder: settings keep no backups."""
    return []
