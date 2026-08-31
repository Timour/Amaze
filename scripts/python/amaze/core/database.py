"""Database handler for Matlib: json documents on disk, one live connection per database file; migration step `_MIGRATIONS[N]` runs when a loaded document carries `version == N` and mutates it in place to version N+1, so a `SCHEMA_VERSION` bump must ship with its step or the document keeps its old version and is recorded as an incomplete chain."""

import copy
import json
import os
import hashlib
import uuid
from typing import Self

from amaze import branding
from amaze.core import debug
from amaze.helpers import hostos
from amaze import messages


SCHEMA_VERSION = 8


_MIGRATIONS = {}


def _migration_v4(data: dict) -> None:
    """v4 to v5: strips `favorite` and `icon` from every asset row; both keys must also stay in the record's retired-key set, else the unknown-key courtesy carries them and the next save re-emits them."""
    rows = data.get("assets")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.pop("favorite", None)
        row.pop("icon", None)


_MIGRATIONS[4] = _migration_v4


def _migration_v5(data: dict) -> None:
    """v5 to v6: strips `favorite` again - Colors rows never pass through `Material`, so schema-5 files kept regrowing it; the key must also stay in the retired-key set or the next save re-emits it."""
    rows = data.get("assets")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.pop("favorite", None)


_MIGRATIONS[5] = _migration_v5


def _migration_v6(data: dict) -> None:
    """v6 to v7: strips `builder` from every asset row - written by every save since the fork and read by nothing since 2026-08-14; the key must also stay in the record class retired-key set or the next save re-emits it."""
    rows = data.get("assets")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.pop("builder", None)


_MIGRATIONS[6] = _migration_v6


def _migration_v7(data: dict) -> None:
    """v7 to v8: mints an `id` for every asset row that has neither `id` nor the legacy `uid`, IN PLACE - a row without one mints a fresh identity on every load, so the notes and tile icon stored against it orphan, and an ordinary save cannot repair it because the connector unions BY id and keeps the id-less original."""
    rows = data.get("assets")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not str(row.get("id") or row.get("uid") or ""):
            row["id"] = uuid.uuid4().hex


_MIGRATIONS[7] = _migration_v7


_INSTANCES: dict = globals().get("_INSTANCES", {})


_INTEGRITY_NOTES: dict = globals().get("_INTEGRITY_NOTES", {})


_EXISTED_MARKERS = {
    "code.json": (".amaze_code_starter_v1", ".assetlib_code_starter_v1"),
    "gradients.json": (".amaze_gradient_seed_v1",
                       ".assetlib_gradient_seed_v1"),
}


def absent_but_known(directory: str, filename: str) -> str:
    """Name of one trace proving an absent database file once existed in `directory`, or empty when it truly is new; shared with the `library.py` cleanup so no two callers can answer the newness of one file differently."""
    return hostos.existed_before(
        os.path.join(directory, filename), _EXISTED_MARKERS.get(filename, ())
    )


def _and_list(names) -> str:
    """Joins names into a sentence list; a deliberate local twin of `helpers.and_list`, kept because `helpers` imports `hou` at module level and this module must stay importable where Houdini cannot start."""
    names = list(names)
    if len(names) <= 1:
        return names[0] if names else ""
    return "%s and %s" % (", ".join(names[:-1]), names[-1])


def absent_traces(directory: str, filename: str) -> list:
    """Every trace proving the file was here - a refusal must name them all so its instruction works in one pass."""

    return hostos.existed_before_all(
        os.path.join(directory, filename), _EXISTED_MARKERS.get(filename, ())
    )


SECTION_DATABASES = (
    ("library.json", "Material", "material"),
    ("cops.json", "Node", "node"),
    ("code.json", "Code", "snippet"),
    ("gradients.json", "Color", "color"),
)


DATABASES = tuple(name for name, _label, _holds in SECTION_DATABASES)

_SECTION_LABELS = {name: label
                   for name, label, _holds in SECTION_DATABASES}

_SECTION_HOLDS = {name: holds
                  for name, _label, holds in SECTION_DATABASES}


ASSET_FILE_OWNERS = ("library.json", "cops.json")


ID_CLAIMING_DATABASES = ("library.json", "cops.json", "code.json")


def row_id(row: dict) -> str:
    """The id a stored row claims, `mat_id` as the fallback spelling - the ONE home for reading a row's identity, shared with repair's survey."""
    return str(row.get("id", row.get("mat_id", "")))


