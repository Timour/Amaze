"""Repair: what is wrong with this library, and what is safe to do.

Clean Library's opposite number, and the split is the design:

    | |Clean Library|Repair|
    |deletes    |yes, permanently|NEVER|
    |runs when  |the library is coherent|especially when it is NOT|
    |answers    |"tidy what is settled"|"what is wrong, what is safe"|

Clean Library refuses when it cannot tell a leftover from somebody's
asset, and a refusal with no way out is an outage wearing a safety hat.
This is the way out. It reads, it reports in plain words, and the
strongest thing it may do is MOVE files into a dated folder inside the
library - never `os.remove`, never `shutil.rmtree`, not once, not on a
confirmation.

*** WHY THIS IS A SHELF TOOL AND NOT A PANEL COMMAND. ***

practice.md ▸ Restoring a database opens its procedure with "QUIT
HOUDINI. A running panel writes the index on many actions and will
overwrite whatever you put back", and records that a restore races the
panel's own deferred save timers. A list put back from inside the panel
is overwritten by its own host seconds later and the user is left
believing they recovered - which converts a recoverable library into a
confident wrong belief. That is worse than no tool at all.

So Repair runs from the shelf, where the panel is closed, nothing holds
a model, and nothing is about to flush a deferred save. It also means
Repair works when the panel will not open, which is the case it exists
for - and it is why nothing in this module imports the panel or builds a
model.

For the same reason it REFUSES TO CHANGE ANYTHING while a library is
open in this Houdini session, and that refusal is read from code rather
than guessed: `DatabaseConnector.load()` is gated on `if not self._data`
(database.py), so a connector that has already read a list will NOT
re-read it - it holds the OLD document and the next save writes that
document back over anything put back here. The report is always safe and
always runs; changing needs a session that has not opened a library yet.
There is deliberately no detect-and-latch cleverness around a live
panel: a pgrep-wait pattern was once written up here as if it were
system behaviour and never existed. One honest refusal beats a
mechanism nobody has measured.

NOT debug.alert, and that is not an oversight. That sink is for telling
someone something they did not ask about - deferred to the next event
loop turn so it cannot steal a drop's release click, and shown once per
session so a condition inside a loop cannot produce ten dialogs. Every
dialog here is the opposite: the user clicked Repair and is waiting for
an answer, the answer decides what happens next, and running Repair
twice must say it twice. Its findings go to debug.event either way, so
the log carries the whole run.
"""

import datetime
import json
import os

import hou

from amaze.core import database, debug, material
from amaze.core.library import STAMP_SUFFIX
from amaze.helpers import hostos, restore as restore_lib
from amaze.prefs import prefs as prefs_module


#: Every list Repair knows how to read, in the order the panel shows
#: them. gradients.json is here although it has no DatabaseConnector -
#: it is the least protected file in the library (no rolling copies at
#: all on the real one) and therefore the one most worth reporting on.
DATABASES = ("library.json", "cops.json", "code.json", "gradients.json")

#: Every file suffix an asset row owns in the asset folder - the ONE
#: home for the set. Clean Library sweeps with these and the survey
#: classifies with them, and the rehearsal test builds its expectation
#: FROM here: a hand-rolled copy went stale twice, first missing
#: .stamp.json, then .builder.json - each time on the first real
#: library that had saved under the newer writer.
ASSET_SIDECARS = (".mat", ".interface", ".builder.json", ".stamp.json")


def side_tables() -> tuple:
    """The keyed side tables, from the ONE registry that declares them.

    Repair used to know only the four lists above, while BOTH side
    tables' unreadable alerts send the user here by name - "put back a
    recent copy with the Repair tool in the Amaze shelf" - and Repair
    then surveyed neither and offered neither. `tools/library-audit.py`
    kept the same list and grew the side tables on 2026-08-02; this copy
    stayed narrow and nothing went red, because a hand-written list is
    only as long as whoever last edited it remembered.
    """
    from amaze.core import keyed_store
    return keyed_store.filenames()

#: What a re-attached asset is called. It is not a guess dressed up as a
#: fact: the name, categories and tags lived ONLY in the list, and the
#: files do not carry them (research.md - name/renderer strings appear
#: in an asset file partly by coincidence, with no labelled field to
#: read them from, and tags and date are absent outright).
RECOVERED_CATEGORY = "Recovered"


