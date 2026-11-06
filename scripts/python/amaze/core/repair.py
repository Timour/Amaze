"""Repair: never deletes, only reports and moves. ▸p/db-restore"""

import filecmp
import json
import os
import time

from amaze import branding
from amaze.core import database, debug, keyed_store, material, renderers
from amaze.core import library_files as naming
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


CAPTURES_DIR = naming.CAPTURE_FOLDER + "/"

SCRATCH_MIN_AGE = 60 * 60    # a younger scratch may be another session's live write

UNCATEGORISED = "Uncategorized"

_UNLISTABLE = (    # (folder, the kinds in it that belong to an asset by id)
    (naming.ASSET_FOLDER, (naming.ASSET, naming.BUILDER, naming.STAMP, naming.COMPANION)),
    (naming.RENDER_FOLDER, (naming.RENDER, naming.TILE_ICON)),
    (naming.CAPTURE_FOLDER, (naming.CAPTURE,)))


def survey(preferences_or_directory, asset_dir: str = "mat/",
           img_dir: str = "img/") -> dict:
    """Everything Check Library reports, from one walk; with preferences the Files section too."""
    preferences = None
    directory = preferences_or_directory
    if not isinstance(preferences_or_directory, (str, os.PathLike)):
        preferences = preferences_or_directory
        directory = str(preferences.dir or "")
        asset_dir, img_dir = preferences.asset_dir, preferences.img_dir
    directory = str(directory)
    from amaze.core import quarantine as holding
    holding.prune_quarantine(directory)
    listing = _walk(directory)
    root_names = listing["names"].get("")

    lists = []
    ids = set()
    complete = True
    for filename in DATABASES + side_tables():
        entry = _survey_one(directory, filename, root_names)
        lists.append(entry)
        ids |= entry["ids"]
        if entry["state"] in ("unreadable", "absent-but-known"):
            complete = False

    keys = {naming.ASSET_FOLDER: asset_dir, naming.RENDER_FOLDER: img_dir,
            naming.CAPTURE_FOLDER: CAPTURES_DIR}
    unaccounted = {}
    unreadable_folders = []
    for folder, kinds in _UNLISTABLE:
        names = listing["names"].get(folder)
        if names is None and (folder != naming.CAPTURE_FOLDER
                              or folder in listing["unreadable"]):
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
        "asset_dir": asset_dir,
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
    findings["shrunk"] = [
        (entry["filename"], entry["info"]["count"] or 0, newest)
        for entry, newest in ((entry, _newest_copy_holds(entry)) for entry in lists
                              if entry["filename"] in DATABASES
                              and entry["state"] in ("ok", "empty"))
        if newest is not None and database.held_much_less(entry["info"]["count"] or 0, newest)]
    findings["holding"] = holding.held(directory)
    return findings


def _walk(directory: str) -> dict:
    """The library in one walk: {names: {folder: {name: (kind, detail)}}, out_of_place, unreadable}."""
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
    return {"names": names, "out_of_place": out_of_place, "unreadable": unreadable}


def _stamps_of_unlisted_pairs(findings: dict, listing: dict) -> dict:
    """{id: record or None} for each unlisted pair or lone stamp: the only stamps a survey opens."""
    names = listing["names"].get(naming.ASSET_FOLDER) or {}
    folder = os.path.join(findings["directory"], findings["asset_dir"])
    return {asset_id: (read_stamp(os.path.join(folder, asset_id + STAMP_SUFFIX))
                       if asset_id + STAMP_SUFFIX in names else None)
            for asset_id in _ids_with_a_stamp(findings)}


