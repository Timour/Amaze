"""Reading, and putting back, the copies Amaze keeps of its lists.

Every write to a critical list (the material library, settings, the
Code/Nodes lists) first copies the current file to a rolling
``.bak-1/2/3`` beside it, plus a ``.bak-first`` that never rotates. This
module is the only code that reads those copies and the only code that
puts one back.

ONE IMPLEMENTATION, TWO CALLERS, and that is the whole reason this file
exists rather than the logic living in ``tools/restore.py`` where it
started:

* ``tools/restore.py`` - the terminal tool, for when Houdini will not
  start at all. It imports this by adding ``scripts/python`` to the path;
  nothing here may import anything but the standard library, or that
  claim stops being true.
* the **Repair** shelf tool, for when Houdini starts and the library is
  the thing that is broken.

A second implementation of a restore is a second answer: the two would
disagree about which copies exist, or about what "readable" means, and
the one the user happened to reach would be the one that decided. The
recovery tool must never disagree with the thing it recovers.

NOTHING HERE DELETES, and nothing here is destructive except
``put_back``, which writes the current state to an undo copy first - and
that undo copy is itself one of the copies this module offers, so the
sentence "this can be undone" names something a caller can actually do.
"""

import datetime
import json
import os
import shutil

from amaze.helpers import hostos

#: The snapshot suffixes the app maintains, newest first.
TIERS = ("bak-1", "bak-2", "bak-3", "bak-first")

#: The prefix of the copies a RESTORE writes, each holding whatever was
#: there just before one restore. Kept out of TIERS because the app never
#: writes them and never rotates them - but offered by snapshots() all
#: the same, and that is not a cosmetic choice: put_back's own dialog
#: says the restore can be undone by putting the copy back, so it has to
#: be a copy the tools will actually offer. A promised undo the picker
#: cannot list is worse than silence, because it is the reassurance that
#: makes someone click.
#:
#: EACH RESTORE GETS ITS OWN, timestamped, never reused. One fixed name
#: made the second restore a delete: it overwrote the only copy of the
#: pre-first-restore state, so two restores in a row - which is exactly
#: what somebody trying copies until one looks right does - silently
#: destroyed the state they started from. Measured through the shipped
#: CLI before the fix: 500 assets, restore bak-1 (495), restore the undo,
#: two success messages, and the 500-asset state nowhere on disk.
UNDO_TIER = "bak-before-restore"

#: Top-level list keys, in the order a document is likely to carry one.
#: ("assets" covers the material, Nodes and Code lists; "gradients" is
#: the Colors section's own format, which has no connector.)
_LIST_KEYS = ("assets", "snippets", "cops", "gradients")


def _mapping_payloads():
    """The side tables' payload keys, from the ONE registry.

    Their payload is a MAPPING, not a list, so `_LIST_KEYS` never
    matched one and a notes.json holding 40 notes fell through to the
    settings branch and counted as "1 settings". That number is not
    cosmetic: `put_back` refuses a restore that would lose records by
    comparing the two counts, so 1 against 1 never fired - a two-note
    snapshot could be put back over a forty-note table in silence, and
    Repair calls put_back with allow_loss=True precisely because the
    picker is supposed to have told the user the counts.
    """
    try:
        from amaze.core import keyed_store
    except Exception:                                     # noqa: BLE001
        # Pure-stdlib callers (the CLI on a machine where Houdini will
        # not start) keep the old behaviour rather than failing.
        return ()
    return tuple((spec.payload, spec.noun) for spec in keyed_store.stores())


