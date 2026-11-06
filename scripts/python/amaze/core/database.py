"""JSON documents on disk, one live connection per file, migrated stepwise. ▸r/chain-starts-at-four"""

import contextlib
import copy
import json
import os
import hashlib
import uuid
from typing import Self

from amaze import branding
from amaze.core import debug, library_files
from amaze.helpers import hostos, restore, wording
from amaze import messages


SCHEMA_VERSION = 8

RETIRED_KEYS = ("tags",)    # dropped at load and never adopted from a peer, so the next save removes them


def _drop_retired(document: dict) -> None:
    for key in RETIRED_KEYS:
        document.pop(key, None)


_MIGRATIONS = {}


def _migration_v4(data: dict) -> None:
    """v4 to v5: strips `favorite` and `icon`; both keys must stay in the record's retired-key set."""
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
    """v5 to v6: strips `favorite` again; the key must stay in the retired-key set."""
    rows = data.get("assets")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.pop("favorite", None)


_MIGRATIONS[5] = _migration_v5


def _migration_v6(data: dict) -> None:
    """v6 to v7: strips `builder` from every asset row; the key must stay in the retired-key set."""
    rows = data.get("assets")
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.pop("builder", None)


_MIGRATIONS[6] = _migration_v6


_MINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "amaze:minted-asset-id")    # never change: ids derive from it


def _minted_id(row: dict, index: int) -> str:
    """An id derived from the row and its place, so every load on every machine mints the same one."""
    canonical = json.dumps(row, sort_keys=True)
    return uuid.uuid5(_MINT_NAMESPACE, "%d:%s" % (index, canonical)).hex


def _migration_v7(data: dict) -> None:
    """v7 to v8: mints an `id`, in place, for every asset row with neither `id` nor legacy `uid`."""
    rows = data.get("assets")
    if not isinstance(rows, list):
        return
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if not str(row.get("id") or row.get("uid") or ""):
            row["id"] = _minted_id(row, index)


_MIGRATIONS[7] = _migration_v7


_INSTANCES: dict = globals().get("_INSTANCES", {})


_EXISTED_MARKERS = {
    "code.json": (".amaze_code_starter_v1", ".assetlib_code_starter_v1"),
    "gradients.json": (".amaze_gradient_seed_v1",
                       ".assetlib_gradient_seed_v1"),
}


def absent_but_known(directory: str, filename: str, names=None) -> str:
    """One trace that an absent list once existed here, or empty; `names` answers from a listing."""
    found = hostos.existed_before_all(
        os.path.join(directory, filename), _EXISTED_MARKERS.get(filename, ()), names)
    return found[0] if found else ""


def held_much_less(holds: int, newest_copy_holds: int) -> bool:
    """A list holding under half of what its newest saved copy holds: worth saying out loud."""
    return newest_copy_holds >= 2 and holds < newest_copy_holds / 2


def shrunk_sentence(filename: str, holds: int, newest_copy_holds: int) -> str:
    return ("Your %s list holds %d %s, but its newest saved copy holds %d %s. If "
            "you did not remove them yourself, use Library ▸ Check Library… before you "
            "change anything - it can put that copy back."
            % (section_label(filename), holds, section_noun(filename, holds),
               newest_copy_holds, section_noun(filename, newest_copy_holds)))


def absent_traces(directory: str, filename: str) -> list:
    """Every trace proving the file was here, for a refusal that names them all."""

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


ID_CLAIMING_DATABASES = DATABASES    # every section's list claims ids: a saved palette stamps `mat/` too


def category_label(stored) -> str:
    """How a STORED category name reads to the user - the one home of the leading-underscore strip."""
    text = str(stored)
    return text[1:] if text.startswith("_") else text


def row_id(row: dict) -> str:
    """The id a stored row claims, `mat_id` as the fallback spelling."""
    return str(row.get("id", row.get("mat_id", "")))


