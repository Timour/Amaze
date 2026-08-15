"""Declare a guarded JSON side-table with `register`; open it with `open_store`. ▸p/store-guards ▸p/store-declarations"""

from __future__ import annotations

import copy
import json
import os

from amaze.core import database, debug
from amaze.helpers import hostos


KEY_ID = "id"                       # an asset id - a folder move leaves it
KEY_PATH = "path"                   # a path - a folder move rewrites it
KEY_MIXED = "mixed"                 # both, so the store declares path_prefix

USER_SEP = "|"                      # `<uid>|<key>`, split on the FIRST one

READ = "read"                       # parsed from a file that is there
FRESH = "fresh"                     # absent, nothing says it was ever here
BLIND = "blind"                     # unreadable or absent-but-proven: no writes

REASON_NONE = ""                    # it landed
REASON_UNCHANGED = "unchanged"      # nothing to do; `ok` is True
REASON_LATCHED = "latched"          # the file is there and will not parse
REASON_ABSENT = "absent-but-known"  # it is gone and something says it was here
REASON_DENIED = "denied"            # OSError - read-only, full, unreachable
REASON_NO_USER = "no-user"          # tagged store, nobody picked on this machine


class Written:
    """A write's outcome AND its reason; truthy also when there was nothing to do."""

    __slots__ = ("ok", "reason", "sentence", "keys")

    def __init__(self, ok: bool, reason: str = REASON_NONE,
                 sentence: str = "", keys=()) -> None:
        self.ok = ok
        self.reason = reason
        self.sentence = sentence        # fit to show the user as-is
        self.keys = tuple(keys)         # which keys this write was about

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:                                # pragma: no cover
        return "<Written %s%s>" % (
            "ok" if self.ok else "refused",
            "" if not self.reason else ": " + self.reason)


MERGE_MINE = "mine"                 # ours wins - the default ▸p/document-not-table
MERGE_COMBINE = "combine"           # ours, then theirs, no duplicates
MERGE_FIELDS = "fields"             # field by field inside a record both hold


class Spec:
    """One store as DATA - everything the engine needs to guard a file it has never heard of. ▸p/store-declarations"""

    __slots__ = ("filename", "payload", "keyspace", "label", "noun",
                 "normalise", "path_prefix", "unreadable_alert",
                 "refused_sentence", "alert_key", "denied_alert",
                 "category", "in_library", "survives_forget",
                 "user_tagged", "merge_rules", "falsy_is_a_value",
                 "absence_is_fresh")

    def __init__(self, filename, payload, keyspace, label, noun,
                 normalise, path_prefix="", unreadable_alert="",
                 refused_sentence="", alert_key="", denied_alert="",
                 category="store", in_library=True,
                 survives_forget=True, user_tagged=False,
                 merge_rules=None, falsy_is_a_value=False,
                 absence_is_fresh=False) -> None:
        self.filename = filename
        self.payload = payload
        self.keyspace = keyspace
        self.label = label              # what Repair calls it on screen
        self.noun = noun                # singular, for "40 comments"
        self.normalise = normalise
        self.path_prefix = path_prefix  # KEY_MIXED only
        self.unreadable_alert = unreadable_alert
        self.refused_sentence = refused_sentence
        self.alert_key = alert_key or (filename + "-unreadable")
        self.denied_alert = denied_alert    # BLANK MEANS SAY NOTHING
        self.category = category            # debug-log category
        self.in_library = in_library        # does Repair survey it?
        self.user_tagged = user_tagged      # are its keys `<uid>|<key>`?
        self.survives_forget = survives_forget  # outlive a location removal?
        self.merge_rules = dict(merge_rules or {})
        self.falsy_is_a_value = bool(falsy_is_a_value)
        self.absence_is_fresh = bool(absence_is_fresh)

    def is_path_key(self, key: str) -> bool:
        """Does a path move rewrite this key?"""
        if self.keyspace == KEY_PATH:
            return True
        if self.keyspace == KEY_MIXED:
            return bool(self.path_prefix) and str(key).startswith(
                self.path_prefix)
        return False

    def __repr__(self) -> str:                                # pragma: no cover
        return "<Spec %s>" % (self.filename,)


_registry: dict = globals().get("_registry", {})  # survives a panel reload ▸r/module-reload


