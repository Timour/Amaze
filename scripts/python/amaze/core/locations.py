"""Registered file locations and File favourites as per-user library stores. ▸o/keyed-store"""

from __future__ import annotations

import os
import uuid

from amaze.core import debug, keyed_store
from amaze.helpers import hostos


LOCATIONS_FILE = keyed_store.LOCATIONS
FAVOURITES_FILE = keyed_store.FAVOURITES
IDS_FILE = keyed_store.LOCATION_PATHS

LOC_PREFIX = keyed_store.LOC_PREFIX

MIGRATED_KEY = "file_locations_migrated"  # set once the settings keys proved landed in the library

FIELDS = ("registered", "name", "color", "show_all", "recursive",
          "kinds", "pathname")  # the record's fields, each with its own branch in normalise()

KIND_IMAGE = "image"  # the kinds a record's `kinds` field lists; stored in locations.json, so fixed
KIND_GEO = "geometry"
KIND_HIP = "hip"
KIND_OTHER = "other"
SHOWN_BY_DEFAULT = (KIND_IMAGE, KIND_GEO, KIND_HIP)    # what Show ▸ ticks on a new location
EVERY_KIND = SHOWN_BY_DEFAULT + (KIND_OTHER,)    # the Import location's ticks: a package carries any file

_deferred: set = globals().get("_deferred", set())  # libraries whose migration did not land this session


def normalise(value) -> dict:
    """A well-formed location record, or {} for junk; `show_all` keeps False, unknown fields pass."""
    if not isinstance(value, dict):
        return {}
    known = FIELDS  # a field added to FIELDS needs its own branch below or its write vanishes
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
    kinds = value.get("kinds")
    if isinstance(kinds, (list, tuple)):    # [] is a real value: Show ▸ with no kind ticked
        record["kinds"] = sorted({kind for kind in kinds if isinstance(kind, str)})
    if value.get("pathname"):
        record["pathname"] = True
    return record


def normalise_favourite(value) -> dict:
    """A star, stored as the record {"favourite": True}, or {} for none."""
    if not value:
        return {}
    return {"favourite": True}


def normalise_location_path(value) -> dict:
    """An identity row, or {} for junk; its required path is kept verbatim, trailing separator too."""
    if not isinstance(value, dict):
        return {}
    path = value.get("path")
    if not isinstance(path, str) or not path.strip():
        return {}
    record = {k: v for k, v in value.items() if k != "path"}
    record["path"] = path
    return record


def _same_path(a: str, b: str) -> bool:
    """One location, two legal spellings - the trailing separator never separates them."""
    return keyed_store.path_identity(a) == keyed_store.path_identity(b)


SPEC = keyed_store.bind(LOCATIONS_FILE, normalise)
FAVOURITES_SPEC = keyed_store.bind(FAVOURITES_FILE, normalise_favourite)
IDS_SPEC = keyed_store.bind(IDS_FILE, normalise_location_path)


def library_present(preferences) -> bool:
    """Is the library folder there to be read? Asked of the filesystem, not the store."""
    directory = str(getattr(preferences, "dir", "") or "")
    return bool(directory) and os.path.isdir(directory)


def isolated(preferences) -> bool:
    """Test Mode: this library keeps its own locations; the settings copy is never read or written."""
    return bool(getattr(preferences, "test_mode", False)
                and getattr(preferences, "test_dir", ""))


def showing_last_known(preferences) -> bool:
    """Is the File section showing the settings.json copy rather than the library's own answer?"""
    return not _ready(preferences)


def _awaiting_user(preferences) -> bool:
    """The store is per-user and nobody is picked: reads serve the settings copy, writes refuse."""
    if not SPEC.user_tagged:
        return False
    try:
        return not str(preferences.library_user or "")
    except AttributeError:
        return True


def ready(preferences) -> bool:
    """Whether file idents can be read now - the gate for a per-file store keyed on them."""
    return _ready(preferences)


_ready_memo: tuple = ((), False)    # (key, answer)


def _ready_key(preferences) -> tuple:
    """What moves `_ready_now`'s answer, but the disk: writes, store loads, library, user, conversion."""
    library = str(getattr(preferences, "dir", ""))
    return (_generation, keyed_store.loads(), library, library in _converted,
            str(getattr(preferences, "library_user", "") or ""))


