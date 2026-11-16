"""The Files section's locations and every section's stars, in the library's databases."""

from __future__ import annotations

import os
import uuid

from amaze.core import debug, library_db, library_files
from amaze.helpers import hostos

FILES = library_files.FILES
LOCATIONS, PATHS, FAVORITES, COMMENTS, ICONS = (
    "locations", "paths", "favorites", "comments", "icons")
LOC_PREFIX = "loc:"    # `loc:<id>[/<relative>]`: a location's own key, and every file key under it

FIELDS = ("registered", "name", "color", "recursive",
          "kinds", "pathname")  # the record's fields, each with its own branch in normalise()

KIND_IMAGE = "image"  # the kinds a record's `kinds` field lists; stored in files.json, so fixed
KIND_GEO = "geometry"
KIND_HIP = "hip"
KIND_OTHER = "other"
KNOWN_KINDS = (KIND_IMAGE, KIND_GEO, KIND_HIP)    # the kinds Amaze pictures; Other Files is the rest
SHOWN_BY_DEFAULT = KNOWN_KINDS + (KIND_OTHER,)    # a new location's Show ▸ ticks
EVERY_KIND = SHOWN_BY_DEFAULT    # the Import location's ticks: a package carries any file

_generation = globals().get("_generation", 0)    # moves on every location write; the paint path's token
_id_map: tuple = ("", -1, {})    # (library, generation, {path identity: smallest id at it})


def normalise(value) -> dict:
    """A well-formed location record, or {} for junk; unknown fields pass."""
    if not isinstance(value, dict):
        return {}
    record = {k: v for k, v in value.items() if k not in FIELDS}
    if value.get("registered"):
        record["registered"] = True
    name = value.get("name")
    if isinstance(name, str) and name.strip():
        record["name"] = name
    color = value.get("color")
    if isinstance(color, str) and color.strip():
        record["color"] = color
    if value.get("recursive"):
        record["recursive"] = True
    kinds = value.get("kinds")
    if isinstance(kinds, (list, tuple)):    # [] is a real value: Show ▸ with no kind ticked
        record["kinds"] = sorted({kind for kind in kinds if isinstance(kind, str)})
    if value.get("pathname"):
        record["pathname"] = True
    return record


def path_identity(path) -> str:
    """The spelling two location paths compare by: trailing `/` off, the root kept as `/`."""
    return str(path).rstrip("/") or "/"


def _boundary(prefix: str) -> str:
    """A folder prefix that cannot match a SIBLING: without it `/a/tex` takes `/a/textures`."""
    return prefix.rstrip("/") + "/"


def _files(preferences):
    return library_db.document(preferences, FILES)


def library_present(preferences) -> bool:
    """Is the library folder there to be read? Asked of the filesystem."""
    directory = str(getattr(preferences, "dir", "") or "")
    return bool(directory) and os.path.isdir(directory)


def ready(preferences) -> bool:
    """Whether file keys can be read and written now: files.json reads and a user is picked."""
    if not str(getattr(preferences, "library_user", "") or ""):
        return False
    held = _files(preferences)
    return held.writable and bool(held.user())


def showing_last_known(preferences) -> bool:
    """Whether the Files section has no library answer to show right now."""
    return not ready(preferences)


def generation() -> int:
    """A number that moves whenever any location record moves."""
    return _generation


def touch() -> None:
    """Bump the generation after location state was edited outside this module."""
    global _generation
    _generation += 1
    library_db.look_again()


def _mine(preferences, section: str) -> dict:
    held = _files(preferences)
    return dict(held.mine(section)) if held.user() else {}


def _id_table(preferences) -> dict:
    global _id_map
    key = library_db.key_of(preferences)
    if _id_map[0] == key and _id_map[1] == _generation:
        return _id_map[2]
    table = {}
    rows = _files(preferences).table(PATHS)
    for lid in sorted(rows):    # sorted, so the FIRST id at a path is the smallest
        path = str((rows[lid] or {}).get("path") or "")
        if path:
            table.setdefault(path_identity(path), lid)
    _id_map = (key, _generation, table)
    return table


