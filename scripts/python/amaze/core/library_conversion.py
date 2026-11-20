"""Library format 3 to 4; the only module that knows the old layouts: read, converted, removed."""

import filecmp
import hashlib
import json
import os
import re
import shutil
import uuid

from amaze import branding
from amaze.core import asset_record, debug, guard, library_files, library_policy, material
from amaze.core import locations, notes, renderers
from amaze.helpers import hostos

OLD_FOLDER = "mat"    # format 3: every section's asset files and version folders, together
OLD_PICTURES = "img"    # format 3: `img/<id>.png`, `img/<id>_icon.png`, `img/comments/<hex>.<ext>`
OLD_CAPTURES = "captures"    # format 3: `captures/<id>.png` and `captures/file_<sha1>.png`
OLD_COMMENT_PICTURES = OLD_PICTURES + "/comments"
OLD_FILE_CAPTURE = re.compile(r"^file_([0-9a-f]{40})\.png$")
INTERFACE = ".interface"    # the builder as `asCode()` Python: read for its type, never executed
BUILDER = ".builder.json"    # the builder as data, its interface under `dialog_script`
STAMP = ".stamp.json"    # the row, written beside the asset files
OLD_SUFFIXES = (BUILDER, STAMP, INTERFACE)
ICON_TAIL = "_icon"    # `img/<id>_icon.png`: a custom icon composed to disk
OLD_FACES = ("preview", "capture")    # stored tile choices that are treated as `image` now
TEXTURE_UPDATE_BACKUP = ".pre-adopt"    # `mat/<id>.mat.pre-adopt`: backups an earlier texture update left
UPGRADE_BACKUP = "backup-redshift-vopnet-"    # `mat/<this><date>/`: backups a builder upgrade left
OLD_MEMBER_KINDS = ("builder", "interface", "stamp", "tile_icon", "capture")    # an old package's
STALE_SIDECAR_S = 60    # one format 3 save wrote `.builder.json` and `.interface` moments apart

OLD_VERSION_STEM = re.compile(r"^(?:[^\W_]+-)?(\d+)$")    # a version file `<n>` or `<writer>-<n>`
OLD_VERSION_SUFFIXES = library_files.VERSION_SUFFIXES + (library_files.CODE_VERSION_SUFFIX,)
_CREATE_NODE = re.compile(rb'createNode\(\s*[\'"]([^\'"]+)[\'"]')

DONE, NOTHING, BLOCKED, CANCELLED = ("done", "nothing", "blocked", "cancelled")
STOPPED = "stopped"    # a file could not be read or written partway: running it again finishes it


class Stopped(Exception):
    """A file of the library could not be read or written; `str()` names it and the error."""


class Outcome:
    """How one conversion went: its status, why it was blocked, the assets it set aside."""

    def __init__(self, status: str, why: str = "", set_aside=(), counts=None,
                 old_trash: str = "") -> None:
        self.status = status
        self.why = why
        self.set_aside = list(set_aside)    # `SetAside`: rows taken out, old files untouched
        self.counts = dict(counts or {})
        self.old_trash = old_trash    # this computer's old trash for the library, "" for none


def interface_type(raw: bytes) -> str:
    """The builder type a format 3 `.interface` creates first, or ""."""
    match = _CREATE_NODE.search(raw or b"")
    return match.group(1).decode("utf-8", "replace") if match else ""


def builder_from_bytes(raw: bytes, interface, stale: bool = False, where: str = "") -> dict:
    """The builder section from `.builder.json`'s bytes; `interface()` returns `.interface`'s."""
    data = {}
    if raw:
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except ValueError as exc:
            debug.event("convert", "builder sidecar unreadable", path=where, error=str(exc))
            data = {}
        if not isinstance(data, dict) or "dialog_script" not in data:
            debug.event("convert", "builder sidecar has the wrong shape", path=where)
            data = {}
    found = asset_record.builder_section(dict(data, interface=data.get("dialog_script"))) \
        if data else {}
    if not found.get("type") or stale:    # re-saved by an Amaze that wrote no sidecar
        typed = interface_type(interface())
        if typed:
            found = dict(found or {"interface": "", "values": {}}, type=typed)
    return found


def builder_from_members(held: dict) -> dict:
    """The builder in a package's members: a new `json`, else format 3's `builder`/`interface`."""
    if held.get("json"):
        try:
            document = json.loads(held["json"].decode("utf-8-sig"))
        except (ValueError, AttributeError) as exc:
            debug.event("packages", "builder member unreadable", error=str(exc))
            document = {}
        found = asset_record.builder_section((document or {}).get(asset_record.BUILDER)) \
            if isinstance(document, dict) else {}
        if found:
            return found
    return builder_from_bytes(held.get("builder", b""), lambda: held.get("interface", b""))


def _bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return b""


def _old_builder(builder_path: str, interface_path: str) -> dict:
    raw = _bytes(builder_path) if builder_path else b""
    try:
        stale = bool(raw) and bool(interface_path) and (
            os.stat(builder_path).st_mtime < os.stat(interface_path).st_mtime - STALE_SIDECAR_S)
    except OSError:
        stale = False
    return builder_from_bytes(raw, lambda: _bytes(interface_path) if interface_path else b"",
                              stale, builder_path)


def _stamp(path: str):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            record = json.load(handle)
        return record if isinstance(record, dict) else None
    except (OSError, ValueError):
        return None


def _id_of(name: str, suffixes: tuple) -> str:
    """The id of a format 3 file name, by the old rule: letters and digits only."""
    for suffix in suffixes:
        if name.endswith(suffix) and name[: -len(suffix)].isalnum():
            return name[: -len(suffix)]
    return ""


def old_shape(relative: str) -> bool:
    """Whether a library path is one only format 3 wrote: a leftover the conversion did not use."""
    parts = library_files.split(relative)
    if not parts:
        return False
    top, name = parts[0], parts[-1]
    if top == OLD_FOLDER:    # files left in `mat/` are unknown to the conversion: reported, never removed
        return False
    if len(parts) == 2 and library_files.owns_assets(top) and name.endswith(TEXTURE_UPDATE_BACKUP):
        return bool(_id_of(name[: -len(TEXTURE_UPDATE_BACKUP)], (".mat",)))
    if len(parts) == 2 and library_files.owns_assets(top):
        return bool(_id_of(name, OLD_SUFFIXES))
    if len(parts) == 2 and top == OLD_PICTURES:
        return bool(_id_of(name, (ICON_TAIL + ".png", ".png")))
    if len(parts) == 2 and top == OLD_CAPTURES:
        return not name.startswith("file_") and bool(_id_of(name, (".png",)))
    if len(parts) == 4 and parts[1] == library_files.VERSIONS and library_files.owns_assets(top):
        return name.endswith((BUILDER, INTERFACE))
    return False