class RestoreRefused(Exception):
    """A restore that was asked for and not done.

    The exception's own text is a COMPLETE SENTENCE FIT FOR A DIALOG - no
    parse position, no Errno, nothing the reader cannot act on. The
    technical half rides along in `.detail` for the terminal tool and the
    log, because a message that is complete without it is the rule and a
    detail nobody can read is what breaks it."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


def read_document(path: str):
    """(document, error) - error is "" on success, else a phrase.

    utf-8-sig, like every reader in the package. A byte-order mark is an
    ordinary artifact of a file that has been through a Windows editor or
    a sync client's conflict helper, and since the app now loads one
    fine, hostos.parses_as_json calls a BOM'd document healthy and
    snapshot_before_write copies it into the write-once .bak-first tier.
    Reading plain utf-8 here made that exact file the one this tool
    listed as "NOT VALID JSON" and refused to put back - the recovery
    tool disagreeing with the thing it recovers, on the one shape that
    most needs recovering.
    """
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle), ""
    except (OSError, ValueError) as exc:
        return None, str(exc)


def count_in(document):
    """(how many, what they are) for a parsed document, or (None, "")
    when it is not shaped like one of Amaze's lists.

    A dict with no list key at all is settings - counted by key, because
    "44 settings" is the number that tells a user which copy of
    settings.json they are looking at."""
    if not isinstance(document, dict):
        return None, ""
    for key in _LIST_KEYS:
        if isinstance(document.get(key), list):
            return len(document[key]), key
    for payload, noun in _mapping_payloads():
        if isinstance(document.get(payload), dict):
            return len(document[payload]), noun + "s"
    return len(document), "settings"


def info(path: str) -> dict:
    """Everything a caller needs to say what a file is, without reading
    it twice. `count` is None when the file could not be read at all -
    NOT 0, because "it holds nothing" and "it would not open" are the two
    answers a restore decision turns on and they must never share a
    value."""
    if not os.path.exists(path):
        return {"path": path, "name": os.path.basename(path),
                "exists": False, "size": 0, "when": "", "count": None,
                "noun": "", "error": ""}
    document, error = read_document(path)
    count, noun = count_in(document) if not error else (None, "")
    return {
        "path": path,
        "name": os.path.basename(path),
        "exists": True,
        "size": os.path.getsize(path),
        "when": datetime.datetime.fromtimestamp(
            os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
        "count": count,
        "noun": noun,
        "error": error,
    }


def describe(path: str) -> str:
    """Size, date, and - for a list - what it actually holds. "What would
    I get back" is the question a restore has to answer.

    This is the terminal tool's line; the Repair tool writes its own
    sentences from info() instead, because a column layout is not a
    sentence and a dialog is not a terminal."""
    facts = info(path)
    if not facts["exists"]:
        return "missing"
    if facts["error"]:
        detail = ", NOT VALID JSON"
    elif facts["count"] is None:
        detail = ""
    else:
        detail = ", %d %s" % (facts["count"], facts["noun"])
    return "%7d bytes  %s%s" % (facts["size"], facts["when"], detail)


def snapshots(target: str) -> list:
    """(tier, path) for every copy that exists beside `target`, newest
    first.

    The undo copies come FIRST when any are there: they are the newest
    states of all - each one was on disk moments before a restore - and
    they only exist at all after somebody restored, which is exactly when
    they may want one back. EVERY undo copy is listed, not just the
    latest: each holds a different state, and the one somebody needs is
    usually the oldest - the state before the first restore of the run.
    (The old single fixed-name copy, if one is still lying around from an
    earlier build, matches the same prefix and is offered the same way.)
    """
    name = os.path.basename(target)
    folder = os.path.dirname(target) or "."
    prefix = name + "." + UNDO_TIER
    try:
        siblings = os.listdir(folder)
    except OSError:
        siblings = []
    # BY THE STAMP IN THE NAME, descending - the same key
    # _retire_old_undo_copies uses, and for the reason practice.md
    # records: mtime says when a file was last TOUCHED, the name says
    # which state it HOLDS, and a backup pass or a transport rewrites
    # the former. These two functions answered "which undo copy is
    # newest" from two different keys, so the copy the picker offered
    # first as the newest state was not the one retirement was keeping
    # - and past five copies the tool could retire the one it had just
    # called newest. The copies are made with shutil.copy2, which
    # practice.md flags by name for preserving a misleading mtime.
    undos = sorted((s for s in siblings if s.startswith(prefix)),
                   reverse=True)
    found = [(sibling[len(name) + 1:], os.path.join(folder, sibling))
             for sibling in undos]
    found += [(tier, target + "." + tier) for tier in TIERS
              if os.path.exists(target + "." + tier)]
    return found


def _fresh_undo_path(target: str) -> str:
    """A path for one restore's undo copy that no earlier restore owns.

    Timestamped to the second, with a counter when two restores land
    inside one second (a picker retry does). Reusing an existing name is
    the one thing this must never do - overwriting an undo copy is
    deleting a state that exists nowhere else, from the tool whose whole
    claim is that it never deletes."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = "%s.%s-%s" % (target, UNDO_TIER, stamp)
    candidate, number = base, 2
    while os.path.exists(candidate):
        candidate = "%s-%d" % (base, number)
        number += 1
    return candidate


