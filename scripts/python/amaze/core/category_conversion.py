"""The only module that knows categories stored by name; it gives each one an id."""

import os
import uuid

from amaze.core import library_files, material

DATABASE_IDS = 6    # a section database of this format or newer holds its categories by id
RECORD_IDS = 2    # an `<id>.json` of this format or newer names its categories by id
NAMESPACE = uuid.UUID("def650ab-1698-4075-ace9-21aacbfa95f3")    # never changed: ids follow it
ALL_ROW = ("All", "_All")    # the All row, never a category


def id_for(name: str) -> str:
    """The id a category stored as `name` gets, the same on every computer."""
    return uuid.uuid5(NAMESPACE, name).hex


def _format(document: dict) -> int:
    try:
        return int(document.get("format", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _names(value) -> list:
    """The category names a row holds, All left out."""
    return [name for name in material.category_names(value) if name not in ALL_ROW]


def _order(entry: dict) -> int:
    order = entry.get("order")
    return order if isinstance(order, int) and not isinstance(order, bool) else -1


def database(document):
    """A section database with its categories under ids; one already by id is returned as it is."""
    if not isinstance(document, dict) or _format(document) >= DATABASE_IDS:
        return document
    table, rows = document.get("categories"), document.get("assets")
    listed = {}
    for name, entry in (table.items() if isinstance(table, dict) else ()):
        named = str(name).strip()
        if named and named not in ALL_ROW and id_for(named) not in listed:
            listed[id_for(named)] = dict(entry if isinstance(entry, dict) else {}, name=named)
    after = max([_order(entry) for entry in listed.values()] + [-1]) + 1
    found = dict(document, format=DATABASE_IDS, categories=listed)
    if isinstance(rows, dict):
        found["assets"] = {}
        for asset_id, row in rows.items():
            if isinstance(row, dict) and "categories" in row:
                names = _names(row["categories"])
                for named in names:
                    if id_for(named) not in listed:    # a name its rows use and its list lacks
                        listed[id_for(named)] = {"name": named, "order": after}
                        after += 1
                row = dict(row, categories=[id_for(named) for named in names])
            found["assets"][asset_id] = row
    return found


def record(document):
    """An `<id>.json` with its categories as ids, their names kept beside them."""
    if not isinstance(document, dict) or _format(document) >= RECORD_IDS:
        return document
    found = dict(document, format=RECORD_IDS)
    metadata = document.get("metadata")
    if isinstance(metadata, dict) and "categories" in metadata:
        names = _names(metadata["categories"])
        found["metadata"] = dict(metadata, categories=[id_for(name) for name in names])
        if names:
            found["category_names"] = {id_for(name): name for name in names}
    return found


def convert(held, user: str = "") -> int:
    """Every database and record still by name written with ids, as one change; how many files."""
    from amaze.core import asset_record
    change, records = held.change(user), 0
    for name, folder in library_files.SECTION_FOLDERS.items():
        reading = held.read(name)
        if reading.writable and reading.document:
            change.put(reading.ticket, reading.document)    # read with ids; unchanged bytes are kept
            change.keep_old(name)
        base = held.path(folder)
        for owned in sorted(os.listdir(base)) if os.path.isdir(base) else ():
            owner = library_files.folder_id(owned)
            path = os.path.join(base, owned, owner + library_files.RECORD_SUFFIX) if owner else ""
            wanted = asset_record.in_this_format(path) if path else b""
            if wanted:
                change.put_file(held.inside(path), wanted)
                records += 1
    return records + len(change.commit())
