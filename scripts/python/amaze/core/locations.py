"""Registered FILE LOCATIONS and File FAVOURITES, as library stores.

**A File row's facts used to answer to two different scopes.** Its tile
icon and its comment were written into whichever library was open; the
location that listed it, and whether it was starred, were written into
settings.json beside the install. Switch library and the file was still
registered, still on disk, still listed - and its icon was gone. Two
libraries could hold different icons for the same file with nothing
reconciling them.

So the content facts follow the library, and only the POINTER to the
library stays behind: the bootstrap problem is real, but it covers
`directory` and nothing else (devlog #260, reversed on that narrow
ground 2026-08-05).

**settings.json keeps a copy, and it is not a second truth.** It does
the one job the library cannot do - be readable when the library is
not. The File section is the browser you most want working when a drive
is unmounted or a sync has not landed, so the last-known list still
shows, marked unreachable rather than silently missing. The
copy is written FROM the store, never back into it.

**It does NOT serve the other Mac.** The roadmap's A3 said to keep the
six old keys "so the other Mac's older build still works", and that
reason is hollow: settings.json is per-machine and has never travelled
between the two (INSTALL.md - "Preferences no longer sync between the
two Macs"). The keys are still worth writing, for the reason A4 gives
and for a build ROLLBACK on THIS machine, which is a real case and the
only back-compatibility a per-machine file can offer.

**The copy also carries the ORDER.** A store is a dict written with
`sort_keys=True`, so insertion order does not survive a write - and
location order is registration order, which no user authored and no
gesture can change. Keeping the local list's order means adding a
location on one Mac does not reshuffle the sidebar on the other; order
is a local presentation detail, membership is the shared fact.

**The records are PER-USER since ROADMAP line 22 stage C**: the store
declares `user_tagged`, so each user of a shared library registers
their own folders and rows from before the tag adopt into whoever
opens the library (`_adopt_untagged`). With a library present and
nobody picked, reads serve the copy - the sidebar keeps its last-known
list through the ASK dialog - and writes refuse; a removal still
sweeps EVERY user's keys under the folder, the shared-act rule.
"""

from __future__ import annotations

import os

from amaze.core import debug, keyed_store
from amaze.helpers import hostos


LOCATIONS_FILE = keyed_store.LOCATIONS
FAVOURITES_FILE = keyed_store.FAVOURITES

#: Set once the six settings.json keys have been proved to have landed
#: in the library, so a location the user later removes stays removed
#: rather than being re-adopted every launch. NOT swept with the other
#: one-time work in 2026-08-12: `_store_was_lost` clears this marker on
#: purpose, so the migration is also the recovery path for a
#: `locations.json` that was deleted or restored away.
MIGRATED_KEY = "file_locations_migrated"

#: The record's fields, and the settings.json surface each came from.
#: `registered` has no old surface of its own - it was the membership of
#: the `file_folders` LIST, which is exactly why a location that carried
#: no decoration was invisible to `location_paths()`: measured on the
#: real settings 2026-08-05, two of fourteen.
FIELDS = ("registered", "name", "color", "show_all", "recursive")

#: Libraries whose migration was tried this session and did not land.
#: Carried across module reloads for the same reason the registry is -
#: panel.py reloads this package on every panel open.
_deferred: set = globals().get("_deferred", set())


def normalise(value) -> dict:
    """A well-formed location record, or {} for junk.

    `show_all` is the one field whose FALSE is a real value - it is an
    override of the global Show Unknown Files preference, and the real
    settings hold exactly one of them, set to False. Dropping falsy
    fields here would silently turn that location's override back on.
    """
    if not isinstance(value, dict):
        return {}
    # UNKNOWN FIELDS RIDE ALONG: a newer build's field must survive an
    # older build's rewrite of the record - the engine keeps whole
    # foreign ENTRIES for the same reason, one level up.
    known = ("registered", "name", "color", "show_all", "recursive")
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
    """A star. Stored as a record rather than a bare true so the file
    has somewhere to grow, and so it reads the same way as every other
    store in the engine."""
    if not value:
        return {}
    return {"favourite": True}