OLD_SECTIONS = {    # an old section database -> the 2.0 one, and the key prefix of its comments
    "library.json": (library_files.MATERIALS, "material"),
    "cops.json": (library_files.NODES, "cop"),
    "code.json": (library_files.CODE, "code"),
    "gradients.json": (library_files.COLORS, "gradient"),
}
OLD_TABLES = {    # an old side table -> the key its file holds its table under
    "notes.json": "notes", "icons.json": "icons", "favourites.json": "favourites",
    "locations.json": "locations", "location_paths.json": "location_paths",
    "users.json": "users", "prefs.json": "prefs",
}
OLD_POLICY = "policy.json"
OLD_ROOT_FILES = tuple(OLD_SECTIONS) + tuple(OLD_TABLES) + (OLD_POLICY,)
OLD_MARKS = {    # the old marker files, "the starters were offered here once" -> the 2.0 mark
    ".amaze_gradient_seed_v1": "gradient_seed_v1", ".assetlib_gradient_seed_v1": "gradient_seed_v1",
    ".amaze_code_starter_v1": "code_starter_v1", ".assetlib_code_starter_v1": "code_starter_v1",
}
OLD_COPY_TAILS = (".bak-1", ".bak-2", ".bak-3", ".bak-first", ".bak-before-restore",
                  ".unreadable")    # the copies the old engines kept beside a file
RETIRED_ROW_KEYS = ("favorite", "icon", "builder")    # the old schema chain, v4 to v7
RETIRED_TEXT_FIELDS = ("about", "description")    # a row's text that is now its comment
USER_SEP = "|"    # an old per-user key: `<uid>|<key>`
LOC = "loc:"
_MINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "amaze:minted-asset-id")    # never change: ids derive from it


def _read_old(library_dir: str, name: str):
    """(document, why) of one old root file: why is empty when read; `({}, "")` when absent."""
    path = os.path.join(library_dir, name)
    if not os.path.lexists(path):
        return {}, ""
    try:
        with open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, str(exc)
    if not isinstance(document, dict):
        return None, "it is not a database"
    return document, ""


def _old_traces(library_dir: str, name: str) -> list:
    """Every copy the old engines kept beside `name`: its backups and its unreadable copies."""
    return [entry for entry in _listing(library_dir)
            if entry.startswith(name + ".") and any(
                entry[len(name):].startswith(tail) for tail in OLD_COPY_TAILS)]


def _row_id(row: dict, index: int) -> str:
    """A row's id: `id`, the older `mat_id` or `uid`, else one derived from the row and its index."""
    found = str(row.get("id", row.get("mat_id", row.get("uid", ""))) or "")
    if found:
        return found
    canonical = json.dumps(row, sort_keys=True)
    return uuid.uuid5(_MINT_NAMESPACE, "%d:%s" % (index, canonical)).hex


def _converted_databases(library_dir: str) -> bool:
    """Whether the six databases are already written: a conversion stopped after that step."""
    document, _why = _read_old(library_dir, library_files.MASTER)
    entry = ((document or {}).get("policy") or {}).get("library") or {}
    return isinstance(entry, dict) and entry.get("version") == library_policy.LIBRARY_VERSION


def _databases(library_dir: str) -> tuple:
    """({2.0 section database: {id: row}}, why the conversion may not run, or "")."""
    found = {}
    master, why = _read_old(library_dir, library_files.MASTER)
    if master is None:
        return {}, "the Library database is corrupt/unreadable."
    entry = (master.get("policy") or {}).get("library") or {}
    version = entry.get("version") if isinstance(entry, dict) else 0
    if (isinstance(version, int) and version > library_policy.LIBRARY_VERSION) or _ahead(master):
        return {}, "the library was saved by a newer Amaze."
    if _converted_databases(library_dir):
        for name, _prefix in OLD_SECTIONS.values():
            document, _why = _read_old(library_dir, name)
            found[name] = dict(((document or {}).get("assets") or {}))
        return found, ""
    for filename in OLD_SECTIONS:
        document, why = _read_old(library_dir, filename)
        if document is None or not isinstance(document.get("assets", []), list):
            return {}, "the %s database is corrupt/unreadable." % _old_label(filename)
        if not document and not os.path.lexists(os.path.join(library_dir, filename)) \
                and _old_traces(library_dir, filename):
            return {}, ("there is no %s database in the library folder, though Amaze can "
                        "see there was one here before." % _old_label(filename))
        if _ahead(document):
            return {}, "the %s database was saved by a newer Amaze." % _old_label(filename)
        listed = [(_row_id(row, index), row)
                  for index, row in enumerate(document.get("assets") or []) if isinstance(row, dict)]
        found[OLD_SECTIONS[filename][0]] = dict(listed)
        if len(found[OLD_SECTIONS[filename][0]]) != len(listed):
            debug.event("convert", "two rows share an id - the later one is kept", file=filename,
                        rows=len(listed), ids=len(found[OLD_SECTIONS[filename][0]]))
    for filename in OLD_TABLES:
        document, why = _read_old(library_dir, filename)
        if document is None:
            return {}, "the %s file is corrupt/unreadable." % filename
    return found, ""


def _ahead(document: dict) -> bool:
    """Whether a database's `format` is one a newer Amaze wrote."""
    try:
        return int(document.get("format", 0) or 0) > branding.LIBRARY_FORMAT
    except (TypeError, ValueError):
        return False


def _old_label(filename: str) -> str:
    return library_files.section_label(OLD_SECTIONS[filename][0])


def _is_new_code(library_dir: str) -> bool:
    """Whether `code.json` is already 2.0's: an interrupted conversion wrote it."""
    document, _why = _read_old(library_dir, "code.json")
    return isinstance(document, dict) and isinstance(document.get("assets"), dict)


def _listing(folder: str) -> list:
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def _old_databases_left(library_dir: str) -> list:
    """The old root files still here; a `policy.json` beside `DataBase.json` is Check Library's."""
    master = os.path.isfile(os.path.join(library_dir, library_files.MASTER))
    left = []
    for name in OLD_ROOT_FILES + tuple(OLD_MARKS):
        if name == OLD_POLICY and master:
            continue
        if name == "code.json" and _is_new_code(library_dir):
            continue
        if os.path.lexists(os.path.join(library_dir, name)):
            left.append(name)
    return left


def needs_conversion(library_dir: str) -> bool:
    """Whether anything older than 2.0 is left: an old database, or a format 3 file."""
    library_dir = str(library_dir or "")
    if not library_dir or not os.path.isdir(library_dir):
        return False
    if _old_databases_left(library_dir):
        return True
    if _converted_databases(library_dir):    # what a finished run left is Check Library's,
        return _pictures_to_move(library_dir)    # but pictures not yet in their section are moved
    return bool(_plan_ids(library_dir, pictures=False) or _old_version_folders(library_dir))