def ids_claimed_by(directory: str, filenames: tuple = ()) -> tuple:
    """Returns `(by_file, unreadable)`: asset ids claimed per readable database in `directory`, plus filenames that exist but will not read; absent files appear in neither (newness is `absent_but_known` policy) - the one home for id ownership over the shared asset folders."""
    by_file, unreadable = {}, []
    for filename in (filenames or ID_CLAIMING_DATABASES):
        full = os.path.join(directory, filename)
        if not os.path.exists(full):
            continue
        try:
            with open(full, encoding="utf-8-sig") as handle:
                data = json.load(handle)
            malformed = wrong_shape(data)
            if malformed:
                raise ValueError(malformed)
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            unreadable.append(filename)
            debug.event("database", "a database claiming ids could not "
                                    "be read", file=full, error=str(exc))
            continue
        found = set()
        for asset in data.get("assets") or []:
            if not isinstance(asset, dict):
                debug.event("database", "skipped a non-record entry",
                            file=full, entry=repr(asset)[:80])
                continue
            found.add(row_id(asset))
        by_file[filename] = found
    return (by_file, unreadable)


def asset_id_for_file(name: str, extensions: tuple,
                      tail: str = "") -> str | None:
    """The asset id a file in the library folders belongs to, or None when it is not such a file; the one classifier for both the delete guard and the sweep, strict only in the refusing direction - a stem not purely alphanumeric once `tail` and the extension come off (a sync-client conflicted-copy rename, for example) is logged and left alone, because the sweep deletes what this returns."""
    matched = next((e for e in extensions
                    if name.lower().endswith(e.lower())), None)
    if matched is None:
        return None

    stem = name[: -len(matched)]
    if tail and stem.endswith(tail):
        stem = stem[: -len(tail)]
    if "." in stem:
        debug.event("cleanup", "file not classified - extra suffix",
                    file=name, stem=stem[:60])
        return None

    if not stem.isalnum():
        debug.event("cleanup", "file not classified - left alone",
                    file=name, stem=stem[:60])
        return None
    return stem


def _merge_record(mine: dict, theirs: dict, base, filename: str,
                  adopted: list) -> None:
    """Field-wise three-way merge for a record both sessions hold - EVERY field, judged against `base`, the row as of our last load or successful save. Only a field both sides moved away from the base is a conflict; that one keeps the local value and tells the user. `base` None means we cannot say who moved, and every difference is treated as a conflict."""
    for field in set(mine) | set(theirs):
        if field == "id" or field not in theirs:
            continue
        their_value = theirs.get(field)
        my_value = mine.get(field)
        if my_value == their_value:
            continue
        based = isinstance(base, dict)
        theirs_moved = not based or their_value != base.get(field)
        mine_moved = not based or my_value != base.get(field)
        if theirs_moved and not mine_moved:
            mine[field] = their_value
            adopted.append((str(mine.get("id")), field, their_value))
            debug.event("database", "adopted a field another session "
                        "changed", file=filename,
                        mat_id=str(mine.get("id")), field=field)
        elif mine_moved and not theirs_moved:
            continue    # ours is the only edit; nothing to say
        else:
            debug.event("database", "field collision - this session's "
                        "value kept", file=filename,
                        mat_id=str(mine.get("id")), field=field)
            debug.alert(
                messages.EDIT_CONFLICT_KEPT_YOURS % (
                    mine.get("name") or mine.get("id") or "this item",),
                key="edit-conflict-%s-%s" % (mine.get("id"), field))


def wrong_shape(document) -> str:
    """Empty string when `document` is shaped like a database, else a log phrase; valid json is not a valid database, and the merge and the cleanup must share this one answer - container keys only (`assets`, `categories`, `tags`, `gradients`), never individual rows, so one bad row cannot cost a session its writes."""
    if not isinstance(document, dict):
        return "top level is %s, not an object" % type(document).__name__

    for key in ("assets", "categories", "tags", "gradients"):
        value = document.get(key, [])
        if not isinstance(value, list):
            return "%s is %s, not a list" % (key, type(value).__name__)
    return ""


def wrong_table_shape(document, key: str) -> str:
    """Empty string when `document` is `{key: {...}}`, else a log phrase; the `wrong_shape` twin for the mapping-payload side tables - a null or list payload otherwise reaches `.items()` and raises AttributeError, which the `(OSError, ValueError)` database guards never catch."""
    if not isinstance(document, dict):
        return "top level is %s, not an object" % type(document).__name__
    value = document.get(key, {})
    if not isinstance(value, dict):
        return "%s is %s, not an object" % (key, type(value).__name__)
    return ""