SPEC = keyed_store.bind(LOCATIONS_FILE, normalise)
FAVOURITES_SPEC = keyed_store.bind(FAVOURITES_FILE, normalise_favourite)


# -- reachability ------------------------------------------------------


def library_present(preferences) -> bool:
    """Is the library folder actually there to be read?

    Asked of the FILESYSTEM, not of the store's state: a store opened
    against a directory that is not mounted reports FRESH - absent, and
    nothing says it was here - which is indistinguishable from a brand
    new library and would answer "you have no folders" at exactly the
    moment the truth is "I cannot see them".
    """
    directory = str(getattr(preferences, "dir", "") or "")
    return bool(directory) and os.path.isdir(directory)


def isolated(preferences) -> bool:
    """Test Mode: this library keeps its OWN locations, and the
    settings copy is neither read into it nor written from it.

    THE COPY IS A MIGRATION SEED, and a deliberate switch to another
    library is indistinguishable from the two accidents the seeding
    exists for - a restored snapshot, a hand-deleted `locations.json`.
    Measured 2026-08-08 on the first switch: the test library was
    handed the real library's folders, and the mirror would then have
    carried the test set back into the copy, leaving it as the seed
    for a future repair of the REAL library.

    So under Test Mode the store is the only truth. A fresh test
    library starts with no locations, which is the honest answer.
    """
    return bool(getattr(preferences, "test_mode", False)
                and getattr(preferences, "test_dir", ""))


def showing_last_known(preferences) -> bool:
    """Is the File section showing the settings.json copy rather than
    the library's own answer? What the sidebar marks as unreachable."""
    return not _ready(preferences)


def _awaiting_user(preferences) -> bool:
    """The store is per-user and nobody has been picked here yet, so it
    cannot answer WHOSE locations these are.

    Reads then serve the settings copy - the sidebar keeps its
    last-known list through the ASK dialog instead of opening empty on
    a machine that has folders - and writes are refused, the
    favourites' own no-user contract: writing the copy instead would
    show a folder that silently vanishes the moment a user is picked.
    Untagged, this is never the case and nothing here changes.
    """
    if not SPEC.user_tagged:
        return False
    try:
        return not str(preferences.library_user or "")
    except AttributeError:
        return True


def _ready(preferences) -> bool:
    """Is the library's own answer the one to use?

    Three states, and only the first two used to be distinguished. A
    library that is present but has NOT yet taken the settings over
    reads as an empty store - which is a perfectly good answer to "what
    does locations.json hold" and a disastrous one to "which folders are
    registered": the sidebar empties. So the migration is attempted HERE
    as well as at load, because `dir` can be set long after settings
    were read, and the copy stays the truth until it has landed.
    """
    if not library_present(preferences):
        return False
    if not _store(preferences).writable:
        return False
    if isolated(preferences):
        # NO MIGRATION UNDER TEST MODE. The store is present and
        # writable, so it is the answer - empty if this test library is
        # new, which is the truth about it. Falling through would seed
        # it from the real library's copy. The untagged-row adoption
        # DOES run: it moves rows inside this library's own file and
        # the copy plays no part in it.
        _adopt_untagged(preferences)
        return True
    if _awaiting_user(preferences):
        # Not parked and not a migration attempt: the check is one
        # attribute read, and the ASK dialog can land a user
        # mid-session - the very next read serves the store.
        return False
    data = getattr(preferences, "data", None)
    if isinstance(data, dict) and data.get(MIGRATED_KEY, False) \
            and _store_was_lost(preferences):
        # SELF-HEALING, decided 2026-08-05. A library restored from a
        # snapshot, or a `locations.json` deleted by hand, leaves a
        # readable EMPTY store on a machine that has already migrated -
        # and the sidebar goes empty with nothing said, which is exactly
        # what happened while section A was being built. Clearing the
        # marker sends it back through the migration, which re-seeds the
        # store from the copy: no second code path, and the union rule
        # already handles anything another machine has put there since.
        debug.event("file", "the location store is empty but the copy is "
                            "not - migrating again",
                    known=len(getattr(preferences, "last_known_folders", ())))
        data.pop(MIGRATED_KEY, None)
    if isinstance(data, dict) and not data.get(MIGRATED_KEY, False):
        # ONCE PER LIBRARY PER SESSION. This is reached from the paint
        # path, and a migration that cannot land - a read-only library,
        # a store that will not parse - must not be retried per tile.
        key = str(getattr(preferences, "dir", ""))
        if key in _deferred:
            return False
        migrate(preferences)
        if not data.get(MIGRATED_KEY, False):
            _deferred.add(key)
            return False
    if not _adopt_untagged(preferences):
        # Pre-tag rows still await their owner: the copy keeps serving
        # and the rows stay in the file for a session that can adopt.
        return False
    return True


