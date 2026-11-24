"""Check Library: a library surveyed, the report it reads as, and its fixes. ▸docs/requirements"""

import filecmp
import json
import os
import time

from amaze import messages
from amaze.core import asset_record, debug, documents, guard, library_db, library_files
from amaze.core import layout_conversion, library_policy, locations, material, renderers
from amaze.helpers import hostos, wording

SCRATCH_MIN_AGE = 60 * 60    # a younger scratch may be another session's live write
UNCATEGORIZED, RECOVERED = "Uncategorized", "Recovered"
LISTS, ASSET_SECTIONS = library_files.LISTS, library_files.ASSET_SECTIONS
TROUBLE = ("unreadable", "missing", "newer", "held")
FOUND, UNCHECKED, CLEAN = "found", "unchecked", "clean"    # a light's state, the weightiest first
_STATES = {guard.FINE: "ok", guard.FRESH: "absent", guard.CORRUPT: "unreadable",
           guard.MISSING: "missing", guard.NEWER: "newer", guard.HELD: "held"}


class Refused(Exception):
    """A fix that may not run now; the message says why."""


def held_here(library_dir: str) -> bool:
    """Whether this Houdini has the library open in a panel: a fix then runs only from there."""
    return hostos.canonical_path_key(str(library_dir or "")) in library_db.held_libraries()



def survey(library_dir: str, preferences=None) -> dict:
    """What the library holds and what is wrong with it; reading it changes nothing."""
    library_dir = str(library_dir)
    held = guard.Guard(library_dir)
    databases = [_database(held, reading) for reading in held.health()]
    rows = {entry["name"]: entry["rows"] for entry in databases if entry["name"] in LISTS}
    ids = set().union(*(set(found) for found in rows.values()))
    listing, out_of_place, unreadable = _walk(library_dir)
    findings = {"directory": library_dir, "databases": databases, "unreadable_folders": unreadable,
                "missing_files": {}, "no_picture": {}, "no_category": {}, "unlisted": [],
                "orphans": _orphan_versions(library_dir, listing), "trash": held.trash_held()}
    for section in LISTS:
        if section in ASSET_SECTIONS:
            _assets(findings, section, rows.get(section, {}), listing, ids)
        else:
            _inline_folders(findings, section, listing, ids)
    findings.update(_out_of_place(library_dir, out_of_place))
    findings.update(_files_section(preferences))
    findings["holding_back"] = _holding_back(findings)
    return findings


def _database(held, reading) -> dict:
    kind = guard.DATABASES[reading.name]
    document = reading.document if isinstance(reading.document, dict) else None
    count = (len(document.get(kind.counted) or {})
             if document is not None and kind.counted else None)
    state = _STATES.get(reading.verdict, "unreadable")
    if state == "ok" and reading.name in LISTS and not count:
        state = "empty"
    return {"name": reading.name, "state": state, "count": count, "why": reading.why,
            "backups": held.backups(reading.name), "shrunk": reading.shrunk,
            "rows": dict((document or {}).get("assets") or {}) if reading.name in LISTS else {}}


def _walk(library_dir: str) -> tuple:
    """({folder: {name: (kind, detail)}}, the out-of-place entries, the folders not listed)."""
    listing, out, unreadable = {}, [], []
    for relative, kind, detail, info in library_files.walk(library_dir):
        if kind == library_files.UNREADABLE:
            unreadable.append(relative)
            continue
        parts = library_files.split(relative)
        listing.setdefault(library_files.join(parts[:-1]), {})[parts[-1]] = (kind, detail)
        if kind in library_files.OUT_OF_PLACE:
            out.append((relative, kind, detail, info))
    return listing, out, unreadable


def _asset_folders(listing: dict, section: str) -> dict:
    """{id: folder name} of every asset folder of a section."""
    top = library_files.SECTION_FOLDERS[section]
    return {library_files.folder_id(name): name for name, (kind, _detail)
            in (listing.get(top) or {}).items()
            if kind == library_files.FOLDER and library_files.folder_id(name)}