def register(filename: str, payload: str, keyspace: str, label: str,
             noun: str, normalise=None, path_prefix: str = "",
             unreadable_alert: str = "", refused_sentence: str = "",
             alert_key: str = "", denied_alert: str = "",
             category: str = "store", in_library: bool = True,
             survives_forget: bool = True,
             user_tagged: bool = False,
             merge_rules: dict = None,
             falsy_is_a_value: bool = False,
             absence_is_fresh: bool = False) -> Spec:
    """Declare a store; idempotent per filename, so a module reload re-registers. ▸p/store-declarations"""
    if keyspace not in (KEY_ID, KEY_PATH, KEY_MIXED):
        raise ValueError("unknown keyspace %r" % (keyspace,))
    if keyspace == KEY_MIXED and not path_prefix:
        raise ValueError(
            "a mixed-keyspace store must say which prefix marks a path "
            "key, or a folder move cannot tell them apart")
    spec = Spec(filename=filename, payload=payload, keyspace=keyspace,
                label=label, noun=noun, normalise=normalise,
                path_prefix=path_prefix,
                unreadable_alert=unreadable_alert,
                refused_sentence=refused_sentence, alert_key=alert_key,
                denied_alert=denied_alert, category=category,
                in_library=in_library, survives_forget=survives_forget,
                user_tagged=user_tagged, merge_rules=merge_rules,
                falsy_is_a_value=falsy_is_a_value,
                absence_is_fresh=absence_is_fresh)
    _registry[filename] = spec
    return spec


def bind(filename: str, normalise) -> Spec:
    """Attach the normaliser; a declared store nothing has bound is surveyable, not openable. ▸p/store-declarations"""
    spec = _registry.get(filename)
    if spec is None:
        raise KeyError("%s is not a declared store" % (filename,))
    spec.normalise = normalise
    return spec


def stores() -> tuple:
    """THE enumeration - never write your own; `tools/library-audit.py` cannot see it and keeps a copy. ▸p/store-declarations"""
    return tuple(_registry.values())


def store_for(filename: str):
    return _registry.get(filename)


def filenames() -> tuple:
    """Only the stores that are FILES IN THE LIBRARY - what Repair surveys and the audit expects on disk."""
    return tuple(name for name, spec in _registry.items() if spec.in_library)


register(
    filename="notes.json",
    payload="notes",
    keyspace=KEY_MIXED,
    path_prefix="file:",
    label="Comments",
    noun="comment",
    category="notes",
    alert_key="notes-unreadable",
    unreadable_alert=(
        "Your notes could not be read, so Amaze will not save over "
        "them.\n\n"
        "Nothing has been lost. The Notes panel shows empty pages for "
        "now, and anything you write will not be kept.\n\n"
        "Close Houdini and put back a recent copy with the Repair tool "
        "in the Amaze shelf."),
    refused_sentence=(
        "the notes file could not be read earlier this run, so what you "
        "wrote was not saved - writing now would replace every note "
        "already in it."),
    denied_alert=(
        "Your comment could not be saved.\n\n"
        "Nothing already saved has been lost - only this change. It is "
        "still on screen, so you can copy it somewhere safe before "
        "closing Houdini."),
    survives_forget=False,
)

LOCATIONS = "locations.json"        # one record per registered folder

FAVOURITES = "favourites.json"      # every section's, keyed to its owner

register(
    filename=LOCATIONS,
    payload="locations",
    keyspace=KEY_PATH,
    label="File locations",
    noun="location",
    category="file",
    alert_key="locations-unreadable",
    unreadable_alert=(
        "Your registered folders could not be read, so Amaze will not "
        "save over them.\n\n"
        "Nothing has been lost. The File section is showing the copy "
        "your last session left behind, and any folder you add or "
        "rename now will not be kept.\n\n"
        "Close Houdini and put back a recent copy with the Repair tool "
        "in the Amaze shelf."),
    refused_sentence=(
        "the registered folders could not be read earlier this run, so "
        "this change was not saved - writing now would replace every "
        "folder already in the list."),
    survives_forget=False,
    user_tagged=True,
)

register(
    filename=FAVOURITES,
    payload="favourites",
    keyspace=KEY_PATH,
    label="Favourites",
    noun="favourite",
    category="file",
    alert_key="favourites-unreadable",
    unreadable_alert=(
        "Your file favorites could not be read, so Amaze will not save "
        "over them.\n\n"
        "Nothing has been lost. The star shows nothing for now, and "
        "anything you star will not be kept.\n\n"
        "Close Houdini and put back a recent copy with the Repair tool "
        "in the Amaze shelf."),
    refused_sentence=(
        "the favorites file could not be read earlier this run, so your "
        "star was not saved - writing now would replace every favorite "
        "already in it."),
    survives_forget=False,
    user_tagged=True,
)