#: (dir, uid) pairs whose untagged-row adoption could not land this
#: session - keyed on the USER too, like `_asset_deferred`, so picking
#: somebody in the ASK dialog or Preferences retries immediately.
_orphans_deferred: set = globals().get("_orphans_deferred", set())


def _adopt_untagged(preferences) -> bool:
    """File the rows from before locations were per-user under the
    current user, and PROVE it landed (ROADMAP line 22 stage C).

    SELF-MARKING: the file's own untagged rows are the to-do list. The
    engine keeps them aside at load and `adopt_orphans` writes their
    tagged spellings in the single commit that retires the untagged
    ones, so the move lands whole or not at all. Adopt-only: a row the
    user already holds wins. Runs from `_ready` and never from
    `load()`, which beats the first ordinary write to the rows because
    every write door passes through `_ready` first.

    Answers whether the store's own answer may be SERVED - nothing was
    waiting, or everything waiting landed and read back. False keeps
    the copy serving, the rows intact in the file.
    """
    store = _store(preferences)
    if not store.orphan_count():
        return True
    try:
        tag = str(preferences.library_user or "")
    except AttributeError:
        tag = ""
    if not tag:
        # Nobody to file them under - not parked, because the ASK
        # dialog can land a user mid-session and the next read should
        # finish the job.
        return False
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
        # Comparing, not counting the write (practice.md ▸ A migration
        # must COMPARE): a row that did not read back parks the
        # adoption and the copy keeps serving.
        _orphans_deferred.add(key)
        debug.event("file", "the location adoption did not reproduce",
                    missing=len(missing))
        return False
    debug.event("file", "locations from before the user tag adopted",
                count=len(waiting))
    return True


def _store_was_lost(preferences) -> bool:
    """Readable, already migrated, and EMPTY while the copy is not.

    NO FILE ON DISK - not merely an empty table. Removing the last
    location leaves a real file holding `{}`, and the copy is not
    rewritten until that same write finishes, so a rule keyed on "empty
    table plus non-empty copy" fires DURING the removal, from inside
    `_sync_mirror`, and puts the last folder straight back. Measured,
    not reasoned: the write reported ok and the key was still there.
    (`state` was no help - it was set once at load and stayed FRESH
    through every write, which is fixed in the engine now.)

    A deleted file is not this case either. It answers BLIND - absent
    but proven, by the `.bak` tier the engine wrote - and `_ready`
    refuses before reaching here, which is refuse-over-overwrite doing
    its job: reads fall back to the copy, writes wait for a repair.

    What is left is a store that has genuinely never existed here while
    this machine says it has already migrated: a library replaced, or
    pointed somewhere new, with the copy still holding what was last
    seen.
    """
    store = _store(preferences)
    if store.count() or os.path.exists(store.path):
        return False
    # The RECORDS, not the folder list: the migration's own input
    # (`_from_settings`) is derived from records, so asking a different
    # surface here let a folders-only copy re-clear the marker after a
    # migration that rightly carried nothing - a livelock between two
    # derivations of one fact.
    known = getattr(preferences, "last_known_records", None) or {}
    return bool(known)


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def _favourites_store(preferences):
    return keyed_store.open_store(FAVOURITES_SPEC, preferences)