def _listed_rows_checked(lists: list, listing: dict) -> dict:
    """Per Material and Node list: rows whose files are gone, renders missing, no category."""
    assets = listing["names"].get(naming.ASSET_FOLDER)
    renders = listing["names"].get(naming.RENDER_FOLDER)
    missing_files, missing_renders, uncategorised = {}, {}, {}
    for entry in lists:
        filename = entry["filename"]
        if filename not in database.ASSET_FILE_OWNERS:
            continue
        gone, unrendered, loose = [], [], []
        for row in entry.get("rows", ()):
            asset_id = database.row_id(row)
            named = (asset_id, str(row.get("name") or asset_id))
            if not _categories_of(row):
                loose.append(named)
            if assets is None or not material.is_safe_asset_id(asset_id):
                continue
            if asset_id + ".mat" not in assets or asset_id + ".interface" not in assets:
                gone.append(named)
            elif (renders is not None and asset_id + ".png" not in renders
                  and (filename == "library.json"
                       or renderers.can_hold_a_render(row.get("renderer")))):
                unrendered.append(named)
        missing_files[filename] = gone
        missing_renders[filename] = unrendered
        uncategorised[filename] = loose
    return {"missing_files": missing_files, "missing_renders": missing_renders,
            "uncategorised": uncategorised}


def _categories_of(row: dict) -> list:
    """A row's categories as a list, blanks dropped; a legacy comma string is split."""
    found = row.get("categories")
    if isinstance(found, str):
        found = found.split(",") if found else []
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
        elif kind == naming.PRE_ADOPT_COPY:
            leftovers.append((relative, kind, size, when))
        elif kind == naming.DUPLICATE:
            why = _why_a_duplicate_stays(directory, relative, detail, listing)
            if why:
                held_back.append((relative, detail, size, when, why))
            else:
                leftovers.append((relative, kind, size, when))
        elif detail == "folder":
            files, total = _folder_size(os.path.join(directory, relative))
            unknown_folders.append((relative, files, total, when))
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
    for here, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(here, name))
                count += 1
            except OSError:
                pass
    return count, total


def _files_section(preferences) -> dict:
    """The Files section's folders not on this computer, on a drive not connected, and stars gone."""
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
        if not os.path.isdir(os.path.dirname(path)):    # its folder is not here, set aside or unsynced
            continue
        found["dead_stars"].append(path)
    return found


def _newest_copy_holds(entry: dict):
    """What the newest saved copy beside a list holds, the tier order `database` reads, or None."""
    copies = dict(entry["snapshots"])
    for tier in restore_lib.TIERS:
        snap = copies.get(tier)
        if snap is not None:
            return None if snap["error"] else snap["count"]
    return None


def _snapshots_among(path: str, names: dict) -> list:
    """`restore.snapshots` answered from the folder's listing: undo copies newest first, then tiers."""
    base = os.path.basename(path)
    folder = os.path.dirname(path)
    prefix = base + "." + restore_lib.UNDO_TIER
    found = [(name[len(base) + 1:], os.path.join(folder, name))
             for name in sorted((name for name in names if name.startswith(prefix)),
                                reverse=True)]
    return found + [(tier, path + "." + tier) for tier in restore_lib.TIERS
                    if base + "." + tier in names]


def _survey_one(directory: str, filename: str, names=None) -> dict:
    """One list: its state, what it holds, and what copies sit beside it; `names` lists the folder."""
    path = os.path.join(directory, filename)
    facts, document = restore_lib.surveyed(path)    # ONE parse for both - the state below reads `facts`, the ids read `document`
    copies = (restore_lib.snapshots(path) if names is None
              else _snapshots_among(path, names))
    entry = {
        "filename": filename,
        "label": database.section_label(filename),
        "path": path,
        "info": facts,
        "ids": set(),
        "rows": [],
        "trace": "",
        "snapshots": [(tier, restore_lib.info(snap)) for tier, snap in copies],
    }
    if not facts["exists"]:
        entry["trace"] = database.absent_but_known(directory, filename, names)
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
            entry["rows"].append(row)
    entry["state"] = "empty" if not facts["count"] else "ok"
    return entry


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