def _ready(preferences) -> bool:
    """`_ready_now`, once per generation: the paint path asks per cell. An unmount shows at a write."""
    global _ready_memo
    if _ready_memo[0] == _ready_key(preferences):
        return _ready_memo[1]
    answer = _ready_now(preferences)
    _ready_memo = (_ready_key(preferences), answer)    # after: the answer may migrate or bump
    return answer


def _ready_now(preferences) -> bool:
    """Is the library's own answer the one to use? May run the migration and the adoption."""
    if not library_present(preferences):
        return False
    if not _store(preferences).writable:
        return False
    if not _ids_store(preferences).writable:
        return False  # every `loc:` key resolves through the identity table
    if isolated(preferences):
        _adopt_untagged(preferences)  # no migration under Test Mode; adoption only
        _convert_once(preferences)
        return True
    if _awaiting_user(preferences):
        return False  # not parked: a user picked mid-session is served on the next read
    data = getattr(preferences, "data", None)
    if isinstance(data, dict) and data.get(MIGRATED_KEY, False) \
            and _store_was_lost(preferences):
        debug.event("file", "the location store is empty but the copy is "  # a lost store re-migrates from the copy
                            "not - migrating again",
                    known=len(getattr(preferences, "last_known_folders", ())))
        data.pop(MIGRATED_KEY, None)
    if isinstance(data, dict) and not data.get(MIGRATED_KEY, False):
        key = str(getattr(preferences, "dir", ""))  # one migration try per library per session
        if key in _deferred:
            return False
        migrate(preferences)
        if not data.get(MIGRATED_KEY, False):
            _deferred.add(key)
            return False
    if not _adopt_untagged(preferences):
        return False  # untagged rows still await their owner; the copy keeps serving
    _convert_once(preferences)
    return True


def _convert_once(preferences) -> None:
    """`convert_to_ids` once per library per session; clearing `_converted` re-arms it."""
    key = str(getattr(preferences, "dir", ""))
    if key not in _converted:
        _converted.add(key)
        convert_to_ids(preferences)


_orphans_deferred: set = globals().get("_orphans_deferred", set())  # (dir, uid) pairs whose adoption did not land this session


def _adopt_untagged(preferences) -> bool:
    """File untagged rows under the current user and prove it; False keeps the copy serving."""
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
        _orphans_deferred.add(key)  # a row that did not read back parks it ▸p/migration-compare-assume
        debug.event("file", "the location adoption did not reproduce",
                    missing=len(missing))
        return False
    debug.event("file", "locations from before the user tag adopted",
                count=len(waiting))
    return True


def _store_was_lost(preferences) -> bool:
    """No store file on disk while the copy holds records; an empty `{}` file is not lost."""
    store = _store(preferences)
    if store.count() or os.path.exists(store.path):
        return False
    known = getattr(preferences, "last_known_records", None) or {}
    return bool(known)


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def _favourites_store(preferences):
    return keyed_store.open_store(FAVOURITES_SPEC, preferences)


def _ids_store(preferences):
    return keyed_store.open_store(IDS_SPEC, preferences)


_id_map: tuple = globals().get("_id_map", ("", -1, {}))  # (dir, generation, {normalised path: smallest id at it})


def _id_table(preferences) -> dict:
    global _id_map
    key = str(getattr(preferences, "dir", ""))
    if _id_map[0] == key and _id_map[1] == _generation:
        return _id_map[2]
    table = {}
    for lid in sorted(_ids_store(preferences).all()):    # sorted, so the FIRST id at a path is the smallest - the same winner the rival collapse keeps
        path = str(_ids_store(preferences).get(lid).get("path") or "")
        if path:
            table.setdefault(keyed_store.path_identity(path), lid)
    _id_map = (key, _generation, table)
    return table


def location_id(preferences, path: str, mint: bool = False) -> str:
    """The id of the location at `path`, "" for none; `mint=True` creates one, shared by all users."""
    global _generation
    wanted = hostos.storage_path_key(str(path))
    best = _id_table(preferences).get(keyed_store.path_identity(wanted), "")
    if best or not mint:
        return best
    lid = uuid.uuid4().hex
    if not _ids_store(preferences).set(lid, {"path": wanted}):    # the verbatim spelling, trailing separator included
        return ""
    _generation += 1
    return lid