#: How many undo copies to keep per file. Each restore mints one, so
#: this bounds a family that otherwise grows forever in a synced
#: folder - the exact accumulation the quarantine window exists to end
#: elsewhere. Five covers a panicked evening with room to spare.
KEEP_UNDO_COPIES = 5


def _retire_old_undo_copies(target: str, keep: int = KEEP_UNDO_COPIES):
    """Move undo copies beyond the newest `keep` into the quarantine.

    MOVED, NOT DELETED - each holds a state that exists nowhere else,
    and this module's whole claim is that it never deletes. They land in
    the same machine-local quarantine Clean Library uses, where the
    30-day window applies; expiry there is the deliberate, already-
    decided end of the line rather than a silent unlink here.

    Ordered by the TIMESTAMP IN THE NAME, not mtime, for the recorded
    reason: mtime says when a file was last touched, the name says which
    state it holds, and a backup pass rewrites the former.
    """
    name = os.path.basename(target)
    folder = os.path.dirname(target) or "."
    prefix = name + "." + UNDO_TIER + "-"
    try:
        family = sorted(n for n in os.listdir(folder)
                        if n.startswith(prefix))
    except OSError:
        return []
    retired = []
    for stale in family[:-keep] if keep > 0 else []:
        full = os.path.join(folder, stale)
        try:
            # core.quarantine, NOT core.library: library.py imports hou
            # at module level, so from the terminal tool this import
            # raised every single time and was swallowed with nothing
            # recorded - the bound above retired nothing on the one
            # path that runs when Houdini will not start, which is the
            # path this whole tool exists for. Reproduced at eight
            # restores, eight copies kept, bound of five.
            from amaze.core import quarantine
            moved = quarantine.quarantine_file(folder, full)
        except (ImportError, OSError) as exc:
            # SAY WHY. This was a bare `except Exception` returning a
            # neutral value, which is how the failure above stayed
            # invisible for as long as it did.
            print("could not retire %s: %s" % (stale, exc))
            moved = ""
        if moved:
            retired.append(stale)
        else:
            # Could not quarantine: LEAVE IT. An undo copy in place is
            # clutter; an undo copy gone is a state lost.
            break
    return retired