def _pictures_to_move(library_dir: str) -> bool:
    """Whether `move_old_pictures` has work left: an old file capture, or an old comment picture."""
    for name in _listing(os.path.join(library_dir, OLD_CAPTURES)):
        match = OLD_FILE_CAPTURE.match(name)    # one whose new name is taken stays: Check reports it
        if match and not os.path.lexists(os.path.join(
                library_dir, library_files.FILES_FOLDER, match.group(1) + ".png")):
            return True
    return any(not library_files.is_os_noise(name)
               for name in _listing(os.path.join(library_dir, OLD_COMMENT_PICTURES)))


def old_users(library_dir: str) -> dict:
    """`{uid: name}` of an older library, for picking who converts it."""
    try:
        table = _old_table(str(library_dir or ""), "users.json")
    except (OSError, ValueError):
        return {}
    return {str(uid): str(record["name"]).strip() for uid, record in table.items()
            if isinstance(record, dict) and str(record.get("name") or "").strip()}


def old_version(library_dir: str) -> int:
    """The library version an older library records in its `policy.json`; 0 for no library."""
    document, _why = _read_old(library_dir, OLD_POLICY)
    found = (document or {}).get("library_version")
    if isinstance(found, int) and not isinstance(found, bool) and found > 0:
        return found
    return 1 if needs_conversion(library_dir) else 0


def _plan_ids(library_dir: str, pictures: bool = True) -> set:
    """Every id with a format 3 file: in `mat/`, beside a section's files, or a picture."""
    ids = set()
    for name in _listing(os.path.join(library_dir, OLD_FOLDER)):
        found = _id_of(name, OLD_SUFFIXES + ("_cop.mat", ".mat"))
        if found:
            ids.add(found)
    for section in library_files.ASSET_SECTIONS:
        for name in _listing(material.section_folder(library_dir, section)):
            found = _id_of(name, OLD_SUFFIXES)
            if found:
                ids.add(found)
    if not pictures:    # a folder holding only pictures is no library
        return ids
    for name in _listing(os.path.join(library_dir, OLD_PICTURES)):
        found = _id_of(name, (ICON_TAIL + ".png", ".png"))
        if found:
            ids.add(found)
    for name in _listing(os.path.join(library_dir, OLD_CAPTURES)):
        found = "" if name.startswith("file_") else _id_of(name, (".png",))
        if found:
            ids.add(found)
    return ids


def _old_version_folders(library_dir: str) -> list:
    """(folder, section) of every version folder to move out of `mat/` or still holding old files."""
    found = []
    for asset_id in _listing(os.path.join(library_dir, OLD_FOLDER, library_files.VERSIONS)):
        found.append((os.path.join(library_dir, OLD_FOLDER, library_files.VERSIONS, asset_id),
                      ""))
    for section in library_files.ASSET_SECTIONS:
        root = material.section_folder(library_dir, section, library_files.VERSIONS)
        for asset_id in _listing(root):
            folder = os.path.join(root, asset_id)
            if any(name.endswith((BUILDER, INTERFACE)) for name in _listing(folder)):
                found.append((folder, section))
    return found


def _owner(rows: dict, asset_id: str):
    """The section an id's files go to; "" for Code or Colors; None when two asset sections claim it."""
    owners = [name for name in library_files.ASSET_SECTIONS if asset_id in rows.get(name, {})]
    if len(owners) > 1:
        return None
    if owners:
        return owners[0]
    if any(asset_id in ids for ids in rows.values()):
        return next(name for name, ids in rows.items() if asset_id in ids)
    return library_files.ORPHAN_SECTION


def _is_asset(library_dir: str, asset_id: str, section: str, rows: dict) -> bool:
    """Whether an id is an asset to convert: a database names it, or its `.mat` is here."""
    if any(asset_id in ids for ids in rows.values()):
        return True
    return any(os.path.lexists(os.path.join(folder, asset_id + ".mat")) for folder in (
        os.path.join(library_dir, OLD_FOLDER), material.section_folder(library_dir, section)))


def _copy_in(source: str, target: str) -> None:
    """`source` into `target` through a scratch beside it, promoted; OSError propagates."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    scratch = hostos.unique_scratch(target)
    try:
        shutil.copyfile(source, scratch)
        hostos.replace_with_scratch(scratch, target)
    finally:
        hostos.discard_scratch(scratch)


def _remove(paths) -> int:
    """Delete each converted file through the product's own delete; how many went."""
    gone = 0
    for path in paths:
        hostos.check_deletable(path)
        hostos.remove_file(path)
        gone += 1
    return gone


def _shown_picture(faces: dict, asset_id: str, section: str, render: str, capture: str) -> str:
    """The picture a tile showed in format 3: a stored Capture its capture, else its render."""
    if faces.get(asset_id) == "capture" and capture:
        return capture
    if section not in library_files.ASSET_SECTIONS:    # Code and Colors paint their own preview
        return ""
    return render or capture


def _convert_asset(library_dir: str, asset_id: str, section: str, rows: dict,
                   faces: dict, counts: dict) -> tuple:
    """One asset as a unit: (converted, its format 3 files); a failure undoes what it wrote."""
    created, stopped = [], None
    try:
        ok, old_files = _convert_one(library_dir, asset_id, section, rows, faces, counts, created)
    except (ValueError, hostos.PathOutsideBase) as exc:
        ok, old_files = _kept(asset_id, str(exc), counts), _old_files(library_dir, asset_id,
                                                                      section)
    except OSError as exc:    # a file in use or a full disk: the asset converts in the next run
        ok, old_files, stopped = False, [], exc
    if not ok:
        for path in created:    # the files written for this asset; its format 3 files stay untouched
            try:
                hostos.remove_file(path)
            except OSError:
                pass
    if stopped is not None:
        debug.event("convert", "conversion stopped at an asset", mat_id=asset_id,
                    error=str(stopped))
        raise Stopped(str(stopped)) from stopped
    return ok, old_files


def _old_files(library_dir: str, asset_id: str, section: str) -> list:
    """Every format 3 file of one asset, wherever it lies."""
    section_dir = material.section_folder(library_dir, section)
    old_dir = os.path.join(library_dir, OLD_FOLDER)
    candidates = [os.path.join(folder, asset_id + suffix) for folder in (old_dir, section_dir)
                  for suffix in OLD_SUFFIXES]
    candidates += [os.path.join(old_dir, asset_id + suffix) for suffix in (".mat", "_cop.mat")]
    candidates += [os.path.join(library_dir, OLD_PICTURES, asset_id + ".png"),
                   os.path.join(library_dir, OLD_PICTURES, asset_id + ICON_TAIL + ".png"),
                   os.path.join(library_dir, OLD_CAPTURES, asset_id + ".png")]
    return [path for path in candidates if os.path.lexists(path)]