def _keyed_store_label(filename: str) -> str:
    """The label a side table declares for itself in the `keyed_store` registry - one table, so the name Repair says cannot drift from the store it names."""
    try:
        from amaze.core import keyed_store
    except Exception:                                     # noqa: BLE001
        return ""
    spec = keyed_store.store_for(filename)
    return spec.label if spec else ""


def _keyed_store_noun(filename: str) -> str:
    try:
        from amaze.core import keyed_store
    except Exception:                                     # noqa: BLE001
        return ""
    spec = keyed_store.store_for(filename)
    return spec.noun if spec else ""


def section_name(filename: str) -> str:
    """The section label with its filename, like `Nodes (cops.json)` - the filename stays because it is what the user will look for on disk."""

    label = _SECTION_LABELS.get(filename) or _keyed_store_label(filename)
    return "%s (%s)" % (label, filename) if label else filename


def section_label(filename: str) -> str:
    """The bare tab name, like `Nodes`, for a sentence that sends the reader to a control; both forms come from the one table, and a message must keep one name per thing."""
    return (_SECTION_LABELS.get(filename)
            or _keyed_store_label(filename) or filename)


def section_noun(filename: str, count: int = 2) -> str:
    """The word a section count counts, like `material` or `nodes`, singular or plural by `count`; from the same table as the labels so the noun cannot drift, because a bare number in a recovery dialog is unanswerable."""
    noun = (_SECTION_HOLDS.get(filename)
            or _keyed_store_noun(filename) or "saved thing")
    return noun if count == 1 else noun + "s"


def load_survivable(db, path: str, reload: bool = False):
    """load() for a model built or switched during panel setup: the primary index raises through to the repair dialog, while an unreadable secondary latches `_write_blocked`, preserves the file beside itself, alerts once and returns a fresh empty document - never the connector cache, whose falsy state is what makes the next load retry; `reload` must be true on a library switch, because `load()` returns any cached document."""
    try:
        return db.reload_with_path(path) if reload else db.load(path)
    except (OSError, ValueError) as exc:
        if db._filename == "library.json":
            raise
        db._write_blocked = True
        hostos.preserve_unreadable(
            os.path.join(str(path), db._filename),
            why=section_label(db._filename))
        debug.event("database", "unreadable - saving disabled",
                    file=db._filename, error=str(exc))
        debug.alert(
            messages.SECTION_UNREADABLE_SAVING_DISABLED
            % section_noun(db._filename),
            key="unreadable-" + db._filename)
        return {"categories": ["_All"], "tags": [], "assets": []}