def location_id(preferences, path: str, mint: bool = False) -> str:
    """The id of the location at `path`, "" for none; `mint=True` creates one, shared by all users."""
    global _generation
    wanted = hostos.storage_path_key(str(path))
    best = _id_table(preferences).get(path_identity(wanted), "")
    if best or not mint:
        return best
    lid = uuid.uuid4().hex
    if not _files(preferences).put(PATHS, lid, {"path": wanted}):
        return ""
    _generation += 1
    return lid


def location_path_for(preferences, locid: str) -> str:
    """The STORAGE-spelling path a location id points at, "" for an unknown id."""
    return str((_files(preferences).get(PATHS, str(locid)) or {}).get("path") or "")


def _path_of_key(preferences, key: str) -> str:
    """The storage-spelling path a `loc:<id>[/<relative>]` key means today; a plain path as it is."""
    key = str(key)
    if not key.startswith(LOC_PREFIX):
        return key
    head, _, rel = key[len(LOC_PREFIX):].partition("/")
    base = location_path_for(preferences, head)
    if not base:
        return ""
    return base.rstrip("/") + ("/" + rel if rel else "") if rel else base


def _ident_under(owners: dict, stored: str) -> str:
    """The `loc:` key of a stored path under the innermost of `owners` ({path: id}), or ""."""
    best, found = "", ""
    for base, lid in owners.items():
        if (stored == base or stored.startswith(base + "/")) and len(base) > len(best):
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
    """`loc:<id>/<relative>` under the innermost location, or ""; every per-file key."""
    if not ready(preferences):
        return ""
    return _ident_under(_id_table(preferences), hostos.storage_path_key(str(full_path)))


def record(preferences, path: str) -> dict:
    """Everything this user keeps for a location, as one record; a field not set is absent."""
    lid = location_id(preferences, path)
    if not lid:
        return {}
    return dict(_mine(preferences, LOCATIONS).get(LOC_PREFIX + lid) or {})


def paths(preferences) -> list:
    """Every location this user has a record for, registered or not, as absolutes."""
    out = []
    for key in _mine(preferences, LOCATIONS):
        path = _path_of_key(preferences, key)
        if path:
            out.append(hostos.expand_storage_path(path))
    return out


def _copy_order(preferences) -> list:
    """This machine's sidebar order in STORAGE spelling, each location once."""
    order, seen = [], set()
    for path in (getattr(preferences, "last_known_folders", ()) or ()):
        stored = hostos.storage_path_key(path)
        if stored and stored not in seen:
            seen.add(stored)
            order.append(stored)
    return order


def registered_paths(preferences) -> list:
    """THE SIDEBAR LIST: registered locations in this machine's order, then the rest."""
    return [hostos.expand_storage_path(p) for p in _registered_stored(preferences)]


def _registered_stored(preferences) -> list:
    if not ready(preferences):
        return []
    live = set()
    for key, rec in _mine(preferences, LOCATIONS).items():
        if isinstance(rec, dict) and rec.get("registered"):
            path = _path_of_key(preferences, key)
            if path:
                live.add(path)
    known = _copy_order(preferences)
    ordered = [path for path in known if path in live]
    ordered.extend(sorted(live.difference(ordered)))
    return ordered


def move_registered(preferences, path: str, row: int) -> bool:
    """Move a registered location to another sidebar row in memory; `commit_registered_order` saves."""
    current = registered_paths(preferences)
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


def _keep_order(preferences, order=None) -> None:
    """This machine's sidebar order follows what is registered now; saved with the settings."""
    keep = getattr(preferences, "keep_last_known", None)
    if callable(keep):
        keep(None, order if order is not None else _registered_stored(preferences), None)


