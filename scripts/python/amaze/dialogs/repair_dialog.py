"""Check Library's report, confirms and answers, for both doors; the checks are core/repair.py's."""

import os

import hou

from amaze import messages
from amaze.core import database, debug, keyed_store, repair
from amaze.helpers import ui_helpers
from amaze.helpers import restore as restore_lib

MOST_BUTTONS = 5    # actions one report shows before Choose an Action lists them instead


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


def _say(text: str, severity=None) -> None:
    """A finished sentence; `severity` Warning for what failed, Error for damage, else Message."""
    hou.ui.displayMessage(text, title=messages.TITLE_CHECK_LIBRARY,    # type: ignore
                          severity=severity or hou.severityType.Message)    # type: ignore


def _confirmed(text: str, buttons: tuple, help_text: str = "", warn: bool = False) -> bool:
    """One confirm with Cancel as Enter and close; True only for its first button."""
    return hou.ui.displayMessage(                         # type: ignore
        text, help=help_text, buttons=buttons, default_choice=1, close_choice=1,
        title=messages.TITLE_CHECK_LIBRARY,
        severity=hou.severityType.Warning if warn else hou.severityType.Message) == 0    # type: ignore


def _repair_settings(settings: dict) -> None:
    """settings.json will not read, is missing or names no library: offer saved copies back."""
    folder = os.path.dirname(settings["path"])
    if not settings["snapshots"]:
        _say(messages.SETTINGS_UNREADABLE_NO_COPIES % folder, hou.severityType.Error)
        return
    if open_panel_tab() is not None:
        _say(messages.CHECK_LIBRARY_IN_THE_PANEL)
        return
    findings = {"directory": folder, "lists": [], "settings": settings,
                "complete": False, "unaccounted": {}}
    copies = "\n".join(
        messages.SETTINGS_COPY_LINE_UNREADABLE % snap["when"] if snap["error"]
        else snap["when"] for _tier, snap in settings["snapshots"])
    if settings["state"] == "absent":
        text = messages.SETTINGS_MISSING_REPAIR_REPORT % copies
    elif settings["state"] == "no-library":
        text = messages.SETTINGS_NO_LIBRARY_REPAIR_REPORT % copies
    else:
        text = messages.SETTINGS_UNREADABLE_REPAIR_REPORT % copies
    may_change = not repair.session_has_a_library_open()
    if not may_change:
        text += "\n\n" + messages.CHECK_LIBRARY_ONLY_A_REPORT
    choices, actions = _choices(findings, may_change)
    picked = hou.ui.displayMessage(                       # type: ignore
        text, buttons=tuple(choices),
        default_choice=len(choices) - 1, close_choice=len(choices) - 1,
        title=messages.TITLE_CHECK_LIBRARY,
        severity=(hou.severityType.Error if settings["state"] == "unreadable"    # damage
                  else hou.severityType.Warning))
    if 0 <= picked < len(actions) and actions[picked] == "restore":
        act(findings, "restore")


def run(preferences=None) -> None:
    """The shelf tool, for a panel that will not open: reports always, acts with no library read."""
    settings = repair.settings_survey(preferences)
    if settings is not None and (settings["state"] == "unreadable" or (
            settings["state"] == "absent" and settings["snapshots"])):
        _repair_settings(settings)
        return
    configured = repair.configured_library(preferences)
    if not configured:
        named = repair.copies_naming_a_library(settings)
        if named:
            _repair_settings(dict(settings, state="no-library", snapshots=named))
            return
        _say(messages.NO_LIBRARY_FOLDER_CONFIGURED, hou.severityType.Warning)
        return
    if not os.path.isdir(configured):
        _say(messages.LIBRARY_FOLDER_UNREACHABLE % configured, hou.severityType.Warning)
        debug.event("repair", "refused - the library folder is not there", path=configured)
        return
    if open_panel_tab() is not None:
        _say(messages.CHECK_LIBRARY_IN_THE_PANEL)
        debug.event("repair", "refused - a panel is open")
        return
    findings = repair.survey(configured)
    findings["settings"] = settings
    surveyed(findings)
    action = report(findings, may_change=not repair.session_has_a_library_open())
    if action is not None:
        act(findings, action)


def check_in_panel(panel) -> None:
    """Library ▸ Check Library…: report, act and report again until Close, re-reading after each."""
    from amaze.actions import check
    check.let_go(panel)
    while True:
        findings = repair.survey(panel.prefs)
        findings["settings"] = repair.settings_survey(panel.prefs)
        surveyed(findings)
        action = report(findings)
        if action is None:
            return
        act(findings, action, guard=False, changed=lambda: check.read_again(panel))


