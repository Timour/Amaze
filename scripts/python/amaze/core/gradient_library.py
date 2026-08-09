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
import uuid

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

    def switch_model_data(self) -> None:
        """Re-point at the library the panel now serves.

        THE SAME VERB EVERY OTHER LIBRARY-BACKED MODEL ANSWERS, and
        that is the whole point of its existing. The work is
        `refresh()`'s - rebuild the labels from the library, which by
        now holds the new library's rows - but this model was the ONE
        that spelled its repoint differently, so the panel's three
        hand-written switch lists never carried it and the guard
        watching those lists could not see it either: it searched for
        `switch_model_data` and found `refresh`. Two names for one
        event is how a model goes missing from a list nobody can
        prove is short.

        Kept as two methods rather than one, because they are two
        events: `refresh()` is "the categories changed inside this
        library" (a rename, a delete), and this is "the library
        underneath changed". They agree today; a divergence belongs
        in whichever one it applies to.
        """
        self.refresh()

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
        self._user = []
        self._user_categories = []
        # Category colours, name -> hex, beside the names in the same
        # file - the shape every other section already uses.
        self._category_colors: dict = {}
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
        self._adopt_entry_icons_once()

    #: The one database file this model owns. Named like every other
    #: library model's, because it now IS one.
    DB_FILENAME = "gradients.json"

    @property
    def _load_failed(self) -> bool:
        """Whether the connector is refusing to write this file.

        The model kept its OWN latch, set on a parse failure and on an
        absent-but-known file. The connector latches for both of those
        reasons already (`_write_blocked`), so keeping a second one
        meant two answers to one question - the shape this whole move
        removes. Read through to the connector's."""
        if self._preferences is None:
            return False
        return bool(getattr(
            database.DatabaseConnector(self.DB_FILENAME),
            "_write_blocked", False))

    def _db(self):
        """This model's connector, pointed at the current library."""
        return database.DatabaseConnector(self.DB_FILENAME)

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
            self._user = []
            self._user_categories = []
            self._category_colors = {}
            # THROUGH reload_with_path, the door the other three take.
            self._load_user(reload=True)
            self._seed_curated_once()
            self._entries = self._all_entries()
            self._backfill_uids_once()
            self._sweep_notes_to_store_once()
            self._adopt_entry_icons_once()
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
                with open(path, "r", encoding="utf-8-sig") as f:
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
                        # STAMPED AT BIRTH, like every other section's
                        # identity. Without it the backfill below found
                        # every seeded entry unstamped and saved the
                        # whole file a second time on first open.
                        "id": uuid.uuid4().hex,
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

    def _load_user(self, reload: bool = False) -> None:
        """Read the palettes through the connector, like every other
        library-backed model.

        `reload` picks the DOOR, and which one is not cosmetic.
        `load()` returns the connector's cached document when it
        already holds one - correct at construction, wrong on a
        library switch, where it would hand back the previous
        library's rows AND keep its latches. `reload_with_path` is the
        route `library.switch_model_data` takes for exactly that
        reason: its own docstring records that a latch belonging to
        library A, carried into healthy library B, silently drops
        every save for the session. Re-derived from disk, never
        remembered - so a repaired file heals on the next switch
        instead of staying refused until restart.

        WHAT WENT WHEN THIS ARRIVED: a hand-built copy of the
        connector's whole load policy - the absent-but-known refusal
        with its own `absent_traces` call and its own message, the
        wrong-shape check, the non-dict row skip, the unreadable
        preservation and latch. The connector does all five, which is
        the entire reason for the move: `gradients.json` was the ONE
        database not going through it, so every guard the other three
        inherit had been given to it by hand and three were still
        missing as late as 2026-07-30.

        `_All` IS DROPPED HERE. Every secondary database gets it
        inserted by the connector's `_normalize_all_category`; the
        Colors sidebar builds its own All row at position 0, so
        carrying the stored one through would show two.
        """
        if self._preferences is None:
            return
        path = str(self._preferences.dir) + os.sep
        try:
            db = self._db()
            data = db.reload_with_path(path) if reload else db.load(path)
        except (OSError, ValueError) as exc:
            # A CORRUPT FILE MUST NOT TAKE THE PANEL DOWN. The
            # connector raises here and its other callers are built
            # for that; this model is constructed during panel setup,
            # so an escape kills the panel before there is an
            # interface to report anything in - the failure the old
            # loader documented preventing, and it is not undone by
            # moving house. The connector's OWN latch is set, not a
            # second one beside it, so there is still one answer to
            # whether this file may be written.
            db = self._db()
            db._write_blocked = True
            hostos.preserve_unreadable(
                os.path.join(str(self._preferences.dir), self.DB_FILENAME),
                why="gradient library")
            debug.event("gradient", "gradients.json unreadable - saving "
                        "disabled", error=str(exc))
            debug.alert(
                "Your saved colours could not be read, so Amaze will not "
                "save over them.\n\n"
                "Nothing has been lost - the file is untouched. Colour "
                "changes you make now will not be kept.\n\n"
                "Close Houdini and put back a recent copy with the Repair "
                "tool in the Amaze shelf.",
                key="gradients-unreadable")
            return
        rows = data.get("assets")
        rows = rows if isinstance(rows, list) else []
        self._user = [row for row in rows if isinstance(row, dict)]
        for entry in self._user:
            # A MEMORY marker: every row here is a user gradient since
            # the curated palettes became ordinary seeded entries.
            entry["type"] = "user"
        self._user_categories = [
            name for name in (data.get("categories") or [])
            if isinstance(name, str) and name != "_All"
        ]
        table = data.get("category_colors")
        self._category_colors = {
            str(k): str(v) for k, v in table.items()
            if isinstance(k, str) and isinstance(v, str) and v
        } if isinstance(table, dict) else {}

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
        # EVERY GUARD BELOW IS THE CONNECTOR'S NOW. What stood here was
        # a hand-built copy of each one, written because this file had
        # no connector: the library-moved refusal (db.serves), the
        # unreadable latch (_write_blocked), the stale-write compare
        # (the connector's own content stat and merge), the snapshot,
        # the atomic write and the loud failure. Two sets of guards
        # answering one question is what this move removes - so they
        # are DELETED rather than left beside the inherited ones.
        db = self._db()
        if not db.serves(self._preferences.dir):
            debug.event("gradient", "save refused - these colours came "
                        "from another library", file=path)
            return False
        db.set({
            "categories": self._user_categories,
            "category_colors": self._category_colors,
            # `type` is a MEMORY marker, never stored - the same line
            # the hand-built writer carried.
            "assets": [
                {k: v for k, v in entry.items() if k != "type"}
                for entry in self._user
            ],
        })
        return bool(db.save())

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

    def _icon_of(self, entry: dict) -> dict:
        """This entry's icon: the SHARED STORE first, the entry field
        as the fallback - the same precedence `library.tile_icon` uses,
        so both archetypes answer the question one way.

        It mattered which way round. The entry field used to be the
        only reader, with the store copied INTO it on load - so a pick
        made through the store rode back out on the next save and the
        dual-write survived its own retirement. Asking the store here
        is what lets `set_tile_icon` stop writing the field at all.
        """
        if not entry:
            return {}
        uid = self._id_of(entry)
        stored = tile_icons.override_for(self._preferences, uid) \
            if uid else {}
        return stored or tile_icons.normalise(entry.get("icon"))

    def tile_icon(self, row: int) -> dict:
        """This gradient's chosen icon, {} when it shows its swatch.
        Same two-method contract every other section answers, so the
        panel's one Customize handler serves Colors too."""
        return self._icon_of(self.entry(row))

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
        # THE SHARED STORE IS THE ONE HOME, keyed by the entry uid. The
        # entry field used to be written too, so a build predating the
        # store still read the pick - retired 2026-08-09 with
        # LIBRARY_FORMAT 2, which covers that case generally: such a
        # build opens the library read-only and is told to update.
        # The field is still READ (see _icon_of) and never deleted, so
        # a library from an older build keeps its picks.
        stored = tile_icons.set_override(
            self._preferences, self.note_uid(row), spec)
        if save:
            self._save_user()
        idx = self.index(row, 0)
        self.row_changed(idx.row(), [QtCore.Qt.ItemDataRole.DecorationRole])
        return bool(stored)

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
                "id": uuid.uuid4().hex,
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

    @staticmethod
    def _id_of(entry: dict) -> str:
        """This entry's identity, whatever it is spelled.

        `id` since the move onto the connector - which reads that field
        in seven places, so a row without one collapses with every
        other id-less row into a single key in its union and they
        overwrite each other. `uid` is the pre-move spelling, read here
        so an entry still carrying it in memory keeps working; the
        VALUE is the same either way, which is what matters, because
        comments are keyed `gradient:<value>` and tile icons by the
        same value.
        """
        return str(entry.get("id") or entry.get("uid") or "")

    def _backfill_uids_once(self) -> None:
        """Every gradient carries a uid, like every asset carries its
        id - identity from birth, not stamped when a feature happens
        to need it ("this will just backfire trying to do shortcuts").
        Existing libraries are brought up in ONE pass here; after the
        first save, loads stamp nothing and cost nothing. A freshly
        SEEDED entry arrives stamped, so this finds nothing to do and
        does not write - the seed used to leave it a whole file to
        save a second time on first open."""
        stamped = 0
        for entry in self._entries:
            if not self._id_of(entry):
                # Full uuid4 hex - ONE mint across the app (the asset
                # family's, core/material.py). Early libraries carry
                # 12-char uids from the first cut; they stay valid
                # keys and are left alone.
                entry["id"] = uuid.uuid4().hex
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
        # COLLECTED, then written ONCE. Calling set_note per entry
        # rewrote notes.json per entry and rotated a snapshot each
        # time, so 39 old notes pushed the restore tier's real history
        # out with 39 copies of the same minute.
        pages = {}
        carriers = {}
        for entry in self._entries:
            if "note" not in entry:
                continue
            text = str(entry.get("note", "") or "").strip()
            if not text:
                del entry["note"]
                cleared += 1
                continue
            key = notes.note_key(
                "gradient", self._id_of(entry))
            page = notes.note_for(self._preferences, key)
            items = list(pages.get(key, page.get("items", [])))
            items.append({"t": "text", "text": text})
            pages[key] = items
            carriers.setdefault(key, []).append(entry)
        if pages and notes.set_notes(self._preferences, pages):
            # The field is consumed only on a write that LANDED - a
            # read-only session keeps it and retries next load, which
            # is the moved-never-dropped contract.
            for entries in carriers.values():
                for entry in entries:
                    entry.pop("note", None)
                    moved += 1
        if moved or cleared:
            self._save_user()
            debug.event("gradients", "notes swept to the notes store",
                        moved=moved, cleared=cleared)

    def _adopt_entry_icons_once(self) -> None:
        """Entry-level tile icons move to the shared store - one
        icons.json for every section, this one keyed by the entry uid
        beside asset ids and file paths. Unlike the notes sweep the
        entry field is NOT consumed: it keeps being written for one
        release so the other machine's older build still reads the
        pick. A store entry this build finds (set on another machine
        by a newer one) overlays into memory, so every reader of the
        entry field sees the merged truth."""
        adopted = 0
        for entry in self._entries:
            uid = self._id_of(entry)
            if not uid:
                continue
            if tile_icons.override_for(self._preferences, uid):
                # Already in the store, which is where every reader
                # looks. NOT copied back onto the entry: that overlay
                # is how a store pick rode out to disk on the next
                # save and kept the dual-write alive.
                continue
            spec = tile_icons.normalise(entry.get("icon"))
            if spec and tile_icons.set_override(
                    self._preferences, uid, spec):
                adopted += 1
        if adopted:
            debug.event("gradients", "entry icons adopted into the store",
                        adopted=adopted)

    def note_uid(self, row: int) -> str:
        """The entry's own identity - present from load (backfill) or
        birth (add_user_gradient), simply read here."""
        entry = self.entry(row)
        if entry is None:
            return ""
        return self._id_of(entry)

    @staticmethod
    def _is_banded(entry: dict) -> bool:
        """A palette / stepped ramp paints as bands; a smooth ramp as a
        gradient. True when every basis is Constant (or there's no ramp
        yet - a freshly seeded palette)."""
        bases = (entry.get("ramp") or {}).get("bases") or []
        return bool(entry.get("colors")) and (
            not bases or all(b == "Constant" for b in bases)
        )

    def _entry_thumb_key(self, entry: dict):
        """Content-addressed (the hexes, plus ramp bases) - renames can't
        stale it, edits naturally mint a new key and the old image ages
        out of the shared LRU.

        An INSTANCE method since 2026-08-09: the icon half now comes
        from the shared store, which needs the preferences to reach.
        It stays callable on a bare dict - an entry with no uid simply
        has no stored pick and falls back to the field."""
        hexes = tuple(c["hex"] for c in entry["colors"])
        bases = tuple((entry.get("ramp") or {}).get("bases") or ())
        icon = self._icon_of(entry)
        # The icon is part of the key: a tile that has one paints the
        # icon INSTEAD of the swatch, so the two must not share a slot.
        icon_key = (icon.get("name"), icon.get("bg"), icon.get("ink")) \
            if icon else None
        return ("grad", self._is_banded(entry), hexes, bases, icon_key,
                THUMB_SIZE)

    def _thumb(self, row: int) -> QtGui.QImage:
        entry = self._entries[row]
        key = self._entry_thumb_key(entry)
        image = thumbnails.engine.peek(key)
        if image is not None:
            return image
        icon = self._icon_of(entry)
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
            uid = self._id_of(entry)
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

    def watched_roles(self):
        """Exactly what this filter reads through roles - the display
        name and the favourite - plus the sort role. Category and size
        are read straight off the entry, and every edit that changes
        them announces itself structurally (reset/insert), never as a
        role-scoped dataChanged; the role-scoped emissions here are the
        category-colour sweep (paint only, over every row), the
        thumbnail's DecorationRole and FavoriteRole. Falling through to
        the blacklist bought a full re-filter and re-sort per colour
        pick (the base's watched_roles docstring names the gesture)."""
        watched = {QtCore.Qt.ItemDataRole.DisplayRole, self.sortRole()}
        role = getattr(self.sourceModel(), "FavoriteRole", None)
        if role is not None:
            watched.add(role)
        return watched

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
