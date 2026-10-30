"""Repair's questions and answers; the checks are core/repair.py's, and neither needs the pane."""

import os

import hou

from amaze import messages
from amaze.core import database, debug, keyed_store, repair
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
        report += "\n\n" + messages.REPAIR_ONLY_A_REPORT_NOW
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
        named = repair.copies_naming_a_library(settings)
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
        lines += ["", messages.REPAIR_ONLY_A_REPORT_NOW]

    choices, actions = _choices(findings, may_change)
    picked = hou.ui.displayMessage(                       # type: ignore
        "\n".join(lines),
        buttons=tuple(choices),
        default_choice=len(choices) - 1,
        close_choice=len(choices) - 1,
        title=messages.TITLE_AMAZE_REPAIR,
    )
    action = actions[picked] if 0 <= picked < len(actions) else None
    if action == "add-back":
        _do_add_back(findings)
    elif action == "restore":
        _do_restore(findings)
    elif action == "quarantine":
        _do_quarantine(findings)
    elif action == "reattach":
        _do_reattach(findings)


def _choices(findings: dict, may_change: bool):
    """Only the buttons that would change something, each with its own count."""
    choices, actions = [], []
    on_record = repair.materials_on_record(findings)
    if may_change and on_record and not repair.why_nothing_can_be_added(
            findings, "library.json"):
        choices.append(messages.BUTTON_REPAIR_ADD_BACK
                       % repair.count_on_a_button(len(on_record), "library.json"))
        actions.append("add-back")
    if may_change and repair.offered_copies(findings):
        choices.append(messages.BUTTON_REPAIR_PUT_COPY_BACK)
        actions.append("restore")
    if (may_change and repair.unsorted_pairs(findings)
            and not repair.why_nothing_can_be_added(findings)):
        choices.append(messages.BUTTON_REPAIR_ADD_TO_SECTION
                       % repair.files_on_a_button(len(repair.reattachable_files(
                           findings))))
        actions.append("reattach")
    aside = repair.unaccounted_total(repair.movable(findings))
    if may_change and findings["complete"] and aside:
        choices.append(messages.BUTTON_REPAIR_MOVE_ASIDE % repair.files_on_a_button(aside))
        actions.append("quarantine")
    choices.append(messages.BUTTON_REPAIR_CLOSE)
    actions.append(None)
    return choices, actions


def _do_add_back(findings: dict) -> None:
    """Confirm, put the materials back from what is saved beside their files, and say how many."""
    count = len(repair.materials_on_record(findings))
    label = database.section_label("library.json")
    written_new = (messages.ADD_BACK_WRITES_A_NEW_LIST % label
                   if repair.list_is_missing(findings, "library.json") else "")
    if hou.ui.displayMessage(                             # type: ignore
        messages.CONFIRM_ADD_UNLISTED_TO_SECTION
        % (count, database.section_noun("library.json", count), label),
        help=messages.HELP_ADD_BACK % written_new,
        buttons=messages.BUTTONS_ADD_BACK,
        default_choice=1, close_choice=1,
        title=messages.TITLE_AMAZE_REPAIR,
    ) != 0:
        return
    try:
        result = repair.add_materials_back(findings)
    except ValueError as exc:
        hou.ui.displayMessage(                            # type: ignore
            messages.SECTION_LIST_UNCHANGED_REASON % (label, exc),
            title=messages.TITLE_AMAZE_REPAIR)
        return
    added = len(result["added"])
    hou.ui.displayMessage(                                # type: ignore
        messages.UNLISTED_FILES_ADDED_BACK_DONE
        % (added, database.section_noun("library.json", added), label),
        title=messages.TITLE_AMAZE_REPAIR)


