"""Library format 3 to 4, the one place that knows the old shapes: read, converted, removed."""

import filecmp
import json
import os
import re
import shutil

from amaze import branding
from amaze.core import asset_record, database, debug, library_files, material
from amaze.helpers import hostos

OLD_FOLDER = "mat"    # format 3: every section's asset files and version folders, together
OLD_PICTURES = library_files.RENDER_FOLDER    # format 3: `img/<id>.png` and `img/<id>_icon.png`
OLD_CAPTURES = library_files.CAPTURE_FOLDER    # format 3: `captures/<id>.png`
INTERFACE = ".interface"    # the builder as `asCode()` Python: read for its type, never executed
BUILDER = ".builder.json"    # the builder as data, its interface under `dialog_script`
STAMP = ".stamp.json"    # the row, written beside the asset files
OLD_SUFFIXES = (BUILDER, STAMP, INTERFACE)
ICON_TAIL = "_icon"    # `img/<id>_icon.png`: a custom icon composed to disk
OLD_FACES = ("preview", "capture")    # stored tile choices that read as `image` now
PRE_ADOPT = ".pre-adopt"    # `mat/<id>.mat.pre-adopt`: backups an earlier texture update left
UPGRADE_BACKUP = "backup-redshift-vopnet-"    # `mat/<this><date>/`: backups a builder upgrade left
OLD_MEMBER_KINDS = ("builder", "interface", "stamp", "tile_icon", "capture")    # an old package's
STALE_SIDECAR_S = 60    # one format 3 save wrote `.builder.json` and `.interface` moments apart

_CREATE_NODE = re.compile(rb'createNode\(\s*[\'"]([^\'"]+)[\'"]')

DONE, NOTHING, BLOCKED, CANCELLED = ("done", "nothing", "blocked", "cancelled")


class Outcome:
    """How one conversion went: its status, why it was blocked, the assets it set aside."""

    def __init__(self, status: str, why: str = "", set_aside=(), counts=None) -> None:
        self.status = status
        self.why = why
        self.set_aside = list(set_aside)    # `SetAside`: rows taken out, old files untouched
        self.counts = dict(counts or {})


def interface_type(raw: bytes) -> str:
    """The builder type a format 3 `.interface` creates first, or ""."""
    match = _CREATE_NODE.search(raw or b"")
    return match.group(1).decode("utf-8", "replace") if match else ""


def builder_from_bytes(raw: bytes, interface, stale: bool = False, where: str = "") -> dict:
    """The builder section from `.builder.json`'s bytes; `interface()` answers `.interface`'s."""
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
    """The builder a package's members carry: a new `json`, else format 3's `builder`/`interface`."""
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
    """Whether a library path is one only format 3 wrote: a leftover the conversion did not take."""
    parts = library_files.split(relative)
    if not parts:
        return False
    top, name = parts[0], parts[-1]
    if top == OLD_FOLDER:    # what the conversion left there is unknown to it: named, never swept
        return False
    if len(parts) == 2 and library_files.owns_assets(top):
        return bool(_id_of(name, OLD_SUFFIXES))
    if len(parts) == 2 and top == OLD_PICTURES:
        return bool(_id_of(name, (ICON_TAIL + ".png", ".png")))
    if len(parts) == 2 and top == OLD_CAPTURES:
        return not name.startswith("file_") and bool(_id_of(name, (".png",)))
    if len(parts) == 4 and parts[1] == library_files.VERSIONS and library_files.owns_assets(top):
        return name.endswith((BUILDER, INTERFACE))
    return False


def _databases(library_dir: str) -> tuple:
    """({database: {id: row}}, why the conversion may not run, or "") from one read of each."""
    found = {}
    for filename in database.DATABASES:
        full = os.path.join(library_dir, filename)
        if not os.path.exists(full):
            if database.absent_but_known(library_dir, filename):
                return {}, ("there is no %s database in the library folder, though Amaze can "
                            "see there was one here before." % database.section_label(filename))
            continue
        try:
            with open(full, encoding="utf-8-sig") as handle:
                document = json.load(handle)
            malformed = database.wrong_shape(document)
            if malformed:
                raise ValueError(malformed)
        except (OSError, ValueError, AttributeError, TypeError):
            return {}, "the %s database is corrupt/unreadable." % database.section_label(filename)
        try:
            ahead = int(document.get("format", 0) or 0) > branding.LIBRARY_FORMAT
        except (TypeError, ValueError):
            ahead = False
        if ahead:
            return {}, ("the %s database was saved by a newer Amaze."
                        % database.section_label(filename))
        found[filename] = {database.row_id(row): row for row in document.get("assets") or []
                           if isinstance(row, dict)}
    return found, ""


