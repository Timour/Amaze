"""The only module that knows the 2.0 layout: flat asset files and `matX/`; it converts to 3.0."""

import os
import shutil

from amaze.core import asset_record, debug, guard, library_files, library_policy
from amaze.core import library_settings, material, texstore

KINDS = (".mat", library_files.RECORD_SUFFIX, library_files.PICTURE_SUFFIX,
         library_files.COMPANION_TAIL + ".mat")    # a 2.0 asset's files, `<id><kind>` side by side


def needs_conversion(library_dir: str) -> bool:
    """Whether the library is in the 2.0 layout, which this Amaze opens only once converted."""
    return library_settings.library_formats(library_dir)[0] == library_policy.LAYOUT_2_0


def convert(held: guard.Guard, user: str = "") -> int:
    """Each asset's files into its folder, `matX/` into the materials using it; the count moved."""
    change, copies, moved = held.change(user), [], 0
    try:
        for section in library_files.ASSET_SECTIONS:
            moved += _assets_into_folders(held, change, section)
        _store_into_materials(held, change, copies)
        for _kind, target, scratch in copies:
            change.take(held.inside(target), scratch)
        change.commit()    # from its journal on, the copies are the guard's to finish or remove
    except (guard.Refused, ValueError) as exc:    # refused before anything was written
        asset_record.discard(copies)
        raise OSError(str(exc)) from exc
    leftover = held.change(user)    # second: a trash step runs before the moves of its own change
    for name in (texstore.OLD_STORE,) + tuple(
            "%s/%s" % (library_files.SECTION_FOLDERS[section], library_files.VERSIONS)
            for section in library_files.ASSET_SECTIONS):
        if os.path.exists(held.path(*name.split("/"))):
            leftover.trash(name)
    leftover.commit()
    debug.event("library", "converted to 3.0", dir=held.dir, assets=moved)
    return moved


def _rows(held, section: str) -> dict:
    return dict((held.read(section).document or {}).get("assets") or {})


def _folder_of(held, section: str, asset_id: str, rows: dict) -> str:
    row = rows.get(asset_id) if isinstance(rows.get(asset_id), dict) else {}
    return os.path.join(material.section_folder(held.dir, section),
                        material.folder_name(row.get("name"), asset_id))


def _assets_into_folders(held, change, section: str) -> int:
    """Every flat `<id>.*` file and `versions/<id>/` of a section moved into `<name>__<id>/`."""
    base, rows, owners = material.section_folder(held.dir, section), _rows(held, section), set()
    names = sorted(os.listdir(base)) if os.path.isdir(base) else []
    for name in names:
        owner = next((library_files.asset_id(name, (kind,)) for kind in KINDS
                      if library_files.asset_id(name, (kind,))), None)
        if owner and os.path.isfile(os.path.join(base, name)):
            change.move(held.inside(os.path.join(base, name)),
                        held.inside(os.path.join(_folder_of(held, section, owner, rows), name)))
            owners.add(owner)
    stores = os.path.join(base, library_files.VERSIONS)
    for owner in sorted(os.listdir(stores)) if os.path.isdir(stores) else ():
        if material.is_safe_asset_id(owner) and os.path.isdir(os.path.join(stores, owner)):
            change.move(held.inside(os.path.join(stores, owner)), held.inside(os.path.join(
                _folder_of(held, section, owner, rows), library_files.VERSIONS)))
            owners.add(owner)
    return len(owners)


def _store_into_materials(held, change, copies: list) -> None:
    """Each `matX/` folder a material lists: moved into its first user, copied into the others."""
    rows, users = _rows(held, library_files.MATERIALS), {}
    for asset_id, row in sorted(rows.items()):
        for token in (row.get("textures") if isinstance(row, dict) else None) or ():
            old = texstore.old_store_parts(token)
            if old:
                owned = users.setdefault(old[0], [])
                if asset_id not in owned:
                    owned.append(asset_id)
    firsts = {}    # material -> its first store folder, whose files keep their places in it
    for folder in sorted(users):
        source = held.path(texstore.OLD_STORE, folder)
        if not os.path.isdir(source):
            continue
        for number, owner in enumerate(users[folder]):
            own = _folder_of(held, library_files.MATERIALS, owner, rows)
            first = firsts.setdefault(owner, folder) == folder
            for path in _files_under(source):
                rest = os.path.relpath(path, source).split(os.sep)
                target = texstore.old_store_target(own, folder, rest, first)
                if number == 0:
                    change.move(held.inside(path), held.inside(target))
                else:
                    copies.append(asset_record.staged_write(
                        target, lambda scratch, path=path: shutil.copyfile(path, scratch)))


def _files_under(folder: str) -> list:
    found = []
    for root, _dirs, files in os.walk(folder):
        found += [os.path.join(root, name) for name in sorted(files)
                  if not library_files.is_os_noise(name)]
    return sorted(found)
