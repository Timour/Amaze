"""The `.amazepkg` container, format 2: one zip whose `package.json` lists ASSET entries (a library record verbatim, every existing family file, the token-keyed textures, the note page) and plain FILE entries with a kind - the unit of sharing between libraries and the online store's payload."""

import json
import os
import zipfile

from PySide6 import QtCore

from amaze import branding
from amaze.core import debug, notes, texstore
from amaze.helpers import hostos

FORMAT = 2    # 2: entries may carry {token: arc} textures - a format-1 build must refuse rather than import silently bare
SUFFIX = ".amazepkg"
MANIFEST = "package.json"
DERIVED = ("stamp",)    # regenerated from the record on every save, so packing one ships an instantly-stale copy


class PackageError(Exception):
    """A package this build cannot read or write - the message carries the reason whole."""


def collect_asset(model, mat_id) -> dict:
    """One exportable entry for a library asset: the record verbatim, {kind: source path} for every family file that EXISTS, and its note page; the model's own NOTES_SECTION names the section."""
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
        record = dict(record)    # the packed record must not promise a texture the package does not carry
        record["textures"] = sorted(textures)
    page = notes.note_for(model.preferences,
                          notes.note_key(model.NOTES_SECTION, mat_id))
    return {"type": "asset", "section": model.NOTES_SECTION,
            "id": mat_id, "record": record,
            "note": page, "sources": sources, "textures": textures}


def collect_file(path: str, kind: str) -> dict:
    """One exportable entry for a plain file row - the file rides whole under its kind."""
    if not os.path.isfile(path):
        raise PackageError("not a file: %s" % path)
    return {"type": "file", "kind": str(kind or "other"),
            "name": os.path.basename(path), "source": path}