def _listing(folder: str) -> list:
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def needs_conversion(library_dir: str) -> bool:
    """Whether anything of format 3 is left: below library version 3, by one listing per folder."""
    from amaze.core import library_policy
    library_dir = str(library_dir or "")
    if not library_dir or library_policy.library_version(library_dir) >= \
            library_policy.LIBRARY_VERSION:
        return False
    return bool(_plan_ids(library_dir) or _old_version_folders(library_dir))


def settle_version(library_dir: str) -> bool:
    """An open library with nothing of format 3 left takes library version 3; True when it moved."""
    from amaze.core import library_policy
    if not library_dir or not os.path.isfile(os.path.join(library_dir, library_files.MATERIALS)):
        return False
    if library_policy.library_version(library_dir) >= library_policy.LIBRARY_VERSION \
            or needs_conversion(library_dir):
        return False
    return library_policy.set_library_version(library_dir, library_policy.LIBRARY_VERSION)


def _plan_ids(library_dir: str) -> set:
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
        hostos.promote_scratch(scratch, target)
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
    created = []
    try:
        ok, old_files = _convert_one(library_dir, asset_id, section, rows, faces, counts, created)
    except (OSError, ValueError, hostos.PathEscape) as exc:
        ok, old_files = _kept(asset_id, str(exc), counts), _old_files(library_dir, asset_id,
                                                                      section)
    if not ok:
        for path in created:    # what this asset's turn wrote; its format 3 files stay untouched
            try:
                hostos.remove_file(path)
            except OSError:
                pass
    return ok, old_files


def _old_files(library_dir: str, asset_id: str, section: str) -> list:
    """Every format 3 file of one asset, wherever it lies."""
    home = material.section_folder(library_dir, section)
    old_dir = os.path.join(library_dir, OLD_FOLDER)
    candidates = [os.path.join(folder, asset_id + suffix) for folder in (old_dir, home)
                  for suffix in OLD_SUFFIXES]
    candidates += [os.path.join(old_dir, asset_id + suffix) for suffix in (".mat", "_cop.mat")]
    candidates += [os.path.join(library_dir, OLD_PICTURES, asset_id + ".png"),
                   os.path.join(library_dir, OLD_PICTURES, asset_id + ICON_TAIL + ".png"),
                   os.path.join(library_dir, OLD_CAPTURES, asset_id + ".png")]
    return [path for path in candidates if os.path.lexists(path)]


def _convert_one(library_dir: str, asset_id: str, section: str, rows: dict,
                 faces: dict, counts: dict, created: list) -> tuple:
    """`_convert_asset`'s work; every file it writes new is listed in `created`."""
    old_files = _old_files(library_dir, asset_id, section)
    old_dir = os.path.join(library_dir, OLD_FOLDER)
    home = material.section_folder(library_dir, section)
    old = {suffix: path for suffix in OLD_SUFFIXES
           for path in (os.path.join(old_dir, asset_id + suffix),
                        os.path.join(home, asset_id + suffix)) if os.path.lexists(path)}
    moves = []    # (source, target, keep the target as it is because it is newer)
    for suffix in (".mat", "_cop.mat"):
        source = os.path.join(old_dir, asset_id + suffix)
        if os.path.lexists(source):
            target = os.path.join(home, asset_id + suffix)
            moves.append((source, target, os.path.lexists(target)))
    render = os.path.join(library_dir, OLD_PICTURES, asset_id + ".png")
    capture = os.path.join(library_dir, OLD_CAPTURES, asset_id + ".png")
    icon = os.path.join(library_dir, OLD_PICTURES, asset_id + ICON_TAIL + ".png")
    render, capture = (render if os.path.lexists(render) else "",
                       capture if os.path.lexists(capture) else "")
    shown = _shown_picture(faces, asset_id, section, render, capture)
    picture = os.path.join(home, asset_id + ".png")
    pictures = [path for path in (render, capture) if path]
    if os.path.lexists(icon):
        pictures.append(icon)
    if section in library_files.ASSET_SECTIONS and not any(
            target for _s, target, _n in moves if target.endswith(asset_id + ".mat")) \
            and not os.path.lexists(os.path.join(home, asset_id + ".mat")):
        return _kept(asset_id, "its .mat is missing", counts), old_files
    for source, target, newer in moves:
        if not newer:
            created.append(target)
            _copy_in(source, target)
    shown = shown if shown and not os.path.lexists(picture) else ""    # one there already is newer
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
    counts["deleted"] += _remove(list(old.values()) + [source for source, _t, _n in moves]
                                 + pictures)
    counts["converted"] += 1
    return True, []


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
            counts["left"] += 1    # two sections name it, or it is no asset's: Check Library names it
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
    return True


