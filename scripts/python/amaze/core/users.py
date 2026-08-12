"""Who uses this library: a `uuid4` UID with a `name` beside it.

Everything a user owns is tagged with the UID and never with the typed
name, so a rename relinks the label and moves nothing (ROADMAP line 21,
which also carries what is user-scoped and what is not).
"""

from __future__ import annotations

import random
import uuid

from amaze.core import keyed_store

USERS_FILE = "users.json"

#: The pool a library's FIRST user is named from: minted once per
#: LIBRARY, never per machine, and never the OS user or the machine
#: name (ROADMAP line 21 - it lived in `versions.py` and the unit is
#: what changed).
PLACEHOLDER_NAMES = (
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

#: What the first open of a library must do about identity: the pointer
#: already names someone this library knows, the library has nobody yet,
#: or it HAS people and this machine is not one of them.
#:
#: ASK is the one that earns its cost - it stops a second machine
#: minting a second identity for one person (ROADMAP line 21).
RESOLVED = "resolved"
MINT = "mint"
ASK = "ask"


def normalise(value) -> dict:
    """A well-formed record, or {} for junk: a user with no name cannot
    be shown in a picker, so it reads as absent."""
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
    """Mint a user and answer its UID, or "" if the store refused.

    Names are not checked for uniqueness: two people called Anna are two
    UIDs, and forbidding it would key on the name through the back door.
    """
    name = str(name or "").strip()
    if not name:
        return ""
    uid = uuid.uuid4().hex
    if not _store(preferences).set(uid, {"name": name}):
        # A UID that is not on disk would orphan everything tagged with
        # it the moment the session ends.
        return ""
    return uid


def rename(preferences, uid, name: str) -> bool:
    """Relink a UID's name. Nothing tagged is touched - one field
    write, where a name-keyed store would need `keyed_store.rekey`."""
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
    """This machine's user for this library, or None when the caller
    must ask.

    None is not an error and must not be papered over with a mint: it is
    a second machine meeting a library that already has people in it,
    and only the caller can put a picker on screen.
    """
    state = first_run_state(preferences)
    if state == RESOLVED:
        return str(preferences.library_user)
    if state == ASK:
        return None
    try:
        carried = str(preferences.library_user or "").strip()
    except AttributeError:
        carried = ""
    # A name left by the first build is ADOPTED, so an install already
    # signing as Plum keeps being Plum and its stems still match.
    uid = create(preferences, carried or random.choice(PLACEHOLDER_NAMES))
    if not uid:
        return None
    return adopt(preferences, uid)


def adopt(preferences, uid):
    """Point this machine at `uid` and remember it - what the picker
    calls once the user has chosen."""
    uid = str(uid)
    try:
        preferences.library_user = uid
        preferences.save()
    except (AttributeError, OSError):
        # The session still works; the next one asks again.
        return uid
    return uid


def forget() -> None:
    """Drop the cache - a library switch or a test needs a re-read."""
    keyed_store.release()
