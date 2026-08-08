"""
Database Handler for Matlib - Saves Data as json to disk and ensures only one active connection
"""

import json
import os
import hashlib
from typing import Self

from amaze import branding
from amaze.core import debug
from amaze.helpers import hostos


#: Schema version stamped into every database on save. Version 1 is
#: the implicit legacy schema (no "version" key). Bump this together
#: with a new _MIGRATIONS step - the load path applies steps in order,
#: so either machine of a two-machine setup can open a library written
#: by the other and land on the same schema.
SCHEMA_VERSION = 2

#: version-it-upgrades-FROM -> function(data) -> None (mutates in
#: place). Step N runs when data["version"] == N, producing N+1.
_MIGRATIONS = {}


def _migration_v1(data: dict) -> None:
    """v1 -> v2: the explicit-schema baseline. Guarantees the three
    top-level keys exist; carries everything else through untouched
    (existing asset ids deliberately KEEP their legacy values - scene
    nodes stamp them as userData, and renaming would orphan every
    stamp in existing hip files)."""
    data.setdefault("categories", ["_All"])
    data.setdefault("tags", [])
    data.setdefault("assets", [])


_MIGRATIONS[1] = _migration_v1


#: Survives the module reload; the class attribute points at it.
_INSTANCES: dict = globals().get("_INSTANCES", {})


#: Per-database sibling files that prove that database was here before,
#: for the case where it is momentarily ABSENT. Beyond the .bak-N /
#: .unreadable copies hostos writes for every database, which
#: existed_before checks unconditionally.
#:
#: Measured on the real library 2026-07-29: cops.json has four .bak
#: files and no marker, code.json has a marker and NO .bak at all - so
#: neither kind of trace alone covers both, and a .bak-only guard would
#: pass code.json straight through to the empty-seed path it is meant to
#: stop. The legacy marker name is listed too: it is only renamed on
#: sight by code_library, which does not run until after this load.
_EXISTED_MARKERS = {
    "code.json": (".amaze_code_starter_v1", ".assetlib_code_starter_v1"),
    # Literals, not GradientLibrary._SEED_MARKER: gradient_library
    # imports this module, so naming its class here would be a circular
    # import. The code.json entry above is written out for the same
    # reason. gradients.json was the ONE database missing from this
    # table, which made Repair and the colours loader answer "was this
    # file ever here?" differently about the same file.
    "gradients.json": (".amaze_gradient_seed_v1",
                       ".assetlib_gradient_seed_v1"),
}


def absent_but_known(directory: str, filename: str) -> str:
    """For a database that is NOT on disk: the name of a trace saying it
    was, or "" when this really is a new library.

    Shared with library.py's cleanup, deliberately. Two callers ask the
    same question about the same file within one session - "is this
    missing because it is new, or because it has not arrived yet?" - and
    they must never answer it differently: load() seeding an empty
    cops.json and cleanup then reading its 8 assets' files as orphans is
    the exact two-step that deleted 21 live files.
    """
    return hostos.existed_before(
        os.path.join(directory, filename), _EXISTED_MARKERS.get(filename, ())
    )


#: What the PANEL calls each database, so a refusal can talk about the
#: section the user can actually see instead of only the storage file.
#: "cops.json" means nothing to someone looking at a tab labelled
#: "Nodes", and a message that cannot be matched to anything on screen
#: is indistinguishable from noise.
#:
#: Duplicated from panel/sections.py rather than imported: core must not
#: depend on the UI package (panel imports core, and the reload chain
#: relies on that staying one-way). test_absent_database asserts the two
#: agree, so the copy cannot drift silently.
#:
#: gradients.json is listed although it has no DatabaseConnector: the
#: gradient library runs the same absent-but-known guard and must name
#: its section the same way.
_SECTION_LABELS = {
    "library.json": "Material",
    "cops.json": "Node",
    "code.json": "Code",
    "gradients.json": "Color",
}

#: What ONE of a section's saved things is called, so a count can carry a
#: noun. "548 saved" answers nothing - saved what? - and the answer is
#: different per section: materials, nodes, snippets, colors. Singular,
#: because every one of them pluralises with an s and "1 saved material"
#: is the half that reads wrong when a table stores the plural.
_SECTION_HOLDS = {
    "library.json": "material",
    "cops.json": "node",
    "code.json": "snippet",
    "gradients.json": "color",
}

#: The lists whose assets own files in the shared ASSET folder, and
#: therefore the only lists whose emptiness can say anything about a
#: leftover .mat/.interface there.
#:
#: Code keeps its snippets INLINE in code.json (code_library: "No
#: <id>.mat/.png files at all") and Colors keeps its ramps inline in
#: gradients.json, so neither can own one. Both readers of that fact need
#: the same answer: Clean Library's guard, which decides whether a list
#: that reads empty holds the asset-folder sweep back, and Repair, which
#: asks the user which section an unlisted pair belongs in. A section that
#: cannot own the file must appear in neither.
ASSET_FILE_OWNERS = ("library.json", "cops.json")


def asset_id_for_file(name: str, extensions: tuple,
                      tail: str = "") -> str | None:
    """The asset id a file in the library's own folders belongs to, or
    None when the name is not one of these files at all.

    ONE classifier for the guard and for the sweep, deliberately. The
    guard decides whether deleting is safe by counting the files that no
    section lists; the sweep is the thing that deletes them. Two separate
    copies of "which asset does this file belong to" can disagree, and a
    guard that counts a different set of files than the sweep touches is
    not a guard at all - it is a second opinion nobody reconciled.

    STRICT BY SHAPE, and only ever in the refusing direction. A file
    whose stem is not an id this app writes is not classified at all -
    it is skipped and logged, never counted and never swept.

    That asymmetry is the whole design. The sweep deletes what this
    returns, so a classifier that guesses generously deletes generously.
    The case it exists for is a sync client's conflicted-copy rename -
    `library (conflicted copy 2026-07-29).mat` - which used to split on
    the first dot, read as an unrecognised owner, and be swept as an
    orphan: destroying the one artifact that existed to preserve a
    divergence.

    Two id shapes are accepted, because both are real: `uuid4().hex`
    for everything new, and the pre-uuid all-digit timestamp ids that
    Material.__init__ promises live forever. Anything else - a stem with
    a space, a bracket, a dash, a second dot - is refused.
    """
    matched = next((e for e in extensions
                    if name.lower().endswith(e.lower())), None)
    if matched is None:
        return None
    # EXACTLY stem + tail + extension, with nothing else between.
    # Splitting on the first dot instead reads `asset.backup.mat` as
    # belonging to asset "asset" - and then sweeps somebody's manual
    # backup as a leftover the moment no row is called "asset".
    stem = name[: -len(matched)]
    if tail and stem.endswith(tail):
        stem = stem[: -len(tail)]
    if "." in stem:
        debug.event("cleanup", "file not classified - extra suffix",
                    file=name, stem=stem[:60])
        return None
    # ALPHANUMERIC, nothing narrower. Real ids are uuid4 hex or the
    # pre-uuid all-digit timestamps, and a rule spelled that way is
    # tempting - but it refuses any id shape not anticipated here, and
    # the sweep is not the place to discover one. What has to be
    # excluded is punctuation and spaces, which is exactly what a
    # conflicted-copy rename adds and what an id never contains.
    if not stem.isalnum():
        # Refusing is the SAFE direction: an unrecognised file stays
        # exactly where it is. Logged rather than silent, because a
        # library accumulating unclassifiable files is worth seeing.
        debug.event("cleanup", "file not classified - left alone",
                    file=name, stem=stem[:60])
        return None
    return stem