def location_path_for(preferences, locid: str) -> str:
    """The STORAGE-spelling path a location id points at, "" for an unknown id."""
    return str(_ids_store(preferences).get(str(locid)).get("path") or "")


def _path_of_key(preferences, key: str) -> str:
    """The storage-spelling path behind a record key: a `loc:` key resolved, a legacy path as is."""
    key = str(key)
    if key.startswith(LOC_PREFIX):
        return location_path_for(preferences, key[len(LOC_PREFIX):])
    return key


def _legacy_spelling(preferences, ident: str) -> str:
    """A `loc:<id>/<relative>` ident as the storage path it means today, "" for anything else."""
    ident = str(ident)
    if not ident.startswith(LOC_PREFIX):
        return ""
    head, _, rel = ident[len(LOC_PREFIX):].partition("/")
    base = location_path_for(preferences, head)
    if not base:
        return ""
    return base + ("/" + rel if rel else "")


def _ident_under(owners: dict, stored: str) -> str:
    """The `loc:` ident of a stored path under the innermost of `owners` ({path: id}), or ""."""
    best, found = "", ""
    for base, lid in owners.items():
        if (stored == base or stored.startswith(base + "/")) \
                and len(base) > len(best):
            best, found = base, lid
    if not found:
        return ""
    rel = stored[len(best) + 1:] if len(stored) > len(best) else ""
    return LOC_PREFIX + found + ("/" + rel if rel else "")


def innermost(bases, path: str) -> str:
    """The longest of `bases` that is `path` or a folder above it, as given; "" for none."""
    key = hostos.canonical_path_key(str(path)).rstrip("/")
    best, length = "", -1
    for base in bases:
        root = hostos.canonical_path_key(str(base)).rstrip("/")
        if (key == root or key.startswith(root + "/")) and len(root) > length:
            best, length = base, len(root)
    return best


def owner_of(preferences, path: str) -> str:
    """The registered location a folder belongs to - the innermost when they nest - or ""."""
    return innermost(registered_paths(preferences), path)


def file_ident(preferences, full_path: str) -> str:
    """`loc:<id>/<relative>` under the innermost registered location, or ""; every per-file key."""
    if not _ready(preferences):
        return ""
    return _ident_under(_id_table(preferences),
                        hostos.storage_path_key(str(full_path)))


def record(preferences, path: str) -> dict:
    """Everything this location keeps, as one record; a field not set is absent."""
    if not _ready(preferences):
        return _copy_record(preferences, path)
    store = _store(preferences)
    lid = location_id(preferences, path)
    if lid:
        found = store.get(LOC_PREFIX + lid)
        if found:
            return found
    return store.get(path)


def paths(preferences) -> list:
    """Every path the store mentions, registered or not, as absolutes."""
    if not _ready(preferences):
        return [hostos.expand_storage_path(hostos.storage_path_key(p))
                for p in _copy_paths(preferences)]
    out = []
    for key in _store(preferences).all():
        path = _path_of_key(preferences, key)
        if path:
            out.append(hostos.expand_storage_path(path))
    return out


def _copy_order(preferences) -> list:
    """The settings copy's sidebar order in STORAGE spelling, each location once, however written."""
    order, seen = [], set()
    for path in (getattr(preferences, "last_known_folders", ()) or ()):
        stored = hostos.storage_path_key(path)
        if stored and stored not in seen:
            seen.add(stored)
            order.append(stored)
    return order


def registered_paths(preferences) -> list:
    """THE SIDEBAR LIST: registered locations in the copy's order, then the store's others."""
    return [hostos.expand_storage_path(p)    # absolutes: the sidebar and scanner open them
            for p in _registered_stored(preferences)]


def _registered_stored(preferences) -> list:
    """The sidebar list in STORAGE spelling, the spelling the copy's order is written in."""
    known = _copy_order(preferences)
    if not _ready(preferences):
        return known
    live = set()
    for key, rec in _store(preferences).all().items():
        if not rec.get("registered"):
            continue
        path = _path_of_key(preferences, key)
        if path:
            live.add(path)
    ordered = [path for path in known if path in live]
    ordered.extend(sorted(live.difference(ordered)))
    return ordered