def _assets(findings: dict, section: str, rows: dict, listing: dict, ids: set) -> None:
    """A section's rows without files, picture or category, and its folders no database lists."""
    top = library_files.SECTION_FOLDERS[section]
    folders = _asset_folders(listing, section)
    missing, unpictured, loose = [], [], []
    for asset_id, row in sorted(rows.items()):
        row = row if isinstance(row, dict) else {}
        named = (asset_id, str(row.get("name") or asset_id))
        if not material.category_names(row.get("categories")):
            loose.append(named)
        if not library_files.is_safe_id(asset_id):
            continue
        here = listing.get(top + "/" + folders[asset_id], {}) if asset_id in folders else {}
        if asset_id + ".mat" not in here or asset_id + library_files.RECORD_SUFFIX not in here:
            missing.append(named)
        elif asset_id + library_files.PICTURE_SUFFIX not in here and (
                section == library_files.MATERIALS or renderers.can_hold_a_render(row.get("renderer"))):
            unpictured.append(named)
    findings["missing_files"][section] = missing
    findings["no_picture"][section] = unpictured
    findings["no_category"][section] = loose
    for asset_id, name in sorted(folders.items()):
        if asset_id not in ids:
            record = asset_record.read(os.path.join(
                findings["directory"], top, name, asset_id + library_files.RECORD_SUFFIX))
            findings["unlisted"].append({"section": section, "id": asset_id,
                                         "folder": top + "/" + name,
                                         "record": record[asset_record.METADATA] or None})


def _inline_folders(findings: dict, section: str, listing: dict, ids: set) -> None:
    """Code's and Colors' folders no database lists; with no record, none can be recovered."""
    top = library_files.SECTION_FOLDERS[section]
    for asset_id, name in sorted(_asset_folders(listing, section).items()):
        if asset_id not in ids:
            findings["unlisted"].append({"section": section, "id": asset_id,
                                         "folder": top + "/" + name, "record": None})


def _orphan_versions(library_dir: str, listing: dict) -> list:
    """Each version file its folder's ledger does not list."""
    found = []
    suffixes = library_files.VERSION_SUFFIXES
    for folder, names in listing.items():
        parts = library_files.split(folder)
        if len(parts) != 3:
            continue
        if not (library_files.owns_assets(parts[0]) and parts[2] == library_files.VERSIONS):
            continue
        owner = library_files.folder_id(parts[1])
        numbers = _ledger_numbers(os.path.join(library_dir, *parts))
        if owner and numbers is not None:
            found += ["%s/%s" % (folder, name) for name, (kind, _detail) in sorted(names.items())
                      if kind == library_files.VERSION
                      and library_files.version_number(name, owner, suffixes) not in numbers]
    return found


def _ledger_numbers(folder: str):
    """The version numbers a ledger lists; empty without one, None when it cannot be read."""
    path = os.path.join(folder, library_files.LEDGER)
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return {int(row.get("n", 0)) for row in json.load(handle).get("versions")}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _out_of_place(library_dir: str, out: list) -> dict:
    """Leftovers to trash, conflict copies kept, and what matches no name Amaze writes."""
    now, found = time.time(), {"leftovers": [], "conflicts": [], "unknown": []}
    for relative, kind, detail, info in out:
        when = info.st_mtime if info is not None else now
        if kind == library_files.SCRATCH:
            if now - when >= SCRATCH_MIN_AGE:
                found["leftovers"].append(relative)
        elif kind == library_files.DUPLICATE:
            why = _copy_kept(library_dir, relative, detail)
            if why:
                found["conflicts"].append((relative, why))
            else:
                found["leftovers"].append(relative)
        else:
            found["unknown"].append(relative)
    return found


def _copy_kept(library_dir: str, copy: str, original: str) -> str:
    """Why a sync service's copy stays: `alone` or `differs`; "" when it is a leftover."""
    first = os.path.join(library_dir, *library_files.split(original))
    if not os.path.isfile(first):
        return "alone"
    if library_files.classify(original)[0] in library_files.COPIES:
        return ""
    try:
        same = filecmp.cmp(first, os.path.join(library_dir, *library_files.split(copy)),
                           shallow=False)
    except OSError:
        same = False
    return "" if same else "differs"


