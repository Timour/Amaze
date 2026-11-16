"""The `.amazepkg` container: one zip whose `package.json` lists asset entries and file entries."""

import json
import os
import shutil
import zipfile

from amaze import branding, messages
from amaze.core import asset_record, debug, library_conversion, library_files, material, notes
from amaze.core import texstore
from amaze.helpers import hostos, wording

FORMAT = 4    # the newest this build reads; 4: add-on rows (groups, Add-On tab icons), core/addons.py
ASSETS_FORMAT = 2    # what a package of library assets is written as, so an older Amaze still reads it
SUFFIX = ".amazepkg"
MANIFEST = "package.json"
RECORD_KIND = "json"    # `<id>.json` holding the builder alone: the row is stored in the manifest
DERIVED = (RECORD_KIND,)    # composed for the package, never copied: the library's copy holds the metadata
MAX_UNPACKED_BYTES = 16 * 1024 ** 3    # the largest one import may unpack, by the sizes the zip declares ▸r/zip-declared-size
OBJECTS = ("record", "note", "files", "textures")    # what an entry holds as an object, or leaves out
PIECE = 1024 * 1024    # how much of a member is in memory at once while it is compared


class PackageError(Exception):
    """A package this build cannot read or write - the message holds the complete reason."""


def collect_asset(model, mat_id) -> dict:
    """One asset's row, comments, files and builder, as an export packs them; flushes saves first."""
    from amaze.core import library_db
    library_db.flush(model.preferences)    # its `<id>.json` holds every change made before the export
    return _collected(model, mat_id)


def _collected(model, mat_id) -> dict:
    """One exportable entry for a library asset: its record, its existing files, textures and note."""
    mat_id = str(mat_id)
    asset = next((a for a in model.assets
                  if str(a.mat_id) == mat_id), None)
    if asset is None:
        raise PackageError("no asset %s in the %s library"
                           % (mat_id, model.NOTES_SECTION))
    sources = {kind: path
               for kind, path in model.asset_files(mat_id).items()
               if kind not in DERIVED and os.path.exists(path)}
    record = asset.get_as_dict()
    textures = {}
    for token in (record.get("textures") or ()):
        source = texstore.resolve(str(token), model.preferences)
        if os.path.isfile(source):
            textures[str(token)] = source
        else:
            debug.event("packages", "inventory texture missing",
                        token=str(token), mat_id=mat_id)
    if len(textures) != len(record.get("textures") or ()):
        record = dict(record)    # the packed record must not list a texture the package does not contain
        record["textures"] = sorted(textures)
    page = notes.note_for(model.preferences,
                          notes.note_key(model.NOTES_SECTION, mat_id))
    builder = (asset_record.saved_builder(model.preferences, mat_id, model.DB_FILENAME)
               if model.DB_FILENAME in library_files.ASSET_SECTIONS else {})
    return {"type": "asset", "section": model.NOTES_SECTION,
            "id": mat_id, "record": record,
            "note": page, "sources": sources, "textures": textures, "builder": builder}


def collect_file(path: str, kind: str) -> dict:
    """One exportable entry for a plain file row - the whole file is stored under its kind."""
    if not os.path.isfile(path):
        raise PackageError("not a file: %s" % path)
    return {"type": "file", "kind": str(kind or "other"),
            "name": os.path.basename(path), "source": path}


