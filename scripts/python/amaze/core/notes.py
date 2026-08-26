"""The notes store: a notebook page per asset, in the library - one notes.json beside the index, keyed `<section>:<asset id>` for the asset sections and `file:<path>` for File rows. A note is `{"items": [...]}`, an ORDERED flow of `{"t": "text", "text": str}` and `{"t": "todo", "label": str, "done": bool}` (the older `{"text", "todos"}` shape converts on read); writing an EMPTY page removes the key, which is how a note is deleted. An ADAPTER over the Keyed Store Engine: it owns the note's SHAPE and nothing else (▸p/store-guards). A File key is the RAW `os.path.join`, NOT canonicalised - canonicalising would orphan every entry written before the 2026-07-31 merge."""

from __future__ import annotations

from amaze.core import debug, keyed_store

NOTES_FILE = "notes.json"


def note_key(section: str, ident) -> str:
    """The store key for one asset: `<section>:<id-or-path>`."""
    return "%s:%s" % (section, ident)


def normalise(value) -> dict:
    """A well-formed page, or {} for junk/empty - tolerant on purpose: a hand-edited or older-build entry keeps whatever parts parse, including the first build's `{"text", "todos"}` shape, which becomes text-then-todos in the flow."""
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
        elif kind == "text":
            text = item.get("text", "")
            if isinstance(text, str) and text.strip():
                items.append({"t": "text", "text": text})
    if not items:
        return {}
    page = {k: v for k, v in value.items()  # unknown page-level fields ride along (a newer build's addition); "text" and "todos" do not - they were CONSUMED into items above, and carrying them too would duplicate the page on the next read
            if k not in ("items", "text", "todos")}
    page["items"] = items
    return page


SPEC = keyed_store.bind(NOTES_FILE, normalise)  # the engine DECLARES this store; this attaches the one thing it cannot know - what a well-formed page is


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def notes(preferences) -> dict:
    """Every note in this library, keyed by note_key() - a COPY, because a caller holding the live cache could mutate the table without writing anything."""
    return _store(preferences).all()


def note_for(preferences, key: str) -> dict:
    """One asset's note - {} when it has none."""
    return _store(preferences).get(key)


def has_note(preferences, key: str) -> bool:
    """Whether this asset carries anything - the tile badge's question, asked per tile per repaint; a membership test, no copy."""
    return _store(preferences).has(key)


def set_note(preferences, key: str, items: list) -> bool:
    """Store one asset's page (an ordered item flow); an empty page removes the key. Returns whether the write actually happened - a read-only library must not take notes it will lose at restart. The failure reporting is the ENGINE's: the words on the store's Spec (`denied_alert`), the policy in `_commit`."""
    return bool(_store(preferences).set(key, {"items": items}))


def set_notes(preferences, pages: dict):
    """Store MANY pages in one write, `{key: items}` - a sweep calling `set_note` per key rotates a snapshot per key and pushes the restore tier's real history out with copies of the same minute; the engine already had the batched shape (`keyed_store.update`) and this exposes it."""
    return _store(preferences).update(
        {key: {"items": items} for key, items in (pages or {}).items()})


def forget_notes() -> None:
    """Drop the cache - a test seam like its keyed-store siblings; the product's library switch drops every table through `keyed_store.release()` at the switch door."""
    keyed_store.release()


IMAGE_DIR = "img/comments"    # ▸p/comment-images


def adopt_image(preferences, source: str) -> str:
    """Copy `source` into the library and return its LIBRARY-RELATIVE path, or "" when it cannot be read - the note stores that path, never the pixels. ▸p/comment-images"""
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
        with hostos.scratch_beside(target) as scratch:    # the same promote-on-complete every library write uses, so a half-copied picture is never left where a note points ▸p/asset-write-unit
            shutil.copyfile(source, scratch)
    except OSError as exc:
        debug.event("notes", "image not adopted",
                    source=source, error=str(exc))
        return ""
    return relative