def rebuild_from_stamps(directory: str, asset_dir: str = "mat/",
                        index_filename: str = "library.json") -> dict:
    """One index rebuilt from stamps; never write it while `unreadable` is set. ▸p/clean-library-sweep"""
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


def _copies_by_what_they_hold(target: str) -> list:
    """The tiers of saved copies that parse, newest first; those holding nothing after the rest."""
    found = []
    for order, tier in enumerate(restore_lib.TIERS):
        source = "%s.%s" % (target, tier)
        document, error = restore_lib.read_document(source)
        if error or database.wrong_shape(document):
            continue
        try:
            when = os.path.getmtime(source)
        except OSError:
            continue
        holds = bool(document.get("assets"))
        found.append((not holds, -when, order, tier))
    return [tier for *_key, tier in sorted(found)]


def repair_index(directory: str, asset_dir: str = "mat/", guard: bool = True) -> tuple:
    """The newest copy holding materials, else the newest that parses, else a rebuild; (ok, how)."""
    if guard:
        _refuse_a_houdini_that_holds_the_library()
    target = os.path.join(directory, "library.json")
    for tier in _copies_by_what_they_hold(target):
        try:
            outcome = restore_lib.put_back(target, tier)
        except restore_lib.RestoreRefused as refusal:
            debug.event("repair", "snapshot refused for the rebuild",
                        tier=tier, error=str(refusal))
            continue
        debug.event("repair", "index restored from a snapshot",
                    tier=tier, undo=outcome.get("undo", ""))
        return True, _after_a_put_back(directory, asset_dir, "library.json",
                                       "the newest saved copy was put back")["said"]
    document = rebuild_from_stamps(directory, asset_dir)
    if document["unreadable"]:  # an unparsed list claims nothing ▸p/clean-library-sweep
        debug.event("repair", "rebuild refused - a sibling list is "
                    "unreadable", files=document["unreadable"])
        return False, ("%s cannot be read, so a rebuild cannot tell its "
                       "assets from this list's"
                       % wording.and_list(document["unreadable"]))
    if not document["assets"]:
        return False, ("no saved copy parses and no recovery stamps "
                       "were found")
    try:
        hostos.preserve_unreadable(target, why="library index")  # the only copy kept of an unparsable file ▸p/db-restore
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


def _rows_against_their_stamps(target: str, folder: str) -> tuple:
    """(listed rows that took their stamp's record, names of rows with no .mat and no stamp)."""
    document, error = restore_lib.read_document(target)
    if error or database.wrong_shape(document):
        return 0, []
    rows = document.get("assets") or []
    categories = document.setdefault("categories", ["_All"])
    taken, gone = 0, []
    for index, row in enumerate(rows):
        asset_id = database.row_id(row) if isinstance(row, dict) else ""
        if not material.is_safe_asset_id(asset_id):
            continue
        stamp = os.path.join(folder, asset_id + STAMP_SUFFIX)
        if not os.path.exists(stamp):
            if not os.path.exists(os.path.join(folder, asset_id + ".mat")):
                gone.append(str(row.get("name") or asset_id))    # listed, never dropped
            continue
        record = read_stamp(stamp)    # written only after its list landed: never older than a copy
        if record is None or str(record.get("id", asset_id)) != asset_id:
            continue
        record["id"] = row.get("id", asset_id)
        if record != row:
            rows[index] = record
            taken += 1
            for cat in record.get("categories") or []:
                if cat and cat not in categories:
                    categories.append(cat)    # a newer record brings its category back too
    if taken:
        try:
            _write_json(target, document)
        except OSError as exc:    # the copy is back either way
            debug.event("repair", "newer records not taken", error=str(exc))
            taken = 0
    debug.event("repair", "rows checked against their stamps", taken=taken, gone=len(gone))
    return taken, sorted(gone)


