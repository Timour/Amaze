"""Check Library's three lights and its two repairs, over `repair`'s survey and fixes."""

from amaze import messages
from amaze.core import debug, guard, repair
from amaze.core import library_files as naming
from amaze.helpers import wording

CLEAN, FOUND, UNJUDGED = "clean", "found", "unjudged"
ERRORS, FILES, REFS = "errors", "files", "refs"
PARTS = (ERRORS, FILES, REFS)

FIX_FAILED = (ValueError, OSError, guard.Refused, repair.RestoreRefused)

_UNREAD = ("unreadable", "absent-but-known", "newer")
_MENDABLE = ("unreadable", "absent-but-known")


def _in_state(findings: dict, states) -> list:
    return [entry for entry in findings.get("lists", ()) if entry["state"] in states]


def _are(count: int) -> str:
    return "is" if count == 1 else "are"


def _have(count: int) -> str:
    return "has" if count == 1 else "have"


def _total(found: dict) -> int:
    return sum(len(rows) for rows in (found or {}).values())


def _files_and_folders(files: int, folders: int) -> str:
    """`2 files and 1 folder`, a part that counts nothing left out."""
    return wording.and_list(([repair.files(files)] if files else [])
                            + ([repair.folders(folders)] if folders else []))


def _conflict_copies(count: int) -> str:
    return "1 conflict copy" if count == 1 else "%d conflict copies" % count


def _unread_line(entry: dict) -> str:
    if entry["state"] == "unreadable":
        return messages.CHECK_DATABASE_CORRUPT % entry["label"]
    if entry["state"] == "newer":
        return messages.CHECK_DATABASE_NEWER % entry["label"]
    return messages.CHECK_DATABASE_MISSING % entry["label"]


def _error_lines(findings: dict) -> list:
    said = []
    for entry in _in_state(findings, _UNREAD):
        said.append(_unread_line(entry))
        if (entry["state"] in _MENDABLE and entry["filename"] not in naming.ASSET_SECTIONS
                and not _backup_to_restore(entry)):
            said.append(messages.CHECK_DATABASE_NO_BACKUP % entry["label"])
    return said


def _file_lines(findings: dict) -> list:
    """One line per kind of finding in the folders, most serious first."""
    said = []
    for filename, rows in (findings.get("missing_files") or {}).items():
        if rows:
            said.append(messages.CHECK_NO_FILES % (
                "%d %s" % (len(rows), naming.section_noun(filename, len(rows))), _have(len(rows))))
    for folder, names in findings["unaccounted"].items():
        if names:
            said.append(messages.CHECK_IN_NO_DATABASE % (
                repair.files(len(names)), folder, _are(len(names))))
    leftovers = len(findings.get("leftovers") or ())
    if leftovers:
        said.append(messages.CHECK_LEFTOVERS % (repair.files(leftovers), _are(leftovers)))
    files, folders = (len(findings.get(key) or ()) for key in ("unknown", "unknown_folders"))
    if files or folders:
        said.append(messages.CHECK_UNKNOWN % (_files_and_folders(files, folders),
                                              _are(files + folders)))
    copies = len(findings.get("held_back") or ())
    if copies:
        said.append(messages.CHECK_CONFLICT_COPIES % _conflict_copies(copies))
    return said


def _ref_lines(findings: dict) -> list:
    said = []
    stars = len(findings.get("dead_stars") or ())
    if stars:
        said.append(messages.CHECK_DEAD_FAVORITES % (
            repair.favorites(stars), _are(stars),
            "a file that is" if stars == 1 else "files that are"))
    dead = len(findings.get("dead_folders") or ())
    if dead:
        said.append(messages.CHECK_DEAD_FOLDERS % (repair.folders(dead), _are(dead)))
    return said


def _files_count(findings: dict) -> int:
    return (_total(findings.get("missing_files")) + repair.unaccounted_total(findings)
            + sum(len(findings.get(key) or ())
                  for key in ("leftovers", "unknown", "unknown_folders", "held_back")))