def configured_library(preferences=None) -> str:
    """The library folder the settings NAME, whether or not it is there.

    Kept apart from library_directory because the two answers earn two
    different messages, and merging them was a WRONG DIAGNOSIS: nothing
    configured yet is a fresh install and sends the reader to Preferences,
    while a folder that is named and not reachable is an unmounted drive
    or a synced folder that is not online. Telling that second reader they
    have no library, and pointing them at Preferences, is how somebody
    re-points Amaze at an empty folder and loses the library from the
    panel. A wrong diagnosis costs more than none.

    Takes preferences so a test can inject a fixture library; falls back
    to reading the user's settings, which is what the shelf tool does.
    Prefs.load() degrades to "unconfigured" rather than raising (it is
    read with a default on every key for exactly this reason), so a
    settings file that will not parse lands here as "" and gets the same
    honest answer as a fresh install."""
    if preferences is None:
        preferences = prefs_module.Prefs()
        preferences.load()
    return str(getattr(preferences, "dir", "") or "")


def library_directory(preferences=None) -> str:
    """The library folder if Amaze can look inside it, else ""."""
    directory = configured_library(preferences)
    return directory if directory and os.path.isdir(directory) else ""


def survey(directory: str, asset_dir: str = "mat/",
           img_dir: str = "img/") -> dict:
    """READ ONLY: everything Repair knows, gathered once.

    Returns a dict the report and every action work from, so the sentence
    on screen and the file that gets moved can never come from two
    different readings of the disk.

    `complete` is the important one. It is True only when every list
    either read cleanly or is genuinely absent with nothing saying it was
    ever here - i.e. when the union of ids is the WHOLE union. While it
    is False, no file may be called unclaimed: ORPHANHOOD IS RELATIVE TO
    EVERY LIST SHARING THE DIRECTORY (measured: 548 + 8 = 556 .mat files,
    exactly), and a file belonging to a list nobody could read looks
    identical to a leftover. Twice now that reasoning has produced a
    confident deletion of live assets - once in code, once by hand. So
    the report says so, and quarantine is not offered at all.

    A FOLDER AMAZE COULD NOT LOOK INSIDE counts against `complete` for
    the same reason a list that will not parse does. It is the most
    measured broken state in this project - the small json arriving
    before the big folder on a second machine - and reporting it as
    "every file is accounted for" would be a false all-clear from the one
    tool whose job is to say what is wrong."""
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
            # The SAME kinds Clean Library sweeps with - a builder
            # sidecar or recovery stamp whose asset row is gone must
            # count here too, or the two tools report different numbers
            # about one folder (the exact bug this module's own
            # docstring forbids).
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
    """One list: what state it is in, what it holds, and what copies sit
    beside it."""
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
        # ABSENT IS ONLY "NEW" WHEN NOTHING SAYS THE FILE WAS EVER HERE.
        # The same question load() and Clean Library both ask, answered by
        # the same function, because three callers disagreeing about
        # whether a library is new is how an empty list was seeded over
        # eight live assets.
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
        # A side table's payload is a MAPPING, so the list shape test
        # would call every healthy one malformed. Its own test is the
        # one the store itself loads through, plus the same
        # payload-key-present rule: a file holding the OTHER store's
        # key parses, reads as empty, and is not this store's file.
        malformed = database.wrong_table_shape(document, spec.payload)
        if not malformed and spec.payload not in (document or {}):
            malformed = ("it holds no %r, so it is not the %s file"
                         % (spec.payload, spec.label))
    elif filename == "gradients.json":
        # The Colors list is not shaped like the others (its own
        # format, no connector), so the database shape test does not
        # apply to it.
        malformed = ""
    else:
        malformed = database.wrong_shape(document)
    if malformed or facts["count"] is None:
        # VALID JSON IS NOT A VALID LIST, and the same classifier the
        # connector and Clean Library use decides it here too. `count is
        # None` catches the Colors file the same way without needing a
        # second shape test for it: a document nothing can be counted in
        # is one nobody can read, and calling it EMPTY instead would say
        # "there is nothing here" about a file that may be full.
        entry["state"] = "unreadable"
        entry["info"] = dict(
            facts,
            error=malformed or "it is not shaped like a list Amaze wrote")
        return entry
    for row in (document.get("assets") or []):
        if isinstance(row, dict):
            entry["ids"].add(str(row.get("id", row.get("mat_id", ""))))
    entry["state"] = "empty" if not facts["count"] else "ok"
    return entry


def _unlisted_in(directory: str, folder: str, extensions: tuple, tail: str,
                 known_ids: set):
    """Names of the files in one of the library's own folders that no list
    accounts for, or None when the folder could not be read at all.

    The SAME classifier Clean Library sweeps with
    (database.asset_id_for_file), so Repair cannot report a different set
    of files than Clean Library refused over. Two tools telling the user
    two different numbers about one folder is its own bug.

    None, not [] - the rule its sibling in library.py
    (_files_no_section_accounts_for) already states: "a handler that
    returns a neutral value makes a failure indistinguishable from an
    honest empty result". Returning [] here read a folder that has not
    synced down as a folder with nothing unaccounted for, and printed
    "every file is accounted for" about a folder nobody had seen, while
    Clean Library refused outright over the same directory."""
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