def move_registered(preferences, path: str, row: int) -> bool:
    """Move a registered location to another sidebar row in memory; `commit_registered_order` saves."""
    current = registered_paths(preferences)  # both sides compared in storage spelling
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
    """Persist the order `move_registered` staged; call once per gesture, on release."""
    preferences.save()


def _copy_tag(preferences) -> str:
    """The user tag this machine's copy entries carry, "" when the store is not user-tagged."""
    if not FAVOURITES_SPEC.user_tagged:
        return ""
    try:
        return str(preferences.library_user or "")
    except AttributeError:
        return ""


def _copy_favourites(preferences) -> list:
    """This user's favourites out of the settings.json copy, untagged; [] with nobody picked."""
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
    """The star list for `keep_last_known`, others' entries kept; None with nobody to attribute to."""
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


def _is_file_key(key) -> bool:
    """A File star's key - a `loc:` ident or a stored path, either platform's - not an asset id."""
    key = str(key)
    return (key.startswith(LOC_PREFIX) or hostos.foreign_path(key)
            or os.path.isabs(hostos.expand_storage_path(key)))


def favourite_paths(preferences) -> list:
    """This user's FILE stars as paths; a library asset's star shares the store and is left out."""
    if not _ready(preferences):
        return [hostos.expand_storage_path(hostos.storage_path_key(p))
                for p in _copy_favourites(preferences) if _is_file_key(p)]
    out = []
    for key in sorted(_favourites_store(preferences).all()):
        if not _is_file_key(key):
            continue
        legacy = _legacy_spelling(preferences, key)    # a `loc:` ident answers as the path it means TODAY
        out.append(hostos.expand_storage_path(legacy or key))
    return out


def is_favourite(preferences, path: str) -> bool:
    """Is this `loc:` ident, path or asset id starred? Cheap enough to ask per row per repaint."""
    migrate_asset_favourites(preferences)
    if not _ready(preferences):
        wanted = hostos.storage_path_key(path)
        return wanted in {hostos.storage_path_key(p)
                          for p in _copy_favourites(preferences)}
    store = _favourites_store(preferences)
    if store.has(path):
        return True
    key = str(path)
    other = (_legacy_spelling(preferences, key)    # answers for both the ident and the path spelling
             if key.startswith(LOC_PREFIX)
             else file_ident(preferences, key))
    return bool(other) and store.has(other)


_generation = 0  # bumped on every record write; the paint path's cache token


def generation() -> int:
    """A number that moves whenever any location record moves."""
    return _generation


def touch() -> None:
    """Bump the generation after location state was edited outside this module."""
    global _generation
    _generation += 1


def set_record(preferences, path: str, value) -> keyed_store.Written:
    """Write one location's whole record; an empty one forgets it. With no library, writes the copy."""
    global _generation
    _generation += 1
    path = hostos.storage_path_key(path)  # STORAGE spelling from here down, so the store and the copy hold the same portable form
    if not _ready(preferences):
        if library_present(preferences) and _awaiting_user(preferences):
            return keyed_store.Written(  # library there, nobody picked: refused
                False, keyed_store.REASON_NO_USER, "", (path,))
        return _write_copy(preferences, path, value)
    lid = location_id(preferences, path, mint=bool(value))    # a forget writes wherever the record lives today
    key = (LOC_PREFIX + lid) if lid else path
    before = _store(preferences).get(key).get("registered")
    written = _store(preferences).set(key, value or {})
    if written and bool(before) != bool((value or {}).get("registered")):
        _converted.discard(str(getattr(preferences, "dir", "")))    # the next read re-settles owners
    _sync_mirror(preferences)
    return written


def register(preferences, path: str) -> keyed_store.Written:
    """Register a location pointer, keeping whatever the record already carries."""
    current = record(preferences, path)
    current["registered"] = True
    return set_record(preferences, path, current)


