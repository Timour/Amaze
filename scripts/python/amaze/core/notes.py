"""Comments: one page per asset or file, in the `comments` section of the database it belongs to."""

from __future__ import annotations

import os
import types
import uuid

from amaze.core import debug, guard, library_db, library_files, material, texstore
from amaze.helpers import hostos

SECTION = "comments"

DATABASE_OF = {    # a note key's section prefix -> the database its comments are stored in
    "material": library_files.MATERIALS,
    "cop": library_files.NODES,
    "code": library_files.CODE,
    "gradient": library_files.COLORS,
    "file": library_files.FILES,
}


def note_key(section: str, ident) -> str:
    """The key for one asset's or file's comments: `<section>:<id-or-file-key>`."""
    return "%s:%s" % (section, ident)


def _split(key: str) -> tuple:
    """(database, key in it) for a note key; two empty strings for a key of no known section."""
    section, _sep, ident = str(key).partition(":")
    return DATABASE_OF.get(section, ""), ident


def normalise_items(items) -> list:
    """The valid text, todo and image items, each with its `id` and its author; others dropped."""
    kept = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("t")
        if kind == "todo":
            label = item.get("label", "")
            if not isinstance(label, str) or not label.strip():
                continue
            one = {"t": "todo", "label": label.strip(), "done": bool(item.get("done", False))}
        elif kind == "image":
            src = item.get("src", "")
            if not isinstance(src, str) or not src.strip():
                continue    # an image with no src is dropped ▸p/comment-images
            fallback = item.get("text", "")
            one = {"t": "image", "src": src.strip(),
                   "text": fallback if isinstance(fallback, str) else ""}
        elif kind == "text":
            text = item.get("text", "")
            if not isinstance(text, str) or not text.strip():
                continue
            one = {"t": "text", "text": text}
        else:
            continue
        one["id"] = str(item.get("id") or uuid.uuid4().hex)
        one["author"] = str(item.get("author") or "")
        kept.append(one)
    return kept


def _same_item(old: dict, new: dict) -> bool:
    """Whether `new` is `old` sent back by the editor: same kind and text; `done` is not compared."""
    return all(old.get(field) == new.get(field) for field in ("t", "text", "label", "src"))


def _document(preferences, database: str, library: str = ""):
    if library:
        preferences = types.SimpleNamespace(
            dir=library, library_user=getattr(preferences, "library_user", ""))
    return library_db.document(preferences, database)


