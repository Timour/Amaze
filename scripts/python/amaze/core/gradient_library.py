"""
Models for the Gradients ("Colors") section.

Every entry is a normal USER gradient, stored in <library dir>/
gradients.json with its full ramp (basis/key/value) so it re-applies
exactly as saved, in user-defined categories.

The curated palettes are just prefilled colours, not read-only -
SEEDED once into the user gradients on first run (see
GradientLibrary._seed_curated_once), from the JSON defs in res/def/
listed in CURATED_SETS: Sanzo Wada's "A Dictionary of Color Combinations"
(348 combinations; data github.com/dblodorn/sanzo-wada, MIT, source work
public domain), plus artist sets from colour theory - Paul Klee (palette
sampled from "Farbtafel qu 1", 1930), Josef Albers (Homage to the Square /
Interaction of Color), Johannes Itten (twelve-part Farbkreis). After
seeding they are ordinary gradients: moveable, editable, deletable, their
categories removable, their colour-theory notes editable. Each JSON
documents its own sources in a "source" field.
"""

import json
import os

import hou
from PySide6 import QtCore, QtGui

from amaze.core import category, grid_proxy
from amaze.core import grid_columns
from amaze.core import database
from amaze.core import debug
from amaze.core import thumbnails
from amaze.core import tile_icons
from amaze.helpers import hostos

THUMB_SIZE = 256


def _def_path(filename: str) -> str:
    base = hou.getenv("AMAZE")
    if not base:
        return ""
    return os.path.join(
        base, "scripts", "python", "amaze", "res", "def", filename
    )


# The curated (read-only) sets, in display order. Entry dicts get
# "type" = the set key, and everything downstream branches only on
# user-vs-curated, so adding a set here (plus its JSON in res/def/) is
# the whole job. "label" feeds the sidebar group names and the list
# view's Category column ("Wada 5 Colors", ...).
CURATED_SETS = (
    {"key": "wada", "label": "Wada", "file": "sanzo_wada.json"},
    {"key": "klee", "label": "Klee", "file": "paul_klee.json"},
    {"key": "albers", "label": "Albers", "file": "josef_albers.json"},
    {"key": "itten", "label": "Itten", "file": "johannes_itten.json"},
)


def _palette_ramp_data(colors: list) -> dict:
    """A STEPPED (constant-basis) ramp from a palette's hex colours, in
    the same shape as a saved user ramp - so a seeded palette re-applies
    exactly like the curated stepped-ramp did and paints as bands."""
    n = len(colors)
    keys, values = [], []
    for i, c in enumerate(colors):
        keys.append(i / n if n else 0.0)
        h = c["hex"].lstrip("#")
        values.append([int(h[j:j + 2], 16) / 255.0 for j in (0, 2, 4)])
    return {"keys": keys, "values": values, "bases": ["Constant"] * n}


class GradientCategories(QtCore.QAbstractListModel):
    """Sidebar list for the Gradients section: "All", then the user's
    categories (which after seeding include the palette groups - "Wada 5
    Colors", "Klee 3 Colors", ...). Rebuilt via refresh() on change."""

    def __init__(self, library, parent=None) -> None:
        super().__init__(parent)
        self._library = library
        self._labels = []
        self._filters = []
        self._rebuild()

    def _rebuild(self) -> None:
        self._labels = ["All"]
        self._filters = [("all", None)]
        for cat in self._library.user_categories():
            self._labels.append(cat)
            self._filters.append(("category", cat))

    def refresh(self) -> None:
        self.beginResetModel()
        self._rebuild()
        self.endResetModel()

    # The ONE definition lives in category.py; imported so the four
    # sidebar models can never drift apart.
    COUNT_ROLE = category.SIDEBAR_COUNT_ROLE

    def filter_for_row(self, row: int):
        """(kind, value) for the proxy: ("all", None) or
        ("category", name)."""
        if 0 <= row < len(self._filters):
            return self._filters[row]
        return ("all", None)

    def rowCount(self, parent=None) -> int:
        return len(self._labels)

    def data(self, index, role: int = 0):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return self._labels[index.row()]
        if role == self.COUNT_ROLE:
            kind, value = self.filter_for_row(index.row())
            return self._library.count_for_filter(kind, value)
        if role == category.SIDEBAR_COLOR_ROLE:
            # The same role the asset sidebars answer, so the one
            # sidebar delegate paints this bar too. "All" is a view,
            # never coloured.
            kind, value = self.filter_for_row(index.row())
            if kind == "category":
                return self._library.category_color_of(value)
            return ""
        return None


