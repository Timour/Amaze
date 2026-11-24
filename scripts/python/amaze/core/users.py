"""Who uses this library: a `uuid4` UID with a `name`, in `DataBase.json`'s `users` section."""

from __future__ import annotations

import os
import types
import uuid

from amaze.core import documents, guard, library_db, library_files

SECTION = "users"

RESOLVED = "resolved"    # `library_user` names a user of this library...
MINT = "mint"            # ...the library has no users yet...
ASK = "ask"              # ...or it has users and `library_user` is none of them


def uid_shaped(value: str) -> bool:
    """Is this a generated UID, the 32-hex `uuid4().hex` form?"""
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
    held.refresh()    # callers prune by this set, so reread to include other sessions' changes
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


def _put(preferences, uid: str, record: dict, library: str = "") -> bool:
    """Store one user's record; written by the new UID itself unless a user of the open one writes it."""
    held = _master(preferences, library)
    if not library and str(getattr(preferences, "library_user", "") or "") in all_users(preferences):
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


def create(preferences, name: str, library: str = "") -> str:
    """A new user's UID in this library or `library`; "" for a blank or taken name or a refused write."""
    name = str(name or "").strip()
    if not name or name_taken(preferences, name, library=library):
        return ""
    uid = uuid.uuid4().hex
    return uid if _put(preferences, uid, {"name": name}, library) else ""


def delete(preferences, uid) -> bool:
    """Remove a user, their favourites and folder list; their comments and all they made stay."""
    uid = str(uid)
    held = _master(preferences)
    if not held.get(SECTION, uid):
        return False
    library_db.flush(preferences)    # changes still waiting are saved first, by who made them
    for name, kind in guard.DATABASES.items():
        own = library_db.document(preferences, name)
        dropped = [section for section, how in kind.sections.items()
                   if how == guard.PER_USER and own.drop_user(section, uid)]
        if dropped and not library_db.save(preferences, name):
            return False    # the user stays, so a second delete removes the rest
    if not held.drop(SECTION, uid):
        return False
    if not library_db.save(preferences, library_files.MASTER):
        return False
    try:
        preferences.forget_user(uid)
    except (AttributeError, OSError):
        pass    # `first_run_state` returns ASK on the next open either way
    return True


def rename(preferences, uid, name: str) -> bool:
    """Change a UID's name; nothing they own is changed."""
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
    """This machine's user in this library, or None if `library_user` is no user here; none is created."""
    if first_run_state(preferences) != RESOLVED:
        return None
    return str(preferences.library_user)


def set_current_user(preferences, uid):
    """Set and save `library_user` to `uid`; the user picker calls this once the user has chosen."""
    uid = str(uid)
    try:
        preferences.library_user = uid
        preferences.save()
    except (AttributeError, OSError):
        return uid    # this session still uses `uid`; the next session asks again
    return uid
