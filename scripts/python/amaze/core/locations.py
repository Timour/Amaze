"""Registered FILE LOCATIONS and File FAVOURITES, as library stores. Content facts follow the library; only the POINTER to it stays in settings.json, which also keeps a last-known copy so the list still shows when the library is unreachable - write that copy FROM the store, never back into it. Order lives in the local list, not the store (`sort_keys=True` loses it). Records are PER-USER (`user_tagged`); with a library present and no user picked, reads serve the copy and writes refuse. ▸o/keyed-store"""

from __future__ import annotations

import os

from amaze.core import debug, keyed_store
from amaze.helpers import hostos


LOCATIONS_FILE = keyed_store.LOCATIONS
FAVOURITES_FILE = keyed_store.FAVOURITES

MIGRATED_KEY = "file_locations_migrated"  # set once the six settings.json keys proved to have landed in the library; `_store_was_lost` clears it on purpose, so the migration is also the recovery path for a deleted or restored-away locations.json

FIELDS = ("registered", "name", "color", "show_all", "recursive")  # the record's fields; `registered` had no old settings surface of its own - it was membership of the file_folders LIST, which is why an undecorated location was invisible to location_paths()

_deferred: set = globals().get("_deferred", set())  # libraries whose migration was tried this session and did not land; survives module reloads for the same reason the registry does


def normalise(value) -> dict:
    """A well-formed location record, or {} for junk - `show_all` is the one field whose FALSE is a real value (an override of the global Show Unknown Files preference), so falsy fields are not blanket-dropped."""
    if not isinstance(value, dict):
        return {}
    known = ("registered", "name", "color", "show_all", "recursive")  # unknown fields ride along: a newer build's field must survive an older build's rewrite, the engine's own whole-foreign-entries rule one level up
    record = {k: v for k, v in value.items() if k not in known}
    if value.get("registered"):
        record["registered"] = True
    name = value.get("name")
    if isinstance(name, str) and name.strip():
        record["name"] = name
    color = value.get("color")
    if isinstance(color, str) and color.strip():
        record["color"] = color
    if value.get("show_all") is not None:
        record["show_all"] = bool(value.get("show_all"))
    if value.get("recursive"):
        record["recursive"] = True
    return record


def normalise_favourite(value) -> dict:
    """A star - stored as a record rather than a bare true so the file has somewhere to grow and reads like every other store in the engine."""
    if not value:
        return {}
    return {"favourite": True}


SPEC = keyed_store.bind(LOCATIONS_FILE, normalise)
FAVOURITES_SPEC = keyed_store.bind(FAVOURITES_FILE, normalise_favourite)


def library_present(preferences) -> bool:
    """Is the library folder actually there to be read? Asked of the FILESYSTEM, not the store: a store opened against an unmounted directory reports FRESH-absent, indistinguishable from a brand new library - answering that no folders exist at exactly the moment the truth is that they cannot be seen."""
    directory = str(getattr(preferences, "dir", "") or "")
    return bool(directory) and os.path.isdir(directory)


def isolated(preferences) -> bool:
    """Test Mode: this library keeps its OWN locations and the settings copy is neither read into it nor written from it - the copy is a MIGRATION SEED, and a test library allowed to touch it would arm a future repair of the REAL library with test data (measured 2026-08-08 on the first switch). A fresh test library starts with no locations, which is the honest answer."""
    return bool(getattr(preferences, "test_mode", False)
                and getattr(preferences, "test_dir", ""))


def showing_last_known(preferences) -> bool:
    """Is the File section showing the settings.json copy rather than the library's own answer - the tests' spelling of the unreachable state (product paths branch on `_ready` internally), which is its reason to stay."""
    return not _ready(preferences)


def _awaiting_user(preferences) -> bool:
    """The store is per-user and nobody has been picked, so it cannot answer WHOSE locations these are - reads then serve the settings copy (the sidebar keeps its last-known list through the ASK dialog) and writes are refused, because a copy-written folder would silently vanish the moment a user is picked."""
    if not SPEC.user_tagged:
        return False
    try:
        return not str(preferences.library_user or "")
    except AttributeError:
        return True