def ids_claimed_by(directory: str, filenames: tuple = ()) -> tuple:
    """`(by_file, unreadable)`: ids claimed per readable database, and files that will not read."""
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
    """The asset id a library file belongs to, or None; `library_files.asset_id` holds the rule."""
    found = library_files.asset_id(name, extensions, tail)
    if found is None and name.lower().endswith(tuple(e.lower() for e in extensions)):
        debug.event("cleanup", "file not classified - left alone", file=name[:80])
    return found


def _merge_record(mine: dict, theirs: dict, base, filename: str,
                  adopted: list) -> None:
    """Field-wise three-way merge against `base`; a conflict keeps mine, and `base` None conflicts all."""
    based = isinstance(base, dict)
    for field in set(mine) | set(theirs):
        if field == "id":
            continue
        if field not in theirs:
            if based and field in base and mine.get(field) == base.get(field):    # gone from theirs, in our base, untouched by us: their removal
                del mine[field]
                debug.event("database", "dropped a field another session "
                            "removed", file=filename,
                            mat_id=str(mine.get("id")), field=field)
            continue
        their_value = theirs.get(field)
        my_value = mine.get(field)
        if my_value == their_value:
            continue
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
    """Empty string when `document` is shaped like a database, else a log phrase; rows unchecked."""
    if not isinstance(document, dict):
        return "top level is %s, not an object" % type(document).__name__

    for key in ("assets", "categories", "gradients"):
        value = document.get(key, [])
        if not isinstance(value, list):
            return "%s is %s, not a list" % (key, type(value).__name__)
    return ""


def wrong_table_shape(document, key: str) -> str:
    """Empty string when `document` is `{key: {...}}`, else a log phrase; for the side tables."""
    if not isinstance(document, dict):
        return "top level is %s, not an object" % type(document).__name__
    value = document.get(key, {})
    if not isinstance(value, dict):
        return "%s is %s, not an object" % (key, type(value).__name__)
    return ""


def _declared(filename: str, field: str) -> str:
    """A side table's own `label` or `noun` from the `keyed_store` registry, "" for none."""
    try:
        from amaze.core import keyed_store
    except Exception:                                     # noqa: BLE001
        return ""
    spec = keyed_store.store_for(filename)
    return getattr(spec, field) if spec else ""


def section_name(filename: str) -> str:
    """The section label with its filename, like `Nodes (cops.json)`."""

    label = _SECTION_LABELS.get(filename) or _declared(filename, "label")
    return "%s (%s)" % (label, filename) if label else filename


def section_label(filename: str) -> str:
    """The bare tab name, like `Nodes`, for a sentence that sends the reader to a control."""
    return (_SECTION_LABELS.get(filename)
            or _declared(filename, "label") or filename)


def section_noun(filename: str, count: int = 2) -> str:
    """The word a section count counts, like `material` or `nodes`, singular or plural by `count`."""
    noun = (_SECTION_HOLDS.get(filename)
            or _declared(filename, "noun") or "saved thing")
    return noun if count == 1 else noun + "s"


_SWITCH_READS = None    # the files the switch now running has read; None outside one


@contextlib.contextmanager
def one_read_per_file():
    """A switch inside it reads each file once: every later model on the file shares that document."""
    global _SWITCH_READS
    outer, _SWITCH_READS = _SWITCH_READS, set()
    try:
        yield
    finally:
        _SWITCH_READS = outer