def rebuild_from_stamps(directory: str, asset_dir: str = "mat/") -> dict:
    """Reconstruct a library index from the per-asset recovery stamps.

    THE DISASTER PATH, and the only reader of a stamp. Before stamps
    existed the answer to "can this library survive losing
    library.json?" was measured and it was NO: the asset files carry no
    tags, no description, no favourite, no date, and no labelled field
    to read a name or category out of (research.md).

    Returns {"assets": [...], "categories": [...], "tags": [...],
    "damaged": [...]} - a document in the shape library.json holds, plus
    the ids whose stamp could not be read.

    WHAT COMES BACK AND WHAT DOES NOT. Every per-asset field returns,
    because the stamp is the asset's whole record. Cross-asset state
    does not: the ORDER of categories, and their colours, are library
    facts rather than asset facts and live only in the index. Categories
    and tags are re-derived from the union of what the assets name, so
    the set survives and the arrangement does not.

    One damaged stamp costs its own asset and nothing else. The rebuild
    completes and names it - a partial library the owner can see is
    worth more than a refusal they cannot act on.
    """
    folder = os.path.join(directory, asset_dir)
    assets, damaged = [], []
    categories, tags = [], []
    try:
        names = sorted(os.listdir(folder))
    except OSError as exc:
        debug.event("repair", "cannot read the asset folder for a rebuild",
                    folder=folder, error=str(exc))
        return {"assets": [], "categories": [], "tags": [], "damaged": []}

    for name in names:
        if not name.endswith(STAMP_SUFFIX):
            continue
        asset_id = name[: -len(STAMP_SUFFIX)]
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                record = json.load(handle)
            if not isinstance(record, dict):
                raise ValueError("top level is not an object")
        except (OSError, ValueError) as exc:
            debug.event("repair", "recovery stamp unreadable",
                        asset_id=asset_id, error=str(exc))
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


def unaccounted_total(findings: dict) -> int:
    return sum(len(names) for names in findings["unaccounted"].values())


def restorable(findings: dict) -> list:
    """(filename, tier, snapshot info, current info) for every copy that
    could be put back - newest first within each list, lists in panel
    order. A healthy list is included: rolling one back is a legitimate
    thing to want, and only offering it for a broken one would be a
    guess about why the user came here."""
    offers = []
    for entry in findings["lists"]:
        for tier, snap in entry["snapshots"]:
            offers.append((entry["filename"], tier, snap, entry["info"]))
    return offers


# ---------------------------------------------------------------------
# What the user reads. Every sentence in this section is the product;
# the code above only decides which of them are true.
# ---------------------------------------------------------------------

def _holdings(entry: dict) -> str:
    """"548 saved materials" - the count with the word for what was
    counted. "548 saved" asks the reader to supply the noun, and for
    Colors the number is colours while for Code it is snippets."""
    count = entry["info"]["count"] or 0
    return "%d saved %s" % (
        count, database.section_noun(entry["filename"], count))


def _copy_named_by_what_it_holds(filename: str, snap: dict) -> str:
    """"from 2026-07-27 20:31, 8 saved nodes" - a saved copy named by the
    only two things that can answer "which one do I want".

    NEVER BY ITS TIER. "bak-1" and "bak-first" are storage suffixes;
    nothing on screen or anywhere in Houdini has ever shown them, so
    asking someone to choose between them under pressure is asking them
    to guess. The date and the count are the identity, and they are what
    the real library's copies differ by (measured: cops.json bak-1 8
    assets, bak-2 6, bak-first 2)."""
    if snap["error"]:
        return "from %s, cannot be read" % snap["when"]
    count = snap["count"] or 0
    return "from %s, %d saved %s" % (
        snap["when"], count, database.section_noun(filename, count))


