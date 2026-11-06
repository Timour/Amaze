"""The one naming convention of a library folder; stdlib only, the audit tool loads it by path."""

import os
import re

LISTS = ("library.json", "cops.json", "code.json", "gradients.json")    # `database.SECTION_DATABASES`, held equal by a test
SIDE_TABLES = ("notes.json", "icons.json", "locations.json",    # `keyed_store.filenames()`, held equal by a test
               "location_paths.json", "favourites.json", "users.json",
               "prefs.json")
POLICY = "policy.json"
ROOT_FILES = LISTS + SIDE_TABLES + (POLICY,)

MARKERS = (".amaze_gradient_seed_v1", ".amaze_code_starter_v1",    # "the starters were offered here once"
           ".assetlib_gradient_seed_v1", ".assetlib_code_starter_v1")

TIERS = ("bak-1", "bak-2", "bak-3", "bak-first")    # `restore.TIERS`, held equal by a test
UNDO_TIER = "bak-before-restore"

ASSET_FOLDER = "mat"
RENDER_FOLDER = "img"
CAPTURE_FOLDER = "captures"
CODE_FOLDER = "code"
VERSIONS = "versions"
PACKAGE_FOLDER = "matX"    # a permanent store: the check does not enter it, the audit looks for scratch only
LEDGER = "versions.json"

ASSET_SUFFIXES = (".mat", ".interface", ".builder.json", ".stamp.json")    # `repair.ASSET_SIDECARS`
COMPANION_TAIL = "_cop"    # `<id>_cop.mat`, a node asset's companion network
ICON_TAIL = "_icon"    # `img/<id>_icon.png`, a chosen tile icon
PRE_ADOPT = ".pre-adopt"    # the backups the August texture adoption left beside `.mat` and `.builder.json`
VERSION_SUFFIXES = (".mat", ".interface", ".builder.json", ".png")
CODE_VERSION_SUFFIX = ".txt"

SCRATCH_TAILS = (".writing", ".capturing", ".tmp", ".temp", ".new", ".part",    # a write of ours that died partway
                 ".partial", ".lock", ".swp", "~", ".repairing", ".rollback")
SCRATCH_INFIXES = (".rendering.", ".capturing.")    # a render or capture scratch keeps its image extension last
SCRATCH_PREFIX = ".amaze_scratch"

OS_NOISE = (".DS_Store", "Thumbs.db", "desktop.ini", ".Spotlight-V100",    # the system's own, left alone and not reported
            ".fseventsd", ".TemporaryItems")

LIST = "list"    # the kinds that belong in a library
SIDE_TABLE = "side-table"
POLICY_FILE = "policy"
MARKER = "marker"
BACKUP = "backup"            # `<file>.bak-1` .. `.bak-first`
UNDO = "undo"                # `<file>.bak-before-restore-<stamp>`
PRESERVED = "preserved"      # `<file>.unreadable[.n]`
ASSET = "asset"              # `mat/<id>.mat`, `mat/<id>.interface`
BUILDER = "builder"
STAMP = "stamp"
COMPANION = "companion"
RENDER = "render"            # `img/<id>.png`
TILE_ICON = "tile-icon"
CAPTURE = "capture"          # `captures/<id>.png`
FILE_CAPTURE = "file-capture"    # `captures/file_<40 hex>.png`
VERSION = "version"
VERSION_LEDGER = "ledger"
PACKAGE = "package"
FOLDER = "folder"            # a folder the convention names
SCRATCH = "scratch"    # and the kinds that do not
PRE_ADOPT_COPY = "pre-adopt"
DUPLICATE = "duplicate"      # a known name with ` <n>` before its last suffix: a sync service's second copy
UNKNOWN = "unknown"
OS_NOISE_KIND = "os-noise"
UNREADABLE = "unreadable"    # a folder `walk` could not list; its detail is the error

KNOWN = frozenset((LIST, SIDE_TABLE, POLICY_FILE, MARKER, BACKUP, UNDO, PRESERVED,
                   ASSET, BUILDER, STAMP, COMPANION, RENDER, TILE_ICON, CAPTURE,
                   FILE_CAPTURE, VERSION, VERSION_LEDGER, PACKAGE, FOLDER))
COPIES = frozenset((BACKUP, UNDO, PRESERVED))    # a duplicate of one of these is swept whatever its bytes
OUT_OF_PLACE = frozenset((SCRATCH, PRE_ADOPT_COPY, DUPLICATE, UNKNOWN))    # `walk` stats these, and only these