#: The fields two people can edit on the same asset from two machines
#: without either edit being about the other: ROADMAP's "shared
#: metadata" write kind, by name. Content is NOT here (the .mat pair
#: has its own exclusive guard), and neither is anything derived from
#: content (renderer, builder, date).
_SHARED_METADATA_FIELDS = ("name", "categories", "tags", "description",
                           "license", "about", "icon", "node_color")


def _merge_shared_metadata(mine: dict, theirs: dict, filename: str) -> None:
    """Field-wise merge for a record both sessions hold.

    "Two people editing DIFFERENT fields of the same asset is not a
    conflict at all" (ROADMAP) - and whole-record ours-wins made it one:
    my rename erased your retag, because the record was the unit of
    comparison when the FIELD was the unit of editing.

    Baseline-free, so the honest rule is asymmetric: a field where
    THEIRS differs and MINE is empty/default takes theirs - an empty
    description losing to a written one loses nothing - and anything
    else keeps mine, with the collision RECORDED, not dialogued: an
    editor mid-flow cannot answer "whose tags win" about an edit they
    have never seen, and the note is enough to find the loser's value
    in the peer's snapshot tiers.
    """
    for field in _SHARED_METADATA_FIELDS:
        if field not in theirs:
            continue
        their_value = theirs.get(field)
        my_value = mine.get(field)
        if my_value == their_value:
            continue
        empties = ("", None, [], {})
        if my_value in empties and their_value not in empties:
            mine[field] = their_value
            debug.event("database", "adopted a field another session "
                        "filled", file=filename,
                        mat_id=str(mine.get("id")), field=field)
        else:
            debug.event("database", "field collision - this session's "
                        "value kept", file=filename,
                        mat_id=str(mine.get("id")), field=field)


def wrong_shape(document) -> str:
    """"" when `document` is shaped like a database, else what is wrong
    with it - a phrase for the log, since the user-facing sentence is the
    same however a file failed to be readable.

    VALID JSON IS NOT A VALID DATABASE, and both readers of these files
    need the same answer to that: the connector's merge, and library.py's
    cleanup, which decides from it whether deleting anything is safe. Two
    callers asking one question about one file must never answer it
    differently - the same reason absent_but_known is shared.

    Only the containers a reader actually walks are checked. An individual
    asset entry is NOT validated here: the merge already skips a non-dict
    row and leaves it on disk for whoever wrote it, which is the right
    granularity - one bad row must not cost a session its writes.
    """
    if not isinstance(document, dict):
        return "top level is %s, not an object" % type(document).__name__
    # "gradients" is here because gradients.json is read by this same
    # helper and its loader walks that container - checking only the
    # three names the other databases use would have passed
    # {"gradients": "oops"} straight through to the code that iterates
    # it. A key absent from a given file costs nothing: .get defaults to
    # a list, so each file is only checked for what it actually carries.
    for key in ("assets", "categories", "tags", "gradients"):
        value = document.get(key, [])
        if not isinstance(value, list):
            return "%s is %s, not a list" % (key, type(value).__name__)
    return ""


def wrong_table_shape(document, key: str) -> str:
    """"" when `document` is `{key: {...}}`, else what is wrong with it.

    wrong_shape's twin for the two library-adjacent SIDE TABLES -
    notes.json and icons.json - whose payload is a mapping rather than
    a list. Same argument as its sibling: valid JSON is not a valid
    store, and the readers of one file must not answer that question
    two different ways.

    Both hand-rolled something weaker and neither survived a wrong
    shape. `{"icons": null}` and `{"icons": []}` reached `.items()` and
    raised AttributeError - which is neither OSError nor ValueError, so
    the unreadable latch never engaged, the table was never cached, and
    the exception repeated on every call from a PAINT path. notes.json
    wrote `(loaded.get("notes") or {})`, which survives null but not a
    non-empty list, and in the surviving case treated the junk as "no
    notes yet" - so the next note written replaced every note in the
    library with a one-key file.
    """
    if not isinstance(document, dict):
        return "top level is %s, not an object" % type(document).__name__
    value = document.get(key, {})
    if not isinstance(value, dict):
        return "%s is %s, not an object" % (key, type(value).__name__)
    return ""


def _keyed_store_label(filename: str) -> str:
    """The side tables name themselves, in the registry that declares
    them. Repair's alert sends the user here by name, so Repair must be
    able to SAY the name - and a second copy of the four-entry table
    below is how the two lists drifted in the first place."""
    try:
        from amaze.core import keyed_store
    except Exception:                                     # noqa: BLE001
        return ""
    spec = keyed_store.store_for(filename)
    return spec.label if spec else ""


def _keyed_store_noun(filename: str) -> str:
    try:
        from amaze.core import keyed_store
    except Exception:                                     # noqa: BLE001
        return ""
    spec = keyed_store.store_for(filename)
    return spec.noun if spec else ""


def section_name(filename: str) -> str:
    """"Nodes (cops.json)" - the user's word for a database, with the
    filename kept because it is what they will look for on disk."""
    label = _SECTION_LABELS.get(filename) or _keyed_store_label(filename)
    return "%s (%s)" % (label, filename) if label else filename


def section_label(filename: str) -> str:
    """"Nodes" alone - the tab's own name, for a sentence that sends the
    reader to a CONTROL rather than to a file.

    Both forms come from the one table so they cannot drift. Which to use
    is not a style choice: section_name introduces the pair once, and a
    later sentence in the same message that says "cops.json" where the
    first said "Nodes (cops.json)" reads as a third thing. One name per
    thing, in every file."""
    return (_SECTION_LABELS.get(filename)
            or _keyed_store_label(filename) or filename)


def section_noun(filename: str, count: int = 2) -> str:
    """"nodes", "material" - the word for what a section's count counts,
    already singular or plural.

    A bare number in a recovery dialog is unanswerable: "that copy holds
    8" beside "the list you have now holds 548" reads as arithmetic, and
    the reader still cannot tell whether the 8 are materials or colours.
    From the same table as the labels, so the word for what a section
    holds cannot drift from the name of the section."""
    noun = (_SECTION_HOLDS.get(filename)
            or _keyed_store_noun(filename) or "saved thing")
    return noun if count == 1 else noun + "s"


