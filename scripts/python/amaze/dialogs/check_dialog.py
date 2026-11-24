"""Check Library's one flow, from Preferences and the shelf: the report, its fixes, what they did."""

import os

import hou

from amaze import messages
from amaze.core import check_library, debug, library_files
from amaze.helpers import wording


def _say(text: str, details: str = "", warn: bool = False) -> None:
    hou.ui.displayMessage(text, details=details or None, details_expanded=bool(details),
                          title=messages.TITLE_CHECK_LIBRARY,
                          severity=hou.severityType.Warning if warn else hou.severityType.Message)


def _ask(text: str, buttons: tuple, details: str = "") -> int:
    """The button picked; the last one, Cancel, for Return, Esc and closing the window."""
    return hou.ui.displayMessage(text, buttons=buttons, default_choice=len(buttons) - 1,
                                 close_choice=len(buttons) - 1, details=details or None,
                                 details_expanded=bool(details), title=messages.TITLE_CHECK_LIBRARY,
                                 severity=hou.severityType.Warning)


def show(library_dir: str, preferences=None, changed=None, report_only: bool = False) -> bool:
    """The report of one library and its fixes; `changed()` after a fix; True when one ran."""
    findings = check_library.survey(library_dir, preferences)
    lines = check_library.report_lines(findings)
    trash = check_library.trash_line(findings)
    if not lines or report_only:
        _say("\n".join([messages.CHECK_FOUND_HEAD, ""] + (lines or [messages.CHECK_NOTHING_TO_REPAIR])
                       + ([messages.CHECK_LIBRARY_ONLY_A_REPORT] if report_only and lines else [])),
             details=trash)
        return False
    safe = bool([one for one in findings["unlisted"] if one["record"]] or
                findings["locations_gone"] or findings["favorites_gone"])
    buttons = ((messages.BUTTON_FIX_ALL,) + ((messages.BUTTON_FIX_SAFE,) if safe else ())
               + (messages.BUTTON_FIX_CANCEL,))
    picked = buttons[_ask("\n".join([messages.CHECK_FOUND_HEAD, ""] + lines), buttons, trash)]
    if picked == messages.BUTTON_FIX_CANCEL:
        return False
    user = str(getattr(preferences, "library_user", "") or "")
    try:
        if picked == messages.BUTTON_FIX_SAFE:
            done = check_library.fix_safe(library_dir, preferences, findings, user)
        else:
            named = check_library.confirmable(findings)
            keys = [key for key, _label in named]
            if named:
                answer = _ask(messages.CONFIRM_FIX_ALL_TRASH, messages.BUTTONS_FIX_ALL_TRASH,
                              "\n".join(label for _key, label in named))
                if answer == 2:
                    return False
                keys = keys if answer == 0 else []
            done = check_library.fix_all(library_dir, preferences, findings, keys, user)
    except (check_library.Refused, OSError) as exc:
        debug.event("check", "a fix was refused", error=str(exc))
        _say(messages.NOTHING_CHANGED_REASON % str(exc).rstrip("."), warn=True)
        return False
    if changed is not None:
        changed()    # the library read again: the panel shows the change without a restart
    _say("\n".join(done_lines(done)) or messages.LIBRARY_CHANGED_SINCE_CHECK)
    return True


def done_lines(done: dict) -> list:
    """What the fixes did, one line each."""
    lines = []
    for name, how in sorted(done.get("mended", {}).items()):
        label = library_files.section_label(name)
        lines.append(messages.FIXED_RESTORED % label if how == "restored"
                     else messages.FIXED_REBUILT % label if how == "rebuilt"
                     else messages.FIXED_EMPTIED % label)
    if done.get("recovered"):
        lines.append(messages.FIXED_RECOVERED % wording.count(done["recovered"], "asset"))
    if done.get("removed"):
        lines.append(messages.FIXED_REMOVED % wording.count(done["removed"], "asset"))
    if done.get("trashed"):
        lines.append(messages.FIXED_TRASHED % wording.count(done["trashed"], "file"))
    if done.get("favorites"):
        lines.append(messages.FIXED_FAVORITES % wording.count(done["favorites"], "favorite"))
    if done.get("folders"):
        lines.append(messages.FIXED_FOLDERS % wording.count(done["folders"], "folder"))
    return lines


def run(preferences=None) -> None:
    """The shelf tool: the library the settings name, checked; only a report while a panel has it."""
    if preferences is None:
        from amaze.prefs import prefs as prefs_module
        preferences = prefs_module.Prefs()
        preferences.load()
    folder = str(getattr(preferences, "dir", "") or "")
    if not folder:
        _say(messages.NO_LIBRARY_FOLDER_CONFIGURED, warn=True)
    elif not os.path.isdir(folder):
        _say(messages.LIBRARY_FOLDER_UNREACHABLE % folder, warn=True)
    else:
        show(folder, preferences, report_only=check_library.held_here(folder))


def repair_failed(library_dir: str, preferences) -> None:
    """A library whose Material or Node database cannot be read: restore or rebuild, as picked."""
    findings = check_library.survey(library_dir)
    user = str(getattr(preferences, "library_user", "") or "")
    for entry in findings["databases"]:
        name, label = entry["name"], library_files.section_label(entry["name"])
        if name not in library_files.ASSET_SECTIONS or entry["state"] not in ("unreadable", "missing"):
            continue
        backup = entry["backups"][0] if entry["backups"] else None
        try:
            if backup is not None:
                answer = _ask(messages.CHECK_PICK_REPAIR % (label, backup[1].strftime("%Y-%m-%d %H:%M")),
                              messages.BUTTONS_RESTORE_OR_REBUILD)
                if answer == 0:
                    check_library.restore(library_dir, name, backup[0], user)
                elif answer == 1:
                    check_library.rebuild(library_dir, name, user)
            elif _ask(messages.CHECK_PICK_REBUILD % label, messages.BUTTONS_REBUILD_ONLY) == 0:
                check_library.rebuild(library_dir, name, user)
        except (check_library.Refused, OSError) as exc:
            debug.event("check", "a repair was refused", database=name, error=str(exc))
            _say(messages.NOTHING_CHANGED_REASON % str(exc).rstrip("."), warn=True)