def unregister(preferences, path: str) -> keyed_store.Written:
    """Forget a location's pointer; rows keyed under it go through the engine's `retire_prefix`."""
    return set_record(preferences, path, {})


def set_field(preferences, path: str, field: str, value) -> keyed_store.Written:
    """Set one field of one location, read-modify-write through the whole record."""
    if field not in FIELDS:
        raise ValueError("%r is not a location field" % (field,))
    current = record(preferences, path)
    if value is None or value == "" or value is False and field != "show_all":
        current.pop(field, None)
    else:
        current[field] = value
    return set_record(preferences, path, current)


def relocate_record(preferences, old: str, new: str) -> keyed_store.Written:
    """Move ONE location and keep its sidebar row; its identity row carries every user and machine."""
    old = hostos.storage_path_key(old)
    new = hostos.storage_path_key(new)
    order = _copy_order(preferences)
    written = _repoint(preferences, old, new)
    if written and written.reason != keyed_store.REASON_UNCHANGED:
        _keep_row(preferences, order, old, new)
    return written


def _keep_row(preferences, order: list, old: str, new: str) -> None:
    """Put `new` where `old` stood in `order`, the copy's sidebar order from before the move."""
    keep = getattr(preferences, "keep_last_known", None)
    if not callable(keep) or not any(_same_path(p, old) for p in order):
        return
    keep(None, [new if _same_path(p, old) else p
                for p in order if not _same_path(p, new)], None)


def _repoint(preferences, old: str, new: str) -> keyed_store.Written:
    """The move: the path on the location's identity row, or the legacy rekey for one from before ids."""
    global _generation
    _generation += 1
    if not old or not new or old == new:
        return keyed_store.Written(True, keyed_store.REASON_UNCHANGED)
    if not _ready(preferences):
        if library_present(preferences) and _awaiting_user(preferences):
            return keyed_store.Written(  # same refusal as set_record: nobody picked, nobody to move a record for
                False, keyed_store.REASON_NO_USER, "", (old, new))
        record = _copy_record(preferences, old)  # no library to write into: the copy is the only truth, and it carries the record under its own key
        _write_copy(preferences, old, {})
        return _write_copy(preferences, new, record)
    lid = location_id(preferences, old)
    if lid:
        ids = _ids_store(preferences)
        old_edge, new_edge = keyed_store._boundary(old), keyed_store._boundary(new)
        rows = {}
        for other, row in ids.all().items():    # every row AT or UNDER the old path, as relocate reads one
            path = str(row.get("path") or "")
            if keyed_store.path_identity(path) == keyed_store.path_identity(old):
                rows[other] = dict(row, path=new)
            elif path.startswith(old_edge):
                rows[other] = dict(row, path=new_edge + path[len(old_edge):])
        written = ids.update(rows)
        _generation += 1    # after the row edit, so the cached map rebuilds
        _converted.discard(str(getattr(preferences, "dir", "")))    # the next read collapses rivals
        _sync_mirror(preferences)
        return written
    written = _store(preferences).rekey({old: new})
    _sync_mirror(preferences)
    return written


def set_favourite(preferences, path: str, on: bool) -> keyed_store.Written:
    return set_favourites(preferences, {path: on})


def set_favourites(preferences, wanted: dict) -> keyed_store.Written:
    """Star or unstar every `{path: on}` in ONE store write and one settings save; later keys win."""
    migrate_asset_favourites(preferences)  # BEFORE the write, so a later union cannot resurrect an unstar
    if not _ready(preferences):
        return _write_copy_favourites(
            preferences, {hostos.storage_path_key(path): bool(on)
                          for path, on in wanted.items()})
    updates = {}
    for path, on in wanted.items():
        key = str(path)
        ident = (key if key.startswith(LOC_PREFIX)
                 else file_ident(preferences, key))
        home = ident or key    # the ident is the one home; an unstar kills every twin spelling
        updates[home] = bool(on)
        for twin in (key, _legacy_spelling(preferences, ident)):
            if twin and twin != home:
                updates[twin] = False
    written = _favourites_store(preferences).update(updates)
    _sync_mirror(preferences)
    return written


def files_moved(preferences, keys: dict) -> dict:
    """Files moved on disk: their entries follow `{old key: new key}`, the settings copy too."""
    written = keyed_store.rekey_files(preferences, keys)
    _sync_mirror(preferences)
    return written