def _stored_faces(library_dir: str) -> dict:
    """{key: face} as format 3 stored them in icons.json, read raw: the store refuses old faces."""
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
        if name.endswith(PRE_ADOPT) and os.path.isfile(path) and not os.path.islink(path):
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


def convert(directory: str, confirm, progress=None) -> Outcome:
    """Convert a format 3 library whole once `confirm()` says yes; `progress(done, total)` is told."""
    from amaze.core import library_policy
    library_dir = str(directory or "")
    if not needs_conversion(library_dir):
        return Outcome(NOTHING)
    rows, why = _databases(library_dir)
    if why:
        debug.event("convert", "conversion blocked - nothing was changed", why=why)
        return Outcome(BLOCKED, why)
    if not confirm():
        debug.event("convert", "conversion declined - nothing was changed")
        return Outcome(CANCELLED)
    faces = _stored_faces(library_dir)
    counts = {"converted": 0, "deleted": 0, "kept": 0, "left": 0}
    set_aside = []
    units = [("asset", asset_id) for asset_id in sorted(_plan_ids(library_dir))] + [
        ("versions", folder) for folder in _old_version_folders(library_dir)]
    for done, (kind, item) in enumerate(units):
        if progress is not None:    # shown only: a conversion is not stopped partway by choice
            progress(done, len(units))
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
            counts["left"] += 1    # a picture or a stamp of nothing: Check Library names it
            continue
        ok, old_files = _convert_asset(library_dir, item, owner, rows, faces, counts)
        if not ok:
            set_aside.append(SetAside(item, owner, rows.get(owner, {}).get(item), old_files))
    _take_out(library_dir, set_aside)
    counts["deleted"] += _remove_old_backups(os.path.join(library_dir, OLD_FOLDER))
    for folder in (os.path.join(library_dir, OLD_FOLDER, library_files.VERSIONS),
                   os.path.join(library_dir, OLD_FOLDER),
                   os.path.join(library_dir, OLD_CAPTURES)):
        _remove_empty(folder)
    counts["left"] += len(_listing(os.path.join(library_dir, OLD_FOLDER)))
    debug.event("convert", "library conversion", set_aside=len(set_aside), **counts)
    library_policy.set_library_version(library_dir, library_policy.LIBRARY_VERSION)
    return Outcome(DONE, set_aside=set_aside, counts=counts)


class SetAside:
    """An asset the conversion could not convert: its row, taken out, and its untouched old files."""

    def __init__(self, asset_id: str, section: str, row, files: list) -> None:
        self.asset_id = asset_id
        self.section = section
        self.row = row    # None for files no database named
        self.files = list(files)

    @property
    def name(self) -> str:
        return str((self.row or {}).get("name") or self.asset_id)


def _take_out(library_dir: str, set_aside: list) -> None:
    """Each set-aside row out of its database, in one write per database, logged whole first."""
    by_section = {}
    for one in set_aside:
        if one.row is not None and one.section in library_files.ASSET_SECTIONS:
            by_section.setdefault(one.section, set()).add(one.asset_id)
            debug.event("convert", "row taken out of its database - its files could not be "
                        "converted", file=one.section, row=one.row, files=one.files)
    for filename, ids in by_section.items():
        path = os.path.join(library_dir, filename)
        try:
            with open(path, encoding="utf-8-sig") as handle:
                document = json.load(handle)
            document["assets"] = [row for row in document.get("assets") or []
                                  if not (isinstance(row, dict) and database.row_id(row) in ids)]
            hostos.snapshot_before_write(path)
            hostos.write_json_atomic(path, document, indent=4)
        except (OSError, ValueError) as exc:
            debug.event("convert", "set-aside rows not taken out", file=filename, error=str(exc))


def trash_set_aside(library_dir: str, set_aside: list) -> int:
    """The set-aside assets' old files into Amaze's trash, at the user's word; how many moved."""
    from amaze.core import quarantine
    moved = sum(bool(quarantine.quarantine_file(library_dir, path))
                for one in set_aside for path in one.files if os.path.lexists(path))
    debug.event("convert", "set-aside files moved to the trash", moved=moved)
    return moved
