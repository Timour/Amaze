"""Each open library's databases, one `documents.Library` per folder; saves wait for a timer."""

from __future__ import annotations

import os

from amaze import messages
from amaze.core import debug, documents, guard, library_files
from amaze.helpers import hostos

_libraries: dict = globals().get("_libraries", {})    # library key -> documents.Library
_preferences: dict = globals().get("_preferences", {})    # library key -> the Prefs last passed in
_schedulers: list = globals().get("_schedulers", [])    # the panels' save timers, newest last
_alerted: dict = globals().get("_alerted", {})    # (library key, database) -> the verdict last alerted
_listeners: dict = globals().get("_listeners", {})    # called after each save: the models
_in_use: set = globals().get("_in_use", set())    # library keys in use by a panel's models
_present: set = globals().get("_present", set())    # folders found on disk; `recheck_folders` clears
_users: dict = globals().get("_users", {})    # library key -> the user last making changes there

TROUBLE = (guard.CORRUPT, guard.MISSING, guard.NEWER)


def key_of(preferences) -> str:
    """The key a library is stored under in this module: its folder, canonical."""
    return hostos.canonical_path_key(str(getattr(preferences, "dir", "") or ""))


def _user_of(key: str) -> str:
    """The user making changes at `key`; `""` with no folder; a found folder is not rechecked."""
    preferences = _preferences.get(key)
    if key_of(preferences) != key:    # the Prefs names another library now: the user it had here
        return _users.get(key, "")
    folder = str(getattr(preferences, "dir", "") or "")
    if not folder or (folder not in _present and not os.path.isdir(folder)):
        return ""
    _present.add(folder)
    _users[key] = str(getattr(preferences, "library_user", "") or "")
    return _users[key]


def recheck_folders() -> None:
    """Make the next change check on disk whether each library folder still exists."""
    _present.clear()


def library_for(preferences) -> documents.Library:
    """This library's one `documents.Library`, created on the first call."""
    key = key_of(preferences)
    _preferences[key] = preferences
    found = _libraries.get(key)
    if found is None:
        found = documents.Library(str(getattr(preferences, "dir", "") or ""),
                                  lambda: _user_of(key), defer=_deferred)
        _libraries[key] = found
    return found


def document(preferences, name: str) -> documents.Document:
    """One database of this library; `alert_database_problem` alerts once about its problems."""
    found = library_for(preferences).document(name)
    alert_database_problem(key_of(preferences), found)
    return found


def guard_of(preferences) -> guard.Guard:
    """The guard of this library's folder."""
    return library_for(preferences).guard


def accepts(preferences, name: str) -> bool:
    """Whether a change to database `name` can be kept now: it is writable and a user is set."""
    found = document(preferences, name)
    _read_again(key_of(preferences), found)
    return found.writable and bool(found.user())


def takes_changes(model) -> bool:
    """Whether a model may write: its rows are of the library its Prefs names, taking changes."""
    preferences = model.preferences
    if getattr(model, "read_from", None) not in (None, key_of(preferences)):
        debug.event("library", "change refused - the rows are from another library",
                    store=model.DB_FILENAME, dir=str(getattr(preferences, "dir", "") or ""))
        return False    # the folder changed and the models have not switched yet
    return accepts(preferences, model.DB_FILENAME)


def _read_again(key: str, held: documents.Document) -> None:
    """Read a database that takes no change once more: a file in use a moment ago may open now."""
    if held.writable:
        return
    try:
        moved = held.refresh()
    except OSError as exc:
        debug.event("database", "refresh failed", library=key, error=str(exc))
        return
    alert_database_problem(key, held)
    if moved:
        _call_listeners(key, held.name)


def _call_listeners(key: str, name: str) -> None:
    """Call each `on_saved` listener: the models load what a save or a read merged in."""
    for listener in list(_listeners.values()):
        try:
            listener(key, name)
        except Exception as exc:                             # noqa: BLE001
            debug.event("database", "a listener after a save failed", error=str(exc))


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
    """`listener(key, database)` after every save: the models load what the save merged in."""
    _listeners[listener.__module__ + "." + listener.__qualname__] = listener    # a reload replaces it


def _deferred(save) -> None:
    """A change waits for a panel's timer; with no panel (tests, tools) it saves at once."""
    if _schedulers:
        _schedulers[-1]()
        return
    held = getattr(save, "__self__", None)
    if held is None:
        report_save(save())
        return
    for key, found in list(_libraries.items()):
        if any(one is held for one in found.opened().values()):
            _save_one(key, held)
            return
    report_save(save())


def changed(preferences, name: str) -> None:
    """A changed database is due: the panel's timer saves it, or at once with no panel."""
    held = document(preferences, name)
    if held.dirty:
        _deferred(held.save)