register(
    filename="users.json",
    payload="users",
    keyspace=KEY_ID,
    label="Users",
    noun="user",
    category="users",
    alert_key="users-unreadable",
    unreadable_alert=(
        "The list of people using this library could not be read, so "
        "Amaze will not save over it.\n\n"
        "Nothing has been lost. Amaze is working without a user for "
        "now, so anything you star or register this session will not "
        "be kept.\n\n"
        "Close Houdini and put back a recent copy with the Repair tool "
        "in the Amaze shelf."),
    refused_sentence=(
        "the list of people using this library could not be read "
        "earlier this run, so your change was not saved - writing now "
        "would replace everyone already in it."),
    survives_forget=True,
)

register(
    filename="icons.json",
    payload="icons",
    keyspace=KEY_PATH,
    label="Tile icons",
    noun="tile icon",
    category="icons",
    alert_key="icons-unreadable",
    unreadable_alert=(
        "The tile icons you chose could not be read, so Amaze will not "
        "save over them.\n\n"
        "Nothing has been lost. Your tiles show their default icons for "
        "now, and any icon you pick will not be kept.\n\n"
        "Close Houdini and put back a recent copy with the Repair tool "
        "in the Amaze shelf."),
    refused_sentence=(
        "the tile icon file could not be read earlier this run, so your "
        "icon choice was not saved - writing now would replace every "
        "icon already in it."),
    denied_alert=(
        "The icon you picked could not be saved.\n\n"
        "Nothing already saved has been lost - only this choice. The "
        "tile goes back to the icon it had next time Amaze opens."),
    survives_forget=False,
)

PREFS = "prefs.json"                # the library's SHARED settings, untagged

register(
    filename=PREFS,
    payload="prefs",
    keyspace=KEY_ID,
    label="Shared settings",
    noun="setting",
    category="prefs",
    alert_key="shared-settings-unreadable",
    unreadable_alert=(
        "The library's shared settings could not be read, so Amaze "
        "will not save over them.\n\n"
        "Nothing has been lost. Amaze is using the settings your last "
        "session left behind for now, and any setting you change will "
        "not be kept.\n\n"
        "Close Houdini and put back a recent copy with the Repair tool "
        "in the Amaze shelf."),
    refused_sentence=(
        "the library's shared settings could not be read earlier this "
        "run, so your change was not saved - writing now would replace "
        "every setting already in it."),
    denied_alert=(
        "Your setting could not be saved.\n\n"
        "Nothing already saved has been lost - only this change. It "
        "still applies for now, and goes back to what it was next time "
        "Amaze opens."),
    survives_forget=True,
)

SETTINGS = "settings.json"          # machine-local: it POINTS at the library

register(
    filename=SETTINGS,
    payload="",
    keyspace=KEY_ID,
    label="Settings",
    noun="setting",
    category="prefs",
    in_library=False,
    falsy_is_a_value=True,
    absence_is_fresh=True,
    merge_rules={                   # BOTH shapes are live: flat, and under a uid
        "file_folders": MERGE_COMBINE,
        "file_favorites": MERGE_COMBINE,
        "users/*/file_folders": MERGE_COMBINE,
        "users/*/file_favorites": MERGE_COMBINE,
        "file_location_records": MERGE_FIELDS,
        "users/*/file_location_records": MERGE_FIELDS,
        "users": MERGE_FIELDS,
    },
    alert_key="prefs-unreadable",
    unreadable_alert=(
        "Your Amaze settings could not be read, so Amaze has opened "
        "with the defaults.\n\n"
        "Nothing has been lost. Your settings file was kept untouched, "
        "and Amaze will not save over it - so your library path, "
        "folders and favourites are still there.\n\n"
        "Your settings are also recorded in the debug log. Use the "
        "Repair tool in the Amaze shelf to put them back."),
    refused_sentence=(
        "your settings could not be read earlier this run, so this "
        "change was not saved - writing now would replace the library "
        "path, folders and favourites already in the file."),
    denied_alert=(
        "Amaze could not save your preferences.\n\n"
        "Your settings for this session still work, but they will not "
        "be there next time Houdini opens."),
    survives_forget=True,
)


_open: dict = {}                    # (filename, resolved path) -> Store


def _root_for(spec: Spec, preferences) -> str:
    """Which directory this store's file lives in; REFUSES rather than defaulting to the library. ▸p/store-declarations"""
    if spec.in_library:
        return str(preferences.dir)
    root = str(getattr(preferences, "path", "") or "")
    if not root:
        raise ValueError(
            "%s is machine-local and this Prefs cannot say where the "
            "configuration lives - refusing to fall back to the "
            "library" % spec.filename)
    return root