def check_failed_library(folder: str, preferences) -> None:
    """Check Library on a library a switch left closed; fixes only while nothing here holds it."""
    while True:
        findings = repair.survey(folder, preferences.asset_dir, preferences.img_dir)
        findings["settings"] = None
        surveyed(findings)
        action = report(findings, may_change=not repair.session_holds(folder))
        if action is None or (action != "holding" and repair.session_holds(folder)):
            return
        act(findings, action, guard=False)


def surveyed(findings: dict) -> None:
    """The survey's record in the log, one event per check."""
    debug.event("repair", "surveyed", complete=findings["complete"],
                unaccounted=repair.unaccounted_total(findings),
                states={entry["filename"]: entry["state"] for entry in findings["lists"]})


def report(findings: dict, may_change: bool = True):
    """The report with only the buttons that apply; the chosen action, or None for Close."""
    text = "\n".join(repair.report_lines(findings))
    if not may_change:
        text += "\n\n" + messages.CHECK_LIBRARY_ONLY_A_REPORT
    choices, actions = _choices(findings, may_change)
    picked = hou.ui.displayMessage(                       # type: ignore
        text, buttons=tuple(choices), help=messages.HELP_CHECK_LIBRARY,
        default_choice=len(choices) - 1, close_choice=len(choices) - 1,
        title=messages.TITLE_CHECK_LIBRARY, severity=hou.severityType.Message)
    action = actions[picked] if 0 <= picked < len(actions) else None
    if action != "choose":
        return action
    labels, keys = _every_choice(findings, may_change)
    chosen = hou.ui.selectFromList(                       # type: ignore
        labels, exclusive=True, clear_on_cancel=True, title=messages.TITLE_CHECK_LIBRARY,
        message=messages.PICK_AN_ACTION, column_header=messages.COLUMN_ACTION)
    return keys[chosen[0]] if chosen else None


def _choices(findings: dict, may_change: bool):
    """The report's buttons and their actions; past `MOST_BUTTONS`, Choose an Action instead."""
    labels, keys = _every_choice(findings, may_change)
    if len(keys) > MOST_BUTTONS:
        labels, keys = [messages.BUTTON_CHOOSE_AN_ACTION], ["choose"]
    return labels + [messages.BUTTON_REPAIR_CLOSE], keys + [None]


def _every_choice(findings: dict, may_change: bool):
    """Every action that would change something, with its own count; Show Holding Folder too."""
    labels, keys = [], []

    def offer(label, key):
        labels.append(label)
        keys.append(key)

    if may_change:
        on_record = repair.materials_on_record(findings)
        if on_record and not repair.why_nothing_can_be_added(findings, "library.json"):
            offer(messages.BUTTON_REPAIR_ADD_BACK
                  % repair.count_on_a_button(len(on_record), "library.json"), "add-back")
        if repair.offered_copies(findings):
            offer(messages.BUTTON_REPAIR_PUT_COPY_BACK, "restore")
        if repair.unsorted_pairs(findings) and not repair.why_nothing_can_be_added(findings):
            offer(messages.BUTTON_REPAIR_ADD_TO_SECTION % repair.files_on_a_button(
                len(repair.reattachable_files(findings))), "reattach")
        aside = repair.files_to_move_aside(findings)
        if aside:
            offer(messages.BUTTON_REPAIR_MOVE_ASIDE % repair.files_on_a_button(aside),
                  "quarantine")
        unknown = repair.unknown_to_move_aside(findings)
        if unknown:
            offer(messages.BUTTON_MOVE_ONE_UNKNOWN_ASIDE if unknown == 1
                  else messages.BUTTON_MOVE_UNKNOWN_ASIDE % unknown, "unknown")
        dead, stars = findings.get("dead_folders") or [], findings.get("dead_stars") or []
        if dead:
            offer(messages.BUTTON_SET_ASIDE_FOLDERS
                  % repair.on_a_button(repair.folders(len(dead))), "set-aside")
        elif stars:
            offer(messages.BUTTON_REMOVE_DEAD_STARS
                  % repair.on_a_button(repair.favorites(len(stars))), "stars")
        if repair.uncategorised_count(findings):
            offer(messages.BUTTON_PUT_IN_UNCATEGORIZED
                  % (repair.on_a_button(repair.uncategorised_count(findings)),
                     repair.UNCATEGORISED), "uncategorised")
    if (findings.get("holding") or {}).get("files"):
        offer(messages.BUTTON_SHOW_HOLDING_FOLDER, "holding")
    return labels, keys


