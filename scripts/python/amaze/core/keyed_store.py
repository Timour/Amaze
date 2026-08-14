"""The KEYED STORE ENGINE - one guarded JSON side-table, keyed by a
stable identity, for every store that keeps per-key choices beside the
thing they belong to.

Three stores were the same store and each implemented the guard set
separately: `notes.json` (a comment page per asset), `icons.json` (a
chosen tile icon per asset or path), and the per-location preference
dicts in settings.json. `notes.py`'s own docstring says it copied its
guards from `icons.json` - and it did not copy them all, because
`icons.json` never had them all. That is the shape this engine exists
to end.

FOUR STORES NOW, ALL OF THEM REAL FILES IN THE LIBRARY (2026-08-05).
The registered locations and the File favourites used to be presented
through this protocol while their bytes stayed in settings.json, so
they joined the ENUMERATION and the LIFECYCLE but never the guards.
They are `locations.json` and `favourites.json`, and the adapter class
that faked them is gone: a File row's icon, comment, favourite and the
location listing it now answer to the same scope, which is what stopped
an icon vanishing when you switched library. settings.json keeps a copy
of both, written from here, for the one job the library cannot do - be
readable when the library is not (`core/locations.py`).

**REGISTRATION IS HOW A STORE COMES INTO EXISTENCE.** A store is DATA -
a filename, a payload key, a keyspace, the words the user reads, and
one normaliser - handed to :func:`register`. There is no way to have a
store and not be in :func:`stores`, which is what lets Repair, restore
and the library audit enumerate the side tables instead of each keeping
a hand-written list that can be one short. Both of those lists were one
short, and neither went red when it happened.

**ABSENCE IS A VERDICT THE ENGINE RESOLVES, NEVER A VALUE A CALLER
RECEIVES.** Opening a store answers READ, FRESH or BLIND. Only the
first two may be written. There is no `if os.path.exists(path):` in any
store, so there is no missing `else` for a store to be missing - which
is exactly what `icons.json` was missing (measured on the real library
2026-08-03: `icons.json` is absent and has no `.bak` tier of any kind,
so the very next icon picked would have been written as the whole
file).

**A READ HANDS OUT A COPY; A WRITE STAGES AND COMMITS ONLY ON SUCCESS.**
The cache is a projection of the last successful write, never a
scratchpad a caller mutates in place. `notes.set_note` used to mutate
the live table and then attempt the write, so a REFUSED write still lit
the tile's comment badge for a note that was never saved - and a later
pass read that phantom back and wrote it twice.

**AN ENGINE VERIFIES ITS OWN OUTPUT.** The same rule the Conversion
Engine ships (`core/conversion.py`) and the Material Engine has always
had: `set`/`rekey`/`retire` answer with a :class:`Written`, which
carries a REASON and a sentence fit for a dialog - never a bare False
that leaves the caller guessing whether the folder was read-only or the
file would not parse. A measured case: a refused icon write returned
False and the panel told the user to check the library folder was
writable, when the folder was fine and the file simply would not parse.
"""

from __future__ import annotations

import copy
import json
import os

from amaze.core import database, debug
from amaze.helpers import hostos


# -- keyspaces --------------------------------------------------------
#
# What a key IS, which decides who may rewrite it. A folder that moves
# rewrites path keys; an asset id does not move when a folder does.

KEY_ID = "id"
KEY_PATH = "path"
#: Both, in one file. `notes.json` holds `material:<id>` beside
#: `file:<path>` and the on-disk format cannot change (§ the contracts
#: below), so a mixed store declares the PREFIX that marks a path key
#: and the fan-out touches only those.
KEY_MIXED = "mixed"

#: What separates a user tag from the key it tags: `<uid>|<key>`.
#: Split on the FIRST one only - a uuid4 hex cannot contain it, a path
#: can (ROADMAP line 21).
USER_SEP = "|"


# -- what opening a store answered ------------------------------------

#: parsed from a file that is there
READ = "read"
#: absent, and nothing anywhere says it was ever here - a new library
FRESH = "fresh"
#: absent-but-proven, or present-but-unparseable. Reads answer empty,
#: writes are refused for the session.
BLIND = "blind"


# -- why a write did not land -----------------------------------------

REASON_NONE = ""                    # it landed
REASON_UNCHANGED = "unchanged"      # nothing to do; `ok` is True
REASON_LATCHED = "latched"          # the file is there and will not parse
REASON_ABSENT = "absent-but-known"  # it is gone and something says it was here
REASON_DENIED = "denied"            # OSError - read-only, full, unreachable
REASON_NO_USER = "no-user"          # tagged store, nobody picked on this machine


class Written:
    """What a write answers with - an outcome AND a reason.

    Truthy when the store on disk now says what the caller asked for,
    which includes REASON_UNCHANGED: asking for what is already there
    is not a failure.
    """

    __slots__ = ("ok", "reason", "sentence", "keys")

    def __init__(self, ok: bool, reason: str = REASON_NONE,
                 sentence: str = "", keys=()) -> None:
        self.ok = ok
        self.reason = reason
        #: a complete sentence, fit to show the user as-is
        self.sentence = sentence
        #: which keys this write was about
        self.keys = tuple(keys)

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:                                # pragma: no cover
        return "<Written %s%s>" % (
            "ok" if self.ok else "refused",
            "" if not self.reason else ": " + self.reason)


#: HOW A PEER'S VALUE FOR A KEY WE ALREADY HOLD IS FOLDED IN. Ours
#: wins is right for independent records and wrong for a document,
#: whose keys are different KINDS of thing (ROADMAP line 26). Every
#: rule only ADDS, and `MINE` is both the default and what every store
#: does today.
MERGE_MINE = "mine"
#: A list two panes each added to: ours, then theirs, no duplicates.
MERGE_COMBINE = "combine"
#: A map of records, merged field by field inside a record both hold.
#: A record only they have arrives whole; a value either side spells as
#: something other than a map takes ours.
MERGE_FIELDS = "fields"


