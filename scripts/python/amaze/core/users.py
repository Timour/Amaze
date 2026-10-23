"""Who uses this library: a `uuid4` UID with a `name` beside it - everything a user owns is tagged with the UID and never the typed name, so a rename relinks the label and moves nothing (ROADMAP line 21 carries what is user-scoped and what is not)."""

from __future__ import annotations

import uuid

from amaze.core import keyed_store

USERS_FILE = "users.json"

RESOLVED = "resolved"    # the pointer names someone this library knows...
MINT = "mint"            # ...the library has nobody yet...
ASK = "ask"              # ...or it HAS people and this machine is none of them - the state that earns its cost, stopping a second machine minting a second identity for one person (ROADMAP line 21)


def normalise(value) -> dict:
    """A well-formed record, or {} for junk: a user with no name cannot be shown in a picker, so it reads as absent."""
    if not isinstance(value, dict):
        return {}
    name = value.get("name", "")
    if not isinstance(name, str):
        return {}
    name = name.strip()
    if not name:
        return {}
    kept = dict(value)
    kept["name"] = name
    return kept


SPEC = keyed_store.bind(USERS_FILE, normalise)


def _store(preferences, library: str = ""):
    return keyed_store.open_store(SPEC, preferences, library)


def all_users(preferences, library: str = "") -> dict:
    """`{uid: name}` for this library, or for `library` - a COPY, like every store read."""
    return {uid: record.get("name", "")
            for uid, record in _store(preferences, library).all().items()}


def roster(preferences) -> set:
    """Every uid `users.json` holds now, checked against the file; empty when that cannot be proved."""
    store = keyed_store.opened(SPEC, preferences)
    return (store.held_keys() if store is not None else None) or set()


def name_for(preferences, uid) -> str:
    """The name this UID displays under, or "" if unknown here."""
    return _store(preferences).get(str(uid)).get("name", "")


def name_taken(preferences, name: str, besides: str = "", library: str = "") -> bool:
    """Whether a user other than `besides` already has `name` here, or in `library`, ignoring case."""
    return bool(named(preferences, name, library=library, besides=besides))


def named(preferences, name: str, library: str = "", besides: str = "") -> str:
    """The UID of the user called `name` here, or in `library`, ignoring case; "" for nobody."""
    wanted = str(name or "").strip().casefold()
    return next((uid for uid, other in all_users(preferences, library).items()
                 if wanted and uid != str(besides) and other.strip().casefold() == wanted), "")


def create(preferences, name: str) -> str:
    """A new user's UID, or "" for a blank name, a name already taken, or a refused write."""
    name = str(name or "").strip()
    if not name or name_taken(preferences, name):
        return ""
    uid = uuid.uuid4().hex
    if not _store(preferences).set(uid, {"name": name}):
        return ""
    return uid


def delete(preferences, uid) -> bool:
    """Remove a user AND everything tagged theirs - favourites and registered folders, one guarded write per store - then the record, which a refused sweep KEEPS (the user stays visible and the deletion retryable, never half-invisible); a machine pointing at them clears its pointer, any other falls to ASK on its next open (settled 2026-08-22)."""
    uid = str(uid)
    store = _store(preferences)
    if not store.get(uid):
        return False
    swept = keyed_store.retire_owner(preferences, uid)
    if any(not written for written in swept.values()):
        return False
    if not store.retire([uid]):
        return False
    try:
        preferences.forget_user(uid)
    except (AttributeError, OSError):
        pass    # the next open lands in ASK either way
    return True


def rename(preferences, uid, name: str) -> bool:
    """Relink a UID's name. Nothing tagged is touched - one field write, where a name-keyed store would need `keyed_store.rekey`."""
    uid = str(uid)
    name = str(name or "").strip()
    store = _store(preferences)
    record = store.get(uid)
    if not name or not record or name_taken(preferences, name, besides=uid):
        return False
    record = dict(record)
    record["name"] = name
    return bool(store.set(uid, record))


def first_run_state(preferences) -> str:
    """RESOLVED, MINT or ASK - see the constants."""
    known = _store(preferences).all()
    if not known:
        return MINT
    try:
        pointer = str(preferences.library_user or "")
    except AttributeError:
        pointer = ""
    return RESOLVED if pointer in known else ASK


def current(preferences):
    """This machine's user in this library, or None when it names nobody here; nobody is made."""
    if first_run_state(preferences) != RESOLVED:
        return None
    return str(preferences.library_user)


def adopt_named(preferences, name: str) -> str:
    """Adopt the user called `name` here, creating them when missing; "" for no name."""
    uid = named(preferences, name) or create(preferences, name)
    return adopt(preferences, uid) if uid else ""


def adopt(preferences, uid):
    """Point this machine at `uid` and remember it - what the picker calls once the user has chosen."""
    uid = str(uid)
    try:
        preferences.library_user = uid
        preferences.save()
    except (AttributeError, OSError):
        return uid    # the session still works; the next one asks again
    return uid
