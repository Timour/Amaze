"""The notes store: one page per asset in notes.json, keyed by `note_key`. ▸p/store-guards"""

from __future__ import annotations

from amaze.core import debug, keyed_store

NOTES_FILE = "notes.json"


def note_key(section: str, ident) -> str:
    """The store key for one asset: `<section>:<id-or-path>`."""
    return "%s:%s" % (section, ident)


def normalise(value) -> dict:
    """A well-formed page, `{items: [...]}`, or {} for junk or empty; keeps what parses."""
    if not isinstance(value, dict):
        return {}
    raw_items = value.get("items", None)
    if not isinstance(raw_items, list):
        raw_items = []  # the first build's shape: one text block, then the todo list
        text = value.get("text", "")
        if isinstance(text, str) and text.strip():
            raw_items.append({"t": "text", "text": text})
        legacy = value.get("todos", [])
        if isinstance(legacy, list):
            for item in legacy:
                if isinstance(item, dict):
                    raw_items.append({"t": "todo",
                                      "label": item.get("label", ""),
                                      "done": item.get("done", False)})
    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        kind = item.get("t")
        if kind == "todo":
            label = item.get("label", "")
            if not isinstance(label, str) or not label.strip():
                continue
            items.append({"t": "todo", "label": label.strip(),
                          "done": bool(item.get("done", False))})
        elif kind == "image":
            src = item.get("src", "")
            if not isinstance(src, str) or not src.strip():
                continue    # an image with no src is dropped ▸p/comment-images
            fallback = item.get("text", "")
            items.append({"t": "image", "src": src.strip(),
                          "text": fallback if isinstance(fallback, str)
                          else ""})
        elif kind == "text":
            text = item.get("text", "")
            if isinstance(text, str) and text.strip():
                items.append({"t": "text", "text": text})
    if not items:
        return {}
    page = {k: v for k, v in value.items()  # unknown page-level fields ride along
            if k not in ("items", "text", "todos")}
    page["items"] = items
    return page


SPEC = keyed_store.bind(NOTES_FILE, normalise)  # the keyed store, with this module's page shape


def _store(preferences, library: str = ""):
    return keyed_store.open_store(SPEC, preferences, library)


def notes(preferences) -> dict:
    """A copy of every note in this library, keyed by note_key()."""
    return _store(preferences).all()


def note_for(preferences, key: str) -> dict:
    """One asset's note - {} when it has none."""
    return _store(preferences).get(key)


def has_note(preferences, key: str) -> bool:
    """Whether this asset has a note; a membership test, cheap enough per repaint."""
    return _store(preferences).has(key)


def set_note(preferences, key: str, items: list, library: str = "") -> bool:
    """Store one asset's page; an empty page removes the key. Whether the write happened."""
    return bool(_store(preferences, library).set(key, {"items": items}))


def set_notes(preferences, pages: dict):
    """Store many pages, `{key: items}`, in one write; use it for a sweep, not `set_note`."""
    return _store(preferences).update(
        {key: {"items": items} for key, items in (pages or {}).items()})


IMAGE_DIR = "img/comments"    # ▸p/comment-images


def adopt_image(preferences, source: str) -> str:
    """Copy `source` into the library; its library-relative path, or "". ▸p/comment-images"""
    import os
    import shutil
    import uuid

    from amaze.helpers import hostos

    library = str(getattr(preferences, "dir", "") or "")
    if not library or not source or not os.path.isfile(source):
        return ""
    extension = os.path.splitext(source)[1].lower() or ".png"
    folder = os.path.join(library, *IMAGE_DIR.split("/"))
    relative = "%s/%s%s" % (IMAGE_DIR, uuid.uuid4().hex, extension)
    target = os.path.join(library, *relative.split("/"))
    try:
        os.makedirs(folder, exist_ok=True)
        with hostos.scratch_beside(target) as scratch:    # promoted only when complete ▸p/asset-write-unit
            shutil.copyfile(source, scratch)
    except OSError as exc:
        debug.event("notes", "image not adopted",
                    source=source, error=str(exc))
        return ""
    return relative
