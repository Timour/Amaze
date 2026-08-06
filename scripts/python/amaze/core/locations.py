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
"""

from __future__ import annotations

import os

from amaze.core import debug, keyed_store
from amaze.helpers import hostos


LOCATIONS_FILE = keyed_store.LOCATIONS
FAVOURITES_FILE = keyed_store.FAVOURITES

#: Set once the six settings.json keys have been proved to have landed
#: in the library. The same marker shape `file_section_migrated`
#: already uses, and for the same reason: a location the user later
#: removes must stay removed rather than being re-adopted every launch.
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
    record = {}
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


def showing_last_known(preferences) -> bool:
    """Is the File section showing the settings.json copy rather than
    the library's own answer? What the sidebar marks as unreachable."""
    return not _ready(preferences)


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
    known = getattr(preferences, "last_known_folders", ()) or ()
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


def favourite_paths(preferences) -> list:
    if not _ready(preferences):
        return [hostos.expand_storage_path(hostos.storage_path_key(p))
                for p in (getattr(preferences, "last_known_favourites", ())
                          or ())]
    return [hostos.expand_storage_path(p)
            for p in sorted(_favourites_store(preferences).all())]


def is_favourite(preferences, path: str) -> bool:
    """The star's question, asked per row per repaint - a membership
    test, no copy. Compared in STORAGE spelling, so the star does not
    depend on which spelling registered the file."""
    if not _ready(preferences):
        wanted = hostos.storage_path_key(path)
        return wanted in {
            hostos.storage_path_key(p)
            for p in (getattr(preferences, "last_known_favourites", ())
                      or ())}
    return _favourites_store(preferences).has(path)


# -- writing -----------------------------------------------------------


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
    # STORAGE spelling from here down, so the store and the settings
    # copy hold the same portable form - the store would convert for
    # itself, the copy would not.
    path = hostos.storage_path_key(path)
    if not _ready(preferences):
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


def set_favourite(preferences, path: str, on: bool) -> keyed_store.Written:
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
    favourites = list(getattr(preferences, "last_known_favourites", ()) or ())
    if on and path not in favourites:
        favourites.append(path)
    elif not on and path in favourites:
        favourites.remove(path)
    else:
        return keyed_store.Written(True, keyed_store.REASON_UNCHANGED,
                                   keys=(path,))
    keep(None, None, favourites)
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
    store = _store(preferences)
    favourites = _favourites_store(preferences)
    if not store.writable and not favourites.writable:
        return
    keep = getattr(preferences, "keep_last_known", None)
    if not callable(keep):
        return
    keep(store.all() if store.writable else None,
         registered_paths(preferences) if store.writable else None,
         sorted(favourites.all()) if favourites.writable else None)


# -- the migration -----------------------------------------------------


def _from_settings(preferences) -> tuple:
    """What the migration carries in: THE COPY, never the accessors.

    `preferences.file_folder_names` and its three siblings are derived
    from this module now, so reading them here would ask the migration's
    own output what the migration should write - and re-enter `_ready`
    on the way. `_load_location_copy` has already composed the copy out
    of the six old keys, which is exactly the input wanted.
    """
    records = {}
    for path, value in (getattr(preferences, "last_known_records", None)
                        or {}).items():
        value = normalise(value)
        if value:
            records[path] = value
    favourites = [
        path for path in
        (getattr(preferences, "last_known_favourites", ()) or [])
        if isinstance(path, str) and path]
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
    written_favs = favourites.update({p: True for p in wanted_favs})
    if not written or not written_favs:
        debug.event("file", "location migration refused",
                    reason=written.reason or written_favs.reason)
        return {"state": "refused",
                "why": written.reason or written_favs.reason}

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


def forget() -> None:
    """Drop the cached tables - a library switch or a test needs a
    re-read. The deferred set goes with them: a library that could not
    be migrated because it was unreachable deserves another try once
    something has changed enough to call this."""
    _deferred.clear()
    keyed_store.release()
