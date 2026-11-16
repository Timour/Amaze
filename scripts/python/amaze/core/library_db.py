"""Each open library's databases, one `documents.Library` per folder; saves wait for a timer."""

from __future__ import annotations

import os

from amaze import messages
from amaze.core import debug, documents, guard, library_files
from amaze.helpers import hostos

_libraries: dict = globals().get("_libraries", {})    # library key -> documents.Library
_preferences: dict = globals().get("_preferences", {})    # library key -> the Prefs that answers last
_schedulers: list = globals().get("_schedulers", [])    # the panels' save timers, newest last
_said: dict = globals().get("_said", {})    # (library key, database) -> the verdict last alerted
_listeners: dict = globals().get("_listeners", {})    # told after each save: the models
_in_use: set = globals().get("_in_use", set())    # library keys a panel's models serve
_present: set = globals().get("_present", set())    # library folders seen there; `look_again` drops them

TROUBLE = (guard.CORRUPT, guard.MISSING, guard.NEWER)


def key_of(preferences) -> str:
    """The key a library is held under: its folder, canonical."""
    return hostos.canonical_path_key(str(getattr(preferences, "dir", "") or ""))


def _user_of(key: str) -> str:
    """The user making changes in the library at `key`, "" with no folder; a folder seen stays seen."""
    preferences = _preferences.get(key)
    folder = str(getattr(preferences, "dir", "") or "")
    if not folder or (folder not in _present and not os.path.isdir(folder)):
        return ""
    _present.add(folder)
    return str(getattr(preferences, "library_user", "") or "")


def look_again() -> None:
    """The next change asks the filesystem whether each library folder is still there."""
    _present.clear()


def library_for(preferences) -> documents.Library:
    """This library's one `documents.Library`, made on first ask."""
    key = key_of(preferences)
    _preferences[key] = preferences
    found = _libraries.get(key)
    if found is None:
        found = documents.Library(str(getattr(preferences, "dir", "") or ""),
                                  lambda: _user_of(key), defer=_deferred)
        _libraries[key] = found
    return found


def document(preferences, name: str) -> documents.Document:
    """One database of this library, its trouble said to the user once."""
    found = library_for(preferences).document(name)
    judge(key_of(preferences), found)
    return found


def guard_of(preferences) -> guard.Guard:
    """The guard of this library's folder."""
    return library_for(preferences).guard


def accepts(preferences, name: str) -> bool:
    """Whether a change to database `name` can be kept now: it reads, and a user is picked."""
    found = document(preferences, name)
    return found.writable and bool(found.user())


def set_scheduler(schedule) -> None:
    """A panel's save timer: `schedule()` starts it, and it calls `flush()` when it fires."""
    if schedule not in _schedulers:
        _schedulers.append(schedule)


def drop_scheduler(schedule=None) -> None:
    """Forget a panel's timer; with none named, every timer, so each change saves at once."""
    if schedule is None:
        _schedulers.clear()
    elif schedule in _schedulers:
        _schedulers.remove(schedule)


def on_saved(listener) -> None:
    """`listener(key, database)` after every save: the models take what the save merged in."""
    _listeners[listener.__module__ + "." + listener.__qualname__] = listener    # a reload replaces it


def _deferred(save) -> None:
    """A change waits for a panel's timer; with no panel (tests, tools) it saves at once."""
    if _schedulers:
        _schedulers[-1]()
        return
    held = getattr(save, "__self__", None)
    if held is None:
        told(save())
        return
    for key, found in list(_libraries.items()):
        if any(one is held for one in found.opened().values()):
            _save_one(key, held)
            return
    told(save())


def changed(preferences, name: str) -> None:
    """A change made while holding is due: the panel's timer saves it, or with no panel now."""
    held = document(preferences, name)
    if held.dirty:
        _deferred(held.save)


def _records(key: str, held: documents.Document):
    """`also` for a section owning asset files: each changed row's metadata into its `<id>.json`."""
    if held.name not in library_files.ASSET_SECTIONS:
        return None
    folder = library_files.SECTION_FOLDERS[held.name]

    def also(change):
        from amaze.core import asset_record, material
        for asset_id in held.changed("assets"):
            row = held.get("assets", asset_id)
            relative = "%s/%s%s" % (folder, asset_id, library_files.RECORD_SUFFIX)
            if row is None or not material.is_safe_asset_id(asset_id):
                continue    # a deleted row's files leave with the delete itself
            path = held.guard.path(folder, asset_id + library_files.RECORD_SUFFIX)
            if not os.path.exists(path) and not os.path.exists(
                    held.guard.path(folder, asset_id + ".mat")):
                continue    # no files of its own: nothing to rebuild a lost database from
            if asset_record.unreadable(path):
                continue
            metadata = {field: value for field, value in row.items()
                        if field not in documents.STAMPS}
            if asset_record.read(path)[asset_record.METADATA] != metadata:
                change.put_file(relative, asset_record.with_sections(
                    path, {asset_record.METADATA: metadata}))
    return also


def _save_one(key: str, held: documents.Document, also=None) -> documents.Saved:
    """Save one database with its records' metadata and the caller's files, then say how it went."""
    records = _records(key, held)
    if records is None or not held.dirty:
        both = also
    elif also is None:
        both = records
    else:
        def both(change):
            records(change)
            also(change)    # last: a record the caller writes whole outranks the metadata above
    saved = held.save(also=both)
    told(saved, held.name)
    judge(key, held)
    for listener in list(_listeners.values()):
        try:
            listener(key, held.name)
        except Exception as exc:                             # noqa: BLE001
            debug.event("database", "a listener after a save failed", error=str(exc))
    return saved