def act(findings: dict, action: str, guard: bool = True, changed=None) -> bool:
    """Confirm and run one action, `changed` called once it lands, then say so; True if it did."""
    if action == "holding":
        ui_helpers.reveal(findings["holding"]["path"])
        return False
    done = {"add-back": _do_add_back, "restore": _do_restore, "reattach": _do_reattach,
            "quarantine": _do_move_aside, "unknown": _do_move_unknown,
            "set-aside": _do_set_aside, "stars": _do_set_aside,
            "uncategorised": _do_uncategorised}[action]
    landed = []

    def changed_once():
        landed.append(True)
        if changed is not None:
            changed()

    done(findings, guard, changed_once)
    return bool(landed)


def _do_add_back(findings: dict, guard: bool, changed) -> None:
    """Confirm, put the materials back from what is saved beside their files, and say how many."""
    count = len(repair.materials_on_record(findings))
    label = database.section_label("library.json")
    written_new = (messages.ADD_BACK_WRITES_A_NEW_LIST % label
                   if repair.list_is_missing(findings, "library.json") else "")
    if not _confirmed(messages.CONFIRM_ADD_UNLISTED_TO_SECTION
                      % (count, database.section_noun("library.json", count), label),
                      messages.BUTTONS_ADD_BACK, messages.HELP_ADD_BACK % written_new):
        return
    try:
        result = repair.add_materials_back(findings, guard=guard)
    except ValueError as exc:
        _say(messages.SECTION_LIST_UNCHANGED_REASON % (label, exc), hou.severityType.Warning)
        return
    changed()
    added = len(result["added"])
    _say(messages.UNLISTED_FILES_ADDED_BACK_DONE
         % (added, database.section_noun("library.json", added), label))


def _do_restore(findings: dict, guard: bool, changed) -> None:
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
    if _put_copy_back(findings, offer, guard, changed, older=bool(older)) != "older":
        return
    offer = _pick(older, messages.PICK_OLDER_COPY_TO_PUT_BACK
                  % database.section_label(offer[0]), messages.COLUMN_OLDER_SAVED_COPIES)
    if offer is not None:
        _put_copy_back(findings, offer, guard, changed)


def _pick(offers: list, message: str, header: str, sections: bool = False):
    """One copy from a list that opens on its first row; None on Cancel."""
    chosen = hou.ui.selectFromList(                       # type: ignore
        [("%s - " % database.section_label(filename) if sections else "")
         + repair.copy_named_by_what_it_holds(filename, snap)
         for filename, _tier, snap, _current in offers],
        default_choices=(0,), exclusive=True,
        clear_on_cancel=True,    # without it Cancel answers the row that opened picked
        title=messages.TITLE_CHECK_LIBRARY, message=message, column_header=header)
    return offers[chosen[0]] if chosen else None


def _copy_buttons(older: bool) -> dict:
    """The confirm's buttons, with Older Copies where there are some; Cancel is Enter and close."""
    buttons = (messages.BUTTONS_PUT_COPY_BACK_OR_OLDER if older
               else messages.BUTTONS_PUT_COPY_BACK)
    return {"buttons": buttons, "default_choice": len(buttons) - 1,
            "close_choice": len(buttons) - 1}


def _put_copy_back(findings: dict, offer: tuple, guard: bool, changed, older: bool = False):
    """Confirm one copy and put it back; `older` when Older Copies was pressed instead."""
    filename, tier, snap, current = offer
    if filename == keyed_store.SETTINGS:
        return _do_restore_settings(findings, tier, snap, guard, changed, older=older)
    label = database.section_label(filename)
    if snap["error"]:
        _say(messages.CHOSEN_SAVED_COPY_CANNOT_BE_READ % label, hou.severityType.Warning)
        return None
    held = snap["count"] or 0
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
        title=messages.TITLE_CHECK_LIBRARY,
        **_copy_buttons(older))
    if older and picked == 1:
        return "older"
    if picked != 0:
        return None
    try:
        done = repair.put_back(findings, filename, tier, guard=guard)
    except restore_lib.RestoreRefused as exc:
        _say(str(exc), hou.severityType.Warning)
        return None
    changed()
    undo = (restore_lib.info(os.path.join(findings["directory"], done["undo"]))
            if done["undo"] else None)
    if undo is not None and undo["exists"]:
        went_back = messages.LIST_EARLIER_COPY_KEPT % undo["when"]
    else:
        went_back = messages.NO_EARLIER_LIST
    _say(messages.SAVED_COPY_PUT_BACK_DONE
         % (label, snap["when"], " " + done["said"] if done["said"] else "", went_back))
    return None