def _snapshot_line(entry: dict) -> str:
    """What the copies beside a list would bring back."""
    if not entry["snapshots"]:
        # WHAT WAS NOT DAMAGED, in the same breath as the limit. "There is
        # nothing to put back" on its own reads as "your work is gone",
        # and for a list it is not: the materials are files in the folder,
        # and a list Amaze cannot read has not touched them.
        line = ("%s: there are no saved copies of this list beside it, so "
                "there is nothing to put back." % entry["label"])
        if entry["filename"] in database.ASSET_FILE_OWNERS:
            # ONLY WHERE IT IS TRUE. Code keeps its snippets inline and
            # Colors keeps its ramps inline, so for those two sections
            # there are no files of their own in the folder and the
            # reassurance would point at nothing - a reassurance that is
            # not quite true is worse than none, because the reader stops
            # believing the next one.
            line += (" Your %s' own files and thumbnails are still in the "
                     "library folder either way."
                     % database.section_noun(entry["filename"], 2))
        return line
    parts = [_copy_named_by_what_it_holds(entry["filename"], snap)
             for _tier, snap in entry["snapshots"]]
    return "%s: saved copies - %s." % (entry["label"], "; ".join(parts))


def _and_list(words) -> str:
    """"a, b and c" - the user's punctuation, not a comma-joined list.

    "Materials", "Materials and Nodes", "Materials, Nodes and Code".

    There were TWO of these at module level (this one and a second at
    the report end), so the later definition silently won for all five
    call sites, including the two written against this one. They agreed
    on every input, so nothing was ever wrong - but an edit to the one
    that lost would have changed nothing, with no error to say so.
    """
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return "%s and %s" % (", ".join(words[:-1]), words[-1])


def report_lines(findings: dict) -> list:
    """The whole report, in the user's words.

    No index, no record, no row, no database, no session, no merge, no
    schema, no orphan, no stale. The library, your materials, the folder,
    the file, the list, saved copies. A user who cannot tell from this
    what is wrong and what happens next has been handed a log, not a
    report.

    "Section" is the one word here the user has never seen on a control -
    the tabs say Materials, Nodes, Code and Colors - so the first line
    introduces it against those four names rather than leaving it to be
    inferred four paragraphs later."""
    # Without the rstrip the sentence ends in "/." - prefs keeps the
    # library path with its separator because everything else joins onto
    # it, and a full stop after a slash reads as a typo.
    # The SIDE TABLES are named from the registry, not spelled out
    # here. This sentence introduced four sections and then the report
    # listed six things, because Repair learned the side tables
    # (2026-08-03) and the sentence above them did not - which is the
    # same drift, one line higher, that the registry exists to end.
    from amaze.core import keyed_store
    extra = [spec.label.lower() for spec in keyed_store.stores()
             if spec.in_library]
    also = ""
    if extra:
        also = (", and one%s for the %s you add to them"
                % (" each" if len(extra) > 1 else "", _and_list(extra)))
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
            # THE TRACE IS NOT NAMED HERE. "and cops.json.bak-1 beside it
            # says there was one" gives "beside it" no antecedent - the
            # list is the thing that is not there - and names a file in a
            # sentence that does not send anybody to touch it. Clean
            # Library names it, because that message does.
            lines.append(
                "%s: there is no list for it in the library folder, though "
                "Amaze can see there was one here before. If this folder "
                "syncs, it may still be on its way - give it a minute and "
                "run Repair again." % label)
        else:
            lines.append("%s: nothing saved here yet." % label)

    if empty:
        # ONE line for all of them, not one per section: two empty
        # sections used to produce two near-identical thirty-word
        # sentences in one dialog, which is the nagging the aggregate
        # rule exists to prevent. Clean Library teaches this same
        # ambiguity; the tool the refusal sends people to may not say
        # less about it than the refusal did.
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
        # NAME THE SECTION, do not point at the dialog. "a list above
        # could not be read either" makes the reader count paragraphs,
        # and "some of them may well be its" makes them parse a
        # possessive to find out whether their assets are at risk.
        lines.append(
            "No section lists %s. Amaze could not check the %s list either, "
            "so some of those files may be its. Nothing will be moved "
            "while that is true."
            % (_files_by_folder(findings), _and_list(unchecked)))
    else:
        lines.append("Every file in the library's own folders is accounted "
                     "for by a section.")

    if troubled:
        lines.append("")
        for entry in troubled:
            lines.append(_snapshot_line(entry))

    return lines


def _files(count: int) -> str:
    """"1 file" / "3 files". The engineer's "file(s)" is the plural of a
    program, not of English, and it lands in the sentences somebody acts
    on."""
    return "1 file" if count == 1 else "%d files" % count


def _files_on_a_button(count: int) -> str:
    """"2 Files" - the same count, capitalised for a button label, since
    every other button in this tool is Title Case and one lowercase word
    in the row reads as a typo."""
    return _files(count).replace("file", "File")


def _and_folders(folders: list) -> str:
    return _and_list(["%s folder" % _folder_name(folder)
                      for folder in folders])