def write_package(out_path: str, items) -> int:
    """Write collector items as one package - sandbox-guarded, landed whole via scratch-beside - answering how many entries went in."""
    hostos.check_sandbox(out_path)
    entries = []
    payload = []
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
            entry["files"] = arcs
            texarcs = {}
            for t, (token, source) in enumerate(
                    sorted(entry.pop("textures", {}).items())):
                arc = "assets/%s/%s/textures/%d_%s" % (    # the index keeps shared-store basenames apart; landing goes by TOKEN, never by arc
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
    manifest = {"format": FORMAT, "app": branding.APP_VERSION,
                "entries": entries}
    with hostos.scratch_beside(out_path) as scratch:
        with zipfile.ZipFile(scratch, "w",
                             zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr(MANIFEST, json.dumps(manifest, indent=2))
            for arc, source in payload:
                bundle.write(source, arc)
    return len(entries)


def read_manifest(path: str) -> dict:
    """The package's manifest - refused by name for a missing/unreadable manifest or a format NEWER than this build reads."""
    try:
        with zipfile.ZipFile(path) as bundle:
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
    got = manifest.get("format")
    if not isinstance(got, int) or got > FORMAT:
        raise PackageError(
            "package format %s is newer than the %s this build reads "
            "- update Amaze to import it" % (got, FORMAT))
    return manifest


def import_package(models, prefs, path: str, restore: bool = False) -> dict:
    """Bring one package into the library - FRESH by default (ids minted, every asset filed under `Import`), adopt-only by the package's ORIGINAL ids with `restore=True` - refusing whole on a missing member or no library, and answering {imported, skipped, files, refused, problems, categories}."""
    if not getattr(prefs, "dir", ""):
        raise PackageError("no library set - nowhere to import into")
    problems = verify_package(path)
    if problems:
        raise PackageError("%s is not whole: %s"
                           % (os.path.basename(path),
                              "; ".join(problems)))
    manifest = read_manifest(path)
    with zipfile.ZipFile(path) as bundle:
        return import_entries(models, prefs, bundle,
                              manifest.get("entries", ()), restore)


def import_entries(models, prefs, bundle, entries,
                   restore: bool = False) -> dict:
    """SELECTED entries out of an open package (local or remote-ranged) into the library - the whole-package door above and the per-tile online door share this one loop; a member whose zip CRC refuses counts `refused` without abandoning the batch."""
    if not getattr(prefs, "dir", ""):
        raise PackageError("no library set - nowhere to import into")
    summary = {"imported": 0, "skipped": 0, "files": 0, "refused": 0,
               "categories": {}, "problems": []}
    for entry in entries:
        name = str((entry.get("record") or {}).get("name")
                   or entry.get("name") or "?")
        try:
            if entry.get("type") == "asset":
                _import_asset(models, prefs, bundle, entry, restore,
                              summary)
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
            summary["problems"].append("%s: %s" % (name, exc))    # the REAL cause, not re-costumed as a data failure: a sandbox refusal or a full disk is not a corrupt package
    return summary


def _import_asset(models, prefs, bundle, entry, restore, summary) -> None:
    """One asset entry into its section's model - payload family first, then the row, then save, then the note; a refused save takes the row back out and counts `refused`."""
    section = str(entry.get("section") or "")
    model = models.get(section)
    if model is None:
        summary["skipped"] += 1
        return
    row = dict(entry.get("record") or {})
    if restore:
        tag = str(row.get("curated") or "")
        if tag:    # curated rows match on the TAG - ids are minted per library, so the same palette carries a different id everywhere
            present = {str((getattr(a, "_extra", None) or {})
                           .get("curated") or "") for a in model.assets}
        else:
            present = {str(a.mat_id) for a in model.assets}
        if (tag or str(row.get("id") or "")) in present:
            summary["skipped"] += 1
            return
    else:
        row.pop("id", None)
        row.pop("uid", None)    # the pre-connector id spelling adopts onto `id` in every reader, so it must go too or the mint never runs
        row["categories"] = ["Import"]
    asset = model._asset_from_row(row)
    targets = model.asset_files(asset.mat_id)
    for kind, arcname in (entry.get("files") or {}).items():
        target = targets.get(kind)
        if not target:
            continue
        hostos.check_sandbox(target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with hostos.scratch_beside(target) as scratch:
            with open(scratch, "wb") as handle:
                handle.write(bundle.read(arcname))
    store_prefix = texstore.TOKEN_PREFIX + texstore.STORE_DIR_NAME + "/"
    for token, arcname in (entry.get("textures") or {}).items():
        if not str(token).startswith(store_prefix):    # contained is not enough - a token aimed anywhere but the store could mint the library's own control files (policy.json, a file named matX)
            raise PackageError("not a store texture token: %r" % token)
        target = hostos.contained_join(    # the token comes off a manifest nobody vouches for - PathEscape refuses `..` and the whole entry counts refused
            prefs.dir, *str(token)[len(texstore.TOKEN_PREFIX):].split("/"))
        data = bundle.read(arcname)
        if os.path.exists(target):
            with open(target, "rb") as handle:
                if handle.read() == data:
                    continue    # byte-identical - another asset already shares the file
            debug.event("packages", "texture member replaced",    # the folder name carries the OWNING asset's identity, so an updated package updates it; a copy-to sharer drifts with it
                        token=str(token))
        hostos.check_sandbox(target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with hostos.scratch_beside(target) as scratch:
            with open(scratch, "wb") as handle:
                handle.write(data)
    at = len(model._assets)
    model.beginInsertRows(QtCore.QModelIndex(), at, at)
    try:
        model._assets.append(asset)
    finally:
        model.endInsertRows()
    if not model.save():
        model.beginRemoveRows(QtCore.QModelIndex(), at, at)    # nothing named the id yet, so taking the row back leaves only lonely payload files, which Clean Library already sweeps
        try:
            model._assets.pop(at)
        finally:
            model.endRemoveRows()
        summary["refused"] += 1
        return
    page = entry.get("note") or {}
    if page.get("items"):
        try:    # the asset is already saved - a failed note page must not recount a landed import as refused
            notes.set_note(prefs, notes.note_key(section, asset.mat_id),
                           page["items"])
        except Exception as exc:                          # noqa: BLE001
            debug.event("packages", "note not written", error=str(exc),
                        name=str(asset.mat_id))
    cats = row.get("categories") or []
    summary["categories"].setdefault(section, set()).update(
        [cats] if isinstance(cats, str) else cats)
    summary["imported"] += 1


def _import_file(prefs, bundle, entry, summary) -> None:
    """One plain-file entry into `<library>/import/`, a numbered suffix keeping an existing name safe."""
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
            handle.write(bundle.read(entry["arc"]))
    summary["files"] += 1


def verify_package(path: str) -> list:
    """Problems, one sentence each - every manifest member the zip does not hold; [] means whole."""
    problems = []
    with zipfile.ZipFile(path) as bundle:
        held = set(bundle.namelist())
    for entry in read_manifest(path).get("entries", ()):
        arcs = ([entry.get("arc")] if entry.get("type") == "file"
                else list((entry.get("files") or {}).values())
                + list((entry.get("textures") or {}).values()))
        for arc in arcs:
            if arc and arc not in held:
                problems.append("missing member %s" % arc)
    return problems