def _do_restore_settings(findings: dict, tier: str, snap: dict, guard: bool, changed,
                         older: bool = False):
    """Confirm and put a settings copy back, saying how to undo it; `older` as above."""
    if snap["error"]:
        _say(messages.SETTINGS_COPY_CANNOT_BE_READ, hou.severityType.Warning)
        return None
    way_back = findings["settings"]["state"] == "ok"
    picked = hou.ui.displayMessage(                       # type: ignore
        messages.CONFIRM_PUT_SETTINGS_BACK % snap["when"],
        help=messages.HELP_PUT_SETTINGS_BACK % (
            messages.SETTINGS_NOW_SAVED_FIRST if way_back else ""),
        severity=hou.severityType.Warning,                # type: ignore
        title=messages.TITLE_CHECK_LIBRARY,
        **_copy_buttons(older))
    if older and picked == 1:
        return "older"
    if picked != 0:
        return None
    try:
        done = repair.put_back(findings, keyed_store.SETTINGS, tier, guard=guard)
    except restore_lib.RestoreRefused as exc:
        _say(str(exc), hou.severityType.Warning)
        return None
    changed()
    folder = os.path.dirname(repair.target_of(findings, keyed_store.SETTINGS))
    undo = (restore_lib.info(os.path.join(folder, done["undo"]))
            if done["undo"] else None)
    kept = (messages.SETTINGS_EARLIER_COPY_KEPT % undo["when"]
            if way_back and undo is not None and undo["exists"] and not undo["error"]
            else "")
    _say(messages.SETTINGS_PUT_BACK_DONE % (snap["when"], kept))
    return None


def _moved(result: dict) -> None:
    """What a move aside did, and what it could not move."""
    if result["failed"]:
        _say(messages.FILES_MOVED_ASIDE_SOME_FAILED
             % (repair.files(len(result["moved"])), repair.files(len(result["failed"]))),
             hou.severityType.Warning)
    else:
        _say(messages.FILES_MOVED_ASIDE_DONE % repair.files(len(result["moved"])))


def _do_move_aside(findings: dict, guard: bool, changed) -> None:
    """The unlisted files `movable` leaves and the leftovers, in one move after one confirm."""
    aside = repair.movable(findings)
    unlisted = 0 if repair.why_unlisted_stay(findings) else repair.unaccounted_total(aside)
    leftovers = findings.get("leftovers") or []
    said = []
    if unlisted:
        said.append(messages.HELP_MOVE_UNLISTED % repair.files_by_folder(aside))
    if leftovers:
        said.append(messages.HELP_MOVE_LEFTOVERS % ", ".join(entry[0] for entry in leftovers))
    if not _confirmed(messages.CONFIRM_MOVE_FILES_ASIDE % repair.files(unlisted + len(leftovers)),
                      messages.BUTTONS_MOVE_ASIDE,
                      messages.HELP_MOVE_FILES_ASIDE % (
                          " ".join(said), messages.HELP_MOVE_UNLISTED_LAST if unlisted else "")):
        return
    what = (("unlisted",) if unlisted else ()) + (("leftovers",) if leftovers else ())
    try:
        result = repair.move_aside(findings, what, guard=guard)
    except ValueError as exc:
        _say(messages.NOTHING_MOVED_ASIDE_REASON % exc, hou.severityType.Warning)
        return
    if result["moved"]:
        changed()
    _moved(result)


def _do_move_unknown(findings: dict, guard: bool, changed) -> None:
    """The files and folders no name fits, after their own confirm naming each."""
    names = [entry[0] + "/" for entry in findings.get("unknown_folders") or ()] + [
        entry[0] for entry in findings.get("unknown") or ()]
    if not _confirmed(messages.CONFIRM_MOVE_UNKNOWN_ASIDE, messages.BUTTONS_MOVE_ASIDE,
                      messages.HELP_MOVE_UNKNOWN_ASIDE % ", ".join(sorted(names)), warn=True):
        return
    try:
        result = repair.move_aside(findings, "unknown", guard=guard)
    except ValueError as exc:
        _say(messages.NOTHING_MOVED_ASIDE_REASON % exc, hou.severityType.Warning)
        return
    if result["moved"]:
        changed()
    _moved(result)