def _files_section(preferences) -> dict:
    """Locations whose folder is gone or on a drive not connected, and favorites of gone files."""
    found = {"files_checked": False, "locations_gone": [], "locations_unreachable": [],
             "favorites_gone": []}
    if preferences is None or not locations.ready(preferences):
        return found
    found["files_checked"] = True
    for path in locations.registered_paths(preferences):
        if not os.path.isdir(path):
            found["locations_unreachable" if hostos.volume_unreachable(path)
                  else "locations_gone"].append(path)
    found["favorites_gone"] = [path for path in locations.favourite_paths(preferences)
                               if not os.path.exists(path)
                               and os.path.isdir(os.path.dirname(path))]
    return found


def _holding_back(findings: dict) -> str:
    """Why nothing may be trashed: a folder or a database could not be read, or holds nothing."""
    if layout_conversion.needs_conversion(findings["directory"]):
        return messages.CHECK_NEEDS_CONVERSION
    if findings["unreadable_folders"]:
        return messages.CHECK_FOLDER_UNREAD % findings["unreadable_folders"][0]
    for entry in findings["databases"]:
        label = library_files.section_label(entry["name"])
        if entry["name"] in LISTS and entry["state"] in TROUBLE:
            return _state_line(entry["state"], label)
        if entry["state"] == "empty" and any(one["section"] == entry["name"]
                                             for one in findings["unlisted"]):
            return messages.CHECK_DATABASE_EMPTY_KEEPS % label
    return ""



def _state_line(state: str, label: str) -> str:
    """The sentence for a database that cannot be used: unreadable, missing, newer or held."""
    if state == "missing":
        return messages.CHECK_DATABASE_MISSING % label
    if state == "newer":
        return messages.CHECK_DATABASE_NEWER % label
    if state == "held":
        return messages.CHECK_DATABASE_IN_USE % label
    return messages.CHECK_DATABASE_CORRUPT % label


def report_lines(findings: dict) -> list:
    """What the check found, one sentence each, the weightiest first; [] when nothing."""
    lines = []
    for entry in findings["databases"]:
        label = library_files.section_label(entry["name"])
        if entry["state"] in TROUBLE:
            backups = len(entry["backups"])
            lines.append(_state_line(entry["state"], label) + " " + (
                messages.CHECK_BACKUPS % wording.count(backups, "backup")
                if backups else messages.CHECK_NO_BACKUP))
        elif entry["shrunk"]:
            holds, backup_holds = entry["shrunk"]
            lines.append(messages.CHECK_DATABASE_SHRUNK % (label, holds, backup_holds))
    for path in findings["unreadable_folders"]:
        lines.append(messages.CHECK_FOLDER_UNREAD % path)
    for section, rows in findings["missing_files"].items():
        if rows:
            lines.append(messages.CHECK_ROWS_WITHOUT_FILES % (
                wording.and_list([name for _id, name in rows]), library_files.section_label(section),
                "has" if len(rows) == 1 else "have"))
    unlisted = findings["unlisted"]
    if unlisted:
        saved = sum(1 for one in unlisted if one["record"])
        lines.append(messages.CHECK_UNLISTED_FOLDERS % (
            wording.count(len(unlisted), "asset folder"), saved))
    if findings["orphans"]:
        lines.append(messages.CHECK_ORPHANS % wording.count(len(findings["orphans"]), "file"))
    if findings["leftovers"]:
        lines.append(messages.CHECK_LEFTOVERS_FOUND % wording.count(len(findings["leftovers"]), "file"))
    if findings["conflicts"]:
        lines.append(messages.CHECK_CONFLICTS_KEPT % wording.count(
            len(findings["conflicts"]), "copy", "copies"))
    if findings["unknown"]:
        lines.append(messages.CHECK_UNKNOWN_FOUND % wording.and_list(findings["unknown"]))
    for section, rows in findings["no_picture"].items():
        if rows:
            lines.append(messages.CHECK_NO_PICTURE % wording.count(
                len(rows), library_files.section_noun(section, 1)))
    for section, rows in findings["no_category"].items():
        if rows:
            lines.append(messages.CHECK_NO_CATEGORY % wording.count(
                len(rows), library_files.section_noun(section, 1)))
    if findings["locations_gone"]:
        lines.append(messages.CHECK_LOCATIONS_GONE % wording.and_list(findings["locations_gone"]))
    if findings["locations_unreachable"]:
        lines.append(messages.CHECK_DRIVE_NOT_CONNECTED)
    if findings["favorites_gone"]:
        lines.append(messages.CHECK_FAVORITES_GONE % wording.count(
            len(findings["favorites_gone"]), "favorite"))
    return lines