def set_record(preferences, path: str, value) -> bool:
    """Write one location's whole record for this user; an empty one forgets it."""
    global _generation
    _generation += 1
    if not ready(preferences):
        return False
    path = hostos.storage_path_key(path)
    lid = location_id(preferences, path, mint=bool(value))
    if not lid:
        return not value
    held = _files(preferences)
    with library_db.library_for(preferences).holding():
        held.put_mine(LOCATIONS, LOC_PREFIX + lid, normalise(value) or None)
    saved = library_db.save(preferences, FILES)
    _generation += 1
    _keep_order(preferences)
    return bool(saved) or saved.reason == "unchanged"


def register(preferences, path: str) -> bool:
    """Register a location, keeping whatever the record already carries."""
    current = record(preferences, path)
    current["registered"] = True
    return set_record(preferences, path, current)


def unregister(preferences, path: str) -> bool:
    """Forget this user's record of a location; what is keyed under it goes with `retire_prefix`."""
    return set_record(preferences, path, {})


def set_field(preferences, path: str, field: str, value) -> bool:
    """Set one field of one location, read-modify-write through the whole record."""
    if field not in FIELDS:
        raise ValueError("%r is not a location field" % (field,))
    current = record(preferences, path)
    if value is None or value == "" or value is False:
        current.pop(field, None)
    else:
        current[field] = value
    return set_record(preferences, path, current)


def relocate_record(preferences, old: str, new: str) -> bool:
    """Move ONE location: its path row, and every row under it, follow for every user."""
    global _generation
    old, new = hostos.storage_path_key(old), hostos.storage_path_key(new)
    if not old or not new or old == new or not ready(preferences):
        return False
    held = _files(preferences)
    old_edge, new_edge = _boundary(old), _boundary(new)
    order = _copy_order(preferences)
    moved = False
    with library_db.library_for(preferences).holding():
        for lid, row in list(held.table(PATHS).items()):
            path = str((row or {}).get("path") or "")
            if path_identity(path) == path_identity(old):
                moved = held.put(PATHS, lid, dict(row, path=new)) or moved
            elif path.startswith(old_edge):
                moved = held.put(PATHS, lid, dict(row, path=new_edge + path[len(old_edge):])) \
                    or moved
    saved = library_db.save(preferences, FILES)
    _generation += 1
    if moved and saved:
        _keep_order(preferences, [new if path_identity(p) == path_identity(old) else p
                                  for p in order if path_identity(p) != path_identity(new)])
    return moved and bool(saved)


def _stars(preferences, database: str) -> dict:
    held = library_db.document(preferences, database)
    return held.mine(FAVORITES) if held.user() else {}


def _file_star_key(preferences, key: str) -> str:
    key = str(key)
    if key.startswith(LOC_PREFIX):
        return key
    return file_ident(preferences, key) or hostos.storage_path_key(key)


def is_favourite(preferences, key, database: str = FILES) -> bool:
    """Is this asset id, or this file's key or path, starred by this user? Cheap per repaint."""
    stars = _stars(preferences, database)
    if not stars:
        return False
    if database != FILES:
        return bool(stars.get(str(key)))
    return bool(stars.get(_file_star_key(preferences, key)))


def favourite_paths(preferences) -> list:
    """This user's starred files as paths."""
    out = []
    for key in sorted(_stars(preferences, FILES)):
        path = _path_of_key(preferences, key)
        if path:
            out.append(hostos.expand_storage_path(path))
    return out


def set_favourite(preferences, key, on: bool, database: str = FILES) -> bool:
    return set_favourites(preferences, {key: on}, database)


def set_favourites(preferences, wanted: dict, database: str = FILES) -> bool:
    """Star or unstar every `{key: on}` as ONE change of this user's stars; later keys win."""
    held = library_db.document(preferences, database)
    if not held.writable or not held.user():
        return False
    with library_db.library_for(preferences).holding():
        for key, on in wanted.items():
            home = str(key) if database != FILES else _file_star_key(preferences, key)
            held.put_mine(FAVORITES, home, True if on else None)
    saved = library_db.save(preferences, database)
    return bool(saved) or saved.reason == "unchanged"


