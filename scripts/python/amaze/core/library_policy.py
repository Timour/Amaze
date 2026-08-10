"""
Settings that belong to the LIBRARY, not to the person using it.

`prefs.Prefs` lives in the OS preferences directory: per-user,
per-machine, never synced. That is right for "how big are my tiles" and
wrong for anything protecting the shared library, because a safety
switch that only one machine can see protects nobody - it would read as
protection while offering none.

So this file sits BESIDE library.json, travels with the library, and
every session that opens the library obeys it.

NOT A LOCK. A lock is a transient claim on write access, and those
cannot work over a sync folder - no atomicity, no leases, no way to tell
a dead holder from a slow one. This is a persistent PROPERTY: read on
open, changed rarely, and last-write-wins is honest for it. It needs
none of the machinery a real lock would, which is exactly why it works
where a lock would not.

Its own file, deliberately - not a key inside library.json. Flipping a
boolean must not mean rewriting 548 asset records, and reading it must
not mean parsing 355KB. A few hundred bytes that no asset write ever
touches also means it cannot collide with one.

FAILS CLOSED. A policy file that exists but will not parse is read as
the most restrictive setting, never the most permissive: "I could not
check" must not mean "go ahead". An ABSENT file means allow, so
libraries written before this existed keep working unchanged.
"""

import json
import os

from amaze.core import debug
from amaze.helpers import hostos

#: Schema version for the file itself, so a future setting can be added
#: without a newer build's file being misread by an older one.
POLICY_VERSION = 1

FILENAME = "policy.json"

#: What an absent file means, per setting. Absent = the library predates
#: this mechanism, so nothing may change behaviour its owner did not ask
#: for.
DEFAULTS = {
    "allow_overwrite": True,
}


def path_for(library_dir: str) -> str:
    return os.path.join(library_dir or "", FILENAME)