def _after_a_put_back(directory: str, asset_dir: str, filename: str, how=None) -> dict:
    """A Material or Node list just put back: newer stamps taken, rows saved after it added back."""
    target = os.path.join(directory, filename)
    refreshed, gone = _rows_against_their_stamps(target, os.path.join(directory, asset_dir))
    newer = _rows_newer_than_the_copy(directory, asset_dir, filename)
    return {"refreshed": refreshed, "newer": newer, "gone": gone,
            "said": _put_back_sentence(refreshed, newer, gone, filename, how)}


def _put_back_sentence(refreshed: int, newer: int, gone: list,
                       filename: str = "library.json", how=None) -> str:
    """`how`, then what came after the copy and the rows whose files are gone; no `how`, a sentence."""
    def counted(count, after):
        return "the %d %s %s after it %s" % (
            count, database.section_noun(filename, count), after,
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
        said += "%s%s %s listed in it, but %s files are gone" % (
            " - " if said else "",
            wording.and_list(gone[:8]) + (" and %d more" % (len(gone) - 8) if len(gone) > 8 else ""),
            "is" if len(gone) == 1 else "are", "its" if len(gone) == 1 else "their")
    if how is None and said:
        said = "Also, " + said + "."
    return said


def _rows_newer_than_the_copy(directory: str, asset_dir: str, filename: str) -> int:
    """The rows a put-back copy predates, added from their stamps; how many came back."""
    findings = survey(directory, asset_dir)
    ids = [asset_id for asset_id, _record in on_record(findings, filename)]
    if not ids or why_nothing_can_be_added(findings, filename):
        return 0
    try:
        return len(_add_rows(findings, filename, ids)["added"])
    except (OSError, ValueError) as exc:    # the copy is back either way; these stay for Repair
        debug.event("repair", "rows newer than the copy not added",
                    file=filename, error=str(exc))
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

    troubled = [entry for entry in findings["lists"] if entry["state"] in _TROUBLE_LINES]
    problems = []
    if troubled:
        problems.append("\n".join(_TROUBLE_LINES[entry["state"]] % entry["label"]
                                  for entry in troubled))
    if any(entry["state"] == "empty" for entry in troubled):
        problems.append(
            "A list that holds nothing looks the same whether nothing was "
            "ever saved there or it failed to load this time, so Amaze "
            "will not decide on its own which it is.")
    well = [_lists_line(findings["lists"], bool(troubled))]

    total = unaccounted_total(findings)
    unchecked = [entry["label"] for entry in troubled
                 if entry["state"] in ("unreadable", "absent-but-known")]
    if findings["unreadable_folders"]:
        problems.append(
            "Amaze could not look inside the %s, so it cannot say whether "
            "anything in there is listed by no section. Nothing will be "
            "moved while that is true."
            % _and_folders(findings["unreadable_folders"]))
    elif total and findings["complete"]:
        held = ["None of them will be moved aside while a list that may own them holds "
                "nothing: put a saved copy of it back, or add them to a section."
                ] if why_unlisted_stay(findings) else []
        problems.append(" ".join(["No section lists %s. Either they belong to something "
                                  "whose list was lost, or nothing needs them any more."
                                  % files_by_folder(findings)]
                                 + _what_can_be_added_back(findings) + held))
    elif total:
        problems.append(" ".join([
            "No section lists %s. Amaze could not check the %s list either, "
            "so some of those files may be its. Nothing will be moved "
            "while that is true."
            % (files_by_folder(findings), wording.and_list(unchecked))]
            + _what_can_be_added_back(findings)))
    elif findings["unaccounted"]:
        well.append("Every file in %s belongs to a %s on the lists."
                    % (wording.and_list(["`%s`" % folder for folder in findings["unaccounted"]]),
                       " or ".join(database.section_noun(filename, 1)
                                   for filename in database.ASSET_FILE_OWNERS)))

    said, fine = _check_lines(findings)
    problems.extend(said)
    well.extend(fine)
    problems.extend(_snapshot_line(entry) for entry in troubled)

    for line in problems + [line for line in well if line]:
        lines.extend([line, ""])
    if "holding" in findings:
        lines.append(_holding_line(findings["holding"]))
    return lines


_TROUBLE_LINES = {    # a list's state, and the line it gets when it is in trouble
    "empty": "%s: the list is there and holds nothing.",
    "unreadable": "%s: the list is there and Amaze cannot read it. It has not been changed.",
    "absent-but-known": (
        "%s: there is no list for it in the library folder, though Amaze can see there "
        "was one here before. If this folder syncs, it may still be on its way - give it "
        "a minute and run Check Library again."),
}


def _lists_line(lists: list, others: bool) -> str:
    """One line for every list that reads fine, each count in its own noun; empty when none does."""
    held = [_counted(entry["info"]["count"] or 0, entry["filename"])
            for entry in lists if entry["state"] == "ok"]
    unsaved = [entry["label"] for entry in lists if entry["state"] == "absent"]
    said = []
    if held:
        said.append("%s: %s." % ("The other lists read fine" if others
                                 else "Every list reads fine", wording.and_list(held)))
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
    return "%d %s" % (count, database.section_noun(filename, count))


def _per_section(found: dict) -> str:
    """`3 materials and 1 node`, a count per list in its own noun, empty lists left out."""
    return wording.and_list([_counted(len(rows), filename)
                             for filename, rows in found.items() if rows])


def _every_section() -> str:
    """`material and node`: the nouns of the lists that own asset files."""
    return wording.and_list([database.section_noun(filename, 1)
                             for filename in database.ASSET_FILE_OWNERS])


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
    """(problems, all-well lines) for what only a full survey asks; a question with no problem says so."""
    if "leftovers" not in findings:
        return [], []
    said, well = [], []
    missing = findings.get("missing_files") or {}
    for filename, rows in missing.items():
        if rows:
            said.append("%s %s on the %s list, but %s files are missing: %s. A file "
                        "that has not finished syncing looks the same as one that is gone."
                        % (_counted(len(rows), filename), "is" if len(rows) == 1 else "are",
                           database.section_label(filename),
                           "its" if len(rows) == 1 else "their",
                           _named(name for _id, name in rows)))
    renders = findings.get("missing_renders") or {}
    if any(renders.values()):
        total = sum(len(rows) for rows in renders.values())
        said.append("No thumbnail image yet for %s - select %s in Amaze and use Update "
                    "Render when convenient, since a render takes time."
                    % (_per_section(renders), "it" if total == 1 else "them"))
    if not any(missing.values()) and not any(renders.values()):
        well.append("Every %s on the lists has its files, and every one that can have a "
                    "render has one." % _every_section())
    elif not any(missing.values()):
        well.append("Every %s on the lists has its files." % _every_section())
    gone = _leftover_lines(findings) + _unknown_lines(findings)
    said.extend(gone)
    if not gone:
        well.append("Nothing is left over from a save that did not finish, and every file "
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
        said.append("Your %s list holds %s, but its newest saved copy holds %s. If you "
                    "did not remove them yourself, that copy can be put back."
                    % (database.section_label(filename), _counted(holds, filename),
                       _counted(newest, filename)))
    return said, well


_LEFTOVER_KINDS = (    # (kind, one, more)
    (naming.SCRATCH, "file left by a save that did not finish",
     "files left by saves that did not finish"),
    (naming.PRE_ADOPT_COPY, "backup kept from before an earlier texture update",
     "backups kept from before an earlier texture update"),
    (naming.DUPLICATE, "second copy a sync service made of a file still here",
     "second copies a sync service made of files still here"),
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
                    "aside takes them out of the library: %s."
                    % (files(len(leftovers)), wording.and_list(parts),
                       _named("`%s`" % entry[0] for entry in leftovers)))
    for relative, original, size, when, why in findings.get("held_back") or []:
        if why == "alone":
            said.append("`%s` looks like a second copy of `%s`, which is not here, so "
                        "it is left where it is." % (relative, original))
        else:
            said.append("`%s` is a second version of `%s`, from %s (%s), and the two "
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
                       "its" if len(dead) == 1 else "their", "\n  ".join(sorted(dead))))
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
            "its" if len(stars) == 1 else "their", "\n  ".join(sorted(stars))))
    return said