def trash_line(findings: dict) -> str:
    """What the library's trash holds, and when its oldest day is deleted."""
    held = findings["trash"]
    if not held["files"]:
        return messages.CHECK_TRASH_EMPTY
    return messages.CHECK_TRASH_HOLDS % (wording.count(held["files"], "file"),
                                         wording.byte_size(held["bytes"]),
                                         min(day[1] for day in held["days"] if day[1]))


def summary(findings: dict) -> dict:
    """For Preferences: the three lights, each (state, number), the line shown, and every line."""
    lists_ok = not any(entry["state"] in ("held",) for entry in findings["databases"])
    errors = sum(1 for entry in findings["databases"] if entry["state"] in TROUBLE)
    files = (sum(len(rows) for rows in findings["missing_files"].values()) + len(findings["unlisted"])
             + len(findings["orphans"]) + len(findings["leftovers"]) + len(findings["unknown"])
             + len(findings["conflicts"]))
    refs = len(findings["locations_gone"]) + len(findings["favorites_gone"])

    def light(number, checked=True):
        return (FOUND if number else CLEAN) if checked else UNCHECKED, number
    lines = report_lines(findings)
    return {"lights": {"errors": light(errors),
                       "files": light(files, lists_ok and not findings["unreadable_folders"]),
                       "refs": light(refs, lists_ok and findings["files_checked"]
                                     and not (findings["locations_unreachable"] and not refs))},
            "info": lines[0] if lines else messages.CHECK_NOTHING_TO_REPAIR, "lines": lines}


def confirmable(findings: dict) -> list:
    """(key, label) of each thing Fix All removes only once named: rows, unknown, unlisted files."""
    named = [(("row", section, asset_id), "%s (%s)" % (name, library_files.section_label(section)))
             for section, rows in findings["missing_files"].items() for asset_id, name in rows]
    named += [(("path", one["folder"]), one["folder"]) for one in findings["unlisted"]
              if not one["record"]]
    named += [(("path", path), path) for path in findings["unknown"] + findings["orphans"]]
    return named



def _guard(library_dir: str):
    """The guard a fix writes through; refused on a 2.0 library, which is converted first."""
    if layout_conversion.needs_conversion(library_dir):
        raise Refused(messages.CHECK_NEEDS_CONVERSION)
    return guard.Guard(library_dir)


def _section_reading(held, section: str):
    reading = held.read(section)
    if reading.verdict not in (guard.FINE, guard.FRESH):
        raise Refused(_state_line(_STATES.get(reading.verdict, ""), library_files.section_label(section)))
    return reading


def _with_rows(reading, rows: dict) -> dict:
    """The database's document with `rows` as its assets and every category they name listed."""
    document = dict(reading.document or {})
    categories = dict(document.get("categories") or {})
    for row in rows.values():
        for name in material.category_names((row or {}).get("categories")):
            categories.setdefault(name, {"order": len(categories)})
    return dict(document, assets=rows, categories=categories)


def _row_of(asset_id: str, record) -> dict:
    """A row from an asset's record, or a placeholder in Recovered when it has none."""
    if isinstance(record, dict) and record:
        row = {key: value for key, value in record.items() if key not in documents.STAMPS}
        return dict(row, id=asset_id)
    return {"id": asset_id, "name": "%s %s" % (RECOVERED, asset_id), "categories": [RECOVERED]}


def _records_of(library_dir: str, section: str) -> dict:
    """{id: its record or None} of every asset folder of a section."""
    base = material.section_folder(library_dir, section)
    found = {}
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else ():
        owner = library_files.folder_id(name)
        if owner and os.path.isdir(os.path.join(base, name)):
            found[owner] = asset_record.read(os.path.join(
                base, name, owner + library_files.RECORD_SUFFIX))[asset_record.METADATA] or None
    return found