def _items(preferences, key: str) -> list:
    """The items of one page that are tables; a page of any other shape has none."""
    database, ident = _split(key)
    page = _document(preferences, database).get(SECTION, ident) if database else None
    items = page.get("items") if isinstance(page, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def note_for(preferences, key: str) -> dict:
    """One page, `{"items": [...]}` - {} when it has none."""
    items = _items(preferences, key)
    return {"items": [dict(item) for item in items]} if items else {}


def has_note(preferences, key: str) -> bool:
    """Whether this asset or file has a comment; cheap enough per repaint."""
    return bool(_items(preferences, key))


def _stage(held, ident: str, items) -> bool:
    """Put one page into a document; an empty page removes it. Whether the document accepted it."""
    author = held.user()
    if not author or not held.writable:
        return False
    pool = [item for item in ((held.get(SECTION, ident) or {}).get("items") or [])
            if isinstance(item, dict)]
    kept = []
    for item in normalise_items([dict(item) for item in (items or [])
                                 if isinstance(item, dict)]):
        if not item.get("author"):    # an unchanged item takes back its stored id and author; a new one gets this user
            same = next((old for old in pool if _same_item(old, item)), None)
            if same is not None:
                pool.remove(same)
                item["id"], item["author"] = str(same.get("id")), str(same.get("author") or "")
            else:
                item["author"] = author
        kept.append(item)
    if not kept:
        if held.get(SECTION, ident) is not None:
            held.drop(SECTION, ident)
        return True
    held.put(SECTION, ident, {"items": kept})
    return True


def set_note(preferences, key: str, items: list, library: str = "") -> bool:
    """Store one page; an empty page removes it. Whether the database accepted it."""
    database, ident = _split(key)
    if not database:
        return False
    return _stage(_document(preferences, database, library), ident, items)


def set_notes(preferences, pages: dict) -> bool:
    """Store many pages, `{key: items}`, as one change per database."""
    taken = True
    held = library_db.library_for(preferences)
    touched = set()
    with held.holding():
        for key, items in (pages or {}).items():
            database, ident = _split(key)
            if not database:
                continue
            taken = _stage(_document(preferences, database), ident, items) and taken
            touched.add(database)
    for database in touched:
        saved = library_db.save(preferences, database)
        taken = taken and (bool(saved) or saved.reason == "unchanged")
    return taken


def _shown(held, ident: str, page) -> set:
    """The library-relative path of each picture `page` shows; none outside the library."""
    prefix = next((name for name, database in DATABASE_OF.items() if database == held.name), "")
    found = set()
    for item in normalise_items(page.get("items")) if isinstance(page, dict) else ():
        path = image_path(held.guard.dir, note_key(prefix, ident), item["src"]) \
            if item["t"] == "image" else ""
        if path and held.guard.inside(path):
            found.add(held.guard.inside(path))
    return found


def pictures_follow(held):
    """`also` for a save: a picture no comment shows is trashed, one shown again comes back."""
    if SECTION not in held.kind.sections:
        return None
    pages = [ident for ident in held.changed(SECTION)    # a deleted asset's folder is trashed whole
             if held.name == library_files.FILES or held.get("assets", ident) is not None]
    if not pages:
        return None

    def follow(change):
        shown = set()
        for ident, page in held.table(SECTION).items():
            shown |= _shown(held, ident, page)
        for ident in pages:
            for relative in _shown(held, ident, held.was(SECTION, ident)) - shown:
                if os.path.isfile(held.guard._relative(relative)):
                    change.trash(relative)
            for relative in _shown(held, ident, held.get(SECTION, ident)):
                kept = "" if os.path.exists(held.guard._relative(relative)) \
                    else held.guard.in_trash(relative)    # taken out, then put back by an undo
                if kept:
                    change.move(kept, relative)
    return follow


def copy_image_into_library(preferences, source: str, key: str) -> str:
    """Copy image `source` into the comments folder of the asset `key` names, or of Files; its src."""
    library = str(getattr(preferences, "dir", "") or "")
    database, ident = _split(key)
    if not library or not database or not source or not os.path.isfile(source):
        return ""
    name = uuid.uuid4().hex + (os.path.splitext(source)[1].lower() or ".png")
    try:
        held = library_db.guard_of(preferences)
        if database == library_files.FILES:
            src = relative = "%s/%s/%s" % (library_files.FILES_FOLDER, library_files.COMMENT_FOLDER, name)
        else:
            row = _document(preferences, database).get("assets", ident) or {}
            folder = material.folder_in(library, database, ident, row.get("name", ""))
            relative = held.inside(os.path.join(folder, library_files.COMMENT_FOLDER, name))
            src = texstore.OWN_PREFIX + library_files.COMMENT_FOLDER + "/" + name
        with open(source, "rb") as handle:
            data = handle.read()
        change = held.change(str(getattr(preferences, "library_user", "")))
        change.put_file(relative, data)
        change.commit()
    except (OSError, hostos.PathOutsideBase, guard.Refused) as exc:
        debug.event("notes", "image not copied", source=source, error=str(exc))
        return ""
    return src


def image_path(library_dir: str, key: str, src: str) -> str:
    """A comment picture's file, in its asset's folder for `$AMAZEASSET/`; "" for one outside."""
    if not src or os.path.isabs(src) or ".." in src.replace("\\", "/").split("/"):
        return ""
    if not src.startswith(texstore.OWN_PREFIX):
        return os.path.join(library_dir or "", src)
    database, ident = _split(key)
    if not database or not material.is_safe_asset_id(ident):
        return ""
    return os.path.join(material.listed_dir(library_dir, database, ident),
                        *src[len(texstore.OWN_PREFIX):].split("/"))
