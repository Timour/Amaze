"""Documents: each database as keyed sections, changed by a user, merged and saved via the guard."""

from __future__ import annotations

import collections
import copy

from amaze.core import debug, guard

BY, AT = "_by", "_at"    # on every shared entry: who changed it last, and when
STAMPS = (BY, AT)
SAVE_TRIES = 3    # reads of a file that keeps moving before a save gives up
SAVE_DELAY_MS = 300    # how long a caller's timer waits after the last change before it saves

SAVED, UNCHANGED, NO_USER, MOVED, DENIED = "", "unchanged", "no-user", "moved", "denied"

_GONE = object()

Collision = collections.namedtuple("Collision", "document section key field by")


class Saved:
    """A save's outcome: whether the file holds the change, and the reason when it does not."""

    __slots__ = ("ok", "reason", "detail")

    def __init__(self, ok: bool, reason: str = SAVED, detail: str = "") -> None:
        self.ok, self.reason, self.detail = ok, reason, detail

    def __bool__(self) -> bool:
        return self.ok


def _bare(value):
    """An entry without its stamps, so two are compared by what they hold."""
    if isinstance(value, dict):
        return {key: one for key, one in value.items() if key not in STAMPS}
    return value


def _same(one, other) -> bool:
    return (one is _GONE and other is _GONE) or (
        one is not _GONE and other is not _GONE and _bare(one) == _bare(other))


def _copy(value):
    """A deep copy, with the absent mark kept as the one object it is."""
    return value if value is _GONE else copy.deepcopy(value)


def _identified(value) -> bool:
    """Whether a value is a list of items that each carry an `id`: merged item by item."""
    return isinstance(value, list) and all(
        isinstance(item, dict) and "id" in item for item in value)


def _merge_items(ours: list, theirs: list, base) -> list:
    """Two lists of identified items against their base; an item both changed stays ours."""
    by_id = [{str(item["id"]): item for item in side}
             for side in (ours, theirs, base if _identified(base) else [])]
    merged = _merge_table(by_id[0], by_id[1], by_id[2], None)
    return list(merged.values())


def _merge_fields(ours: dict, theirs: dict, base, key, collide) -> dict:
    """One entry field by field; a field both changed stays ours and is reported."""
    base = base if isinstance(base, dict) else {}
    out, took, kept = {}, False, False
    for field in list(ours) + [name for name in theirs if name not in ours]:
        if field in STAMPS:
            continue
        mine, other, was = (side.get(field, _GONE) for side in (ours, theirs, base))
        if _same(other, was):
            value, kept = mine, kept or not _same(mine, was)
        elif _same(mine, was):
            value, took = _copy(other), True
        elif _same(mine, other):
            value = mine
        elif _identified(mine) and _identified(other):
            value, took, kept = _merge_items(mine, other, was), True, True
        else:
            value, kept = mine, True
            if collide is not None:
                collide(key, field, theirs.get(BY, ""))
        if value is not _GONE:
            out[field] = value
    source = theirs if took and not kept else ours
    out.update({stamp: source[stamp] for stamp in STAMPS if stamp in source})
    return out


def _merge_entry(ours, theirs, base, key, collide):
    """One entry three ways; `_GONE` stands for absent, and an edit outranks a removal."""
    if _same(theirs, base):
        return ours
    if _same(ours, base):
        return _copy(theirs)
    if _same(ours, theirs) or theirs is _GONE:
        return ours
    if ours is _GONE:
        return _copy(theirs)
    if isinstance(ours, dict) and isinstance(theirs, dict):
        return _merge_fields(ours, theirs, base, key, collide)
    if collide is not None:
        collide(key, "", "")
    return ours


def _merge_table(ours: dict, theirs: dict, base: dict, collide) -> dict:
    """One keyed table three ways, ours in its own order and their additions after."""
    out = {}
    for key in list(ours) + [name for name in theirs if name not in ours]:
        value = _merge_entry(ours.get(key, _GONE), theirs.get(key, _GONE),
                             base.get(key, _GONE), key, collide)
        if value is not _GONE:
            out[key] = value
    return out