def _convert_one(library_dir: str, asset_id: str, section: str, rows: dict,
                 faces: dict, counts: dict, created: list) -> tuple:
    """`_convert_asset`'s work; every new file it writes is listed in `created`."""
    old_files = _old_files(library_dir, asset_id, section)
    old_dir = os.path.join(library_dir, OLD_FOLDER)
    section_dir = material.section_folder(library_dir, section)
    old = {suffix: path for suffix in OLD_SUFFIXES
           for path in (os.path.join(old_dir, asset_id + suffix),
                        os.path.join(section_dir, asset_id + suffix)) if os.path.lexists(path)}
    moves = []    # (source, target, keep the target as it is because it is newer)
    for suffix in (".mat", "_cop.mat"):
        source = os.path.join(old_dir, asset_id + suffix)
        if os.path.lexists(source):
            target = os.path.join(section_dir, asset_id + suffix)
            moves.append((source, target, os.path.lexists(target)))
    render = os.path.join(library_dir, OLD_PICTURES, asset_id + ".png")
    capture = os.path.join(library_dir, OLD_CAPTURES, asset_id + ".png")
    icon = os.path.join(library_dir, OLD_PICTURES, asset_id + ICON_TAIL + ".png")
    render, capture = (render if os.path.lexists(render) else "",
                       capture if os.path.lexists(capture) else "")
    shown = _shown_picture(faces, asset_id, section, render, capture)
    picture = os.path.join(section_dir, asset_id + ".png")
    pictures = [path for path in (render, capture) if path]
    if os.path.lexists(icon):
        pictures.append(icon)
    if section in library_files.ASSET_SECTIONS and not any(
            target for _s, target, _n in moves if target.endswith(asset_id + ".mat")) \
            and not os.path.lexists(os.path.join(section_dir, asset_id + ".mat")):
        return _kept(asset_id, "its .mat is missing", counts), old_files
    for source, target, newer in moves:
        if not newer:
            created.append(target)
            _copy_in(source, target)
    shown = shown if shown and not os.path.lexists(picture) else ""    # a picture already there is newer
    if shown:
        created.append(picture)
        _copy_in(shown, picture)
    built = {}
    if section in library_files.ASSET_SECTIONS:
        path = asset_record.path_for(_Prefs(library_dir), asset_id, section)
        if not os.path.lexists(path):
            created.append(path)
        present = asset_record.read(path)
        row = rows.get(section, {}).get(asset_id)
        metadata = json.loads(json.dumps(row)) if row else (
            present[asset_record.METADATA] or _stamp(old.get(STAMP, "")) or {})
        builder = present[asset_record.BUILDER] or _old_builder(old.get(BUILDER, ""),
                                                                old.get(INTERFACE, ""))
        built = {asset_record.METADATA: metadata, asset_record.BUILDER: builder}
        with asset_record.LOCK:
            for name, data in built.items():
                if data and present[name] != data:
                    asset_record.write_section(path, name, data)
        back = asset_record.read(path)
        if any(data and back[name] != data for name, data in built.items()):
            return _kept(asset_id, "the new file did not read back as built", counts), old_files
    for source, target, newer in moves:
        if not newer and not filecmp.cmp(source, target, shallow=False):
            return _kept(asset_id, "a moved file did not read back byte for byte",
                         counts), old_files
    if shown and not filecmp.cmp(shown, picture, shallow=False):
        return _kept(asset_id, "the picture did not read back byte for byte", counts), old_files
    for path in list(old.values()) + [source for source, _t, _n in moves] + pictures:
        try:    # the new files read back: an old file that cannot be deleted is a leftover, not a failure
            counts["deleted"] += _remove([path])
        except OSError as exc:
            counts["left"] += 1
            debug.event("convert", "an old file could not be deleted", path=path, error=str(exc))
    counts["converted"] += 1
    return True, []


CLASSIC = {each.classic_container: each for each in renderers.ALL if each.classic_container}


def _classics(library_dir: str, rows: dict) -> dict:
    """{id: its Renderer} for each Material saved in a classic container, which 2.0 does not read."""
    found = {}
    folders = (os.path.join(library_dir, OLD_FOLDER),
               material.section_folder(library_dir, library_files.MATERIALS))
    for asset_id in rows.get(library_files.MATERIALS, {}):
        old = {suffix: next((path for path in (os.path.join(folder, asset_id + suffix)
                                               for folder in folders) if os.path.lexists(path)), "")
               for suffix in (BUILDER, INTERFACE)}
        try:
            builder = asset_record.read(asset_record.path_for(
                _Prefs(library_dir), asset_id, library_files.MATERIALS))[asset_record.BUILDER] \
                or _old_builder(old[BUILDER], old[INTERFACE])
        except (OSError, ValueError, hostos.PathOutsideBase):
            continue    # an id with no file here: its own conversion step sets it aside
        renderer = CLASSIC.get(builder.get("type", ""))
        if renderer is not None:
            found[asset_id] = renderer
    return found


def _new_files(library_dir: str, asset_id: str, section: str) -> list:
    """The 2.0 files of one asset that are there."""
    section_dir = material.section_folder(library_dir, section)
    return [path for path in (os.path.join(section_dir, asset_id + suffix)
                              for suffix in (".mat", "_cop.mat", ".json", ".png"))
            if os.path.lexists(path)]


def _rebuilt(classic, library_dir: str, asset_id: str, renderer, row, counts: dict) -> bool:
    """A converted classic Material rewritten as its USD builder through `classic`; whether it was."""
    why = "its classic builder is rebuilt in Houdini alone"
    if classic is not None:
        try:
            classic.rebuild(asset_id, str((row or {}).get("name") or asset_id), renderer)
            saved = asset_record.read(asset_record.path_for(
                _Prefs(library_dir), asset_id, library_files.MATERIALS))[asset_record.BUILDER]
            if saved.get("type") == renderer.usd_builder:
                return True
            why = "its saved builder is still %s" % saved.get("type")
        except Exception as exc:    # noqa: BLE001 - Houdini's errors, which this module cannot name
            why = "its classic builder could not be rebuilt: %s" % exc
    counts["converted"] -= 1
    return _kept(asset_id, why, counts)


def _files_under(folder: str) -> list:
    return [os.path.join(root, name) for root, _dirs, names in os.walk(folder) for name in names]


def _kept(asset_id: str, why: str, counts: dict) -> bool:
    counts["kept"] += 1
    debug.event("convert", "an asset's old files are kept", mat_id=asset_id, why=why)
    return False


class _Prefs:
    """Just enough of a Prefs for the path builders: the library folder."""

    def __init__(self, library_dir: str) -> None:
        self.dir = library_dir