def _ready(preferences) -> bool:
    """Is the library's own answer the one to use? Present, writable, not awaiting a user, migrated, and the untagged rows adopted - the migration is attempted HERE as well as at load because `dir` can be set long after settings were read, and the copy stays the truth until it has landed."""
    if not library_present(preferences):
        return False
    if not _store(preferences).writable:
        return False
    if isolated(preferences):
        _adopt_untagged(preferences)  # NO MIGRATION under Test Mode - falling through would seed it from the real library's copy; the untagged-row adoption DOES run, moving rows inside this library's own file
        return True
    if _awaiting_user(preferences):
        return False  # not parked: the check is one attribute read, and the ASK dialog can land a user mid-session - the very next read serves the store
    data = getattr(preferences, "data", None)
    if isinstance(data, dict) and data.get(MIGRATED_KEY, False) \
            and _store_was_lost(preferences):
        debug.event("file", "the location store is empty but the copy is "  # SELF-HEALING (2026-08-05): a restored snapshot or hand-deleted locations.json on an already-migrated machine re-enters the migration, which re-seeds from the copy; the union rule handles anything another machine added since
                            "not - migrating again",
                    known=len(getattr(preferences, "last_known_folders", ())))
        data.pop(MIGRATED_KEY, None)
    if isinstance(data, dict) and not data.get(MIGRATED_KEY, False):
        key = str(getattr(preferences, "dir", ""))  # once per library per session: this is reached from the paint path, and a migration that cannot land must not be retried per tile
        if key in _deferred:
            return False
        migrate(preferences)
        if not data.get(MIGRATED_KEY, False):
            _deferred.add(key)
            return False
    if not _adopt_untagged(preferences):
        return False  # pre-tag rows still await their owner: the copy keeps serving and the rows stay in the file for a session that can adopt
    return True


_orphans_deferred: set = globals().get("_orphans_deferred", set())  # (dir, uid) pairs whose untagged-row adoption could not land this session - keyed on the USER too, so picking somebody in the ASK dialog or Preferences retries immediately


def _adopt_untagged(preferences) -> bool:
    """File the rows from before locations were per-user under the current user, and PROVE it landed. SELF-MARKING: the file's own untagged rows are the to-do list - the engine keeps them aside at load and `adopt_orphans` writes their tagged spellings in the single commit that retires the untagged ones. Adopt-only; runs from `_ready`, which beats every ordinary write to the rows. Answers whether the store's own answer may be SERVED; False keeps the copy serving, the rows intact."""
    store = _store(preferences)
    if not store.orphan_count():
        return True
    try:
        tag = str(preferences.library_user or "")
    except AttributeError:
        tag = ""
    if not tag:
        return False  # nobody to file them under - not parked, the next read with a user finishes the job
    key = (str(getattr(preferences, "dir", "")), tag)
    if key in _orphans_deferred:
        return False
    waiting = list(store.orphaned())
    written = store.adopt_orphans()
    if not written:
        _orphans_deferred.add(key)
        debug.event("file", "untagged locations could not be adopted",
                    reason=written.reason, waiting=len(waiting))
        return False
    missing = [p for p in waiting if not store.has(p)]
    if missing:
        _orphans_deferred.add(key)  # comparing, not counting the write (practice.md ▸ A migration must COMPARE): a row that did not read back parks the adoption and the copy keeps serving
        debug.event("file", "the location adoption did not reproduce",
                    missing=len(missing))
        return False
    debug.event("file", "locations from before the user tag adopted",
                count=len(waiting))
    return True


def _store_was_lost(preferences) -> bool:
    """Readable, already migrated, and NO FILE ON DISK while the copy holds records - a store that has genuinely never existed here (a library replaced or re-pointed). Not merely an empty table: removing the last location leaves a real `{}` file, and an empty-table rule fired DURING that removal from inside `_sync_mirror` and put the last folder straight back (measured). A deleted-but-proven file answers BLIND and `_ready` refuses before reaching here. Asks the RECORDS, not the folder list - the migration's own input derives from records, and a different surface once livelocked two derivations of one fact."""
    store = _store(preferences)
    if store.count() or os.path.exists(store.path):
        return False
    known = getattr(preferences, "last_known_records", None) or {}
    return bool(known)


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def _favourites_store(preferences):
    return keyed_store.open_store(FAVOURITES_SPEC, preferences)