def load_survivable(db, path: str, reload: bool = False):
    """Like load(), surviving an unreadable secondary file; `reload` re-reads, once per switch."""
    if reload and _SWITCH_READS is not None:
        if db._filename in _SWITCH_READS and db.serves(path) and db._data:
            return db._data
        _SWITCH_READS.add(db._filename)
    try:
        return db.reload_with_path(path) if reload else db.load(path)
    except (OSError, ValueError) as exc:
        if db._filename == "library.json":
            raise    # the primary index raises through to the repair dialog
        empty = {"categories": ["_All"], "assets": []}
        if reload or not db.serves(path):    # a failed switch put the PREVIOUS library back
            db._hold_unreadable(path, empty)
        else:
            db._write_blocked = True    # left unread, so the next load reads the file again
        hostos.preserve_unreadable(
            os.path.join(str(path), db._filename),
            why=section_label(db._filename))
        debug.event("database", "unreadable - saving disabled",
                    file=db._filename, error=str(exc))
        debug.alert(
            messages.SECTION_UNREADABLE_SAVING_DISABLED
            % section_noun(db._filename),
            key="unreadable-" + db._filename)
        return empty


def open_document(model, reload: bool = False) -> dict:
    """`model`'s document as its connector holds it, read once a switch, the recolour baseline taken."""
    db = DatabaseConnector(model.DB_FILENAME)
    data = load_survivable(db, model.preferences.dir, reload=reload)
    model._colours_seen = db._colours_adopted
    return data


def connector_for_save(model, what: str):
    """`model`'s connector, or None, said once, when another pane switched it to another library."""
    db = DatabaseConnector(model.DB_FILENAME)
    if db.serves(model.preferences.dir):
        return db
    debug.event("library", "%s refused - the connector now serves another "
                "library" % what, model=model.preferences.dir, connector=db._path)
    debug.alert(messages.LIBRARY_NOT_SAVED_ANOTHER_PANEL, key="connector-moved")
    return None


def colours_moved(model, db) -> bool:
    """Whether a merge recoloured a category since `model` opened or last asked; asking clears it."""
    moved = db._colours_adopted != model._colours_seen
    model._colours_seen = db._colours_adopted
    return moved