class Spec:
    """One store, as DATA. Everything the engine needs to guard a file
    it has never heard of."""

    __slots__ = ("filename", "payload", "keyspace", "label", "noun",
                 "normalise", "path_prefix", "unreadable_alert",
                 "refused_sentence", "alert_key", "denied_alert",
                 "category", "in_library", "survives_forget",
                 "user_tagged", "merge_rules")

    def __init__(self, filename, payload, keyspace, label, noun,
                 normalise, path_prefix="", unreadable_alert="",
                 refused_sentence="", alert_key="", denied_alert="",
                 category="store", in_library=True,
                 survives_forget=True, user_tagged=False,
                 merge_rules=None) -> None:
        self.filename = filename
        self.payload = payload
        self.keyspace = keyspace
        #: what Repair and the restore picker call it on screen
        self.label = label
        #: singular, for counting: "40 comments"
        self.noun = noun
        self.normalise = normalise
        #: KEY_MIXED only: the prefix that marks a path-shaped key
        self.path_prefix = path_prefix
        self.unreadable_alert = unreadable_alert
        self.refused_sentence = refused_sentence
        self.alert_key = alert_key or (filename + "-unreadable")
        #: WHAT TO SAY WHEN A WRITE IS DENIED - the store's own half of
        #: it: what could not be saved and what is therefore unchanged.
        #: The engine appends WHY, from `hostos.why_failed`.
        #:
        #: BLANK MEANS SAY NOTHING, AND THAT IS A DECISION, NOT A
        #: DEFAULT. Speaking is only worth it when the failure is
        #: INVISIBLE. A comment stays on screen in the editor after a
        #: refused save, so nothing tells the user but this. A location
        #: or a favourite is DERIVED from this store and the cache does
        #: not move on failure, so the folder simply never appears and
        #: the star never lights - the gesture visibly does nothing, so
        #: an alert would announce an outcome already on screen
        #: (practice.md ▸ Dialogs are a bill you send the user).
        self.denied_alert = denied_alert
        #: debug-log category
        self.category = category
        #: Is this a FILE in the library directory? Repair, the restore
        #: picker and the library audit enumerate only those. Every
        #: declared store answers True since 2026-08-05, when the
        #: locations and the File favourites stopped being views onto
        #: settings.json; the flag stays because "which files does a
        #: library contain" is a question this registry must keep
        #: answering in one place, and a future store that is not one
        #: would otherwise be discovered by Repair reporting it missing.
        self.in_library = in_library
        #: Are this store's keys TAGGED with the user who owns them?
        #: One flag, so any future store opts in the same way. The tag
        #: is a UID, so a rename relinks a label and moves no key.
        self.user_tagged = user_tagged
        #: DOES THIS SURVIVE A LOCATION BEING REMOVED? A PRODUCT
        #: decision, stated out loud in one readable place - not
        #: inferred from which lines a removal method happens to
        #: contain, which is exactly how the colour and the Show All
        #: Files override came to be forgotten when they were added
        #: after the hook was written.
        #:

        #: CALL on 2026-08-03: "clear everything - favourites, comments
        #: and icons". Re-adding the folder gives a clean slate
        #: (ui-text.md ▸ File (folders) ▸ Remove). The field stays
        #: although all four path stores now answer the same way - it
        #: is a product decision that has already been reversed once,
        #: and a keyspace test could not carry it even when they
        #: differed, because they are all path-keyed.
        self.survives_forget = survives_forget
        #: key -> MERGE_*, for the keys where ours-wins is the wrong
        #: answer. Copied, so a caller's dict cannot change the rules
        #: of a live store afterwards.
        self.merge_rules = dict(merge_rules or {})

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


#: Every registered store, in registration order. Repair, the restore
#: picker and tools/library-audit.py read THIS - the two hand-written
#: copies of it had already drifted apart by one entry.
#
# Carried across module reloads for the same reason the thumbnail
# engine carries its parked threads: panel.py reloads this package on
# every panel open, and a plain `= {}` would empty the registry while
# the stores that filled it are not re-imported.
_registry: dict = globals().get("_registry", {})


def register(filename: str, payload: str, keyspace: str, label: str,
             noun: str, normalise=None, path_prefix: str = "",
             unreadable_alert: str = "", refused_sentence: str = "",
             alert_key: str = "", denied_alert: str = "",
             category: str = "store", in_library: bool = True,
             survives_forget: bool = True,
             user_tagged: bool = False,
             merge_rules: dict = None) -> Spec:
    """Declare a store. Idempotent per filename, so a module reload
    re-registers rather than duplicating."""
    if keyspace not in (KEY_ID, KEY_PATH, KEY_MIXED):
        raise ValueError("unknown keyspace %r" % (keyspace,))
    if keyspace == KEY_MIXED and not path_prefix:
        raise ValueError(
            "a mixed-keyspace store must say which prefix marks a path "
            "key, or a folder move cannot tell them apart")
    # BY NAME, not by position. Adding `denied_alert` to the middle of
    # Spec's signature silently handed `category` to it while this call
    # still read correctly - fourteen positional arguments kept in step
    # by hand is the shape overview.md's *A VALUE CARRIES ITS OWN NAME*
    # is about, and nothing raises when they drift.
    spec = Spec(filename=filename, payload=payload, keyspace=keyspace,
                label=label, noun=noun, normalise=normalise,
                path_prefix=path_prefix,
                unreadable_alert=unreadable_alert,
                refused_sentence=refused_sentence, alert_key=alert_key,
                denied_alert=denied_alert, category=category,
                in_library=in_library, survives_forget=survives_forget,
                user_tagged=user_tagged, merge_rules=merge_rules)
    _registry[filename] = spec
    return spec


