"""Repair's questions and answers; the checks are core/repair.py's, and neither needs the pane."""

import os

import hou

from amaze import messages
from amaze.core import database, debug, repair
from amaze.helpers import restore as restore_lib


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


_ONLY_A_REPORT_NOW = (
    "Repair can only tell you this much right now: Amaze has "
    "already read this library since Houdini started, and it would "
    "write what it remembers back over anything put right here. "
    "Quit Houdini, start it again, and run Repair before you open "
    "Amaze - then Repair can also put a saved copy back, or move "
    "unlisted files aside for you.")


def _repair_settings(settings: dict) -> None:
    """settings.json will not read, is missing or names no library: offer saved copies back."""
    folder = os.path.dirname(settings["path"])
    if not settings["snapshots"]:
        hou.ui.displayMessage(                           # type: ignore
            messages.SETTINGS_UNREADABLE_NO_COPIES % folder,
            title=messages.TITLE_AMAZE_REPAIR)
        return
    if open_panel_tab() is not None:
        hou.ui.displayMessage(                           # type: ignore
            messages.AMAZE_OPEN_STOPS_REPAIR,
            title=messages.TITLE_AMAZE_REPAIR)
        return
    findings = {"directory": folder, "lists": [], "settings": settings,
                "complete": False, "unaccounted": {}}
    copies = "\n".join(
        messages.SETTINGS_COPY_LINE_UNREADABLE % snap["when"] if snap["error"]
        else snap["when"] for _tier, snap in settings["snapshots"])
    if settings["state"] == "absent":
        report = messages.SETTINGS_MISSING_REPAIR_REPORT % copies
    elif settings["state"] == "no-library":
        report = messages.SETTINGS_NO_LIBRARY_REPAIR_REPORT % copies
    else:
        report = messages.SETTINGS_UNREADABLE_REPAIR_REPORT % copies
    may_change = not repair.session_has_a_library_open()
    if not may_change:
        report += "\n\n" + _ONLY_A_REPORT_NOW
    choices, actions = _choices(findings, may_change)
    picked = hou.ui.displayMessage(                       # type: ignore
        report, buttons=tuple(choices),
        default_choice=len(choices) - 1, close_choice=len(choices) - 1,
        title=messages.TITLE_AMAZE_REPAIR)
    if 0 <= picked < len(actions) and actions[picked] == "restore":
        _do_restore(findings)


def run(preferences=None) -> None:
    """The shelf tool: reports always, changes only with no library open."""
    settings = repair.settings_survey(preferences)
    if settings is not None and (settings["state"] == "unreadable" or (
            settings["state"] == "absent" and settings["snapshots"])):
        _repair_settings(settings)    # with no settings, no library can be named
        return
    configured = repair.configured_library(preferences)
    if not configured:
        named = repair._copies_naming_a_library(settings)
        if named:
            _repair_settings(dict(settings, state="no-library", snapshots=named))
            return
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

    findings = repair.survey(directory)
    findings["settings"] = settings
    debug.event("repair", "surveyed", complete=findings["complete"],
                unaccounted=repair.unaccounted_total(findings),
                states={entry["filename"]: entry["state"]
                        for entry in findings["lists"]})

    lines = repair.report_lines(findings)
    may_change = not repair.session_has_a_library_open()
    if not may_change:
        lines += ["", _ONLY_A_REPORT_NOW]

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
    if may_change and repair.restorable(findings):
        choices.append("Put a Saved Copy Back")
        actions.append("restore")
    if may_change and findings["complete"] and repair._complete_pairs(findings):
        choices.append("Add %s to a Section"
                       % repair._files_on_a_button(len(repair._reattachable_files(
                           findings))))
        actions.append("reattach")
    if may_change and findings["complete"] and repair.unaccounted_total(findings):
        choices.append("Move %s Aside"
                       % repair._files_on_a_button(repair.unaccounted_total(findings)))
        actions.append("quarantine")
    choices.append("Close")
    actions.append(None)
    return choices, actions


def _do_restore(findings: dict) -> None:
    offers = repair.restorable(findings)
    labels = ["%s - %s" % (database.section_label(filename),
                           repair._copy_named_by_what_it_holds(filename, snap))
              for filename, _tier, snap, _current in offers]
    chosen = hou.ui.selectFromList(                       # type: ignore
        labels, exclusive=True, title=messages.TITLE_AMAZE_REPAIR,
        message="Which saved copy should Amaze put back?",
        column_header="Saved copies")
    if not chosen:
        return
    filename, tier, snap, current = offers[chosen[0]]
    if filename == repair._SETTINGS:
        _do_restore_settings(findings, tier, snap)
        return
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
        done = repair.put_back(findings, filename, tier)
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