def _convert_versions(library_dir: str, folder: str, section: str, rows: dict,
                      counts: dict) -> bool:
    """A version folder into its section, each format 3 archive rewritten as `<stem>.json`."""
    asset_id = os.path.basename(folder)
    if not section:
        owner = _owner(rows, asset_id) if asset_id.isalnum() else None
        if owner not in library_files.ASSET_SECTIONS:
            counts["left"] += 1    # two sections list it, or no asset has it: Check Library reports it
            return True
        target = os.path.join(material.section_folder(library_dir, owner, library_files.VERSIONS),
                              asset_id)
        if os.path.lexists(target):
            counts["left"] += 1
            debug.event("convert", "a version folder stays in mat/ - its section has one",
                        mat_id=asset_id)
            return True
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.replace(folder, target)    # one rename: the folder is whole in one place or the other
        folder = target
    names = _listing(folder)
    for stem in sorted({name[: -len(suffix)] for name in names for suffix in (BUILDER, INTERFACE)
                        if name.endswith(suffix)}):
        builder_path = os.path.join(folder, stem + BUILDER)
        interface_path = os.path.join(folder, stem + INTERFACE)
        built = _old_builder(builder_path if os.path.lexists(builder_path) else "",
                             interface_path if os.path.lexists(interface_path) else "")
        target = os.path.join(folder, stem + library_files.RECORD_SUFFIX)
        document = {"format": asset_record.FORMAT}
        if built:
            document[asset_record.BUILDER] = built
        hostos.write_json_atomic(target, document, serialised=asset_record.encode(document))
        if asset_record.read(target)[asset_record.BUILDER] != (built or {}):
            return _kept(asset_id, "a version's new file did not read back as built", counts)
        counts["deleted"] += _remove([path for path in (builder_path, interface_path)
                                      if os.path.lexists(path)])
    _rename_versions(folder)
    return True


def _rename_versions(folder: str) -> None:
    """Each old version file renamed `<id>_<n>`, and `file` dropped from the ledger rows."""
    asset_id = os.path.basename(folder)
    path = os.path.join(folder, library_files.LEDGER)
    ledger, rows = None, []
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as handle:
                ledger = json.load(handle)
            rows = ledger.get("versions")
        except (OSError, ValueError, AttributeError):
            return    # the version store reports an unreadable ledger
        if not isinstance(rows, list):
            return
    rows = [row for row in rows if isinstance(row, dict) and str(row.get("n", "")).isdigit()]
    named = {str(row.get("file") or int(row["n"])): int(row["n"]) for row in rows}
    numbers = set(named.values())
    renamed = 0
    for name in _listing(folder):
        stem, suffix = os.path.splitext(name)
        if suffix not in OLD_VERSION_SUFFIXES:
            continue
        number = named.get(stem)
        old = OLD_VERSION_STEM.match(stem)
        if number is None and old and int(old.group(1)) not in numbers:
            number = int(old.group(1))    # a file no row lists: orphaned, but renamed too
        target = os.path.join(folder, "%s_%d%s" % (asset_id, number or 0, suffix))
        if number is None or os.path.lexists(target):
            continue
        os.replace(os.path.join(folder, name), target)
        renamed += 1
    if ledger is not None and any("file" in row for row in rows):
        for row in rows:
            row.pop("file", None)
        hostos.write_json_atomic(path, ledger)
    if renamed:
        debug.event("convert", "version files renamed", folder=folder, files=renamed)


def _stored_faces(library_dir: str) -> dict:
    """{key: face} from format 3's icons.json, read directly: the icon store rejects old faces."""
    try:
        with open(os.path.join(library_dir, "icons.json"), encoding="utf-8-sig") as handle:
            table = (json.load(handle) or {}).get("icons") or {}
    except (OSError, ValueError, AttributeError) as exc:
        debug.event("convert", "stored tile choices unreadable - renders are kept",
                    error=str(exc))
        return {}
    return {str(key): spec.get("face") for key, spec in table.items()
            if isinstance(spec, dict) and spec.get("face") in OLD_FACES}


def _remove_old_backups(old_dir: str) -> int:
    """Delete the backups two earlier updates left in `mat/`; how many files went."""
    gone = 0
    for name in _listing(old_dir):
        path = os.path.join(old_dir, name)
        if name.endswith(TEXTURE_UPDATE_BACKUP) and os.path.isfile(path) and not os.path.islink(path):
            gone += _remove([path])
        elif name.startswith(UPGRADE_BACKUP) and os.path.isdir(path) \
                and not os.path.islink(path):
            files = [os.path.join(path, each) for each in _listing(path)]
            if all(os.path.isfile(each) and not os.path.islink(each) for each in files):
                gone += _remove(files)    # a flat folder of files, as the upgrade wrote it
                _remove_empty(path)
    return gone


def _remove_empty(folder: str) -> None:
    """Remove `folder` when only the system's own files are left in it."""
    try:
        names = os.listdir(folder)
        if any(not library_files.is_os_noise(name) for name in names):
            return
        for name in names:
            os.remove(os.path.join(folder, name))
        os.rmdir(folder)
    except OSError:
        pass


def convert(directory: str, confirm, progress=None, user: str = "",
            machine_stars=(), classic=None,
            user_name: str = "") -> Outcome:
    """Convert an older library to 2.0 whole once `confirm()` says yes; `progress(done, total)`."""
    try:
        return _convert(str(directory or ""), confirm, progress, user, machine_stars,
                        classic, user_name)
    except Stopped as exc:
        return Outcome(STOPPED, str(exc))
    except (OSError, guard.Refused) as exc:
        debug.event("convert", "conversion stopped", error=str(exc))
        return Outcome(STOPPED, str(exc))