def bind(filename: str, normalise) -> Spec:
    """An adapter attaches the one thing the engine cannot know: what a
    well-formed VALUE of this store is.

    The split is deliberate. WHICH keyed files a library contains, what
    they are called and what they hold is ENGINE knowledge, declared
    below with no import beyond the standard library - so Repair, the
    restore picker and `tools/library-audit.py` can enumerate them on a
    machine where Houdini will not start. The normaliser lives with the
    store, because it is the store's shape, and `tile_icons`' pulls in
    Qt. A declared store that nothing has bound can be SURVEYED but not
    OPENED, which is exactly the right answer for a repair tool.
    """
    spec = _registry.get(filename)
    if spec is None:
        raise KeyError("%s is not a declared store" % (filename,))
    spec.normalise = normalise
    return spec


def stores() -> tuple:
    """Every declared store. THE enumeration for anything that may
    import this package - `repair.py` and `helpers/restore.py`.

    Those two each kept their own copy of this list and had already
    drifted: the audit grew the two side tables on 2026-08-02 and
    Repair's copy stayed narrow, silently, while the alert the user
    reads sends them to Repair by name for exactly those files.

    `tools/library-audit.py` IS NOT A CONSUMER AND CANNOT BE. It is
    pure stdlib on purpose, so it runs where Houdini will not start,
    which means it cannot see this registry at any price. It keeps its
    own list, and a new store must be added there too - the audit is
    the loud one, since `--strict` calls an undeclared file UNKNOWN and
    exits 1. Said here because this docstring used to name all three,
    which reads as a consolidation that covered a file it never did.
    """
    return tuple(_registry.values())


def store_for(filename: str):
    return _registry.get(filename)


def filenames() -> tuple:
    """Only the stores that are FILES IN THE LIBRARY - what Repair
    surveys and what the audit expects to find on disk."""
    return tuple(name for name, spec in _registry.items() if spec.in_library)


# -- THE DECLARATIONS -------------------------------------------------
#
# Here, not in the adapter modules, so that enumerating the side tables
# costs no import of Qt and no import of Houdini. Each adapter binds
# its normaliser when it loads.

register(
    filename="notes.json",
    payload="notes",
    keyspace=KEY_MIXED,
    # `material:<id>` beside `file:<path>` in ONE file. The on-disk
    # format cannot change, so the fan-out is told which keys are
    # path-shaped rather than being told the whole store is.
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
    # SPEAKS, because the failure is invisible. A refused save leaves
    # the text sitting in the editor looking saved; nothing on screen
    # changes, and the user finds out next session when it is gone.
    denied_alert=(
        "Your comment could not be saved.\n\n"
        "Nothing already saved has been lost - only this change. It is "
        "still on screen, so you can copy it somewhere safe before "
        "closing Houdini."),

    # icons". Removing a location forgets everything about it. Only the
    # keys UNDER that location go; an asset's comment is untouched,
    # which is what the mixed keyspace is for.
    survives_forget=False,
)

#: One record per registered location, keyed by its path: whether it is
#: registered at all, plus the colour, custom name, recursion and Show
#: All Files override. Those four were separate tables that every caller
#: had to remember to visit - so "remove a location" and "relocate a
#: location" were two independently maintained lists of the same four
#: names, and they already disagreed: relocate walked a three-name tuple
#: plus a list, remove open-coded two of the four, and the two it forgot
#: are exactly the two that were added AFTER the hook was written.
#:
#: IN THE LIBRARY since 2026-08-05, reversing the note that used to sit
#: here. The claim was that lifting it "would break cross-machine grace
#: to gain nothing", and the gain is what that missed: a File row's
#: facts answered to two different scopes, so the icon and the comment
#: on `/…/brick.jpg` lived with the library while the location that
#: listed it lived with the machine. Switch library and the file was
#: still registered, still on disk, still listed - and its icon was
#: gone. Only the POINTER to the library cannot live inside it
#: (`directory` stays in settings.json); the content facts can, and
#: gain the guard set these two have never had - unreadable latch,
#: adopt-on-write, atomic write, snapshot tier.
LOCATIONS = "locations.json"

#: EVERY section's favourites since 2026-08-13, keyed by FILE path for
#: File rows and by bare asset id for the asset and gradient sections -
#: the icons.json scheme. They follow the library, like the icons and
#: the comments on the same row, which is what makes two machines agree
#: about them - and the user tag below is what made that PRIVATE again:
#: the 2026-08-05 cost ("in a shared library, favourites are not
#: private") was retired by keying every star to its owner.
FAVOURITES = "favourites.json"

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
    # NO denied_alert, DELIBERATELY. The sidebar is DERIVED from this
    # store (locations.registered_paths) and the cache does not move on
    # a failed write, so a folder that could not be registered simply
    # never appears. The gesture visibly does nothing, which IS the
    # report - saying it as well would announce what the user just
    # watched happen.
    # The one store a location removal takes with it.
    survives_forget=False,
    # YOUR SIDEBAR IS NOT MINE (ROADMAP line 22 stage C): each user of
    # a shared library registers their own folders, keyed `<uid>|<path>`
    # like the favourites below. Rows from before the tag adopt into
    # whoever opens the library - `locations._adopt_untagged`, through
    # `adopt_orphans` - and a removal still sweeps every user's keys
    # under the folder, because a removal is a shared act.
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
    # NO denied_alert, for the same reason as the locations above: the
    # star is painted from this store, so a star that could not be
    # written does not light.
    survives_forget=False,
    # MINE ARE NOT YOURS. Keys carry the owner's UID, so one library
    # holds everyone's stars without anyone seeing anyone else's, and a
    # rename relabels a person without moving a single key
    # (ROADMAP line 21).
    user_tagged=True,
)