# -- reading -----------------------------------------------------------


def record(preferences, path: str) -> dict:
    """Everything this location keeps, as one record. A field that is
    not set simply is not in it."""
    if not _ready(preferences):
        return _copy_record(preferences, path)
    return _store(preferences).get(path)


def paths(preferences) -> list:
    """Every path the store mentions, registered or not - as
    absolutes; the portable spelling is the file's business."""
    if not _ready(preferences):
        return [hostos.expand_storage_path(hostos.storage_path_key(p))
                for p in _copy_paths(preferences)]
    return [hostos.expand_storage_path(p)
            for p in _store(preferences).all()]


def registered_paths(preferences) -> list:
    """THE SIDEBAR LIST: the locations that are registered, in the local
    order, with anything the other machine added appended.

    Derived from the `registered` field rather than kept as a second
    list, which is what stops a location existing in one place and not
    the other. The order comes from the settings.json copy for the
    reason given at the top of this module.
    """
    # Order entries and store keys meet in STORAGE spelling - the copy
    # may still hold a legacy absolute beside the spelling the store
    # now uses, and comparing raw would list one location twice. The
    # answer expands back to absolutes at the end: the sidebar and the
    # scanner need paths `os.walk` can open; only the FILES carry the
    # portable spelling.
    known, seen = [], set()
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


def _copy_tag(preferences) -> str:
    """The tag this machine's COPY entries carry, "" when the store is
    not user-tagged.

    THE COPY IS KEYED THE WAY THE STORE IS, or the two disagree the
    moment the flag moves. Both ends of the copy are in this module -
    it is written by `_sync_mirror` and read by the fallbacks below - so
    the tag lives here rather than in `prefs`, which only holds the
    list.
    """
    if not FAVOURITES_SPEC.user_tagged:
        return ""
    try:
        return str(preferences.library_user or "")
    except AttributeError:
        return ""


def _copy_favourites(preferences) -> list:
    """THIS user's favourites out of the settings.json copy, UNTAGGED -
    the spelling every caller here already speaks.

    Without the scoping the copy answered for everybody, which is how a
    machine with nobody picked still lit another user's star while the
    store itself correctly wrote nothing.
    """
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
    """What to hand `keep_last_known`: tagged when the store is, and
    everyone ELSE's entries kept verbatim.

    Answers None when there is nobody to attribute them to, which the
    caller already treats as leave-it-alone - this machine has no
    business editing anybody else's rows.
    """
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
    """The star's question, asked per row per repaint - a membership
    test, no copy. Compared in STORAGE spelling, so the star does not
    depend on which spelling registered the file. The key is a file
    PATH for File rows and a bare asset id for every other section -
    the icons.json scheme - and an id rides through the path
    conversion unchanged.

    The migration hook is the same cheap early-out `_ready` keeps for
    the locations: one dict lookup when there is nothing to move."""
    migrate_asset_favourites(preferences)
    if not _ready(preferences):
        wanted = hostos.storage_path_key(path)
        return wanted in {hostos.storage_path_key(p)
                          for p in _copy_favourites(preferences)}
    return _favourites_store(preferences).has(path)


# -- writing -----------------------------------------------------------


#: Bumped on every record write - the cache token for the paint path.
#: A colour set through ANY prefs surface must show on the very next
#: data() read with no notification channel (the pinned File-tile
#: contract), and this is the one write door they all go through.
_generation = 0


def generation() -> int:
    """A number that moves whenever any location record moves."""
    return _generation