def record(preferences, path: str) -> dict:
    """Everything this location keeps, as one record - a field that is not set simply is not in it."""
    if not _ready(preferences):
        return _copy_record(preferences, path)
    return _store(preferences).get(path)


def paths(preferences) -> list:
    """Every path the store mentions, registered or not - as absolutes; the portable spelling is the file's business."""
    if not _ready(preferences):
        return [hostos.expand_storage_path(hostos.storage_path_key(p))
                for p in _copy_paths(preferences)]
    return [hostos.expand_storage_path(p)
            for p in _store(preferences).all()]


def registered_paths(preferences) -> list:
    """THE SIDEBAR LIST: registered locations in the local order, with anything the other machine added appended - derived from the `registered` field rather than kept as a second list, the order coming from the settings copy per the module docstring."""
    known, seen = [], set()  # order entries and store keys meet in STORAGE spelling (the copy may hold a legacy absolute beside the portable form, and raw comparison listed one location twice); the answer expands back to absolutes because the sidebar and scanner need paths os.walk can open
    for path in (getattr(preferences, "last_known_folders", ()) or ()):
        stored = hostos.storage_path_key(path)
        if stored not in seen:
            seen.add(stored)
            known.append(stored)
    if not _ready(preferences):
        return [hostos.expand_storage_path(p) for p in known]
    live = {path for path, rec in _store(preferences).all().items()
            if rec.get("registered")}
    ordered = [path for path in known if path in live]
    ordered.extend(sorted(live.difference(ordered)))
    return [hostos.expand_storage_path(p) for p in ordered]


def move_registered(preferences, path: str, row: int) -> bool:
    """Move one registered location to another sidebar row, IN MEMORY only - the order is the settings copy's alone (the store is a sorted dict), so a move rewrites the copy via `hold_folder_order`, adopted whole so a store-only path riding at the end gets a real position the first time the user orders anything; deliberately NO save, `commit_registered_order` persists once on release."""
    current = registered_paths(preferences)  # BOTH sides in storage spelling before comparison - a raw caller path against a canonical answer read one legal spelling as "not registered" and the move returned False silently (every native os.path.join spelling on Windows)
    keys = [hostos.storage_path_key(p) for p in current]
    wanted = hostos.storage_path_key(path)
    if wanted not in keys:
        return False
    at = keys.index(wanted)
    row = max(0, min(int(row), len(current) - 1))
    if at == row:
        return False
    current.insert(row, current.pop(at))
    hold = getattr(preferences, "hold_folder_order", None)
    if not callable(hold):
        return False
    hold([hostos.storage_path_key(p) for p in current])
    return True


def commit_registered_order(preferences) -> None:
    """Persist the order `move_registered` staged - one write per gesture, on release; the copy already holds the order, so this is the plain settings save, and the next `_sync_mirror` rebuilds from this copy, which is how the order survives every later store write."""
    preferences.save()


def _copy_tag(preferences) -> str:
    """The tag this machine's COPY entries carry, "" when the store is not user-tagged - the copy is keyed the way the store is, or the two disagree the moment the flag moves; both ends of the copy live in this module, so the tag does too."""
    if not FAVOURITES_SPEC.user_tagged:
        return ""
    try:
        return str(preferences.library_user or "")
    except AttributeError:
        return ""


def _copy_favourites(preferences) -> list:
    """THIS user's favourites out of the settings.json copy, UNTAGGED - without the scoping the copy answered for everybody, lighting another user's star on a machine with nobody picked while the store itself correctly wrote nothing."""
    raw = [p for p in (getattr(preferences, "last_known_favourites", ())
                       or ()) if isinstance(p, str) and p]
    if not FAVOURITES_SPEC.user_tagged:
        return raw
    tag = _copy_tag(preferences)
    if not tag:
        return []
    out = []
    for entry in raw:
        owner, sep, rest = entry.partition(keyed_store.USER_SEP)
        if sep and owner == tag:
            out.append(rest)
    return out