def read(library_dir: str) -> dict:
    """The library's policy, merged over the defaults.

    Never raises: this is consulted on paths that must not be able to
    fail (opening the panel, saving a material), so a broken file
    degrades to the SAFE reading rather than to an exception.
    """
    settings = dict(DEFAULTS)
    path = path_for(library_dir)
    if not path:
        return settings
    # ABSENT and BROKEN are different answers, and isfile() conflates
    # them: a dangling symlink and a directory sitting where the file
    # should be both return False from isfile - and both then read as
    # "the library predates this mechanism", which is the PERMISSIVE
    # default. lexists() sees the dangling link; isdir() sees the
    # directory. Either is a damaged policy, and a policy we cannot
    # read fails closed by this module's own contract.
    if os.path.islink(path) and not os.path.exists(path):
        debug.note(
            "the library's policy.json is a link that points at nothing, "
            "so the most restrictive settings are in force. Fix or delete "
            "it to change that.", path=path)
        return {key: False for key in DEFAULTS}
    if os.path.isdir(path):
        debug.note(
            "there is a folder where the library's policy.json should "
            "be, so the most restrictive settings are in force. Remove "
            "it to change that.", path=path)
        return {key: False for key in DEFAULTS}
    if not os.path.isfile(path):
        # ABSENT IS ONLY "NEW" WHEN NOTHING SAYS IT WAS EVER HERE.
        # Every other branch of this function fails CLOSED, which is
        # the module's stated contract; absence returned the permissive
        # defaults on the reasoning that "the library predates this
        # mechanism". That conflates "never had one" with "has one and
        # it is not here right now" - and _write snapshots, so a
        # library that ever set a policy carries policy.json.bak-1
        # beside it. Reproduced: allow_overwrite False with the file
        # present, True the moment it was momentarily gone, which is
        # the one protection whose whole point is being checked at the
        # library layer rather than beside a caller.
        trace = ""
        try:
            trace = hostos.existed_before(path)
        except OSError:
            trace = ""
        if trace:
            debug.note(
                "the library's policy.json is not there right now, but "
                "%s beside it says there was one, so the most "
                "restrictive settings are in force until it comes back."
                % trace, path=path)
            return {key: False for key in DEFAULTS}
        return settings
    try:
        # utf-8-sig: this is the one library file a user is INVITED to
        # hand-edit, and Windows Notepad prepends a BOM - which made
        # the parse raise, and fail-closed then read a healthy
        # permissive policy as the most restrictive one.
        with open(path, encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("policy is %s, not an object"
                             % type(loaded).__name__)
    except Exception as exc:                             # noqa: BLE001
        # Fail CLOSED - every default here is the permissive one, so a
        # file we cannot read must NOT fall back to them.
        debug.note(
            "the library's policy.json could not be read (%s), so the "
            "most restrictive settings are in force. Fix or delete the "
            "file to change that." % exc, path=path)
        return {key: False for key in DEFAULTS}
    for key in DEFAULTS:
        if key not in loaded:
            continue
        value = loaded[key]
        # A TYPE CHECK, not bool(). bool("false") is True - so a policy
        # hand-edited to the string "false", the most natural way to
        # write it wrong, silently read as PERMISSIVE. A value that is
        # not a real boolean is a damaged policy: fail closed and say so.
        if isinstance(value, bool):
            settings[key] = value
        else:
            debug.note(
                'the library\'s policy.json has "%s" set to %r, which is '
                "not a yes-or-no value, so the most restrictive setting "
                "is in force for it. Use true or false, unquoted."
                % (key, value), path=path)
            settings[key] = False
    return settings


def allow_overwrite(library_dir: str) -> bool:
    """Whether saving over an existing material is permitted HERE.

    Off makes the library append-only, which does not merely reduce the
    lost-update conflict between two writers - it removes it, because
    there is no path that replaces content someone else may be holding.
    """
    return bool(read(library_dir).get("allow_overwrite", True))


def set_allow_overwrite(library_dir: str, allowed: bool) -> bool:
    """Persist the setting into the LIBRARY. True if it was written."""
    return _write(library_dir, {"allow_overwrite": bool(allowed)})


def _write(library_dir: str, changes: dict) -> bool:
    path = path_for(library_dir)
    # The only library JSON with zero backup coverage until now.
    hostos.snapshot_before_write(path)
    # Whether this write CREATES the file, asked before it does.
    # snapshot_before_write rightly declines a path that is not there
    # yet, so a policy set once and then left alone - which is what
    # setting a policy normally looks like - had no `.bak-first`, no
    # `.unreadable` and no marker. read()'s absent-but-known branch
    # then had no evidence to find, so the one guard that must survive
    # a momentarily-missing file could never fire for the file it
    # guards. Seeded below, from the file this call is about to write.
    created = not os.path.isfile(path)
    if not library_dir or not os.path.isdir(library_dir):
        debug.event("policy", "not written - no library directory",
                    path=path)
        return False
    current = {}
    if os.path.isfile(path):
        try:
            # utf-8-sig, same reason as read(): a Notepad BOM must not
            # make the write path treat the file as unreadable and
            # replace it, dropping its other keys.
            with open(path, encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                current = loaded
        except Exception as exc:                         # noqa: BLE001
            # Preserve what we could not read before replacing it - the
            # same policy the databases follow.
            #
            # ONLY CLAIM THE COPY WHEN THERE IS ONE. This sentence was
            # unconditional, and preserve_unreadable has three paths that
            # create nothing - a 0-byte source, a copy that already exists,
            # and a failed copy - so it sent people looking for a file that
            # was not there. The same untrue reassurance was fixed in
            # database.py's refusal; it was here too.
            kept = hostos.preserve_unreadable(path, why="library policy")
            copy_sentence = ("; a copy is beside it as %s"
                             % os.path.basename(kept)) if kept else ""
            debug.note("the previous policy.json could not be read (%s)%s"
                       % (exc, copy_sentence), path=path)
    current.update(changes)
    current["version"] = POLICY_VERSION
    try:
        # A UNIQUE scratch name, not the fixed `path + ".writing"` this
        # used: two writers of one destination shared that single buffer.
        # This file is small and written rarely, which makes a collision
        # unlikely and not impossible - and it is the file that decides
        # whether overwriting a material is permitted at all, so a
        # half-written one is read as the most restrictive setting and
        # blocks real work. Same helper as every other writer here, so
        # the four cannot drift apart again.
        hostos.write_json_atomic(path, current, indent=2)
    except OSError as exc:
        debug.note("could not write the library policy (%s)" % exc,
                   path=path)
        return False
    if created:
        # THE FLOOR, FROM THE FIRST WRITE - the same line keyed_store
        # carries, and for the same reason its docstring gives: this
        # writes no new KIND of file, it makes the documented
        # `.bak-first` arrive one write earlier so absence is
        # answerable.
        hostos.seed_restore_floor(path)
    debug.event("policy", "written", path=path, **changes)
    return True