def _holding_line(held: dict) -> str:
    """The holding folder's line: what it holds, when the oldest day goes, and where it is."""
    if not held["files"]:
        return ("Amaze's holding folder on this computer is empty. Anything moved "
                "aside goes there and is kept for %d days: %s"
                % (_quarantine_days(), held["path"]))
    first = next((expires for _day_name, expires, _n, _b in held["days"] if expires), "")
    return ("Amaze's holding folder on this computer holds %s (%s), moved aside on "
            "%s. Each day's files are kept for %d days%s: %s"
            % (files(held["files"]), _size(held["bytes"]),
               "1 day" if len(held["days"]) == 1 else "%d days" % len(held["days"]),
               _quarantine_days(),
               ", and the oldest go on %s" % first if first else "", held["path"]))


def _quarantine_days() -> int:
    from amaze.core import quarantine as holding
    return holding.QUARANTINE_DAYS


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
    """`3 materials and 1 node`: the rows with no category, each list in its own noun."""
    return _per_section(findings.get("uncategorised") or {})


def _and_folders(folders: list) -> str:
    return wording.and_list(["%s folder" % _folder_name(folder)
                      for folder in folders])


def files_by_folder(findings: dict) -> str:
    """Folder by folder, never one total, each folder's names while there are few."""
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
    spared = len(_files_of(findings, stamped_unlisted(findings)))
    if spared:
        one = spared == 1
        said.append("Moving files aside leaves %s where %s: the name and category of what "
                    "%s to are saved beside %s, so %s can still be put back."
                    % (files(spared), "it is" if one else "they are",
                       "it belongs" if one else "they belong", "it" if one else "them",
                       "it" if one else "they"))
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
    "this Houdini has already read the library, so open Amaze and use Library ▸ Check Library…")