def set_record(preferences, path: str, value) -> keyed_store.Written:
    """Write one location's whole record; an EMPTY record forgets the
    location across every field at once, registration included.

    The one call a removal and a relocation both go through, so neither
    can visit four fields of five again.

    WITH NO LIBRARY IT WRITES THE COPY. The File section works with no
    library configured at all - it did before any of this, because it
    was backed by settings.json - and the answer to "where does this go
    then" must not be a relative path next to the current directory,
    which is what joining a store filename onto an empty `dir` gives.
    The copy is the only truth available, so it is the one written; the
    migration carries it in the moment a library appears.
    """
    global _generation
    _generation += 1
    # STORAGE spelling from here down, so the store and the settings
    # copy hold the same portable form - the store would convert for
    # itself, the copy would not.
    path = hostos.storage_path_key(path)
    if not _ready(preferences):
        if library_present(preferences) and _awaiting_user(preferences):
            # The library is there and the store is per-user: a write
            # with nobody picked has nobody to belong to. Refused like
            # a favourite's - the folder never appears, which is the
            # report. The copy is NOT written: a copy-only folder
            # would show now and silently vanish the moment a user is
            # picked, which is worse than the gesture doing nothing.
            return keyed_store.Written(
                False, keyed_store.REASON_NO_USER, "", (path,))
        return _write_copy(preferences, path, value)
    written = _store(preferences).set(path, value or {})
    _sync_mirror(preferences)
    return written


def register(preferences, path: str) -> keyed_store.Written:
    """Register a location pointer. Keeps whatever the record already
    carries - re-adding a folder that another machine had labelled must
    not throw the label away."""
    current = record(preferences, path)
    current["registered"] = True
    return set_record(preferences, path, current)


def unregister(preferences, path: str) -> keyed_store.Written:
    """Forget a location entirely. Everything ELSE keyed under it -
    favourites, comments, tile icons - goes through the engine's
    `retire_prefix`, which the File model calls; this is the pointer."""
    return set_record(preferences, path, {})


def set_field(preferences, path: str, field: str, value) -> keyed_store.Written:
    """One field of one location, read-modify-write through the record.

    Named rather than left to callers so that "set the colour" cannot
    become "write a record with only a colour in it", which is how a
    registration would disappear behind a sidebar colour pick.
    """
    if field not in FIELDS:
        raise ValueError("%r is not a location field" % (field,))
    current = record(preferences, path)
    if value is None or value == "" or value is False and field != "show_all":
        current.pop(field, None)
    else:
        current[field] = value
    return set_record(preferences, path, current)


def relocate_record(preferences, old: str, new: str) -> keyed_store.Written:
    """Move ONE location's record to a new path, in one write.

    This was two `set_record` calls - remove the old key, then add the
    new one - and they are two independent trips to disk. If the first
    landed and the second was denied, which is one transient outage of
    a synced library, the location was deregistered and its record went
    with it: colour, custom name, recursion and Show All Files, gone,
    with the folder simply missing from the sidebar.

    `rekey` is the engine's answer and its docstring is about exactly
    this: *a half-rewritten keyspace is worse than the orphaning it
    fixes, and a rename expressed as delete-then-add can be
    half-resurrected by the other pane.* One guarded write that either
    lands whole or does not land.
    """
    global _generation
    _generation += 1
    old = hostos.storage_path_key(old)
    new = hostos.storage_path_key(new)
    if not old or not new or old == new:
        return keyed_store.Written(True, keyed_store.REASON_UNCHANGED)
    if not _ready(preferences):
        if library_present(preferences) and _awaiting_user(preferences):
            # Same refusal as `set_record`: with the library present
            # and nobody picked there is nobody to move a record for.
            return keyed_store.Written(
                False, keyed_store.REASON_NO_USER, "", (old, new))
        # No library to write into: the copy is the only truth, and it
        # carries the record under its own key.
        record = _copy_record(preferences, old)
        _write_copy(preferences, old, {})
        return _write_copy(preferences, new, record)
    written = _store(preferences).rekey({old: new})
    _sync_mirror(preferences)
    return written


def set_favourite(preferences, path: str, on: bool) -> keyed_store.Written:
    # The migration runs BEFORE the write, so an unstar cannot be
    # resurrected by a later union of the not-yet-moved settings list.
    migrate_asset_favourites(preferences)
    path = hostos.storage_path_key(path)
    if not _ready(preferences):
        return _write_copy_favourite(preferences, path, bool(on))
    written = _favourites_store(preferences).set(path, bool(on))
    _sync_mirror(preferences)
    return written