register(
    filename="users.json",
    payload="users",
    # A UID. The NAME is a field on the record, never the key - so a
    # rename relinks one label and moves nothing that is tagged with
    # the UID. Same shape as an asset: uuid4 in the key, name beside it.
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
    # NO denied_alert, for the same reason as the locations and the
    # favourites below: the name shown in Preferences is READ BACK from
    # this store, so a refused rename visibly snaps back and a refused
    # mint leaves the box empty. The gesture doing nothing IS the
    # report.
    #
    # A user OUTLIVES a location being removed: a person is not a
    # property of a folder they happened to register.
    survives_forget=True,
)

register(
    filename="icons.json",
    payload="icons",
    # Bare absolute paths for File rows and bare asset ids for the
    # asset sections - no section prefix, unlike notes.json. Two
    # schemes in two files, and neither may be unified onto the other:
    # both are contracts with entries already on disk.
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
        # The user just picked an icon, so the sentence is about THEIR
        # choice, not about a file. "session" is banned and the path is
        # one they have never opened, so both stay out of it - the
        # alert above already sent them to the Repair tool once, and
        # repeating that on every pick would spend the alarm budget on
        # something they have already been told.
        "the tile icon file could not be read earlier this run, so your "
        "icon choice was not saved - writing now would replace every "
        "icon already in it."),
    # SPEAKS, for the same reason notes do: the tile keeps showing the
    # icon that was picked, so nothing on screen says the choice did
    # not survive.
    denied_alert=(
        "The icon you picked could not be saved.\n\n"
        "Nothing already saved has been lost - only this choice. The "
        "tile goes back to the icon it had next time Amaze opens."),
    survives_forget=False,
)

#: The library's SHARED settings - one record per preference key, no
#: user tag: what the library looks like and how it renders is ONE
#: answer for everyone who opens it (ROADMAP line 22). The per-USER
#: half of that line rides the tagged stores above; the per-machine
#: half stays in settings.json, which keeps the bootstrap keys - the
#: pointer to the library cannot live inside it.
#:
#: NOTHING READS THIS YET (practice.md ▸ LAND IT WITH THE SWITCH
#: OFF): the flip commits move the keys onto it one group per commit,
#: and until a group flips its keys keep living in settings.json.
PREFS = "prefs.json"

register(
    filename=PREFS,
    payload="prefs",
    # A preference NAME, never a path: nothing here is rewritten by a
    # folder move.
    keyspace=KEY_ID,
    label="Shared settings",
    noun="setting",
    category="prefs",
    # NOT "prefs-unreadable": persistence.py already raises that key
    # for an unreadable settings.json, and alert keys are once per
    # session - sharing one would let whichever file breaks first
    # swallow the other's report.
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
    # SPEAKS, for the same reason notes do: a changed setting keeps
    # applying for the session (the panel works off memory), so nothing
    # on screen says the change did not reach disk - the user finds out
    # next launch, when it is gone.
    denied_alert=(
        "Your setting could not be saved.\n\n"
        "Nothing already saved has been lost - only this change. It "
        "still applies for now, and goes back to what it was next time "
        "Amaze opens."),
    # A setting is not a property of a folder someone registered.
    survives_forget=True,
)


# -- the guarded table ------------------------------------------------


#: (spec.filename, resolved path) -> Store. A library switch drops the
#: entries for that library through release().
_open: dict = {}


def _root_for(spec: Spec, preferences) -> str:
    """WHICH DIRECTORY this store's file lives in.

    The library stores live with the library. A machine-local one lives
    beside settings.json, because the file that holds the POINTER to a
    library is the one file that cannot live inside it - `filenames()`
    already excludes it from what Repair and the audit survey, and this
    is the other half of that answer.

    REFUSES rather than defaulting. A Prefs that cannot say where its
    configuration lives used to mean "the library" by omission, and for
    a machine-local store that writes one machine's own settings into a
    synced folder every other machine reads. The one direction this
    must never fail in is quietly.
    """
    if spec.in_library:
        return str(preferences.dir)
    root = str(getattr(preferences, "path", "") or "")
    if not root:
        raise ValueError(
            "%s is machine-local and this Prefs cannot say where the "
            "configuration lives - refusing to fall back to the "
            "library" % spec.filename)
    return root


def open_store(spec: Spec, preferences) -> "Store":
    """The store for this library, read once and cached.

    Named `open_store` rather than `open` deliberately: this module is
    read by people, and shadowing the builtin inside it would make
    every plain file read here look like a store lookup.
    """
    path = os.path.join(_root_for(spec, preferences), spec.filename)
    handle = _open.get((spec.filename, path))
    if handle is None:
        handle = Store(spec, path, preferences)
        _open[(spec.filename, path)] = handle
    else:
        # The cache is keyed by FILE, and the user can change under it
        # (the Preferences picker). Re-point rather than re-read: the
        # bytes are the same, only whose rows they are has moved.
        handle.preferences = preferences
    return handle