def _refuse_a_houdini_that_holds_the_library(refusal=ValueError) -> None:
    """Every action enforces this for itself; the button logic is a courtesy."""
    if session_has_a_library_open():
        raise refusal(_SESSION_HOLDS_THE_LIBRARY)


def movable(findings: dict) -> dict:
    """`findings` less the files of each unlisted pair whose stamp reads: those can be put back."""
    kept = set(_files_of(findings, stamped_unlisted(findings)))
    if not kept:
        return findings
    return dict(findings, unaccounted={
        folder: [name for name in names if name not in kept]
        for folder, names in findings["unaccounted"].items()})


def files_to_move_aside(findings: dict) -> int:
    """Move Files Aside's count: the unlisted files `movable` leaves, and the leftovers."""
    unlisted = 0 if why_unlisted_stay(findings) else unaccounted_total(movable(findings))
    return unlisted + len(findings.get("leftovers") or ())


def why_unlisted_stay(findings: dict) -> str:
    """Empty when unlisted files may be moved aside; else why a list may still own them."""
    if not findings.get("complete"):
        return "one of the library's lists cannot be read, so these files may belong to it"
    empty = [entry["label"] for entry in findings.get("lists", ())
             if entry["state"] == "empty" and entry["filename"] in database.ASSET_FILE_OWNERS]
    if empty and findings["unaccounted"].get(findings.get("asset_dir")):
        return ("the %s list holds nothing, so these files may belong to it"
                % wording.and_list(empty))
    return ""


def unknown_to_move_aside(findings: dict) -> int:
    """Move Unknown Files Aside's count: each unknown file, and each unknown folder as one."""
    return len(findings.get("unknown") or ()) + len(findings.get("unknown_folders") or ())