def _same_file(path: str) -> str:
    """The cache IDENTITY of a store file - the KEY only; `Store.path` keeps its spelling. ▸p/one-file-one-table"""
    return hostos.canonical_path_key(path)


def open_store(spec: Spec, preferences) -> "Store":
    """The store for this library, read once and CACHED - every reader the same rows. ▸p/one-file-one-table"""
    path = os.path.join(_root_for(spec, preferences), spec.filename)
    handle = _open.get((spec.filename, _same_file(path)))
    if handle is None:
        handle = Store(spec, path, preferences)
        _open[(spec.filename, _same_file(path))] = handle
    else:
        handle.preferences = preferences  # the user can change under it
    return handle


def own_store(spec: Spec, preferences) -> "Store":
    """A store this caller alone holds, with its OWN stale-write baseline - for a document two panes disagree about. ▸p/document-not-table"""
    return Store(spec, os.path.join(_root_for(spec, preferences),
                                    spec.filename), preferences)


class Store:
    """One library's copy of one registered store."""

    def __init__(self, spec: Spec, path: str, preferences=None) -> None:
        # `preferences` resolves the user tag and nothing else. ▸p/keyed-store-slate
        self.spec = spec
        self.path = path
        self.preferences = preferences
        self._blank_slate()
        self._load()

    def _forget_tables(self) -> None:
        """Empty the three tables a load fills: readers', the peer's, the ownerless. ▸p/keyed-store-slate"""
        self._table: dict = {}
        self._foreign: dict = {}
        self._orphans: dict = {}

    def _blank_slate(self) -> None:
        """Forget disk entirely, verdict included - the state a `_load` starts from. ▸p/keyed-store-slate"""
        self._forget_tables()
        self._disk_state = None
        self.state = FRESH
        self.trace = ""

    def _rejected(self, kept) -> bool:
        """Did the normaliser refuse this value? A settings store refuses with None. ▸p/store-declarations"""
        if self.spec.falsy_is_a_value:
            return kept is None
        return not kept

    def _staged_value(self, value):
        """What to store, or None to REMOVE the key - a settings store removes through `retire` instead."""
        if self.spec.falsy_is_a_value:
            return self.spec.normalise(value)
        if not value:
            return None
        return self.spec.normalise(value) or None

    def _table_in(self, loaded: dict):
        """The map inside a document that has just been read."""
        return loaded.get(self.spec.payload) if self.spec.payload else loaded

    def _document(self, table: dict) -> dict:
        """The bytes to write - the map ITSELF for a store that declares no payload."""
        return {self.spec.payload: table} if self.spec.payload else table

    def _load(self) -> None:
        """Read the file once and settle the verdict: READ, FRESH or BLIND. ▸p/store-commit-order"""
        spec = self.spec
        try:
            if os.path.exists(self.path):
                with open(self.path, "rb") as handle:
                    raw = handle.read()
                loaded = json.loads(raw.decode("utf-8-sig"))  # -sig: a BOM would latch it
                wrong = database.wrong_table_shape(loaded, spec.payload)
                if wrong:
                    raise ValueError(wrong)
                if spec.payload and spec.payload not in loaded:
                    raise ValueError(
                        "%s holds no %r - this is not the %s file"
                        % (spec.filename, spec.payload, spec.label))
                table = {}
                orphans = 0
                for key, value in self._table_in(loaded).items():
                    stored = restored_key(spec, str(key))
                    if spec.user_tagged and not untagged_key(spec, stored)[0]:
                        kept = spec.normalise(value)
                        if (not self._rejected(kept)
                                and stored not in self._orphans):
                            self._orphans[stored] = kept
                        orphans += 1
                        continue
                    kept = spec.normalise(value)
                    if self._rejected(kept):
                        if value and stored not in self._foreign:
                            self._foreign[stored] = value
                        continue
                    if stored in table:
                        debug.event(spec.category,
                                    "two spellings of one key on load "
                                    "- first kept",
                                    kept=stored, dropped=str(key))
                        continue
                    table[stored] = kept
                self._table = table
                if orphans:
                    debug.event(spec.category,
                                "entries from before this store had "
                                "owners - dropped", count=orphans,
                                store=spec.filename)
                if self._foreign:
                    debug.event(spec.category,
                                "entries this build cannot read - kept "
                                "aside, written back on every save",
                                count=len(self._foreign),
                                store=spec.filename)
                self.state = READ
            else:
                self.trace = ("" if spec.absence_is_fresh
                              else hostos.existed_before(self.path))
                if self.trace:
                    self.state = BLIND
                    self._refuse_and_alert(
                        "%s is missing but %s says it was here"
                        % (spec.filename, self.trace))
                else:
                    self.state = FRESH
        except (OSError, ValueError) as exc:
            self.state = BLIND
            self._forget_tables()
            hostos.preserve_unreadable(self.path, why=spec.label.lower())
            self._refuse_and_alert(str(exc))
        self._remember_disk_state()

    def _refuse_and_alert(self, why: str) -> None:
        spec = self.spec
        debug.event(spec.category,
                    "%s unreadable - changes disabled this session"
                    % (spec.filename,), path=self.path, error=why,
                    state=self.state)
        if spec.unreadable_alert:
            debug.alert(spec.unreadable_alert, key=spec.alert_key)

    def user_tag(self) -> str:
        """The UID these keys are tagged with, "" when untagged or nobody is picked - never a shared bucket."""
        if not self.spec.user_tagged:
            return ""
        try:
            return str(self.preferences.library_user or "")
        except AttributeError:
            return ""

    def _key(self, key) -> str:
        """The stored spelling, tag included; "" when tagged and nobody is picked - no read, no write."""
        if self.spec.user_tagged:
            tag = self.user_tag()
            if not tag:
                return ""
            return storage_key(self.spec, key, tag)
        return storage_key(self.spec, key)

    def has(self, key) -> bool:
        """Does this key carry anything? THE PAINT PATH - a membership test, no copy, no I/O."""
        stored = self._key(key)
        return bool(stored) and stored in self._table

    def get(self, key) -> dict:
        """One value as a COPY, {} when there is none - the live value would let a caller mutate the cache."""
        stored = self._key(key)
        if not stored or stored not in self._table:
            return {}
        value = self._table[stored]
        if not (value or self.spec.falsy_is_a_value):
            return {}
        return copy.deepcopy(value)

    def all(self) -> dict:
        """THIS USER's entries as a COPY, keyed without the tag; `everyones()` is the unscoped read."""
        if not self.spec.user_tagged:
            return copy.deepcopy(self._table)
        tag = self.user_tag()
        if not tag:
            return {}
        out = {}
        for stored, value in self._table.items():
            owner, bare = untagged_key(self.spec, stored)
            if owner == tag:
                out[bare] = copy.deepcopy(value)
        return out

    def everyones(self) -> dict:
        """The whole table as stored, tags included - repair and migration, never the paint path."""
        return copy.deepcopy(self._table)

    def orphaned(self) -> dict:
        """Rows from before this store had owners, keyed bare - empty again after ANY commit. ▸p/store-commit-order"""
        return copy.deepcopy(self._orphans)

    def orphan_count(self) -> int:
        """The cheap half of `orphaned`, for the per-paint guard."""
        return len(self._orphans)

    def count(self) -> int:
        return len(self._table)

    @property
    def writable(self) -> bool:
        return self.state in (READ, FRESH)

    def set(self, key, value) -> Written:
        """Store one key; a falsy value REMOVES it - an empty note deletes the note."""
        key = self._key(key)
        if not key:
            debug.event(self.spec.category, "write skipped - no user",
                        store=self.spec.filename)
            return Written(False, REASON_NO_USER)
        value = self._staged_value(value)
        if value is not None:
            if key in self._table and self._table[key] == value:
                return Written(True, REASON_UNCHANGED, keys=(key,))
            staged = dict(self._table)
            staged[key] = value
        else:
            if key not in self._table:
                return Written(True, REASON_UNCHANGED, keys=(key,))
            staged = dict(self._table)
            staged.pop(key, None)
        return self._commit(staged, (key,))

    def update(self, values: dict) -> Written:
        """Store many keys in ONE write - per-key `set` would rotate the restore tier away. ▸p/store-commit-order"""
        staged = dict(self._table)
        touched = []
        if not (values or {}):          # doing nothing cannot fail
            return Written(True, REASON_UNCHANGED)
        if self.spec.user_tagged and not self.user_tag():
            return Written(False, REASON_NO_USER)
        for key, value in (values or {}).items():
            key = self._key(str(key))
            value = self._staged_value(value)
            if value is not None:
                if key in self._table and self._table[key] == value:
                    continue
                staged[key] = value
            else:
                if key not in self._table:
                    continue
                staged.pop(key, None)
            touched.append(key)
        if not touched:
            return Written(True, REASON_UNCHANGED)
        return self._commit(staged, touched)

    def rekey(self, moves: dict) -> Written:
        """Rewrite keys in ONE write - a half-rewritten keyspace is worse than the orphaning it fixes."""
        if not (moves or {}):
            return Written(True, REASON_UNCHANGED)
        if self.spec.user_tagged and not self.user_tag():
            return Written(False, REASON_NO_USER)
        moves = {self._key(str(k)): self._key(str(v))
                 for k, v in (moves or {}).items()}
        moves = {k: v for k, v in moves.items() if k != v}
        touched = [k for k in moves if k in self._table]
        if not touched:
            return Written(True, REASON_UNCHANGED)
        staged = dict(self._table)
        for old in touched:
            value = staged.pop(old)
            staged.setdefault(moves[old], value)  # a destination entry WINS
        return self._commit(staged, touched)

    def adopt_orphans(self) -> Written:
        """File every ownerless row under the current user in ONE write; adoption only ADDS. ▸p/store-commit-order"""
        if not self.spec.user_tagged or not self._orphans:
            return Written(True, REASON_UNCHANGED)
        if not self.user_tag():
            return Written(False, REASON_NO_USER)
        staged = dict(self._table)
        adopted = []
        for bare, value in self._orphans.items():
            key = self._key(bare)
            if key in staged:
                continue
            staged[key] = value
            adopted.append(key)
        return self._commit(staged, adopted)

    def retire_stored(self, keys) -> Written:
        """Drop keys AS STORED - every owner's, no user needed; `retire` is the scoped door. ▸p/keyed-store-slate"""
        return self._drop([str(k) for k in (keys or ())
                           if str(k) in self._table])

    def _drop(self, doomed) -> Written:
        """Commit the table without these STORED keys; an empty list is unchanged, not a failure. ▸p/keyed-store-slate"""
        if not doomed:
            return Written(True, REASON_UNCHANGED)
        staged = dict(self._table)
        for key in doomed:
            staged.pop(key, None)
        return self._commit(staged, doomed)

    def retire(self, keys) -> Written:
        """Drop keys - ONE write. A location is gone for good."""
        keys = list(keys or ())
        if not keys:
            return Written(True, REASON_UNCHANGED)
        if self.spec.user_tagged and not self.user_tag():
            return Written(False, REASON_NO_USER)
        return self._drop([self._key(str(k)) for k in keys
                           if self._key(str(k)) in self._table])

    def replace(self, document: dict, retire=()) -> Written:
        """Commit a WHOLE document - a key its author dropped is GONE; `retire` names what this build removed. ▸p/document-not-table"""
        if not isinstance(document, dict):
            raise TypeError("a document is an object, not %s"
                            % type(document).__name__)
        staged = {str(key): value for key, value in document.items()}
        return self._commit(staged, tuple(staged), retire=retire)

    def reread(self) -> Written:
        """Read the file again, discarding this Store's cache, and answer what the reopened store can do. ▸p/keyed-store-slate"""
        self._blank_slate()
        self._load()
        return Written(self.writable, REASON_NONE if self.writable
                       else (REASON_ABSENT if self.trace else REASON_LATCHED),
                       self.spec.refused_sentence if not self.writable else "")

    def _commit(self, staged: dict, keys, retire=()) -> Written:
        """EVERY write lands here - one guard set, and the cache moves only on success. ▸p/store-commit-order"""
        spec = self.spec
        if not self.writable:
            debug.note(spec.refused_sentence or (
                "%s could not be read earlier this run, so your change "
                "was not saved." % spec.label), path=self.path)
            reason = (REASON_ABSENT if self.trace else REASON_LATCHED)
            return Written(False, reason, spec.refused_sentence, keys)
        created = not os.path.exists(self.path)
        foreign = dict(self._foreign)   # a COPY, or a refused write loses it
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._adopt_from_disk(staged, foreign)
            for key in retire:          # AFTER the adoption, or it comes back
                staged.pop(str(key), None)
                foreign.pop(str(key), None)
            for key in keys:            # a key just SET stops being foreign
                foreign.pop(key, None)
            hostos.snapshot_before_write(self.path)
            hostos.write_json_atomic(
                self.path,
                self._document({**foreign, **staged}),
                indent=1, sort_keys=True)
            if created:
                hostos.seed_restore_floor(self.path)  # a write-once file has no .bak
            self._remember_disk_state()
            self.state = READ           # written is READ, never still FRESH
        except OSError as exc:
            cause, why = hostos.why_failed(exc, self.path)
            debug.event(spec.category, "could not save %s" % spec.filename,
                        path=self.path, error=str(exc), cause=cause)
            if spec.denied_alert:
                debug.alert("%s\n\nThis happened because %s"
                            % (spec.denied_alert, why),
                            key="%s-denied-%s" % (spec.filename, cause))
            return Written(False, REASON_DENIED, why, keys)
        self._table = staged            # only NOW does the cache move
        self._foreign = foreign
        self._orphans = {}              # the file no longer holds them
        return Written(True, REASON_NONE, "", keys)

    def _remember_disk_state(self) -> None:
        self._disk_state = hostos.disk_state(self.path)

    def _adopt_from_disk(self, staged: dict, foreign: dict) -> None:
        """Fold in keys another session added since this one read; ADDS only, and a same-session delete can come back. ▸p/store-commit-order"""
        current = hostos.disk_state(self.path)
        if current is None or self._disk_state == current:
            return                          # nothing moved underneath us
        try:
            with open(self.path, "rb") as handle:
                loaded = json.loads(handle.read().decode("utf-8-sig"))
        except (OSError, ValueError):
            return
        if not isinstance(loaded, dict):
            return
        peer = self._table_in(loaded)
        if not isinstance(peer, dict):
            return
        adopted = 0
        for key, value in peer.items():
            stored = restored_key(self.spec, str(key))
            kept = self.spec.normalise(value)
            if not self._rejected(kept):
                if stored not in staged:
                    staged[stored] = kept
                    adopted += 1
                else:                   # both hold it: ours, unless a rule says otherwise
                    folded = _fold(
                        rule_for(self.spec.merge_rules, (stored,))
                        or MERGE_MINE,
                        staged[stored], kept,
                        self.spec.merge_rules, (stored,))
                    if folded is not None:
                        staged[stored] = folded
                        adopted += 1
            elif (value and stored not in staged
                  and stored not in foreign):
                foreign[stored] = value  # theirs, or OUR write erases it
                adopted += 1
        if adopted:
            debug.event(self.spec.category,
                        "adopted entries another session wrote",
                        path=self.path, adopted=adopted,
                        store=self.spec.filename)


