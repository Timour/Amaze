"""The one naming convention of a library folder; stdlib only, the audit tool loads it by path."""

import os
import re

MASTER = "DataBase.json"    # policy, shared settings, users, the manifest, the starter marks
MATERIALS = "materials.json"
NODES = "nodes.json"
CODE = "code.json"
COLORS = "colors.json"
FILES = "files.json"
LISTS = (MATERIALS, NODES, CODE, COLORS)    # the sections whose rows are assets
DATABASES = (MASTER,) + LISTS + (FILES,)    # `guard.DATABASES`, held equal by a test
ROOT_FILES = DATABASES
JOURNAL = ".amaze-journal"    # `guard.JOURNAL`: there only while a change is being applied
BACKUP_FOLDER = "backup"    # `guard.BACKUP_DIR`
TRASH_FOLDER = "trash"    # `guard.TRASH_DIR`, one folder per day

SECTION_FOLDERS = {    # THE table: a section's database, and the folder for what its rows own
    MATERIALS: "materials",
    NODES: "nodes",
    CODE: "code",
    COLORS: "colors",
}
LABELS = {MASTER: "Library", MATERIALS: "Materials", NODES: "Nodes", CODE: "Code",
          COLORS: "Colors", FILES: "Files"}    # what the user reads for each database
NOUNS = {MASTER: "user", MATERIALS: "material", NODES: "node", CODE: "snippet",
         COLORS: "color", FILES: "location"}    # what one counted entry is called
ASSET_SECTIONS = (MATERIALS, NODES)    # whose rows own asset files
ORPHAN_SECTION = MATERIALS    # where a file no database names goes, and is reported from

VERSIONS = "versions"    # a section folder's one sub-folder; its top holds the asset files
RENDER_FOLDER = "img"    # `img/comments/`, which no section owns
CAPTURE_FOLDER = "captures"    # `captures/file_<hex>.png`, the Files section's
CODE_FOLDER = SECTION_FOLDERS[CODE]
PACKAGE_FOLDER = "matX"    # a permanent store: the check does not enter it, the audit looks for scratch only
COMMENT_FOLDER = "comments"    # `img/comments/`, the pictures pasted into comments; `notes.IMAGE_DIR`
IMPORT_FOLDER = "import"    # where Package Import writes plain files: a File location, its contents the user's
LEDGER = "versions.json"

RECORD_SUFFIX = ".json"    # `<id>.json`: metadata and builder, `core/asset_record.py`
PICTURE_SUFFIX = ".png"    # `<id>.png`: the asset's one picture, rendered or captured
ASSET_SUFFIXES = (".mat", RECORD_SUFFIX)    # `repair.ASSET_SIDECARS`
COMPANION_TAIL = "_cop"    # `<id>_cop.mat`, a material's companion COP network
VERSION_SUFFIXES = (".mat", RECORD_SUFFIX, PICTURE_SUFFIX)
CODE_VERSION_SUFFIX = ".txt"

SCRATCH_TAILS = (".writing", ".capturing", ".tmp", ".temp", ".new", ".part",    # a write of ours that died partway
                 ".partial", ".lock", ".swp", "~", ".repairing", ".rollback")
SCRATCH_INFIXES = (".rendering.", ".capturing.")    # a render or capture scratch keeps its image extension last
SCRATCH_PREFIX = ".amaze_scratch"

OS_NOISE = (".DS_Store", "Thumbs.db", "desktop.ini", ".Spotlight-V100",    # the system's own, left alone and not reported
            ".fseventsd", ".TemporaryItems")

LIST = "list"    # the kinds that belong in a library
JOURNAL_FILE = "journal"
BACKUP = "backup"            # anything in `backup/`
ASSET = "asset"              # `materials/<id>.mat`
RECORD = "record"            # `materials/<id>.json`
COMPANION = "companion"
RENDER = "render"            # `materials/<id>.png`, the asset's one picture
FILE_CAPTURE = "file-capture"    # `captures/file_<40 hex>.png`
COMMENT_IMAGE = "comment-image"    # `img/comments/<32 hex>.<ext>`
VERSION = "version"
VERSION_LEDGER = "ledger"
PACKAGE = "package"
FOLDER = "folder"            # a folder the convention names
SCRATCH = "scratch"    # and the kinds that do not
DUPLICATE = "duplicate"      # a known name with ` <n>` before its last suffix: a sync service's second copy
UNKNOWN = "unknown"
OS_NOISE_KIND = "os-noise"
UNREADABLE = "unreadable"    # a folder `walk` could not list; its detail is the error
SUPERSEDED = "superseded"    # what the format 4 conversion left behind; `library_conversion` names it

