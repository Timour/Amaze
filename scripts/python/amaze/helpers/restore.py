"""Reads the `.bak` copies and puts one back; never deletes, stdlib only. ▸archive/restore.py"""

import datetime
import json
import os
import shutil

from amaze.helpers import hostos

TIERS = ("bak-1", "bak-2", "bak-3", "bak-first")

UNDO_TIER = "bak-before-restore"

_LIST_KEYS = ("assets", "snippets", "cops", "gradients")


def _mapping_payloads():
    """`(payload, noun)` for each registered side table, whose payload is a mapping."""
    try:
        from amaze.core import keyed_store
    except Exception:                                     # noqa: BLE001
        return ()
    return tuple((spec.payload, spec.noun) for spec in keyed_store.stores())


class RestoreRefused(Exception):
    """A restore not done; `str()` is a sentence for a dialog, the technical half is `.detail`."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


def read_document(path: str):
    """`(document, error)`, error `""` on success; reads utf-8-sig, so a BOM is accepted."""
    return read_payload(path)[1:]


def read_payload(path: str):
    """`(bytes, document, error)` from ONE read, for a caller that writes back what it checked."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        return b"", None, str(exc)
    try:
        return raw, json.loads(raw.decode("utf-8-sig")), ""
    except ValueError as exc:
        return raw, None, str(exc)


def count_in(document):
    """`(how many, what they are)`, `(None, "")` for a non-dict; a dict with no list is settings."""
    if not isinstance(document, dict):
        return None, ""
    for key in _LIST_KEYS:
        if isinstance(document.get(key), list):
            return len(document[key]), key
    for payload, noun in _mapping_payloads():
        if isinstance(document.get(payload), dict):
            return len(document[payload]), noun + "s"
    return len(document), "settings"


def surveyed(path: str):
    """`(facts, document)` from one parse; `info()` is this without the document."""
    if not os.path.exists(path):
        return ({"path": path, "name": os.path.basename(path),
                 "exists": False, "size": 0, "when": "", "count": None,
                 "noun": "", "error": ""}, None)
    document, error = read_document(path)
    count, noun = count_in(document) if not error else (None, "")
    return ({
        "path": path,
        "name": os.path.basename(path),
        "exists": True,
        "size": os.path.getsize(path),
        "when": datetime.datetime.fromtimestamp(
            os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
        "count": count,
        "noun": noun,
        "error": error,
    }, document)


def info(path: str) -> dict:
    """What a file is; `count` is None, never 0, when it would not open."""
    return surveyed(path)[0]


def describe(path: str) -> str:
    """One terminal-width line: size, date, and what a list holds."""
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
    """`(tier, path)` for every copy beside `target`, all undo copies first, newest stamp first."""
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
    """A stamped undo path no file holds yet; it never reuses a name."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = "%s.%s-%s" % (target, UNDO_TIER, stamp)
    candidate, number = base, 2
    while os.path.exists(candidate):
        candidate = "%s-%d" % (base, number)
        number += 1
    return candidate


KEEP_UNDO_COPIES = 5


def _retire_old_undo_copies(target: str, keep: int = KEEP_UNDO_COPIES):
    """Move undo copies past the newest `keep` into the quarantine; never import `hou` here."""
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
    """Put a snapshot over `target`, undo copy first; or RestoreRefused. Nothing may hold it open."""
    tier = tier.lstrip(".")
    source = target + "." + tier
    if not os.path.exists(source):
        raise RestoreRefused(
            "That copy is no longer in the library folder, so nothing was "
            "put back and the list you have now is untouched.",
            detail="%s does not exist" % source)
    payload, document, error = read_payload(source)
    if error:
        raise RestoreRefused(
            "That copy of %s cannot be read, so nothing was put back and "
            "the list you have now is untouched."
            % os.path.basename(target), detail=error)

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