class Document:
    """One database, held in memory as its sections; every change is a user's."""

    def __init__(self, guard_: guard.Guard, name: str, user, defer=None) -> None:
        self.guard = guard_
        self.name = name
        self.kind = guard.DATABASES[name]
        self._user = user
        self._defer = defer    # `defer(save)`: the caller's timer, so a burst is one save
        self.collisions = []
        self.load()

    def user(self) -> str:
        """Who is making changes now; "" when nobody is picked."""
        return str((self._user() if callable(self._user) else self._user) or "")

    def load(self) -> None:
        """Read the file as it is now, dropping anything not yet saved."""
        self._adopt(self.guard.read(self.name))

    def _adopt(self, reading: guard.Reading) -> None:
        self.verdict, self.why, self.shrunk = reading.verdict, reading.why, reading.shrunk
        self._ticket = reading.ticket
        self._data, self._extra = self._split(reading.document or {})
        self._base = copy.deepcopy(self._data)
        self._dirty = False

    def _split(self, document: dict) -> tuple:
        """(the declared sections, every other key the file holds) of one parsed file."""
        sections = {name: copy.deepcopy(document.get(name) or {}) for name in self.kind.sections}
        extra = {key: value for key, value in document.items()
                 if key not in self.kind.sections and key != "format"}
        return sections, extra

    def _whole(self) -> dict:
        return dict(self._extra, **self._data)

    @property
    def writable(self) -> bool:
        return self._ticket is not None

    @property
    def dirty(self) -> bool:
        return self._dirty

    def _may_change(self, section: str, how: str) -> str:
        """The user making a change to a section of this kind, or "" when it is refused."""
        if self.kind.sections.get(section) != how:
            raise KeyError("%s has no %s section %r" % (self.name, how, section))
        return self.user() if self.writable else ""

    def _touch(self) -> None:
        self._dirty = True
        if self._defer is not None:
            self._defer(self.save)

    def table(self, section: str) -> dict:
        """A shared section as it is held: read it, never change it in place."""
        return self._data[section]

    def get(self, section: str, key: str, default=None):
        return self._data[section].get(key, default)

    def put(self, section: str, key: str, entry: dict) -> bool:
        """Store one shared entry as this user's change; False when refused or nothing changed."""
        user = self._may_change(section, guard.SHARED)
        if not isinstance(entry, dict):
            raise TypeError("a shared entry is a table, not %s" % type(entry).__name__)
        if not user or _same(self._data[section].get(key, _GONE), entry):
            return False
        stamped = copy.deepcopy(_bare(entry))
        stamped[BY], stamped[AT] = user, self.guard.stamp()
        self._data[section][str(key)] = stamped
        self._touch()
        return True

    def edit(self, section: str, key: str, **fields) -> bool:
        """Change some fields of one shared entry, making the entry if it is new."""
        return self.put(section, key, dict(self._data[section].get(key) or {}, **fields))

    def drop(self, section: str, key: str) -> bool:
        if not self._may_change(section, guard.SHARED) or key not in self._data[section]:
            return False
        del self._data[section][key]
        self._touch()
        return True

    def mine(self, section: str) -> dict:
        """This user's own table in a per-user section; empty when nobody is picked."""
        self._may_change(section, guard.PER_USER)
        return self._data[section].get(self.user(), {})

    def everyones(self, section: str) -> dict:
        """{user: table} of a per-user section."""
        return self._data[section]

    def put_mine(self, section: str, key: str, value) -> bool:
        """Store one of this user's own entries; `None` removes it."""
        user = self._may_change(section, guard.PER_USER)
        own = self._data[section].get(user, {})
        if not user or own.get(key, None) == value:
            return False
        if value is None:
            del self._data[section][user][key]
            if not self._data[section][user]:
                del self._data[section][user]
        else:
            self._data[section].setdefault(user, {})[str(key)] = copy.deepcopy(value)
        self._touch()
        return True

    def take_collisions(self) -> list:
        """Each field two users changed at once where ours was kept, handed over once."""
        found, self.collisions = self.collisions, []
        return found

    def _merge(self, theirs_document: dict) -> None:
        """Fold what is on disk into what is held; disk becomes the base of the next merge."""
        theirs, extra = self._split(theirs_document)
        me, merged = self.user(), {}
        for section, how in self.kind.sections.items():
            ours, base = self._data[section], self._base[section]

            def collide(key, field, by, section=section):
                self.collisions.append(Collision(self.name, section, key, field, by))
            if how == guard.PER_USER:
                table = {uid: copy.deepcopy(own) for uid, own in theirs[section].items()
                         if uid != me}
                own = _merge_table(ours.get(me, {}), theirs[section].get(me, {}),
                                   base.get(me, {}), None) if me else {}
                if own:
                    table[me] = own
            else:
                table = _merge_table(ours, theirs[section], base, collide)
            merged[section] = table
        self._data, self._base = merged, theirs
        self._extra = dict(extra, **self._extra)

    def refresh(self) -> bool:
        """Take in what another session saved; True when what is held changed."""
        reading = self.guard.read(self.name)
        if (self._ticket is not None and reading.ticket is not None
                and reading.ticket.raw == self._ticket.raw):
            return False
        if not reading.writable or (self._ticket is None and not self._dirty):
            moved = (self.verdict, self.writable) != (reading.verdict, reading.writable)
            if self._dirty:    # what is unsaved is kept until the file reads again
                self.verdict, self.why, self._ticket = reading.verdict, reading.why, None
            else:
                self._adopt(reading)
            return moved
        before = copy.deepcopy(self._data)
        self._merge(reading.document)
        self._ticket = reading.ticket
        self.verdict, self.why, self.shrunk = reading.verdict, reading.why, reading.shrunk
        return self._data != before

    def save(self) -> Saved:
        """Write what changed, folding in what another session saved since the read."""
        if not self._dirty:
            return Saved(True, UNCHANGED)
        if not self.writable:
            return Saved(False, self.verdict, self.why)
        user = self.user()
        if not user:
            return Saved(False, NO_USER)
        for _attempt in range(SAVE_TRIES):
            change = self.guard.change(user)
            change.put(self._ticket, self._whole())
            try:
                tickets = change.commit()
            except guard.Moved:
                reading = self.guard.read(self.name)
                if not reading.writable:
                    self.verdict, self.why, self._ticket = reading.verdict, reading.why, None
                    debug.event("documents", "save refused - the file no longer reads",
                                file=self.name, verdict=reading.verdict)
                    return Saved(False, reading.verdict, reading.why)
                self._merge(reading.document)
                self._ticket = reading.ticket
                continue
            except guard.Refused as exc:
                return Saved(False, DENIED, str(exc))
            except OSError as exc:
                return Saved(False, DENIED, str(exc))
            self._ticket = tickets.get(self.name, self._ticket)
            self._base = copy.deepcopy(self._data)
            self._dirty = False
            self.verdict = guard.FINE
            return Saved(True)
        return Saved(False, MOVED)


class Library:
    """One library's documents: one of each, one user, one way to hold a save back."""

    def __init__(self, library_dir: str, user, defer=None, disk=None, now=None) -> None:
        self.guard = guard.Guard(library_dir, disk=disk, now=now)
        self._user = user
        self._defer = defer
        self._open = {}

    def document(self, name: str) -> Document:
        """The one `Document` of a database in this library, read on first ask."""
        if name not in self._open:
            self._open[name] = Document(self.guard, name, self._user, self._defer)
        return self._open[name]

    def flush(self) -> dict:
        """Save every document holding a change now; {name: Saved} for each that had one."""
        return {name: document.save() for name, document in self._open.items() if document.dirty}

    def refresh(self) -> list:
        """Take in what other sessions saved; the names of the documents that changed."""
        return [name for name, document in self._open.items() if document.refresh()]
