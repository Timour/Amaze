"""The notes store: a notebook page per asset, in the library.

The Notes panel (2026-08-01 design: a right-docked page with free text
and a to-do list) writes here. One notes.json beside the index, keyed
`<section>:<asset id>` for the asset sections and `file:<path>` for
File rows - so a note comes back when a removed folder is re-added.

A note is `{"items": [...]}` - an ORDERED flow of
`{"t": "text", "text": str}` and `{"t": "todo", "label": str,
"done": bool}` entries, because the page IS a flowing document: text
above, below and between the to-do frames, in the order written (the
live-pass correction of the first, two-stacks build). The first
build's `{"text", "todos"}` shape converts on read. An EMPTY page is
not stored: writing one removes the key, which is how a note is
deleted - the same shape as clearing a tile icon.

**This module is now an ADAPTER over the Keyed Store Engine**
(`core/keyed_store.py`, 2026-08-03). It owns the note's SHAPE - what a
page is, how a key is spelled, the words the user reads - and nothing
else. Absence, damage, the restore tier, the merge, the atomic write
and the refusal all belong to the engine, in one place, for every
keyed side table.

The docstring here used to say the guard set was icons.json's, "copied
deliberately". It was not: this file had the absent-but-known guard and
icons.json had none, and the tuple of markers this one passed to prove
it was a no-op - five backup names `existed_before` already checks
unconditionally. Two files claiming to share a guard set while each
holds a different part of it is the whole argument for the engine.

**A key is not a path here, and that is deliberate.** The File ident is
the RAW `os.path.join`, un-canonicalised, because canonicalising it
would orphan every entry written before the 2026-07-31 merge. It
follows that a File note does NOT travel between operating systems -
the older docstring claimed it did, and that was never true.
"""

from __future__ import annotations

from amaze.core import keyed_store

NOTES_FILE = "notes.json"

#: The note-yellow from the design - the Notes icon, the + button and
#: the tile badge all carry it.
NOTE_YELLOW = "#fffc66"

#: The prefix a File row's key carries. Named here rather than spelled
#: at the two call sites, because the engine needs it to tell a path
#: key from an asset id inside one mixed file.
FILE_SECTION = "file"


def note_key(section: str, ident) -> str:
    """The store key for one asset: `<section>:<id-or-path>`."""
    return "%s:%s" % (section, ident)


def normalise(value) -> dict:
    """A well-formed page, or {} for junk/empty. Tolerant on purpose:
    a hand-edited or older-build entry keeps whatever parts parse -
    including the first build's {"text", "todos"} shape, which becomes
    text-then-todos in the flow."""
    if not isinstance(value, dict):
        return {}
    raw_items = value.get("items", None)
    if not isinstance(raw_items, list):
        # The first build's shape: one text block, then the list.
        raw_items = []
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
    # Unknown page-level fields ride along (a newer build's addition);
    # "text" and "todos" do not - they were CONSUMED into items above,
    # and carrying them too would duplicate the page on the next read.
    page = {k: v for k, v in value.items()
            if k not in ("items", "text", "todos")}
    page["items"] = items
    return page


#: The engine DECLARES this store (filename, payload, keyspace, the
#: words the user reads); this attaches the one thing it cannot know -
#: what a well-formed page is. Declared centrally so Repair and the
#: library audit can enumerate the side tables without importing Qt.
SPEC = keyed_store.bind(NOTES_FILE, normalise)


def _store(preferences):
    return keyed_store.open_store(SPEC, preferences)


def notes(preferences) -> dict:
    """Every note in this library, keyed by note_key() - a COPY.

    It used to be the live cache, and a caller holding that could
    mutate the table without writing anything: a refused save still lit
    the tile's comment badge, and a later pass read the phantom back
    and wrote its text a second time.
    """
    return _store(preferences).all()


def note_for(preferences, key: str) -> dict:
    """One asset's note - {} when it has none."""
    return _store(preferences).get(key)


def has_note(preferences, key: str) -> bool:
    """Whether this asset carries anything - the tile badge's question,
    asked per tile per repaint. A membership test, no copy."""
    return _store(preferences).has(key)


def set_note(preferences, key: str, items: list) -> bool:
    """Store one asset's page (an ordered item flow); an empty page
    removes the key. Returns whether the write actually happened - a
    read-only library must not take notes it will lose at restart.

    The engine answers with a REASON; this returns the bool its callers
    already branch on. `written()` below is the fuller answer for a
    caller that needs to say WHY.
    """
    return bool(written(preferences, key, items))


def written(preferences, key: str, items: list):
    """set_note, with the engine's full answer - `ok`, `reason` and a
    sentence fit to show the user."""
    result = _store(preferences).set(key, {"items": items})
    if not result and result.sentence:
        from amaze.core import debug
        debug.note(result.sentence)
    elif not result and result.reason == keyed_store.REASON_DENIED:
        from amaze.core import debug
        debug.alert(
            "Your note could not be saved.\n\n"
            "Nothing else has been lost - only this change. The page "
            "keeps what it had.\n\n"
            "Check the library folder is reachable and not read-only, "
            "then edit the note again.",
            key="notes-not-saved")
    return result


def set_notes(preferences, pages: dict):
    """Store MANY pages in one write - `{key: items}`.

    A sweep calling `set_note` per key rewrites `notes.json` once per
    key and rotates a snapshot each time, so 39 gradients carrying an
    old note pushed the restore tier's real history out with 39 copies
    of the same minute. The engine already had the batched shape
    (`keyed_store.update`); this exposes it.
    """
    return _store(preferences).update(
        {key: {"items": items} for key, items in (pages or {}).items()})


def forget_notes() -> None:
    """Drop the cache - a library switch or a test needs a re-read."""
    keyed_store.release()
