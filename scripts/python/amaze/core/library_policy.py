"""Settings belonging to the LIBRARY rather than the person, in their own file beside `library.json`. FAILS CLOSED: anything unreadable reads as the most restrictive setting, never the most permissive - `I could not check` must not mean `go ahead`. ▸archive/library_policy.py"""

import json
import os

from amaze.core import debug
from amaze.helpers import hostos

POLICY_VERSION = 1

FILENAME = "policy.json"

DEFAULTS = {
    "allow_overwrite": True,
}


def path_for(library_dir: str) -> str:
    return os.path.join(library_dir or "", FILENAME)


def read(library_dir: str) -> dict:
    """The library's policy over the defaults. NEVER RAISES - it is consulted while opening the panel and saving a material, so every damaged shape degrades to the restrictive reading instead."""
    settings = dict(DEFAULTS)
    path = path_for(library_dir)
    if not path:
        return settings
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
        with open(path, encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("policy is %s, not an object"
                             % type(loaded).__name__)
    except Exception as exc:                             # noqa: BLE001
        debug.note(
            "the library's policy.json could not be read (%s), so the "
            "most restrictive settings are in force. Fix or delete the "
            "file to change that." % exc, path=path)
        return {key: False for key in DEFAULTS}
    for key in DEFAULTS:
        if key not in loaded:
            continue
        value = loaded[key]
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
    """Whether saving over an existing material is permitted HERE - off makes the library append-only."""
    return bool(read(library_dir).get("allow_overwrite", True))


def set_allow_overwrite(library_dir: str, allowed: bool) -> bool:
    """Persist the setting into the LIBRARY. True if it was written."""
    return _write(library_dir, {"allow_overwrite": bool(allowed)})


def _write(library_dir: str, changes: dict) -> bool:
    """Merges `changes` into the library's policy. `created` is asked BEFORE the write and seeds the restore floor after it - without that floor, `read()` cannot tell a library that never had a policy from one whose file is momentarily missing."""
    path = path_for(library_dir)
    hostos.snapshot_before_write(path)
    created = not os.path.isfile(path)
    if not library_dir or not os.path.isdir(library_dir):
        debug.event("policy", "not written - no library directory",
                    path=path)
        return False
    current = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                current = loaded
        except Exception as exc:                         # noqa: BLE001
            kept = hostos.preserve_unreadable(path, why="library policy")
            copy_sentence = ("; a copy is beside it as %s"
                             % os.path.basename(kept)) if kept else ""
            debug.note("the previous policy.json could not be read (%s)%s"
                       % (exc, copy_sentence), path=path)
    current.update(changes)
    current["version"] = POLICY_VERSION
    try:
        hostos.write_json_atomic(path, current, indent=2)
    except OSError as exc:
        debug.note("could not write the library policy (%s)" % exc,
                   path=path)
        return False
    if created:
        hostos.seed_restore_floor(path)
    debug.event("policy", "written", path=path, **changes)
    return True