def _files_by_folder(findings: dict) -> str:
    """"2 files in the mat folder (A.mat, A.interface) and 1 file in the
    img folder (A_icon.png)".

    FOLDER BY FOLDER, never as one total: Clean Library weighs the asset
    folder alone, so a combined number here would have the refusal saying
    2 and the tool it sends you to saying 3 about one library. The names
    are given while there are few of them, because the next dialog offers
    to move these files and "2 in mat" is not something anybody can check
    before clicking."""
    parts = []
    for folder, names in findings["unaccounted"].items():
        if not names:
            continue
        part = "%s in the %s folder" % (_files(len(names)),
                                        _folder_name(folder))
        if unaccounted_total(findings) <= 6:
            part += " (%s)" % ", ".join(names)
        parts.append(part)
    return _and_list(parts)


def _what_can_be_added_back(findings: dict) -> list:
    """The line that keeps the two buttons apart.

    Adding back takes only complete pairs; moving aside takes everything
    unaccounted for. With three unlisted files where one is half a
    material, two buttons act on two different sets and nothing on screen
    said so - and "unlisted" against "unclaimed" read as a synonym rather
    than a distinction."""
    addable = _reattachable_files(findings)
    total = unaccounted_total(findings)
    if not addable or len(addable) == total:
        return []
    return ["Of those, %s can be added back to a section. The rest are "
            "halves of an asset whose other file is not in the folder, so "
            "they can only be moved aside." % _files(len(addable))]


def _folder_name(folder: str) -> str:
    return str(folder).rstrip("/\\") or folder


# ---------------------------------------------------------------------
# The actions. Two of them write; neither can delete.
# ---------------------------------------------------------------------

#: Why no action may run from a Houdini that has read the library, as a
#: phrase the callers' refusal sentences carry whole. Worded without a
#: full stop at the end so "Amaze moved nothing: %s." composes cleanly.
_SESSION_HOLDS_THE_LIBRARY = (
    "this Houdini has already read the library and would write what it "
    "remembers back over the change - quit Houdini, start it again, and "
    "run Repair before you open Amaze")


def _refuse_a_houdini_that_holds_the_library(refusal=ValueError) -> None:
    """EVERY ACTION ENFORCES THIS FOR ITSELF, before touching anything.

    run() checks the same thing to decide which buttons exist, and the
    first version stopped there - which made the guard a property of one
    UI helper rather than of the operations. Any other route to these
    functions (a future menu item, a shelf script, somebody driving the
    module from the Python shell) would have changed a library that this
    process is about to overwrite from memory. The operations are where
    the danger is, so the operations are where the guard lives; the
    button logic is a courtesy on top."""
    if session_has_a_library_open():
        raise refusal(_SESSION_HOLDS_THE_LIBRARY)


def quarantine(findings: dict) -> dict:
    """MOVE every unclaimed file into THE quarantine - the same
    machine-local one Clean Library uses. Returns {"folder", "moved",
    "failed"}.

    The strongest thing Repair may do. This wrote to its own
    <library>/_removed_<date>/ until 2026-07-31, which the campaign had
    already ruled out for Clean Library three times over: it grows
    inside the library forever, it breaks the no-temporary-files rule,
    and it puts the recovered copies inside the very synced tree the
    worst case arrives through. Two tools with two quarantines is also
    two answers to "where did my file go". One location now, one
    30-day window, one place to look - named in the report.

    Refuses outright while any list is unreadable. Moving a file whose
    owner could not be read is moving data on a guess, and that guess has
    already cost this project real assets twice.

    Also refuses a Houdini that has already read the library - for
    itself, not by trusting run() to have asked. A moved file is not
    overwritten by a later save the way a restored list is, but the
    decision to move it was made against findings this process's own
    memory is about to invalidate."""
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
            # The shared mover: same destination, same collision rule,
            # same 30-day retention as Clean Library's sweep.
            if library_mod.quarantine_file(findings["directory"], source):
                moved.append(name)
            else:
                # SAY WHY on every failure - "3 moved" with two silently
                # left behind is a report that lies by omission.
                debug.event("repair", "file could not be moved aside",
                            file=source)
                failed.append(name)
    debug.event("repair", "unclaimed files moved aside", folder=root,
                moved=len(moved), failed=len(failed))
    return {"folder": root, "moved": moved, "failed": failed}