def _do_set_aside(findings: dict, guard: bool, changed) -> None:
    """Folders not on this computer set aside, and stars on files that are gone dropped too."""
    dead, stars = findings.get("dead_folders") or [], findings.get("dead_stars") or []
    if dead:
        asked = _confirmed(messages.CONFIRM_SET_ASIDE_FOLDERS % repair.folders(len(dead)),
                           messages.BUTTONS_SET_ASIDE, messages.HELP_SET_ASIDE_FOLDERS
                           % (messages.HELP_DEAD_STARS_GO_TOO if stars else ""))
    else:
        asked = _confirmed(messages.CONFIRM_REMOVE_DEAD_STARS % repair.favorites(len(stars)),
                           messages.BUTTONS_REMOVE)
    if not asked:
        return
    try:
        folders = repair.set_aside_folders(findings, guard=guard) if dead else []
        gone = repair.drop_dead_stars(findings, guard=guard) if stars else []
    except ValueError as exc:
        _say(messages.NOTHING_CHANGED_REASON % exc, hou.severityType.Warning)
        return
    if folders or gone:
        changed()
    if folders:
        _say(messages.FOLDERS_SET_ASIDE_DONE % (
            repair.folders(len(folders)),
            messages.DEAD_STARS_ALSO_REMOVED % repair.favorites(len(gone)) if gone else ""))
    else:
        _say(messages.DEAD_STARS_REMOVED_DONE % repair.favorites(len(gone)))


def _do_uncategorised(findings: dict, guard: bool, changed) -> None:
    """Every row with no category put in Uncategorized, after one confirm."""
    counted = repair.uncategorised_count(findings)
    if not _confirmed(messages.CONFIRM_PUT_IN_UNCATEGORIZED % (counted, repair.UNCATEGORISED),
                      messages.BUTTONS_PUT_THEM_THERE, messages.HELP_PUT_IN_UNCATEGORIZED):
        return
    try:
        done = repair.rescue_uncategorised(findings, guard=guard)
    except ValueError as exc:
        _say(messages.NOTHING_CHANGED_REASON % exc, hou.severityType.Warning)
        return
    if done:
        changed()
    _say(messages.PUT_IN_UNCATEGORIZED_DONE % (
        repair.uncategorised_count({"uncategorised": {
            filename: [None] * count for filename, count in done.items()}}),
        repair.UNCATEGORISED))


def _do_reattach(findings: dict, guard: bool, changed) -> None:
    """Pick the section the unsorted pairs belong to, confirm, add them, and say how many."""
    pairs = repair.unsorted_pairs(findings)
    owners = database.ASSET_FILE_OWNERS
    labels = [database.section_label(name) for name in owners]
    chosen = hou.ui.selectFromList(                       # type: ignore
        labels, exclusive=True, title=messages.TITLE_CHECK_LIBRARY,
        message=messages.PICK_SECTION_FOR_FILES
                % repair.files(len(repair.reattachable_files(findings))),
        column_header=messages.COLUMN_SECTION)
    if not chosen:
        return
    filename = owners[chosen[0]]
    label = database.section_label(filename)
    noun = database.section_noun(filename, len(pairs))
    if not _confirmed(messages.CONFIRM_ADD_UNLISTED_TO_SECTION % (len(pairs), noun, label),
                      messages.BUTTONS_ADD_BACK,
                      messages.HELP_ADD_TO_SECTION
                      % (repair.RECOVERED_CATEGORY, repair.RECOVERED_CATEGORY, label)):
        return
    try:
        result = repair.reattach(findings, filename, only=pairs, guard=guard)
    except ValueError as exc:
        _say(messages.SECTION_LIST_UNCHANGED_REASON % (label, exc), hou.severityType.Warning)
        return
    changed()
    count = len(result["added"])
    noun = database.section_noun(filename, count)
    minted = len(result["minted"])
    if minted:
        said = messages.UNLISTED_FILES_ADDED_BACK_SOME_UNNAMED % (
            count, noun, label, minted, repair.RECOVERED_CATEGORY)
    else:
        said = messages.UNLISTED_FILES_ADDED_BACK_DONE % (count, noun, label)
    _say(said)
