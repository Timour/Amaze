"""Guard: all access to a library's files - read with a Ticket, change as one unit, give verdicts."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import threading
import uuid

from amaze import branding
from amaze.core import debug
from amaze.helpers import hostos

FINE, FRESH, CORRUPT, MISSING, NEWER = "fine", "fresh", "corrupt", "missing", "newer"
HELD = "held"    # there, but it cannot be opened now: another program has it, or no permission
SHARED, PER_USER = "shared", "per-user"

MASTER = "DataBase.json"
MANIFEST = "manifest"    # in MASTER: the databases this library has, so a missing one is detected
BACKUP_DIR, TRASH_DIR = "backup", "trash"
JOURNAL = ".amaze-journal"    # present only while a change of several files is being applied
STEPS = ("swap", "move", "remove")    # the journal steps `_apply` carries out
SCRATCH = ".writing"
BACKUP_TAIL = ".bak"
UNDO_TAIL = ".before-restore.bak"
UNREADABLE_MARK = ".unreadable-"
STAMP = "%Y-%m-%d_%H%M%S"
RECENT_BACKUPS = 3
DAILY_BACKUP_DAYS = 30
BACKUP_SPACING_S = 30 * 60    # a save sooner than this after the newest backup makes no new one
TRASH_DAYS = 30
SHRUNK_FLOOR = 4    # a database this small or smaller in its backup is never called shrunk


class Kind:
    """One database a library holds: its sections, and the section its size is counted by."""

    def __init__(self, sections: dict, counted: str = "") -> None:
        self.sections = dict(sections)
        self.counted = counted


_ASSETS = {"assets": SHARED, "categories": SHARED, "comments": SHARED, "icons": SHARED,
           "favorites": PER_USER}

DATABASES = {
    MASTER: Kind({"policy": SHARED, "settings": SHARED, "users": SHARED, MANIFEST: SHARED,
                  "marks": SHARED}),
    "materials.json": Kind(_ASSETS, "assets"),
    "nodes.json": Kind(_ASSETS, "assets"),
    "code.json": Kind(_ASSETS, "assets"),
    "colors.json": Kind(_ASSETS, "assets"),
    "files.json": Kind({"locations": PER_USER, "paths": SHARED, "comments": SHARED,
                        "icons": SHARED, "favorites": PER_USER}, "locations"),
}


class Refused(Exception):
    """A read or a change Guard does not allow; its message is the reason."""


class Moved(Refused):
    """The file differs from what the ticket read: read it again, merge, and try once more."""


class Disk:
    """The filesystem as Guard uses it; a test substitutes one that stops at a chosen step."""

    def read(self, path: str) -> bytes:
        with open(path, "rb") as handle:
            return handle.read()

    def exists(self, path: str) -> bool:
        return os.path.lexists(path)

    def names(self, folder: str) -> list:
        try:
            return sorted(os.listdir(folder))
        except OSError:
            return []

    def write(self, path: str, data: bytes) -> None:
        """`data` as the whole of a new file at `path`, flushed; the folder is made if needed."""
        hostos.check_sandbox(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def swap(self, scratch: str, target: str) -> None:
        """`scratch` becomes `target` in one rename, keeping the replaced file's mode."""
        hostos.check_sandbox(target)
        os.makedirs(os.path.dirname(target), exist_ok=True)    # a file added by `take` may go into a new folder
        hostos.replace_with_scratch(scratch, target)

    def move(self, source: str, target: str) -> None:
        hostos.check_sandbox(target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.replace(source, target)

    def remove(self, path: str) -> None:
        hostos.check_sandbox(path)
        hostos.remove_file(path)

    def remove_folder(self, path: str) -> None:
        hostos.check_sandbox(path)
        shutil.rmtree(path)


class Ticket:
    """The record of one read: a database's name and exactly the bytes it held, None when absent."""

    __slots__ = ("name", "raw")

    def __init__(self, name: str, raw) -> None:
        self.name = name
        self.raw = raw


class Reading:
    """What a read found: the verdict, the document if it parsed, a ticket if it may be written."""

    def __init__(self, name: str, verdict: str, document=None, ticket=None, why: str = "",
                 shrunk=None) -> None:
        self.name = name
        self.verdict = verdict
        self.document = document
        self.ticket = ticket
        self.why = why
        self.shrunk = shrunk    # (its count, its newest backup's count) when under half, else None

    @property
    def writable(self) -> bool:
        return self.ticket is not None


def encode(document: dict) -> bytes:
    """A document as the bytes of its file, stamped with the format: the same bytes on every OS."""
    stamped = dict(document, format=max(_format_of(document), branding.LIBRARY_FORMAT))
    return (json.dumps(stamped, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _format_of(document) -> int:
    try:
        return int(document.get("format", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _parse(raw: bytes, kind: Kind) -> tuple:
    """(document, empty text) for a database of this kind, else (None, why it is not one)."""
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, str(exc)
    if not isinstance(document, dict):
        return None, "the file holds %s, not a database" % type(document).__name__
    for section in kind.sections:
        if section in document and not isinstance(document[section], dict):
            return None, "its %s section is %s, not a table" % (
                section, type(document[section]).__name__)
    return document, ""


class Guard:
    """One library's files: every read, write, removal and verdict on them goes through here."""

    def __init__(self, library_dir: str, disk: Disk = None, now=None) -> None:
        self.dir = str(library_dir)
        self.disk = disk or Disk()
        self._now = now or datetime.datetime.now
        self._lock = threading.RLock()
        self._quietly(self.recover)    # a change still waiting on a file reads as HELD, never raises here

    def stamp(self) -> str:
        """Now, in the text format of every date that Guard and documents.py write."""
        return self._now().strftime(STAMP)

    def path(self, *parts: str) -> str:
        """A path inside the library; `hostos.PathOutsideBase` for one outside it."""
        return hostos.contained_join(self.dir, *parts)

    def _relative(self, relative: str) -> str:
        parts = [part for part in str(relative).replace("\\", "/").split("/") if part]
        return self.path(*parts)

    def inside(self, path: str) -> str:
        """`path` relative to the library, `/` separated; empty for one outside it."""
        try:
            relative = os.path.relpath(os.path.abspath(str(path)), os.path.abspath(self.dir))
        except ValueError:    # another drive on Windows
            return ""
        relative = relative.replace("\\", "/")
        if relative == "." or relative == ".." or relative.startswith("../"):
            return ""
        return relative

    def recover(self) -> bool:
        """Finish a change a crash left half applied; True when there was one."""
        journal = self.path(JOURNAL)
        if not self.disk.exists(journal):
            return False
        with self._lock, hostos.file_lock(journal) as held:
            if not held:
                return False    # another session on this machine is applying it now
            return self._finish_journal()

    def _waiting(self) -> bool:
        """Whether a recorded change is still not fully applied, after one more attempt."""
        journal = self.path(JOURNAL)
        if not self.disk.exists(journal):
            return False
        self._quietly(self.recover)
        return self.disk.exists(journal)

    def _finish_journal(self) -> bool:
        """`recover`'s work, for a caller that already holds the machine lock."""
        journal = self.path(JOURNAL)
        if not self.disk.exists(journal):
            return False
        try:
            steps = json.loads(self.disk.read(journal).decode("utf-8"))["steps"]
            runs = self._runnable(steps)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            debug.event("guard", "journal unreadable - set aside", error=str(exc))
            self._quietly(self.disk.move, journal, journal + UNREADABLE_MARK + "journal")
            return False
        if not runs:
            debug.event("guard", "journal holds a step this Amaze does not know - left in place")
            return False
        self._apply(steps)
        self.disk.remove(journal)
        debug.event("guard", "a change left half applied was finished", steps=len(steps))
        return True

    def _runnable(self, steps) -> bool:
        """Whether `_apply` knows every step; ValueError for steps that are no steps at all."""
        if not isinstance(steps, list):
            raise ValueError("the journal's steps are %s, not a list" % type(steps).__name__)
        known = True
        for step in steps:
            if not isinstance(step, dict) or not isinstance(step.get("op"), str):
                raise ValueError("a journal step is not a step")
            names = ("to",) if step["op"] == "remove" else ("from", "to")
            for name in names:
                if not isinstance(step.get(name), str) or not step[name]:
                    raise ValueError("a journal step names no file")
                self._relative(step[name])    # `hostos.PathOutsideBase`, a ValueError, for one outside
            known = known and step["op"] in STEPS
        return known

    def _apply(self, steps: list) -> None:
        """Carry out journal steps; each is skipped when a run before this one already did it."""
        for step in steps:
            source = self._relative(step["from"]) if "from" in step else ""
            target = self._relative(step["to"])
            try:
                if step["op"] == "swap" and self.disk.exists(source):
                    self.disk.swap(source, target)
                elif step["op"] == "move" and self.disk.exists(source) and not self.disk.exists(
                        target):    # a trash target is new in its change: one that exists was moved already
                    self.disk.move(source, target)
                elif step["op"] == "remove" and self.disk.exists(target):
                    self.disk.remove(target)
            except FileNotFoundError:
                continue    # removed between the check and the step: another run did it

    def _quietly(self, act, *args) -> bool:
        try:
            act(*args)
            return True
        except OSError as exc:
            debug.event("guard", "housekeeping step failed", step=act.__name__, error=str(exc))
            return False

    def read(self, name: str) -> Reading:
        """One database, checked as it is now; only a FINE or FRESH one comes with a ticket."""
        kind = DATABASES.get(name)
        if kind is None:
            raise Refused("%s is no database of a library" % name)
        if self._waiting():
            return Reading(name, HELD, why="a change is waiting on a file that is in use")
        path = self.path(name)
        if not self.disk.exists(path):
            if self._known(name):
                return Reading(name, MISSING, why="it was here before and is gone")
            return Reading(name, FRESH, {}, Ticket(name, None))
        try:
            raw = self.disk.read(path)
        except OSError as exc:
            return Reading(name, HELD, why=str(exc))
        document, why = _parse(raw, kind)
        if document is None:
            self._keep_unreadable(name, raw)
            return Reading(name, CORRUPT, why=why)
        if _format_of(document) > branding.LIBRARY_FORMAT:
            return Reading(name, NEWER, document, why="it was saved by a newer Amaze")
        return Reading(name, FINE, document, Ticket(name, raw),
                       shrunk=self._shrunk(name, kind, document))

    def read_file(self, relative: str) -> bytes:
        """The bytes of any other file in the library; OSError when it cannot be read."""
        return self.disk.read(self._relative(relative))

    def health(self) -> list:
        """A `Reading` for every database a library can hold, in the order they are declared."""
        return [self.read(name) for name in DATABASES]

    def _reads(self, name: str) -> bool:
        try:
            return _parse(self.disk.read(self.path(name)), DATABASES[name])[0] is not None
        except OSError:
            return False

    def _known(self, name: str) -> bool:
        """Whether an absent database is known to have existed: the manifest names it."""
        if name == MASTER:    # known if another database reads; a same-named older file alone does not count
            return any(self._reads(other) for other in DATABASES if other != MASTER)
        try:
            document, _why = _parse(self.disk.read(self.path(MASTER)), DATABASES[MASTER])
        except OSError:
            return False
        return name in ((document or {}).get(MANIFEST) or {})

    def _keep_unreadable(self, name: str, raw: bytes) -> None:
        """One copy of an unreadable database in `backup/`, once per content; never of an empty one."""
        if not raw:
            return
        target = self.path(BACKUP_DIR, name + UNREADABLE_MARK + hashlib.sha256(raw).hexdigest()[:8])
        if not self.disk.exists(target):
            self._quietly(self.disk.write, target, raw)

    def backups(self, name: str) -> list:
        """(file name, when) of each backup of one database, newest first."""
        found = []
        for entry in self.disk.names(self.path(BACKUP_DIR)):
            if not entry.startswith(name + ".") or not entry.endswith(BACKUP_TAIL):
                continue
            stamp = entry[len(name) + 1:].split(".")[0]
            try:
                found.append((entry, datetime.datetime.strptime(stamp, STAMP)))
            except ValueError:
                continue
        return sorted(found, key=lambda one: one[1], reverse=True)

    def _plain_backups(self, name: str) -> list:
        return [one for one in self.backups(name) if not one[0].endswith(UNDO_TAIL)]

    def _shrunk(self, name: str, kind: Kind, document: dict):
        """(holds, backup holds) when a database holds under half of its newest backup."""
        newest = self._plain_backups(name)
        if not kind.counted or not newest:
            return None
        try:
            backed, _why = _parse(self.disk.read(self.path(BACKUP_DIR, newest[0][0])), kind)
        except OSError:
            return None
        here = len(document.get(kind.counted) or {})
        there = len((backed or {}).get(kind.counted) or {})
        return (here, there) if there > SHRUNK_FLOOR and here * 2 < there else None

    def _backup_steps(self, name: str, raw: bytes, tail: str = BACKUP_TAIL, spaced=True,
                      written=None) -> list:
        """Write the old bytes of a database as a new backup's scratch; its swap step, or none."""
        now = self._now()
        newest = self._plain_backups(name)
        if spaced and newest:
            if 0 <= (now - newest[0][1]).total_seconds() < BACKUP_SPACING_S:    # a backup dated in the future means a clock change, not a recent backup
                return []
            try:
                if self.disk.read(self.path(BACKUP_DIR, newest[0][0])) == raw:
                    return []    # the newest backup already holds exactly this
            except OSError:
                pass
        target = "%s/%s.%s%s" % (BACKUP_DIR, name, now.strftime(STAMP), tail)
        scratch = "%s.%s%s" % (target, uuid.uuid4().hex[:8], SCRATCH)
        if written is not None:
            written.append(scratch)    # before the write: a write that fails halfway leaves a file
        self.disk.write(self._relative(scratch), raw)
        return [{"op": "swap", "from": scratch, "to": target}]

    def _prune_backups(self, name: str) -> None:
        """Keep the newest few backups and one a day for DAILY_BACKUP_DAYS; remove the rest."""
        now = self._now()
        keep, days = set(), set()
        for index, (entry, when) in enumerate(self._plain_backups(name)):
            age = (now.date() - when.date()).days
            if index < RECENT_BACKUPS or (age < DAILY_BACKUP_DAYS and when.date() not in days):
                keep.add(entry)
            days.add(when.date())
        for entry, when in self.backups(name):
            old_undo = entry.endswith(UNDO_TAIL) and (now - when).days >= DAILY_BACKUP_DAYS
            if (not entry.endswith(UNDO_TAIL) and entry not in keep) or old_undo:
                self._quietly(self.disk.remove, self.path(BACKUP_DIR, entry))

    def change(self, user: str = "") -> "Change":
        """A change to the library's files, applied whole by its `commit()` or not at all."""
        return Change(self, user)

    def restore(self, name: str, backup: str) -> None:
        """Restore one backup as its database, keeping the current file as an undo copy."""
        kind = DATABASES.get(name)
        if kind is None or not any(backup == entry for entry, _when in self.backups(name)):
            raise Refused("%s is no backup of %s" % (backup, name))
        data = self.disk.read(self.path(BACKUP_DIR, backup))
        if _parse(data, kind)[0] is None:
            raise Refused("that backup cannot be read")
        change = Change(self, "")
        change._forced[name] = data
        change.commit()

    def trash_held(self) -> dict:
        """{path, files, bytes, days}: each day is (day, the day it is removed, files, bytes)."""
        root = self.path(TRASH_DIR)
        found = {"path": root, "files": 0, "bytes": 0, "days": []}
        for day in self.disk.names(root):
            count = total = 0
            for here, _dirs, names in os.walk(os.path.join(root, day)):
                for name in names:
                    try:
                        total += os.path.getsize(os.path.join(here, name))
                        count += 1
                    except OSError:
                        pass
            try:
                goes = (datetime.date.fromisoformat(day)
                        + datetime.timedelta(days=TRASH_DAYS + 1)).isoformat()
            except ValueError:
                goes = ""
            found["days"].append((day, goes, count, total))
            found["files"] += count
            found["bytes"] += total
        return found

    def expire_trash(self) -> int:
        """Remove the trash's day folders older than TRASH_DAYS; how many were removed."""
        cutoff = (self._now() - datetime.timedelta(days=TRASH_DAYS)).strftime("%Y-%m-%d")
        gone = 0
        for day in self.disk.names(self.path(TRASH_DIR)):
            if len(day) == 10 and day < cutoff:
                gone += self._quietly(self.disk.remove_folder, self.path(TRASH_DIR, day))
        return gone


class Change:
    """Files to write, remove and trash as ONE unit: all of it is applied, or none of it is."""

    def __init__(self, guard: Guard, user: str) -> None:
        self.guard = guard
        self.user = str(user or "")
        self._documents = {}    # name -> (ticket, bytes)
        self._forced = {}    # name -> bytes, written whatever is there: a restore, the conversion
        self._replacing = set()    # forced names whose old bytes are a plain backup, not an undo copy
        self._files = {}    # relative path -> bytes
        self._taken = {}    # relative path -> a file already written whole, moved into place
        self._removals = []
        self._trashed = []
        self.waiting = ""    # after `commit`: why the recorded change is not yet all in place

    def put(self, ticket: Ticket, document: dict) -> None:
        """A database's new content; it needs the ticket of the read this content is based on."""
        if not isinstance(ticket, Ticket) or ticket.name not in DATABASES:
            raise Refused("a database is written with the ticket of its read")
        self._documents[ticket.name] = (ticket, encode(document))

    def replace(self, name: str, document: dict) -> None:
        """The library conversion's write: a database whatever is there, its old bytes backed up."""
        if name not in DATABASES:
            raise Refused("%s is no database of a library" % name)
        self._forced[name] = encode(document)
        self._replacing.add(name)

    def put_file(self, relative: str, data: bytes) -> None:
        """Any other file in the library, written whole."""
        if str(relative).replace("\\", "/").split("/")[-1] in DATABASES:
            raise Refused("a database is written with `put`")
        self._files[str(relative)] = bytes(data)

    def take(self, relative: str, written: str) -> None:
        """A file already written whole at `written` (Houdini's own save) put at `relative`."""
        if str(relative).replace("\\", "/").split("/")[-1] in DATABASES:
            raise Refused("a database is written with `put`")
        self._taken[str(relative)] = str(written)

    def remove(self, relative: str) -> None:
        self._removals.append(str(relative))

    def trash(self, relative: str) -> None:
        """Move a file into today's folder of the library's trash."""
        self._trashed.append(str(relative))

    def commit(self) -> dict:
        """Apply the change; {name: Ticket} for each database written. `Moved`: read and redo."""
        guard, disk = self.guard, self.guard.disk
        with guard._lock, hostos.file_lock(guard.path(JOURNAL)) as locked:
            if not locked:    # another session here is mid-change: nothing is written at the same time
                raise OSError("another Amaze session on this computer is writing to the library")
            guard._finish_journal()
            if disk.exists(guard.path(JOURNAL)):
                raise OSError("a change recorded in the library is still waiting to be applied")
            steps, tickets, written = [], {}, []
            try:
                writes = self._changed_databases()
                for name, (old, data) in writes.items():
                    if old and name in self._replacing and _parse(old, DATABASES[name])[0] is None:
                        old = None    # a replaced file that could not be parsed is not backed up
                    if old:
                        undo = name in self._forced and name not in self._replacing
                        tail = UNDO_TAIL if undo else BACKUP_TAIL
                        steps += guard._backup_steps(name, old, tail, name not in self._forced,
                                                     written)
                    tickets[name] = Ticket(name, data)
                steps += [{"op": "move", "from": relative, "to": self._trash_target(relative)}
                          for relative in self._trashed]    # first: so a file written to the same path is kept
                for relative, data in list(writes.items()) + list(self._files.items()):
                    payload = data[1] if isinstance(data, tuple) else data
                    scratch = "%s.%s%s" % (relative, uuid.uuid4().hex[:8], SCRATCH)
                    written.append(scratch)
                    disk.write(guard._relative(scratch), payload)
                    steps.append({"op": "swap", "from": scratch, "to": relative})
                for relative, source in self._taken.items():
                    inside = guard.inside(source)
                    if not inside:    # written outside the library: copied in, then swapped
                        inside = "%s.%s%s" % (relative, uuid.uuid4().hex[:8], SCRATCH)
                        written.append(inside)
                        disk.write(guard._relative(inside), disk.read(source))
                    steps.append({"op": "swap", "from": inside, "to": relative})
                steps += [{"op": "remove", "to": relative} for relative in self._removals]
                written = [step["from"] for step in steps if step["op"] == "swap"]
                if len(steps) == 1:
                    guard._apply(steps)    # one rename is atomic by itself
                elif steps:
                    journal = guard.path(JOURNAL)
                    scratch = "%s.%s%s" % (journal, uuid.uuid4().hex[:8], SCRATCH)
                    disk.write(scratch, json.dumps({"steps": steps}).encode("utf-8"))
                    written = []    # from here journal recovery handles the scratch files
                    disk.swap(scratch, journal)
                    try:
                        guard._apply(steps)
                        disk.remove(journal)
                    except OSError as exc:    # the journal is written, so the change stands: the next read finishes it
                        debug.event("guard", "a change waits on a file", error=str(exc))
                        self.waiting = str(exc)
            except OSError:
                for scratch in written:
                    if disk.exists(guard._relative(scratch)):
                        guard._quietly(disk.remove, guard._relative(scratch))
                raise
            for name in tickets:
                guard._prune_backups(name)
            return tickets

    def _changed_databases(self) -> dict:
        """{name: (old bytes or None, new bytes)} for each database that really changes."""
        guard, disk = self.guard, self.guard.disk
        writes, created = {}, []
        for name, (ticket, data) in self._documents.items():
            path = guard.path(name)
            current = disk.read(path) if disk.exists(path) else None
            if current != ticket.raw:
                raise Moved("%s changed since it was read" % name)
            if data != current:
                writes[name] = (current, data)
                if current is None and name != MASTER:
                    created.append(name)
        for name, data in self._forced.items():
            path = guard.path(name)
            writes[name] = (disk.read(path) if disk.exists(path) else None, data)
            if name != MASTER:
                created.append(name)
        if created:
            self._list_in_manifest(created, writes)
        return writes

    def _list_in_manifest(self, created: list, writes: dict) -> None:
        """List each database being created in the DataBase.json manifest, in this same change."""
        guard = self.guard
        if MASTER in writes:
            old, data = writes[MASTER]
            document = json.loads(data.decode("utf-8"))
        else:
            reading = guard.read(MASTER)
            if not reading.writable:
                raise Refused("the library's %s is %s, so no database can be added to it"
                              % (MASTER, reading.verdict))
            old, document = reading.ticket.raw, dict(reading.document)
        manifest = dict(document.get(MANIFEST) or {})
        fresh = [name for name in created if name not in manifest]
        if not fresh:
            return
        for name in fresh:
            manifest[name] = {"created": guard._now().strftime(STAMP), "by": self.user}
        writes[MASTER] = (old, encode(dict(document, **{MANIFEST: manifest})))

    def _trash_target(self, relative: str) -> str:
        """Where a trashed file is moved: today's folder, its path kept, a number added if taken."""
        guard = self.guard
        day = guard._now().strftime("%Y-%m-%d")
        clean = "/".join(part for part in relative.replace("\\", "/").split("/") if part)
        target, bump = "%s/%s/%s" % (TRASH_DIR, day, clean), 1
        while guard.disk.exists(guard._relative(target)):
            bump += 1
            stem, ext = os.path.splitext(clean)
            target = "%s/%s/%s %d%s" % (TRASH_DIR, day, stem, bump, ext)
        return target