def _convert(library_dir: str, confirm, progress, user: str, machine_stars,
             classic, user_name: str) -> Outcome:
    """`convert`'s work; `Stopped`, OSError or `guard.Refused` when a file cannot be reached."""
    if not needs_conversion(library_dir):
        return Outcome(NOTHING)
    rows, why = _databases(library_dir)
    if why:
        debug.event("convert", "conversion blocked - nothing was changed", why=why)
        return Outcome(BLOCKED, why)
    if not confirm():
        debug.event("convert", "conversion declined - nothing was changed")
        return Outcome(CANCELLED)
    classics = _classics(library_dir, rows)
    rebuilt = set()
    to_trash = {}    # id -> SetAside: classic Materials whose renderer is not loaded, sent to the trash
    for renderer in renderers.ALL:
        ids = [asset_id for asset_id, found in classics.items() if found is renderer]
        if not ids or classic is None or classic.loaded(renderer):
            continue
        if not classic.ask(len(ids), renderer):
            debug.event("convert", "conversion declined - a renderer is not loaded",
                        renderer=renderer.key)
            return Outcome(CANCELLED)
        to_trash.update({asset_id: None for asset_id in ids})
    old_trash = old_trash_of(library_dir)
    faces = _stored_faces(library_dir)
    counts = {"converted": 0, "deleted": 0, "kept": 0, "left": 0}
    set_aside = []
    units = [("asset", asset_id)    # a classic one an interrupted run left converted is rebuilt now
             for asset_id in sorted(_plan_ids(library_dir) | set(classics))] + [
        ("versions", folder) for folder in _old_version_folders(library_dir)]
    for done, (kind, item) in enumerate(units):
        if progress is not None:    # display only: the user cannot stop a conversion partway
            progress(done, len(units))
        if kind == "versions" and os.path.basename(item[0]) in classics:
            held = to_trash.get(os.path.basename(item[0]))
            if held is not None:    # to the trash with its asset
                held.files.extend(_files_under(item[0]))
            elif os.path.basename(item[0]) in rebuilt:    # archives no 2.0 Amaze can load
                shutil.rmtree(item[0], ignore_errors=True)
            continue    # of a Material set aside: left with its files
        if kind == "versions":
            try:
                _convert_versions(library_dir, item[0], item[1], rows, counts)
            except (OSError, ValueError) as exc:    # its old archives stay as they are
                _kept(os.path.basename(item[0]), str(exc), counts)
            continue
        owner = _owner(rows, item)
        if owner is None:
            counts["left"] += 1
            debug.event("convert", "two sections name one id - its files stay", mat_id=item)
            continue
        if not _is_asset(library_dir, item, owner, rows):
            counts["left"] += 1    # a picture or stamp with no asset: Check Library reports it
            continue
        row = rows.get(owner, {}).get(item)
        if item in to_trash:
            to_trash[item] = SetAside(item, owner, row, sorted(set(
                _old_files(library_dir, item, owner) + _new_files(library_dir, item, owner))))
            continue
        ok, old_files = _convert_asset(library_dir, item, owner, rows, faces, counts)
        if ok and item in classics:
            if _rebuilt(classic, library_dir, item, classics[item], row, counts):
                rebuilt.add(item)
            else:
                ok, old_files = False, _new_files(library_dir, item, owner)
        if not ok:
            set_aside.append(SetAside(item, owner, row, old_files))
    trashed = [one for one in to_trash.values() if one is not None]
    if trashed and not trash_set_aside(library_dir, trashed):
        set_aside.extend(trashed)    # still in the folder: named in the result with the others
        trashed = []
    for root in [material.section_folder(library_dir, section, library_files.VERSIONS)
                 for section in library_files.ASSET_SECTIONS] + [
                     os.path.join(library_dir, library_files.CODE_FOLDER, library_files.VERSIONS)]:
        for asset_id in _listing(root):
            try:
                _rename_versions(os.path.join(root, asset_id))
            except (OSError, ValueError) as exc:    # a locked file: Check Library reports what is left
                _kept(asset_id, "its version files were not renamed: %s" % exc, counts)
    try:
        counts["deleted"] += _remove_old_backups(os.path.join(library_dir, OLD_FOLDER))
    except OSError as exc:
        debug.event("convert", "an old backup could not be deleted", error=str(exc))
    for folder in (os.path.join(library_dir, OLD_FOLDER, library_files.VERSIONS),
                   os.path.join(library_dir, OLD_FOLDER),
                   os.path.join(library_dir, OLD_CAPTURES)):
        _remove_empty(folder)
    counts["left"] += len(_listing(os.path.join(library_dir, OLD_FOLDER)))
    if not _converted_databases(library_dir):
        built = build_databases(library_dir, {(one.section, one.asset_id)
                                              for one in set_aside + trashed
                                              if one.row is not None}, user, machine_stars,
                                user_name)
        _write_databases(library_dir, built, user)
        if not _read_back(library_dir, built):
            debug.event("convert", "the new databases did not read back - the old files stay")
            return Outcome(BLOCKED, "the new databases did not read back as they were written.")
    counts["deleted"] += _remove_old_root_files(library_dir, user)
    move_old_pictures(library_dir, user)    # an OSError stops the run: the next one moves them
    debug.event("convert", "library conversion", set_aside=len(set_aside), **counts)
    return Outcome(DONE, set_aside=set_aside, counts=counts, old_trash=old_trash)


class SetAside:
    """An asset the conversion could not convert: its row, taken out, and its untouched old files."""

    def __init__(self, asset_id: str, section: str, row, files: list) -> None:
        self.asset_id = asset_id
        self.section = section
        self.row = row    # None for files no database listed
        self.files = list(files)

    @property
    def name(self) -> str:
        return str((self.row or {}).get("name") or self.asset_id)


def trash_set_aside(library_dir: str, set_aside: list) -> int:
    """Move the set-aside assets' old files to the library's trash once confirmed; how many moved."""
    held = guard.Guard(library_dir)
    change = held.change("")
    moved = 0
    for one in set_aside:
        for path in one.files:
            relative = held.inside(path)
            if relative and os.path.lexists(path):
                change.trash(relative)
                moved += 1
    try:
        change.commit()
    except OSError as exc:
        debug.event("convert", "set-aside files not moved to the trash", error=str(exc))
        return 0
    debug.event("convert", "set-aside files moved to the trash", moved=moved)
    return moved


def machine_stars(preferences) -> list:
    """The stars this computer's settings kept beside the library's, which the conversion adds."""
    data = getattr(preferences, "data", None)
    found = data.get("material_favorites") if isinstance(data, dict) else None
    return [str(one) for one in found or () if str(one).strip()] if isinstance(
        found, (list, tuple)) else []


def _is_file_key(key: str) -> bool:
    """Whether an old key names a file of the Files section rather than an asset id."""
    key = str(key)
    return key.startswith((LOC, "/", "$", "~", "\\\\", "//")) or hostos.foreign_path(key) \
        or (len(key) > 2 and key[1] == ":")


class _Paths:
    """The Files section's location paths, one id per path, and old keys rewritten to use them."""

    def __init__(self, table: dict) -> None:
        self.rows, self.winner = {}, {}
        by_path = {}
        for lid in sorted(table):
            path = str((table[lid] or {}).get("path") or "") if isinstance(table[lid], dict) else ""
            if not path.strip():
                continue
            identity = path.rstrip("/") or "/"
            if identity in by_path:
                self.winner[lid] = by_path[identity]    # two ids at one path: the smallest is kept
                continue
            by_path[identity] = lid
            self.rows[lid] = {"path": path}
        self.by_path = by_path

    def id_for(self, path: str) -> str:
        """The id of the location at `path`, created when it has none."""
        identity = str(path).rstrip("/") or "/"
        if identity not in self.by_path:
            lid = hashlib.sha1(("amaze:location:" + identity).encode("utf-8")).hexdigest()[:32]
            self.by_path[identity] = lid
            self.rows[lid] = {"path": str(path)}
        return self.by_path[identity]

    def file_key(self, key: str) -> str:
        """An old file key on a location id: under the innermost location, a duplicate id merged."""
        key = str(key)
        if key.startswith(LOC):
            head, sep, rel = key[len(LOC):].partition("/")
            return LOC + self.winner.get(head, head) + sep + rel
        best = ""
        for identity in self.by_path:
            if (key == identity or key.startswith(identity.rstrip("/") + "/")) \
                    and len(identity) > len(best):
                best = identity
        if not best:
            return key
        rel = key[len(best.rstrip("/")) + 1:] if len(key) > len(best) else ""
        return LOC + self.by_path[best] + ("/" + rel if rel else "")


