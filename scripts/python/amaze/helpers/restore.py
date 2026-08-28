"""Reads the `.bak` copies and puts one back - the only code that does either, and it never deletes. STDLIB ONLY, because the terminal tool imports it on a machine where Houdini will not start. ▸archive/restore.py"""

import datetime
import json
import os
import shutil

from amaze.helpers import hostos

TIERS = ("bak-1", "bak-2", "bak-3", "bak-first")

UNDO_TIER = "bak-before-restore"

_LIST_KEYS = ("assets", "snippets", "cops", "gradients")


def _mapping_payloads():
    """`(payload, noun)` for each registered side table, whose payload is a MAPPING - `_LIST_KEYS` cannot match one, so a miss counts the whole document as settings."""
    try:
        from amaze.core import keyed_store
    except Exception:                                     # noqa: BLE001
        return ()
    return tuple((spec.payload, spec.noun) for spec in keyed_store.stores())


class RestoreRefused(Exception):
    """A restore asked for and not done - `str()` is a complete sentence fit for a dialog, the technical half rides in `.detail`."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


def read_document(path: str):
    """`(document, error)`, error `""` on success. utf-8-SIG: plain utf-8 here reads a BOM'd file as invalid JSON and refuses to put back a copy the app itself calls healthy."""
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle), ""
    except (OSError, ValueError) as exc:
        return None, str(exc)


def count_in(document):
    """`(how many, what they are)`, or `(None, "")` when the document is not one of Amaze's lists - a dict with no list key counts by key as settings."""
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
    """What a file is, read once. `count` is None when it would not open - NEVER 0, or `holds nothing` and `would not open` become the same answer."""
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
    """One terminal-width line: size, date, and what a list holds. The Repair dialog writes its own from `info()`."""
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
    """`(tier, path)` for every copy beside `target`, undo copies first and EVERY one of them. Sorted BY THE STAMP IN THE NAME - `shutil.copy2` preserves a misleading mtime, and this must agree with what retirement keeps."""
    name = os.path.basename(target)
    folder = os.path.dirname(target) or "."
    prefix = name + "." + UNDO_TIER
    try:
        siblings = os.listdir(folder)
    except OSError:
        siblings = []
    undos = sorted((s for s in siblings if s.startswith(prefix)),
                   reverse=True)
    found = [(sibling[len(name) + 1:], os.path.join(folder, sibling))
             for sibling in undos]
    found += [(tier, target + "." + tier) for tier in TIERS
              if os.path.exists(target + "." + tier)]
    return found


def _fresh_undo_path(target: str) -> str:
    """A stamped undo path no earlier restore owns. REUSING A NAME IS THE ONE THING THIS MUST NEVER DO - overwriting an undo copy deletes a state that exists nowhere else."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = "%s.%s-%s" % (target, UNDO_TIER, stamp)
    candidate, number = base, 2
    while os.path.exists(candidate):
        candidate = "%s-%d" % (base, number)
        number += 1
    return candidate


KEEP_UNDO_COPIES = 5


def _retire_old_undo_copies(target: str, keep: int = KEEP_UNDO_COPIES):
    """MOVES undo copies past the newest `keep` into the quarantine, never deletes, ordered by the stamp in the NAME. Imports `core.quarantine`, never `core.library`, which imports `hou` and would raise on every terminal-tool run."""
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
            from amaze.core import quarantine
            moved = quarantine.quarantine_file(folder, full)
        except (ImportError, OSError) as exc:
            print("could not retire %s: %s" % (stale, exc))
            moved = ""
        if moved:
            retired.append(stale)
        else:
            break
    return retired


def put_back(target: str, tier: str, allow_loss: bool = False) -> dict:
    """Copies one snapshot over `target`, saving the current state to an undo copy first; answers `{"tier", "undo"}` or raises `RestoreRefused`. THE CALLER MUST ENSURE NOTHING HAS THE FILE OPEN - a restore while a panel is running is overwritten by that panel's next save, and the user is left believing they recovered."""
    tier = tier.lstrip(".")
    source = target + "." + tier
    if not os.path.exists(source):
        raise RestoreRefused(
            "That copy is no longer in the library folder, so nothing was "
            "put back and the list you have now is untouched.",
            detail="%s does not exist" % source)
    document, error = read_document(source)
    if error:
        raise RestoreRefused(
            "That copy of %s cannot be read, so nothing was put back and "
            "the list you have now is untouched."
            % os.path.basename(target), detail=error)

    with open(source, "rb") as handle:
        payload = handle.read()

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
        undo_path = _fresh_undo_path(target)
        shutil.copy2(target, undo_path)
        undo = os.path.basename(undo_path)
        _retire_old_undo_copies(target)

    with hostos.scratch_beside(target) as scratch:
        with open(scratch, "wb") as handle:
            handle.write(payload)

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