class GradientLibrary(grid_columns.GridColumnsMixin,
                     QtCore.QAbstractTableModel):
    """User gradients first, then the Wada combinations. Entries are
    dicts with a "type" key ("user"/"wada"); user entries carry their
    full ramp data, Wada entries their color list. Thumbnails are
    painted on demand and cached - Wada as stacked horizontal bands
    (the dictionary's own presentation), user ramps as a left-to-right
    gradient (banded when fully constant-basis)."""

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "SubtitleRole",
        "category": "CategoryLabelRole",
        "favorite": "FavoriteRole",
        "comments": "NotesRole",
    }

    SubtitleRole = QtCore.Qt.ItemDataRole.UserRole + 1
    ColorsRole = QtCore.Qt.ItemDataRole.UserRole + 2
    FavoriteRole = QtCore.Qt.ItemDataRole.UserRole + 3
    #: list mode's Category column: the user category for saved
    #: gradients, the curated set's label (Wada/Klee/...) otherwise
    CategoryLabelRole = QtCore.Qt.ItemDataRole.UserRole + 4
    #: The colour set on this gradient's category. UserRole + 8 to
    #: match MaterialLibrary, so the one tile delegate reads one
    #: number whichever section it is painting.
    CategoryColorRole = QtCore.Qt.ItemDataRole.UserRole + 8
    #: Whether this gradient carries a note - the badge's question,
    #: shared role number with every other tile model (UserRole + 10).
    NotesRole = QtCore.Qt.ItemDataRole.UserRole + 10

    def __init__(self, preferences=None, parent=None) -> None:
        super().__init__(parent)
        self._preferences = preferences
        # WHICH library these gradients came from, canonical. Set FIRST:
        # _save_user() checks it, and __init__ reaches _save_user before
        # it finishes (via _backfill_uids_once and the seeder), so
        # setting it at the end of __init__ made construction raise
        # AttributeError - and the panel builds this model, so the panel
        # did not open at all.
        self._loaded_from = self._library_key()
        self._user = []
        self._user_categories = []
        # Category colours, name -> hex, beside the names in the same
        # file - the shape every other section already uses.
        self._category_colors: dict = {}
        # Set BEFORE _load_user, which reads it on the failure path.
        self._disk_stat = None
        # Latched by _load_user when the file on disk could not be
        # trusted - unreadable, or missing when it should not be. Set
        # here too so _seed_curated_once can consult it plainly rather
        # than through a getattr default.
        self._load_failed = False
        self._load_user()
        # The curated palettes are no longer a read-only class of their
        # own - they're SEEDED once into the user gradients (like the Code
        # section's Starter Toolbox), so they can be moved, edited, deleted
        # and their categories removed just like any saved gradient -
        # ordinary editable entries, not read-only. After seeding
        # every entry is a normal user gradient.
        self._seed_curated_once()
        self._entries = self._all_entries()
        self._backfill_uids_once()
        self._sweep_notes_to_store_once()

    def _library_key(self) -> str:
        """The library directory these gradients belong to, canonical."""
        if self._preferences is None:
            return ""
        return hostos.canonical_path_key(str(self._preferences.dir))

    def switch_model_data(self) -> None:
        """Re-read the colours from the library the panel now points at.

        Every other library-backed model is switched when the library
        directory changes; this one was built once and never told, so
        the Colors tab kept showing library A's palettes after a switch
        to B - and the next edit wrote A's whole colour library into
        B/gradients.json. Nothing refused it: the stale-write guard
        compares against a file that does not exist yet, which reads as
        "nothing moved underneath us".

        beginResetModel for the reason MaterialLibrary.switch_model_data
        states: this replaces the whole row set, and a proxy left
        holding the old count paints an out-of-range row.
        """
        self.beginResetModel()
        try:
            # BEFORE the loaders, for the same reason __init__ sets it
            # first: the seeder and the uid backfill both call
            # _save_user, and _save_user refuses a write aimed at a
            # library other than this one. Left until the end, it still
            # named the library we just switched AWAY from, so the
            # backfill's save into the new library was refused.
            self._loaded_from = self._library_key()
            self._user = []
            self._user_categories = []
            self._category_colors = {}
            self._disk_stat = None
            self._load_failed = False
            self._load_user()
            self._seed_curated_once()
            self._entries = self._all_entries()
            self._backfill_uids_once()
            self._sweep_notes_to_store_once()
        finally:
            self.endResetModel()

    #: bump when the seed contents change, so a new set re-seeds
    _SEED_MARKER = ".amaze_gradient_seed_v1"
    #: Pre-rename marker; renamed on sight so an old library does not
    #: re-seed the curated gradients and duplicate them.
    _SEED_MARKER_LEGACY = ".assetlib_gradient_seed_v1"

    def _seed_curated_once(self) -> None:
        """First run per library: turn every curated combination into a
        normal user gradient (stepped ramp, its set+size as the category,
        its colour-theory note kept and now editable). Guarded by a marker
        file so a later delete/edit/move sticks and it never re-seeds.
        Best-effort - never blocks construction."""
        if self._preferences is None:
            return
        if self._load_failed:
            # _save_user() refuses while this is latched, so seeding here
            # would write the MARKER for a save that never happened -
            # and the marker is permanent, so the curated palettes would
            # never seed again. The marker is usually the evidence that
            # latched it, but a .bak can latch it with no marker present,
            # which is exactly this case.
            return
        marker = os.path.join(self._preferences.dir, self._SEED_MARKER)
        hostos.migrate_legacy_file(
            self._preferences.dir, self._SEED_MARKER_LEGACY,
            self._SEED_MARKER)
        if os.path.exists(marker):
            return
        try:
            seeded = 0
            for curated in CURATED_SETS:
                path = _def_path(curated["file"])
                if not path or not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    combos = json.load(f).get("combinations", [])
                for combo in combos:
                    colors = combo.get("colors") or []
                    if not colors:
                        continue
                    n = len(colors)
                    cat_name = "%s %s Color%s" % (
                        curated["label"], n, "" if n == 1 else "s"
                    )
                    if cat_name not in self._user_categories:
                        self._user_categories.append(cat_name)
                    name = combo.get("name") or "Combination %s" % combo.get("id")
                    self._user.append({
                        "type": "user",
                        "name": name,
                        "category": cat_name,
                        "colors": colors,
                        "note": combo.get("note", ""),
                        "ramp": _palette_ramp_data(colors),
                        "favorite": False,
                    })
                    seeded += 1
            # Only mark "done" once we actually seeded something: if the
            # def files were unreachable this run (e.g. AMAZE not set
            # yet) we added nothing, so leave the marker off and retry next
            # launch rather than permanently blocking the seed.
            if not seeded:
                return
            # The marker is PERMANENT and it is the only trace
            # gradients.json leaves, so it must not be minted for a save
            # that never landed. code_library's seeder has always
            # withheld its marker this way; this one wrote it whatever
            # happened, and _save_user has three non-raising refusals -
            # so marker-present + file-absent was reachable, and that
            # pair latches _load_failed on the next launch and refuses
            # every colour edit for the session.
            if not self._save_user():
                debug.event("gradient", "curated seed not marked - the save "
                            "did not reach disk")
                return
        except Exception as exc:                        # noqa: BLE001
            # note vs event for this file: the same split as
            # code_library's seeding - the seed failure itself is
            # internal, while the marker failure below states a
            # consequence the user can observe.
            debug.event("gradient", "curated palette seed failed",
                        error=str(exc))
            return
        # The marker is written OUTSIDE the handler that wraps the save,
        # and a failure to write it is a HARD STOP.
        #
        # Both were inside one broad `except Exception` that only
        # printed. If _save_user succeeded and the marker write failed,
        # the next launch seeded again: 348+ duplicated curated
        # gradients per launch, growing without bound. If the save
        # failed, the model showed seeded content that was never
        # persisted, and the first user edit persisted a partial set.
        try:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("seeded %d curated palettes\n" % seeded)
        except OSError as exc:
            debug.exception("gradient seed marker", exc, marker=marker)
            debug.note(
                "the curated palettes are in your Colors library, but "
                "adding them could not be recorded (%s) - so they "
                "will be added a second time when Houdini next "
                "starts. Your own palettes are not affected." % exc)
            # A RECORD, not a guard - same as code_library's marker. The
            # comment above says what actually happens next launch, and
            # the message now says the same thing instead of claiming it
            # was prevented. No remedy sentence: hand-deleting 348
            # duplicated palettes is not a next step that works, and a
            # fake one is worse than none.
            self._seed_marker_failed = True

    # ------------------------------------------------------------------
    # User-gradient persistence: <library dir>/gradients.json - lives
    # with the library data (synced along with it), not in the app
    # install or settings.
    def _user_file(self) -> str:
        if self._preferences is None:
            return ""
        return os.path.join(self._preferences.dir, "gradients.json")

    def _load_user(self) -> None:
        path = self._user_file()
        if not path:
            return
        if not os.path.exists(path):
            # The module had a careful policy for a file that will not
            # PARSE and none at all for one that is momentarily ABSENT,
            # although the outcome is identical and worse: _load_failed
            # stayed False, _user stayed [], the seed marker already
            # existed so nothing re-seeded, and the next _save_user()
            # serialised that empty list over the file as soon as it
            # arrived. Reproduced 2026-07-29: 290,454 bytes / 388
            # gradients / 12 categories -> 39 bytes / 0 / 0.
            #
            # THE SEED MARKER IS THE EVIDENCE THAT MATTERS HERE, not a
            # backup. gradients.json is written rarely enough that the
            # real library has NO gradients.json.bak-* files at all -
            # verified 2026-07-29 - so a guard keyed on backups alone
            # would fail OPEN on the one file this bug was measured on
            # while looking fixed. `.amaze_gradient_seed_v1` is written
            # only after a successful save of the seeded gradients, so
            # its presence beside a missing gradients.json means the
            # file was here.
            # THE SHARED helper, not a private repeat of it. Repair
            # asks the same question through database.absent_but_known
            # and was getting a different answer, because gradients.json
            # was the one database missing from its marker table: with
            # the marker present and the file gone, Repair reported
            # "nothing saved here yet" at the exact moment this loader
            # had latched and refused every colour write.
            evidence = database.absent_but_known(
                os.path.dirname(path), os.path.basename(path))
            if not evidence:
                return          # genuinely a new library: seed normally
            self._load_failed = True
            # ONE debug.note, not a print AND a note. note() is the sink
            # the project is moving these lines to: it prints for a user
            # with Debug Mode off and records the same text for the
            # diagnosis afterwards, so the two cannot drift. They HAD
            # drifted - the printed lines named the trace and the way
            # out, the note said only "saving disabled" - and on Windows
            # note() returns before printing (any print pops the Houdini
            # Console in front of the user's scene), so the record is
            # the WHOLE channel there. A log line missing the actionable
            # half leaves a Windows user with a Colors section that is
            # empty, silent and unsaveable.
            #
            # This is also what the database half of the same guard
            # does, and one guard speaking with two voices is how a
            # message gets fixed in one place and not the other.
            debug.note(
                "%s is not on disk, but %s beside "
                "it says it was here - so it is treated as "
                "not-yet-arrived, not as an empty library.\n"
                "  Saving is disabled this session so an empty file is "
                "not written over it. Let the sync finish, then restart "
                "Houdini.\n"
                "  Expected at: %s\n"
                # The way OUT of the refusal, named. Without it the
                # guard is permanent for anyone who deleted
                # gradients.json on purpose: the marker stays behind and
                # keeps answering "it was here" forever, with nothing on
                # screen saying what to do.
                "  If you removed it on purpose, remove %s as well and "
                "the next launch starts fresh."
                % (database.section_name("gradients.json"), evidence,
                   path, evidence),
                file=path, evidence=evidence)
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # VALID JSON IS NOT A VALID DATABASE. Every sibling checks
            # this; this loader did not, so a file of the wrong shape
            # raised out of the constructor and took the whole panel
            # down instead of routing into the _load_failed latch that
            # exists for exactly this. Raised as ValueError so it lands
            # in the handler below with the parse failures.
            malformed = database.wrong_shape(data)
            if malformed:
                raise ValueError(malformed)
            # ROW shape, not just container shape. wrong_shape above
            # validates the containers deliberately, so `{"gradients":
            # [42]}` parses and passes it - and then `entry["type"]`
            # raises TypeError, which is NOT in the handler below, so
            # it escapes the constructor and takes the whole panel down
            # (the very thing the latch exists to prevent). Skip the
            # bad rows and keep the good ones, which is what the
            # connector's own merge does with a non-dict row.
            rows = data.get("gradients", [])
            rows = rows if isinstance(rows, list) else []
            self._user = [e for e in rows if isinstance(e, dict)]
            skipped = len(rows) - len(self._user)
            if skipped:
                debug.event("gradient", "rows skipped - not objects",
                            skipped=skipped, file=path)
            for entry in self._user:
                entry["type"] = "user"
            self._user_categories = data.get("categories", [])
            table = data.get("category_colors")
            self._category_colors = {
                str(k): str(v) for k, v in table.items()
                if isinstance(k, str) and isinstance(v, str) and v
            } if isinstance(table, dict) else {}
            self._remember_disk_state(path)
            # A SUCCESSFUL READ CLEARS THE LATCH, the same way prefs.py
            # now does. Both modules set it on a parse failure and neither
            # cleared it anywhere, so a repaired file could never be saved
            # again for the life of the object. Kept symmetrical
            # deliberately: one policy speaking with two voices is how a
            # guard gets fixed in one module and not the other, which has
            # already happened to this exact pair of files.
            self._load_failed = False
        except (OSError, ValueError) as exc:
            # The file EXISTS and would not parse. That is not an empty
            # library, and the difference is everything: _user stays []
            # while the model believes it is complete, the seed marker
            # already exists so nothing re-seeds, and the first user
            # action calls _save_user() - which serialises that empty
            # list over the file.
            #
            # Measured: 200 gradients + one truncated-file launch + one
            # "save gradient" left ONE entry in gradients.json. And
            # snapshot_before_write had already copied the CORRUPT file
            # into .bak-1, spending the rolling window on garbage.
            self._load_failed = True
            # PRESERVE THE FILE BESIDE ITSELF - clause two of the
            # refuse-over-overwrite policy, which names this file by
            # name and which this handler took only clause one of. The
            # latch lasts one SESSION; the next launch reads whatever
            # the transport has left there, and if that parses as a
            # partial document the latch never fires and the model
            # adopts it. The .unreadable copy is also one of the two
            # traces hostos.existed_before reads, and gradients.json is
            # recorded as having no .bak at all - so not writing it
            # costs the absence guard its only evidence here.
            hostos.preserve_unreadable(path, why="gradient library")
            # RARE + IMPORTANT, so it interrupts: the colours are still
            # on disk, and the user has to know that nothing they do this
            # session will be kept. A print would say this only on macOS
            # (note() returns before printing on Windows, and its log
            # write is gated on Debug Mode), so the one platform the
            # no-print rule protects would have got silence.
            debug.event("gradient", "gradients.json unreadable - saving "
                        "disabled", file=path, error=str(exc))
            debug.alert(
                "Your saved colours could not be read, so Amaze will not "
                "save over them.\n\n"
                "Nothing has been lost - the file is untouched. Colour "
                "changes you make now will not be kept.\n\n"
                "Close Houdini and put back a recent copy with the Repair "
                "tool in the Amaze shelf.",
                key="gradients-unreadable")

    @staticmethod
    def _stat_of(path: str):
        """(size, sha256), or None when the file is not there.

        Deliberately the same key DatabaseConnector now uses, so the
        two guards agree about what "changed" means. Content rather
        than (mtime, size): the measured errors of the stat key run in
        both directions - a same-size edit slips through and loses the
        peer's change, and a byte-identical rewrite trips a conflict
        that is not there. This file is ~290KB; the read costs ~1ms on
        saves only.
        """
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
            import hashlib
            return (len(raw), hashlib.sha256(raw).hexdigest())
        except OSError:
            return None

    def _remember_disk_state(self, path: str) -> None:
        """What the file looked like when we last read or wrote it."""
        self._disk_stat = self._stat_of(path)

    def _disk_changed(self, path: str) -> bool:
        """True when another writer has touched the file since we read it.

        FAILS SAFE IN BOTH DIRECTIONS. No baseline (we never managed to
        read the file) means do not claim a change - the caller's other
        guards own that case. A baseline plus a MISSING file also means
        do not block: the file being gone is not another session's edit,
        and refusing there would leave the user unable to save at all.
        """
        current = self._stat_of(path)
        if self._disk_stat is None or current is None:
            return False
        return current != self._disk_stat

    def _save_user(self) -> bool:
        """True only when the colours actually reached disk.

        It used to return None from four different exits - the missing
        path, the unreadable-file refusal, the changed-on-disk refusal
        and a caught OSError - so a caller could not tell a completed
        save from a refused one. The seeder is that caller, and it wrote
        its permanent marker regardless.
        """
        path = self._user_file()
        if not path:
            return False
        # THE LIBRARY MAY HAVE MOVED under this model. Every connector-
        # backed model asks db.serves() here; gradients.json has no
        # connector, so it asks the same question of the directory it
        # actually loaded from. Without this, a switch that never
        # reached this model wrote library A's whole colour library
        # into B - and the stale-write guard below cannot catch it,
        # because B having no gradients.json yet reads as "unchanged".
        if self._loaded_from and self._library_key() != self._loaded_from:
            debug.event("gradient", "save refused - these colours came "
                        "from another library",
                        loaded_from=self._loaded_from,
                        now=self._library_key())
            debug.alert(
                "Amaze did not save your colours, because the library "
                "was changed while they were open.\n\n"
                "Nothing is lost. Reopen the panel and your colours "
                "will save again.",
                key="gradient-library-moved")
            return False
        if getattr(self, "_load_failed", False):
            # Refuse rather than overwrite what we could not read. The
            # user was already told once at load; alert() keys on the same
            # condition so a save attempt per edit does not re-interrupt.
            debug.event("gradient", "refusing to save gradients over an "
                        "unreadable file", file=path)
            debug.alert(
                "Your saved colours could not be read, so Amaze will not "
                "save over them.\n\n"
                "Nothing has been lost - the file is untouched. Colour "
                "changes you make now will not be kept.\n\n"
                "Close Houdini and put back a recent copy with the Repair "
                "tool in the Amaze shelf.",
                key="gradients-unreadable")
            return False
        data = {
            "categories": self._user_categories,
            "category_colors": self._category_colors,
            "gradients": [
                {k: v for k, v in entry.items() if k != "type"}
                for entry in self._user
            ],
        }
        if self._disk_changed(path):
            # REFUSE OVER OVERWRITE. This file is the one database that
            # does NOT go through DatabaseConnector, so it inherited no
            # stale-write guard at all: two sessions editing gradients
            # clobbered each other in silence, at 290KB a time. A merge
            # belongs here eventually; until then, refusing is the
            # honest behaviour, because the other session's write is
            # still intact on disk and this one is still in memory.
            debug.event("gradient", "gradients.json changed on disk since "
                        "it was read - save refused", file=path)
            debug.alert(
                "Someone else changed the saved colours while this Houdini "
                "was open, so Amaze did not save over their version.\n\n"
                "Nothing has been lost. Their colours are on disk and "
                "yours are still here in this session.\n\n"
                "Reopen the Amaze panel to load their version - your "
                "unsaved changes will be replaced when you do.",
                key="gradients-changed-on-disk")
            return False
        try:
            # Unique scratch name, fsync, atomic swap - shared with the
            # other three databases via hostos so this one cannot drift
            # behind them again.
            hostos.snapshot_before_write(path)
            hostos.write_json_atomic(path, data, indent=1)
            self._remember_disk_state(path)
            return True
        except OSError as exc:
            debug.event("library", "gradients save failed",
                        file=path, error=str(exc))
            return False

    def _all_entries(self) -> list:
        # Everything is a user gradient now (curated palettes are seeded
        # in on first run - see _seed_curated_once).
        return list(self._user)

    def _reset_entries(self) -> None:
        self.beginResetModel()
        self._entries = self._all_entries()
        self.endResetModel()

    def user_categories(self) -> list:
        return list(self._user_categories)

    def add_user_category(self, name: str) -> None:
        name = (name or "").strip()
        if name and name not in self._user_categories:
            self._user_categories.append(name)
            self._save_user()

    def count_in_category(self, name: str) -> int:
        return sum(1 for e in self._user if e.get("category") == name)

    def count_for_filter(self, kind: str, value) -> int:
        """Entry count for a sidebar filter - same semantics as
        GradientFilterProxyModel.filterAcceptsRow, minus search/favs."""
        if kind == "category":
            return self.count_in_category(value)
        return len(self._entries)

    # ------------------------------------------------------------------
    # Favorites - every gradient keeps its flag inline in gradients.json.
    def is_favorite(self, row: int) -> bool:
        entry = self.entry(row)
        return bool(entry.get("favorite")) if entry is not None else False

    def category_color_of(self, name: str) -> str:
        """The colour set on a gradient category, "" for none."""
        return str(self._category_colors.get(str(name), "") or "")

    def category_color(self, row: int) -> str:
        """The colour of THIS gradient's category - what the tile
        paints, the same question MaterialLibrary answers."""
        entry = self.entry(row)
        if entry is None:
            return ""
        return self.category_color_of(entry.get("category") or "")

    def set_category_color(self, name: str, color: str) -> bool:
        """Colour one category, or clear it with an empty colour.

        Keyed by NAME, so a rename has to carry the colour across and
        a removal takes it with it - both handled at their call sites,
        because an orphan key silently reattaches if the name returns."""
        name = str(name or "").strip()
        if not name:
            return False
        if color:
            self._category_colors[name] = str(color)
        else:
            self._category_colors.pop(name, None)
        if not self._save_user():
            return False
        # The grid reads the colour per ROW, so every tile in that
        # category has to repaint - role-scoped, never a bare emit.
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0),
                [self.CategoryColorRole])
        return True

    def rename_category_color(self, old: str, new: str) -> None:
        """Carry a colour across a category rename."""
        colour = self._category_colors.pop(str(old), "")
        if colour and new:
            self._category_colors[str(new)] = colour

    def drop_category_color(self, name: str) -> None:
        """A removed category takes its colour with it."""
        self._category_colors.pop(str(name), None)

    def tile_name(self, row: int) -> str:
        """The gradient's display name - what the Customize dialog's
        Name field shows."""
        entry = self.entry(row)
        return str((entry or {}).get("name", "") or "")

    def set_tile_name(self, row: int, name: str) -> bool:
        """Rename one gradient from the Customize dialog - the rename
        path that replaced the retired Info dialog's Name field. A
        blank or unchanged name is a no-op."""
        name = (name or "").strip()
        entry = self.entry(row)
        if entry is None or not name or name == entry.get("name"):
            return False
        entry["name"] = name
        self._save_user()
        self._reset_entries()
        return True

    def tile_icon(self, row: int) -> dict:
        """This gradient's chosen icon, {} when it shows its swatch.
        Same two-method contract every other section answers, so the
        panel's one Customize handler serves Colors too."""
        entry = self.entry(row)
        return tile_icons.normalise(entry.get("icon")) if entry else {}

    def tile_key(self, row: int) -> str:
        """A palette is keyed by its uid - the same identity its
        comment page uses, and the one a rename cannot move."""
        return self.note_uid(row)

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        """Give one gradient a tile icon, or clear it with an empty
        spec.

        NO PNG is written, unlike every other section: a gradient has
        no asset id and no file of its own on disk (gradients.json
        holds the whole entry), so there is nowhere to put an
        `<id>_icon.png` and nothing to clean up when it is cleared.
        The spec rides on the entry and the icon is composed in memory
        by _thumb(), which is what the swatch already does."""
        row = index.row() if hasattr(index, "row") else int(index)
        entry = self.entry(row)
        if entry is None:
            return False
        spec = tile_icons.normalise(spec)
        if spec:
            entry["icon"] = spec
        else:
            entry.pop("icon", None)
        if save:
            self._save_user()
        idx = self.index(row, 0)
        self.row_changed(idx.row(), [QtCore.Qt.ItemDataRole.DecorationRole])
        return True

    def commit_tile_icons(self, rows=None) -> None:
        """Save once after a multi-row Customize (the panel handler
        passes save=False per row, then calls this).

        `rows` is unused here, as it is in the two sibling models -
        but the panel's ONE Customize handler passes it positionally
        to whichever model the section owns, so the parameter is the
        contract, not a convenience. Declaring it `(self)` made
        Customize on a colour tile raise TypeError after the icon had
        already been applied in memory: the tile repainted, the save
        never ran, and the icon was gone at the next launch.
        """
        self._save_user()

    def toggle_favorite(self, row: int) -> None:
        entry = self.entry(row)
        if entry is None:
            return
        entry["favorite"] = not entry.get("favorite")
        self._save_user()
        index = self.index(row, 0)
        self.row_changed(index.row(), [self.FavoriteRole])

    def set_user_category(self, rows: list, category: str) -> int:
        """Move the given rows' gradients to a category (dragged onto a
        sidebar category, or the Move-to menu). Returns how many moved."""
        category = (category or "").strip()
        if not category:
            return 0
        if category not in self._user_categories:
            self._user_categories.append(category)
        moved = 0
        for row in rows:
            entry = self.entry(row)
            if entry is not None and entry.get("category") != category:
                entry["category"] = category
                moved += 1
        if moved:
            self._save_user()
            self._reset_entries()
        return moved


    def rename_user_category(self, old: str, new: str) -> bool:
        """Rename a gradient category, carrying its gradients AND its
        colour across - the same contract the asset sections have."""
        old = str(old or "").strip()
        new = str(new or "").strip()
        if not old or not new or old == new:
            return False
        if old in self._user_categories:
            self._user_categories[self._user_categories.index(old)] = new
        elif new not in self._user_categories:
            self._user_categories.append(new)
        for entry in self._user:
            if entry.get("category") == old:
                entry["category"] = new
        self.rename_category_color(old, new)
        if not self._save_user():
            return False
        self._reset_entries()
        return True

    def remove_user_category(self, name: str) -> None:
        """Drops the category itself; its gradients are kept, just
        uncategorized (still listed under "All")."""
        if name in self._user_categories:
            self._user_categories.remove(name)
        # A removed category takes its colour with it - an orphan key
        # would silently reattach if the name ever came back.
        self.drop_category_color(name)
        changed = False
        for entry in self._user:
            if entry.get("category") == name:
                entry["category"] = ""
                changed = True
        self._save_user()
        if changed:
            # Subtitles show the category, so affected rows repaint.
            self._reset_entries()

    def add_user_gradient(self, name: str, category: str, ramp_data: dict) -> None:
        """Registers a saved ramp. The color list is derived from the
        ramp values so search/swatches/subtitles work identically to the
        Wada entries (hex stands in for a color name)."""
        colors = []
        for value in ramp_data.get("values", []):
            hex_color = "#%02x%02x%02x" % tuple(
                max(0, min(255, round(c * 255))) for c in value[:3]
            )
            colors.append({"name": hex_color, "hex": hex_color})
        category = (category or "").strip()
        if category and category not in self._user_categories:
            self._user_categories.append(category)
        import uuid
        self._user.insert(
            0,
            {
                "type": "user",
                "name": (name or "Gradient").strip() or "Gradient",
                "category": category,
                "colors": colors,
                "ramp": ramp_data,
                # Identity at birth, like every section's assets -
                # and the same mint: full uuid4 hex, exactly what
                # Material stamps for mat_id.
                "uid": uuid.uuid4().hex,
            },
        )
        self._save_user()
        self._reset_entries()

    def remove_user_gradient(self, row: int) -> None:
        entry = self.entry(row)
        if entry is None:
            return
        self._user.remove(entry)
        self._save_user()
        self._reset_entries()

    # ------------------------------------------------------------------
    def rowCount(self, parent=None) -> int:
        return len(self._entries)

    def entry(self, row: int) -> dict | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _backfill_uids_once(self) -> None:
        """Every gradient carries a uid, like every asset carries its
        id - identity from birth, not stamped when a feature happens
        to need it ("this will just backfire trying to do shortcuts").
        Existing libraries are brought up in ONE pass here; after the
        first save, loads stamp nothing and cost nothing."""
        import uuid
        stamped = 0
        for entry in self._entries:
            if not str(entry.get("uid", "") or ""):
                # Full uuid4 hex - ONE mint across the app (the asset
                # family's, core/material.py). Early libraries carry
                # 12-char uids from the first cut; they stay valid
                # keys and are left alone.
                entry["uid"] = uuid.uuid4().hex
                stamped += 1
        if stamped:
            self._save_user()
            debug.event("gradients", "uids backfilled", count=stamped)


    def _sweep_notes_to_store_once(self) -> None:
        """The entry-level "note" text moved to the Notes store
        (2026-08-01): a gradient's free text belongs on its Notes page
        with everything else, not in a dialog of its own. Any entry
        still carrying one - an old library, or a fresh curated seed -
        has it appended to its page here and the field consumed, so
        every future source is covered by the same sweep. A note the
        store cannot take (read-only session) stays on the entry and
        is retried next load - moved, never dropped."""
        from amaze.core import notes
        moved = cleared = 0
        for entry in self._entries:
            if "note" not in entry:
                continue
            text = str(entry.get("note", "") or "").strip()
            if not text:
                del entry["note"]
                cleared += 1
                continue
            key = notes.note_key(
                "gradient", str(entry.get("uid", "") or ""))
            page = notes.note_for(self._preferences, key)
            items = list(page.get("items", []))
            items.append({"t": "text", "text": text})
            if notes.set_note(self._preferences, key, items):
                del entry["note"]
                moved += 1
        if moved or cleared:
            self._save_user()
            debug.event("gradients", "notes swept to the notes store",
                        moved=moved, cleared=cleared)

    def note_uid(self, row: int) -> str:
        """The entry's own identity - present from load (backfill) or
        birth (add_user_gradient), simply read here."""
        entry = self.entry(row)
        if entry is None:
            return ""
        return str(entry.get("uid", "") or "")

    @staticmethod
    def _is_banded(entry: dict) -> bool:
        """A palette / stepped ramp paints as bands; a smooth ramp as a
        gradient. True when every basis is Constant (or there's no ramp
        yet - a freshly seeded palette)."""
        bases = (entry.get("ramp") or {}).get("bases") or []
        return bool(entry.get("colors")) and (
            not bases or all(b == "Constant" for b in bases)
        )

    @classmethod
    def _entry_thumb_key(cls, entry: dict):
        """Content-addressed (the hexes, plus ramp bases) - renames can't
        stale it, edits naturally mint a new key and the old image ages
        out of the shared LRU."""
        hexes = tuple(c["hex"] for c in entry["colors"])
        bases = tuple((entry.get("ramp") or {}).get("bases") or ())
        icon = tile_icons.normalise(entry.get("icon"))
        # The icon is part of the key: a tile that has one paints the
        # icon INSTEAD of the swatch, so the two must not share a slot.
        icon_key = (icon.get("name"), icon.get("bg"), icon.get("ink")) \
            if icon else None
        return ("grad", cls._is_banded(entry), hexes, bases, icon_key,
                THUMB_SIZE)

    def _thumb(self, row: int) -> QtGui.QImage:
        entry = self._entries[row]
        key = self._entry_thumb_key(entry)
        image = thumbnails.engine.peek(key)
        if image is not None:
            return image
        icon = tile_icons.normalise(entry.get("icon"))
        if icon:
            # Composed in memory - no file, see set_tile_icon.
            composed = tile_icons.compose(
                icon["name"], icon["bg"], THUMB_SIZE, ink=icon["ink"])
            if composed is not None:
                thumbnails.engine.deposit(key, composed)
                return composed
        image = QtGui.QImage(
            THUMB_SIZE, THUMB_SIZE, QtGui.QImage.Format.Format_RGB32
        )
        painter = QtGui.QPainter(image)
        if self._is_banded(entry):
            # Palette / stepped ramp -> horizontal colour bands (the
            # dictionary's own presentation, kept for the seeded palettes).
            colors = entry["colors"]
            band_h = THUMB_SIZE / max(len(colors), 1)
            for i, color in enumerate(colors):
                painter.fillRect(
                    QtCore.QRectF(0, i * band_h, THUMB_SIZE, band_h + 1),
                    QtGui.QColor(color["hex"]),
                )
        else:
            self._paint_ramp(painter, entry.get("ramp") or {})
        painter.end()
        # PAINT provider: synchronous paint-on-miss, deposited under
        # the same shared budget as every other section's thumbnails.
        thumbnails.engine.deposit(key, image)
        return image

    @staticmethod
    def _paint_ramp(painter: QtGui.QPainter, ramp_data: dict) -> None:
        """Left-to-right preview of a saved ramp: hard bands when the
        ramp is fully constant-basis, otherwise a linear-interpolated
        gradient (close enough visually for the smooth bases)."""
        keys = ramp_data.get("keys", [])
        values = ramp_data.get("values", [])
        bases = ramp_data.get("bases", [])
        if not keys or not values:
            painter.fillRect(0, 0, THUMB_SIZE, THUMB_SIZE, QtGui.QColor("#444444"))
            return
        if all(b == "Constant" for b in bases):
            edges = list(keys) + [1.0]
            for i, value in enumerate(values):
                x0 = max(0.0, min(1.0, edges[i])) * THUMB_SIZE
                x1 = max(0.0, min(1.0, edges[i + 1])) * THUMB_SIZE
                color = QtGui.QColor.fromRgbF(*value[:3])
                painter.fillRect(QtCore.QRectF(x0, 0, x1 - x0 + 1, THUMB_SIZE), color)
            return
        gradient = QtGui.QLinearGradient(0, 0, THUMB_SIZE, 0)
        for key, value in zip(keys, values):
            gradient.setColorAt(
                max(0.0, min(1.0, key)), QtGui.QColor.fromRgbF(*value[:3])
            )
        painter.fillRect(0, 0, THUMB_SIZE, THUMB_SIZE, QtGui.QBrush(gradient))

    def data(self, index, role: int = 0):
        # LATER COLUMNS are the table's, not the row's (step 1 of the
        # QTableView migration). Column 0 falls through unchanged, so
        # grid mode cannot tell any of this happened.
        if index.column() > 0:
            return self.column_data(index, role)
        row = index.row()
        entry = self.entry(row)
        if entry is None:
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return entry.get("name") or "Gradient"
        if role == self.NotesRole:
            # Read-only here (data() is a paint path): a gradient with
            # no uid HAS no note yet - stamping happens in
            # ensure_note_uid when a note is actually opened.
            uid = str(entry.get("uid", "") or "")
            if not uid:
                return False
            from amaze.core import notes
            return notes.has_note(self._preferences,
                                  notes.note_key("gradient", uid))
        if role == self.SubtitleRole:
            # Uniformly "Gradient" - the Type column/grid subtitle names
            # the KIND of thing, consistent with Materials' "Redshift"
            # and Textures' "HDR". Which set/palette
            # size an entry belongs to is Category-column information.
            return "Gradient"
        if role == QtCore.Qt.ItemDataRole.DecorationRole:
            return self._thumb(row)
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            from amaze.helpers import ui_helpers

            names = ", ".join(c["name"] for c in entry["colors"])
            return ui_helpers.tooltip_text(names)
        if role == self.ColorsRole:
            return entry["colors"]
        if role == self.FavoriteRole:
            return self.is_favorite(row)
        if role == self.CategoryLabelRole:
            return entry.get("category") or "Uncategorized"
        if role == self.CategoryColorRole:
            return self.category_color(row)
        return None