KNOWN = frozenset((LIST, JOURNAL_FILE, BACKUP, ASSET, RECORD, COMPANION, RENDER, FILE_CAPTURE,
                   COMMENT_IMAGE, VERSION, VERSION_LEDGER, PACKAGE, FOLDER))
COPIES = frozenset((BACKUP,))    # a duplicate of one of these is swept whatever its bytes
OUT_OF_PLACE = frozenset((SCRATCH, DUPLICATE, UNKNOWN))    # `walk` stats these, and only these

_VERSION_STEM = re.compile(r"^([^\W_]+)_(\d+)$")    # `<id>_<n>`, the id its folder's name
_FILE_CAPTURE = re.compile(r"^file_[0-9a-f]{40}\.png$")
_COMMENT_IMAGE = re.compile(r"^[0-9a-f]{32}\.\w+$")
_COPY_NUMBER = re.compile(r" \d+(?=\.|$)")


def section_label(database: str) -> str:
    """What the user reads for a database, like `Nodes`; the name itself for one unknown."""
    return LABELS.get(database, database)


def section_noun(database: str, count: int = 2) -> str:
    """What one of its entries is called, singular or plural by `count`: `material`, `nodes`."""
    noun = NOUNS.get(database, "saved thing")
    return noun if count == 1 else noun + "s"


def section_of_folder(name: str) -> str:
    """The section database whose folder is called `name`, or ""."""
    return next((db for db, folder in SECTION_FOLDERS.items() if folder == name), "")


def owns_assets(top: str) -> bool:
    """Whether top folder `top` is an asset section's folder."""
    return section_of_folder(top) in ASSET_SECTIONS


def asset_id(name: str, extensions: tuple, tail: str = ""):
    """The asset id `name` belongs to, or None: the stem must be one run of letters and digits."""
    lowered = name.lower()
    matched = next((e for e in extensions if lowered.endswith(e.lower())), None)
    if matched is None:
        return None
    stem = name[: -len(matched)]
    if tail and stem.endswith(tail):
        stem = stem[: -len(tail)]
    if not stem.isalnum():    # a dot, a space, a dash or an underscore: not a name Amaze writes
        return None
    return stem


def is_scratch(name: str) -> bool:
    lowered = name.lower()
    return (lowered.endswith(SCRATCH_TAILS) or name.startswith(SCRATCH_PREFIX)
            or any(infix in lowered for infix in SCRATCH_INFIXES))


def is_os_noise(name: str) -> bool:
    return name in OS_NOISE or name.startswith("._")


def _root(name: str):
    if name in DATABASES:
        return LIST, name
    if name == JOURNAL:
        return JOURNAL_FILE, name
    return None


def _backup(name: str):
    """(BACKUP, the database it copies) for a file in `backup/`; None for one of no database."""
    base = next((one for one in DATABASES if name.startswith(one + ".")), "")
    return (BACKUP, base) if base else None


def _asset_folder(name: str):
    if name[: -len(".mat")].endswith(COMPANION_TAIL):
        found = asset_id(name, (".mat",), COMPANION_TAIL)
        if found:
            return COMPANION, found
    for suffix, kind in ((".mat", ASSET), (RECORD_SUFFIX, RECORD), (PICTURE_SUFFIX, RENDER)):
        found = asset_id(name, (suffix,))
        if found:
            return kind, found
    return None


def _picture(name: str):
    found = asset_id(name, (PICTURE_SUFFIX,))
    return (RENDER, found) if found else None


def version_number(name: str, owner: str, suffixes: tuple):
    """The version number `<owner>_<n><suffix>` names, or None for any other name."""
    for suffix in suffixes:
        if name.endswith(suffix):
            found = _VERSION_STEM.match(name[: -len(suffix)])
            if found and found.group(1) == owner:
                return int(found.group(2))
    return None


