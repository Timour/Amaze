"""Who uses this library: a `uuid4` UID with a `name` beside it - everything a user owns is tagged with the UID and never the typed name, so a rename relinks the label and moves nothing (ROADMAP line 21 carries what is user-scoped and what is not)."""

from __future__ import annotations

import random
import uuid

from amaze.core import keyed_store

USERS_FILE = "users.json"

PLACEHOLDER_NAMES = (    # the pool a library's FIRST user is named from - minted once per LIBRARY, never per machine, never the OS user or machine name (ROADMAP line 21)
    "Amber", "Aqua", "Auburn", "Azure", "Beige", "Blush", "Bronze",
    "Burgundy", "Carmine", "Celadon", "Cerise", "Cerulean", "Charcoal",
    "Chartreuse", "Cinnabar", "Cobalt", "Copper", "Coral", "Cream",
    "Crimson", "Cyan", "Ebony", "Emerald", "Fawn", "Fuchsia", "Gold",
    "Heliotrope", "Indigo", "Ivory", "Jade", "Lavender", "Lilac",
    "Magenta", "Mahogany", "Maroon", "Mauve", "Mint", "Moss", "Ochre",
    "Olive", "Onyx", "Orchid", "Pearl", "Periwinkle", "Pewter", "Plum",
    "Rose", "Ruby", "Russet", "Rust", "Saffron", "Sage", "Salmon",
    "Sapphire", "Scarlet", "Sepia", "Sienna", "Silver", "Slate",
    "Tangerine", "Taupe", "Teal", "Terracotta", "Turquoise", "Ultramarine",
    "Umber", "Vermilion", "Violet", "Viridian", "Wisteria",
)

RESOLVED = "resolved"    # what the first open must do about identity: the pointer names someone this library knows...
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


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def all_users(preferences) -> dict:
    """`{uid: name}` for this library - a COPY, like every store read."""
    return {uid: record.get("name", "")
            for uid, record in _store(preferences).all().items()}


def name_for(preferences, uid) -> str:
    """The name this UID displays under, or "" if unknown here."""
    return _store(preferences).get(str(uid)).get("name", "")


def create(preferences, name: str) -> str:
    """Mint a user and answer its UID, or "" when the store refused (a UID not on disk would orphan everything tagged with it) - names are NOT unique on purpose: two Annas are two UIDs, and forbidding it would key on the name through the back door."""
    name = str(name or "").strip()
    if not name:
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
        if str(preferences.library_user or "") == uid:
            preferences.library_user = ""
            preferences.save()
    except (AttributeError, OSError):
        pass    # the next open lands in ASK either way
    return True


def _looks_like_uid(value: str) -> bool:
    """Is this a minted UID rather than a person's name? 32 hex characters, the `uuid4().hex` shape."""
    value = str(value or "")
    return len(value) == 32 and all(
        c in "0123456789abcdef" for c in value)


def rename(preferences, uid, name: str) -> bool:
    """Relink a UID's name. Nothing tagged is touched - one field write, where a name-keyed store would need `keyed_store.rekey`."""
    uid = str(uid)
    name = str(name or "").strip()
    store = _store(preferences)
    record = store.get(uid)
    if not name or not record:
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
    """This machine's user for this library, or None when the caller must ASK - never papered over with a mint, since only the caller can put a picker on screen; the MINT path adopts a legacy NAME left in the pointer (an install signing as Plum stays Plum) but never a stale UID."""
    state = first_run_state(preferences)
    if state == RESOLVED:
        return str(preferences.library_user)
    if state == ASK:
        return None
    try:
        carried = str(preferences.library_user or "").strip()
    except AttributeError:
        carried = ""
    if _looks_like_uid(carried):
        carried = ""    # a pointer at a DELETED user is a UID, never a name to mint under
    uid = create(preferences, carried or random.choice(PLACEHOLDER_NAMES))
    if not uid:
        return None
    return adopt(preferences, uid)


def adopt(preferences, uid):
    """Point this machine at `uid` and remember it - what the picker calls once the user has chosen."""
    uid = str(uid)
    try:
        preferences.library_user = uid
        preferences.save()
    except (AttributeError, OSError):
        return uid    # the session still works; the next one asks again
    return uid


def forget() -> None:
    """Drop the cache - a library switch or a test needs a re-read."""
    keyed_store.release()