_UNDO = re.compile(r"^%s-\d{8}-\d{6}(-\d+)?$" % re.escape(UNDO_TIER))
_PRESERVED = re.compile(r"^unreadable(\.\d+)?$")
_STEM = re.compile(r"^(?:[^\W_]+-)?\d+$")    # a version stem: `<writer>-<n>` or `<n>`, the writer alphanumeric
_FILE_CAPTURE = re.compile(r"^file_[0-9a-f]{40}\.png$")
_COPY_NUMBER = re.compile(r" \d+(?=\.|$)")


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


def _copy_kind(name: str, bases: tuple):
    """(kind, base) for a backup tier, undo copy or preserved copy of one of `bases`, else None."""
    for base in bases:
        if not name.startswith(base + "."):
            continue
        rest = name[len(base) + 1:]
        if rest in TIERS:
            return BACKUP, base
        if _UNDO.match(rest):
            return UNDO, base
        if _PRESERVED.match(rest):
            return PRESERVED, base
    return None


def _root(name: str):
    if name in LISTS:
        return LIST, name
    if name in SIDE_TABLES:
        return SIDE_TABLE, name
    if name == POLICY:
        return POLICY_FILE, name
    if name in MARKERS:
        return MARKER, name
    return _copy_kind(name, ROOT_FILES)


def _asset_folder(name: str):
    if name.endswith(PRE_ADOPT):
        found = asset_id(name[: -len(PRE_ADOPT)], (".mat", ".builder.json"))
        return (PRE_ADOPT_COPY, found) if found else None
    for suffix, kind in ((".builder.json", BUILDER), (".stamp.json", STAMP),
                         (".interface", ASSET), (".mat", ASSET)):
        found = asset_id(name, (suffix,))
        if found:
            return kind, found
    if name[: -len(".mat")].endswith(COMPANION_TAIL):
        found = asset_id(name, (".mat",), COMPANION_TAIL)
        if found:
            return COMPANION, found
    return None


def _render_folder(name: str):
    if not name.endswith(".png"):
        return None
    if name[: -len(".png")].endswith(ICON_TAIL):
        found = asset_id(name, (".png",), ICON_TAIL)
        return (TILE_ICON, found) if found else None
    found = asset_id(name, (".png",))
    return (RENDER, found) if found else None


def _capture_folder(name: str):
    if _FILE_CAPTURE.match(name):
        return FILE_CAPTURE, ""
    found = asset_id(name, (".png",))
    return (CAPTURE, found) if found else None


def _version_folder(name: str, suffixes: tuple):
    if name == LEDGER:
        return VERSION_LEDGER, name
    copy = _copy_kind(name, (LEDGER,))
    if copy:
        return copy
    for suffix in suffixes:
        if name.endswith(suffix) and _STEM.match(name[: -len(suffix)]):
            return VERSION, name[: -len(suffix)]
    return None


def _folder(parts: list) -> bool:
    """Whether the folder at `parts` is one the convention names."""
    depth = len(parts)
    if depth == 1:
        return parts[0] in (ASSET_FOLDER, RENDER_FOLDER, CAPTURE_FOLDER,
                            CODE_FOLDER, PACKAGE_FOLDER)
    if parts[0] == PACKAGE_FOLDER:
        return True
    if parts[0] in (ASSET_FOLDER, CODE_FOLDER) and parts[1] == VERSIONS:
        return depth == 2 or (depth == 3 and parts[2].isalnum())
    return False


def _plain(parts: list):
    """(kind, detail) for a file name the convention names where it stands, else None."""
    name, depth = parts[-1], len(parts)
    if depth == 1:
        return _root(name)
    top = parts[0]
    if depth == 2 and top == ASSET_FOLDER:
        return _asset_folder(name)
    if depth == 2 and top == RENDER_FOLDER:
        return _render_folder(name)
    if depth == 2 and top == CAPTURE_FOLDER:
        return _capture_folder(name)
    if depth == 4 and parts[1] == VERSIONS and parts[2].isalnum():
        if top == ASSET_FOLDER:
            return _version_folder(name, VERSION_SUFFIXES)
        if top == CODE_FOLDER:
            return _version_folder(name, (CODE_VERSION_SUFFIX,))
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
    if parts[0] == PACKAGE_FOLDER and len(parts) > 1:
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
                if here[0] != PACKAGE_FOLDER or packages:
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