def _do_restore(findings: dict) -> None:
    """A list's newest saved copy is the one offered; an older one only through Older Copies."""
    offers = repair.offered_copies(findings)
    newest = []
    for offer in offers:
        if offer[0] not in [first[0] for first in newest]:
            newest.append(offer)
    if len(newest) > 1:
        offer = _pick(newest, messages.PICK_LIST_TO_PUT_BACK,
                      messages.COLUMN_NEWEST_SAVED_COPIES, sections=True)
    else:
        offer = newest[0] if newest else None
    if offer is None:
        return
    older = [other for other in offers if other[0] == offer[0] and other is not offer]
    if _put_copy_back(findings, offer, older=bool(older)) != "older":
        return
    offer = _pick(older, messages.PICK_OLDER_COPY_TO_PUT_BACK
                  % database.section_label(offer[0]), messages.COLUMN_OLDER_SAVED_COPIES)
    if offer is not None:
        _put_copy_back(findings, offer)


def _pick(offers: list, message: str, header: str, sections: bool = False):
    """One copy from a list that opens on its first row; None on Cancel."""
    chosen = hou.ui.selectFromList(                       # type: ignore
        [("%s - " % database.section_label(filename) if sections else "")
         + repair.copy_named_by_what_it_holds(filename, snap)
         for filename, _tier, snap, _current in offers],
        default_choices=(0,), exclusive=True,
        clear_on_cancel=True,    # without it Cancel answers the row that opened picked
        title=messages.TITLE_AMAZE_REPAIR, message=message, column_header=header)
    return offers[chosen[0]] if chosen else None


def _copy_buttons(older: bool) -> dict:
    """The confirm's buttons, with Older Copies where there are some; Cancel is Enter and close."""
    buttons = (messages.BUTTONS_PUT_COPY_BACK_OR_OLDER if older
               else messages.BUTTONS_PUT_COPY_BACK)
    return {"buttons": buttons, "default_choice": len(buttons) - 1,
            "close_choice": len(buttons) - 1}


def _put_copy_back(findings: dict, offer: tuple, older: bool = False):
    """Confirm one copy and put it back; "older" when Older Copies was pressed instead."""
    filename, tier, snap, current = offer
    if filename == keyed_store.SETTINGS:
        return _do_restore_settings(findings, tier, snap, older=older)
    label = database.section_label(filename)
    if snap["error"]:
        hou.ui.displayMessage(                            # type: ignore
            messages.CHOSEN_SAVED_COPY_CANNOT_BE_READ % label,
            title=messages.TITLE_AMAZE_REPAIR)
        return None
    held = snap["count"] or 0    # name the gain and the loss, and do the subtraction
    if current["error"]:
        change = messages.CURRENT_LIST_UNREADABLE
    else:
        now_holds = current["count"] or 0
        change = (messages.CURRENT_LIST_COMPARED
                  % (now_holds, now_holds, held, label, snap["when"]))
    picked = hou.ui.displayMessage(                       # type: ignore
        messages.CONFIRM_PUT_SAVED_COPY_BACK % (label, snap["when"]),
        help=messages.HELP_PUT_SAVED_COPY_BACK
             % (snap["when"], held, database.section_noun(filename, held),
                change, database.section_noun(filename, 2)),
        severity=hou.severityType.Warning,                # type: ignore
        title=messages.TITLE_AMAZE_REPAIR,
        **_copy_buttons(older))
    if older and picked == 1:
        return "older"
    if picked != 0:
        return None
    try:
        done = repair.put_back(findings, filename, tier)
    except restore_lib.RestoreRefused as exc:
        hou.ui.displayMessage(str(exc), title=messages.TITLE_AMAZE_REPAIR)  # type: ignore
        return None
    undo = (restore_lib.info(os.path.join(findings["directory"],
                                          done["undo"]))
            if done["undo"] else None)
    if undo is not None and undo["exists"]:
        went_back = messages.LIST_EARLIER_COPY_KEPT % undo["when"]
    else:
        went_back = messages.NO_EARLIER_LIST
    hou.ui.displayMessage(                                # type: ignore
        messages.SAVED_COPY_PUT_BACK_DONE % (label, snap["when"], went_back),
        title=messages.TITLE_AMAZE_REPAIR)
    return None