MOVABLE = ("unlisted", "leftovers", "unknown")


def move_aside(findings: dict, what, guard: bool = True) -> dict:
    """Move into the holding folder what `what` names, one of MOVABLE or several; never deletes."""
    if guard:
        _refuse_a_houdini_that_holds_the_library()
    asked = (what,) if isinstance(what, str) else tuple(what)
    for one in asked:
        if one not in MOVABLE:
            raise ValueError("there is nothing called %r to move aside" % one)
    directory = findings["directory"]
    held = why_unlisted_stay(findings) if "unlisted" in asked else ""
    if held:
        raise ValueError(held)
    from amaze.core import quarantine as holding
    root = holding.quarantine_folder(directory)
    moved, failed, record = [], [], []

    def take(relative, shown):
        source = os.path.join(directory, *naming.split(relative))
        landed = holding.quarantine_file(directory, source) if os.path.lexists(source) else ""
        (moved if landed else failed).append(shown)
        if landed:
            record.append([source, landed])

    if "unlisted" in asked:
        for folder, names in movable(findings)["unaccounted"].items():
            for name in names:
                take(folder.rstrip("/\\") + "/" + name, name)
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
    holding.prune_quarantine(directory)
    debug.event("repair", "files moved aside", what=list(asked), folder=root,
                moved=len(moved), failed=len(failed), files=record,
                failed_files=failed)
    return {"folder": root, "moved": moved, "failed": failed}


def set_aside_folders(findings: dict, guard: bool = True) -> list:
    """Drop the Files section's pointer to each folder not on this computer; its files are untouched."""
    if guard:
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


def drop_dead_stars(findings: dict, guard: bool = True) -> list:
    """Unstar each starred file gone from a folder that is still here, in one write."""
    if guard:
        _refuse_a_houdini_that_holds_the_library()
    from amaze.core import locations
    gone = [path for path in findings.get("dead_stars", ())
            if not os.path.exists(path) and os.path.isdir(os.path.dirname(path))]
    if gone:
        locations.set_favourites(findings["preferences"], {path: False for path in gone})
    debug.event("repair", "stars on files that are gone dropped", files=gone)
    return gone


def rescue_uncategorised(findings: dict, guard: bool = True) -> dict:
    """Put each row with no category in Uncategorized, list by list; {filename: how many}."""
    if guard:
        _refuse_a_houdini_that_holds_the_library()
    done = {}
    for filename, rows in findings.get("uncategorised", {}).items():
        wanted = {asset_id for asset_id, _name in rows}
        if not wanted:
            continue
        path = os.path.join(findings["directory"], filename)
        document, error = restore_lib.read_document(path)
        if error or database.wrong_shape(document):
            raise ValueError("that list cannot be read, so nothing was changed in it")
        count = 0
        for row in document.get("assets") or []:
            if (isinstance(row, dict) and database.row_id(row) in wanted
                    and not _categories_of(row)):
                row["categories"] = [UNCATEGORISED]
                count += 1
        if not count:
            continue
        categories = document.setdefault("categories", ["_All"])
        if UNCATEGORISED not in categories:
            categories.append(UNCATEGORISED)
        hostos.snapshot_before_write(path)
        _write_json(path, document)
        done[filename] = count
    debug.event("repair", "rows with no category put in one", lists=done)
    return done


def reattach(findings: dict, filename: str, only=None, guard: bool = True) -> dict:
    """Add the unclaimed pairs, or the ids in `only`, to `filename` from their stamps ▸p/recovery-stamp"""
    if guard:
        _refuse_a_houdini_that_holds_the_library()
    return _add_rows(findings, filename,
                     complete_pairs(findings) if only is None else list(only))