class Store:
    """One library's copy of one registered store."""

    def __init__(self, spec: Spec, path: str, preferences=None) -> None:
        self.spec = spec
        self.path = path
        #: Held ONLY to resolve the user tag. Read straight off
        #: `library_user` and never through `users.current()`, which
        #: mints - minting from inside a favourites read would write a
        #: user into the library as a side effect of painting a star.
        self.preferences = preferences
        self._table: dict = {}
        #: Entries the normaliser REJECTED, kept verbatim - usually a
        #: NEWER build's data (an icon name this build lacks, a shape
        #: from next year). Invisible to readers, written back by every
        #: commit: an older build must not erase what a newer one wrote.
        self._foreign: dict = {}
        #: A tagged store's rows from BEFORE it had owners, keyed bare.
        #: Dropped from every read surface and never written back - the
        #: first commit retires them from the file - but kept aside so
        #: a store whose product decision is ADOPTION can file them
        #: under the current user first (`adopt_orphans`). Favourites
        #: drop theirs for good: nothing calls the door there.
        self._orphans: dict = {}
        self._disk_state = None
        self.state = FRESH
        self.trace = ""
        self._load()

    # -- opening ------------------------------------------------------

    def _load(self) -> None:
        spec = self.spec
        try:
            if os.path.exists(self.path):
                with open(self.path, "rb") as handle:
                    raw = handle.read()
                # utf-8-sig, not utf-8: a BOM is what a Windows editor
                # leaves behind, and it makes json.load raise - which
                # this engine would then read as a damaged file and
                # latch the whole store read-only for the session.
                loaded = json.loads(raw.decode("utf-8-sig"))
                wrong = database.wrong_table_shape(loaded, spec.payload)
                if wrong:
                    raise ValueError(wrong)
                if spec.payload not in loaded:
                    # THE PAYLOAD KEY MUST BE PRESENT on a file that
                    # exists. wrong_table_shape reads a MISSING key as
                    # a valid empty table, so icons.json copied over
                    # notes.json parses, reads as zero notes, and the
                    # next note written replaces the file. Every file
                    # this engine writes carries its key, even when the
                    # table is empty (measured on the real library:
                    # notes.json is `{"notes": {...}}` with 40 entries),
                    # so requiring it costs nothing and closes that.
                    raise ValueError(
                        "%s holds no %r - this is not the %s file"
                        % (spec.filename, spec.payload, spec.label))
                table = {}
                orphans = 0
                for key, value in loaded[spec.payload].items():
                    # Every legacy spelling is absorbed HERE, one
                    # conversion on the way in, no migration event: the
                    # real favourites held one file three ways. On a
                    # collision the FIRST entry wins whole - no clever
                    # merge - and the drop is logged by both spellings.
                    stored = restored_key(spec, str(key))
                    if spec.user_tagged and not untagged_key(spec, stored)[0]:
                        # A ROW FROM BEFORE THIS STORE HAD OWNERS.
                        # Dropped from every read surface: nothing on it
                        # says whose it was, and giving it to whoever
                        # opens the library first hands one person
                        # everybody's entries. Deliberately NOT held in
                        # `_foreign` - that is for a newer build's
                        # values, which are written back, and this one
                        # must not ride back into the file. It waits in
                        # `_orphans` instead, so a store that decides
                        # its pre-tag rows are ADOPTED can file them
                        # under the current user before the first
                        # commit retires them from disk (ROADMAP line
                        # 22 stage C - the locations; favourites drop
                        # theirs for good and never call the door).
                        kept = spec.normalise(value)
                        if kept and stored not in self._orphans:
                            self._orphans[stored] = kept
                        orphans += 1
                        continue
                    kept = spec.normalise(value)
                    if not kept:
                        # A truthy value the normaliser cannot read is
                        # FOREIGN, not junk: held aside verbatim so the
                        # rewrite keeps it (see _foreign). A falsy one
                        # is the delete contract and stays dropped.
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
                # ABSENT IS ONLY "NEW" WHEN NOTHING SAYS IT WAS HERE. A
                # sync placeholder still arriving, a conflict rename or
                # a partial restore all look like an empty library for
                # one instant, and writing one key into that instant is
                # how a whole table becomes a one-key file.
                #
                # The traces are the ones THIS ENGINE writes - the .bak
                # tier and the .unreadable copy - so there is no caller
                # tuple to get wrong. notes.py passed five backup names
                # that existed_before already checks unconditionally: a
                # tuple that looks like evidence and adds none.
                self.trace = hostos.existed_before(self.path)
                if self.trace:
                    self.state = BLIND
                    self._refuse_and_alert(
                        "%s is missing but %s says it was here"
                        % (spec.filename, self.trace))
                else:
                    self.state = FRESH
        except (OSError, ValueError) as exc:
            # The file EXISTS and would not parse. An empty table is
            # indistinguishable from "nothing stored yet", and the next
            # save would write that emptiness over everything.
            self.state = BLIND
            self._table = {}
            self._orphans = {}
            # Clause two of refuse-over-overwrite: keep the file beside
            # itself, once. The latch lasts one session; the copy is
            # one of the traces existed_before reads.
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

    # -- reading ------------------------------------------------------

    def user_tag(self) -> str:
        """The UID this store's keys are tagged with, "" when untagged
        or when nobody has been picked on this machine.

        Straight off the preference. A blank one is not a shared
        bucket - `_key` refuses to build a key at all, so a machine
        with no user reads and writes nothing rather than filing
        everyone's entries together.
        """
        if not self.spec.user_tagged:
            return ""
        try:
            return str(self.preferences.library_user or "")
        except AttributeError:
            return ""

    def _key(self, key) -> str:
        """The stored spelling, tag included. Answers "" when this store
        is tagged and there is no user - no key, so no read and no
        write."""
        if self.spec.user_tagged:
            tag = self.user_tag()
            if not tag:
                return ""
            return storage_key(self.spec, key, tag)
        return storage_key(self.spec, key)

    def has(self, key) -> bool:
        """Does this key carry anything? THE PAINT PATH.

        Called per tile per repaint from three models' data(). A
        membership test and nothing else - no copy, no stat, no I/O.
        """
        stored = self._key(key)
        return bool(stored) and stored in self._table

    def get(self, key) -> dict:
        """One value, as a COPY. {} when there is none.

        A copy because a caller holding the live value can mutate the
        cache without writing, which is how a comment badge lit for a
        note that was refused.
        """
        stored = self._key(key)
        value = self._table.get(stored) if stored else None
        return copy.deepcopy(value) if value else {}

    def all(self) -> dict:
        """THIS USER's entries, as a COPY, keyed without the tag.

        Scoped, because every caller of this means *the things that are
        mine* - the favourites list a section paints, the keys a sweep
        walks. An untagged store is unaffected. `everyones()` is the
        unscoped read, for repair and migration, which are the only two
        jobs that legitimately see across people.
        """
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
        """The whole table as stored, tags included - repair, migration
        and the audit, never the paint path."""
        return copy.deepcopy(self._table)

    def orphaned(self) -> dict:
        """The rows from before this store had owners, keyed bare, as a
        COPY - what an adopting store's migration reads. Empty on an
        untagged store, and empty again after any commit: the write
        that did not adopt them is the write that retired them."""
        return copy.deepcopy(self._orphans)

    def orphan_count(self) -> int:
        """The cheap half of `orphaned`, for the per-paint guard."""
        return len(self._orphans)

    def count(self) -> int:
        return len(self._table)

    @property
    def writable(self) -> bool:
        return self.state in (READ, FRESH)

    # -- writing ------------------------------------------------------

    def set(self, key, value) -> Written:
        """Store one key; a falsy value REMOVES it - the contract both
        stores already have (an empty note deletes the note)."""
        key = self._key(key)
        if not key:
            # Tagged store, nobody picked. Refusing beats filing the
            # entry under a blank tag, which is an ABSENT user rather
            # than a shared one.
            debug.event(self.spec.category, "write skipped - no user",
                        store=self.spec.filename)
            return Written(False, REASON_NO_USER)
        value = self.spec.normalise(value) if value else {}
        if value:
            if self._table.get(key) == value:
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
        """Store many keys - ONE write for the whole set.

        A migration that calls `set` per key writes the file once per
        key and rotates a snapshot each time: fourteen locations would
        push the restore tier's real history out with fourteen copies of
        the same minute. It is also the only shape a migration can be
        COMPARED in - the end state is one write that either landed
        whole or did not land at all.
        """
        staged = dict(self._table)
        touched = []
        # DOING NOTHING CANNOT FAIL, so a refusal is only asked for once
        # there is something to write. Otherwise a store that cannot key
        # anything answers "refused" to a caller that asked for nothing,
        # and a caller checking that answer reads a failure into an
        # empty list.
        if not (values or {}):
            return Written(True, REASON_UNCHANGED)
        if self.spec.user_tagged and not self.user_tag():
            return Written(False, REASON_NO_USER)
        for key, value in (values or {}).items():
            key = self._key(str(key))
            value = self.spec.normalise(value) if value else {}
            if value:
                if self._table.get(key) == value:
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
        """Rewrite keys - ONE write for the whole move.

        A half-rewritten keyspace is worse than the orphaning it fixes,
        and the adopt-only merge means a rename expressed as
        delete-then-add can be half-resurrected by the other pane.
        """
        if not (moves or {}):
            return Written(True, REASON_UNCHANGED)
        if self.spec.user_tagged and not self.user_tag():
            return Written(False, REASON_NO_USER)
        # Tagged on BOTH sides: a folder that moved moves it for the
        # user doing the moving, and leaves everyone else's rows where
        # they are - they will relocate their own when they next look.
        moves = {self._key(str(k)): self._key(str(v))
                 for k, v in (moves or {}).items()}
        moves = {k: v for k, v in moves.items() if k != v}
        touched = [k for k in moves if k in self._table]
        if not touched:
            return Written(True, REASON_UNCHANGED)
        staged = dict(self._table)
        for old in touched:
            value = staged.pop(old)
            # An existing entry at the destination WINS: it was chosen
            # for the new path, and a rename must not overwrite it.
            staged.setdefault(moves[old], value)
        return self._commit(staged, touched)

    def adopt_orphans(self) -> Written:
        """File every ownerless row under the current user, in ONE
        write - the commit that writes the tagged spellings is the same
        one that stops writing the untagged ones, so the move lands
        whole or not at all.

        Adoption can only ADD: a key its owner already holds keeps the
        owner's value, and the orphan is retired unadopted. A store
        with orphans but nothing new to add still commits once, because
        the untagged spellings sit on disk being re-read and re-dropped
        by every session until a write retires them. Which stores call
        this is a product decision per store, not the engine's:
        locations adopt (ROADMAP line 22 stage C), favourites decided
        against it and drop their pre-tag rows for good.
        """
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
        """Drop keys AS STORED - tags included, every owner's.

        The location-removal altitude, beside `everyones()`: removing
        a folder is a SHARED act on the shared folder list, so its
        sweep covers EVERY user's keys under the location and needs no
        user picked on the removing machine - the same rule that stops
        the per-user half of a migration refusing the shared half.
        Never the paint path; `retire()` below is the scoped door for
        a caller speaking bare keys.
        """
        doomed = [str(k) for k in (keys or ()) if str(k) in self._table]
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
        doomed = [self._key(str(k)) for k in keys
                  if self._key(str(k)) in self._table]
        if not doomed:
            return Written(True, REASON_UNCHANGED)
        staged = dict(self._table)
        for key in doomed:
            staged.pop(key, None)
        return self._commit(staged, doomed)

    # -- the one commit -----------------------------------------------

    def _commit(self, staged: dict, keys) -> Written:
        """Every write in this engine lands here, so the guard set runs
        in ONE place and the cache moves only on success."""
        spec = self.spec
        if not self.writable:
            debug.note(spec.refused_sentence or (
                "%s could not be read earlier this run, so your change "
                "was not saved." % spec.label), path=self.path)
            reason = (REASON_ABSENT if self.trace else REASON_LATCHED)
            return Written(False, reason, spec.refused_sentence, keys)
        created = not os.path.exists(self.path)
        # STAGED, exactly like `_table`. Both mutations below - the
        # peer's foreign entries folded in, and the caller's keys
        # dropped - used to land on `self._foreign` BEFORE the write,
        # and the OSError path returns without putting them back. That
        # breaks this method's own rule in the one direction that
        # loses data: a newer build's value for a key whose write was
        # REFUSED left memory, and the next successful write of any
        # other key serialised the file without it.
        foreign = dict(self._foreign)
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._adopt_from_disk(staged, foreign)
            # A key the user just SET stops being foreign - the chosen
            # value must not be shadowed by the unreadable copy.
            for key in keys:
                foreign.pop(key, None)
            # The same restore tier every database gets. Foreign
            # entries ride under the staged ones (staged wins a key
            # both hold), so a rewrite never erases what a newer build
            # wrote.
            hostos.snapshot_before_write(self.path)
            hostos.write_json_atomic(
                self.path,
                {spec.payload: {**foreign, **staged}},
                indent=1, sort_keys=True)
            if created:
                # THE FLOOR, FROM THE FIRST WRITE. snapshot_before_write
                # correctly refuses to snapshot a file that does not
                # exist yet, so a store written exactly once had no
                # trace of any kind - and absent-but-known cannot find
                # evidence that was never written. Measured on the real
                # library 2026-08-03: icons.json is absent with no .bak
                # of any kind, so its first pick was also its only
                # unprotected one. Minting the write-once floor from
                # the file we just wrote closes that with a filename
                # already in the library's documented contents.
                hostos.seed_restore_floor(self.path)
            self._remember_disk_state()
            # A STORE THAT HAS BEEN WRITTEN IS READ, NOT FRESH. `state`
            # was set once at load and never moved, so a store created
            # by its own first write went on reporting "absent, and
            # nothing says it was ever here" for the rest of the
            # session - and any caller distinguishing "no file at all"
            # from "a file holding nothing" got the wrong answer. Found
            # 2026-08-05: a rule keyed on FRESH fired after the last key
            # was removed and put it straight back.
            self.state = READ
        except OSError as exc:
            # THE THIRD REPORT, BESIDE THE OTHER TWO. `_unreadable`
            # alerts with `spec.unreadable_alert` and the refusal above
            # notes `spec.refused_sentence`; this case alone was left to
            # the adapters, so `notes` and `tile_icons` each grew their
            # own copy of it and the other two stores silently had none.
            # The words are the store's, the policy is the engine's, and
            # the CAUSE comes from the one place that reads an errno.
            cause, why = hostos.why_failed(exc, self.path)
            debug.event(spec.category, "could not save %s" % spec.filename,
                        path=self.path, error=str(exc), cause=cause)
            if spec.denied_alert:
                debug.alert("%s\n\nThis happened because %s"
                            % (spec.denied_alert, why),
                            key="%s-denied-%s" % (spec.filename, cause))
            return Written(False, REASON_DENIED, why, keys)
        # COMMIT. Only now does the cache move - both halves of it.
        self._table = staged
        self._foreign = foreign
        # The file this commit wrote no longer holds the ownerless
        # rows, so the bucket empties with it - a bucket that outlived
        # the file would let a later adoption resurrect rows the user
        # had meanwhile removed.
        self._orphans = {}
        return Written(True, REASON_NONE, "", keys)

    def _remember_disk_state(self) -> None:
        self._disk_state = hostos.disk_state(self.path)

    def _adopt_from_disk(self, staged: dict, foreign: dict) -> None:
        """Fold in keys another session added since this one read.

        Adoption can only ADD: a key on disk this session does not hold
        is theirs and is kept; a key both hold takes ours, because this
        session is the active editor; a key we removed this session
        stays removed, which works because the removal is already
        absent from `staged`. The honest cost, unchanged from the
        stores this replaces: without tombstones, a same-session delete
        of a key the other pane also holds comes back.
        """
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
        peer = loaded.get(self.spec.payload)
        if not isinstance(peer, dict):
            return
        adopted = 0
        for key, value in peer.items():
            stored = restored_key(self.spec, str(key))
            kept = self.spec.normalise(value)
            if kept:
                if stored not in staged:
                    staged[stored] = kept
                    adopted += 1
                else:
                    # BOTH HOLD IT. Ours stands unless this key's rule
                    # says the two ANSWERS can both be true - a folder
                    # each pane registered, a field each pane set.
                    folded = _fold(
                        self.spec.merge_rules.get(stored, MERGE_MINE),
                        staged[stored], kept)
                    if folded is not None:
                        staged[stored] = folded
                        adopted += 1
            elif (value and stored not in staged
                  and stored not in foreign):
                # The peer's unreadable entry is as foreign as one from
                # our own load - kept, or OUR write erases THEIR data.
                # Into the STAGING copy, so a write that then fails
                # leaves the live table where it was.
                foreign[stored] = value
                adopted += 1
        if adopted:
            debug.event(self.spec.category,
                        "adopted entries another session wrote",
                        path=self.path, adopted=adopted,
                        store=self.spec.filename)