def _tag_for_copy(preferences, favourites):
    """What to hand `keep_last_known`: tagged when the store is, everyone ELSE's entries kept verbatim - None when there is nobody to attribute to, which the caller treats as leave-it-alone."""
    if not FAVOURITES_SPEC.user_tagged:
        return list(favourites)
    tag = _copy_tag(preferences)
    if not tag:
        return None
    mine = tag + keyed_store.USER_SEP
    others = [str(e) for e in
              (getattr(preferences, "last_known_favourites", ()) or ())
              if not str(e).startswith(mine)]
    return others + [mine + str(p) for p in favourites]


def favourite_paths(preferences) -> list:
    if not _ready(preferences):
        return [hostos.expand_storage_path(hostos.storage_path_key(p))
                for p in _copy_favourites(preferences)]
    return [hostos.expand_storage_path(p)
            for p in sorted(_favourites_store(preferences).all())]


def is_favourite(preferences, path: str) -> bool:
    """The star's question, asked per row per repaint - a membership test, no copy, compared in STORAGE spelling so the star does not depend on which spelling registered the file; the key is a file PATH for File rows and a bare asset id everywhere else, and an id rides through the conversion unchanged. The migration hook is the same cheap early-out `_ready` keeps."""
    migrate_asset_favourites(preferences)
    if not _ready(preferences):
        wanted = hostos.storage_path_key(path)
        return wanted in {hostos.storage_path_key(p)
                          for p in _copy_favourites(preferences)}
    return _favourites_store(preferences).has(path)


_generation = 0  # bumped on every record write - the cache token for the paint path: a colour set through ANY prefs surface must show on the very next data() read with no notification channel, and this is the one write door


def generation() -> int:
    """A number that moves whenever any location record moves."""
    return _generation


def set_record(preferences, path: str, value) -> keyed_store.Written:
    """Write one location's whole record; an EMPTY record forgets the location across every field at once, registration included - the one call a removal and a relocation both go through. WITH NO LIBRARY IT WRITES THE COPY: the File section works with no library configured, and the copy is the only truth available - the migration carries it in the moment a library appears."""
    global _generation
    _generation += 1
    path = hostos.storage_path_key(path)  # STORAGE spelling from here down, so the store and the copy hold the same portable form
    if not _ready(preferences):
        if library_present(preferences) and _awaiting_user(preferences):
            return keyed_store.Written(  # library there, store per-user, nobody picked: refused like a favourite's - the folder never appears, which is the report; a copy-only folder would show now and silently vanish when a user is picked
                False, keyed_store.REASON_NO_USER, "", (path,))
        return _write_copy(preferences, path, value)
    written = _store(preferences).set(path, value or {})
    _sync_mirror(preferences)
    return written


def register(preferences, path: str) -> keyed_store.Written:
    """Register a location pointer - keeps whatever the record already carries, so re-adding a folder another machine labelled does not throw the label away."""
    current = record(preferences, path)
    current["registered"] = True
    return set_record(preferences, path, current)


def unregister(preferences, path: str) -> keyed_store.Written:
    """Forget a location entirely - everything ELSE keyed under it (favourites, comments, tile icons) goes through the engine's `retire_prefix`, which the File model calls; this is the pointer."""
    return set_record(preferences, path, {})


def set_field(preferences, path: str, field: str, value) -> keyed_store.Written:
    """One field of one location, read-modify-write through the record - named so setting the colour cannot become writing a record holding only a colour, which is how a registration would disappear behind a sidebar colour pick."""
    if field not in FIELDS:
        raise ValueError("%r is not a location field" % (field,))
    current = record(preferences, path)
    if value is None or value == "" or value is False and field != "show_all":
        current.pop(field, None)
    else:
        current[field] = value
    return set_record(preferences, path, current)