def recover(library_dir: str, user: str = "") -> int:
    """Each unlisted asset folder listed in its section's database from its record; how many."""
    held, added = _guard(library_dir), 0
    for section in ASSET_SECTIONS:
        found = [one for one in survey(library_dir)["unlisted"] if one["section"] == section]
        if not found:
            continue
        reading = _section_reading(held, section)
        rows = dict((reading.document or {}).get("assets") or {})
        for one in found:
            if one["id"] not in rows:
                rows[one["id"]] = _row_of(one["id"], one["record"])
                added += 1
        change = held.change(user)
        change.put(reading.ticket, _with_rows(reading, rows))
        change.commit()
    return added


def restore(library_dir: str, name: str, backup: str, user: str = "") -> int:
    """A backup as its database, then its assets brought up to date from their records."""
    held = _guard(library_dir)
    try:
        held.restore(name, backup)
    except guard.Refused as exc:
        raise Refused(str(exc)) from exc
    if name not in ASSET_SECTIONS:
        return 0
    reading = _section_reading(held, name)
    rows = dict((reading.document or {}).get("assets") or {})
    changed = 0
    for asset_id, record in _records_of(library_dir, name).items():
        newer = _row_of(asset_id, record)
        if record and rows.get(asset_id, {}) != newer:    # saved or changed after the backup
            rows[asset_id] = dict(rows.get(asset_id) or {}, **newer)
            changed += 1
    if changed:
        change = held.change(user)
        change.put(reading.ticket, _with_rows(reading, rows))
        change.commit()
    return changed


def rebuild(library_dir: str, name: str, user: str = "") -> int:
    """A Material or Node database that cannot be read, written anew from its records; how many."""
    held = _guard(library_dir)
    if name not in ASSET_SECTIONS or held.read(name).verdict not in (guard.CORRUPT, guard.MISSING):
        raise Refused(messages.CHECK_REBUILD_REFUSED % library_files.section_label(name))
    rows = {asset_id: _row_of(asset_id, record)
            for asset_id, record in _records_of(library_dir, name).items()}
    change = held.change(user)
    change.replace(name, _with_rows(guard.Reading(name, guard.FRESH, {}), rows))
    change.commit()
    return len(rows)


def start_empty(library_dir: str, name: str, user: str = "") -> None:
    """A database that cannot be read and has no backup, written new and empty."""
    held = _guard(library_dir)
    if held.read(name).verdict not in (guard.CORRUPT, guard.MISSING):
        raise Refused(messages.CHECK_REBUILD_REFUSED % library_files.section_label(name))
    document = {}
    if name == library_files.MASTER:    # what a new library has, and the databases that are here
        document = {"policy": {"library": {"version": library_policy.LIBRARY_VERSION}},
                    guard.MANIFEST: {other: {"created": held.stamp(), "by": ""}
                                     for other in guard.DATABASES if other != name
                                     and os.path.lexists(held.path(other))}}
    change = held.change(user)
    change.replace(name, document)
    change.commit()


def remove_rows(library_dir: str, keys: list, user: str = "") -> int:
    """The named rows whose files are still missing, removed, and their folders trashed."""
    fresh = survey(library_dir)
    if fresh["holding_back"]:
        raise Refused(fresh["holding_back"])
    held, removed = _guard(library_dir), 0
    for section in ASSET_SECTIONS:
        wanted = {key[2] for key in keys if key[:2] == ("row", section)}
        going = [asset_id for asset_id, _name in fresh["missing_files"].get(section, ())
                 if asset_id in wanted]
        if not going:
            continue
        reading = _section_reading(held, section)
        rows = {key: row for key, row in ((reading.document or {}).get("assets") or {}).items()
                if key not in going}
        change = held.change(user)
        change.put(reading.ticket, dict(reading.document or {}, assets=rows))
        for asset_id in going:
            folder = material.folder_in(library_dir, section, asset_id)
            if os.path.isdir(folder):
                change.trash(held.inside(folder))
        change.commit()
        removed += len(going)
    return removed


def trash(library_dir: str, shown: dict, keys: list, user: str = "") -> int:
    """Leftovers, and the named unknown and unlisted files the check showed and are still so."""
    fresh = survey(library_dir)
    if fresh["holding_back"]:
        raise Refused(fresh["holding_back"])
    named = {key[1] for key in keys if key[0] == "path"}
    still = {key[1] for key, _label in confirmable(fresh) if key[0] == "path"}
    going = [path for path in fresh["leftovers"] if path in shown["leftovers"]]
    going += sorted(named & still & {key[1] for key, _label in confirmable(shown)
                                     if key[0] == "path"})
    if not going:
        return 0
    held = _guard(library_dir)
    change = held.change(user)
    for relative in going:
        change.trash(relative)
    change.commit()
    return len(going)


