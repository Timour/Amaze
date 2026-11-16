"""Opening a library: the steps that need no panel. ▸archive/actions/library.py"""

import os

from amaze import messages
from amaze.core import debug, guard, library_conversion, library_files, library_policy
from amaze.core import library_settings, material
from amaze.helpers import hostos
from amaze.prefs import prefs as prefs_mod


def index_unreadable(lib_dir: str) -> bool:
    """The Materials database is there and does not read: Repair can restore or rebuild it."""
    if not lib_dir or not os.path.isdir(lib_dir) or library_conversion.needs_conversion(lib_dir):
        return False
    return guard.Guard(lib_dir).read(library_files.MATERIALS).verdict == guard.CORRUPT


def index_unopenable(lib_dir: str) -> str:
    """Why the library will not OPEN here, "" when it opens or is absent; never one for Repair."""
    if not lib_dir:
        return ""
    path = os.path.join(lib_dir, library_files.MASTER)
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
    """Whether `lib_dir` holds a library: its `DataBase.json`, or an older library to convert."""
    return bool(lib_dir) and (os.path.isfile(os.path.join(lib_dir, library_files.MASTER))
                              or library_conversion.needs_conversion(lib_dir))


def list_not_arrived(lib_dir: str) -> bool:
    """A folder that has held a library and has none now, which `prepare` will not seed over."""
    return (prefs_mod.can_hold_a_library(lib_dir) and not index_present(lib_dir)
            and bool(starter_would_overwrite(lib_dir)))


def newer_version(preferences) -> int:
    """The version of a library a newer Amaze wrote, which this one leaves closed; else 0."""
    library_dir = str(preferences.dir or "")
    found = library_settings.library_version(library_dir) if library_dir else 0
    return found if found > library_policy.LIBRARY_VERSION else 0


def starter_would_overwrite(lib_dir: str) -> list:
    """The evidence that `lib_dir` has held a library, or []; `prepare` asks this before seeding."""
    found = []
    for name in (library_files.BACKUP_FOLDER, library_files.RENDER_FOLDER) + tuple(
            library_files.SECTION_FOLDERS[section] for section in library_files.ASSET_SECTIONS):
        folder = os.path.join(lib_dir, name)
        if os.path.isdir(folder) and os.listdir(folder):
            found.append(name + "/")
    found.extend(name for name in library_files.LISTS + (library_files.FILES,)
                 if os.path.isfile(os.path.join(lib_dir, name)))
    return found


def prepare(preferences) -> None:
    """The library folder ready to open: `DataBase.json` in an empty one, each section's folder."""
    lib_dir = preferences.dir
    if not prefs_mod.can_hold_a_library(lib_dir):
        debug.event("session", "no library directory set", dir=lib_dir)
        return
    new_folder = False
    if not index_present(lib_dir):
        held = starter_would_overwrite(lib_dir)    # ABSENT IS NOT EMPTY: never seed over it
        if held:
            debug.event("session", "library NOT created - the directory has held a library",
                        dir=lib_dir, evidence=held)
            debug.alert(messages.STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY,
                        key="starter-refused")
            return
        prefs_mod.create_library(lib_dir)
        new_folder = True
    if ensure_library_dirs(preferences):
        new_folder = True
    if new_folder:
        debug.event("session", "library created", dir=lib_dir)


def ensure_library_dirs(preferences) -> bool:
    """img/ and each asset section's folder made, each asked on its own; True if one was made."""
    made = False
    for folder in [os.path.join(preferences.dir, preferences.img_dir)] + [
            material.section_folder(preferences.dir, section)
            for section in library_files.ASSET_SECTIONS]:
        if not os.path.isdir(folder):
            made = True
        os.makedirs(folder, exist_ok=True)
    return made


def update(preferences) -> bool:
    """The library at this Amaze's version, its old trash expired; True once its version moved."""
    library_dir = str(preferences.dir or "")
    if not library_dir or not os.path.isdir(library_dir):
        return False
    from amaze.core import library_db
    library_db.guard_of(preferences).expire_trash()
    before = library_settings.library_version(library_dir)
    if before >= library_policy.LIBRARY_VERSION:
        return False
    return library_settings.stamp_version(preferences)


def seed_starters(code_model, code_categories, gradient_model, gradient_categories) -> None:
    """The shipped starters, once per library: the Code section's Examples, the Colors palettes."""
    if code_model is not None:
        code_model.seed_starter_snippets(code_categories)
    if gradient_model is not None:
        gradient_model.seed_curated_palettes(gradient_categories)