def relocate_record(preferences, old: str, new: str) -> keyed_store.Written:
    """Move ONE location's record to a new path in one write - two `set_record` trips could half-land on a transient outage, deregistering the location and losing its colour, name, recursion and Show All; the engine's `rekey` is one guarded write that lands whole or not at all."""
    global _generation
    _generation += 1
    old = hostos.storage_path_key(old)
    new = hostos.storage_path_key(new)
    if not old or not new or old == new:
        return keyed_store.Written(True, keyed_store.REASON_UNCHANGED)
    if not _ready(preferences):
        if library_present(preferences) and _awaiting_user(preferences):
            return keyed_store.Written(  # same refusal as set_record: nobody picked, nobody to move a record for
                False, keyed_store.REASON_NO_USER, "", (old, new))
        record = _copy_record(preferences, old)  # no library to write into: the copy is the only truth, and it carries the record under its own key
        _write_copy(preferences, old, {})
        return _write_copy(preferences, new, record)
    written = _store(preferences).rekey({old: new})
    _sync_mirror(preferences)
    return written


def set_favourite(preferences, path: str, on: bool) -> keyed_store.Written:
    migrate_asset_favourites(preferences)  # the migration runs BEFORE the write, so an unstar cannot be resurrected by a later union of the not-yet-moved settings list
    path = hostos.storage_path_key(path)
    if not _ready(preferences):
        return _write_copy_favourite(preferences, path, bool(on))
    written = _favourites_store(preferences).set(path, bool(on))
    _sync_mirror(preferences)
    return written


def _copy_record(preferences, path: str) -> dict:
    """One record out of the copy, only reached when the library is not there to answer - the copy may predate the portable spelling, so the raw path is the second look."""
    records = getattr(preferences, "last_known_records", None) or {}
    return dict(records.get(hostos.storage_path_key(path))
                or records.get(path) or {})


def _copy_paths(preferences) -> list:
    return list((getattr(preferences, "last_known_records", None) or {}))


def _write_copy(preferences, path: str, value) -> keyed_store.Written:
    """A location write with no library to put it in."""
    keep = getattr(preferences, "keep_last_known", None)
    if not callable(keep):
        return keyed_store.Written(False, keyed_store.REASON_DENIED, "",
                                   (path,))
    records = dict(getattr(preferences, "last_known_records", None) or {})
    order = list(getattr(preferences, "last_known_folders", ()) or ())
    value = normalise(value or {})
    if value:
        records[path] = value
        if value.get("registered") and path not in order:
            order.append(path)
        elif not value.get("registered") and path in order:
            order.remove(path)
    else:
        records.pop(path, None)
        if path in order:
            order.remove(path)
    keep(records, order, None)
    return keyed_store.Written(True, keyed_store.REASON_NONE, "", (path,))


def _write_copy_favourite(preferences, path: str,
                          on: bool) -> keyed_store.Written:
    keep = getattr(preferences, "keep_last_known", None)
    if not callable(keep):
        return keyed_store.Written(False, keyed_store.REASON_DENIED, "",
                                   (path,))
    favourites = _copy_favourites(preferences)
    if on and path not in favourites:
        favourites.append(path)
    elif not on and path in favourites:
        favourites.remove(path)
    else:
        return keyed_store.Written(True, keyed_store.REASON_UNCHANGED,
                                   keys=(path,))
    tagged = _tag_for_copy(preferences, favourites)
    if tagged is None:
        return keyed_store.Written(False, keyed_store.REASON_NO_USER, "",  # nobody picked, nobody to attribute to - the store refuses the same write for the same reason
                                   (path,))
    keep(None, None, tagged)
    return keyed_store.Written(True, keyed_store.REASON_NONE, "", (path,))