RULE_SEP = "/"                      # separates the levels of a nested rule
RULE_ANY = "*"                      # stands for any one key


def rule_for(rules: dict, path: tuple) -> str:
    """The rule declared for this path into the document, "" if none; MOST SPECIFIC wins. ▸p/document-not-table"""
    if not rules:
        return ""
    best, fewest = "", None
    for pattern, rule in rules.items():
        parts = str(pattern).split(RULE_SEP)
        if len(parts) != len(path):
            continue
        if not all(part in (RULE_ANY, actual)
                   for part, actual in zip(parts, path)):
            continue
        stars = parts.count(RULE_ANY)
        if fewest is None or stars < fewest:
            best, fewest = rule, stars
    return best


def _rules_below(rules: dict, path: tuple) -> bool:
    """Does any rule name something DEEPER than this path? The walk must know before it gets there."""
    if not rules:
        return False
    for pattern in rules:
        parts = str(pattern).split(RULE_SEP)
        if len(parts) <= len(path):
            continue
        if all(part in (RULE_ANY, actual)
               for part, actual in zip(parts, path)):
            return True
    return False


def _shallow_fields(ours, theirs):
    """The DEFAULT for a key both sides hold that no rule names: one level of field union, then ours."""
    if not (isinstance(ours, dict) and isinstance(theirs, dict)):
        return None                         # ours, as the shallow rule
    missing = {field: value for field, value in theirs.items()
               if field not in ours}
    if not missing:
        return None
    return {**ours, **missing}              # REBOUND - the record is the live cache's


