"""Comments: one page per asset or file, in the `comments` section of the database it belongs to."""

from __future__ import annotations

import types
import uuid

from amaze.core import debug, library_db, library_files

SECTION = "comments"

DATABASE_OF = {    # a note key's section prefix -> the database its comments live in
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
    """(database, key in it) for a note key; ("", "") for one of no section."""
    section, _sep, ident = str(key).partition(":")
    return DATABASE_OF.get(section, ""), ident


def normalise_items(items) -> list:
    """The items kept: text, a todo, an image; each with its `id` and its author."""
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
    """Whether the editor sent `old` back: the same kind and words; a ticked todo is still itself."""
    return all(old.get(field) == new.get(field) for field in ("t", "text", "label", "src"))


def _document(preferences, database: str, library: str = ""):
    if library:
        preferences = types.SimpleNamespace(
            dir=library, library_user=getattr(preferences, "library_user", ""))
    return library_db.document(preferences, database)


def notes(preferences) -> dict:
    """Every page in this library, keyed by note_key()."""
    found = {}
    for section, database in DATABASE_OF.items():
        for ident, page in _document(preferences, database).table(SECTION).items():
            if isinstance(page, dict) and page.get("items"):
                found[note_key(section, ident)] = {"items": list(page["items"])}
    return found


def note_for(preferences, key: str) -> dict:
    """One page, `{"items": [...]}` - {} when it has none."""
    database, ident = _split(key)
    if not database:
        return {}
    page = _document(preferences, database).get(SECTION, ident)
    if not isinstance(page, dict) or not page.get("items"):
        return {}
    return {"items": [dict(item) for item in page["items"]]}


def has_note(preferences, key: str) -> bool:
    """Whether this asset or file has a comment; cheap enough per repaint."""
    database, ident = _split(key)
    if not database:
        return False
    page = _document(preferences, database).get(SECTION, ident)
    return isinstance(page, dict) and bool(page.get("items"))


def _stage(held, ident: str, items) -> bool:
    """One page into a document; an empty page removes it. Whether it was taken."""
    author = held.user()
    if not author or not held.writable:
        return False
    pool = [item for item in ((held.get(SECTION, ident) or {}).get("items") or [])
            if isinstance(item, dict)]
    kept = []
    for item in normalise_items([dict(item) for item in (items or [])
                                 if isinstance(item, dict)]):
        if not item.get("author"):    # minted just now: an item the editor sent back unchanged keeps its own
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
    """Store one page; an empty page removes it. Whether the database took it."""
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


IMAGE_DIR = "img/comments"    # ▸p/comment-images


def adopt_image(preferences, source: str) -> str:
    """Copy `source` into the library through the guard; its library-relative path, or ""."""
    import os

    library = str(getattr(preferences, "dir", "") or "")
    if not library or not source or not os.path.isfile(source):
        return ""
    extension = os.path.splitext(source)[1].lower() or ".png"
    relative = "%s/%s%s" % (IMAGE_DIR, uuid.uuid4().hex, extension)
    try:
        with open(source, "rb") as handle:
            data = handle.read()
        change = library_db.guard_of(preferences).change(str(getattr(preferences,
                                                                     "library_user", "")))
        change.put_file(relative, data)
        change.commit()
    except OSError as exc:
        debug.event("notes", "image not adopted", source=source, error=str(exc))
        return ""
    return relative