def lights(findings: dict) -> dict:
    """{part: (CLEAN, 0) | (FOUND, count) | (UNJUDGED, None)} for Errors, Files and Ref."""
    held = bool(_in_state(findings, ("held",)))
    unread = _in_state(findings, _UNREAD)
    refs = len(findings.get("dead_stars") or ()) + len(findings.get("dead_folders") or ())
    files_unread = any(entry["filename"] == naming.FILES for entry in unread)

    def judged(unjudged: bool, count: int) -> tuple:
        if unjudged:
            return UNJUDGED, None
        return (FOUND, count) if count else (CLEAN, 0)

    return {
        ERRORS: judged(held, len(unread)),
        FILES: judged(held or not findings.get("complete"), _files_count(findings)),
        REFS: judged(held or files_unread or findings.get("preferences") is None
                     or (not refs and bool(findings.get("unmounted_folders"))), refs),
    }


def _unjudged_line(findings: dict) -> str:
    """Why a part is amber, when nothing found says it already."""
    held = _in_state(findings, ("held",))
    if held:
        return messages.CHECK_DATABASE_IN_USE % held[0]["label"]
    if findings.get("unreadable_folders"):
        return messages.CHECK_FOLDER_UNREAD % findings["unreadable_folders"][0].rstrip("/\\")
    if findings.get("unmounted_folders"):
        return messages.CHECK_DRIVE_NOT_CONNECTED
    return ""


def finding_lines(findings: dict) -> list:
    """The Repair dialog's lines: each kind of finding in a judged part, most serious first."""
    shown = lights(findings)
    said = []
    for part, lines in ((ERRORS, _error_lines), (FILES, _file_lines), (REFS, _ref_lines)):
        if shown[part][0] == FOUND:
            said.extend(lines(findings))
    return said


def _backup_to_restore(entry: dict):
    """The newest backup of a database that reads and holds something; None for none."""
    for tier, snap in entry.get("snapshots", ()):
        if not snap["error"] and (snap["count"] or entry["filename"] not in naming.LISTS):
            return tier
    return None


def _mendable(findings: dict) -> list:
    """(database, backup or None) of each corrupt or missing one, `DataBase.json` first."""
    return [(entry["filename"], _backup_to_restore(entry))
            for entry in _in_state(findings, _MENDABLE)]


def confirmable(findings: dict) -> dict:
    """What Fix All only does once the user has seen each name: {rows, unlisted, unknown}."""
    found = {"rows": {}, "unlisted": [], "unknown": []}
    if lights(findings)[FILES][0] != FOUND:
        return found
    found["rows"] = repair.rows_without_a_mat(findings)
    if not repair.why_unlisted_stay(findings):
        found["unlisted"] = [(folder, name)
                             for folder, names in repair.movable(findings)["unaccounted"].items()
                             for name in names]
    found["unknown"] = [entry[0] for key in ("unknown", "unknown_folders")
                        for entry in findings.get(key) or ()]
    return found


def confirmable_names(findings: dict, found: dict) -> list:
    """Each thing in `confirmable`, one per line: a row by section and name, a file by its path."""
    names = []
    for filename, ids in found["rows"].items():
        shown = dict((findings.get("missing_files") or {}).get(filename) or ())
        names.extend("%s: %s" % (naming.section_label(filename), shown.get(one, one))
                     for one in ids)
    names.extend("%s%s" % (folder, name) for folder, name in found["unlisted"])
    folders = {entry[0] for entry in findings.get("unknown_folders") or ()}
    names.extend(one + "/" if one in folders else one for one in found["unknown"])
    return [str(name) for name in names]


def _only_confirmed(findings: dict, confirmed) -> dict:
    """`findings` with the rows, unlisted files and unknown files cut down to `confirmed`."""
    confirmed = confirmed or {"rows": {}, "unlisted": [], "unknown": []}
    unlisted, unknown = set(map(tuple, confirmed["unlisted"])), set(confirmed["unknown"])
    return dict(
        findings,
        missing_files={filename: [row for row in rows
                                  if row[0] in confirmed["rows"].get(filename, ())]
                       for filename, rows in (findings.get("missing_files") or {}).items()},
        unaccounted={folder: [name for name in names if (folder, name) in unlisted]
                     for folder, names in findings["unaccounted"].items()},
        unknown=[entry for entry in findings.get("unknown") or () if entry[0] in unknown],
        unknown_folders=[entry for entry in findings.get("unknown_folders") or ()
                         if entry[0] in unknown])