def files_moved(preferences, keys: dict) -> bool:
    """Files moved on disk: their comments, icons and this user's stars follow `{old: new}`."""
    held = _files(preferences)
    if not keys or not held.writable or not held.user():
        return not keys
    with library_db.library_for(preferences).holding():
        for old, new in keys.items():
            old, new = str(old), str(new)
            for section in (COMMENTS, ICONS):
                entry = held.get(section, old)
                if entry is not None:
                    held.put(section, new, entry)    # a moved file's own entry over one left behind
                    held.drop(section, old)
            if held.mine(FAVORITES).get(old):
                held.put_mine(FAVORITES, new, True)
                held.put_mine(FAVORITES, old, None)
    saved = library_db.save(preferences, FILES)
    return bool(saved) or saved.reason == "unchanged"


def _under(key: str, lid: str, prefix: str) -> bool:
    """Whether a file key is the location `lid` or inside it, by id or by path."""
    key = str(key)
    own = LOC_PREFIX + lid
    if lid and (key == own or key.startswith(own + "/")):
        return True
    bare = path_identity(prefix)
    return not key.startswith(LOC_PREFIX) and (key == bare or key.startswith(bare + "/"))


def retire_prefix(preferences, path: str) -> bool:
    """A location is gone: its comments, icons and this user's stars go; its path row when unused."""
    global _generation
    held = _files(preferences)
    if not held.writable or not held.user():
        return False
    prefix = hostos.storage_path_key(str(path))
    lids = [lid for lid, row in held.table(PATHS).items()
            if path_identity(str((row or {}).get("path") or "")) == path_identity(prefix)]
    with library_db.library_for(preferences).holding():
        for lid in lids or [""]:
            for section in (COMMENTS, ICONS):
                for key in [k for k in held.table(section) if _under(k, lid, prefix)]:
                    held.drop(section, key)
            for key in [k for k in held.mine(FAVORITES) if _under(k, lid, prefix)]:
                held.put_mine(FAVORITES, key, None)
            for key in [k for k in held.mine(LOCATIONS) if _under(k, lid, prefix)]:
                held.put_mine(LOCATIONS, key, None)
            others = [own for user, own in held.everyones(LOCATIONS).items()
                      if user != held.user() and LOC_PREFIX + lid in (own or {})]
            if lid and not others:
                held.drop(PATHS, lid)
    saved = library_db.save(preferences, FILES)
    _generation += 1
    return bool(saved) or saved.reason == "unchanged"


def rehome_covered(preferences, path: str) -> bool:
    """Move each key a REMAINING location covers off the one at `path`; False when it was refused."""
    if not library_present(preferences) or not ready(preferences):
        return True
    held = _files(preferences)
    gone = path_identity(hostos.storage_path_key(str(path)))
    leaving = {lid for lid, row in held.table(PATHS).items()
               if path_identity(str((row or {}).get("path") or "")) == gone}
    owners = {base: lid for base, lid in _id_table(preferences).items() if base != gone}
    moves = {}
    for key in list(held.table(COMMENTS)) + list(held.table(ICONS)) + list(held.mine(FAVORITES)):
        if key.startswith(LOC_PREFIX):
            head, _, rel = key[len(LOC_PREFIX):].partition("/")
            full = gone + "/" + rel if head in leaving and rel else ""
        else:
            full = key if key == gone or key.startswith(gone + "/") else ""
        fresh = _ident_under(owners, full) if full else ""
        if fresh:
            moves[key] = fresh
    if not moves:
        return True
    landed = files_moved(preferences, moves)
    if moves:
        debug.event("file", "a removed location's keys moved to the one still covering them",
                    moved=len(moves))
    return landed


def forget() -> None:
    """Drop what is cached of the locations; call on a library switch."""
    global _id_map
    _id_map = ("", -1, {})
    touch()