def reattach(findings: dict, filename: str) -> dict:
    """Add a row to `filename` for every unclaimed asset pair, so the
    files stop being unclaimed. Returns {"added": [ids], "path": ...}.

    ONLY a complete pair (<id>.mat AND <id>.interface) is offered: one
    half of a pair is not an asset, and inventing a row for it would put
    a tile in the panel that cannot open.

    WHAT THIS CANNOT RECOVER, and the caller says so before asking: the
    name, the categories, the tags and the date lived only in the list.
    They are not in the files (research.md - a renderer or name string
    turns up in an asset file partly by coincidence, with no labelled
    field to read it from). So a re-attached asset comes back under a
    plain name in one new category, and the renderer field is left empty
    rather than guessed at. Import does not consult it - the node type
    comes from the saved file itself - so the asset works; the badge is
    blank until it is saved again.

    Rows are built by Material itself and written with get_as_dict, not
    hand-assembled here, so the shape cannot drift from what the app
    writes.

    Refuses a Houdini that has already read the library - for itself,
    like quarantine and put_back: a row added to a list this process
    holds in memory is erased by that process's next save, whoever
    called."""
    _refuse_a_houdini_that_holds_the_library()
    if not findings["complete"]:
        raise ValueError("one of the library's lists cannot be read, so "
                         "these files may belong to it")
    path = os.path.join(findings["directory"], filename)
    document, error = restore_lib.read_document(path)
    malformed = error or database.wrong_shape(document)
    if malformed:
        # NO RAW EXCEPTION TEXT ON SCREEN. The reason goes to the log, and
        # the sentence the caller shows is complete without it.
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
    """The ids among the unclaimed files that have BOTH halves in the
    asset folder, in a stable order."""
    halves = {}
    for name in findings["unaccounted"].get(findings["asset_dir"], []):
        asset_id = database.asset_id_for_file(
            name, (".mat", ".interface"), "_cop")
        if not asset_id:
            continue
        halves.setdefault(asset_id, set()).add(
            os.path.splitext(name)[1].lower())
    return sorted(asset_id for asset_id, seen in halves.items()
                  if {".mat", ".interface"} <= seen)


def _reattachable_files(findings: dict) -> list:
    """Every unlisted FILE that adding a pair back would account for -
    both halves, and the thumbnail beside them.

    Counted in files rather than in assets because that is the unit the
    other button is counted in, and the two numbers are only comparable
    if they count the same thing."""
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
    """Write a list back, keeping the app's own formatting (indent 4) so
    the next real save produces a minimal diff in a synced folder.

    THROUGH THE PACKAGE'S OWN SCRATCH-AND-PROMOTE, not a hand-rolled one.
    unique_scratch cannot collide with another writer's buffer (a fixed
    name was measured producing 794 reads that PARSED while holding
    records from both writers), and promote_scratch carries the fsync and
    the permission rule this project paid for twice - preserve the
    destination's mode, EXCEPT 0600, which is our own earlier bug's
    fingerprint. Writing this by hand would have narrowed the one library
    file that is 0666 on the real machine down to the umask default, and
    narrowing is the direction that locks a colleague out of a shared
    library silently.

    NOT write_json_atomic, which is the same thing plus
    snapshot_before_write: that rotates the rolling copies, and the copy
    it would rotate out is one the user may be about to restore from. A
    recovery tool must not spend the evidence."""
    scratch = hostos.unique_scratch(path, suffix=".repairing")
    try:
        # newline="\n" for the same reason write_json_atomic carries it:
        # this writes the SAME database documents, so a repair that left
        # CRLF behind on Windows would defeat save()'s identical-write
        # guard and have the next ordinary save rewrite the file - the
        # bug that keyword fixes, arriving through the one door that
        # deliberately does not go through that function.
        with open(scratch, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)
    except OSError:
        hostos.discard_scratch(scratch)
        raise
    hostos.promote_scratch(scratch, path)


def put_back(findings: dict, filename: str, tier: str) -> dict:
    """Put one saved copy back, through the same code the terminal tool
    uses. A second implementation of a restore is a second answer.

    Refuses a Houdini that has already read the library - FOR ITSELF,
    not by trusting the caller. restore_lib.put_back leaves that to
    whoever calls it because the terminal tool cannot know about
    connectors; this function can, it is the one Houdini route to a
    restore, and a list put back under a live connector is overwritten
    by that connector's next save while the user believes they
    recovered. Raised as RestoreRefused so the caller's one refusal
    path shows it whole."""
    _refuse_a_houdini_that_holds_the_library(
        lambda phrase: restore_lib.RestoreRefused(
            "Nothing was put back: %s." % phrase))
    target = os.path.join(findings["directory"], filename)
    # allow_loss: THIS caller has already informed the choice. The
    # picker names every copy by date and record count and the report
    # names what the list holds now, so a smaller copy chosen here is
    # chosen knowingly. The refusal exists for the blind path - the
    # terminal tool restoring a parseable-but-empty snapshot with no
    # counts shown anywhere - and that path keeps it.
    done = restore_lib.put_back(target, tier, allow_loss=True)
    debug.event("repair", "saved copy put back", file=filename, tier=tier,
                undo=done["undo"])
    return done