def _do_restore_settings(findings: dict, tier: str, snap: dict, older: bool = False):
    """Confirm and put a settings copy back, saying how to undo it; "older" as `_put_copy_back`."""
    if snap["error"]:
        hou.ui.displayMessage(                            # type: ignore
            messages.SETTINGS_COPY_CANNOT_BE_READ,
            title=messages.TITLE_AMAZE_REPAIR)
        return None
    way_back = findings["settings"]["state"] == "ok"    # only settings that read and name a library are a way back
    picked = hou.ui.displayMessage(                       # type: ignore
        messages.CONFIRM_PUT_SETTINGS_BACK % snap["when"],
        help=messages.HELP_PUT_SETTINGS_BACK % (
            messages.SETTINGS_NOW_SAVED_FIRST if way_back else ""),
        severity=hou.severityType.Warning,                # type: ignore
        title=messages.TITLE_AMAZE_REPAIR,
        **_copy_buttons(older))
    if older and picked == 1:
        return "older"
    if picked != 0:
        return None
    try:
        done = repair.put_back(findings, keyed_store.SETTINGS, tier)
    except restore_lib.RestoreRefused as exc:
        hou.ui.displayMessage(str(exc), title=messages.TITLE_AMAZE_REPAIR)  # type: ignore
        return None
    folder = os.path.dirname(repair.target_of(findings, keyed_store.SETTINGS))
    undo = (restore_lib.info(os.path.join(folder, done["undo"]))
            if done["undo"] else None)
    kept = (messages.SETTINGS_EARLIER_COPY_KEPT % undo["when"]
            if way_back and undo is not None and undo["exists"] and not undo["error"]
            else "")
    hou.ui.displayMessage(                                # type: ignore
        messages.SETTINGS_PUT_BACK_DONE % (snap["when"], kept),
        title=messages.TITLE_AMAZE_REPAIR)
    return None


def _do_quarantine(findings: dict) -> None:
    aside = repair.movable(findings)
    total = repair.unaccounted_total(aside)
    if hou.ui.displayMessage(                             # type: ignore
        messages.CONFIRM_MOVE_FILES_ASIDE % repair.files(total),
        help=messages.HELP_MOVE_FILES_ASIDE % repair.files_by_folder(aside),
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
            % (repair.files(len(result["moved"])),
               repair.files(len(result["failed"]))),
            title=messages.TITLE_AMAZE_REPAIR)
    else:
        hou.ui.displayMessage(                            # type: ignore
            messages.FILES_MOVED_ASIDE_DONE
            % repair.files(len(result["moved"])),
            title=messages.TITLE_AMAZE_REPAIR)


def _do_reattach(findings: dict) -> None:
    pairs = repair.unsorted_pairs(findings)
    owners = database.ASSET_FILE_OWNERS
    labels = [database.section_label(name) for name in owners]
    chosen = hou.ui.selectFromList(                       # type: ignore
        labels, exclusive=True, title=messages.TITLE_AMAZE_REPAIR,
        message=messages.PICK_SECTION_FOR_FILES
                % repair.files(len(repair.reattachable_files(findings))),
        column_header=messages.COLUMN_SECTION)
    if not chosen:
        return
    filename = owners[chosen[0]]
    label = database.section_label(filename)
    noun = database.section_noun(filename, len(pairs))
    if hou.ui.displayMessage(                             # type: ignore
        # How a material is stored is not what it is.
        messages.CONFIRM_ADD_UNLISTED_TO_SECTION % (len(pairs), noun, label),
        help=messages.HELP_ADD_TO_SECTION
             % (repair.RECOVERED_CATEGORY, repair.RECOVERED_CATEGORY, label),
        buttons=messages.BUTTONS_ADD_BACK,
        default_choice=1, close_choice=1,
        title=messages.TITLE_AMAZE_REPAIR,
    ) != 0:
        return
    try:
        result = repair.reattach(findings, filename, only=pairs)
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