def _copy_records(preferences) -> dict:
    """The settings copy's records keyed in STORAGE spelling, however they were written."""
    return {hostos.storage_path_key(path): dict(value) for path, value in
            (getattr(preferences, "last_known_records", None) or {}).items()
            if path}


def _copy_record(preferences, path: str) -> dict:
    """One record out of the copy, matched in STORAGE spelling; read with no library to answer."""
    records = getattr(preferences, "last_known_records", None) or {}
    wanted = hostos.storage_path_key(path)
    found = records.get(wanted) or records.get(path)
    if not found:
        found = next((value for key, value in records.items()
                      if _same_path(hostos.storage_path_key(key), wanted)),
                     None)
    return dict(found or {})


def _copy_paths(preferences) -> list:
    return list((getattr(preferences, "last_known_records", None) or {}))


def _write_copy(preferences, path: str, value) -> keyed_store.Written:
    """A location write with no library to put it in; the copy is rewritten in STORAGE spelling."""
    keep = getattr(preferences, "keep_last_known", None)
    if not callable(keep):
        return keyed_store.Written(False, keyed_store.REASON_DENIED, "",
                                   (path,))
    records = {key: record for key, record in _copy_records(preferences).items()
               if not _same_path(key, path)}
    order = _copy_order(preferences)
    at = next((i for i, held in enumerate(order) if _same_path(held, path)),
              None)
    value = normalise(value or {})
    if value:
        records[path] = value
    if value.get("registered"):
        if at is None:
            order.append(path)
        else:
            order[at] = path
    elif at is not None:
        del order[at]
    keep(records, order, None)
    return keyed_store.Written(True, keyed_store.REASON_NONE, "", (path,))


def _write_copy_favourites(preferences,
                           wanted: dict) -> keyed_store.Written:
    """`set_favourites` with no library: the copy's star list, rewritten and saved once."""
    keys = tuple(wanted)
    keep = getattr(preferences, "keep_last_known", None)
    if not callable(keep):
        return keyed_store.Written(False, keyed_store.REASON_DENIED, "",
                                   keys)
    favourites = _copy_favourites(preferences)
    changed = False
    for path, on in wanted.items():
        if on and path not in favourites:
            favourites.append(path)
        elif not on and path in favourites:
            favourites.remove(path)
        else:
            continue
        changed = True
    if not changed:
        return keyed_store.Written(True, keyed_store.REASON_UNCHANGED,
                                   keys=keys)
    tagged = _tag_for_copy(preferences, favourites)
    if tagged is None:
        return keyed_store.Written(False, keyed_store.REASON_NO_USER, "",  # nobody to attribute to
                                   keys)
    keep(None, None, tagged)
    return keyed_store.Written(True, keyed_store.REASON_NONE, "", keys)


def _sync_mirror(preferences) -> None:
    """Refresh and save the settings copy from the library, one way; skipped in Test Mode or no user."""
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
    mine = None
    if favourites.writable:
        spelled = []    # the copy holds paths, not idents
        for key in sorted(favourites.all()):
            spelled.append(_legacy_spelling(preferences, key) or key)
        mine = _tag_for_copy(preferences, spelled)
    records = None
    if store.writable:
        records = {}
        for key, rec in store.all().items():
            path = _path_of_key(preferences, key)
            if path:
                records[path] = rec
    keep(records,
         _registered_stored(preferences) if store.writable else None,
         mine)


def _from_settings(preferences) -> tuple:
    """What the migration carries in, read from the copy, never the derived accessors."""
    records = {}
    for path, value in (getattr(preferences, "last_known_records", None)
                        or {}).items():
        value = normalise(value)
        if value:
            records[path] = value
    favourites = _copy_favourites(preferences)
    return records, favourites


