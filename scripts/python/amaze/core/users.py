"""Who uses this library: a `uuid4` UID with a `name`, in `DataBase.json`'s `users` section."""

from __future__ import annotations

import os
import types
import uuid

from amaze.core import documents, library_db, library_files

SECTION = "users"

RESOLVED = "resolved"    # the pointer names someone this library knows...
MINT = "mint"            # ...the library has nobody yet...
ASK = "ask"              # ...or it has people and this machine is none of them


def uid_shaped(value: str) -> bool:
    """Is this a minted UID, the 32-hex `uuid4().hex` shape?"""
    value = str(value or "")
    return len(value) == 32 and all(c in "0123456789abcdef" for c in value)


def _master(preferences, library: str = ""):
    if library:
        other = types.SimpleNamespace(
            dir=library, library_user=getattr(preferences, "library_user", ""))
        if library_db.key_of(other) != library_db.key_of(preferences):
            preferences = other
    return library_db.document(preferences, library_files.MASTER)


def all_users(preferences, library: str = "") -> dict:
    """`{uid: name}` for this library, or for `library`."""
    return {uid: str(record.get("name") or "")
            for uid, record in _master(preferences, library).table(SECTION).items()
            if isinstance(record, dict) and str(record.get("name") or "").strip()}


def roster(preferences) -> set:
    """Every uid the library's users section holds now; empty when it cannot be read."""
    held = _master(preferences)
    held.refresh()    # a prune acts on it: a roster read before another session's change is stale
    return set(all_users(preferences)) if held.writable else set()


def name_for(preferences, uid) -> str:
    """The name this UID displays under, or "" if unknown here."""
    return str((_master(preferences).get(SECTION, str(uid)) or {}).get("name") or "")


def name_taken(preferences, name: str, besides: str = "", library: str = "") -> bool:
    """Whether a user other than `besides` already has `name` here, or in `library`, ignoring case."""
    return bool(named(preferences, name, library=library, besides=besides))


def named(preferences, name: str, library: str = "", besides: str = "") -> str:
    """The UID of the user called `name` here, or in `library`, ignoring case; "" for nobody."""
    wanted = str(name or "").strip().casefold()
    return next((uid for uid, other in all_users(preferences, library).items()
                 if wanted and uid != str(besides) and other.strip().casefold() == wanted), "")


def _put(preferences, uid: str, record: dict) -> bool:
    """Store one user's record; with nobody picked yet, the newcomer signs their own row."""
    held = _master(preferences)
    if held.user():
        if not held.put(SECTION, uid, record):
            return False
        saved = library_db.save(preferences, library_files.MASTER)
        return bool(saved) or saved.reason == documents.UNCHANGED
    if not os.path.isdir(held.guard.dir):
        return False
    reading = held.guard.read(library_files.MASTER)
    if not reading.writable:
        return False
    whole = dict(reading.document)
    table = dict(whole.get(SECTION) or {})
    table[uid] = dict(record, **{documents.BY: uid, documents.AT: held.guard.stamp()})
    change = held.guard.change(uid)
    change.put(reading.ticket, dict(whole, **{SECTION: table}))
    try:
        change.commit()
    except (OSError, documents.guard.Refused):
        return False
    held.refresh()
    return True


def create(preferences, name: str) -> str:
    """A new user's UID, or "" for a blank name, a name already taken, or a refused write."""
    name = str(name or "").strip()
    if not name or name_taken(preferences, name):
        return ""
    uid = uuid.uuid4().hex
    return uid if _put(preferences, uid, {"name": name}) else ""


def delete(preferences, uid) -> bool:
    """Remove a user; what they starred stays theirs in the file, never another user's to change."""
    uid = str(uid)
    held = _master(preferences)
    if not held.get(SECTION, uid):
        return False
    if not held.drop(SECTION, uid):
        return False
    if not library_db.save(preferences, library_files.MASTER):
        return False
    try:
        preferences.forget_user(uid)
    except (AttributeError, OSError):
        pass    # the next open lands in ASK either way
    return True


def rename(preferences, uid, name: str) -> bool:
    """Relink a UID's name; nothing they own is touched."""
    uid = str(uid)
    name = str(name or "").strip()
    record = _master(preferences).get(SECTION, uid)
    if not name or not record or name_taken(preferences, name, besides=uid):
        return False
    return _master(preferences).edit(SECTION, uid, name=name) and bool(
        library_db.save(preferences, library_files.MASTER))


def first_run_state(preferences) -> str:
    """RESOLVED, MINT or ASK - see the constants."""
    known = all_users(preferences)
    if not known:
        return MINT
    pointer = str(getattr(preferences, "library_user", "") or "")
    return RESOLVED if pointer in known else ASK


def current(preferences):
    """This machine's user in this library, or None when it names nobody here; nobody is made."""
    if first_run_state(preferences) != RESOLVED:
        return None
    return str(preferences.library_user)


def adopt(preferences, uid):
    """Point this machine at `uid` and remember it - what the picker calls once the user has chosen."""
    uid = str(uid)
    try:
        preferences.library_user = uid
        preferences.save()
    except (AttributeError, OSError):
        return uid    # the session still works; the next one asks again
    return uid