# -- the key lifecycle, fanned out over the registry -------------------
#
# THE OWNER ANNOUNCES, THE ENGINE FANS OUT. The engine sees strings and
# can never know a folder moved; only the File section does, because
# only it ran the picker. But the caller must never enumerate the
# stores - that is the defect, twice over: the relocate hook named four
# per-location dicts and neither side table, and the removal hook named
# two of those same four. An enumeration held by a caller is a list
# someone can write short, and both of these already were.


def _fold(rule: str, ours, theirs):
    """OURS with the peer's additions folded in, or None if there were
    none - so the caller can count a real adoption and skip a rewrite
    that would change nothing.

    ADDS ONLY, like the adoption it extends. A shape that does not fit
    the rule answers None rather than guessing, which lands on ours -
    the same verdict a key with no rule gets, and the safe one.
    """
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
            mine = merged[key]
            if not (isinstance(mine, dict) and isinstance(value, dict)):
                continue                    # ours, as the shallow rule
            missing = {}
            if missing:
                # REBOUND, never mutated: `dict(ours)` is shallow, so
                # the record under this key is the live cache's own
                # object and editing it in place would move the table
                # before the write that is supposed to commit it.
                merged[key] = {**mine, **missing}
                changed = True
        return merged if changed else None
    return None


def _boundary(prefix: str) -> str:
    """A folder prefix that cannot match a SIBLING. Without the
    separator, relocating `/a/tex` captures `/a/textures` - and a
    trailing-slash mismatch on a different path-keyed table once
    orphaned 2,000 cached thumbnails."""
    return prefix.rstrip("/") + "/"