def _version_folder(name: str, suffixes: tuple, owner: str):
    if name == LEDGER:
        return VERSION_LEDGER, name
    if version_number(name, owner, suffixes) is not None:
        return VERSION, name[: name.rindex(".")]
    return None


def _folder(parts: list) -> bool:
    """Whether the folder at `parts` is one the convention names."""
    depth = len(parts)
    top = parts[0]
    if depth == 1:
        return top in tuple(SECTION_FOLDERS.values()) + (
            RENDER_FOLDER, CAPTURE_FOLDER, PACKAGE_FOLDER, IMPORT_FOLDER, BACKUP_FOLDER,
            TRASH_FOLDER)
    if top in (PACKAGE_FOLDER, TRASH_FOLDER):
        return True
    if parts == [RENDER_FOLDER, COMMENT_FOLDER]:
        return True
    if (owns_assets(top) or top == CODE_FOLDER) and parts[1] == VERSIONS:
        return depth == 2 or (depth == 3 and parts[2].isalnum())
    return False


def _plain(parts: list):
    """(kind, detail) for a file name the convention names where it stands, else None."""
    name, depth = parts[-1], len(parts)
    if depth == 1:
        return _root(name)
    top = parts[0]
    if depth == 2 and top == BACKUP_FOLDER:
        return _backup(name)
    if depth == 2 and owns_assets(top):
        return _asset_folder(name)
    if depth == 2 and section_of_folder(top):    # Code and Colors own a captured picture at most
        return _picture(name)
    if depth == 2 and top == CAPTURE_FOLDER:
        return (FILE_CAPTURE, "") if _FILE_CAPTURE.match(name) else None
    if depth == 3 and parts[:2] == [RENDER_FOLDER, COMMENT_FOLDER]:
        return (COMMENT_IMAGE, "") if _COMMENT_IMAGE.match(name.lower()) else None
    if depth == 4 and parts[1] == VERSIONS and parts[2].isalnum():
        if top == CODE_FOLDER:
            return _version_folder(name, (CODE_VERSION_SUFFIX,), parts[2])
        if owns_assets(top):
            return _version_folder(name, VERSION_SUFFIXES, parts[2])
    return None


def split(relative: str) -> list:
    return [part for part in relative.replace("\\", "/").split("/") if part]


def join(parts) -> str:
    return "/".join(parts)


def classify(relative: str, is_dir: bool = False) -> tuple:
    """(kind, detail) for a relative path: detail is the asset id, the copied file, or `folder`."""
    parts = split(relative)
    if not parts:
        return FOLDER, ""
    name = parts[-1]
    if is_os_noise(name):
        return OS_NOISE_KIND, ""
    if is_scratch(name):
        return SCRATCH, ""
    if parts[0] in (PACKAGE_FOLDER, IMPORT_FOLDER, TRASH_FOLDER) and len(parts) > 1:
        return (FOLDER if is_dir else PACKAGE), ""
    if is_dir:
        return (FOLDER, "") if _folder(parts) else (UNKNOWN, "folder")
    found = _plain(parts)
    if found:
        return found
    for match in _COPY_NUMBER.finditer(name):
        original = parts[:-1] + [name[:match.start()] + name[match.end():]]
        if _plain(original):
            return DUPLICATE, join(original)
    return UNKNOWN, ""


def walk(library_dir: str, packages: bool = False):
    """Yield (relative, kind, detail, stat) listing each folder once; matX/ only with `packages`."""
    pending = [[]]
    while pending:
        parts = pending.pop(0)
        try:
            with os.scandir(os.path.join(library_dir, *parts)) as listing:
                entries = sorted(listing, key=lambda entry: entry.name)
        except OSError as exc:
            yield join(parts), UNREADABLE, str(exc), None
            continue
        for entry in entries:
            here = parts + [entry.name]
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            kind, detail = classify(join(here), is_dir)
            if is_dir and kind == FOLDER:
                if here[0] == TRASH_FOLDER:
                    pass    # the trash is the guard's: counted by it, never entered here
                elif here[0] != PACKAGE_FOLDER or packages:
                    pending.append(here)
                yield join(here), kind, detail, None
                continue
            info = None
            if kind in OUT_OF_PLACE:
                try:
                    info = entry.stat()
                except OSError:
                    info = None
            yield join(here), kind, detail, info