class DatabaseConnector:
    """
    Database Handler for Matlib - saves data as json to disk with one
    active connection PER DATABASE FILE. Historically a plain singleton
    hardcoded to library.json; the v2 COP section runs a second,
    fully independent library over cops.json, so instances are now keyed
    by filename (same instance returned for the same filename - all
    existing callers pass nothing and keep sharing the library.json
    connection exactly as before).
    """

    #: Registry of live connectors, one per database FILE.
    #:
    #: Held OUTSIDE the class body: panel.py reloads this module on
    #: every panel open, and reload re-executes the `class` statement -
    #: producing a NEW class object with an empty registry. The models
    #: keep pointing at the old connector's _data while db.set() writes
    #: a different one, so sidebar counts and category colours silently
    #: stop tracking saves. Worse, the fresh instance has no _path and
    #: no stale-write baseline, so save() would build a RELATIVE path
    #: and write into Houdini's working directory.
    _instances: dict = _INSTANCES

    def __new__(cls, filename: str = "library.json") -> Self:
        inst = cls._instances.get(filename)
        if inst is None:
            inst = super().__new__(cls)
            inst._filename = filename
            inst._data = {}
            inst._path = ""
            inst._disk_stat = None
            inst._loaded_ids = set()
            #: Rows adopted from another session's save, awaiting
            #: handover to the model (see take_adopted).
            inst._adopted = []
            #: Ids the caller has explicitly deleted. _absorb_rows can
            #: only KEEP rows, so a delete needs to be said out loud.
            inst._forgotten = set()
            #: Schema version as READ from disk, so save() cannot stamp
            #: a downgrade over a newer build's file.
            inst._loaded_version = SCHEMA_VERSION
            #: "_migrate stopped early, so this document is NOT at
            #: SCHEMA_VERSION." Read by save(), which otherwise stamped
            #: the target version over a chain that never completed.
            inst._migration_incomplete = False
            #: "This file could not be trusted, so do not write it."
            #: Set here rather than left to a getattr default so both
            #: latches can be read plainly - and so reload_with_path has
            #: something to reset rather than an attribute that may or
            #: may not exist.
            inst._write_blocked = False
            #: The LIBRARY FORMAT as read from disk (0 = pre-stamp),
            #: and the read-only latch a stamp ahead of
            #: branding.LIBRARY_FORMAT sets. Unlike _write_blocked it
            #: never heals mid-session: the way out is updating Amaze,
            #: not retrying the write.
            inst._loaded_format = 0
            inst._format_ahead = False
            inst._format_reported = False
            #: Whether the user has been TOLD that saving is off. Once
            #: per connector per session: save() is called from ordinary
            #: sidebar use, so a line per save would be a wall of text.
            inst._block_reported = False
            cls._instances[filename] = inst
        return inst

    def _stat_file(self):
        """(size, sha256) of the file on disk, or None when unreadable.

        CONTENT, not (mtime_ns, size). Both directions of the stat
        guard's error were measured (research.md): a same-size edit - a
        boolean flip, an equal-length rename - passes a stat compare and
        silently loses the peer's change, and a peer's byte-identical
        atomic rewrite trips it as a conflict that is not there, sending
        an ordinary save down the merge path for nothing.

        The size rides along so a mismatch is answered before hashing
        in the common case; the hash is the verdict. Cost: reading the
        file - 1.4ms for the real 355KB library.json (research.md,
        measured), on saves only, never per frame.
        """
        try:
            with open(self._path + self._filename, "rb") as handle:
                raw = handle.read()
            import hashlib
            return (len(raw), hashlib.sha256(raw).hexdigest())
        except OSError:
            return None

    def _remember_disk_state(self) -> None:
        """Baseline for the stale-write guard: what the FILE looked
        like when this session last read or wrote it, plus which asset
        ids existed then (the membership baseline a three-way merge
        needs to tell OUR deletions from THEIR additions)."""
        self._disk_stat = self._stat_file()
        self._loaded_ids = {
            str(a.get("id")) for a in (self._data or {}).get("assets", [])
        }

    def _migrate(self, data: dict) -> None:
        """Applies schema migrations in order to `data` and stamps the
        current version on it. A database from a NEWER schema than this
        build knows is left untouched and reported - never downgraded
        blind.

        Takes the document as an ARGUMENT rather than reading self._data,
        so load() can migrate a parse result that is not committed yet.
        A migration step raises like any other code, and while this ran
        against self._data a half-applied step left the connector holding
        a partial document with no stale-write baseline behind it
        (_remember_disk_state never ran) - i.e. exactly the state save()
        is least able to write safely."""
        version = int(data.get("version", 1))
        self._loaded_version = version
        # Re-derived on every read, never remembered: this connector can
        # be pointed at another library at any time, and a gap in ONE
        # library's chain must not follow the user into the next.
        self._migration_incomplete = False
        # THE FORMAT STAMP - a separate contract from the schema chain:
        # schema migrates shapes this build knows, format says whether
        # this build may WRITE the file at all. Ahead of what this
        # build knows = the session is read-only for this file, said
        # ONCE, and the latch never heals - the way out is updating
        # Amaze, not retrying.
        try:
            self._loaded_format = int(data.get("format", 0) or 0)
        except (TypeError, ValueError):
            self._loaded_format = 0
        self._format_ahead = (
            self._loaded_format > branding.LIBRARY_FORMAT)
        if self._format_ahead:
            debug.event("database", "library format ahead - read-only",
                        file=self._filename, found=self._loaded_format,
                        known=branding.LIBRARY_FORMAT)
            debug.alert(
                "This library was saved by a newer Amaze. To keep it "
                "safe, this machine opens it read-only - update "
                "Amaze, then everything works as normal.",
                key="format-ahead-%s" % self._filename)
        if version > SCHEMA_VERSION:
            debug.event(
                "database", "newer schema than this build",
                file=self._filename, found=version, known=SCHEMA_VERSION,
            )
            return
        while version < SCHEMA_VERSION:
            step = _MIGRATIONS.get(version)
            if step is None:
                # A gap in the chain: stamping SCHEMA_VERSION here would
                # claim migrations that never ran. This refusal was
                # correct and then completely undone by save(), which
                # stamped max(_loaded_version, SCHEMA_VERSION) anyway -
                # so the flag is what carries the refusal that far.
                debug.event("database", "migration step missing",
                            file=self._filename, at_version=version)
                self._migration_incomplete = True
                break
            step(data)
            version += 1
            debug.event("database", "migrated", file=self._filename,
                        to_version=version)
        data["version"] = version
        self._loaded_version = version

    def load(self, path: str) -> dict:
        """
        Loads the Database from disk as json. Secondary databases
        (anything that isn't library.json) are seeded as an empty
        library on first use instead of failing - library.json itself
        keeps the old behavior, since a missing PRIMARY database is a
        real error the caller must surface, not silently paper over.

        "First use" means NOTHING beside the file says it was ever here
        (see absent_but_known). Absence alone is not newness: the file
        only had to be gone for the instant panel.py constructs the
        model - and panel.py constructs CopLibrary on EVERY panel open,
        so a sync placeholder still arriving hit that window every
        launch. Reproduced 2026-07-29: cops.json 5,537 bytes / 8 records
        -> 96 bytes / 0 records, then Clean Library reported "23
        orphaned file(s) on disk were removed" and all 21 files those 8
        live assets owned were gone. snapshot_before_write returns early
        for a path that does not exist, so the write that emptied the
        file took NO backup either.
        """
        self._path = path
        if not self._data:
            full = self._path + self._filename
            if not os.path.exists(full) and self._filename != "library.json":
                evidence = absent_but_known(self._path, self._filename)
                if evidence:
                    self._refuse_absent(full, evidence)
                    return self._data
                # "_All", not "All": the leading underscore is the
                # library's long-standing sort trick - it sorts before
                # any letter so the pseudo-category stays pinned on top,
                # and Categories.data() strips it for display.
                self._data = {"categories": ["_All"], "tags": [], "assets": []}
                self.save()
            else:
                # utf-8-sig, not utf_8. A BOM in front of the document is
                # a routine half-synced-editor artifact - Notepad and a
                # few sync clients' conflict-resolution helpers write one
                # - and json.load raises on it, which for library.json is
                # a load with no recovery path at all. utf-8-sig reads a
                # BOM-less file byte-identically, so this costs nothing
                # for the normal case; the codec strips the marker only
                # when it is actually there. Writing stays plain utf-8:
                # nothing here should ever ADD a BOM.
                #: PARSE INTO A LOCAL, COMMIT AFTER THE MIGRATION.
                #: self._data used to be assigned straight from json.load
                #: and migrated in place, so anything a migration step
                #: raised left the connector holding a HALF-MIGRATED
                #: document - with no stale-write baseline behind it,
                #: because _remember_disk_state is the line after. That is
                #: the worst state save() can be asked to write from: it
                #: believes it holds the library, and _disk_stat is None
                #: so the guard that would have caught the difference is
                #: not armed. Leaving _data falsy instead means the
                #: refusal is honest AND the next load() retries, because
                #: `if not self._data` is what gates this whole branch.
                with open(full, encoding="utf-8-sig") as lib_json:
                    parsed = json.load(lib_json)
                # THE SAME CLASSIFIER AS THE MERGE, and it belongs here
                # too. `[]` is valid JSON and not a database, and this is
                # the PRIMARY index's read: _migrate's very first line is
                # data.get(), so a list document raised AttributeError out
                # of the model constructor - a class no caller can catch,
                # because everything that guards a database read here
                # guards (OSError, ValueError), the pair a truncated file
                # raises. Reproduced live: library.json holding `[]` ->
                # AttributeError: 'list' object has no attribute 'get'.
                #
                # Raising ValueError is deliberately the SAME outcome a
                # truncated file already gets, not a new one. "Refuse over
                # overwrite" is the settled policy for a file that exists
                # and will not read, and a document of the wrong shape is
                # that file; making this one shape uniquely fatal-in-a-
                # different-way is how the merge ended up bypassing the
                # whole preserve/latch/tell-the-user path.
                malformed = wrong_shape(parsed)
                if malformed:
                    debug.event("database", "load refused - not a database",
                                file=self._filename, reason=malformed)
                    raise ValueError(
                        "%s is not a database (%s)"
                        % (self._filename, malformed))
                self._migrate(parsed)
                self._data = parsed
                if self._filename != "library.json":
                    self._normalize_all_category()
                self._note_suspicious_shrink(full)
            self._remember_disk_state()
        return self._data

    #: Findings the next Clean Library report should surface: a list of
    #: plain-language sentences, per filename, PERSISTED on the class -
    #: a transient console note is easy to miss and invisible on
    #: Windows, and the person who should read it is the one about to
    #: run a cleanup against this data.
    _integrity_notes: dict = {}

    @classmethod
    def take_integrity_notes(cls) -> list:
        """The pending findings, cleared on read - they describe load
        moments that have been superseded once the next load runs."""
        notes = [line for lines in cls._integrity_notes.values()
                 for line in lines]
        cls._integrity_notes.clear()
        return notes

    def _note_suspicious_shrink(self, full: str) -> None:
        """After a successful parse: does this document hold under half
        of what its newest snapshot holds? Report-only - a shrink can be
        legitimate (a big deliberate cleanup), so it never blocks and
        never repairs; it makes sure a human SEES the number before the
        next sweep treats the shrunken list as the truth.
        """
        try:
            here = len(self._data.get("assets") or [])
            newest = None
            for tier in ("bak-1", "bak-2", "bak-3", "bak-first"):
                candidate = full + "." + tier
                if os.path.exists(candidate):
                    newest = candidate
                    break
            if newest is None:
                return
            with open(newest, encoding="utf-8-sig") as handle:
                backed = len((json.load(handle)).get("assets") or [])
            if backed >= 2 and here < backed / 2:
                sentence = (
                    "Your %s lists %d %s, but the most recent saved copy "
                    "holds %d - if you did not remove them yourself, run "
                    "Repair Library before cleaning anything."
                    % (section_label(self._filename), here,
                       section_noun(self._filename, here), backed))
                type(self)._integrity_notes.setdefault(
                    self._filename, []).append(sentence)
                debug.event("database", "suspicious shrink at load",
                            file=self._filename, holds=here,
                            newest_snapshot=backed)
        except (OSError, ValueError, TypeError):
            return                          # the note must never cost a load

    def _refuse_absent(self, full: str, evidence: str) -> None:
        """A secondary database that is gone but was here: hold an empty
        library in memory so the panel still builds, and block every
        write for the session so that emptiness cannot reach disk.

        _write_blocked is the mechanism the merge-failure path already
        uses, and reusing it is the point - it is the one flag save()
        consults before doing anything, so there is no second way to
        write that could miss this. Refusing ONCE would not be enough
        anyway: it is the SECOND save that overwrites what the first one
        preserved.

        The model shows an empty section this session, which is honest -
        the records genuinely are not readable right now - and nothing
        is lost, because nothing is written.
        """
        self._data = {"categories": ["_All"], "tags": [], "assets": []}
        self._write_blocked = True
        debug.note(
            "%s is not on disk, but %s beside it says it was - so it is "
            "treated as not-yet-arrived, NOT as a new library. Nothing "
            "was created and nothing will be saved to it this session, "
            "so the file cannot be replaced by an empty one. Let the "
            "sync finish, then restart Houdini.\n"
            # The PATH, not just the filename. The reader has to go and
            # look at a directory they chose months ago; a bare
            # "cops.json" leaves them hunting for it (prefs.py's
            # unreadable-settings message names its full path for the
            # same reason).
            "  Expected at: %s\n"
            # The way OUT of the refusal, named. Without it the guard is
            # permanent for anyone who deleted the database deliberately
            # - the trace stays behind and keeps answering "it was here"
            # forever, with nothing on screen saying what to do about it.
            # Bare name, not a second full path: "Expected at" above
            # already gives the directory, and both files are in it.
            "  If you removed it on purpose, remove %s as well and the "
            "next launch starts a fresh one."
            % (section_name(self._filename), evidence, full, evidence),
            file=full, evidence=evidence)
        # _block_reported deliberately NOT set here. Being told once at
        # panel open is not the same as being told at the moment an edit
        # is dropped, which can be an hour later and is the point at
        # which the user loses something.

    def _normalize_all_category(self) -> None:
        """One-time repair for secondary databases seeded before the
        "_All" convention was honored there: a plain "All" entry sorted
        alphabetically among real categories instead of pinning to the
        top. Rewrites it to "_All" (and guarantees the entry exists)."""
        cats = self._data.get("categories")
        if not isinstance(cats, list):
            return
        changed = False
        if "All" in cats:
            cats[:] = [c for c in cats if c != "All"]
            changed = True
        if "_All" not in cats:
            cats.insert(0, "_All")
            changed = True
        if changed:
            self.save()

    def set(self, assets: dict) -> None:
        """Set data without saving, WITHOUT swapping the containers.

        `current[:] = new` rather than `self._data[key] = new`. Fixing
        only the merge was not enough: Categories and MaterialLibrary
        hold a direct alias to these list objects, and this rebound all
        four keys on every set - so the alias was already detached
        before a merge could adopt anything into it.

        This still replaces the CONTENT wholesale, which is a separate
        defect (a second pane's rows are dropped by the first pane's
        set/save) and a separate step. What it no longer does is change
        which object the models are pointing at.
        """
        # The incoming value is COPIED before the container is emptied.
        # A caller very often hands back the same object it was given -
        # models pass `self._data`-derived state straight through - and
        # `colours.clear()` on a dict that IS the source wipes what the
        # update was about to read. Measured: four category-colour tests
        # went red the moment this was written the obvious way.
        for key in ("categories", "tags"):
            if key in assets:
                incoming = list(assets[key] or [])
                current = self._data.setdefault(key, [])
                current[:] = incoming
        if "assets" in assets:
            self._absorb_rows(list(assets["assets"] or []))
        if "category_colors" in assets:
            incoming_colours = dict(assets["category_colors"] or {})
            colours = self._data.setdefault("category_colors", {})
            colours.clear()
            colours.update(incoming_colours)

    def serves(self, library_dir: str) -> bool:
        """Is this connector still pointed at `library_dir`?

        The registry is keyed by FILENAME alone, so one instance serves
        every pane in the process. That is deliberate - it survives the
        module reload a panel open performs - but it means a library
        switch in one pane rebinds the connector under all of them.

        Measured shape of the failure: two panes on library A, one
        switches to B via reload_with_path, and the other pane's model
        still holds A's rows in memory. Its next save writes A's rows
        into B's file.

        Callers ask this before writing. Keying the registry by path
        instead would have been the other fix, and it is the bigger
        one: reload_with_path mutates the shared instance in place and
        every model holds the instance, so path-keying changes how a
        library switch works everywhere. This asks the same question
        without moving the mechanism.
        """
        if not self._path or not library_dir:
            return True                    # nothing loaded yet to disagree
        return (hostos.canonical_path_key(self._path)
                == hostos.canonical_path_key(library_dir))

    def _absorb_rows(self, incoming: list) -> None:
        """Take the caller's rows WITHOUT dropping rows it never saw.

        This used to replace the whole list from the caller's own copy.
        Two panes share one connector but keep separate in-memory asset
        lists, and the connector's write refreshes its OWN stale-write
        baseline - so the guard never fires for the in-process case and
        pane 2's save silently deleted the material pane 1 just added.

        Union by id: the caller's version of a row it holds wins, and a
        row it simply does not know about is kept. Absence therefore no
        longer means "delete", which is why forget() exists.
        """
        current = self._data.setdefault("assets", [])
        by_id, order = {}, []
        for row in current:
            if isinstance(row, dict):
                key = str(row.get("id"))
                if key not in by_id:
                    order.append(key)
                by_id[key] = row
        for row in incoming:
            if not isinstance(row, dict):
                continue
            key = str(row.get("id"))
            if key not in by_id:
                order.append(key)
            by_id[key] = row
        # In place: models alias this list (see set()).
        current[:] = [by_id[key] for key in order
                      if key not in self._forgotten]
        self._forgotten.clear()

    def forget(self, mat_id: str) -> None:
        """Drop a row on the next set(): the caller means DELETE.

        Needed because _absorb_rows can only keep rows. Omitting a row
        stopped meaning "remove it" the moment absence became "a pane
        that has not heard of it", and without an explicit signal a
        delete would simply be re-adopted from the connector's copy.
        """
        self._forgotten.add(str(mat_id))
        debug.event("database", "row marked for removal",
                    file=self._filename, mat_id=str(mat_id))

    def unforget(self, mat_id: str) -> None:
        """Take back a forget() whose delete did not go through.

        The mark outlives a refused save - _absorb_rows is what
        consumes and clears it, and a save that returns False never
        reaches there. So a caller that puts a row back in its model
        after a refusal has to clear the mark too, or the NEXT save
        deletes the row it just restored.
        """
        self._forgotten.discard(str(mat_id))
        debug.event("database", "row removal taken back",
                    file=self._filename, mat_id=str(mat_id))

    def save(self) -> bool:
        """One always-on record per save() call, whatever happens inside.

        The wrapper shape is deliberate, and it is the answer to the
        step's own warning: converting the most safety-critical function
        in the codebase into a single-exit body would restructure every
        guard in it to gain a log line. Instead each exit names its
        outcome and the finally writes exactly one record - including
        the path where the body RAISES, which a tail line inside the
        body can never see.

        The library directory is logged as a digest, never raw: the log
        is exportable and paths are the personal-data rule's territory.
        """
        self._save_outcome = "unrecorded"
        try:
            return self._save_inner()
        finally:
            digest = hashlib.sha256(
                hostos.canonical_path_key(self._path or "")
                .encode("utf-8")).hexdigest()[:10]
            debug.event("database", "save", file=self._filename,
                        outcome=self._save_outcome, dir_key=digest)

    def _refuse_unreadable_peer(self, full: str) -> bool:
        """The stale-write merge could not READ the other session's
        copy: preserve theirs, latch writes for the session, say it
        once in full. Extracted from _save_inner when the format
        latch gained its own refusal beside this one."""
        kept = hostos.preserve_unreadable(
            full, why="another session's database would not parse")
        self._write_blocked = True
        # ONLY CLAIM THE COPY WHEN THERE IS ONE. preserve_unreadable
        # has two paths that create nothing - a 0-byte source and a
        # failed copy - and a reassurance that is not quite true is
        # worse than none.
        copy_sentence = (
            " A copy of it is beside it as %s."
            % os.path.basename(kept)) if kept else ""
        debug.note(
            "could not read the other session's %s, so this "
            "library will not be saved this session - their "
            "copy is left untouched.%s Reopen Amaze once the "
            "other machine has finished writing."
            % (self._filename, copy_sentence),
            file=full)
        # Said in full here, so the once-per-session line in
        # _save_inner does not repeat it on the next save.
        self._block_reported = True
        self._save_outcome = "merge-refused"
        return False

    def _save_inner(self) -> bool:
        """Save Data to Disk. True only when the data reached the file.

        The return value is not decoration. Every refusal below - an
        empty document, the write-blocked latch, a merge that could not
        read the other session's copy, a held file - used to return None
        exactly like a completed save, so a caller that had ALREADY
        written asset content to disk could not tell that the index
        listing it never landed.

        Written to a sibling temp file first, then swapped in with
        hostos.replace_file (atomic on all three OSes, with a brief
        retry for Windows transient holds - cloud-sync clients and
        indexers briefly reopen the file after every change): a crash
        or kill mid-write must never leave a truncated library.json -
        it is the PRIMARY database and load() has no recovery path for
        it. A persistent hold is reported to the user instead of
        raised: callers are Qt slots, where an escaping exception only
        lands on stderr, and self._data keeps the new state so the next
        successful save persists it."""
        if not self._data:
            self._save_outcome = "empty-document"
            return False
        full = self._path + self._filename
        # STALE-WRITE GUARD: another session (the other Mac, the other
        # Houdini version) may have saved since this one loaded -
        # writing our in-memory copy blind would silently erase their
        # work. A changed file merges by asset id first: their NEW ids
        # are adopted, ids WE deleted stay deleted (they were present
        # at our load), and records both sides hold take OUR version
        # (this session is the active editor).
        # ONE read for the whole save: the stale-write guard and the
        # identical-write compare both need (len, sha256) of the file,
        # and nothing writes it between the two questions inside this
        # call - reading it twice cost a full parse-sized read per save
        # for an answer that could not differ.
        current_stat = self._stat_file()
        if self._disk_stat is not None and current_stat not in (
            None, self._disk_stat
        ):
            # REFUSE OVER OVERWRITE. This guard fires precisely when the
            # file changed underneath us - the two-Mac / cloud-sync case
            # - and the merge's only failure mode is "their file will
            # not parse right now", typically because it is mid-write.
            # It used to `return` and let save() carry straight on,
            # writing our copy over theirs: measured, 200 of their
            # assets gone, with only a debug.event nobody sees. And
            # snapshot_before_write is once-per-session, so a second
            # save in the same session left no copy at all.
            if not self._merge_from_disk(full):
                if getattr(self, "_format_ahead", False):
                    # The merge READ the peer fine - it refused because
                    # the peer's format is ahead. That is the format
                    # latch's case, not an unreadable-file case: fall
                    # through to the guard below, which says the true
                    # sentence and preserves nothing (their file needs
                    # no rescue - it is the newer one).
                    pass
                else:
                    return self._refuse_unreadable_peer(full)
        if getattr(self, "_write_blocked", False):
            # Set when a merge could not be performed, or when load()
            # refused an absent-but-known file. Refusing ONCE is not
            # enough: the next save would overwrite exactly what the
            # first one preserved.
            #
            # And it has to SAY so. This was a debug.event, which is
            # Debug-Mode gated and never prints - so a user whose edits
            # were being dropped got no line anywhere, the exact shape
            # practice.md forbids ("SAY WHY on every swallowed
            # failure"). It matters more now than it did: _write_blocked
            # used to need a two-session merge failure, and load() can
            # now latch it from a sync hiccup at panel open.
            #
            # Once per connector per session - save() is called from
            # ordinary sidebar use, and a line per save is a wall of
            # text nobody reads.
            if not getattr(self, "_block_reported", False):
                self._block_reported = True
                debug.note(
                    "not saving %s - it could not be read this session, "
                    "so writing now would put whatever little is in "
                    "memory over it. Your change is still on screen but "
                    "it is NOT on disk. Fix the file (or let the sync "
                    "finish), then restart Houdini."
                    % section_name(self._filename), file=full)
            debug.event("database", "save refused - writes blocked "
                        "this session", file=self._filename)
            self._save_outcome = "write-blocked"
            return False
        if getattr(self, "_format_ahead", False):
            # THE FORMAT LATCH: this library was saved by a newer
            # Amaze, so this build must not write a byte of it. Said
            # once per connector per session; the load-time alert
            # already told the user in full.
            if not getattr(self, "_format_reported", False):
                self._format_reported = True
                debug.note(
                    "not saving %s - it was saved by a newer Amaze, "
                    "and writing it from this one could damage it. "
                    "Your change is still on screen but NOT on disk. "
                    "Update Amaze, then save again."
                    % section_name(self._filename), file=full)
            debug.event("database", "save refused - library format "
                        "ahead", file=self._filename,
                        found=getattr(self, "_loaded_format", 0),
                        known=branding.LIBRARY_FORMAT)
            self._save_outcome = "format-ahead"
            return False
        loaded_version = int(
            getattr(self, "_loaded_version", SCHEMA_VERSION) or 0)
        if getattr(self, "_migration_incomplete", False):
            # THE STAMP MUST NOT CLAIM A MIGRATION THAT DID NOT RUN.
            # _migrate stops at the last successfully-applied version when
            # a step is missing from the chain - and save() then wrote
            # max(_loaded_version, SCHEMA_VERSION) over it, which undoes
            # the refusal completely. Reproduced live: SCHEMA_VERSION=3
            # with no step 2, and the file correctly said 2 after the
            # load and then wrongly said 3 after one ordinary save from
            # ordinary sidebar use.
            #
            # A wrong stamp is not cosmetic. The version is what every
            # other machine's load() decides from, so a file marked as
            # upgraded is never migrated again by ANY build - the data
            # stays at the old shape while every reader believes it is at
            # the new one, permanently, and silently. That is why this
            # ships before Versions, which is the next SCHEMA_VERSION
            # bump: with a half-upgraded fleet it would mis-stamp a
            # library on the first save.
            self._data["version"] = loaded_version
            debug.event("database", "version stamp held back - the "
                        "migration chain is incomplete",
                        file=self._filename, stamped=loaded_version,
                        target=SCHEMA_VERSION)
        else:
            # max(), not a blind stamp. _migrate correctly REFUSES to
            # touch a database from a newer build - and then save()
            # overwrote its version anyway. Verified: load a version 99
            # database, one save, and the file said version 2 with the
            # newer build's data still in it - so that machine re-runs
            # its whole migration chain over already-migrated data on the
            # next open.
            self._data["version"] = max(loaded_version, SCHEMA_VERSION)
        # THE FORMAT STAMP rides every write, never downgrading: a
        # newer peer's stamp survives the same way the schema version
        # does (and format-ahead already refused above, so reaching
        # here means ours is current or the file's is older).
        self._data["format"] = max(
            int(getattr(self, "_loaded_format", 0) or 0),
            branding.LIBRARY_FORMAT)
        # SKIP A WRITE THAT CHANGES NOTHING. The serialised document is
        # compared to what is on disk, and an identical one is not
        # written: every write costs a snapshot rotation, a sync upload
        # and a backup-system event downstream, so a no-op save should
        # be a no-op on disk too. Sync hygiene, explicitly not speed.
        serialised_stat = None
        try:
            import hashlib
            serialised = json.dumps(self._data, indent=4).encode("utf-8")
            serialised_stat = (len(serialised),
                               hashlib.sha256(serialised).hexdigest())
            # A merge above rewrote self._data, never the file, so the
            # stat from the top of this call is still the disk's.
            if current_stat is not None and current_stat == serialised_stat:
                # The disk already holds these exact bytes - remember
                # THAT, no third read.
                self._disk_stat = serialised_stat
                self._save_outcome = "identical-skip"
                return True
        except (TypeError, ValueError):
            pass                    # let the real writer report it

        hostos.snapshot_before_write(full)
        try:
            # Unique scratch name, fsync, atomic swap - all of it in
            # hostos so the four databases cannot drift apart. The old
            # shape wrote to a FIXED `full + ".tmp"`, which two savers
            # shared: measured 794 reads that parsed cleanly while
            # holding records from both writers.
            hostos.write_json_atomic(full, self._data, indent=4)
        except OSError as exc:
            debug.exception("database save", exc, file=full)
            # debug.alert, not hou.ui.displayMessage. There is no hou.ui
            # in a headless session - the thumbnail and report harnesses
            # both run there - so the raw call raised AttributeError
            # from inside this handler and replaced a legible "the file
            # is held" with an obscure one about a missing attribute.
            # alert() shows the dialog when there is a UI and prints
            # when there is not, and keys so a save per edit does not
            # re-interrupt.
            debug.alert(
                "Could not save the library database - the file is held"
                " by another program:\n" + full
                + "\n\nThe change is kept in memory and will be written"
                " with the next save.",
                key="database-file-held")
            self._save_outcome = "file-held"
            return False
        else:
            if serialised_stat is not None:
                # The bytes just written ARE the serialisation above -
                # write_json_atomic writes them verbatim (the
                # identical-skip guard depends on exactly that and its
                # test proves it) - so the baseline is derived, not
                # re-read: this was the third full read+hash per save.
                self._disk_stat = serialised_stat
            else:
                self._remember_disk_state()
            self._save_outcome = "stored"
            return True

    def take_adopted(self) -> list:
        """Rows adopted from another session's save, handed over exactly
        once so the model can insert them. Draining is deliberate: a
        second call must not re-insert the same rows."""
        rows = self._adopted
        self._adopted = []
        return rows

    def _merge_from_disk(self, full: str) -> bool:
        """Three-way merge against a database another session changed
        underneath us. Membership baseline = the ids present at OUR
        load: a disk id missing from memory is OUR deletion if it was
        in the baseline, THEIR addition if not. Categories and tags
        union; conflicting records take memory (the active editor)."""
        try:
            # utf-8-sig for the same reason as load(): a BOM'd peer
            # document would fail to parse here, and this failure path
            # latches _write_blocked for the session - so the cheap read
            # fix matters MORE here than in load().
            with open(full, encoding="utf-8-sig") as lib_json:
                disk = json.load(lib_json)
        except (OSError, ValueError) as exc:
            debug.event("database", "merge read failed",
                        file=self._filename, error=str(exc))
            return False
        # VALID JSON IS NOT A VALID DATABASE. The try/except above wraps
        # only the parse, so a peer document that is `[]`, `null`, or
        # `{"assets": null}` sailed past it and then raised
        # AttributeError/TypeError out of the lines below - straight out
        # of save(), which is a Qt slot, so it landed on stderr and
        # nowhere else. Reproduced live for all three shapes. Worse than
        # the crash: it bypassed the whole preserve/latch/tell-the-user
        # path that a merely TRUNCATED file gets, so the one file shape
        # that most needs preserving was the one shape that got none of
        # it. Returning False routes it into that path instead.
        malformed = wrong_shape(disk)
        if malformed:
            debug.event("database", "merge refused - not a database",
                        file=self._filename, reason=malformed)
            return False
        # CARRY THE DISK'S VERSION THROUGH. The unknown-key loop at the
        # end of this method cannot do it - "version" is always already in
        # self._data, so it is always skipped - and this merge runs
        # precisely when another session wrote the file, which is exactly
        # when that other session may be the NEWER build. Without this the
        # save that follows stamps our own version over theirs and the
        # newer machine re-runs its whole chain over migrated data.
        #
        # NOT WHEN OUR OWN CHAIN HAS A GAP, and that exception is the
        # whole reason this line is guarded. The two halves of this fix
        # otherwise fight each other: save() stamps `_loaded_version` when
        # _migration_incomplete is set, so raising it here to a peer's
        # higher number puts THAT number on a document whose rows the
        # missing migration step never touched. Measured: SCHEMA_VERSION 3
        # with no step 2, a v2 file, a peer that rewrites it at 3 - after
        # one ordinary save the file said 3 with two rows still v2-shaped.
        # No build will ever migrate them again, which is precisely the
        # permanent silent mis-stamp this step exists to prevent, reached
        # through the door this step opened.
        #
        # The two harms are not equal, and that is what decides the
        # direction. Holding the stamp down makes the newer machine re-run
        # a migration over data it has already migrated - wasteful, and
        # visible in its log. Raising it makes rows that were never
        # migrated permanently indistinguishable from rows that were -
        # silent, and unrecoverable without knowing which rows to look at.
        # Stamping low is the honest claim: "at least one row here is
        # still at the older shape."
        try:
            theirs_version = int(disk.get("version", 1))
        except (TypeError, ValueError):
            theirs_version = 1
        if getattr(self, "_migration_incomplete", False):
            debug.event("database", "peer version not carried through - "
                        "our migration chain is incomplete",
                        file=self._filename, theirs=theirs_version,
                        ours=int(getattr(self, "_loaded_version",
                                         SCHEMA_VERSION) or 0))
        elif theirs_version > int(
                getattr(self, "_loaded_version", SCHEMA_VERSION) or 0):
            self._loaded_version = theirs_version
        # A peer stamped AHEAD of this build's format arrived while we
        # ran - the other machine updated Amaze mid-session. Merging
        # our old-format state over its file is exactly the write the
        # stamp exists to stop, so the latch closes here and this save
        # refuses through the format guard.
        try:
            theirs_format = int(disk.get("format", 0) or 0)
        except (TypeError, ValueError):
            theirs_format = 0
        if theirs_format > branding.LIBRARY_FORMAT:
            self._loaded_format = theirs_format
            self._format_ahead = True
            debug.event("database", "peer library format ahead - "
                        "latched read-only mid-session",
                        file=self._filename, theirs=theirs_format,
                        known=branding.LIBRARY_FORMAT)
            return False
        ours = {
            str(a.get("id")): a for a in self._data.get("assets", [])
            if isinstance(a, dict)
        }
        adopted_rows = []
        for theirs in disk.get("assets", []):
            if not isinstance(theirs, dict):
                # Not a row. Left on disk untouched for whoever wrote
                # it; guessing at it is how one bad entry takes a save
                # down with it.
                debug.event('database', 'skipped a non-record asset entry',
                            file=self._filename, entry=repr(theirs)[:80])
                continue
            tid = str(theirs.get("id"))
            if tid not in ours and tid not in self._loaded_ids:
                self._data.setdefault("assets", []).append(theirs)
                adopted_rows.append(theirs)
            elif tid in ours:
                _merge_shared_metadata(ours[tid], theirs, self._filename)
        adopted = len(adopted_rows)
        # Handed to the MODEL after the write (see take_adopted). It
        # used to stop here: the row reached disk, _remember_disk_state
        # folded its id into _loaded_ids, and the model never learned of
        # it - so the NEXT save rebuilt assets[] from the model and wrote
        # the row out of existence. Measured: Mac A adds a material, Mac
        # B toggles a favourite -> disk 8 assets, model 7, second toggle
        # -> disk back to 7. Gone, and B's grid never showed it.
        self._adopted.extend(adopted_rows)
        # IN PLACE, never a rebind. Categories.__init__ and
        # MaterialLibrary.__init__ hold a direct alias to these list
        # objects, so `self._data[key] = merged` swaps the connector's
        # list for a new one and leaves the model pointing at the old
        # one. The adopted category reaches disk on this save and is
        # erased by the very next one, because the model still holds -
        # and re-serialises - the list without it.
        for key in ("categories", "tags"):
            existing = self._data.setdefault(key, [])
            for value in disk.get(key, []):
                if value not in existing:
                    existing.append(value)
        # category_colors is a DICT, and it was in neither list above -
        # so another session's colours were simply overwritten by ours,
        # or dropped entirely when this session had no colours at all.
        # Union by key; ours wins a genuine conflict, as with assets.
        theirs_colors = disk.get("category_colors")
        if isinstance(theirs_colors, dict):
            # In place for the same reason as the two lists above: a
            # rebind detaches any alias a model is holding.
            ours_colors = self._data.setdefault("category_colors", {})
            for name, colour in theirs_colors.items():
                ours_colors.setdefault(name, colour)
        # Anything else a NEWER build wrote and this one does not know
        # about: carry it through untouched rather than dropping it.
        for key, value in disk.items():
            if key not in self._data:
                self._data[key] = value
        debug.event(
            "database", "merged concurrent changes",
            file=self._filename, adopted_assets=adopted,
            disk_assets=len(disk.get("assets", [])),
            memory_assets=len(self._data.get("assets", [])),
        )

        # THE LATCH HEALS HERE, and only here. It was set nowhere but a
        # merge failure and cleared nowhere but __new__ and
        # reload_with_path - so the recovery the message prescribes
        # ("reopen Amaze") could not work: reopening re-enters load(),
        # which short-circuits on the data it already holds. A user who
        # fixed the file still could not save for the rest of the
        # session.
        #
        # A merge that SUCCEEDED is proof the peer file parses again,
        # which is the exact condition the latch was about. Nothing is
        # weakened: the next save re-derives the refusal from disk if
        # the file is bad again.
        #
        # NOT paired with moving the latch check above the stale-write
        # block, which the step also proposed. That ordering would
        # return False before the merge ever runs, so the latch could
        # never clear - the check has to stay below the thing that
        # heals it.
        if getattr(self, "_write_blocked", False):
            debug.event("database", "write block cleared - the file "
                        "merges again", file=self._filename)
            self._write_blocked = False
            self._block_reported = False

        return True

    def reload_with_path(self, path: str) -> dict:
        """Point this connector at a DIFFERENT library and read it.

        The latches belong to the FILE, not to the session. Clearing
        them is not optional: a connector is one process-wide instance
        per filename, and Preferences can switch libraries at any time
        (panel.switch_model_data -> library.reload_with_path). Measured
        on the fixed build before this line existed - library A with
        cops.json mid-sync latches _write_blocked, the user points
        Preferences at healthy library B, B loads its assets fine, and
        every save into B is silently dropped for the rest of the
        session. A guard that follows the user to a library it was
        never about is an outage.

        load() re-latches immediately if the NEW path has the same
        problem, so nothing is weakened - the refusal is re-derived from
        what is on disk rather than remembered.
        """
        # EVERYTHING NEEDED TO PUT IT BACK, captured first. This set
        # `_data = None` unconditionally with no try/except, so a load
        # that failed - a path with no library.json - left the connector
        # holding None for the life of the process. Every later save
        # short-circuits on `if not self._data` and is silently
        # discarded, while the panel keeps showing the rows it still has
        # in memory. The user sees a library that will not save and no
        # reason why.
        previous = (self._data, self._path, self._disk_stat,
                    set(self._loaded_ids),
                    getattr(self, "_loaded_version", SCHEMA_VERSION),
                    getattr(self, "_migration_incomplete", False),
                    getattr(self, "_write_blocked", False),
                    getattr(self, "_block_reported", False),
                    getattr(self, "_loaded_format", 0),
                    getattr(self, "_format_ahead", False),
                    getattr(self, "_format_reported", False))
        self._data = None
        self._write_blocked = False
        self._block_reported = False
        # Same reasoning as the two latches above: an incomplete
        # migration chain is a fact about THIS library's file, and
        # carrying it into the next one would hold that library's version
        # stamp back for no reason. load() re-derives it.
        self._migration_incomplete = False
        # The format latch is a fact about THIS library too - the next
        # one deserves a fresh read, and load() re-derives all three.
        self._loaded_format = 0
        self._format_ahead = False
        self._format_reported = False
        try:
            return self.load(path)
        except Exception:
            # Put the previous library back and re-raise: the caller
            # decides what a failed switch means, and it must not
            # inherit a connector that can no longer write.
            (self._data, self._path, self._disk_stat, self._loaded_ids,
             self._loaded_version, self._migration_incomplete,
             self._write_blocked, self._block_reported,
             self._loaded_format, self._format_ahead,
             self._format_reported) = previous
            debug.event("database", "library switch failed - previous "
                        "library restored", file=self._filename,
                        attempted=path)
            raise
