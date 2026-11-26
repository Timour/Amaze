"""Opening a library: the steps that need no panel. ▸archive/actions/library.py"""

import os

from amaze import messages
from amaze.core import debug, guard, library_files, library_policy
from amaze.core import library_settings, material
from amaze.helpers import hostos
from amaze.prefs import prefs as prefs_mod


def index_unreadable(lib_dir: str, name: str = library_files.MATERIALS) -> bool:
    """Whether database `name`, the Materials one by default, is there but cannot be read."""
    if not lib_dir or not os.path.isdir(lib_dir):
        return False
    return guard.Guard(lib_dir).read(name).verdict == guard.CORRUPT


def index_unopenable(lib_dir: str) -> str:
    """Why the library cannot OPEN here, `""` when it opens or is absent; never one for Repair."""
    if not lib_dir:
        return ""
    path = os.path.join(lib_dir, library_files.MASTER)
    try:
        with open(path, "rb"):
            pass
    except (FileNotFoundError, NotADirectoryError):
        return ""    # absent: `index_present` checks that
    except OSError as exc:
        cause, why = hostos.why_failed(exc, path)
        if cause == hostos.FAILED_READ_ONLY:    # its message is for a WRITE; a denied read is a permissions problem
            return messages.LIBRARY_INDEX_READ_NOT_PERMITTED % path
        return why
    return messages.LIBRARY_OLDER_THAN_2_0 if older_than_2_0(lib_dir) else ""


def older_than_2_0(lib_dir: str) -> int:
    """The version of a library older than format 2.0, which this Amaze neither opens nor marks."""
    found = library_settings.library_version(lib_dir) if lib_dir else 0
    return found if 0 < found < library_policy.LAYOUT_2_0 else 0


def index_present(lib_dir: str) -> bool:
    """Whether `lib_dir` holds a library: its `DataBase.json`."""
    return bool(lib_dir) and os.path.isfile(os.path.join(lib_dir, library_files.MASTER))


def folder_not_empty_without_library(lib_dir: str) -> bool:
    """Whether the folder holds no library and is not empty: a new library needs an empty folder."""
    return (prefs_mod.can_hold_a_library(lib_dir) and not index_present(lib_dir)
            and bool(starter_would_overwrite(lib_dir)))


def newer_version(preferences) -> int:
    """The library's version if a newer Amaze wrote it, so this one does not open it; else 0."""
    library_dir = str(preferences.dir or "")
    found = library_settings.library_version(library_dir) if library_dir else 0
    return found if found > library_policy.LIBRARY_VERSION else 0


def starter_would_overwrite(lib_dir: str) -> list:
    """The files in `lib_dir` other than OS files, or []; `prepare` checks before creating one."""
    try:
        return sorted(name for name in os.listdir(lib_dir)
                      if not library_files.is_os_noise(name))
    except OSError:
        return []


def prepare(preferences) -> None:
    """Prepare the library folder: `DataBase.json` in an empty one, and each section's folder."""
    lib_dir = preferences.dir
    if not prefs_mod.can_hold_a_library(lib_dir):
        debug.event("session", "no library directory set", dir=lib_dir)
        return
    new_folder = False
    if not index_present(lib_dir):
        held = starter_would_overwrite(lib_dir)    # a new library is created only in an empty folder
        if held:
            debug.event("session", "library NOT created - the folder is not empty",
                        dir=lib_dir, evidence=held[:10])
            debug.alert(messages.LIBRARY_FOLDER_NOT_EMPTY, key="starter-refused")
            return
        prefs_mod.create_library(lib_dir)
        new_folder = True
    if ensure_library_dirs(preferences):
        new_folder = True
    if new_folder:
        debug.event("session", "library created", dir=lib_dir)


def ensure_library_dirs(preferences) -> bool:
    """Create each asset section's folder, each checked separately; True if one was created."""
    made = False
    for folder in [material.section_folder(preferences.dir, section)
                   for section in library_files.ASSET_SECTIONS]:
        if not os.path.isdir(folder):
            made = True
        os.makedirs(folder, exist_ok=True)
    return made


def update(preferences) -> bool:
    """Expire the old trash, stamp this Amaze's library version; True when the version changed."""
    library_dir = str(preferences.dir or "")
    if not library_dir or not os.path.isdir(library_dir) or older_than_2_0(library_dir):
        return False
    from amaze.core import library_db, locations
    library_db.guard_of(preferences).expire_trash()
    locations.fold_duplicate_ids(preferences)
    before = library_settings.library_formats(library_dir)
    if all(found >= ours for found, ours in zip(before, library_settings.THIS_AMAZE)):
        return False
    return library_settings.stamp_version(preferences)


def seed_starters(code_model, code_categories, gradient_model, gradient_categories) -> None:
    """Add shipped starters once per library: the Code section's Examples, the Colors palettes."""
    if code_model is not None:
        code_model.seed_starter_snippets(code_categories)
    if gradient_model is not None:
        gradient_model.seed_curated_palettes(gradient_categories)