def _fold(rule: str, ours, theirs, rules: dict = None, path: tuple = ()):
    """OURS with the peer's additions folded in, or None when there were none; ADDS ONLY. ▸p/document-not-table"""
    if rule == MERGE_COMBINE:
        if not (isinstance(ours, list) and isinstance(theirs, list)):
            return None
        extra = [value for value in theirs if value not in ours]
        return (ours + extra) if extra else None
    if rule == MERGE_FIELDS:
        if not (isinstance(ours, dict) and isinstance(theirs, dict)):
            return None
        merged = dict(ours)
        changed = False
        for key, value in theirs.items():
            if key not in merged:
                merged[key] = value
                changed = True
                continue
            below = path + (str(key),)
            named = rule_for(rules, below)
            if not named and _rules_below(rules, below):
                named = MERGE_FIELDS    # a rule names a level below: keep walking
            folded = (_fold(named, merged[key], value, rules, below)
                      if named else _shallow_fields(merged[key], value))
            if folded is not None:
                merged[key] = folded
                changed = True
        return merged if changed else None
    return None


def _boundary(prefix: str) -> str:
    """A folder prefix that cannot match a SIBLING - without it, `/a/tex` captures `/a/textures`."""
    return prefix.rstrip("/") + "/"


def _bare_path(spec: Spec, key: str) -> str:
    """The PATH inside a key, keyspace prefix taken off - ONE answer for both halves of the lifecycle."""
    if spec.path_prefix and key.startswith(spec.path_prefix):
        return key[len(spec.path_prefix):]
    return key