def _bare_path(spec: Spec, key: str) -> str:
    """The PATH inside a key, with any keyspace prefix taken off.

    `notes.json` keys a File row as `file:/photos/a.exr`, so a raw
    comparison against `/photos/` matches nothing - which is how the
    first version of `retire_prefix` swept the locations and the icons
    and silently left every comment behind. ONE function answers this
    now, for both halves of the lifecycle; two of them is what the
    engine exists to stop, and my own code had grown the second within
    the hour.
    """
    if spec.path_prefix and key.startswith(spec.path_prefix):
        return key[len(spec.path_prefix):]
    return key


def storage_key(spec: Spec, key, user: str = "") -> str:
    """The spelling a path-shaped key is STORED under - variable-
    relative via `hostos.storage_path_key`, so the file's bytes resolve
    on every machine sharing the library. Id keys pass through; a mixed
    store converts only inside its declared prefix. Callers keep
    speaking whatever spelling they hold: the boundary converts, the
    same one-implementation rule as `_bare_path` above.

    A `user_tagged` store prefixes `<uid>|` here, which is why the tag
    reaches every read and write without any of them knowing: this is
    already the one door they all pass through."""
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
    """A key read FROM DISK, normalised WITHOUT disturbing its tag.

    The legacy-spelling absorption on load and the peer adoption both
    re-normalise every key they read. On a tagged store that key is
    `<uid>|<path>`, and handing the whole string to the path
    normaliser mangles it into a portable spelling of something that is
    not a path. Split, normalise the path half, put the tag back.
    """
    owner, bare = untagged_key(spec, key)
    if owner:
        return owner + USER_SEP + storage_key(spec, bare)
    return storage_key(spec, key)