def migrate(preferences) -> dict:
    """Move the settings keys into the library, proven; a `state` dict. ▸p/migration-compare-assume"""
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

    existing = store.all()  # adopt-only union: this machine's folders join the store's
    wanted = dict(existing)
    for path, record in mine.items():  # storage spelling before the union; the first duplicate wins
        path = hostos.storage_path_key(path)
        if path not in wanted:
            wanted[path] = record
    wanted_favs = sorted(set(favourites.all())
                         | {hostos.storage_path_key(p) for p in my_favs})
    adopted = len(wanted) - len(existing)

    written = store.update(wanted)
    if not written and written.reason == keyed_store.REASON_NO_USER:
        debug.event("file", "locations waiting for a user",  # marker unset, old keys still the truth
                    locations=len(wanted))
        return {"state": "deferred", "why": "no user yet"}
    written_favs = favourites.update({p: True for p in wanted_favs})
    if not written:
        debug.event("file", "location migration refused",
                    reason=written.reason)
        return {"state": "refused", "why": written.reason}
    if not written_favs:
        if written_favs.reason == keyed_store.REASON_NO_USER:
            debug.event("file", "locations moved, favourites waiting "  # marker unset; a later session finishes
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
        debug.event("file", "location migration did not reproduce",  # not marked; the next launch retries
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
            "joined": adopted, "already_there": len(existing)}  # `joined`: this machine's locations new to the store


_converted: set = globals().get("_converted", set())  # libraries converted to ids this session


def _file_key_specs():
    """The four stores holding location-keyed rows, imported through their binding modules."""
    from amaze.core import notes, tile_icons
    return (SPEC, FAVOURITES_SPEC, notes.SPEC, tile_icons.SPEC)


def convert_to_ids(preferences) -> None:
    """Re-home every location-keyed row onto its current owner; a clashing destination is kept."""
    global _generation
    ids = _ids_store(preferences)
    store = _store(preferences)
    if not ids.writable or not store.writable:
        return
    by_path, losers, id_paths = {}, {}, {}    # keyed by the NORMALISED path; the row itself keeps its verbatim spelling
    for lid in sorted(ids.all()):
        raw = str(ids.get(lid).get("path") or "")
        if not raw.strip():
            continue
        path = keyed_store.path_identity(raw)
        id_paths[lid] = path
        if path in by_path:
            losers[lid] = by_path[path]
        else:
            by_path[path] = lid
    minted, spellings = {}, {}
    for stored in store.everyones():
        _owner, bare = keyed_store.untagged_key(SPEC, stored)
        if bare.startswith(LOC_PREFIX):
            continue
        path = keyed_store.path_identity(bare)
        if path not in by_path and path not in minted:
            minted[path] = uuid.uuid4().hex
            spellings[path] = bare
    if minted:
        if not ids.update({lid: {"path": spellings[path]}
                           for path, lid in minted.items()}):
            return    # the identities did not land, so nothing may be re-keyed onto them
        by_path.update(minted)
        id_paths.update({lid: path for path, lid in minted.items()})
        _generation += 1

    prefixes = sorted(by_path.items(), key=lambda pair: -len(pair[0]))

    def _owned(bare):
        for base, lid in prefixes:
            if bare == base or bare.startswith(base + "/"):
                return lid, base
        return "", ""

    moved, kept, blocked = 0, 0, set()
    for spec in _file_key_specs():
        target = keyed_store.open_store(spec, preferences)
        table = target.everyones()
        moves = {}
        for stored in table:
            owner, tagless = keyed_store.untagged_key(spec, stored)
            bare = keyed_store._bare_path(spec, tagless)
            prefix = tagless[:len(tagless) - len(bare)]
            tag = (owner + keyed_store.USER_SEP) if owner else ""
            if bare.startswith(LOC_PREFIX):
                head, _, rel = bare[len(LOC_PREFIX):].partition("/")
                lid = losers.get(head, head)
                fresh = ""
                if rel and lid in id_paths:    # a FILE ident re-settles on the innermost owner of the path it means today
                    full = id_paths[lid] + "/" + rel
                    owner_id, base = _owned(full)
                    if owner_id and owner_id != head:
                        fresh = (LOC_PREFIX + owner_id
                                 + "/" + full[len(base) + 1:])
                elif not rel and lid != head:    # a record ident only follows a rival collapse
                    fresh = LOC_PREFIX + lid
                if fresh:
                    moves[stored] = tag + prefix + fresh
                continue
            if spec is SPEC:
                lid = by_path.get(keyed_store.path_identity(bare))
                if lid:
                    moves[stored] = tag + LOC_PREFIX + lid
                continue
            lid, base = _owned(bare)
            if not lid:
                continue
            rel = bare[len(base) + 1:] if len(bare) > len(base) else ""
            moves[stored] = (tag + prefix + LOC_PREFIX + lid
                             + ("/" + rel if rel else ""))
        clashing = {}    # a destination holding a different value: both stay, the rival id too
        for old, new in list(moves.items()):
            standing = table.get(new)
            if new in table and standing != table.get(old):
                clashing[old] = new
                moves.pop(old)
                bare = keyed_store._bare_path(
                    spec, keyed_store.untagged_key(spec, old)[1])
                if bare.startswith(LOC_PREFIX):
                    blocked.add(bare[len(LOC_PREFIX):].partition("/")[0])
        if moves:
            if target.rekey_stored(moves):
                moved += len(moves)
            else:
                blocked.update(losers)    # the store refused the whole move - no loser it holds may be retired
        kept += len(clashing)
    safe = [lid for lid in losers if lid not in blocked]
    if safe:
        ids.retire(safe)
        _generation += 1
    if moved or safe or kept:
        debug.event("file", "location keys re-homed onto ids",
                    moved=moved, collapsed=len(safe), kept_aside=kept)


def rehome_covered(preferences, path: str) -> bool:
    """Move each key a REMAINING location covers off the one at `path`; False if a store refused."""
    if not library_present(preferences):
        return True
    gone = keyed_store.path_identity(hostos.storage_path_key(str(path)))
    leaving = set(keyed_store.location_ids_at(preferences, path))
    owners = {base: lid for base, lid in _id_table(preferences).items()
              if base != gone}
    moved, already, landed = 0, 0, True
    for spec in _file_key_specs():
        if spec is SPEC:
            continue    # a location's own record retires with it
        target = keyed_store.open_store(spec, preferences)
        table = target.everyones()
        moves = {}
        for stored in table:
            owner, tagless = keyed_store.untagged_key(spec, stored)
            bare = keyed_store._bare_path(spec, tagless)
            if bare.startswith(LOC_PREFIX):
                head, _, rel = bare[len(LOC_PREFIX):].partition("/")
                full = gone + "/" + rel if head in leaving and rel else ""
            elif keyed_store._under(spec, tagless, path):
                full = bare
            else:
                continue
            fresh = _ident_under(owners, full) if full else ""
            if fresh:
                tag = owner + keyed_store.USER_SEP if owner else ""
                moves[stored] = tag + tagless[:len(tagless) - len(bare)] + fresh
        if moves and not target.rekey_stored(moves):
            debug.event("file", "a removed location's keys could not move",
                        store=spec.filename, waiting=len(moves))
            landed = False
            break
        moved += len(moves)
        already += sum(1 for new in moves.values() if new in table)
    _converted.discard(str(getattr(preferences, "dir", "")))    # the next read re-settles keys on what is left
    if moved:
        debug.event("file", "a removed location's keys moved to the one "
                            "still covering them", moved=moved,
                    destination_kept=already)
    return landed


_asset_deferred: set = globals().get("_asset_deferred", set())  # (dir, uid) pairs whose asset-star migration did not land


def migrate_asset_favourites(preferences) -> dict:
    """Move `material_favorites` into the favourites store, proven before the key pops; a dict."""
    data = getattr(preferences, "data", None)
    if not isinstance(data, dict):
        return {"state": "deferred", "why": "no settings"}
    raw = [str(x) for x in (data.get("material_favorites") or ())
           if str(x).strip()]
    if not raw:
        data.pop("material_favorites", None)
        return {"state": "done"}
    if isolated(preferences):
        return {"state": "deferred", "why": "test mode"}  # these stars belong to the real library
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
        _asset_deferred.add(key)  # not popped: the old key stays the truth
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
    """Drop the cached tables and the deferred sets; call on a library switch."""
    global _ready_memo
    _deferred.clear()
    _asset_deferred.clear()
    _orphans_deferred.clear()
    _converted.clear()
    _ready_memo = ((), False)
    keyed_store.release()