# ---------------------------------------------------------------------
# The shelf tool's own flow: the guards, one report, then the choice.
# ---------------------------------------------------------------------

def open_panel_tab():
    """An Amaze panel tab in the current desktop, or None.

    Reads Houdini's own pane list - it does NOT import or construct
    anything of Amaze's, which is the whole point: this runs when the
    panel cannot be built."""
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
    """Whether anything in this Houdini session has already read a list.

    One connector exists per file for the whole process and load() is
    gated on `if not self._data`, so a connector that has read a list
    holds that document until the process ends - and its next save writes
    that document, not what is on disk. Anything put back now would be
    overwritten by it. Includes the case where the panel was opened and
    closed again, which is exactly how someone arrives here."""
    return bool(database.DatabaseConnector._instances)


def run(preferences=None) -> None:
    """The shelf tool. Reports always; changes only from a Houdini that
    has not opened a library yet."""
    configured = configured_library(preferences)
    if not configured:
        hou.ui.displayMessage(                           # type: ignore
            "Amaze has no library folder yet.\n\n"
            "Open Amaze and pick one in Preferences, then run Repair "
            "again.",
            title="Amaze Repair")
        return
    if not os.path.isdir(configured):
        # A DIFFERENT SITUATION AND A DIFFERENT MESSAGE. Telling somebody
        # with an offline drive that they have no library, and sending
        # them to Preferences, is how a library gets re-pointed at an
        # empty folder.
        hou.ui.displayMessage(                           # type: ignore
            "Amaze cannot reach the library folder it is set to use:\n\n%s"
            "\n\nNothing was changed. If it is on a drive or in a synced "
            "folder, connect it and run Repair again. If you moved the "
            "library, open Amaze and point Preferences at the new place."
            % configured,
            title="Amaze Repair")
        debug.event("repair", "refused - the library folder is not there",
                    path=configured)
        return
    directory = configured

    panel = open_panel_tab()
    if panel is not None:
        # ONE HONEST REFUSAL, AND THE WAY OUT IS THE WHOLE POINT OF IT.
        # Nothing here tries to work around a live panel: it writes the
        # list on many actions and on timers nobody here has measured, so
        # anything put back would be overwritten within seconds and the
        # user would believe they had recovered.
        #
        # "Close Amaze, then run Repair again" was the first wording and
        # it was a next step that does NOT work: one connector per file
        # lives for the whole process, so closing the panel leaves the
        # lists in memory and the second run lands on the paragraph below
        # with no buttons. Only quitting Houdini empties them, so that is
        # what the sentence says. Not Warning severity either: nothing was
        # attempted and nothing is at risk - alarm is a budget, and it is
        # spent on the restore confirm.
        hou.ui.displayMessage(                           # type: ignore
            "Amaze is open, so Repair stopped before reading anything.\n\n"
            "An open Amaze saves the library while you work, and it would "
            "write over anything Repair put back. Quit Houdini, start it "
            "again, and run Repair before you open Amaze.",
            title="Amaze Repair")
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
        title="Amaze Repair",
    )
    action = actions[picked] if 0 <= picked < len(actions) else None
    if action == "restore":
        _do_restore(findings)
    elif action == "quarantine":
        _do_quarantine(findings)
    elif action == "reattach":
        _do_reattach(findings)