def _sync_mirror(preferences) -> None:
    """Refresh the settings.json copy from what the library now says, and persist it - ONE direction only: a mirror that can write is a second truth, and two truths over one fact is the whole defect this module exists to end. Declines under Test Mode (the copy is the seed a future repair of the REAL library reads) and with nobody picked (a scoped read answers {}, which is "no answer", not "no locations" - blanking the copy with it would lose the fallback while it is serving)."""
    if not library_present(preferences):
        return
    if isolated(preferences):
        return
    if _awaiting_user(preferences):
        return
    store = _store(preferences)
    favourites = _favourites_store(preferences)
    if not store.writable and not favourites.writable:
        return
    keep = getattr(preferences, "keep_last_known", None)
    if not callable(keep):
        return
    mine = (_tag_for_copy(preferences, sorted(favourites.all()))
            if favourites.writable else None)
    keep(store.all() if store.writable else None,
         registered_paths(preferences) if store.writable else None,
         mine)


def _from_settings(preferences) -> tuple:
    """What the migration carries in: THE COPY, never the accessors - `file_folder_names` and its siblings are derived from this module now, so reading them would ask the migration's own output what the migration should write, re-entering `_ready` on the way."""
    records = {}
    for path, value in (getattr(preferences, "last_known_records", None)
                        or {}).items():
        value = normalise(value)
        if value:
            records[path] = value
    favourites = _copy_favourites(preferences)
    return records, favourites


def migrate(preferences) -> dict:
    """Move the six settings.json keys into the two library stores and PROVE it landed before saying so - the acceptance test is the END STATE (practice.md ▸ A migration must COMPARE): every record read back and compared BOTH ways, a disagreement leaving the marker unset and the old keys intact. Answers a dict because the not-done outcomes differ: `deferred` (no library or user yet) and `refused` (did not land). A success reports how many of this machine's locations JOINED ones already there, because on the second machine that union is the visible outcome."""
    if getattr(preferences, "data", None) is None:
        return {"state": "deferred", "why": "no settings"}
    if preferences.data.get(MIGRATED_KEY, False):
        return {"state": "done"}
    if not library_present(preferences):
        return {"state": "deferred", "why": "no library"}
    store = _store(preferences)
    favourites = _favourites_store(preferences)
    if not store.writable or not favourites.writable:
        return {"state": "refused", "why": "the store cannot be written"}

    mine, my_favs = _from_settings(preferences)

    existing = store.all()  # THE UNION, ADOPT-ONLY (the engine's own rule): settings.json never travels, so this machine's keys are its OWN folders, not a stale copy of the other machine's - taking the store as-is would empty a sidebar, and the honest cost is both machines converging on the union, which Remove Folder can undo where a silent discard could not
    wanted = dict(existing)
    for path, record in mine.items():  # STORAGE spelling before the union and the compare: the copy's legacy spellings can never reproduce against the store's portable form, and converting here also collapses the copy's own duplicates, first in winning
        path = hostos.storage_path_key(path)
        if path not in wanted:
            wanted[path] = record
    wanted_favs = sorted(set(favourites.all())
                         | {hostos.storage_path_key(p) for p in my_favs})
    adopted = len(wanted) - len(existing)

    written = store.update(wanted)
    if not written and written.reason == keyed_store.REASON_NO_USER:
        debug.event("file", "locations waiting for a user",  # BOTH halves belong to a person since the per-user tag: with nobody picked the whole migration waits, marker unset, old keys still the truth
                    locations=len(wanted))
        return {"state": "deferred", "why": "no user yet"}
    written_favs = favourites.update({p: True for p in wanted_favs})
    if not written:
        debug.event("file", "location migration refused",
                    reason=written.reason)
        return {"state": "refused", "why": written.reason}
    if not written_favs:
        if written_favs.reason == keyed_store.REASON_NO_USER:
            debug.event("file", "locations moved, favourites waiting "  # a belt for a user cleared between the two writes: marker unset, a later session finishes the favourites
                        "for a user", locations=len(wanted),
                        favourites=len(wanted_favs))
            return {"state": "deferred", "why": "no user yet"}
        debug.event("file", "location migration refused",
                    reason=written_favs.reason)
        return {"state": "refused", "why": written_favs.reason}

    landed = store.all()
    landed_favs = set(favourites.all())
    missing = [p for p in wanted if landed.get(p) != wanted[p]]
    extra = [p for p in landed if p not in wanted]
    missing_favs = [p for p in wanted_favs if p not in landed_favs]
    extra_favs = [p for p in landed_favs if p not in wanted_favs]
    if missing or extra or missing_favs or extra_favs:
        debug.event("file", "location migration did not reproduce",  # NOT MARKED: the old keys are still written and read, so the section keeps working off them and the next launch tries again
                    missing=len(missing), extra=len(extra),
                    missing_favourites=len(missing_favs),
                    extra_favourites=len(extra_favs))
        return {"state": "refused", "why": "the stores do not match",
                "missing": missing, "extra": extra}

    preferences.data[MIGRATED_KEY] = True
    _sync_mirror(preferences)
    preferences.save()
    debug.event("file", "locations moved into the library",
                locations=len(wanted), favourites=len(wanted_favs),
                joined=adopted, already_there=len(existing))
    return {"state": "migrated", "locations": len(wanted),
            "favourites": len(wanted_favs),
            "joined": adopted, "already_there": len(existing)}  # `joined`: how many of this machine's locations joined ones the other machine already put there - a visible product outcome, the second sidebar growing by the first's folders