class DatabaseConnector:
    """Saves a json database to disk with one live connection per database file, instances keyed by `filename`; `_instances` and `_integrity_notes` bind to module-level dicts because `panel.py` reloads this module on every panel open and a re-executed class body would otherwise strand live models on a dead registry."""

    _instances: dict = _INSTANCES

    def __new__(cls, filename: str = "library.json") -> Self:
        inst = cls._instances.get(filename)
        if inst is None:
            inst = super().__new__(cls)
            inst._filename = filename
            inst._data = {}
            inst._path = ""
            inst._disk_stat = None
            inst._loaded_ids = set()
            inst._loaded_rows = {}

            inst._adopted = []
            inst._adopted_fields = []
            inst._dropped = []

            # `_forgotten` records explicit deletes because `_absorb_rows` can only keep rows; the version, format and write latches below are read by `save()` and reset by `reload_with_path`, so they are set plainly here, never left as getattr defaults.
            inst._forgotten = set()

            inst._loaded_version = SCHEMA_VERSION
            inst._migration_incomplete = False
            inst._write_blocked = False
            inst._loaded_format = 0
            inst._format_ahead = False
            inst._format_reported = False
            inst._block_reported = False
            cls._instances[filename] = inst
        return inst

    def _stat_file(self):
        """(size, sha256) of the file on disk, or None when unreadable - CONTENT, not (mtime_ns, size): a same-size edit passes a stat compare and a byte-identical rewrite trips it, so the hash is the verdict (~1.4ms on the real library, saves only). ▸r/peer-read"""
        return hostos.fingerprint_of(self._path + self._filename)

    def _remember_disk_state(self) -> None:
        """The stale-write and merge baseline, read from the FILE and never from the buffer we meant to write - a save whose rename is overwritten in the same instant must see its own row missing here, or its next save reads that row as a peer's DELETION and drops it. `_disk_stat`, `_loaded_rows` and `_loaded_ids` are re-derived together, from one read. ▸r/peer-read"""
        answer = hostos.peer_read(self._path + self._filename)
        document = (answer.document if answer.document is not None
                    else (self._data or {}))    # unreadable or absent: our memory is the only baseline available, and the stale-write guard has its own refusal for that
        self._disk_stat = answer.fingerprint
        self._loaded_rows = {
            str(a.get("id")): copy.deepcopy(a)
            for a in document.get("assets", [])
            if isinstance(a, dict)
        }    # the merge BASE: a field differing from this is an edit, and only a field BOTH sides moved is a conflict
        self._loaded_ids = set(self._loaded_rows)

    def _migrate(self, data: dict) -> None:
        """Apply `_MIGRATIONS` in order and stamp the reached version - on `data` as an ARGUMENT, so a raising step cannot leave the connector holding a half-migrated document; a newer-schema document is left untouched, a chain gap latches `_migration_incomplete` (save() holds the stamp back on it), and the format latch - write permission, never healing mid-session - is read here too, per library, never remembered across a repoint."""
        try:
            version = int(data.get("version", 1))
        except (TypeError, ValueError):
            debug.event("database", "unreadable version stamp - read "
                        "as legacy", file=self._filename,
                        found=repr(data.get("version")))
            version = 1
        self._loaded_version = version
        self._migration_incomplete = False
        try:
            self._loaded_format = int(data.get("format", 0) or 0)
        except (TypeError, ValueError):
            self._loaded_format = 0
        self._format_ahead = (
            self._loaded_format > branding.LIBRARY_FORMAT)
        if self._format_ahead:
            debug.event("database", "library format ahead - read-only",
                        file=self._filename, found=self._loaded_format,
                        known=branding.LIBRARY_FORMAT)
            debug.alert(
                messages.LIBRARY_FORMAT_AHEAD_READ_ONLY,
                key="format-ahead-%s" % self._filename)
        if version > SCHEMA_VERSION:
            debug.event(
                "database", "newer schema than this build",
                file=self._filename, found=version, known=SCHEMA_VERSION,
            )
            return
        while version < SCHEMA_VERSION:
            step = _MIGRATIONS.get(version)
            if step is None:
                debug.event("database", "migration step missing",
                            file=self._filename, at_version=version)
                self._migration_incomplete = True
                break
            step(data)
            version += 1
            debug.event("database", "migrated", file=self._filename,
                        to_version=version)
        data["version"] = version
        self._loaded_version = version

    def load(self, path: str) -> dict:
        """Load from disk. A secondary database absent WITH traces refuses for the session (absent_but_known - absence alone is not newness), absent without them seeds empty; a missing PRIMARY index raises to the caller; a path change reroutes to `reload_with_path`, never repointing `_path` under the cached document; reads are `utf-8-sig` (a BOM is a routine sync artifact) while writes stay plain utf-8; the parse commits to `_data` only AFTER `_migrate`, so a raising step leaves it falsy and the next load retries; a parsed non-database raises ValueError - refuse over overwrite, the same outcome a truncated file gets."""
        if (self._data and self._path
                and hostos.canonical_path_key(self._path)
                != hostos.canonical_path_key(path)):
            return self.reload_with_path(path)
        self._path = path
        if not self._data:
            full = self._path + self._filename
            if not os.path.exists(full) and self._filename != "library.json":
                traces = absent_traces(self._path, self._filename)
                if traces:
                    self._refuse_absent(full, traces)
                    return self._data
                self._data = {"categories": ["_All"], "tags": [], "assets": []}
                self.save()
            else:
                with open(full, encoding="utf-8-sig") as lib_json:
                    parsed = json.load(lib_json)
                malformed = wrong_shape(parsed)
                if malformed:
                    debug.event("database", "load refused - not a database",
                                file=self._filename, reason=malformed)
                    raise ValueError(
                        "%s is not a database (%s)"
                        % (self._filename, malformed))
                self._migrate(parsed)
                self._data = parsed
                self._normalize_all_category()
                self._note_suspicious_shrink(full)
            self._remember_disk_state()
        return self._data

    _integrity_notes: dict = _INTEGRITY_NOTES

    @classmethod
    def take_integrity_notes(cls) -> list:
        """The pending findings, cleared on read - they describe load moments superseded once the next load runs."""
        notes = [line for lines in cls._integrity_notes.values()
                 for line in lines]
        cls._integrity_notes.clear()
        return notes

    def _note_suspicious_shrink(self, full: str) -> None:
        """After a successful parse: report (never block, never repair) a document holding under half of its newest snapshot - `wrong_shape` is ASKED, not caught, because a mis-shaped snapshot raising here would cost the load this note promises never to cost."""
        try:
            here = len(self._data.get("assets") or [])
            newest = None
            for tier in ("bak-1", "bak-2", "bak-3", "bak-first"):
                candidate = full + "." + tier
                if os.path.exists(candidate):
                    newest = candidate
                    break
            if newest is None:
                return
            with open(newest, encoding="utf-8-sig") as handle:
                snapshot = json.load(handle)
            if wrong_shape(snapshot):
                return
            backed = len(snapshot.get("assets") or [])
            if backed >= 2 and here < backed / 2:
                sentence = (
                    "Your %s lists %d %s, but the most recent saved copy "
                    "holds %d - if you did not remove them yourself, run "
                    "Repair Library before cleaning anything."
                    % (section_label(self._filename), here,
                       section_noun(self._filename, here), backed))
                type(self)._integrity_notes.setdefault(
                    self._filename, []).append(sentence)
                debug.event("database", "suspicious shrink at load",
                            file=self._filename, holds=here,
                            newest_snapshot=backed)
        except (OSError, ValueError, TypeError):
            return                          # the note must never cost a load

    def _refuse_absent(self, full: str, traces) -> None:
        """Absent-but-known: hold an empty library in memory so the panel still builds, and latch `_write_blocked` - the ONE flag save() consults, because it is the SECOND save that overwrites what the first preserved; the note names the full path, the way out, and EVERY trace (following one at a time spent a recovery copy per launch)."""
        self._data = {"categories": ["_All"], "tags": [], "assets": []}
        self._write_blocked = True
        debug.note(
            "%s is not on disk, but %s beside it says it was - so it is "
            "treated as not-yet-arrived, NOT as a new library. Nothing "
            "was created and nothing will be saved to it this session, "
            "so the file cannot be replaced by an empty one. Let the "
            "sync finish, then restart Houdini.\n"
            "  Expected at: %s\n"
            "  If you removed it on purpose, remove %s as well and the "
            "next launch starts a fresh one."
            % (section_name(self._filename), _and_list(traces), full,
               _and_list(traces)),
            file=full, evidence=", ".join(traces))

    def _normalize_all_category(self) -> None:
        """Keep the categories invariant at load: `_All` present at row 0 and legacy plain `All` rewritten, mutating the list in place because models alias it (see `set`)."""
        cats = self._data.get("categories")
        if not isinstance(cats, list):
            return
        changed = False
        if "All" in cats:
            cats[:] = [c for c in cats if c != "All"]
            changed = True
        if "_All" not in cats:
            cats.insert(0, "_All")
            changed = True
        elif cats[0] != "_All":
            cats[:] = (["_All"]
                       + [c for c in cats if c != "_All"])
            changed = True
        if changed:
            self.save()

    def set(self, assets: dict) -> None:
        """Set data without saving and never rebind the containers - models alias them - so contents change in place and incoming values are copied first because a caller may hand back the very objects being cleared."""
        for key in ("categories", "tags"):
            if key in assets:
                incoming = list(assets[key] or [])
                current = self._data.setdefault(key, [])
                current[:] = incoming
        if "assets" in assets:
            self._absorb_rows(list(assets["assets"] or []))
        if "category_colors" in assets:
            incoming_colours = dict(assets["category_colors"] or {})
            colours = self._data.setdefault("category_colors", {})
            colours.clear()
            colours.update(incoming_colours)

    def serves(self, library_dir: str) -> bool:
        """True while this connector still points at `library_dir`; the registry is keyed by filename alone so one instance serves every pane, and callers must ask this before writing - a library switch in one pane rebinds the connector under all of them."""
        if not self._path or not library_dir:
            return True                    # nothing loaded yet to disagree
        return (hostos.canonical_path_key(self._path)
                == hostos.canonical_path_key(library_dir))

    def _absorb_rows(self, incoming: list) -> None:
        """Union incoming rows by id in place: the caller wins for rows it holds, rows it never saw are kept, and only an explicit `forget` mark deletes - absence never means delete."""
        current = self._data.setdefault("assets", [])
        by_id, order = {}, []
        for row in current:
            if isinstance(row, dict):
                key = str(row.get("id"))
                if key not in by_id:
                    order.append(key)
                by_id[key] = row
        for row in incoming:
            if not isinstance(row, dict):
                continue
            key = str(row.get("id"))
            if key not in by_id:
                order.append(key)
            by_id[key] = row
        current[:] = [by_id[key] for key in order
                      if key not in self._forgotten]
        self._forgotten.clear()

    def forget(self, mat_id: str) -> None:
        """Mark a row for deletion on the next `set`: `_absorb_rows` can only keep rows, so an omitted row would otherwise be re-adopted from the connector copy."""
        self._forgotten.add(str(mat_id))
        debug.event("database", "row marked for removal",
                    file=self._filename, mat_id=str(mat_id))

    def unforget(self, mat_id: str) -> None:
        """Clear a `forget` mark after a refused save: only `_absorb_rows` consumes marks, so a caller that restores a row must clear the mark too or the next save deletes the restored row."""
        self._forgotten.discard(str(mat_id))
        debug.event("database", "row removal taken back",
                    file=self._filename, mat_id=str(mat_id))

    def save(self) -> bool:
        """Wrap `_save_inner` so the `finally` emits exactly one record per call, the raising path included, with the library directory logged only as a digest (paths are personal data)."""
        self._save_outcome = "unrecorded"
        try:
            return self._save_inner()
        finally:
            digest = hashlib.sha256(
                hostos.canonical_path_key(self._path or "")
                .encode("utf-8")).hexdigest()[:10]
            debug.event("database", "save", file=self._filename,
                        outcome=self._save_outcome, dir_key=digest)

    def _refuse_unreadable_peer(self, full: str) -> bool:
        """Refuse the save when the peer copy at `full` would not parse: preserve it, latch `_write_blocked` for the session, report once in full, and set `_block_reported` so `_save_inner` does not repeat it."""
        kept = hostos.preserve_unreadable(
            full, why="another session's database would not parse")
        self._write_blocked = True
        copy_sentence = (
            " A copy of it is beside it as %s."
            % os.path.basename(kept)) if kept else ""
        debug.note(
            "could not read the other session's %s, so this "
            "library will not be saved this session - their "
            "copy is left untouched.%s Reopen Amaze once the "
            "other machine has finished writing."
            % (self._filename, copy_sentence),
            file=full)
        self._block_reported = True
        self._save_outcome = "merge-refused"
        return False

    def _save_inner(self) -> bool:
        """Merge concurrent changes, then write through a sibling temp file and atomic replace; True only when the bytes reached disk - every refusal path (empty document, write latch, unreadable peer, format ahead, held file) returns False, and version and format stamps never downgrade nor claim a migration that did not run."""
        if not self._data:
            self._save_outcome = "empty-document"
            return False
        full = self._path + self._filename
        current_stat = self._stat_file()
        if self._disk_stat is not None and current_stat not in (
            None, self._disk_stat
        ):
            if not self._merge_from_disk(full):
                if getattr(self, "_format_ahead", False):
                    pass
                else:
                    return self._refuse_unreadable_peer(full)
        if getattr(self, "_write_blocked", False):
            if not getattr(self, "_block_reported", False):
                self._block_reported = True
                debug.note(
                    "not saving %s - it could not be read this session, "
                    "so writing now would put whatever little is in "
                    "memory over it. Your change is still on screen but "
                    "it is NOT on disk. Fix the file (or let the sync "
                    "finish), then restart Houdini."
                    % section_name(self._filename), file=full)
            debug.event("database", "save refused - writes blocked "
                        "this session", file=self._filename)
            self._save_outcome = "write-blocked"
            return False
        if getattr(self, "_format_ahead", False):
            if not getattr(self, "_format_reported", False):
                self._format_reported = True
                debug.note(
                    "not saving %s - it was saved by a newer Amaze, "
                    "and writing it from this one could damage it. "
                    "Your change is still on screen but NOT on disk. "
                    "Update Amaze, then save again."
                    % section_name(self._filename), file=full)
            debug.event("database", "save refused - library format "
                        "ahead", file=self._filename,
                        found=getattr(self, "_loaded_format", 0),
                        known=branding.LIBRARY_FORMAT)
            self._save_outcome = "format-ahead"
            return False
        loaded_version = int(
            getattr(self, "_loaded_version", SCHEMA_VERSION) or 0)
        if getattr(self, "_migration_incomplete", False):
            self._data["version"] = loaded_version
            debug.event("database", "version stamp held back - the "
                        "migration chain is incomplete",
                        file=self._filename, stamped=loaded_version,
                        target=SCHEMA_VERSION)
        else:
            self._data["version"] = max(loaded_version, SCHEMA_VERSION)
        self._data["format"] = max(
            int(getattr(self, "_loaded_format", 0) or 0),
            branding.LIBRARY_FORMAT)
        serialised_stat = None
        try:
            serialised = json.dumps(self._data, indent=4).encode("utf-8")
            serialised_stat = hostos.file_fingerprint(serialised)    # ▸r/peer-read
            if current_stat is not None and current_stat == serialised_stat:
                self._remember_disk_state()
                self._save_outcome = "identical-skip"
                return True
        except (TypeError, ValueError):
            pass                    # let the real writer report it

        hostos.snapshot_before_write(full)
        created = not os.path.exists(full)
        try:
            hostos.write_json_atomic(full, self._data, indent=4)
        except OSError as exc:
            debug.exception("database save", exc, file=full)
            cause, why = hostos.why_failed(exc, full)
            debug.alert(
                messages.LIBRARY_WRITE_FAILED % why,
                key="database-write-failed-%s" % cause)
            self._save_outcome = "write-failed-%s" % cause
            return False
        else:
            if created:
                hostos.seed_restore_floor(full)
            self._remember_disk_state()
            self._save_outcome = "stored"
            return True

    def take_adopted(self) -> list:
        """Rows adopted from a peer save, handed over exactly once - drained so a second call cannot re-insert the same rows."""
        rows = self._adopted
        self._adopted = []
        return rows

    def take_adopted_fields(self) -> list:
        """`(id, field, value)` for every field a peer changed on a row we also hold, handed over exactly once - a model that does not apply these writes its own stale value back on its next save."""
        fields = self._adopted_fields
        self._adopted_fields = []
        return fields

    def take_dropped(self) -> list:
        """Rows a peer's save deleted from disk, handed over exactly once - the model must drop them too, or its next save writes them back."""
        rows = self._dropped
        self._dropped = []
        return rows

    @staticmethod
    def _migrate_peer(disk: dict) -> None:
        """Bring a PEER document up to our shape, in place - shape only: no stamping, no latching, no reporting, because those verdicts belong to the file THIS connector loaded."""
        try:
            version = int(disk.get("version", 1))
        except (TypeError, ValueError):
            version = 1
        while version < SCHEMA_VERSION:
            step = _MIGRATIONS.get(version)
            if step is None:
                return              # a gap: leave the rest untouched
            step(disk)
            version += 1

    def _merge_from_disk(self, full: str) -> bool:
        """Three-way merge against a database another session changed underneath us - membership baseline is the ids as of OUR last load or successful save (`_remember_disk_state` refreshes both together): a disk id missing from memory is OUR deletion if it was in the baseline, THEIR addition if not; categories and tags union; conflicting records take memory (the active editor)."""
        answer = hostos.peer_read(full)    # ▸r/peer-read
        if answer.verdict != hostos.PEER_CHANGED:
            debug.event("database", "merge read failed",
                        file=self._filename, verdict=answer.verdict,
                        error=answer.error)
            return False
        disk = answer.document
        malformed = wrong_shape(disk)
        if malformed:
            debug.event("database", "merge refused - not a database",
                        file=self._filename, reason=malformed)
            return False
        try:
            self._migrate_peer(disk)
        except Exception as exc:                         # noqa: BLE001
            debug.event("database", "peer migration failed - merge refused",
                        file=self._filename, error=str(exc))
            return False
        try:
            theirs_version = int(disk.get("version", 1))
        except (TypeError, ValueError):
            theirs_version = 1
        if getattr(self, "_migration_incomplete", False):
            debug.event("database", "peer version not carried through - "
                        "our migration chain is incomplete",
                        file=self._filename, theirs=theirs_version,
                        ours=int(getattr(self, "_loaded_version",
                                         SCHEMA_VERSION) or 0))
        elif theirs_version > int(
                getattr(self, "_loaded_version", SCHEMA_VERSION) or 0):
            self._loaded_version = theirs_version
        try:
            theirs_format = int(disk.get("format", 0) or 0)
        except (TypeError, ValueError):
            theirs_format = 0
        if theirs_format > branding.LIBRARY_FORMAT:
            self._loaded_format = theirs_format
            self._format_ahead = True
            debug.event("database", "peer library format ahead - "
                        "latched read-only mid-session",
                        file=self._filename, theirs=theirs_format,
                        known=branding.LIBRARY_FORMAT)
            return False
        ours = {
            str(a.get("id")): a for a in self._data.get("assets", [])
            if isinstance(a, dict)
        }
        adopted_rows = []
        for theirs in disk.get("assets", []):
            if not isinstance(theirs, dict):
                debug.event('database', 'skipped a non-record asset entry',
                            file=self._filename, entry=repr(theirs)[:80])
                continue
            tid = str(theirs.get("id"))
            if tid not in ours and tid not in self._loaded_ids:
                self._data.setdefault("assets", []).append(theirs)
                adopted_rows.append(theirs)
            elif tid in ours:
                _merge_record(ours[tid], theirs, self._loaded_rows.get(tid),
                              self._filename, self._adopted_fields)
        adopted = len(adopted_rows)
        self._adopted.extend(adopted_rows)
        disk_ids = {str(theirs.get("id"))
                    for theirs in disk.get("assets", [])
                    if isinstance(theirs, dict)}
        dropped_rows = []    # the third direction: in our memory AND the baseline but gone from disk is THE PEER'S DELETION, and its files are already unlinked - kept, the row is a fileless ghost on both machines
        current = self._data.setdefault("assets", [])
        for row in list(current):
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id"))
            if rid in self._loaded_ids and rid not in disk_ids:
                current.remove(row)
                dropped_rows.append(row)
        self._dropped.extend(dropped_rows)
        for key in ("categories", "tags"):
            existing = self._data.setdefault(key, [])
            for value in disk.get(key, []):
                if value not in existing:
                    existing.append(value)
        theirs_colors = disk.get("category_colors")
        if isinstance(theirs_colors, dict):
            ours_colors = self._data.setdefault("category_colors", {})
            for name, colour in theirs_colors.items():
                ours_colors.setdefault(name, colour)
        for key, value in disk.items():
            if key not in self._data:
                self._data[key] = value
        debug.event(
            "database", "merged concurrent changes",
            file=self._filename, adopted_assets=adopted,
            dropped_assets=len(dropped_rows),
            disk_assets=len(disk.get("assets", [])),
            memory_assets=len(self._data.get("assets", [])),
        )

        if getattr(self, "_write_blocked", False):
            debug.event("database", "write block cleared - the file "
                        "merges again", file=self._filename)
            self._write_blocked = False
            self._block_reported = False

        return True

    def reload_with_path(self, path: str) -> dict:
        """Point this connector at a DIFFERENT library and read it - every latch and stamp belongs to the FILE, not the session, so all are reset for `load()` to re-derive from the new path; a failed load restores the previous library state and re-raises."""
        previous = (self._data, self._path, self._disk_stat,
                    set(self._loaded_ids),
                    getattr(self, "_loaded_version", SCHEMA_VERSION),
                    getattr(self, "_migration_incomplete", False),
                    getattr(self, "_write_blocked", False),
                    getattr(self, "_block_reported", False),
                    getattr(self, "_loaded_format", 0),
                    getattr(self, "_format_ahead", False),
                    getattr(self, "_format_reported", False))
        self._data = None
        self._disk_stat = None    # the OLD library's stat and baseline must not survive into the new load - the normalisation save inside load() would merge the new file against them, with itself
        self._loaded_ids = set()
        self._write_blocked = False
        self._block_reported = False
        self._migration_incomplete = False
        self._loaded_version = SCHEMA_VERSION
        self._loaded_format = 0
        self._format_ahead = False
        self._format_reported = False
        try:
            return self.load(path)
        except Exception:
            (self._data, self._path, self._disk_stat, self._loaded_ids,
             self._loaded_version, self._migration_incomplete,
             self._write_blocked, self._block_reported,
             self._loaded_format, self._format_ahead,
             self._format_reported) = previous
            debug.event("database", "library switch failed - previous "
                        "library restored", file=self._filename,
                        attempted=path)
            raise