def write_package(out_path: str, items) -> int:
    """Write collector items as one package, in one atomic step; returns how many entries went in."""
    hostos.check_sandbox(out_path)
    entries = []
    payload = []
    written = []    # (arc, bytes) composed here rather than copied from a file
    for n, item in enumerate(items):
        entry = dict(item)
        if entry.get("type") == "asset":
            arcs = {}
            for kind, source in entry.pop("sources", {}).items():
                arc = "assets/%s/%s/%s" % (
                    entry["section"], entry["id"],
                    os.path.basename(source))
                arcs[kind] = arc
                payload.append((arc, source))
            builder = entry.pop("builder", None)
            if builder:
                arcs[RECORD_KIND] = "assets/%s/%s/%s%s" % (
                    entry["section"], entry["id"], entry["id"], material.RECORD_SUFFIX)
                written.append((arcs[RECORD_KIND], asset_record.encode(
                    {"format": asset_record.FORMAT, asset_record.BUILDER: builder})))
            entry["files"] = arcs
            texarcs = {}
            for t, (token, source) in enumerate(
                    sorted(entry.pop("textures", {}).items())):
                arc = "assets/%s/%s/textures/%d_%s" % (    # the index keeps equal basenames apart; import places by token
                    entry["section"], entry["id"], t,
                    os.path.basename(source))
                texarcs[token] = arc
                payload.append((arc, source))
            if texarcs:
                entry["textures"] = texarcs
        elif entry.get("type") == "file":
            arc = "files/%d_%s" % (n, entry["name"])    # the index keeps two exports of one basename apart
            entry["arc"] = arc
            payload.append((arc, entry.pop("source")))
        else:
            raise PackageError("unknown entry type %r"
                               % entry.get("type"))
        entries.append(entry)
    manifest = {"format": ASSETS_FORMAT, "app": branding.APP_VERSION,
                "entries": entries}
    with hostos.scratch_beside(out_path) as scratch:
        with zipfile.ZipFile(scratch, "w",
                             zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(MANIFEST, json.dumps(manifest, indent=2))
            for arc, source in payload:
                bundle.write(source, arc)
            for arc, raw in written:
                bundle.writestr(arc, raw)
    return len(entries)


def manifest_from(bundle, path: str) -> dict:
    """The manifest of an open bundle; PackageError when missing, unreadable, too new or malformed."""
    try:
        raw = bundle.read(MANIFEST)
    except KeyError:
        raise PackageError("%s carries no %s - not an Amaze package"
                           % (os.path.basename(path), MANIFEST)) from None
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageError("cannot read %s: %s" % (path, exc)) from None
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise PackageError("unreadable %s: %s"
                           % (MANIFEST, exc)) from None
    got = manifest.get("format") if isinstance(manifest, dict) else None
    if _whole_number(got) and got > FORMAT:
        raise PackageError(
            "package format %s is newer than the %s this build reads "
            "- update Amaze to import it" % (got, FORMAT))
    problems = _shape_problems(manifest)
    if problems:
        debug.event("packages", "manifest refused",
                    package=os.path.basename(path), problems=problems[:20])
        raise PackageError(messages.PACKAGE_NOT_READABLE
                           % os.path.basename(path))
    return manifest


def _whole_number(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _shape_problems(manifest) -> list:
    """What in a parsed manifest would make a reader fail, one phrase each; [] when nothing."""
    if not isinstance(manifest, dict):
        return ["the manifest is not an object"]
    found = [] if _whole_number(manifest.get("format")) \
        else ["format is not a whole number"]
    entries = manifest.get("entries", [])
    if not isinstance(entries, list):
        return found + ["entries is not a list"]
    for n, entry in enumerate(entries, 1):
        found += ["entry %d: %s" % (n, problem)
                  for problem in _entry_problems(entry)]
    return found


def _entry_problems(entry) -> list:
    """What in one manifest entry would make a reader fail: the fields it reads, by their types."""
    if not isinstance(entry, dict):
        return ["not an object"]
    found = ["%s is not an object" % key for key in OBJECTS
             if entry.get(key) is not None and not isinstance(entry[key], dict)]
    for key in ("files", "textures"):
        named = entry.get(key)
        if isinstance(named, dict) and not all(
                isinstance(arc, str) for arc in named.values()):
            found.append("%s names a member that is not text" % key)
    if entry.get("type") == "file" and not isinstance(entry.get("arc"), str):
        found.append("arc is not text")
    record = entry.get("record") if isinstance(entry.get("record"), dict) else {}
    cats = record.get("categories")
    if cats is not None and not isinstance(cats, str) and not (
            isinstance(cats, list) and all(isinstance(c, str) for c in cats)):
        found.append("categories is not text or a list of text")
    if record.get("colors") is not None and not isinstance(record["colors"], list):
        found.append("colors is not a list")
    note = entry.get("note") if isinstance(entry.get("note"), dict) else {}
    if note.get("items") is not None and not isinstance(note["items"], list):
        found.append("note items is not a list")
    return found


def unpacked_bytes(bundle, members) -> int:
    """What `members` of an open bundle unpack to, by the sizes the zip declares. ▸r/zip-declared-size"""
    sizes = {info.filename: info.file_size for info in bundle.infolist()}
    return sum(sizes.get(name, 0) for name in set(members))


def copy_member(bundle, member, handle) -> None:
    """One member of an open bundle into an open file, a piece at a time, never whole in memory."""
    with bundle.open(member) as source:
        shutil.copyfileobj(source, handle)


def _holds(bundle, member, path) -> bool:
    """Whether the file at `path` is the member byte for byte, both read a piece at a time."""
    if os.path.getsize(path) != bundle.getinfo(member).file_size:
        return False
    with bundle.open(member) as source, open(path, "rb") as handle:
        while True:
            piece = source.read(PIECE)
            if piece != handle.read(PIECE):
                return False
            if not piece:
                return True


def read_manifest(path: str) -> dict:
    """The package's manifest, opening the file once."""
    try:
        with zipfile.ZipFile(path) as bundle:
            return manifest_from(bundle, path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageError("cannot read %s: %s" % (path, exc)) from None


def import_package(models, prefs, path: str, restore: bool = False) -> dict:
    """Import a package, new ids under `Import` or own ids with `restore`; PackageError if incomplete."""
    if not getattr(prefs, "dir", ""):
        raise PackageError("no library set - nowhere to import into")
    try:
        bundle = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageError("cannot read %s: %s" % (path, exc)) from None
    with bundle:    # one open file for the manifest, the check and the import
        manifest = manifest_from(bundle, path)
        if manifest.get("kind"):
            raise PackageError("%s is an add-on, not library assets"
                               % os.path.basename(path))
        problems = _verify(bundle, manifest)
        if problems:
            raise PackageError("%s is not whole: %s"
                               % (os.path.basename(path),
                                  "; ".join(problems)))
        return import_entries(models, prefs, bundle,
                              manifest.get("entries", ()), restore)


def import_entries(models, prefs, bundle, entries,
                   restore: bool = False) -> dict:
    """Import chosen entries of an open package; a failing entry adds to `refused`, the rest go on."""
    if not getattr(prefs, "dir", ""):
        raise PackageError("no library set - nowhere to import into")
    needed = unpacked_bytes(bundle, [arc for entry in entries for arc in _arcs(entry)])
    if needed > MAX_UNPACKED_BYTES:    # before the first write, so a rejected import leaves the library unchanged
        raise PackageError(messages.PACKAGE_TOO_LARGE % (
            wording.byte_size(needed), wording.byte_size(MAX_UNPACKED_BYTES)))
    summary = {"imported": 0, "skipped": 0, "files": 0, "refused": 0,
               "categories": {}, "problems": []}
    staged = []    # appended rows and their written files, committed once per model by `_commit_assets`
    taken = set()    # texture targets already staged: two entries may share one
    for entry in entries:
        name = str((entry.get("record") or {}).get("name")
                   or entry.get("name") or "?")
        try:
            if entry.get("type") == "asset":
                appended = _import_asset(models, prefs, bundle, entry,
                                         restore, summary, taken)
                if appended is not None:
                    staged.append(appended)
            elif entry.get("type") == "file":
                _import_file(prefs, bundle, entry, summary)
        except zipfile.BadZipFile as exc:
            debug.event("packages", "entry refused", error=str(exc),
                        name=name)
            summary["refused"] += 1
            summary["problems"].append(
                "%s did not read back whole" % name)
        except Exception as exc:                          # noqa: BLE001
            debug.event("packages", "entry refused", error=str(exc),
                        name=name)
            summary["refused"] += 1
            summary["problems"].append("%s: %s" % (name, exc))    # the real cause, as raised
    _commit_assets(prefs, staged, summary)
    return summary


def _land_model(prefs, model, items) -> bool:
    """One model's appended rows and every file they brought, as ONE change; False: none saved."""
    from amaze.core import library_db
    if not library_db.accepts(prefs, model.DB_FILENAME):
        return False
    held = library_db.guard_of(prefs)
    with library_db.library_for(prefs).holding():
        model._stage_rows(model._doc())

    def files(change):
        for _model, asset, _entry, _row, written in items:
            asset_record.add_staged(change, held, written,
                                    metadata=json.loads(json.dumps(asset.get_as_dict())))
    return bool(library_db.save(prefs, model.DB_FILENAME, also=files))


def _commit_assets(prefs, staged, summary) -> None:
    """Save each model's rows and files once, then the saved ones' notes; failed rows are removed."""
    pages = {}
    by_model = {}
    for item in staged:
        by_model.setdefault(id(item[0]), []).append(item)
    for items in by_model.values():
        model = items[0][0]
        try:
            stored = _land_model(prefs, model, items)
        except Exception as exc:                          # noqa: BLE001
            debug.event("packages", "entry refused", error=str(exc),
                        name=model.DB_FILENAME)
            summary["problems"].extend("%s: %s" % (item[1].name or "?", exc)
                                       for item in items)
            stored = False
        if not stored:
            for _model, asset, _entry, _row, written in reversed(items):
                asset_record.discard(written)
                model._take_back_refused_append(asset)
            summary["refused"] += len(items)
            continue
        for _model, asset, entry, row, _written in items:
            model._content_state[str(asset.mat_id)] = model._content_stat(asset.mat_id)    # saved now
            page = entry.get("note") or {}
            section = str(entry.get("section") or "")
            if page.get("items"):
                pages[notes.note_key(section, asset.mat_id)] = page["items"]
            cats = row.get("categories") or []
            summary["categories"].setdefault(section, set()).update(
                [cats] if isinstance(cats, str) else cats)
            summary["imported"] += 1
    if not pages:
        return
    try:    # the assets are already saved - a failed note write must not recount them as refused
        notes.set_notes(prefs, pages)
    except Exception as exc:                          # noqa: BLE001
        debug.event("packages", "note not written", error=str(exc),
                    names=sorted(pages))


def _import_asset(models, prefs, bundle, entry, restore, summary, taken):
    """One asset entry's row into its model and its files into scratches, unsaved; None when skipped."""
    section = str(entry.get("section") or "")
    model = models.get(section)
    if model is None:
        summary["skipped"] += 1
        return
    row = dict(entry.get("record") or {})
    if restore:
        tag = str(row.get("curated") or "")
        if tag:    # curated rows match on the tag, since ids differ per library
            present = {str(a._extra.get("curated") or "")
                       for a in model.assets}
        else:
            present = {str(a.mat_id) for a in model.assets}
        if (tag or str(row.get("id") or "")) in present:
            summary["skipped"] += 1
            return
    else:
        row.pop("id", None)
        row.pop("uid", None)    # the old id key, which readers copy into `id`
        row["categories"] = ["Import"]
    asset = model._asset_from_row(row)
    targets = model.asset_files(asset.mat_id)
    held = {}    # the builder's members, read into `<id>.json` rather than written as files
    written = []    # (asset_record.TAKE, target, scratch) and the record: committed with the row
    try:
        for kind, arcname in (entry.get("files") or {}).items():
            if kind == RECORD_KIND or kind in library_conversion.OLD_MEMBER_KINDS:
                held[kind] = _small_member(bundle, arcname)
                continue
            target = targets.get(kind)
            if not target or kind in DERIVED:
                continue
            written.append(_staged_member(bundle, arcname, target))
        store_prefix = texstore.TOKEN_PREFIX + texstore.STORE_DIR_NAME + "/"
        for token, arcname in (entry.get("textures") or {}).items():
            if not str(token).startswith(store_prefix):    # only store tokens may be written
                raise PackageError("not a store texture token: %r" % token)
            target = hostos.contained_join(    # PathEscape on `..`; the entry counts in `refused`
                prefs.dir, *str(token)[len(texstore.TOKEN_PREFIX):].split("/"))
            if target in taken:
                continue
            if os.path.exists(target):
                if _holds(bundle, arcname, target):
                    continue    # byte-identical - another asset already shares the file
                debug.event("packages", "texture member replaced",
                            token=str(token))
            written.append(_staged_member(bundle, arcname, target))
            taken.add(target)
        written.extend(_staged_builder(model, asset.mat_id, held))
    except BaseException:
        asset_record.discard(written)
        raise
    model._append_record(asset)
    return model, asset, entry, row, written


def _staged_member(bundle, member, target) -> tuple:
    """`member` written whole into a scratch beside `target`, staged to replace it on commit."""
    hostos.check_sandbox(target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    scratch = hostos.unique_scratch(target)
    try:
        with open(scratch, "wb") as handle:
            copy_member(bundle, member, handle)
    except BaseException:
        hostos.discard_scratch(scratch)
        raise
    return (asset_record.TAKE, target, scratch)


BUILDER_MEMBER_MAX = 16 * 1024 * 1024    # a builder is text; anything larger is not one


def _small_member(bundle, member) -> bytes:
    """A builder member's bytes, read through a bounded stream; PackageError past the bound."""
    with bundle.open(member) as source:
        raw = source.read(BUILDER_MEMBER_MAX + 1)
    if len(raw) > BUILDER_MEMBER_MAX:
        raise PackageError("%s is too large to be a builder" % member)
    return raw


def _staged_builder(model, mat_id, held: dict) -> list:
    """The asset's `<id>.json`, with the builder a package holds; old formats via library_conversion."""
    if model.DB_FILENAME not in library_files.ASSET_SECTIONS:
        return []
    builder = library_conversion.builder_from_members(held) if held else {}
    sections = {asset_record.BUILDER: builder} if builder else {}
    return [(asset_record.RECORD, asset_record.path_for(
        model.preferences, mat_id, model.DB_FILENAME), sections)]


def _import_file(prefs, bundle, entry, summary) -> None:
    """One plain-file entry into `<library>/import/`, a numbered suffix avoiding an existing name."""
    folder = os.path.join(prefs.dir, "import")
    os.makedirs(folder, exist_ok=True)
    name = os.path.basename(str(entry.get("name") or "package_file"))
    target = os.path.join(folder, name)
    stem, ext = os.path.splitext(name)
    bump = 0
    while os.path.exists(target):
        bump += 1
        target = os.path.join(folder, "%s_%d%s" % (stem, bump, ext))
    hostos.check_sandbox(target)
    with hostos.scratch_beside(target) as scratch:
        with open(scratch, "wb") as handle:
            copy_member(bundle, entry["arc"], handle)
    summary["files"] += 1


def _arcs(entry) -> list:
    """The members one entry writes: a file entry its `arc`, an asset entry its files and textures."""
    if entry.get("type") == "file":
        return [entry.get("arc")]
    return (list((entry.get("files") or {}).values())
            + list((entry.get("textures") or {}).values()))


def _verify(bundle, manifest) -> list:
    """Every manifest member an open bundle lacks, one sentence each; [] means none is missing."""
    problems = []
    held = set(bundle.namelist())
    for entry in manifest.get("entries", ()):
        for arc in _arcs(entry):
            if arc and arc not in held:
                problems.append("missing member %s" % arc)
    return problems


def verify_package(path: str) -> list:
    """Missing members, one sentence each, opening the file once; [] means none is missing."""
    with zipfile.ZipFile(path) as bundle:
        return _verify(bundle, manifest_from(bundle, path))