def untagged_key(spec: Spec, key: str) -> tuple:
    """`(uid, key)` for a stored key - `("", key)` when it carries no
    tag. Split on the FIRST separator only: a uuid4 hex cannot contain
    one and a path can."""
    if not spec.user_tagged:
        return ("", key)
    tag, sep, rest = str(key).partition(USER_SEP)
    return (tag, rest) if sep else ("", key)


def _under(spec: Spec, key: str, prefix: str) -> bool:
    """Is this key the location itself, or something inside it?

    The caller's prefix is converted to STORAGE spelling first, because
    that is the space the table's keys live in - comparing an absolute
    against `~/...` matches nothing, which would leave every key under
    a removed location behind, the exact sweep `retire_prefix` exists
    to do."""
    if not spec.is_path_key(key):
        return False
    prefix = hostos.storage_path_key(prefix)
    bare = _bare_path(spec, key)
    return bare in (prefix, prefix.rstrip("/")) or bare.startswith(
        _boundary(prefix))


def relocate(preferences, old: str, new: str) -> dict:
    """A registered location moved: rewrite every path-shaped key in
    every store, one guarded write each. Returns {filename: Written}."""
    results = {}
    if not old or not new or old == new:
        return results
    # Storage space on both sides, the same conversion `_under` makes:
    # the table's keys are variable-relative, so the edges must be too.
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
                # The LOCATION's own key, not a file under it. The
                # caller's `new` is used verbatim - `relocate_folder`
                # has already decided whether it carries a trailing
                # slash, and a trailing-slash mismatch on a path-keyed
                # table is what orphaned 2,000 cached thumbnails once.
                moved = new
            else:
                continue
            moves[key] = (spec.path_prefix or "") + moved
        if moves:
            results[spec.filename] = store.rekey(moves)
    return results


def retire_prefix(preferences, prefix: str) -> dict:
    """A location is gone for good: drop every key under it, in the
    stores that do NOT survive a removal.

    Which stores those are is `survives_forget` on the spec, and it is
    a PRODUCT decision rather than a shape one. Since 2026-08-03 every

    favourites, comments and icons" - so a removal takes the label,
    colour, recursion, Show All Files override, favourites, comments
    and tile icons with it, and re-adding the folder is a clean slate.

    The field is still the right home for that even now they agree: it
    was the opposite answer for the first half of 2026-08-03, and this
    function deleted every tile icon under a removed folder for its
    first half hour by inferring the answer from the keyspace instead.
    They are all path-keyed; the shape never carried the decision.
    """
    results = {}
    for spec in stores():
        if spec.survives_forget or spec.keyspace == KEY_ID:
            continue
        store = open_store(spec, preferences)
        if spec.user_tagged:
            # EVERY user's keys under the location, not the remover's.
            # A removal is a shared act on the shared folder list - the
            # 2026-08-03 clean slate holds across the tag - and it must
            # work on a machine with nobody picked, so the walk is the
            # stored table and the drop keeps the spellings it found.
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
    """Drop the cached tables - a library switch, or a test.

    `notes.forget_notes()` and `tile_icons.forget_overrides()` were two
    identical functions with ZERO production callers between them; this
    is the one live requirement they each half-expressed.
    """
    if preferences is None:
        _open.clear()
        return
    # BOTH SIDES THROUGH canonical_path_key. `prefs.dir` comes out of
    # `prefs._normalised_dir`, which guarantees a TRAILING SLASH, and
    # `os.path.dirname` of a store path never has one - so the raw
    # compare could not match for any real Prefs and this branch
    # released nothing at all. `normpath` collapses both spellings, and
    # it is the same helper `serves()` and the location keys already
    # compare through.
    root = hostos.canonical_path_key(str(preferences.dir))
    for key in [k for k in _open
                if hostos.canonical_path_key(os.path.dirname(k[1])) == root]:
        _open.pop(key, None)


def reset() -> None:
    """Tests only: forget every open table AND every registration."""
    _open.clear()