def _choices(findings: dict, may_change: bool):
    """The buttons, and only the ones that would change something. A
    button offering a route that cannot work is the failure practice.md
    names by name."""
    choices, actions = [], []
    if may_change and restorable(findings):
        choices.append("Put a Saved Copy Back")
        actions.append("restore")
    if may_change and findings["complete"] and _complete_pairs(findings):
        # THE COUNT IS ON THE BUTTON, and it is not decoration: this one
        # acts on the complete pairs and the next one on everything
        # unaccounted for, which are different sets whenever a half file
        # is lying about. "Files" in both, too - "unlisted" against
        # "unclaimed" read as a synonym and hid the distinction.
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
        labels, exclusive=True, title="Amaze Repair",
        message="Which saved copy should Amaze put back?",
        column_header="Saved copies")
    if not chosen:
        return
    filename, tier, snap, current = offers[chosen[0]]
    label = database.section_label(filename)
    if snap["error"]:
        # NOT "cannot be read EITHER" - the list this copy belongs to may
        # be perfectly healthy, and a picker deliberately offers those
        # too, so "either" sends the reader looking for a second fault
        # that is not there.
        hou.ui.displayMessage(                            # type: ignore
            "That copy of the %s list cannot be read, so Amaze left "
            "everything alone. Try another copy." % label,
            title="Amaze Repair")
        return
    # NAME WHAT IT RECOVERS AND WHAT IT WOULD LOSE - and DO THE
    # SUBTRACTION. A confirm that only names the loss is answered with
    # Cancel forever; one that only names the gain is a trap; and one
    # that hands over two numbers under pressure leaves the reader to
    # work out that 548 -> 8 is 540 gone, which is the whole decision.
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
        "Put the %s list back to the copy from %s?" % (label, snap["when"]),
        help="That copy is from %s and holds %d %s. %s\n\nYour %s' own "
             "files and thumbnails are not touched either way, and the "
             "list you have now is saved in the library folder first - "
             "run Repair again and it offers that copy back."
             % (snap["when"], held, database.section_noun(filename, held),
                change, database.section_noun(filename, 2)),
        buttons=("Put This Copy Back", "Cancel"),
        default_choice=1, close_choice=1,
        severity=hou.severityType.Warning,                # type: ignore
        title="Amaze Repair",
    ) != 0:
        return
    try:
        done = put_back(findings, filename, tier)
    except restore_lib.RestoreRefused as exc:
        hou.ui.displayMessage(str(exc), title="Amaze Repair")  # type: ignore
        return
    # THE UNDO NAMES A ROUTE THE TOOL ACTUALLY HAS. The copy of the
    # previous state is one of the copies snapshots() offers, so "run
    # Repair again and put it back" is a step somebody can follow -
    # earlier this said "this can be undone by putting that one back"
    # while the picker could not list it at all. The copy put_back
    # actually made, by the name it returned - each restore writes its
    # own timestamped one now, so a guessed fixed name would point at
    # the wrong restore's copy or at nothing.
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
        "The %s list is back to the copy from %s.\n\nOpen Amaze to look at "
        "it. %s" % (label, snap["when"], went_back),
        title="Amaze Repair")


def _do_quarantine(findings: dict) -> None:
    total = unaccounted_total(findings)
    if hou.ui.displayMessage(                             # type: ignore
        "Move %s aside?" % _files(total),
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
        buttons=("Move Them Aside", "Cancel"),
        default_choice=1, close_choice=1,
        title="Amaze Repair",
    ) != 0:
        return
    try:
        result = quarantine(findings)
    except ValueError as exc:
        # Unreachable through the buttons - _choices does not offer this
        # while a list is unreadable - and handled anyway, because "the
        # button cannot be there" is a claim about a different function.
        hou.ui.displayMessage(                            # type: ignore
            "Amaze moved nothing: %s." % exc,             # a sentence
            title="Amaze Repair")
        return
    if result["failed"]:
        hou.ui.displayMessage(                            # type: ignore
            "%s moved into Amaze's holding folder on this computer - "
            "outside your library, kept for 30 days. %s could not be "
            "moved and are still where they were - nothing was lost "
            "either way."
            % (_files(len(result["moved"])),
               _files(len(result["failed"]))),
            title="Amaze Repair")
    else:
        hou.ui.displayMessage(                            # type: ignore
            "%s moved into Amaze's holding folder on this computer - "
            "outside your library, kept for 30 days. Nothing was "
            "deleted, and Clean Library will run again now."
            % _files(len(result["moved"])),
            title="Amaze Repair")


def _do_reattach(findings: dict) -> None:
    pairs = _complete_pairs(findings)
    owners = database.ASSET_FILE_OWNERS
    labels = [database.section_label(name) for name in owners]
    chosen = hou.ui.selectFromList(                       # type: ignore
        labels, exclusive=True, title="Amaze Repair",
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
        # "file pair" is how a material is STORED, not what it is - the
        # reader has never had to know it takes two files.
        "Add %d unlisted %s to %s?" % (len(pairs), noun, label),
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
        buttons=("Add Them Back", "Cancel"),
        default_choice=1, close_choice=1,
        title="Amaze Repair",
    ) != 0:
        return
    try:
        result = reattach(findings, filename)
    except ValueError as exc:
        hou.ui.displayMessage(                            # type: ignore
            "Amaze did not change the %s list: %s." % (label, exc),
            title="Amaze Repair")
        return
    hou.ui.displayMessage(                                # type: ignore
        "%d %s came back into %s. Open Amaze to see them - they are in the "
        "%s category, ready to be renamed."
        % (len(result["added"]),
           database.section_noun(filename, len(result["added"])),
           label, RECOVERED_CATEGORY),
        title="Amaze Repair")