def storage_key(spec: Spec, key, user: str = "") -> str:
    """The spelling a key is STORED under - variable-relative, and `<uid>|` prefixed on a tagged store."""
    key = str(key)
    if spec.keyspace == KEY_PATH:
        key = hostos.storage_path_key(key)
    elif (spec.keyspace == KEY_MIXED and spec.path_prefix
            and key.startswith(spec.path_prefix)):
        key = spec.path_prefix + hostos.storage_path_key(
            key[len(spec.path_prefix):])
    if spec.user_tagged and user:
        key = user + USER_SEP + key
    return key


def restored_key(spec: Spec, key: str) -> str:
    """A key read FROM DISK, normalised without disturbing its tag - normalise the path half only."""
    owner, bare = untagged_key(spec, key)
    if owner:
        return owner + USER_SEP + storage_key(spec, bare)
    return storage_key(spec, key)


def untagged_key(spec: Spec, key: str) -> tuple:
    """`(uid, key)` for a stored key, `("", key)` when untagged - split on the FIRST separator only."""
    if not spec.user_tagged:
        return ("", key)
    tag, sep, rest = str(key).partition(USER_SEP)
    return (tag, rest) if sep else ("", key)


def _under(spec: Spec, key: str, prefix: str) -> bool:
    """Is this key the location itself, or something inside it? The prefix converts to STORAGE spelling first."""
    if not spec.is_path_key(key):
        return False
    prefix = hostos.storage_path_key(prefix)
    bare = _bare_path(spec, key)
    return bare in (prefix, prefix.rstrip("/")) or bare.startswith(
        _boundary(prefix))