_asset_deferred: set = globals().get("_asset_deferred", set())  # (dir, uid) pairs whose asset-favourites migration could not land this session - keyed on the USER too, so picking one in the ASK dialog or Preferences retries immediately; reload-stable like its two siblings above


def migrate_asset_favourites(preferences) -> dict:
    """Move `material_favorites` (the Materials/Nodes/Code stars that lived in settings.json and never travelled) into the favourites store under the active user, and PROVE it landed before the key is dropped. SELF-MARKING: the settings key IS the to-do list, popped only after every id reads back, so a deferral or refusal leaves the old key authoritative. Adopt-only union like `migrate`. Runs from the favourite doors as well as load, because `dir` and the user can both be set long after settings were read."""
    data = getattr(preferences, "data", None)
    if not isinstance(data, dict):
        return {"state": "deferred", "why": "no settings"}
    raw = [str(x) for x in (data.get("material_favorites") or ())
           if str(x).strip()]
    if not raw:
        data.pop("material_favorites", None)  # an empty list is finished business - drop the key so the unknown-key courtesy stops carrying it forever
        return {"state": "done"}
    if isolated(preferences):
        return {"state": "deferred", "why": "test mode"}  # these are the real library's stars; landing them in a test library would pop the key and lose them for the real one
    key = (str(getattr(preferences, "dir", "")),
           str(getattr(preferences, "library_user", "") or ""))
    if key in _asset_deferred:
        return {"state": "deferred", "why": "already tried"}
    if not library_present(preferences):
        _asset_deferred.add(key)
        return {"state": "deferred", "why": "no library"}
    store = _favourites_store(preferences)
    if not store.writable:
        _asset_deferred.add(key)
        return {"state": "refused", "why": "the store cannot be written"}
    written = store.update({sid: True for sid in raw})
    if not written:
        _asset_deferred.add(key)
        if written.reason == keyed_store.REASON_NO_USER:
            debug.event("file", "asset favourites waiting for a user",
                        favourites=len(raw))
            return {"state": "deferred", "why": "no user yet"}
        debug.event("file", "asset favourite migration refused",
                    reason=written.reason)
        return {"state": "refused", "why": written.reason}
    missing = [sid for sid in raw if not store.has(sid)]
    if missing:
        _asset_deferred.add(key)  # NOT POPPED: the old key is still the truth and the next session tries again - comparing, not counting the write
        debug.event("file", "asset favourite migration did not "
                            "reproduce", missing=len(missing))
        return {"state": "refused", "why": "the store does not match"}
    data.pop("material_favorites", None)
    save = getattr(preferences, "save", None)
    if callable(save):
        save()
    debug.event("file", "asset favourites moved into the library",
                favourites=len(raw))
    return {"state": "migrated", "favourites": len(raw)}


def forget() -> None:
    """Drop the cached tables AND the deferred sets - the library switch's own door (`switch_all_models` calls this), because a switch is exactly the change that earns an unreachable library another migration try; also the test seam."""
    _deferred.clear()
    _asset_deferred.clear()
    _orphans_deferred.clear()
    keyed_store.release()