# -- the settings.json copy -------------------------------------------


def _copy_record(preferences, path: str) -> dict:
    """One record, out of the copy. Only reached when the library is not
    there to answer. The copy may predate the portable spelling, so the
    raw path is the second look, not the first."""
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
        # Nobody picked, so there is nobody to attribute this to. The
        # store refuses the same write for the same reason.
        return keyed_store.Written(False, keyed_store.REASON_NO_USER, "",
                                   (path,))
    keep(None, None, tagged)
    return keyed_store.Written(True, keyed_store.REASON_NONE, "", (path,))


def _sync_mirror(preferences) -> None:
    """Refresh the settings.json copy from what the library now says,
    and persist it.

    One direction only. The copy is never read back into the store: a
    mirror that can write is a second truth, and two truths over one
    fact is the whole defect this module exists to end.
    """
    if not library_present(preferences):
        return
    if isolated(preferences):
        # THE OTHER DIRECTION, and the dangerous one. The copy is the
        # seed a future repair of the REAL library reads, so letting a
        # test library write it would arm that repair with test data.
        return
    if _awaiting_user(preferences):
        # A scoped read with nobody picked answers {} - which is not
        # "no locations", it is "no answer". Blanking the copy with it
        # would lose the fallback at the exact moment it is serving.
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


# -- the migration -----------------------------------------------------


def _from_settings(preferences) -> tuple:
    """What the migration carries in: THE COPY, never the accessors.

    `preferences.file_folder_names` and its three siblings are derived
    from this module now, so reading them here would ask the migration's
    own output what the migration should write - and re-enter `_ready`
    on the way. `last_known_records` is the copy load() carried in,
    which is exactly the input wanted.
    """
    records = {}
    for path, value in (getattr(preferences, "last_known_records", None)
                        or {}).items():
        value = normalise(value)
        if value:
            records[path] = value
    favourites = _copy_favourites(preferences)
    return records, favourites