def relocate(preferences, old: str, new: str) -> dict:
    """A location moved: rewrite every path-shaped key in every store, one guarded write each."""
    results = {}
    if not old or not new or old == new:
        return results
    old, new = hostos.storage_path_key(old), hostos.storage_path_key(new)
    old_edge, new_edge = _boundary(old), _boundary(new)
    for spec in stores():
        if spec.keyspace == KEY_ID:
            continue                # an asset id does not move
        store = open_store(spec, preferences)
        moves = {}
        for key in store.all():
            if not spec.is_path_key(key):
                continue
            bare = _bare_path(spec, key)
            if bare.startswith(old_edge):
                moved = new_edge + bare[len(old_edge):]
            elif bare in (old, old.rstrip("/")):
                moved = new             # the location's OWN key; `new` verbatim
            else:
                continue
            moves[key] = (spec.path_prefix or "") + moved
        if moves:
            results[spec.filename] = store.rekey(moves)
    return results


def retire_prefix(preferences, prefix: str) -> dict:
    """A location is gone: drop every key under it, in the stores whose `survives_forget` says so. ▸p/store-declarations"""
    results = {}
    for spec in stores():
        if spec.survives_forget or spec.keyspace == KEY_ID:
            continue
        store = open_store(spec, preferences)
        if spec.user_tagged:            # EVERY user's - a removal is a shared act
            doomed = [stored for stored in store.everyones()
                      if _under(spec, untagged_key(spec, stored)[1],
                                prefix)]
            if doomed:
                results[spec.filename] = store.retire_stored(doomed)
            continue
        doomed = [k for k in store.all() if _under(spec, k, prefix)]
        if doomed:
            results[spec.filename] = store.retire(doomed)
    return results




def release(preferences=None) -> None:
    """Drop the cached tables - a library switch, or a test. ▸p/one-file-one-table"""
    if preferences is None:
        _open.clear()
        return
    root = hostos.canonical_path_key(str(preferences.dir))  # BOTH sides through it
    for key in [k for k in _open
                if hostos.canonical_path_key(os.path.dirname(k[1])) == root]:
        _open.pop(key, None)


def reset() -> None:
    """Tests only: forget every open table AND every registration."""
    _open.clear()