def _to_trash(findings: dict) -> tuple:
    """What `repair.move_aside` takes for Fix All: the kinds that have something to move."""
    unlisted = not repair.why_unlisted_stay(findings) and repair.unaccounted_total(
        repair.movable(findings))
    return ((("unlisted",) if unlisted else ())
            + (("leftovers",) if findings.get("leftovers") else ())
            + (("unknown",) if repair.unknown_to_move_aside(findings) else ()))


def safe_fixes(findings: dict) -> list:
    """What Fix Safe would do here: `recover`, `favorites`, `folders`."""
    shown = lights(findings)
    fixes = []
    if (shown[FILES][0] == FOUND and repair.recoverable(findings)
            and not repair.why_nothing_can_be_added(findings)):
        fixes.append("recover")
    if shown[REFS][0] == FOUND:
        fixes.extend(key for key, held in (("favorites", "dead_stars"), ("folders", "dead_folders"))
                     if findings.get(held))
    return fixes


def all_fixes(findings: dict) -> list:
    """What Fix All would do here: the safe fixes, then `databases`, `rows`, `trash`."""
    shown = lights(findings)
    fixes = safe_fixes(findings)
    if shown[ERRORS][0] == FOUND and _mendable(findings):
        fixes.append("databases")
    if shown[FILES][0] == FOUND:
        if repair.rows_without_a_mat(findings):
            fixes.append("rows")
        if _to_trash(findings):
            fixes.append("trash")
    return fixes


def found_names(findings: dict) -> list:
    """Each asset, file and folder the red lights count, one per line, for the Repair dialog."""
    shown = lights(findings)
    names = []
    if shown[FILES][0] == FOUND:
        for filename, rows in (findings.get("missing_files") or {}).items():
            names.extend("%s: %s" % (naming.section_label(filename), name) for _id, name in rows)
        for folder, files in findings["unaccounted"].items():
            names.extend("%s/%s" % (folder, name) for name in files)
        for key in ("leftovers", "unknown", "unknown_folders", "held_back"):
            names.extend(entry[0] for entry in findings.get(key) or ())
    if shown[REFS][0] == FOUND:
        names.extend(findings.get("dead_stars") or ())
        names.extend(findings.get("dead_folders") or ())
    return [str(name) for name in names]


def summary(findings: dict) -> dict:
    """The Databases row: {lights, info, lines, names, safe, fixable}."""
    lines = finding_lines(findings)
    fixes = all_fixes(findings)
    return {"lights": lights(findings),
            "lines": lines,
            "names": found_names(findings),
            "info": (lines[0] if lines else _unjudged_line(findings)
                     or messages.CHECK_NOTHING_TO_REPAIR),
            "safe": bool(safe_fixes(findings)),
            "fixable": bool(fixes)}


def _nothing_done() -> dict:
    return {"restored": [], "rebuilt": [], "emptied": [], "recovered": {}, "removed": {}, "files": 0,
            "folders": 0, "favorites": 0, "locations": 0, "failed": []}


def _attempt(done: dict, what: str, fix, *args, **kwargs):
    """`fix` run; what it raises when it does not land is kept in `done`, and None returned."""
    try:
        return fix(*args, **kwargs)
    except FIX_FAILED as exc:
        debug.event("repair", "a fix did not land", fix=what, error=str(exc))
        done["failed"].append(str(exc).rstrip("."))
        return None


def _surveyed_again(findings: dict) -> dict:
    preferences = findings.get("preferences")
    if preferences is not None:
        return repair.survey(preferences)
    return repair.survey(findings["directory"], findings["img_dir"])


def _fix_safe(findings: dict, done: dict, guard_session: bool) -> None:
    fixes = safe_fixes(findings)
    if "recover" in fixes:
        result = _attempt(done, "recover", repair.recover, findings, guard_session=guard_session)
        for filename, landed in (result or {}).items():
            if landed["added"]:
                done["recovered"][filename] = (done["recovered"].get(filename, 0)
                                               + len(landed["added"]))
    if "folders" in fixes:
        done["locations"] += len(_attempt(done, "folders", repair.set_aside_folders, findings,
                                          guard_session=guard_session) or ())
    if "favorites" in fixes:
        done["favorites"] += len(_attempt(done, "favorites", repair.drop_dead_stars, findings,
                                          guard_session=guard_session) or ())