def add_materials_back(findings: dict, guard: bool = True) -> dict:
    """Put every material `materials_on_record` finds on the Material list; raises as `reattach`."""
    if guard:
        _refuse_a_houdini_that_holds_the_library()
    return _add_rows(findings, "library.json",
                     [asset_id for asset_id, _record in materials_on_record(findings)])


def materials_on_record(findings: dict) -> list:
    """`on_record` for the Material list: what Add Back puts there."""
    return on_record(findings, "library.json")


def on_record(findings: dict, filename: str) -> list:
    """The unlisted pairs whose readable stamp belongs on `filename`, as `(id, record)`, by id."""
    if "asset_dir" not in findings:
        return []
    stamps = _stamps(findings)
    return [(asset_id, stamps[asset_id]) for asset_id in complete_pairs(findings)
            if stamps.get(asset_id) is not None and _list_of(stamps[asset_id]) == filename]


def _list_of(record: dict) -> str:
    """The list a stamp's record goes on: a renderer Amaze knows is a material's, any other a node's."""
    renderer = record.get("renderer")
    if renderers.get(renderer):
        return "library.json"
    return "cops.json" if renderer else ""


def stamped_unlisted(findings: dict) -> list:
    """The unlisted ids whose stamp reads, a pair or a stamp alone: what can still be put back."""
    if "asset_dir" not in findings:
        return []
    stamps = _stamps(findings)
    return sorted(asset_id for asset_id, record in stamps.items() if record is not None)


def _ids_with_a_stamp(findings: dict) -> list:
    """The unlisted complete pairs, and the ids whose unlisted stamp sits alone, by id."""
    stamps = [name[: -len(STAMP_SUFFIX)]
              for name in findings["unaccounted"].get(findings.get("asset_dir"), [])
              if name.endswith(STAMP_SUFFIX)]
    return sorted(set(complete_pairs(findings)) | {one for one in stamps
                                                   if material.is_safe_asset_id(one)})


def _stamps(findings: dict) -> dict:
    """The stamps of the unlisted pairs, read once per survey; a hand-made findings reads them here."""
    if "stamps" not in findings:
        folder = os.path.join(findings["directory"], findings["asset_dir"])
        findings["stamps"] = {}
        for asset_id in _ids_with_a_stamp(findings):
            path = os.path.join(folder, asset_id + STAMP_SUFFIX)
            findings["stamps"][asset_id] = read_stamp(path) if os.path.exists(path) else None
    return findings["stamps"]


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
        if entry["state"] == "absent-but-known" and entry["filename"] != filename:
            return ("the %s list has not arrived in the library folder yet, so these "
                    "files may belong to it" % entry["label"])
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
                         "Amaze looked, so nothing was added to it - run "
                         "Check Library again")
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
    """Scratch-and-promote without the snapshot: a recovery tool keeps the copies."""
    with hostos.scratch_beside(path, suffix=".repairing") as scratch:
        with open(scratch, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)


def target_of(findings: dict, filename: str) -> str:
    """The file a saved copy goes back over: settings.json in its own folder, a list in the library."""
    settings = findings.get("settings") or {}
    if filename == settings.get("filename"):
        return settings["path"]
    return os.path.join(findings["directory"], filename)


def put_back(findings: dict, filename: str, tier: str, guard: bool = True) -> dict:
    """One saved copy back, then for a Material or Node list what `repair_index` does after; `said`."""
    if guard:
        _refuse_a_houdini_that_holds_the_library(
            lambda phrase: restore_lib.RestoreRefused(
                "Nothing was put back: %s." % phrase))
    target = target_of(findings, filename)
    done = restore_lib.put_back(target, tier, allow_loss=True)
    debug.event("repair", "saved copy put back", file=filename, tier=tier,
                undo=done["undo"])
    done["said"] = ""
    if (filename in database.ASSET_FILE_OWNERS
            and target == os.path.join(findings["directory"], filename)):
        done.update(_after_a_put_back(findings["directory"],
                                      findings.get("asset_dir") or "mat/", filename))
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