def _records(key: str, held: documents.Document):
    """`also` for a section database: each changed row's `<id>.json`, and its folder's name."""
    if held.name not in library_files.SECTION_FOLDERS:
        return None

    def also(change):
        from amaze.core import material
        for asset_id in held.changed("assets"):
            row = held.get("assets", asset_id)
            if row is None or not material.is_safe_asset_id(asset_id):
                continue    # the delete itself removes a deleted row's files
            own = material.folder_in(held.guard.dir, held.name, asset_id)
            if not os.path.isdir(own):
                continue    # a snippet or color with no file yet has no folder
            if held.name in library_files.ASSET_SECTIONS and not _record(change, held, own, asset_id, row):
                continue
            named = material.folder_name(row.get("name"), asset_id)
            if os.path.basename(own).lower() != named.lower():    # renamed: its folder follows the record; case alone is no move on every disk
                change.move(held.guard.inside(own), held.guard.inside(
                    os.path.join(os.path.dirname(own), named)))
    return also


def _record(change, held, own: str, asset_id: str, row: dict) -> bool:
    """The row's metadata into its `<id>.json`; False with no network or record, or one unreadable."""
    from amaze.core import asset_record
    path = os.path.join(own, asset_id + library_files.RECORD_SUFFIX)
    if not os.path.exists(path) and not os.path.exists(os.path.join(own, asset_id + ".mat")):
        return False    # no files of its own: nothing to rebuild a lost database from
    if asset_record.unreadable(path):
        return False
    metadata = {field: value for field, value in row.items() if field not in documents.STAMPS}
    if asset_record.read(path)[asset_record.METADATA] != metadata:
        change.put_file(held.guard.inside(path), asset_record.with_sections(
            path, {asset_record.METADATA: metadata}))
    return True


def _save_one(key: str, held: documents.Document, also=None) -> documents.Saved:
    """Save one database, its records' metadata and the caller's files, then `report_save`."""
    records = _records(key, held)
    if records is None or not held.dirty:
        both = also
    elif also is None:
        both = records
    else:
        def both(change):
            records(change)
            also(change)    # last: a record the caller writes whole overrides the metadata above
    _read_again(key, held)
    saved = held.save(also=both)
    report_save(saved, held.name)
    alert_database_problem(key, held)
    if saved.merged:    # only then does memory hold rows the models have not shown
        _call_listeners(key, held.name)
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
            alert_database_problem(key, held)
            alert_collisions(key, held)
    return done


def save(preferences, name: str, also=None) -> documents.Saved:
    """Save one database now, `also(change)` adding the files that belong with it."""
    return _save_one(key_of(preferences), document(preferences, name), also)


def report_save(saved, name: str = "") -> None:
    """Report a save: a failed disk write alerts; a read-only one by `alert_database_problem`."""
    for key, found in list(_libraries.items()):
        for held in found.opened().values():
            alert_collisions(key, held)
    if saved or saved.reason in (documents.NO_USER,) + TROUBLE:
        return
    debug.event("database", "save failed", file=name, reason=saved.reason,
                detail=saved.detail)
    debug.alert(messages.LIBRARY_WRITE_FAILED % (saved.detail or saved.reason),
                key="database-write-failed-%s" % saved.reason)


def alert_collisions(key: str, held: documents.Document) -> None:
    """Each field two users changed at once, alerted once, naming the other user."""
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


def alert_database_problem(key: str, held: documents.Document) -> None:
    """Alert a database's problem once per file per session; cleared when it reads again."""
    where = (key, held.name)
    verdict = held.verdict
    if verdict == guard.HELD:
        _alerted.pop(where, None)
        debug.event("database", "database not opened - access refused", file=held.name,
                    why=held.why)
        return    # access, not damage: read-only until it opens; a save attempt alerts with `why`
    if verdict not in TROUBLE:
        _alerted.pop(where, None)
    elif _alerted.get(where) != verdict:
        _alerted[where] = verdict
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
        _alerted.pop(shrunk, None)
    elif _alerted.get(shrunk) != held.shrunk:
        _alerted[shrunk] = held.shrunk
        holds, backed = held.shrunk
        debug.alert(messages.DATABASE_SHRUNK % (
            library_files.section_label(held.name), holds,
            library_files.section_noun(held.name, holds), backed,
            library_files.section_noun(held.name, backed)), key="shrunk-%s-%s" % where)


def refresh(preferences=None) -> dict:
    """Load other sessions' saves; {library key: [databases that changed]}."""
    recheck_folders()
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
            alert_database_problem(key, held)
            alert_collisions(key, held)
    return moved


def preferences_of(key: str):
    """The Prefs last passed in for the library at `key`, or None."""
    return _preferences.get(key)


def use(preferences) -> None:
    """A panel's models now use this library: it stays in `_in_use` until `release`."""
    _in_use.add(key_of(preferences))


def unuse(key: str) -> None:
    """No panel's models use the library at `key` any more; its databases stay until `release`."""
    _in_use.discard(key)


def held_libraries() -> list:
    """The keys of every library whose databases models in this session use."""
    return [key for key in _libraries if key in _in_use]


def release(preferences=None) -> None:
    """Drop the cached databases: on a switch to another library folder, or in a test."""
    recheck_folders()
    if preferences is None:
        _libraries.clear()
        _alerted.clear()
        _in_use.clear()
        _users.clear()
        return
    _users.pop(key_of(preferences), None)
    _libraries.pop(key_of(preferences), None)
    _in_use.discard(key_of(preferences))
