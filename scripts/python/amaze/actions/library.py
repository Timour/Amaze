"""Opening a library: the steps that need no panel. ▸archive/actions/library.py"""

import json
import os

from amaze import messages
from amaze.core import captures, database, debug, library_policy, locations
from amaze.helpers import hostos
from amaze.prefs import prefs as prefs_mod


def index_unreadable(lib_dir: str) -> bool:
    """A list on disk the library cannot load: it does not parse, or it is not shaped like one."""
    if not lib_dir:
        return False
    try:
        with open(os.path.join(lib_dir, "library.json"), "rb") as handle:
            raw = handle.read()
    except OSError:
        return False    # a missing list is not an unreadable one
    if not hostos.parses_as_json(raw):
        return True
    return bool(database.wrong_shape(json.loads(raw.decode("utf-8-sig"))))


def index_unopenable(lib_dir: str) -> str:
    """Why the list will not OPEN here, "" when it opens or is absent - closed, never one for Repair."""
    if not lib_dir:
        return ""
    path = os.path.join(lib_dir, "library.json")
    try:
        with open(path, "rb"):
            return ""
    except (FileNotFoundError, NotADirectoryError):
        return ""    # absent: `index_present` answers that
    except OSError as exc:
        cause, why = hostos.why_failed(exc, path)
        if cause == hostos.FAILED_READ_ONLY:    # its sentence is a WRITE's; a refused read is permissions
            return messages.LIBRARY_INDEX_READ_NOT_PERMITTED % path
        return why


def index_present(lib_dir: str) -> bool:
    """Whether `lib_dir` holds a list at all; an empty folder has none until `prepare` seeds one."""
    return bool(lib_dir) and os.path.isfile(os.path.join(lib_dir, "library.json"))


def list_not_arrived(lib_dir: str) -> bool:
    """A folder that has held a library and has no list now, which `prepare` will not seed over."""
    return (prefs_mod.can_hold_a_library(lib_dir) and not index_present(lib_dir)
            and bool(starter_would_overwrite(lib_dir)))


def newer_version(preferences) -> int:
    """The version of a library a newer Amaze updated, which this one leaves closed; else 0."""
    library_dir = str(preferences.dir or "")
    found = library_policy.library_version(library_dir) if library_dir else 0
    return found if found > library_policy.LIBRARY_VERSION else 0


def starter_would_overwrite(lib_dir: str) -> list:
    """The evidence that `lib_dir` has held a library, or []; `prepare` asks this before seeding."""
    found = []
    evidence = database.absent_but_known(lib_dir, "library.json")
    if evidence:
        found.append(evidence)
    for name in ("mat", "img"):
        folder = os.path.join(lib_dir, name)
        if os.path.isdir(folder) and os.listdir(folder):
            found.append(name + "/")
    return found


def prepare(preferences) -> None:
    """The library folder ready to open: a starter index in an empty one, img/ and mat/ always."""
    lib_dir = preferences.dir
    if not prefs_mod.can_hold_a_library(lib_dir):    # once wrote "//library.json"
        debug.event("session", "no library directory set", dir=lib_dir)
        return
    new_folder = False
    if not os.path.exists(preferences.dir + "/library.json"):
        held = starter_would_overwrite(preferences.dir)    # ABSENT IS NOT EMPTY: never seed over it
        if held:
            debug.event("session", "starter NOT seeded - the "
                        "directory has held a library",
                        dir=preferences.dir, evidence=held)
            debug.alert(
                messages.STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY,
                key="starter-refused")
            return
        prefs_mod.seed_starter_index(preferences.dir)    # stamped on the way in ▸p/library-creation-doors
        new_folder = True
    if ensure_library_dirs(preferences):
        new_folder = True
    if new_folder:
        debug.event("session", "library created", dir=preferences.dir)


def ensure_library_dirs(preferences) -> bool:
    """img/ and mat/ made, each asked on its own rather than as a pair; True if either was made."""
    made = False
    for tail in (preferences.img_dir, preferences.asset_dir):
        folder = os.path.join(preferences.dir, tail)
        if not os.path.isdir(folder):
            made = True
        os.makedirs(folder, exist_ok=True)
    return made


def update(preferences) -> bool:
    """The library to this Amaze's version before any tile paints; True once its version moved."""
    library_dir = str(preferences.dir or "")
    if not library_dir or not locations.ready(preferences):
        return False    # no file keys yet: a capture moved now would miss its tile
    if captures.machine_capture_count():    # no question: installing this Amaze was the choice
        captures.adopt_machine_captures(preferences)
    if library_policy.library_version(library_dir) < library_policy.LIBRARY_VERSION:
        library_policy.set_library_version(library_dir, library_policy.LIBRARY_VERSION)
        return True
    return False


def seed_starters(code_model, code_categories, gradient_model, gradient_categories) -> None:
    """The shipped starters, once per library: the Code section's Examples, the Colors palettes."""
    if code_model is not None:
        code_model.seed_starter_snippets(code_categories)
    if gradient_model is not None:
        gradient_model.seed_curated_palettes(gradient_categories)