def _do_restore_settings(findings: dict, tier: str, snap: dict) -> None:
    """Confirm, put the chosen settings copy back through the shared door, and say how to undo it."""
    if snap["error"]:
        hou.ui.displayMessage(                            # type: ignore
            messages.SETTINGS_COPY_CANNOT_BE_READ,
            title=messages.TITLE_AMAZE_REPAIR)
        return
    way_back = findings["settings"]["state"] == "ok"    # only settings that read and name a library are a way back
    if hou.ui.displayMessage(                             # type: ignore
        messages.CONFIRM_PUT_SETTINGS_BACK % snap["when"],
        help=messages.HELP_PUT_SETTINGS_BACK % (
            messages.SETTINGS_NOW_SAVED_FIRST if way_back else ""),
        buttons=messages.BUTTONS_PUT_COPY_BACK,
        default_choice=1, close_choice=1,
        severity=hou.severityType.Warning,                # type: ignore
        title=messages.TITLE_AMAZE_REPAIR,
    ) != 0:
        return
    try:
        done = repair.put_back(findings, repair._SETTINGS, tier)
    except restore_lib.RestoreRefused as exc:
        hou.ui.displayMessage(str(exc), title=messages.TITLE_AMAZE_REPAIR)  # type: ignore
        return
    folder = os.path.dirname(repair._target_of(findings, repair._SETTINGS))
    undo = (restore_lib.info(os.path.join(folder, done["undo"]))
            if done["undo"] else None)
    kept = (messages.SETTINGS_EARLIER_COPY_KEPT % undo["when"]
            if way_back and undo is not None and undo["exists"] and not undo["error"]
            else "")
    hou.ui.displayMessage(                                # type: ignore
        messages.SETTINGS_PUT_BACK_DONE % (snap["when"], kept),
        title=messages.TITLE_AMAZE_REPAIR)


def _do_quarantine(findings: dict) -> None:
    total = repair.unaccounted_total(findings)
    if hou.ui.displayMessage(                             # type: ignore
        messages.CONFIRM_MOVE_FILES_ASIDE % repair._files(total),
        help="The files no section lists: %s. They move into Amaze's "
             "own holding folder on this computer - outside your "
             "library, so they do not sync and do not travel. Nothing "
             "is deleted today: they are kept for 30 days and named in "
             "the report, and moving one back is copying it back.\n\n"
             "Everything showing in Amaze stays. Do this only if you have "
             "already tried putting a saved copy of a list back: if one of "
             "these files belongs to a material whose list was lost, "
             "restoring the list is what brings it back."
             % repair._files_by_folder(findings),
        buttons=messages.BUTTONS_MOVE_ASIDE,
        default_choice=1, close_choice=1,
        title=messages.TITLE_AMAZE_REPAIR,
    ) != 0:
        return
    try:
        result = repair.quarantine(findings)
    except ValueError as exc:
        # Unreachable through the buttons, and handled anyway.
        hou.ui.displayMessage(                            # type: ignore
            messages.NOTHING_MOVED_ASIDE_REASON % exc,             # a sentence
            title=messages.TITLE_AMAZE_REPAIR)
        return
    if result["failed"]:
        hou.ui.displayMessage(                            # type: ignore
            messages.FILES_MOVED_ASIDE_SOME_FAILED
            % (repair._files(len(result["moved"])),
               repair._files(len(result["failed"]))),
            title=messages.TITLE_AMAZE_REPAIR)
    else:
        hou.ui.displayMessage(                            # type: ignore
            messages.FILES_MOVED_ASIDE_DONE
            % repair._files(len(result["moved"])),
            title=messages.TITLE_AMAZE_REPAIR)


def _do_reattach(findings: dict) -> None:
    pairs = repair._complete_pairs(findings)
    owners = database.ASSET_FILE_OWNERS
    labels = [database.section_label(name) for name in owners]
    chosen = hou.ui.selectFromList(                       # type: ignore
        labels, exclusive=True, title=messages.TITLE_AMAZE_REPAIR,
        message="Which section do these %s belong in? Amaze cannot tell "
                "from the files themselves - a saved material and a saved "
                "node look the same in the folder."
                % repair._files(len(repair._reattachable_files(findings))),
        column_header="Section")
    if not chosen:
        return
    filename = owners[chosen[0]]
    label = database.section_label(filename)
    noun = database.section_noun(filename, len(pairs))
    if hou.ui.displayMessage(                             # type: ignore
        # How a material is stored is not what it is.
        messages.CONFIRM_ADD_UNLISTED_TO_SECTION % (len(pairs), noun, label),
        help="Each one keeps the name, category and tags recorded beside "
             "its files, and comes back where it was. Anything with no "
             "such record comes back in a new category called %s, named "
             "%s plus the start of its file name, with no renderer badge "
             "until you save it again - rename those afterwards.\n\n"
             "If there is a saved copy of the %s list from before they "
             "went missing, putting that back instead is still the "
             "closest match. Nothing here is deleted or overwritten "
             "either way."
             % (repair.RECOVERED_CATEGORY, repair.RECOVERED_CATEGORY, label),
        buttons=messages.BUTTONS_ADD_BACK,
        default_choice=1, close_choice=1,
        title=messages.TITLE_AMAZE_REPAIR,
    ) != 0:
        return
    try:
        result = repair.reattach(findings, filename)
    except ValueError as exc:
        hou.ui.displayMessage(                            # type: ignore
            messages.SECTION_LIST_UNCHANGED_REASON % (label, exc),
            title=messages.TITLE_AMAZE_REPAIR)
        return
    count = len(result["added"])
    noun = database.section_noun(filename, count)
    minted = len(result["minted"])
    if minted:                    # only these need renaming; the rest kept their own names
        said = messages.UNLISTED_FILES_ADDED_BACK_SOME_UNNAMED % (
            count, noun, label, minted, repair.RECOVERED_CATEGORY)
    else:
        said = messages.UNLISTED_FILES_ADDED_BACK_DONE % (count, noun, label)
    hou.ui.displayMessage(said,                           # type: ignore
                          title=messages.TITLE_AMAZE_REPAIR)