def _old_table(library_dir: str, name: str) -> dict:
    document, _why = _read_old(library_dir, name)
    table = (document or {}).get(OLD_TABLES[name])
    return table if isinstance(table, dict) else {}


def _owner_and_key(key: str, user: str) -> tuple:
    """(user, key) of an old per-user key; an entry from before users goes to the converting user."""
    owner, sep, rest = str(key).partition(USER_SEP)
    if sep and len(owner) == 32 and all(c in "0123456789abcdef" for c in owner):
        return owner, rest
    return user, str(key)


def _first_shape(page) -> list:
    """A comment page's items; the first version's text-and-todos layout converted to items."""
    if not isinstance(page, dict):
        return []
    items = page.get("items")
    if isinstance(items, list):
        return items
    found = []
    text = page.get("text", "")
    if isinstance(text, str) and text.strip():
        found.append({"t": "text", "text": text})
    for item in page.get("todos") or []:
        if isinstance(item, dict):
            found.append({"t": "todo", "label": item.get("label", ""),
                          "done": item.get("done", False)})
    return found


def _categories_of(row: dict) -> list:
    """A row's categories as a list; an old comma string split, blanks dropped."""
    found = row.get("categories")
    if isinstance(found, str):
        found = found.split(",")
    return [one.strip() for one in (found or []) if isinstance(one, str) and one.strip()]


RETIRED_LOCATION_KEYS = ("show_all", "kinds", "recursive", "pathname")    # what a location listed, once


def build_databases(library_dir: str, set_aside=(), user: str = "", machine_stars=(),
                    user_name: str = "") -> dict:
    """The six 2.0 databases, {name: document}, built from every old root file in one pass."""
    sections = {name: {"assets": {}, "categories": {}, "comments": {}, "icons": {}, "favorites": {}}
                for name, _prefix in OLD_SECTIONS.values()}
    files = {"locations": {}, "paths": {}, "comments": {}, "icons": {}, "favorites": {}}
    master = {"policy": {}, "settings": {}, "users": {}, "marks": {}}
    owner_of = {}
    pages, retired = {}, {}    # note key -> its items; note key -> its row's text, now a comment
    for filename, (name, prefix) in OLD_SECTIONS.items():
        document, _why = _read_old(library_dir, filename)
        document = document or {}
        for index, row in enumerate(document.get("assets") or []):
            if not isinstance(row, dict):
                continue
            asset_id = _row_id(row, index)
            if (name, asset_id) in set_aside:
                continue
            row = {key: value for key, value in row.items()
                   if key not in RETIRED_ROW_KEYS + ("mat_id", "uid")}
            row["id"] = asset_id
            if "categories" in row:
                row["categories"] = _categories_of(row)
            for field in RETIRED_TEXT_FIELDS:
                text = row.pop(field, "")
                if isinstance(text, str) and text.strip():
                    retired.setdefault(notes.note_key(prefix, asset_id), []).append(text.strip())
            sections[name]["assets"][asset_id] = row
            owner_of[asset_id] = name
        colours = document.get("category_colors") if isinstance(
            document.get("category_colors"), dict) else {}
        order = [one for one in (document.get("categories") or [])    # the All row is no category
                 if isinstance(one, str) and one.strip() and one.lstrip("_") != "All"]
        for row in sections[name]["assets"].values():
            order.extend(one for one in row.get("categories") or [] if one not in order)
        for position, category in enumerate(dict.fromkeys(order)):
            entry = {"order": position}
            if colours.get(category):
                entry["color"] = str(colours[category])
            sections[name]["categories"][category] = entry
    paths = _Paths(_old_table(library_dir, "location_paths.json"))
    for key, record in _old_table(library_dir, "locations.json").items():
        owner, bare = _owner_and_key(key, user)
        if not owner or not isinstance(record, dict) or not record:
            continue
        location_key = bare if bare.startswith(LOC) else LOC + paths.id_for(bare)
        files["locations"].setdefault(owner, {})[paths.file_key(location_key)] = {
            key: value for key, value in record.items() if key not in RETIRED_LOCATION_KEYS}
    for key, page in _old_table(library_dir, "notes.json").items():
        items = _first_shape(page)
        if items:
            pages[str(key)] = list(items)
    for key, texts in retired.items():
        items = pages.setdefault(key, [])
        for text in reversed(texts):
            if not any(item.get("t") == "text" and str(item.get("text", "")).strip() == text
                       for item in items if isinstance(item, dict)):
                items.insert(0, {"t": "text", "text": text})    # added once, at the top
    for key, items in pages.items():
        prefix, _sep, ident = key.partition(":")
        kept = notes.normalise_items([dict(item) for item in items])
        if not kept:
            continue
        if prefix == "file":
            files["comments"][paths.file_key(ident)] = {"items": kept}
            continue
        name = notes.DATABASE_OF.get(prefix)
        if name in sections and (name, ident) not in set_aside:
            sections[name]["comments"][ident] = {"items": kept}
    old_faces = ("preview", "capture")    # stored tile choices that are treated as `image` now
    for key, spec in _old_table(library_dir, "icons.json").items():
        if not isinstance(spec, dict) or not spec or spec.get("face") in old_faces:
            continue
        if str(key) in owner_of:
            sections[owner_of[str(key)]]["icons"][str(key)] = dict(spec)
        elif _is_file_key(key):
            files["icons"][paths.file_key(key)] = dict(spec)
    stars = list(_old_table(library_dir, "favourites.json").items()) + [
        (star, {"favourite": True}) for star in machine_stars or ()]
    for key, value in stars:
        owner, bare = _owner_and_key(key, user)
        if not owner or not value:
            continue
        if bare in owner_of:
            sections[owner_of[bare]]["favorites"].setdefault(owner, {})[bare] = True
        elif _is_file_key(bare):
            files["favorites"].setdefault(owner, {})[paths.file_key(bare)] = True
    files["paths"] = dict(paths.rows)
    for uid, record in _old_table(library_dir, "users.json").items():
        if isinstance(record, dict) and str(record.get("name") or "").strip():
            master["users"][str(uid)] = dict(record, name=str(record["name"]).strip())
    if user and user not in master["users"] and str(user_name or "").strip():
        master["users"][user] = {"name": str(user_name).strip()}    # a library from before users
    for key, record in _old_table(library_dir, "prefs.json").items():
        if isinstance(record, dict) and "value" in record:
            master["settings"][str(key)] = {"value": record["value"]}
    policy, _why = _read_old(library_dir, OLD_POLICY)
    allowed = (policy or {}).get("allow_overwrite")
    if isinstance(allowed, bool):
        master["policy"]["allow_overwrite"] = {"value": allowed}
    master["policy"]["library"] = {"version": library_policy.LIBRARY_VERSION}
    for marker, mark in OLD_MARKS.items():
        if os.path.lexists(os.path.join(library_dir, marker)):
            master["marks"][mark] = {"offered": True}
    built = {library_files.MASTER: master}
    if any(files.values()):
        built[library_files.FILES] = files
    for filename, (name, _prefix) in OLD_SECTIONS.items():    # an empty one is created at its first save
        if any(sections[name].values()) or os.path.lexists(os.path.join(library_dir, filename)):
            built[name] = sections[name]
    return built