def put_back(target: str, tier: str, allow_loss: bool = False) -> dict:
    """Copy one snapshot over `target`, saving the current state first.

    Returns {"tier", "undo"} - `undo` is the basename of the copy the
    current state was saved to, or "" when there was nothing there to
    save. Raises RestoreRefused, with a sentence, rather than putting
    back something unreadable: a cloud client can truncate the BACKUP
    too, and restoring garbage over a live list turns one problem into
    two.

    The caller is responsible for making sure nothing has the file open -
    a restore performed while a panel is running is overwritten by the
    panel's own next save, and the user is left believing they recovered.
    """
    tier = tier.lstrip(".")
    source = target + "." + tier
    if not os.path.exists(source):
        # NO TIER NAME AND NO FILENAME IN THE SENTENCE. "There is no
        # bak-1 copy of library.json" is a storage suffix and a file
        # nobody has opened, in a dialog whose every other line says
        # "Nodes" and "a copy from 2026-07-27 20:31". The terminal tool
        # prints .detail after it and stays followable.
        raise RestoreRefused(
            "That copy is no longer in the library folder, so nothing was "
            "put back and the list you have now is untouched.",
            detail="%s does not exist" % source)
    document, error = read_document(source)
    if error:
        # NOT "cannot be read EITHER". A perfectly healthy list can have
        # a truncated copy beside it - which is precisely the copy a
        # picker offers for a section reported as reading fine - and
        # "either" sends that reader hunting a second fault that is not
        # there.
        raise RestoreRefused(
            "That copy of %s cannot be read, so nothing was put back and "
            "the list you have now is untouched."
            % os.path.basename(target), detail=error)

    # THE SOURCE IS IN MEMORY BEFORE ANYTHING IS WRITTEN. The order used
    # to be write-the-undo-then-copy, and with a fixed undo name that
    # made restoring the undo copy overwrite its own source before
    # reading it. Unique names alone close that door; reading first
    # closes it structurally, whatever the names do - the largest of
    # these lists is 350KB on the real library, so holding one is cheap.
    with open(source, "rb") as handle:
        payload = handle.read()

    # A RESTORE THAT LOSES RECORDS NEEDS TO BE MEANT. A snapshot that
    # parses is not therefore a snapshot worth restoring: a bare [] or a
    # 1-row starter parses perfectly, and putting it over a 548-record
    # list with exit code 0 and no warning is the tool doing the damage
    # it exists to undo. Counted against what is THERE now; allow_loss
    # is the explicit override, and the refusal names both numbers so
    # the choice is informed rather than brave.
    current_doc, current_error = read_document(target) \
        if os.path.exists(target) else (None, "absent")
    if not current_error and not allow_loss:
        have, noun = count_in(current_doc)
        got, _ = count_in(document)
        if have is not None and got is not None and got < have:
            raise RestoreRefused(
                "That copy holds %d %s and the list you have now holds "
                "%d - putting it back would lose %d. If that is what you "
                "want, say so explicitly."
                % (got, noun, have, have - got),
                detail="pass allow_loss=True / --allow-loss")

    undo = ""
    if os.path.exists(target):
        # The restore is itself reversible - a wrong choice under
        # pressure must not be the end of the story. A FRESH name every
        # time: each undo copy holds a state that exists nowhere else,
        # and the second restore of a panicked evening must not delete
        # what the first one saved.
        undo_path = _fresh_undo_path(target)
        shutil.copy2(target, undo_path)
        undo = os.path.basename(undo_path)
        _retire_old_undo_copies(target)

    # Through a scratch and a rename, not written onto the live file.
    # The bare open(target, "wb") truncated the one copy being replaced
    # BEFORE the new bytes were durable - a kill between truncate and
    # write left neither the old list nor the new one, in the one tool
    # whose job is getting a list back. Byte-identical to the snapshot
    # (BOM and all), and stamped with a CURRENT mtime rather than
    # shutil.copy2's backdated one, so "which file changed just now"
    # stays answerable in a synced folder.
    with hostos.scratch_beside(target) as scratch:
        with open(scratch, "wb") as handle:
            handle.write(payload)

    # SAY WHAT IS NOW STRANDED. Files whose ids the restored list does
    # not carry are not deleted - they never are - but a restore that
    # quietly orphans them leaves the next Clean Library to make that
    # discovery instead.
    stranded = []
    try:
        restored_ids = {str(a.get("id"))
                        for a in (document.get("assets") or [])
                        if isinstance(a, dict)} \
            if isinstance(document, dict) else set()
        if current_doc and isinstance(current_doc, dict):
            before_ids = {str(a.get("id"))
                          for a in (current_doc.get("assets") or [])
                          if isinstance(a, dict)}
            stranded = sorted(before_ids - restored_ids)
    except (TypeError, AttributeError):
        stranded = []
    return {"tier": tier, "undo": undo, "stranded": stranded}