def uncategorized(library_dir: str, user: str = "") -> int:
    """Every row with no category put in Uncategorized, in its database and its record."""
    held, done = _guard(library_dir), 0
    fresh = survey(library_dir)
    for section in ASSET_SECTIONS:
        loose = [asset_id for asset_id, _name in fresh["no_category"].get(section, ())]
        if not loose:
            continue
        reading = _section_reading(held, section)
        rows = dict((reading.document or {}).get("assets") or {})
        change = held.change(user)
        for asset_id in loose:
            rows[asset_id] = dict(rows.get(asset_id) or {}, categories=[UNCATEGORIZED])
            record = os.path.join(material.folder_in(library_dir, section, asset_id),
                                  asset_id + library_files.RECORD_SUFFIX)
            if os.path.isfile(record) and not asset_record.unreadable(record):
                metadata = dict(asset_record.read(record)[asset_record.METADATA] or {},
                                categories=[UNCATEGORIZED])
                change.put_file(held.inside(record), asset_record.with_sections(
                    record, {asset_record.METADATA: metadata}))
        change.put(reading.ticket, _with_rows(reading, rows))
        change.commit()
        done += len(loose)
    return done


def set_aside(preferences, shown: dict) -> int:
    """Each location still gone, out of this user's sidebar, its id and annotations kept."""
    going = [path for path in shown["locations_gone"]
             if not os.path.isdir(path) and not hostos.volume_unreachable(path)]
    for path in going:
        preferences.remove_file_folder(path)
    return len(going)


def drop_favorites(preferences, shown: dict) -> int:
    """This user's favorites of files still gone, removed; no other section's favorite."""
    going = [path for path in shown["favorites_gone"] if not os.path.exists(path)]
    if going and not locations.set_favourites(preferences, {path: False for path in going}):
        raise Refused(messages.CHECK_FAVORITES_NOT_SAVED)
    return len(going)


def fix_safe(library_dir: str, preferences, shown: dict, user: str = "") -> dict:
    """What can be done without losing anything: recover, set aside, favorites of gone files."""
    done = {"recovered": recover(library_dir, user)}
    if preferences is not None and hostos.canonical_path_key(str(getattr(preferences, "dir", ""))) \
            == hostos.canonical_path_key(library_dir):    # the Files section is the open library's
        done["folders"] = set_aside(preferences, shown)
        done["favorites"] = drop_favorites(preferences, shown)
    return done


def _mend(library_dir: str, user: str) -> dict:
    """Each database that cannot be read: its newest readable backup, a rebuild, or empty."""
    held, done = _guard(library_dir), {}
    for entry in survey(library_dir)["databases"]:
        name = entry["name"]
        if entry["state"] not in ("unreadable", "missing"):
            continue
        backup = next((file for file, _when in held.backups(name) if _reads(held, name, file)), "")
        if backup:
            restore(library_dir, name, backup, user)
            done[name] = "restored"
        elif name in ASSET_SECTIONS:
            rebuild(library_dir, name, user)
            done[name] = "rebuilt"
        else:
            start_empty(library_dir, name, user)
            done[name] = "emptied"
    return done


def _reads(held, name: str, backup: str) -> bool:
    try:
        return guard._parse(held.read_file(guard.BACKUP_DIR + "/" + backup),
                            guard.DATABASES[name])[0] is not None
    except OSError:
        return False


def fix_all(library_dir: str, preferences, shown: dict, keys: list, user: str = "") -> dict:
    """Mend the databases, run the safe fixes, remove the named rows, then trash what was shown."""
    done = {"mended": _mend(library_dir, user)}
    done.update(fix_safe(library_dir, preferences, shown, user))
    done["removed"] = remove_rows(library_dir, keys, user)
    done["trashed"] = trash(library_dir, shown, keys, user)
    debug.event("check", "fix all", **{key: value for key, value in done.items()
                                        if key != "mended"}, mended=sorted(done["mended"]))
    return done