def flush(preferences=None) -> dict:
    """Save every change waiting, in this library or all; {database: Saved} of each that had one."""
    done = {}
    for key, found in list(_libraries.items()):
        if preferences is not None and key != key_of(preferences):
            continue
        for name, held in found.opened().items():
            if held.dirty:
                done[name] = _save_one(key, held)
            judge(key, held)
            say_collisions(key, held)
    return done


def save(preferences, name: str, also=None) -> documents.Saved:
    """Save one database now, `also(change)` adding the files that belong with it."""
    return _save_one(key_of(preferences), document(preferences, name), also)


def told(saved, name: str = "") -> None:
    """A save's outcome said: a write the disk refused alerts; a refused database alerts elsewhere."""
    for key, found in list(_libraries.items()):
        for held in found.opened().values():
            say_collisions(key, held)
    if saved or saved.reason in (documents.NO_USER,) + TROUBLE:
        return
    debug.event("database", "save did not land", file=name, reason=saved.reason,
                detail=saved.detail)
    debug.alert(messages.LIBRARY_WRITE_FAILED % (saved.detail or saved.reason),
                key="database-write-failed-%s" % saved.reason)


def say_collisions(key: str, held: documents.Document) -> None:
    """Each field two users changed at once, said once, naming the other user."""
    for collision in held.take_collisions():
        entry = held.get(collision.section, collision.key) \
            if held.kind.sections.get(collision.section) == guard.SHARED else None
        named = str((entry or {}).get("name") or collision.key)
        who = display_name(key, collision.by)
        text = (messages.EDIT_CONFLICT_KEPT_YOURS_BY % (who, named) if who
                else messages.EDIT_CONFLICT_KEPT_YOURS % named)
        debug.event("database", "field collision - this session's value kept",
                    file=collision.document, key=collision.key, field=collision.field,
                    by=collision.by)
        debug.alert(text, key="edit-conflict-%s-%s-%s" % (collision.document, collision.key,
                                                          collision.field))


def display_name(key: str, uid: str) -> str:
    """The name a user goes by in this library, "" when it is not known."""
    found = _libraries.get(key)
    if not uid or found is None:
        return ""
    record = found.document(library_files.MASTER).get("users", str(uid)) or {}
    return str(record.get("name") or "")


def judge(key: str, held: documents.Document) -> None:
    """Say a database's trouble once per file per session; one that reads again is forgotten."""
    where = (key, held.name)
    verdict = held.verdict
    if verdict == guard.HELD:
        _said.pop(where, None)
        debug.event("database", "database not opened - access refused", file=held.name,
                    why=held.why)
        return    # access, not damage: read-only until a read opens it; the library's door says why
    if verdict not in TROUBLE:
        _said.pop(where, None)
    elif _said.get(where) != verdict:
        _said[where] = verdict
        label = library_files.section_label(held.name)
        debug.event("database", "database refused - read-only", file=held.name,
                    verdict=verdict, why=held.why)
        if verdict == guard.NEWER:
            text = messages.LIBRARY_FORMAT_AHEAD_READ_ONLY
        elif verdict == guard.MISSING:
            text = messages.DATABASE_MISSING_READ_ONLY % label
        else:
            text = messages.DATABASE_CORRUPT_READ_ONLY % label
        debug.alert(text, key="database-%s-%s-%s" % (verdict, key, held.name))
    shrunk = where + ("shrunk",)
    if not held.shrunk:
        _said.pop(shrunk, None)
    elif _said.get(shrunk) != held.shrunk:
        _said[shrunk] = held.shrunk
        holds, backed = held.shrunk
        debug.alert(messages.DATABASE_SHRUNK % (
            library_files.section_label(held.name), holds,
            library_files.section_noun(held.name, holds), backed,
            library_files.section_noun(held.name, backed)), key="shrunk-%s-%s" % where)


def refresh(preferences=None) -> dict:
    """Take in other sessions' saves; {library key: [databases that changed]}."""
    look_again()
    moved = {}
    for key, found in list(_libraries.items()):
        if preferences is not None and key != key_of(preferences):
            continue
        try:
            moved[key] = found.refresh()
        except OSError as exc:
            debug.event("database", "refresh failed", library=key, error=str(exc))
            continue
        for held in found.opened().values():
            judge(key, held)
            say_collisions(key, held)
    return moved


def preferences_of(key: str):
    """The Prefs that last asked for the library at `key`, or None."""
    return _preferences.get(key)


def use(preferences) -> None:
    """A panel's models now serve this library: it is held until released."""
    _in_use.add(key_of(preferences))


def held_libraries() -> list:
    """The keys of every library whose databases models in this session serve."""
    return [key for key in _libraries if key in _in_use]


def release(preferences=None) -> None:
    """Forget the databases held: a library switch onto another tree, or a test."""
    look_again()
    if preferences is None:
        _libraries.clear()
        _said.clear()
        _in_use.clear()
        return
    _libraries.pop(key_of(preferences), None)
    _in_use.discard(key_of(preferences))