class DatabaseConnector:
    """Saves a json database to disk, one live connection per file, instances keyed by `filename`."""

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
            inst._loaded_containers = {}

            inst._adopted = []
            inst._adopted_fields = []
            inst._dropped = []
            inst._colours_adopted = 0    # a count, so every model on the file sees each one

            # explicit deletes, then the latches `save()` reads and `reload_with_path` resets
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
        """The file now, in ONE read: a `PeerFile`, its fingerprint a content hash. ▸r/peer-read"""
        return hostos.peer_read(self._path + self._filename, self._disk_stat)

    def _remember_written(self, full: str, written) -> None:
        """What we wrote is the base only while the file holds it; else the base before it stands."""
        self._disk_stat = written    # whatever replaced our write, the next save merges it
        if hostos.fingerprint_of(full) != written:
            return    # replaced at once, maybe by a save that never saw ours: our rows are not its deletions
        self._remember_disk_state(hostos.PeerFile(
            hostos.PEER_CHANGED, self._data, written))

    def _remember_disk_state(self, read=None) -> None:
        """The baseline from one document, parsed or written. ▸p/merge-needs-a-base"""
        answer = (read if read is not None
                  else hostos.peer_read(self._path + self._filename))
        if read is None and answer.document is not None:
            self._migrate_peer(answer.document)    # in our shape, as a merge sees theirs
        document = (answer.document if answer.document is not None
                    else (self._data or {}))    # unreadable or absent: our memory is the baseline
        self._disk_stat = answer.fingerprint
        self._loaded_rows = {
            str(a.get("id")): copy.deepcopy(a)
            for a in document.get("assets", [])
            if isinstance(a, dict)
        }    # the merge base: a field differing from this is an edit
        self._loaded_ids = set(self._loaded_rows)
        self._loaded_containers = {
            key: list(document.get(key, []) or [])
            for key in ("categories",)
        }    # the base for the LIST container, so a peer's removal is not undone by a union
        colours = document.get("category_colors")
        self._loaded_containers["category_colors"] = (
            dict(colours) if isinstance(colours, dict) else {})    # and for the colour table, per name

    def _migrate(self, data: dict) -> None:
        """Migrate `data` in place and stamp it; a newer schema is left alone, a gap latches."""
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
        """Load from disk; a missing primary index or a parsed non-database raises."""
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
                self._data = {"categories": ["_All"], "assets": []}
                if not self.save():    # a landed save set the baseline itself
                    self._remember_disk_state()
            else:
                with open(full, "rb") as lib_json:
                    raw = lib_json.read()
                parsed = json.loads(raw.decode("utf-8-sig"))
                malformed = wrong_shape(parsed)
                if malformed:
                    debug.event("database", "load refused - not a database",
                                file=self._filename, reason=malformed)
                    raise ValueError(
                        "%s is not a database (%s)"
                        % (self._filename, malformed))
                self._migrate(parsed)
                _drop_retired(parsed)
                self._data = parsed
                self._remember_disk_state(hostos.PeerFile(    # the bytes parsed, never a second read
                    hostos.PEER_CHANGED, parsed, hostos.file_fingerprint(raw)))
                parsed.setdefault("categories", ["_All"])    # `{}` parses: every model reads both
                parsed.setdefault("assets", [])
                self._normalize_all_category()
                self._note_suspicious_shrink(full)
        return self._data

    def _note_suspicious_shrink(self, full: str) -> None:
        """After a parse, alert (never block) a document holding under half of its newest snapshot."""
        try:
            here = len(self._data.get("assets") or [])
            newest = None
            for tier in restore.TIERS:
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
            if held_much_less(here, backed):
                sentence = shrunk_sentence(self._filename, here, backed)
                debug.event("database", "suspicious shrink at load",
                            file=self._filename, holds=here,
                            newest_snapshot=backed)
                debug.alert(sentence, key="shrunk:" + full)
        except (OSError, ValueError, TypeError):
            return                          # the note must never cost a load

    def _refuse_absent(self, full: str, traces) -> None:
        """Absent-but-known: hold an empty library in memory and latch `_write_blocked` for the session."""
        self._data = {"categories": ["_All"], "assets": []}
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
            % (section_name(self._filename), wording.and_list(traces), full,
               wording.and_list(traces)),
            file=full, evidence=", ".join(traces))

    def _normalize_all_category(self) -> None:
        """Put `_All` at row 0 and rewrite a legacy `All`, mutating the list in place."""
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
            self._rebind_model_queues()    # a model builds from `_data`, which holds what this merged

    def set(self, assets: dict) -> None:
        """Set data without saving, in place; models alias the containers, so they are never rebound."""
        for key in ("categories",):
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
        """True while this connector still points at `library_dir`; ask before writing."""
        if not self._path or not library_dir:
            return True                    # nothing loaded yet to disagree
        return (hostos.canonical_path_key(self._path)
                == hostos.canonical_path_key(library_dir))

    def _absorb_rows(self, incoming: list) -> None:
        """Union incoming rows by id in place; only a `forget` mark deletes, absence never does."""
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
        """Mark a row for deletion on the next `set`; omitting a row does not delete it."""
        self._forgotten.add(str(mat_id))
        debug.event("database", "row marked for removal",
                    file=self._filename, mat_id=str(mat_id))

    def unforget(self, mat_id: str) -> None:
        """Clear a `forget` mark; a caller restoring a row after a refused save must call this."""
        self._forgotten.discard(str(mat_id))
        debug.event("database", "row removal taken back",
                    file=self._filename, mat_id=str(mat_id))

    def save(self) -> bool:
        """Run `_save_inner` and log exactly one record per call, the library directory as a digest."""
        self._save_outcome = "unrecorded"
        try:
            return self._save_inner()
        finally:
            digest = hashlib.sha256(
                hostos.canonical_path_key(self._path or "")
                .encode("utf-8")).hexdigest()[:10]
            debug.ledger("database", "save", file=self._filename,
                         outcome=self._save_outcome, dir_key=digest)

    def _refuse_unreadable_peer(self, full: str) -> bool:
        """Refuse the save over an unparseable peer copy at `full`; latch `_write_blocked`, report once."""
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
        """Merge concurrent changes, then replace the file atomically; True only when bytes reached disk."""
        if not self._data:
            self._save_outcome = "empty-document"
            return False
        full = self._path + self._filename
        with hostos.file_lock(full):    # after the refusals, as it makes a sidecar; a refused lock still writes
            return self._merge_and_write(full)

    def _merge_and_write(self, full: str) -> bool:
        """Merge what a peer wrote, then replace the file; callers hold the lock. ▸p/merge-needs-a-base"""
        seen = self._stat_file()    # one read decides AND merges
        current_stat = seen.fingerprint
        if self._disk_stat is not None and current_stat not in (
            None, self._disk_stat
        ):
            was_ahead = getattr(self, "_format_ahead", False)
            if not self._merge_from_disk(full, already_read=seen):
                if not (getattr(self, "_format_ahead", False) and not was_ahead):    # only a latch this merge set explains its own refusal
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
        serialised = None
        try:
            serialised = json.dumps(self._data, indent=4).encode("utf-8")
            serialised_stat = hostos.file_fingerprint(serialised)    # ▸r/peer-read
            if current_stat is not None and current_stat == serialised_stat:
                self._remember_disk_state(hostos.PeerFile(    # these bytes ARE the file
                    hostos.PEER_CHANGED, self._data, serialised_stat))
                self._save_outcome = "identical-skip"
                return True
        except (TypeError, ValueError):
            pass                    # let the real writer report it

        hostos.snapshot_before_write(full)
        created = not os.path.exists(full)
        try:
            written = hostos.write_json_atomic(full, self._data, indent=4,
                                               serialised=serialised)
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
            self._remember_written(full, written)
            self._save_outcome = "stored"
            return True

    def refresh(self) -> bool:
        """Merge a peer's writes without saving; drain the `take_*` queues after. ▸r/peer-read"""
        if not self._data or not self._path:
            return False
        full = self._path + self._filename
        answer = hostos.peer_read(full, self._disk_stat)
        if answer.verdict == hostos.PEER_UNCHANGED:
            return False
        if not self._merge_from_disk(full, already_read=answer):    # the SAME read decides and merges: two reads can straddle a peer's write
            return False    # unreadable or refused: `_merge_from_disk` has said why, and our copy stands
        self._remember_disk_state(answer)    # and is the baseline, for the same reason
        return True

    def take_adopted(self) -> list:
        """Rows adopted from a peer save, handed over exactly once."""
        rows = self._adopted
        self._adopted = []
        return rows

    def take_adopted_fields(self) -> list:
        """`(id, field, value)` per field a peer changed on a row we hold, handed over exactly once."""
        fields = self._adopted_fields
        self._adopted_fields = []
        return fields

    def take_dropped(self) -> list:
        """Rows a peer's save deleted, handed over exactly once; the model must drop them too."""
        rows = self._dropped
        self._dropped = []
        return rows

    @staticmethod
    def _migrate_peer(disk: dict) -> None:
        """Bring a peer document up to our shape in place, without stamping, latching or reporting."""
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

    def _merge_from_disk(self, full: str, already_read=None) -> bool:
        """Three-way merge against a database another session changed; conflicts keep memory."""
        answer = already_read or hostos.peer_read(full)    # ▸r/peer-read
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
        dropped_rows = []    # in memory and the baseline but gone from disk: the peer deleted it
        current = self._data.setdefault("assets", [])
        for row in list(current):
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id"))
            if rid in self._loaded_ids and rid not in disk_ids:
                current.remove(row)
                dropped_rows.append(row)
        self._dropped.extend(dropped_rows)
        for key in ("categories",):    # a row's three-way rule, on a LIST ▸p/merge-needs-a-base
            existing = self._data.setdefault(key, [])
            theirs = disk.get(key, [])
            was = self._loaded_containers.get(key, [])
            for value in list(existing):
                if value in was and value not in theirs:
                    existing.remove(value)
            for value in theirs:
                if value not in existing and value not in was:    # in the base and gone here: OUR removal
                    existing.append(value)
        theirs_colors = disk.get("category_colors")
        if isinstance(theirs_colors, dict):    # per name, three ways ▸p/merge-needs-a-base
            ours_colors = self._data.setdefault("category_colors", {})
            was = self._loaded_containers.get("category_colors", {})
            for name in list(ours_colors) + [n for n in theirs_colors
                                             if n not in ours_colors]:
                mine, base = ours_colors.get(name), was.get(name)
                theirs = theirs_colors.get(name)
                if theirs in (mine, base):
                    continue    # nothing new on their side
                if mine != base:
                    debug.event("database", "category colour collision - "
                                "this session's kept", file=self._filename,
                                category=name)
                    debug.alert(
                        messages.EDIT_CONFLICT_KEPT_YOURS
                        % category_label(name),
                        key="colour-conflict-%s-%s" % (self._filename, name))
                    continue
                if name in theirs_colors:
                    ours_colors[name] = theirs
                else:
                    ours_colors.pop(name, None)    # their removal
                self._colours_adopted += 1
        for key, value in disk.items():
            if key not in self._data and key not in RETIRED_KEYS:
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

    def _forget_file_state(self) -> None:
        """Drop every latch, stamp and baseline - they belong to the FILE, so a new one re-derives them."""
        self._disk_stat = None    # if kept, load()'s normalising save merges the new file with itself
        self._loaded_ids = set()    # with the stat, or library B's rows are judged by library A's ids
        self._loaded_rows = {}
        self._loaded_containers = {}
        self._write_blocked = False
        self._block_reported = False
        self._migration_incomplete = False
        self._loaded_version = SCHEMA_VERSION
        self._loaded_format = 0
        self._format_ahead = False
        self._format_reported = False
        self._rebind_model_queues()    # what a merge left for the models is that file's too
        self._forgotten = set()

    def _rebind_model_queues(self) -> None:
        """Empty what merges left for the models - REBOUND, so a rollback can put the old lists back."""
        self._adopted = []
        self._adopted_fields = []
        self._dropped = []

    def _hold_unreadable(self, path: str, document: dict) -> None:
        """Serve `path` with `document` and refuse every write there: its file would not read."""
        self._forget_file_state()
        self._path = path
        self._data = document
        self._write_blocked = True

    def reload_with_path(self, path: str) -> dict:
        """Point this connector at another library and load it; a failed load restores and re-raises."""
        previous = (self._data, self._path, self._disk_stat,
                    set(self._loaded_ids),
                    dict(self._loaded_rows),
                    dict(self._loaded_containers),
                    getattr(self, "_loaded_version", SCHEMA_VERSION),
                    getattr(self, "_migration_incomplete", False),
                    getattr(self, "_write_blocked", False),
                    getattr(self, "_block_reported", False),
                    getattr(self, "_loaded_format", 0),
                    getattr(self, "_format_ahead", False),
                    getattr(self, "_format_reported", False))
        queued = (self._adopted, self._adopted_fields, self._dropped,
                  self._forgotten)
        self._data = None
        self._forget_file_state()
        try:
            return self.load(path)
        except Exception:
            (self._data, self._path, self._disk_stat, self._loaded_ids,
             self._loaded_rows, self._loaded_containers,
             self._loaded_version, self._migration_incomplete,
             self._write_blocked, self._block_reported,
             self._loaded_format, self._format_ahead,
             self._format_reported) = previous
            (self._adopted, self._adopted_fields, self._dropped,
             self._forgotten) = queued
            debug.event("database", "library switch failed - previous "
                        "library restored", file=self._filename,
                        attempted=path)
            raise