def _write_databases(library_dir: str, built: dict, user: str) -> None:
    """The six databases, as ONE change; OSError propagates."""
    held = guard.Guard(library_dir)
    change = held.change(user)
    if "code.json" in built and os.path.lexists(os.path.join(library_dir, "code.json")) \
            and not _is_new_code(library_dir):
        change.trash("code.json")    # the old one: the new one is written to the same name
    for name, document in built.items():
        change.replace(name, document)
    change.commit()


def _read_back(library_dir: str, built: dict) -> bool:
    """Whether each new database reads through the guard as exactly what was built."""
    held = guard.Guard(library_dir)
    for name, document in built.items():
        reading = held.read(name)
        if reading.verdict != guard.FINE:
            return False
        for section, table in document.items():
            if (reading.document or {}).get(section, {}) != table:
                return False
    return True


def _remove_old_root_files(library_dir: str, user: str) -> int:
    """Every old root file, marker and copy beside them, into the trash as ONE change; how many."""
    held = guard.Guard(library_dir)
    change = held.change(user)
    gone = []
    for name in OLD_ROOT_FILES + tuple(OLD_MARKS):
        if name != "code.json" and os.path.lexists(
                os.path.join(library_dir, name)):
            gone.append(name)
        gone.extend(_old_traces(library_dir, name))
    for name in gone:
        change.trash(name)
    change.commit()
    return len(gone)


def move_old_pictures(library_dir: str, user: str = "") -> int:
    """File captures into `files/`, comment pictures into their section, as one change; how many."""
    held = guard.Guard(library_dir)
    change = held.change(user)
    moved = 0
    for name in _listing(os.path.join(library_dir, OLD_CAPTURES)):
        match = OLD_FILE_CAPTURE.match(name)
        target = "%s/%s.png" % (library_files.FILES_FOLDER, match.group(1)) if match else ""
        if target and not os.path.lexists(os.path.join(library_dir, *target.split("/"))):
            change.take(target, os.path.join(library_dir, OLD_CAPTURES, name))
            moved += 1
    pictures = set(_listing(os.path.join(library_dir, OLD_COMMENT_PICTURES)))
    used = set()
    prefix = OLD_COMMENT_PICTURES + "/"
    for database in library_files.DATABASE_FOLDERS:
        reading = held.read(database)
        if reading.verdict != guard.FINE:
            continue
        document, changed = json.loads(json.dumps(reading.document)), False
        for page in (document.get("comments") or {}).values():
            for item in (page.get("items") or []) if isinstance(page, dict) else []:
                src = str(item.get("src") or "") if isinstance(item, dict) else ""
                if not src.startswith(prefix):
                    continue
                name = src[len(prefix):]
                target = "%s/%s" % (notes.image_folder(database), name)
                item["src"], changed = target, True
                source = os.path.join(library_dir, OLD_PICTURES, "comments", name)
                if name in pictures and name not in used:
                    change.take(target, source)
                    used.add(name)
                    moved += 1
                elif name in pictures:    # one picture in two sections' comments: each gets its own copy
                    change.put_file(target, _bytes(source))
        if changed:
            change.put(reading.ticket, document)
    for name in sorted(pictures - used):    # a picture no comment shows
        change.trash(prefix + name)
    change.commit()
    for name in _listing(os.path.join(library_dir, OLD_PICTURES)):
        if name.endswith(".lock"):    # lock files an old render left beside a deleted picture
            _remove([os.path.join(library_dir, OLD_PICTURES, name)])
    for section_dir in (library_files.SECTION_FOLDERS[name] for name in library_files.LISTS):
        root = os.path.join(library_dir, section_dir, library_files.VERSIONS)
        for asset_id in _listing(root):    # the copies the old engine kept beside a version ledger
            _remove([os.path.join(root, asset_id, name)
                     for name in _listing(os.path.join(root, asset_id))
                     if name.startswith(library_files.LEDGER + ".")
                     and name.endswith(OLD_COPY_TAILS)])
    for folder in (os.path.join(library_dir, OLD_PICTURES, "comments"),
                   os.path.join(library_dir, OLD_PICTURES), os.path.join(library_dir, OLD_CAPTURES)):
        _remove_empty(folder)
    debug.event("convert", "pictures moved into their sections", moved=moved)
    return moved


def old_trash_of(library_dir: str) -> str:
    """This computer's old trash and history for the library, by its old id or path; "" for none."""
    folder = os.path.abspath(str(library_dir))
    policy, _why = _read_old(library_dir, OLD_POLICY)
    found = []
    library_id = (policy or {}).get("library_id")
    if isinstance(library_id, str) and re.match(r"^[0-9a-f]{32}$", library_id):
        found.append(os.path.join(hostos.config_root(), "history", "library-" + library_id))
    digest = hashlib.sha256(hostos.canonical_path_key(folder).encode("utf-8")).hexdigest()[:10]
    label = hostos.safe_filename(os.path.basename(folder) or "library")[:24]
    found.append(os.path.join(hostos.config_root(), "history", "%s-%s" % (label, digest)))
    return next((path for path in found if os.path.isdir(path)), "")


def old_trash_size(folder: str) -> tuple:
    """(files, bytes) the old trash folder holds."""
    count = total = 0
    for here, _dirs, names in os.walk(folder):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(here, name))
                count += 1
            except OSError:
                pass
    return count, total


def size_text(count: int) -> str:
    """A size in KB or MB, as the user reads it."""
    if count < 1024 * 1024:
        return "%d KB" % max(1, round(count / 1024.0)) if count else "0 KB"
    return "%.1f MB" % (count / 1048576.0)


def delete_old_trash(folder: str) -> bool:
    """Remove the whole old trash folder once the user confirms; whether it was removed."""
    try:
        hostos.check_sandbox(folder)
        shutil.rmtree(folder)
    except OSError as exc:
        debug.event("convert", "the old trash was not removed", folder=folder, error=str(exc))
        return False
    debug.event("convert", "the old trash was removed", folder=folder)
    return True