class GradientFilterProxyModel(grid_proxy.GridProxyModel):
    """Search over names AND the color names inside entries, combined
    with the sidebar filter (a user category) and the toolbar's size
    filter (how many colors the palette holds).

    The Grid area's invariant - what is shown and in what order - is the
    base class's (core/grid_proxy.py), the same one the asset sections
    and File use."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._name_filter = ""
        self._kind = "all"
        self._value = None
        self._favorites_only = False
        self._size_filter = None

    def set_name_filter(self, text: str) -> None:
        self._name_filter = (text or "").strip().lower()
        self.refilter()

    def set_favorites_only(self, enabled: bool) -> None:
        self._favorites_only = bool(enabled)
        self.refilter()

    def set_sidebar_filter(self, kind: str, value) -> None:
        """("all", None) or ("category", name)."""
        self._kind = kind
        self._value = value
        self.refilter()

    def set_size_filter(self, bounds) -> None:
        """Show only palettes holding this many colors.

        `bounds` is (fewest, most), `most` None meaning no upper end -
        so "5+ colors" is (5, None) and "3 colors" is (3, 3). None
        switches the filter off entirely.

        A range, not a count, so the open-ended entry needs no special
        case here: the menu decides what each entry MEANS and this
        reads the pair it is handed. panel/sections.py ▸
        GradientSection.FILTER_CHOICES is where those pairs live.
        """
        self._size_filter = bounds
        self.refilter()

    def filterAcceptsRow(self, source_row, source_parent) -> bool:
        model = self.sourceModel()
        entry = model.entry(source_row)
        if entry is None:
            return False
        if self._favorites_only and not model.is_favorite(source_row):
            return False
        if self._kind == "category" and entry.get("category") != self._value:
            return False
        if self._size_filter is not None:
            fewest, most = self._size_filter
            held = len(entry.get("colors") or ())
            if held < fewest or (most is not None and held > most):
                return False
        if not self._name_filter:
            return True
        index = model.index(source_row, 0)
        name = (model.data(index, QtCore.Qt.ItemDataRole.DisplayRole) or "").lower()
        if self._name_filter in name:
            return True
        for color in entry["colors"]:
            if self._name_filter in color["name"].lower():
                return True
        return False