def migrate(preferences) -> dict:
    """Move the six settings.json keys into the two library stores, and
    PROVE it landed before saying so.

    The acceptance test is the END STATE, not that the write ran
    (practice.md ▸ *A migration must COMPARE*): every record is read
    back out of the store and compared with what went in, BOTH ways, and
    a disagreement leaves the marker unset so the next launch tries
    again with the old keys still intact.

    Answers a dict rather than a bool because the not-done outcomes
    are different things: `deferred` (no library yet - try again when
    there is one) and `refused` (it did not land, and the old keys are
    still the truth). A success reports how many of this machine's own
    locations JOINED ones already in the library, because on the second
    Mac that number is the visible outcome.
    """
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

    # THE UNION, ADOPT-ONLY - the engine's own rule (`_adopt_from_disk`:
    # adoption can only ADD). When the other machine migrated first the
    # store already holds ITS locations, and this machine's six keys are
    # NOT a stale copy of them: **preferences never synced between the
    # two Macs** (INSTALL.md - "favourites, registered folders and view
    # state are per-machine"), so they are this machine's own registered
    # folders and nothing has ever carried them anywhere. Taking the
    # store as-is would empty that machine's sidebar on the first launch
    # of this build.
    #
    # The cost, and it is the honest one: the two Macs end up with the
    # union of both sets of folders, on both machines. That is what
    # "locations follow the library" MEANS, it is visible, and Remove
    # Folder undoes it - where a silent discard could not be undone at
    # all, because the only record of what was lost was the file just
    # overwritten.
    existing = store.all()
    wanted = dict(existing)
    # STORAGE spelling before the union and the compare. The copy's
    # keys are legacy spellings - native, absolute, or two of them for
    # one folder - while the store answers in the portable form, so a
    # raw-keyed `wanted` can never reproduce: every entry reads as
    # missing on one side and extra on the other, and the migration
    # refuses forever. Converting here also collapses the copy's own
    # duplicate spellings, first in winning, same as the load rule.
    for path, record in mine.items():
        path = hostos.storage_path_key(path)
        if path not in wanted:
            wanted[path] = record
    wanted_favs = sorted(set(favourites.all())
                         | {hostos.storage_path_key(p) for p in my_favs})
    adopted = len(wanted) - len(existing)

    written = store.update(wanted)
    if not written and written.reason == keyed_store.REASON_NO_USER:
        # BOTH HALVES BELONG TO A PERSON since the locations went
        # per-user (stage C of ROADMAP line 22), so with nobody picked
        # the whole migration waits: marker unset, old keys still the
        # truth, and the next read with a user finishes the job.
        debug.event("file", "locations waiting for a user",
                    locations=len(wanted))
        return {"state": "deferred", "why": "no user yet"}
    written_favs = favourites.update({p: True for p in wanted_favs})
    if not written:
        debug.event("file", "location migration refused",
                    reason=written.reason)
        return {"state": "refused", "why": written.reason}
    if not written_favs:
        if written_favs.reason == keyed_store.REASON_NO_USER:
            # The locations landed but the favourites found nobody - a
            # belt for a user cleared between the two writes. Marker
            # unset, so a later session finishes the favourites.
            debug.event("file", "locations moved, favourites waiting "
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
        # NOT MARKED. The old keys are still written and still read, so
        # the section keeps working off them and the next launch tries
        # again - which is the whole point of comparing rather than
        # counting the write as the result.
        debug.event("file", "location migration did not reproduce",
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
            #: How many of this machine's own locations JOINED ones the
            #: other machine had already put there. Reported because the
            #: union is a visible product outcome, not bookkeeping: the
            #: second Mac's sidebar grows by the first Mac's folders.
            "joined": adopted, "already_there": len(existing)}


#: (dir, uid) pairs whose asset-favourites migration could not land
#: this session - the same per-tile retry guard `_ready` keeps for the
#: location migration, keyed on the USER too, so picking one in the
#: ASK dialog or Preferences retries immediately.
_asset_deferred: set = set()


def migrate_asset_favourites(preferences) -> dict:
    """Move `material_favorites` - the Materials/Nodes/Code stars that
    lived in settings.json and never travelled - into the favourites
    store under the active user, and PROVE it landed before the key is
    dropped (practice.md ▸ *A migration must COMPARE*).

    SELF-MARKING: the settings key IS the to-do list. It is popped only
    after every id reads back out of the store, so a deferral (no
    library yet, no user yet, Test Mode) or a refusal leaves the old
    key authoritative and a later session finishes the job. Adopt-only
    union like the location migration above: an id already in the
    store is kept, so two machines migrating one user's lists converge
    on the union and nothing is ever discarded silently.

    Runs from `load()` beside `migrate`, and again from the favourite
    doors below - `dir` and the user can both be set long after
    settings were read, and the second machine's stars should appear
    the moment its owner picks themselves rather than next launch.
    """
    data = getattr(preferences, "data", None)
    if not isinstance(data, dict):
        return {"state": "deferred", "why": "no settings"}
    raw = [str(x) for x in (data.get("material_favorites") or ())
           if str(x).strip()]
    if not raw:
        # An empty list is finished business - drop the key so the
        # unknown-key courtesy stops carrying it forever.
        data.pop("material_favorites", None)
        return {"state": "done"}
    if isolated(preferences):
        # NO MIGRATION UNDER TEST MODE. These are the real library's
        # stars; landing them in a test library would also pop the key
        # and lose them for the real one.
        return {"state": "deferred", "why": "test mode"}
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
        # NOT POPPED. The old key is still the truth and the next
        # session tries again - comparing, not counting the write.
        _asset_deferred.add(key)
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
    """Drop the cached tables - a library switch or a test needs a
    re-read. The deferred sets go with them: a library that could not
    be migrated because it was unreachable deserves another try once
    something has changed enough to call this."""
    _deferred.clear()
    _asset_deferred.clear()
    _orphans_deferred.clear()
    keyed_store.release()