def fix_safe(findings: dict, guard_session: bool = True) -> dict:
    """Adds and tidies only: unlisted assets recovered, dead references dropped; what was done."""
    done = _nothing_done()
    _fix_safe(findings, done, guard_session)
    debug.event("repair", "fix safe", **_counts(done))
    return done


def _mend_databases(findings: dict, done: dict, guard_session: bool) -> None:
    """Each corrupt or missing database: its newest backup that reads, else a rebuild, else empty."""
    rebuild = []
    for filename, backup in _mendable(findings):
        if backup and _attempt(done, "restore", repair.put_back, findings, filename, backup,
                               guard_session=guard_session) is not None:
            done["restored"].append(filename)
        elif filename in naming.ASSET_SECTIONS:
            rebuild.append(filename)
        elif _attempt(done, "empty", repair.start_empty, findings["directory"], filename,
                      guard_session=guard_session) is not None:
            done["emptied"].append(filename)
    for filename in rebuild:
        built = _attempt(done, "rebuild", repair.rebuild, findings["directory"], filename,
                         guard_session=guard_session, or_empty=True)
        if built is not None:
            done["rebuilt" if built["assets"] else "emptied"].append(filename)


def fix_all(findings: dict, guard_session: bool = True, confirmed=None) -> dict:
    """Fix Safe, databases mended, leftovers trashed; and what `confirmed` names of `confirmable`."""
    done = _nothing_done()
    if not all_fixes(findings):
        return done
    if "databases" in all_fixes(findings):
        _mend_databases(findings, done, guard_session)
        findings = _surveyed_again(findings)
    _fix_safe(findings, done, guard_session)
    findings = _only_confirmed(_surveyed_again(findings), confirmed)
    fixes = all_fixes(findings)
    if "rows" in fixes:
        dropped = _attempt(done, "rows", repair.drop_rows_without_files, findings,
                           guard_session=guard_session) or {}
        done["removed"].update(dropped.get("removed") or {})
        done["files"] += len(dropped.get("moved") or ())
        findings = _only_confirmed(_surveyed_again(findings), confirmed)
        fixes = all_fixes(findings)
    if "trash" in fixes:
        result = _attempt(done, "trash", repair.move_aside, findings, _to_trash(findings),
                          guard_session=guard_session)
        folders = {entry[0] for entry in findings.get("unknown_folders") or ()}
        moved = (result or {}).get("moved", ())
        done["folders"] += sum(1 for one in moved if one in folders)
        done["files"] += sum(1 for one in moved if one not in folders)
    debug.event("repair", "fix all", **_counts(done))
    return done


def _counts(done: dict) -> dict:
    return {key: (value if isinstance(value, int) else len(value)) for key, value in done.items()}


def _databases(names: list) -> str:
    """`1 database`, `2 databases`."""
    return "1 database" if len(names) == 1 else "%d databases" % len(names)


def done_lines(done: dict) -> list:
    """What a fix did, as counts, one line per kind."""
    said = []
    if done["restored"]:
        said.append(messages.FIXED_RESTORED % (
            _databases(done["restored"]),
            "its backup" if len(done["restored"]) == 1 else "their backups"))
    if done["rebuilt"]:
        said.append(messages.FIXED_REBUILT % _databases(done["rebuilt"]))
    if done["emptied"]:
        said.append(messages.FIXED_EMPTIED % (
            _databases(done["emptied"]), "s" if len(done["emptied"]) == 1 else ""))
    recovered, removed = (
        wording.and_list(["%d %s" % (count, naming.section_noun(filename, count))
                          for filename, count in done[key].items() if count])
        for key in ("recovered", "removed"))
    if recovered:
        said.append(messages.FIXED_RECOVERED % recovered)
    if removed:
        said.append(messages.FIXED_REMOVED % removed)
    if done["files"] or done["folders"]:
        said.append(messages.FIXED_TRASHED % _files_and_folders(done["files"], done["folders"]))
    if done["favorites"]:
        said.append(messages.FIXED_FAVORITES % repair.favorites(done["favorites"]))
    if done["locations"]:
        said.append(messages.FIXED_FOLDERS % repair.folders(done["locations"]))
    return said
